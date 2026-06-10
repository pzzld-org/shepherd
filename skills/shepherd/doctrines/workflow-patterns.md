# Workflow Pattern Selection — binding doctrine

Every sprint plan's Stage Graph MUST trace its top-level dispatch structure to one or more of the **six canonical workflow patterns** defined in `references/workflow-templates.md`. This doctrine provides the binding selection decision tree, composition grammar, circuit-breaker invariants, and anti-patterns for the pattern system.

The patterns are not guidelines — they are the vocabulary the engineer is authorized to compose from. A Stage Graph whose dispatch structure cannot be explained as a pattern composition is a Stage Graph that needs revision.

---

## The principle

> A sprint's Stage Graph is a composition of canonical workflow patterns. The engineer declares which patterns apply and how they compose. The conductor walks the graph; it does not re-derive the pattern selection mid-walk.

Three corollaries:

1. **Pattern selection happens at planning time.** The engineer chooses patterns during Phase 0 seed analysis and encodes them as graph structure. The conductor does not choose patterns — it walks the graph the engineer emitted.
2. **Every top-level dispatch traces to a pattern.** "I'm dispatching @discovery now" without a graph node is off-graph. "I'm walking the CLASSIFY node of a Classify-And-Act pattern" is on-graph. The conductor must always know its pattern context.
3. **Pattern mismatch is a plan defect.** If the runtime evidence contradicts the selected pattern (e.g., a Fanout-And-Synthesize pattern produces overlapping scopes), the conductor halts and surfaces a PLAN-AMEND request — it does not adapt the pattern silently.

---

## Selection decision tree

The engineer applies this tree during Phase 0 seed analysis to assign a pattern to each top-level flow in the plan:

```
Q1: Is the task type determinable from seed evidence alone?
  │
  ├── NO → PATTERN 1: Classify-And-Act (routing prefix)
  │         @discovery classifies first; conductor branches on classification output
  │
  └── YES → Q2

Q2: Does the task decompose into parallel independent units?
  │
  ├── YES, structurally identical units (non-overlapping scopes)
  │    → PATTERN 2: Fanout-And-Synthesize
  │
  ├── YES, competing alternative approaches — rubric selects best
  │    → PATTERN 4: Generate-And-Filter
  │
  ├── YES, competing alternatives — comparative ranking more reliable than rubric
  │    → PATTERN 5: Tournament
  │
  └── NO → Q3

Q3: Does the task produce a high-stakes artifact requiring independent adversarial challenge?
  │
  ├── YES → PATTERN 3: Adversarial Verification
  │         (@critic for plan gate; @auditor swarm for close or intro mode)
  │
  └── NO → Q4

Q4: Is completion defined by "no new findings" rather than a fixed number of steps?
  │
  ├── YES → PATTERN 6: Loop-Until-Done
  │         (max_iterations mandatory; structured new_findings field mandatory)
  │
  └── NO → direct single-agent dispatch
            (no pattern wrapper; valid only for XS-scope tasks or atomic leaf nodes)
```

**Default for ambiguous cases:** when the engineer cannot clearly resolve Q2 into Pattern 4 vs 5, use Pattern 4 unless the rubric requires pairwise comparison ("which is less confusing to a new user" vs "which has higher coverage"). Pairwise subjective ranking → Pattern 5. Objective scorable criteria → Pattern 4.

---

## Composition grammar

Patterns compose hierarchically. Each composed pattern contributes one or more Stage Graph nodes.

### Legal compositions

| Outer pattern | Inner pattern | Attachment point |
|--------------|--------------|-----------------|
| Classify-And-Act | Any | Each `on-class-X` branch is the root of an inner pattern's graph |
| Fanout-And-Synthesize | Adversarial Verification | Synthesis node is replaced by a CLOSE-SWARM (Pattern 3 verifier group) |
| Generate-And-Filter | Fanout-And-Synthesize | EXECUTE-WINNER node spawns a fanout wave (Pattern 2) implementing the winning design |
| Tournament | Fanout-And-Synthesize | IMPLEMENT-WINNER node spawns a fanout wave (Pattern 2) |
| Loop-Until-Done | Fanout-And-Synthesize | Each ITERATE node fans out parallel sub-tasks (Pattern 2) before checking findings |
| Loop-Until-Done | Adversarial Verification | Each ITERATE node ends with a verification sub-graph (Pattern 3) before the findings check |
| Classify-And-Act | Tournament | Classification narrows domain; each class branch runs a tournament |

