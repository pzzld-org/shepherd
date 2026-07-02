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

This file owns the canonical dispatch DAG for a shepherd sprint — the bridge between **declarative planning** (planter authors seed, engineer authors plan) and **deterministic execution** (conductor walks graph, fires next-eligible stages). Once the engineer commits the plan, the conductor's job is "walk the graph": no fresh sequencing decisions, no re-reading flock.md mid-sprint, no checklist-juggling.

> **Reads with:** `SKILL.md` §III (sprint sections), `flock.md` (per-agent dispatch), `agents/engineer.md` (plan emits the graph), `references/seed-template.md` (planter sketches the graph), `doctrines/stage-graph.md` (the principle).

---

## I. Why a graph

Pre-4.2.0: SKILL.md §III lists phases, flock.md lists per-agent triggers, the plan describes wave composition in prose — the conductor synthesizes "what to dispatch next" by re-reading all three at every decision point.

4.2.0 model: the engineer's plan emits one declarative artifact — the Stage Graph — naming every dispatch event, its preconditions, its agents, its outputs, and its successor edges. Conductor runtime becomes mechanical: at each tick, find nodes whose predecessors are satisfied, batch per parallel-safety rules, fire, await, evaluate edge predicates, advance. Halt only on hard-stop predicates.

| Benefit | Mechanism |
|---|---|
| Drift reduction | Every dispatch maps to a named graph node — off-graph work is an auditor-catchable violation |
| Cognitive-load reduction | Conductor reads the graph instead of choosing "what next" |
| Deterministic execution | Same plan + graph + predicates → same dispatch sequence |
| Auditable provenance | Every commit traces to a graph node; every node traces to a plan section |
| Pattern B is structural | "Audit Wave N + impl Wave N+1 in one batch" is a graph shape |
| Hot-fix discipline | Hot-fix subgraphs are first-class, never improvised |
| Autorun simplifies | Loop = "walk graph until terminal node, re-seed, re-walk" |

---

## II. Stage taxonomy (the node types)

Every node is one of these types. The type determines dispatch shape (single agent / parallel batch / conductor-inline) and legal edge predicates.

