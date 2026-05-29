---
title: primitive-axis-binding
status: binding
since: v6.0.2
description: |
  The canonical binding of shepherd's planning ontology (waves × steps; spawn-time
  lanes) to Claude Code's native primitives (Agent Teams, Dynamic Workflows,
  subagents). Each axis maps to exactly one primitive (or none); each unit maps to
  exactly one dispatch construct. This doctrine is the single source of truth for
  "which primitive does which job" and the load-bearing fix for the v6.0.1 field
  regression (#89) in which Dynamic Workflows spawned the conductor wave and
  teammates failed to compile their step fan-out — each primitive used for the
  OTHER one's job. Cross-links: claude-code-platform-alignment.md (teammate-state
  axis), workflow-compile-down.md (execution axis), native-coordination.md
  (coordination-function view), dispatch-tier-separation.md (who-dispatches-whom).
---

# Primitive ↔ axis binding — one primitive per axis, never inverted

> **Why this doctrine exists.** In a live axiom session (2026-05-29, #89) the root
> shepherd spawned the first wave of conductors **via a Dynamic Workflow** instead
> of **Agent Teams**, and the resulting teammate-conductors then **did NOT** compile
> their gate-free step fan-out to a Dynamic Workflow. Each native primitive was used
> for the *other* primitive's job. **Dynamic Workflows is a research-preview feature
> roughly one day old** (announced 2026-05-28; requires Claude Code ≥ v2.1.154). The
> model has **no training prior** for it — its entire understanding of *what it is
> and when to reach for it* comes from shepherd's own doctrines. When those doctrines
> are ambiguous about primitive↔axis, the model improvises on a tool it has never
> seen and inverts. **This doctrine is the only teacher; it must be unambiguous.**

---

## I. The binding table (canonical)

There are **four axes** in a shepherd sprint. Each binds to exactly one Claude-native
primitive (planning binds to none — it is pure authorship), and each has exactly one
**unit**:

| Axis | Native primitive | Unit |
|---|---|---|
| **Planning** (engineer-authored, **no parallelism concept**) | — (none) | **waves × steps** |
| **Teammate-state / parallelization** (lanes) | **Agent Teams** | one teammate-conductor per **lane** |
| **Execution** (gate-free **step** fan-out) | **Dynamic Workflows** (compiled) | the compiled script orchestrating **subagents** |
| **Worker** | **subagents** (`subagent_type: "shepherd:<role>"`) | the **steps** themselves |

This table is canonical. Every doctrine, agent profile, command, and guard obeys it.
It is the same axis split that `claude-code-platform-alignment.md §VII` (teammate-state)
and `workflow-compile-down.md §I` (execution) describe as "orthogonal backend axes";
this doctrine is the single place that names **all four** and binds each to its **unit**.

---

## II. Definitions (crisp — memorize these)

- **WAVE** — a sequential, gated **stage** of a plan. A plan is **N sequential waves**.
  Gates run **between** waves (never inside one). A wave is a *structural* unit of the
  plan, not a tier and not a set of anything parallel.
- **STEP** — a unit of work **within** a wave. A wave is **X steps**. Each step ≈ **one
  subagent**'s unit of work. Steps within a wave may fan out concurrently (gate-free);
  that concurrency is the *execution* axis, compiled to a Dynamic Workflow.
- **LANE** — a cohesive **vertical slice across waves**, owned by **one
  teammate-conductor** at a time. A lane is formed **only in spawn mode**, **after** the
  plan is authored and gated. A lane is **NOT** a planning concept; the engineer does not
  author lanes in the plan body, and **a lane NEVER nests inside a wave**. (Lane
  decomposition authority is the engineer's, post-plan — #67 / #88.)
- **SUBAGENT** — the ephemeral worker that executes a step
  (`Agent({ subagent_type: "shepherd:<role>" })`). The closed flock roles ARE the
  subagent definitions (`agents/<role>.md` + `tools:` allowlist).

> A plan is **N sequential WAVES; each wave is X STEPS; each step ≈ one SUBAGENT.**
> A **LANE** is a vertical slice across those waves, formed at spawn time, owned by
> one teammate-conductor. Waves are horizontal-and-sequential; lanes are
> vertical-and-parallel; they are **orthogonal**, and lanes are projected from the
> finished plan — never written into it.

```
            wave-1        wave-2        wave-3        (sequential; gates between)
          ┌─ step ─┐    ┌─ step ─┐    ┌─ step ─┐
lane A    │  step  │    │  step  │    │  step  │      ← one teammate-conductor (Agent Teams)
          └─ step ─┘    └─ step ─┘    └─ step ─┘         compiles each wave's gate-free
          ┌─ step ─┐    ┌─ step ─┐                       step fan-out to a Dynamic Workflow
lane B    │  step  │    │  step  │                  ← another teammate-conductor
          └─ step ─┘    └─ step ─┘                     (each step ≈ one subagent)
             ▲                          ▲
        engineer authors           gate runs here
        waves × steps              (between waves, conductor-inline)
        (NO lanes here)
```

The engineer authors the grid columns (waves) and cells (steps). The **lanes are the
rows**, drawn over the finished grid at spawn time. The plan has no rows.

### II.1 — Lane refresh: a durable lane, a recyclable teammate

One teammate-conductor occupies a lane **at a time** — but that teammate is **not
permanent**. When a lane's teammate goes **idle** (it finished its wave-N steps and is
waiting on the wave gate), root MAY shut the panel/teammate down and **spawn a fresh
teammate-conductor to take over the same lane for wave-N+1**. The motivation is **fresh
context per wave**: a recycled teammate starts clean, avoiding the token + latency cost
of compaction on a long-lived session.

> **Refreshing a lane's teammate is NOT creating a new lane.** The lane is durable
> (defined once, at projection time); only the *teammate instance* occupying it changed.

Consequences:
- **You count LANES, not teammate-instances.** The lane count is **constant across
  waves**. A sprint with 4 lanes and 3 waves may spawn up to 12 teammate *instances*
  (4 lanes × 3 refreshes) but still has exactly **4 lanes**.
- **This is the origin of the retired "per lane per wave" phrasing.** That wording
  conflated the per-(lane × wave) *teammate instance* with a per-wave *lane*. The lane is
  vertical and constant; the teammate is the thing that may recur per wave. Never write
  "lanes per wave" — write "lanes" (the count) and, if needed, "a refreshed teammate per
  wave within a lane."
- Refresh is **optional**: a teammate MAY persist across waves if its context stays
  small. Refresh is the lever root pulls when compaction cost would otherwise grow.
- Refresh vs. crash: a *refresh* is a deliberate recycle at an idle boundary; a *crash*
  is unplanned (`agents/shepherd.md §Crashed-teammate detection`). Both re-spawn into the
  same lane with the archived lane brief.

---

## III. The non-inversion rules (the #89 fix — binding)

Two constructions are **forbidden on sight**. They are the exact inversions observed in
the field. A guard rejects each (mechanism layer, #86 / #89 guard — Wave 1).

### III.1 — Spawning teammate-conductors = Agent Teams, NEVER a Dynamic Workflow

To stand up the parallel lanes, root spawns **one teammate-conductor per lane** via
**Agent Teams** (`Agent({ team_name: ..., subagent_type: "shepherd:conductor" })`).

**Forbidden:** instantiating teammate-conductors from inside a Dynamic Workflow, or
emitting a workflow whose "steps" are teammate-conductors. A workflow orchestrates
**subagents** (the worker primitive), not teammates. Teammate-state is the Agent Teams
axis; it is **never** an execution-workflow output.

> **Platform-confirmed (`code.claude.com/docs/en/workflows`, verified 2026-05-29):** a
> Dynamic Workflow "is a JavaScript script that orchestrates **subagents** at scale" — it
> has **no** teammate-spawn capability, and "subagents cannot spawn other subagents." So
> at the platform level inversion-1 cannot occur through a *faithfully compiled* workflow;
> it can only arise from a **hand-authored or mis-compiled** script. The compiler
> segment-purity guard (#85) plus the workflow-launch guard (`bash_guard.sh` Check 0-bis)
> close that residue. Conversely, Agent Teams is the only primitive that creates a
> teammate (a lane) — so spawning lanes is Agent Teams, by construction.

> Halt: `PRIMITIVE-INVERSION — workflow-spawns-teammates`. Spawning a lane =
> Agent Teams. Refuse the workflow-spawn.

### III.2 — A teammate's gate-free step fan-out = a compiled Dynamic Workflow, NEVER hand-rolled dispatch

Inside a lane, a teammate-conductor's gate-free **step** fan-out within a wave (e.g.
`WAVE-IMPL` coders ‖ worker, `WAVE-AUDIT` auditors, `CLOSE-SWARM`) compiles to a
**Dynamic Workflow** that orchestrates the step subagents out-of-context
(`workflow-compile-down.md §III–VI`). The same holds for a **solo** conductor under
`/shepherd:start`: it compiles its own fan-out (no team needed).

**Forbidden:** hand-rolling the step fan-out as ad-hoc, in-context `Agent(...)` calls
where a compiled workflow is required, OR letting Claude free-author an orchestration
script outside the critic-gated graph (`workflow-compile-down.md §X.1`). Execution is the
Dynamic Workflows axis; it is **never** a pile of improvised dispatches.

> Halt: `PRIMITIVE-INVERSION — handrolled-fanout`. A gate-free step fan-out =
> `shctx graph compile`. Refuse the hand-rolled dispatch.

### III.3 — Never invert

| You are about to… | Use | NOT |
|---|---|---|
| stand up parallel lanes (teammate-conductors) | **Agent Teams** | a Dynamic Workflow |
| fan out a wave's gate-free steps (subagents) | a **Dynamic Workflow** (compiled from `G`) | hand-rolled `Agent(...)` calls |
| run one step | a **subagent** (`shepherd:<role>`) | a teammate, a workflow |
| author the plan | **waves × steps** (no primitive) | lanes, parallelism, or any primitive |

---

## IV. Tier mapping (ontological — sharpens dispatch-tier-separation.md)

The dispatch tiers (`dispatch-tier-separation.md §I–II`) map **one-to-one** onto the
ontology units:

| Ontology unit | Dispatch tier | Primitive |
|---|---|---|
| **step** | Tier 1 (flock) | subagent |
| **lane** | Tier 2 (teammate-conductor, spawn mode) | Agent Teams teammate |
| **wave** | — (a sequential gated stage; not a tier) | conductor-inline gate at the seam |

Consequences, enforced by `dispatch-tier-separation.md §IV-bis`:

- A **step** is dispatched as a subagent — `subagent_type: "shepherd:<role>"`,
  `team_name` UNSET. A step dispatched **as a teammate** is
  `DISPATCH-TEAMMATE-TYPE-MISMATCH`.
- A **lane** is owned by a teammate-conductor — `team_name` SET,
  `subagent_type: "shepherd:conductor"`. A lane stood up **as a subagent** (no team) is
  the solo/in-context degenerate case; standing one up **as a workflow step** is the
  §III.1 inversion.
- A **wave gate** is conductor-inline (git/shell/operator) — a **seam** node, never
  compiled into a workflow (`workflow-compile-down.md §VI`).

---

## V. Lifecycle — where each primitive enters

A sprint moves through four phases; the binding tells you which primitive (if any) is
live in each:

1. **PLAN (engineer, once per sprint — no primitive).** The engineer authors the plan as
   **waves × steps**. No lanes. No parallelism construct. No Agent Teams, no workflow.
   The plan is gated by `@critic`. (Phase-0 ground truth is supplied by the root-run
   discovery wave / INTRO-COMBO-WAVE, which the engineer **consumes** — it does not
   re-run the mesh; see `intro-combo-wave.md` and `agents/engineer.md §Step 2`.)

2. **PROJECT TO LANES (engineer authority, post-plan, spawn mode ONLY).** After the plan
   is gated, and only under `/shepherd:spawn`, the finished waves×steps plan is sliced
   **vertically across waves** into **lanes** — each a cohesive, file-disjoint slice
   owned by one teammate-conductor. Carry-over / open-issue handling is a candidate
   **dedicated lane** (its own teammate-conductor), not steps folded into the plan body
   (#88). Solo `/shepherd:start` **skips this phase** — there are no lanes; the conductor
   walks the plan in-session.

3. **SPAWN (root, spawn mode).** Root spawns **one teammate-conductor per lane** via
   **Agent Teams** (§III.1). The number of teammate-conductors equals the lane count
   (NOT a per-wave count — lanes are vertical).

4. **EXECUTE (conductor, any mode).** Within each wave, the gate-free **step** fan-out
   compiles to a **Dynamic Workflow** over **subagents** (§III.2). Between waves, the
   conductor runs the wave gate inline (seam). In spawn mode, all lanes proceed through
   the waves in lockstep at the gate barriers: each lane's teammate completes its wave-N
   steps and goes idle, root runs the wave-N gate across the aggregated output, then the
   lanes advance to wave-N+1 — at which point root MAY **refresh** an idle lane's teammate
   (shut it down, spawn a fresh one into the **same** lane for the next wave; §II.1). The
   lane persists; the teammate instance may not.

The minimum-decomposition disciplines split along the same seam:
- **Planning discipline** (T-shirt → substantive LOC floor + many fine-grained steps,
  2–5 min each) lives on the *waves × steps* axis. See `agents/engineer.md`.
- **Parallelization discipline** (T-shirt → minimum **lane** count; "more lanes is
  better") lives on the *spawn-time lane* axis, and is **never** expressed "per wave."

---

## VI. Why the binding is load-bearing (no training prior)

`workflow-compile-down.md` and `claude-code-platform-alignment.md` each describe one axis;
before this doctrine, no single file *bound* the four axes to their units, so the model —
which has **never seen Dynamic Workflows in training** — guessed, and guessed wrong (#89).
Three properties make the binding non-negotiable:

1. **Dynamic Workflows has no training prior.** The model cannot fall back on "what this
   feature usually does." Shepherd's doctrine is the *entire* prior. Ambiguity here is not
   a style issue — it is a correctness hole.
2. **The two primitives look superficially substitutable.** Both "run agents in
   parallel." The difference is *what they own*: Agent Teams owns durable teammate **state**
   (a lane); Dynamic Workflows owns out-of-context **execution** of a step fan-out. Using
   one for the other's job (either direction) breaks the property it was reached for —
   teammate liveness/escalation, or context-offloaded fan-out.
3. **Prose deterrence already failed.** v6.0.1 stated "Agent Teams owns teammate-state;
   Dynamic Workflows owns execution" and the field still inverted. The binding therefore
   ships with a **mechanical guard** (Wave 1, #86/#89) — `PRIMITIVE-INVERSION` halts on
   both §III constructions — not prose alone.

---

## VII. Anti-patterns

1. **Workflow-spawns-teammates.** Emitting a Dynamic Workflow whose steps instantiate
   teammate-conductors. Lanes = Agent Teams (§III.1). *(The #89 inversion #1.)*
2. **Hand-rolled step fan-out.** A teammate (or solo conductor) firing a wave's gate-free
   steps as ad-hoc in-context `Agent(...)` calls instead of `compile(G_seg)`. *(The #89
   inversion #2.)*
3. **Lanes in the plan.** The engineer authoring `lane:` / `wave: <N>` fields, "min lanes
   per wave," or "a wave is a set of lanes." The plan is waves × steps; lanes are a
   post-plan spawn-time projection (§V, phase 2 — PROJECT TO LANES).
4. **"Per lane per wave."** Counting teammate-conductors per wave. A lane is vertical
   across waves; you count lanes, full stop.
5. **Step dispatched as a teammate / lane dispatched as a workflow step.** Tier/primitive
   mismatch (§IV) — `DISPATCH-TEAMMATE-TYPE-MISMATCH` / `PRIMITIVE-INVERSION`.
6. **Free-authored orchestration script under `/shepherd:*`.** The script must be
   `compile(G)` where `G` is critic-gated (`workflow-compile-down.md §X.1`).

---

## VIII. What this doctrine does NOT do

- It does **not** open the closed flock or change the dispatch contract — it binds the
  *existing* primitives to the *existing* ontology.
- It does **not** implement the guards. The mechanical `PRIMITIVE-INVERSION` enforcement
  is Wave 1 (#86 / #89); this doctrine is the truth those guards enforce.
- It does **not** implement the compile path. `shctx graph compile` is `workflow-compile-down.md §III–VI`
  + #77 (Wave 2). This doctrine fixes *what compiles to what*, not *how*.
- It does **not** delegate canonical state to any primitive. SQLite + git stay
  conductor-owned at the seam (`sqlite-canonical-state.md`, `workflow-compile-down.md §VI`).

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
