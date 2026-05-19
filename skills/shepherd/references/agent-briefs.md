# Agent Dispatch Brief Templates

Use these as starting points when dispatching flock agents from a `/shepherd:*` sprint. Fill in `{...}` placeholders. Project-specific values come from `shepherd.toml`.

---

## Conductor Brief-Validity Checklist (DEDUP-GATE node — run BEFORE every coder dispatch)

This checklist IS the runtime body of the `DEDUP-GATE` graph node (per `pipeline.md` §II + `doctrines/zero-duplicate-tolerance.md`). A coder brief is **invalid** unless every box below is checked. **The Agent batch does NOT fire until every box is green.** Skipping this checklist means you are gambling that the agent will invent what you forgot — which has produced documented duplicate-code drift across patches.

### Brief-shape checks
- [ ] All **seven** bracketed headers present verbatim — `[SKILLS]`, `[CONTEXT-INVENTORY]`, `[DO-NOT-DUPLICATE]`, `[USER-STYLE]`, `[FILE-SCOPE]`, `[NON-GOALS]`, `[ACCEPTANCE]`. Do NOT rename or paraphrase — the parser is strict.
- [ ] `[WORKTREE]` block present with `Path:`, `Branch:`, `Commit template:` lines.
- [ ] **`[BASE-COMMIT-EXPECTED]` block present** with the recorded SHA (the conductor runs `git rev-parse HEAD` on `{sprint_branch}` IMMEDIATELY before this dispatch and pastes the short SHA). Per `doctrines/conductor-cwd.md` companion contract — the coder rejects the worktree on mismatch.
- [ ] **`[SIBLING-LANES]` block present** (v5.0.9, `doctrines/flock-cohesion.md`) — every OTHER lane in this wave listed with its `[FILE-SCOPE]` summary + the symbols/artifacts it produces. Empty list (`- none — solo wave`) is acceptable for single-lane waves.
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
**Seed:** `{paths.plans}/{sprint_slug}.seed.md`
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
[ROLE] @coder — implementation lane for {sprint_branch}

Repo: {abs_path}, branch `{sprint_branch}`. Implementation task.
Commit template: fix(dev.{N}/{track}): {subject}
DO NOT run gates / build / test — main chat validates.
No new build-manifest dependencies without conductor approval.

**Mission:** {one-sentence goal}

**Seed + plan references:**
- `{paths.plans}/{patch_slug}.seed.md`        — patch-arc seed
- `{paths.plans}/{sprint_slug}.plan.md`        — this sprint's plan
- {any prior audit reports that inform this task}

# --- STABLE FRAMING BLOCK (cacheable prefix; reused across dispatches) ---
# Per doctrines/brief-cache-discipline.md — these sections come FIRST and
# are emitted verbatim across every dispatch in this sprint.

