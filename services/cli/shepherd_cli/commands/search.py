"""``shepherd search`` — FTS5 full-text search over symbols and artifacts.

Native port of ``skills/context/scripts/cmd_search.sh``: a single verb,
``shctx search <text> [--scope=symbols|artifacts|all] [--all] [--limit=N]
[--md|--json]``, that runs a SQLite FTS5 ``MATCH`` query against
``index_fts_symbols`` (backing ``index_symbols``) and/or
``index_fts_artifacts`` (backing ``artifacts``) — the two virtual tables
migration ``0004_fts_search.sql`` creates — and prints the ranked hits
either as markdown (default) or JSON.

This is a raw-SQL port by design (hard rule #8), like
:mod:`shepherd_cli.commands.query`: FTS5 ``MATCH``/``bm25()``/``snippet()``
are SQLite-specific virtual-table functions with no ORM equivalent, and
``cmd_search.sh``'s two queries are short enough that mirroring them
byte-for-byte as parameterized raw SQL (via
``Tortoise.get_connection("default").execute_query_dict``) is both
simpler and more faithful than reimplementing FTS5 ranking through the
ORM. No Tortoise model is declared in this module or in a sibling
``models_search.py`` — nothing here reads or writes a table through the
ORM; :class:`shepherd_cli.models_status.IndexSymbol` and
:class:`shepherd_cli.models_status.Artifact` already mirror the two base
(non-virtual) tables for OTHER commands (``shepherd status``), but this
module never imports them, since every column this command needs is
fetched directly off the raw connection instead.

Project-id resolution deliberately does NOT follow
:mod:`shepherd_cli.commands.mem`'s "read the ``projects`` table" deviation.
``cmd_search.sh`` calls ``shctx_project_id()`` unconditionally BEFORE ever
opening a database connection (it reads ``<workdir>/project.json`` via
``jq``, entirely off the filesystem) — mirroring
:mod:`shepherd_cli.commands.query`'s ``_read_project_id`` instead, for the
same reason ``query.py`` gives: this command's bash source resolves
``project_id`` from the file, not the table, so filesystem-based
resolution is the truer parity target. :func:`_read_project_id` is
duplicated locally (not imported from ``query.py``) because both modules
are self-contained per the port's instructions and
:mod:`shepherd_cli.resolution` (the one shared module both may import) has
no project-id helper of its own.

Bash parity notes worth flagging up front (all preserved deliberately, not
"fixed"):

* The FTS5-tables-missing guard (``index_fts_symbols`` absent from
  ``sqlite_master`` — a project whose DB predates migration 0004) exits
  with code **2**, distinct from every other validation failure in this
  command, which exits 1. This is preserved exactly; do not conflate the
  two exit codes.
* ``--json`` output is built by hand (:func:`_render_json`), NOT
  ``json.dumps``, because ``cmd_search.sh``'s own ``emit_json`` is
  deliberately (if inconsistently) escaped: ``title``/``context`` string
  values have embedded ``"`` doubled to ``\\"`` (bash: ``sed
  's/"/\\"/g'``), but ``package``/``kind``/``name``/``file``/``path``/
  ``branch`` do not get ANY escaping at all — a value containing a
  literal ``"`` in one of those fields would silently corrupt the JSON in
  the original bash tool, and this port reproduces that exact quirk
  rather than silently fixing it out from under bash-parity callers. See
  :func:`_json_escape_quotes` and :func:`_render_json`'s docstring.
* ``line`` renders as a bare (unquoted) JSON ``null`` when the symbol's
  ``line`` column is NULL (bash: ``${line:-null}``), and as a bare
  (unquoted) integer otherwise — never a JSON string. ``rank`` is always
  a bare (unquoted) numeric-looking token too (the ``printf('%.4f', ...)``
  text, interpolated with no quotes), for the same reason.
* Row filtering: a hit whose ``name`` (symbols) or ``path`` (artifacts) is
  empty is skipped entirely, in BOTH formats (bash: ``[[ -z "$name" ]] &&
  continue`` / ``[[ -z "$path" ]] && continue``). Both columns are
  ``NOT NULL`` in the base tables (``0001_init.sql``), so this is
  defensive/dead in practice — preserved anyway, byte-for-byte.
* Malformed FTS5 query text (e.g. a search string containing an
  un-quoted mid-word ``-``, which FTS5's own query grammar parses as a
  NOT-operator and can reject outright) is a DELIBERATE, DOCUMENTED
  deviation from bash, not silent parity: see :func:`_search_impl`'s
  docstring for why bash's own behavior on that input (a real SQL error
  silently spliced into otherwise-valid markdown output, exit 0) is not
  worth reproducing, and what this port does instead (a controlled
  stderr message, exit 1).
"""

