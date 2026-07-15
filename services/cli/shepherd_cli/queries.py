"""Scoped reads (and the two small teammate writes) — the #195 clean home.

Every function here is async and expects to run inside
``shepherd_cli.db.lifespan()``. This module owns the SCOPING logic that
``liveness`` needs (#195: a fresh spawn must not surface a prior
session's ghost teammates) and the small ``declared_state`` read/write
pair (migration 0019). Verdict computation itself lives on
:class:`shepherd_cli.models.Teammate` — this module only decides WHICH
rows are in scope and in what order, never how a row reads.
"""

from __future__ import annotations

import time

from tortoise.exceptions import OperationalError
from tortoise.queryset import QuerySet

from shepherd_cli.models import DECLARED_STATES, Project, Teammate

#: Statuses ``v_teammates_live`` (migration 0007) excludes:
#: ``WHERE t.status NOT IN ('crashed','retired')``. Every scoping branch
#: below applies this first so Python-side liveness output matches the
#: bash view row-for-row before any team/project narrowing.
_LIVE_STATUSES_EXCLUDED = ("crashed", "retired")

#: Fields safe to select when the underlying table predates migration
#: 0019 and has no ``declared_state`` column yet — used only by the
#: belt-and-suspenders degrade path in :func:`teammates_live`.
_PRE_0019_FIELDS = (
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
)


async def active_project_id() -> str | None:
    """Return the active project's id.

    Bash parity with ``project_id()`` in ``cmd_teammate.sh``:
    ``SELECT id FROM projects LIMIT 1`` — no ``ORDER BY``, so this
    relies on the same table-natural-order "first row" semantics as the
    bash query, not an explicit ranking.

    Returns:
        The first ``projects.id``, or None if no project is registered
        (e.g. ``shctx init`` has not run yet).
    """
    project = await Project.all().first()
    return project.id if project is not None else None


async def _resolve_scoped_team(project_id: str | None, session_id: str | None) -> str | None:
    """Resolve "my" ``team_name`` for the default (unscoped-by-flag) liveness view.

    Implements the #195 fix: prefers the team of the teammate row whose
    ``session_id`` matches the caller's resolved session (so a teammate
    spawned in THIS session sees its own team), else falls back to the
    most-recently-spawned team overall (``MAX(spawned_at)``) — never a
    stale prior-session team just because it happens to sort differently.

    Args:
        project_id: Restrict the lookup to this project when known (from
            :func:`active_project_id`); None searches across all
            projects (only relevant on a DB with no registered project
            yet).
        session_id: The resolved session id
            (:func:`shepherd_cli.resolution.resolve_session_id`), or
            None if unavailable.

    Returns:
        The resolved ``team_name``, or None if the teammates table has
        no rows in scope at all (a brand-new project with nothing
        spawned yet).
    """
    base: QuerySet[Teammate] = Teammate.all()
    if project_id is not None:
        base = base.filter(project_id=project_id)

    if session_id:
        by_session = await base.filter(session_id=session_id).order_by("-spawned_at").first()
        if by_session is not None:
            return by_session.team_name

    most_recent = await base.order_by("-spawned_at").first()
    return most_recent.team_name if most_recent is not None else None


async def _teammates_live_degraded(query: QuerySet[Teammate]) -> list[Teammate]:
    """Belt-and-suspenders (#200): re-run ``query`` without ``declared_state``.

    Only reached when a query against ``teammates`` still raises "no such
    column" for ``declared_state`` after :func:`shepherd_cli.db.lifespan`
    already ran :func:`shepherd_cli.db.ensure_migrated` — i.e. self-heal
    itself failed (fail-soft, so it wouldn't raise). Rather than surface
    a raw ``OperationalError`` to the user, re-select the same filtered
    query using only the columns known to exist on every schema this CLI
    supports (pre-0019), and construct in-memory ``Teammate`` rows with
    ``declared_state=None`` — the same value a genuinely-undeclared row
    would carry, so :meth:`~shepherd_cli.models.Teammate.verdict` falls
    back to the timing heuristic exactly as it would for any other NULL.

    Args:
        query: The already-filtered (status/team/project) queryset that
            just failed when awaited directly.

    Returns:
        Reconstructed ``Teammate`` model instances (not persisted / not
        fetched from the DB again as full model instances — built
        directly from the degraded column set) with
        ``declared_state=None``.
    """
    rows = await query.values(*_PRE_0019_FIELDS)
    return [Teammate(**row, declared_state=None) for row in rows]


