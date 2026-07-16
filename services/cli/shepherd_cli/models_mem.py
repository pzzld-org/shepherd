"""Tortoise ORM model mirroring the existing ``mem_entries`` table.

ARCHITECTURE — COEXISTENCE: the SQL migrations under
``skills/context/schema/`` (``0001_init.sql`` + ``migrations/*.sql``) remain
the single schema source of truth. The bash ``shctx mem`` subcommand
(``skills/context/scripts/cmd_mem.sh``) and this Python CLI share the SAME
sqlite database file, so this model MIRRORS a table that already exists —
it sets ``Meta.table`` and this module NEVER calls
``Tortoise.generate_schemas``. Field shapes below match
``0001_init.sql``'s ``mem_entries`` table, with ``kind``'s allowed value
set widened by ``migrations/0011_mem_entries_prior_kind.sql`` (adds
``'prior'``, used by shepherd's self-improvement harvest of audit
findings).

Only the columns ``cmd_mem.sh`` actually reads or writes are declared:
``id``, ``project_id``, ``kind``, ``title``, ``body``, ``tags``,
``pinned``, ``created_at``, ``updated_at``. ``source_path`` (present in the
real table, added for a future artifact-provenance feature) is left
untouched — ``cmd_mem.sh`` never reads or writes it, so it is omitted here
per the port's "only-touched-columns" rule; it remains fully intact on
disk for any other tooling that does use it.
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model

#: Valid values for ``mem_entries.kind`` — the sqlite ``CHECK(kind IN
#: (...))`` constraint from ``0001_init.sql``, widened by migration 0011
#: to add ``'prior'`` (shepherd v6.0.4 #95: self-improvement harvests
#: HIGH/CRITICAL audit_findings into mem_entries as kind='prior' lessons).
#: Not enforced in Python — ``cmd_mem.sh add`` never validates ``--kind``
#: before writing either, it lets the sqlite CHECK constraint itself
#: reject an unknown value at INSERT time (bash-parity: see
#: ``commands/mem.py``'s ``_insert_entry``). Declared here purely as
#: documentation/reference for callers and tests.
MEM_KINDS: tuple[str, ...] = ("doctrine", "note", "decision", "incident", "session", "prior")


class MemEntry(Model):
    """Mirrors the ``mem_entries`` table (``0001_init.sql`` + migration 0011).

    One row of project memory: a titled note/decision/incident/etc. with
    free-text ``body``, a JSON-array ``tags`` string, and a ``pinned``
    flag that keeps it surfaced ahead of recency ordering. Every
    timestamp column here is epoch **seconds** (bash's ``shctx_now`` is
    ``date +%s``) — NOT the epoch-millisecond unit
    :class:`shepherd_cli.models.Teammate` uses for ``spawned_at``/
    ``last_seen_at``. Mixing the two units up is the single easiest way
    to silently corrupt this table; every read/write path in
    :mod:`shepherd_cli.commands.mem` goes through whole seconds.
    """

    id = fields.CharField(max_length=64, pk=True)
    project_id = fields.CharField(max_length=64)
    kind = fields.CharField(max_length=32)
    #: Unbounded ``TEXT NOT NULL`` in the real column (no CHAR length cap
    #: in the schema) — declared as ``TextField`` rather than
    #: ``CharField`` so an arbitrarily long ``--title`` is never at risk
    #: of an accidental Python-side truncation/validation mismatch with
    #: the actual unbounded sqlite column.
    title = fields.TextField()
    body = fields.TextField()
    #: JSON array text, e.g. ``"[]"`` — the sqlite column additionally
    #: carries ``CHECK(json_valid(tags))``, enforced at the DB layer only
    #: (this model does not parse/validate JSON itself, matching
    #: ``cmd_mem.sh``'s own pass-through treatment of ``--tags``).
    tags = fields.TextField(default="[]")
    pinned = fields.IntField(default=0)
    created_at = fields.BigIntField()
    updated_at = fields.BigIntField()

    class Meta:
        table = "mem_entries"

    def __str__(self) -> str:
        return f"MemEntry(id={self.id!r}, kind={self.kind!r}, title={self.title!r})"


__all__ = ["MEM_KINDS", "MemEntry"]
