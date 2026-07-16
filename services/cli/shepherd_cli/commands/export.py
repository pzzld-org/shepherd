"""``shepherd export`` — canned-export-to-markdown Typer sub-app.

Bash parity target: ``skills/context/scripts/cmd_export.sh``
(``shctx export <kind> [--out=<path>] [--all]``). Bash's own
implementation is a thin orchestrator: each ``<kind>`` shells out to
either ``cmd_query.sh <name> --md`` (a canned ``.sql`` file under
``skills/context/queries/``) or ``cmd_mem.sh list`` (a hand-written
``mem_entries`` query rendered via ``sqlite3 -header -column``), then
either prints the result or writes it to ``--out``. ``--all`` bundles
every supported kind into a directory, one ``<kind>.md`` file each.

This module is deliberately self-contained (Pydantic-free — every kind
here is a raw ``.sql``/table query, not a typed row shape worth modeling)
per the port's disjoint-file-ownership contract: it duplicates a few
small helpers already present in :mod:`shepherd_cli.commands.query`
(``_find_queries_dir``, ``_render_markdown``, the ``project.json``
project-id reader) and :mod:`shepherd_cli.commands.mem`
(``_render_sqlite_table``'s ``-column`` rendering) rather than importing
their private names across sibling command modules — see each helper's
own docstring below for why.

No new Tortoise model module: hard rule #8 applies six times over.
``canonical-types``/``open-issues``/``open-prs``/``recent-releases``/
``drift-risk`` byte-load the SAME ``skills/context/queries/<name>.sql``
files ``cmd_query.sh`` does (so a query edit there is picked up here too,
with zero drift risk) and bind ``:project_id`` the same way; ``mem``
mirrors ``cmd_mem.sh list``'s literal ``SELECT`` text. All six run
through Tortoise's raw connection (``conn.execute_query_dict``), never
the ORM.

Two representations of a kind's output matter for exact bash parity, and
this module keeps them explicitly separate:

* **"raw stdout"** — exactly the bytes ``bash cmd_query.sh <name> --md``
  (or ``cmd_mem.sh list``) would write to its own stdout: a rendered
  table with ONE natural trailing newline, or ZERO bytes for a
  zero-row result (verified empirically against ``sqlite3 -header
  -markdown``/``-column`` — see :func:`_run_canned_query_stdout` and
  :func:`_run_mem_list_stdout`). ``--all`` mode writes this
  representation directly to ``<bundle_dir>/<kind>.md``, unmodified —
  matching bash's direct ``emit_one "$k" > "$f"`` redirect. A
  zero-row kind therefore produces a genuinely empty (0-byte) file.
* **single-kind "data"** — bash's ``data=$(emit_one "$kind")`` STRIPS
  every trailing newline via command substitution, then
  ``printf '%s\\n' "$data"`` re-adds exactly ONE, regardless of whether
  ``$data`` was empty. So single-kind mode (to stdout or to ``--out``)
  ALWAYS ends with exactly one trailing newline, even for a zero-row
  result (which prints/writes a single blank line, NOT zero bytes) —
  the opposite of ``--all``'s zero-byte-file behavior for the same
  input. :func:`_run_single` reproduces this by
  ``raw_stdout.rstrip("\\n")`` then re-adding one newline unconditionally
  (``typer.echo`` / an explicit ``"\\n"`` on file write both do this for
  free).

Failure-mode parity (bash's per-kind ``case`` in ``emit_one``) is
likewise kept exact:

* ``canonical-types`` and ``open-issues`` have NO bash fallback — a
  failure (missing ``project.json``, an unknown query file, a query
  error) propagates. In single-kind mode this means ``shctx export``
  exits 1 with the underlying error on stderr; in ``--all`` mode the
  OUTER ``2>/dev/null`` + ``if/else`` in ``cmd_export.sh`` catches it
  too, printing ``skip <kind> (unavailable)`` instead of aborting the
  whole bundle.
* ``open-prs``, ``recent-releases``, ``drift-risk``, and ``mem`` each
  have their OWN bash fallback (``2>/dev/null || echo "# (... query
  unavailable)"`` / ``"# (no memories)"``) — any failure for these
  kinds is swallowed at the ``emit_one`` level itself and NEVER
  propagates, in EITHER mode; ``--all`` therefore always reports
  ``wrote <bundle_dir>/<kind>.md`` for these four kinds (containing the
  fallback text), never ``skip``.

Argument parsing mirrors ``cmd_export.sh``'s positional-then-flags loop
line for line, including a genuine bash quirk worth flagging explicitly:
``-h``/``--help`` is only recognized as a FLAG when it appears at
position 2+ (``shctx export <kind> -h``) — as the very FIRST token
(``shctx export -h``), it is consumed as ``$1`` (the ``<kind>`` value)
by the script's own ``kind="${1:-}"; ...; shift`` dispatch BEFORE the
flag-scanning loop ever runs, so it instead reaches ``emit_one`` as an
(invalid) kind name and prints ``ERROR: unknown export kind: -h`` on
exit 1 — it does NOT print help. See :func:`_parse_args`.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import typer
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.resolution import resolve_repo_root, resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Mirrors shepherd_cli.commands.query's context_settings: `<kind>` and
    # `all` are plain positional tokens (not flags), and Click's Group
    # dispatch would otherwise try to resolve them as subcommand names.
    # allow_extra_args/ignore_unknown_options let everything flow into the
    # single variadic `raw` argument below, split apart by _parse_args.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Export a canned query/report kind to markdown (single kind, or --all to bundle every kind).",
)

#: Verbatim bash help text (`cmd_export.sh`'s `-h|--help` heredoc), byte-for-byte,
#: INCLUDING the doc bug it ships with: `search-symbols` is listed as a valid
#: `<kind>` here but `emit_one` has no case for it (falls through to "unknown
#: export kind"). Preserved as-is per the port's bash-parity mandate — not a
#: bug this port is allowed to silently fix.
_HELP_TEXT = """shctx export <kind> [--out=<path>]
shctx export --all   [--out=<dir>]
shctx export all     [--out=<dir>]

  <kind>     canonical-types | open-issues | open-prs | recent-releases
             | drift-risk | search-symbols | mem
  --out      output path (file for single kind, dir for --all)
  --all      bundle every supported export kind to a directory"""

#: The six kinds `cmd_export.sh`'s `--all` bundle loop actually iterates
#: (`for k in canonical-types open-issues open-prs recent-releases drift-risk mem`),
#: in that exact order — this is the real supported-kind list; `_HELP_TEXT`'s
#: `search-symbols` mention above is not part of it (see the module docstring).
_ALL_KINDS: tuple[str, ...] = ("canonical-types", "open-issues", "open-prs", "recent-releases", "drift-risk", "mem")

#: Relative path from a plugin/repo root to the canned-queries directory —
#: duplicated from shepherd_cli.commands.query's `_QUERIES_RELPATH` (that
#: module's helper is private and this port does not import across sibling
#: command modules; see the module docstring).
_QUERIES_RELPATH = os.path.join("skills", "context", "queries")

#: sqlite3 CLI's own `-column` mode gutter (verified empirically against
#: sqlite3 3.45.1 — two literal spaces between every column, including
#: before the last one), matching mem.py's `_COLUMN_GUTTER` constant.
_MEM_COLUMN_GUTTER = "  "

#: Two-space-padded markdown pipe-table gutter, matching query.py's
#: `_COLUMN_GUTTER` constant (this module's `_render_markdown` twin).
_MD_COLUMN_GUTTER = " | "


class ExportKindError(Exception):
    """Raised for an unrecognized ``<kind>`` — bash: ``ERROR: unknown export kind: <k>``."""


class ExportQueryError(Exception):
    """Raised when resolving the project id or running a kind's query fails.

    Carries the bash-parity stderr message as its sole argument (matching
    ``_lib.sh``'s ``shctx_project_id``/``cmd_query.sh``'s own ``ERROR: ...``
    lines, which flow straight through to ``cmd_export.sh``'s stderr since
    ``data=$(emit_one "$kind")`` only captures stdout).
    """


# --------------------------------------------------------------------------
# Small stdlib helpers (duplicated intentionally — see module docstring).
# --------------------------------------------------------------------------
def _find_queries_dir() -> str | None:
    """Locate the canned-queries directory (``skills/context/queries``).

    Duplicate of :mod:`shepherd_cli.commands.query`'s private
    ``_find_queries_dir`` (same ``CLAUDE_PLUGIN_ROOT``-first, then
    walk-up-from-repo-root resolution as every other ``find_*`` helper in
    :mod:`shepherd_cli.resolution`) — not imported across sibling command
    modules per the disjoint-file-ownership rule.

    Returns:
        The queries directory path, or None if it cannot be found via
        ``CLAUDE_PLUGIN_ROOT`` nor anywhere on the walk up from the repo
        root.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidate = os.path.join(plugin_root, _QUERIES_RELPATH)
        if os.path.isdir(candidate):
            return candidate

    current = resolve_repo_root()
    while True:
        candidate = os.path.join(current, _QUERIES_RELPATH)
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _resolve_project_id() -> str:
    """Resolve the active project id, bash-parity with ``_lib.sh``'s ``shctx_project_id``.

    Every kind this module exports resolves its project id the SAME way
    bash does: reading the ``"id"`` key out of the ``project.json`` FILE
    in the resolved shepherd work directory (``jq -r '.id' "$(shctx_project_id_path)"``)
    — a file, not the ``projects`` table. ``cmd_query.sh`` (which
    ``canonical-types``/``open-issues``/``open-prs``/``recent-releases``/
    ``drift-risk`` shell out to) and ``cmd_mem.sh`` (which ``mem`` shells
    out to) BOTH call ``shctx_project_id()`` unconditionally at their own
    top, so this is not a per-kind deviation — every kind shares this one
    resolution path, matching bash's actual call graph.

    Returns:
        The project id string (or the literal three-character string
        ``"null"`` if ``project.json``'s ``"id"`` key is present-but-null
        or the file's top level isn't an object — jq -r's own rendering
        of JSON ``null``, reproduced here for parity).

    Raises:
        ExportQueryError: With bash's exact stderr message
            (``"ERROR: <path> missing — run 'shctx init' first"``) if
            ``project.json`` does not exist. Also raised (with an
            equivalent, but not byte-identical, message — bash's ``jq``
            would instead abort with jq's own parse-error text) if the
            file exists but is not valid JSON.
    """
    path = os.path.join(resolve_workdir(), "project.json")
    if not os.path.isfile(path):
        raise ExportQueryError(f"ERROR: {path} missing — run 'shctx init' first")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ExportQueryError(f"ERROR: failed to parse {path} as JSON") from exc
    raw_id = data.get("id") if isinstance(data, dict) else None
    return "null" if raw_id is None else str(raw_id)


