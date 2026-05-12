# Agent Dispatch Brief Templates

Use these as starting points when dispatching flock agents from a `/shepherd:*` sprint. Fill in `{...}` placeholders. Project-specific values come from `shepherd.toml`.

---

## Conductor Brief-Validity Checklist (DEDUP-GATE node — run BEFORE every coder dispatch)

This checklist IS the runtime body of the `DEDUP-GATE` graph node (per `pipeline.md` §II + `doctrines/zero-duplicate-tolerance.md`). A coder brief is **invalid** unless every box below is checked. **The Agent batch does NOT fire until every box is green.** Skipping this checklist means you are gambling that the agent will invent what you forgot — which has produced documented duplicate-code drift across patches.

### Brief-shape checks
- [ ] All **seven** bracketed headers present verbatim — `[SKILLS]`, `[CONTEXT-INVENTORY]`, `[DO-NOT-DUPLICATE]`, `[USER-STYLE]`, `[FILE-SCOPE]`, `[NON-GOALS]`, `[ACCEPTANCE]`. Do NOT rename or paraphrase — the parser is strict.
- [ ] `[WORKTREE]` block present with `Path:`, `Branch:`, `Commit template:` lines.
- [ ] **`[BASE-COMMIT-EXPECTED]` block present** with the recorded SHA (the conductor runs `git rev-parse HEAD` on `{sprint_branch}` IMMEDIATELY before this dispatch and pastes the short SHA). Per `doctrines/conductor-cwd.md` companion contract — the coder rejects the worktree on mismatch.
- [ ] `[FILE-SCOPE]` is file-disjoint from every OTHER coder dispatched in the same wave.
- [ ] `[NON-GOALS]` explicitly lists scope items reserved for other sprints or other coders.
- [ ] `[ACCEPTANCE]` is runnable (greps, structural assertions, LOC counts) — not prose.
- [ ] Four supporting lines present: absolute repo path + branch, commit-message template (`fix(dev.N/<track>): ...`), `DO NOT run gates / build / test`, `No new build-manifest deps without approval`.

### Skills auto-attachment (mechanical — conductor computes, never trusts engineer)
- [ ] `[SKILLS]` matches the conductor's mechanical computation per `flock.md` §II.@coder Required-Skills Matrix.
- [ ] Every primary-language file in `[FILE-SCOPE]` has its matching language skill in `[SKILLS]` (.rs→`rust`, .py→`python`, .ts/.tsx→`typescript`, .go→`go`, ...).
- [ ] `[skills.mandatory]` entries (always `code-style`) all appear.
- [ ] Every `[skills.detection]` pattern matching a `[FILE-SCOPE]` path contributes its skills.
- [ ] `[USER-STYLE]` contains `code-style` at minimum.

### Anti-duplication pre-flight (conductor RUNS the greps; failure BLOCKS dispatch)
- [ ] `[CONTEXT-INVENTORY]` cites at least one existing symbol per new package / module the scope touches, each with an absolute path verified by Read or Grep.
- [ ] `[CONTEXT-INVENTORY]` cites from `{paths.ctx}/canonical-types.md` for every concept the lane touches.
- [ ] `[DO-NOT-DUPLICATE]` names every new identifier the coder is about to introduce, with an expected grep result.
- [ ] **The conductor has run every `[DO-NOT-DUPLICATE]` grep in the live workspace** — every result equals the expected count. Hits ≠ expected → DISPATCH BLOCKED, brief amended (convert lane to "wire to existing"), re-run checklist.

A brief that fails any checkbox must be fixed before you call the Agent tool. Per `doctrines/zero-duplicate-tolerance.md`, fixing-after-dispatch wastes context and is the documented failure mode.

---

## `@engineer` — Phase 0 mesh + plan authorship

```
You are @engineer for {sprint_branch}. Your job is two-part:
(1) compile the current-state mesh (Phase 0), and
(2) use the mesh + seed to write a detailed, parallel-optimized sprint plan.

**Repo:** {abs_path}, branch `{sprint_branch}`.
**Seed:** `{paths.plans}/{sprint_branch}.seed.md`
**Prior handoff:** `{paths.docs}/<date>-<prior sprint>-close-handoff.md`
**Prior close report:** `{paths.reports}/<date>-<prior sprint>-close.md` (if exists)
**Carry-forward GH issues:** <list of GH# from handoff>
**Carry-forward ledger:** `{ledger.carry_forward_file}`
**Mesh surface availability:** github={mcp.github}, sentry={mcp.sentry}, supabase={mcp.supabase}, fly={cli.fly}

Read your full system prompt at ${CLAUDE_PLUGIN_ROOT}/agents/engineer.md for behavioral contract.
```

