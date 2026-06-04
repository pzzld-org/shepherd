---
name: plant
description: Opus-pinned seed authorship mode. Reads everything available (prior plans, close reports, GH milestones, deploy/error/datastore state, project memory) and emits drift-resistant, dense, multi-phase sprint seeds the @engineer can translate into plans with minimal expansion.
argument-hint: "[ scope ]   scopes: nothing (next-sprint+future), dev.N, dev.N..dev.M, arc, next-version  — NOTE: for a brand-new patch arc N always starts at 0, not 1"
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
---

# /shepherd:plant — Sprint Seed Authorship

**The planter is an Opus session that authors seeds. Seeds are the upstream artifact the @engineer translates into plans — not the plans themselves.**

The planter does NOT dispatch agents. It is a *mode* the current main-chat session enters when `/shepherd:plant` is invoked. The flock remains closed at six domain agents (`@engineer`, `@critic`, `@coder`, `@auditor`, `@worker`, `@discovery`); the planter is a **meta-orchestrator** that sits upstream of every sprint pipeline.

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

## Step 1 — Load planter profile + config

1. **Load the planter behavioral contract** — read `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` in full and adopt it as a system-prompt addendum for this session. It is the single source of truth for planter behavior: mesh protocol, seed authorship, drift-resistance contract, density discipline, verification checklist, hard prohibitions, and the hand-off report shape.
2. **Read shepherd.toml** — `.claude/shepherd.toml`. Apply `[paths]`, `[branching]`, `[ledger]`, `[mcp]`, `[cli]` throughout.
   - **Bootstrap path (#120):** If `.claude/shepherd.toml` does not exist, this is a first-ever plant. Surface: *"No `.claude/shepherd.toml` found. Copy `${CLAUDE_PLUGIN_ROOT}/examples/minimal/shepherd.toml` to `.claude/shepherd.toml`, fill in `[branching]`, `[paths]`, and `[ledger]`, then re-invoke `/shepherd:plant`."* Then STOP — do not attempt to derive config inline. The template provides safe defaults; the operator must make the branching + path choices before seeding.
3. **Load project doctrines** — read every `*.md` under `[memory].project_doctrines` and treat as authoritative.
4. **Read project memory** — entries under `[memory].project_memory` for prior planter notes, framework feedback, project doctrines.
5. **Load reference docs** — `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/seed-template.md` (canonical seed shape).

---

## Step 2 — Run plant mode

Execute per `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` §"Plant mode — seed authorship" (Steps 2–5): run the 12-row planter mesh — row 12 reads the adaptation priors (`shctx adapt priors --lessons`); cite any `prior:<id>` that shapes the seed per `doctrines/self-improvement.md` — author seeds for the scope argument, run the pre-flight verification checklist on every seed, commit, and emit the PLANTER REPORT. The planter session ends after the report is emitted. Do not dispatch the engineer; do not begin the sprint pipeline.

> **Sprint numbering:** Before authoring any seed, run the N-derivation step in `agents/planter.md §Step 3` to determine the correct starting sprint number. For a brand-new patch arc (no `dev.*` branches on origin for this patch version), N is always **0** — never infer it from a prior patch's sprint counter.

---

## See also

- `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` — full planter behavioral contract (mesh, authorship, prohibitions, babysitter mode)
- `${CLAUDE_PLUGIN_ROOT}/commands/spawn.md` — teammate variants (`--auto`, `--parallel <N>`)
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/seed-template.md` — canonical seed shape
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/seed-anchored-by-issues.md` — lane-anchoring discipline
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/chain-repair.md` — when mesh contradicts seed
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/self-improvement.md` — adaptation priors (harvested lessons) feed seed authorship
