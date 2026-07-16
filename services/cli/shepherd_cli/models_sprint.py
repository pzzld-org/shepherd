"""Tortoise ORM model mirroring the existing ``lane_closures`` table.

ARCHITECTURE — COEXISTENCE: same contract as :mod:`shepherd_cli.models`. The
SQL migrations under ``skills/context/schema/`` remain the single schema
source of truth — ``lane_closures`` is created wholesale by
``migrations/0003_canonical_types_filter.sql`` and no later migration
touches it (confirmed by grep across ``skills/context/schema/migrations/``).
This module NEVER calls ``Tortoise.generate_schemas`` and declares ONLY the
columns :mod:`shepherd_cli.commands.sprint` reads (``shepherd sprint
close``'s "close each known lane tied to this sprint" step) — the table
also carries ``resolved_issues``, ``acceptance_log``, ``status``, and
``notes``, all owned exclusively by ``cmd_close-lane.sh`` (not yet ported;
this port only ever shells out to it, never writes this table directly),
so those columns are intentionally omitted per the port contract's hard
rule #2.

COLLISION RULE: grepped ``table = "lane_closures"`` across
``shepherd_cli/models*.py`` before writing this file — no existing model
maps this table (``models.py`` has ``Project``/``SchemaVersion``/
``Teammate``/``SessionSignal``; ``models_status.py`` has the
``index_*``/``sessions``/``profiles_defs``/``artifacts``/``logs_events``/
``locks_history`` models; ``models_mem.py`` has ``MemEntry``;
``models_deliverable.py`` has ``Deliverable``). This is a genuinely new
table for the ORM layer.
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class LaneClosure(Model):
    """Mirrors ``lane_closures`` (``migrations/0003_canonical_types_filter.sql``).

    Per-lane mid-sprint closure ledger. ``cmd_close-lane.sh`` (bash,
    unported) is the sole writer — this model is READ-ONLY from
    :mod:`shepherd_cli.commands.sprint`'s point of view: ``shepherd sprint
    close`` queries it to find lanes tied to the closing sprint branch that
    still need ``cmd_close-lane.sh`` invoked on them, then shells out to
    that bash script per lane (never an ORM ``.create()``/``.save()`` on
    this model).

    Attributes:
        id: ``TEXT PRIMARY KEY`` — a UUIDv7 string minted by ``_lib.sh``'s
            ``shctx_uuid7`` (NOT an autoincrement integer, unlike
            :class:`shepherd_cli.models.SessionSignal` or
            :class:`shepherd_cli.models_deliverable.Deliverable`).
        project_id: FK into ``projects.id`` (plain ``CharField``, matching
            every other model in this package's convention of leaving
            cross-table relations to the SQL layer, not a Tortoise
            ``ForeignKeyField``).
        sprint_branch: The sprint branch this lane closed (or is pending
            closure) under.
        lane_id: The short lane identifier (e.g. ``"lane-3"``,
            ``"wave-2-lane-b"``).
        closed_at: Epoch-SECONDS the lane was closed (``_lib.sh``'s
            ``shctx_now()`` unit — NOT the epoch-milliseconds
            ``deliverables``/``session_signals``/``teammates`` use). The
            schema declares this column ``NOT NULL`` and
            ``cmd_close-lane.sh`` always sets it to ``shctx_now()`` on
            every insert/upsert, so in practice no row here ever actually
            has ``closed_at IS NULL``. ``shepherd sprint close`` still
            issues that exact ``WHERE closed_at IS NULL`` query — bash
            parity means mirroring the query bash wrote, not silently
            "fixing" what looks like a dead branch — so this field is
            declared nullable here purely so Tortoise's
            ``closed_at__isnull=True`` filter is expressible; it does not
            relax the underlying ``NOT NULL`` DB constraint.
    """

    id = fields.CharField(max_length=64, pk=True)
    project_id = fields.CharField(max_length=64)
    sprint_branch = fields.TextField()
    lane_id = fields.TextField()
    closed_at = fields.BigIntField(null=True)

    class Meta:
        table = "lane_closures"

    def __str__(self) -> str:
        return f"LaneClosure(lane_id={self.lane_id!r}, sprint_branch={self.sprint_branch!r})"


__all__ = ["LaneClosure"]
