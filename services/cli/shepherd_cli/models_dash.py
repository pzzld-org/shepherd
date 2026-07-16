"""Tortoise ORM models mirroring the two objects ``shepherd dash`` needs that
no earlier port has mapped yet: the ``focus`` table and the
``v_loops_active`` view.

ARCHITECTURE — COEXISTENCE (same contract as :mod:`shepherd_cli.models`):
the SQL migrations under ``skills/context/schema/`` (``0001_init.sql`` +
``migrations/*.sql``) remain the single schema source of truth. These
models MIRROR objects that already exist there; ``Tortoise.
generate_schemas`` is NEVER called anywhere in this module or its callers.

COLLISION RULE (checked before writing this file): grepped ``table =
"<name>"`` across every ``shepherd_cli/models*.py`` for ``focus`` and
``v_loops_active`` — neither had an existing model, so both are declared
fresh below. Every OTHER table/view ``shepherd dash`` reads is already
mapped elsewhere and imported read-only by
:mod:`shepherd_cli.commands.dash` instead of being redeclared here:
``teammates`` -> :class:`shepherd_cli.models.Teammate`, ``session_signals``
-> :class:`shepherd_cli.models.SessionSignal` (named in the collision list,
though ``dash.py`` ultimately reads it via raw SQL for tie-break parity —
see that module's docstring), ``index_issues``/``index_prs`` ->
:mod:`shepherd_cli.models_status`, ``v_escalations_open`` ->
:class:`shepherd_cli.models_report.EscalationOpen`, ``mem_entries`` ->
:class:`shepherd_cli.models_mem.MemEntry`, ``schema_versions`` ->
:class:`shepherd_cli.models.SchemaVersion`. ``v_sprint_metrics_avg``,
``v_eval_latest``, and the ``eval_runs`` ``sqlite_master`` existence check
are deliberately NOT modeled here either — see
:mod:`shepherd_cli.commands.dash`'s raw-SQL notes for why (SQLite ``ROUND``
parity and an optional/rarely-populated table).
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class Focus(Model):
    """Mirrors the ``focus`` table (``migrations/0013_focus.sql``, reshaped by ``0017_focus_lane.sql``).

    Per-``(sprint, lane)`` north-star record. Migration 0017 changed the
    primary key from bare ``sprint`` to the composite ``(sprint, lane)``
    — Tortoise has no composite-primary-key support, so this model
    instead keys on SQLite's implicit ``rowid``. That is safe here: the
    table is declared as a normal rowid table (0017's ``CREATE TABLE
    focus_new (... PRIMARY KEY (sprint, lane))`` carries no ``WITHOUT
    ROWID`` clause), so every row has a real, unique, always-present
    ``rowid`` regardless of the declared composite PK's shape. This
    model is read-only from ``shepherd dash``'s point of view (only
    ``shepherd_cli.commands.dash._focus_objective`` ever queries it, via
    ``Focus.filter(sprint=...).first()``), so ``rowid`` not being a
    meaningful application-level identifier is immaterial.

    Only ``sprint`` and ``objective`` are declared — the two columns
    ``cmd_dash.sh``'s ``FOCUS`` line actually reads::

        SELECT COALESCE(substr(replace(replace(objective,char(10),' '),
               char(13),' '),1,76),'')
        FROM focus WHERE sprint='$branch' LIMIT 1;

    ``lane``, ``active_node``, ``ready_set``, ``obligations``,
    ``invariants``, and ``updated_at`` are all owned exclusively by
    ``cmd_loop.sh`` (unported; this module never writes this table) and
    are intentionally omitted per hard rule #2.

    Bash's own query has NO ``lane`` filter — it matches ANY row for the
    given ``sprint`` (the sprint-level ``lane=''`` row, or any per-lane
    row) and returns whichever one SQLite's default (no ``ORDER BY``)
    query plan happens to pick first. ``Focus.filter(sprint=...).
    first()`` reproduces that literally: a plain ``SELECT ... WHERE
    sprint=? LIMIT 1`` with no added ordering, so it is subject to the
    exact same SQLite-implementation-defined row choice as the bash
    query — deliberately NOT stabilized with an ``order_by`` bash's own
    query doesn't have either.
    """

    rowid = fields.IntField(pk=True)
    sprint = fields.CharField(max_length=255)
    objective = fields.TextField(null=True)

    class Meta:
        table = "focus"

    def __str__(self) -> str:
        return f"Focus(sprint={self.sprint!r})"


class LoopActive(Model):
    """Mirrors the ``v_loops_active`` VIEW (``migrations/0012_loop_state.sql``).

    ::

        DROP VIEW IF EXISTS v_loops_active;
        CREATE VIEW v_loops_active AS
          SELECT l.id, l.project_id, l.kind, l.task, l.agent,
                 l.max_iterations, l.until_field, l.interval, l.status,
                 l.created_at,
                 COUNT(li.iteration)  AS iterations_recorded,
                 MAX(li.iteration)    AS latest_iteration,
                 SUM(li.new_findings) AS total_findings,
                 MAX(li.recorded_at)  AS last_recorded_at
          FROM loops l
          LEFT JOIN loop_iterations li ON li.loop_id = l.id
          WHERE l.status = 'active'
          GROUP BY l.id;

    A read-only projection (active loops only, pre-aggregated per loop),
    never written to directly. ``id`` (the underlying ``loops.id`` TEXT
    uuid7 primary key, carried through the view's ``SELECT l.id`` and
    ``GROUP BY l.id``) is genuinely unique per row here, unlike
    :class:`Focus`, so it is used as the Tortoise pk directly rather
    than falling back to ``rowid``.

    Only the columns ``shepherd dash``'s ``LOOPS`` section reads are
    declared: ``kind``, ``latest_iteration``, ``max_iterations``,
    ``total_findings`` (plus ``created_at`` for the ``ORDER BY``).
    ``project_id``, ``task``, ``agent``, ``until_field``, ``interval``,
    ``status``, ``iterations_recorded``, and ``last_recorded_at`` are
    all part of the view's wider projection but unused by this command.
    """

    id = fields.CharField(max_length=64, pk=True)
    kind = fields.CharField(max_length=32, null=True)
    max_iterations = fields.IntField()
    latest_iteration = fields.IntField(null=True)
    total_findings = fields.IntField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "v_loops_active"

    def __str__(self) -> str:
        return f"LoopActive(id={self.id!r}, kind={self.kind!r})"


__all__ = ["Focus", "LoopActive"]