def _render_markdown(rows: list[dict[str, object]]) -> str:
    """Render rows as a left-justified GitHub-flavored markdown pipe table.

    Duplicate of :mod:`shepherd_cli.commands.query`'s private
    ``_render_markdown`` (same left-justified-everywhere approximation of
    ``sqlite3 -header -markdown``, which centers header text instead —
    see that module's docstring for the full deviation note). Not
    imported across sibling command modules per the disjoint-file-
    ownership rule.

    Args:
        rows: Query result rows, each a ``{column: value}`` dict in
            column-select order.

    Returns:
        The rendered table (header, separator, one line per row; no
        trailing newline). Callers must special-case an empty ``rows``
        themselves — there is no header-only rendering, matching
        ``sqlite3 -header -markdown`` printing zero bytes for zero rows.
    """
    columns = list(rows[0].keys())

    def cell(value: object) -> str:
        return "" if value is None else str(value)

    str_rows = [[cell(row[column]) for column in columns] for row in rows]
    widths = [len(column) for column in columns]
    for str_row in str_rows:
        for index, value in enumerate(str_row):
            widths[index] = max(widths[index], len(value))

    def render_row(cells: list[str]) -> str:
        return "| " + _MD_COLUMN_GUTTER.join(cell.ljust(width) for cell, width in zip(cells, widths, strict=True)) + " |"

    header = render_row(columns)
    separator = "|" + "|".join("-" * (width + 2) for width in widths) + "|"
    body = [render_row(str_row) for str_row in str_rows]
    return "\n".join([header, separator, *body])


