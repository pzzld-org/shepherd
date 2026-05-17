---
name: start
description: Run one complete sprint end-to-end (engineer → critic → coder waves → auditor swarm → close), then PAUSE for operator sign-off before opening the next sprint.
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
---

# /shepherd:start — Single Sprint Execution

Execute **one sprint** end-to-end then stop and wait for the operator. For continuous mode, see `/shepherd:autorun`. For multi-sprint worktree fan-out, see `/shepherd:parallel`.

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

Then proceed.

---

## Pipeline

```
Step 0    → auto-orient (config + handoff + branch detect + doctrines + CLAUDE.md)

§1 INTRO  → main chat verifies seed → dispatch @engineer (Opus) → Phase 0 mesh runs first → plan returned
§2 BODY   → @critic gate → parallel @coder waves (mandatory + domain skills loaded; workers dispatched at Wave 1 START)
            between waves: {gates.check} + {gates.lint} + {gates.format} + extra gates from [gates.extra]
            tests/benches wave runs INSIDE the body (not a separate phase)
            hot-fix coders as needed (< S each, max 3 concurrent)
            Pattern B overlap: auditors on Wave N run in same batch as Wave N+1 coders
§3 CLOSE  → @auditor SWARM (3–5 agents, parallel, by concern; completeness verifies issue-ledger discipline + SUBTRACT)
            synthesize close report + grade + memory + project-doctrine updates + CLAUDE.md patch
            rebase-merge dev.N → patch branch
            DELETE dev branch from origin AND locally (verify deletion)
            run [release.driver] if dev.{last} (most projects: github-workflow takes over)
            cut dev.{N+1} branch off the patch branch
            write handoff doc

PAUSE     → stop and wait for operator to clear context before dev.{N+1}
```

---

## §1 INTRODUCTION — @engineer dispatch

@engineer (Opus) is dispatched with:
- Path to the seed file: `{paths.plans}/{sprint_slug}.seed.md`
- Path to the prior close report (from handoff)
- Carry-forward GH issue numbers from the handoff
- Path to the project's carry-forward ledger: `[ledger.carry_forward_file]`
- Mesh surface availability flags: `[mcp]` and `[cli]` from `shepherd.toml`
- Explicit instruction to **run Phase 0 mesh first** (per `${CLAUDE_PLUGIN_ROOT}/agents/engineer.md` and `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/SKILL.md` §III)

Engineer writes `{paths.plans}/{sprint_slug}.plan.md` — a parallel-optimized plan with wave decomposition, full `[CONTEXT-INVENTORY]` and `[DO-NOT-DUPLICATE]` per lane, conditional links between phases, and an embedded Phase 0 mesh report. Main chat does NOT write the plan.

The introduction produces ALIGNMENT, not code. §2 BODY follows once @critic gates the plan.

---

## Exit conditions (single sprint — always exits after one)

After the PAUSE step, execution stops. Re-invoke `/shepherd:start` for the next sprint, or `/shepherd:autorun` to bypass the pause.

---

## Hard stops mid-sprint

Stop immediately and surface to the operator when:
- @critic returns RED (seed-level issue — needs operator amendment)
- @critic pass-2 returns a `substantive` flag (not `dispatcher-patch`)
- Gates fail after all coder waves and no hot-fix wave can resolve it
- A secret rotation or irrevocable action outside flock scope is required
- dev.{last} close reached (release pipeline needs explicit release signal unless sprint-through was granted)
- Phase 0 mesh contradicts the seed's premise → verify per `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/chain-repair.md` before escalating

---

## See also

- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/flock.md` — full per-agent dispatch rules
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/autorun.md` — loop variant (`/shepherd:autorun`)
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/agent-briefs.md` — copy-paste brief templates
- `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` — shepherd.toml schema
