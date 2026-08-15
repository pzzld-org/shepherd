---
name: adaptation
description: "Harvest and reuse measured failures and successes through Shepherd's adaptation loop. Use after a gate, review, eval, or run produces a repeatable lesson, trend, prior, or dispatch recommendation."
---

# adaptation — the self-improvement loop every role runs

Never relearn the same failure; "barely passes" is a halt condition. This defines the
harvest-store-inject-cite loop, `INSIGHTS`, and the shared excellence bar.

## Loop contract

The registry (a project-local store, concrete implementation per harness) holds three
kinds of row: per-run metrics (grade, size, cost), per-finding severity/concern rows (the
harvest source), and deduped lessons promoted from HIGH/CRITICAL findings only — never from
info/low/medium. **Harvest**: at close, roll every HIGH/CRITICAL finding into one deduped
lesson per recurring concern (never per occurrence). **Inject**: at the start of plan or
seed authorship, surface the accumulated lessons and metrics into that role's context — an
empty store emits nothing, never an error. **Cite**: a plan or seed acting on a lesson MUST
cite its id in its own rationale — this is the measurement signal that the inject step is
actually being read, not skipped. **Trend**: before a run closes, mechanically (never
eyeballed) check the last few runs for a recurring severity, a downward grade trend, or
rising cost, and surface it as an informational alert.

## INSIGHTS

Any role's report MAY append an optional `INSIGHTS` block — a cross-lane observation,
separate from its acceptance predicates, never required. Exactly six kinds: `relocation`
(thing lives in the wrong place), `extension` (extend this while nearby), `duplication` (N
copies of a pattern exist), `consolidation` (two things could merge, or dead code exists),
`gap` (something the plan didn't anticipate), `nit` (minor, actioned only once 3+
accumulate). Read-only awareness — never a mutation channel; the plan author decides which
insights become scoped work next time.

## Excellence bar

Every role states and follows seven rules: (1) read before writing, reuse before creating,
and run dedup checks before dispatch and implementation; (2) turn a scope gap into an
amendment or halt, never silent expansion; (3) honor language idioms and refuse a
one-file dumping ground; (4) justify each wrapper, dependency, or abstraction with a
documented invariant or three concrete uses; (5) halt rather than ship below-bar work;
(6) cite instead of restating and delegate bulk work within a bound; (7) put arithmetic,
date math, lookups, parsing, hashing, and counting in tested deterministic code. Missing
this bar from a role contract is a review finding.