def _render_column_table(columns: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    """Render rows exactly as sqlite3 CLI's ``-header -column`` mode would.

    Duplicate of :mod:`shepherd_cli.commands.mem`'s private
    ``_render_sqlite_table`` (same column-width/gutter/separator rules,
    verified empirically against sqlite3 3.45.1) — used for the ``mem``
    kind, which mirrors ``cmd_mem.sh list``'s own ``sqlite3 -header
    -column`` rendering (NOT the markdown format every other kind uses).
    Not imported across sibling command modules per the disjoint-file-
    ownership rule.

    Args:
        columns: Column header names, in display order.
        rows: Each row's cells, already stringified, in the same column
            order as ``columns``.

    Returns:
        The rendered table (no trailing newline), or ``""`` if ``rows``
        is empty (sqlite3 prints not even the header for zero rows).
    """
    if not rows:
        return ""
    widths = [len(column) for column in columns]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    header = _MEM_COLUMN_GUTTER.join(column.ljust(width) for column, width in zip(columns, widths, strict=True))
    separator = _MEM_COLUMN_GUTTER.join("-" * width for width in widths)
    body_lines = [
        _MEM_COLUMN_GUTTER.join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)) for row in rows
    ]
    return "\n".join([header, separator, *body_lines])


# --------------------------------------------------------------------------
# Inline async data layer.
# --------------------------------------------------------------------------
async def _run_canned_query_stdout(name: str) -> str:
    """Load, bind, run, and render one ``skills/context/queries/<name>.sql`` file.

    Byte-loads the SAME ``.sql`` file ``cmd_query.sh <name> --md`` reads
    (so this tracks any future edit to that file with zero drift risk),
    substitutes the sole ``:project_id`` token every one of the five
    canned queries this module uses actually contains (verified by
    inspection — none of ``canonical-types``/``open-issues``/
    ``open-prs``/``recent-releases``/``drift-risk``'s ``.sql`` text uses
    any OTHER ``:token``, so the general-purpose NULL-fill pass
    :mod:`shepherd_cli.commands.query` needs for arbitrary canned queries
    has no equivalent here), then runs the bound SQL as ONE statement via
    Tortoise's raw connection.

    Args:
        name: The query's base filename (without ``.sql``) — one of
            ``canonical-types``, ``open-issues``, ``open-prs``,
            ``recent-releases``, ``drift-risk``.

    Returns:
        The "raw stdout" representation described in the module
        docstring: the rendered markdown table plus exactly ONE trailing
        newline, or the empty string (zero bytes) if the query matched
        zero rows.

    Raises:
        ExportQueryError: If ``project.json`` is missing/unparseable
            (via :func:`_resolve_project_id`), if
            ``<queries_dir>/<name>.sql`` cannot be found, or if the bound
            SQL statement itself raises.
    """
    project_id = _resolve_project_id()
    queries_dir = _find_queries_dir()
    sql_path = os.path.join(queries_dir, f"{name}.sql") if queries_dir is not None else None
    if sql_path is None or not os.path.isfile(sql_path):
        raise ExportQueryError(f"ERROR: query not found: {name}")
    with open(sql_path, encoding="utf-8") as fh:
        sql_text = fh.read()
    bound_sql = sql_text.replace(":project_id", f"'{project_id}'")

    connection = Tortoise.get_connection("default")
    try:
        rows = await connection.execute_query_dict(bound_sql)
    except Exception as exc:  # noqa: BLE001 - mirrors bash's blanket "the sqlite3 invocation failed"
        raise ExportQueryError(f"ERROR: query failed: {exc}") from exc

    if not rows:
        return ""  # bash-parity: sqlite3 -header -markdown -> zero bytes for zero rows.
    return _render_markdown(rows) + "\n"