from __future__ import annotations

import asyncio
import json
import os

import typer
from pydantic import BaseModel, ConfigDict
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from shepherd_cli import db
from shepherd_cli.resolution import resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Bash parity requires FULL control over -h/--help's own output (see
    # _USAGE / the token loop below) instead of Click's autogenerated help
    # text, so Click's own --help machinery is disabled entirely
    # (help_option_names=[]) -- mirroring shepherd_cli.commands.models's
    # documented technique. allow_extra_args + ignore_unknown_options let
    # every "--scope=...", "--all", "--limit=...", "--md"/"--json" token
    # flow into the single variadic `raw` argument below instead of Click
    # trying (and failing) to parse them as its own options -- mirroring
    # shepherd_cli.commands.query's identical context_settings, for the
    # identical reason: the bash source interleaves free-text words and
    # flags in ANY order on one command line, and a single variadic
    # positional argument is the only Typer/Click shape that captures
    # "every remaining token, in order" without the Group's own
    # subcommand-resolution step trying (and failing) to treat the first
    # leftover token as a subcommand name.
    context_settings={
        "help_option_names": [],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
    help="FTS5 search over the project's symbol index and artifact content.",
)

#: Verbatim bash-parity usage text -- cmd_search.sh's usage() heredoc,
#: printed to STDOUT (not stderr) on -h/--help, and to STDERR (prefixed by
#: an ERROR line) on every validation failure that shows it.
_USAGE = (
    "shctx search <text> [--scope=symbols|artifacts|all] [--limit=N] [--md|--json]\n"
    "\n"
    "FTS5 search over the project's symbol index and artifact content. Requires\n"
    'schema migration 0004 (run `shctx migrate` if it errors with "no such table").\n'
    "\n"
    "  text          search text — passes to FTS5 (`name AND signature` etc OK)\n"
    "  --scope       symbols | artifacts | all (default: all)\n"
    "  --all         alias for --scope=all (canonical universal flag, v5.0.4)\n"
    "  --limit       max results per scope (default: 20)\n"
    "  --md | --json output format (default: md)\n"
    "\n"
    "Examples:\n"
    '  shctx search "BookSnapshot"\n'
    '  shctx search "QuestDB ILP" --scope=artifacts\n'
    '  shctx search "candle OR ohlc" --scope=symbols --limit=10 --json'
)

#: ``run_symbols()`` in cmd_search.sh, mirrored column-for-column
#: (including the unused ``signature`` select -- selected by bash but
#: never referenced by either renderer; kept here purely for parity, see
#: the module docstring). ``rank`` is TEXT (``printf('%.4f', ...)``), and
#: ``ORDER BY rank`` sorts by that same formatted-string expression, not
#: the underlying numeric bm25 value -- preserved exactly, not "fixed".
_SYMBOLS_SQL = """\
SELECT s.package AS package, s.kind AS kind, s.name AS name, s.signature AS signature,
       s.file_path AS file, s.line AS line,
       printf('%.4f', bm25(index_fts_symbols)) AS rank
FROM index_fts_symbols
JOIN index_symbols s ON s.rowid = index_fts_symbols.rowid
WHERE index_fts_symbols MATCH ?
  AND s.project_id = ?
ORDER BY rank
LIMIT ?
"""

#: ``run_artifacts()`` in cmd_search.sh, mirrored column-for-column,
#: including the ``snippet()`` newline/carriage-return stripping.
_ARTIFACTS_SQL = """\
SELECT a.kind AS kind, a.path AS path, COALESCE(a.title,'') AS title,
       COALESCE(a.sprint_branch,'') AS branch,
       replace(replace(snippet(index_fts_artifacts, 2, '«', '»', ' … ', 12), char(10), ' '), char(13), ' ') AS ctx,
       printf('%.4f', bm25(index_fts_artifacts)) AS rank
FROM index_fts_artifacts
JOIN artifacts a ON a.rowid = index_fts_artifacts.rowid
WHERE index_fts_artifacts MATCH ?
  AND a.project_id = ?
ORDER BY rank
LIMIT ?
"""