### Illegal compositions

These compositions are structurally unsound and forbidden in the Stage Graph:

| Composition | Why forbidden |
|-------------|--------------|
| Generate-And-Filter **inside** Tournament | Filter and tournament are alternative selection mechanisms; nesting them compounds verification cost without benefit — choose one |
| Loop-Until-Done **inside** Fanout-And-Synthesize iteration body | A loop whose body is another loop requires multi-level `max_iterations` caps; instead, restructure as a single loop with a wider body |
| Adversarial Verification as the **classifier** in Classify-And-Act | Adversarial verifiers do not route tasks; they challenge artifacts. Use `@discovery` for classification |
| Pattern 5 (Tournament) with only N = 2 attempts | Degenerates to a single pairwise comparison — use Pattern 3 (Adversarial Verification) with `@critic` as the verifier |

---

## Circuit-breaker invariants

Certain patterns require hard ceilings enforced by the graph, not by conductor discipline.

### Pattern 2 — Fanout-And-Synthesize

- **Non-overlapping scope guarantee.** The engineer must verify that no two fanout units touch the same file or module. If a scope conflict is discovered mid-execution, the conductor halts — does NOT merge conflicting units.
- **All-or-nothing synthesis.** Synthesis fires only when ALL fanout units have reported. If any unit stalls, the conductor surfaces a stall signal before synthesis — never synthesizes partial results.
- **Fanout cap.** Maximum concurrent units = `shepherd.toml [coder].max_parallel_lanes` (default: 8). Exceeding this limit is a DISPATCH-OVERFLOW halt.

### Pattern 4 — Generate-And-Filter

- **Rubric-before-dispatch.** The rubric must be present in the seed at plant time. A rubric assembled after observing generator outputs is CIRCULAR-RUBRIC — a PLAN-AMEND is required.
- **Identical brief invariant.** Generator briefs must be identical except for a `variant` seed field. Divergent briefs produce incomparable outputs; the filter result is invalid.

### Pattern 5 — Tournament

- **Bracket declaration.** The bracket structure (N, bye assignments, round counts) must be declared in the seed before dispatch. Mid-walk bracket changes require PLAN-AMEND.
- **Match isolation.** Each judge (pairwise or final) reads only its assigned pair — no cross-match context. Violation is TOURNAMENT-CONTAMINATION; the affected match result is void.
- **N ≥ 4 or fallback.** For N = 2, substitute Pattern 3 (single `@critic` pairwise). Tournament overhead is unjustified for a two-way comparison.

### Pattern 6 — Loop-Until-Done

- **`max_iterations` is mandatory.** Every loop graph node must declare a numeric ceiling in the seed. Absence is a PLAN-MISSING-LOOP-CAP halt at preflight.
- **Structured termination field.** The iterator agent's brief must specify that it emit `new_findings: true|false` as a top-level field in its report. Unstructured prose reports are LOOP-REPORT-INVALID.
- **Cap-exceeded is a halt, not silent exit.** When `iterations >= max_iterations`, the loop terminates with a `LOOP-CAP` halt — the operator is surfaced with the iteration inventory and asked whether to extend the cap or accept the current state.
- **Default ceiling: 5 iterations.** Any value > 5 requires explicit engineer justification in the plan. Values > 10 require critic sign-off at PLAN-GATE.

---

## Pattern-to-flock alignment

Each pattern has a canonical flock binding. These bindings are invariant — using the wrong agent type for a role is a DISPATCH-WRONG-ROLE halt per `doctrines/dispatch-tier-separation.md`.

| Pattern | Classifier/Router | Producer | Executor | Verifier/Judge | Synthesizer |
|---------|------------------|---------|---------|----------------|-------------|
| 1 Classify-And-Act | `@discovery` | — | `@coder`/`@worker`/`@discovery` | — | — |
| 2 Fanout-And-Synthesize | — | — | `@coder`/`@worker` | — | `@worker` or conductor |
| 3 Adversarial Verification | — | `@engineer`/`@coder`/`@worker` | — | `@critic` (plan) / `@auditor` swarm (close/intro) | Conductor inline |
| 4 Generate-And-Filter | — | — | `@discovery`/`@coder` | `@critic` / `@auditor` | — |
| 5 Tournament | — | — | `@coder`/`@worker`/`@discovery` | `@critic` (pairwise + final) | — |
| 6 Loop-Until-Done | — | — | `@worker`/`@discovery` | — | Conductor inline |