The engineer's full Phase 0 mesh + plan-authorship contract lives in `${CLAUDE_PLUGIN_ROOT}/agents/engineer.md` — the conductor injects that body at the head of every dispatch.

---

## `@coder` — feature implementation

Use this template as the canonical coder brief. The bracketed structure is non-negotiable.

```
Repo: {abs_path}, branch `{sprint_branch}`. Implementation task.
Commit template: fix(dev.{N}/{track}): {subject}
DO NOT run gates / build / test — main chat validates.
No new build-manifest dependencies without conductor approval.

**Mission:** {one-sentence goal}

**Seed + plan references:**
- `{paths.plans}/{patch_branch}.seed.md`        — patch-arc seed
- `{paths.plans}/{sprint_branch}.plan.md`        — this sprint's plan
- {any prior audit reports that inform this task}

[WORKTREE]
- Path: {abs_worktree_path}                    (the conductor sets `isolation: "worktree"`; this is your home)
- Branch: {worktree_branch}                    (the agent's isolated branch — DO NOT push)
- Commit template: fix(dev.{N}/{track}): {subject}

[BASE-COMMIT-EXPECTED]
# The SHA the worktree was branched from. Coder MUST verify before any edits
# (per agents/coder.md Step 0.5). Mismatch ⇒ HALT with `BASE-DRIFT`.
- {sprint_branch} HEAD at dispatch: {short_sha}    (run `git rev-parse HEAD` in the worktree)

[SKILLS]
- code-style                          (mandatory per [skills.mandatory])
- {language-skill}                     (per [skills.by_domain] for this lane's primary language)
- {domain-skill 1}                     (per [skills.by_domain] for this lane's domain)
- {domain-skill 2}                     (if applicable)

[CONTEXT-INVENTORY]
# Every existing symbol the lane will reuse, with absolute path
- `{Symbol}` in `{abs path}::{module}` — {one-line description}
- ...

[DO-NOT-DUPLICATE]
# Language-specific greps that MUST return 0 hits before lane writes new code
- {grep pattern} → expected 0
- {grep pattern} → expected 0

[USER-STYLE]
- code-style

[FILE-SCOPE]
MAY MODIFY:
- {path 1}
- {path 2}
MUST NOT TOUCH:
- {paths owned by other lanes in this wave}

[NON-GOALS]
- {scope items reserved for later sprints}
- {scope items reserved for other lanes}

[ACCEPTANCE]
# Runnable greps and structural assertions; NOT prose
- {grep} → {expected count}
- {gate command from [gates] passes — main chat runs}
- {file count delta verification}
```

> **`[BASE-COMMIT-EXPECTED]` is mandatory as of v5.0.3.** The conductor records
> the SHA at dispatch time (`git rev-parse HEAD` on `{sprint_branch}`); the
> coder verifies it before Step 1. This catches the v5.0.1 failure mode where
> a worktree was branched from `main` instead of the active sprint branch
> (cherry-pick conflict storm). See `doctrines/conductor-cwd.md` for the
> companion conductor discipline.

---

## `@critic` — adversarial gate

```
You are @critic. READ-ONLY. Adversarial review of the engineer's plan.

**Plan to review:** `{paths.plans}/{sprint_branch}.plan.md`
**Seed:** `{paths.plans}/{sprint_branch}.seed.md`
**Phase 0 mesh:** `{paths.reports}/<date>-{sprint_branch}-phase0.md`

**Project primary objectives** (yardstick — pulled from project CLAUDE.md "north star"):
1. {primary objective 1}
2. {primary objective 2}
3. {primary objective 3}

Read your full system prompt at ${CLAUDE_PLUGIN_ROOT}/agents/critic.md for behavioral contract.

**Output the verbatim verdict shape — Verdict, Primary Concerns, Unstated Assumptions, Scope Cuts, Cheaper Alternatives, Alignment Check, Issue-Ledger Considerations, Questions for Dispatcher.**
```

---

## `@auditor` — code-quality review (per concern)

Dispatch ONE auditor per concern. 3–5 concerns per swarm.

