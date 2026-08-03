"""``shepherd status`` — schema version, table row counts, refresh staleness, lock state.

Thin synchronous Typer command over the async data layer
(:mod:`shepherd_cli.db`, :mod:`shepherd_cli.models`,
:mod:`shepherd_cli.models_status`). Native port of
``skills/context/scripts/cmd_status.sh`` — a READ-ONLY summary, so unlike
``shepherd teammate`` this module owns its query functions directly
(inline, per the #198-successor porting notes for single-verb read-only
groups) rather than delegating to :mod:`shepherd_cli.queries`, which is
reserved for cross-command scoping logic that doesn't apply here.

``cmd_status.sh`` prints four sections, in this exact order:

1. ``Schema version: <MAX(version) FROM schema_versions>``
2. ``Tables (rows):`` — one ``COUNT(*)`` line per table, in the bash
   loop's exact order (see :data:`_TABLE_MODELS`).
3. ``Refresh staleness:`` — ``MAX(refreshed_at)`` age in minutes (or
   ``never``) for the five ``index_*`` tables that carry a
   ``refreshed_at`` column.
4. ``Lock: held`` (+ the raw lock JSON, pretty-printed) or ``Lock:
   free`` — read directly from the ``<workdir>/shepherd.lock`` file
   (NOT a database table; see :func:`_read_lock_state`).

This module renders exactly those four sections, in the same order, with
the same column widths (``printf "  %-20s %s\\n"`` bash-parity) and the
same not-found behavior (missing DB file -> stderr + exit 1).

**WRITE-SAFETY (#250): this command is fully READ-ONLY.** It opens the DB
via ``db.lifespan(db_path, migrate=False)`` — it NEVER self-heals/mutates
``schema_versions`` as a side effect of being asked a question, unlike
:func:`shepherd_cli.db.lifespan`'s own default. Before opening the DB it
checks :func:`shepherd_cli.db.schema_is_current`; a behind schema is
refused loudly (one stderr line, exit 1 — see :func:`_status_async`)
rather than silently upgraded or left to surface as a confusing crash.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import typer
from pydantic import BaseModel, ConfigDict
from tortoise.models import Model

from shepherd_cli import db
from shepherd_cli.models import Project, SchemaVersion
from shepherd_cli.models_mem import MemEntry
from shepherd_cli.models_status import (
    Artifact,
    IndexConcept,
    IndexIssue,
    IndexMilestone,
    IndexPR,
    IndexRelease,
    IndexSymbol,
    LockHistoryRow,
    LogEvent,
    ProfileDef,
    SessionRow,
)
from shepherd_cli.resolution import resolve_db_path, resolve_workdir

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    help="Schema version, table row counts, refresh staleness, and lock state.",
)

#: Table name -> mirroring Tortoise model, in the EXACT order
#: ``cmd_status.sh``'s ``for t in projects sessions profiles_defs ...`` loop
#: visits them. ``projects`` reuses the existing
#: :class:`shepherd_cli.models.Project` (imported, not redeclared) — see
#: :mod:`shepherd_cli.models_status` for why the other eleven get a fresh
#: minimal model each.
_TABLE_MODELS: dict[str, type[Model]] = {
    "projects": Project,
    "sessions": SessionRow,
    "profiles_defs": ProfileDef,
    "mem_entries": MemEntry,
    "index_symbols": IndexSymbol,
    "index_concepts": IndexConcept,
    "index_issues": IndexIssue,
    "index_prs": IndexPR,
    "index_releases": IndexRelease,
    "index_milestones": IndexMilestone,
    "logs_events": LogEvent,
    "artifacts": Artifact,
    "locks_history": LockHistoryRow,
}

#: The five tables ``cmd_status.sh``'s "Refresh staleness" section reads,
#: in its exact loop order (a subset of, and reordering-free relative to,
#: ``_TABLE_MODELS``'s own order).
_STALENESS_TABLES: tuple[str, ...] = (
    "index_symbols",
    "index_issues",
    "index_prs",
    "index_releases",
    "index_milestones",
)

_LOCK_FILENAME = "shepherd.lock"
_COLUMN_WIDTH = 20

#: #250 refusal message: this command opens the DB with ``migrate=False``
#: (see the module docstring), so a behind schema is reported this way
#: instead of being silently self-healed.
_SCHEMA_BEHIND_MSG = "schema is behind the shipped migrations; run: shepherd migrate"


class LockState(BaseModel):
    """The ``Lock:`` section of ``shepherd status``.

    Mirrors ``cmd_status.sh``'s check of ``<workdir>/shepherd.lock``
    (NOT a database row — a JSON file ``shctx lock acquire`` writes and
    ``shctx lock release`` removes; see ``cmd_lock.sh``).

    Attributes:
        held: True if the lock file exists (``[[ -f "$lock" ]]``).
        holder: The lock file's ``holder_session_id`` field when held
            and the file parses as JSON with that key; None when free,
            or when the file exists but could not be read/parsed as the
            expected shape (a held-but-unreadable lock still reports
            ``held=True``, matching bash printing whatever ``jq .``
            manages to show).
    """

    model_config = ConfigDict(from_attributes=True)

    held: bool
    holder: str | None = None


class StatusReport(BaseModel):
    """The full ``shepherd status --json`` payload.

    Attributes:
        schema_version: ``MAX(version) FROM schema_versions``, or None
            if the table is empty (bash prints an empty value in that
            case; ``--json`` prints ``null``).
        tables: ``{table_name: row_count}``, one entry per
            :data:`_TABLE_MODELS` key, in that same insertion order.
        staleness: ``{table_name: minutes_since_last_refresh}`` for each
            of :data:`_STALENESS_TABLES`; a value of None means "never
            refreshed" (bash's ``age="never"``), matching
            ``COALESCE(MAX(refreshed_at),0)`` reading as 0.
        lock: The current lock file state.
    """

    model_config = ConfigDict(from_attributes=True)

    schema_version: int | None
    tables: dict[str, int]
    staleness: dict[str, int | None]
    lock: LockState


async def _schema_version() -> int | None:
    """Return ``MAX(version) FROM schema_versions``.

    Returns:
        The highest applied migration version, or None if
        ``schema_versions`` has no rows (an uninitialized/corrupt DB;
        bash-parity with ``SELECT MAX(version) FROM schema_versions;``
        returning SQL NULL). ``version`` is the table's primary key, so
        ordering by it descending and taking the first row is exactly
        equivalent to ``MAX(version)`` without needing a separate
        aggregate query.
    """
    row = await SchemaVersion.all().order_by("-version").first()
    return row.version if row is not None else None


async def _table_counts() -> dict[str, int]:
    """Return ``COUNT(*)`` for every table in :data:`_TABLE_MODELS`.

    Returns:
        A dict keyed by table name, in :data:`_TABLE_MODELS`'s insertion
        order (bash-parity with the ``for t in ...`` loop's print order).
    """
    counts: dict[str, int] = {}
    for name, model in _TABLE_MODELS.items():
        counts[name] = await model.all().count()
    return counts


async def _refresh_staleness(now_s: int) -> dict[str, int | None]:
    """Return refresh-staleness in whole minutes for each staleness table.

    Bash parity with ``cmd_status.sh``'s ``Refresh staleness:`` loop:
    ``last=$(shctx_sql "SELECT COALESCE(MAX(refreshed_at),0) FROM $t;")``
    then, if ``last`` is 0, ``age="never"``, else
    ``age="$(( (now - last) / 60 )) min ago"`` — integer division
    truncating toward zero, matching bash's ``$(( ))`` arithmetic exactly
    (Python's ``int(x / 60)`` truncates toward zero the same way;
    ``//`` would floor toward negative infinity instead and diverge on a
    future-dated ``refreshed_at``).

    Args:
        now_s: The current time in epoch SECONDS — ``refreshed_at`` is
            written via ``shctx_now`` (``date +%s``), NOT the epoch-
            millisecond unit ``teammates.spawned_at``/``last_seen_at``
            use.

    Returns:
        A dict keyed by table name, in :data:`_STALENESS_TABLES` order.
        A value of None means "never refreshed" (bash's ``"never"``);
        otherwise the whole minutes elapsed since the most recent
        ``refreshed_at`` in that table.
    """
    staleness_models: dict[str, type[Model]] = {
        "index_symbols": IndexSymbol,
        "index_issues": IndexIssue,
        "index_prs": IndexPR,
        "index_releases": IndexRelease,
        "index_milestones": IndexMilestone,
    }
    result: dict[str, int | None] = {}
    for name in _STALENESS_TABLES:
        model = staleness_models[name]
        row = await model.all().order_by("-refreshed_at").first()
        last = row.refreshed_at if row is not None else 0
        result[name] = None if last == 0 else int((now_s - last) / 60)
    return result


def _lock_path() -> str:
    """Resolve the live lock file's path.

    Bash parity with ``_lib.sh``'s ``shctx_lock_path``:
    ``$(shctx_artifacts_root)/shepherd.lock``, where
    ``shctx_artifacts_root`` delegates straight to ``resolve_workdir``.

    Returns:
        The absolute path to ``shepherd.lock`` in the resolved shepherd
        work directory (need not exist on disk).
    """
    return os.path.join(resolve_workdir(), _LOCK_FILENAME)


def _read_lock_state() -> tuple[LockState, dict[str, object] | None]:
    """Read the live lock file, if any.

    Bash parity with ``cmd_status.sh``'s lock section:
    ``[[ -f "$lock" ]]`` gates ``held`` vs ``free``; when held, bash
    prints the file's raw contents via ``jq .`` (pretty-printed,
    2-space indent, key order preserved from the file).

    Returns:
        A ``(LockState, raw_dict_or_None)`` pair. ``raw_dict_or_None``
        is the parsed JSON object (for the text renderer to
        pretty-print exactly as ``jq .`` would) when the lock is held
        and parses as a JSON object; None when free, or when the file
        exists but is not valid/object-shaped JSON (``held`` still
        reports True in that case — a corrupt lock file is still a held
        lock, matching bash's ``[[ -f ]]`` check, which does not
        validate JSON shape before reporting ``held``).
    """
    path = _lock_path()
    if not os.path.isfile(path):
        return LockState(held=False, holder=None), None
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return LockState(held=True, holder=None), None
    if not isinstance(raw, dict):
        return LockState(held=True, holder=None), None
    holder = raw.get("holder_session_id")
    return LockState(held=True, holder=holder if isinstance(holder, str) else None), raw


def _render_text(report: StatusReport, raw_lock: dict[str, object] | None) -> str:
    """Render a :class:`StatusReport` as bash-parity plain text.

    Column formatting mirrors ``printf "  %-20s %s\\n" "$t" "$n"``
    exactly: two leading spaces, the name left-justified to 20 columns,
    one space, then the value.

    Args:
        report: The computed status report.
        raw_lock: The parsed lock JSON (for pretty-printing), or None.

    Returns:
        The full multi-line report, matching ``cmd_status.sh``'s section
        order, blank lines, and column widths.
    """
    lines: list[str] = [
        f"Schema version: {report.schema_version if report.schema_version is not None else ''}",
        "",
        "Tables (rows):",
    ]
    lines.extend(f"  {name:<{_COLUMN_WIDTH}} {count}" for name, count in report.tables.items())
    lines.append("")
    lines.append("Refresh staleness:")
    for name in _STALENESS_TABLES:
        minutes = report.staleness.get(name)
        age = "never" if minutes is None else f"{minutes} min ago"
        lines.append(f"  {name:<{_COLUMN_WIDTH}} {age}")
    lines.append("")
    if report.lock.held:
        lines.append("Lock: held")
        if raw_lock is not None:
            lines.append(json.dumps(raw_lock, indent=2))
    else:
        lines.append("Lock: free")
    return "\n".join(lines)


async def _status_async(json_out: bool) -> None:
    """Fetch and print the full status report.

    Args:
        json_out: When True, print a JSON object
            (:class:`StatusReport`) instead of the plain-text report.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if no database
            file exists at the resolved path — bash parity with
            ``cmd_status.sh``'s ``[[ -f "$db" ]] ||`` guard. Checked
            BEFORE opening any Tortoise connection: unlike bash's
            ``sqlite3``, Tortoise's sqlite backend silently creates a
            missing file on connect, which would turn a genuine
            "never initialized" error into a fresh empty database. Also
            code 1 (and a distinct stderr message) if the DB file exists
            but its schema is behind the shipped migrations (#250) — see
            :func:`shepherd_cli.db.schema_is_current`. This command opens
            the DB with ``migrate=False`` (see the module docstring), so
            that check runs BEFORE ``db.lifespan`` instead of relying on
            self-heal to paper over the gap.
    """
    db_path = resolve_db_path()
    if not os.path.isfile(db_path):
        typer.echo(f"ERROR: no DB at {db_path} — run 'shctx init'", err=True)
        raise typer.Exit(code=1)
    if not db.schema_is_current(db_path):
        typer.echo(_SCHEMA_BEHIND_MSG, err=True)
        raise typer.Exit(code=1)

    now_s = int(time.time())
    async with db.lifespan(db_path, migrate=False):
        schema_version = await _schema_version()
        tables = await _table_counts()
        staleness = await _refresh_staleness(now_s)

    lock_state, raw_lock = _read_lock_state()
    report = StatusReport(
        schema_version=schema_version,
        tables=tables,
        staleness=staleness,
        lock=lock_state,
    )
    if json_out:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(_render_text(report, raw_lock))


@app.callback(invoke_without_command=True)
def status(
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON object (schema_version, tables, staleness, lock) instead of the text report.",
    ),
) -> None:
    """Show schema version, table row counts, refresh staleness, and lock state.

    Native port of ``shctx status`` (``cmd_status.sh``) — a read-only
    summary of the project database and its live lock file. Takes no
    positional arguments, matching the bash script.

    Args:
        json_out: Emit JSON instead of the plain-text report.
    """
    asyncio.run(_status_async(json_out=json_out))


__all__ = ["app"]
