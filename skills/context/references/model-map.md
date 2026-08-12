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
