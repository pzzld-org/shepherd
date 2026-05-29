---
title: pipeline
description: |
  The conditional-dispatch graph (Stage Graph) that ties seeds → plans → coder waves
  → auditors → close into one walkable DAG. Defines the stage taxonomy, edge
  predicates, fan-in / fan-out batches, and the conductor's walk algorithm.
  v4.2.0 introduces this artifact so the conductor walks a graph instead of
  re-reading three files at every decision point.
---

# Pipeline — The Stage Graph

This file owns the canonical dispatch DAG for a shepherd sprint. The DAG is the bridge between **declarative planning** (planter authors seed, engineer authors plan) and **deterministic execution** (conductor walks graph, fires next-eligible stages). Once the engineer commits the plan, the conductor's job collapses to "walk the graph". No fresh sequencing decisions. No re-reading flock.md mid-sprint. No checklist-juggling.

The Stage Graph is the structural fix for "the conductor has the load of orchestrating six agents across N waves with M conditional gates" — that load lives in the graph now, not in the conductor's working memory.

> **Reads with:** `SKILL.md` §III (sprint sections), `flock.md` (per-agent dispatch), `agents/engineer.md` (plan emits the graph), `references/seed-template.md` (planter sketches the graph), `doctrines/stage-graph.md` (the principle).

---

## I. Why a graph

The pre-4.2.0 model: SKILL.md §III lists §1 → §2 → §3 phases; flock.md lists per-agent triggers; the plan describes wave composition in prose. The conductor synthesizes "what to dispatch next" by re-reading all three at every decision point. That works but burns context, leaks attention, and forces every conductor session to re-derive the same sequencing.

The 4.2.0 model: the engineer's plan emits one declarative artifact — the Stage Graph — that names every dispatch event, its preconditions, its agents, its expected outputs, and its successor edges. The conductor's runtime is mechanical: at each tick, identify nodes whose predecessors are satisfied, batch them per parallel-safety rules, fire, await, evaluate edge predicates, advance. Halt only on hard-stop predicates.

Benefits, made explicit:

| Benefit | Mechanism |
|---|---|
| **Drift reduction** | Every dispatch corresponds to a named graph node — silently inserting work outside the graph IS a process violation auditors catch |
| **Cognitive-load reduction** | Conductor doesn't choose "what next" — it reads the graph |
| **Deterministic execution** | Same plan + same graph + same predicates → same dispatch sequence |
| **Auditable provenance** | Every commit traces to a graph node; every node traces to a plan section |
| **Pattern B is structural** | The "audit Wave N + impl Wave N+1 in one batch" rule is a graph shape, not a checklist item |
| **Hot-fix discipline** | Hot-fix subgraphs are first-class — never improvised |
| **Autorun simplifies** | The loop becomes "walk graph until terminal node, then re-seed and re-walk" |

---

## II. Stage taxonomy (the node types)

Every node in the graph is one of these types. The type determines the dispatch shape (single agent vs parallel batch vs conductor-inline) and the legal edge predicates.

