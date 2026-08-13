# Cheap fan-out: who gets to dispatch it

**Status:** proposed — operator decision, due at the W2 decomposition
**Date:** 2026-08-13
**Applies to:** v6.4.5 arc, `SKILL.md §Dispatch law`, `§Fan-out counterweight` (#256), #263
**Blocks on:** DF-46

## The want

Maximize reach per token. A reviewer that fans out eight narrow haiku probes covers more
ground than one sonnet reading serially, at a fraction of the cost. The operator's tiering
policy already encodes the principle: *"discovery can be sonnet or haiku but if haiku then
larger fan-out, more specific task."* The proposal extends it — grant `Workflow` to
`@discovery`, `@critic` and `@auditor` so each compiles its own cheap fan-out, dispatching
either its own role or `@worker` at haiku.

The want is right. The mechanism is where this splits.

## Most of the reach is already coming, from a rule we are landing anyway

`AUDIT-CONCERN-UNDECLARED` (Check 7, lane l6-guards, W2-G1) denies any `@auditor` brief
carrying zero or ≥2 `[CONCERN]` declarations. Its purpose was to stop concern-bundling
(DF-43). Its **side effect is the fan-out being asked for here**, and that is not a
coincidence — bundling and cheap-fan-out are the same axis read in opposite directions.

Measured, this wave:

| | Bundled (observed) | One-concern-per-dispatch (Check 7) |
|---|---|---|
| root's W1-S2 audit | 5 concerns, 1 sonnet agent, **124,348 tok / 537s** | 4 read-only haiku + 1 sonnet (the only one needing `cargo`), parallel, **~73k / ~3 min** |
| l1's W1-S1 audit | 8 items, 1 sonnet brief | 8 narrow briefs; most are file-scope/dedup/doc-link reads → haiku |

A narrow brief is what makes haiku viable. Check 7 forces narrow briefs. **The reach falls
out of the guard with no new dispatch grants at all** — the conductor, which already holds
`Workflow` legitimately under #263, dispatches N cheap single-concern auditors instead of one
fat one. Same coverage, same cost curve, zero new dispatching tiers.

## Why the grant itself is the expensive part

Three objections, in descending order of how much they bite.

**1. We cannot observe the tiers we already have (DF-46, CRITICAL, today).** Root dispatched
auditor `a7b8…`; l2-registry independently reported waiting on "my own dispatched auditor,
agentId `a7b8…`" — root's agent. Both tiers claimed it. Root was right only by holding the
`tool_use_id`. Nothing answers *"who dispatched this agent"*; `auditor-verdicts.txt` was
empty; `ListAgents` returned no teammates. The loser of that ambiguity **deadlocks silently**
while reading healthy in `shctx teammate liveness`. Adding a third and fourth dispatching
tier multiplies the ambiguity that stalled a lane this morning. Ordering is not negotiable:
**dispatch-ownership recording lands before any grant widens.**

**2. `@auditor` and `@critic` are judgment roles; sharding them averages instead of judges.**
An auditor's grade is supposed to be defensible by the agent that signed it
(`agents/auditor.md` — grade, rationale, methodology, one report per concern). An auditor
that dispatches haiku sub-auditors and synthesizes their verdicts is **laundering grading
authority through agents that never loaded the rubric**. Worse, a haiku `@worker` dispatched
by an auditor carries no `[CONCERN]`, no rubric, no report shape — it reproduces DF-43's
bundling defect one level down, below where Check 7 can see it. The same argument holds for
`@critic`: splitting adversarial reasoning across shards and averaging is not adversarial
reasoning.

**3. The counterweight binds harder, not softer (#256).** Auditors invoke the build. N
auditors × M probes each running `cargo` is precisely the FL03/axiom incident — 16 MB free
physical memory, 8.6/9.2 GB swap, the kernel SIGKILLing a *teammate doing useful work* rather
than the excess fan-out. #263 already widened compile-a-workflow to three tiers and the
counterweight says that binds harder each time the set grows. Rule 2 is the direct answer
here: **fan out fixes, verify once centrally.**

## `@discovery` is the exception, and it is a real win

Every objection above is about grading, mutating, or building. `@discovery` does none of
them — the role table already says it *"NEVER mutates, grades, or dispatches"*, and the first
two of those are what make the third safe to relax:

- no rubric → nothing to launder
- no writes → no file-scope collisions
- no build → the shared-resource clause does not apply
- output is a compiled report, which is exactly the shape that shards and merges cleanly

This is also precisely what the operator proposed earlier this sprint — *"a sonnet discovery
subagent who dispatches haiku agents to compile a research report on behalf of the engineer
in his initial workflow thing."* Sonnet `@discovery` as the compiler, haiku `@worker` shards
underneath it, one report out. Bounded, cheap, safe.

## Recommendation

1. **Now, free:** take the reach from Check 7. One `[CONCERN]` per dispatch, model chosen per
   brief width — haiku for read-only concerns (file scope, dedup, doc-links, naming,
   byte-diffs), sonnet for anything invoking the build, and the build runs **once**.
2. **Next, gated:** grant `Workflow` to `@discovery` only, with a declared concurrency cap and
   haiku-`@worker` shards. Gate it on DF-46's ownership recording landing first.
3. **Refuse:** `Workflow` for `@critic` and `@auditor`. Their value is a single accountable
   verdict. If one auditor is not enough coverage, that is a signal to dispatch **more
   auditors from the conductor**, each with its own concern — which is (1), and which the
   guard now enforces.

Net effect: the reach the proposal wants, minus the two grants that would make DF-46 worse.

## Open question for the operator

The proposal named **"luna"** as a candidate cheap model. No such id exists in this session's
Agent tool (`sonnet`, `opus`, `haiku`, `fable`) and `grep -rn 'luna'` across `.shepherd/`,
`agents/` and `skills/` returns nothing. Assuming haiku throughout. **If `luna` is a real
model you have access to, give me the exact id** — `shepherd.toml [models]` pins literal
slugs and `Workflow agent()` never reads that map (#255), so a wrong slug fails at dispatch,
not at config load.
