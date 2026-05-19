---
name: spawn
description: |
  Spawn a teammate-conductor to run a sprint while main chat stays lean as the
  planter/babysitter. Requires the Agent Teams feature (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true,
  Claude Code ≥ v2.1.32, teammateMode configured). Main chat adopts the planter profile;
  the teammate's first action is /shepherd:start against the active sprint scope.

  Two flags extend the base behavior:
    --parallel <N>  Fan out N sibling teammates inside the lead's single team. Each
                    teammate runs one sprint in its own worktree. Planter pre-checks
                    scope for file-disjoint collision before any spawn fires. Escalations
                    are multiplexed; planter triages by teammate_name. Merges are
                    dev-order gated (predecessor merged before successor).
    --auto          Sequential autopilot. Planter spawns one teammate per sprint, does
                    inter-sprint cleanup + git + handoff between spawns, then spawns the
                    next. Each sprint gets a fresh context window. Loop terminates at
                    last dev, operator interrupt, grade floor, or error budget exhaustion.
argument-hint: "[ sprint_slug ] [ --parallel <N> | --auto ]   defaults to next unstarted dev.N"
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
---

# /shepherd:spawn — Teammate-Conductor Dispatch

Spawn a teammate session to run a full sprint pipeline while this main-chat session
stays lean as the ambient planter and babysitter. The teammate boots with the conductor
profile pre-loaded, invokes `/shepherd:start` against the inherited sprint scope, and
surfaces hard stops back to you through a structured escalation channel. Main chat
monitors heartbeats, responds to escalations, owns all git operations, and executes
the post-sprint merge sequence.

> **Mechanical contract** — file paths, polling cadence, hook events, lock semantics,
> multiplex triage, halt-code → action map, heartbeat format — lives in
> `skills/shepherd/doctrines/spawn-escalation.md`. This command does NOT re-state those
> mechanics; it cites the doctrine and stays focused on the operator-visible contract.

---

## § Smooth path (happy-path walkthrough)

A single-sprint spawn on a green project, no flags, no escalations:

```
[1] operator types:  /shepherd:spawn
[2] preflight        Check 1 (feature flag)         → OK
                     Check 2 (Claude ≥ v2.1.32)     → OK
                     Check 3 (no active team)       → OK
                     Check 4 (shepherd.toml)        → OK
                     (Check 5 skipped — no --parallel / --auto)
[3] main chat        adopts planter profile (agents/planter.md, spawn mode)
[4] main chat        builds teammate boot prompt (seed + handoff + carry-forwards
                     + shepherd.toml snapshot)
[5] main chat        calls Agent(subagent_type, prompt) → teammate session created
[6] teammate         loads agents/conductor.md, fires /shepherd:start
[7] teammate         walks Stage Graph (§1 INTRO → §2 BODY → §3 CLOSE)
[8] teammate         at each wave boundary: SendMessage(to: lead, halt_code: null)
                     → planter commits the wave via TaskCompleted hook
[9] teammate         at CLOSE-FINALIZE: emits CONDUCTOR CLOSE REPORT, idles
[10] planter         verifies close report → rebase-merge → cuts next dev branch
                     → updates carry-forward ledger → runs cleanup stewardship
[11] planter         emits PLANTER REPORT and hands back to the operator
```

For `--parallel <N>` the smooth path forks at [5]: N teammates spawn into N
worktrees after a collision pre-check; planter babysits all N in parallel;
merges land in dev-order. For `--auto` the loop wraps [4]–[10] per sprint with
planter-authored inter-sprint handoffs between iterations.

Escalations interrupt this path — consult `skills/shepherd/doctrines/spawn-escalation.md`
for the full halt → resume contract.

---

## § Platform compatibility

