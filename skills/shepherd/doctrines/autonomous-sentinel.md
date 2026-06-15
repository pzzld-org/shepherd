---
title: autonomous-sentinel
description: |
  The default soak is detection-only: a SOAK-LOOP probe surfaces an
  OUTCOME-REGRESSION and the operator decides whether to fix it. AUTONOMOUS-SENTINEL
  is the supervised-remediation SUPERSET of SOAK-LOOP — an operator who has
  EXPLICITLY empowered the conductor to FIX live regressions during a soak/close,
  not merely report them. It can NEVER fire by default: it is gated behind an
  explicit `close: autonomous-sentinel` seed declaration plus a REQUIRED rails
  block, and every ACT dispatches through the existing hotfix-dispatch ladder.
introduced: v6.2.0
---

# Autonomous sentinel — supervised self-heal as the authorized superset of SOAK-LOOP

## The gap this fills

`references/loop-templates.md §SOAK-LOOP` and `§WORKER-WATCH` are **detection-only** by
design: "the probe detects and surfaces; it does not fix… remediation is the operator's
decision," and remediation embedded inside a watch loop is named an anti-pattern (the
depth-3 composition limit, `doctrines/workflow-patterns.md §Composition depth limit`). That
is the correct **default** — an unattended loop that silently rewrites live state is exactly
the runaway the circuit-breakers exist to prevent.

But detection-only is too restrictive for **authorized supervised autonomy**: an operator who
has explicitly read the rails, accepted the blast radius, and empowered the conductor to FIX a
live regression during a soak/close window rather than wait a tick to be asked. AUTONOMOUS-SENTINEL
is that authorized case, and **only** that case. It is the supervised-remediation **superset of
SOAK-LOOP**: everything SOAK-LOOP does (re-run the seeded acceptance predicates on wall-clock
time) plus an **ACT** stage that dispatches a bounded hotfix through the existing
hotfix-dispatch ladder, re-probes, and either converges or hard-stops.

## When it may fire (NEVER by default)

AUTONOMOUS-SENTINEL is **opt-in, twice over**. Both conditions are mandatory; absence of either
means the default detection-only SOAK-LOOP runs instead:

1. **Explicit seed declaration.** The seed carries `close: autonomous-sentinel` (the
   `references/seed-template.md` close-mode field). A seed that does not declare it can never
   produce a self-heal loop — the close report recommends a detection-only SOAK-LOOP exactly as
   today (`doctrines/outcome-enforcement.md §Seam 4`).
2. **A REQUIRED rails block.** The seed (or the loop invocation) MUST carry a `sentinel_rails`
   block declaring every hard rail below. A `close: autonomous-sentinel` declaration **without**
   a complete rails block is a seed defect — `@critic` rejects it at PLAN-GATE with
   `SENTINEL-RAILS-MISSING`, the same shape as `PLAN-MISSING-OUTCOME-VERIFICATION`
   (`doctrines/outcome-enforcement.md §Seam 2`).

The safe default is **OFF**. The config key `[close].autonomous_sentinel` defaults to `"off"`
(detection-only); it must be set to `"on"` AND the seed must declare it AND the rails block must
be complete before a single ACT can fire. Three independent gates, all opt-in.

## The stage walk

AUTONOMOUS-SENTINEL is SOAK-LOOP's `PROBE → CLASSIFY → (yield)` with an **ACT** stage spliced
between CLASSIFY and the next tick. The full walk:

