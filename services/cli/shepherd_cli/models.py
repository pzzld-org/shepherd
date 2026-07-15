"""Tortoise ORM models mirroring the existing shepherd SQL tables.

ARCHITECTURE — COEXISTENCE: the SQL migrations at
``skills/context/schema/`` (``0001_init.sql`` + ``migrations/*.sql``) are
the single schema source of truth. The bash ``shctx`` tooling and this
Python CLI share the SAME sqlite database file. These models therefore
MIRROR tables that already exist — every model sets ``Meta.table`` and
this package NEVER calls ``Tortoise.generate_schemas``. Field shapes below
match ``migrations/0007_canonical_state.sql`` (the ``teammates`` table)
and ``migrations/0019_teammate_declared_state.sql`` (``declared_state``).
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model

#: Valid values for ``teammates.declared_state`` (migration 0019). An
#: explicit declaration always wins over the last_seen_at timing
#: heuristic in :meth:`Teammate.verdict`. Mirrors ``cmd_teammate.sh``'s
#: ``DECLARED_STATES="init in-progress error complete idle"``.
DECLARED_STATES: tuple[str, ...] = ("init", "in-progress", "error", "complete", "idle")

#: ``teammates.status`` values a writer ever sets (migration 0007's
#: CHECK constraint). Not exhaustively enforced here — the underlying
#: sqlite CHECK constraint is still the actual gate — but documented for
#: readers of :meth:`Teammate.verdict`.
_STATUS_VALUES: tuple[str, ...] = ("booting", "active", "idle", "crashed", "retired")


class Project(Model):
    """Mirrors the ``projects`` table (``0001_init.sql``).

    Only the columns this CLI actually reads are declared (``id``,
    ``name``) — Tortoise SELECTs exactly its declared fields, so the
    unmirrored columns (``scope``, ``metadata``, ``tags``,
    ``created_at``, ``updated_at``) are simply left untouched by this
    model; they remain fully intact for the bash tooling that owns them.
    """

    id = fields.CharField(max_length=64, pk=True)
    name = fields.CharField(max_length=255, default="")

    class Meta:
        table = "projects"

    def __str__(self) -> str:
        return f"Project(id={self.id!r}, name={self.name!r})"


class SchemaVersion(Model):
    """Mirrors the ``schema_versions`` table (``0001_init.sql``).

    Not required by the #198 teammate surface, but declared for any
    future CLI command that wants to report schema currency without
    shelling out to sqlite3 directly.
    """

    version = fields.IntField(pk=True)
    applied_at = fields.BigIntField()
    checksum = fields.CharField(max_length=64)

    class Meta:
        table = "schema_versions"

    def __str__(self) -> str:
        return f"SchemaVersion(version={self.version})"


class Teammate(Model):
    """Mirrors the ``teammates`` table (``0007_canonical_state.sql`` + ``0019_teammate_declared_state.sql``).

    Identity + liveness record for one teammate spawn. ``declared_state``
    (0019) is nullable because it did not exist before that migration —
    ``NULL`` means "no declaration", which falls back to the
    ``last_seen_at`` timing heuristic in :meth:`verdict`, preserving every
    pre-0019 DB's behavior unchanged.
    """

    id = fields.CharField(max_length=64, pk=True)
    project_id = fields.CharField(max_length=64)
    team_name = fields.CharField(max_length=128)
    teammate_name = fields.CharField(max_length=128)
    agent_type = fields.CharField(max_length=64)
    session_id = fields.CharField(max_length=128, null=True)
    tmux_pane_id = fields.CharField(max_length=32, null=True)
    spawned_at = fields.BigIntField()
    last_seen_at = fields.BigIntField()
    status = fields.CharField(max_length=32)
    metadata = fields.TextField(null=True)
    declared_state = fields.CharField(max_length=32, null=True)

    class Meta:
        table = "teammates"

    def ms_since_seen(self, now_ms: int) -> int:
        """Milliseconds elapsed since this teammate's last heartbeat.

        Args:
            now_ms: The current time in epoch milliseconds. Callers pass
                a single shared ``now_ms`` across a batch of rows so a
                sort by this value is internally consistent (mirrors
                ``v_teammates_live``'s ``ms_since_seen`` column, computed
                there via a single ``strftime('%s','now')`` per query).

        Returns:
            ``now_ms - last_seen_at``. Not clamped to zero — a clock
            skew or a ``now_ms`` older than ``last_seen_at`` surfaces as a
            negative value rather than being silently hidden.
        """
        return now_ms - self.last_seen_at

    def verdict(self, now_ms: int, stale_ms: int) -> str:
        """Compute the liveness verdict for this teammate row.

        Bash-parity with ``cmd_teammate.sh``'s ``liveness`` ``CASE``
        expression (#193/#200) — the exact branch order matters: an
        explicit ``declared_state`` (0019) always wins over the
        ``last_seen_at`` timing heuristic, so a teammate that declared
        ``in-progress`` reads ``ok`` no matter how stale its heartbeat is
        (the #193 false-positive this migration fixed).

        Args:
            now_ms: The current time in epoch milliseconds.
            stale_ms: Staleness threshold in milliseconds (``stale_mins *
                60_000`` at the CLI layer).

        Returns:
            One of ``"ok"``, ``"error"``, ``"complete"``, ``"idle"``, or
            ``"presumed-crashed"``.
        """
        if self.declared_state == "in-progress":
            return "ok"
        if self.declared_state == "error":
            return "error"
        if self.declared_state == "complete":
            return "complete"
        if self.declared_state == "idle":
            return "idle"
        if self.ms_since_seen(now_ms) > stale_ms and self.status in ("booting", "active"):
            return "presumed-crashed"
        return "ok"

    def __str__(self) -> str:
        return f"Teammate(teammate_name={self.teammate_name!r}, team_name={self.team_name!r})"


__all__ = ["DECLARED_STATES", "Project", "SchemaVersion", "Teammate"]