#: cmd_search.sh's FTS-tables-present guard: ``SELECT 1 FROM sqlite_master
#: WHERE type='table' AND name='index_fts_symbols';`` piped to ``grep -q
#: 1``. Any returned row means the table exists (migration 0004 applied).
_FTS_CHECK_SQL = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_fts_symbols'"


class SymbolHit(BaseModel):
    """One ``index_fts_symbols`` MATCH row, shaped for both renderers.

    Attributes:
        package: ``index_symbols.package`` (``NOT NULL``).
        kind: ``index_symbols.kind`` (``NOT NULL``).
        name: ``index_symbols.name`` (``NOT NULL``); a hit with an empty
            name is dropped before construction (see
            :func:`_rows_to_symbol_hits`), matching bash's ``[[ -z "$name"
            ]] && continue``.
        signature: ``index_symbols.signature`` (nullable). Selected for
            bash-parity with ``run_symbols()``'s column list but never
            rendered by either format -- see the module docstring.
        file: ``index_symbols.file_path`` (``NOT NULL``); bash's ``$path``
            loop variable, renamed here to match this port's own JSON key
            (``"file"``, per ``cmd_search.sh``'s ``emit_json``).
        line: ``index_symbols.line`` (nullable ``INTEGER``).
        rank: The ``printf('%.4f', bm25(...))`` TEXT value, kept as a
            string (not parsed to float) so both renderers reproduce the
            exact formatted text bash interpolates verbatim.
    """

    model_config = ConfigDict(from_attributes=True)

    package: str
    kind: str
    name: str
    signature: str | None
    file: str
    line: int | None
    rank: str


class ArtifactHit(BaseModel):
    """One ``index_fts_artifacts`` MATCH row, shaped for both renderers.

    Attributes:
        kind: ``artifacts.kind`` (``NOT NULL``).
        path: ``artifacts.path`` (``NOT NULL``); a hit with an empty path
            is dropped before construction, matching bash's ``[[ -z
            "$path" ]] && continue``.
        title: ``COALESCE(artifacts.title, '')`` -- always a string,
            never None (bash: an empty ``read`` field, not "unset").
        branch: ``COALESCE(artifacts.sprint_branch, '')`` -- same
            always-a-string contract as ``title``.
        ctx: The highlighted FTS5 ``snippet()`` text, newlines/carriage
            returns already collapsed to spaces by the SQL itself
            (mirrors ``run_artifacts()``'s ``replace(replace(...))``
            chain) -- always a string, possibly empty.
        rank: The ``printf('%.4f', bm25(...))`` TEXT value, kept as a
            string for the same reason as :attr:`SymbolHit.rank`.
    """

    model_config = ConfigDict(from_attributes=True)

    kind: str
    path: str
    title: str
    branch: str
    ctx: str
    rank: str


def _read_project_id() -> str:
    """Resolve the active project id, bash-parity with ``_lib.sh``'s ``shctx_project_id``.

    Duplicated from :mod:`shepherd_cli.commands.query`'s identical helper
    (not imported -- both modules are self-contained per the port's
    instructions, and :mod:`shepherd_cli.resolution`, the one shared
    module either could import, has no project-id helper of its own).
    ``cmd_search.sh`` calls this ``_lib.sh`` helper unconditionally, BEFORE
    ever opening a database connection: it reads ``<workdir>/project.json``
    (``jq -r '.id' "$(shctx_project_id_path)"``), a file, not a table --
    see the module docstring for why this command mirrors that (rather
    than ``mem.py``'s "read the ``projects`` table" deviation).

    Returns:
        The project id string, or the literal three-character string
        ``"null"`` if ``project.json``'s ``"id"`` key is present-but-null
        or absent -- jq -r's raw-output rendering of JSON ``null``,
        reproduced here for parity.

    Raises:
        typer.Exit: Code 1, with the exact bash stderr message
            (``"ERROR: <path> missing — run 'shctx init' first"``), if
            ``project.json`` does not exist. Also code 1 (with an
            equivalent, but not byte-identical, message) if the file
            exists but is not valid JSON; bash's ``jq`` would instead
            abort the whole script with jq's own parse-error message.
    """
    path = os.path.join(resolve_workdir(), "project.json")
    if not os.path.isfile(path):
        typer.echo(f"ERROR: {path} missing — run 'shctx init' first", err=True)
        raise typer.Exit(code=1)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(f"ERROR: failed to parse {path} as JSON", err=True)
        raise typer.Exit(code=1) from exc
    raw_id = data.get("id") if isinstance(data, dict) else None
    return "null" if raw_id is None else str(raw_id)


