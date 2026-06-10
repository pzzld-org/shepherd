# Workflow Templates — Six Canonical Patterns

These six patterns define the structural vocabulary for every Stage Graph authored under `/shepherd:plant`. Each pattern maps an abstract coordination structure to shepherd's native primitives (flock agents, Stage Graph nodes, Dynamic Workflows, and Agent Teams lanes).

**Patterns are composable.** A sprint's Stage Graph is typically a sequence or nesting of two or more patterns. Composition rules and the selection decision tree are in `doctrines/workflow-patterns.md`.

---

## Quick-selection guide

| # | Pattern | Select when | Key flock binding |
|---|---------|-------------|-------------------|
| 1 | Classify-And-Act | Task nature unknown or spans multiple agent types | `@discovery` → branch edge → target agent |
| 2 | Fanout-And-Synthesize | Work decomposes into independent, parallel, non-overlapping units | parallel `@coders` / `@workers` → synthesizer |
| 3 | Adversarial Verification | High-stakes artifact requires independent adversarial challenge | producer → `@auditor` swarm (parallel, no shared context) |
| 4 | Generate-And-Filter | Multiple viable approaches exist; rubric selects winner | parallel generators → `@critic` gate |
| 5 | Tournament | Comparative ranking outperforms absolute rubric scoring | N attempts → bracket of `@critic` pairs → final judge |
| 6 | Loop-Until-Done | Completion defined by absence of new findings | `@worker`/`@discovery` → check node → conditional back-edge |

---

## Pattern 1 — Classify-And-Act

```
                      ┌─> [agent-A]  (on-class-A)
[task] → (classify) ──┼─> [agent-B]  (on-class-B)
                      └─> [agent-C]  (on-class-C)
                          (on-ambiguous: HALT)
```

### When to use

- Task spans multiple possible agent types and type is not determinable from seed evidence alone.
- A fresh-project orientation is needed before any flock dispatch fires.
- Routing depends on runtime evidence (file presence, gate state, prior sprint grade).

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Classifier | `@discovery` | Read-only orientation; emits a `classification` field in its report |
| Actor | `@coder`, `@worker`, or `@discovery` | Dispatched by conductor post-classification |

`@critic` and `@engineer` are NOT valid classifiers — they are gates and plan authors, not routers.

### Stage Graph shape

```yaml
CLASSIFY (discovery):
  brief: classify
  scope: read-only
  emits: classification: {class: A|B|C|ambiguous, rationale: <one-line>}
  on-class-A:     → EXECUTE-A (coder):     {brief: lane-A}
  on-class-B:     → EXECUTE-B (worker):    {brief: lane-B}
  on-class-C:     → EXECUTE-C (discovery): {brief: lane-C}
  on-ambiguous:   → HALT (conductor):      surface classification to operator
```

### Compose notes

- Precedes any other pattern as a **routing prefix**; it is not a complete flow by itself.
- Outgoing `on-class-X` edges must be **mutually exclusive** predicates resolvable from the classify node's `classification` output field.
- If classification yields multiple simultaneous classes, fall forward to **Pattern 2** (Fanout-And-Synthesize) rather than branching to multiple actors inline.

### Anti-patterns

- **Using `@worker` as classifier.** Workers execute bounded tasks; they do not orient, classify, or route.
- **Routing on implicit context.** Classification predicates must be explicit report fields, not inferred from ambient session state.
- **Omitting `on-ambiguous`.** If the classifier's output doesn't match any declared branch, the conductor MUST surface — never guess the branch.

---

## Pattern 2 — Fanout-And-Synthesize

```
         ┌─> [worker-1] ──┐
[task] ──┼─> [worker-2] ──┼─> (synthesize) → [result]
         └─> [worker-N] ──┘
```

### When to use

- Work decomposes into N **independent, parallel, non-overlapping** units.
- Units are structurally identical (same agent type, same brief template, distinct scopes).
- A single synthesizer can unify all results without re-dispatching.
- Canonical uses: multi-file implementation waves, parallel domain research, parallel `shctx` enrichment, INTRO-COMBO-WAVE (discoveries + intro auditors).

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Fanout units | `@coder` (non-overlapping file scopes) or `@worker` (parallel ops) | Bounded execution per unit |
| Synthesizer | `@worker` (aggregation) or conductor inline | Unify, deduplicate, emit single artifact |

### Stage Graph shape

