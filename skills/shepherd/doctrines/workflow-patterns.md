# Workflow Pattern Selection — binding doctrine

Every sprint plan's Stage Graph MUST trace its top-level dispatch structure to
one or more of the **six canonical workflow patterns** defined in
`references/workflow-templates.md`. This doctrine is the binding selection
tree, composition grammar, circuit-breaker invariants, and anti-patterns.

The patterns are the vocabulary the engineer composes from, not guidelines.
A Stage Graph that can't be explained as a pattern composition needs revision.

---

## The principle

> A sprint's Stage Graph is a composition of canonical workflow patterns. The
> engineer declares which patterns apply and how they compose. The conductor
> walks the graph; it does not re-derive pattern selection mid-walk.

1. **Pattern selection happens at planning time.** The engineer chooses
   patterns during Phase 0 seed analysis and encodes them as graph structure.
2. **Every top-level dispatch traces to a pattern.** "Dispatching @discovery"
   without a graph node is off-graph. The conductor must always know its
   pattern context.
3. **Pattern mismatch is a plan defect.** If runtime evidence contradicts the
   selected pattern (e.g. a Fanout-And-Synthesize produces overlapping
   scopes), the conductor halts with PLAN-AMEND — it never adapts silently.

---

## Selection decision tree

The engineer applies this during Phase 0 to assign a pattern to each
top-level flow:

```
Q1: Is the task type determinable from seed evidence alone?
  ├── NO  → PATTERN 1: Classify-And-Act (@discovery classifies; conductor branches on output)
  └── YES → Q2

Q2: Does the task decompose into parallel independent units?
  ├── YES, structurally identical, non-overlapping scopes → PATTERN 2: Fanout-And-Synthesize
  ├── YES, competing approaches, rubric selects best        → PATTERN 4: Generate-And-Filter
  ├── YES, competing approaches, comparative ranking wins   → PATTERN 5: Tournament
  └── NO → Q3

Q3: Does the task produce a high-stakes artifact needing adversarial challenge?
  ├── YES → PATTERN 3: Adversarial Verification (@critic for plan; @auditor swarm for close/intro)
  └── NO → Q4

Q4: Is completion defined by "no new findings" rather than a fixed step count?
  ├── YES → PATTERN 6: Loop-Until-Done (max_iterations + structured new_findings mandatory)
  └── NO  → direct single-agent dispatch (no wrapper; XS-scope or atomic leaf nodes only)
```

**Ambiguous Q2:** default to Pattern 4 unless the rubric requires pairwise
comparison ("which is less confusing" vs "which has higher coverage").
Subjective pairwise → Pattern 5. Objective/scorable → Pattern 4.

---

## Composition grammar

### Legal compositions

| Outer | Inner | Attachment point |
|-------|-------|-------------------|
| Classify-And-Act | Any | Each `on-class-X` branch roots an inner pattern's graph |
| Fanout-And-Synthesize | Adversarial Verification | Synthesis node replaced by a CLOSE-SWARM (Pattern 3 verifier group) |
| Generate-And-Filter | Fanout-And-Synthesize | EXECUTE-WINNER spawns a fanout wave implementing the winner |
| Tournament | Fanout-And-Synthesize | IMPLEMENT-WINNER spawns a fanout wave |
| Loop-Until-Done | Fanout-And-Synthesize | Each ITERATE node fans out sub-tasks before checking findings |
| Loop-Until-Done | Adversarial Verification | Each ITERATE node ends with a verification sub-graph before the findings check |
| Classify-And-Act | Tournament | Classification narrows domain; each class branch runs a tournament |

### Illegal compositions

| Composition | Why forbidden |
|-------------|--------------|
| Generate-And-Filter inside Tournament | Alternative selection mechanisms; nesting compounds cost — pick one |
| Loop-Until-Done inside Fanout iteration body | Needs multi-level `max_iterations`; restructure as one loop with a wider body |
| Adversarial Verification as classifier in Classify-And-Act | Verifiers challenge artifacts, they don't route; use `@discovery` |
| Tournament with N = 2 | Degenerates to a pairwise comparison — use Pattern 3 with `@critic` |

---

## Circuit-breaker invariants

Certain patterns require hard ceilings enforced by the graph, not conductor discipline.

### Pattern 2 — Fanout-And-Synthesize

- **Non-overlapping scope.** No two fanout units touch the same file/module. A
  mid-execution scope conflict halts the conductor — never merges conflicting units.
- **All-or-nothing synthesis.** Fires only when ALL units report. A stalled unit
  surfaces a stall signal before synthesis, never a partial synthesis.
