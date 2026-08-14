---
name: shepherd
---

# shepherd — the sprint-execution contract

The contract binding every role's dispatch, gating, and reporting into one sprint
execution. Detailed per-harness dispatch mechanics live in `content/predicates/` and each
harness's own adapter; this skill states the harness-neutral CONTRACT those mechanics
enforce.

## The flock is closed

Six implementer roles (`content/roles/{engineer,critic,coder,auditor,worker,discovery}.md`)
plus two meta tiers (`conductor`, the lane-executor lead; `planter`, the seed author and
spawn babysitter) plus the root orchestrator (`shepherd`) — nine roles total, never a tenth
invented ad hoc. A specialist need outside this set is a scope decision for the dispatcher
to make explicitly, never a silent substitution.

## Dispatch law

Every dispatch of an implementer role names the role explicitly and pins a model — never
inherits whatever model the dispatching session happens to run under. The brief goes in
the dispatch payload, never inline-restated agent-body text. A lane-executor lead never
dispatches the plan-author or gating roles directly — that's root-tier-exclusive; a lead
needing one escalates instead of substituting its own judgment.

## Root contract

Work splits by SECTION, not by role: **introduction** (a fresh discovery-and-orientation
pass every run, plan authorship, a gate) always runs before anything spawns and never
inherits a prior run's version of itself; **body** (one lane-executor lead per lane) runs
until every lane's wave graph is walked, wave-gated by a clean review verdict at each
boundary; **close** (root-direct) aggregates every lane's payload, runs a concern-split
review swarm on the aggregate, remediates anything critical, then executes every
close-time integration operation itself. Root never writes source, never dispatches an
implementer directly outside its own no-lead fallback mode, and never silently absorbs a
subordinate's finding without materializing it as a durable artifact.

## Principles

**Durable artifact** — every top-tier dispatch terminates in exactly one durable artifact
(a plan, a seed, a report, a registry row); reasoning that lives only in a transcript is
spend without impact.

**Subtract** — a run should end net-negative on production surface (files, dependencies,
abstractions, lines) scoped to source only; net-positive requires explicit pre-authorized
justification, never a silent overrun. Ship net-negative while still delivering the
feature: replace rather than append, inline single-callers, collapse hollow wrappers,
retire deprecated shims the same run, and prune the dependency tree regularly.

**External-service write discipline** — when a managed write API is genuinely available
(loaded, connected, and answering within a stated time budget), every write goes through
it; when it's unavailable — absent, unloaded, or hung past budget — the sanctioned
lower-level fallback is not a contract violation, it's the correct choice, and the report
says so explicitly rather than leaving the fallback unexplained. A tool that is loaded but
hangs past its budget is UNAVAILABLE for contract purposes, not merely slow.

**Provider-agnostic discovery** — never hard-assume a specific external-service binding by
name; discover the connected provider's capability at runtime and degrade to a sanctioned
fallback when discovery finds nothing connected, rather than failing silently.
