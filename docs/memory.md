# Memory and context

Shepherd separates durable structured state from host-native prose memory. The
separation is what lets Claude, Codex, and Pi resume the same run without
copying one harness's private files into another.

## Shepherd-owned context

The project namespace has two related stores:

- `.shepherd/ctx/` is the canonical cross-run context artifact root.
- `.shepherd/shepherd.db` is the typed registry used for searchable records,
  identity, liveness, locks, duplicate declarations, and recorded results.

Run-specific facts live under `.shepherd/runs/<run>/`. A run's seed, plan,
lane plans, dispatch records, reports, audits, handoff, and close evidence must
not be copied into a global notes directory. Cross-run documentation belongs
directly under the flat `.shepherd/docs/` root.

The user namespace at `~/.shepherd/` holds only direct `shepherd*.toml` default
candidates. It is not a second project run ledger, context root, profile store,
or template store. The native resolver keeps project and user roots distinct;
project templates stay project-owned under `.shepherd/templates/`.

## What the registry provides

The registry is deterministic and queryable. It is used for facts that must be
available outside a model turn:

| Structured Shepherd state | Why it is not just prose |
| --- | --- |
| Run and lane lifecycle | Commands must validate transitions and ownership. |
| Dispatch identity and resume | A later harness must verify the same identity key. |
| Teammate liveness and coordination locks | Hooks and operators need current state without a model response. |
| Duplicate declarations and symbol/artifact search | Gates need repeatable queries. |
| Recorded evaluation and issue views | Results need stable schemas and exit behavior. |

The native `mem`, `query`, `search`, `insights`, and `export` command families
read these typed records. They do not invoke a second interpreter or judge.

## Host-native memory

Claude Code, Codex, and Pi may each have their own user or project memory
features. Those are useful for preferences and prose lessons, but they are not
Shepherd authority. A host-native note cannot authorize a run transition, change
a guard policy, or replace a dispatch record.

When a host memory contains a reusable lesson, promote the stable contract to a
project doctrine or a bounded content source. Keep the live run decision in the
run artifact that produced it.

## Context selection and budgets

Resume assembles a bounded context from the canonical run and registry facts.
It prefers the seed, current plan, active lane evidence, recent dispatch state,
and the latest handoff, then truncates lower-priority prose before it crosses
the native context budget. The component/compiler uses the same versioned
UAX #29 measurement rules for roles, skills, and references.

Keep context useful:

- record one fact once and link to it rather than restating it;
- put run decisions in the run directory, not in a global doctrine;
- put durable cross-run lessons in `ctx/` or a flat `docs/` document;
- keep role and skill files under their hard word and byte ceilings;
- keep host-specific observations in adapter diagnostics, not in the core.

## Safe resume

Resume is accepted only when the canonical run id, harness identity, dispatch
binding, and artifact paths validate together. A missing or ambiguous identity
is unresolved or blocked according to the typed contract. It must not silently
fall back to a guessed role, guessed run, or host-local memory file.

See [Integration](integration.md) for the cross-harness contract and
[Configuration](configuration.md) for namespace ownership.
