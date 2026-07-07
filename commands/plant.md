---
name: plant
description: Seed authorship mode. Reads project signal (issues, PRs, prior close, memory) and emits sprint seeds for @engineer to plan. Use when starting a new sprint, patch, or version arc.
argument-hint: "[ scope ]   scopes: nothing (next-sprint+future), dev.N, dev.N..dev.M, arc, next-version  — NOTE: for a brand-new patch arc N always starts at 0, not 1"
allowed-tools: Bash, Edit, Glob, Grep, Read, AskUserQuestion, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
---

# /shepherd:plant — Sprint Seed Authorship

`/shepherd:plant` enters **planter mode** — meta-orchestrator state, never a flock dispatch. MUST NOT dispatch `@engineer`/`@critic`/`@coder`/`@auditor`/`@worker`/`@discovery`; flock stays closed at six domain agents.

## Step 0 — Model advisory (always first)

Detect model tier; surface advisory ONCE — advisory only, NEVER a gate; proceed on ANY tier.

| Tier | Model id | Stance |
|---|---|---|
| Superior | `claude-fable-5` | Best seed quality, priciest; use when quality dominates cost. |
| Recommended (default) | `claude-opus-4-8[1m]` | Deep-enough synthesis at reasonable cost. |
| Allowed — degraded | `claude-sonnet-4-6` / `claude-haiku-4-5-20251001` | Planting proceeds; emit advisory below. |

Below recommended, emit ONCE, continue:

```
PLANTER MODEL ADVISORY — current model is {detected}. Opus is recommended (Fable 5 superior).
Seed quality may be degraded on this tier; the @engineer may need to re-harvest context.
To upgrade: /model opus  (or restart in an Opus/Fable 5 session). Proceeding to plant.
```

NEVER refuse to plant on a lower tier — operator may have deliberately chosen it.

## Step 1 — Adopt the planter contract

Load `agents/planter.md` in full as system-prompt addendum; `§Plant mode` is canonical past Step 0: config/doctrine load, 12-row mesh, seed authorship, pre-flight verification, commit, PLANTER REPORT.

For a brand-new patch arc (no `dev.*` branches on origin), sprint numbering N is ALWAYS 0 — never derived from prior patch's counter (`agents/planter.md §Sprint numbering`).

Scope argument: nothing (next-sprint + future skeletons), `dev.N`, `dev.N..dev.M`, `arc`, `next-version`.

Session ends after the PLANTER REPORT is emitted (`agents/planter.md §Seed handoff`). NEVER dispatches the engineer; NEVER begins the sprint pipeline.

## See also

- `agents/planter.md` §Plant mode, §Sprint numbering, §Seed handoff — mesh, authorship, prohibitions, N-rule, report shape, babysitter mode
- `skills/shepherd/references/spawn-flags.md` §--staged — concurrent staged-spawn handoff
- `skills/shepherd/references/seed-template.md` — canonical seed shape
- `skills/adaptation/SKILL.md` §Loop contract — priors cited during authorship
