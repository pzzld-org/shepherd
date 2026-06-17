---
title: dispatch-generosity
status: binding
introduced: v6.1.7
description: |
  Reach for the lane, the swarm, and the loop. Only ONE flock role is
  count-capped (the @engineer, once per sprint); every other role is freely and
  repeatably dispatchable. The observed degradation — sessions lean on
  coder/engineer/critic and rarely dispatch additional auditors, workers, or
  discovery past the initial wave — is an INCENTIVE gap, not a cap. This doctrine
  supplies the missing pull, and removes its root cause: the false belief that
  every subagent result must be held in the conductor's context. With the native
  Workflow tool (enabled across entrypoints; #146 corrected) gate-free fan-out
  compiles out-of-context, so extra dispatch is context-CHEAP. Pull, not policing
  — no new halt code; this is default-posture coaching.
---

# Dispatch generosity — reach for the lane, the swarm, and the loop

> **The principle in one line:** the framework gives you six specialized lanes and
> a first-class loop primitive — *use them*. Inlining work the flock should own, or
> one-shotting a capability that is meant to be repeated, is the quiet way a
> powerful flock decays into "coder + engineer + critic, and nothing else."

## I. The cap reality — only the engineer is capped

| Role | Dispatch cardinality | Capped? |
|---|---|---|
| `@engineer` | **once per sprint** (one job: seed → plan) | ✅ the ONLY count-cap |
| `@critic` | once per gate (PLAN-GATE, revisions, re-seeds) — repeatable | ✖ |
| `@coder` | per step, many per wave, many waves per sprint | ✖ |
| `@auditor` | intro lanes + close swarm (3–5) **+ mid-body waves** — repeatable | ✖ |
| `@worker` | per bounded task, parallel, any number — repeatable | ✖ |
| `@discovery` | six dispatch patterns, repeatable across the WHOLE sprint | ✖ |

The close-swarm "3–5 auditors" and the intro wave's discovery lanes are **floors,
not ceilings.** Nothing in the framework limits you to one discovery wave or one
audit pass. If you are reaching for `@engineer` a second time in a sprint, that is
the one place to stop and ask why (`flock.md`, `agents/engineer.md`); everywhere
else, reaching again is normal and expected.

## II. Why the degradation happens — and why it's now wrong

A Sonnet conductor minimizes context. Every subagent return it collects in-context
is a cost, so the instinct is to *inline* a bounded task instead of dispatching
`@worker`, or to *stop after* the intro discovery wave rather than re-dispatch
`@discovery` mid-body. That instinct made sense when fan-out was walked in working
memory. **It is now backwards.**

With the native `Workflow` tool — **enabled across Claude Code entrypoints, web /
remote / cloud-container included** (`references/glossary.md §1`, #146 corrected) —
gate-free agent fan-out **compiles out-of-context** (`doctrines/workflow-compile-
down.md`): intermediate results live in script variables, not your conversation, and
up to 16 agents run in the background while you stay responsive. So dispatching five
concern-split auditors or three workers or a second discovery wave costs your context
window **almost nothing**. Inlining to "save context" spends MORE context for LESS
parallelism — a self-inflicted handicap (`doctrines/workflow-tool-self-check.md §IV`).
Generosity and frugality now point the same way: **dispatch the lane.**

## III. Reach-for-the-lane defaults (per role)

- **`@worker` — worker-first for bounded ops.** When a task is IO-bound (> ~5 min),
  MCP-heavy (> ~10 calls), a structured non-code deliverable, or otherwise non-
  contending, dispatch `@worker` at Wave-1 START — do NOT inline it into your own
  turn. Inlining a worker-shaped task is the single most common under-utilization.
  Canonical heuristics: `doctrines/worker-patterns.md`.
- **`@auditor` — audit mid-body, not only at close.** The close swarm is the floor.
  Dispatch concern-split auditors *during* the body — concurrent with the next impl
  wave (Pattern-B overlap, `doctrines/pattern-b-overlap.md`) and inside any
  `DISCOVERY-COMBO-WAVE` (`doctrines/discovery-combo-wave.md`) — especially when a
  wave touched a money-path, schema, or cross-cutting surface. Read-only reviewers
  never contend; there is no reason to defer the signal to close.
- **`@discovery` — repeatable, all sprint long.** Discovery is not a one-shot intro
  wave. Its six patterns (PRE-MESH, PRE-HOTFIX, ARCHITECTURE, DOCTRINE-RECONCILIATION,
  MCP-STATE, RESEARCH-SUMMARY; `agents/discovery.md`) are tools to reach for whenever
  you are about to act on an under-explored surface. A fresh `@discovery` lane before
  a risky wave is cheaper than a wrong wave.

## IV. Reach-for-the-loop (Pattern 6)

The same under-reach applies to loops. When a task's completion is defined by
**"no new findings / converged / state reconciled"** rather than a fixed checklist,
that is **Loop-Until-Done** (`doctrines/workflow-patterns.md §Q4`) — dispatch a
**bounded loop**, not a single best-effort pass:

- `/shepherd:loop` for an explicit role loop, or a `CONVERGENCE-LOOP` / `WATCH-LOOP`
  node authored into the plan (`references/loop-templates.md`).
- Always bounded (`--max` declared up front), role-shaped, terminating on a
  measurable `new_findings` predicate. A loop is not "run forever" — it is "iterate
  until the predicate clears, then stop" (`doctrines/loop-templates.md`).
- Common misses: a discovery that should be `DISCOVERY-EXHAUST`; a worker monitor
  that should be `WORKER-WATCH`; a post-close acceptance check that should be a
  `SOAK-LOOP` (`doctrines/outcome-enforcement.md §Seam 4`); a stuck coder that should
  be `CODER-CONVERGENCE` rather than three hand-managed re-dispatches.

## V. Generosity is bounded, not profligate

Reaching for the lane/swarm/loop does **not** mean unbounded fan-out:

- The `@engineer` cap stands (once per sprint).
- Concurrency stays bounded (≤16 per compiled batch; `parallel_max` / `max_parallel_lanes`).
- Lanes stay scope-partitioned (no two agents on the same read/write target).
- Read-only reviewers stay read-only; tier discipline stands.
- Loops stay bounded by `--max` with a measurable predicate.

This is **pull, not policing.** Per the maintainer's direction there is no new halt
code and no auditor under-utilization check — the lever is the default posture above,
plus the compile-down economics that make it the cheap choice. If you find yourself
inlining a worker task, closing without a mid-body audit on a schema-touching wave, or
running a single pass where convergence was the real bar — that is the smell this
doctrine exists to catch.

## VI. Cross-references

- `skills/shepherd/flock.md` — the six roles + the only-engineer-capped table.
- `doctrines/worker-patterns.md` — worker-first dispatch heuristics + timing.
- `doctrines/pattern-b-overlap.md` — mid-body auditor overlap with the next wave.
- `doctrines/discovery-combo-wave.md` / `doctrines/intro-combo-wave.md` — repeatable mixed waves.
- `doctrines/workflow-patterns.md §Q4` + `references/loop-templates.md` + `doctrines/loop-templates.md` — Loop-Until-Done.
- `doctrines/workflow-compile-down.md` + `doctrines/workflow-tool-self-check.md` — why out-of-context fan-out makes dispatch context-cheap.
