"""``shepherd doctor`` — pre-flight diagnostic for the shepherd context registry.

Native port of ``skills/context/scripts/cmd_doctor.sh`` (v5.0.4): a
READ-ONLY health check across six sections, in this exact order —

1. **Binaries** — ``sqlite3``/``jq``/``git`` (FAIL if missing) and ``gh``
   (WARN only — ``refresh --scope=github`` degrades gracefully without it).
2. **Namespace** — the resolved ``.shepherd``/``.artifacts`` work
   directory, a WARN if BOTH exist (split-brain), and ``project.json``.
3. **DB + schema** — the db file itself (size via ``du -h``), the highest
   applied ``schema_versions.version``, and a GAP-AWARE count of shipped
   migrations absent from ``schema_versions`` (mirrors ``_lib.sh``'s
   v6.3.3 #200 self-heal detection, but never applies anything — see the
   "NO SELF-HEAL" section below).
4. **Lock state** — the live ``<workdir>/shepherd.lock`` file: free, held
   (fresh), or held-and-stale (WARN, age > 60 minutes).
5. **Refresh staleness** — ``rows=N`` + age for five zones (symbols,
   issues, prs, releases, artifacts), each backed by one table.
6. **Config** — whether ``shepherd.toml`` is locatable at any of three
   standard paths.

Two POST-PARITY sections follow (v6.4.1 — not in ``cmd_doctor.sh``; both
emit rows only CONDITIONALLY, so gate-less / version-matched fixtures still
render byte-identically to the legacy script):

7. **Gates ledger** (#59) — whether ``[gates].check``/``lint`` and each
   ``[gates.extra]`` entry has a recorded invocation this session, read from
   the newest ``<workdir>/tmp/gates-ran-<session>.jsonl`` that
   ``hooks/scripts/bash_post.sh`` appends to. No configured gates → no rows.
8. **Binary version** (#235) — WARN when the running CLI ``__version__``
   differs from the ``plugin.json`` version at ``CLAUDE_PLUGIN_ROOT``.
   Match / unset env / unreadable file → no row.
9. **User-level tier** (#254) — whether ``~/.shepherd`` exists (INFO, not
   a failure, when absent — the tier is optional and ``shepherd home
   init`` is the fix), plus which tier each PROJECT-declared profile
   (a real file, never a bundled default) resolves from. Unlike sections
   7/8, the ``~/.shepherd`` row is NOT purely conditional — it always
   prints, since the whole point is surfacing a tier nothing else ever
   creates.

Every ``add()`` call in ``cmd_doctor.sh`` becomes one :class:`Result`
appended, in the SAME order, to the SAME five-tuple shape (status,
category, name, message, fix) — :func:`_collect_results` is a literal,
section-by-section transliteration of the bash script, not a
restructuring.

ARCHITECTURE DEVIATION FROM THE PORT'S OWN HARD RULE 7 (fully synchronous,
NO ``db.lifespan()``/Tortoise/asyncio) — READ THIS FIRST
=============================================================================
Every other DB-touching command in this package is "a thin sync Typer
wrapper around ``asyncio.run(_impl_async())`` inside ``async with
db.lifespan():``" (the port's own hard rule 7). This module deliberately
does NOT follow that shape for its DB-touching sections (3 and 5), and
instead opens a plain, synchronous ``sqlite3.connect()`` per query,
mirroring ``_lib.sh``'s own ``shctx_sql`` (a bare ``sqlite3 -bail $db
"..."`` subprocess call) — never through Tortoise at all. This is not an
oversight; it is the ONE conflict in this port where following hard rule 7
would make the ported command WRONG, not just non-idiomatic:

``shepherd_cli.db.lifespan()`` unconditionally calls
``shepherd_cli.db.ensure_migrated()`` BEFORE Tortoise ever opens a
connection (see that module's own docstring: "self-heal the schema before
any query can hit a missing column" — the v6.3.3 #200 fix). That is
exactly correct for every OTHER command, which wants a healthy schema to
operate against and doesn't care how it got that way. It is exactly WRONG
for ``doctor``, whose entire "DB + schema" section exists to REPORT
whether the schema has drifted — ``cmd_doctor.sh`` deliberately never
calls ``shctx_ensure_migrated``/``shctx_apply_pending_migrations``
anywhere (unlike ``shctx_ensure_migrated``'s callers elsewhere, and unlike
``shctx migrate``, which explicitly applies pending migrations on
request). If this module used ``db.lifespan()``, the very act of running
``shepherd doctor`` would silently heal the schema BEFORE the "pending
migrations" check ran against it, so that check would read "none
(schema at head)" on EVERY invocation but the first — permanently masking
the exact drift condition (#200's own regression class) this diagnostic
exists to surface. A "doctor" that cures the patient before taking their
temperature is not a diagnostic. This module reads the raw on-disk state
with plain ``sqlite3``, exactly like ``shctx_sql``, so nothing about the
schema is ever touched by running it — true bash-parity READ-ONLY
behavior, which the group notes for this port explicitly call for.

(Also incidentally simpler: none of this module's six DB queries — three
``COUNT``/``MAX`` aggregates repeated per some zones, one
``MAX(version)``, one per-migration-version existence check — need
Tortoise's async ORM or query-building; each is one bound SQL string.)

COLLISION-RULE NOTE — no ``models_doctor.py``
=============================================================================
Because every DB read in this module goes through plain ``sqlite3.connect()``
(never Tortoise), there is nothing to mirror with a Tortoise model, and no
``models_doctor.py`` is declared. This is a stronger version of the
"reuse read-scoped model" case: not merely avoiding a redeclaration
collision, but avoiding Tortoise (and its ``db.lifespan()`` self-heal
side effect) for this module's DB sections entirely, for the reason above.

OTHER BASH-PARITY NOTES
=============================================================================
* **The dual-namespace stderr warning duplicates itself, deliberately.**
  ``cmd_doctor.sh`` resolves the work directory FOUR separate times across
  the script (``root=$(SHCTX_QUIET=1 shctx_artifacts_root)`` for the
  namespace-dir check; ``shctx_project_id_path``; ``shctx_db_path`` —
  short-circuited when ``SHCTX_DB`` is set; ``shctx_lock_path``), and only
  the FIRST call suppresses ``_lib.sh``'s split-brain stderr warning via a
  one-shot ``SHCTX_QUIET=1`` prefix scoped to that single subshell — every
  later call is unsuppressed and re-prints the same two-line warning if
  both ``.shepherd/`` and ``.artifacts/`` exist (verified empirically
  against the real script: 3 stderr copies when ``SHCTX_DB`` is unset, 2
  when it is set, since ``shctx_db_path``'s own env-override short-circuit
  skips the work-directory resolution — and therefore the warning —
  entirely in that case). This module reproduces the SAME call graph
  (:func:`_quiet_resolve_workdir` used ONCE, for ``root``; every other
  call site below uses :func:`shepherd_cli.resolution.resolve_workdir`/
  ``resolve_db_path`` plainly) rather than caching ``root`` and reusing
  it — :mod:`shepherd_cli.resolution` already implements the identical
  warning side effect, so calling it the same number of times, in the
  same order, reproduces the duplicate-warning quirk for free, with no
  bespoke warning-printing code of this module's own.
* **``jq -r`` raw-output semantics, reused from
  :mod:`shepherd_cli.commands.lock`'s established pattern** (not
  imported — self-contained modules per the port's instructions):
  :func:`_jq_r_or_fallback` renders a missing/``null`` JSON key as the
  four-character string ``"null"`` (jq's own behavior), and only falls
  back to the caller's own default when the ENTIRE file fails to parse as
  a JSON object (bash: ``jq -r .foo "$lock" 2>/dev/null || echo
  "$fallback"`` — the fallback fires on a failing ``jq`` invocation, not
  on a present-but-null field, which ``jq -r`` renders successfully as
  the text ``"null"``).
* **The lock file's ``age`` computation mirrors a genuine bash arithmetic
  quirk**, not a Python idiom: ``age=$(( $(shctx_now) - $(jq -r
  .acquired_at "$lock" 2>/dev/null || echo 0) ))`` — when ``jq`` prints
  the literal text ``"null"`` (a well-formed lock file simply missing
  ``acquired_at``), bash's ``$(( ))`` treats that bareword as an
  (unset, so zero-valued) variable NAME, not a syntax error — silently
  identical to the ``|| echo 0`` fallback that fires when ``jq`` itself
  fails outright on an unparseable file. :func:`_jq_numeric_or_zero`
  reproduces both paths landing on 0. ``age_min = int(age / 60)``
  (never ``//``) matches bash's ``$(( age / 60 ))`` truncating toward
  zero, the same idiom already documented in
  :mod:`shepherd_cli.commands.status`/:mod:`shepherd_cli.commands.mem`
  for identical reasons.
* **The ``artifacts`` refresh zone is structurally ALWAYS "never
  refreshed"** — verified against both the schema and the real bash
  script: ``artifacts`` (``0001_init.sql``) has no ``refreshed_at``
  column at all (unlike the other four zones' tables), so
  ``cmd_doctor.sh``'s ``SELECT MAX(refreshed_at) FROM artifacts;``
  always fails with sqlite's own "no such column" error, silently
  swallowed by ``2>/dev/null || echo 0`` — ``latest`` is therefore always
  0, so this zone reads ``warn ... never refreshed`` on every real
  project, forever (confirmed against ``cmd_doctor.sh`` directly with a
  seeded ``artifacts`` row: ``rows=1, never refreshed``). This is
  preserved AS A BUG, not fixed — :func:`_sql_scalar`'s blanket
  ``sqlite3.OperationalError`` tolerance reproduces it automatically
  (the SAME code path every other zone uses, no artifacts-specific
  branch needed), exactly like bash's own uniform per-zone loop that
  happens to hit this for one of its five iterations.
* **``shepherd.toml`` candidate order is project → local → XDG** — the
  OPPOSITE precedence ``_lib.sh``'s ``cfg_get``/``cfg_section_get`` use
  (local → project → XDG) for VALUE resolution. This is not a bug this
  module should "fix" to match ``cfg_get``: ``cmd_doctor.sh``'s own
  ``for cand in "$repo/.claude/shepherd.toml" "$repo/.claude/
  shepherd.local.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/shepherd.toml"``
  loop is a distinct, deliberately different "is ANY config file
  locatable at all" existence probe, not a precedence-sensitive value
  read — reproduced here in that exact order.

Timestamps: epoch SECONDS throughout (``shctx_now`` / ``date +%s`` —
``schema_versions.applied_at``, ``locks_history``/lock-file
``acquired_at``, every ``refreshed_at`` column), matching every other
``_lib.sh``-second-denominated command this port has already established
(NOT the epoch-millisecond unit ``teammates``/``deliverables`` use).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass

import typer

from shepherd_cli.profiles import list_profiles
from shepherd_cli.resolution import (
    find_migrations_dir,
    resolve_db_path,
    resolve_repo_root,
    resolve_user_home,
    resolve_workdir,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Bash parity requires FULL control over -h/--help's own output (the
    # verbatim usage heredoc below) instead of Click's autogenerated help
    # text, so Click's own --help machinery is disabled entirely
    # (help_option_names=[]) -- mirroring shepherd_cli.commands.search's
    # identical technique. allow_extra_args + ignore_unknown_options let
    # "--md"/"--json"/"-h"/"--help" (and any unrecognized token, which
    # this module's own loop rejects with bash's exact error) flow into
    # the single variadic `raw` argument below instead of Click trying
    # (and failing) to parse them as its own options.
    context_settings={
        "help_option_names": [],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
    help="Pre-flight diagnostic for the shepherd context registry (bash: cmd_doctor.sh).",
)

#: Verbatim bash-parity usage text -- cmd_doctor.sh's `-h|--help)` heredoc,
#: printed to STDOUT (not stderr) on -h/--help, exit 0. No trailing
#: newline: the sole caller (`_parse_args`) prints it via `typer.echo`,
#: which appends exactly one -- matching bash's `cat <<'EOF' ... EOF`,
#: whose own output already ends with exactly one trailing newline.
_USAGE = (
    "shctx doctor [--md|--json]\n"
    "\n"
    "Pre-flight diagnostic for the shepherd context registry. Checks:\n"
    "  - required binaries (sqlite3, jq, gh, git)\n"
    "  - namespace dir + project.json present\n"
    "  - schema version + pending migrations\n"
    "  - lock state (held / stale / free)\n"
    "  - refresh staleness per zone (symbols / github / artifacts)\n"
    "  - shepherd.toml locatable\n"
    "\n"
    "Exit codes: 0 = ok, 1 = at least one FAIL, 2 = warnings only."
)

#: `cmd_doctor.sh`'s exact `for zone in symbols issues prs releases
#: artifacts` loop -- (zone label, backing table) pairs, in loop order.
#: Every table name below is a fixed, hardcoded constant (never derived
#: from user input), so building the `SELECT ... FROM {table}` strings by
#: f-string interpolation below carries no injection risk -- the same
#: "fixed table/column allow-list" contract
#: `tests/conftest.py::_insert_row` and `tests/test_status.py::_insert_row`
#: already document for the identical reason.
_ZONE_TABLES: tuple[tuple[str, str], ...] = (
    ("symbols", "index_symbols"),
    ("issues", "index_issues"),
    ("prs", "index_prs"),
    ("releases", "index_releases"),
    ("artifacts", "artifacts"),
)

#: `cmd_doctor.sh`'s `age_min > 60` (lock staleness) / `age_min > 120`
#: (refresh staleness) thresholds, in MINUTES.
_LOCK_STALE_MINUTES = 60
_REFRESH_STALE_MINUTES = 120

#: Matches a shipped migration filename, capturing its integer version --
#: mirrors `shepherd_cli.db._MIGRATION_NAME_RE` (not imported -- this
#: module is self-contained per the port's instructions) and bash's own
#: `grep -oE '^[0-9]+'` extraction from `NNNN_*.sql`.
_MIGRATION_NAME_RE = re.compile(r"^(\d+)_.*\.sql$")

#: Matches a bare (optionally signed) integer literal -- used by
#: `_jq_numeric_or_zero` to reproduce bash's arithmetic-context handling
#: of a JSON string value that nonetheless "looks like a number" (bash's
#: `$(( ))` parses it as a literal, not a variable reference).
_INT_LITERAL_RE = re.compile(r"[+-]?\d+")

#: `printf '%-6s' "$icon"` inputs -- each already 5 characters wide in
#: `cmd_doctor.sh` (`"OK   "`/`"WARN "`/`"FAIL "`), THEN padded to 6 by
#: the format spec itself. Stored pre-padded here so `_render_md`'s
#: `f"{icon:<6}"` reproduces the two-stage padding exactly.
_ICON: dict[str, str] = {"ok": "OK   ", "warn": "WARN ", "fail": "FAIL ", "info": "INFO "}


@dataclass(frozen=True, slots=True)
class Result:
    """One diagnostic finding -- the five-tuple `cmd_doctor.sh`'s `add()` builds.

    Attributes:
        status: One of ``"ok"``, ``"warn"``, ``"fail"`` -- the three bash
            `cmd_doctor.sh` itself uses -- plus ``"info"``, a v6.4.1
            post-parity addition (#254, section 9) for purely informational
            rows that must never affect the exit code or the `N ok` tally
            (see `_render_md`'s `ok_count`, which counts `"ok"` explicitly
            rather than by subtraction, for exactly this reason).
        category: One of ``"bin"``, ``"ns"``, ``"db"``, ``"lock"``,
            ``"refresh"``, ``"config"`` -- matches bash's `add()` call
            sites' second argument verbatim.
        name: The check's short label (e.g. ``"sqlite3"``, ``"schema_version"``).
        message: The human-readable finding text.
        fix: A remediation command/note, or ``""`` when the check passed
            outright (bash: the `add()` call's trailing empty-string
            argument -- `""`, never omitted, so every result always HAS a
            fix field, just sometimes empty).
    """

    status: str
    category: str
    name: str
    message: str
    fix: str


# --------------------------------------------------------------------------
# Section 1 -- binaries.
# --------------------------------------------------------------------------
def _bin_version(binary: str) -> str:
    """First line of `<binary> --version`'s STDOUT, bash-parity with `| head -1`.

    Args:
        binary: The executable name (already confirmed present via
            `shutil.which` by the caller).

    Returns:
        The first line of stdout, or `""` if the process produced no
        stdout output or could not be started (bash: `2>/dev/null | head
        -1` -- stderr is discarded either way; a failing exit status does
        not itself raise here, matching bash's command-substitution-as-
        argument semantics, which do not trigger `set -e`).
    """
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = (proc.stdout or "").splitlines()
    return lines[0] if lines else ""


def _check_binaries() -> list[Result]:
    """Section 1: `sqlite3`/`jq`/`git` (FAIL if missing) + `gh` (WARN if missing).

    Returns:
        Four :class:`Result`s, in `cmd_doctor.sh`'s exact loop order
        (`sqlite3`, `jq`, `git`, then `gh` separately).
    """
    results: list[Result] = []
    for binary in ("sqlite3", "jq", "git"):
        if shutil.which(binary):
            results.append(Result("ok", "bin", binary, _bin_version(binary), ""))
        else:
            results.append(
                Result(
                    "fail",
                    "bin",
                    binary,
                    "not installed",
                    f"install {binary} (brew install {binary} / apt install {binary})",
                )
            )
    if shutil.which("gh"):
        results.append(Result("ok", "bin", "gh", _bin_version("gh"), ""))
    else:
        results.append(
            Result(
                "warn",
                "bin",
                "gh",
                "not installed (refresh --scope=github will be skipped)",
                "install gh: https://cli.github.com/",
            )
        )
    return results


# --------------------------------------------------------------------------
# Section 2 -- namespace dir + project.json.
# --------------------------------------------------------------------------
def _quiet_resolve_workdir() -> str:
    """`resolve_workdir()` with `SHCTX_QUIET=1` scoped to just this one call.

    Bash parity with `cmd_doctor.sh`'s `root="$(SHCTX_QUIET=1
    shctx_artifacts_root)"` -- a subshell-scoped env var override that
    suppresses `_lib.sh`'s split-brain stderr warning for THIS call only,
    restoring the ambient environment immediately after (so every LATER
    `resolve_workdir()`/`resolve_db_path()` call in this module, made
    plainly, re-triggers the warning if the split-brain condition holds --
    see the module docstring's "dual-namespace stderr warning duplicates
    itself" note).

    Returns:
        The resolved work directory path (need not exist on disk).
    """
    previous = os.environ.get("SHCTX_QUIET")
    os.environ["SHCTX_QUIET"] = "1"
    try:
        return resolve_workdir()
    finally:
        if previous is None:
            os.environ.pop("SHCTX_QUIET", None)
        else:
            os.environ["SHCTX_QUIET"] = previous


def _jq_r(data: dict[str, object], key: str) -> str:
    """Render `data[key]` exactly as `jq -r .<key>` would, given a parsed JSON object.

    Mirrors `shepherd_cli.commands.lock._jq_r` (duplicated, not imported --
    self-contained modules per the port's instructions).

    Args:
        data: A parsed JSON object (never None -- callers that need the
            "entire file failed to parse" case use `_jq_r_or_fallback`
            instead).
        key: The field to render.

    Returns:
        The four-character string `"null"` for a missing/`None` value
        (jq's own behavior for a missing key or explicit JSON `null`);
        the string itself, unquoted, for a string value; `"true"`/
        `"false"` for a boolean; the plain JSON text for anything else.
    """
    value = data.get(key)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _check_project_json(pjson_path: str) -> Result:
    """Section 2b: `<workdir>/project.json` present + has a non-null `.id`.

    Bash parity with `cmd_doctor.sh`:
    `pid=$(jq -r '.id' "$pjson" 2>/dev/null || echo "")` then
    `[[ -n "$pid" && "$pid" != "null" ]]`.

    Args:
        pjson_path: The resolved `project.json` path (need not exist).

    Returns:
        `ok` with `id=<value>` when the file parses as a JSON object with
        a present, non-null `.id`; `fail ... "malformed (no .id)"` when
        the file exists but `.id` is missing/null (or the file is valid
        JSON but not an object, or unparseable -- jq would itself fail on
        an unparseable file or a non-object top level, landing on the
        SAME `pid=""` fallback bash's `|| echo ""` produces); `fail ...
        "missing"` when the file does not exist at all.
    """
    if not os.path.isfile(pjson_path):
        return Result("fail", "ns", "project.json", "missing", "run 'shctx init'")

    try:
        with open(pjson_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        pid = ""
    else:
        pid = _jq_r(raw, "id") if isinstance(raw, dict) else ""

    if pid and pid != "null":
        return Result("ok", "ns", "project.json", f"id={pid}", "")
    return Result(
        "fail", "ns", "project.json", "malformed (no .id)", f"delete {pjson_path} and run 'shctx init'"
    )


def _check_namespace(root: str, repo: str) -> list[Result]:
    """Section 2a: the resolved namespace dir, + a WARN if both namespaces exist.

    Args:
        root: The resolved work directory (`_quiet_resolve_workdir()`'s
            result -- either `<repo>/.shepherd` or `<repo>/.artifacts`).
        repo: The resolved repo root.

    Returns:
        One `Result` for the namespace-dir existence check, PLUS a second
        `warn` `Result` (bash: `add warn ns "namespace conflict" ...`)
        only when BOTH `<repo>/.shepherd` and `<repo>/.artifacts` exist on
        disk -- omitted entirely otherwise, matching bash's conditional
        `add` call (not a third status value).
    """
    results: list[Result] = []
    if os.path.isdir(root):
        results.append(Result("ok", "ns", "namespace dir", root, ""))
    else:
        results.append(
            Result("fail", "ns", "namespace dir", "missing", "run 'shctx init' or 'shctx ready'")
        )

    shepherd_dir = os.path.join(repo, ".shepherd")
    artifacts_dir = os.path.join(repo, ".artifacts")
    if os.path.isdir(shepherd_dir) and os.path.isdir(artifacts_dir):
        active = os.path.basename(root)
        unused = ".artifacts" if active == ".shepherd" else ".shepherd"
        results.append(
            Result(
                "warn",
                "ns",
                "namespace conflict",
                f"both .shepherd/ and .artifacts/ exist; using {active}/, {unused}/ is unused",
                f"remove {unused}/ or run 'shctx init --{unused.replace('.', '')}' to switch",
            )
        )
    return results


# --------------------------------------------------------------------------
# Section 3 -- DB + schema (plain sqlite3, no Tortoise -- see module docstring).
# --------------------------------------------------------------------------
def _sql_scalar(db_path: str, sql: str, params: tuple[object, ...] = ()) -> object | None:
    """Run a single-row, single-column query, tolerant of any sqlite error.

    Bash parity with `shctx_sql "..." 2>/dev/null || echo <default>`: a
    missing table/column, a locked/corrupt database, or any other sqlite
    failure all resolve to `None` here (the caller applies its own
    bash-parity default), exactly like bash's stderr-discarding `||`
    fallback. Opens and closes a FRESH connection per call -- matching
    `shctx_sql`'s own one-shot `sqlite3` subprocess per query -- rather
    than holding one connection across this module's several queries.

    Args:
        db_path: Path to the sqlite database file (already confirmed to
            exist by the caller).
        sql: The SQL text to run (a single `SELECT`).
        params: Bound parameters for `sql`.

    Returns:
        The first row's first column, or `None` if the query returned no
        row, the value itself is SQL `NULL`, or any `sqlite3.Error` was
        raised while connecting or executing (including, deliberately,
        "no such column" -- see the module docstring's `artifacts` zone
        note, which relies on exactly this tolerance).
    """
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return row[0] if row is not None else None


def _du_h(path: str) -> str:
    """`du -h "$path" | cut -f1` -- the human-readable disk-usage size.

    Args:
        path: The file to measure (already confirmed to exist).

    Returns:
        The first tab-separated field of `du -h`'s first output line
        (e.g. `"492K"`), or `""` if `du` failed to run or produced no
        output -- matching bash's `2>/dev/null | cut -f1` (stderr
        discarded; a failing exit status does not itself raise, same
        command-substitution-as-argument semantics as `_bin_version`).
    """
    try:
        proc = subprocess.run(["du", "-h", path], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = (proc.stdout or "").splitlines()
    if not lines:
        return ""
    return lines[0].split("\t", 1)[0]


def _count_pending_migrations(db_path: str) -> int:
    """GAP-AWARE count of shipped migrations absent from `schema_versions`.

    Bash parity with `cmd_doctor.sh`'s v6.3.3 #200 gap-fill DETECTION
    (this module never applies anything -- see the module docstring):
    every migration file whose integer version is ABSENT from
    `schema_versions` counts as pending, regardless of whether that
    version is above or below the current `MAX(version)` -- a genuine gap
    a middle migration left behind counts too, not merely "anything newer
    than the max".

    Args:
        db_path: Path to the sqlite database file (already confirmed to
            exist).

    Returns:
        The number of shipped migration files whose version has no
        matching row in `schema_versions`. Returns 0 if the migrations
        directory cannot be located (bash: the whole `if [[ -d
        "$HERE/../schema/migrations" ]]` loop is skipped, leaving
        `pending=0`) or is unreadable.
    """
    migrations_dir = find_migrations_dir()
    if migrations_dir is None:
        return 0
    try:
        names = sorted(os.listdir(migrations_dir))
    except OSError:
        return 0

    pending = 0
    for name in names:
        match = _MIGRATION_NAME_RE.match(name)
        if match is None:
            continue
        version = int(match.group(1))
        exists = _sql_scalar(db_path, "SELECT 1 FROM schema_versions WHERE version=? LIMIT 1;", (version,))
        if exists is None:
            pending += 1
    return pending


def _check_db(db_path: str) -> list[Result]:
    """Section 3: DB file existence/size, schema_version, pending migrations.

    Args:
        db_path: The resolved database file path (need not exist).

    Returns:
        One `Result` (`fail ... "missing"`) if the DB file does not
        exist -- matching bash, which then skips `schema_version`/
        `pending migrations` ENTIRELY (no `Result` for either, not a
        degraded one). Otherwise three `Result`s: the DB file itself
        (`ok`, message = `_du_h` size), `schema_version` (`ok` with the
        value, or `warn "no schema_versions row"` if the table is empty),
        and `pending migrations` (`ok "none (schema at head)"`, or `warn
        "N unapplied (schema drift)"`).
    """
    db_name = os.path.basename(db_path)
    if not os.path.isfile(db_path):
        return [Result("fail", "db", db_name, "missing", "run 'shctx init' or 'shctx ready'")]

    results = [Result("ok", "db", db_name, _du_h(db_path), "")]

    schema_ver = _sql_scalar(db_path, "SELECT MAX(version) FROM schema_versions;")
    if schema_ver is not None:
        results.append(Result("ok", "db", "schema_version", str(schema_ver), ""))
    else:
        results.append(Result("warn", "db", "schema_version", "no schema_versions row", "run 'shctx migrate'"))

    pending = _count_pending_migrations(db_path)
    if pending > 0:
        results.append(
            Result(
                "warn",
                "db",
                "pending migrations",
                f"{pending} unapplied (schema drift)",
                "run 'shctx migrate' (stateful commands also self-heal — v6.3.3 #200)",
            )
        )
    else:
        results.append(Result("ok", "db", "pending migrations", "none (schema at head)", ""))

    return results


# --------------------------------------------------------------------------
# Section 4 -- lock state.
# --------------------------------------------------------------------------
def _load_lock_json(path: str) -> dict[str, object] | None:
    """Parse the lock file as a JSON object, or None on ANY failure to do so.

    Args:
        path: The lock file path (already confirmed to exist by the
            caller).

    Returns:
        The parsed object on success; `None` if the file is unreadable,
        not valid JSON, or valid JSON whose top level is not an object --
        every one of those is a case `jq -r .<key> "$lock"` would itself
        fail on, landing on bash's `|| echo "$fallback"` arm (see
        `_jq_r_or_fallback`/`_jq_numeric_or_zero`).
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _jq_r_or_fallback(data: dict[str, object] | None, key: str, fallback: str) -> str:
    """`jq -r .<key> "$lock" 2>/dev/null || echo "$fallback"`, given a pre-parsed object.

    Args:
        data: The result of `_load_lock_json` -- `None` means the ENTIRE
            file failed to parse (the `jq` invocation itself would have
            failed), NOT that a particular key is missing.
        key: The field to render.
        fallback: Returned only when `data` is `None` (bash's `|| echo`
            arm). A present-but-missing/null key renders as the literal
            string `"null"` instead (jq's own successful-exit behavior
            for that case) -- see `_jq_r`.

    Returns:
        `fallback` if `data` is `None`; otherwise `_jq_r(data, key)`.
    """
    if data is None:
        return fallback
    return _jq_r(data, key)


def _jq_numeric_or_zero(data: dict[str, object] | None, key: str) -> int:
    """Reproduce bash's `$(( now - $(jq -r .<key> ... || echo 0) ))` arithmetic quirk.

    In bash, `$(( ))` treats an unrecognized bareword (like the literal
    text `"null"` `jq -r` prints for a missing/null field, or `jq`'s own
    `|| echo 0` fallback text on total parse failure) as a reference to
    an unset shell variable, which evaluates to 0 -- NOT a syntax error.
    A JSON value that happens to be a numeric-looking STRING (e.g.
    `"1234567890"`) also round-trips correctly, because bash's arithmetic
    parser accepts a plain digit sequence as a literal regardless of how
    it got there.

    Args:
        data: The result of `_load_lock_json` (`None` == total parse
            failure, mirroring the `|| echo 0` fallback).
        key: The field to read numerically.

    Returns:
        The field's value as an int, when it is a JSON int, a JSON float
        (truncated), or a string containing only an optionally-signed
        digit sequence; `0` for `data is None`, a missing/null field, a
        JSON bool, or any other non-numeric-looking value -- every one of
        those collapses to the same "unset variable -> 0" arithmetic
        outcome bash produces.
    """
    if data is None:
        return 0
    value = data.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if _INT_LITERAL_RE.fullmatch(stripped):
            return int(stripped)
    return 0


def _check_lock(lock_path: str) -> Result:
    """Section 4: the live `<workdir>/shepherd.lock` file -- free, held, or stale.

    Args:
        lock_path: The resolved lock file path (need not exist).

    Returns:
        `ok "free"` if the file does not exist; `warn "held ${age}m by
        pid=... sess=... (stale?)"` if held and `age_min > 60`; otherwise
        `ok "held ${age}m by pid=... sess=..."`. A corrupt/unparseable
        lock file still reports `held` (bash: the file's mere `[[ -f
        ]]` existence gates `held` vs `free`, independent of whether its
        contents parse) with `pid=?`/`sess=?` and `age` computed from an
        effective `acquired_at` of 0 -- see `_jq_numeric_or_zero`.
    """
    if not os.path.isfile(lock_path):
        return Result("ok", "lock", "shepherd.lock", "free", "")

    data = _load_lock_json(lock_path)
    now = int(time.time())
    acquired_at = _jq_numeric_or_zero(data, "acquired_at")
    age_min = int((now - acquired_at) / 60)
    pid_display = _jq_r_or_fallback(data, "pid", "?")
    sess_display = _jq_r_or_fallback(data, "holder_session_id", "?")

    message = f"held {age_min}m by pid={pid_display} sess={sess_display}"
    if age_min > _LOCK_STALE_MINUTES:
        return Result("warn", "lock", "shepherd.lock", f"{message} (stale?)", "run 'shctx lock reap'")
    return Result("ok", "lock", "shepherd.lock", message, "")


# --------------------------------------------------------------------------
# Section 5 -- refresh staleness per zone.
# --------------------------------------------------------------------------
def _check_refresh_zones(db_path: str) -> list[Result]:
    """Section 5: `rows=N` + staleness age for each of `_ZONE_TABLES`.

    Args:
        db_path: The resolved database file path (already confirmed to
            exist by the caller -- bash gates this whole section behind
            its own `if [[ -f "$db" ]]`).

    Returns:
        Five `Result`s, in `_ZONE_TABLES` order. Each is `warn ...
        "never refreshed"` when the zone's `MAX(refreshed_at)` is 0/NULL/
        unreadable (including, deliberately, the `artifacts` zone, which
        has no `refreshed_at` column at all -- see the module docstring);
        `warn ... "stale ${age}m"` when `age_min > 120`; otherwise `ok
        ... "fresh ${age}m"`.
    """
    results: list[Result] = []
    now = int(time.time())
    for zone, table in _ZONE_TABLES:
        count = _sql_scalar(db_path, f"SELECT COUNT(*) FROM {table};")  # noqa: S608 - fixed table allow-list above
        count = count if isinstance(count, int) else 0
        latest = _sql_scalar(db_path, f"SELECT MAX(refreshed_at) FROM {table};")  # noqa: S608 - fixed table allow-list above
        latest = latest if isinstance(latest, int) else 0

        if latest == 0:
            results.append(
                Result(
                    "warn",
                    "refresh",
                    zone,
                    f"rows={count}, never refreshed",
                    f"run 'shctx refresh --scope={zone}' (or 'shctx sync')",
                )
            )
            continue

        age_min = int((now - latest) / 60)
        if age_min > _REFRESH_STALE_MINUTES:
            results.append(
                Result(
                    "warn", "refresh", zone, f"rows={count}, stale {age_min}m", f"run 'shctx refresh --scope={zone}'"
                )
            )
        else:
            results.append(Result("ok", "refresh", zone, f"rows={count}, fresh {age_min}m", ""))
    return results


# --------------------------------------------------------------------------
# Section 6 -- shepherd.toml locatable.
# --------------------------------------------------------------------------
def _check_config(repo: str) -> Result:
    """Section 6: is `shepherd.toml` locatable at any of three standard paths?

    Bash parity with `cmd_doctor.sh`'s candidate ORDER (project -> local
    -> XDG -- see the module docstring for why this deliberately differs
    from `cfg_get`'s own local -> project -> XDG value-resolution
    precedence).

    Args:
        repo: The resolved repo root.

    Returns:
        `ok` with the first existing candidate's path, or `warn "not
        found at standard paths"` if none exist.
    """
    xdg_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.environ.get("HOME", ""), ".config")
    candidates = (
        os.path.join(repo, ".claude", "shepherd.toml"),
        os.path.join(repo, ".claude", "shepherd.local.toml"),
        os.path.join(xdg_home, "shepherd.toml"),
    )
    for candidate in candidates:
        if os.path.isfile(candidate):
            return Result("ok", "config", "shepherd.toml", candidate, "")
    return Result(
        "warn",
        "config",
        "shepherd.toml",
        "not found at standard paths",
        "create .claude/shepherd.toml — see docs/configuration.md",
    )


# --------------------------------------------------------------------------
# Section 7 -- gates-invocation ledger (v6.4.1 #59; NOT in cmd_doctor.sh).
# --------------------------------------------------------------------------
# The first post-parity sections: `cmd_doctor.sh` never had them, and both are
# CONDITIONAL rows (emitted only when their subject exists -- gates configured /
# a version mismatch detected), following the namespace-conflict WARN's own
# conditional-`add()` precedent, so every bash-parity fixture without a
# `[gates]` config or a mismatched plugin.json renders byte-identically to the
# legacy script.

#: Mirrors `_lib.sh`'s toml-line parsing contract (cfg_section_get /
#: cfg_section_keys): section headers normalized by stripping whitespace,
#: `key = value` with a trailing ` # inline comment` and surrounding
#: double-quotes stripped, LAST match wins within a file, first FILE with the
#: key wins across the local -> project -> XDG precedence.
_TOML_HEADER_RE = re.compile(r"^\s*\[(.+?)\]")
_TOML_KEY_RE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=\s*(.*)$")


def _cfg_files(repo: str) -> tuple[str, ...]:
    """The three shepherd-config candidates, in cfg_get's VALUE precedence order."""
    xdg_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.environ.get("HOME", ""), ".config")
    return (
        os.path.join(repo, ".claude", "shepherd.local.toml"),
        os.path.join(repo, ".claude", "shepherd.toml"),
        os.path.join(xdg_home, "shepherd.toml"),
    )


def _toml_section_items(path: str, section: str) -> dict[str, str]:
    """Naive `[section]` key/value scan of one file (bash-parity, not a TOML parser).

    Args:
        path: The config file (need not exist).
        section: The normalized section name (e.g. ``"gates"``, ``"gates.extra"``).

    Returns:
        Ordered key -> value for the section, last assignment winning,
        values stripped of a trailing inline comment and surrounding
        double-quotes -- exactly `_lib.sh`'s awk contract. Empty on any
        read failure.
    """
    items: dict[str, str] = {}
    current = ""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return items
    for line in lines:
        header = _TOML_HEADER_RE.match(line)
        if header:
            current = re.sub(r"\s", "", header.group(1))
            continue
        if current != section:
            continue
        key_match = _TOML_KEY_RE.match(line)
        if not key_match:
            continue
        value = re.sub(r"\s+#.*$", "", key_match.group(2)).strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        items[key_match.group(1)] = value
    return items


def _cfg_section_get(repo: str, section: str, key: str) -> str:
    """`cfg_section_get` parity: first file (local -> project -> XDG) with the key wins."""
    for path in _cfg_files(repo):
        items = _toml_section_items(path, section)
        if items.get(key):
            return items[key]
    return ""


def _cfg_section_keys(repo: str, section: str) -> list[str]:
    """`cfg_section_keys` parity: key union across files, first-seen order."""
    seen: list[str] = []
    for path in _cfg_files(repo):
        for key in _toml_section_items(path, section):
            if key not in seen:
                seen.append(key)
    return seen


def _newest_gates_ledger(workdir: str) -> str | None:
    """The most recently modified `<workdir>/tmp/gates-ran-*.jsonl`, or None.

    The ledger is per-session (`gates-ran-<session>.jsonl`, appended by
    `hooks/scripts/bash_post.sh`); `doctor` runs without a session id of its
    own, so "this session" is read as the newest ledger by mtime -- the
    session most recently running gate commands in this workdir.
    """
    tmp_dir = os.path.join(workdir, "tmp")
    try:
        names = os.listdir(tmp_dir)
    except OSError:
        return None
    candidates = [
        os.path.join(tmp_dir, name)
        for name in names
        if name.startswith("gates-ran-") and name.endswith(".jsonl")
    ]
    best: str | None = None
    best_mtime = -1.0
    for path in candidates:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > best_mtime:
            best, best_mtime = path, mtime
    return best


def _ledger_counts(ledger_path: str | None) -> dict[str, int]:
    """Per-gate invocation counts from one ledger file (tolerant of bad lines)."""
    counts: dict[str, int] = {}
    if ledger_path is None:
        return counts
    try:
        with open(ledger_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return counts
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            gate = row.get("gate")
            if isinstance(gate, str) and gate:
                counts[gate] = counts.get(gate, 0) + 1
    return counts


def _check_gates(repo: str, workdir: str) -> list[Result]:
    """Section 7: has each configured gate a recorded invocation this session? (#59)

    Args:
        repo: The resolved repo root (config source).
        workdir: The resolved work directory (ledger home) -- resolved
            QUIETLY by the caller so this new section never disturbs the
            bash-parity stderr-warning call count.

    Returns:
        One `Result` per configured gate -- `[gates].check`, `[gates].lint`,
        then each `[gates.extra]` entry as ``extra:<key>``, config order --
        `ok "ran Nx this session"` when the ledger records it, `warn "no
        recorded invocation this session"` otherwise. EMPTY when no gate is
        configured at all (no `[gates]` config -> no section, preserving
        bash-parity output on gate-less fixtures).
    """
    gates: list[str] = []
    for key in ("check", "lint"):
        if _cfg_section_get(repo, "gates", key):
            gates.append(key)
    for key in _cfg_section_keys(repo, "gates.extra"):
        if _cfg_section_get(repo, "gates.extra", key):
            gates.append(f"extra:{key}")
    if not gates:
        return []

    ledger = _newest_gates_ledger(workdir)
    counts = _ledger_counts(ledger)
    results: list[Result] = []
    for gate in gates:
        ran = counts.get(gate, 0)
        if ran > 0:
            results.append(Result("ok", "gates", gate, f"ran {ran}x this session", ""))
        else:
            results.append(
                Result(
                    "warn",
                    "gates",
                    gate,
                    "no recorded invocation this session",
                    "run the configured gate command (bash_post.sh records it — #59)",
                )
            )
    return results


# --------------------------------------------------------------------------
# Section 8 -- CLI/plugin binary-version match (v6.4.1 #235; NOT in cmd_doctor.sh).
# --------------------------------------------------------------------------
def _check_version_match() -> list[Result]:
    """Section 8: WARN when the running CLI `__version__` differs from plugin.json.

    Conditional row (namespace-conflict precedent): silent when
    `CLAUDE_PLUGIN_ROOT` is unset, its `.claude-plugin/plugin.json` is
    unreadable/versionless, or the versions MATCH -- a healthy install adds
    no output and no exit-code change. A mismatch is the #235 stale-venv /
    stale-plugin condition: the plugin's hooks and doctrine cite one contract
    while the installed CLI implements another.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if not plugin_root:
        return []
    plugin_json = os.path.join(plugin_root, ".claude-plugin", "plugin.json")
    try:
        with open(plugin_json, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    plugin_version = raw.get("version") if isinstance(raw, dict) else None
    if not isinstance(plugin_version, str) or not plugin_version:
        return []

    from shepherd_cli import __version__

    if plugin_version == __version__:
        return []
    return [
        Result(
            "warn",
            "version",
            "cli/plugin",
            f"running CLI {__version__} != plugin {plugin_version} at CLAUDE_PLUGIN_ROOT",
            "rebuild the plugin venv (hooks/scripts/session_venv.sh) or update the plugin (#235)",
        )
    ]


# --------------------------------------------------------------------------
# Section 9 -- user-level tier, `~/.shepherd` (v6.4.1 #254; NOT in cmd_doctor.sh).
# --------------------------------------------------------------------------
# Unlike sections 7/8, this one is NOT purely conditional: `shepherd home
# init` exists precisely because nothing else ever creates `~/.shepherd` (the
# gap #254 reports), so a doctor section that stays silent whenever the tier
# is absent would never surface that gap either -- the whole point is to
# nudge an operator who has never run `shepherd home init` toward doing so.
# The user-home row therefore ALWAYS prints, `info` (never `warn`/`fail`)
# when absent, since the tier is entirely optional and its absence is not a
# health problem. Per-profile rows stay conditional in the sections-7/8
# spirit: they cover only profiles the PROJECT ITSELF declares -- a real
# file under the project canonical/legacy tier or `~/.shepherd/profiles/`,
# via `shepherd_cli.profiles.list_profiles(bundled_dir=None)`, which
# deliberately EXCLUDES the bundled tier so a project with zero declared
# profiles (every fixture in this port's own test suite) emits zero profile
# rows, not one row per bundled language.
def _check_user_tier(workdir: str) -> list[Result]:
    """Section 9: whether `~/.shepherd` exists, + which tier each declared profile resolves from.

    Args:
        workdir: The resolved work directory (the project profiles root
            `shepherd_cli.profiles.list_profiles` scans) -- resolved
            QUIETLY by the caller so this section never disturbs the
            bash-parity dual-namespace stderr-warning call count (see the
            module docstring's note on sections 7/8, which follow the
            same convention).

    Returns:
        One `Result` for `~/.shepherd` itself (`ok` present / `info`
        absent), PLUS one `ok` `Result` per project-declared profile
        naming the tier (`project`/`legacy`/`user`) it resolves from.
    """
    results: list[Result] = []
    user_home = resolve_user_home()
    if os.path.isdir(user_home):
        results.append(Result("ok", "user", "~/.shepherd", user_home, ""))
    else:
        results.append(
            Result(
                "info",
                "user",
                "~/.shepherd",
                f"not created at {user_home} (optional -- cross-project profiles/templates, #254)",
                "shepherd home init",
            )
        )
    for name, source in list_profiles(workdir=workdir):
        results.append(Result("ok", "user", f"profile:{name}", f"resolves from {source}", ""))
    return results


# --------------------------------------------------------------------------
# Collection + rendering.
# --------------------------------------------------------------------------
def _collect_results() -> list[Result]:
    """Run every section, in `cmd_doctor.sh`'s exact order, and collect the findings.

    Reproduces bash's call graph precisely (see the module docstring's
    "dual-namespace stderr warning duplicates itself" note): `root` is
    resolved ONCE, quietly; every later work-directory-dependent path
    (`project.json`, `shepherd.lock`) is resolved with a FRESH, unquieted
    `resolve_workdir()` call, exactly where bash's own `shctx_project_id_
    path`/`shctx_lock_path` helpers would call `shctx_artifacts_root`
    again. `resolve_db_path()` short-circuits this entirely when
    `SHCTX_DB` is set (matching `shctx_db_path`'s own env-override
    short-circuit) -- the common case for this test suite and for any
    caller pinning a specific DB file.

    Returns:
        Every `Result`, in section order, matching `cmd_doctor.sh`'s
        `results` array exactly.
    """
    results: list[Result] = []
    results.extend(_check_binaries())

    root = _quiet_resolve_workdir()
    repo = resolve_repo_root()
    results.extend(_check_namespace(root, repo))

    pjson_path = os.path.join(resolve_workdir(), "project.json")
    results.append(_check_project_json(pjson_path))

    db_path = resolve_db_path()
    db_exists = os.path.isfile(db_path)
    results.extend(_check_db(db_path))

    lock_path = os.path.join(resolve_workdir(), "shepherd.lock")
    results.append(_check_lock(lock_path))

    if db_exists:
        results.extend(_check_refresh_zones(db_path))

    results.append(_check_config(repo))

    # v6.4.1 post-parity sections (both conditional -- see their docstrings).
    # The workdir is re-resolved QUIETLY so these additions never change the
    # module's carefully-reproduced split-brain stderr-warning call count.
    results.extend(_check_gates(repo, _quiet_resolve_workdir()))
    results.extend(_check_version_match())
    results.extend(_check_user_tier(_quiet_resolve_workdir()))
    return results


def _json_escape_quotes(value: str) -> str:
    """Double every literal `"` in `value` -- bash-parity with `sed 's/"/\\\\"/g'`.

    Deliberately does NOT escape backslashes, newlines, or any other JSON
    control character -- `cmd_doctor.sh`'s JSON emitter only ever runs
    this exact `sed` substitution over `message`/`fix` (never `status`/
    `category`/`name`, which are printed raw, unescaped, via the same
    `printf '%s'`). Mirrors `shepherd_cli.commands.search._json_escape_
    quotes` (duplicated, not imported -- self-contained modules per the
    port's instructions).

    Args:
        value: The raw string (`message` or `fix`) to escape.

    Returns:
        `value` with every `"` replaced by `\\"`.
    """
    return value.replace('"', '\\"')


def _render_json(results: list[Result], fail_count: int, warn_count: int) -> str:
    """Render the bash-parity JSON report, mirroring `cmd_doctor.sh`'s emitter byte-for-byte.

    Reproduces bash's hand-rolled comma placement exactly: a comma is
    emitted BEFORE every entry except the first, on its own line
    immediately after the previous (un-terminated) entry -- see this
    module's own empirical verification against the real script for the
    exact resulting whitespace shape.

    Args:
        results: Every `Result`, in `_collect_results`'s order.
        fail_count: Count of `results` with `status == "fail"`.
        warn_count: Count of `results` with `status == "warn"`.

    Returns:
        The full JSON text (no trailing newline -- the caller's
        `typer.echo` supplies exactly one, matching bash's final `echo
        '}'`).
    """
    parts: list[str] = [
        "{\n",
        '  "summary": {\n',
        f'    "total": {len(results)},\n',
        f'    "fail": {fail_count},\n',
        f'    "warn": {warn_count}\n',
        "  },\n",
        '  "checks": [\n',
    ]
    first = True
    for result in results:
        if not first:
            parts.append(",\n")
        first = False
        msg_esc = _json_escape_quotes(result.message)
        fix_esc = _json_escape_quotes(result.fix)
        parts.append(
            "    {"
            f'"status":"{result.status}","category":"{result.category}","name":"{result.name}",'
            f'"message":"{msg_esc}","fix":"{fix_esc}"'
            "}"
        )
    parts.append("\n")
    parts.append("  ]\n")
    parts.append("}")
    return "".join(parts)


def _render_md(results: list[Result], fail_count: int, warn_count: int) -> str:
    """Render the bash-parity plain-text table, mirroring `cmd_doctor.sh`'s `printf` calls.

    Column formatting mirrors `printf '%-6s %-9s %-22s %s\\n'` (header +
    each row) and `printf '       %-9s %-22s   → fix: %s\\n'` (the
    optional fix line under a row that has one) exactly -- verified
    byte-for-byte against the real script's output, including the
    header's own `printf` (not a hand-typed string).

    Args:
        results: Every `Result`, in `_collect_results`'s order.
        fail_count: Count of `results` with `status == "fail"`.
        warn_count: Count of `results` with `status == "warn"`.

    Returns:
        The full multi-line report (no trailing newline -- the caller's
        `typer.echo` supplies exactly one), ending with the summary line
        `"shctx doctor: N fail, N warn, N ok"`.
    """
    lines: list[str] = [f"{'STATUS':<6} {'CATEGORY':<9} {'NAME':<22} {'MESSAGE'}"]
    for result in results:
        icon = _ICON.get(result.status, result.status)
        lines.append(f"{icon:<6} {result.category:<9} {result.name:<22} {result.message}")
        if result.fix:
            lines.append(f"       {'':<9} {'':<22}   → fix: {result.fix}")
    lines.append("")
    # Counted explicitly (not `len(results) - fail_count - warn_count`) so a
    # post-parity `"info"` row (section 9, #254) never inflates this tally --
    # `info` rows are neither `ok` nor `warn`/`fail`.
    ok_count = sum(1 for r in results if r.status == "ok")
    lines.append(f"shctx doctor: {fail_count} fail, {warn_count} warn, {ok_count} ok")
    return "\n".join(lines)


def _parse_args(tokens: list[str]) -> str:
    """Classify every token, bash-parity with `cmd_doctor.sh`'s `for arg in "$@"` loop.

    Args:
        tokens: Every token given after `doctor`, in order.

    Returns:
        The resolved format, `"md"` (default) or `"json"` -- the LAST
        `--md`/`--json` token wins (bash: plain variable reassignment
        inside the loop, no early exit).

    Raises:
        typer.Exit: Code 0, after printing `_USAGE` to stdout, on the
            FIRST `-h`/`--help` token encountered (bash: `exit 0` inside
            the loop's own `case` arm -- later tokens are never
            examined, matching this short-circuit exactly). Code 1, with
            bash's exact stderr message (`"ERROR: unknown arg: <token>"`),
            on the first token that is not `--json`, `--md`, `-h`, or
            `--help`.
    """
    fmt = "md"
    for token in tokens:
        if token in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        if token == "--json":
            fmt = "json"
        elif token == "--md":
            fmt = "md"
        else:
            typer.echo(f"ERROR: unknown arg: {token}", err=True)
            raise typer.Exit(code=1)
    return fmt


@app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context,
    raw: list[str] = typer.Argument(
        None,
        metavar="[--md|--json]",
        help="Output format -- --md (default, plain-text table) or --json.",
    ),
) -> None:
    """Pre-flight diagnostic for the shepherd context registry.

    Native port of `shctx doctor` (`cmd_doctor.sh`, v5.0.4). Read-only:
    checks binaries, namespace/project.json, DB schema currency, lock
    state, refresh staleness per zone, and `shepherd.toml` locatability,
    then prints a report and exits accordingly. Takes no positional
    arguments other than the output-format flag.

    Args:
        ctx: The Typer/Click context (unused directly; required so
            `invoke_without_command` dispatch works like every other
            single-verb group in this package).
        raw: Every token given after `doctor`, in order (`--md`,
            `--json`, `-h`/`--help`, or an error).

    Raises:
        typer.Exit: Code 0 on `-h`/`--help` (usage printed to stdout,
            checks never run). Code 1 on an unrecognized arg, OR if at
            least one check is `fail`. Code 2 if no check `fail`s but at
            least one `warn`s. Code 0 if every check is `ok`.
    """
    del ctx
    fmt = _parse_args(raw or [])

    results = _collect_results()
    fail_count = sum(1 for r in results if r.status == "fail")
    warn_count = sum(1 for r in results if r.status == "warn")

    if fmt == "json":
        typer.echo(_render_json(results, fail_count, warn_count))
    else:
        typer.echo(_render_md(results, fail_count, warn_count))

    if fail_count > 0:
        raise typer.Exit(code=1)
    if warn_count > 0:
        raise typer.Exit(code=2)


__all__ = ["app", "Result"]
