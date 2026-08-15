---
name: motivation
description: "Maintain durable focus, drive, loops, and outcome tracking across long-running Shepherd work. Use when work must continue through waits, compaction, monitoring, or repeated progress checks."
source: skills/motivation/SKILL.md
portability: cross-harness
---

# motivation — focus, drive, loops, outcomes

Outcomes, not elapsed time, govern work. This defines the durable focus record and bounded
drive loop independently of the harness wake primitive.

## Focus record

A run, and each active lane, records its objective, graph cursor, ready work, obligations,
and invariants. Resume loads that record and the smallest referenced artifacts instead of
replaying a transcript.

## Drive contract

After leads are live, root drives until close. Every wake: **act** on events and verified
completion, **probe** liveness and drift, update focus, then **yield** one status line.
Never busy-wait, passively abandon a dispatch, or prompt the operator without a real stop.

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