- **Fanout cap.** Max concurrent units = `shepherd.toml [coder].max_parallel_lanes`
  (default 8). Exceeding it is `DISPATCH-OVERFLOW`.

### Pattern 4 — Generate-And-Filter

- **Rubric-before-dispatch.** Must be present in the seed at plant time. A rubric
  assembled after observing outputs is CIRCULAR-RUBRIC — PLAN-AMEND required.
- **Identical brief invariant.** Generator briefs are identical except a `variant`
  field. Divergent briefs make outputs incomparable and void the filter result.

### Pattern 5 — Tournament

- **Bracket declaration.** N, byes, round counts declared in the seed before dispatch.
  Mid-walk changes require PLAN-AMEND.
- **Match isolation.** Each judge reads only its assigned pair — no cross-match
  context. Violation is TOURNAMENT-CONTAMINATION; the match result is void.
- **N ≥ 4 or fallback.** For N = 2, substitute Pattern 3 (single `@critic` pairwise).

### Pattern 6 — Loop-Until-Done

- **`max_iterations` is mandatory.** Absence is `PLAN-MISSING-LOOP-CAP` at preflight.
- **Structured termination field.** The iterator's brief must specify `new_findings:
  true|false` as a top-level report field. Unstructured prose is LOOP-REPORT-INVALID.
- **Cap-exceeded is a halt, not silent exit.** At `iterations >= max_iterations` the
  loop halts with `LOOP-CAP`, surfacing the iteration inventory for the operator to
  extend or accept.
- **Default ceiling: 5 iterations.** >5 requires engineer justification in the plan;
  >10 requires critic sign-off at PLAN-GATE.

---

## Pattern-to-flock alignment

Bindings are invariant — wrong agent for a role is `DISPATCH-WRONG-ROLE`.

| Pattern | Classifier | Producer | Executor | Verifier/Judge | Synthesizer |
|---------|-----------|---------|---------|----------------|-------------|
| 1 Classify-And-Act | `@discovery` | — | `@coder`/`@worker`/`@discovery` | — | — |
| 2 Fanout-And-Synthesize | — | — | `@coder`/`@worker` | — | `@worker` or conductor |
| 3 Adversarial Verification | — | `@engineer`/`@coder`/`@worker` | — | `@critic` (plan) / `@auditor` swarm (close/intro) | Conductor inline |
| 4 Generate-And-Filter | — | — | `@discovery`/`@coder` | `@critic`/`@auditor` | — |
| 5 Tournament | — | — | `@coder`/`@worker`/`@discovery` | `@critic` (pairwise + final) | — |
| 6 Loop-Until-Done | — | — | `@worker`/`@discovery` | — | Conductor inline |

**Hard rules:**
- `@auditor` is a verifier only — never judge, classifier, or synthesizer.
- `@discovery` is read-only — valid as classifier/generator/attempt/iterator ONLY
  for research/orientation output. Never write execution.
- `@engineer`/`@critic` aren't dispatchable by teammate-conductors under
  `/shepherd:spawn` (`doctrines/dispatch-tier-separation.md`); Pattern 3
  (PLAN-GATE) is the primary context. Exception: a self-contained `@engineer`
  teammate runs its own `@critic` in-window (`doctrines/engineer-self-contained-plan.md`)
  — root then runs neither the discovery wave nor `@critic`.

---

## Rigor additions beyond the six patterns

**Checkpoint nodes.** For L/XL sprints with complex compositions, insert
checkpoint nodes at composition boundaries: materialize intermediate state
via `shctx sprint record` and emit `## Checkpoint: <node-id>`. Enables
mid-sprint recovery, operator amendment points, and `shctx doctor` artifact
verification before resume:

```yaml
CHECKPOINT-N (conductor):
  action: shctx sprint record --checkpoint=N --artifacts=[list]
  on-complete: → next pattern entry node
```

**Escalation laddering.** When a pattern's primary path fails, define an
escalation ladder rather than a bare HALT:

| Level | Trigger | Action |
|-------|---------|--------|
| L1 | Single unit fail in Fanout | HOTFIX the failing unit; others continue |
| L2 | Filter/judge tie | Surface to operator for tiebreaker criterion |
| L3 | All candidates fail | HALT with structured failure report |
| L4 | Loop cap exceeded | LOOP-CAP halt; operator extends or accepts |

Every pattern's `on-fail`/`on-all-fail` edge must trace to a declared level.

### Composition depth limit

Nested compositions beyond **three levels** (e.g. Classify → Loop → Fanout →
Adversarial) signal over-engineered scope. Deeper compositions need
justification in the plan's `## Scope rationale`, gated by the critic.
Missing justification → PLAN-GATE REJECT (`COMPOSITION-TOO-DEEP`).