| Type | Dispatch shape | Owner | Produces |
|---|---|---|---|
| `SEED-VERIFY` | Conductor inline (no agent) | Conductor | seed-loaded boolean + drift-suspicion flag |
| `MESH` | Single `@engineer` (Opus) | @engineer | Phase 0 mesh report + plan + the Stage Graph itself for §2/§3 |
| `CHAIN-REPAIR` | Conductor inline (verify) → Edit (amend seed) → re-fire `MESH` | Conductor | amended seed (or escalation) |
| `PLAN-GATE` | Single `@critic` | @critic | verdict ∈ {GREEN, YELLOW, RED} |
| `PLAN-REVISION` | Single `@engineer` | @engineer | revised plan (max once before pass-2) |
| `DEDUP-GATE` | Conductor inline (run every step's `[DO-NOT-DUPLICATE]` greps + `[SKILLS]` mechanical-recompute) | Conductor | dispatch-allowed boolean + amended briefs (per `doctrines/zero-duplicate-tolerance.md`) |
| `GATES-DISCOVERY` | Conductor inline (run every configured gate verbosely; tee to discovery report) | Conductor | full latent error inventory (per `doctrines/gates-restoration.md` — fires before any `WAVE-IMPL` whose mission is "restore the gates", typically Wave 0) |
| `WAVE-IMPL` | Parallel batch of N `@coder` (one per step) + `@worker` IO-bound batch in the SAME message | @coder + @worker | committed worktrees |
| `WAVE-GATE` | Conductor inline (rebase + four-step gate) | Conductor | gate-pass boolean + rebased commit |
| `LANE-CLOSE` | Conductor inline (`shctx close-lane <lane-id>`) — fires after each `WAVE-GATE` per lane | Conductor | carry-forward + dedup ledger auto-resolved (per v5.0.3 §2.7) |
| `CANONICAL-TYPES-REFRESH` | Single `@worker` (bounded; non-competing) — fires at every dev.0 | @worker | refreshed `{paths.ctx}/canonical-types.md` |
| `WAVE-AUDIT` | Parallel batch of M `@auditor` (concern-split, scoped to wave N) | @auditor | per-wave audit reports + GH findings |
| `HOTFIX` | One or more `@coder` (≤ 3 concurrent, ≤ S each) — count pre-declared in plan | @coder | committed worktrees per finding |
| `HOTFIX-DYNAMIC` | Variable-cardinality `@coder` batch — count derived from gate-error cluster analysis at runtime | @coder | committed worktrees; count not pre-declared |
| `CLOSE-SWARM` | Parallel batch of 3–5 `@auditor` (concern-split, full sprint scope) | @auditor | close-time audit reports + grades + GH findings |
| `CLOSE-FINALIZE` | Conductor inline | Conductor | close report + handoff + memory + rebase + DELETE dev branch + cut next |
| `RELEASE` | Conditional on dev.{last}; runs per `[release].driver` | Conductor or CI | tag + GH release + next patch branch + dev.0 |
| `WORKER-IO` | One or more `@worker` (bounded; non-competing) | @worker | bounded reports |
| `HARD-STOP` | Conductor inline (terminal) | Conductor | operator-surfaced halt block |
| `PAUSE` | Conductor inline (terminal under `/shepherd:start`; bypassed under `/shepherd:spawn --auto`) | Conductor | end-of-sprint waypoint |
| `DISCOVERY` | Single or parallel `@discovery` (v5.1.1+) | @discovery | DISCOVERY REPORT at `{paths.reports}/<date>-discovery-<id>.md` |
| `INTRO-COMBO-WAVE` | Parallel batch of `@discovery` + `@auditor` (intro-mode) (v5.1.1+) | both | Mesh-input bundle: discoveries + regression + carry-forward-disposition reports |

Each node carries:

```
node id        — short slug (e.g., "wave-2-impl", "close-swarm")
type           — one of the table above
in_predicates  — list of {predecessor-id, edge-label} pairs that must hold to fire
parallel_with  — list of node-ids that MUST fire in the same Agent batch (Pattern B encoded here)
agents         — list of {role, count, brief-ref} (empty for conductor-inline)
out_edges      — list of {label, target-node-id}
```

**HOTFIX-DYNAMIC cardinality.** Unlike `HOTFIX` (count pre-declared in plan), a
`HOTFIX-DYNAMIC` node derives its coder count at walk-time from the gate-error
cluster analysis:

1. Run the gate with structured JSON output (`{gates.lint} --message-format=json
   --keep-going > .shepherd/runs/w{N}-gate.json 2>&1` for tools that support it,
   OR `{gates.lint} 2>&1 | tee .shepherd/runs/w{N}-gate.txt`).
2. Parse errors and cluster by **file-disjoint scope**: each cluster becomes one
   parallel HF coder step.
3. Dispatch all clusters in ONE Agent batch (same Wave-style parallel safety
   rules as WAVE-IMPL — zero file overlap per step).
4. After all HF coders return, re-run the gate ONCE. If still failing, escalate
   (cap at 3 HOTFIX iterations per gate).

The Stage Graph YAML for a `HOTFIX-DYNAMIC` node:
```yaml
- id: hotfix-w1
  type: HOTFIX-DYNAMIC
  in_predicates: [{ predecessor: wave-1-gate, edge: on-fail }]
  cardinality: "1..cluster_count"   # auto-derived at walk-time
  per_instance_brief: hotfix-coder-template  # brief template, not per-step
  out_edges:
    - { label: on-coder-complete, target: wave-1-gate-rerun }
    - { label: on-hard-stop, target: hard-stop }    # > 3 iterations
```

This encodes HF-cascade parallelism structurally rather than requiring the
engineer to pre-declare N specific HF steps (which they cannot know at plan time).

The plan section §"Stage Graph" enumerates every node. The conductor parses it at sprint open and walks it.

**SQL fast-path (v5.0.0+).** Before running per-step greps, the conductor runs `shctx query dedup-check --name=<step.new_symbol>` for each step. If the registry returns ≥1 row, BLOCK with the standard recommendation block (citing the DB row's `file_path:line`). The grep remains the contract — registry rows are derived and may be stale; a registry miss does NOT skip the grep, but a registry hit pre-blocks dispatch and saves the grep step.

---

## III. Edge predicates (the labels)

Edges are conditional transitions between nodes. Each edge has a label; the label is a runtime predicate the conductor evaluates against the predecessor's output. Canonical labels:

| Label | Means |
|---|---|
| `unconditional` | Fires when predecessor completed (any exit) |
| `on-green` | Fires when predecessor's verdict / grade was GREEN / no-finding |
| `on-yellow` | Fires on critic YELLOW (revision lane) |
| `on-red` | Fires on critic RED (terminal — escalates to HARD-STOP) |
| `on-no-drift` | Fires when MESH found no SEED-DRIFT |
| `on-mechanical-drift` | Fires from MESH on mechanical drift → CHAIN-REPAIR |
| `on-substantive-drift` | Fires from MESH on substantive drift → HARD-STOP (per `chain-repair.md`) |
| `on-amend` | Fires from CHAIN-REPAIR after seed amended → re-fire MESH |
| `on-pass` | Fires from WAVE-GATE when all gates green |
| `on-fail` | Fires from WAVE-GATE when a gate failed → HOTFIX or HARD-STOP |
| `on-finding` | Fires from WAVE-AUDIT or CLOSE-SWARM when CRITICAL/HIGH found → HOTFIX |
| `on-no-finding` | Fires when audit produced no CRITICAL/HIGH |
| `on-grade-cap` | Fires from CLOSE-SWARM when completeness grade-caps (per `subtract-dont-add.md` / `issue-ledger-awareness.md`) — does NOT fail the sprint, but lowers the grade |
| `on-budget-exceeded` | Fires from WORKER-IO when budget exhausted; informational |
| `on-coder-complete` | Fires from WAVE-IMPL when ALL coders reported back |
| `on-rebase-clean` | Fires from WAVE-GATE when rebase-merge applied with no conflicts |
| `on-dedup-clear` | Fires from DEDUP-GATE when every grep returned the expected count |
| `on-dedup-block` | Fires from DEDUP-GATE when ANY grep returned > expected; loops back to brief-amendment then re-fires DEDUP-GATE |
| `on-hard-stop` | Fires from any node into HARD-STOP terminal — operator must intervene |
| `on-research-complete` | (v5.1.1+) Fires from DISCOVERY when report written; targets the downstream consumer (MESH, HOTFIX-DYNAMIC, etc.) |
| `on-intro-wave-complete` | (v5.1.1+) Fan-in fires when ALL members of an INTRO-COMBO-WAVE have completed; targets MESH |
| `on-intro-audit-complete` | (v5.1.1+) Fires from intro-mode auditor when its report is written |

A node with multiple `out_edges` is a branch point. Branch points are deterministic: exactly one outgoing edge fires per evaluation.

A node with multiple `in_predicates` is a join. Joins fire only when ALL inbound predicates are satisfied (AND-join). The graph does not currently support OR-joins — those are encoded as separate nodes.

---

## IV. The canonical sprint graph (default shape)

This is the default DAG every `/shepherd:start` walks unless the engineer's plan customizes it. Visualized:

```
                              ┌──────────────────┐
                              │  SEED-VERIFY     │  (conductor inline)
                              └────────┬─────────┘
                                       │ on-green
                                       ▼
                              ┌──────────────────┐
                              │  MESH            │  (@engineer · Opus)
                              └────────┬─────────┘
                       on-mechanical   │   on-no-drift          on-substantive
                          drift        │                          drift
                  ┌──────────────────┐ │ ┌──────────────────────┐ │
                  ▼                  │ │                        │ ▼
        ┌──────────────────┐         │ │                        │ ┌──────────┐
        │  CHAIN-REPAIR    │         │ │                        │ │HARD-STOP │
        │ (verify+amend;   │         │ │                        │ └──────────┘
        │  loop to MESH)   │         │ │                        │
        └────────┬─────────┘         │ │                        │
              on-amend               │ │                        │
                  └──────────────────┤ │                        │
                                     │ │                        │
                                     ▼ ▼                        │
                              ┌──────────────────┐              │
                              │  PLAN-GATE       │  (@critic)   │
                              └────────┬─────────┘              │
                       on-yellow       │ on-green       on-red  │
                  ┌──────────────────┐ │ ┌──────────────────┐   │
                  ▼                  │ │                    │   │
        ┌──────────────────┐         │ │                    └───┤
        │ PLAN-REVISION    │         │ │                        │
        │ (engineer ×1)    │         │ │                        │
        └────────┬─────────┘         │ │                        │
                 │ on-pass-2-green   │ │                        │
                 └─────────────►─────┤ │                        │
                                     │ │                        │
                                     ▼ │                        ▼
                              ┌──────────────────┐
                              │  DEDUP-GATE      │  (conductor inline)
                              │  every lane's    │
                              │  [DO-NOT-DUP]    │
                              │  greps + skill   │
                              │  recompute       │
                              └────────┬─────────┘
                            on-dedup-block│ on-dedup-clear
                                  ▲       │
                          (loop back to ──┤
                           brief-amend +  │
                           re-fire)       ▼
                              ┌────────────────────────────────────────┐
                              │  WAVE-1-IMPL  ║  WORKER-IO (parallel)  │
                              │  (N coders) ──╫─ (M workers)           │
                              └────────┬───────────────────────────────┘
                                       │ on-coder-complete
                                       ▼
                              ┌──────────────────┐
                              │  WAVE-1-GATE     │  (conductor: rebase + 4-step gate)
                              └────────┬─────────┘
                          on-pass      │       on-fail
                                       │       └──────► HOTFIX (≤3, then loop back to WAVE-1-GATE)
                                       ▼
            ┌──────────────────────────────────────────────────────────────┐
            │  Pattern B batch (single Agent message)                      │
            │  ┌────────────────────┐    ┌──────────────────────┐          │
            │  │ WAVE-1-AUDIT       │    │ WAVE-2-IMPL          │          │
            │  │ (auditors / wave-1)│    │ (N coders / wave-2)  │          │
            │  └─────────┬──────────┘    └──────────┬───────────┘          │
            └────────────┼──────────────────────────┼──────────────────────┘
                         │ on-finding               │ on-coder-complete
                         ▼                          ▼
                    ┌──────────┐              ┌──────────────────┐
                    │ HOTFIX   │              │ WAVE-2-GATE      │
                    │ (≤3)     │              └─────────┬────────┘
                    └────┬─────┘                        │ on-pass
                         │                              ▼
                         └──────────►   ... (iterate Pattern B per wave)
                                                       │
                                                       ▼
                                            ┌──────────────────┐
                                            │  CLOSE-SWARM     │  (3–5 @auditor)
                                            │  + completeness  │
                                            │    runs ledger    │
                                            │    refresh +      │
                                            │    SUBTRACT check │
                                            └─────────┬────────┘
                                  on-finding          │ on-no-finding
                                                      │ on-grade-cap (lowers grade only)
                                  ┌───────────────────┤
                                  ▼                   ▼
                            ┌──────────┐    ┌──────────────────┐
                            │ HOTFIX-  │    │ CLOSE-FINALIZE   │
                            │ CLOSE    │    │ (handoff + rebase│
                            │ (≤3)     │    │  + DELETE +      │
                            └────┬─────┘    │  cut next)       │
                                 │          └─────────┬────────┘
                                 └────────────────────┤
                                                      │
                                  on-not-dev.last     │  on-dev.last
                                  ┌───────────────────┤
                                  ▼                   ▼
                            ┌──────────┐    ┌──────────────────┐
                            │  PAUSE   │    │ RELEASE          │
                            │(or loop  │    │ (per [release]   │
                            │ spawn    │    │  .driver)        │
                            └──────────┘    └──────────────────┘
```

The default sprint has 9–11 nodes for a typical M sprint, more for L/XL (more `WAVE-N` clusters), fewer for XS/S (single wave + close).

---

## V. The conductor's walk algorithm

The conductor's runtime, post-plan, is this loop:

```
1. Load plan.md → parse §"Stage Graph" → build in-memory DAG
2. ready_set := { nodes with no in_predicates OR all in_predicates already satisfied }
3. While ready_set is non-empty:
     a. Group ready nodes by `parallel_with` cliques → batches
     b. For each batch:
          - if batch contains a HARD-STOP node, fire it and EXIT
          - if batch is conductor-inline, execute inline
          - if batch contains agents, dispatch IN ONE MESSAGE (per parallel-safety rules)
          - await all returns
     c. For each completed node, evaluate outgoing edge predicates against the node's output
     d. For each satisfied edge, mark the target node as having that in_predicate satisfied
     e. Recompute ready_set
4. When ready_set is empty AND no node is in-flight: graph is complete → terminal
```

The conductor does NOT add ad-hoc nodes mid-walk. If a need emerges that the graph doesn't anticipate (e.g., a fourth hot-fix wave when the graph allows three), that IS a graph violation — the conductor surfaces to the operator and either amends the plan (re-running through `PLAN-GATE` with the new graph) or escalates.

This is the discipline that prevents drift: the graph is the contract; the walk is mechanical; deviation is structural and visible.

**Mechanization (v5.0.9 dispatch cascade):** the abstract walk above is implemented by `shctx graph` — see `doctrines/dispatch-cascade.md`. After MESH, the conductor runs `shctx plan extract <plan.md>` to materialize the graph into `<ns>/graph/state.json`, then loops:

```
shctx graph next   # → batch of ready nodes (parallel_with cliques honored)
# dispatch via Agent tool in ONE message
shctx graph mark <id> --state=done --exit=<edge-label>
# downstream nodes auto-promote to "ready" when all in_predicates satisfied
```

`shctx graph trace` is the append-only event log that feeds `adaptation-loop.md §V-bis` node-level telemetry. The conductor's only LLM-driven step per tick is brief authoring + edge-label selection; routing is mechanical.

### Cache-first brief ordering (v5.1.3+)

Every brief the conductor emits follows the stable-framing-first /
variable-content-last discipline per `doctrines/brief-cache-discipline.md`.
The bracketed-section order is:

**Stable (top):** `[ROLE]` → `[SKILLS]` → `[DOCTRINES]` → `[PROTOCOL-REMINDERS]`
**Variable (bottom):** `[FILE-SCOPE]` → `[CONTEXT-INVENTORY]` → `[DO-NOT-DUPLICATE]` → `[ACCEPTANCE]` → `[NON-GOALS]` → `[WORKTREE]` → `[BASE-COMMIT-EXPECTED]`

Stable sections are reused verbatim across every dispatch in a sprint; the
runtime caches them as the brief prefix. Variable sections are
dispatch-specific and live at the tail so the prefix remains stable across
fan-out. The completeness auditor verifies ordering at close (LOW per
violation; aggregates to MEDIUM if > 30% of captured dispatches violate)
per `doctrines/brief-cache-discipline.md`. The v5.1.3 telemetry hooks
surface per-role hit-rate so the dollar/consistency wins are measurable —
see `doctrines/cache-telemetry.md`.

---

## VI. Pattern B is a graph shape, not a checklist item

Pre-4.2.0, `doctrines/pattern-b-overlap.md` was a discipline the conductor remembered. Now it's a graph constraint:

```
WAVE-N-AUDIT.parallel_with = [ WAVE-(N+1)-IMPL ]
```

Two nodes with `parallel_with` set MUST fire in the same Agent batch. The walk algorithm enforces this — they're scheduled together by construction. A conductor that fires them sequentially is walking the graph wrong.

Same encoding for `WORKER-IO`:

```
WORKER-IO.parallel_with = [ WAVE-1-IMPL ]
```

Workers join the Wave 1 dispatch batch automatically. No "remember to fire workers at Wave 1 START" cognitive load.

---

## VII. Hot-fix subgraphs

When `WAVE-N-AUDIT` returns `on-finding`, the graph routes to a HOTFIX subgraph. The subgraph is a small DAG of its own:

```
WAVE-N-AUDIT  ──on-finding──►  HOTFIX (≤3 parallel coders)
                                  │
                                  │ on-coder-complete
                                  ▼
                              WAVE-N-GATE-RERUN  (conductor re-runs the four-step gate)
                                  │
                                  │ on-pass
                                  ▼
                              (rejoin main flow at WAVE-(N+1)-IMPL)
```

The HOTFIX node carries:

- A finding-id binding (which audit finding it addresses)
- A `[FILE-SCOPE]` ≤ S
- An iteration cap (default 3 retries before HARD-STOP)

The conductor does NOT compose hot-fix briefs from scratch — the auditor's report includes a `Suggested hot-fix lane: [FILE-SCOPE] ... [ACCEPTANCE] ...` block (per `agents/auditor.md` Report Shape) that the conductor pastes into the HOTFIX node's brief verbatim.

---

## VIII. The CLOSE subgraph (where doctrines compose)

`CLOSE-SWARM` is where the doctrines all converge. Its constituent auditors carry concern-bound responsibilities:

| Auditor concern | Doctrines invoked | Edge contribution |
|---|---|---|
| `code-quality` | `code-style:<lang>`, `wrapper-must-earn` | `on-finding` if hits in lane-modified files |
| `data-flow` | project-doctrines (money path) | `on-finding` if fail-closed semantics violated |
| `dependency-topology` | `wrapper-must-earn`, `subtract-dont-add` (dep delta) | `on-finding` for new build-manifest deps without justification |
| `datastore-state` | (project-specific) | `on-finding` for advisor warnings |
| `completeness` | `subtract-dont-add`, `issue-ledger-awareness`, `carry-forward-refresh` | `on-grade-cap` if real-work fails OR SUBTRACT violation OR ledger silence |

`on-grade-cap` is a special edge: it does NOT fire HOTFIX (the violation isn't fixable mid-sprint); it lowers the recorded grade and continues to `CLOSE-FINALIZE`. The grade-cap is provenance, not a re-dispatch trigger.

---

## IX. The autorun walk (loop semantics)

Under `/shepherd:spawn --auto`, after `CLOSE-FINALIZE` for sprint N, the planter:

1. Runs `references/branching-model.md` §II.4 (DELETE + cut next).
2. Spawns a fresh teammate-conductor for sprint N+1 (loads new seed, builds new graph).
3. The teammate walks the new graph.

The loop terminates on:

- `HARD-STOP` node fired anywhere
- `PAUSE` node fired (only happens under `/shepherd:start`; spawn --auto bypasses by definition)
- dev.{last} `CLOSE-FINALIZE` returns `on-dev.last` AND no sprint-through grant → exits to operator before `RELEASE`

Autorun is structurally simpler in 4.2.0: it's "loop the walk algorithm". No special-cased "skip the PAUSE" logic — `PAUSE` is just absent from the spawn --auto graph. Full loop mechanics: `commands/spawn.md §--auto flag`.

---

## X. The parallel walk (worktree fan-out)

Under `/shepherd:spawn --parallel <N>`, the planter fans out N sibling teammate-conductors. Each teammate:

1. Receives an independent graph (one per concurrent sprint).
2. Walks its graph in its own worktree.
3. Joins at `CLOSE-FINALIZE` in dev-order — `dev.{N+1}` waits for `dev.{N}` to finalize before its own `CLOSE-FINALIZE` fires.

The dev-order join is encoded as a cross-graph `in_predicate`:

```
sprint-{N+1}.CLOSE-FINALIZE.in_predicates += [ sprint-{N}.CLOSE-FINALIZE.completed ]
```

The maximum concurrent sprint count is 4 (N must be 2–4 per `commands/spawn.md §Preflight Check 5`). The planter enforces this before any teammate is spawned. Full mechanics: `commands/spawn.md §--parallel flag`.

---

## XI. Where the graph lives

Three layers of progressive specification, each more concrete than the prior:

| Layer | File | Author | Detail level |
|---|---|---|---|
| Hint | `{paths.plans}/{sprint_slug}.seed.md` §"Stage decomposition hint" | Planter | Phase decomposition, parallel-safe groupings, conditional links — non-binding suggestion |
| Contract | `{paths.plans}/{sprint_slug}.plan.md` §"Stage Graph" | Engineer | Full DAG: every node, every edge, every predicate, every brief-ref. This is what the conductor walks. |
| Trace | `{paths.reports}/<date>-{sprint_slug}-walk.md` | Conductor (auto, optional) | Append-only log of node fires, edge evaluations, batch composition — for post-hoc audit |

The seed's hint is **non-binding** — the engineer rebuilds against Phase 0 mesh evidence. The plan's Stage Graph is **binding** — the conductor walks it verbatim.

The walk trace is **optional but encouraged** for L/XL sprints. The auditor's `completeness` concern reads it at close to verify "every commit corresponds to a graph node fire" (no off-graph dispatches).

---

## XII. Plan-section format (what the engineer emits)

The engineer's plan includes a `## Stage Graph` section with one block per node:

````markdown
## Stage Graph

```yaml
nodes:
  - id: seed-verify
    type: SEED-VERIFY
    in_predicates: []
    out_edges:
      - { label: on-green, target: mesh }
      - { label: on-hard-stop, target: hard-stop }

  - id: mesh
    type: MESH
    in_predicates: [{ predecessor: seed-verify, edge: on-green }]
    agents:
      - { role: engineer, count: 1, brief: ${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/agent-briefs.md#engineer }
    out_edges:
      - { label: on-no-drift, target: plan-gate }
      - { label: on-mechanical-drift, target: chain-repair }
      - { label: on-substantive-drift, target: hard-stop }

  - id: plan-gate
    type: PLAN-GATE
    in_predicates: [{ predecessor: mesh, edge: on-no-drift }, { predecessor: chain-repair, edge: on-amend }]
    agents:
      - { role: critic, count: 1 }
    out_edges:
      - { label: on-green, target: wave-1-impl }
      - { label: on-yellow, target: plan-revision }
      - { label: on-red, target: hard-stop }

  - id: dedup-gate-w1
    type: DEDUP-GATE
    in_predicates: [{ predecessor: plan-gate, edge: on-green }]
    out_edges:
      - { label: on-dedup-clear, target: wave-1-impl }
      - { label: on-dedup-block, target: dedup-gate-w1 }   # self-loop after brief-amendment

  - id: wave-1-impl
    type: WAVE-IMPL
    in_predicates: [{ predecessor: dedup-gate-w1, edge: on-dedup-clear }]
    parallel_with: [worker-io]
    agents:
      - { role: coder, count: 4, briefs: [step-A, step-B, step-C, step-D] }
    out_edges:
      - { label: on-coder-complete, target: wave-1-gate }

  - id: worker-io
    type: WORKER-IO
    in_predicates: [{ predecessor: dedup-gate-w1, edge: on-dedup-clear }]
    parallel_with: [wave-1-impl]
    agents:
      - { role: worker, count: 1, brief: deploy-monitor-15min }

  - id: wave-1-gate
    type: WAVE-GATE
    in_predicates: [{ predecessor: wave-1-impl, edge: on-coder-complete }]
    out_edges:
      - { label: on-pass, target: wave-1-audit }
      - { label: on-fail, target: hotfix-w1 }

  # ... wave-1-audit, wave-2-impl (Pattern B parallel_with), etc.

  - id: close-swarm
    type: CLOSE-SWARM
    in_predicates: [{ predecessor: wave-N-gate, edge: on-pass }]
    agents:
      - { role: auditor, count: 4, concerns: [code-quality, data-flow, dependency-topology, completeness] }
    out_edges:
      - { label: on-finding, target: hotfix-close }
      - { label: on-no-finding, target: close-finalize }
      - { label: on-grade-cap, target: close-finalize }   # grade lowered, continues

  - id: close-finalize
    type: CLOSE-FINALIZE
    in_predicates: [{ predecessor: close-swarm, edge: on-no-finding }, { predecessor: hotfix-close, edge: on-pass }, { predecessor: close-swarm, edge: on-grade-cap }]
    out_edges:
      - { label: on-not-dev.last, target: pause }
      - { label: on-dev.last, target: release }   # gated by sprint-through grant

  - id: hard-stop
    type: HARD-STOP

  - id: pause
    type: PAUSE
```
````

The YAML block is parseable. Conductor reads it once at sprint open and walks deterministically.

---

## XIII. Anti-patterns (what auditors watch for)

The `completeness` auditor verifies graph discipline at close:

1. **Off-graph dispatches** — a coder commit whose step id doesn't match any `WAVE-IMPL` node — process violation.
2. **Skipped Pattern B** — `WAVE-N-AUDIT` fired strictly before `WAVE-(N+1)-IMPL` (not in same batch) — process violation.
3. **Missing HARD-STOP edges** — every branch point has an `on-hard-stop` outgoing edge — graph-validity check.
4. **Implicit hot-fix loops** — a HOTFIX subgraph that loops > 3 times without operator surface — process violation.
5. **CLOSE-SWARM without grade-cap edge** — completeness concern can grade-cap; the graph MUST encode that path — graph-validity check.
6. **WORKER-IO not parallel-with WAVE-1-IMPL** — workers are IO-bound; deferring them is the documented anti-pattern (`flock.md` §V.8) — graph-validity check.
7. **CHAIN-REPAIR without amend-and-loop edge** — drift was found but seed wasn't amended — graph-validity check.
8. **WAVE-IMPL without preceding DEDUP-GATE** — per `doctrines/zero-duplicate-tolerance.md`, every WAVE-IMPL has a DEDUP-GATE predecessor with `on-dedup-clear` edge. Skipping it is how duplicate code lands.
9. **dev.0 plan without CANONICAL-TYPES-REFRESH worker** — the workspace catalog at `{paths.ctx}/canonical-types.md` must be refreshed at every patch's dev.0; a plan that omits it ships stale catalog and produces duplicate-prone subsequent sprints.

A graph that fails any of these checks gets a `STAGE-GRAPH-VIOLATION` finding and grade-caps at C+ (per `subtract-dont-add` precedent).

---

## XIII-bis. Structured gate output + parallel HF dispatch (v5.0.6)

> Field origin: axiom v0.3.1-dev.8a, 2026-05-12. Three serialized HF waves
> (HF-1 → HF-2 → HF-3) each unmasked a new error layer because the preceding
> gate run short-circuited at the first compile error. All ~25 errors could have
> surfaced upfront with a single `--keep-going` run; all three HF coders could
> have fired as one parallel wave.

### The problem with streaming gate output

When a gate fails, two problems occur:
1. **Short-circuit masking** — most compilers/linters stop at the first error
   (or the first error in the DAG-blocking package). Downstream errors that would
   have appeared are hidden until the upstream fix lands.
2. **Blocking conductor context** — the gate command blocks for minutes; the
   conductor context is consumed waiting for output rather than doing useful work.

### Structured output pattern

When `shepherd.toml [gates]` tools support JSON output mode, prefer it:

```bash
# Instead of streaming to terminal (blocks; short-circuits):
{gates.lint}

# Prefer structured output with full-depth scan:
{gates.lint} --message-format=json --keep-going \
  > .shepherd/runs/{wave}-{gate}.json 2>&1
# (--keep-going flag requires build tool support; check language skill)
```

Parse the JSON without re-running:
```bash
# Language-agnostic: the language skill provides the exact jq / parsing recipe
# Example (Rust / cargo):
jq -r 'select(.reason == "compiler-message" and .message.level == "error") |
       "\(.target.name)\t\(.message.spans[0].file_name):\(.message.spans[0].line_start)\t\(.message.message[:80])"' \
  .shepherd/runs/{wave}-gate.json | sort -u
```

The result is a TSV table of `crate/module \t file:line \t message` — sortable
by file, clusterizable by file-disjoint scope.

### Cluster → parallel HF dispatch

After parsing, group errors by file (or by file-disjoint cluster if multiple
errors are in the same file):

```
cluster-A: crates/foo/src/bar.rs  (3 errors)
cluster-B: crates/baz/src/lib.rs  crates/baz/src/util.rs  (6 errors)
cluster-C: crates/qux/src/mod.rs  (12 errors)
```

Dispatch ONE @coder per cluster in a SINGLE Agent batch — this is a
`HOTFIX-DYNAMIC` dispatch (§II above). Each coder gets `[FILE-SCOPE]` = its
cluster's files; `[ACCEPTANCE]` = the specific error lines resolved.

**Wall-clock impact:** 3 clusters dispatched in parallel vs 3 serial HF coders
is typically a 3× reduction in wall-clock time from gate-red to gate-green.

### Where to store runs

`.shepherd/runs/` is the per-sprint run directory for structured gate output:

```
.shepherd/runs/
  w1-gate.json          ← Wave 1 gate structured output
  w1-hotfix-gate.json   ← Wave 1 HF wave re-gate
  w2-gate.json          ← ...
```

Add `.shepherd/runs/*.json` to the project's `.gitignore` (or equivalent) —
these are transient artifacts, not tracked state.

---

## XIV. Customization (project-level graph extensions)

Projects with non-standard sprint shapes extend the canonical graph via `[stage_graph]` in `shepherd.toml`:

```toml
[stage_graph]
custom_nodes_dir       = ".claude/stage-graph/"   # project-specific node templates
default_wave_count     = 2                         # auto-extend graph for L/XL sprints
hotfix_max_iterations  = 3
walk_trace_enabled     = true                      # write {paths.reports}/<date>-walk.md

[stage_graph.custom_nodes]
# Project-specific node types (e.g., schema-migration nodes)
schema-migrate = { type = "WAVE-IMPL", agents = [{ role = "coder", count = 1 }], constraint = "single-writer" }
```

The framework defaults work for most projects; the customization layer is optional.

---

## XV. Migration from pre-4.2.0 plans

Plans authored before v4.2.0 (no `## Stage Graph` section) continue to work. The conductor falls back to the §III §1/§2/§3 sequencing in `SKILL.md`. New plans (v4.2.0+) MUST emit the Stage Graph; the engineer's plan-quality bar (in `agents/engineer.md`) is updated to require it.

The cutover plan:

| Sprint | Required |
|---|---|
| First sprint after v4.2.0 install | engineer SHOULD emit Stage Graph; conductor MAY fall back |
| Subsequent sprints | engineer MUST emit Stage Graph; conductor MUST walk it |

---

## XV-bis. Worktree `target/` policy (v5.0.4)

Question raised in v5.0.3 axiom dev.5 §6: are git worktrees fully `target/`-
isolated, or do they share the parent's build cache?

**Answer:** worktrees DO share the parent's build cache by default (each
worktree creates `target/` at its own root, but the cargo invocation path
honors `CARGO_TARGET_DIR` if set; the workspace root's `target/` is the
default lock-target unless overridden). On macOS APFS + git ≥2.40 this
behavior is consistent.

**Policy:** the coder's "no cargo / no build tools in worktree" prohibition
remains in force (per `agents/coder.md` Hard Prohibitions). Concurrent
cargo invocations across N worktrees in the same workspace can deadlock on
the parent `target/` lock under load. The conductor runs ONE validation
pass at sprint root after worktrees are merged. Coders produce correct
code; the wave-gate verifies it.

Projects that want per-worktree `target/` isolation can set
`CARGO_TARGET_DIR=$WORKTREE_PATH/.cargo-target` in their shepherd.toml
`[env]` block — but the framework default is shared, with the prohibition.

## XV-ter. Operator-directed amendments — SendMessage vs spawn

> Field origin: shepherd v5.0.3 conductor feedback (axiom v0.3.0-dev.5),
> §7. Conductor used `Agent({ subagent_type: shepherd:engineer, prompt:
> "SendMessage to: <id>..." })` thinking it was sending a follow-up to the
> existing engineer; it actually spawned a SECOND engineer. The first
> engineer's plan was already in flight; the second engineer's amended
> plan landed AFTER. Conductor reconciled by reading the latest-written
> plan file.

The mechanics:

| Tool call | Effect |
|---|---|
| `Agent({ subagent_type: X, prompt: P })` | ALWAYS spawns a NEW agent. Prompts that LOOK like SendMessage syntax do nothing special — they're treated as the new agent's initial prompt. |
| `SendMessage({ to: <id>, message: M })` | Sends a follow-up message to an EXISTING running agent (must have a current id). |

When a mid-flight amendment arrives, the conductor's preferred path is:

1. **Edit the seed `.md` directly** (per `doctrines/chain-repair.md`).
2. **Re-dispatch the engineer with `Agent({ ... })`** (a fresh planning
   pass on the amended seed) — DO NOT try to SendMessage to the
   already-running engineer; the in-flight engineer can't see the seed
   edit anyway.
3. **Reconcile** by reading the latest-written plan file (most-recent
   mtime under `{paths.plans}/`).

The SendMessage path is appropriate for narrow, conversational follow-ups
to a still-running agent — NOT for amendment loads that should restart
the planning pass.

## XV-quater. Shared-context append discipline

When two coder lanes both write to the same `.shepherd/ctx/*.md` file,
cherry-picks regularly conflict on shared headers/footers. The brief-
authoring conductor includes either:

- **Section line-range** — "your edit applies to lines N..M; do not
  touch outside that range";
- **Footer-append** — "your contribution appends a single bullet to
  the bottom-of-file note section" (additive merges, no conflict).

See `doctrines/coder-brief-format-shared-artifacts.md`.

## XV-quint. Cross-lane dependencies (PAUSE-FOR-DEPENDENCY subgraph retired — #70)

> v6.0.1: the `PAUSE-FOR-DEPENDENCY` / `RESUME-LANE` satellite subgraph is
> deleted.

A cross-lane dependency is a **graph edge** the engineer composes — the
conductor's compiled segment `await`-orders the producer batch before the
consumer batch (`doctrines/native-coordination.md`, `doctrines/dispatch-cascade.md
§IV-bis`). A coder/worker that hits genuinely out-of-scope work files a
`BRIEF-AMENDMENT REQUEST` (so the engineer re-meshes the edge) or surfaces a
finding / GH issue at close — it does **not** mid-lane pause. There is no
satellite dispatch, no resume-condition dance, and no `<ns>/pauses/` registry.

---

## XV-sext. WAVE-GATE cargo invocation rule (v5.0.9)

> Field origin: shepherd v5.0.8 conductor feedback (axiom v0.3.2-dev.0) §5.

The WAVE-GATE gate sequence **MUST run cargo invocations sequentially** — never
as parallel background processes:

```bash
# CORRECT — single chained call; cargo parallelizes internally via -j nproc
{gates.format} && {gates.check} && {gates.lint}

# WRONG — cargo blocks on shared target/ lock; total time ≥ sequential
cargo check & cargo clippy & wait
```

See `doctrines/cargo-sequential-gates.md` for the full rule. This applies to
the conductor's WAVE-GATE inline runs and any `@worker` running build verification.

---

## XV-sept. Phase 0 MCP availability + /reload-plugins (v5.0.9)

> Field origin: shepherd v5.0.8 conductor feedback (axiom v0.3.2-dev.0) §7, §8.

When `[mcp].supabase = true` (or any other `[mcp].*` flag) but the tool prefix
is not callable at session start:

1. **Surface the unavailability explicitly** — do not silently degrade to shell
   (`psql`, `sentry-cli`, etc.).
2. **Request operator to run `/reload-plugins`** — this refreshes the MCP
   catalog without restarting the session.
3. **After reload**, re-verify. If still unavailable: degrade to CLI/shell and
   annotate the mesh report with the degraded surface.

MCP tool preference over shell fallbacks (Supabase example):
1. `mcp__plugin_supabase_supabase__execute_sql` — structured rows, advisory-aware
2. `mcp__plugin_supabase_supabase__get_advisors` — security + perf advisors
3. Shell `psql` — degraded fallback only; flag it

Full doctrine: `doctrines/plugin-reload-escape.md`.

---

## XVI. See also

- `doctrines/stage-graph.md` — the principle (graph is the contract)
- `SKILL.md` §III — sprint sections (still valid; graph specializes them)
- `flock.md` — per-agent dispatch rules (graph nodes cite these)
- `agents/engineer.md` — plan emits the graph
- `references/seed-template.md` — seed sketches the partial graph (non-binding hint)
- `references/agent-briefs.md` — brief templates referenced by node `agents` blocks
- `doctrines/pattern-b-overlap.md` — encoded as `parallel_with` graph constraint
- `doctrines/chain-repair.md` — encoded as the CHAIN-REPAIR node + on-mechanical-drift edge
- `doctrines/subtract-dont-add.md` — encoded as on-grade-cap edge from CLOSE-SWARM
- `doctrines/issue-ledger-awareness.md` — encoded as completeness-auditor input
- `doctrines/carry-forward-refresh.md` — encoded as completeness-auditor input
- `doctrines/gates-restoration.md` — encoded as the GATES-DISCOVERY conductor-inline node (v5.0.3)
- `doctrines/conductor-cwd.md` — companion discipline for graph-walk Bash hygiene (v5.0.3)
- `doctrines/native-coordination.md` — cross-lane deps via in-script ordering (pause-for-dependency retired, #70)
- `doctrines/cargo-sequential-gates.md` — cargo must run sequentially at WAVE-GATE (v5.0.9)
- `doctrines/plugin-reload-escape.md` — /reload-plugins escape hatch for MCP unavailability (v5.0.9)
- `doctrines/dispatch-cascade.md` — Stage Graph as rule engine; `shctx plan extract` + `shctx graph` mechanize the walk (v5.0.9)
- `commands/spawn.md` — `/shepherd:spawn --auto` (loop the walk algorithm) and `--parallel <N>` (N concurrent walks with cross-graph join at CLOSE-FINALIZE)
- `doctrines/workflow-compile-down.md` — the φ node→construct map (§V) is derived from this node taxonomy; compiled fanout segments preserve the walk's predicate semantics (§IV)