async def _run_mem_list_stdout() -> str:
    """Run ``cmd_mem.sh list``'s exact query and render it sqlite3-``-column``-style.

    Bash: ``SELECT id, kind, title, pinned, created_at FROM mem_entries
    WHERE project_id='$project_id' ORDER BY pinned DESC, created_at
    DESC;`` piped through ``sqlite3 -header -column``. This runs the same
    ``SELECT`` (parameter-bound rather than string-interpolated — an
    unobservable difference for a project id, which is never
    user-adversarial input in this flow) and renders it with
    :func:`_render_column_table`, matching bash's column format rather
    than the markdown format every OTHER export kind uses (a deliberate
    ``cmd_export.sh`` inconsistency this port reproduces, not fixes).

    Returns:
        The "raw stdout" representation: the rendered column table plus
        exactly ONE trailing newline, or the empty string (zero bytes)
        if the project has zero ``mem_entries`` rows.

    Raises:
        ExportQueryError: If ``project.json`` is missing/unparseable
            (via :func:`_resolve_project_id`).
        Exception: Any Tortoise/sqlite error from the query itself
            (propagated as-is — the ``mem`` branch of :func:`_emit_raw`
            catches broadly, matching bash's ``2>/dev/null || echo``).
    """
    project_id = _resolve_project_id()
    connection = Tortoise.get_connection("default")
    rows = await connection.execute_query_dict(
        "SELECT id, kind, title, pinned, created_at FROM mem_entries "
        "WHERE project_id=? ORDER BY pinned DESC, created_at DESC",
        [project_id],
    )
    if not rows:
        return ""  # bash-parity: sqlite3 -header -column -> zero bytes for zero rows.
    table = _render_column_table(
        ("id", "kind", "title", "pinned", "created_at"),
        [(row["id"], row["kind"], row["title"], str(row["pinned"]), str(row["created_at"])) for row in rows],
    )
    return table + "\n"


