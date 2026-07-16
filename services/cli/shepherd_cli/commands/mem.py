"""``shepherd mem`` — project memory (``mem_entries``) Typer sub-app.

Thin synchronous Typer commands over an async data layer, following
:mod:`shepherd_cli.commands.teammate`'s pattern exactly: each command is a
sync function wrapping ``asyncio.run`` around an async implementation
using ``db.lifespan``. Unlike ``teammate.py``, this module is deliberately
SELF-CONTAINED per the port's instructions — its Pydantic output schemas
and its async query functions live inline here rather than in
:mod:`shepherd_cli.schemas` / :mod:`shepherd_cli.queries`.

Bash source of truth: ``skills/context/scripts/cmd_mem.sh`` (subcommands
``add|list|search|show|pin|unpin|rm|delete``), built on
``skills/context/scripts/_lib.sh``'s ``shctx_project_id``/``shctx_now``/
``shctx_sql`` helpers.

Two deliberate, documented deviations from a byte-for-byte bash port:

1. **Project-id resolution.** ``cmd_mem.sh`` resolves ``project_id`` via
   ``shctx_project_id()`` (reads ``.shepherd/project.json`` through
   ``jq``). This module instead mirrors
   ``shepherd_cli.queries.active_project_id()``'s approach — ``SELECT id
   FROM projects LIMIT 1`` against the ``projects`` table — because that
   table is what the shared test harness
   (:func:`tests.conftest.insert_project`) and every other ported
   command group scope through, not the JSON sidecar file. In a healthy
   project the two always resolve to the same id: both are written once,
   together, by ``shctx init``. See :func:`_active_project_id`.
2. **Search pattern escaping.** ``search`` is issued as a raw
   parameterized SQL query (not the Tortoise ORM's ``__contains``
   filter) so the ``LIKE`` pattern is exactly ``'%' || q || '%'`` with no
   wildcard-escaping of a literal ``%``/``_`` in the query text —
   matching ``cmd_mem.sh``'s own ``q_esc="%${Q//\\'/''}%"`` construction,
   which only ever doubles single quotes. Tortoise's ``__contains``
   filter runs every value through ``escape_like()`` first, which would
   silently change search results for a query containing a literal ``%``
   or ``_``. See :func:`_search_entries`.

Note on FTS5: migration ``0004_fts_search.sql`` adds full-text search
virtual tables, but only over ``index_symbols`` and ``artifacts`` —
``mem_entries`` was never wired into FTS5 (grep confirms no
``index_fts_mem`` table or sync triggers exist for it anywhere in
``skills/context/schema/``). ``cmd_mem.sh search`` has therefore always
been a plain ``LIKE '%...%'`` substring match, not an FTS5 query — this
module ports that exact behavior, not a nonexistent FTS one.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import typer
from pydantic import BaseModel, ConfigDict
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError

from shepherd_cli import db
from shepherd_cli.models import Project
from shepherd_cli.models_mem import MemEntry

app = typer.Typer(
    add_completion=False,
    help="Project memory (mem_entries): add, list, search, show, pin, unpin, rm.",
)

#: Verbatim bash-parity error for a missing/unknown subcommand — the ``*)``
#: default branch of ``cmd_mem.sh`` prints this to stderr and exits 1 (mem has
#: no ``""|help)`` branch, so unlike deliverable/signal a bare invocation is an
#: ERROR, not a 0-exit usage print).
_USAGE_ERR = "ERROR: usage: shctx mem <add|list|search|show|pin|unpin|rm>"


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Emit the bash usage error and exit 1 when no subcommand is given.

    Bash parity: ``cmd_mem.sh``'s ``*)`` default case prints
    ``_USAGE_ERR`` to stderr and exits 1 for both an empty and an unknown
    subcommand. Typer's ``no_args_is_help`` would exit 2 to stdout instead, so
    this callback restores the exact contract.

    Args:
        ctx: The Typer/Click context; ``invoked_subcommand`` is None only when
            ``shepherd mem`` is run with no subcommand.

    Raises:
        typer.Exit: code 1, after printing the usage error to stderr.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(_USAGE_ERR, err=True)
        raise typer.Exit(code=1)

#: Column order bash's ``cmd_mem.sh list`` selects, used for both the
#: text-table header and the ``MemEntryListRow`` schema.
_LIST_COLUMNS = ("id", "kind", "title", "pinned", "created_at")
#: Column order bash's ``cmd_mem.sh search`` selects — deliberately
#: narrower than ``list`` (no ``created_at``).
_SEARCH_COLUMNS = ("id", "kind", "title", "pinned")
#: Column order bash's ``cmd_mem.sh show`` selects — every stored column
#: except ``project_id`` and ``source_path``.
_SHOW_COLUMNS = ("id", "kind", "title", "body", "tags", "pinned", "created_at", "updated_at")
#: sqlite3 CLI's own ``-column`` mode gutter (verified empirically: two
#: literal spaces between every column, including before the last one).
_COLUMN_GUTTER = "  "


# --------------------------------------------------------------------------
# Pydantic output schemas.
# --------------------------------------------------------------------------
class MemEntryListRow(BaseModel):
    """One row of ``shepherd mem list`` output.

    Mirrors the columns bash's ``cmd_mem.sh list`` selects: ``id, kind,
    title, pinned, created_at``.

    Attributes:
        id: The entry's UUIDv7-shaped primary key.
        kind: One of :data:`shepherd_cli.models_mem.MEM_KINDS`.
        title: The entry's title.
        pinned: ``1`` if pinned, ``0`` otherwise (the raw stored
            integer, not coerced to ``bool``, so JSON output matches
            what the sqlite column literally holds).
        created_at: Epoch seconds the entry was created.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    pinned: int
    created_at: int


