"""Tortoise ORM models mirroring ``eval_runs`` (table) and ``v_eval_latest`` (view).

ARCHITECTURE — COEXISTENCE (same contract as :mod:`shepherd_cli.models`):
the SQL migrations under ``skills/context/schema/`` (``0001_init.sql`` +
``migrations/*.sql``) are the single schema source of truth. These models
MIRROR objects that already exist there — ``eval_runs``/``v_eval_latest``
are both created by ``migrations/0018_eval_runs.sql`` — and
``Tortoise.generate_schemas`` is NEVER called anywhere in this module or
its callers.

Native port of ``skills/context/scripts/cmd_eval.sh``: the shepherd-side
stateful boundary for the eval harness. ``eval run --record`` INSERTs a
verdict row into ``eval_runs``; ``eval report``/``eval list`` read it back
(the former through ``v_eval_latest``, the "latest verdict per (project,
kind, subject_ref)" view; the latter straight off ``eval_runs`` itself).

COLLISION RULE (checked before writing this file): grepped ``table =
"<name>"`` across every ``shepherd_cli/models*.py`` for ``eval_runs`` and
``v_eval_latest`` — neither had an existing model, so both are declared
fresh below. :mod:`shepherd_cli.models_dash` explicitly calls out that IT
deliberately does *not* model either object (its own docstring: "``v_eval_
latest``... deliberately NOT modeled here" — ``shepherd dash`` only ever
needs one pre-formatted summary line + a count, cheaply built as raw SQL
inline in ``commands/dash.py``). This module's needs are different and
wider: ``shepherd eval run --record`` needs a genuine multi-column INSERT
into ``eval_runs`` (id, project_id, kind, subject_ref, score, threshold,
passed, model, scores_json, rationale, created_at — effectively every
column the table has), and ``report``/``list`` need ordered, filtered
SELECTs with every one of those columns projected back out. That is a
"this command owns the table" shape (like
:class:`shepherd_cli.models_mem.MemEntry` or
:class:`shepherd_cli.models_deliverable.Deliverable`), not a narrow
read-scoped projection — so a full mirror model, not a raw-SQL-only
module, is the right shape here, and reused for both tables/objects this
module declares.

**Integration note for whoever wires this module into Tortoise's app
registry:** per this porting wave's hard rule #10 ("DO NOT edit
db.py/app.py/__main__.py — orchestrator's job"), this module is NOT yet
listed in :func:`shepherd_cli.db.lifespan`'s ``modules={"models": [...]}``
dict, and :mod:`shepherd_cli.commands.eval` is not yet registered in
:mod:`shepherd_cli.app`'s ``add_typer`` calls or
:mod:`shepherd_cli.__main__`'s ``PORTED`` set. Every other command group
that introduced a brand-new mirror model (``models_mem``, ``models_sprint``,
``models_dash``, ...) followed the exact same two-step shape: a "port"
pass writes the model + command files, and a separate "integrate" pass
(already the established pattern in this repo's own task history) adds the
three wiring lines. Until that integration lands, :class:`EvalRun`/
:class:`EvalLatest` are syntactically complete and unit-testable in
isolation, but any query issued through them will raise Tortoise's own
"app not configured" error, exactly like every prior new-mirror-model
module did before its own integration pass landed.

Timestamps: ``eval_runs.created_at`` is epoch **SECONDS**
(``cmd_eval.sh``'s ``shctx_now`` == ``date +%s`` — the same unit
:class:`shepherd_cli.models_mem.MemEntry` uses, NOT the epoch-millisecond
unit :class:`shepherd_cli.models.Teammate`/
:class:`shepherd_cli.models_deliverable.Deliverable` use).
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class EvalRun(Model):
    """Mirrors the ``eval_runs`` table (``migrations/0018_eval_runs.sql``).

    One recorded quality verdict for a LATENT agent output (a conductor
    reflection, a discovery report, a seed, ...), scored by
    ``services/eval/eval.sh`` against a named rubric ``kind`` and written
    here by ``shctx eval run --record``. Every column the table declares
    is mirrored (this command is the table's sole owner — no
    ``cmd_*.sh`` other than ``cmd_eval.sh`` itself ever touches it).

    Attributes:
        id: ``TEXT PRIMARY KEY`` — a UUIDv7 string minted by this CLI (or,
            on the bash side, ``_lib.sh``'s ``shctx_uuid7``) at record
            time.
        project_id: FK into ``projects.id`` (plain ``CharField``, matching
            every other model in this package's convention of leaving
            cross-table relations to the SQL layer rather than a Tortoise
            ``ForeignKeyField``).
        kind: The rubric name scored against (e.g. ``"reflection"``,
            ``"discovery"``, ``"seed"`` — one per
            ``services/eval/rubrics/<kind>.rubric.json`` file). Not
            constrained to a fixed set in Python; a rubric file is added
            by dropping a new JSON file in that directory, so this column
            deliberately accepts any string, matching bash's own
            unconstrained ``--kind=`` passthrough.
        subject_ref: What was scored — a sprint branch, a mem entry's
            sprint tag, or an input file's basename. Nullable in the
            schema (bash always supplies *some* string in practice, but
            the column itself carries no ``NOT NULL``).
        score: The deterministic weighted overall, 0..100.
        threshold: The pass line in force when this run was recorded
            (``--threshold`` if given, else the rubric's own default —
            already resolved by the time ``cmd_eval.sh``/this module
            records it, never recomputed here).
        passed: ``1``/``0`` flag (INTEGER, not a Tortoise
            ``BooleanField``, so the raw stored value round-trips
            unchanged through ``--json`` output exactly like ``sqlite3``
            would print it — see :mod:`shepherd_cli.commands.mem`'s
            ``pinned`` column, and
            :mod:`shepherd_cli.models_style`'s ``active`` column, for the
            same convention).
        model: The judge model alias actually used (e.g. ``"opus"``),
            nullable.
        scores_json: The per-dimension ``{dim: 1..scale}`` object, stored
            as COMPACT JSON text (mirrors ``cmd_eval.sh``'s own ``jq -c
            '.scores'`` capture) — never parsed back out by this model;
            callers that need the structured dict decode it themselves.
        rationale: The judge's one-line justification, nullable.
        created_at: Epoch **SECONDS** this verdict was recorded (``_lib.sh``'s
            ``shctx_now`` unit — see the module docstring).
    """

    id = fields.CharField(max_length=64, pk=True)
    project_id = fields.CharField(max_length=64)
    kind = fields.CharField(max_length=64)
    subject_ref = fields.CharField(max_length=255, null=True)
    score = fields.IntField()
    threshold = fields.IntField()
    passed = fields.IntField()
    model = fields.CharField(max_length=64, null=True)
    scores_json = fields.TextField(null=True)
    rationale = fields.TextField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "eval_runs"

    def __str__(self) -> str:
        return f"EvalRun(id={self.id!r}, kind={self.kind!r}, score={self.score})"


class EvalLatest(Model):
    """Mirrors the ``v_eval_latest`` VIEW (``migrations/0018_eval_runs.sql``).

    ::

        DROP VIEW IF EXISTS v_eval_latest;
        CREATE VIEW v_eval_latest AS
          SELECT e.*
          FROM eval_runs e
          WHERE e.id = (
            SELECT e2.id FROM eval_runs e2
            WHERE e2.project_id = e.project_id
              AND e2.kind = e.kind
              AND IFNULL(e2.subject_ref,'') = IFNULL(e.subject_ref,'')
            ORDER BY e2.created_at DESC, e2.id DESC
            LIMIT 1
          );

    A read-only projection — the latest verdict per ``(project_id, kind,
    subject_ref)`` — never written to directly (every INSERT this command
    performs targets :class:`EvalRun`/``eval_runs`` itself; the view
    updates implicitly). Backs ``shctx eval report``, which selects every
    column the view carries (it is a plain ``SELECT e.*``, so the view's
    columns are identical to :class:`EvalRun`'s), so every field is
    mirrored here too rather than a narrower subset. ``order_by`` is
    applied explicitly at the call site (``created_at`` DESC, ``id`` DESC)
    rather than relied upon from the view's own (nonexistent — this view
    has no embedded ``ORDER BY`` at all) definition.
    """

    id = fields.CharField(max_length=64, pk=True)
    project_id = fields.CharField(max_length=64)
    kind = fields.CharField(max_length=64)
    subject_ref = fields.CharField(max_length=255, null=True)
    score = fields.IntField()
    threshold = fields.IntField()
    passed = fields.IntField()
    model = fields.CharField(max_length=64, null=True)
    scores_json = fields.TextField(null=True)
    rationale = fields.TextField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "v_eval_latest"

    def __str__(self) -> str:
        return f"EvalLatest(id={self.id!r}, kind={self.kind!r}, score={self.score})"


__all__ = ["EvalRun", "EvalLatest"]