async def _emit_raw(kind: str) -> str:
    """Bash-parity twin of ``cmd_export.sh``'s ``emit_one`` function.

    Dispatches on ``kind`` exactly like bash's ``case`` statement,
    including which kinds propagate a failure (``canonical-types``,
    ``open-issues`` — no bash fallback) versus which kinds swallow one
    into a fixed fallback string (``open-prs``, ``recent-releases``,
    ``drift-risk``, ``mem`` — each has its own ``2>/dev/null || echo
    "..."`` in bash). See the module docstring's "Failure-mode parity"
    section for the full contract and why it matters for both
    single-kind exit codes and ``--all``'s per-kind wrote/skip lines.

    Args:
        kind: One of :data:`_ALL_KINDS`, or an arbitrary caller-supplied
            string (single-kind mode only — ``--all`` mode only ever
            calls this with a member of :data:`_ALL_KINDS`).

    Returns:
        The "raw stdout" representation for ``kind`` (see the module
        docstring) — either the real query output or, for the four
        fallback-bearing kinds, the fixed ``"# (... unavailable)"`` /
        ``"# (no memories)"`` text plus one trailing newline.

    Raises:
        ExportKindError: If ``kind`` is not one of the six known kinds
            (bash: ``ERROR: unknown export kind: <k>``) — note this
            includes ``search-symbols``, despite it being listed as a
            valid ``<kind>`` in ``_HELP_TEXT``; see the module docstring.
        ExportQueryError: Propagated, unmodified, only for
            ``canonical-types``/``open-issues``.
    """
    if kind == "canonical-types":
        return await _run_canned_query_stdout("canonical-types")
    if kind == "open-issues":
        return await _run_canned_query_stdout("open-issues")
    if kind == "open-prs":
        try:
            return await _run_canned_query_stdout("open-prs")
        except Exception:  # noqa: BLE001 - bash: `... 2>/dev/null || echo "# (open-prs query unavailable)"`
            return "# (open-prs query unavailable)\n"
    if kind == "recent-releases":
        try:
            return await _run_canned_query_stdout("recent-releases")
        except Exception:  # noqa: BLE001 - bash: `... 2>/dev/null || echo "# (recent-releases query unavailable)"`
            return "# (recent-releases query unavailable)\n"
    if kind == "drift-risk":
        try:
            return await _run_canned_query_stdout("drift-risk")
        except Exception:  # noqa: BLE001 - bash: `... 2>/dev/null || echo "# (drift-risk query unavailable)"`
            return "# (drift-risk query unavailable)\n"
    if kind == "mem":
        try:
            return await _run_mem_list_stdout()
        except Exception:  # noqa: BLE001 - bash: `cmd_mem.sh list 2>/dev/null || echo "# (no memories)"`
            return "# (no memories)\n"
    raise ExportKindError(f"ERROR: unknown export kind: {kind}")


