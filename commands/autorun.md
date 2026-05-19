---
name: autorun
description: RETIRED in v5.1.4 — sequential autopilot consolidated into /shepherd:spawn --auto. See migration note below.
allowed-tools: Read, Skill
---

# /shepherd:autorun — Retired in v5.1.4

Sequential-autopilot mode (a loop of sprints in the same Claude Code session) has
been retired in favor of the teammate-based `/shepherd:spawn --auto`. The new
mode spawns a fresh teammate per sprint, giving each one a clean context window
and eliminating the cross-sprint degradation that plagued autorun on long patches.

## Migration

- Old: `/shepherd:autorun`
- New: `/shepherd:spawn --auto`

Requirements for the new mode:
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true` in environment
- Claude Code v2.1.32 or later

If teammates are NOT enabled, use `/shepherd:start` per sprint manually. Sequential
single-session autopilot is no longer supported.

See `commands/spawn.md` for full `--auto` semantics.