class MemEntrySearchRow(BaseModel):
    """One row of ``shepherd mem search`` output.

    Mirrors the columns bash's ``cmd_mem.sh search`` selects: ``id, kind,
    title, pinned`` — intentionally narrower than :class:`MemEntryListRow`
    (no ``created_at``), matching the bash ``SELECT`` list exactly.

    Attributes:
        id: The entry's UUIDv7-shaped primary key.
        kind: One of :data:`shepherd_cli.models_mem.MEM_KINDS`.
        title: The entry's title.
        pinned: ``1`` if pinned, ``0`` otherwise.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    pinned: int


class MemEntryDetail(BaseModel):
    """The full row of ``shepherd mem show`` output.

    Mirrors every column bash's ``cmd_mem.sh show`` selects: ``id, kind,
    title, body, tags, pinned, created_at, updated_at``.

    Attributes:
        id: The entry's UUIDv7-shaped primary key.
        kind: One of :data:`shepherd_cli.models_mem.MEM_KINDS`.
        title: The entry's title.
        body: The entry's free-text body.
        tags: Raw JSON-array text, e.g. ``"[]"`` (not parsed/decoded —
            printed exactly as stored, matching what sqlite3's ``-column``
            mode would print for the column's literal text).
        pinned: ``1`` if pinned, ``0`` otherwise.
        created_at: Epoch seconds the entry was created.
        updated_at: Epoch seconds the entry was last updated (by
            ``add``, ``pin``, or ``unpin``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    body: str
    tags: str
    pinned: int
    created_at: int
    updated_at: int


# --------------------------------------------------------------------------
# Small stdlib helpers.
# --------------------------------------------------------------------------
def _now() -> int:
    """Return the current wall-clock time in epoch seconds.

    Returns:
        The current time as whole seconds since the Unix epoch, matching
        the unit ``_lib.sh``'s ``shctx_now`` (``date +%s``) uses for
        ``mem_entries.created_at``/``updated_at`` — NOT the millisecond
        unit ``teammates`` uses (see :mod:`shepherd_cli.models_mem`).
    """
    return int(time.time())


def _uuid7() -> str:
    """Generate a UUIDv7 (RFC 9562) id for a new ``mem_entries`` row.

    Bash generates ids via ``_lib.sh``'s ``shctx_uuid7`` (a 48-bit
    millisecond-timestamp-prefixed, timestamp-sortable UUID built from
    ``date +%s%3N`` and ``/dev/urandom``). This is an independent,
    equally-valid UUIDv7 generator over the stdlib ``time``/``os.urandom``
    — it is NOT byte-for-byte identical to bash's construction (different
    random source, different bit-packing helper), but every id it
    produces is a spec-compliant, monotonically-sortable-by-creation-time
    UUIDv7, which is the only property either tool's rows or tests
    actually depend on: uniqueness and rough time-ordering, never an
    exact bit pattern.

    Returns:
        A lowercase, hyphenated UUIDv7 string, e.g.
        ``"018f4d2e-1234-7abc-89de-0123456789ab"``.
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


def _render_sqlite_table(columns: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    """Render rows exactly as sqlite3 CLI's ``-header -column`` mode would.

    ``cmd_mem.sh`` shells out to ``sqlite3 -header -column`` for every
    non-writing subcommand, so bash-parity here means reproducing that
    CLI's own rendering rules (verified empirically against sqlite3
    3.45.1), not this package's own ``teammate.py`` table style (which
    renders a bash-computed ``printf`` table that never went through
    sqlite3's ``-column`` mode in the first place):

    - Each column's width is ``max(len(header), len(cell) for cell in
      rows)`` — computed over ALL rows, not just a sample.
    - Columns are left-justified, padded to their column's width, joined
      by a two-space gutter — including a padded (not right-trimmed)
      LAST column, and including a gutter after every column but the
      last.
    - A row of ``-`` repeated to each column's width, gutter-joined,
      separates the header from the data rows.
    - Zero matching rows produce a completely empty string (sqlite3
      prints not even the header in that case) — callers must skip
      calling ``typer.echo`` entirely when this returns ``""``, since
      ``typer.echo("")`` would print a bare newline sqlite3 never does.

    Args:
        columns: Column header names, in display order.
        rows: Each row's cells, already stringified, in the same column
            order as ``columns``.

    Returns:
        The rendered table (no trailing newline), or ``""`` if ``rows``
        is empty.
    """
    if not rows:
        return ""
    widths = [len(column) for column in columns]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    header = _COLUMN_GUTTER.join(column.ljust(width) for column, width in zip(columns, widths, strict=True))
    separator = _COLUMN_GUTTER.join("-" * width for width in widths)
    body_lines = [
        _COLUMN_GUTTER.join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)) for row in rows
    ]
    return "\n".join([header, separator, *body_lines])


# --------------------------------------------------------------------------
# Inline async data layer (self-contained per the port's instructions).
# --------------------------------------------------------------------------
async def _active_project_id() -> str | None:
    """Return the sole registered project's id, or None if none exists.

    See the module docstring's deviation note #1: this queries the
    ``projects`` table (``SELECT id FROM projects LIMIT 1``, no
    ``ORDER BY`` — same "first row" semantics as
    ``shepherd_cli.queries.active_project_id()``) rather than reading
    ``.shepherd/project.json`` the way ``cmd_mem.sh``'s own
    ``shctx_project_id()`` does.

    Returns:
        The first ``projects.id``, or None if no project is registered.
    """
    project = await Project.all().first()
    return project.id if project is not None else None


async def _require_project_id() -> str:
    """Resolve the active project id, or exit 1 (bash-parity prerequisite gate).

    Bash parity: ``cmd_mem.sh`` computes ``project_id=$(shctx_project_id)``
    UNCONDITIONALLY at the top of the script, before dispatching to any
    subcommand, under ``set -eu -o pipefail`` — so a missing project
    aborts every subcommand (``add``, ``list``, ``search``, ``show``,
    ``pin``, ``unpin``, ``rm``) with exit 1 before any SQL runs, and
    before any subcommand-specific argument validation (e.g. a missing
    ``--title`` never even gets checked if there is no project). Every
    Typer command in this module calls this FIRST, inside
    ``db.lifespan()``, before validating its own arguments, to preserve
    that exact ordering.

    Returns:
        The active project id.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if no project is
            registered.
    """
    project_id = await _active_project_id()
    if project_id is None:
        typer.echo("ERROR: no project registered — run 'shctx init' first", err=True)
        raise typer.Exit(code=1)
    return project_id


async def _insert_entry(project_id: str, kind: str, title: str, body: str, tags: str, now: int) -> str:
    """Insert one ``mem_entries`` row and return its generated id.

    Bash parity with ``cmd_mem.sh add``: ``pinned`` always starts at
    ``0``; ``created_at``/``updated_at`` both get the SAME ``now`` value
    (epoch seconds, matching ``shctx_now``). ``kind``/``tags`` are passed
    through UNVALIDATED, exactly like bash's own pass-through — an
    unknown ``kind`` or invalid-JSON ``tags`` is rejected by the sqlite
    ``CHECK`` constraints at INSERT time, not pre-validated here (see the
    module docstring and :data:`shepherd_cli.models_mem.MEM_KINDS`).

    Args:
        project_id: The owning project's id.
        kind: One of :data:`shepherd_cli.models_mem.MEM_KINDS` (not
            enforced in Python — see above).
        title: The entry's title (caller has already checked non-empty).
        body: The entry's free-text body.
        tags: JSON-array text for the ``tags`` column.
        now: Epoch seconds to stamp both ``created_at`` and
            ``updated_at`` with.

    Returns:
        The newly generated entry id.

    Raises:
        tortoise.exceptions.IntegrityError: If ``kind`` is not one of the
            sqlite ``CHECK(kind IN (...))`` values, or ``tags`` is not
            valid JSON (``CHECK(json_valid(tags))``).
    """
    entry_id = _uuid7()
    await MemEntry.create(
        id=entry_id,
        project_id=project_id,
        kind=kind,
        title=title,
        body=body,
        tags=tags,
        pinned=0,
        created_at=now,
        updated_at=now,
    )
    return entry_id


async def _list_entries(project_id: str) -> list[MemEntry]:
    """All ``mem_entries`` rows for ``project_id``, pinned first then newest first.

    Bash parity: ``SELECT id, kind, title, pinned, created_at FROM
    mem_entries WHERE project_id=? ORDER BY pinned DESC, created_at
    DESC``.

    Args:
        project_id: The owning project's id.

    Returns:
        Matching rows in bash's exact order.
    """
    return await MemEntry.filter(project_id=project_id).order_by("-pinned", "-created_at")


async def _search_entries(project_id: str, query_text: str) -> list[dict[str, object]]:
    """Title/body substring search, bash-parity raw-SQL ``LIKE``.

    See the module docstring's deviation note #2 for why this is a raw
    parameterized query rather than the Tortoise ORM's ``__contains``
    filter: bash's own pattern construction
    (``q_esc="%${Q//\\'/''}%"``) never escapes a literal ``%``/``_`` in
    the search text, only doubles single quotes (and even that quote
    handling is moot here — this query is parameter-bound, not
    string-interpolated, so it needs no escaping of any kind and is safe
    against injection besides).

    Args:
        project_id: The owning project's id.
        query_text: The substring to search for (caller has already
            checked non-empty). Wrapped as ``'%' || query_text || '%'``
            with no wildcard-escaping, matching bash exactly.

    Returns:
        Row dicts with keys ``id, kind, title, pinned``, in bash's exact
        order (``ORDER BY pinned DESC, created_at DESC``, even though
        ``created_at`` itself is not selected).
    """
    connection = Tortoise.get_connection("default")
    pattern = f"%{query_text}%"
    return await connection.execute_query_dict(
        "SELECT id, kind, title, pinned FROM mem_entries "
        "WHERE project_id=? AND (title LIKE ? OR body LIKE ?) "
        "ORDER BY pinned DESC, created_at DESC",
        [project_id, pattern, pattern],
    )


async def _show_entry(project_id: str, entry_id: str) -> MemEntry | None:
    """One ``mem_entries`` row by id, scoped to ``project_id``.

    Bash parity: ``SELECT ... FROM mem_entries WHERE project_id=? AND
    id=?`` — zero matching rows is not an error, it is simply an empty
    result (see :func:`_render_sqlite_table`'s empty-output contract).

    Args:
        project_id: The owning project's id.
        entry_id: The entry id to look up.

    Returns:
        The matching row, or None if no row matches both
        ``project_id`` and ``entry_id``.
    """
    return await MemEntry.filter(project_id=project_id, id=entry_id).first()


async def _set_pinned(project_id: str, entry_id: str, pinned_value: int, now: int) -> None:
    """``UPDATE`` ``pinned``/``updated_at`` for one row — a silent no-op if absent.

    Bash parity with ``cmd_mem.sh``'s ``pin``/``unpin``: a bare
    ``UPDATE ... WHERE id=? AND project_id=?`` with no existence check
    and no output of any kind — an id that matches zero rows still exits
    0 with empty stdout, exactly like a genuinely successful update.

    Args:
        project_id: The owning project's id.
        entry_id: The entry id to update.
        pinned_value: ``1`` for ``pin``, ``0`` for ``unpin``.
        now: Epoch seconds to stamp ``updated_at`` with.
    """
    await MemEntry.filter(project_id=project_id, id=entry_id).update(pinned=pinned_value, updated_at=now)


async def _delete_entry(project_id: str, entry_id: str) -> None:
    """``DELETE`` one row — a silent no-op if ``entry_id`` doesn't match.

    Bash parity with ``cmd_mem.sh``'s ``rm``/``delete``: the DELETE runs
    unconditionally and the confirmation message
    (``"shctx mem rm: removed <id>"``) is printed regardless of whether a
    row actually existed — this function mirrors that by never raising
    or reporting a row count.

    Args:
        project_id: The owning project's id.
        entry_id: The entry id to delete.
    """
    await MemEntry.filter(project_id=project_id, id=entry_id).delete()


# --------------------------------------------------------------------------
# Async command implementations.
# --------------------------------------------------------------------------
async def _add_async(kind: str, title: str, body: str, tags: str) -> None:
    """Validate, insert, and print the new entry's id.

    Args:
        kind: The ``--kind`` value (defaults to ``"note"``, unvalidated —
            see :func:`_insert_entry`).
        title: The ``--title`` value; required, checked AFTER project
            resolution (bash-parity ordering — see
            :func:`_require_project_id`).
        body: The ``--body`` value (defaults to ``""``).
        tags: The ``--tags`` value (defaults to ``"[]"``, unvalidated).

    Raises:
        typer.Exit: Code 1, if no project is registered, if ``title`` is
            empty (bash: ``"ERROR: --title required"``), or if the
            sqlite ``CHECK`` constraints reject ``kind``/``tags``.
    """
    now = _now()
    async with db.lifespan():
        project_id = await _require_project_id()
        if not title:
            typer.echo("ERROR: --title required", err=True)
            raise typer.Exit(code=1)
        try:
            entry_id = await _insert_entry(project_id, kind, title, body, tags, now)
        except IntegrityError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(entry_id)


async def _list_async(json_out: bool) -> None:
    """Fetch and print every entry for the active project.

    Args:
        json_out: When True, print a JSON array of
            :class:`MemEntryListRow` instead of a sqlite3-style table.

    Raises:
        typer.Exit: Code 1, if no project is registered.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        rows = await _list_entries(project_id)
    views = [
        MemEntryListRow(id=row.id, kind=row.kind, title=row.title, pinned=row.pinned, created_at=row.created_at)
        for row in rows
    ]
    if json_out:
        typer.echo(json.dumps([view.model_dump(mode="json") for view in views], indent=2))
        return
    table = _render_sqlite_table(
        _LIST_COLUMNS,
        [(view.id, view.kind, view.title, str(view.pinned), str(view.created_at)) for view in views],
    )
    if table:
        typer.echo(table)


async def _search_async(query_text: str, json_out: bool) -> None:
    """Validate, search, and print matching entries for the active project.

    Args:
        query_text: The ``--q`` value; required, checked AFTER project
            resolution (bash-parity ordering).
        json_out: When True, print a JSON array of
            :class:`MemEntrySearchRow` instead of a sqlite3-style table.

    Raises:
        typer.Exit: Code 1, if no project is registered, or if
            ``query_text`` is empty (bash: ``"ERROR: --q=<text> required
            for mem search"``).
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if not query_text:
            typer.echo("ERROR: --q=<text> required for mem search", err=True)
            raise typer.Exit(code=1)
        rows = await _search_entries(project_id, query_text)
    views = [MemEntrySearchRow(**row) for row in rows]
    if json_out:
        typer.echo(json.dumps([view.model_dump(mode="json") for view in views], indent=2))
        return
    table = _render_sqlite_table(
        _SEARCH_COLUMNS,
        [(view.id, view.kind, view.title, str(view.pinned)) for view in views],
    )
    if table:
        typer.echo(table)


async def _show_async(entry_id: str | None, json_out: bool) -> None:
    """Validate, fetch, and print one entry in full.

    Args:
        entry_id: The positional id argument; required, checked AFTER
            project resolution (bash-parity ordering).
        json_out: When True, print a JSON object of :class:`MemEntryDetail`
            (``null`` if not found) instead of a sqlite3-style table.

    Raises:
        typer.Exit: Code 1, if no project is registered, or if
            ``entry_id`` is missing (bash: ``"ERROR: usage: shctx mem show
            <id>"``). A well-formed but non-matching id is NOT an error
            (bash-parity: zero matching rows is empty output, exit 0 —
            see :func:`_render_sqlite_table`).
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if not entry_id:
            typer.echo("ERROR: usage: shctx mem show <id>", err=True)
            raise typer.Exit(code=1)
        row = await _show_entry(project_id, entry_id)
    view = (
        MemEntryDetail(
            id=row.id,
            kind=row.kind,
            title=row.title,
            body=row.body,
            tags=row.tags,
            pinned=row.pinned,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        if row is not None
        else None
    )
    if json_out:
        typer.echo(json.dumps(view.model_dump(mode="json") if view is not None else None, indent=2))
        return
    if view is None:
        return  # bash-parity: zero rows -> zero output, exit 0.
    table = _render_sqlite_table(
        _SHOW_COLUMNS,
        [
            (
                view.id,
                view.kind,
                view.title,
                view.body,
                view.tags,
                str(view.pinned),
                str(view.created_at),
                str(view.updated_at),
            )
        ],
    )
    typer.echo(table)


async def _pin_async(entry_id: str | None, pinned_value: int, subcommand: str) -> None:
    """Validate, then set ``pinned`` for one entry — no stdout on success.

    Args:
        entry_id: The positional id argument; required, checked AFTER
            project resolution (bash-parity ordering).
        pinned_value: ``1`` for ``pin``, ``0`` for ``unpin``.
        subcommand: ``"pin"`` or ``"unpin"``, used only to build the
            bash-exact usage message (``"shctx mem $sub <id>"``).

    Raises:
        typer.Exit: Code 1, if no project is registered, or if
            ``entry_id`` is missing.
    """
    now = _now()
    async with db.lifespan():
        project_id = await _require_project_id()
        if not entry_id:
            typer.echo(f"ERROR: usage: shctx mem {subcommand} <id>", err=True)
            raise typer.Exit(code=1)
        await _set_pinned(project_id, entry_id, pinned_value, now)
    # No stdout output on success — bash-parity: cmd_mem.sh's pin/unpin
    # case never echoes anything.


async def _rm_async(entry_id: str | None) -> None:
    """Validate, then delete one entry and print the removal confirmation.

    Args:
        entry_id: The positional id argument; required, checked AFTER
            project resolution (bash-parity ordering).

    Raises:
        typer.Exit: Code 1, if no project is registered, or if
            ``entry_id`` is missing. The usage message is always
            ``"shctx mem rm <id>"`` — bash hard-codes ``rm`` in this
            message even when invoked via the ``delete`` alias.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        if not entry_id:
            typer.echo("ERROR: usage: shctx mem rm <id>", err=True)
            raise typer.Exit(code=1)
        await _delete_entry(project_id, entry_id)
    # bash hard-codes "rm" in the confirmation too, even via the "delete" alias.
    typer.echo(f"shctx mem rm: removed {entry_id}")


# --------------------------------------------------------------------------
# Typer commands.
# --------------------------------------------------------------------------
@app.command()
def add(
    title: str = typer.Option("", "--title", help="Entry title (required)."),
    kind: str = typer.Option(
        "note",
        "--kind",
        help="Entry kind: doctrine | note | decision | incident | session | prior.",
    ),
    body: str = typer.Option("", "--body", help="Entry body text."),
    tags: str = typer.Option("[]", "--tags", help="JSON array of tags, e.g. '[\"a\",\"b\"]'."),
) -> None:
    """Insert a new mem_entries row and print its generated id.

    Args:
        title: The entry title; required (bash: exits 1 with
            ``"ERROR: --title required"`` if empty).
        kind: The entry kind; defaults to ``"note"``, unvalidated in
            Python (the sqlite ``CHECK`` constraint is the real gate).
        body: The entry body text; defaults to ``""``.
        tags: JSON-array tags text; defaults to ``"[]"``, unvalidated in
            Python.
    """
    asyncio.run(_add_async(kind=kind, title=title, body=body, tags=tags))


@app.command("list")
def list_cmd(
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON array of MemEntryListRow objects instead of a table.",
    ),
) -> None:
    """List every mem_entries row for the active project, pinned first.

    Args:
        json_out: Emit JSON instead of a sqlite3-style table.
    """
    asyncio.run(_list_async(json_out=json_out))


@app.command()
def search(
    q: str = typer.Option("", "--q", help="Substring to search for in title or body (required)."),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON array of MemEntrySearchRow objects instead of a table.",
    ),
) -> None:
    """Search mem_entries by title/body substring match (plain LIKE, not FTS).

    Args:
        q: The search substring; required (bash: exits 1 with
            ``"ERROR: --q=<text> required for mem search"`` if empty).
        json_out: Emit JSON instead of a sqlite3-style table.
    """
    asyncio.run(_search_async(query_text=q, json_out=json_out))


@app.command()
def show(
    id: str | None = typer.Argument(None, help="The mem_entries id to show."),  # noqa: A002 - fixed CLI contract: positional name mirrors bash's <id>.
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON object of MemEntryDetail instead of a table.",
    ),
) -> None:
    """Show one mem_entries row in full, by id.

    Args:
        id: The entry id to show; required (bash: exits 1 with
            ``"ERROR: usage: shctx mem show <id>"`` if omitted). A
            well-formed but non-matching id is not an error.
        json_out: Emit JSON instead of a sqlite3-style table.
    """
    asyncio.run(_show_async(entry_id=id, json_out=json_out))


@app.command()
def pin(
    id: str | None = typer.Argument(None, help="The mem_entries id to pin."),  # noqa: A002
) -> None:
    """Set pinned=1 on one mem_entries row (silent no-op if id doesn't match).

    Args:
        id: The entry id to pin; required (bash: exits 1 with
            ``"ERROR: usage: shctx mem pin <id>"`` if omitted).
    """
    asyncio.run(_pin_async(entry_id=id, pinned_value=1, subcommand="pin"))


@app.command()
def unpin(
    id: str | None = typer.Argument(None, help="The mem_entries id to unpin."),  # noqa: A002
) -> None:
    """Set pinned=0 on one mem_entries row (silent no-op if id doesn't match).

    Args:
        id: The entry id to unpin; required (bash: exits 1 with
            ``"ERROR: usage: shctx mem unpin <id>"`` if omitted).
    """
    asyncio.run(_pin_async(entry_id=id, pinned_value=0, subcommand="unpin"))


@app.command("rm")
def rm(
    id: str | None = typer.Argument(None, help="The mem_entries id to delete."),  # noqa: A002
) -> None:
    """Delete one mem_entries row and print a removal confirmation.

    Bash alias: ``cmd_mem.sh`` accepts both ``rm`` and ``delete`` for this
    subcommand — see the separate :func:`delete` command below, which
    wraps the exact same implementation.

    Args:
        id: The entry id to delete; required (bash: exits 1 with
            ``"ERROR: usage: shctx mem rm <id>"`` if omitted).
    """
    asyncio.run(_rm_async(entry_id=id))


@app.command("delete")
def delete(
    id: str | None = typer.Argument(None, help="The mem_entries id to delete."),  # noqa: A002
) -> None:
    """Delete one mem_entries row and print a removal confirmation (alias of ``rm``).

    Args:
        id: The entry id to delete; required (bash: exits 1 with
            ``"ERROR: usage: shctx mem rm <id>"`` if omitted — bash
            hard-codes ``rm`` in this message even via this alias).
    """
    asyncio.run(_rm_async(entry_id=id))


__all__ = ["app"]
