"""Pydantic v2 typed I/O for the shepherd CLI.

Boundary types for serializing Tortoise model data out to ``--json``
output. Kept deliberately thin — one schema per CLI-facing shape, no
business logic. The scoping/verdict logic itself lives in
:mod:`shepherd_cli.models` and :mod:`shepherd_cli.queries`; these classes
only describe what crosses the process boundary.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TeammateLiveness(BaseModel):
    """One row of ``shepherd teammate liveness`` output.

    Mirrors the columns bash's ``cmd_teammate.sh liveness`` prints:
    ``teammate_name  agent_type  status  declared  sec_since_seen
    verdict`` — field names here use the Python-side names
    (``declared_state`` instead of ``declared``) since this is the typed
    shape, not the rendered table; the CLI table renderer maps
    ``declared_state or "-"`` to the bash ``declared`` column itself.

    Attributes:
        teammate_name: The teammate's registered name.
        agent_type: The role/type the teammate registered with (e.g.
            ``shepherd:conductor``).
        status: The machine-written lifecycle status (``booting``,
            ``active``, ``idle``, ``crashed``, ``retired``).
        declared_state: The explicit progress declaration (migration
            0019), or None when undeclared.
        sec_since_seen: Seconds since the last heartbeat
            (``ms_since_seen // 1000``).
        verdict: The computed liveness verdict — see
            :meth:`shepherd_cli.models.Teammate.verdict`.
    """

    model_config = ConfigDict(from_attributes=True)

    teammate_name: str
    agent_type: str
    status: str
    declared_state: str | None
    sec_since_seen: int
    verdict: str


__all__ = ["TeammateLiveness"]