# --------------------------------------------------------------------------
# Argument parsing (bash-parity port of cmd_export.sh's positional loop).
# --------------------------------------------------------------------------
def _parse_args(argv: list[str]) -> tuple[str, bool, str]:
    """Parse ``shctx export``'s arguments, mirroring ``cmd_export.sh`` line for line.

    Bash::

        kind="${1:-}"; all=0; out=""
        if [[ "$kind" == "--all" ]]; then all=1; kind="all"; shift
        elif [[ "$kind" == "all" ]]; then all=1; shift
        else shift || true
        fi
        for a in "$@"; do
          case "$a" in
            --out=*) out="${a#--out=}" ;;
            --all)   all=1; kind="all" ;;
            -h|--help) print help; exit 0 ;;
          esac
        done

    Two bash quirks this reproduces exactly, both load-bearing for
    parity (see the module docstring's final section for the first):

    1. ``-h``/``--help`` is a recognized flag ONLY from the second token
       onward — as the very first token it is consumed as ``kind``
       itself (then shifted away) before the flag-scanning loop ever
       sees it, so ``shepherd export -h`` (bare) does NOT print help; it
       falls through to :func:`_emit_raw` as an unrecognized kind named
       ``"-h"``.
    2. The flag-scanning loop has NO catch-all ``*)`` case — any token
       that is neither ``--out=...``, ``--all``, ``-h``, nor ``--help``
       is silently ignored (not an error), and processing continues with
       the next token. A ``--out=`` set before a later ``-h``/``--help``
       IS honored (loop order matters) but never gets a chance to matter
       for a *later* ``--all``/``--out=`` occurring after ``-h`` — the
       loop exits (help + code-0) the instant it reaches ``-h``.

    Args:
        argv: Every token given to ``shepherd export`` after the command
            name itself, in order.

    Returns:
        ``(kind, all_flag, out)`` when no ``-h``/``--help`` flag was
        encountered — ``kind`` is ``"all"`` when ``all_flag`` is True
        (bash reassigns ``kind`` alongside ``all`` in both places that
        set it), ``out`` is ``""`` if ``--out=`` was never given (last
        occurrence wins if given more than once, matching bash's plain
        variable reassignment).

    Raises:
        typer.Exit: Code 0, after printing :data:`_HELP_TEXT` to stdout,
            the instant an ``-h``/``--help`` token is reached in the
            flag-scanning loop (never for a bare ``-h``/``--help`` as
            the very first token — see quirk 1 above).
    """
    kind = argv[0] if argv else ""
    all_flag = False
    if kind == "--all":
        all_flag = True
        kind = "all"
        rest = argv[1:]
    elif kind == "all":
        all_flag = True
        rest = argv[1:]
    else:
        rest = argv[1:] if argv else argv  # `shift || true` — safe no-op when argv is already empty.

    out = ""
    for token in rest:
        if token.startswith("--out="):
            out = token[len("--out="):]
        elif token == "--all":
            all_flag = True
            kind = "all"
        elif token in ("-h", "--help"):
            typer.echo(_HELP_TEXT)
            raise typer.Exit(code=0)
        # else: silently ignored — bash's case statement has no `*)` branch.
    return kind, all_flag, out


# --------------------------------------------------------------------------
# Async command implementations.
# --------------------------------------------------------------------------
def _default_bundle_dir() -> str:
    """The default ``--all`` bundle directory when ``--out`` is not given.

    Bash: ``"${out:-$(shctx_artifacts_root)/exports/$(date +%Y-%m-%dT%H-%M-%S)}"``
    — ``shctx_artifacts_root`` is ``_lib.sh``'s delegate to
    ``resolve_workdir`` (mirrored here by
    :func:`shepherd_cli.resolution.resolve_workdir`), and the timestamp
    is the local wall-clock time, second precision, in
    ``YYYY-MM-DDTHH-MM-SS`` form (colon-free so it's a valid path
    component on every OS bash's own ``date`` invocation targets).

    Returns:
        ``<workdir>/exports/<local-timestamp>``.
    """
    timestamp = time.strftime("%Y-%m-%dT%H-%M-%S")
    return os.path.join(resolve_workdir(), "exports", timestamp)


