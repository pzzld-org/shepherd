"""Native ports of the three ``refresh-*.sh`` stage scripts (cache-rebuild zones).

Ports ``skills/context/scripts/refresh-symbols.sh`` (v5.0.3),
``refresh-github.sh``, and ``refresh-artifacts.sh`` into three plain,
synchronous functions with the SAME observable behavior — stdout/stderr
lines, exit codes, graceful-absence semantics, and the exact rows each
script wrote:

* :func:`refresh_symbols`   — rust public-symbol index via ``cargo metadata``
  + the same grep-shaped line scan, upserted into ``index_symbols`` with a
  stale-row sweep.
* :func:`refresh_github`    — issues / PRs / releases / milestones via the
  ``gh`` CLI (with the ``shctx_gh_retry`` transient-failure retry loop),
  upserted into ``index_issues``/``index_prs``/``index_releases``/
  ``index_milestones``.
* :func:`refresh_artifacts` — markdown specs / plans / handoffs / journal
  classified by the same suffix/dir patterns, upserted into ``artifacts``
  (content column detected via ``PRAGMA table_info``, exactly like bash's
  v5.0.3 ``has_content_col`` probe).

This module is NOT a command module — it is the shared in-process
implementation :mod:`shepherd_cli.commands.refresh` (the ``symbols``/
``github``/``artifacts`` scopes) and :mod:`shepherd_cli.commands.init` (the
post-scaffold auto-refresh) both call, replacing their former
``["bash", .../refresh-*.sh]`` subprocesses. Each function returns a
process-style exit code (0/1/...) and prints exactly what the bash script
printed; the callers map that int onto their own ``typer.Exit`` codes.

WHY PLAIN ``sqlite3``, NOT TORTOISE
=============================================================================
Bash's ``shctx_sql`` spawns a fresh ``sqlite3`` process per statement, so
every INSERT auto-commits (each script's own comments call this out). Both
callers of this module are fully synchronous (``init`` deliberately never
opens a Tortoise connection — see its module docstring's architecture
deviation note), and every write here is a canned parameterized UPSERT with
no row shape worth an ORM model (hard rule #8's raw-SQL escape hatch).
Plain stdlib ``sqlite3`` with ``isolation_level=None`` (autocommit)
therefore mirrors bash's per-statement commit behavior exactly while
staying callable from both sync call sites.

BASH-PARITY NOTES (all preserved deliberately)
=============================================================================
* **Parameterized SQL vs bash's inline escaping.** Bash SQL-escaped values
  with ``sed "s/'/''/g"`` before splicing them into a quoted literal — the
  STORED value is the original text. Parameter binding stores byte-identical
  values for every input bash handled, without the malformed-SQL failure
  mode. One knock-on effect is preserved exactly:
  ``refresh-symbols.sh`` hashes ``"$rel:$line:$sig"`` where ``$sig`` is the
  ALREADY-ESCAPED signature (quotes doubled) — :func:`_symbol_hash` feeds
  the escaped variant into sha256 so stored hashes match bash's
  byte-for-byte.
* **The issues ``milestone`` literal-``'NULL'`` quirk.** Bash writes
  ``'${milestone:-NULL}'`` — QUOTED — so an issue without a milestone stores
  the literal four-character string ``NULL``, not SQL NULL. Reproduced
  (``milestone or "NULL"``) so python- and bash-refreshed rows are
  indistinguishable. (PR ``merged_at`` / release ``published_at`` /
  milestone ``due_on`` use UNQUOTED ``NULL`` in bash and are real SQL NULLs
  here, via ``None``.)
* **``jq -r`` null rendering.** ``jq -r .body`` renders JSON ``null`` as
  the literal string ``"null"`` — :func:`_jq_r` reproduces this for every
  field bash read without ``// empty``.
* **The artifacts title single-quote QUIRK.** ``refresh-artifacts.sh``'s
  title pipeline is ``sed -E 's/^#+ //;s/'\\''/''/g'`` which, after shell
  dequoting, is ``s/^#+ //;s/'//g`` — it REMOVES single quotes entirely
  (verified empirically: ``# It's a 'plan'`` -> ``Its a plan``), unlike the
  content pipeline's genuine ``s/'/''/g`` doubling. Reproduced exactly:
  titles are stored quote-stripped, content is stored verbatim.
* **Graceful absence.** ``cargo`` missing -> ``"shctx: cargo not installed;
  skipping rust symbols"``, exit 0. ``gh`` missing -> ``"shctx: gh CLI not
  installed; skipping github refresh"``, exit 0. (Bash's ``jq`` requirement
  check has no Python equivalent — JSON is parsed natively — so the
  ``"shctx: jq required"`` exit-1 branch is structurally unreachable and
  deliberately dropped.)
* **``shctx_gh_retry``.** :func:`_gh_retry` reproduces the transient-failure
  retry loop verbatim: ``SHCTX_GH_RETRY_MAX`` (default 3) attempts,
  ``SHCTX_GH_RETRY_BACKOFF`` (default 2) ** attempt seconds of backoff, the
  same transient markers (HTTP 504/502/503, timeout, timed out, connection
  reset) matched against the COMBINED stdout+stderr, fail-fast with the
  captured output on stderr for a non-transient failure, and the
  ``"exhausted N attempts; last output:"`` trailer. Call sites that bash
  suppressed with ``2>/dev/null`` (``repo view``, the milestones ``gh
  api``) pass ``quiet=True``.
* **Hard gh failures abort the stage's script.** Under ``set -eu -o
  pipefail`` a non-zero ``shctx_gh_retry`` in any of the four list
  pipelines aborts ``refresh-github.sh`` with that code before later
  stages run — :func:`refresh_github` returns the failing stage's code
  immediately, in the same fixed order (issues -> PRs -> releases ->
  milestones).
* **Timestamps.** ``epoch_iso()`` (GNU ``date -d`` semantics for
  ``%Y-%m-%dT%H:%M:%SZ`` values, treated as UTC; unparseable -> 0) is
  :func:`_epoch_iso`. ``shctx_now`` is ``int(time.time())`` — epoch
  seconds, captured ONCE per function run exactly like bash's single
  ``now=$(shctx_now)``, so the trailing stale-row sweep in
  :func:`refresh_symbols` (``refreshed_at < now``, rust rows only) uses the
  same cutoff as the upserts it protects.
* **``project.json`` resolution.** Every script calls ``_lib.sh``'s
  ``shctx_project_id`` first — missing file prints ``"ERROR: <path> missing
  — run 'shctx init' first"`` to stderr and (under ``set -e``) aborts with
  exit 1. :func:`_project_id` mirrors this, including ``jq -r``'s
  ``"null"`` rendering for a present-but-JSON-``null`` ``"id"``, matching
  :mod:`shepherd_cli.commands.refresh`'s own ``_telemetry_project_id``.
* **Content cap + decode.** Bash caps stored artifact content at 262144 raw
  BYTES (``head -c``); this port truncates the same byte prefix and decodes
  it ``errors="replace"`` (sqlite TEXT needs str) — a truncated multi-byte
  character becomes U+FFFD instead of bash's raw broken byte, the only
  (disclosed) divergence, unobservable for ASCII/UTF-8-aligned content.
* **sqlite errors.** ``sqlite3 -bail`` printed its own error and aborted
  the script with exit 1; each function catches ``sqlite3.Error``, prints
  a controlled ``"ERROR: sqlite3: <detail>"`` stderr line (not
  byte-identical to the CLI tool's own text), and returns 1.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

import typer

from shepherd_cli.resolution import resolve_db_path, resolve_repo_root, resolve_workdir

# --------------------------------------------------------------------------
# Shared helpers.
# --------------------------------------------------------------------------


def _project_id() -> str | None:
    """Resolve the active project id, bash-parity with ``_lib.sh``'s ``shctx_project_id``.

    Duplicated from :mod:`shepherd_cli.commands.refresh`'s
    ``_telemetry_project_id`` (self-contained-module convention): missing
    ``<workdir>/project.json`` prints bash's exact stderr error and signals
    failure; malformed JSON prints an equivalent (not byte-identical —
    jq's own parse-error text is not reproduced) message; a
    present-but-JSON-``null`` ``"id"`` renders as the literal ``"null"``
    (``jq -r``'s raw-output rendering).

    Returns:
        The resolved project id string, or None on any failure (error
        already printed to stderr).
    """
    path = os.path.join(resolve_workdir(), "project.json")
    if not os.path.isfile(path):
        typer.echo(f"ERROR: {path} missing — run 'shctx init' first", err=True)
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        typer.echo(f"ERROR: failed to parse {path} as JSON", err=True)
        return None
    if not isinstance(data, dict) or data.get("id") is None:
        return "null"
    value = data["id"]
    return value if isinstance(value, str) else json.dumps(value)


def _uuid7() -> str:
    """Generate a UUIDv7 (RFC 9562) row id.

    Independent, equally-valid UUIDv7 generator over stdlib
    ``time``/``os.urandom`` — duplicated from
    :mod:`shepherd_cli.commands.init`/:mod:`shepherd_cli.commands.mem`'s
    identical helpers (self-contained-module convention). NOT byte-for-byte
    identical to bash's ``shctx_uuid7`` bit-packing; every id it produces is
    a spec-compliant, time-sortable UUIDv7, the only property any consumer
    depends on.

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


def _epoch_iso(value: str) -> int:
    """Coerce one ISO-8601 timestamp string to epoch seconds, bash-parity with ``epoch_iso()``.

    Bash: ``date -j -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s || date -d "$1" +%s ||
    echo 0`` — GNU ``date -d`` treats a trailing ``Z`` as UTC; anything
    unparseable degrades to 0.

    Args:
        value: The raw timestamp string (e.g. ``"2026-01-02T03:04:05Z"``).

    Returns:
        Epoch seconds (UTC), or 0 when ``value`` is empty/unparseable.
    """
    if not value:
        return 0
    text = value[:-1] if value.endswith("Z") else value
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp())


def _jq_r(value: object) -> str:
    """Render one JSON value the way ``jq -r`` does.

    Args:
        value: Any decoded JSON value.

    Returns:
        The string itself for strings; the literal ``"null"`` for None
        (``jq -r``'s raw-output rendering of JSON ``null``);
        ``"true"``/``"false"`` for booleans; compact JSON otherwise.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _strip_repo_prefix(path: str, repo_root: str) -> str:
    """Strip the repo-root prefix, bash-parity with ``${f#$(shctx_repo_root)/}``.

    Args:
        path: An absolute file/directory path.
        repo_root: The resolved repository root.

    Returns:
        ``path`` relative to ``repo_root`` when it lives underneath it;
        ``path`` unchanged otherwise (bash's ``#`` prefix-strip is a no-op
        when the prefix doesn't match).
    """
    prefix = repo_root.rstrip("/") + "/"
    return path[len(prefix) :] if path.startswith(prefix) else path


def _connect(db_path: str) -> sqlite3.Connection:
    """Open the project DB in autocommit mode (per-statement commit, like ``shctx_sql``)."""
    return sqlite3.connect(db_path, isolation_level=None)


# --------------------------------------------------------------------------
# symbols — port of refresh-symbols.sh (v5.0.3 grep-based rust extractor).
# --------------------------------------------------------------------------

#: The grep -nE pre-filter from ``refresh-symbols.sh`` line 42 — a line
#: must match this before any per-line parsing happens.
_SYMBOL_FILTER_RE = re.compile(
    r'^\s*(pub(\([^)]+\))?\s+)?'
    r'((async|unsafe|const|extern(\s*"[^"]*")?)\s+)*'
    r"(fn|struct|trait|enum|const|static|type|mod|use)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*|\{)"
)

_VIS_RE = re.compile(r"^(pub(\([^)]+\))?)\s")
_MOD_RE = re.compile(r'^(async|unsafe|extern\s*"[^"]*"|extern)\s')
_CONST_FN_RE = re.compile(r"^const\s+fn\s")
_KIND_RE = re.compile(r"^(fn|struct|trait|enum|const|static|type|mod)\s+([A-Za-z_][A-Za-z0-9_]*)")
_USE_RE = re.compile(r"^use\s+(.+)$")
_GROUP_RE = re.compile(r"\{(.+)\}")
_AS_ALIAS_RE = re.compile(r"\sas\s+([A-Za-z_][A-Za-z0-9_]*)")
_TRAILING_IDENT_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*$")

_SYMBOL_UPSERT_SQL = (
    "INSERT INTO index_symbols "
    "(id, project_id, name, kind, package, file_path, line, visibility, signature, "
    "doc_summary, language, hash, refreshed_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'rust', ?, ?) "
    "ON CONFLICT(project_id, name, package, kind) DO UPDATE SET "
    "file_path=excluded.file_path, line=excluded.line, "
    "visibility=excluded.visibility, signature=excluded.signature, "
    "hash=excluded.hash, refreshed_at=excluded.refreshed_at"
)


def _cargo_packages() -> list[tuple[str, str]]:
    """Enumerate workspace packages, bash-parity with the ``cargo metadata | jq`` pipeline.

    Runs ``cargo metadata --format-version 1 --no-deps`` in the current
    working directory (exactly where bash ran it) with stderr discarded
    (bash: ``2>/dev/null``). Any failure — cargo erroring, unparseable
    output — collapses to an empty list, exactly like ``jq`` reading an
    empty/broken stream produced zero package rows.

    Returns:
        ``(name, manifest_path)`` pairs in ``cargo metadata``'s own order.
    """
    try:
        result = subprocess.run(
            ["cargo", "metadata", "--format-version", "1", "--no-deps"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, list):
        return []
    pairs: list[tuple[str, str]] = []
    for pkg in packages:
        if isinstance(pkg, dict) and isinstance(pkg.get("name"), str) and isinstance(pkg.get("manifest_path"), str):
            pairs.append((pkg["name"], pkg["manifest_path"]))
    return pairs


def _rust_source_files(src_dir: str) -> list[str]:
    """Every ``*.rs`` file under ``src_dir``, bash-parity with ``find ... -name '*.rs'``.

    Args:
        src_dir: The package's ``src/`` directory (may not exist — bash's
            ``find`` failure was ``2>/dev/null``-suppressed and yielded
            nothing).

    Returns:
        Absolute paths, sorted for determinism (bash's ``find`` order is
        filesystem-dependent and never asserted on).
    """
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames.sort()
        for filename in sorted(filenames):
            if filename.endswith(".rs"):
                files.append(os.path.join(dirpath, filename))
    return files


def _symbol_rows(content: str) -> list[tuple[str, str, str, bool]]:
    """Parse one matched source line into symbol rows, bash-parity with the read loop.

    Reproduces ``refresh-symbols.sh``'s normalization exactly: strip
    leading whitespace, peel off visibility (``pub``/``pub(...)``), peel
    off modifier sequences (``async``/``unsafe``/``extern "C"``/``extern``;
    ``const`` only when directly followed by ``fn``), then read
    ``kind + name`` — or, for ``use`` lines, the re-export branch (only
    ``pub use`` is indexed; group bodies split on commas, ``as`` aliases
    honored, the last path segment otherwise).

    Args:
        content: The raw matched line (no trailing newline).

    Returns:
        ``(name, kind, visibility, hash_over_name)`` tuples — usually one;
        several for a group re-export; empty when the line normalizes to
        nothing indexable. ``hash_over_name`` is True only for GROUP
        re-export items, whose bash hash input is ``rel:line:SYM`` rather
        than ``rel:line:ESCAPED_SIG``.
    """
    c = content.lstrip()
    vis = "private"
    match = _VIS_RE.match(c)
    if match:
        vis = match.group(1)
        c = c[match.end(1) :].lstrip()
    while (match := _MOD_RE.match(c)) is not None:
        c = c[match.end(1) :].lstrip()
    if _CONST_FN_RE.match(c):
        c = c[len("const") :].lstrip()

    match = _KIND_RE.match(c)
    if match:
        return [(match.group(2), match.group(1), vis, False)]

    match = _USE_RE.match(c)
    if match is None:
        return []
    # Re-export: only `pub use` is interesting — private `use` is just an import.
    if vis == "private":
        return []
    path_expr = match.group(1)
    if ";" in path_expr:  # bash: ${path_expr%;*} — strip from the LAST `;`.
        path_expr = path_expr[: path_expr.rindex(";")]

    group = _GROUP_RE.search(path_expr)
    if group:
        rows: list[tuple[str, str, str, bool]] = []
        for raw_item in group.group(1).split(","):
            item = raw_item.strip()
            if not item:
                continue
            alias = _AS_ALIAS_RE.search(item)
            if alias:
                sym = alias.group(1)
            else:
                trailing = _TRAILING_IDENT_RE.search(item)
                if trailing is None:
                    continue
                sym = trailing.group(1)
            rows.append((sym, "re-export", vis, True))
        return rows

    alias = _AS_ALIAS_RE.search(path_expr)
    if alias:
        sym = alias.group(1)
    else:
        trailing = _TRAILING_IDENT_RE.search(path_expr)
        if trailing is None:
            return []
        sym = trailing.group(1)
    return [(sym, "re-export", vis, False)]


def _symbol_hash(rel: str, line: int, tail: str) -> str:
    """sha256 of ``"<rel>:<line>:<tail>"``, bash-parity with the ``shasum -a 256`` pipe."""
    return hashlib.sha256(f"{rel}:{line}:{tail}".encode("utf-8")).hexdigest()


def refresh_symbols() -> int:
    """Rebuild the rust public-symbol index — native port of ``refresh-symbols.sh``.

    Returns:
        0 after printing ``"shctx refresh symbols: ok"`` (or one of the two
        graceful-skip lines: cargo missing / no rust packages found); 1 on
        a missing/unparseable ``project.json`` or a sqlite failure (error
        already printed to stderr), matching bash's ``set -e`` abort.
    """
    if shutil.which("cargo") is None:
        typer.echo("shctx: cargo not installed; skipping rust symbols")
        return 0
    project_id = _project_id()
    if project_id is None:
        return 1
    now = int(time.time())

    packages = _cargo_packages()
    if not packages:
        typer.echo("shctx: no rust packages found")
        return 0

    repo_root = resolve_repo_root()
    try:
        conn = _connect(resolve_db_path())
    except sqlite3.Error as exc:
        typer.echo(f"ERROR: sqlite3: {exc}", err=True)
        return 1
    try:
        for _name, manifest_path in packages:
            pkg_dir = os.path.dirname(manifest_path)
            rel_pkg = _strip_repo_prefix(pkg_dir, repo_root)
            for source_path in _rust_source_files(os.path.join(pkg_dir, "src")):
                rel = _strip_repo_prefix(source_path, repo_root)
                try:
                    with open(source_path, encoding="utf-8", errors="replace") as fh:
                        lines = fh.read().splitlines()
                except OSError:
                    continue  # bash: grep 2>/dev/null || true — unreadable file yields no matches
                for lineno, content in enumerate(lines, 1):
                    if not _SYMBOL_FILTER_RE.match(content):
                        continue
                    rows = _symbol_rows(content)
                    if not rows:
                        continue
                    sig = content.lstrip()
                    sig_escaped = sig.replace("'", "''")  # bash hashed the SQL-ESCAPED signature
                    for sym, kind, vis, hash_over_name in rows:
                        digest = _symbol_hash(rel, lineno, sym if hash_over_name else sig_escaped)
                        conn.execute(
                            _SYMBOL_UPSERT_SQL,
                            (_uuid7(), project_id, sym, kind, rel_pkg, rel, lineno, vis, sig, digest, now),
                        )
        # Sweep stale rows (rust only) older than this run.
        conn.execute(
            "DELETE FROM index_symbols WHERE project_id=? AND language='rust' AND refreshed_at<?",
            (project_id, now),
        )
    except sqlite3.Error as exc:
        typer.echo(f"ERROR: sqlite3: {exc}", err=True)
        return 1
    finally:
        conn.close()
    typer.echo("shctx refresh symbols: ok")
    return 0


# --------------------------------------------------------------------------
# github — port of refresh-github.sh (gh CLI + shctx_gh_retry).
# --------------------------------------------------------------------------

#: Transient-failure markers from ``_lib.sh``'s ``shctx_gh_retry`` case arm,
#: matched as substrings of the COMBINED stdout+stderr.
_TRANSIENT_MARKERS = ("HTTP 504", "HTTP 502", "HTTP 503", "timeout", "timed out", "connection reset")


def _env_int(name: str, default: int) -> int:
    """Read an integer env override, falling back to ``default`` when unset/malformed."""
    raw = os.environ.get(name, "")
    try:
        return int(raw)
    except ValueError:
        return default


def _gh_retry(args: list[str], *, quiet: bool = False) -> tuple[int, str]:
    """Run ``gh <args>`` with transient-failure retry, bash-parity with ``shctx_gh_retry``.

    Args:
        args: The ``gh`` argv tail, e.g. ``["issue", "list", ...]``.
        quiet: True to suppress every stderr line this helper would emit —
            models the ``2>/dev/null`` bash applied at the ``repo view``
            and milestones ``gh api`` call sites.

    Returns:
        ``(0, stdout)`` on success; ``(rc, "")`` on failure, after
        printing the captured combined output (non-transient) or the
        ``"exhausted N attempts"`` trailer (transient, retries used up) to
        stderr unless ``quiet``.
    """
    max_attempts = _env_int("SHCTX_GH_RETRY_MAX", 3)
    backoff_base = _env_int("SHCTX_GH_RETRY_BACKOFF", 2)
    attempt = 1
    rc = 0
    combined = ""
    while attempt <= max_attempts:
        try:
            result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
        except OSError:
            return 127, ""  # gh vanished after the which() check — bash's command-not-found code
        if result.returncode == 0:
            return 0, result.stdout
        rc = result.returncode
        combined = result.stdout + result.stderr
        if any(marker in combined for marker in _TRANSIENT_MARKERS):
            if attempt < max_attempts:
                sleep_for = backoff_base**attempt
                if not quiet:
                    typer.echo(
                        f"shctx_gh_retry: transient failure (attempt {attempt}/{max_attempts}); "
                        f"retrying in {sleep_for}s...",
                        err=True,
                    )
                time.sleep(sleep_for)
        else:
            # Non-transient failure — fail fast (bash: printf '%s' "$out" >&2).
            if not quiet:
                sys.stderr.write(combined)
                sys.stderr.flush()
            return rc, ""
        attempt += 1
    if not quiet:
        typer.echo(f"shctx_gh_retry: exhausted {max_attempts} attempts; last output:", err=True)
        sys.stderr.write(combined + "\n")
        sys.stderr.flush()
    return rc, ""


def _gh_json_rows(args: list[str], *, quiet: bool = False, tolerant: bool = False) -> tuple[int, list[dict]]:
    """Run one ``gh ... --json`` listing and decode its array, bash-parity with the jq pipes.

    Args:
        args: The ``gh`` argv tail.
        quiet: Forwarded to :func:`_gh_retry`.
        tolerant: True for the milestones stage's ``jq -c '.[]?'`` shape —
            a non-array top level yields zero rows instead of an error.

    Returns:
        ``(0, rows)`` on success (rows only includes dict elements, like
        ``jq -c '.[]'`` streaming objects); ``(rc, [])`` when the gh call
        failed (its own stderr already handled); ``(1, [])`` with a
        controlled stderr line when the output is unparseable/non-array
        (bash: the jq stage of the pipeline failing under ``pipefail``).
    """
    rc, out = _gh_retry(args, quiet=quiet)
    if rc != 0:
        return rc, []
    if not out.strip():
        return 0, []  # jq on an empty stream emits nothing
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        typer.echo("ERROR: gh returned unparseable JSON", err=True)
        return 1, []
    if not isinstance(data, list):
        if tolerant:
            return 0, []
        typer.echo("ERROR: gh returned unexpected JSON shape", err=True)
        return 1, []
    return 0, [row for row in data if isinstance(row, dict)]


def _compact_names(items: object, key: str) -> str:
    """``jq -c '[.X[].name]'``-shaped compact JSON array of ``item[key]`` values."""
    values = [item.get(key) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    return json.dumps(values, separators=(",", ":"))


def refresh_github() -> int:
    """Rebuild the github caches — native port of ``refresh-github.sh``.

    Refreshes issues, PRs, releases, and milestones in that fixed order,
    aborting at the FIRST stage whose ``gh`` pipeline fails (bash: ``set
    -eu -o pipefail``), and prints ``"shctx refresh github: ok"`` only when
    all four completed.

    Returns:
        0 on success or the graceful gh-missing skip; 1 on a missing
        ``project.json`` or sqlite failure; otherwise the failing gh
        pipeline's own exit code.
    """
    if shutil.which("gh") is None:
        typer.echo("shctx: gh CLI not installed; skipping github refresh")
        return 0
    project_id = _project_id()
    if project_id is None:
        return 1
    now = int(time.time())

    rc, out = _gh_retry(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], quiet=True)
    repo = out.rstrip("\n") if rc == 0 else "unknown/unknown"

    try:
        conn = _connect(resolve_db_path())
    except sqlite3.Error as exc:
        typer.echo(f"ERROR: sqlite3: {exc}", err=True)
        return 1
    try:
        # Issues
        rc, rows = _gh_json_rows(
            [
                "issue",
                "list",
                "--state",
                "all",
                "--limit",
                "500",
                "--json",
                "number,title,state,labels,milestone,assignees,body,url,createdAt,updatedAt",
            ]
        )
        if rc != 0:
            return rc
        for row in rows:
            num = row.get("number")
            milestone = (row.get("milestone") or {}).get("title") or ""
            conn.execute(
                "INSERT INTO index_issues "
                "(id, project_id, source, number, title, state, labels, milestone, assignees, "
                "body, url, created_at, updated_at, refreshed_at) "
                "VALUES (?, ?, 'github', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, state=excluded.state, labels=excluded.labels, "
                "milestone=excluded.milestone, assignees=excluded.assignees, body=excluded.body, "
                "url=excluded.url, updated_at=excluded.updated_at, refreshed_at=excluded.refreshed_at",
                (
                    f"github:{repo}#{num}",
                    project_id,
                    num,
                    _jq_r(row.get("title")),
                    _jq_r(row.get("state")).lower(),
                    _compact_names(row.get("labels"), "name"),
                    milestone or "NULL",  # bash quirk: '${milestone:-NULL}' stores the literal string
                    _compact_names(row.get("assignees"), "login"),
                    _jq_r(row.get("body")),
                    _jq_r(row.get("url")),
                    _epoch_iso(_jq_r(row.get("createdAt"))),
                    _epoch_iso(_jq_r(row.get("updatedAt"))),
                    now,
                ),
            )

        # PRs
        rc, rows = _gh_json_rows(
            [
                "pr",
                "list",
                "--state",
                "all",
                "--limit",
                "500",
                "--json",
                "number,title,state,baseRefName,headRefName,labels,url,createdAt,updatedAt,mergedAt",
            ]
        )
        if rc != 0:
            return rc
        for row in rows:
            num = row.get("number")
            merged = row.get("mergedAt") or ""
            conn.execute(
                "INSERT INTO index_prs "
                "(id, project_id, source, number, title, state, base_branch, head_branch, labels, "
                "url, created_at, updated_at, merged_at, refreshed_at) "
                "VALUES (?, ?, 'github', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, state=excluded.state, labels=excluded.labels, "
                "url=excluded.url, updated_at=excluded.updated_at, merged_at=excluded.merged_at, "
                "refreshed_at=excluded.refreshed_at",
                (
                    f"github:{repo}#pr{num}",
                    project_id,
                    num,
                    _jq_r(row.get("title")),
                    _jq_r(row.get("state")).lower(),
                    _jq_r(row.get("baseRefName")),
                    _jq_r(row.get("headRefName")),
                    _compact_names(row.get("labels"), "name"),
                    _jq_r(row.get("url")),
                    _epoch_iso(_jq_r(row.get("createdAt"))),
                    _epoch_iso(_jq_r(row.get("updatedAt"))),
                    _epoch_iso(merged) if merged else None,
                    now,
                ),
            )

        # Releases
        rc, rows = _gh_json_rows(
            ["release", "list", "--limit", "200", "--json", "tagName,name,isDraft,isPrerelease,publishedAt"]
        )
        if rc != 0:
            return rc
        for row in rows:
            tag = _jq_r(row.get("tagName"))
            published = row.get("publishedAt") or ""
            conn.execute(
                "INSERT INTO index_releases "
                "(id, project_id, source, tag, name, prerelease, draft, body, url, published_at, refreshed_at) "
                "VALUES (?, ?, 'github', ?, ?, ?, ?, NULL, ?, ?, ?) "
                "ON CONFLICT(project_id, source, tag) DO UPDATE SET "
                "name=excluded.name, prerelease=excluded.prerelease, draft=excluded.draft, "
                "url=excluded.url, published_at=excluded.published_at, refreshed_at=excluded.refreshed_at",
                (
                    f"github:{repo}:tag:{tag}",
                    project_id,
                    tag,
                    row.get("name") or "",
                    1 if row.get("isPrerelease") else 0,
                    1 if row.get("isDraft") else 0,
                    # gh CLI does not expose `url` on releases; construct it.
                    f"https://github.com/{repo}/releases/tag/{tag}",
                    _epoch_iso(published) if published else None,
                    now,
                ),
            )

        # Milestones (REST API)
        rc, rows = _gh_json_rows(
            ["api", f"repos/{repo}/milestones?state=all&per_page=100"], quiet=True, tolerant=True
        )
        if rc != 0:
            return rc
        for row in rows:
            num = row.get("number")
            due = row.get("due_on") or ""
            conn.execute(
                "INSERT INTO index_milestones "
                "(id, project_id, source, number, title, state, due_on, description, url, refreshed_at) "
                "VALUES (?, ?, 'github', ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, source, number) DO UPDATE SET "
                "title=excluded.title, state=excluded.state, due_on=excluded.due_on, "
                "description=excluded.description, url=excluded.url, refreshed_at=excluded.refreshed_at",
                (
                    f"github:{repo}:ms:{num}",
                    project_id,
                    num,
                    _jq_r(row.get("title")),
                    _jq_r(row.get("state")),
                    _epoch_iso(due) if due else None,
                    row.get("description") or "",
                    _jq_r(row.get("html_url")),
                    now,
                ),
            )
    except sqlite3.Error as exc:
        typer.echo(f"ERROR: sqlite3: {exc}", err=True)
        return 1
    finally:
        conn.close()
    typer.echo("shctx refresh github: ok")
    return 0


# --------------------------------------------------------------------------
# artifacts — port of refresh-artifacts.sh (markdown classifier + upsert).
# --------------------------------------------------------------------------

#: ``classify()``'s suffix arms, in bash's exact case-statement order —
#: dot-separated kind suffix (primary) and hyphen-prefixed kind suffix
#: (fallback) per arm, checked BEFORE the directory arms.
_ARTIFACT_KIND_SUFFIXES: tuple[tuple[str, tuple[str, str]], ...] = (
    ("seed", (".seed.md", "-seed.md")),
    ("plan", (".plan.md", "-plan.md")),
    ("phase0", (".phase0.md", "-phase0.md")),
    ("close", (".close.md", "-close.md")),
    ("walk", (".walk.md", "-walk.md")),
    ("handoff", (".handoff.md", "-handoff.md")),
    ("spec", (".spec.md", "-spec.md")),
    ("design", (".design.md", "-design.md")),
    ("addendum", (".addendum.md", "-addendum.md")),
)

#: Byte cap for persisted artifact content (bash: ``head -c 262144``).
_ARTIFACT_CONTENT_CAP = 262144

_TITLE_HASHES_RE = re.compile(r"^#+ ")


def _classify_artifact(path: str) -> str:
    """Classify one markdown file's artifact kind, bash-parity with ``classify()``.

    Args:
        path: The file's (absolute) path — bash matched the full ``find``
            path against its case patterns.

    Returns:
        The kind string, or ``""`` for an unclassified file (skipped by
        the caller).
    """
    for kind, suffixes in _ARTIFACT_KIND_SUFFIXES:
        if path.endswith(suffixes):
            return kind
    if "/docs/diagrams/" in path:
        return "diagram"
    if "/docs/journal/" in path:
        return "journal"
    return ""


def _artifact_title(data: bytes) -> str:
    """Derive the stored title from a file's first line, bash-parity with the head/sed pipe.

    Bash: ``head -1 "$f" | sed -E 's/^#+ //;s/'\\''/''/g' | head -c 200`` —
    which (after shell dequoting) strips one leading ``#+ `` heading marker,
    REMOVES every single quote (the ``s/'//g`` quirk, verified against the
    real script), and truncates to 200 BYTES.

    Args:
        data: The file's full raw content.

    Returns:
        The derived title string (possibly empty).
    """
    first_line = data.split(b"\n", 1)[0].decode("utf-8", errors="replace")
    title = _TITLE_HASHES_RE.sub("", first_line, count=1)
    title = title.replace("'", "")
    return title.encode("utf-8")[:200].decode("utf-8", errors="ignore")


def _markdown_files(root: str) -> list[str]:
    """Every ``*.md`` file under ``root``, bash-parity with ``find "$root" -name '*.md'``.

    Args:
        root: The namespace directory (may not exist — bash's ``find``
            failure yielded zero iterations).

    Returns:
        Absolute paths, sorted for determinism.
    """
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            if filename.endswith(".md"):
                files.append(os.path.join(dirpath, filename))
    return files


def refresh_artifacts() -> int:
    """Rebuild the markdown artifact index — native port of ``refresh-artifacts.sh``.

    Scans ``resolve_workdir()`` for ``*.md`` files, classifies each via
    :func:`_classify_artifact`, and upserts one ``artifacts`` row per
    classified file — persisting full content (capped at
    :data:`_ARTIFACT_CONTENT_CAP` bytes) when the schema has the
    ``artifacts.content`` column (migration ``0004_fts_search.sql``),
    exactly like bash's ``has_content_col`` probe.

    Returns:
        0 after printing ``"shctx refresh artifacts: ok"``; 1 on a
        missing/unparseable ``project.json``, an unreadable file (bash: a
        failing ``shasum`` command substitution aborts under ``set -e``),
        or a sqlite failure — error already printed to stderr.
    """
    project_id = _project_id()
    if project_id is None:
        return 1
    now = int(time.time())
    root = resolve_workdir()
    repo_root = resolve_repo_root()

    try:
        conn = _connect(resolve_db_path())
    except sqlite3.Error as exc:
        typer.echo(f"ERROR: sqlite3: {exc}", err=True)
        return 1
    try:
        has_content_col = any(
            info[1] == "content" for info in conn.execute("PRAGMA table_info(artifacts)")
        )
        for path in _markdown_files(root):
            rel = _strip_repo_prefix(path, repo_root)
            kind = _classify_artifact(path)
            if not kind:
                continue
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError as exc:
                typer.echo(f"ERROR: failed to read {path}: {exc}", err=True)
                return 1
            digest = hashlib.sha256(data).hexdigest()
            title = _artifact_title(data)
            if has_content_col:
                # bash: content=$(head -c 262144 "$f" | ...) — command
                # substitution strips ALL trailing newlines; reproduce that.
                content = data[:_ARTIFACT_CONTENT_CAP].decode("utf-8", errors="replace").rstrip("\n")
                conn.execute(
                    "INSERT INTO artifacts "
                    "(id, project_id, kind, path, sprint_branch, title, hash, content, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(project_id, path) DO UPDATE SET "
                    "kind=excluded.kind, title=excluded.title, hash=excluded.hash, "
                    "content=excluded.content, updated_at=excluded.updated_at",
                    (_uuid7(), project_id, kind, rel, title, digest, content, now, now),
                )
            else:
                conn.execute(
                    "INSERT INTO artifacts "
                    "(id, project_id, kind, path, sprint_branch, title, hash, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?) "
                    "ON CONFLICT(project_id, path) DO UPDATE SET "
                    "kind=excluded.kind, title=excluded.title, hash=excluded.hash, "
                    "updated_at=excluded.updated_at",
                    (_uuid7(), project_id, kind, rel, title, digest, now, now),
                )
    except sqlite3.Error as exc:
        typer.echo(f"ERROR: sqlite3: {exc}", err=True)
        return 1
    finally:
        conn.close()
    typer.echo("shctx refresh artifacts: ok")
    return 0


__all__ = ["refresh_symbols", "refresh_github", "refresh_artifacts"]