def _parse_args(tokens: list[str]) -> tuple[str, str, str, str]:
    """Classify every token on the command line, bash-parity with cmd_search.sh's ``while`` loop.

    Walks ``tokens`` in order, exactly mirroring the bash ``case`` chain's
    precedence (checked top-to-bottom, per token, in this exact order):
    ``-h``/``--help`` (prints usage to STDOUT and exits 0 immediately --
    later tokens are never examined, matching bash's ``usage; exit 0``
    short-circuit), ``--scope=*``, ``--all`` (alias for
    ``--scope=all``), ``--limit=*``, ``--md``, ``--json``, any other
    ``--``-prefixed token (unknown flag -> error), and finally anything
    else is appended to the free-text search string (space-joined, bash:
    ``text+="${text:+ }$1"``). Flags and text words may appear in ANY
    order on the command line -- this loop does not require text to come
    first or last.

    Args:
        tokens: Every token given after ``search``, in order (both free
            text words and flags, interleaved as the caller gave them).

    Returns:
        A ``(text, scope, limit, fmt)`` tuple: ``text`` is the
        space-joined free-text search string (possibly empty -- checked
        by the caller, not here, matching bash's own two-step validation
        order: parse first, then check ``-n "$text"`` separately);
        ``scope`` is whatever raw string followed ``--scope=`` or
        ``"all"`` (default, or after ``--all``) -- NOT validated against
        ``symbols|artifacts|all`` here (bash validates it in a separate
        ``case`` statement after the loop; see :func:`_validate_scope`);
        ``limit`` is the raw string that followed ``--limit=`` or the
        default ``"20"`` -- likewise not yet parsed to an int; ``fmt`` is
        ``"md"`` (default) or ``"json"``, last ``--md``/``--json`` flag
        wins (bash: plain variable reassignment).

    Raises:
        typer.Exit: Code 0, after printing :data:`_USAGE` to stdout, on
            the first ``-h``/``--help`` token. Code 1, with bash's exact
            stderr message (``"ERROR: unknown flag: <token>"`` followed by
            :data:`_USAGE` on stderr), on the first token that starts
            with ``--`` and matches none of the recognized flag shapes.
    """
    scope = "all"
    limit = "20"
    fmt = "md"
    text_parts: list[str] = []

    for token in tokens:
        if token in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        elif token.startswith("--scope="):
            scope = token[len("--scope=") :]
        elif token == "--all":
            scope = "all"
        elif token.startswith("--limit="):
            limit = token[len("--limit=") :]
        elif token == "--md":
            fmt = "md"
        elif token == "--json":
            fmt = "json"
        elif token.startswith("--"):
            typer.echo(f"ERROR: unknown flag: {token}", err=True)
            typer.echo(_USAGE, err=True)
            raise typer.Exit(code=1)
        else:
            text_parts.append(token)

    return " ".join(text_parts), scope, limit, fmt


def _validate_scope(scope: str) -> None:
    """Bash parity: ``case "$scope" in symbols|artifacts|all) ;; *) ERROR ... ;; esac``.

    Args:
        scope: The raw ``--scope``/``--all`` value from :func:`_parse_args`.

    Raises:
        typer.Exit: Code 1, with bash's exact stderr message (``"ERROR:
            --scope must be symbols|artifacts|all"``), and NO usage text
            (bash's own guard does not call ``usage`` here), if ``scope``
            is anything other than ``symbols``, ``artifacts``, or ``all``.
    """
    if scope not in ("symbols", "artifacts", "all"):
        typer.echo("ERROR: --scope must be symbols|artifacts|all", err=True)
        raise typer.Exit(code=1)


def _validate_fmt(fmt: str) -> None:
    """Bash parity: ``case "$fmt" in md|json) ;; *) ERROR ... ;; esac``.

    Dead code in practice (:func:`_parse_args` can only ever produce
    ``"md"`` or ``"json"``, exactly like bash's own loop can only ever
    set ``fmt=md``/``fmt=json``) -- kept for byte-for-byte structural
    parity with ``cmd_search.sh``, which performs the same always-true
    check.

    Args:
        fmt: The format string from :func:`_parse_args`.

    Raises:
        typer.Exit: Code 1, with bash's exact stderr message (``"ERROR:
            format must be --md or --json"``), if ``fmt`` is anything
            other than ``"md"`` or ``"json"``.
    """
    if fmt not in ("md", "json"):
        typer.echo("ERROR: format must be --md or --json", err=True)
        raise typer.Exit(code=1)


