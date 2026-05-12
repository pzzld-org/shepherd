---
name: autorun
description: Sequential autopilot — runs sprint after sprint without the inter-sprint PAUSE. Same pipeline as /shepherd:start, looping until a hard stop or operator interrupt.
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
---

# /shepherd:autorun — Sequential Autopilot

**One conductor session, one flock, one sprint at a time, no pause between sprints.**

This is `/shepherd:start` running in a loop with the PAUSE step removed. There is no parallel branching, no worktree fan-out, no multi-sprint interleaving. For multi-sprint parallel orchestration, use `/shepherd:parallel`.

## Step 0 — Auto-orient (every invocation)

Identical to `/shepherd:start` Step 0 — load skill, read `shepherd.toml`, detect branch, load project doctrines, fetch handoff, read CLAUDE.md, synthesize orientation. See `${CLAUDE_PLUGIN_ROOT}/commands/start.md` for the full Step 0.

## What changes vs `/shepherd:start`

| `/shepherd:start` | `/shepherd:autorun` |
|---|---|
| PAUSE after every sprint close | No PAUSE — seed dev.{N+1} immediately |
| User clears context manually between sprints | Conductor continues into next sprint |
| User explicitly re-invokes `/shepherd:start` | Loop continues until exit condition |
| dev.{last} close → STOP, wait for release signal | dev.{last} close → STOP unless sprint-through granted |

Everything else is **identical** to `/shepherd:start`:

- @engineer authors plan via `superpowers:brainstorming` + `superpowers:writing-plans`, gated by @critic
- Coder waves dispatched in parallel batches per the Brief-Validity Checklist
- Gates between every wave (one pass: `[gates.check]` + `[gates.lint]` + `[gates.format]` + `[gates.extra]`)
- @auditor swarm of 3–5 by concern at sprint close (Pattern B overlap during waves)
- Close finalizer: handoff doc + memory update + CLAUDE.md patch
- Rebase-merge into patch branch → cut next sprint branch

## Sprint-through grant (release pipeline autonomy)

The default behavior on dev.{last} close is STOP and wait for the operator's release signal. To pre-authorize the full release pipeline, the operator says one of:

- "sprint through"
- "autonomous release at dev.{last}"
- "pipe through to v{next}"

OR a per-project `feedback_sprint_through_release_authority.md` (or equivalent) memory exists tagged with the current version.

Sprint-through authorizes the dev.{last} release pipeline (squash → main → tag → release → bump → cut next patch + dev.0). Non-dev.{last} merges to main still require explicit approval.

## Hard stops (always halt the loop)

1. **@critic returns RED** or substantive pass-2 flag → operator amendment needed
2. **Gates broken** after all coder waves exhausted → no wave can resolve it
3. **dev.{last} close without sprint-through** → release signal required
4. **Secret / credential rotation needed** → outside flock scope
5. **Seed drift** from Phase 0 mesh — verify per `doctrines/chain-repair.md` before escalating; if substantive, halt
6. **Operator interrupt** — "pause", "stop", "exit autorun"
7. **Coder rejected brief with `BRIEF INVALID`** → fix conductor's brief before re-dispatch (do not silently retry)

On exit: write final entry to `{paths.docs}/<date>-autorun-summary.md` with what landed, what's running, what's next, what needs the operator.

## See also

- `${CLAUDE_PLUGIN_ROOT}/commands/start.md` — single-sprint sibling
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/autorun.md` — full autorun behavior + loop discipline
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/SKILL.md` — conductor quick reference
