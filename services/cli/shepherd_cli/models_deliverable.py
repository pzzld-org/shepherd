"""Tortoise ORM model mirroring the existing ``deliverables`` table.

ARCHITECTURE — COEXISTENCE: same contract as :mod:`shepherd_cli.models`.
The SQL migrations under ``skills/context/schema/`` remain the single
schema source of truth for this table — ``deliverables`` is created
wholesale by ``migrations/0007_canonical_state.sql`` and has never been
touched by a later migration (confirmed by grep: no other
``migrations/*.sql`` file references ``deliverables``). This module NEVER
calls ``Tortoise.generate_schemas`` and declares only the columns
``shepherd deliverable`` reads or writes — every column in the table
happens to be one of those, so the field list below is the full column
set, but that is a property of this particular table, not a license for
other model modules to assume the same.
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model

#: Valid values for ``deliverables.status`` — mirrors the CHECK constraint
#: in ``migrations/0007_canonical_state.sql``:
#: ``CHECK(status IN ('pending','delivered','stalled','aborted'))``. Not
#: enforced in Python (the underlying sqlite CHECK constraint is the
#: actual gate) — documented here for readers of
#: :mod:`shepherd_cli.commands.deliverable`, which only ever writes
#: ``'pending'`` (on ``promise``) and ``'delivered'`` (on ``complete``);
#: ``'stalled'`` and ``'aborted'`` are read-only values from this CLI's
#: point of view, matching ``cmd_deliverable.sh`` (which never writes
#: them either — ``stalled`` is a computed view, not a persisted
#: transition, in the bash tooling as ported here).
DELIVERABLE_STATUSES: tuple[str, ...] = ("pending", "delivered", "stalled", "aborted")


class Deliverable(Model):
    """Mirrors the ``deliverables`` table (``0007_canonical_state.sql``).

    A promise made by one agent session ("I will produce X") tracked
    through to delivery. ``delivered_at`` is nullable because a
    freshly-``promise``d row has not been ``complete``d yet — ``NULL``
    means "still pending" (or, from ``stalled``'s point of view, "pending
    and possibly overdue").

    Attributes:
        id: Autoincrement primary key, echoed back by ``promise`` so the
            caller can later ``complete`` this exact row.
        project_id: FK into ``projects.id``. A plain ``CharField``, not a
            Tortoise ``ForeignKeyField`` — mirrors
            :class:`shepherd_cli.models.Teammate`'s ``project_id``
            convention of leaving cross-table relations to the SQL layer
            rather than modeling them in the ORM.
        agent_session: The promising agent's session id
            (``CLAUDE_SESSION_ID`` at promise time, or ``"unknown"``).
        agent_role: The promising agent's role (``--role``, else
            ``CLAUDE_AGENT_ROLE``, else ``"unknown"``).
        kind: The caller-supplied deliverable kind (free text, e.g.
            ``"pr"``, ``"doc"`` — not constrained by a CHECK in the
            schema).
        target_ref: The caller-supplied reference for what was promised
            (free text — a PR URL, a file path, whatever the caller
            passed as ``--target``).
        promised_at: Epoch-milliseconds when ``promise`` created this row.
        delivered_at: Epoch-milliseconds when ``complete`` marked this row
            delivered, or None while still pending.
        status: One of :data:`DELIVERABLE_STATUSES`. This CLI only ever
            writes ``"pending"`` (on create) and ``"delivered"`` (on
            complete).
    """

    id = fields.IntField(pk=True)
    project_id = fields.CharField(max_length=64)
    agent_session = fields.CharField(max_length=128)
    agent_role = fields.CharField(max_length=64)
    kind = fields.CharField(max_length=64)
    target_ref = fields.TextField()
    promised_at = fields.BigIntField()
    delivered_at = fields.BigIntField(null=True)
    status = fields.CharField(max_length=16, default="pending")

    class Meta:
        table = "deliverables"

    def __str__(self) -> str:
        return f"Deliverable(id={self.id!r}, kind={self.kind!r}, status={self.status!r})"


__all__ = ["DELIVERABLE_STATUSES", "Deliverable"]