def _parse_limit(limit_raw: str) -> int:
    """Parse ``--limit``'s raw string into an int, bash-parity with ``$((limit + 0))``.

    Bash's ``limit_n=$((limit + 0))`` arithmetic expansion accepts any
    string bash's arithmetic parser accepts as an integer (including a
    leading ``+``/``-`` sign and, unlike this port, octal-looking
    ``0``-prefixed strings) and aborts the whole script (via ``set -e``,
    since arithmetic-expansion failure is a command failure) with a
    non-zero exit status and bash's own uncontrolled error text on
    anything else. This port accepts exactly the strings Python's
    ``int()`` accepts (a strict superset of bash's for ordinary decimal
    input, a strict subset for bash's octal quirk -- no shipped caller
    passes an octal-looking ``--limit``) and raises the SAME class of
    "abort with a non-zero exit and a stderr message" failure on anything
    else, with this port's own (not byte-identical) message -- documented
    deviation, not silent.

    Args:
        limit_raw: The raw string from ``--limit=<value>`` (default
            ``"20"``).

    Returns:
        The parsed integer. A negative value is passed straight through
        to the SQL ``LIMIT`` clause, where SQLite's own semantics apply
        (a negative ``LIMIT`` means "no limit") -- exactly what bash's
        arithmetic-then-``LIMIT $limit_n`` pipeline would also produce,
        with no special-casing needed here.

    Raises:
        typer.Exit: Code 1, with a stderr message, if ``limit_raw`` is
            not parseable as a base-10 integer.
    """
    try:
        return int(limit_raw)
    except ValueError as exc:
        typer.echo(f"ERROR: --limit must be an integer, got: {limit_raw}", err=True)
        raise typer.Exit(code=1) from exc


def _json_escape_quotes(value: str) -> str:
    """Double every literal ``"`` in ``value``, bash-parity with ``sed 's/"/\\\\"/g'``.

    Deliberately does NOT escape backslashes, newlines, or any other JSON
    control character -- ``cmd_search.sh``'s ``emit_json`` only ever runs
    this exact ``sed`` substitution over ``title``/``ctx``, nothing more.
    See the module docstring's ``--json`` bullet for why this quirk is
    preserved rather than replaced with a real JSON string encoder.

    Args:
        value: The raw string (``title`` or ``ctx``) to escape.

    Returns:
        ``value`` with every ``"`` replaced by ``\\"``.
    """
    return value.replace('"', '\\"')


def _rows_to_symbol_hits(rows: list[dict[str, object]]) -> list[SymbolHit]:
    """Build :class:`SymbolHit` rows from raw query rows, dropping empty-name hits.

    Args:
        rows: Raw dict rows from :data:`_SYMBOLS_SQL`, in the query's own
            ``ORDER BY rank`` order (preserved).

    Returns:
        Validated :class:`SymbolHit` instances, skipping any row whose
        ``name`` is empty or None -- bash: ``[[ -z "$name" ]] && continue``.
    """
    hits: list[SymbolHit] = []
    for row in rows:
        if not row.get("name"):
            continue
        hits.append(SymbolHit.model_validate(row))
    return hits


def _rows_to_artifact_hits(rows: list[dict[str, object]]) -> list[ArtifactHit]:
    """Build :class:`ArtifactHit` rows from raw query rows, dropping empty-path hits.

    Args:
        rows: Raw dict rows from :data:`_ARTIFACTS_SQL`, in the query's
            own ``ORDER BY rank`` order (preserved).

    Returns:
        Validated :class:`ArtifactHit` instances, skipping any row whose
        ``path`` is empty or None -- bash: ``[[ -z "$path" ]] && continue``.

    Note:
        ``ctx`` (unlike ``title``/``branch``) is NOT wrapped in a SQL-level
        ``COALESCE`` (see :data:`_ARTIFACTS_SQL`, mirroring
        ``run_artifacts()`` exactly) -- FTS5's ``snippet()`` returns SQL
        NULL, not an empty string, for a hit whose match came entirely
        from a non-snippeted column (``path``/``title``) with nothing in
        the snippeted ``content`` column to highlight. Bash never sees
        this as "unset": ``sqlite3``'s list-mode output renders a NULL
        cell as an empty string by default, so bash's ``read`` always
        assigns ``ctx=""`` in that case. The driver behind
        ``execute_query_dict`` has no such rendering step and surfaces
        the NULL as Python ``None`` instead, so it is coerced to ``""``
        here, before validation, to reproduce that same "NULL renders as
        empty string" convention rather than raising a validation error.
    """
    hits: list[ArtifactHit] = []
    for row in rows:
        if not row.get("path"):
            continue
        hits.append(ArtifactHit.model_validate({**row, "ctx": row.get("ctx") or ""}))
    return hits


