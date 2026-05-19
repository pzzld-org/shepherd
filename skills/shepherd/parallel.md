---
name: shepherd-parallel
description: RETIRED in v5.1.4 — see skills/shepherd/SKILL.md and commands/spawn.md for the --parallel <N> replacement.
---

# Retired

`/shepherd:parallel` was retired in v5.1.4. The skill body that supported the
single-session multi-worktree mode is preserved in git history. The replacement
is `/shepherd:spawn --parallel <N>`, documented in:

- `${CLAUDE_PLUGIN_ROOT}/commands/spawn.md` — command body + --parallel flag
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/spawn-escalation.md` §X — multiplexed escalation doctrine
- `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` — planter's multi-teammate triage responsibility

No further content in this file.
