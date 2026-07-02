---
title: model-map
status: binding
introduced: v6.2.5
description: |
  One place maps each flock/meta role to the model it dispatches with — the
  [models] block of .claude/shepherd.toml, resolved by `shctx models resolve
  <role>`. Every dispatching tier (root, conductor, engineer) injects the
  resolved slug as the Agent-tool `model:` pin instead of hand-pinning per spawn.
  Unset roles fall to built-in defaults (root/planter/engineer = opus[1m]; the
  rest = sonnet). root is ADVISORY — a config key cannot rebind a running
  main-chat session, so a spawn preflight only warns on mismatch. Config-driven
  wiring; the resolution chain leaves insertion points for future profile/mode
  presets with zero rework to the map.
---

# Model map — one table maps roles to models, so scale stops meaning error (#170)

At ultra-parallel scale for long durations, hand-pinning `model:` on every spawn
is a class of error: forget the pin and an Opus lead session makes every teammate
inherit Opus, multiplying cost by the lane count (the v6.0.9 conductor-pin
regression). The fix is a single declarative map.

## The map

`.claude/shepherd.toml [models]` maps each role to a model slug:

```toml
[models]
root      = "opus[1m]"   # advisory (see below)
planter   = "opus[1m]"
engineer  = "opus[1m]"
conductor = "sonnet"
critic    = "sonnet"
discovery = "sonnet"
coder     = "sonnet"
auditor   = "sonnet"
worker    = "sonnet"
```

Set any role to any slug for total control. The section is read section-aware
(`cfg_section_get`, mirrored in both `_lib.sh` copies), so the bare role keys do
not collide with other sections.

## Resolution chain (forward-compatible)

`shctx models resolve <role>` resolves in order:

1. explicit `[models].<role>` key — **ships now** (total control)
2. active profile/mode preset — **future** (deferred; a named preset that expands
   to a role→model set, so an operator need not write the table)
3. root-tier-derived default — **future** (the root's model auto-derives the flock
   map; e.g. `root = fable` → richer flock, `root = sonnet` → limited)
4. built-in default — **ships now** (= the table above)

Layers 2-3 are deferred; the chain leaves the slots so they land with zero rework
to the map. See `docs/configuration.md §models`.

## Dispatch wiring — every tier injects the pin

The map only bites if dispatchers honor it. Each dispatching tier resolves the
target role's model and injects it as the Agent-tool `model:` param / teammate
spawn pin:

- **root / `@shepherd`** — resolves `planter`, `engineer`, and each spawned
  lane's `conductor`; injects the pin. Generalizes the v6.0.9 conductor pin.
- **`@conductor`** — resolves `coder`, `auditor`, `worker`, `discovery` for its
  in-lane fan-out; injects the pin.
- **`@engineer`** (self-contained mode) — resolves `discovery`, `auditor`, and
  `critic` for its in-session read-only sub-flock (the INTRO-COMBO-WAVE it runs +
  its own critic gate; `doctrines/engineer-self-contained-plan.md`).

The conductor cost advisory still fires: if `conductor` resolves to an opus tier,
the pre-spawn advisory (`commands/spawn.md`) warns about the per-lane cost
multiplier — the map makes the choice explicit, it does not hide the cost.

## root is advisory

`agents/shepherd.md` is `model: inherit` **by design** — the root tier IS the lead
chat's model. A `[models].root` key cannot rebind a session that is already
running, so it names the model the session SHOULD run: a spawn preflight
(`shctx models show`) warns once if the live session differs (an under-powered
root is the coordination-quality bottleneck for ultra-parallel spawns). The 8
spawned roles are the ones actually hard-driven by the pin.

## Mechanical teeth

- `shctx models resolve <role>` is deterministic: config value if set, else the
  built-in default; an unknown role is an error, not a silent empty pin.
- `shctx models show` renders the full resolved table + source per row (feeds the
  dashboard and the spawn preflight).
- Built-in defaults equal the documented defaults, so a project with no `[models]`
  block behaves exactly as the stated defaults.

## Anti-patterns

- Hand-pinning `model:` per spawn instead of resolving from the map.
- Assuming a `[models].root` key changes the running main-chat model (it is
  advisory — warn, do not pretend).
- A dispatcher that reads the map but forgets to inject the pin (an inert map).

## See also

- `doctrines/primitive-axis-binding.md` — the tiers that dispatch.
- `doctrines/dispatch-tier-separation.md` — who dispatches whom.
- `doctrines/brief-cache-discipline.md` — why the per-lane pin matters for cost.
- `doctrines/engineer-self-contained-plan.md` — the engineer's in-session discovery dispatch.
