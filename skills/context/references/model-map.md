---
title: model-map
description: |
  The [models] table maps each flock/meta role to a model slug, resolved via
  `shctx models resolve <role>`. Use when pinning a dispatch model or auditing
  which model a role actually runs with.
---

# Model map — one table, every role

Hand-pinning `model:` on every spawn is an error class at scale: forget the pin and
an Opus lead makes every teammate inherit Opus, multiplying cost by lane count. The
fix is one declarative map.

## The map

`.claude/shepherd.toml [models]`:

```toml
[models]
root      = "opus[1m]"   # advisory — see below
planter   = "opus[1m]"
engineer  = "opus[1m]"
conductor = "sonnet"
critic    = "sonnet"
discovery = "sonnet"
coder     = "sonnet"
auditor   = "sonnet"
worker    = "sonnet"
```

**Bare-key rule:** `[models]` role keys carry no section prefix. The config reader
(`cfg_section_get`) resolves them section-scoped, so a bare `coder` key here MUST
NOT collide with `[gates].coder` or any other section's same-named key.

## Resolution

`shctx models resolve <role>` resolves, in order: (1) explicit `[models].<role>` —
ships now; (2) active profile/mode preset — deferred; (3) root-derived default —
deferred; (4) built-in default (the table above) — ships now. An unknown role is an
error, never a silent empty pin. `shctx models show` renders the full resolved table
with the source of each row.

## Dispatch wiring

Every dispatching tier MUST resolve and inject the pin before it spawns:

- **root** — resolves `planter`, `engineer`, and each lane's `conductor`.
- **`@conductor`** — resolves `coder`, `auditor`, `worker`, `discovery` for its
  in-lane fan-out.
- **`@engineer`** (self-contained mode) — resolves `discovery`, `auditor`, `critic`
  for its in-session read-only sub-flock.

If `conductor` resolves to an opus tier, the pre-spawn cost advisory still fires —
the map makes the choice explicit, it does not hide the cost.

## Tier sets fan-out width

The map answers *which* model. This answers *how many*. A dispatcher that knows the
role but not the tier under-scales cheap work and over-scales expensive work, and
both are waste.

| Tier | Cost | Fan-out posture |
|---|---|---|
| `haiku`, `luna` | cheap | **Wide. 60+ in one workflow is normal, not reckless.** Shard fine, overlap deliberately, use redundancy as the hallucination filter. |
| `sonnet`, `terra` | mid | The default working tier. Mid-width — a wave of steps, a handful of auditors. |
| `sol`, `opus`, `fable` | expensive | **Reserved, not fanned out.** One shot at the join, the judgement, the synthesis — the places where being wrong is costly. |

Two consequences worth stating, because dispatchers get both backwards:

- **Redundancy is cheaper than care at the bottom tier.** N independent `haiku` agents
  on one question with a majority vote beats one careful agent, and it kills fabricated
  citations that a single pass will confidently emit. Spend the redundancy where it
  costs nothing.
- **Sharding twice is nearly free.** Two independent decompositions of the same corpus
  (by subject AND by file, say) catch what either alone structurally cannot — a
  subject-sharded agent never sees a claim in a file its greps do not reach.

### This is the accelerator; #256 is the brake

`skills/shepherd/SKILL.md §Fan-out counterweight` caps concurrency and is binding. It
does NOT cap agent COUNT — it caps contention for a **shared resource**, and every rule
in it is about the project's build. Sixty `haiku` agents running `grep` and `Read`
contend for nothing; twelve `sonnet` agents each invoking `cargo` took a 16 GB box to
16 MB free. Classify the wave before sizing it:

- **Resource-bound** (runs the build, the test suite, a container, a migration) →
  #256 governs. Compute the cap from headroom. Verify once, centrally.
- **Token-bound** (reads, greps, prose extraction, judging, voting) → tier governs.
  Go wide. The runtime already caps live concurrency at `min(16, cpus - 2)`; a surplus
  queues rather than thrashes, so under-dispatching buys nothing but thinner coverage.

## Spawn depth

`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` decides whether a dispatched agent can itself
dispatch. At depth ≥ 2 a `sonnet` sub-lead — a `@discovery` or an intro-`@auditor` —
may fan out its own `haiku` helpers, which is the cheapest way to widen a read-only
sweep without widening the lead's own context. At depth 1 it cannot: the `Agent` tool
is removed from the agent's pool at the depth limit.

**Resolve it, do not read it.** The env var is configuration; the capability is whether
`Agent` is in the sub-lead's visible tool list. Those are different layers and this run
proved they disagree (`dogfood.md` DF-64/65/67/68). A dispatcher that reads the key and
plans a depth-2 tree is making the DF-66 mistake one level down. The sub-lead probes its
own tool list for `Agent` before promising a sub-fan-out, and falls back to doing the
work itself when it is absent — a downgrade to state, not to apologise for.

Never `ToolSearch` for `Agent` to answer this: it resolves deferred tools only, so a null
is a false negative by construction (`skills/harness/SKILL.md §Tool presence`).

## `root` is advisory

`agents/shepherd.md` is `model: inherit` by design: a `[models].root` key cannot
rebind an already-running session. `shctx models show` warns once on a mismatch; the
other 8 roles are hard-driven by the pin.

## Anti-patterns

- Hand-pinning `model:` per spawn instead of resolving from the map.
- Assuming `[models].root` changes the running session's model.
- Reading the map but forgetting to inject the pin (an inert map).

## See also

- `shctx models resolve conductor` is cited from `commands/spawn.md §Spawn dispatch`.
- `skills/shepherd/references/flock.md §Dispatch` — the tiers that dispatch.