| Type | Dispatch shape | Owner | Produces |
|---|---|---|---|
| `SEED-AUTHOR` | Conductor inline: present seed → pass-through; missing seed (single `--scope sprint` only) → one turn-ending confirm, then planter inner frame (`agents/planter.md §Plant mode`) authors it from the operator reply + planter mesh, gated by `shctx seed verify`. Multi-sprint / `--parallel` routes to `/shepherd:plant` (`spawn.md` Check 6). v6.2.1. | Conductor / root | committed, `SEED-GATE`-passed seed (or pass-through) |
| `SEED-VERIFY` | Conductor inline | Conductor | seed-loaded boolean + drift-suspicion flag |
| `MESH` | Single `@engineer` (Opus) | @engineer | Phase 0 mesh report + plan + the Stage Graph itself |
| `CHAIN-REPAIR` | Conductor inline (verify) → Edit (amend seed) → re-fire `MESH` | Conductor | amended seed (or escalation) |
| `PLAN-GATE` | Single `@critic` | @critic | verdict ∈ {GREEN, YELLOW, RED} |
| `PLAN-REVISION` | Single `@engineer` | @engineer | revised plan (max once before pass-2) |
| `DEDUP-GATE` | Conductor inline (every step's `[DO-NOT-DUPLICATE]` greps + `[SKILLS]` mechanical recompute) | Conductor | dispatch-allowed boolean + amended briefs (`doctrines/zero-duplicate-tolerance.md`) |
| `GATES-DISCOVERY` | Conductor inline (every configured gate, verbose, teed to discovery report) | Conductor | full latent-error inventory (`doctrines/gates-restoration.md` — precedes any gate-restoration `WAVE-IMPL`, typically Wave 0) |
| `WAVE-IMPL` | Parallel batch of N `@coder` (one per step) + `@worker` IO-bound batch in the SAME message | @coder + @worker | committed worktrees |
| `WAVE-GATE` | Conductor inline (rebase + four-step gate) | Conductor | gate-pass boolean + rebased commit |
| `LANE-CLOSE` | Conductor inline (`shctx close-lane <lane-id>`), fires after each `WAVE-GATE` per lane | Conductor | carry-forward + dedup ledger auto-resolved (v5.0.3 §2.7) |
| `LANE-INTEGRATE` | Root-owned conductor inline seam (never compiled into a Dynamic Workflow); fires after a teammate lane completes, before root merges the lane diff into dev. Root reviews the diff; large diffs (≥ 200 lines) get an `@auditor` diff-review concern first. Root-exclusive in spawn mode; solo conductor IS root, integrates directly. v6.0.9, #99. | Root (spawn) / Conductor (solo) | lane diff reviewed + merged, or blocked for auditor concern |
| `CANONICAL-TYPES-REFRESH` | Single `@worker` (bounded, non-competing), fires at every dev.0 | @worker | refreshed `{paths.ctx}/canonical-types.md` |
| `WAVE-AUDIT` | Parallel batch of M `@auditor` (concern-split, scoped to wave N) | @auditor | per-wave audit reports + GH findings |
| `HOTFIX` | One or more `@coder` (≤ 3 concurrent, ≤ S each), count pre-declared in plan | @coder | committed worktrees per finding |
| `HOTFIX-DYNAMIC` | Variable-cardinality `@coder` batch, count derived from gate-error cluster analysis at runtime | @coder | committed worktrees; count not pre-declared |
| `CLOSE-SWARM` | Parallel batch of 3–5 `@auditor` (concern-split, full sprint scope) | @auditor | close-time audit reports + grades + GH findings |
| `CLOSE-FINALIZE` | Conductor inline | Conductor | close report + handoff + memory + rebase + DELETE dev branch + cut next |
| `RELEASE` | Conditional on dev.{last}; runs per `[release].driver` | Conductor or CI | tag + GH release + next patch branch + dev.0 |
| `WORKER-IO` | One or more `@worker` (bounded, non-competing) | @worker | bounded reports |
| `HARD-STOP` | Conductor inline (terminal) | Conductor | operator-surfaced halt block |
| `PAUSE` | Conductor inline (terminal under `/shepherd:start`; bypassed under `/shepherd:spawn --auto`) | Conductor | end-of-sprint waypoint |
| `DISCOVERY` | Single or parallel `@discovery` (v5.1.1+), gate-free fan-out, compiles to a Dynamic Workflow (φ map, `doctrines/workflow-compile-down.md §V`; incl. plant-mode 1–3 read-only lanes, #119) | @discovery | DISCOVERY REPORT at `{paths.reports}/<date>-discovery-<id>.md` |
| `INTRO-COMBO-WAVE` | Parallel batch of `@discovery` + `@auditor` (intro-mode) (v5.1.1+), gate-free fan-out, compiles to a Dynamic Workflow (`doctrines/workflow-compile-down.md §V`); conductor-inline Lane 0 (patch-branch advancement) runs as a §VI seam before the batch | both | Mesh-input bundle: discoveries + regression + carry-forward-disposition reports |
| `DISCOVERY-COMBO-WAVE` | Parallel batch of `@auditor` + `@discovery` + optional `@worker` (body-phase) (v6.0.8+), gate-free fan-out, compiles to a Dynamic Workflow (`doctrines/workflow-compile-down.md §V`; `doctrines/discovery-combo-wave.md`) | all three | `BODY-AGGREGATE` (conductor inline) → feeds next wave or PLAN-GATE |

Each node carries:

```
node id        — short slug (e.g., "wave-2-impl", "close-swarm")
type           — one of the table above
in_predicates  — list of {predecessor-id, edge-label} pairs that must hold to fire
parallel_with  — list of node-ids that MUST fire in the same Agent batch (Pattern B encoded here)
agents         — list of {role, count, brief-ref} (empty for conductor-inline)
out_edges      — list of {label, target-node-id}
```

**HOTFIX-DYNAMIC cardinality.** Unlike `HOTFIX` (count pre-declared), `HOTFIX-DYNAMIC` derives its coder count at walk-time from gate-error cluster analysis. The dispatch vehicle follows the cardinality ladder (`doctrines/hotfix-dispatch.md`, #135): `H=1` cluster → ONE single subagent (never a teammate); `H ∈ (1,5]` → ONE batched dynamic workflow dispatched by root; `H ≥ 6` → a dedicated HOT-FIX lane. Derivation:

1. Run the gate with structured JSON output (`{gates.lint} --message-format=json --keep-going > .shepherd/runs/w{N}-gate.json 2>&1`, or `{gates.lint} 2>&1 | tee .shepherd/runs/w{N}-gate.txt` if unsupported).
2. Parse errors, cluster by **file-disjoint scope**: each cluster becomes one parallel HF coder step.
3. Dispatch all clusters in ONE Agent batch (same zero-overlap parallel-safety rules as WAVE-IMPL).
4. After all HF coders return, re-run the gate ONCE. If still failing, escalate (cap 3 HOTFIX iterations per gate).

A `HOTFIX-DYNAMIC` node's YAML sets `cardinality: "1..cluster_count"` (auto-derived at walk-time) and `per_instance_brief:` a template rather than per-step briefs (shape in §XII). This encodes HF-cascade parallelism structurally instead of requiring the engineer to pre-declare N specific HF steps it cannot know at plan time.

The plan's `## Stage Graph` section enumerates every node. The conductor parses it at sprint open and walks it.

**SQL fast-path (v5.0.0+).** Before per-step greps, the conductor runs `shctx query dedup-check --name=<step.new_symbol>` for each step. A registry hit BLOCKS with the standard recommendation block (citing the DB row's `file_path:line`) and saves the grep step; the grep remains the contract of record — a registry miss does NOT skip it, since registry rows are derived and may be stale.

---

## III. Edge predicates (the labels)

Each edge label is a runtime predicate the conductor evaluates against the predecessor's output.

| Label | Means |
|---|---|
| `unconditional` | Fires when predecessor completed (any exit) |
| `on-green` | Predecessor's verdict/grade was GREEN / no-finding |
| `on-yellow` | Critic YELLOW (revision lane) |
| `on-red` | Critic RED — terminal, escalates to HARD-STOP |
| `on-no-drift` | MESH found no SEED-DRIFT |
| `on-mechanical-drift` | MESH found mechanical drift → CHAIN-REPAIR |
| `on-substantive-drift` | MESH found substantive drift → HARD-STOP (`chain-repair.md`) |
| `on-amend` | CHAIN-REPAIR amended seed → re-fire MESH |
| `on-pass` | WAVE-GATE: all gates green |
| `on-fail` | WAVE-GATE: a gate failed → HOTFIX or HARD-STOP |
| `on-finding` | WAVE-AUDIT or CLOSE-SWARM: CRITICAL/HIGH found → HOTFIX |
| `on-no-finding` | Audit produced no CRITICAL/HIGH |
| `on-grade-cap` | CLOSE-SWARM completeness grade-caps (`subtract-dont-add.md` / `issue-ledger-awareness.md`) — lowers grade, does not fail the sprint |
| `on-budget-exceeded` | WORKER-IO budget exhausted; informational |
| `on-coder-complete` | WAVE-IMPL: ALL coders reported back |
| `on-rebase-clean` | WAVE-GATE: rebase-merge applied with no conflicts |
| `on-dedup-clear` | DEDUP-GATE: every grep returned the expected count |
| `on-dedup-block` | DEDUP-GATE: a grep returned > expected; loops to brief-amendment then re-fires DEDUP-GATE |
| `on-hard-stop` | Any node into HARD-STOP terminal — operator must intervene |
| `on-research-complete` | (v5.1.1+) DISCOVERY report written; targets downstream consumer (MESH, HOTFIX-DYNAMIC, etc.) |
| `on-intro-wave-complete` | (v5.1.1+) Fan-in when ALL INTRO-COMBO-WAVE members complete; targets MESH |
| `on-intro-audit-complete` | (v5.1.1+) Intro-mode auditor report written |

A node with multiple `out_edges` is a branch point — exactly one outgoing edge fires per evaluation. A node with multiple `in_predicates` is an AND-join (fires only when ALL inbound predicates are satisfied). The graph does not support OR-joins; those are separate nodes.

---

## IV. The canonical sprint graph (default shape)

Default DAG every `/shepherd:start` walks unless the engineer's plan customizes it:

```
SEED-AUTHOR ─on-green(seed committed+gated)→ SEED-VERIFY ─on-green→ MESH
  MESH ─on-mechanical-drift→ CHAIN-REPAIR ─on-amend→ (loop to MESH)
  MESH ─on-substantive-drift→ HARD-STOP
  MESH ─on-no-drift→ PLAN-GATE (@critic)
    PLAN-GATE ─on-yellow→ PLAN-REVISION(@engineer ×1) ─on-pass-2-green→ DEDUP-GATE
    PLAN-GATE ─on-red→ HARD-STOP
    PLAN-GATE ─on-green→ DEDUP-GATE (conductor inline; every lane's [DO-NOT-DUP] greps + skill recompute)
      DEDUP-GATE ─on-dedup-block→ (loop back to brief-amend, re-fire)
      DEDUP-GATE ─on-dedup-clear→ WAVE-1-IMPL ║ WORKER-IO (same batch)
        WAVE-1-IMPL/WORKER-IO ─on-coder-complete→ WAVE-1-GATE (conductor: rebase + 4-step gate)
          WAVE-1-GATE ─on-fail→ HOTFIX (≤3) → loop to WAVE-1-GATE
          WAVE-1-GATE ─on-pass→ Pattern B batch: WAVE-1-AUDIT ║ WAVE-2-IMPL (same message)
            WAVE-1-AUDIT ─on-finding→ HOTFIX (≤3)
            WAVE-2-IMPL ─on-coder-complete→ WAVE-2-GATE ─on-pass→ ... (iterate Pattern B per wave)
              ... → CLOSE-SWARM (3–5 @auditor; + completeness ledger refresh + SUBTRACT check)
                CLOSE-SWARM ─on-finding→ HOTFIX-CLOSE (≤3) → CLOSE-FINALIZE
                CLOSE-SWARM ─on-no-finding / on-grade-cap→ CLOSE-FINALIZE (handoff + rebase + DELETE + cut next)
                  CLOSE-FINALIZE ─on-not-dev.last→ PAUSE (or loop spawn)
                  CLOSE-FINALIZE ─on-dev.last→ RELEASE (per [release].driver)
```

The default sprint has 10–12 nodes for a typical M sprint (including the `SEED-AUTHOR` open node — a pass-through when a seed exists), more for L/XL (more `WAVE-N` clusters), fewer for XS/S (single wave + close).

---

## V. The conductor's walk algorithm

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

> **WAVE-GATE inline step — spawn mode (v6.0.3, #100):** when executing a WAVE-GATE node conductor-inline, root releases the next wave via `TaskUpdate(status: completed)` on the `wave-{N}-gate-{sprint_slug}` marker; lanes' wave-(N+1) IMPL tasks carry `addBlockedBy` on it and cannot be claimed until release. Mechanical, not prose.

The conductor does NOT add ad-hoc nodes mid-walk. A need the graph doesn't anticipate (e.g. a fourth hot-fix wave when the graph allows three) IS a graph violation — surface to the operator, amend the plan (re-running `PLAN-GATE` with the new graph) or escalate. The graph is the contract; the walk is mechanical; deviation is structural and visible.

**Mechanization (v5.0.9 dispatch cascade):** `shctx graph` implements the walk (`doctrines/dispatch-cascade.md`). After MESH, the conductor runs `shctx plan extract <plan.md>` to materialize the graph into `<ns>/graph/state.json`, then loops:

```bash
shctx graph next   # → batch of ready nodes (parallel_with cliques honored)
# dispatch via Agent tool in ONE message
shctx graph mark <id> --state=done --exit=<edge-label>
# downstream nodes auto-promote to "ready" when all in_predicates satisfied
```

`shctx graph trace` is the append-only event log feeding `adaptation-loop.md §V-bis` node-level telemetry. The conductor's only LLM-driven step per tick is brief authoring + edge-label selection; routing is mechanical.

**Cache-first brief ordering (v5.1.3+).** Every brief follows stable-framing-first / variable-content-last (`doctrines/brief-cache-discipline.md`): **Stable (top):** `[ROLE]` → `[SKILLS]` → `[DOCTRINES]` → `[PROTOCOL-REMINDERS]`. **Variable (bottom):** `[FILE-SCOPE]` → `[CONTEXT-INVENTORY]` → `[DO-NOT-DUPLICATE]` → `[ACCEPTANCE]` → `[NON-GOALS]` → `[WORKTREE]` → `[BASE-COMMIT-EXPECTED]`. Stable sections are cached as the brief prefix and reused verbatim across a sprint's dispatches; variable sections live at the tail. The completeness auditor checks ordering at close (LOW per violation; MEDIUM if > 30% of captured dispatches violate). Per-role hit-rate telemetry: `doctrines/cache-telemetry.md`.

---

## VI. Pattern B is a graph shape, not a checklist item

`doctrines/pattern-b-overlap.md` used to be a discipline the conductor remembered. Now it's a graph constraint:

```
WAVE-N-AUDIT.parallel_with = [ WAVE-(N+1)-IMPL ]
WORKER-IO.parallel_with = [ WAVE-1-IMPL ]
```

Nodes with `parallel_with` set MUST fire in the same Agent batch — the walk algorithm enforces this by construction. A conductor that fires them sequentially is walking the graph wrong. Workers join the Wave 1 dispatch batch automatically; no "remember to fire workers at Wave 1 START" cognitive load.

---

## VII. Hot-fix subgraphs

When `WAVE-N-AUDIT` returns `on-finding`, the graph routes to a small HOTFIX subgraph:

```
WAVE-N-AUDIT ─on-finding→ HOTFIX (≤3 parallel coders) ─on-coder-complete→
  WAVE-N-GATE-RERUN (conductor re-runs the 4-step gate) ─on-pass→
    (rejoin main flow at WAVE-(N+1)-IMPL)
```

The HOTFIX node carries a finding-id binding, a `[FILE-SCOPE]` ≤ S, and an iteration cap (default 3 retries before HARD-STOP). The conductor does NOT compose hot-fix briefs from scratch — the auditor's report includes a `Suggested hot-fix lane: [FILE-SCOPE] ... [ACCEPTANCE] ...` block (`agents/auditor.md` Report Shape) the conductor pastes verbatim into the HOTFIX brief.

---

## VIII. The CLOSE subgraph (where doctrines compose)

`CLOSE-SWARM`'s auditors carry concern-bound responsibilities:

| Auditor concern | Doctrines invoked | Edge contribution |
|---|---|---|
| `code-quality` | `code-style:<lang>`, `wrapper-must-earn` | `on-finding` if hits in lane-modified files |
| `data-flow` | project-doctrines (money path) | `on-finding` if fail-closed semantics violated |
| `dependency-topology` | `wrapper-must-earn`, `subtract-dont-add` (dep delta) | `on-finding` for new build-manifest deps without justification |
| `datastore-state` | (project-specific) | `on-finding` for advisor warnings |
| `completeness` | `subtract-dont-add`, `issue-ledger-awareness`, `carry-forward-refresh` | `on-grade-cap` if real-work fails OR SUBTRACT violation OR ledger silence |

`on-grade-cap` does NOT fire HOTFIX (the violation isn't fixable mid-sprint); it lowers the recorded grade and continues to `CLOSE-FINALIZE`. The grade-cap is provenance, not a re-dispatch trigger.

---

## IX. The autorun walk (loop semantics)

Under `/shepherd:spawn --auto`, after `CLOSE-FINALIZE` for sprint N, the planter: (1) runs `references/branching-model.md §II.4` (DELETE + cut next); (2) spawns a fresh teammate-conductor for sprint N+1 (loads new seed, builds new graph); (3) the teammate walks the new graph.

The loop terminates on: `HARD-STOP` fired anywhere; `PAUSE` fired (only under `/shepherd:start` — spawn --auto bypasses by definition); or dev.{last} `CLOSE-FINALIZE` returns `on-dev.last` with no sprint-through grant, exiting to the operator before `RELEASE`.

Autorun is structurally simpler in 4.2.0: "loop the walk algorithm". `PAUSE` is simply absent from the spawn --auto graph — no special-cased skip logic. Full loop mechanics: `commands/spawn.md §--auto flag`.

---

## X. The parallel walk (worktree fan-out)

Under `/shepherd:spawn --parallel <N>`, the planter fans out N sibling teammate-conductors. Each receives an independent graph, walks it in its own worktree, and joins at `CLOSE-FINALIZE` in dev-order — `dev.{N+1}` waits for `dev.{N}` to finalize before its own `CLOSE-FINALIZE` fires:

```
sprint-{N+1}.CLOSE-FINALIZE.in_predicates += [ sprint-{N}.CLOSE-FINALIZE.completed ]
```

Max concurrent sprint count is 4 (N must be 2–4 per `commands/spawn.md §Preflight Check 5`); the planter enforces this before spawning any teammate. Full mechanics: `commands/spawn.md §--parallel flag`.

---

## XI. Where the graph lives

Two layers, each more concrete than the prior (the seed's non-binding `## Stage decomposition hint` §7-bis was removed in v6.2.1 — the engineer authors the graph from Phase-0, so a parallel planter sketch was throwaway):

| Layer | File | Author | Detail level |
|---|---|---|---|
| Contract | `{paths.plans}/{sprint_slug}.plan.md` §"Stage Graph" | Engineer | Full DAG: every node, edge, predicate, brief-ref — this is what the conductor walks |
| Trace | `{paths.reports}/<date>-{sprint_slug}-walk.md` | Conductor (auto, optional) | Append-only log of node fires, edge evaluations, batch composition — for post-hoc audit |

The seed's hint is non-binding — the engineer rebuilds against Phase 0 mesh evidence. The plan's Stage Graph is binding — the conductor walks it verbatim. The walk trace is optional but encouraged for L/XL sprints; the auditor's `completeness` concern reads it at close to verify every commit corresponds to a graph node fire.

---

## XII. Plan-section format (what the engineer emits)

The engineer's plan includes a `## Stage Graph` section with one YAML block per node:

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
  # LANE-INTEGRATE nodes (spawn mode only) follow the same shape: in_predicates
  # off the lane's wave-gate, an auditor diff-review agent gated by a
  # size_gate_threshold condition, out_edges on-integrate-clean/-blocked/-hard-stop.
  # Full field list: §II node-taxonomy row for LANE-INTEGRATE.

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

1. **Off-graph dispatches** — a coder commit whose step id doesn't match any `WAVE-IMPL` node.
2. **Skipped Pattern B** — `WAVE-N-AUDIT` fired strictly before `WAVE-(N+1)-IMPL` instead of same batch.
3. **Missing HARD-STOP edges** — every branch point must have an `on-hard-stop` outgoing edge.
4. **Implicit hot-fix loops** — a HOTFIX subgraph looping > 3 times without operator surface.
5. **CLOSE-SWARM without grade-cap edge** — completeness can grade-cap; the graph MUST encode that path.
6. **WORKER-IO not parallel-with WAVE-1-IMPL** — workers are IO-bound; deferring them is a documented anti-pattern (`flock.md` §V.8).
7. **CHAIN-REPAIR without amend-and-loop edge** — drift found but seed not amended.
8. **WAVE-IMPL without preceding DEDUP-GATE** — per `doctrines/zero-duplicate-tolerance.md`, every WAVE-IMPL needs a DEDUP-GATE predecessor with `on-dedup-clear`. Skipping it is how duplicate code lands.
9. **dev.0 plan without CANONICAL-TYPES-REFRESH worker** — `{paths.ctx}/canonical-types.md` must refresh at every patch's dev.0; omitting it ships a stale catalog and breeds duplicate-prone sprints.
10. **Teammate lane merged without `LANE-INTEGRATE` review (v6.0.9)** — root must run `LANE-INTEGRATE` before merging a lane diff into dev. A teammate merging itself triggers `TEAMMATE-GIT-WRITE`; a root skipping the review bypasses `doctrines/teammate-integration-authority.md`.

A graph failing any of these checks gets a `STAGE-GRAPH-VIOLATION` finding and grade-caps at C+ (per `subtract-dont-add` precedent).

---

## XIII-bis. Structured gate output + parallel HF dispatch (v5.0.6)

Streaming gate output has two costs: short-circuit masking (most compilers/linters stop at the first error, hiding downstream errors until the upstream fix lands) and blocking conductor context (the command blocks for minutes while context is consumed waiting). (#downstream Rust service field report, 2026-05-12: three serialized HF waves each unmasked a new error layer for want of a `--keep-going` run.)

**Structured output pattern.** When `shepherd.toml [gates]` tools support JSON output, prefer it over streaming:

```bash
# Instead of streaming to terminal (blocks; short-circuits):
{gates.lint}

# Prefer structured output with full-depth scan:
{gates.lint} --message-format=json --keep-going \
  > .shepherd/runs/{wave}-{gate}.json 2>&1
# (--keep-going flag requires build tool support; check language skill)
```

Parse the JSON without re-running (language-agnostic; the language skill supplies the exact jq recipe). Example, Rust/cargo:
```bash
jq -r 'select(.reason == "compiler-message" and .message.level == "error") |
       "\(.target.name)\t\(.message.spans[0].file_name):\(.message.spans[0].line_start)\t\(.message.message[:80])"' \
  .shepherd/runs/{wave}-gate.json | sort -u
```
Result: a TSV table of `crate/module \t file:line \t message`, sortable by file, clusterizable by file-disjoint scope.

**Cluster → parallel HF dispatch.** Group errors by file (or file-disjoint cluster if multiple errors share a file):

```
cluster-A: crates/foo/src/bar.rs  (3 errors)
cluster-B: crates/baz/src/lib.rs  crates/baz/src/util.rs  (6 errors)
cluster-C: crates/qux/src/mod.rs  (12 errors)
```

Dispatch ONE `@coder` per cluster in a SINGLE Agent batch (a `HOTFIX-DYNAMIC` dispatch, §II). Each coder gets `[FILE-SCOPE]` = its cluster's files, `[ACCEPTANCE]` = the specific error lines resolved. Wall-clock impact: 3 clusters in parallel vs 3 serial HF coders is typically a 3× reduction from gate-red to gate-green.

`.shepherd/runs/` is the per-sprint run directory for structured gate output (`w1-gate.json`, `w1-hotfix-gate.json`, `w2-gate.json`, ...). Add `.shepherd/runs/*.json` to the project's `.gitignore` — transient artifacts, not tracked state.

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

Plans authored before v4.2.0 (no `## Stage Graph` section) continue to work — the conductor falls back to the §III §1/§2/§3 sequencing in `SKILL.md`. New plans (v4.2.0+) MUST emit the Stage Graph; the engineer's plan-quality bar (`agents/engineer.md`) requires it.

| Sprint | Required |
|---|---|
| First sprint after v4.2.0 install | engineer SHOULD emit Stage Graph; conductor MAY fall back |
| Subsequent sprints | engineer MUST emit Stage Graph; conductor MUST walk it |

---

## XV-bis–sept. Field-derived operational notes

| Note | Rule | Doctrine / ref |
|---|---|---|
| **XV-bis. Worktree `target/` policy (v5.0.4)** | Worktrees share the parent's build cache by default (`CARGO_TARGET_DIR` honored if set; else workspace-root `target/` is the lock-target). Coder's "no cargo / no build tools in worktree" prohibition stays in force — concurrent cargo across N worktrees can deadlock on the shared lock. Conductor runs ONE validation pass at sprint root after worktrees merge. Projects wanting isolation set `CARGO_TARGET_DIR=$WORKTREE_PATH/.cargo-target` in `[env]`. | `agents/coder.md` Hard Prohibitions |
| **XV-ter. SendMessage vs spawn** | `Agent({subagent_type, prompt})` ALWAYS spawns a NEW agent — SendMessage-looking prompt text is just the new agent's initial prompt, not a follow-up. `SendMessage({to, message})` is the only way to reach an EXISTING running agent. Mid-flight amendment: (1) edit the seed `.md` directly, (2) re-dispatch the engineer with `Agent({...})` — a fresh planning pass, never SendMessage to the in-flight engineer (it can't see the seed edit), (3) reconcile by reading the latest-written plan file (most-recent mtime under `{paths.plans}/`). | `doctrines/chain-repair.md` |
| **XV-quater. Shared-context append discipline** | Two coder lanes writing the same `.shepherd/ctx/*.md` file conflict on shared headers/footers. Brief either a **section line-range** ("edit applies to lines N..M only") or a **footer-append** ("append one bullet to the bottom-of-file note section" — additive, no conflict). | `doctrines/coder-brief-format-shared-artifacts.md` |
| **XV-quint. Cross-lane dependencies (PAUSE-FOR-DEPENDENCY retired, v6.0.1, #70)** | A cross-lane dependency is a **graph edge** the engineer composes — the compiled segment `await`-orders producer before consumer. Out-of-scope work files a `BRIEF-AMENDMENT REQUEST` or surfaces a finding/GH issue at close; it never mid-lane pauses. No satellite dispatch, no resume-condition dance, no `<ns>/pauses/` registry. | `doctrines/native-coordination.md`, `doctrines/dispatch-cascade.md §IV-bis` |
| **XV-sext. WAVE-GATE cargo invocation rule (v5.0.9)** | Cargo invocations at WAVE-GATE **MUST run sequentially** — `{gates.format} && {gates.check} && {gates.lint}` (cargo parallelizes internally via `-j nproc`), never `cargo check & cargo clippy & wait` (deadlocks on the shared `target/` lock). Applies to WAVE-GATE inline runs and any `@worker` build verification. | `doctrines/cargo-sequential-gates.md` |
| **XV-sept. Phase 0 MCP availability + /reload-plugins (v5.0.9)** | When `[mcp].*` is configured but the tool prefix isn't callable at session start: surface the unavailability explicitly (never silently degrade to shell); request `/reload-plugins` to refresh the MCP catalog without restarting; re-verify, and only then degrade to CLI/shell with an annotation. MCP-over-shell preference (Supabase example): `execute_sql` → `get_advisors` → shell `psql` (degraded fallback only). | `doctrines/plugin-reload-escape.md` |

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
- `doctrines/hotfix-dispatch.md` — hot-fix dispatch cardinality ladder: `H=1` single subagent, `(1,5]` root-batched dynamic workflow, `H≥6` dedicated lane (v6.0.8, #135)
- `doctrines/teammate-integration-authority.md` — binding doctrine: teammate-conductors never integrate to the dev branch; `LANE-INTEGRATE` is the root-owned review gate (v6.0.9, #99)
- `commands/spawn.md` — `/shepherd:spawn --auto` (loop the walk algorithm) and `--parallel <N>` (N concurrent walks with cross-graph join at CLOSE-FINALIZE)
- `doctrines/workflow-compile-down.md` — the φ node→construct map (§V) is derived from this node taxonomy; compiled fanout segments preserve the walk's predicate semantics (§IV)