def _render_markdown(text: str, scope: str, symbols: list[SymbolHit], artifacts: list[ArtifactHit]) -> str:
    """Render the bash-parity markdown report, mirroring ``emit_md`` line-for-line.

    Every element appended to the internal line list corresponds to
    exactly one ``echo`` call in ``cmd_search.sh``'s ``emit_md`` (an empty
    string element == a bare ``echo`` == one blank line) -- joining with
    ``"\\n"`` and letting the caller's single trailing ``typer.echo``
    supply the final newline reproduces bash's output byte-for-byte
    (each ``echo`` terminates its own line; ``"\\n".join`` plus one
    trailing newline is exactly equivalent to summing "line + its own
    newline" over every element).

    Args:
        text: The original free-text search string (rendered verbatim in
            the ``# shctx search — `text`` `` header, backticks and all --
            never escaped, matching bash's own unescaped interpolation).
        scope: The validated scope (``"symbols"``, ``"artifacts"``, or
            ``"all"``).
        symbols: Symbol hits, already rank-ordered and empty-name-filtered.
        artifacts: Artifact hits, already rank-ordered and
            empty-path-filtered.

    Returns:
        The full multi-line report (no trailing newline -- the caller's
        ``typer.echo`` supplies exactly one, matching bash).
    """
    lines: list[str] = [f"# shctx search — `{text}`", ""]

    if scope in ("symbols", "all"):
        lines.append("## Symbols")
        lines.append("")
        lines.append("| package | kind | name | file:line | rank |")
        lines.append("|---|---|---|---|---|")
        for hit in symbols:
            line_val = "" if hit.line is None else str(hit.line)
            lines.append(f"| `{hit.package}` | {hit.kind} | `{hit.name}` | `{hit.file}:{line_val}` | {hit.rank} |")
        lines.append("")

    if scope in ("artifacts", "all"):
        lines.append("## Artifacts")
        lines.append("")
        for hit in artifacts:
            branch_part = f" · branch `{hit.branch}`" if hit.branch else ""
            lines.append(f"- **{hit.kind}** · `{hit.path}`{branch_part} · rank {hit.rank}")
            lines.append(f"  - {hit.title}")
            if hit.ctx:
                lines.append(f"  - {hit.ctx}")

    return "\n".join(lines)


def _render_json(scope: str, symbols: list[SymbolHit], artifacts: list[ArtifactHit]) -> str:
    """Render the bash-parity JSON report, mirroring ``emit_json`` byte-for-byte.

    Reproduces ``cmd_search.sh``'s hand-rolled comma placement exactly
    (each fragment appended below corresponds to exactly one ``echo``/
    ``printf`` call in bash, in the same order): a comma is emitted
    BEFORE every entry except the first, immediately after the previous
    entry's un-terminated text -- which is what makes the final output
    valid, conventionally-formatted JSON (``entry1,\\n    entry2`` rather
    than a dangling leading comma). See the module docstring's ``--json``
    bullet for the escaping quirks (``title``/``ctx`` only) this
    intentionally preserves.

    Args:
        scope: The validated scope (``"symbols"``, ``"artifacts"``, or
            ``"all"``).
        symbols: Symbol hits, already rank-ordered and empty-name-filtered.
        artifacts: Artifact hits, already rank-ordered and
            empty-path-filtered.

    Returns:
        The full JSON text (no trailing newline -- the caller's
        ``typer.echo`` supplies exactly one, matching bash's final
        ``echo '}'``). Always well-formed JSON for well-formed input rows
        (empty arrays render as ``[ ]`` with an interior blank line, byte-
        parity with bash's own unconditional blank-line ``echo`` even when
        a loop produced zero entries).
    """
    parts: list[str] = ["{\n"]

    if scope in ("symbols", "all"):
        parts.append('  "symbols": [\n')
        first = True
        for hit in symbols:
            if not first:
                parts.append(",\n")
            first = False
            line_token = "null" if hit.line is None else str(hit.line)
            parts.append(
                "    {"
                f'"package":"{hit.package}","kind":"{hit.kind}","name":"{hit.name}",'
                f'"file":"{hit.file}","line":{line_token},"rank":{hit.rank}'
                "}"
            )
        parts.append("\n")
        parts.append("  ]\n")

    if scope == "all":
        parts.append("  ,\n")

    if scope in ("artifacts", "all"):
        parts.append('  "artifacts": [\n')
        first = True
        for hit in artifacts:
            if not first:
                parts.append(",\n")
            first = False
            title_esc = _json_escape_quotes(hit.title)
            ctx_esc = _json_escape_quotes(hit.ctx)
            parts.append(
                "    {"
                f'"kind":"{hit.kind}","path":"{hit.path}","title":"{title_esc}",'
                f'"branch":"{hit.branch}","context":"{ctx_esc}","rank":{hit.rank}'
                "}"
            )
        parts.append("\n")
        parts.append("  ]\n")

    parts.append("}")
    return "".join(parts)


