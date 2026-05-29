# Stage-graph — the plan IS the dispatch contract

Every sprint plan emits a **Stage Graph**: a directed acyclic graph whose nodes are dispatch events (agent batches or conductor-inline steps) and whose edges are conditional transitions labeled with runtime predicates. The conductor's job is to **walk** the graph — not to compose it.

This doctrine establishes the principle. The mechanics live in `pipeline.md`.

## The principle

> Every dispatch the conductor performs corresponds to a named node in the plan's Stage Graph. Every transition between dispatches corresponds to a labeled edge. Drift from the graph IS drift from the plan.

Three corollaries:

1. **The conductor does not invent dispatches.** If a need emerges that the graph doesn't anticipate, the conductor surfaces to the operator and either amends the plan (re-running PLAN-GATE on the new graph) or escalates. Silently dispatching a node not in the graph is a process violation.
2. **The conductor does not skip dispatches.** If the graph names a node, the conductor fires it. Skipping the close-time auditor swarm because "the wave audits already covered it" is a process violation — close-swarm is a graph node with its own concern split.
3. **The conductor does not re-order dispatches.** Edge predicates determine sequencing. Firing WAVE-2-IMPL before WAVE-1-GATE has emitted on-pass is walking the graph wrong.

## Why the graph

The pre-4.2.0 model placed the orchestration burden on the conductor's working memory — it re-read SKILL.md §III, flock.md, and the plan at every decision point to figure out "what next". The cognitive load was high, the failure mode (silent drift, skipped Pattern B, ad-hoc dispatch) was real.

The graph moves orchestration from working memory to declarative artifact. Three benefits:

- **Drift reduction.** A dispatch outside the graph is structurally visible (no node id matches) — auditors catch it, conductors notice it during the walk.
- **Cognitive-load reduction.** The conductor reads the graph once at sprint open, then mechanically walks it. No re-deriving sequencing per dispatch.
- **Auditable provenance.** Every commit traces to a graph node; every node traces to a plan section; every plan section traces to a seed lane.

## The three layers of progressive specification

| Layer | File | Author | Binding? |
|---|---|---|---|
| Hint | seed `## Stage decomposition hint` | Planter | Non-binding suggestion |
| Contract | plan `## Stage Graph` | Engineer | **Binding** — this is what the conductor walks |
| Trace | `{paths.reports}/<date>-{sprint}-walk.md` | Conductor (auto, optional) | Append-only post-hoc audit log |

The seed sketches partial structure (phase decomposition, parallel-safe groupings, conditional edges). The engineer rebuilds against Phase 0 mesh evidence and emits the binding graph. The walk trace is optional but encouraged for L/XL sprints.

## What the graph encodes

Doctrines that previously lived as conductor-side discipline are now encoded as graph constraints:

| Doctrine | Pre-4.2.0 enforcement | Post-4.2.0 encoding |
|---|---|---|
| `pattern-b-overlap` | Conductor remembers to batch wave-N-audit + wave-(N+1)-impl | Graph constraint: `parallel_with` field |
| `chain-repair` | Conductor remembers VERIFY → AMEND → CONTINUE on drift | Graph subgraph: CHAIN-REPAIR node + on-mechanical-drift edge |
| `subtract-dont-add` | Auditor flags violations at close | Graph edge: `on-grade-cap` from CLOSE-SWARM (lowers grade, continues) |
| `issue-ledger-awareness` | Engineer Phase 0 mesh + auditor completeness | Graph constraint: MESH must produce ledger-classification artifact |
| `carry-forward-refresh` | Auditor completeness runs the refresh | Graph constraint: CLOSE-SWARM completeness concern includes refresh step |
| `wrapper-must-earn` | Auditor dependency-topology runs grep | Graph constraint: WAVE-AUDIT and CLOSE-SWARM include the grep |
| `auditor-readonly` | Auditor system prompt forbids edits | Graph constraint: `WAVE-AUDIT` / `CLOSE-SWARM` nodes cannot have outgoing edges that imply file edits |
| `seed-anchored-by-issues` | Planter pre-commit verification | Graph constraint: lanes referenced in WAVE-IMPL nodes must cite GH# |

