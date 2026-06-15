---
title: outcome-enforcement
description: |
  Shepherd ships code and green gates reliably but drifts off the OUTCOME a seed
  promised. This doctrine binds outcome verification to four existing seams — the
  seed declares machine-checkable acceptance predicates, the plan-gate confirms
  they exist, the close gate RE-RUNS them before grading, and an optional
  post-close SOAK-LOOP re-verifies them on wall-clock time. Behavioral wiring
  only — no new schema, no new state table.
introduced: v6.1.3
---

# Outcome enforcement — make the seeded outcome the thing that closes the sprint

## The drift this fixes

A shepherd sprint is good at *delivery*: code lands, the worktree rebases clean, the gates
(`format`/`check`/`lint`/tests) go green, the auditor swarm grades for code quality. None of
that proves the **outcome the planter seeded** is actually true. The seed says "the API p99
drops under 100 ms" or "there are exactly five `impl X for Y`" or "the error rate stays under
1/min" — and the sprint can grade **A** while that promise silently regressed, because nothing
between the seed and the grade re-evaluates the promise.

The fix is not a new subsystem. The seed *already* carries acceptance predicates (`seed §6`),
and the auditor *already* re-runs the **prior** sprint's predicates at INTRO
(`doctrines/intro-combo-wave.md §4`). This doctrine closes the loop on the **current** sprint:
the outcome a seed promised is the thing whose truth the close gate certifies, and an optional
SOAK-LOOP keeps certifying it after delivery.

## The acceptance predicate

An **acceptance predicate** is a single runnable check with a known expected result — a grep
with a count assertion, a structural assertion, a LOC floor, a query against a log/metric/DB,
a health probe. Prose is not a predicate. "Auth feels faster" is not enforceable;
`curl -fsS $URL/health | jq -e '.p99_ms < 100'` is. Every deliverable in `seed §6` carries at
least one (`references/seed-template.md`); the engineer makes them runnable in the plan's
`[ACCEPTANCE]` blocks (`references/agent-briefs.md`).

## The four seams (normative)

Outcome enforcement binds to seams that already exist. A sprint that promises an outcome MUST
honor all four; a sprint that genuinely promises no machine-checkable outcome (rare — pure
docs/scaffolding) declares that explicitly so the gates can no-op instead of silently passing.

### Seam 1 — SEED: declare the outcome as a predicate

The planter writes each deliverable's outcome as a runnable acceptance predicate in `seed §6`
(`references/seed-template.md §6` + the new `§6-bis Outcome verification`). The predicate is
the promise in checkable form. A deliverable with a prose acceptance line and no runnable
check is a seed defect — `planter §Step 4` rejects it.

### Seam 2 — PLAN-GATE: confirm the predicates exist (the @critic check)

When the `@critic` runs PLAN-GATE, it verifies every deliverable carries a runnable acceptance
predicate the close gate can execute. A plan whose `[ACCEPTANCE]` blocks are prose-only, or
that drops a seeded predicate, fails the gate with **`PLAN-MISSING-OUTCOME-VERIFICATION`** and
reverts to the engineer for amendment (`agents/critic.md`). This is not a new gate — it is one
more item on the existing PLAN-GATE checklist.

### Seam 3 — CLOSE: re-run the predicates before the grade (the enforcement point)

This is where enforcement bites. At CLOSE-FINALIZE, **before** the completeness grade is
synthesized, the close auditor re-runs every seeded acceptance predicate against current HEAD /
live state and compares each to its promised truth value (`agents/auditor.md` close mode,
`agents/conductor.md §3 CLOSE-SWARM`):

- A predicate **promised true that now returns false** is an **`OUTCOME-REGRESSION`** — filed
  as a HIGH finding, and it **caps the completeness grade** (no A/A- while a seeded outcome is
  false) per `references/grading-rubric.md`.
- All predicates holding → the grade proceeds normally.

This makes the seeded outcome, not just code quality, load-bearing on the grade. It reuses the
auditor's existing read-only re-run machinery (the same one INTRO uses on the prior sprint),
pointed at *this* sprint's seed.

### Seam 4 — SOAK (optional, post-close): keep verifying on wall-clock time