async def _run_single(kind: str, out: str) -> None:
    """Export exactly one kind — bash's non-``--all`` branch.

    Args:
        kind: The export kind (bash-parity: required, non-empty).
        out: The ``--out=<path>`` value, or ``""`` if not given (prints
            to stdout instead of writing a file).

    Raises:
        typer.Exit: Code 1, with bash's exact stderr message
            (``"ERROR: kind required (or pass --all)"``), if ``kind`` is
            empty. Also code 1, with the underlying
            :class:`ExportKindError`/:class:`ExportQueryError` message on
            stderr, if :func:`_emit_raw` raises (only possible for
            ``canonical-types``, ``open-issues``, or an unrecognized
            kind — see the module docstring). Also code 1 if ``--out``
            names a path that cannot be written (e.g. its parent
            directory doesn't exist) — bash: an unredirectable ``>``
            target aborts the script under ``set -e``; the exact stderr
            text is a Python ``OSError`` message here rather than bash's
            own redirection-failure text (a documented, unavoidable
            deviation from shelling out).
    """
    if not kind:
        typer.echo("ERROR: kind required (or pass --all)", err=True)
        raise typer.Exit(code=1)

    try:
        raw_stdout = await _emit_raw(kind)
    except (ExportKindError, ExportQueryError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    # Bash: `data=$(emit_one "$kind")` strips every trailing newline via
    # command substitution; `printf '%s\n' "$data"` (to stdout or --out)
    # then re-adds exactly one, unconditionally — see the module docstring.
    data = raw_stdout.rstrip("\n")

    if out:
        try:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(data + "\n")
        except OSError as exc:
            typer.echo(f"ERROR: could not write {out}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"wrote {out}")
    else:
        typer.echo(data)


async def _run_all(out: str) -> None:
    """Bundle every export kind into a directory — bash's ``--all`` branch.

    Args:
        out: The ``--out=<dir>`` value, or ``""`` to use
            :func:`_default_bundle_dir`.

    Raises:
        typer.Exit: Code 1 if the bundle directory cannot be created
            (bash: ``mkdir -p "$bundle_dir"`` failing aborts the script
            under ``set -e``). Never raised for an individual kind's
            failure — those are caught per-kind and reported as a
            ``skip <kind> (unavailable)`` line, exactly like bash's outer
            ``if emit_one "$k" > "$f" 2>/dev/null; then ... else rm -f
            "$f"; echo "skip $k (unavailable)"; fi``.
    """
    bundle_dir = out if out else _default_bundle_dir()
    try:
        os.makedirs(bundle_dir, exist_ok=True)
    except OSError as exc:
        typer.echo(f"ERROR: could not create {bundle_dir}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for kind in _ALL_KINDS:
        target = os.path.join(bundle_dir, f"{kind}.md")
        try:
            content = await _emit_raw(kind)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(content)
        except Exception:  # noqa: BLE001 - bash: `if emit_one "$k" > "$f" 2>/dev/null; then ... else ...`
            if os.path.exists(target):
                os.remove(target)
            typer.echo(f"skip {kind} (unavailable)")
            continue
        typer.echo(f"wrote {target}")

    typer.echo(f"shctx export --all: bundle at {bundle_dir}")


async def _export_async(kind: str, all_flag: bool, out: str) -> None:
    """Top-level async dispatch, wrapping every query in one DB lifespan.

    Args:
        kind: The resolved export kind (``"all"`` when ``all_flag`` is
            True, per :func:`_parse_args`'s contract).
        all_flag: Whether ``--all``/``all`` was given.
        out: The ``--out=<path-or-dir>`` value, or ``""``.
    """
    async with db.lifespan():
        if all_flag:
            await _run_all(out)
        else:
            await _run_single(kind, out)


# --------------------------------------------------------------------------
# Typer command.
# --------------------------------------------------------------------------
@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    raw: list[str] = typer.Argument(
        None,
        metavar="[KIND|--all|all] [--out=<path>] [-h|--help]",
        help=(
            "Export kind (canonical-types|open-issues|open-prs|recent-releases|"
            "drift-risk|mem), or --all/all to bundle every kind to a directory."
        ),
    ),
) -> None:
    """Export a canned query/report kind to markdown.

    Native port of ``shctx export`` (``cmd_export.sh``). Takes the export
    kind as its first token (or ``--all``/``all`` to bundle every kind),
    then any mix of ``--out=<path>`` and ``-h``/``--help`` — captured
    together as one variadic argument (see the module-level
    ``context_settings`` comment for why) and split apart in
    :func:`_parse_args`, which also handles the bash ``-h``-as-first-
    token quirk documented there.

    Args:
        ctx: The Typer/Click context (unused directly; required so
            ``invoke_without_command`` dispatch works like every other
            single-verb group in this package).
        raw: ``[kind, *flags]``, or None/empty if no arguments were given
            at all — bash-parity with a bare ``shctx export`` (exits 1,
            ``"ERROR: kind required (or pass --all)"``).
    """
    del ctx  # required by invoke_without_command dispatch; unused otherwise.
    argv = list(raw) if raw else []
    kind, all_flag, out = _parse_args(argv)
    asyncio.run(_export_async(kind=kind, all_flag=all_flag, out=out))


__all__ = ["app"]