**Hard rules:**
- `@auditor` is a VERIFIER, never a judge (Pattern 5), never a classifier (Pattern 1), never a synthesizer.
- `@discovery` is read-only — valid as classifier (Pattern 1), generator (Pattern 4), attempt (Pattern 5), or iterator (Pattern 6) ONLY for research/orientation output. Never for write execution.
- `@engineer` and `@critic` are root-tier-exclusive under `/shepherd:spawn` per `doctrines/dispatch-tier-separation.md`. Pattern 3 (PLAN-GATE) is the primary context; they are NOT dispatched by teammate-conductors.

---

## Rigor additions beyond the six patterns

Three refinements strengthen any pattern composition:

### Checkpoint nodes

For L/XL sprints with complex compositions (e.g., Loop containing Fanout containing Adversarial Verification), insert explicit **checkpoint nodes** at composition boundaries. A checkpoint node materializes intermediate state to the context registry (`shctx sprint record`) and emits a `## Checkpoint: <node-id>` section to the walk trace. Benefits:
- Mid-sprint recovery starts from the last checkpoint, not from scratch.
- Operator surfacing at checkpoints gives natural amendment opportunities.
- `shctx doctor` can verify checkpoint artifact existence before resuming.

Declare checkpoint nodes in the Stage Graph as:
```yaml
CHECKPOINT-N (conductor):
  action: shctx sprint record --checkpoint=N --artifacts=[list]
  on-complete: → next pattern entry node
```

### Escalation laddering

When a pattern's primary path fails (e.g., all Generate-And-Filter candidates fail the rubric), define an **escalation ladder** in the graph rather than a bare HALT:

| Level | Trigger | Action |
|-------|---------|--------|
| L1 | Single unit fail in Fanout | HOTFIX the failing unit; other units continue |
| L2 | Filter/judge tie | Surface to operator for tiebreaker criterion |
| L3 | All candidates fail | HALT with structured failure report; operator reprompts |
| L4 | Loop cap exceeded | LOOP-CAP halt; operator extends cap or accepts current state |

Every pattern's `on-fail` and `on-all-fail` edges must trace to a declared escalation level, not an unconstrained HALT.

### Composition depth limit

Nested pattern compositions beyond **three levels** (e.g., Classify → Loop → Fanout → Adversarial) indicate over-engineered sprint scope. The engineer must justify compositions deeper than three levels in the plan's `## Scope rationale` section. The critic gates this justification. If the justification is absent, PLAN-GATE returns REJECT with code `COMPOSITION-TOO-DEEP`.

---

## Enforcement surface

| Invariant | Enforced by | Halt code |
|-----------|-------------|-----------|
| Pattern declared in seed | Critic at PLAN-GATE | `PLAN-MISSING-PATTERN` |
| Non-overlapping scope (Pattern 2) | Engineer Phase 0 mesh; auditor dependency-topology concern | `FANOUT-SCOPE-OVERLAP` |
| Rubric before dispatch (Pattern 4) | Critic at PLAN-GATE | `CIRCULAR-RUBRIC` |
| Bracket declaration (Pattern 5) | Critic at PLAN-GATE | `TOURNAMENT-NO-BRACKET` |
| Match isolation (Pattern 5) | Conductor dispatch structure (parallel_with; no cross-read) | `TOURNAMENT-CONTAMINATION` |
| `max_iterations` present (Pattern 6) | Preflight `shctx doctor`; critic at PLAN-GATE | `PLAN-MISSING-LOOP-CAP` |
| Structured `new_findings` field (Pattern 6) | Conductor on loop iteration report receipt | `LOOP-REPORT-INVALID` |
| Wrong agent role for pattern | Dispatch guard (`hooks/scripts/dispatch_guard.sh`) | `DISPATCH-WRONG-ROLE` |
| Composition depth ≤ 3 | Critic at PLAN-GATE | `COMPOSITION-TOO-DEEP` |