```
PROBE:     Run each seeded acceptance predicate (seed §6) against live state — the same
           read-only checks SOAK-LOOP runs and the close auditor ran. No mutation here.
CLASSIFY:  Bucket each predicate result:
             HOLD       — promised-true, still true → nothing to do
             REGRESSED  — promised-true, now false  → a regression to remediate
             NEW        — a failure with no seeded baseline → NOT in scope; surface only
ACT:       For each REGRESSED predicate (NEW is detection-only, never auto-remediated):
             1. Cluster the regressions file-disjoint → H clusters (hotfix-dispatch §Counting H).
             2. Severity gate: every cluster MUST be ≤S scope. A cluster exceeding ≤S is a
                SENTINEL-SCOPE-EXCEEDED hard-stop — surface to operator, never widen.
             3. Dispatch through the hotfix-dispatch ladder (NOT a bespoke mechanism):
                  H = 1     → ONE @coder dynamic-workflow agent() step (never a teammate)
                  (1, 3]    → ONE batched dynamic workflow, ≤3 concurrent
                  > caps    → SENTINEL-HF-CAP hard-stop (see rails)
             4. GATES-BEFORE-DEPLOY: run the full gate set (format/check/lint/tests + the
                regressed predicates) on the fix BEFORE any deploy/promotion. A failed gate is
                AUTO-ROLLBACK — revert the fix, do not deploy, surface the failure.
             5. Deploy/promote ONLY if gates green AND the rails permit a live flip (paper-only
                by default — see rails). Otherwise stop at the gate-green artifact and surface.
             6. RE-PROBE: re-run the regressed predicate(s) against live state to confirm the
                fix held. A re-probe that still shows REGRESSED counts as one failed ACT cycle.
TERMINATE: K consecutive clean ticks (all HOLD)            → SENTINEL-DONE (converged)
           N total hot-fixes dispatched across the window  → SENTINEL-HF-CAP hard-stop
           --max ticks reached                             → SENTINEL-LOOP-CAP (LOOP-CAP shape)
           any hard rail tripped                           → SENTINEL-HARD-STOP (operator decision)
```

`@worker` owns PROBE/CLASSIFY (bounded, read-only, identical to SOAK-LOOP). ACT is **not** a
worker step — it dispatches `@coder` through the hotfix-dispatch ladder, conductor/root inline,
exactly as a gate-failure hot-fix would. The sentinel does not invent a remediation vehicle.

## The hard rails (all mandatory; declared in `sentinel_rails`)

These are the rails that proved this out downstream, lifted to framework-intrinsic form. Every
one is REQUIRED in the `sentinel_rails` block; a missing rail is `SENTINEL-RAILS-MISSING`:

| Rail | Binding rule | Trip → halt code |
|------|--------------|------------------|
| **gates-before-deploy** | The full gate set runs on every fix BEFORE any deploy/promotion. No deploy on red. | `SENTINEL-HARD-STOP` |
| **auto-rollback** | A failed gate reverts the fix automatically — never ships a red fix, never leaves a half-applied change. | `SENTINEL-ROLLBACK` (logged; loop continues to next tick or HF cap) |
| **≤S severity cap** | Every remediation cluster is ≤S scope (`pipeline.md §VII`). A larger fix is out of sentinel scope — surface, never widen. | `SENTINEL-SCOPE-EXCEEDED` |
| **≤3 concurrent** | At most 3 concurrent `@coder` clusters per ACT (the standing HOTFIX concurrency cap, `doctrines/hotfix-dispatch.md` corollary 1). | `SENTINEL-HARD-STOP` |
| **≤N total HF cap** | At most N hot-fixes across the whole soak window (`hf_cap`, default small). The N+1th regression hard-stops to the operator. | `SENTINEL-HF-CAP` |
| **no destructive DB ops** | No `DROP`/`TRUNCATE`/destructive migration, no irreversible data mutation, ever — regardless of authorization. | `SENTINEL-HARD-STOP` |
| **paper-only / never-flip-to-live** | Remediation stops at the gate-green artifact and does NOT flip to live/production unless the operator authorized a live flip in `sentinel_rails` (`live_flip: authorized`). Default is paper-only. | `SENTINEL-HARD-STOP` |
| **operator-override-each-tick** | The operator can halt the loop at any tick (the native `/loop` is cancelable; an operator HALT message is honored before the next ACT). The sentinel never becomes un-stoppable. | n/a (always honored) |
| **full audit trail** | Every PROBE result, CLASSIFY bucket, ACT dispatch, gate outcome, deploy decision, and re-probe is recorded via `shctx loop record` + the hook event log (`doctrines/hook-event-log.md`). A tick that mutated state without an audit row is a framework violation. | `SENTINEL-HARD-STOP` |

The ≤S, ≤3-concurrent, and ≤N caps **compose** with — they do not replace — the existing HOTFIX
caps (`doctrines/hotfix-dispatch.md` corollary 1, `pipeline.md §VII`). The sentinel's caps are an
**additional** ceiling layered on top of the standing ones.

## Termination and abort

- **Converge:** `K` consecutive clean ticks (every predicate HOLD) → `SENTINEL-DONE`. Emit the
  `## Sentinel summary` with the full predicate roster, per-tick CLASSIFY history, every ACT
  cycle (dispatch → gate → deploy/rollback → re-probe), and final verdict.