```yaml
WAVE-N-IMPL (coder × N):
  parallel_with: WAVE-(N-1)-AUDIT          # Pattern B specialization
  non_overlapping: true
  on-pass (all units):    → WAVE-N-GATE (conductor): run {gates.check}
  on-partial-fail:        → HOTFIX (coder): rework failing units only
  on-all-fail:            → HALT (conductor): surface to operator

SYNTHESIZE (worker):
  brief: aggregate-WAVE-N
  input: all WAVE-N-IMPL reports
  on-pass:       → next node
  on-incomplete: → HALT: missing units enumerated
```

### Compose notes

- Fanout is bounded by `[coder].max_parallel_lanes` in `shepherd.toml`. Exceeding the limit breaks the non-overlapping guarantee.
- Synthesis follows **all** fanout units completing (all-or-nothing). Never synthesize on partial completion — that is a HOTFIX path.
- **Pattern B** (`doctrines/pattern-b-overlap.md`) is a specialization: `WAVE-N-AUDIT` and `WAVE-(N+1)-IMPL` fire as a `parallel_with` pair; the audit implicitly synthesizes wave N while wave N+1 begins.

### Anti-patterns

- **Overlapping scopes in parallel fanout.** Two `@coders` touching the same file will conflict on merge. The engineer verifies non-overlap before emitting the graph.
- **Partial synthesis.** Synthesizing before all fanout units report produces an incomplete artifact the auditor will flag INCOMPLETE at close.
- **Using `@discovery` as a fanout unit for write work.** Discovery is read-only — fan out `@worker` instead for bounded write operations.

---

## Pattern 3 — Adversarial Verification

```
                        ┌─> [verifier-1] ──┐
[producer] → (produce) ─┼─> [verifier-2] ──┼─> (aggregate) → [findings]
                        └─> [verifier-3] ──┘
```

### When to use

- Artifact correctness is high-stakes (plan, merge gate, close review).
- Multiple **independent** verifiers are needed to minimize shared-anchor bias.
- Each verifier operates on a **distinct concern split** — verifiers must NOT share intermediate results before filing.
- Canonical uses: PLAN-GATE (`@critic`), CLOSE-SWARM (`@auditor` swarm 3–5), INTRO-COMBO-WAVE intro-mode (`@auditor` 1–2 lanes).

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Producer | `@coder`, `@worker`, or `@engineer` | Emits the artifact under review |
| Verifiers | `@auditor` swarm (3–5 close, 1–2 intro) or `@critic` (plan gate) | Independent adversarial review; hypothesis-driven findings per `doctrines/auditor-hypothesis-driven.md` |
| Aggregator | Conductor inline | Merge findings by severity; emit `## Findings summary` |

### Stage Graph shape

```yaml
PRODUCE (engineer):
  brief: phase-0-mesh + plan
  on-complete: → PLAN-GATE

PLAN-GATE (critic):
  brief: plan-gate
  model: sonnet
  on-pass:   → BODY entry node
  on-fail:   → PLAN-AMEND (engineer): {brief: minimal-amend, scope: graph-only-if-structural}
  on-abort:  → HALT: operator decision

CLOSE-SWARM (auditor × 3–5):
  parallel_with: null
  concern_split: [code-quality, data-flow, dependency-topology, datastore-state, completeness]
  on-all-filed:  → FINDINGS-AGGREGATE (conductor)
  on-critical:   → HOTFIX (coder) → CLOSE-SWARM-RECHECK
  on-pass:       → CLOSE-FINALIZE
```

### Compose notes

