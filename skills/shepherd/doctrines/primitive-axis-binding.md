---
title: primitive-axis-binding
status: binding
since: v6.0.2
description: |
  Canonical binding of shepherd's planning ontology (waves × steps; spawn-time
  lanes) to Claude Code's native primitives (Agent Teams, Dynamic Workflows,
  subagents). Each axis maps to exactly one primitive (or none); each unit maps to
  exactly one dispatch construct. Single source of truth for "which primitive does
  which job" — the load-bearing fix for the v6.0.1 field regression (#89) where
  each primitive was used for the other's job. Cross-links:
  claude-code-platform-alignment.md (teammate-state axis), workflow-compile-down.md
  (execution axis), native-coordination.md (coordination-function view),
  dispatch-tier-separation.md (who-dispatches-whom).
---

# Primitive ↔ axis binding — one primitive per axis, never inverted

> **Why this doctrine exists.** In a live session (2026-05-29, #89) root spawned
> the first wave of conductors via a Dynamic Workflow instead of Agent Teams, and
> the teammate-conductors then did NOT compile their step fan-out to a Dynamic
> Workflow — each primitive used for the other's job. Dynamic Workflows was a
> research-preview feature ~1 day old at the time, so the model has **no training
> prior** for it: ambiguous doctrine gets improvised on a tool it's never seen, and
> inverts. This doctrine is the only teacher; it must be unambiguous.

---

## I. The binding table (canonical)

Four axes, each bound to exactly one Claude-native primitive (planning binds to
none — pure authorship) and exactly one unit:

| Axis | Native primitive | Unit |
|---|---|---|
| **Planning** (engineer-authored, no parallelism concept) | — (none) | waves × steps |
| **Teammate-state / parallelization** (lanes) | **Agent Teams** | one teammate-conductor per lane |
| **Execution** (gate-free step fan-out) | **Dynamic Workflows** (compiled) | the compiled script orchestrating subagents |
| **Worker** | **subagents** (`subagent_type: "shepherd:<role>"`) | the steps themselves |

Canonical — every doctrine, agent profile, command, and guard obeys it. Same split
`claude-code-platform-alignment.md §VII` and `workflow-compile-down.md §I` each call
an "orthogonal backend axis"; this is the one place naming all four and their units.

---

## II. Definitions (crisp — memorize)

- **WAVE** — a sequential, gated stage of a plan (N sequential waves; gates run
  between, never inside). Structural, not a tier, not a parallel set.
- **STEP** — a unit of work within a wave (a wave is X steps); each step ≈ one
  subagent. Steps within a wave may fan out concurrently (gate-free) — that's the
  execution axis, compiled to a Dynamic Workflow.
- **LANE** — a cohesive vertical slice across waves, owned by one teammate-conductor
  at a time. Formed only in spawn mode, after the plan is authored and gated. NOT a
  planning concept — the engineer doesn't author lanes in the plan, and a lane never
  nests inside a wave (decomposition authority is the engineer's, post-plan, #67/#88).
- **SUBAGENT** — the ephemeral worker executing a step (`Agent({ subagent_type:
  "shepherd:<role>" })`); the closed flock roles ARE the subagent definitions
  (`agents/<role>.md` + `tools:` allowlist).

```
          wave-1     wave-2     wave-3     (sequential; gates between)
         ┌ step ┐   ┌ step ┐   ┌ step ┐
lane A   │ step │   │ step │   │ step │    ← one teammate-conductor (Agent Teams);
         └ step ┘   └ step ┘   └ step ┘      compiles gate-free step fan-out to a
         ┌ step ┐   ┌ step ┐                  Dynamic Workflow (each step ≈ 1 subagent)
lane B   │ step │   │ step │              ← another teammate-conductor
         └ step ┘   └ step ┘
            ▲                       ▲
     engineer authors          gate runs here
     waves × steps (no lanes)  (between waves, conductor-inline)
```

The engineer authors the grid columns (waves) and cells (steps). Lanes are the
rows, drawn over the finished grid at spawn time — the plan has no rows.

### II.1 — Lane refresh: a durable lane, a recyclable teammate

One teammate-conductor occupies a lane at a time but is not permanent. When a
lane's teammate goes idle (finished wave-N steps, waiting on the gate), root MAY
shut it down and spawn a fresh teammate-conductor into the **same lane** for
wave-N+1 — fresh context per wave, avoiding compaction cost.

> Refreshing a lane's teammate is NOT creating a new lane — the lane is durable
> (defined once, at projection time); only the teammate instance changes. **Count
> LANES, not teammate-instances**: 4 lanes × 3 waves may spawn 12 teammate
> instances but still has 4 lanes. Never write "lanes per wave."

Refresh is optional — a teammate may persist across waves if context stays small;
it's the lever root pulls when compaction cost would grow. Refresh vs. crash: a
refresh is a deliberate recycle at an idle boundary, a crash is unplanned
(`agents/shepherd.md §Crashed-teammate detection`) — both re-spawn into the same
lane with the archived brief.

---

## III. The non-inversion rules (the #89 fix — binding)

Two constructions are forbidden on sight — the exact inversions observed in the
field. A guard rejects each (#86/#89 guard, Wave 1).

### III.1 — Spawning teammate-conductors = Agent Teams, NEVER a Dynamic Workflow

Root stands up parallel lanes via **Agent Teams** — a native teammate-spawn
referencing `shepherd:conductor` as each teammate's agent type (#93/v2.1.178 — no
`TeamCreate` tool; spawning needs no setup step). `Agent`/`Task` spawn subagents,
never teammates — `team_name` is accepted but ignored; the discriminator is spawn
INTENT, not a field.

**Forbidden:** instantiating teammate-conductors from inside a Dynamic Workflow, or
a workflow whose "steps" are teammate-conductors — a workflow orchestrates
subagents, never teammates, and cannot spawn other subagents; inversion-1 can only
arise from a hand-authored or mis-compiled script. The compiler segment-purity
guard (#85) and workflow-launch guard (`bash_guard.sh` Check 0-bis) close that
residue.

> Halt: `PRIMITIVE-INVERSION — workflow-spawns-teammates`. Refuse the
> workflow-spawn.

### III.2 — A teammate's gate-free step fan-out = a compiled Dynamic Workflow, NEVER hand-rolled dispatch

Inside a lane, a teammate-conductor's gate-free step fan-out within a wave (e.g.
`WAVE-IMPL` coders ‖ worker, `WAVE-AUDIT` auditors, `CLOSE-SWARM`) compiles to a
**Dynamic Workflow** orchestrating step subagents out-of-context
(`workflow-compile-down.md §III–VI`) — same for a solo conductor under
`/shepherd:start`, which compiles its own fan-out.

**Forbidden:** hand-rolling the fan-out as ad-hoc in-context `Agent(...)` calls, or
free-authoring an orchestration script outside the critic-gated graph
(`workflow-compile-down.md §X.1`).

> Halt: `PRIMITIVE-INVERSION — handrolled-fanout`. A gate-free step fan-out =
> `shctx graph compile`.

### III.3 — Never invert

| You are about to… | Use | NOT |
|---|---|---|
| stand up parallel lanes (teammate-conductors) | Agent Teams | a Dynamic Workflow |
| fan out a wave's gate-free steps (subagents) | a Dynamic Workflow (compiled from `G`) | hand-rolled `Agent(...)` calls |
| run one step | a subagent (`shepherd:<role>`) | a teammate, a workflow |
| author the plan | waves × steps (no primitive) | lanes, parallelism, or any primitive |

---

## IV. Tier mapping (ontological — sharpens dispatch-tier-separation.md)

Dispatch tiers (`dispatch-tier-separation.md §I–II`) map one-to-one onto ontology
units:

| Ontology unit | Dispatch tier | Primitive |
|---|---|---|
| step | Tier 1 (flock) | subagent |
| lane | Tier 2 (teammate-conductor, spawn mode) | Agent Teams teammate |
| wave | — (sequential gated stage, not a tier) | conductor-inline gate at the seam |

Enforced by `dispatch-tier-separation.md §IV-bis`:

- A step dispatches as a subagent via `Agent`/`Task` (`subagent_type:
  "shepherd:<role>"`); stood up as a teammate → `DISPATCH-TEAMMATE-TYPE-MISMATCH`.
- A lane is owned by a teammate-conductor via the native teammate-spawn
  (`subagent_type: "shepherd:conductor"`; #93/v2.1.178 — no `TeamCreate`,
  discriminator is intent). Stood up as a subagent (no team) is the solo/in-context
  degenerate case; as a workflow step is the §III.1 inversion.
- A wave gate is conductor-inline (git/shell/operator) — a seam node, never
  compiled into a workflow (`workflow-compile-down.md §VI`).

---

## V. Lifecycle — where each primitive enters

Four phases:

1. **PLAN (engineer, once per sprint — no primitive).** Engineer authors waves ×
   steps; no lanes, no Agent Teams, no workflow. Gated by `@critic`. Phase-0 ground
   truth is the INTRO-COMBO-WAVE; classic/solo is root-run (engineer consumes
   `[DISCOVERY-CONTEXT]`/`[INTRO-AUDIT-CONTEXT]`); self-contained (teammate) runs
   its own read-only sub-flock and gates with its own `@critic`, keeping context
   out of root's window (`engineer-self-contained-plan.md`, `intro-combo-wave.md`,
   `agents/engineer.md §Step 2`).
2. **PROJECT TO LANES (engineer authority, post-plan, spawn mode only).** After
   gating, under `/shepherd:spawn`, the plan is sliced vertically across waves into
   file-disjoint lanes, each owned by one teammate-conductor. Carry-over/open-issues
   is a dedicated lane, not steps folded into the plan (#88). Solo `/shepherd:start`
   skips this phase.
3. **SPAWN (root, spawn mode).** Root spawns one teammate-conductor per lane via
   Agent Teams (§III.1); count equals lane count, not a per-wave count.
4. **EXECUTE (conductor, any mode).** Within each wave, gate-free step fan-out
   compiles to a Dynamic Workflow over subagents (§III.2); between waves the
   conductor runs the gate inline (seam). In spawn mode all lanes proceed in
   lockstep at gate barriers, and root MAY refresh an idle lane's teammate at the
   wave-N+1 boundary (§II.1) — the lane persists, the teammate instance may not.

Planning discipline (fine-grained steps, 2-5 min each) lives on waves × steps
(`agents/engineer.md`); parallelization discipline (a small lane count of fat
vertical slices — fewer fat lanes beat many thin sessions) lives on the spawn-time
lane axis, never "per wave." Minting a session per step crosses axes —
`PRIMITIVE-INVERSION`.

---

## VI. Why the binding is load-bearing (no training prior)

The two primitives look substitutable — both "run agents in parallel" — but Agent
Teams owns durable teammate **state** (a lane) while Dynamic Workflows owns
out-of-context **execution** of a step fan-out; using one for the other's job
breaks the property it was reached for. v6.0.1 stated this split in prose alone
and the field still inverted (#89), so it also ships with a mechanical guard
(`PRIMITIVE-INVERSION`, Wave 1, #86/#89).

---

## VII. Anti-patterns

| Anti-pattern | Halt / fix |
|---|---|
| Workflow-spawns-teammates (#89 inversion #1) | Lanes = Agent Teams (§III.1) |
| Hand-rolled step fan-out (#89 inversion #2) | `compile(G_seg)`, not ad-hoc `Agent(...)` |
| Lanes in the plan (`lane:`/`wave: <N>` fields, "lanes per wave") | Plan is waves × steps; lanes are a post-plan projection (§V phase 2) |
| "Per lane per wave" (counting teammate-conductors per wave) | A lane is vertical across waves; count lanes, full stop |
| Step-as-teammate / lane-as-workflow-step | `DISPATCH-TEAMMATE-TYPE-MISMATCH`/`PRIMITIVE-INVERSION` (§IV) |
| Free-authored orchestration script under `/shepherd:*` | Must be `compile(G)`, `G` critic-gated (`workflow-compile-down.md §X.1`) |

---

## VIII. What this doctrine does NOT do

Does not open the closed flock or change the dispatch contract (binds existing
primitives to existing ontology); does not implement the guards
(`PRIMITIVE-INVERSION` enforcement is Wave 1, #86/#89 — this is the truth they
enforce); does not implement the compile path (`shctx graph compile` is
`workflow-compile-down.md §III–VI` + #77, Wave 2); does not delegate canonical
state to any primitive (SQLite + git stay conductor-owned at the seam —
`sqlite-canonical-state.md`, `workflow-compile-down.md §VI`).

---

## IX. See also

- `doctrines/claude-code-platform-alignment.md §VII` — the **teammate-state axis** (Agent Teams); §II primitive map.
- `doctrines/workflow-compile-down.md` — the **execution axis** (Dynamic Workflows); §IV faithfulness bar; §VI seam.
- `doctrines/native-coordination.md` — the **coordination-function** view of the same three primitives (retired mechanic → native replacement).
- `doctrines/dispatch-tier-separation.md` — the who-dispatches-whom matrix; §IV-bis forbidden-dispatch halt codes; §I-bis tier↔unit mapping.
- `doctrines/stage-graph.md` — the plan IS the dispatch contract; the source `G` that compiles to a workflow.
- `skills/shepherd/pipeline.md` — node taxonomy; the waves × steps the graph encodes.
- `agents/engineer.md` — authors waves × steps (no lanes); projects lanes post-plan under spawn.
- `doctrines/intro-combo-wave.md` — the root-run discovery wave the engineer consumes (Phase-0 split).