async def _fts_tables_present() -> bool:
    """Check whether migration 0004's FTS5 tables exist.

    Bash parity: ``SELECT 1 FROM sqlite_master WHERE type='table' AND
    name='index_fts_symbols';`` piped to ``grep -q 1``.

    Returns:
        True if ``index_fts_symbols`` exists in ``sqlite_master``.
    """
    connection = Tortoise.get_connection("default")
    rows = await connection.execute_query_dict(_FTS_CHECK_SQL)
    return len(rows) > 0


async def _run_symbols(query_text: str, project_id: str, limit: int) -> list[SymbolHit]:
    """Run :data:`_SYMBOLS_SQL` and return validated, filtered hits.

    Args:
        query_text: The raw FTS5 ``MATCH`` expression (the free-text
            search string, unmodified -- bash-parity: bash only
            SQL-escapes single quotes for its own string-interpolated
            query; parameter binding here achieves the same effect
            without needing that manual escaping step).
        project_id: The active project id, scoping the join.
        limit: The parsed ``--limit`` value (may be negative -- SQLite
            treats a negative ``LIMIT`` as "no limit").

    Returns:
        Rank-ordered symbol hits, empty-name rows already dropped.
    """
    connection = Tortoise.get_connection("default")
    rows = await connection.execute_query_dict(_SYMBOLS_SQL, [query_text, project_id, limit])
    return _rows_to_symbol_hits(rows)


async def _run_artifacts(query_text: str, project_id: str, limit: int) -> list[ArtifactHit]:
    """Run :data:`_ARTIFACTS_SQL` and return validated, filtered hits.

    Args:
        query_text: The raw FTS5 ``MATCH`` expression.
        project_id: The active project id, scoping the join.
        limit: The parsed ``--limit`` value.

    Returns:
        Rank-ordered artifact hits, empty-path rows already dropped.
    """
    connection = Tortoise.get_connection("default")
    rows = await connection.execute_query_dict(_ARTIFACTS_SQL, [query_text, project_id, limit])
    return _rows_to_artifact_hits(rows)


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    raw: list[str] = typer.Argument(
        None,
        metavar="TEXT... [--scope=symbols|artifacts|all] [--all] [--limit=N] [--md|--json]",
        help="Search text (one or more words) plus any mix of --scope/--all/--limit/--md/--json flags, in any order.",
    ),
) -> None:
    """FTS5 search over the project's symbol index and artifact content.

    Native port of ``shctx search`` (``cmd_search.sh``). Every token after
    ``search`` is either a free-text word (space-joined into the FTS5
    ``MATCH`` expression) or a recognized flag; see :func:`_parse_args`
    for the exact per-token classification bash mirrors.

    Args:
        ctx: The Typer/Click context (unused directly; required so
            ``invoke_without_command`` dispatch works like every other
            single-verb group in this package -- see
            :mod:`shepherd_cli.commands.query`'s identical pattern).
        raw: Every token given after ``search``, in order.

    Raises:
        typer.Exit: Code 0 on ``-h``/``--help`` (usage printed to
            stdout). Code 1 on: an unknown ``--`` flag, empty search text
            (bash: ``"ERROR: search text required"`` plus usage, both on
            stderr), an invalid ``--scope``, an unparseable ``--limit``,
            or a missing/unparseable ``project.json``. Code 2 if
            migration 0004's FTS5 tables are absent.
    """
    del ctx  # required by invoke_without_command dispatch; unused otherwise.
    tokens = raw or []
    text, scope, limit_raw, fmt = _parse_args(tokens)

    if not text:
        typer.echo("ERROR: search text required", err=True)
        typer.echo(_USAGE, err=True)
        raise typer.Exit(code=1)

    _validate_scope(scope)
    _validate_fmt(fmt)
    limit = _parse_limit(limit_raw)

    project_id = _read_project_id()
    asyncio.run(_search_impl(text=text, scope=scope, limit=limit, fmt=fmt, project_id=project_id))