---

## Enforcement surface

| Invariant | Enforced by | Halt code |
|-----------|-------------|-----------|
| Pattern declared in seed | Critic at PLAN-GATE | `PLAN-MISSING-PATTERN` |
| Non-overlapping scope (P2) | Engineer Phase 0 mesh; auditor dependency-topology | `FANOUT-SCOPE-OVERLAP` |
| Rubric before dispatch (P4) | Critic at PLAN-GATE | `CIRCULAR-RUBRIC` |
| Bracket declaration (P5) | Critic at PLAN-GATE | `TOURNAMENT-NO-BRACKET` |
| Match isolation (P5) | Conductor dispatch structure | `TOURNAMENT-CONTAMINATION` |
| `max_iterations` present (P6) | Preflight `shctx doctor`; critic | `PLAN-MISSING-LOOP-CAP` |
| Structured `new_findings` (P6) | Conductor on report receipt | `LOOP-REPORT-INVALID` |
| Wrong agent role for pattern | `hooks/scripts/dispatch_guard.sh` | `DISPATCH-WRONG-ROLE` |
| Composition depth ≤ 3 | Critic at PLAN-GATE | `COMPOSITION-TOO-DEEP` |

---

## Named composite wave templates

Composites are fixed, named instantiations of the six patterns. Use their
full definition when the name appears in a Stage Graph — do not re-derive.

| Name | Pattern | Phase | Key agents |
|------|--------|-------|-----------|
| `INTRO-COMBO-WAVE` | 2 | INTRODUCTION | `@discovery`×N + `@auditor`×M (regression + carry-forward) |
| `DISCOVERY-COMBO-WAVE` | 2 | BODY | `@auditor`×X + `@discovery`×Y + `@worker`×Z (opt.) |
| `HOTFIX-BATCH` | 2 | BODY / CLOSE | `@coder`×H clusters (`H ∈ (1,5]`), root-dispatched |
| `FOCUS-LOOP` | 6 | INTRODUCTION → CLOSE | Orchestrator iterator; wake → act → probe |
| `CONVERGENCE-LOOP` | 6 | BODY / CLOSE | `@coder`/`@worker` iterator; fix → gate-check |
| `WATCH-LOOP` | 6 | BODY / POST-CLOSE | `@worker` probe iterator; wall-clock via `/loop` |

Full definitions: `doctrines/intro-combo-wave.md`, `doctrines/discovery-combo-wave.md`,
`doctrines/hotfix-dispatch.md` (Pattern 2); `references/workflow-templates.md`
FOCUS-LOOP/CONVERGENCE-LOOP/WATCH-LOOP subsections (Pattern 6).

### Pattern-6 composite composition notes

`FOCUS-LOOP`, `CONVERGENCE-LOOP`, `WATCH-LOOP` are all **Loop-OUTER**
composites — the loop is the outermost container, sub-work runs inside each
iteration body. None nests inside a Fanout iteration body, so none triggers
the illegal "Loop-Until-Done inside Fanout" composition.

No new halt codes: they reuse the generic Pattern 6 codes —
`PLAN-MISSING-LOOP-CAP` (missing `max_iterations` at preflight/PLAN-GATE),
`LOOP-REPORT-INVALID` (report omits `new_findings`), `LOOP-CAP` (iterations
exceed the ceiling). The `max_iterations` cap, `shctx loop` backing, and
structured `new_findings` field are mandatory for all three without exception.

---

## See also

- `references/workflow-templates.md` — full pattern definitions, Stage Graph shapes, anti-patterns, composite index
- `doctrines/stage-graph.md` — the plan IS the dispatch contract
- `doctrines/dispatch-tier-separation.md` — tier restrictions on pattern-node dispatch
- `doctrines/pattern-b-overlap.md` — Pattern 2 specialization: WAVE-N-AUDIT ∥ WAVE-(N+1)-IMPL
- `doctrines/hotfix-dispatch.md` — hot-fix cardinality ladder; `(1,5]` is a Pattern-2 fanout, `H≥6` escalates to a dedicated lane
- `doctrines/auditor-hypothesis-driven.md` — Pattern 3 verifier contract
- `doctrines/coordinate-active-drive.md` — Pattern 6 runtime instance at root-shepherd level
- `doctrines/invariant-enforcement-matrix.md` — full invariant coverage map; this doctrine's rows are a subset
- `doctrines/preflight-doctor.md` — `shctx doctor` verifies Pattern 6 cap declarations
- `pipeline.md` — node taxonomy and walk algorithm
