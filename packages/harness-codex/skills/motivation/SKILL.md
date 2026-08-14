---
name: motivation
---

# motivation — focus, drive, loops, outcomes

Time, for a machine, is irrelevant — only outcomes are. This skill states the durable
focus/drive state model and loop discipline any lead role runs, independent of which
harness's own wake/schedule primitive implements it (`schedule-wakeup` in the capability
vocabulary, `RECONCILIATION.md`).

## Focus record

A durable north-star record survives context compaction: an objective, the plan-graph
cursor, the current ready set of work, open obligations, and hold-true invariants — keyed
per run, and per lane for a lane-executor lead's own slice. On a long stretch with no
external wake, the record is what lets a resumed session re-anchor to *where it was and
what outcome it was chasing*, not just restart from nothing.

## Drive contract

Once a run's leads are confirmed live, the top-level lead ENTERS an active drive loop as
its default mode until close — dispatching subordinate work is the start of active
coordination, never a hand-off to wait passively. The cycle, every wake: **act** (drain the
message queue, route by escalation code, release the next gate on a verified completion
signal, prune an idle subordinate); **probe** (sweep liveness and diff subordinate state
for drift, re-anchor the focus record); **yield** (one status line, never a busy-wait spin
and never an operator prompt outside the small enumerated set of legitimate stop points).
Passive-waiting at a dispatch boundary with no real question pending is never legitimate.

## Loop discipline

Every loop MUST be bounded (a max-iteration cap set before the first iteration, never
open-ended), role-shaped (the iterating role's own contract fixes what convergence means —
an implementer converges a gate, a researcher exhausts a question, a reviewer refines a
hypothesis chain), and terminate on a measurable predicate the brief states up front, never
prose. An iteration producing no measurable progress is a stall, flagged as a finding, not
silently repeated. Pacing (fixed-interval vs self-paced vs in-session) is a separate axis
from the bound itself; a watch-style loop that stops early on "healthy" defeats its own
purpose.

## Soak and sentinel

A clean close certifies a seeded outcome only at delivery — a deployed system can still
regress afterward. A soak loop re-runs every seeded acceptance predicate on a post-close
interval, detection-only by default: a regression opens a new decision point, never
auto-remediation. A supervised-remediation superset (never on by default, requiring an
explicit multi-gate authorization) may additionally probe, classify, and fix a regression
through the same hotfix ladder every other remediation path uses — full audit trail, a
hard concurrency and total-fix cap, gates before any deploy, automatic rollback on a failed
gate, and no destructive data operation ever, regardless of authorization.
