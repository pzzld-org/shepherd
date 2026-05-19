---
name: shepherd-autorun
description: RETIRED in v5.1.4 — see skills/shepherd/SKILL.md and commands/spawn.md for the --auto replacement.
---

# Retired

`/shepherd:autorun` was retired in v5.1.4. The skill body that supported its
sequential loop semantics is preserved in git history. The replacement is
`/shepherd:spawn --auto`, documented in:

- `${CLAUDE_PLUGIN_ROOT}/commands/spawn.md` — command body + --auto flag
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/spawn-escalation.md` §XI — sequential autopilot doctrine
- `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` — planter's sprint-rollover responsibility

No further content in this file.
