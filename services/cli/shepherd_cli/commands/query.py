"""``shepherd query`` — canned-SQL runner Typer sub-app.

Native port of ``skills/context/scripts/cmd_query.sh``: a single verb,
``shctx query <name> [--json|--md] [--key=val ...]``, that loads a named
``.sql`` file from ``skills/context/queries/``, substitutes ``:token``
placeholders with caller-supplied values (plus an always-available
``:project_id``), runs the result as ONE statement against the registry
database, and prints the rows either as a markdown-ish table (default) or
as JSON (``--json``).

This is a raw-SQL runner by design (hard rule #8): the canned queries
already live as ``.sql`` files under skills/context/queries/ and mixing a
"real" query language on top of them (through the ORM) would mean
reimplementing every one of those queries a second time, in a second
place, and letting the two drift. Instead this module loads the file text
byte-for-byte and asks Tortoise's raw connection
(``conn.execute_query_dict``) to run it — exactly what ``cmd_query.sh``
does by piping the same file text into ``sqlite3``. No Tortoise model is
declared here; nothing in this module reads or writes a table through the
ORM.

Substitution semantics mirror ``cmd_query.sh`` deliberately closely,
including its rough edges (hard rule #4 — bash parity is the bar, not an
improved reimplementation):

1. Every literal occurrence of the substring ``:project_id`` is replaced
   with the active project id, single-quoted, UNESCAPED (bash:
   ``sql=${sql//:project_id/\\'$project_id\\'}`` — no quote-doubling, since
   a project id is a UUID and never contains a quote in practice).
2. Every ``--key=val`` flag on the command line then replaces every
   literal occurrence of ``:key`` with ``'val'``, with any single quote in
   ``val`` doubled first (SQL-string escaping) — in the exact order the
   flags were given, via plain substring replacement (Python ``str.replace``,
   matching bash's ``${sql//:key/...}``), NOT a token-boundary regex. Like
   bash, this means a bind key that happens to be a prefix of another
   ``:token`` in the SQL (none of the shipped queries have this shape) would
   also clobber part of that longer token — an inherited quirk, not a new
   one.
3. Any ``:token`` still left after steps 1-2 (an optional parameter the
   caller didn't supply) is replaced with a bare, unquoted ``NULL`` via the
   same regex bash's trailing ``sed 's/:[a-z_][a-z_0-9]*/NULL/g'`` pass
   uses — so ``:sprint IS NULL OR sprint = :sprint`` degrades to
   ``NULL IS NULL OR sprint = NULL``, matching (match-all) as intended.
   This final pass runs over the WHOLE sql text, including inside already-
   substituted string literals, exactly like the bash ``sed`` invocation
   does (piped over the entire, already-bound SQL) — another inherited
   quirk kept for parity rather than fixed.

Deviations from ``cmd_query.sh`` (both unavoidable consequences of not
shelling out to the ``sqlite3`` CLI, both noted where they matter below):

* ``--json`` output is pretty-printed (``json.dumps(..., indent=2)``)
  rather than ``sqlite3 -json``'s compact one-object-per-line form. Same
  keys, same values, same empty-result-set contract (zero rows -> zero
  bytes of output, not ``"[]"``) — different whitespace only.
* The default (``--md``) table is a real left-justified GitHub-flavored
  markdown pipe table, built directly in Python. ``cmd_query.sh`` asks
  ``sqlite3 -header -markdown`` to build one (with a ``-header -column``
  fallback for a ``sqlite3`` build too old to support ``-markdown``); this
  module always renders the same way, so that fallback branch has no
  Python equivalent. Column widths and left-justification match this
  package's other table renderers (:mod:`shepherd_cli.commands.mem`'s
  ``_render_sqlite_table``); the exact character-by-character padding
  ``sqlite3 -header -markdown`` uses (it centers the header text within
  each column) is NOT reproduced — both are valid, readable markdown
  tables, but they are not byte-identical.
"""

from __future__ import annotations

import asyncio
import json
import os
import re