[SKILLS]
- code-style                          (mandatory per [skills.mandatory])
- {language-skill}                     (per [skills.by_domain] for this lane's primary language)
- {domain-skill 1}                     (per [skills.by_domain] for this lane's domain)
- {domain-skill 2}                     (if applicable)

[USER-STYLE]
- code-style

[DOCTRINES]
- doctrines/zero-duplicate-tolerance.md
- doctrines/agent-excellence.md
- doctrines/brief-cache-discipline.md
- {any project-doctrines from shepherd.toml [doctrines]}

[PROTOCOL-REMINDERS]
- Halt codes: DUPLICATION RISK, BASE-DRIFT, SCOPE OVERFLOW, PAUSE-FOR-DEPENDENCY
- Read agents/coder.md Step 0.5 before editing (verify [BASE-COMMIT-EXPECTED] SHA).
- Run agents/coder.md Step 3 (fallback dedup grep) before introducing any new symbol.

# --- VARIABLE CONTENT BLOCK (dispatch-specific; tail of brief) ---

[FILE-SCOPE]
MAY MODIFY:
- {path 1}
- {path 2}
MUST NOT TOUCH:
- {paths owned by other lanes in this wave}

[CONTEXT-INVENTORY]
# Every existing symbol the lane will reuse, with absolute path
- `{Symbol}` in `{abs path}::{module}` — {one-line description}
- ...

[DO-NOT-DUPLICATE]
# Language-specific greps that MUST return 0 hits before lane writes new code
- {grep pattern} → expected 0
- {grep pattern} → expected 0

[ACCEPTANCE]
# Runnable greps and structural assertions; NOT prose
- {grep} → {expected count}
- {gate command from [gates] passes — main chat runs}
- {file count delta verification}

[NON-GOALS]
- {scope items reserved for later sprints}
- {scope items reserved for other lanes}

[SIBLING-LANES]
# Read-only awareness (v5.0.9, flock-cohesion.md). The OTHER lanes firing in
# this same Agent batch. You may NOT modify their MAY-MODIFY paths. If you
# need a symbol they're producing, emit PAUSE-FOR-DEPENDENCY (do NOT silently
# wait or duplicate). If you see scope overlap, flag SCOPE OVERFLOW.
- {Lane B} (@{role}) — {file_scope summary}        — produces: {symbols/artifacts}
- {Lane C} (@{role}) — {file_scope summary}        — produces: {symbols/artifacts}
- ...

[WORKTREE]
- Path: {abs_worktree_path}                    (the conductor sets `isolation: "worktree"`; this is your home)
- Branch: {worktree_branch}                    (the agent's isolated branch — DO NOT push)
- Commit template: fix(dev.{N}/{track}): {subject}

[BASE-COMMIT-EXPECTED]
# The SHA the worktree was branched from. Coder MUST verify before any edits
# (per agents/coder.md Step 0.5). Mismatch ⇒ HALT with `BASE-DRIFT`.
- {sprint_branch} HEAD at dispatch: {short_sha}    (run `git rev-parse HEAD` in the worktree)
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

**Plan to review:** `{paths.plans}/{sprint_slug}.plan.md`
**Seed:** `{paths.plans}/{sprint_slug}.seed.md`
**Phase 0 mesh:** `{paths.reports}/<date>-{sprint_slug}-phase0.md`

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
**Plan:** `{paths.plans}/{sprint_slug}.plan.md`
**Phase 0 mesh:** `{paths.reports}/<date>-{sprint_slug}-phase0.md`
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

## Standard worker dispatches (Wave 1 START — fire in parallel with Wave 1 coders)

These four worker patterns are general enough to be useful in almost every sprint. Dispatch them in the SAME batch as Wave 1 coders (per `flock.md §V.8` — workers are IO-bound and non-competing). Each brief follows the `@worker` contract from `agents/worker.md`.

### W-A — Workspace test-surface audit

Classifies all test files in the workspace into four buckets: `refreshed-this-sprint` (tests that touch lane-modified files), `stale` (tests for files untouched this sprint), `dead` (tests for deleted or unreachable code), `unaffected` (standard library / vendored tests that don't need attention). Useful for any sprint that touches > 3 files.

```
You are @worker. Bounded task; report a summary; do not stream updates.

[ROLE] @worker — W-A workspace test-surface audit

[DELIVERABLE]
Classify every test file in the workspace into: refreshed-this-sprint
(tests co-located with or covering files in {wave-1-file-scope-list}),
stale (tests for untouched files), dead (tests for deleted/unreachable
code), unaffected (vendored / stdlib). Report as a table.

[SOURCES]
- git diff {patch_branch}..HEAD --name-only (modified files this sprint)
- rg "#\[cfg(test)\]|#\[test\]|def test_|def Test|it\(" --files-with-matches
- git ls-files "*test*" "*spec*" "*bench*"

[BUDGET]
- Time: 10 min
- Max tool calls: 30

[FORMAT]
Markdown table: file | bucket | coverage_of | note
Write to {paths.reports}/{date}-w-a-test-surface.md

[OUT-OF-SCOPE]
- Do NOT modify any code, data, or config.
- Do NOT run tests.
- Do NOT dispatch other agents.
```

### W-B — Phase 0 mesh validation (MCP / CLI queries)

Runs the heavy MCP and CLI queries the engineer couldn't do inline (large issue lists, deploy status, error monitoring). Returns receipts the engineer can reference in the plan. Useful in any sprint where the mesh surfaces are available (`[mcp]` + `[cli]` flags set).

```
You are @worker. Bounded task; report a summary; do not stream updates.

[ROLE] @worker — W-B Phase 0 mesh validation

[DELIVERABLE]
Query the configured mesh surfaces and return structured receipts:
GH open-issue count by milestone; Sentry error count last 48h;
deploy status; last 5 PRs merged.

[SOURCES]
- mcp__plugin_github_github__list_issues (state=open, per_page=100)
- mcp__plugin_sentry_sentry__search_events (last 48h) [if available]
- fly status --app {project-name} [if available]
- mcp__plugin_github_github__list_pull_requests (state=merged, per_page=5)

[BUDGET]
- Time: 15 min
- Max tool calls: 20

[FORMAT]
Markdown table + summary paragraph. Write to
{paths.reports}/{date}-w-b-mesh-validation.md

[OUT-OF-SCOPE]
- Do NOT modify any code, data, or config.
- Do NOT dispatch other agents.
```

### W-D — Bulk GH issue triage + close script

Walks every open GH issue, classifies each into `{blocking, closeable-now, tracking-future, non-issue}`, and writes a one-line closure rationale for every `closeable-now` issue. Generates a shell script the conductor reviews and runs to bulk-close stale issues. Useful at every sprint — issue ledgers accumulate "fixed but never closed" debt continuously.

```
You are @worker. Bounded task; report a summary; do not stream updates.

[ROLE] @worker — W-D bulk GH issue triage

[DELIVERABLE]
Classify every open GH issue into: blocking-this-sprint (needs a coder
lane), closeable-now (already addressed; just needs close), tracking-future
(milestone out; keep open), non-issue (wontfix/rfc/design-question label).
For every closeable-now issue, write a one-line closure rationale.
Produce a shell script at {paths.reports}/{date}-w-d-bulk-close.sh that
bulk-closes the closeable-now set.

[SOURCES]
- mcp__plugin_github_github__list_issues (state=open, per_page=500)
- mcp__plugin_github_github__issue_read (per issue for ambiguous ones)
- git log {patch_branch}..HEAD --oneline (to verify "fixed in current sprint")

[BUDGET]
- Time: 20 min
- Max tool calls: 60

[FORMAT]
Markdown table + the .sh script. The script uses `gh issue close <N> --comment "<rationale>"`.
Operator reviews + runs the script; worker does NOT close issues directly.

[OUT-OF-SCOPE]
- Do NOT close GH issues directly (produce the script only).
- Do NOT modify any code, data, or config.
- Do NOT dispatch other agents.
```

### W-E — Production diagnostic (on mesh-drift or operator regression amendment)

Dispatched when Phase 0 mesh OR a mid-flight operator amendment reveals a production regression. Enumerates exact failure signals per symptom, cross-references Sentry and deploy logs, and proposes targeted HF coder briefs the conductor can fire. See `doctrines/mid-flight-operator-amendment.md §II Production regression` for the amendment protocol.

```
You are @worker. Bounded task; report a summary; do not stream updates.

[ROLE] @worker — W-E production diagnostic

[DELIVERABLE]
For each regression symptom listed in [SOURCES.issues], enumerate:
(a) exact error messages from Sentry / deploy logs (cite timestamps + counts),
(b) the probable root cause,
(c) a proposed targeted HF coder brief ([FILE-SCOPE] + [ACCEPTANCE]) to fix it.
Return a structured report the conductor uses to dispatch HF coders.

[SOURCES]
- GH issues: {list of P0/P1 issue numbers from the operator amendment}
- mcp__plugin_sentry_sentry__search_events (last 4h per symptom keyword)
- mcp__plugin_sentry_sentry__search_issues
- fly logs --app {project-name} -n 100
- mcp__plugin_supabase_supabase__get_logs [if relevant]

[BUDGET]
- Time: 15 min
- Max tool calls: 40

[FORMAT]
Markdown report: one section per issue. Include: symptom | error excerpt |
probable cause | proposed HF scope.
Write to {paths.reports}/{date}-w-e-prod-diagnostic.md

[OUT-OF-SCOPE]
- Do NOT modify any code, data, or config.
- Do NOT close GH issues.
- Do NOT dispatch other agents.
```

---

## `@discovery` — read-only orientation / research (v5.1.1+)

Discovery briefs are short and tight. Every brief carries six bracketed
sections; missing any one halts the agent at Step 0.

### Generic skeleton

```
You are @discovery. Read-only orientation. Report-only output.

[ROLE]               @discovery — read-only orientation

[QUESTION]
{one sentence — the exact question you want answered}

[SOURCES]
- {file or dir path}
- {MCP query}
- {web URL}

[OUTPUT-PATH]        {paths.reports}/{date}-discovery-{id}.md

[BUDGET]
- Time: {N} min
- Max tool calls: {N}

[FORMAT]
Markdown report. Required sections: ## Sources, ## Findings, ## Open questions, ## Confidence.

[NON-GOALS]
- Do NOT propose code changes; surface facts, not recommendations.
- Do NOT dispatch other agents.
- Do NOT Write outside [OUTPUT-PATH].
- Do NOT run state-modifying Bash (rm, mv, >, >>, tee, gh issue create, etc.).
```

### D-A — PRE-MESH-DISCOVERY: prior-close-audit-summary

Fires in INTRO-COMBO-WAVE before engineer MESH.

```
[ROLE] @discovery — D-A prior-close-audit-summary

[QUESTION]
What HIGH/CRITICAL findings from the prior sprint's close-time audit are still
open at HEAD? For each, surface: severity, location, GH issue (if filed),
recommended disposition (resolved / carry-forward / drift).

[SOURCES]
- {paths.reports}/*-{prior_sprint_slug}-close.md
- {paths.reports}/*-audit-*.md  (close-time audit reports, prior sprint)
- mcp__plugin_github_github__list_issues (state: open, milestone: current)
- git log {prior_sprint_branch}..HEAD --oneline

[OUTPUT-PATH] {paths.reports}/{date}-discovery-prior-close-audit-summary.md

[BUDGET]
- Time: 8 min
- Max tool calls: 25

[FORMAT]
Markdown report. ## Findings table: severity | location | GH# | recommended disposition.
```

### D-B — PRE-MESH-DISCOVERY: canonical-types-freshness

```
[ROLE] @discovery — D-B canonical-types-freshness

[QUESTION]
Is {paths.ctx}/canonical-types.md fresh for this sprint's mesh? Report:
last refresh date, age in days, drift since last refresh (new pub symbols
not yet in the index), and whether the dev.0 CANONICAL-TYPES-REFRESH worker
needs to fire this sprint.

[SOURCES]
- {paths.ctx}/canonical-types.md (mtime + content)
- git log --since="{N} days ago" --name-only -- 'crates/**/*.rs' (or project equivalent)
- rg "pub (fn|struct|trait|enum|type|const) " --type rust  (or project language)

[OUTPUT-PATH] {paths.reports}/{date}-discovery-canonical-types-freshness.md

[BUDGET]
- Time: 5 min
- Max tool calls: 15

[FORMAT]
Markdown. ## Findings: freshness verdict (FRESH / STALE / MISSING), drift
count, recommended action.
```

### D-C — PRE-MESH-DISCOVERY: gh-state-inventory

```
[ROLE] @discovery — D-C gh-state-inventory

[QUESTION]
Classify every open GH issue into ledger buckets:
{drift-risk, current-milestone, non-issue, tracking-future, chronic}.
Surface counts + a flat list of HIGH/CRITICAL items not on current milestone.

[SOURCES]
- mcp__plugin_github_github__list_issues (state: open, per_page: 500)
- mcp__plugin_github_github__list_milestones (state: open)
- {ledger.non_issue_labels} from shepherd.toml

[OUTPUT-PATH] {paths.reports}/{date}-discovery-gh-state-inventory.md

[BUDGET]
- Time: 10 min
- Max tool calls: 30

[FORMAT]
Markdown. ## Findings: bucket counts table + drift-risk table (severity | # | title).
```

### D-D — PRE-HOTFIX-DISCOVERY: error-cluster

Fires when WAVE-N-GATE returns on-fail; conductor uses output to shape
HOTFIX-DYNAMIC dispatch.

```
[ROLE] @discovery — D-D pre-hotfix error-cluster

[QUESTION]
Cluster the gate errors in .shepherd/runs/w{N}-gate.json by file-disjoint
scope. For each cluster, report: files involved, error lines (sample),
proposed [FILE-SCOPE], proposed [ACCEPTANCE] grep.

[SOURCES]
- .shepherd/runs/w{N}-gate.json (or w{N}-gate.txt)
- {paths.plans}/{sprint_slug}.plan.md (for original [FILE-SCOPE] context)

[OUTPUT-PATH] {paths.reports}/{date}-discovery-w{N}-hf-clusters.md

[BUDGET]
- Time: 5 min
- Max tool calls: 15

[FORMAT]
Markdown. ## Findings: cluster table (cluster_id | files | err_count | proposed
HF brief stub). Each cluster becomes one HOTFIX-DYNAMIC coder lane.
```

### D-E — ARCHITECTURE-DISCOVERY

For mid-session re-orientation. The conductor joins a sprint mid-flight.

```
[ROLE] @discovery — D-E architecture-orientation

[QUESTION]
The conductor needs to re-orient on sprint {sprint_branch}. Synthesize:
current Stage Graph position, recent commits (last 20), hot files (most-
edited in last 5 days), open dispatches (if any), pending PAUSE records.

[SOURCES]
- {paths.plans}/{sprint_slug}.plan.md (Stage Graph section)
- {paths.reports}/*-{sprint_slug}-walk.md (if exists)
- git log -20 --stat
- ls .shepherd/pauses/ (or .artifacts/pauses/)
- ls .shepherd/dispatch/{sprint_branch}/ (or .artifacts equivalent)

[OUTPUT-PATH] {paths.reports}/{date}-discovery-architecture-orientation.md

[BUDGET]
- Time: 8 min
- Max tool calls: 20

[FORMAT]
Markdown. ## Findings: where-are-we summary + next-eligible-node + open
dispatches table.
```

### D-F — DOCTRINE-RECONCILIATION-DISCOVERY

```
[ROLE] @discovery — D-F doctrine-reconciliation

[QUESTION]
Does this codebase adhere to {doctrine name}? Walk the doctrine's rules,
grep the codebase, report adherence per rule.

[SOURCES]
- ${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/{doctrine-slug}.md
- Codebase (project-specific paths)

[OUTPUT-PATH] {paths.reports}/{date}-discovery-doctrine-{slug}-adherence.md

[BUDGET]
- Time: 10 min
- Max tool calls: 30

[FORMAT]
Markdown. ## Findings: per-rule adherence table (rule | adheres? | evidence | gaps).
```

### D-G — MCP-STATE-DISCOVERY

```
[ROLE] @discovery — D-G mcp-state

[QUESTION]
Consolidate the current state of every MCP surface advertised in
shepherd.toml [mcp] into one report. For each (github / sentry / supabase):
recent activity counts, advisor warnings (if any), and any anomalies
worth surfacing to the engineer.

[SOURCES]
- mcp__plugin_github_github__list_issues (state: open, recent)
- mcp__plugin_github_github__list_pull_requests (state: open)
- mcp__plugin_sentry_sentry__find_issues (recent)
- mcp__plugin_supabase_supabase__get_advisors

[OUTPUT-PATH] {paths.reports}/{date}-discovery-mcp-state.md

[BUDGET]
- Time: 8 min
- Max tool calls: 20

[FORMAT]
Markdown. ## Findings: per-surface section (github, sentry, supabase, ...)
with counts table + anomaly list.
```

### D-H — RESEARCH-SUMMARY-DISCOVERY

```
[ROLE] @discovery — D-H research-summary

[QUESTION]
{Specific external research question — e.g., "What is the current best-
practice for X in the {library Y} ecosystem as of 2026-05?"}

[SOURCES]
- WebFetch / WebSearch for authoritative sources
- {paths.docs}/{any prior research doc on this topic}
- ToolSearch + Skill (load context7-mcp if library docs needed)

[OUTPUT-PATH] {paths.reports}/{date}-discovery-research-{topic-slug}.md

[BUDGET]
- Time: 12 min
- Max tool calls: 25

[FORMAT]
Markdown. ## Findings: cited summary with [source: URL] footnotes;
## Open questions for anything sources didn't authoritatively resolve.

[NON-GOALS]
- Do NOT recommend a specific implementation — surface options + tradeoffs.
- Do NOT cite single-source claims as authoritative.
```

### Intro-mode auditor briefs (v5.1.1+ — pair with intro discoveries in INTRO-COMBO-WAVE)

```
[ROLE] @auditor (intro mode)

[CONCERN] regression
[MODE] regression

[PRIOR-SPRINT-PLAN]   {paths.plans}/{prior_sprint_slug}.plan.md
[PRIOR-SPRINT-CLOSE]  {paths.reports}/*-{prior_sprint_slug}-close.md
[OUTPUT-PATH]         {paths.reports}/{date}-intro-audit-regression.md
[SPRINT-ROOT]         {abs path}
[SPRINT-BRANCH]       {sprint_branch}

[INSTRUCTIONS]
- Load superpowers:systematic-debugging on entry.
- Read every coder lane's [ACCEPTANCE] block in the prior plan.
- Re-run each runnable grep / structural assertion at the current HEAD.
- File findings per the v5.1.1 Hypothesis + Falsification + Confidence
  contract. No grade — this is intro mode.
- Cap LOW findings (surface under ## Open questions instead).
```

```
[ROLE] @auditor (intro mode)

[CONCERN] carry-forward-disposition
[MODE] carry-forward-disposition

[CARRY-FORWARD-LEDGER]  {paths.ctx}/carry-forward.md  (or [ledger].carry_forward_file)
[OUTPUT-PATH]           {paths.reports}/{date}-intro-audit-carry-forward.md
[SPRINT-ROOT]           {abs path}
[SPRINT-BRANCH]         {sprint_branch}

[INSTRUCTIONS]
- Load superpowers:systematic-debugging on entry.
- For every ledger entry, verify GH issue state + label correctness +
  sprint-target sanity.
- File findings per the v5.1.1 contract. No grade.
- Apply chronic label per [ledger.chronic_threshold_patches] rule.
```

---

## INTRO-COMBO-WAVE dispatch (one Agent batch, sprint open)

After SEED-VERIFY (and before MESH), the conductor dispatches the wave in
ONE message:

```
Agent({ description: "@discovery: D-A prior-close-audit-summary", model: "sonnet", prompt: "<discovery body + D-A brief>" })
Agent({ description: "@discovery: D-B canonical-types-freshness",  model: "sonnet", prompt: "<discovery body + D-B brief>" })
Agent({ description: "@discovery: D-C gh-state-inventory",         model: "sonnet", prompt: "<discovery body + D-C brief>" })
Agent({ description: "@auditor: regression (intro mode)",          model: "sonnet", prompt: "<auditor body + intro-regression brief>" })
Agent({ description: "@auditor: carry-forward-disposition (intro)", model: "sonnet", prompt: "<auditor body + intro-cfd brief>" })
```

When all five return, the conductor consolidates outputs into
`[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` blocks for the engineer's
MESH brief. Per `doctrines/intro-combo-wave.md`.

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
