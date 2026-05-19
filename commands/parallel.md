---
name: parallel
description: RETIRED in v5.1.4 — multi-worktree fanout consolidated into /shepherd:spawn --parallel <N>. See migration note below.
allowed-tools: Read, Skill
---

# /shepherd:parallel — Retired in v5.1.4

Multi-worktree fanout (running several sprints concurrently from a single Claude
Code session) has been retired in favor of the teammate-based
`/shepherd:spawn --parallel <N>`. Each parallel sprint runs in its own teammate
with its own worktree, with the main-chat planter coordinating scope-collision
avoidance, dev-order merge gating, and per-teammate cleanup.

## Migration

- Old: `/shepherd:parallel` (N sprints in one session, N worktrees)
- New: `/shepherd:spawn --parallel <N>` (N sprints in N teammates, N worktrees)

Requirements for the new mode (same as `--auto`):
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true`
- Claude Code v2.1.32 or later

See `commands/spawn.md` for full `--parallel` semantics.
