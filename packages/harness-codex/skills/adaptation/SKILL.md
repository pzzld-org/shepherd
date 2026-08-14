---
name: adaptation
---

# adaptation — the self-improvement loop every role runs

No role should relearn the same failure twice; "barely passes" is a halt condition, not an
acceptable outcome. Canonical home of the harvest-store-inject-cite loop, the `INSIGHTS`
taxonomy, and the excellence bar every role reads first — abstracted from the Claude-side
`shctx adapt` CLI into the registry concept any harness's own store implements.

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

Every role's contract opens with this, verbatim or equivalent: **read before writing,
reuse before creating, justify additions with a documented invariant; the lazy path
through duplication is more work, not less — refuse it; honor language idioms; refuse
"everything in one file"; halt early rather than ship sub-standard work; conserve
tokens — every line is a paid line.** A missing statement of this bar in a role's own
definition is itself a finding at review time, not a stylistic nit.

**Seven rules, briefly:** (1) read-before-write, reuse-before-create, dedup checks run
both pre-dispatch and again inside the implementer's own step; (2) the lazy path is more
work — a scope gap becomes an amendment request or a halt, never a silent expansion or a
duplicate; (3) honor each language's own idioms; (4) justify every new wrapper/dependency/
abstraction against a documented invariant or ≥3 concrete use cases; (5) halt rather than
ship below-bar work; (6) conserve tokens — cite, don't restate, push bulk work to bounded
subordinate dispatches; (7) deterministic work (arithmetic, date math, lookups, parsing,
hashing, counting) is a script, never a model reply improvised twice.
