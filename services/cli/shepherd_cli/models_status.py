"""Tortoise ORM models mirroring the tables ``shepherd status`` reports on.

ARCHITECTURE — COEXISTENCE (same contract as :mod:`shepherd_cli.models`):
the SQL migrations at ``skills/context/schema/`` (``0001_init.sql`` +
``migrations/*.sql``) are the single schema source of truth. These models
MIRROR tables that already exist there; ``Tortoise.generate_schemas`` is
NEVER called anywhere in this module or its callers.

``cmd_status.sh`` (the bash twin) does not own a single table the way
``cmd_teammate.sh`` owns ``teammates`` — it reads a *summary* across
thirteen tables (row counts) plus five of those again (refresh
staleness via ``refreshed_at``). Two of the thirteen — ``projects`` and
``schema_versions`` — already have models in :mod:`shepherd_cli.models`
(``Project``, ``SchemaVersion``); this module does NOT redeclare them,
it imports them read-only (see ``shepherd_cli/commands/status.py``). The
remaining eleven tables get a minimal model here: only the primary key
(needed for ``COUNT(*)`` via Tortoise's queryset API), plus
``refreshed_at`` on the five tables ``cmd_status.sh``'s "Refresh
staleness" section actually reads. Every other column on every one of
these tables is left completely untouched for the bash tooling that
still owns writes to them.
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class SessionRow(Model):
    """Mirrors the ``sessions`` table (``0001_init.sql``).

    Only ``id`` is declared — ``shepherd status`` only needs
    ``COUNT(*)`` over this table, never an individual column value.
    """

    id = fields.CharField(max_length=64, pk=True)

    class Meta:
        table = "sessions"

    def __str__(self) -> str:
        return f"SessionRow(id={self.id!r})"


class ProfileDef(Model):
    """Mirrors the ``profiles_defs`` table (``0001_init.sql``)."""

    id = fields.CharField(max_length=64, pk=True)

    class Meta:
        table = "profiles_defs"

    def __str__(self) -> str:
        return f"ProfileDef(id={self.id!r})"


# NOTE (integration, v6.3.7): the ``mem_entries`` mirror is NOT redeclared here.
# ``models_mem.MemEntry`` already maps that table, and two model classes mapping
# the same table in one Tortoise app collide — ``status`` imports the canonical
# one from ``models_mem`` instead (it only needs COUNT(*), which any mirror gives).


class IndexSymbol(Model):
    """Mirrors the ``index_symbols`` table (``0001_init.sql``).

    ``refreshed_at`` (epoch SECONDS — written via ``shctx_now`` /
    ``refresh-symbols.sh``, NOT the epoch-millisecond unit
    ``teammates.spawned_at``/``last_seen_at`` use) is declared because
    ``cmd_status.sh``'s "Refresh staleness" section reads
    ``MAX(refreshed_at)`` on this table.
    """

    id = fields.CharField(max_length=64, pk=True)
    refreshed_at = fields.BigIntField()

    class Meta:
        table = "index_symbols"

    def __str__(self) -> str:
        return f"IndexSymbol(id={self.id!r})"


class IndexConcept(Model):
    """Mirrors the ``index_concepts`` table (``0001_init.sql``).

    Not part of the "Refresh staleness" section (it has no
    ``refreshed_at`` column at all) — only ``id`` is needed here for the
    row-count section.
    """

    id = fields.CharField(max_length=64, pk=True)

    class Meta:
        table = "index_concepts"

    def __str__(self) -> str:
        return f"IndexConcept(id={self.id!r})"


class IndexIssue(Model):
    """Mirrors the ``index_issues`` table (``0001_init.sql``).

    ``refreshed_at`` is epoch SECONDS (written via ``shctx_now`` /
    ``refresh-github.sh``); read by the "Refresh staleness" section.
    """

    id = fields.CharField(max_length=64, pk=True)
    refreshed_at = fields.BigIntField()

    class Meta:
        table = "index_issues"

    def __str__(self) -> str:
        return f"IndexIssue(id={self.id!r})"


class IndexPR(Model):
    """Mirrors the ``index_prs`` table (``0001_init.sql``).

    ``refreshed_at`` is epoch SECONDS; read by the "Refresh staleness"
    section.
    """

    id = fields.CharField(max_length=64, pk=True)
    refreshed_at = fields.BigIntField()

    class Meta:
        table = "index_prs"

    def __str__(self) -> str:
        return f"IndexPR(id={self.id!r})"


class IndexRelease(Model):
    """Mirrors the ``index_releases`` table (``0001_init.sql``).

    ``refreshed_at`` is epoch SECONDS; read by the "Refresh staleness"
    section.
    """

    id = fields.CharField(max_length=64, pk=True)
    refreshed_at = fields.BigIntField()

    class Meta:
        table = "index_releases"

    def __str__(self) -> str:
        return f"IndexRelease(id={self.id!r})"


class IndexMilestone(Model):
    """Mirrors the ``index_milestones`` table (``0001_init.sql``).

    ``refreshed_at`` is epoch SECONDS; read by the "Refresh staleness"
    section.
    """

    id = fields.CharField(max_length=64, pk=True)
    refreshed_at = fields.BigIntField()

    class Meta:
        table = "index_milestones"

    def __str__(self) -> str:
        return f"IndexMilestone(id={self.id!r})"


class LogEvent(Model):
    """Mirrors the ``logs_events`` table (``0001_init.sql``).

    ``id`` is an ``INTEGER PRIMARY KEY AUTOINCREMENT`` column, so this
    uses ``IntField`` (matching :class:`shepherd_cli.models.SessionSignal`'s
    autoincrement ``id``), not ``CharField`` like the UUID-keyed tables
    above.
    """

    id = fields.IntField(pk=True)

    class Meta:
        table = "logs_events"

    def __str__(self) -> str:
        return f"LogEvent(id={self.id})"


class Artifact(Model):
    """Mirrors the ``artifacts`` table (``0001_init.sql``)."""

    id = fields.CharField(max_length=64, pk=True)

    class Meta:
        table = "artifacts"

    def __str__(self) -> str:
        return f"Artifact(id={self.id!r})"


class LockHistoryRow(Model):
    """Mirrors the ``locks_history`` table (``0001_init.sql`` + ``0009_locks_mode_sprint.sql``).

    NOT the same thing as the live lock file ``shepherd status`` also
    reports on (``<workdir>/shepherd.lock``, a JSON file read directly
    by ``shepherd_cli/commands/status.py`` — this table is only the
    historical audit log of past lock acquisitions, counted here for
    the "Tables (rows)" section like any other table. ``id`` is an
    ``INTEGER PRIMARY KEY AUTOINCREMENT`` column (rebuilt, same shape,
    by ``0009_locks_mode_sprint.sql``).
    """

    id = fields.IntField(pk=True)

    class Meta:
        table = "locks_history"

    def __str__(self) -> str:
        return f"LockHistoryRow(id={self.id})"


__all__ = [
    "SessionRow",
    "ProfileDef",
    "IndexSymbol",
    "IndexConcept",
    "IndexIssue",
    "IndexPR",
    "IndexRelease",
    "IndexMilestone",
    "LogEvent",
    "Artifact",
    "LockHistoryRow",
]
