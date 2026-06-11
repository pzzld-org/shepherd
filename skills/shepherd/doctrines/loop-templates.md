---
title: loop-templates
description: |
  Loops are bounded, role-shaped, and terminate on a measurable predicate — never
  open-ended. Every loop in a Stage Graph traces to a per-role template that declares
  the iterator agent, the termination predicate, the default --max cap, and the
  named Pattern-6 composite it specializes. A loop without a template alignment is a
  loop without an audit surface: reject it at PLAN-GATE.
introduced: v6.2.0
---

# Loop Templates — per-role loop discipline

## Principle

Pattern 6 (Loop-Until-Done) is the correct structure whenever task completion is defined by
the absence of new findings rather than a fixed step count. That structural correctness does
not exempt a loop from discipline: **every loop in a Stage Graph must be bounded, role-shaped,
and terminate on a measurable predicate.**

Three invariants, binding without exception:

1. **Bounded.** Every loop declares a hard `--max` before the first iteration fires. No
   numeric ceiling is a `PLAN-MISSING-LOOP-CAP` halt at preflight (`shctx doctor`) and at
   PLAN-GATE. Default ceiling is 5; values > 5 require explicit engineer justification;
   values > 10 require critic sign-off. Per `doctrines/workflow-patterns.md §Circuit-breaker
   invariants — Pattern 6`.

2. **Role-shaped.** The iterator agent determines the loop's behavioral contract: `@coder`
   converges on a gate; `@discovery` exhausts a research question; `@worker` reconciles state
   or monitors a target; `@auditor` refines a hypothesis chain; `@engineer` (rare, root-tier
   only) converges a plan through a critic gate; the orchestrator drives the sprint FOCUS-LOOP.
   Dispatching the wrong agent type for a loop body is a `DISPATCH-WRONG-ROLE` halt per
   `doctrines/dispatch-tier-separation.md`. The per-role catalog in
   `references/loop-templates.md` is the authoritative binding.

3. **Measurable predicate.** The iterator agent's brief MUST specify that it emit
   `new_findings: true|false` as a top-level field in its report. Unstructured prose reports
   are `LOOP-REPORT-INVALID`. The predicate is evaluated independently by the conductor — the
   conductor does not infer completion from prose. Cap-exceeded (`iterations >= max`) emits
   `LOOP-CAP` halt, not silent exit. Per `doctrines/workflow-patterns.md §Circuit-breaker
   invariants — Pattern 6`.

A loop that satisfies all three invariants is a circuit-closed loop. One that violates any
invariant is a runaway candidate — the same class as an unbounded recursion.

## Per-role template catalog

The full per-role templates — intent, Stage Graph shape, termination predicate, default
`--max`, named composite, anti-patterns — live in `references/loop-templates.md`.

Quick-selection summary (full table in the catalog):

| Role | Template | Composite | Default `--max` | Terminates on |
|------|----------|-----------|-----------------|---------------|
| `@coder` | CODER-CONVERGENCE | CONVERGENCE-LOOP | 5 | Gate green |
| `@discovery` | DISCOVERY-EXHAUST | Pattern 6 generic | 4 | `new_findings: false` |
| `@worker` (state) | WORKER-CONVERGENCE | CONVERGENCE-LOOP | 5 | State predicate met |
| `@worker` (monitor) | WORKER-WATCH | WATCH-LOOP | 20 | Anomaly OR cap |
| `@auditor` | AUDITOR-REFINE | Pattern 6 generic | 3 | Confidence plateau |
| `@engineer` | ENGINEER-PLAN-REFINE | Pattern 6 generic | 3 | Critic gate green |
| orchestrator | FOCUS-LOOP | FOCUS-LOOP (named) | 8 | CLOSE-FINALIZE reached |

When a template's name appears in a Stage Graph node, its full definition from
`references/loop-templates.md` applies — do not re-derive or improvise.

## Circuit-breaker invariants (explicit enumeration)

These are not guidance; they are enforceable halt conditions:

| Invariant | Enforcement point | Halt code |
|-----------|------------------|-----------|
| `max_iterations` declared before first dispatch | `shctx doctor` preflight; PLAN-GATE (`@critic`) | `PLAN-MISSING-LOOP-CAP` |
| Structured `new_findings: true\|false` field in every report | Conductor on report receipt | `LOOP-REPORT-INVALID` |
| Cap-exceeded surfaces to operator; no auto-extend | Conductor on `i >= max` | `LOOP-CAP` |
| Each iteration makes measurable progress toward predicate | Engineer at plan time; auditor at close | `LOOP-STALL` (auditor finding, no halt code) |
| Wrong agent type for loop body | Dispatch guard | `DISPATCH-WRONG-ROLE` |
| `--interval` present only for WATCH-LOOP (WORKER-WATCH) | Critic at PLAN-GATE | `PLAN-INVALID-INTERVAL` |

The "each iteration must make measurable progress" invariant does not have a mechanical halt
code — it is an audit finding. An auditor reviewing a close report for a CODER-CONVERGENCE
loop that iterated 5 times with gate failures unchanged across all 5 rounds MUST file a HIGH
finding: the loop ran but did not converge. The engineer should have halted and escalated.

## What this doctrine does NOT authorize

- **Open-ended loops.** No template in `references/loop-templates.md` permits a loop without
  a declared `--max`. If you believe the task genuinely has no ceiling, it is not a Pattern-6
  task — decompose it differently.
- **Nested loops sharing a loop ID.** Each loop instance (including CONVERGENCE-LOOP
  instances nested within FOCUS-LOOP's Act phase) MUST have its own `shctx loop` ID.
  Reusing a parent loop's ID corrupts the registry record.
- **WATCH-LOOP without native `/loop` delegation.** Wall-clock scheduling is the native
  `/loop` command's job. A WORKER-WATCH loop that polls via `Bash sleep` is a framework
  violation per `doctrines/native-coordination.md`.
- **AUDITOR-REFINE replacing a Pattern-3 swarm.** When the audit question decomposes into
  independent concerns, use Pattern 3 (multiple parallel auditors, no shared context). The
  loop template is for inherently sequential hypothesis chains only.
- **ENGINEER-PLAN-REFINE from teammate-conductor tier.** Root-tier-exclusive per
  `doctrines/dispatch-tier-separation.md`. Teammate-conductors surface escalations; they do
  not author or loop-refine plans.

## Cross-references

- `references/loop-templates.md` — the per-role template catalog; copy-paste Stage Graph
  shapes, termination predicates, and anti-patterns
- `doctrines/workflow-patterns.md §Pattern 6` and `§Circuit-breaker invariants — Pattern 6`
  — binding selection doctrine and enforced invariants
- `references/workflow-templates.md §Named composite wave templates` — full FOCUS-LOOP,
  CONVERGENCE-LOOP, WATCH-LOOP definitions
- `commands/loop.md` — `/shepherd:loop` command; `--agent` selects the iterator; all
  per-role templates are invocable via this entry point
- `doctrines/dispatch-tier-separation.md` — tier restrictions (especially ENGINEER-PLAN-REFINE)
- `doctrines/coordinate-active-drive.md` — FOCUS-LOOP runtime (`wake → act → probe → yield`)
- `doctrines/worker-patterns.md` — `@worker` bounded-task executor contract
- `doctrines/discovery-readonly.md` — `@discovery` read-only contract
- `doctrines/auditor-hypothesis-driven.md` — per-finding evidence contract for AUDITOR-REFINE