---

## Named composite wave templates

Composites are fixed, named instantiations of the six patterns. When a composite name
appears in a Stage Graph, use its full definition — do not re-derive or improvise.

| Name | Pattern basis | Phase | Key agents |
|------|--------------|-------|-----------|
| `INTRO-COMBO-WAVE` | Pattern 2 | INTRODUCTION | `@discovery` × N + `@auditor` × M (regression + carry-forward) |
| `DISCOVERY-COMBO-WAVE` | Pattern 2 | BODY | `@auditor` × X + `@discovery` × Y + `@worker` × Z (opt.) |
| `HOTFIX-BATCH` | Pattern 2 | BODY / CLOSE | `@coder` × H clusters (`H ∈ (1,5]`), one batched dynamic workflow dispatched directly by root |
| `FOCUS-LOOP` | Pattern 6 | INTRODUCTION → CLOSE (full sprint) | Orchestrator iterator; wake → act → probe; focus record convergence anchor |
| `CONVERGENCE-LOOP` | Pattern 6 | BODY / CLOSE | `@coder` or `@worker` iterator; fix → gate-check cycle until gate green |
| `WATCH-LOOP` | Pattern 6 | BODY / POST-CLOSE monitoring | `@worker` probe iterator; wall-clock cadence via native `/loop` |

Full definitions for Pattern-2 composites: `doctrines/intro-combo-wave.md`, `doctrines/discovery-combo-wave.md`, `doctrines/hotfix-dispatch.md`.
Full definitions for Pattern-6 composites: `references/workflow-templates.md` (FOCUS-LOOP, CONVERGENCE-LOOP, WATCH-LOOP subsections).

### Pattern-6 composite composition notes

`FOCUS-LOOP`, `CONVERGENCE-LOOP`, and `WATCH-LOOP` are all **Loop-OUTER** composites: the
loop is the outermost structural container, and sub-work runs *inside* each iteration body.
None is nested inside a Fanout-And-Synthesize iteration body, so none implies the illegal
composition "Loop-Until-Done inside Fanout-And-Synthesize iteration body" — they always sit
at or above the fanout level in the graph.

No new halt codes are required for these composites. They reuse the existing Pattern-6 halt
codes without extension:
- `PLAN-MISSING-LOOP-CAP` — fires at preflight (`shctx doctor`) and PLAN-GATE if any of the three composites is declared without a `max_iterations`.
- `LOOP-REPORT-INVALID` — fires on any iteration report that omits the `new_findings: true|false` field.
- `LOOP-CAP` — fires when `iterations >= max_iterations` on any of the three; surfaces the iteration inventory to the operator for extension or acceptance.

The `max_iterations` ceiling, the `shctx loop` backing, and the structured `new_findings`
field are mandatory for all three composites — the same circuit-breaker invariants that govern
generic Pattern 6 apply without exception.

---

## See also

- `references/workflow-templates.md` — full pattern definitions with Stage Graph shapes, flock agent bindings, compose notes, anti-patterns, and named composite index
- `doctrines/stage-graph.md` — the plan IS the dispatch contract; corollaries map directly onto pattern invariants
- `doctrines/dispatch-tier-separation.md` — tier restrictions on which patterns' nodes may be dispatched by whom
- `doctrines/pattern-b-overlap.md` — Pattern 2 specialization: WAVE-N-AUDIT ∥ WAVE-(N+1)-IMPL
- `doctrines/hotfix-dispatch.md` — hot-fix dispatch cardinality ladder (#135); the `(1,5]` batch band is a Pattern-2 fanout whose circuit-breakers apply, the `H≥6` band escalates to a dedicated HOT-FIX lane
- `doctrines/auditor-hypothesis-driven.md` — Pattern 3 verifier contract
- `doctrines/coordinate-active-drive.md` — Pattern 6 runtime instance at root-shepherd level
- `doctrines/invariant-enforcement-matrix.md` — full coverage map of all invariants; this doctrine's enforcement rows are a subset
- `doctrines/preflight-doctor.md` — `shctx doctor` verifies Pattern 6 cap declarations before sprint open
- `pipeline.md` — node taxonomy and walk algorithm the patterns compose into