Doctrines aren't replaced by the graph — they're **lifted** into it. The graph is the integration surface where they compose.

## What the graph does NOT encode

- **Per-agent identity.** The graph names roles (engineer, critic, coder, auditor, worker), not individual agents. The flock is closed at five (`flock.md` §I); the graph respects that.
- **Brief contents.** The graph references briefs by id (`brief: lane-A`) but doesn't include them. Briefs live where they always have — derived from the plan's lane decomposition (`agents/engineer.md` §"Brief contract") and the agent-briefs templates.
- **Project doctrines.** Project-specific doctrines (`.claude/doctrines/`) load as a preamble per `flock.md`. The graph doesn't repeat them.
- **Skills loaded.** Each agent dispatch loads skills per `[skills.*]` in `shepherd.toml`. The graph doesn't enumerate them.

The graph encodes **dispatch shape and sequencing**. Everything else stays where it lives.

## When the graph is wrong

If, mid-walk, the engineer's graph proves wrong (a node's predecessor doesn't actually unblock it; a parallel_with grouping is unsafe; an edge predicate doesn't reflect reality), the conductor:

1. **Halts the walk** at the first off-graph evidence.
2. **Surfaces to the operator** with a one-block report: "Graph at <node-id> says <X>; runtime evidence says <Y>; the plan needs amendment".
3. **Re-dispatches @engineer** with a minimal brief: "amend the Stage Graph in the plan; everything else stays".
4. **Re-runs PLAN-GATE** with the amended graph.
5. **Resumes the walk** from the amended position.

This protocol mirrors `chain-repair.md` for seed drift, applied to graph drift. The intent is the same: amend artifact, don't paper over.

## Anti-patterns

- **"I'll just fire HOTFIX inline; the graph doesn't have it but the audit found something."** — Wrong; HOTFIX subgraphs are first-class node types. If the engineer's graph didn't anticipate hot-fix paths from this WAVE-AUDIT, the graph is incomplete — amend it.
- **"I'll skip the CLOSE-SWARM because the wave audits already covered the concerns."** — Wrong; close-swarm reviews the FULL sprint scope (all waves combined) and runs the completeness-concern doctrines (subtract, ledger, carry-forward). It is not redundant with wave audits.
- **"I'll re-order: WAVE-2-IMPL first, then WAVE-1-AUDIT."** — Wrong; Pattern B is a structural constraint encoded as `parallel_with` — the two MUST fire in the same Agent batch.
- **"The graph is overkill for an XS sprint."** — Wrong; even the XS sprint graph is small (SEED-VERIFY → MESH → PLAN-GATE → WAVE-1-IMPL → WAVE-1-GATE → CLOSE-SWARM → CLOSE-FINALIZE). The cognitive cost of "no graph" plus "remember the discipline" is higher than "tiny graph the conductor walks".
- **"I'll author the graph mid-walk as scope clarifies."** — Wrong; the graph IS the plan-gate's input. Mid-walk graph authorship skips the critic's adversarial review.

## See also

- `pipeline.md` — the mechanics (node taxonomy, edge labels, walk algorithm)
- `pattern-b-overlap.md` — now encoded as a graph constraint
- `chain-repair.md` — pattern for graph drift mirrors this
- `subtract-dont-add.md` — `on-grade-cap` edge from CLOSE-SWARM
- `issue-ledger-awareness.md` — drives MESH and CLOSE-SWARM completeness concern
- `auditor-readonly.md` — graph constraint: audit nodes cannot fire write-edges
- `agents/engineer.md` — plan-quality bar requires the Stage Graph section
- `SKILL.md` §III — sprint sections that the graph specializes
- `workflow-compile-down.md` — compile-down evaluation; its faithfulness invariant (§IV.1–3: soundness / completeness / determinism) maps directly onto corollaries 1–3 above, now mechanically guaranteed for compiled fanout segments