import typer
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.resolution import resolve_repo_root, resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # allow_extra_args / ignore_unknown_options let arbitrary "--key=val"
    # tokens (not known in advance -- they are the .sql file's own bind
    # parameters) flow through to `raw` below instead of Click rejecting
    # them as unrecognized options. See the module-level note in the test
    # file for why `raw` is declared as a variadic positional rather than
    # a single `name` Argument + `ctx.args`: Typer/Click always builds a
    # module with a `@app.callback` as a dispatch Group, and a Group
    # unconditionally treats the first LEFTOVER token after its own
    # params are consumed as a candidate subcommand name -- which would
    # make e.g. `shepherd query mem-search --q=foo` fail with "No such
    # command '--q=foo'" the moment `name` (a single-value Argument)
    # stopped consuming after `mem-search`. A variadic Argument instead
    # consumes every remaining token itself, so nothing is left over for
    # the Group's subcommand-resolution step to misinterpret.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Run a canned .sql query from skills/context/queries/ and print the rows.",
)

#: Verbatim bash-parity usage/error text — ``cmd_query.sh``'s
#: ``echo "ERROR: usage: ..." >&2; exit 1`` when ``$name`` is empty.
_USAGE = "ERROR: usage: shctx query <name> [--json|--md] [--key=val ...]"

#: Relative path from a plugin/repo root to the canned-queries directory,
#: mirroring ``_lib.sh``'s ``shctx_skill_root`` (``.../skills/context``)
#: with ``/queries`` appended -- the exact directory ``cmd_query.sh``
#: reads ``$name.sql`` out of.
_QUERIES_RELPATH = os.path.join("skills", "context", "queries")

#: Matches ``_lib.sh``'s trailing-substitution regex
#: (``sed 's/:[a-z_][a-z_0-9]*/NULL/g'``) exactly: a colon, then one
#: lowercase-letter-or-underscore, then zero or more
#: lowercase-letters/digits/underscores.
_LEFTOVER_TOKEN_RE = re.compile(r":[a-z_][a-z_0-9]*")

#: Two-space gutter, matching this package's other table renderers'
#: convention (:mod:`shepherd_cli.commands.mem`, ``.teammate``, ``.deliverable``).
_COLUMN_GUTTER = " | "


