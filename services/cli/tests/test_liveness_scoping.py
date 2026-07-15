"""Tests for `shepherd teammate liveness` SCOPING (#195, the "clean home" bug).

Default liveness must show only the current team, excluding stale teammates
left behind by a prior session ("ghost" teammates) — a fresh spawn used to
see a flood of unmatched-team rows from earlier sessions, which is exactly
the field bug #195 fixes. --all and --team=<x> exist as explicit escape
hatches that bypass scoping entirely.
"""

from __future__ import annotations

import json

from conftest import GHOST_TEAM, SeededDb, cli_env, run_cli


def _liveness_names(seeded_db: SeededDb, *, session_id: str | None = None, extra_args: tuple[str, ...] = ()) -> set[str]:
    env = cli_env(seeded_db.db_path, session_id=session_id)
    proc = run_cli(["teammate", "liveness", "--json", *extra_args], env)
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    return {row["teammate_name"] for row in rows}


_CURRENT_TEAM_NAMES = {
    "engineer-inprogress",
    "engineer-undeclared-stale",
    "engineer-undeclared-fresh",
    "engineer-error",
    "engineer-complete",
    "engineer-idle",
}


def test_default_scoping_excludes_ghost_team_with_no_session_set(seeded_db: SeededDb) -> None:
    """With no resolvable session, default scoping falls back to the
    most-recently-spawned team_name — the fresh 'current' team, not the
    30-day-old 'ghost' team."""
    names = _liveness_names(seeded_db)

    assert names == _CURRENT_TEAM_NAMES
    assert "ghost-alpha" not in names


def test_default_scoping_matches_current_session_explicitly(seeded_db: SeededDb) -> None:
    """A resolved session that belongs to the current team scopes to it directly
    (not merely by recency)."""
    names = _liveness_names(seeded_db, session_id=seeded_db.current_session)

    assert names == _CURRENT_TEAM_NAMES
    assert "ghost-alpha" not in names


def test_default_scoping_follows_ghost_session_when_resolved(seeded_db: SeededDb) -> None:
    """A resolved session belonging to the GHOST team scopes to the ghost team —
    session-match wins over "most-recently-spawned team" recency. This is the
    core #195 guarantee: scoping is session-first, not merely a timing heuristic."""
    names = _liveness_names(seeded_db, session_id=seeded_db.ghost_session)

    assert names == {"ghost-alpha"}


def test_all_flag_shows_every_team(seeded_db: SeededDb) -> None:
    """--all is the explicit bash-parity escape hatch: no scoping at all."""
    names = _liveness_names(seeded_db, extra_args=("--all",))

    assert names == _CURRENT_TEAM_NAMES | {"ghost-alpha"}
    assert len(names) == 7


def test_team_flag_shows_only_the_named_team(seeded_db: SeededDb) -> None:
    """--team=<x> bypasses session scoping and shows exactly that team,
    including a team session-scoping would otherwise have excluded."""
    names = _liveness_names(seeded_db, extra_args=("--team", GHOST_TEAM))

    assert names == {"ghost-alpha"}


def test_team_flag_current_team_unaffected_by_ghost_presence(seeded_db: SeededDb) -> None:
    """--team=<current> is unaffected by the ghost team's existence."""
    names = _liveness_names(seeded_db, extra_args=("--team", seeded_db.current_team))

    assert names == _CURRENT_TEAM_NAMES
