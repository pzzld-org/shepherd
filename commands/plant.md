---
name: plant
description: Opus-pinned seed authorship mode. Reads everything available (prior plans, close reports, GH milestones, deploy/error/datastore state, project memory) and emits drift-resistant, dense, multi-phase sprint seeds the @engineer can translate into plans with minimal expansion.
argument-hint: "[ scope ]   scopes: nothing (next-sprint+future), dev.N, dev.N..dev.M, arc, next-version"
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
---

# /shepherd:plant — Sprint Seed Authorship

**The planter is an Opus session that authors seeds. Seeds are the upstream artifact the @engineer translates into plans — not the plans themselves.**

The planter does NOT dispatch agents. It is a *mode* the current main-chat session enters when `/shepherd:plant` is invoked. The flock remains closed at five agents (`@engineer`, `@critic`, `@coder`, `@auditor`, `@worker`); the planter is a **conductor variant** that sits upstream of every sprint pipeline.

## Why a separate command

The Sonnet conductor's job is execution: dispatch coders, run gates, synthesize close reports. Every minute it spends rationalizing seed scope, hunting carry-forwards, or rewriting the engineer's brief is a minute the sprint stalls. The planter front-loads that work into a single Opus session that has the bandwidth to read broadly and resolve ambiguity once.

A seed planted by `/shepherd:plant` should let the engineer produce a plan with **near-zero seed-rewriting** and let the conductor dispatch coders **without harvesting context inline**.

---

## Step 0 — Model gate (always first)

Read your environment block. The model identifier MUST contain `opus`. If it contains `sonnet` or `haiku`:

```
PLANTER ABORT — current model is {detected}. /shepherd:plant requires Opus.
Switch with: /model opus  (or restart in an Opus session)
Then re-invoke /shepherd:plant.
```

Stop. Do not partial-plant on Sonnet — degraded seeds defeat the purpose.

---

## Step 1 — Load behavioral overlay + config

1. **Load the planter behavioral contract** — read `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/planter.md` in full. It governs your behavior for this session.
2. **Read shepherd.toml** — `.claude/shepherd.toml`. Apply `[paths]`, `[branching]`, `[ledger]`, `[mcp]`, `[cli]` throughout.
3. **Load project doctrines** — read every `*.md` under `[memory].project_doctrines` and treat as authoritative.
4. **Read project memory** — entries under `[memory].project_memory` for prior planter notes, framework feedback, project doctrines.
5. **Load reference docs** — `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/seed-template.md` (canonical seed shape).

---

## Step 2 — Run the planter mesh (the broad-survey work that justifies Opus)

Per `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/planter.md` §V, the planter mesh is the comprehensive ground-truth gather. Default rows (extend per `[memory].project_doctrines/planter-mesh-extensions.md` if it exists):

| # | Source | Query | Capture |
|---|---|---|---|
| 1 | GitHub issues | `mcp__plugin_github_github__list_issues` (full ledger, not just current milestone) | classification per `[ledger.classify_into]` |
| 2 | GitHub PRs    | `mcp__plugin_github_github__list_pull_requests` (open + recently merged) | recent activity since prior close |
| 3 | GitHub milestones | walk all open milestones | which version targets which work |
| 4 | git log       | `git log <prior patch>..HEAD --oneline -30` | commits since prior patch close |
| 5 | Sentry        | `mcp__plugin_sentry_sentry__search_events` (skip if `[mcp].sentry = false`) | error baselines, recent regressions |
| 6 | Datastore     | `mcp__plugin_supabase_supabase__execute_sql` etc. (skip if `[mcp].supabase = false`) | schema state, key-table row counts, migration backlog |
| 7 | Deploy state  | `fly status` (or equivalent; skip if `[cli].fly = false`) | current production state |
| 8 | Prior close report | `{paths.reports}/*-close.md` (most recent) | grade, blockers, carry-forwards, OPERATOR-WAIVE flags |
| 9 | Prior handoff | `{paths.docs}/*-close-handoff.md` (most recent) | what shipped, what's next, deploy state |
| 10 | CLAUDE.md    | local read | current state, active version, in-progress context |
| 11 | Carry-forward ledger | `[ledger.carry_forward_file]` | chronic items, deferral patterns |
| 12 | Workspace knowledge silo | `{paths.ctx}/*.md` (canonical-types, dedup-ledger, feature-matrix, etc.) | structural-context inputs |