async def _search_impl(text: str, scope: str, limit: int, fmt: str, project_id: str) -> None:
    """Resolve the FTS5 hits for ``project_id`` and print the report.

    Split out from the synchronous :func:`_default` callback (which
    resolves ``project_id`` off the filesystem BEFORE ever opening a
    database connection, matching bash's exact ordering: ``shctx_project_
    id`` runs first, and only then is ``$db`` touched) so this coroutine's
    only job is the database half: open :func:`shepherd_cli.db.lifespan`,
    check the FTS5 tables exist, run the scoped queries, and render.

    Args:
        text: The validated (non-empty) free-text search string.
        scope: The validated scope (``"symbols"``, ``"artifacts"``, or
            ``"all"``).
        limit: The parsed ``--limit`` value.
        fmt: The validated format (``"md"`` or ``"json"``).
        project_id: The project id resolved by :func:`_read_project_id`.

    Raises:
        typer.Exit: Code 2, with bash's exact stderr message, if
            migration 0004's FTS5 tables are absent. Code 1, with a
            controlled stderr message (NOT bash-parity -- see this
            function's "malformed FTS5 query text" note below), if
            ``text`` is not valid FTS5 query syntax.

    Note (deliberate, documented deviation -- malformed FTS5 query text):
        ``text`` is passed straight through to FTS5's ``MATCH`` as the
        raw query string (bash-parity: neither ``cmd_search.sh`` nor this
        port quote/sanitize it into a phrase first -- see the module
        docstring's SQL constants). FTS5's OWN query-string grammar
        treats characters like an un-quoted mid-word ``-`` specially (a
        search text such as ``foo-bar`` is not literal text to FTS5; it
        parses as ``foo NOT bar``, and something like
        ``nothing-will-match`` fails outright with a SQLite
        ``OperationalError`` -- ``no such column: will`` -- because of
        how FTS5's grammar disambiguates a bare hyphen there). Bash's OWN
        behavior on that same input is arguably worse, not better: the
        ``sqlite3`` CLI's ``.mode list`` heredoc invocation reports that
        per-statement runtime error to STDOUT (``Runtime error near line
        3: no such column: will``) -- mixed directly into the markdown
        body where a data row would have gone -- while the script's own
        ``set -e`` does NOT see it (the failing ``sqlite3`` call runs
        inside a bash process-substitution, ``< <(run_symbols)``, whose
        exit status the parent shell never checks), so ``shctx search``
        exits **0** with a corrupted-looking but "successful" report.
        Reproducing that exact behavior would mean deliberately
        swallowing a real SQL error into the middle of otherwise-valid
        markdown/JSON output -- worse UX, not bash parity worth
        preserving. Instead, any :class:`tortoise.exceptions.
        OperationalError` raised while running the FTS5 queries is
        caught here and reported as a single controlled error line on
        stderr with exit code 1 (grouped with this command's other
        validation-style failures), rather than letting a raw Python
        traceback (or bash's own corrupted-output quirk) reach the
        caller.
    """
    async with db.lifespan():
        if not await _fts_tables_present():
            typer.echo(
                "ERROR: FTS tables missing. Run `shctx migrate` to apply 0004_fts_search.sql.",
                err=True,
            )
            raise typer.Exit(code=2)

        symbols: list[SymbolHit] = []
        artifacts: list[ArtifactHit] = []
        try:
            if scope in ("symbols", "all"):
                symbols = await _run_symbols(text, project_id, limit)
            if scope in ("artifacts", "all"):
                artifacts = await _run_artifacts(text, project_id, limit)
        except OperationalError as exc:
            typer.echo(f"ERROR: invalid search text: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    if fmt == "json":
        typer.echo(_render_json(scope, symbols, artifacts))
    else:
        typer.echo(_render_markdown(text, scope, symbols, artifacts))


__all__ = ["app"]
