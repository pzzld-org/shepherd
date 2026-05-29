---
title: native-coordination
status: binding
since: v6.0.1
description: |
  Replacement mapping: Claude Code's native primitives — Dynamic Workflow
  in-script ordering (execution), Agent Teams SendMessage (teammate state), and
  subagents (the worker primitive) — carry the coordination functions that
  shepherd's hand-rolled mechanics performed: pause-for-dependency (#70),
  heartbeat auto-relay (#53), and idle-teammate pruning (#58). Lands the proven
  replacements BEFORE Lane F deletes the mechanics (epic #76 / #78). The parity
  demonstration is skills/context/tests/test_graph_compile.sh.
---

# Native coordination — the platform owns coordination now

## Why

Through v5.x, shepherd hand-rolled three coordination mechanics because the
platform offered no primitive for them:

- **pause-for-dependency** (#70) — a subagent that hit out-of-scope work halted
  and returned a `PAUSE-FOR-DEPENDENCY` payload for the conductor to dispatch a
  satellite.
- **heartbeat auto-relay** (#53) — sibling teammates relayed a shared-file edit
  payload through multiple `SendMessage` round-trips with root as broker.
- **idle-teammate pruning** (#58) — root pruned idle teammates to cut compaction
  cost.

Under the v6.0.1 substrate (epic #76) each maps onto a **native** primitive.
This doctrine fixes the mapping and the parity demonstration so Lane F (#70 /
#53 / #58) can delete the mechanics with a proven replacement already in place
(#78). The closed flock and the dispatch contract are untouched — this changes
the *coordination substrate*, not the roles.

## The three coordination axes (all native)

| Axis | Native primitive | shepherd surface |
|---|---|---|
| **Execution / fanout ordering** | Dynamic Workflow in-script `await` + bounded `Promise.all` | `shctx graph compile` (`dispatch-cascade.md §IV-bis`, `workflow-compile-down.md`) |
| **Teammate state / cross-lane messaging** | Agent Teams `SendMessage` + shared task list | `agents/conductor.md §Teammate-to-teammate communication`, `commands/spawn.md`, `claude-code-platform-alignment.md` |
| **Worker primitive** | subagents (`subagent_type: "shepherd:<role>"`) | the closed flock — `agents/<role>.md` + `tools:` allowlists |

The execution axis and the teammate-state axis are **orthogonal and compose**
(`workflow-compile-down.md §I`): a teammate-conductor (Agent Teams) compiles its
own lane's fanout to a workflow (execution). Neither subsumes the other.

> **Canonical binding.** This table is the *coordination-function* view of the three
> primitives. The single source of truth that binds each **axis** to its primitive **and
> its ontology unit** (planning → `waves × steps`; teammate-state/lanes → Agent Teams;
> execution/step-fanout → Dynamic Workflows; worker → subagents) is
> `doctrines/primitive-axis-binding.md` (v6.0.2, #89). Spawning a lane = Agent Teams; a
> gate-free step fan-out = a compiled Dynamic Workflow; **never invert**.

## Replacement matrix (retired mechanic → native replacement)

| Retired mechanic | What it did | Native replacement | Demonstrated by |
|---|---|---|---|
| **pause-for-dependency** (#70) | coder halts on out-of-scope work; conductor dispatches a satellite via a resume-condition dance | (a) **in-script `await` ordering** when the dependency is a graph edge — the compiled segment runs batch A, awaits it, then batch B (no halt, no satellite stub); (b) **Agent Teams `SendMessage`** for genuine cross-teammate hand-off; (c) genuinely out-of-sprint work → **finding / GH issue at close** (not a mid-lane pause) | `test_graph_compile.sh` (sequential-edge batches await in order); `dispatch-cascade.md §IV-bis` |
| **heartbeat auto-relay** (#53) | sibling teammates relay a shared-file edit payload through N round-trip `SendMessage`s with root as broker | **script-level ordering within a segment** — the shared-file write becomes a single ordered step: either the segment sequences the dependent edits (`await`), or the conductor owns the shared-file write at the **seam** (`workflow-compile-down.md §VI`). No relay round-trips, no broker | in-script `await` ordering (same demonstration); the conductor owns seam writes |
| **idle-teammate pruning** (#58) | root prunes idle teammates to cut forced compactions | **moot under out-of-context execution** — a compiled workflow holds **no** idle teammates (spawned agents return their result and are gone). For team mode, the existing Agent Teams cleanup at lane close applies (`claude-code-platform-alignment.md §III Rule 5`) | out-of-context execution (Lane D); no held panes/threads |

## The subagent primitive (confirmed)

The compiled workflows (Lane D) orchestrate **subagents**: every spawn is
`agent({ subagent_type: "shepherd:<role>", ... })`. The closed-flock roles ARE
subagent definitions — `agents/<role>.md` with a `tools:` allowlist (read-only
reviewers are capability-enforced per #74 / `auditor-readonly.md`). The
mandatory-`subagent_type` dispatch contract — refusal on omit / `general-purpose`
/ `Explore` (`dispatch-tier-separation.md §IV-bis.1`) — is **intact and
load-bearing** under compile-down: the compiler emits only `shepherd:<role>`
subagent types, and the allowlist is what makes a compiled read-only step
read-only even though the runtime auto-approves edits (`workflow-compile-down.md
§VII`). Compile-down changes the coordination substrate, **not** the roles or the
contract (#78 invariant; #76 invariants).

## Parity demonstration

`skills/context/tests/test_graph_compile.sh` compiles a multi-lane segment with a
cross-lane dependency (`WAVE-1-IMPL ‖ WORKER-IO → WAVE-1-AUDIT`) and asserts:

1. the dependency is realized by **in-script `await` ordering** (batch 0 — the
   `parallel_with` clique of impl + worker — then batch 1, the audit) — not by a
   `PAUSE` node and not by a heartbeat relay;
2. **no** `PAUSE` / `PAUSE-FOR-DEPENDENCY` / `heartbeat` construct appears in the
   compiled path;
3. the §IV faithfulness diff passes (the emitted ordering is faithful to the
   graph edge — soundness / completeness / determinism).

That is the green, demonstrated replacement Lane F (#70 / #53 / #58) requires
before deleting the hand-rolled mechanics.

## What this doctrine does NOT do

- It does not delete the legacy mechanics — that is Lane F (#70 / #53 / #58).
- It does not build the full #70 team-comms event bus (`team-comms-substrate.md`,
  a v6.1.0 candidate). v6.0.1 leans on the native primitives directly; the
  heavier event bus is deferred.
- It does not open the closed flock or change the dispatch contract.

## See also

- `primitive-axis-binding.md` — **canonical** axis ↔ primitive ↔ unit binding (v6.0.2, #89)
- `workflow-compile-down.md` — the execution axis (in-script ordering, §III–VI)
- `claude-code-platform-alignment.md` — the teammate-state axis (Agent Teams)
- `dispatch-tier-separation.md` — the mandatory `subagent_type` contract
- `#70` / `CHANGELOG.md` (v6.0.1) — the retired pause-for-dependency mechanic (doctrine deleted in this release)
- `agents/conductor.md §Teammate-to-teammate communication` — `SendMessage` path
