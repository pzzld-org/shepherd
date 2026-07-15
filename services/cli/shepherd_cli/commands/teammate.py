"""``shepherd teammate`` — liveness, status, and state Typer sub-app.

Thin synchronous Typer commands over the async data layer
(:mod:`shepherd_cli.db`, :mod:`shepherd_cli.queries`). Each command is a sync
function that wraps ``asyncio.run`` around an async implementation using
``db.lifespan`` — Typer/Click commands are called synchronously, but Tortoise
ORM's query API is async, so every command needs exactly one event-loop
boundary. This module owns no data-layer logic itself: scoping (#195),
verdict parity (#193/#200), and schema self-heal all live in
:mod:`shepherd_cli.db`, :mod:`shepherd_cli.queries`, and
:mod:`shepherd_cli.models` — this module only renders their output.
"""

from __future__ import annotations

import asyncio
import json
import time

import typer

from shepherd_cli import db, queries
from shepherd_cli.models import DECLARED_STATES, Teammate
from shepherd_cli.resolution import resolve_session_id
from shepherd_cli.schemas import TeammateLiveness

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Teammate liveness, status, and declared-state commands.",
)

_LIVENESS_COLUMNS = ("teammate_name", "agent_type", "status", "declared", "sec_since_seen", "verdict")
_STATUS_FIELDS = (
    "id",
    "project_id",
    "team_name",
    "teammate_name",
    "agent_type",
    "session_id",
    "tmux_pane_id",
    "spawned_at",
    "last_seen_at",
    "status",
    "metadata",
    "declared_state",
)
_COLUMN_GUTTER = "  "


def _now_ms() -> int:
    """Return the current wall-clock time in epoch milliseconds.

    Returns:
        The current time as milliseconds since the Unix epoch, matching the
        unit used by ``teammates.spawned_at``/``last_seen_at`` (see
        :mod:`shepherd_cli.models`).
    """
    return int(time.time() * 1000)


def _liveness_row(row: Teammate, now_ms: int, stale_ms: int) -> TeammateLiveness:
    """Build the typed liveness view of one teammate row.

    Args:
        row: The Tortoise ``Teammate`` model instance to summarize.
        now_ms: Epoch milliseconds to measure staleness against.
        stale_ms: Staleness threshold in milliseconds, below which an
            undeclared ``booting``/``active`` row still reads ``ok``.

    Returns:
        A :class:`~shepherd_cli.schemas.TeammateLiveness` computed from
        ``row`` at ``now_ms``.
    """
    return TeammateLiveness(
        teammate_name=row.teammate_name,
        agent_type=row.agent_type,
        status=row.status,
        declared_state=row.declared_state,
        sec_since_seen=row.ms_since_seen(now_ms) // 1000,
        verdict=row.verdict(now_ms, stale_ms),
    )


def _render_liveness_table(views: list[TeammateLiveness]) -> str:
    """Render liveness rows as an aligned, fixed-width text table.

    Args:
        views: Typed liveness rows, already in display order.

    Returns:
        A multi-line string: a header row followed by one left-justified,
        whitespace-aligned row per teammate. Columns match
        ``_LIVENESS_COLUMNS`` exactly: teammate_name, agent_type, status,
        declared, sec_since_seen, verdict.
    """
    records = [
        (
            view.teammate_name,
            view.agent_type,
            view.status,
            view.declared_state or "-",
            str(view.sec_since_seen),
            view.verdict,
        )
        for view in views
    ]
    widths = [len(column) for column in _LIVENESS_COLUMNS]
    for record in records:
        for index, value in enumerate(record):
            widths[index] = max(widths[index], len(value))
    lines = [_COLUMN_GUTTER.join(column.ljust(width) for column, width in zip(_LIVENESS_COLUMNS, widths, strict=True))]
    lines.extend(
        _COLUMN_GUTTER.join(value.ljust(width) for value, width in zip(record, widths, strict=True)).rstrip()
        for record in records
    )
    return "\n".join(lines)