- **Hard-stop (abort):** any tripped rail, a regression exceeding ≤S, or the N-HF cap →
  `SENTINEL-HARD-STOP` / `SENTINEL-HF-CAP` / `SENTINEL-SCOPE-EXCEEDED`. The loop stops and
  surfaces an operator decision — it does NOT auto-extend, auto-widen, or auto-flip-to-live.
- **Cap (uncertain):** `--max` ticks reached while a regression is still open → `SENTINEL-LOOP-CAP`
  (the `LOOP-CAP` shape, `doctrines/workflow-patterns.md §Circuit-breaker invariants — Pattern 6`):
  surface the iteration inventory; the operator extends, accepts, or escalates.

A `SENTINEL-ROLLBACK` (auto-rollback on a failed gate) is **logged, not fatal** — it is the rails
working as designed. It counts toward the N-HF cap. Repeated rollbacks that exhaust the HF cap
escalate to `SENTINEL-HF-CAP`.

## Relationship to SOAK-LOOP and hotfix-dispatch

- **Superset of SOAK-LOOP.** AUTONOMOUS-SENTINEL = SOAK-LOOP (`references/loop-templates.md §SOAK-LOOP`,
  the `doctrines/outcome-enforcement.md §Seam 4` post-close detection) **plus** an authorized ACT
  stage. Strip the ACT stage and the rails block and you are left with exactly SOAK-LOOP. The
  default is and remains SOAK-LOOP; AUTONOMOUS-SENTINEL is the explicitly-authorized extension.
- **hotfix-dispatch is the ACT vehicle.** The ACT stage does NOT define a remediation mechanism —
  it dispatches through the cardinality ladder (`doctrines/hotfix-dispatch.md`): `H=1` → one
  subagent, `(1,3]` → one batched dynamic workflow. The sentinel narrows the ladder's upper bound
  (its ≤N HF cap is smaller than a lane), so the `H ≥ 6` dedicated-lane band does NOT apply — a
  regression that would need a dedicated lane has exceeded the sentinel's scope and hard-stops.
- **Outcome-enforcement Seam 4.** This doctrine supersets the detection-only soak that
  `doctrines/outcome-enforcement.md §Seam 4` describes. Seam 4's default is unchanged; this is the
  carve-out for the authorized case.

## What this doctrine does NOT authorize

- **Self-heal by default.** Detection-only is the default and remains the default. Without
  `close: autonomous-sentinel` + a complete rails block + `[close].autonomous_sentinel = "on"`,
  the loop is SOAK-LOOP and the depth-3 anti-pattern (remediation inside a watch loop) still binds.
- **Remediating a NEW failure.** Only `REGRESSED` predicates (promised-true, now-false against a
  seeded baseline) are in ACT scope. A `NEW` failure with no seeded baseline is surfaced for an
  operator decision, never auto-fixed.
- **Live flips without explicit authorization.** Paper-only is the default. A live/production flip
  requires `live_flip: authorized` in the rails block — otherwise the sentinel stops at the
  gate-green artifact.
- **Widening scope to fix a big regression.** A regression exceeding ≤S is out of scope —
  `SENTINEL-SCOPE-EXCEEDED`, surfaced, never widened. The sentinel is bounded remediation, not a
  rescue sprint.
- **An un-stoppable loop.** The operator-override-each-tick rail and the native `/loop`
  cancelation mean the sentinel is always haltable. A sentinel that cannot be stopped is a
  framework violation.

## Cross-doctrine references

- `references/loop-templates.md §AUTONOMOUS-SENTINEL` — the per-role template (Stage Graph shape,
  termination predicate, halt codes, example); the supervised superset of `§SOAK-LOOP`
- `references/loop-templates.md §SOAK-LOOP / §WORKER-WATCH` — the detection-only defaults this extends
- `doctrines/outcome-enforcement.md §Seam 4` — the detection-only post-close soak this supersets
- `doctrines/hotfix-dispatch.md` — the cardinality ladder the ACT stage dispatches through (the vehicle)
- `doctrines/workflow-patterns.md §Composition depth limit` — the depth-3 note reconciled to carve out this case
- `doctrines/loop-templates.md` — binding loop doctrine (bounded / role-shaped / measurable predicate)
- `references/seed-template.md` — the `close: autonomous-sentinel` declaration + `sentinel_rails` block (Seam 1)
- `references/grading-rubric.md` — `OUTCOME-REGRESSION` caps completeness (the regression the sentinel acts on)
- `pipeline.md §VII` — the HOTFIX subgraph caps (≤S scope, ≤3 concurrent, iteration cap) the sentinel layers on