**Status (2026-05-19):** The conductor-as-teammate path is fully functional in
**tmux** `teammateMode` today. **In-process** mode is partially limited by
[Claude Code issue #31977](https://github.com/anthropics/claude-code/issues/31977)
— teammate sessions in in-process mode do not expose the `Agent` tool, so a spawned
teammate's `/shepherd:start` cannot dispatch the flock the same way main chat can.

| `teammateMode` setting | Conductor-as-teammate | Flock dispatch inside teammate |
|---|---|---|
| `tmux`        | Works today | Available |
| `in-process`  | Degraded    | Blocked on #31977 |

**Forward-compat:** this command and the `conductor` + `planter` profiles are designed
for the eventual state (full Agent-tool parity across modes). When #31977 fixes, no
spawn-side redesign is required.

**Recommendation while #31977 is open:** use `tmux` for live spawn workflows that
exercise the full flock. In `in-process` mode, prefer `/shepherd:start` in main chat
until the bug lands.

Preflight detects the feature flag but does NOT gate on `teammateMode` — operator is
expected to know which mode they configured.

---

## § Preflight

Run every check before calling `Agent`. Refuse with a clear error if any check fails.

### Check 1 — Agent Teams feature flag

```bash
echo "${CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS}"
```

Must be `"true"` (the platform also accepts `"1"`; shepherd normalises to `"true"`
per D-API §1). Empty or any other value → refuse:

```
/shepherd:spawn — REFUSED: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS is not set or not "true".

To enable Agent Teams:
  1. Add  CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true  to ~/.claude/.env
  2. Or add it under env.* in ~/.claude/settings.json
  3. Restart Claude Code and re-invoke /shepherd:spawn

Reference: docs/configuration.md §Agent Teams
D-API source: .artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md §1
```

### Check 2 — Claude Code minimum version

```bash
claude --version
```

Below v2.1.32 (the version that introduced Agent Teams per D-API §3) → refuse with
the detected version and `claude update` instruction. `TeammateIdle`, `TaskCreated`,
`TaskCompleted` arrived in v2.1.33 and are required for the wave-boundary commit
discipline. Operator is on v2.1.144 — this check is a portability guard.

### Check 3 — No active team (one-team-per-lead limit)

```bash
ls ~/.claude/teams/ 2>/dev/null
```

If non-empty with a `config.json` carrying `members[]`, an active team is already
running. Per D-API §11: a lead can only manage one team at a time. Refuse and direct
the operator to either complete the prior sprint's hand-back, or inspect
`~/.claude/teams/` and clear stale config after confirmation.

### Check 4 — shepherd.toml (warn-only)

```bash
ls .claude/shepherd.toml 2>/dev/null || ls .local.toml 2>/dev/null
```

If missing, emit `[WARN]` and proceed with framework defaults from
`${CLAUDE_PLUGIN_ROOT}/docs/configuration.md`. Recommend copying
`examples/minimal/shepherd.toml`. Non-blocking.

### Check 5 — Flag-specific preflight

**For `--parallel <N>`:**

1. **Collision pre-check (HARD-STOP).** Read `file_scope.exclusive` from each of N
   seeds. Any path claimed by >1 sprint is a collision. Also flag shared build-manifest
   paths (`Cargo.toml`, `package.json`, `pyproject.toml`, `go.mod`, `*.lock`, `*.sum`,
   `build.gradle`, or anything in `[project].build_manifest_paths`). Surface ALL
   collisions in one block:
   ```
   [COLLISION REPORT]
   path: src/foo/bar.rs
     claimed by: v515-dev1 (exclusive), v515-dev2 (exclusive)

   Re-scope the colliding seeds before retrying /shepherd:spawn --parallel.
   ```
   Operator must amend the seeds; planter does not auto-resolve.
2. **N within bounds (HARD-STOP).** N must be 2–4. N=1 is just base spawn; N>4
   saturates the lead's `TeammateIdle` handler.
3. **N seeds available.** Exactly N `{paths.plans}/{sprint_slug}.seed.md` files
   must exist. Missing → hard stop; operator runs `/shepherd:plant` for the gap.
4. **No dev-order cycle.** If `sprint_dependencies` contains a cycle, the merge
   gate would deadlock — refuse.

**For `--auto`:**

1. **Patch boundary detection (HARD-STOP).** Read `shepherd.toml [branching]` to
   enumerate dev.N branches. Identify `dev.LAST` (precedence: `[version].dev_total`
   → seed count → operator prompt). If undeterminable, prompt:
   ```
   [PROMPT] /shepherd:spawn --auto: Cannot determine the last dev sprint.
   How many dev sprints does this patch contain? (current: dev.{N})
   ```
   Operator input is mandatory before the loop begins.
2. **Min-grade configured.** `[autorun].min_grade` must be set in `shepherd.toml`.
   If absent, default to `B` and warn.

---

## § Adopt the planter profile

Main chat (this session) becomes the ambient planter/babysitter for the lifetime of
the teammate's run.

1. Read `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` (full file).
2. Confirm mode: **spawn** (not plant). Primary activity = ambient read + escalation
   response. Git custody = full. Session ends only after the hand-back sequence in
   `agents/planter.md §Babysitter mode §5` completes.

If `agents/planter.md` is already loaded (e.g., operator ran `/shepherd:plant`
earlier), skip the re-read.

> `agents/planter.md` frontmatter pins model `opus[1m]`. If this session is Sonnet
> and the operator intends a long babysit, recommend switching to Opus now.
> Non-blocking; quality of escalation triage degrades on Sonnet.

---

## § Build the teammate prompt

Construct the teammate's boot prompt before calling `Agent`. The prompt carries all
inherited context the teammate needs without re-asking main chat.

### Required context block

```
You are a spawned teammate-conductor for the shepherd framework.

Your main chat (the lead session) is your planter and babysitter. It watches your
escalations, owns all git operations, and will execute the post-sprint merge sequence.

IDENTITY
  Role: conductor (sprint runner)
  Profile: ${CLAUDE_PLUGIN_ROOT}/agents/conductor.md  (load immediately)
  Escalation channel: skills/shepherd/doctrines/spawn-escalation.md

INHERITED CONTEXT
  CLAUDE.md path:          {project_claude_md_path}
  Active seed path:        {paths.plans}/{sprint_slug}.seed.md
  Prior close handoff:     {paths.docs}/{prior_handoff_filename}
  Carry-forward GH issues: {comma-separated #NNN from handoff}
  shepherd.toml snapshot:  inline below

--- shepherd.toml snapshot ---
{paste full .claude/shepherd.toml content here}
--- end snapshot ---

FIRST ACTION
  Invoke /shepherd:start. Do not wait for further instructions.

ESCALATION RULES — summary; full contract at spawn-escalation doctrine
  On any Halt code from agents/conductor.md §Halt codes:
    1. Stop the walk at the current node.
    2. Write the escalation payload to
         .artifacts/escalations/{sprint_slug}/{ISO-timestamp}-{role}.md
       (schema in spawn-escalation §III).
    3. Call SendMessage(to: lead) with the same payload.
    4. Do NOT proceed until you receive a resume reply.
    5. Heartbeat: emit a status row at every phase boundary.

HARD PROHIBITIONS WHILE SPAWNED
  - NO git commit / push / branch -d / rebase. Git is the planter's exclusive
    domain. See agents/conductor.md §Side-effect boundary + Hard prohibition #12.
  - NO acquiring or releasing .artifacts/shepherd.lock.
  - NO spawning your own teammates (platform forbids nested teams).
  - NO pushing to any remote branch not owned by the active sprint.

WAVE-BOUNDARY COMMIT PROTOCOL
  At each wave completion:
    1. SendMessage(to: lead) wave-complete payload:
         {phase: "body-wave-N", halt_code: null, blocking: false,
          context_files: ["<wave-gate-output-path>"]}
    2. TaskCompleted fires automatically on wave-scope task completion.
  Planter commits your wave on TaskCompleted (spawn-escalation §VI).

TEAMMATE IDENTITY
  Name: shepherd-conductor-{sprint_slug}
  Session transcript: ~/.claude/projects/<project-path>/<session-uuid>.jsonl
```

### Dynamic field resolution

| Token | Source |
|---|---|
| `{project_claude_md_path}` | `pwd`/CLAUDE.md (absolute) |
| `{paths.plans}/{sprint_slug}.seed.md` | `shepherd.toml [paths]` + sprint detect |
| `{paths.docs}/{prior_handoff_filename}` | `ls -t {paths.docs}/*-close-handoff.md \| head -1` |
| `{carry-forward GH issues}` | handoff doc's carry-forward section |
| `shepherd.toml snapshot` | full contents of `.claude/shepherd.toml` |
| `{sprint_slug}` | `shepherd.toml [branching].sprint_branch_pattern` + current dev.N |

---

## § Spawn dispatch

The lead session calls `Agent` (or `Task`) to create the teammate:

```
Agent({
  subagent_type: "claude-sonnet-4-5",   // or operator-specified; see OQ-1
  prompt: <the teammate prompt from § Build the teammate prompt>,
  // Name is encoded in the prompt body under IDENTITY.Name.
  // No per-teammate config files are supported at spawn time (D-API §9).
})
```

> **D-API source**: §5 (spawn lifecycle), §6 (dispatch shape): the lead calls
> `Agent({ subagent_type, prompt })`, which always creates a new session.
> Internally the lead uses `SendMessage` to talk to running teammates and `Agent`/
> `Task` to spawn new ones. §9: no per-teammate config beyond team config;
> teammates inherit the lead's permission mode.

Names are assigned at spawn via `~/.claude/teams/{team-name}/config.json` — written
and owned by the runtime; do NOT pre-author or edit it. Hook routing keys off the
predictable `shepherd-conductor-{sprint_slug}` prefix.

### Post-spawn confirmation

```
[SPAWN] teammate shepherd-conductor-{sprint_slug} dispatched.
        Team config: ~/.claude/teams/shepherd-conductor-{sprint_slug}/config.json
        Teammate transcript: ~/.claude/projects/<project>/<session-uuid>.jsonl
        Babysitter mode: active. Monitoring TeammateIdle + TaskCompleted hooks.
        Heartbeat threshold: 5 min. Alert on staleness.
        Sprint: {sprint_slug}
```

---

## § Teammate tool feed

The teammate-conductor needs a specific tool surface to walk the Stage Graph. The planter is responsible for ensuring it gets fed correctly.

### What the teammate inherits

Per D-API §9, **the teammate inherits the lead session's permission mode** — but tool *availability* is a separate axis. In tmux `teammateMode`, the teammate boots as a full Claude Code session with the default tool set plus any plugin-registered tools the lead has access to. The conductor profile's `tools:` frontmatter at `agents/conductor.md` is the canonical capability list; the lead must ensure each tool in that list is registered in its session before spawning.

### Required tools for a teammate-conductor

| Tool | Why the conductor needs it |
|---|---|
| `Agent` | Dispatch flock lanes (engineer, critic, coder, auditor, worker, discovery). Without this the teammate cannot walk the Stage Graph. |
| `Bash`, `Edit`, `Read`, `Write`, `Glob`, `Grep` | Plan / report / handoff authoring, gate execution at WAVE-GATE, brief assembly. |
| `Skill` | Load `code-style:<lang>`, language-mastery, doctrine skills. |
| `ToolSearch` | Discover specialist agents at runtime per `doctrines/specialist-dispatch.md`. |
| `SendMessage` | Escalation channel back to planter per `spawn-escalation.md §V`. |
| `Task*` | Track in-flight wave state. |
| `WebFetch`, `WebSearch` | Doctrine cross-reference, dependency docs. |
| `mcp__plugin_github_github__*` (read-only set) | Issue ledger, PR / commit awareness for Phase 0 mesh. |
| `mcp__plugin_sentry_sentry__search_*` | Error-monitoring discovery during INTRO-COMBO-WAVE. |
| `mcp__plugin_supabase_supabase__{execute_sql,list_*,get_advisors}` | Datastore-state audit concern. |

### Planter pre-spawn tool check

Before calling `Agent({ subagent_type, prompt })`, the planter SHOULD verify:

1. The `Agent` tool is registered in the lead session. If not (e.g. plugin not loaded), HALT with:
   ```
   /shepherd:spawn — REFUSED: Agent tool not registered in lead session.
   The teammate-conductor needs Agent tool inheritance to dispatch the flock.
   Run /reload-plugins, verify, and re-invoke.
   ```
2. The MCP servers referenced in `agents/conductor.md tools:` are connected (use `/mcp` or `ListMcpResourcesTool`). If a server is missing, the conductor will degrade per `doctrines/plugin-reload-escape.md` — surface a `[WARN]` line at spawn time so the operator knows.
3. The conductor's profile path is readable: `ls ${CLAUDE_PLUGIN_ROOT}/agents/conductor.md`.

### What the teammate does NOT inherit

- **Conversation history.** The teammate boots fresh. Inject all needed context via the boot prompt (per § Build the teammate prompt).
- **Open file context** the lead had loaded. The teammate must `Read` files it needs.
- **Permission grants** beyond the default permission mode. Auto-approved tool calls in the lead don't carry over.
- **Task list.** The teammate creates its own via `TaskCreate`.

### In-process mode caveat

Per § Platform compatibility above, **in-process `teammateMode` currently does not expose `Agent` tool to teammates** (issue #31977). The pre-spawn tool check #1 above is the early-stop for this case. Recommend tmux mode until #31977 ships.

---

## § --parallel flag

`/shepherd:spawn --parallel <N>` fans out N sibling teammates inside the lead's
single team. N is 2–4 (preflight Check 5). Each teammate runs one sprint end-to-end
via `/shepherd:start`. Planter babysits all N concurrently.

Base spawn behavior (§ Adopt the planter profile, § Build the teammate prompt,
§ Spawn dispatch) applies per teammate. Incremental behaviors below; full triage
and resume mechanics in `skills/shepherd/doctrines/spawn-escalation.md §X`.

### Worktree-per-teammate setup

Each teammate runs in its own git worktree for filesystem isolation:

```bash
# For each teammate i in 1..N:
git worktree add .worktrees/{sprint_slug_i} {sprint_branch_i}
```

Include the absolute worktree path in each teammate's INHERITED CONTEXT block:
```
WORKTREE PATH:  {abs_path}/.worktrees/{sprint_slug}
All file reads and writes MUST use this path as the working root.
```

Planter removes each worktree as its teammate's sprint closes (see § Cleanup below).

### Teammate naming convention

`shepherd-parallel-{sprint_slug}` (distinguishes from single-spawn
`shepherd-conductor-{sprint_slug}`). The `TeammateIdle` hook routes by
`teammate_name`; the `shepherd-parallel-` prefix is the routing key.

### Multiplexed escalation + dev-order merge gate

With N teammates active, escalations arrive concurrently. The triage protocol
(CRITICAL preemption, FIFO same-level, mid-triage suspension, status board,
cross-teammate dependency halts via `CROSS-DEP-WAIT`, PARALLEL-COLLISION response)
is fully specified at `skills/shepherd/doctrines/spawn-escalation.md §X`. Planter-side
implementation lives at `agents/planter.md §Multi-teammate triage (--parallel mode)`.

Dev-order merge gate: sprint dev.N+1 may NOT be merged to the patch branch until
dev.N's PR is merged — even if dev.N+1 closes first. Detection, hold, and release
are pinned at `agents/planter.md §Multi-teammate triage > Dev-order merge gate
enforcement`.

### Cleanup at each teammate close

When a teammate's sprint closes:

1. Verify close report (per base hand-back checklist).
2. Apply merge gate. If held → write pending-merge marker, skip merge.
3. If not held → rebase-merge dev.N onto patch branch.
4. `git worktree remove --force .worktrees/{sprint_slug}` (only when branch is
   already merged).
5. Update the multiplexed status board (mark CLOSED).
6. Update the carry-forward ledger for this sprint.
7. **Do NOT run full cleanup stewardship** (agent-* branches, shepherd.lock) until
   ALL N teammates have closed. Full cleanup is end-of-run only.

### Hard stops specific to --parallel

In addition to base hard stops:

- **Collision detected after spawn** — `PARALLEL-COLLISION`; pause all affected
  teammates before addressing. Resolution flow in `spawn-escalation.md §X`.
- **>1 simultaneous CRITICAL halt** — operator priority required:
  ```
  [HARD STOP] Multiple simultaneous CRITICAL halts detected.
  Teammates in CRITICAL state: {list}.
  Presenting all CRITICAL payloads now.
  ```
- **Teammate count drops to 0** — unrecoverable without operator input; stall alert.
- **Dev-order cycle** — refused at Check 5; cycles deadlock the merge gate.

---

## § --auto flag

`/shepherd:spawn --auto` runs a sequential autopilot loop. Planter spawns one
teammate per sprint, waits for close, does all inter-sprint work, then spawns the
next — until the patch is exhausted or a termination condition fires.

**Core win**: each sprint gets a fresh context window. Prior-sprint accumulated
context does not degrade the next sprint's dispatch quality. The planter holds
continuity; the conductor resets.

Base spawn behavior applies per loop iteration. Full loop-boundary contract
(terminal `TaskCompleted` naming, context inheritance, operator pause window) at
`skills/shepherd/doctrines/spawn-escalation.md §XI`.

### Loop structure

```
[AUTO INIT]
  1. Read shepherd.toml → determine dev.N (current) through dev.LAST
  2. Preflight Check 5 --auto: confirm patch boundary + min_grade
  3. Emit loop plan: "Auto-loop will run dev.N through dev.LAST ({M} sprints)."
  4. 10-second pre-spawn countdown; operator may interrupt.

[FOR each dev.N in dev_order]:

  [SPAWN]
    Build teammate prompt + dispatch via Agent.
    Emit: "[AUTO] Sprint {N}/{LAST}: shepherd-auto-{sprint_slug} spawned."

  [BABYSIT]
    Full base babysit (wave commits, heartbeat, escalation).
    Escalation reaches operator-question or hard-stop → AUTO LOOP PAUSES.
    "[AUTO PAUSE] Sprint dev.{N} requires operator input. Resolve and
    type 'resume auto' to continue."

  [SPRINT CLOSE]
    Receive CONDUCTOR CLOSE REPORT via TeammateIdle.
    Execute inter-sprint work (see below).

  [TERMINATION CHECK]
    If dev.LAST → EXIT LOOP → emit PLANTER REPORT (auto-mode variant).
    If grade < [autorun].min_grade → EXIT LOOP → AUTO ABORT REPORT.
    If error_budget_remaining == 0 → EXIT LOOP → AUTO ABORT REPORT.
    If operator interrupted → EXIT LOOP → AUTO ABORT REPORT.
    Otherwise → continue to dev.N+1.

[END LOOP]
```

Teammate naming: `shepherd-auto-{sprint_slug}`.

### Inter-sprint work

The planter's exclusive domain between two spawned teammates. Authoritative
10-step checklist lives at `agents/planter.md §Sprint rollover (--auto mode) >
Inter-sprint work checklist`. Summary:

1. Verify close report (grade, carry-forwards, handoff path, GH dispositions).
2. Catchup commit any uncommitted wave artifacts.
3. Rebase-merge dev.N onto patch branch; verify green gate.
4. Open PR (standalone last dev) or accumulate (mid-patch).
5. Delete dev.N branch (confirm merged).
6. Cut dev.N+1 off the updated patch branch.
7. **Author the handoff doc** for dev.N+1 — continuity bridge for the
   zero-context incoming teammate. Schema and required sections at
   `agents/planter.md §Sprint rollover > Handoff document authorship`. Target
   60–120 lines.
8. Update carry-forward ledger.
9. Update error budget counter.
10. Emit inter-sprint status + 5-second pause window.

Any step failure → `[AUTO PAUSE]` with the failing step identified. Do not
re-attempt without operator confirmation.

### Termination conditions

| Condition | Code | Planter action |
|---|---|---|
| `dev.LAST` closed cleanly | LAST-DEV | Full cleanup stewardship; final PLANTER REPORT |
| Grade < `[autorun].min_grade` | GRADE-FLOOR | AUTO ABORT; operator decides re-spawn |
| `error_budget_remaining == 0` | BUDGET-ZERO | AUTO ABORT |
| Operator interrupt | OPERATOR-INTERRUPT | AUTO ABORT after current inter-sprint work completes |
| Escalation needs operator | ESCALATION-PAUSE | LOOP PAUSES (not terminates); resumes on confirmation |

### Auto ABORT REPORT shape

```
## AUTO ABORT REPORT
- Termination code: {code}
- Sprint at termination: dev.{N} (of dev.{LAST})
- Grade at termination: {grade}
- Error budget remaining: {N}
- Handoff doc (manual continuation): {path}
- Last committed SHA on patch branch: {sha}
- Carry-forwards pending: {list or "see ledger"}
- Recommended action: /shepherd:spawn dev.{N+1} (manual)
  or /shepherd:spawn --auto dev.{N+1}..dev.{LAST} (resume auto)
```

### Hard stops specific to --auto

In addition to base hard stops:

- **Inter-sprint step fails** — `[AUTO PAUSE]` until operator types `'resume auto'`.
- **Handoff doc missing or malformed** — auto-pause; do not spawn into a context vacuum.
- **Teammate stalls > 10 min** — auto-specific threshold (vs. 5 min base);
  `[AUTO PAUSE]` and suspend the loop.

---

## § Babysitter responsibilities

While the teammate-conductor runs the sprint, this main-chat session is the
ambient babysitter. Full behavioral contract: `agents/planter.md §Babysitter mode`.
Mechanical channel contract: `skills/shepherd/doctrines/spawn-escalation.md`.

Summary (one screen):

| Responsibility | Trigger | Action | Source |
|---|---|---|---|
| Hook monitoring | `TeammateIdle` / `TaskCreated` / `TaskCompleted` fires | Read mailbox; route by `halt_code` | doctrine §II, §VI |
| Mailbox polling | `TeammateIdle` BLOCKING | Inspect `halt_code`; null+`blocking:false` = wave-complete; non-null = escalation | doctrine §III |
| Wave-boundary commit | `TaskCompleted` on wave-scope task | `git commit -m "chore(dev.N/wave-K): wave-complete via spawn"` (DO NOT defer) | doctrine §VI |
| Escalation triage | non-null `halt_code` | chain-repair / operator-question / hard-stop categorisation | planter.md §Babysitter mode §1 |
| Heartbeat staleness | >5 min no new shctx row | Alert operator; do NOT auto-recover | doctrine §V |
| Cleanup at sprint close | CLOSE-FINALIZE report received | Rebase-merge, cut next branch, prune worktrees, release lock, emit PLANTER REPORT | planter.md §Babysitter mode §3 + §5 |

**The most critical responsibility is wave-boundary commits.** The one-wave loss
horizon exists ONLY if commits land at every boundary. Full contract:
`skills/shepherd/doctrines/spawn-escalation.md §VI`.

---

## § Hard stops — when /shepherd:spawn must refuse

Preflight-driven (Checks 1–3) plus run-state guards:

1. Preflight Check 1 / 2 / 3 fail.
2. **No active seed** — `{paths.plans}/{sprint_slug}.seed.md` missing. Send
   operator to `/shepherd:plant` first.
3. **Corrupted shepherd.lock** — `.artifacts/shepherd.lock` non-empty, timestamp
   < 30 min with matching active process. Surface; do not spawn.
4. **Active rebase in progress** — `REBASE_HEAD` or `MERGE_HEAD` present;
   spawning mid-rebase produces undefined teammate branch state.
5. **Nested-team attempt** — if this command fires inside a teammate session,
   refuse (D-API §12 forbids nested teams).

Parallel-specific and auto-specific hard stops are listed in the respective sections
above. Failure modes (stall, session drop, SendMessage failure, planter drop) and
recovery semantics live at `skills/shepherd/doctrines/spawn-escalation.md §VII`.

---

## § Open questions

Unresolved by the D-API report; flagged for engineer/operator.

- **OQ-1 (CRITICAL): `subagent_type` value for the conductor teammate.** D-API §6
  documents `Agent({ subagent_type, prompt })` but does not pin the exact
  `subagent_type` string for a shepherd-profile teammate. Options: model slug
  (e.g., `"claude-sonnet-4-5"`), custom agent-type referencing `agents/conductor.md`,
  or omit (inherit lead's model). D-API §4 notes `teammateDefaultModel` is absent,
  so teammates do NOT inherit by default. Until confirmed via live test: use the
  operator's intended model slug. Document the confirmed value in
  `docs/configuration.md §spawn`.
- **OQ-2 (MEDIUM): Teammate name propagation.** D-API §9 says names are assigned at
  spawn. Whether the platform parses from `IDENTITY.Name:` in the prompt or requires
  a dedicated `name:` field on the `Agent` call is unconfirmed.
- **OQ-3 (LOW): `TeammateIdle` routing on ambiguous `teammate_type`.** D-API
  Unknown #1: hook payload may show model slug, `"conductor"`, or custom string.
  Route by predictable `teammate_name` (`shepherd-conductor-{slug}`), not
  `teammate_type`.
- **OQ-4 (MEDIUM, --parallel): Cross-worktree build-manifest contention.** The
  collision check guards `file_scope.exclusive`. Some build tools (cargo shared
  registry cache, npm shared `node_modules`) may still contend on paths outside the
  worktree. Treat as known gap for v5.1.4; mitigation via
  `[project].build_manifest_paths` extension.
- **OQ-5 (LOW, --auto): `resume auto` signal mechanism.** Operator typing
  `'resume auto'` is recognised as text, not a formal tool call. A robust mechanism
  (e.g., `TaskCreate` with resume subject) is deferred.
- **OQ-6 (LOW, --parallel + --auto): Teammate naming collisions across sessions.**
  Re-running `--parallel`/`--auto` without full team cleanup may collide with
  existing `~/.claude/teams/` entries. The one-team-per-lead Check 3 partially
  guards. Mitigation: verify `ls ~/.claude/teams/` is empty before any multi-sprint
  run.

---

## § See also

- `agents/planter.md` — full planter/babysitter contract; §Babysitter mode; §Multi-teammate triage (--parallel); §Sprint rollover (--auto)
- `agents/conductor.md` — conductor profile; §Side-effect boundary; §Hard prohibitions #12; §Escalation protocol
- `skills/shepherd/doctrines/spawn-escalation.md` — **escalation channel contract** (paths, schema, resume shape, heartbeat, wave-boundary commits, failure semantics); §X multiplexed escalation; §XI sequential autopilot
- `commands/start.md` — the command the teammate invokes after boot
- `commands/plant.md` — seed authorship mode (prerequisite for a well-prepared spawn)
- `docs/configuration.md` — shepherd.toml schema + Agent Teams setup
- `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md` — D-API report (platform facts source of truth)
- `.artifacts/docs/specs/2026-05-19-v514-spawn-and-profiles-design.md` — v5.1.4 design spec