- Verifier count scales with sprint size: XS/S → 1 auditor, M → 2–3, L/XL → 4–5.
- **Concern split is mandatory.** Two auditors with the same concern are redundant — re-partition before dispatch.
- `@critic` is a single adversarial gate; `@auditor` is the swarm role. Do not conflate.
- Adversarial Verification composes naturally as the close step of Fanout-And-Synthesize (CLOSE-SWARM reviews the entire sprint output, not a single wave's).

### Anti-patterns

- **Single verifier for high-stakes artifacts.** One `@auditor` for close-mode has no adversarial cross-check. Minimum three for close-mode per `flock.md §III`.
- **Shared context before findings.** Verifiers dispatched in `parallel_with` must NOT reference each other's interim output. Each verifier reads the artifact cold.
- **Producer re-dispatched as verifier.** The `@coder` who wrote the code cannot audit it in the same sprint — independence is the invariant (`doctrines/auditor-hypothesis-driven.md`).

---

## Pattern 4 — Generate-And-Filter

```
          ┌─> [gen-1] ──┐
[task] ───┼─> [gen-2] ──┼─> (filter: rubric + dedupe) → [best]
          └─> [gen-N] ──┘    (discard losers)
```

### When to use

- Multiple viable approaches exist and the engineer cannot determine the best from mesh evidence alone.
- A rubric for "best" is **articulable upfront** (performance, API ergonomics, test coverage, project constraints).
- Deduplication is necessary because generators from the same brief may converge on equivalent solutions.
- Use when the rubric is **absolute** (each proposal scored against explicit criteria). For **comparative** ranking ("which of two is better?"), prefer Pattern 5.

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Generators | `@discovery` (research/design variants) or `@coder` (implementation variants) | Produce independent candidate solutions |
| Filter | `@critic` (plan-level decisions) or `@auditor` (implementation review) | Apply rubric; deduplicate; emit a single `## Selection` field |

### Stage Graph shape

```yaml
GEN-CANDIDATES (discovery × N or coder × N):
  parallel_with: null
  non_overlapping: false               # generators may overlap; filter deduplicates
  brief_variant: [A, B, C, ...]        # identical briefs except variant seed
  on-all-complete: → FILTER-RUBRIC

FILTER-RUBRIC (critic):
  brief: filter-gate
  rubric: <criteria-table-from-seed>   # stated at plant time, not assembled post-hoc
  input: all GEN-* reports
  on-winner-selected:   → EXECUTE-WINNER (coder): {brief: implement-winning-design}
  on-tie:               → HALT: operator selects tiebreaker
  on-all-fail-rubric:   → HALT: no viable approach — rework generators
```

### Compose notes

- Generators MUST be dispatched with **identical briefs except the variant seed**. Divergent briefs produce incomparable outputs.
- The rubric must be stated in the seed **before dispatch** — a post-hoc rubric assembled from generator outputs is a process violation.
- Generate-And-Filter naturally precedes Fanout-And-Synthesize: filter selects the winning approach, fanout implements it in parallel.

### Anti-patterns

- **Generators share context before proposing.** If Gen-1's output is visible to Gen-2 before Gen-2 proposes, Gen-2 is anchored. Generators must run `parallel_with` (no cross-read).
- **Post-hoc rubric.** Assembling a rubric from outputs after seeing them is circular — it will select the output the rubric was built to select.
- **Implementing all candidates before filtering.** Filter at design/proposal stage; implement only the winner. Full implementation of all candidates wastes dispatches.

---

## Pattern 5 — Tournament

```
attempt-1 ──┐                  ┌─> winner-AB ──┐
attempt-2 ──┴─> [judge-AB] ────┘                │
                                                 ├─> [final] → winner
attempt-3 ──┐                  ┌─> winner-CD ──┘
attempt-4 ──┴─> [judge-CD] ────┘
                (pairwise judges)
```

### When to use

- Multiple attempts are **roughly equivalent** under a rubric — absolute scoring is unreliable.
- Pairwise comparison ("which of these two is better?") is more reliable than individual scoring.
- Canonical uses: API naming, error message phrasing, algorithm selection under uncertainty, prose style for user-facing content.
- N must be ≥ 2. For N = 2 Tournament degenerates to a single `@critic` pairwise — use Pattern 3 (Adversarial Verification) instead. Works best at N = 4 or 8 (bracket fills cleanly).

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Attempts | `@coder` (implementation), `@worker` (research/prose), or `@discovery` (design) | Produce independent candidate artifacts |
| Pairwise judges | `@critic` | Compare two candidates; emit a `## Winner` field with rationale |
| Final judge | `@critic` | Compare bracket winners; emit overall winner |

### Stage Graph shape

```yaml
ATTEMPTS (coder × N or worker × N):
  parallel_with: null
  non_overlapping: false
  on-all-complete: → BRACKET-ROUND-1

BRACKET-ROUND-1 (critic × N/2):
  parallel_with: null
  input_pairs: [[attempt-1, attempt-2], [attempt-3, attempt-4], ...]
  each_emits: winner: {id: <attempt-id>, rationale: <one-line>}
  on-all-complete: → BRACKET-FINAL

BRACKET-FINAL (critic × 1):
  input: all ROUND-1 winners
  on-winner:   → IMPLEMENT-WINNER (coder or worker): {brief: execute-winner}
  on-tie:      → HALT: operator decides tiebreaker criterion
```

### Compose notes

- Bracket size must be declared in the seed. **Odd N requires a declared bye** (one candidate advances unmatched in round 1) — state explicitly in the graph.
- Each judge sees **only the two candidates assigned to its match** — not other matches' candidates or results. Cross-match contamination invalidates the tournament.
- Tournament is expensive: N attempts + ⌈N/2⌉ + 1 dispatches. Reserve for genuinely ambiguous choices; use Pattern 4 where a rubric cleanly separates candidates.
- Tournament composes naturally after Classify-And-Act: classification narrows to a domain, then tournament selects the best solution within it.

### Anti-patterns

- **Tournament for deterministic tasks.** If the correct answer is derivable from specs, a tournament wastes dispatches. Use Pattern 4 or direct dispatch.
- **Cross-contaminated bracket matches.** Judge-AB must not read Judge-CD's output before deciding. Each match is independent.
- **Non-power-of-2 bracket without bye declaration.** Three attempts with no bye rule leaves round 2 ambiguous. Declare the bye or reduce to N = 2 or 4.
- **Using `@auditor` as tournament judge.** Auditors file findings against criteria; they do not rank alternatives. `@critic` is the comparative-selection agent.

---

## Pattern 6 — Loop-Until-Done

```
        ┌───────────────────────────────────┐
        │  yes — spawn another (i < max)    │
        ↓                                   │
[agent] → (new findings?) ──────────────────┘
                │
                │ no  (or i >= max)
                ↓
             [done]
```

### When to use

- Task is complete when a "no new findings" condition is achieved — not after a fixed number of steps.
- Findings from each iteration **inform the next** (sequential refinement, not independent parallel units).
- Canonical uses: exhaustive grep/search until coverage confirmed, iterative fix-until-gates-green, progressive audit depth (find → fix → re-audit), adaptation loop (`shctx adapt roll` harvest → inject → measure), coordinate-mode active-drive cycle (`doctrines/coordinate-active-drive.md`).
- **`max_iterations` is mandatory.** A loop with no ceiling is a framework violation.

### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Iterator | `@worker` (execution/fix) or `@discovery` (research/synthesis) | Execute one iteration; emit structured `new_findings: true\|false` field |
| Loop controller | Conductor inline | Read `new_findings`; branch back or terminate |
| Terminator | Conductor inline | On `new_findings: false` OR `iterations >= max`, mark DONE; emit `## Loop summary` |

### Stage Graph shape

```yaml
LOOP-INIT (conductor):
  max_iterations: <N>          # declared in seed; default 5; justify higher cap explicitly
  iteration: 0
  on-start: → ITERATE

ITERATE (worker or discovery):
  brief: loop-body
  iteration: $i
  emits: new_findings: true|false, findings_summary: [...]
  on-findings (new_findings: true, $i < max):  → ITERATE (iteration: $i + 1)
  on-empty (new_findings: false):              → LOOP-DONE
  on-cap ($i >= max):                          → LOOP-DONE-CAPPED (conductor): surface cap-reached to operator

LOOP-DONE (conductor):
  emit: "## Loop summary" with iteration count + exhaustive finding inventory
```

### Compose notes

- The iterator MUST emit a **structured `new_findings` field**. Unstructured prose forces the conductor to infer completion — error-prone and audit-failing.
- **Circuit breaker is non-negotiable.** Default `max_iterations = 5`. The engineer must explicitly justify any value > 5 in the plan. Cap-exceeded emits `LOOP-CAP` halt, not silent termination.
- Composes with Pattern 2: each loop iteration can fan out parallel sub-tasks (Fanout-And-Synthesize nested within each iteration body).
- The coordinate-mode active-drive cycle (`wake → act → probe → yield`) is a runtime instance of this pattern at the root-shepherd level — the loop body is the shepherd's wake-act phase; the `new_findings` check is the probe; `yield-to-events` is the termination condition.

### Anti-patterns

- **Unbounded loops.** No `max_iterations` declaration is a framework violation. Every loop MUST have a declared ceiling.
- **Findings without structure.** Iterator reports without a machine-readable `new_findings: true|false` field are fragile — conductors infer completion from prose and get it wrong.
- **Loop for deterministic finite work.** If the work has a known number of units, use Fanout-And-Synthesize (Pattern 2). Loop-Until-Done is for **convergent** iteration, not parallel decomposition.
- **Back-edge without iteration counter.** A loop that re-dispatches without tracking `$i` cannot enforce `max_iterations`. Always track iteration count.

---

## Composition index

Patterns compose along three axes:

| Composition type | Example | Notes |
|-----------------|---------|-------|
| **Prefix routing** | Classify-And-Act → any | Classify narrows scope; the selected branch runs another pattern |
| **Sequential pipeline** | Generate-And-Filter → Fanout-And-Synthesize | Filter selects winning approach; fanout implements it |
| **Layered verification** | Fanout-And-Synthesize → Adversarial Verification | Parallel implementation, then multi-auditor close sweep |
| **Nested iteration** | Loop-Until-Done containing Fanout-And-Synthesize | Each iteration fans out parallel sub-tasks, then checks findings |
| **Competitive implementation** | Tournament → Fanout-And-Synthesize | Tournament picks design; fanout implements the winner at scale |
| **Routed competition** | Classify-And-Act → Tournament | Classification narrows domain; tournament selects best within domain |

Full binding rules for composition — selection decision tree, invariants, circuit-breakers — are in `doctrines/workflow-patterns.md`.

---

## Named composite wave templates

Composites are fixed instantiations of one or more patterns with a canonical agent mix,
scaling table, and aggregate shape. Use the name — not a prose description — in Stage
Graph YAML. A conductor that re-derives a named composite from scratch is improvising
off-template.

The three composites below (`FOCUS-LOOP`, `CONVERGENCE-LOOP`, `WATCH-LOOP`) are the first
with **Pattern basis = Pattern 6** (Loop-Until-Done). Each is a Loop-OUTER composite: the
loop is the outermost structural container, and the sub-work (wake/act, gate checks,
monitoring) runs *inside* each iteration body. None is nested inside a Fanout-And-Synthesize
iteration body — they are always at or above the fanout level, so no illegal composition is
implied (see `doctrines/workflow-patterns.md` composition grammar).

---

### FOCUS-LOOP — orchestrator self-orientation loop

**Intent.** The orchestrator (root shepherd under `/shepherd:spawn`, or solo conductor under
`/shepherd:start`) runs this loop across an entire sprint to maintain drive continuity. Each
iteration: wake (read the focus record + rehydration digest), act (dispatch / coordinate /
advance the Stage Graph cursor), then probe (check whether CLOSE-FINALIZE has been reached).
The loop is the runtime shape of the coordinate-mode active-drive cycle described in
`doctrines/coordinate-active-drive.md`. Interval mode (long-horizon cadence) delegates the
wake clock to the native `/loop` command.

**Compaction resilience.** The focus record lives in `root.db` and survives compaction
natively. A `PreCompact` snapshot captures the in-context drive cursor (ready/in\_flight
sets, trace tail, undrained mailbox) into `<ns>/snapshots/precompact-<sid>-<epoch>.json`.
After compaction the `SessionStart(source=compact)` rehydration consumer (with a guaranteed
`UserPromptSubmit` fallback) re-injects the snapshot digest as `additionalContext`, so the
orchestrator resumes without re-reading the full conversation.

```
┌──────────────────────────────────────────────────────────────┐
│  FOCUS-LOOP (orchestrator as iterator)                       │
│                                                              │
│  FocusInit ──> Wake ──> Act ──> Probe                        │
│                  ↑               │                           │
│                  │   continue    │  sprint not closed         │
│                  └───────────────┘  AND i < max_iterations   │
│                                 │                            │
│                   closed / cap  ↓                            │
│                              LOOP-DONE                       │
└──────────────────────────────────────────────────────────────┘
  Compaction may fire at any point; snapshot+rehydrate restores
  the cursor. Focus record in root.db survives natively.
```

#### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Iterator / loop body | Orchestrator (root or conductor) | Wake: read focus record + rehydration digest. Act: dispatch / coordinate / advance Stage Graph cursor |
| Focus record keeper | Conductor inline (writes to `loops` + `focus` tables) | Write focus record at SEED-VERIFY; refresh at each WAVE-GATE; finalize at CLOSE-FINALIZE |
| Interval wake clock | Native `/loop` (when `interval` is set) | Emits a wake event on cadence; delegates scheduling; auto-expires after 3 days |

`@discovery` and `@worker` may be dispatched **within** the Act phase (as inner sub-tasks),
but they are not the loop iterator — the orchestrator drives the loop.

#### Stage Graph shape

```yaml
FOCUS-LOOP-INIT (conductor):
  kind: focus
  max_iterations: 8           # default from shepherd.toml [focus].loop_max_default; justify > 10
  interval: null              # set to e.g. '5m' to delegate cadence to native /loop
  iteration: 0
  action: shctx loop init --kind=focus --task="sprint-drive" --max=8 --agent=orchestrator
  on-start: → FOCUS-WAKE

FOCUS-WAKE (conductor):
  brief: read focus record + rehydration digest
  action: shctx loop status --id=$loop_id
  on-ready: → FOCUS-ACT

FOCUS-ACT (conductor):
  brief: advance Stage Graph cursor (dispatch / coordinate)
  emits: new_findings: true|false   # true = sprint still open; false = CLOSE-FINALIZE reached
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-findings (new_findings: true, $i < max):  → FOCUS-WAKE (iteration: $i + 1)
  on-empty (new_findings: false):              → FOCUS-LOOP-DONE
  on-cap ($i >= max):                          → FOCUS-LOOP-CAPPED (conductor): surface LOOP-CAP

FOCUS-LOOP-DONE (conductor):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## Focus loop summary" with iteration count, final Stage Graph node, obligations drained
```

#### Compose notes

- `max_iterations` default is `[focus].loop_max_default` in `shepherd.toml` (default: 8). Values > 10 require critic sign-off at PLAN-GATE.
- When `interval` is non-null, the wake cadence is delegated to native `/loop` (`/loop <interval> /shepherd:loop --resume <id>`). The native `/loop` auto-expires after 3 days, which acts as a hard outer bound in addition to `max_iterations`.
- Compaction safety is non-optional: `[compaction].precompact_snapshot` must be `"on"` (default) for FOCUS-LOOP to survive a mid-sprint compaction deterministically.
- The focus record is updated at three mandatory boundaries: SEED-VERIFY (objective + invariants), each WAVE-GATE (active\_node + ready\_set + obligations), and CLOSE-FINALIZE (terminal state).
- FOCUS-LOOP is Loop-OUTER: it is never nested inside a Fanout-And-Synthesize iteration body. Inner fanout waves run **within** the FOCUS-ACT phase.

#### Anti-patterns

- **Running FOCUS-LOOP without a focus record.** A bare loop counter without the `focus` table record is Pattern 6 generic, not FOCUS-LOOP — the rehydration path will have nothing to re-inject.
- **Setting `interval` without native `/loop` delegation.** If `interval` is set, the wake clock MUST be delegated to `/loop` — do not poll with an inner wait. Wall-clock cadence is native `/loop`'s job.
- **Omitting PreCompact snapshot.** Without the snapshot hook, a mid-sprint compaction loses the in-context cursor. The focus record survives but the conductor wakes disoriented.
- **Nesting FOCUS-LOOP inside another loop.** This is a multi-level loop — restructure as a single FOCUS-LOOP whose FOCUS-ACT dispatches inner convergence work.

---

### CONVERGENCE-LOOP — gate-rerun-until-green

**Intent.** Run a check-and-fix cycle until a defined gate turns green (all tests pass, no
linter errors, no new audit findings). Generalizes the H ≥ 6 HOT-FIX lane loop and the
fix-until-gates-green idiom. The iterator is `@coder` or `@worker`; the check is a
deterministic gate query. Mandatory `max_iterations` cap prevents runaway rework.

```
┌─────────────────────────────────────────────────────────────┐
│  CONVERGENCE-LOOP                                           │
│                                                             │
│  LoopInit ──> Fix ──> Check ──┐                            │
│                 ↑             │  failures remain            │
│                 │             │  AND i < max_iterations     │
│                 └─────────────┘                             │
│                               │                            │
│                  green / cap  ↓                             │
│                            LOOP-DONE                        │
└─────────────────────────────────────────────────────────────┘
```

#### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Iterator (Fix) | `@coder` (code changes) or `@worker` (config / script fixes) | Apply one round of fixes; emit `new_findings: true\|false` where `true` = failures remain |
| Gate check | Conductor inline (or `@worker` running deterministic gate) | Run gate (tests / lint / audit query); produce pass/fail result for the iterator's `new_findings` field |
| Terminator | Conductor inline | On green gate OR cap: emit `## Convergence summary` with round count and final gate state |

#### Stage Graph shape

```yaml
CONVERGENCE-LOOP-INIT (conductor):
  kind: convergence
  max_iterations: 5           # mandatory; values > 5 require engineer justification; > 10 require critic sign-off
  iteration: 0
  gate: <gate-expression>     # e.g. "tests-green AND lint-clean"; declared in seed
  action: shctx loop init --kind=convergence --task="<gate-expression>" --max=5 --agent=coder
  on-start: → CONV-FIX

CONV-FIX (coder or worker):
  brief: convergence-fix
  gate_failures: $gate_failures   # injected from prior CONV-CHECK result
  iteration: $i
  emits: new_findings: true|false   # true = gate still failing; false = gate green
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-findings (new_findings: true, $i < max):  → CONV-FIX (iteration: $i + 1)
  on-empty (new_findings: false):              → CONV-LOOP-DONE
  on-cap ($i >= max):                          → CONV-LOOP-CAPPED (conductor): surface LOOP-CAP

CONV-LOOP-DONE (conductor):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## Convergence summary" with round count, final gate state, fix inventory
```

#### Compose notes

- The gate expression must be **declared in the seed** before dispatch — a post-hoc gate assembled after observing failures is a CIRCULAR-RUBRIC analog.
- CONVERGENCE-LOOP naturally follows Pattern 2 (Fanout-And-Synthesize): the fanout implements a feature; CONVERGENCE-LOOP then drives it to gate-green. The fanout is OUTER to the loop (fanout completes, then loop begins).
- For the H ≥ 6 HOT-FIX lane: the CONVERGENCE-LOOP wraps the rework cycle within the dedicated HOT-FIX lane conductor; it is not a separate top-level sprint loop.
- CONVERGENCE-LOOP is Loop-OUTER: it sits above any inner fanout of fix sub-tasks within a single CONV-FIX iteration.

#### Anti-patterns

- **Unbounded fix cycles.** No `max_iterations` on a convergence loop is a `PLAN-MISSING-LOOP-CAP` halt at preflight.
- **Combining fix and check in one node.** The Fix node emits `new_findings` based on gate state; the gate query must be deterministic and reproducible so the conductor can verify the termination condition independently.
- **Using CONVERGENCE-LOOP for known-finite fix lists.** If the set of failing items is enumerable at loop start, dispatch them as a Fanout-And-Synthesize (Pattern 2) and verify with Adversarial Verification (Pattern 3) — no loop needed.
- **Nesting CONVERGENCE-LOOP inside a FOCUS-LOOP Act phase without a separate loop ID.** Each loop instance must have its own `loop_id`; reusing the FOCUS-LOOP's ID conflates sprint drive with fix convergence.

---

### WATCH-LOOP — interval monitoring via native `/loop`

**Intent.** Bounded, wall-clock-scheduled monitoring: watch a deployment, Sentry error
stream, or service health endpoint at a fixed interval and surface anomalies. The iterator
is `@worker` (bounded, read-only or alerting only). **This is the ONLY named composite that
uses wall-clock interval scheduling** — the scheduling is delegated entirely to the native
`/loop` command, not implemented as a back-edge in the Stage Graph. The native `/loop`
3-day auto-expiry is the outer hard bound; `max_iterations` is the explicit inner cap.

```
┌─────────────────────────────────────────────────────────────────┐
│  WATCH-LOOP (wall-clock cadence via native /loop)               │
│                                                                  │
│  LoopInit ──> [native /loop tick] ──> Probe ──┐                 │
│                       ↑                       │  no anomaly     │
│                       │                       │  AND i < max    │
│                       └───────────────────────┘                 │
│                                               │                  │
│                             anomaly / cap     ↓                  │
│                                           LOOP-DONE              │
└──────────────────────────────────────────────────────────────────┘
  Native /loop auto-expires after 3 days regardless of max_iterations.
```

#### Flock agent binding

| Role | Agent | Job |
|------|-------|-----|
| Probe iterator | `@worker` (bounded, read-only or alert-only) | On each tick: query endpoint / Sentry / logs; emit `new_findings: true\|false` where `true` = anomaly detected |
| Interval scheduler | Native `/loop` | Emits a wake event on cadence; auto-expires after 3 days |
| Terminator | Conductor inline | On anomaly: surface alert to operator. On cap or expiry: emit `## Watch summary` with observation log |

`@discovery` is NOT a valid probe iterator for ongoing monitoring — it is for orientation within
a sprint, not for live service observation. Use `@worker` for all WATCH-LOOP probe iterations.

#### Stage Graph shape

```yaml
WATCH-LOOP-INIT (conductor):
  kind: watch
  max_iterations: <N>         # mandatory; also bounded by native /loop 3-day auto-expiry
  interval: <duration>        # e.g. '15m', '1h' — delegated to native /loop; REQUIRED for WATCH-LOOP
  target: <endpoint-or-query> # e.g. "sentry:project/env" or "deploy:prod/health"
  action: shctx loop init --kind=watch --task="monitor <target>" --max=<N> --interval=<duration> --agent=worker
  on-start: → WATCH-PROBE (via native /loop scheduling)

WATCH-PROBE (worker):
  brief: watch-probe
  target: $target
  iteration: $i
  emits: new_findings: true|false   # true = anomaly; false = nominal
  action: shctx loop record --id=$loop_id --iteration=$i --new_findings=$new_findings
  on-empty (new_findings: false, $i < max):  → WATCH-PROBE (iteration: $i + 1, via /loop tick)
  on-findings (new_findings: true):          → WATCH-ALERT (conductor): surface anomaly to operator
  on-cap ($i >= max):                        → WATCH-LOOP-DONE
  on-expiry (native /loop expired):          → WATCH-LOOP-DONE

WATCH-LOOP-DONE (conductor):
  action: shctx loop close --id=$loop_id --status=converged
  emit: "## Watch summary" with observation count, anomalies found (if any), final status
```

#### Compose notes

- `interval` is **mandatory** for WATCH-LOOP. A WATCH-LOOP without an `interval` is structurally indistinguishable from CONVERGENCE-LOOP — select the correct composite.
- The native `/loop` auto-expiry (3 days) is non-overridable. For monitoring horizons beyond 3 days, re-initialize a new WATCH-LOOP after expiry.
- WATCH-LOOP is always a **leaf composite** in the Stage Graph: it does not contain inner loops or fanout sub-tasks within its probe body. If probe work is non-trivial, delegate to a bounded `@worker` sub-task and return findings to the loop.
- When an anomaly is detected, the WATCH-LOOP terminates and surfaces to the operator. The operator decides the remediation action — WATCH-LOOP itself does not dispatch remediation.
- WATCH-LOOP is Loop-OUTER with respect to any inner `@worker` sub-tasks, but in practice the probe body should be simple enough to require no inner fanout.

#### Anti-patterns

- **Wall-clock cadence without native `/loop` delegation.** Implementing a wait-and-poll inner loop in the Stage Graph is forbidden — wall-clock scheduling belongs to native `/loop` exclusively.
- **Using `@discovery` as probe iterator.** Discovery is sprint-orientation read-only; it is not a monitoring agent. Use `@worker`.
- **Unbounded WATCH-LOOP.** Even with the 3-day native `/loop` expiry, `max_iterations` is mandatory. The two bounds are independent: the native expiry is a platform ceiling; `max_iterations` is the plan-declared ceiling. Both must be declared.
- **Dispatching remediation from within WATCH-LOOP.** The loop's job is to detect and surface; remediation is the operator's decision. Embedding a CONVERGENCE-LOOP inside a WATCH-LOOP anomaly handler violates the leaf-composite constraint and exceeds the depth-3 composition limit.

---

| Name | Phase | Structure | Defined in |
|------|-------|-----------|------------|
| `INTRO-COMBO-WAVE` | INTRODUCTION (before MESH) | N `@discovery` + M `@auditor` (regression + carry-forward) | `doctrines/intro-combo-wave.md` |
| `DISCOVERY-COMBO-WAVE` | BODY (during sprint execution) | X `@auditor` + Y `@discovery` + Z `@worker` (optional) — single parallel batch | `doctrines/discovery-combo-wave.md` |
| `FOCUS-LOOP` | INTRODUCTION → CLOSE (full sprint) | Orchestrator iterator; wake → act → probe; focus record convergence anchor; `max_iterations` mandatory | this file (`references/workflow-templates.md`) |
| `CONVERGENCE-LOOP` | BODY / CLOSE | `@coder` or `@worker` iterator; fix → gate-check cycle; `max_iterations` mandatory | this file (`references/workflow-templates.md`) |
| `WATCH-LOOP` | BODY / POST-CLOSE monitoring | `@worker` probe iterator; wall-clock interval via native `/loop`; `max_iterations` + 3-day expiry mandatory | this file (`references/workflow-templates.md`) |

---

## See also

- `doctrines/workflow-patterns.md` — binding doctrine: selection decision tree, composition invariants, circuit-breakers
- `doctrines/intro-combo-wave.md` — INTRO-COMBO-WAVE: sprint-open parallel orientation composite
- `doctrines/discovery-combo-wave.md` — DISCOVERY-COMBO-WAVE: body-phase parallel audit + research composite
- `doctrines/stage-graph.md` — the plan IS the dispatch contract; patterns encode as graph nodes/edges
- `doctrines/pattern-b-overlap.md` — Pattern 2 specialization: WAVE-N-AUDIT ∥ WAVE-(N+1)-IMPL
- `doctrines/auditor-hypothesis-driven.md` — Pattern 3 verifier contract: Hypothesis + Falsification + Confidence
- `doctrines/dispatch-tier-separation.md` — which tier may dispatch which pattern nodes
- `doctrines/coordinate-active-drive.md` — Pattern 6 runtime instance at root-shepherd level
- `pipeline.md` — full node taxonomy, edge labels, walk algorithm
- `flock.md` — per-agent brief contracts and parallel-safety rules
