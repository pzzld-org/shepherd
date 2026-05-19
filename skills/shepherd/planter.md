---
name: shepherd-planter
description: RETIRED in v5.1.4 — canonical planter profile moved to agents/planter.md.
---

# Retired

The full planter behavioral contract (seed authorship discipline, drift-resistance
contract, density discipline, multi-phase doctrine, anti-patterns) was moved to
`${CLAUDE_PLUGIN_ROOT}/agents/planter.md` in v5.1.4 as part of the meta-tier
extraction (planter + conductor become canonical agent-file profiles).

The planter operates in two modes:

- **Plant mode** (`/shepherd:plant`): seed authorship
- **Spawn mode** (`/shepherd:spawn`): ambient babysitter alongside a spawned
  teammate-conductor

See:
- `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` — canonical profile (both modes)
- `${CLAUDE_PLUGIN_ROOT}/commands/plant.md` — slash command for plant mode
- `${CLAUDE_PLUGIN_ROOT}/commands/spawn.md` — slash command for spawn mode

No further content in this file.
