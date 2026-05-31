---
title: dispatch cascade — Stage Graph as rule engine
description: |
  The plan IS the program; the conductor IS the interpreter; the Stage Graph
  IS the topology. Once the engineer's plan is extracted (`shctx plan extract`),
  the conductor walks the graph mechanically via `shctx graph next` / `mark` —
  no fresh sequencing decisions, no re-reading flock.md mid-sprint, no
  checklist-juggling. Halts and hot-fixes are structural — they extend the
  topology, they don't bypass it. (PAUSE-FOR-DEPENDENCY subgraphs retired
  v6.0.1 #70; cross-lane deps are now graph-edge await ordering.)
introduced: v5.0.9
field_origin: |
  Operator request 2026-05-13: "any chance we could create some type of rule
  engine layer that would generally allow the conductor (main chat) to
  dispatch basically all the agents at the beginning, using conditional links
  or whatever so that agents can basically cascade through the plan."
---

# Doctrine — Dispatch Cascade

## I. Why this exists

The pre-v5.0.9 model: the conductor reads the plan's Stage Graph as prose,
walks it in-context, decides "what next" by re-reading three files at every
tick (`SKILL.md §III`, `flock.md`, `plan.md`). That works but burns context
and forces every conductor session to re-derive identical sequencing logic
from a fixed structure that was authored once at MESH.

The v5.0.9 cascade model: the Stage Graph is **extracted once**
(`shctx plan extract`) into a canonical state file. The walker
(`shctx graph next`) returns the next-eligible batch deterministically.
The conductor's only LLM-driven step per tick is **dispatching** the batch
(authoring brief content, choosing model, parallel-batching with the Agent
tool). Routing is mechanical.

This is what "the plan IS the program" means: the engineer compiles the
seed into a topology; the conductor executes the topology; the operator
audits the trace.

## II. The pieces

