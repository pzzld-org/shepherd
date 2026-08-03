"""``shepherd handoff`` — sprint-handoff document Typer sub-app.

Native port of ``skills/context/scripts/cmd_handoff.sh``: three
subcommands that create/list/show a standard sprint-handoff markdown
document under ``${shctx_artifacts_root}/docs/handoffs/``.

* ``create [--branch=<name>] [--out=<path>]`` — render
  ``skills/context/references/handoff-template.md`` into
  ``<docs/handoffs>/<YYYY-MM-DD>-<branch>-close-handoff.md`` (or the
  ``--out`` path), auto-populating the git-log and registry-metric
  sections and leaving ``[FILL IN]`` markers on the operator-curated ones.
* ``list`` — the handoffs directory's ``*.md`` files, newest first.
* ``show [<branch|date>]`` — the most recent handoff whose full path
  contains the given substring (no argument = newest overall).

WHY ONE VARIADIC CALLBACK, NOT THREE ``@app.command()``s
==========================================================
``cmd_handoff.sh`` is one ``case "$sub" in create|list|show|""|-h|--help|
help|*) ... esac`` dispatch, and ``create`` is itself a hand-rolled
``for a in "$@"; do case "$a" in --branch=*|--out=*|-h|--help|*) ... esac;
done`` token loop with its own "unrecognized flag -> ``ERROR: unknown
flag: <token>``, exit 1" catch-all and its own ``-h``/``--help`` arm
(printing the SAME top-level usage text, not a ``create``-specific one).
None of that matches Typer/Click's own subcommand-dispatch or
option-parsing defaults. Exactly like
:mod:`shepherd_cli.commands.dups`/``dash``/``search``/``sync`` (self-
parsed variadic token loops — see those modules' own "WHY ONE VARIADIC
CALLBACK" notes), this module registers ZERO ``@app.command()``s and
instead defines one ``@app.callback(invoke_without_command=True)`` that
captures every token after ``handoff`` as a raw ``list[str]``
(``context_settings={"ignore_unknown_options": True, "help_option_names":
[]}``, so a token like ``-h`` or ``show``'s free-text pattern argument
lands here as a literal string instead of Click intercepting it) and
dispatches on ``argv[0]`` exactly like bash's ``case`` statement — see
:func:`_dispatch`.

**NO ``models_handoff.py``.** ``create``'s five registry metrics
(``artifacts``/``mem_entries``/``locks_history`` row counts plus the
``v_open_issues``/``v_drift_risk`` view row counts, all filtered by
``project_id``) are fetched via RAW SQL (hard rule #8's "raw SQL when the
ORM is a poor fit" — here, specifically, the COLLISION rule: ``artifacts``
and ``locks_history`` already have minimal mirror models in
:mod:`shepherd_cli.models_status` (``Artifact``, ``LockHistoryRow``) that
declare ONLY their primary key — ``shepherd status`` never needs to filter
either table by ``project_id``, so neither model carries that column, and
this module must not edit :mod:`shepherd_cli.models_status` (a shared
file) to add it, nor redeclare a second, colliding model over the same
table with a wider column set. ``v_open_issues``/``v_drift_risk`` are
plain SQL views (``skills/context/schema/0001_init.sql``), not backed by
any Tortoise model at all in this package. Rather than mix ORM calls for
some of the five counts (``mem_entries`` via the already-importable
:class:`shepherd_cli.models_mem.MemEntry`, which DOES carry ``project_id``)
with raw SQL for the other four, this module fetches all five uniformly
via one small raw-SQL helper (:func:`_count_where_project`) — consistent,
and exactly mirroring bash's own two fetch mechanisms (``count_or_zero``'s
direct ``shctx_sql`` calls for the three tables; ``query_count``'s
delegation to ``cmd_query.sh``'s canned ``open-issues.sql``/
``drift-risk.sql`` for the two views), which both ultimately reduce to
"COUNT(*) ... WHERE project_id = :project_id" with zero other filters (the
canned queries' own ``WHERE`` clauses, read directly from
``skills/context/queries/{open-issues,drift-risk}.sql``, have no
additional predicate beyond that project scope), and both fail soft to 0
on any error. This module therefore imports no Tortoise model at all
(only :mod:`shepherd_cli.db` for the lifespan + ``tortoise.Tortoise`` for
the raw connection).

Known parity gap (shared with every other multi-subcommand port in this
package, e.g. ``sprint``/``deliverable``/``dups``): Typer/Click's own
argument-count validation never fires here (every subcommand consumes a
raw ``list[str]`` with no Click-level arity checks) — this module owns
100% of its own validation, matching bash's own total absence of any
framework-level arg checking.

Timestamps: the handoff document's ``{{DATE}}`` placeholder is the local
calendar date (bash: ``date +%Y-%m-%d``), NOT a database column — this
module writes no row to any table itself (``create`` only READS the
registry for its five metrics). The generated ``{{SESSION}}`` value is a
UUIDv7 id (bash: ``shctx_uuid7``), matching the independent-but-spec-
compliant generator already used by
:mod:`shepherd_cli.commands.mem`/``style``/``lock``.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from datetime import datetime

import typer
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.render import build_env
from shepherd_cli.resolution import find_bash_shctx, resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Bash parity requires full control over -h/--help's own output (the
    # single global usage() heredoc, printed verbatim from any dispatch
    # point) instead of Click's autogenerated help text -- see the module
    # docstring's "WHY ONE VARIADIC CALLBACK" section, mirroring
    # shepherd_cli.commands.dups's identical technique.
    context_settings={"ignore_unknown_options": True, "help_option_names": []},
    help="Sprint-handoff documents: create | list | show (bash: cmd_handoff.sh).",
)

#: Verbatim bash-parity usage text -- cmd_handoff.sh's usage() heredoc,
#: printed to STDOUT on a bare invocation / -h / --help / help (exit 0),
#: and to STDERR (prefixed by an ERROR line) on an unknown subcommand
#: (exit 1) -- mirroring bash's ``usage`` vs ``usage >&2`` call-site
#: redirection (the function itself always writes to its own stdout; only
#: the CALLER decides which fd that lands on).
_USAGE = (
    "shctx handoff <create|list|show> [args]\n"
    "\n"
    "  create [--branch=<name>] [--out=<path>]\n"
    "      Emit a filled-in handoff template at\n"
    "      ${shctx_artifacts_root}/docs/handoffs/<YYYY-MM-DD>-<branch>-close-handoff.md.\n"
    "\n"
    "  list\n"
    "      List existing handoffs (newest first).\n"
    "\n"
    "  show [<branch|date>]\n"
    "      Print the most recent handoff matching the substring (no arg = newest)."
)

#: ``docs/handoffs`` under the resolved shepherd work directory -- bash
#: parity with ``handoff_root() { echo "$(shctx_artifacts_root)/docs/handoffs"; }``.
_HANDOFF_SUBDIR = os.path.join("docs", "handoffs")

#: The file ``create`` reads and fills in -- bash parity with
#: ``$(shctx_skill_root)/references/handoff-template.md``.
_TEMPLATE_RELPATH = os.path.join("references", "handoff-template.md")

_PROJECT_JSON_FILENAME = "project.json"

#: The five registry metrics ``create`` fetches, as ``(placeholder_key,
#: sql)`` pairs, in the exact order ``cmd_handoff.sh`` computes and prints
#: them in its "Sprint metrics" table. Every query is `COUNT(*) ... WHERE
#: project_id = ?` with no other predicate -- see the module docstring's
#: "NO models_handoff.py" section for why these three tables and two views
#: are read via raw SQL rather than the ORM.
_METRIC_QUERIES: tuple[tuple[str, str], ...] = (
    ("ARTIFACTS_COUNT", "SELECT COUNT(*) AS n FROM artifacts WHERE project_id = ?;"),
    ("MEM_COUNT", "SELECT COUNT(*) AS n FROM mem_entries WHERE project_id = ?;"),
    ("LOCK_COUNT", "SELECT COUNT(*) AS n FROM locks_history WHERE project_id = ?;"),
    ("OPEN_ISSUES_COUNT", "SELECT COUNT(*) AS n FROM v_open_issues WHERE project_id = ?;"),
    ("DRIFT_RISK_COUNT", "SELECT COUNT(*) AS n FROM v_drift_risk WHERE project_id = ?;"),
)


# --------------------------------------------------------------------------
# Path resolution.
# --------------------------------------------------------------------------
def _handoff_root() -> str:
    """Resolve the handoffs directory.

    Bash parity with ``cmd_handoff.sh``'s ``handoff_root()``:
    ``$(shctx_artifacts_root)/docs/handoffs``, where ``shctx_artifacts_root``
    delegates straight to ``resolve_workdir`` (see ``_lib.sh``).

    Returns:
        The absolute path to the handoffs directory (need not exist on disk).
    """
    return os.path.join(resolve_workdir(), _HANDOFF_SUBDIR)


def _skill_root() -> str | None:
    """Resolve the ``skills/context`` skill root, for locating the template.

    Bash parity with ``_lib.sh``'s ``shctx_skill_root`` AS USED by
    ``cmd_handoff.sh`` (``$(shctx_skill_root)/references/...``): the
    directory that contains ``references/`` + ``schema/`` + ``scripts/``.
    Derived from :func:`shepherd_cli.resolution.find_bash_shctx` (the
    ``shctx`` dispatcher lives at ``<skill_root>/scripts/shctx``) rather
    than reimplementing ``shctx_skill_root``'s own three-tier precedence
    (``SHCTX_SKILL_ROOT`` env override -> ``CLAUDE_PLUGIN_ROOT``-relative ->
    walk-up-from-the-repo-root) -- the same simplification
    :mod:`shepherd_cli.commands.sprint`/``sync``'s own ``_scripts_dir()``
    helpers make for their sibling-script lookups. The narrow
    ``SHCTX_SKILL_ROOT`` env-var override (a rarely-used, bash-internal
    knob with no other exposure anywhere else in this Python CLI) is not
    reproduced; every other resolution tier is.

    Returns:
        The absolute path to ``skills/context``, or None if the bash
        ``shctx`` tooling cannot be located at all.
    """
    shctx_path = find_bash_shctx()
    if shctx_path is None:
        return None
    scripts_dir = os.path.dirname(shctx_path)
    return os.path.dirname(scripts_dir)


def _template_path() -> str | None:
    """Resolve the handoff template file's path.

    Returns:
        ``<skill_root>/references/handoff-template.md``, or None if the
        skill root itself could not be resolved (see :func:`_skill_root`).
    """
    root = _skill_root()
    if root is None:
        return None
    return os.path.join(root, _TEMPLATE_RELPATH)


# --------------------------------------------------------------------------
# git helpers (create's auto-populated "What landed" section).
# --------------------------------------------------------------------------
def _run_git(args: list[str]) -> tuple[int, str]:
    """Run one ``git`` subcommand and capture its stdout.

    Args:
        args: The ``git`` argv, e.g. ``["rev-parse", "--abbrev-ref", "HEAD"]``
            (WITHOUT the leading ``"git"`` token itself).

    Returns:
        ``(returncode, stdout)``. ``returncode`` is 1 (with empty stdout)
        if ``git`` itself is not installed/executable -- bash parity with
        a failed command substitution under ``2>/dev/null``, which every
        caller here already treats as "git said no" regardless of the
        exact nonzero code.
    """
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    except OSError:
        return 1, ""
    return result.returncode, result.stdout


def _current_branch() -> str:
    """Resolve the current git branch, bash parity with ``cmd_create``'s branch default.

    Bash: ``branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo
    "unknown")`` -- used only when ``--branch=`` was not given (or given
    empty).

    Returns:
        The current branch name (``git rev-parse --abbrev-ref HEAD``'s
        stdout, trailing-newline-stripped), or the literal string
        ``"unknown"`` if that command fails (not a git repo, detached
        state edge cases aside -- ``--abbrev-ref`` prints ``HEAD`` for a
        detached HEAD, which is itself a valid non-``"unknown"`` result).
    """
    rc, out = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if rc == 0:
        return out.strip()
    return "unknown"


def _commits_for(branch: str) -> str:
    """Resolve the last 10 commits for the "What landed" section.

    Bash parity with ``cmd_create``::

        if git rev-parse --verify --quiet "$branch" >/dev/null 2>&1; then
          commits=$(git log --oneline -n 10 "$branch" 2>/dev/null || echo "(no commits)")
        else
          commits=$(git log --oneline -n 10 2>/dev/null || echo "(no commits)")
        fi
        [[ -n "$commits" ]] || commits="(no commits)"

    Args:
        branch: The resolved (default-or-explicit) sprint branch. When it
            resolves as a valid git ref (``git rev-parse --verify
            --quiet``), the log is scoped to that ref; otherwise it falls
            back to ``HEAD`` (bash: plain ``git log --oneline -n 10`` with
            no ref argument at all).

    Returns:
        Up to 10 ``--oneline`` log lines (newline-joined, trailing
        newline(s) stripped), or the literal ``"(no commits)"`` if the log
        command failed or produced no output.
    """
    verify_rc, _ = _run_git(["rev-parse", "--verify", "--quiet", branch])
    if verify_rc == 0:
        log_rc, log_out = _run_git(["log", "--oneline", "-n", "10", branch])
    else:
        log_rc, log_out = _run_git(["log", "--oneline", "-n", "10"])
    if log_rc != 0:
        return "(no commits)"
    commits = log_out.rstrip("\n")
    return commits if commits else "(no commits)"


# --------------------------------------------------------------------------
# project_id + registry metrics (create's "Sprint metrics" section).
# --------------------------------------------------------------------------
def _read_project_id() -> str:
    """Read the host project id from ``<workdir>/project.json``.

    Bash parity with ``_lib.sh``'s ``shctx_project_id`` as called in
    ``cmd_create``: ``project_id=$(shctx_project_id 2>/dev/null || echo
    "")`` -- every failure mode (missing file, unreadable, invalid JSON, a
    non-object top level) is swallowed to ``""`` by that wrapper, so this
    function never raises; it mirrors ``jq -r '.id'``'s exact
    stringification instead. Identical in shape to
    :mod:`shepherd_cli.commands.sprint`'s own ``_read_project_id`` (kept
    as a separate copy here per this package's self-contained-command-
    module convention -- see the module docstring).

    Returns:
        * Missing file, OS error, or invalid JSON -> ``""``.
        * Top level is not a JSON object -> ``""``.
        * ``.id`` absent or JSON ``null`` -> the literal string ``"null"``
          (``jq -r '.id'``'s text rendering of JSON ``null`` -- NOT an
          error, so the ``2>/dev/null || echo ""`` fallback never fires
          here).
        * ``.id`` is a JSON string -> that string, verbatim.
        * ``.id`` is a JSON bool/number -> its ``jq -r`` text form.
        * ``.id`` is a JSON object/array (never happens in a real
          ``project.json``) -> ``jq``'s 2-space-indented pretty-print form.
    """
    path = os.path.join(resolve_workdir(), _PROJECT_JSON_FILENAME)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    if "id" not in data or data["id"] is None:
        return "null"
    value = data["id"]
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, indent=2)


async def _count_where_project(sql: str, project_id: str) -> int:
    """Run one ``COUNT(*) ... WHERE project_id = ?`` query, fail-soft to 0.

    Bash parity with ``cmd_handoff.sh``'s ``count_or_zero``/``query_count``
    helpers: BOTH ultimately reduce to "run a query scoped to this
    project, and if anything about that fails (missing table/view, locked
    db, malformed query), report 0 rather than aborting the whole
    ``create`` run" -- ``count_or_zero`` via ``2>/dev/null || echo 0`` on a
    direct ``shctx_sql`` call, ``query_count`` via
    ``... 2>/dev/null | jq 'length' 2>/dev/null || echo 0`` around a
    ``cmd_query.sh`` subprocess. This is the single fail-soft primitive
    :data:`_METRIC_QUERIES` uses for all five.

    Args:
        sql: A ``SELECT COUNT(*) AS n FROM <table_or_view> WHERE
            project_id = ?;`` statement (one positional ``?`` bind).
        project_id: The value to bind.

    Returns:
        The count, or 0 if the query raised for any reason (missing
        table/view being the practically-relevant case -- e.g. a DB that
        predates the migration that added a given view).
    """
    try:
        conn = Tortoise.get_connection("default")
        rows = await conn.execute_query_dict(sql, [project_id])
    except Exception:  # noqa: BLE001 - deliberate bash-parity fail-soft-to-0, see docstring.
        return 0
    if not rows:
        return 0
    return int(rows[0]["n"])


async def _fetch_metrics_async(project_id: str) -> dict[str, int]:
    """Fetch all five :data:`_METRIC_QUERIES` counts inside one lifespan.

    Args:
        project_id: The host project id (already known non-empty by the
            caller -- bash never even opens the DB when it's empty; see
            :func:`_do_create`).

    Returns:
        ``{placeholder_key: count}`` for every entry in
        :data:`_METRIC_QUERIES`. If the lifespan itself cannot be
        established at all (e.g. the DB file's parent directory doesn't
        exist), every metric reports 0 -- the same fail-soft contract
        :func:`_count_where_project` gives a single query, extended to
        the whole batch (bash: each ``shctx_sql``/``cmd_query.sh`` call is
        independent and self-contained, so a totally unopenable DB would
        make every one of the five calls fail to 0 on its own -- this
        mirrors that end state without needing five separate connections).
    """
    metrics: dict[str, int] = {key: 0 for key, _ in _METRIC_QUERIES}
    try:
        async with db.lifespan():
            for key, sql in _METRIC_QUERIES:
                metrics[key] = await _count_where_project(sql, project_id)
    except Exception:  # noqa: BLE001 - deliberate bash-parity fail-soft-to-0, see docstring.
        return {key: 0 for key, _ in _METRIC_QUERIES}
    return metrics


# --------------------------------------------------------------------------
# Template rendering.
# --------------------------------------------------------------------------
def _render_template(template_text: str, values: dict[str, str]) -> str:
    """Render the handoff template through the ONE jinja engine (v6.4.1).

    Historically this was the repo's second hand-rolled render engine (a
    naive ``str.replace`` twin of bash's ``awk gsub`` pass). Both dialects
    are retired behind :mod:`shepherd_cli.render` (#244): the template's
    ``{{KEY}}`` placeholders are already valid Jinja2 variable syntax, so
    an in-memory ``from_string`` render with the same StrictUndefined
    environment produces identical bytes for the 13-key context while
    gaining hard missing-variable failures instead of silently-unfilled
    placeholders.

    Args:
        template_text: The raw ``handoff-template.md`` contents (the
            skill reference file keeps working as an operator override;
            the bundled ``templates/handoff.md.j2`` is its byte-twin).
        values: Every placeholder key (without the ``{{``/``}}``
            delimiters) mapped to its substitution text.

    Returns:
        The fully-rendered document text.
    """
    return build_env().from_string(template_text).render(**values)


# --------------------------------------------------------------------------
# uuid7 (session id).
# --------------------------------------------------------------------------
def _uuid7() -> str:
    """Generate a UUIDv7 (RFC 9562) id for the handoff's ``{{SESSION}}`` field.

    Bash generates it via ``_lib.sh``'s ``shctx_uuid7`` (a 48-bit
    millisecond-timestamp-prefixed, timestamp-sortable UUID built from
    ``date +%s%3N`` and ``/dev/urandom``). Copied verbatim from
    :func:`shepherd_cli.commands.mem._uuid7` (also duplicated, identically,
    in ``style.py``/``lock.py``) -- an independent, equally-valid UUIDv7
    generator over the stdlib ``time``/``os.urandom``, NOT byte-for-byte
    identical to bash's construction, but spec-compliant and
    timestamp-sortable, the only properties any caller depends on.

    Returns:
        A lowercase, hyphenated UUIDv7 string.
    """
    ts_ms = int(time.time() * 1000)
    raw = bytearray(16)
    raw[0:6] = ts_ms.to_bytes(6, "big")
    rand = os.urandom(10)
    raw[6] = 0x70 | (rand[0] & 0x0F)  # version nibble (0111) + 4 random bits
    raw[7] = rand[1]
    raw[8] = 0x80 | (rand[2] & 0x3F)  # variant bits (10) + 6 random bits
    raw[9:16] = rand[3:10]
    hex_str = raw.hex()
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------
def _do_create(rest: list[str]) -> int:
    """Run ``handoff create``, bash parity with ``cmd_create()``.

    Args:
        rest: Every token after ``create`` on the command line, in order.

    Returns:
        0 on success (the rendered handoff's path is printed to stdout).
        0 (usage printed to stdout) if ``-h``/``--help`` was seen. 1 (an
        ``ERROR: ...`` message on stderr) on the first unrecognized flag,
        a missing template file, or a failure writing the output file.
    """
    branch = ""
    out = ""
    for a in rest:
        if a.startswith("--branch="):
            branch = a[len("--branch=") :]
        elif a.startswith("--out="):
            out = a[len("--out=") :]
        elif a in ("-h", "--help"):
            typer.echo(_USAGE)
            return 0
        else:
            typer.echo(f"ERROR: unknown flag: {a}", err=True)
            return 1

    if not branch:
        branch = _current_branch()
    date = datetime.now().strftime("%Y-%m-%d")
    session_id = _uuid7()

    hroot = _handoff_root()
    os.makedirs(hroot, exist_ok=True)
    if not out:
        out = os.path.join(hroot, f"{date}-{branch}-close-handoff.md")

    template_path = _template_path()
    if template_path is None or not os.path.isfile(template_path):
        shown = template_path or os.path.join("<unresolved skill root>", _TEMPLATE_RELPATH)
        typer.echo(f"ERROR: template missing: {shown}", err=True)
        return 1
    with open(template_path, encoding="utf-8") as fh:
        template_text = fh.read()

    commits = _commits_for(branch)

    project_id = _read_project_id()
    if project_id:
        metrics = asyncio.run(_fetch_metrics_async(project_id))
    else:
        metrics = {key: 0 for key, _ in _METRIC_QUERIES}

    values: dict[str, str] = {
        "BRANCH": branch,
        "DATE": date,
        "SESSION": session_id,
        "NORTH_STAR": "[FILL IN]",
        "CARRY_FORWARDS": "[FILL IN]",
        "NEXT_FOCUS": "[FILL IN]",
        "FILES_OF_INTEREST": "[FILL IN]",
        "COMMITS": commits,
        **{key: str(value) for key, value in metrics.items()},
    }
    content = _render_template(template_text, values)

    try:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError as exc:
        # Not an explicit cmd_create.sh branch (bash's own awk redirection
        # would itself error uncontrolled here under `set -eu`) -- a
        # defensive, documented addition so a bad --out path degrades to a
        # clean exit-1 message instead of an unhandled traceback.
        typer.echo(f"ERROR: failed to write handoff: {out} ({exc.strerror or exc})", err=True)
        return 1

    typer.echo(out)
    return 0


# --------------------------------------------------------------------------
# list / show shared helpers.
# --------------------------------------------------------------------------
def _existing_handoffs_newest_first() -> list[str] | None:
    """List ``<hroot>/*.md``, sorted by mtime descending.

    Bash parity with both ``cmd_list``'s and ``cmd_show``'s shared
    "resolve the handoffs dir, bail with the same message if it's missing
    or empty" preamble (``[[ -d "$hroot" ]] || ...`` then a ``nullglob``
    array-length check), and with ``ls -1t``'s mtime-descending order.

    Returns:
        Full paths, newest-mtime first, or None if the handoffs directory
        does not exist or contains no ``*.md`` files (the caller then
        prints ``"(no handoffs at <hroot>)"`` itself, since the exact
        message text embeds ``hroot``).
    """
    hroot = _handoff_root()
    if not os.path.isdir(hroot):
        return None
    names = [name for name in os.listdir(hroot) if name.endswith(".md")]
    if not names:
        return None
    full_paths = [os.path.join(hroot, name) for name in names]
    full_paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return full_paths


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------
def _do_list(rest: list[str]) -> int:
    """Run ``handoff list``, bash parity with ``cmd_list()``.

    Args:
        rest: Every token after ``list`` on the command line. Bash's
            ``cmd_list()`` function body never reads ``"$@"`` at all, so
            every one of these tokens (including e.g. a stray ``-h``) is
            silently ignored, exactly like bash.

    Returns:
        0, always (bash: ``cmd_list`` has no failing path).
    """
    del rest
    handoffs = _existing_handoffs_newest_first()
    if handoffs is None:
        typer.echo(f"(no handoffs at {_handoff_root()})")
        return 0
    for path in handoffs:
        typer.echo(os.path.basename(path))
    return 0


# --------------------------------------------------------------------------
# show
# --------------------------------------------------------------------------
def _do_show(rest: list[str]) -> int:
    """Run ``handoff show``, bash parity with ``cmd_show()``.

    Bash::

        pat="${1:-}"
        ... (same missing/empty-dir bail as cmd_list) ...
        if [[ -z "$pat" ]]; then
          match=$(ls -1t "$hroot"/*.md 2>/dev/null | head -1 || true)
        else
          match=$(ls -1t "$hroot"/*.md 2>/dev/null | grep -F "$pat" | head -1 || true)
        fi
        [[ -n "$match" ]] || { echo "(no handoff matching '$pat')"; return 1; }
        cat "$match"

    Args:
        rest: Every token after ``show``; only the first (if any) is used
            as ``pat`` (bash: only ``$1`` is ever read). ``grep -F``
            matches against the FULL ``ls -1t`` line -- i.e. the full
            ``<hroot>/<name>.md`` path, not just the basename -- so
            ``pat`` is matched as a substring of the full path here too.

    Returns:
        0 with the matched file's exact byte content printed to stdout
        (no extra trailing newline added or removed) if a match was
        found. 0 with a ``"(no handoffs at ...)"`` message if the
        handoffs directory is missing/empty. 1 with a
        ``"(no handoff matching '<pat>')"`` message (stdout, bash parity
        -- bash's plain ``echo`` here has no ``>&2``) if ``pat`` was given
        but nothing matched.
    """
    pat = rest[0] if rest else ""
    handoffs = _existing_handoffs_newest_first()
    if handoffs is None:
        typer.echo(f"(no handoffs at {_handoff_root()})")
        return 0

    candidates = [path for path in handoffs if pat in path] if pat else handoffs
    if not candidates:
        typer.echo(f"(no handoff matching '{pat}')")
        return 1

    match = candidates[0]
    try:
        with open(match, encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        typer.echo(f"(no handoff matching '{pat}')")
        return 1
    typer.echo(content, nl=False)
    return 0


# --------------------------------------------------------------------------
# Top-level dispatcher + Typer wiring.
# --------------------------------------------------------------------------
def _dispatch(argv: list[str]) -> int:
    """Dispatch on ``argv[0]`` exactly like ``cmd_handoff.sh``'s top-level ``case`` statement.

    Args:
        argv: The raw remaining command-line tokens after ``handoff``,
            e.g. ``["create", "--branch=feature-x"]`` or ``[]``.

    Returns:
        The bash-parity process exit code for whichever subcommand ran
        (or the bare/``-h``/``--help``/``help``/unknown-subcommand arms).
    """
    sub = argv[0] if argv else ""
    rest = argv[1:]

    if sub == "create":
        return _do_create(rest)
    if sub == "list":
        return _do_list(rest)
    if sub == "show":
        return _do_show(rest)
    if sub in ("", "-h", "--help", "help"):
        typer.echo(_USAGE)
        return 0

    typer.echo(f"ERROR: unknown handoff sub: {sub}", err=True)
    typer.echo(_USAGE, err=True)
    return 1


@app.callback(invoke_without_command=True)
def handoff(
    args: list[str] = typer.Argument(
        None,
        metavar="<create|list|show> [args]",
        help=(
            "Subcommand + args: 'create [--branch=<name>] [--out=<path>]' | "
            "'list' | 'show [<branch|date>]'. Defaults to usage."
        ),
    ),
) -> None:
    """Sprint-handoff documents — native port of ``shctx handoff``.

    See the module docstring for why this is ONE variadic callback rather
    than three ``@app.command()``s: bash's own hand-rolled ``create``
    token loop (its own ``-h``/``--help`` arm and "unrecognized flag"
    catch-all), default-to-usage, and exit-1-on-unknown-subcommand
    contracts don't match Typer/Click's own subcommand-dispatch defaults.

    Args:
        args: Every token after ``handoff`` on the command line, in
            order, with NOTHING pre-parsed as flags/options by Click (see
            this app's ``context_settings={"ignore_unknown_options":
            True, "help_option_names": []}``, which is what makes a token
            like ``-h`` or ``show``'s free-text pattern argument land here
            as a literal string instead of Click intercepting it).
            ``None``/empty means a bare ``shepherd handoff`` -- dispatched
            as the usage arm, per bash's ``sub="${1:-}"``.
    """
    raise typer.Exit(code=_dispatch(list(args or [])))


__all__ = ["app"]