async def _liveness_async(stale_mins: int, all_teams: bool, team: str | None, json_out: bool) -> None:
    """Fetch and print teammate liveness.

    Args:
        stale_mins: Minutes of silence before an undeclared ``booting``/
            ``active`` row reads ``presumed-crashed``.
        all_teams: When True, bypass session/team scoping entirely
            (bash-parity legacy `--all`).
        team: When set, scope to this ``team_name`` only, bypassing
            session-based auto-scoping.
        json_out: When True, print a JSON array of
            :class:`~shepherd_cli.schemas.TeammateLiveness` instead of a
            table.
    """
    now_ms = _now_ms()
    stale_ms = stale_mins * 60_000
    async with db.lifespan():
        session_id = resolve_session_id()
        rows = await queries.teammates_live(session_id, include_all=all_teams, team=team)
    views = [_liveness_row(row, now_ms, stale_ms) for row in rows]
    if json_out:
        typer.echo(json.dumps([view.model_dump(mode="json") for view in views], indent=2))
    else:
        typer.echo(_render_liveness_table(views))


@app.command()
def liveness(
    stale_mins: int = typer.Option(
        5,
        "--stale-mins",
        help="Minutes of silence before an undeclared booting/active row reads presumed-crashed.",
    ),
    all: bool = typer.Option(  # noqa: A002 - fixed CLI contract: parameter name mirrors the --all flag.
        False,
        "--all",
        help="Show every teammate across every team/session (bash-parity legacy; bypasses scoping).",
    ),
    team: str | None = typer.Option(
        None,
        "--team",
        help="Show only this team_name, bypassing session-based auto-scoping.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON array of TeammateLiveness objects instead of a table.",
    ),
) -> None:
    """Show liveness for teammates, scoped to the current team/session by default (#195).

    Args:
        stale_mins: Minutes of silence before an undeclared booting/active
            row reads presumed-crashed.
        all: Bypass all scoping and show every teammate (bash-parity legacy).
        team: Restrict to a single team_name, bypassing session scoping.
        json_out: Emit JSON instead of a table.
    """
    asyncio.run(_liveness_async(stale_mins=stale_mins, all_teams=all, team=team, json_out=json_out))


async def _status_async(name: str, json_out: bool) -> None:
    """Fetch and print the latest row for one teammate.

    Args:
        name: The ``teammate_name`` to look up.
        json_out: When True, print a JSON object instead of key:value lines.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if no teammate named
            ``name`` exists.
    """
    async with db.lifespan():
        row = await queries.teammate_status(name)
    if row is None:
        typer.echo(f"ERR: no teammate named {name}", err=True)
        raise typer.Exit(code=1)
    fields = {field: getattr(row, field) for field in _STATUS_FIELDS}
    if json_out:
        typer.echo(json.dumps(fields, indent=2, default=str))
    else:
        for key, value in fields.items():
            typer.echo(f"{key}: {'' if value is None else value}")


@app.command()
def status(
    name: str,
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON object instead of key:value lines.",
    ),
) -> None:
    """Show the latest known row for one teammate.

    Args:
        name: The ``teammate_name`` to look up.
        json_out: Emit JSON instead of key:value lines.
    """
    asyncio.run(_status_async(name=name, json_out=json_out))


async def _state_async(name: str, set_value: str | None) -> None:
    """Optionally declare, then print, a teammate's declared_state.

    Args:
        name: The ``teammate_name`` to read or update.
        set_value: When not None, the new declared_state to set before
            reading (must be one of :data:`shepherd_cli.models.DECLARED_STATES`).

    Raises:
        typer.Exit: With code 2 (and a stderr message) if ``set_value`` is
            not a recognized declared_state.
    """
    async with db.lifespan():
        if set_value is not None:
            try:
                await queries.set_state(name, set_value)
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=2) from exc
        current = await queries.get_state(name)
    typer.echo(current or "")


@app.command()
def state(
    name: str,
    set: str | None = typer.Option(  # noqa: A002 - fixed CLI contract: parameter name mirrors the --set flag.
        None,
        "--set",
        help=f"Declare a new state. One of: {', '.join(DECLARED_STATES)}.",
    ),
) -> None:
    """Read, or declare and read, a teammate's declared_state.

    Args:
        name: The ``teammate_name`` to read or update.
        set: When given, declare this state before reading (must be one of
            DECLARED_STATES); invalid values exit 2 with a stderr message.
    """
    asyncio.run(_state_async(name=name, set_value=set))


__all__ = ["app"]