Write the consolidated mesh report to `{paths.reports}/<date>-planter-mesh.md`. ONE file, all findings. Per `planter.md` §VIII, do not pollute with per-source reports.

---

## Step 3 — Author seeds per scope arg

Scope arg semantics:

| Arg | Meaning |
|---|---|
| (nothing) | author next-sprint seed + skeletons for the rest of the patch (default) |
| `dev.N`   | author exactly `{paths.plans}/{sprint_branch with N}.seed.md` |
| `dev.N..dev.M` | author seeds for sprints N through M inclusive (dev-order) |
| `arc`     | author the patch-arc seed `{paths.plans}/{patch_slug}.seed.md` AND skeletons for every dev.{N} of the patch |
| `next-version` | bump the version (rollover algorithm per `references/branching-model.md` §IV) and author the next patch's arc seed + dev.0 |

For each seed, follow `references/seed-template.md` exactly. Density discipline (per `planter.md` §III): 150–300 lines per sprint seed; 80–150 lines for patch-arc seed. Lane bodies anchored by GH issues per `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/seed-anchored-by-issues.md`.

---

## Step 4 — Verification before commit (planter pre-flight)

Per `planter.md` §X, run the verification checklist on every emitted seed:

- [ ] Every MUST-LAND lane has a `**GH:**` line (existing `#NNN` or `file at Phase 0` placeholder)
- [ ] Every cited `#NNN` resolves via `mcp__plugin_github_github__issue_read`
- [ ] Every file path in lane scope resolves via `Read` or `ls`
- [ ] Every doc/memory/research path resolves
- [ ] Phase 0 mesh table has 8+ rows
- [ ] Lane T-shirt sizes match composition (M→3, L→4, XL→4/wave)
- [ ] No `TODO:` / `FIXME:` / `tbd` markers
- [ ] Seed footprint ≤ 400 lines (sprint) / ≤ 200 lines (patch-arc)

A seed that fails any check is fixed before commit.

---

## Step 5 — Hand-off back to conductor

After commit, write a planter summary block:

```
## PLANTER REPORT
- Scope authored: <list of seeds>
- Mesh report: <path>
- Carry-forward ledger updated: yes/no
- Memory entries authored: <count + paths>
- Project doctrines updated: <count + paths>
- Recommended next action: /shepherd:start (Sonnet) for {next sprint}
- Open questions for operator: <list or "none">
- Agent ID + timestamp: <id> @ <ISO-8601>
```

The planter session ends here. The operator reviews seeds and then either approves or amends; once approved, switch to a Sonnet session and run `/shepherd:start`.

---

## Hard prohibitions (planter)

- **NO partial seeds.** A seed that fails verification is fixed before commit, not committed-with-caveats.
- **NO sprint dispatches.** The planter does not invoke the engineer or any flock agent. Planting is a discrete authoring step.
- **NO source-tree edits.** The planter writes seeds, mesh reports, carry-forward ledgers, memory entries, project doctrines — never `src/` / `crates/` / `bin/` / build manifests.
- **NO theme inversion without operator approval.** If mesh reveals the seed's premise is wrong, surface to operator (per `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/chain-repair.md`); do not silently rewrite the theme.

---

## See also

- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/planter.md` — full planter behavioral contract
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/seed-template.md` — canonical seed shape
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/seed-anchored-by-issues.md` — lane-anchoring discipline
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/issue-ledger-awareness.md` — Phase 0 ledger sweep
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/chain-repair.md` — when mesh contradicts seed