| Artifact | Owner | Lifecycle |
|---|---|---|
| `plan.md` (`## Stage Graph` YAML block) | @engineer at MESH | Append-only after critic GREEN; CHAIN-REPAIR may force re-extract |
| `<ns>/graph/state.json` | `shctx plan extract` | Re-extracted on each MESH; replaces in place under `--force` |
| `<ns>/graph/trace.jsonl` | `shctx graph mark` (append-only) | One line per state transition; never rewritten |
| `<ns>/graph/compiled/<seg>.workflow.js` | `shctx graph compile` (#77) | Compiled fanout segment; regenerated deterministically from `state.json` |

## III. The walker contract

The walker is a **state machine**, not a planner. Its rules are mechanical:

1. **Ready = (state == "pending") ∧ (all in_predicates.satisfied)**. As soon
   as a node's predicates are all satisfied, its state transitions to
   `ready` and `shctx graph next` will return it.
2. **`next` honors `parallel_with` cliques.** Two nodes joined by
   `parallel_with` are returned together — the conductor fires them in
   ONE Agent message (per `doctrines/pattern-b-overlap.md`).
3. **Edges fire on exact label match.** `mark <node> --state=done
   --exit=<edge-label>` satisfies all downstream `in_predicates` whose
   `(predecessor, edge)` matches. Unmatched edges (e.g., `on-fail` when
   only `on-pass` was declared) cause the target to remain blocked
   — visible in `shctx graph status` as a stuck node.
4. **No mid-walk graph mutation by the conductor.** The graph is
   the contract. Extension points are structural:
   - HOTFIX subgraph (`pipeline.md §VII`)
   - CHAIN-REPAIR seed amendment + MESH re-fire (`doctrines/chain-repair.md`)
   These extensions are described by the doctrine; the walker honors
   them via the same mark/next interface.

## IV. The conductor loop (mechanical)

```text
while true:
    batch <- shctx graph next --json
    if batch.empty:
        if any node.state == "in_flight": wait for return  # only happens during human-time pauses
        else: break                                         # graph complete
    dispatch(batch)                                          # ONE Agent tool message
    for each completed node n:
        shctx graph mark n --state=done --exit=<edge-from-n's-output>
        # downstream readies are computed automatically
```

The dispatch step is the only LLM-driven step. Everything else is the
state machine.

## IV-bis. Compile-down — fanout segments run as Dynamic Workflows (v6.0.1, primary)

For a **gate-free agent-fanout segment** (a maximal run of WAVE-IMPL / WAVE-AUDIT /
CLOSE-SWARM / DISCOVERY / WORKER-IO / HOTFIX nodes bounded by operator gates and
conductor-inline FS/git nodes), the **primary** execution path is to compile the
segment to a Claude Code **Dynamic Workflow** and run it out-of-context, instead
of walking each `next` batch in the conductor's own context:

```text
batch <- shctx graph next --json
if batch is a gate-free agent-fanout segment:
    shctx graph compile --segment=<entry-node> --verify     # emits <seg>.workflow.js
    if §IV faithfulness diff FAILS (soundness|completeness|determinism):
        HALT — a mismatch is a compiler bug, not a plan defect (do NOT run the script)
    run the compiled workflow on the platform runtime (out-of-context)
    on runtime failure/unavailability:
        fall back to in-context dispatch(batch)              # the §IV loop — no parallel engine
    read the returned result object → shctx graph mark <each node> --state=done --exit=<edge>
else:
    dispatch(batch)                                          # seam / single-dispatch: in-context as before
```

Binding rules (full doctrine: `workflow-compile-down.md` §III–VI):

- **The compiler is the only script author.** The script is `compile(G_seg)` over
  the critic-gated graph — never free-form (`workflow-compile-down.md §X.1`). The
  §IV diff gates every compiled segment.
- **Seams stay at the conductor (§VI).** Operator gates, `WAVE-GATE` rebase,
  `LANE-CLOSE`, `CLOSE-FINALIZE`, and all SQLite+git canonical writes run at the
  conductor between segments. The workflow only coordinates agent fanout; the
  runtime's within-session resume is **never** canonical (`sqlite-canonical-state.md`).
- **Bounded fanout.** `compile` emits `Promise.all` batches of ≤16 concurrent,
  ≤1000 total; wider waves are chunked, preserving `parallel_with` semantics.
- **Read-only is allowlist-enforced (§VII, #74).** Compiled audit/discovery steps
  carry no edit/mutating tools — the `subagent_type` registry allowlist binds even
  though the runtime auto-approves edits (`acceptEdits`).
- **Mode-agnostic (#77 binding comment).** Solo `/shepherd:start` compiles its own
  fanout segments and gains out-of-context parallelism with **no team spawned**;
  under `/shepherd:spawn` each teammate-conductor compiles its **own lane's** fanout.
  No code path requires a team to be present.

## V. Pattern B is a clique, not a checklist

`parallel_with: [wave-1-impl]` on `worker-io` is **declarative**. When both
nodes' in_predicates are satisfied, `next` returns them as a batch. The
conductor does not need to remember "fire workers at Wave 1 START" —
that's encoded in the clique.

The same shape generalizes to any structural co-dispatch:
- `WAVE-N-AUDIT.parallel_with = [WAVE-(N+1)-IMPL]` — audit + next wave in one batch
- `HOTFIX-A.parallel_with = [HOTFIX-B]` (when ≤3 concurrent, disjoint scopes)
- Any custom topology the engineer expresses in the plan

## VI. Self-modifying subgraphs

Three doctrines describe runtime topology extensions. All three preserve
the walker's interface:

| Extension | Trigger | Topology change | Visible in trace |
|---|---|---|---|
| ~~PAUSE-FOR-DEPENDENCY~~ | *(retired v6.0.1 #70 — replaced by in-script await ordering, `doctrines/native-coordination.md`)* | — | — |
| HOTFIX | WAVE-AUDIT returns `on-finding` | Insert HOTFIX node + WAVE-GATE-RERUN | `subgraph_inserted` |
| CHAIN-REPAIR | MESH returns `on-mechanical-drift` | Conductor edits seed + re-fires MESH | `chain_repair`, `mesh_re_extract` |

In each case the walker is paused, the subgraph is inserted (either via
`shctx plan extract --force` or `shctx graph` direct manipulation), and the
walker resumes. The walker doesn't know "what" happened — only that nodes
moved between states.

## VII. Adaptation feedback (rigorous integration with `adaptation-loop.md`)

The trace is the substrate for self-learning. Each `mark` event records
`from`, `to`, `exit_edge`, `agent_id`, and timestamp. The completeness
auditor at CLOSE-SWARM reads the trace alongside reports to compute
per-node telemetry:

- **Duration** per node (exited_at − started_at)
- **Halt rate** per node-type across sprints (`shctx graph trends`, v5.0.10+)
- **Edge frequency**: how often `on-finding` vs `on-no-finding`, etc.
- **Await-edge-per-lane** rate: do certain lane types reliably produce cross-lane graph-edge await dependencies?

The auditor's sprint-pattern entry (per `adaptation-loop.md §I`) records
node-level summaries. The engineer at the next sprint's Phase 0 mesh
(row 10) can then weight planning decisions on real per-node history:

- "MESH took 4× longer than the prior 3 sprints' average → seed may be
  ambiguous; surface to operator."
- "WAVE-2-IMPL has fired HOTFIX 4/5 sprints → wave too large; decompose."
- "Await-edge dependency on `crates/engine` fired 3 sprints in a row →
  add a Lane 0 to expose its public API more broadly."

This converts the framework from "graph-as-documentation" to
"graph-as-feedback-substrate."

## VIII. What the cascade does NOT do

- **Does not author briefs.** Dispatch content is still LLM-driven; the
  walker only routes.
- **Does not pick exit labels.** The conductor evaluates the node's
  output and chooses the matching edge label (`on-green`, `on-fail`,
  etc.). The walker has no opinion on which exit is correct.
- **Does not bypass the engineer.** Plan revisions still go through
  `@engineer` + `@critic`. The walker re-extracts the new plan; it does
  not mutate the topology directly.
- **Does not eliminate the operator pause.** `PAUSE` (the terminal node
  under `/shepherd:start`) is structural — the walker stops cleanly
  when it's reached. Autorun graphs simply don't include it.

## IX. Operational quick-reference

```bash
# Once after MESH (engineer plan ready):
shctx plan extract {paths.plans}/{sprint_slug}.plan.md
shctx plan validate

# At every dispatch tick:
shctx graph status              # what's where
shctx graph next                # batch to fire NOW (parallel_with respected)

# Gate-free agent-fanout segment → compile + run out-of-context (PRIMARY, v6.0.1, #77):
shctx graph compile --segment=<entry-node> --verify   # §IV diff MUST pass before running
# … run the emitted <seg>.workflow.js on the platform runtime;
#    on runtime failure, fall back to in-context `dispatch(batch)` …
# Seam / single dispatch → fire via the Agent tool as before.

shctx graph mark <id> --state=done --exit=<edge>

# Inspect after the fact:
shctx graph trace --tail=50     # last 50 transitions
shctx graph compile --list      # gate-free fanout segments available to compile
```

## X. See also

- `pipeline.md` — Stage Graph node taxonomy + edge labels + walk algorithm (the abstract spec the walker implements)
- `agents/engineer.md §Phase 2` — plan template that emits the YAML Stage Graph
- `doctrines/stage-graph.md` — the plan-IS-dispatch-contract principle
- `doctrines/pattern-b-overlap.md` — encoded as `parallel_with` clique in the walker
- `doctrines/native-coordination.md` — cross-lane deps via in-script ordering (pause-for-dependency retired, #70)
- `doctrines/chain-repair.md` — seed-amendment + re-extract path
- `doctrines/adaptation-loop.md` — sprint-pattern registry; integrates with `trace.jsonl`
- `skills/context/scripts/cmd_plan.sh` — `shctx plan extract/topology/validate`
- `skills/context/scripts/cmd_graph.sh` — `shctx graph status/next/mark/trace/compile`
- `doctrines/workflow-compile-down.md` — the workflow projection of the Stage Graph shares this `shctx plan extract` surface (§II); one source, two faithful projections