def _find_queries_dir() -> str | None:
    """Locate the canned-queries directory (``skills/context/queries``).

    Mirrors ``_lib.sh``'s ``shctx_skill_root`` resolution as used by every
    other ``find_*`` helper in :mod:`shepherd_cli.resolution`
    (``find_migrations_dir``, ``find_schema_base``, ``find_bash_shctx``):
    prefer ``$CLAUDE_PLUGIN_ROOT/skills/context/queries`` when set, else
    walk up from the repo root looking for a ``skills/context/queries``
    directory. Duplicated locally (rather than imported) because
    :mod:`shepherd_cli.resolution` is a shared module this port does not
    edit (disjoint-file-ownership rule) and its own walk-up helper is
    private (``_find_via_plugin_root_then_walk_up``).

    Returns:
        The queries directory path, or None if it cannot be found
        anywhere on the walk up from the repo root (nor via
        ``CLAUDE_PLUGIN_ROOT``).
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


def _read_project_id() -> str:
    """Resolve the active project id, bash-parity with ``_lib.sh``'s ``shctx_project_id``.

    Unlike most other ported commands (which read ``projects.id`` straight
    out of the database), ``cmd_query.sh`` calls the ``_lib.sh`` helper
    that reads it from the ``project.json`` FILE in the resolved shepherd
    work directory (``jq -r '.id' "$(shctx_project_id_path)"``) — a file,
    not a table. This mirrors that exactly, including jq's raw-output
    quirk: a present-but-``null`` (or altogether absent) ``"id"`` key
    reads back as the literal three-character string ``"null"`` (jq -r's
    text rendering of JSON ``null``), not Python's ``None`` or an empty
    string.

    Returns:
        The project id string (or the literal ``"null"`` per the above).

    Raises:
        typer.Exit: Code 1, with the exact bash stderr message
            (``"ERROR: <path> missing — run 'shctx init' first"``), if
            ``project.json`` does not exist. Also code 1 (with an
            equivalent, but not byte-identical, message -- see the module
            docstring's deviations note) if the file exists but is not
            valid JSON; bash's ``jq`` would instead abort the whole
            script with jq's own parse-error message and exit code.
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


def _parse_flags(flags: list[str]) -> tuple[str, list[str], list[str]]:
    """Classify the flags following ``<name>`` into a format and bind pairs.

    Bash-parity port of ``cmd_query.sh``'s ``for a in "$@"; do case "$a"
    in ...`` loop, evaluated in the exact same order (``--json`` and
    ``--md`` exact-match first, then the ``--*=*`` bind-flag pattern, then
    a catch-all error) -- so e.g. ``--json=x`` does NOT set the format
    (it does not exactly equal ``--json``); it falls through to the bind-flag
    branch and binds ``:json`` to ``x``, exactly as it would in bash.

    Args:
        flags: Every token after ``<name>`` on the command line, in
            order.

    Returns:
        A ``(fmt, bind_keys, bind_vals)`` triple: ``fmt`` is ``"json"`` or
        ``"md"`` (default ``"md"``, last ``--json``/``--md`` flag wins,
        matching bash's plain variable reassignment); ``bind_keys`` and
        ``bind_vals`` are parallel lists of every ``--key=val`` flag, in
        the order given.

    Raises:
        typer.Exit: Code 1, with bash's exact stderr message
            (``"ERROR: bad arg: <a>"``), on the first flag that is
            neither ``--json``, ``--md``, nor ``--key=val``-shaped.
    """
    fmt = "md"
    bind_keys: list[str] = []
    bind_vals: list[str] = []
    for flag in flags:
        if flag == "--json":
            fmt = "json"
        elif flag == "--md":
            fmt = "md"
        elif flag.startswith("--") and "=" in flag:
            key, _, val = flag[2:].partition("=")
            bind_keys.append(key)
            bind_vals.append(val)
        else:
            typer.echo(f"ERROR: bad arg: {flag}", err=True)
            raise typer.Exit(code=1)
    return fmt, bind_keys, bind_vals


def _bind_sql(sql_text: str, project_id: str, bind_keys: list[str], bind_vals: list[str]) -> str:
    """Substitute ``:project_id``, every ``--key=val`` bind, then ``NULL``-fill the rest.

    See the module docstring for the full three-step contract this
    mirrors from ``cmd_query.sh``. All three steps are literal
    substring/regex operations over the whole SQL text, exactly as bash's
    ``${sql//pattern/replacement}`` and trailing ``sed`` pass are -- not
    scoped to string-literal boundaries, not token-aware.

    Args:
        sql_text: The raw ``.sql`` file contents (comments and all).
        project_id: The value to bind for every ``:project_id`` token.
        bind_keys: Bind-flag names, in command-line order (parallel to
            ``bind_vals``).
        bind_vals: Bind-flag raw values, in command-line order (parallel
            to ``bind_keys``); single quotes are doubled before binding.

    Returns:
        The fully-substituted SQL text, ready to execute as one
        statement.
    """
    sql = sql_text.replace(":project_id", f"'{project_id}'")
    for key, val in zip(bind_keys, bind_vals, strict=True):
        escaped = val.replace("'", "''")
        sql = sql.replace(f":{key}", f"'{escaped}'")
    return _LEFTOVER_TOKEN_RE.sub("NULL", sql)


def _render_markdown(rows: list[dict[str, object]]) -> str:
    """Render rows as a left-justified GitHub-flavored markdown pipe table.

    Approximates ``sqlite3 -header -markdown``'s output shape (see the
    module docstring's deviations note for exactly how this differs:
    left-justified everywhere here, vs. sqlite3's centered header text).
    NULL cells render as an empty string, matching sqlite3.

    Args:
        rows: Query result rows, each a ``{column: value}`` dict in
            column-select order (``execute_query_dict`` preserves the
            cursor's column order, which Python dicts then preserve on
            iteration).

    Returns:
        The rendered table (header, separator, one line per row; no
        trailing newline). Callers must skip printing entirely when
        ``rows`` is empty -- there is no header-only rendering, matching
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
        return "| " + _COLUMN_GUTTER.join(cell.ljust(width) for cell, width in zip(cells, widths, strict=True)) + " |"

    header = render_row(columns)
    separator = "|" + "|".join("-" * (width + 2) for width in widths) + "|"
    body = [render_row(str_row) for str_row in str_rows]
    return "\n".join([header, separator, *body])


async def _query_async(name: str, fmt: str, bind_keys: list[str], bind_vals: list[str]) -> None:
    """Load, bind, execute, and print one canned query.

    Args:
        name: The query's base filename (without ``.sql``).
        fmt: ``"json"`` or ``"md"`` (from :func:`_parse_flags`).
        bind_keys: Bind-flag names, in command-line order.
        bind_vals: Bind-flag raw values, in command-line order.

    Raises:
        typer.Exit: Code 1, with bash's exact stderr message
            (``"ERROR: query not found: <name>"``), if no
            ``<queries_dir>/<name>.sql`` file exists (including when the
            queries directory itself cannot be located at all). Also code
            1 (via :func:`_read_project_id`) if ``project.json`` is
            missing or unparseable.
    """
    queries_dir = _find_queries_dir()
    sql_path = os.path.join(queries_dir, f"{name}.sql") if queries_dir is not None else None
    if sql_path is None or not os.path.isfile(sql_path):
        typer.echo(f"ERROR: query not found: {name}", err=True)
        raise typer.Exit(code=1)
    with open(sql_path, encoding="utf-8") as fh:
        sql_text = fh.read()

    project_id = _read_project_id()
    bound_sql = _bind_sql(sql_text, project_id, bind_keys, bind_vals)

    async with db.lifespan():
        connection = Tortoise.get_connection("default")
        rows = await connection.execute_query_dict(bound_sql)

    if not rows:
        return  # bash-parity: zero rows -> zero bytes of output, either format.
    if fmt == "json":
        typer.echo(json.dumps(rows, indent=2))
    else:
        typer.echo(_render_markdown(rows))


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    raw: list[str] = typer.Argument(
        None,
        metavar="NAME [--json|--md] [--key=val ...]",
        help="Query name (matches skills/context/queries/<name>.sql), then format/bind flags.",
    ),
) -> None:
    """Run a canned ``.sql`` query and print its rows.

    Native port of ``shctx query`` (``cmd_query.sh``). Takes the query
    name as its first token, then any mix of ``--json``, ``--md``, and
    ``--key=val`` bind flags -- captured together as one variadic
    argument (see the module-level ``context_settings`` comment for why)
    and split apart here rather than via separate Typer options, since
    the bind-flag names are not known ahead of time (they come from
    whatever ``:token`` placeholders the named ``.sql`` file happens to
    use).

    Args:
        ctx: The Typer/Click context (unused directly; required so
            ``invoke_without_command`` dispatch works like every other
            single-verb group in this package).
        raw: ``[name, *flags]``, or None/empty if no arguments were
            given at all.

    Raises:
        typer.Exit: Code 1, with bash's exact stderr usage message, if
            ``raw`` is empty (no query name given) -- bash:
            ``[[ -n "$name" ]] || { echo "ERROR: usage: ..." >&2; exit 1; }``.
            Also propagates the code-1 exits raised by
            :func:`_parse_flags` and :func:`_query_async` for a bad flag,
            an unknown query name, or an unresolvable project id.
    """
    del ctx  # required by invoke_without_command dispatch; unused otherwise.
    if not raw:
        typer.echo(_USAGE, err=True)
        raise typer.Exit(code=1)

    name, *flags = raw
    fmt, bind_keys, bind_vals = _parse_flags(flags)
    asyncio.run(_query_async(name=name, fmt=fmt, bind_keys=bind_keys, bind_vals=bind_vals))


__all__ = ["app"]
