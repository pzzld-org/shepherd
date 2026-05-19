---
name: start
description: Run one complete sprint end-to-end (engineer → critic → coder waves → auditor swarm → close), then PAUSE for operator sign-off before opening the next sprint. For continuous or multi-sprint modes, see /shepherd:spawn (--auto and --parallel <N> flags).
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
---

# /shepherd:start — Single Sprint Execution

Execute **one sprint** end-to-end then stop and wait for the operator. For continuous or multi-sprint modes, see `/shepherd:spawn` (`--auto` and `--parallel <N>` flags).

## Step 0 — Auto-orient (ALWAYS first, every invocation)

1. **Load shepherd skill context** — invoke `shepherd` via the Skill tool. This loads `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/SKILL.md` and the conductor quick reference.

2. **Read shepherd.toml** — `.claude/shepherd.toml` (or `.local.toml` override). If missing, surface a warning and proceed with framework defaults per `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md`. If the file fails validation, STOP and surface the error.

3. **Detect current branch** — `git branch --show-current`. Match against `[branching].sprint_branch_pattern`. If on a sprint branch → that is the active sprint. If on the patch branch → cut the next sprint branch first, per `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/branching-model.md` §II.

4. **Load project doctrines** — read every `*.md` under `[memory].project_doctrines` (default `.claude/doctrines/`) and inject as a preamble to every flock dispatch this session.

5. **Fetch most recent handoff** — `ls -t {paths.docs}/*-close-handoff.md | head -1`. Read it. Extract: what shipped last sprint, current carry-forwards + GH issue numbers, deploy state, first task for this sprint.

6. **Read project CLAUDE.md** — current workspace state, active version, deploy state, in-progress context.

7. **Synthesize orientation** internally (one paragraph — not shown unless operator asks):
   - Sprint identity (version + sprint slot)
   - Prior close grade + outstanding blockers
   - Carry-forwards that must land this sprint
   - What the seed says the north-star is

Then proceed to Step 1.

---

## Step 1 — Load conductor profile

Read `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` in full and adopt it as a system-prompt addendum for this session. The conductor profile is the single source of truth for sprint-runner behavior: pipeline structure, dispatch rules, Stage Graph walk algorithm, gate discipline, close synthesis, halt codes, and operator communication norms. All behavioral prescriptions for running the sprint live there.

---

## Step 2 — Run pipeline

Execute the three-section pipeline per `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` §§Step 1–3 (INTRODUCTION → BODY → CLOSE). After CLOSE-FINALIZE completes and the CONDUCTOR CLOSE REPORT is emitted, this command halts and waits for operator sign-off — single-sprint discipline enforced. Re-invoke `/shepherd:start` for the next sprint, or `/shepherd:spawn --auto` for the teammate-driven sequential autopilot.

---

## See also

- `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` — full conductor profile (pipeline, dispatch, gates, halt codes)
- `${CLAUDE_PLUGIN_ROOT}/commands/spawn.md` — teammate variants (`--auto`, `--parallel <N>`)
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/flock.md` — per-agent dispatch rules
- `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` — shepherd.toml schema