```
You are @auditor — concern: {code-quality | data-flow | dependency-topology | datastore-state | completeness}.

**READ-ONLY.** You file findings; you do NOT apply fixes (per doctrines/auditor-readonly.md).

**Sprint:** {sprint_branch}
**Plan:** `{paths.plans}/{sprint_branch}.plan.md`
**Phase 0 mesh:** `{paths.reports}/<date>-{sprint_branch}-phase0.md`
**Files touched:** {list from `git diff {patch_branch}..HEAD --name-only`}
**Report path:** `{paths.reports}/<date>-audit-{concern}.md`

**Concern-specific emphasis:**
- code-quality: language-idiom adherence, naming, dead code, deprecated markers (consult {language-skill})
- data-flow: business-critical paths, gate logic, fail-closed verification, side-effects
- dependency-topology: build-manifest hygiene, feature gating, wrapper-grep gate (doctrines/wrapper-must-earn.md)
- datastore-state: schema migrations, advisor warnings, row counts, query correctness
- completeness: real-work test, SUBTRACT verification (doctrines/subtract-dont-add.md), issue-ledger discipline (doctrines/issue-ledger-awareness.md), carry-forward refresh (doctrines/carry-forward-refresh.md)

Read your full system prompt at ${CLAUDE_PLUGIN_ROOT}/agents/auditor.md for behavioral contract.

**Filing GH issues:** every HIGH/CRITICAL finding gets an issue created via `mcp__plugin_github_github__issue_write`. Include severity, location, recommendation, suggested hot-fix [FILE-SCOPE] + [ACCEPTANCE].
```

---

## `@worker` — bounded execution

```
You are @worker. Bounded task; report a summary; do not stream updates.

[ROLE] @worker — bounded task

[DELIVERABLE]
{one sentence: what is the output? a table? a report? a summary?}

[SOURCES]
- {where to read from}
- {which MCP queries / Bash commands / file paths}

[BUDGET]
- Time: {max minutes}
- Max tool calls: {N}

[FORMAT]
- {table | bullet list | under-N-words | path-to-file}

[OUT-OF-SCOPE]
- Do NOT modify any code, data, or config (unless deliverable IS .md).
- Do NOT dispatch other agents.
- Do NOT exceed the budget.

Read your full system prompt at ${CLAUDE_PLUGIN_ROOT}/agents/worker.md for behavioral contract.
```

---

## Audit-grade cutoffs (close-time)

The auditor swarm's collective grade for the sprint:

| Grade | Cutoff |
|---|---|
| A    | All gates green; SUBTRACT win; zero CRITICAL/HIGH findings; real-work delivered fully |
| A-   | Minor MEDIUM findings; SUBTRACT met; real-work delivered |
| B+   | Some MEDIUM findings; SUBTRACT met; real-work delivered substantially |
| B    | MEDIUM findings actionable; SUBTRACT met; real-work delivered |
| B-   | MEDIUM/HIGH findings; SUBTRACT borderline; real-work mostly delivered |
| C+   | **Cap** — failed real-work test OR SUBTRACT violation OR drift-risk silence (`doctrines/issue-ledger-awareness.md`) — none of the above can grade higher |
| C    | Multiple HIGH findings; substantive scope drift; SUBTRACT violation |
| D    | CRITICAL findings unaddressed; theme not delivered |
| F    | Sprint-fail — gates broken at HEAD; theme abandoned; operator escalation |

Per `doctrines/subtract-dont-add.md` and `doctrines/issue-ledger-awareness.md`, the C+ cap is structural — auditors cannot grade above it when the corresponding violations exist.

---

## Pattern B overlap dispatch (auditor + Wave N+1 coders, single batch)

After Wave N gates pass, dispatch IN ONE MESSAGE:

```
Agent({ description: "@auditor: Wave N / code-quality concern", model: "sonnet", prompt: "<auditor body + brief>" })
Agent({ description: "@auditor: Wave N / data-flow concern",     model: "sonnet", prompt: "<auditor body + brief>" })
Agent({ description: "@coder: Wave N+1 / lane A", model: "sonnet", prompt: "<coder body + brief>" })
Agent({ description: "@coder: Wave N+1 / lane B", model: "sonnet", prompt: "<coder body + brief>" })
```

Per `doctrines/pattern-b-overlap.md` — auditors run concurrently with the next coder wave. Findings land while the sprint is still hot-fixable.

---

## See also

- `pipeline.md` — Stage Graph node taxonomy (DEDUP-GATE, WAVE-IMPL, ...)
- `doctrines/stage-graph.md` — graph-as-dispatch-contract principle
- `doctrines/zero-duplicate-tolerance.md` — the conductor pre-dispatch dedup gate (this checklist's contract)
- `flock.md` — full per-agent dispatch reference + Required-Skills Matrix
- `seed-template.md` — what the engineer parses
- `branching-model.md` — branch lifecycle context
- `${CLAUDE_PLUGIN_ROOT}/agents/<role>.md` — agent system prompts (the source of truth)
- `doctrines/*.md` — framework-intrinsic rules cited throughout these briefs