A green close certifies the outcome *at the moment of delivery*. Outcomes can still regress
after — a deploy degrades, a row count drifts, an error rate climbs the next day. The
**SOAK-LOOP** template (`references/loop-templates.md §SOAK-LOOP`) re-runs the seeded
predicates on a post-close interval (T+1d, T+7d) via the native `/loop` + `Monitor`, and
surfaces `OUTCOME-REGRESSION` if a promise breaks. By default it is **detection only** — a
regression opens a new operator decision, never an auto-remediation. The close report
*recommends* a soak when the seed declared post-delivery-sensitive outcomes; the operator
starts it:

```
/shepherd:loop "soak outcomes for <sprint>" --agent worker --interval 1d --max 6
```

**Authorized supervised exception (v6.1.5).** Detection-only is the default and the
anti-pattern for the *unauthorized* case (remediation inside a watch loop — the depth-3
composition limit, `doctrines/workflow-patterns.md §Composition depth limit`). There is one
carve-out: an operator who has *explicitly* empowered the conductor to FIX live regressions —
not merely report them — can run the **AUTONOMOUS-SENTINEL** template
(`references/loop-templates.md §AUTONOMOUS-SENTINEL`), the supervised-remediation **superset of
SOAK-LOOP**: `PROBE → CLASSIFY → ACT (dispatch a ≤S `@coder` hotfix via the hotfix-dispatch
ladder → gates-before-deploy → re-probe) → TERMINATE (K clean ticks / N-HF cap / hard-stop)`. It
can NEVER fire by default — it is gated behind `[close].autonomous_sentinel = "on"` (default
`"off"`) **plus** a `close: autonomous-sentinel` seed declaration **plus** a complete
`sentinel_rails` block (gates-before-deploy, ≤S severity, ≤N HF cap, no destructive DB ops,
auto-rollback, paper-only/never-flip-to-live, operator-override-each-tick, full audit trail).
Without all three gates the soak stays detection-only and embedding remediation in the probe
remains the anti-pattern. See `doctrines/autonomous-sentinel.md` (origin v6.1.5).

## Where the outcome lives across compaction

The seeded predicates ride in the **focus record** the orchestrator already keeps
(`commands/focus.md`, `doctrines/coordinate-active-drive.md`): they belong in the focus
`objective` / `obligations` payload as the sprint's standing "what must remain true," so a
post-compaction rehydration (`hooks/scripts/focus_rehydrate.sh`) restores not just *where* the
walk is but *what outcome* it is driving toward. No schema change is required — the predicate
list is carried as part of the existing focus JSON, the same way obligations are.

## What this doctrine is NOT

- **Not a new gate engine.** It is four annotations on seams that already run (seed author,
  plan-gate, close audit, optional loop). No new hook, no new table, no new command.
- **Not a remediation loop — by default.** Every seam *detects and surfaces*; fixing a
  regressed outcome is the operator's decision and opens its own dispatch (hotfix or sprint).
  The one authorized exception is the **AUTONOMOUS-SENTINEL** superset of Seam 4's SOAK-LOOP
  (`doctrines/autonomous-sentinel.md`), which an operator may EXPLICITLY empower to remediate —
  gated behind `[close].autonomous_sentinel = "on"` + a `close: autonomous-sentinel` seed
  declaration + a complete `sentinel_rails` block, and never by default.
- **Not a replacement for code-quality auditing.** Outcome verification is *additive* to the
  close swarm's existing concerns — a sprint must be both well-built and outcome-true.
- **Not applicable only to services.** Predicates are equally greps/counts/LOC floors for pure
  code sprints, not just latency/error queries.

## Cross-doctrine references

- `references/seed-template.md` — `§6` deliverables + `§6-bis Outcome verification` (Seam 1)
- `agents/critic.md` — `PLAN-MISSING-OUTCOME-VERIFICATION` PLAN-GATE check (Seam 2)
- `agents/auditor.md`, `agents/conductor.md §3` — close-time predicate re-run (Seam 3)
- `references/grading-rubric.md` — `OUTCOME-REGRESSION` caps completeness
- `references/loop-templates.md §SOAK-LOOP` — the detection-only post-close re-verification template (Seam 4)
- `references/loop-templates.md §AUTONOMOUS-SENTINEL`, `doctrines/autonomous-sentinel.md` — the authorized supervised-remediation superset of Seam 4's SOAK-LOOP (v6.1.5); never fires by default
- `doctrines/intro-combo-wave.md §4` — the prior-sprint predicate re-run this generalizes
- `doctrines/coordinate-active-drive.md` — the focus record that carries the predicates