async def teammates_live(
    session_id: str | None,
    include_all: bool = False,
    team: str | None = None,
) -> list[Teammate]:
    """Scoped, live teammates — the #195 fix, bash-parity with ``v_teammates_live``.

    Always excludes ``status IN ('crashed','retired')`` first (matching
    the ``v_teammates_live`` view migration 0007 defines), then applies
    exactly one of three mutually exclusive scoping branches:

    1. ``include_all=True`` — no further filter at all (bash-parity
       legacy: every live teammate across every team/project, i.e. what
       ``--all`` requests).
    2. ``team`` is given — filter to ``team_name == team`` only (no
       project filter; this is how ``--team=<ghost>`` reaches a prior
       session's team on purpose).
    3. Default — filter to ``project_id == active_project_id()`` AND
       ``team_name`` resolved via :func:`_resolve_scoped_team` (the
       caller's own session's team if a row matches, else the
       most-recently-spawned team). This is what excludes a prior
       session's ghost teammates on a fresh spawn (#195).

    Args:
        session_id: The resolved session id
            (:func:`shepherd_cli.resolution.resolve_session_id`), used
            only by the default scoping branch to find "my" team.
        include_all: Bypass all team/project scoping (``--all``).
        team: Explicit ``team_name`` filter (``--team``), bypassing
            session-based auto-scoping.

    Returns:
        Matching ``Teammate`` rows ordered by ``ms_since_seen`` DESC
        (stalest first, matching bash's ``ORDER BY ms_since_seen DESC``),
        computed from a single shared ``now_ms`` so the ordering is
        internally consistent within this call.
    """
    now_ms = int(time.time() * 1000)
    query: QuerySet[Teammate] = Teammate.filter(status__not_in=_LIVE_STATUSES_EXCLUDED)

    if include_all:
        pass
    elif team is not None:
        query = query.filter(team_name=team)
    else:
        project_id = await active_project_id()
        if project_id is not None:
            query = query.filter(project_id=project_id)
        resolved_team = await _resolve_scoped_team(project_id, session_id)
        if resolved_team is not None:
            query = query.filter(team_name=resolved_team)

    try:
        rows = list(await query)
    except OperationalError as exc:
        if "no such column" not in str(exc).lower():
            raise
        rows = await _teammates_live_degraded(query)

    rows.sort(key=lambda row: row.ms_since_seen(now_ms), reverse=True)
    return rows


async def teammate_status(name: str) -> Teammate | None:
    """Return the latest row for one teammate, across all teams/projects.

    Bash parity with ``cmd_teammate.sh status``:
    ``SELECT * FROM teammates WHERE teammate_name=? ORDER BY spawned_at
    DESC LIMIT 1`` — deliberately unscoped by team/project/status (a
    "status" lookup should find a teammate even if it has since been
    retired).

    Args:
        name: The ``teammate_name`` to look up.

    Returns:
        The most-recently-spawned matching row, or None if no teammate
        was ever registered under that name. Callers (the ``status``
        Typer command) are expected to treat None as a not-found error.
    """
    return await Teammate.filter(teammate_name=name).order_by("-spawned_at").first()


async def set_state(name: str, state: str) -> None:
    """Declare a teammate's ``declared_state`` (migration 0019).

    Bash parity with ``cmd_teammate.sh state <name> --set=<s>``, including
    validating BEFORE touching the row (an invalid state must never
    partially write). Looks up the SAME most-recently-spawned row
    :func:`teammate_status` would return.

    Args:
        name: The ``teammate_name`` to update.
        state: The new declared state; must be one of
            :data:`shepherd_cli.models.DECLARED_STATES`.

    Raises:
        ValueError: ``state`` is not a recognized declared state (message
            prefixed ``"TEAMMATE-STATE-INVALID: "``, bash-parity with
            ``validate_state``'s stderr message), OR no teammate is
            registered under ``name`` (message prefixed
            ``"TEAMMATE-NOT-FOUND: "``). Both cases raise the same
            exception type deliberately: the ``state`` Typer command
            catches ``ValueError`` uniformly and exits 2 with the message
            on stderr, so a missing teammate must not raise anything the
            command layer isn't already prepared to handle.
    """
    if state not in DECLARED_STATES:
        raise ValueError(
            f"TEAMMATE-STATE-INVALID: '{state}' is not a known state. Known: {' | '.join(DECLARED_STATES)}."
        )
    teammate = await Teammate.filter(teammate_name=name).order_by("-spawned_at").first()
    if teammate is None:
        raise ValueError(f"TEAMMATE-NOT-FOUND: no teammate named '{name}'.")
    teammate.declared_state = state
    await teammate.save(update_fields=["declared_state"])


async def get_state(name: str) -> str | None:
    """Read a teammate's current ``declared_state``.

    Returns None both when the teammate has no declared state (a
    genuinely undeclared row) and when no teammate is registered under
    ``name`` at all — deliberately not raising, so the ``state`` Typer
    command can uniformly ``typer.echo(current or "")`` without a
    try/except for the read path (only the write path,
    :func:`set_state`, raises).

    Args:
        name: The ``teammate_name`` to look up.

    Returns:
        The current ``declared_state``, or None.
    """
    teammate = await Teammate.filter(teammate_name=name).order_by("-spawned_at").first()
    return teammate.declared_state if teammate is not None else None


__all__ = [
    "active_project_id",
    "teammates_live",
    "teammate_status",
    "set_state",
    "get_state",
]
