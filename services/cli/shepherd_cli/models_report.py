"""Tortoise ORM models mirroring the tables ``shepherd report`` reads.

ARCHITECTURE — COEXISTENCE (same contract as :mod:`shepherd_cli.models`):
the SQL migrations under ``skills/context/schema/`` (``0001_init.sql`` +
``migrations/*.sql``) are the single schema source of truth. These models
MIRROR tables that already exist there; ``Tortoise.generate_schemas`` is
NEVER called anywhere in this module or its callers.

Native port of ``skills/context/scripts/cmd_report.sh`` — a READ-ONLY
markdown-report renderer over four tables (``discovery_findings``,
``audit_findings``, ``escalations``, ``teammates``) plus one view
(``v_escalations_open``), all added by
``migrations/0007_canonical_state.sql``. ``teammates`` already has a model
(:class:`shepherd_cli.models.Teammate`) — this module does NOT redeclare
it (see the COLLISION RULE in that module's docstring); ``commands/
report.py`` imports it read-only instead. The remaining three tables plus
the view each get a minimal model here, declaring ONLY the columns
``cmd_report.sh`` actually SELECTs.

COLLISION RULE (checked before writing this file): grepped
``table = "<name>"`` across every ``shepherd_cli/models*.py`` for
``discovery_findings``, ``audit_findings``, ``escalations``, and
``v_escalations_open`` — none had an existing model, so all four are
declared fresh below.

Timestamp units, for the record (this module never computes with them —
``cmd_report.sh`` only ever relays raw column values verbatim through
``sqlite3``'s text output, and this port does the same): ``discovery_
findings.created_at`` and ``audit_findings.created_at`` are written as
epoch-MILLISECONDS (``ts=$(($(date +%s) * 1000))`` in ``cmd_discovery.sh``/
``cmd_audit.sh``). ``escalations.raised_at`` is read by ``cmd_dash.sh``'s
``_age()`` helper via direct subtraction against ``shctx_now()`` (epoch
SECONDS) with no ``/1000`` anywhere in that arithmetic, so ``raised_at``
(and by extension ``resolved_at``) is epoch-SECONDS — a different unit
than the two ``*_findings`` tables' ``created_at``. Since this command
never does timestamp arithmetic, declaring these as plain ``BigIntField``
(no unit-specific helper methods) is correct either way; the note above
is purely so a future writer-side port does not guess.
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model

#: Valid values for ``audit_findings.severity`` — mirrors the sqlite
#: ``CHECK(severity IN (...))`` constraint in
#: ``migrations/0007_canonical_state.sql``. Not enforced in Python (the
#: underlying CHECK constraint is the actual gate); declared here as the
#: single source of truth for ``commands/report.py``'s severity sort
#: order (``critical`` first, unknown/NULL last).
AUDIT_SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")


class DiscoveryFinding(Model):
    """Mirrors the ``discovery_findings`` table (``0007_canonical_state.sql``).

    One markdown-ready note captured during a discovery run. Only the
    columns ``shctx report discovery`` SELECTs, plus the two columns its
    ``WHERE``/``ORDER BY`` clauses filter and sort on, are declared:
    ``discovery_run``/``sprint_branch`` (filter), ``section``/``created_at``
    (sort), ``title``/``body``/``sources`` (display). ``project_id`` is
    deliberately NOT declared — bash's own query has no project scoping at
    all (``SELECT ... FROM discovery_findings WHERE discovery_run=...``,
    no ``project_id=`` clause), so mirroring that omission here is the
    correct parity choice, not an oversight.
    """

    id = fields.IntField(pk=True)
    sprint_branch = fields.CharField(max_length=255, null=True)
    discovery_run = fields.CharField(max_length=255)
    #: Unbounded ``TEXT`` in the real column (nullable — bash falls back to
    #: ``"General"`` when absent via ``${section:-General}``).
    section = fields.TextField(null=True)
    title = fields.TextField()
    body = fields.TextField()
    #: JSON array/object text (``CHECK(sources IS NULL OR
    #: json_valid(sources))`` at the DB layer), or NULL. Passed through
    #: verbatim, never parsed — matches bash's plain ``$sources``
    #: interpolation.
    sources = fields.TextField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "discovery_findings"

    def __str__(self) -> str:
        return f"DiscoveryFinding(id={self.id}, discovery_run={self.discovery_run!r}, title={self.title!r})"


class AuditFinding(Model):
    """Mirrors the ``audit_findings`` table (``0007_canonical_state.sql``).

    One structured audit finding (hypothesis/falsification/confidence
    framing). Only the columns ``shctx report audit`` SELECTs, plus its
    ``WHERE``/``ORDER BY`` columns, are declared. ``project_id`` is
    omitted for the same bash-parity reason as :class:`DiscoveryFinding`
    — the underlying query has no project scoping.
    """

    id = fields.IntField(pk=True)
    sprint_branch = fields.CharField(max_length=255, null=True)
    concern = fields.CharField(max_length=128)
    severity = fields.CharField(max_length=16)
    hypothesis = fields.TextField()
    falsification = fields.TextField(null=True)
    confidence = fields.CharField(max_length=16, null=True)
    finding = fields.TextField()
    gh_issue = fields.IntField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "audit_findings"

    def __str__(self) -> str:
        return f"AuditFinding(id={self.id}, concern={self.concern!r}, severity={self.severity!r})"


class Escalation(Model):
    """Mirrors the ``escalations`` table (``0007_canonical_state.sql``).

    Backs ``shctx report escalation`` (the non-``--open-only`` branch:
    ``SELECT id, role, question, raised_at, resolved_at FROM escalations
    ORDER BY raised_at DESC``) and the ``close`` composite report's
    ``escalation --open-only`` call, which instead reads
    :class:`EscalationOpen`. Only those five selected columns are
    declared; ``phase``, ``blocking``, ``context_refs``, and
    ``teammate_id`` are untouched by this command and left for the bash
    tooling / :class:`EscalationOpen` (which does need ``phase``).
    """

    id = fields.IntField(pk=True)
    role = fields.CharField(max_length=64)
    question = fields.TextField()
    raised_at = fields.BigIntField()
    resolved_at = fields.BigIntField(null=True)

    class Meta:
        table = "escalations"

    def __str__(self) -> str:
        return f"Escalation(id={self.id}, role={self.role!r})"


class EscalationOpen(Model):
    """Mirrors the ``v_escalations_open`` VIEW (``0007_canonical_state.sql``).

    ``DROP VIEW IF EXISTS v_escalations_open; CREATE VIEW v_escalations_open
    AS SELECT e.*, t.teammate_name, t.team_name FROM escalations e LEFT
    JOIN teammates t ON t.id = e.teammate_id WHERE e.resolved_at IS NULL
    ORDER BY e.raised_at;`` — a read-only projection (unresolved
    escalations only), never written to directly. Tortoise can SELECT
    against a view exactly like a table as long as no write is attempted
    (none is, here), so this is a plain ``Model`` with ``Meta.table``
    pointed at the view name rather than a raw-SQL runner. Backs ``shctx
    report escalation --open-only``, which SELECTs exactly
    ``id, role, phase, question, raised_at`` — declared here, nothing more
    (``teammate_name``/``team_name``/``blocking``/``context_refs``/
    ``teammate_id`` from the view's wider projection are unused by this
    command). ``order_by("raised_at")`` is applied explicitly by the
    query layer rather than relied upon from the view's own embedded
    ``ORDER BY`` — sqlite does not guarantee a view's internal ``ORDER BY``
    survives an outer query verbatim, so bash-parity ordering is asserted
    at the call site instead of assumed here.
    """

    id = fields.IntField(pk=True)
    role = fields.CharField(max_length=64)
    phase = fields.CharField(max_length=64, null=True)
    question = fields.TextField()
    raised_at = fields.BigIntField()

    class Meta:
        table = "v_escalations_open"

    def __str__(self) -> str:
        return f"EscalationOpen(id={self.id}, role={self.role!r})"


__all__ = [
    "AUDIT_SEVERITIES",
    "DiscoveryFinding",
    "AuditFinding",
    "Escalation",
    "EscalationOpen",
]
