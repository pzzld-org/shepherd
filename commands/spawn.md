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
the post-sprint merge sequence. The mechanical details of the escalation channel —
file paths, polling cadence, hook events, lock semantics — are governed by the
binding contract at `skills/shepherd/doctrines/spawn-escalation.md`.

---

## § Platform compatibility

**Status (2026-05-19):** The conductor-as-teammate path documented below is fully
functional in **tmux** `teammateMode` today. **In-process** mode is partially limited
by [Claude Code issue #31977](https://github.com/anthropics/claude-code/issues/31977)
— teammate sessions in in-process mode currently do not expose the `Agent` tool,
so a spawned teammate's `/shepherd:start` cannot dispatch the flock the same way
main chat can.

| `teammateMode` setting | Conductor-as-teammate | Flock dispatch inside teammate |
|---|---|---|
| `tmux`        | ✅ Works today | ✅ Available |
| `in-process`  | ⚠️ Degraded    | ❌ Blocked on #31977 |

**Forward-compat:** This command and the `conductor` + `planter` profiles are
designed for the eventual state (full Agent-tool parity across modes). When
#31977 fixes, no spawn-side redesign is required; in-process users automatically
gain full functionality.

**Recommendation while #31977 is open:**
- Use `tmux` teammateMode for live spawn workflows that exercise the full flock
- In `in-process` mode, prefer `/shepherd:start` in main chat (which dispatches
  the flock via the lead's Agent tool) until the bug lands; the `--as <leaf-role>`
  family of spawn invocations (future v5.1.5 — see Open questions §X) will give
  in-process users single-role teammate isolation without needing nested dispatch

The preflight checks below detect feature-flag presence but do NOT currently gate
on `teammateMode`. Operator is expected to be aware of the mode-vs-feature
mismatch.

---

## § Preflight

Run every check before calling `Agent`. Refuse with a clear error if any check fails.
All four checks are fast (env read + version check + registry read + file existence).

### Check 1 — Agent Teams feature flag

```bash
# The env var is set at ~/.claude/.env or in settings.json under env.*
# It must be the string "true" — NOT "1" (both are accepted by the platform
# but shepherd normalises to "true" per the D-API report).
echo "${CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS}"
```

If the result is empty or any value other than `true` (or `1`, which the platform
also accepts):

```
/shepherd:spawn — REFUSED: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS is not set or not "true".

To enable Agent Teams:
  1. Add  CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true  to ~/.claude/.env
  2. Or add it under env.* in ~/.claude/settings.json
  3. Restart Claude Code and re-invoke /shepherd:spawn

Reference: docs/configuration.md §Agent Teams
D-API source: .artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md §1
```

> D-API note: the operator's `~/.claude/.env` has this var set to `"true"` as of
> 2026-05-19 (D-API §1). This check is a correctness guard for future states or
> other machines.

### Check 2 — Claude Code minimum version

```bash
claude --version
```

If the version is below v2.1.32 (the version that introduced Agent Teams per D-API §3):

```
/shepherd:spawn — REFUSED: Claude Code version is {detected}. Minimum required: v2.1.32.

Update with:  claude update
Then re-invoke /shepherd:spawn.
```

Agent Teams shipped in v2.1.32. `TeammateIdle`, `TaskCreated`, `TaskCompleted` hooks
were added in v2.1.33 and are required for the wave-boundary commit discipline.
Operator is on v2.1.144 — this check is a guard for portability.

### Check 3 — No active team (one-team-per-lead limit)

```bash
# Check the runtime team config directory.
ls ~/.claude/teams/ 2>/dev/null
```

If `~/.claude/teams/` is non-empty and contains a `config.json` with at least one
`members[]` entry, an active team is already running:

```
/shepherd:spawn — REFUSED: A team is already active.

The platform limits each lead session to one team at a time (D-API §11).
To resolve:
  - If the prior team's sprint is complete: run the hand-back sequence
    (verify close report, merge, cleanup) and then re-invoke /shepherd:spawn.
  - If the prior team is orphaned (no matching session): inspect
    ~/.claude/teams/ and remove stale config after operator confirmation.
    Then re-invoke /shepherd:spawn.
```

> D-API §11 (confirmed hard limit): "a lead can only manage one team. Must clean up
> before creating another." — `code.claude.com/docs/en/agent-teams §Limitations`.

### Check 4 — shepherd.toml (warn-only)

```bash
ls .claude/shepherd.toml 2>/dev/null || ls .local.toml 2>/dev/null
```

If no `shepherd.toml` is found:

```
[WARN] /shepherd:spawn: No .claude/shepherd.toml found.
Proceeding with framework defaults from ${CLAUDE_PLUGIN_ROOT}/docs/configuration.md.
Planting without a shepherd.toml is fragile — the conductor will operate in
default-mode with no project-specific path, gate, or ledger configuration.
Recommended: copy examples/minimal/shepherd.toml to .claude/shepherd.toml
and fill in your project's fields before spawning.

Continuing anyway — you may override by pressing Ctrl-C now.
```

This check is **non-blocking** (framework defaults cover the gap). All other checks
are hard-stop.

### Check 5 — Flag-specific preflight (--parallel and --auto only)

**For `--parallel <N>`:**

1. **Collision pre-check (HARD-STOP).** Before any spawn fires, planter reads each
   seed's `file_scope.exclusive` frontmatter for all N sprints. Seeds that share any
   path are colliding. A collision before spawn fires is a hard stop:
   ```
   /shepherd:spawn --parallel — REFUSED: Collision detected.
   Sprints {A} and {B} both claim exclusive write to {path}.
   Re-scope one sprint's file_scope before retrying.
   ```
   Operator must amend the seeds; then re-invoke. Planter does not auto-resolve collisions.

2. **N within bounds (HARD-STOP).** `N` must be 2–4. N=1 is just base spawn; N>4
   saturates the lead's `TeammateIdle` handler. Refuse with:
   ```
   /shepherd:spawn --parallel <N> — REFUSED: N must be between 2 and 4 (got {N}).
   ```

3. **N seeds available.** Exactly N seeds must exist as
   `{paths.plans}/{sprint_slug}.seed.md`. Missing seeds → hard stop; operator must run
   `/shepherd:plant` for the missing slots.

**For `--auto`:**

1. **Patch boundary detection (HARD-STOP).** Planter reads `shepherd.toml [branching]`
   to enumerate all dev.N branches in the current patch. It must identify which dev.N
   is the last before spawning:
   ```bash
   # Infer last dev from shepherd.toml [version] or the seed count on the patch branch
   grep -E 'dev\.' .claude/shepherd.toml | tail -1
   ```
   If the patch boundary cannot be determined (no `dev_total` or `patch_dev_count` key
   in `shepherd.toml`), planter prompts the operator:
   ```
   [PROMPT] /shepherd:spawn --auto: Cannot determine the last dev sprint.
   How many dev sprints does this patch contain? (current: dev.{N})
   Enter total count or "stop after dev.{N}" to cap the run:
   ```
   Operator input is mandatory before auto-loop begins.

2. **Min-grade configured.** `[autorun].min_grade` must be set in `shepherd.toml`.
   If absent, default to `B` and warn the operator.

---

## § Adopt the planter profile

Main chat (this session) becomes the ambient planter/babysitter for the lifetime of
the teammate's run. The planter profile loads now and stays active until the teammate
returns a close report and the hand-back sequence completes.

```
1. Load the planter behavioral contract:
   read ${CLAUDE_PLUGIN_ROOT}/agents/planter.md  (full file)

2. Confirm spawn mode (not plant mode):
   - Primary activity: ambient read + escalation response
   - Secondary activity: seed authorship on demand
   - Git custody: full (see agents/planter.md §Babysitter mode §2)
   - Session ends: only after teammate close + hand-back sequence (§7 steps)
```

If `agents/planter.md` is already loaded in this session (e.g., the operator ran
`/shepherd:plant` earlier), skip the re-read — the profile is current. Confirm
the mode is **spawn**, not **plant**.

> `agents/planter.md` frontmatter pins model: `opus[1m]`. If this session is running
> Sonnet and the operator intends a long babysit, recommend switching to Opus now.
> Non-blocking: spawn proceeds regardless; quality of escalation triage degrades on Sonnet.

---

## § Build the teammate prompt

Construct the teammate's boot prompt before calling `Agent`. The prompt carries all
inherited context the teammate needs to operate without asking main chat for
orientation material.

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
  Invoke /shepherd:start.
  Do not wait for further instructions from main chat before starting.
  The seed, handoff, and carry-forwards above are sufficient to orient.

ESCALATION RULES (summary — full contract at spawn-escalation doctrine)
  When you encounter any Halt code from agents/conductor.md §"Halt codes":
    1. Stop the walk at the current node.
    2. Write the escalation payload to:
         .artifacts/escalations/{sprint_slug}/{ISO-timestamp}-{role}.md
       Schema: {role, phase, halt_code, question, blocking, context_files[], suggested_resolution}
    3. Call SendMessage(to: lead) with the same payload as the message body.
    4. Do NOT proceed until you receive a resume reply from main chat.
    5. Heartbeat: write a shctx status row at every phase boundary so the planter
       knows you are alive. (PostToolUse hook handles this automatically if wired.)

HARD PROHIBITIONS WHILE SPAWNED
  - Do NOT call git commit, git push, git branch -d, git rebase on any branch.
    Git is owned exclusively by the planter (main chat). See agents/conductor.md
    §"Side-effect boundary" and Hard Prohibition #12.
  - Do NOT acquire or release .artifacts/shepherd.lock.
  - Do NOT spawn your own teammates. (Platform hard limit — nested teams are
    not allowed. You may still dispatch regular subagents via Agent tool.)
  - Do NOT push to any remote branch not owned by the active sprint.

WAVE-BOUNDARY COMMIT PROTOCOL
  At each wave completion, you MUST:
    1. Send a SendMessage(to: lead) wave-complete notification with:
         {phase: "body-wave-N", halt_code: null, question: null, blocking: false,
          context_files: ["<wave-gate-output-path>"], suggested_resolution: null}
    2. TaskCompleted signal fires automatically on wave-scope task completion.
    The planter commits your wave's work on TaskCompleted. If you stall in wave N+1,
    only wave N+1 work is lost (one-wave loss horizon).

TEAMMATE IDENTITY
  Name: shepherd-conductor-{sprint_slug}
  You are session: {will be assigned at spawn}
  Your session transcript: ~/.claude/projects/<project-path>/<session-uuid>.jsonl
```

### Dynamic field resolution

Before pasting the prompt, resolve all `{...}` tokens:

| Token | Source |
|---|---|
| `{project_claude_md_path}` | `pwd`/CLAUDE.md (absolute path) |
| `{paths.plans}/{sprint_slug}.seed.md` | from `shepherd.toml` `[paths]` + sprint detect |
| `{paths.docs}/{prior_handoff_filename}` | `ls -t {paths.docs}/*-close-handoff.md \| head -1` |
| `{carry-forward GH issues}` | extracted from handoff doc's carry-forward section |
| `shepherd.toml snapshot` | full contents of `.claude/shepherd.toml` |
| `{sprint_slug}` | from `shepherd.toml [branching].sprint_branch_pattern` + current dev.N |

---

## § Spawn dispatch

The lead session calls `Agent` to create the teammate. Internally, Claude Code
uses the `Agent` (or `Task`) tool to spawn new teammate sessions.

### Dispatch shape

```
Agent({
  subagent_type: "claude-sonnet-4-5",   // or operator-specified model; see Open Questions #1
  prompt: <the teammate prompt from § Build the teammate prompt>,
  // Teammate name is assigned in the prompt text itself under IDENTITY.Name
  // No per-teammate config files are supported at spawn time (D-API §9).
  // The conductor profile is loaded by the teammate itself via /shepherd:start.
})
```

> **D-API source**: D-API §5 (spawn lifecycle) and §6 (dispatch shape):
> "The lead calls `Agent({ subagent_type: X, prompt: P })` — always creates a new session."
> "Internally the lead uses the `SendMessage` tool to communicate with running
> teammates, and `Agent`/`Task` tool calls to spawn new ones."
>
> D-API §9 confirms: "There are no per-teammate config files beyond the team config.
> Teammates cannot have different `settings.json` sections; they inherit the lead's
> permission mode."

### Session naming

The teammate's name (`shepherd-conductor-{sprint_slug}`) is passed inside the prompt
body and is also the key used in `TeammateIdle` hook routing. Use a predictable,
sprint-scoped name so hook scripts can route by name without ambiguity.

Names are assigned at spawn via the team config at
`~/.claude/teams/{team-name}/config.json` — written and owned by the runtime;
do NOT pre-author or edit it.

### Post-spawn confirmation

After calling `Agent`, emit:

```
[SPAWN] teammate shepherd-conductor-{sprint_slug} dispatched.
        Team config: ~/.claude/teams/shepherd-conductor-{sprint_slug}/config.json
        Teammate transcript: ~/.claude/projects/<project>/<session-uuid>.jsonl
        Babysitter mode: active. Monitoring TeammateIdle + TaskCompleted hooks.
        Heartbeat threshold: 5 min. Alert on staleness.
        Sprint: {sprint_slug}
```

---

## § --parallel flag

`/shepherd:spawn --parallel <N>` fans out N sibling teammates inside the lead's single
team. N is typically 2–4 (see preflight Check 5). Each teammate runs exactly one
sprint end-to-end via `/shepherd:start`. The planter (main chat) acts as the
multiplexed babysitter for all N teammates simultaneously.

Base spawn behavior (§ Adopt the planter profile, § Build the teammate prompt,
§ Spawn dispatch) applies to each teammate. The sections below describe the
**incremental behavior** specific to `--parallel`.

### Pre-spawn collision check

Before calling `Agent` for any teammate, the planter executes the collision check
from preflight Check 5 (§ Preflight). This check is repeated here as a hard gate:

1. Read `file_scope.exclusive` from each seed's YAML frontmatter.
2. Build a union map: `{path → [sprint_slugs_that_claim_it]}`.
3. Any path with more than one claimant is a collision.
4. Surfaces ALL collisions to the operator in one block before stopping:
   ```
   [COLLISION REPORT]
   path: src/foo/bar.rs
     claimed by: v515-dev1 (exclusive), v515-dev2 (exclusive)
   path: Cargo.toml
     claimed by: v515-dev1 (exclusive), v515-dev3 (exclusive)

   Re-scope the colliding seeds before retrying /shepherd:spawn --parallel.
   ```
5. **Also check for shared build-manifest writes.** Paths matching `Cargo.toml`,
   `package.json`, `pyproject.toml`, `go.mod`, `*.lock`, `*.sum`, `build.gradle`
   (or equivalent per `[project].build_manifest_paths` in shepherd.toml) are
   single-writer surfaces. If more than one sprint writes these, it is always a
   collision regardless of `file_scope` classification.
6. If zero collisions: emit `[COLLISION CHECK PASSED — N sprints are file-disjoint]`
   and proceed to spawn.

If a collision is detected AFTER spawn (e.g., a coder brief discovers an unexpected
shared file), the teammate MUST surface it as a halt with `halt_code: PARALLEL-COLLISION`.
Planter receives this, pauses ALL affected teammates via SendMessage, then resolves before
allowing any affected teammate to continue. See §X (PARALLEL-COLLISION halt) in spawn-escalation doctrine.

### Worktree-per-teammate setup

Each of the N teammates runs in its own git worktree to guarantee filesystem isolation:

```bash
# For each teammate i (1..N):
git worktree add .worktrees/{sprint_slug_i} {sprint_branch_i}
```

The worktree path is `.worktrees/{sprint_slug}` (e.g., `.worktrees/v515-dev2`).

Include the worktree path in the teammate's boot prompt (INHERITED CONTEXT block):
```
WORKTREE PATH:  {abs_path}/.worktrees/{sprint_slug}
All file reads and writes MUST use this path as the working root.
```

Cleanup: planter removes each worktree as its teammate's sprint closes
(see § Babysitter responsibilities §4, and Cleanup at each teammate close below).

### Teammate naming convention (--parallel)

Teammate names follow the pattern `shepherd-parallel-{sprint_slug}` to distinguish
from single-spawn (`shepherd-conductor-{sprint_slug}`). The `TeammateIdle` hook routes
by `teammate_name`; the `shepherd-parallel-` prefix is the routing key.

### Multiplexed escalation queue

With N teammates active simultaneously, escalations can arrive concurrently. The planter
processes them as a queue with the following rules:

1. **CRITICAL preemption.** Any escalation carrying `halt_code` in the CRITICAL tier
   (from `agents/conductor.md §Halt codes`) jumps the queue immediately, regardless of
   arrival order. If multiple CRITICAL escalations arrive simultaneously, process them
   alphabetically by `teammate_name` (deterministic ordering).

2. **Same-level FIFO.** Non-CRITICAL escalations are processed first-in-first-out, keyed
   by `TeammateIdle` hook arrival time.

3. **Mid-triage arrival.** If the planter is currently triaging teammate A's escalation
   and teammate B fires another:
   - If B's escalation is CRITICAL: emit `[QUEUE PREEMPT] Interrupting A-triage for B
     CRITICAL halt`. Suspend A-triage state by writing a bookmark to
     `.artifacts/escalations/{sprint_A}/triage-suspended.md`. Address B first.
     Resume A after B's resume signal is sent.
   - If B's escalation is non-CRITICAL: enqueue it. Emit `[QUEUE] Teammate B escalation
     queued (position {N}). Completing A-triage first.`

4. **Cross-teammate dependency halt.** If teammate A is waiting for an output from
   teammate B's sprint (a declared `sprint_dependencies` link in the seed):
   - Teammate A surfaces `halt_code: CROSS-DEP-WAIT` with payload identifying the
     blocking sprint and the specific artifact path.
   - Planter checks teammate B's current phase via its heartbeat row. If B's relevant
     wave has completed, planter delivers the artifact path to A via resume reply.
   - If B has not yet produced the artifact, planter notifies A that B is still in
     flight and sets a check interval (every TeammateIdle fire, re-check).
   - Do NOT block A permanently on B without a timeout. After `[spawn].cross_dep_timeout_sec`
     (default: 300), escalate to the operator as an `ESCALATION — operator question`.

5. **Status board.** Planter maintains a lightweight in-memory status board:
   ```
   | teammate_name              | phase     | queue_depth | last_seen |
   | shepherd-parallel-dev1     | body-wave-2 | 0         | 14:03 |
   | shepherd-parallel-dev2     | body-wave-1 | 1 (queued) | 14:01 |
   | shepherd-parallel-dev3     | intro      | 0         | 13:58 |
   ```
   After each `TeammateIdle` or `TaskCompleted` hook fire, update the board and
   print it if the operator is watching the session.

### Dev-order merge gate

The seeds for parallel sprints declare a merge order (via `sprint_dependencies` or
`dev_order` in the seed frontmatter). The planter enforces this order:

1. **Merge gate rule.** Sprint dev.N+1 may NOT be merged to the patch branch until
   dev.N's PR is merged. Even if dev.N+1's sprint closes first.

2. **Detection.** On each `TeammateIdle` fire for a closing teammate, planter reads the
   `dev_order` from the teammate's seed. If any predecessor sprint is unmerged:
   ```
   [MERGE GATE] shepherd-parallel-{sprint_slug} sprint closed cleanly.
   Predecessor dev.{M} PR is not yet merged. Holding merge.
   Carrying close report in .artifacts/docs/handoffs/<timestamp>-{sprint_slug}-pending-merge.md
   Monitoring TeammateIdle for dev.{M} to close.
   ```

3. **Release.** When the predecessor closes and its PR merges, planter immediately
   releases the held sprint: rebases `dev.N+1` onto the now-updated patch branch,
   verifies green gate, merges.

4. **Order invariant.** The patch branch commit graph must always reflect dev-order
   regardless of which sprint finished first. The merge gate enforces this.

### Cleanup at each teammate close

When a teammate's sprint closes (CONDUCTOR CLOSE REPORT received via `TeammateIdle`):

1. Verify the close report per base spawn (§ Babysitter responsibilities §4).
2. Apply the merge gate (above). If held: write pending-merge marker, skip merge.
3. If not held (predecessor already merged): execute the rebase-merge sequence.
4. Remove the teammate's worktree:
   ```bash
   git worktree remove --force .worktrees/{sprint_slug}
   # --force only if the branch is already merged; otherwise surface to operator.
   ```
5. Update the multiplexed status board to mark this teammate as CLOSED.
6. Update the carry-forward ledger for this sprint's items.
7. DO NOT run the full cleanup stewardship (agent-* branches, shepherd.lock) until
   ALL N teammates have closed. Run the full §3 cleanup only at final close.

### Hard stops specific to --parallel

In addition to the base hard stops (§ Hard stops), refuse or halt when:

8. **Collision detected after spawn.** Halt with `PARALLEL-COLLISION`. Pause ALL
   affected teammates via SendMessage before addressing. See spawn-escalation §X (PARALLEL-COLLISION halt).
9. **More than 1 simultaneous CRITICAL halt.** If two or more teammates fire CRITICAL
   escalations at the same time, halt the planter's entire ambient loop:
   ```
   [HARD STOP] Multiple simultaneous CRITICAL halts detected.
   Teammates in CRITICAL state: {list}.
   This requires operator judgment on priority. Presenting all CRITICAL payloads now.
   ```
   Operator decides resolution order. Do not auto-prioritize CRITICAL vs. CRITICAL.
10. **Teammate count drops to 0 unexpectedly.** If all N teammates stall or session-drop
    before any sprint closes, the parallel run is unrecoverable without operator input.
    Emit full stall alert per § Failure modes & recovery.
11. **Dev-order cycle detected.** If the `sprint_dependencies` graph contains a cycle
    (A depends on B, B depends on A), the merge gate would deadlock. Detect this during
    Check 5 (pre-spawn) and refuse with:
    ```
    /shepherd:spawn --parallel — REFUSED: Dependency cycle detected in sprint_dependencies.
    Cycle: {A} → {B} → {A}. Fix the seed frontmatter before retrying.
    ```

---

## § --auto flag

`/shepherd:spawn --auto` runs a sequential autopilot loop. The planter spawns one
teammate per sprint, waits for it to close, does all inter-sprint work, then spawns
the next — until the patch is exhausted or a termination condition fires.

The core win over repeated `/shepherd:start` or `/shepherd:spawn`: **each sprint gets a
fresh context window**. The previous sprint's accumulated context does not degrade the
next sprint's dispatch quality. The planter holds continuity; the conductor resets.

Base spawn behavior (§ Adopt the planter profile, § Build the teammate prompt,
§ Spawn dispatch, § Babysitter responsibilities) applies to each loop iteration.
The sections below describe the **loop semantics** and the inter-sprint work.

### Loop structure

```
[AUTO INIT]
  1. Read shepherd.toml → determine dev.0 (or current dev.N) through dev.LAST
  2. Execute preflight Check 5 --auto: confirm patch boundary + min_grade
  3. Emit loop plan: "Auto-loop will run dev.N through dev.LAST ({M} sprints)."
  4. Operator has 10 seconds to interrupt before first spawn fires (emit countdown).

[FOR each dev.N in dev_order]:

  [SPAWN]
    a. Build teammate prompt (§ Build the teammate prompt) for dev.N
    b. Dispatch via Agent (§ Spawn dispatch)
    c. Emit: "[AUTO] Sprint {N}/{LAST}: shepherd-auto-{sprint_slug} spawned."

  [BABYSIT]
    d. Full base babysit: wave-boundary commits, heartbeat monitoring,
       escalation response (§ Babysitter responsibilities)
    e. If escalation reaches operator-question or hard-stop: AUTO LOOP PAUSES.
       Print: "[AUTO PAUSE] Sprint dev.{N} requires operator input. Auto-loop
       is suspended. Resolve the escalation and type 'resume auto' to continue."
       Loop resumes only on explicit operator confirmation.

  [SPRINT CLOSE]
    f. Receive CONDUCTOR CLOSE REPORT from teammate via TeammateIdle
    g. Execute inter-sprint work (see below)

  [TERMINATION CHECK — runs after inter-sprint work]
    h. If this was dev.LAST: EXIT LOOP → emit PLANTER REPORT (auto-mode variant)
    i. If grade < [autorun].min_grade: EXIT LOOP → emit AUTO ABORT REPORT
    j. If error_budget_remaining == 0: EXIT LOOP → emit AUTO ABORT REPORT
    k. If operator sent interrupt signal: EXIT LOOP → emit AUTO ABORT REPORT
    l. Otherwise: continue to next iteration (dev.N+1)

[END LOOP]
```

Teammate naming convention for auto-loop: `shepherd-auto-{sprint_slug}` (distinguishes
from single-spawn `shepherd-conductor-*` and parallel `shepherd-parallel-*`).

### Inter-sprint work

The inter-sprint work is the planter's exclusive domain between two spawned teammates.
It runs after the close report arrives and before the next teammate is spawned.

**Checklist (execute in order; each step is a hard gate for the next):**

1. **Verify the close report.**
   - Grade present, carry-forwards enumerated, handoff doc written to `{paths.docs}/`.
   - All CRITICAL/HIGH GH# dispositions listed.
   - If verification fails: emit `[AUTO PAUSE]` — do not continue to the next sprint.

2. **Wave-boundary commits catchup (if any missed).**
   - `git status` — stage and commit any uncommitted wave artifacts.
   - Emit per-file list of what was committed.

3. **Rebase-merge dev.N onto patch branch.**
   ```bash
   git checkout {patch_branch}
   git rebase {dev_N_branch}
   # or: git merge --no-ff {dev_N_branch} -m "merge({dev_N_branch}): sprint close"
   ```
   Verify green gate. If gate fails: `[AUTO PAUSE]` — operator must fix before auto continues.

4. **Open PR (if sprint is standalone) or accumulate (if mid-patch).**
   - Standalone sprint (last dev): open and merge PR per
     `feedback_pr_required_not_bypass.md` discipline.
   - Mid-patch sprint: accumulate the merge, DO NOT open PR yet. PR opens when
     the last dev.N closes.

5. **Delete dev.N branch.**
   ```bash
   git branch -d {dev_N_branch}
   ```
   Confirm branch is merged before deleting. If not merged: surface to operator.

6. **Cut dev.N+1 branch** (if not the last dev):
   ```bash
   git checkout -b {dev_N+1_branch} {patch_branch}
   ```

7. **Write handoff document for dev.N+1.**
   Path: `{paths.docs}/<date>-{sprint_slug_N+1}-auto-handoff.md`
   Content schema (the next teammate has zero prior context; this doc IS its history):
   ```markdown
   # Auto-handoff: {sprint_slug_N+1}

   ## Prior sprint summary
   - Sprint: {sprint_slug_N}
   - Grade: {grade}
   - Closed at: {ISO-timestamp}
   - Key deliverables: {bullet list from close report}

   ## Carry-forwards from dev.{N}
   {verbatim carry-forward list from close report}

   ## GH issues closed
   {list of #NNN merged}

   ## GH issues opened or updated
   {list}

   ## Branch state
   - Patch branch: {patch_branch} @ {sha}
   - dev.{N+1} branch: {dev_N+1_branch} @ {sha} (cut from patch branch)

   ## Error budget
   - Budget at dev.{N} close: {error_budget_remaining}
   - Errors consumed: {count}

   ## Operator instructions (if any)
   {any instructions the operator provided during the auto-loop}

   ## Context files for dev.{N+1} seed
   - Seed: {paths.plans}/{sprint_slug_N+1}.seed.md
   - Prior handoff: this file
   - Carry-forward ledger: {ledger.carry_forward_file}
   ```

8. **Update carry-forward ledger.**
   Every CRITICAL/HIGH item from the close report placed, deferred with a target,
   or operator-dropped. No silent disappearances.

9. **Update the error budget.**
   Deduct any errors consumed this sprint. If `error_budget_remaining` reaches 0:
   termination condition J fires.

10. **Emit inter-sprint status.**
    ```
    [AUTO] Sprint dev.{N} closed → dev.{N+1} ready.
    Grade: {grade} | Budget remaining: {N} | Sprints remaining: {M}
    Handoff written: {path}
    Next spawn in 5 seconds — interrupt with Ctrl-C now to pause.
    ```
    The 5-second window is the operator's pause opportunity between sprints.

### Termination conditions

The auto-loop exits on any of these conditions (all checked at step h–k above):

| Condition | Code | Planter action |
|---|---|---|
| `dev.LAST` closed cleanly | LAST-DEV | Full cleanup stewardship; emit final PLANTER REPORT |
| Grade < `[autorun].min_grade` | GRADE-FLOOR | AUTO ABORT; emit abort report; operator decides whether to re-spawn manually |
| `error_budget_remaining == 0` | BUDGET-ZERO | AUTO ABORT; same as GRADE-FLOOR |
| Operator sends interrupt | OPERATOR-INTERRUPT | AUTO ABORT after current sprint's inter-sprint work completes cleanly (do not orphan a mid-sprint teammate) |
| Escalation requires operator input mid-sprint | ESCALATION-PAUSE | AUTO LOOP PAUSES (not terminates); resumes on explicit operator confirmation |

### Auto ABORT REPORT shape

When a non-LAST-DEV termination fires, emit:

```
## AUTO ABORT REPORT
- Termination code: {code}
- Sprint at termination: dev.{N} (of dev.{LAST})
- Grade at termination: {grade}
- Error budget remaining: {N}
- Handoff doc (for manual continuation): {path}
- Last committed SHA on patch branch: {sha}
- Carry-forwards pending: {list or "see ledger"}
- Recommended action: /shepherd:spawn dev.{N+1} (manual single-sprint)
  or /shepherd:spawn --auto dev.{N+1}..dev.{LAST} (resume auto from here)
```

### Context the next teammate inherits

Beyond the seed (which carries the plan), the next teammate receives via its boot prompt:

```
INHERITED CONTEXT
  Prior auto-handoff: {paths.docs}/<date>-{sprint_slug_N+1}-auto-handoff.md
  Prior close report: {paths.reports}/<date>-{sprint_slug_N}-close.md
  Carry-forward ledger: {ledger.carry_forward_file}
  Error budget remaining: {N}
  Patch branch SHA: {sha}
```

The handoff doc (step 7 above) is the continuity bridge. It must be authored completely
before the next spawn fires — an incomplete handoff produces a confused teammate.

### Hard stops specific to --auto

In addition to base hard stops (§ Hard stops), the auto-loop also halts when:

12. **Inter-sprint work step fails.** Any step in the inter-sprint checklist that fails
    (gate failure, merge conflict, branch cut failure) triggers `[AUTO PAUSE]`. The loop
    does not proceed until the operator resolves the failure and types `'resume auto'`.
13. **Handoff doc missing or malformed.** Before each spawn, the planter verifies the
    handoff doc for the next sprint exists and contains all required fields. If missing:
    auto-pause; do not spawn into a context vacuum.
14. **Teammate stalls > 10 min (auto-specific threshold).** In base spawn the threshold
    is 5 min with operator decision. In auto mode, a 10-minute stall (without escalation)
    triggers `[AUTO PAUSE]` and suspends the loop. Operator must confirm whether to wait
    longer, declare stall, or abort auto.

---

## § Babysitter responsibilities

While the teammate-conductor runs the sprint, this main-chat session is the ambient
babysitter. Full behavioral contract is in `agents/planter.md §Babysitter mode`. Summary:

### 1. Hook monitoring

Three hook events are relevant (D-API §13):

| Hook | Fires when | Lead context? | Action |
|---|---|---|---|
| `TeammateIdle` | Teammate about to go idle | Yes (BLOCKING) | Read mailbox; route escalation or confirm clean close |
| `TaskCreated` | A task is created | Yes (may block) | Log; update shctx if relevant |
| `TaskCompleted` | A wave-scope task completes | Yes (may block) | **Commit the wave's work to dev branch** |

`TeammateIdle` is BLOCKING in the lead context — when it fires, main chat must
respond before the teammate becomes fully idle. This is the natural escalation
pause point. Do NOT let it time out silently.

### 2. Mailbox polling

The teammate calls `SendMessage(to: lead)` to surface escalations and wave-complete
notifications. Read the mailbox on every `TeammateIdle` fire. In ambient mode, also
check proactively every few exchanges.

When a `SendMessage` arrives, inspect the payload's `halt_code` field:
- `halt_code: null` + `blocking: false` → wave-complete notification → commit the wave.
- Any non-null `halt_code` → escalation → follow the triage protocol in
  `agents/planter.md §Babysitter mode §1` and the escalation doctrine.

### 3. Wave-boundary commits

**This is the most critical babysitter responsibility.** On every `TaskCompleted`
hook fire for a wave-scope task:

1. Read the SendMessage wave-complete payload to identify which files landed.
2. Run `git status` to verify branch and unstaged state.
3. Stage and commit the wave's artifacts: `git commit -m "chore(dev.N/wave-K): wave-complete via spawn"`.
4. The teammate's next wave continues; if the teammate then stalls, only that wave is lost.

Do NOT defer wave commits. The one-wave loss horizon exists ONLY if commits land at
every boundary. Full contract: `skills/shepherd/doctrines/spawn-escalation.md §Wave-boundary commit discipline`.

### 4. Cleanup at sprint close

When `TeammateIdle` fires and the payload carries the CONDUCTOR CLOSE REPORT:

1. Verify the close report: grade, carry-forwards enumerated, handoff doc written.
2. Execute the rebase-merge sequence: `dev.N` onto the patch branch.
3. Verify green gate.
4. Cut the next dev branch (`dev.N+1`) off the patch branch.
5. Update the carry-forward ledger.
6. Run zombie worktree prune + agent-* branch cleanup.
7. Release `shepherd.lock` if held.
8. Emit PLANTER REPORT (spawn-mode variant).

See `agents/planter.md §Babysitter mode §5` (hand-back timing) and `§3` (cleanup
stewardship) for complete procedures.

---

## § Failure modes & recovery

Platform hard limits (from D-API §11) impose asymmetric failure costs. Know these
before spawning.

### Teammate stalls (heartbeat goes stale)

**Detection**: the `PostToolUse` hook writes a shctx row per teammate tool call.
Planter staleness threshold: **5 minutes** of no new heartbeat row.

If stale beyond threshold:

```
[ALERT] Teammate shepherd-conductor-{sprint_slug} heartbeat stale (>{threshold}min).
Last heartbeat: {timestamp} | Phase: {phase}
Options:
  (1) Wait longer — teammate may be in a long tool call (e.g., large Agent dispatch).
      Recommended if within 10 min.
  (2) Send a probe via SendMessage(to: shepherd-conductor-{sprint_slug}):
      "Status check: are you alive? Current phase?" — if no reply within 2 min, treat as stalled.
  (3) Declare stall: kill team, preserve work committed at last wave boundary.
      Progress since last wave-boundary commit is LOST. Restart with /shepherd:spawn
      from the next uncommitted wave.
```

Do NOT auto-recover. Operator must decide. There is no `/resume` for in-process
teammates (D-API §11 confirmed hard limit).

### Teammate session drops (crash / OOM / SIGKILL)

`TeammateIdle` does NOT fire on crash — only on graceful idle (D-API §13, Unknown #3).
If the teammate session disappears without a `TeammateIdle`:

```
[ALERT] Teammate session dropped without TeammateIdle. Session ID no longer
present in ~/.claude/sessions/.

Evidence:
  Last shctx heartbeat row: {timestamp} | Phase: {phase}
  Last wave-boundary commit: {commit-sha}
  Work since last commit: LOST

Recovery:
  Progress since the last wave-boundary commit cannot be recovered — no /resume
  for in-process teammates (D-API §11). The loss horizon is one wave.

  To continue the sprint:
    1. Inspect the sprint branch: git log {sprint_branch} --oneline | head -10
    2. Identify the last landed wave from commit messages.
    3. /shepherd:spawn again — the teammate will re-read the plan's Stage Graph,
       find the walk position from git log + walk trace, and continue from the
       next unstarted node.
    4. Wave N+1 work must be re-done; waves 0..N are preserved in git.
```

Mark the orphaned team config: `~/.claude/teams/shepherd-conductor-{sprint_slug}/config.json`
may need manual removal before re-spawn (one-team-per-lead limit).

### SendMessage delivery fails

If `SendMessage` returns an error or the payload does not appear in the mailbox:

1. Fall back to the durable filesystem channel: `~/.claude/tasks/{team-name}/`.
   The teammate's conductor writes escalation files to
   `.artifacts/escalations/{sprint_slug}/<timestamp>-<role>.md` as the durable path.
   Read those files directly.
2. If both mailbox and filesystem fail: the escalation is lost. Alert the operator;
   do NOT auto-resume. Treat as a stall scenario (see above).

D-API source: §8 — "there is no live RPC; communication is asynchronous via the
mailbox and the task list."

### Operator interrupts (Ctrl-C in main chat)

Pressing Ctrl-C in main chat while the teammate is active leaves the teammate
running as an orphan:

```
[WARN] Main chat interrupted. The teammate-conductor is likely still running
as an orphan session. It will continue dispatching agents, but:
  - No commits will land (git custody is with the now-interrupted planter).
  - No escalations will be answered.
  - The team will eventually idle but the close report will have no receiver.

Manual cleanup required:
  1. Find the teammate's session: ls ~/.claude/teams/shepherd-conductor-{sprint_slug}/
  2. Note the session UUID from config.json.
  3. Kill the session if Claude Code exposes a termination path.
  4. Remove the team config: rm -rf ~/.claude/teams/shepherd-conductor-{sprint_slug}/
  5. Inspect the sprint branch for any partial artifacts.
  6. Re-spawn with /shepherd:spawn when ready.
```

There is no "graceful interrupt" path for in-process teammates. Prevention is the
control: operator should send a `SendMessage` requesting a clean stop before
interrupting main chat.

---

## § Hard stops — when /shepherd:spawn must refuse

In addition to the preflight failures in `§ Preflight`, refuse to spawn when:

1. **Preflight Check 1 fails** — feature flag not active.
2. **Preflight Check 2 fails** — Claude Code below v2.1.32.
3. **Preflight Check 3 fails** — active team already exists (one-team limit).
4. **No active seed** — `{paths.plans}/{sprint_slug}.seed.md` does not exist.
   Without a seed the teammate cannot orient; send operator to `/shepherd:plant` first.
5. **Corrupted shepherd.lock** — `.artifacts/shepherd.lock` is non-empty and
   timestamp < 30 min ago with a matching active process. Spawning a new team over
   an unresolved lock creates split ownership. Surface and wait for operator.
6. **Active rebase in progress** — `git status` shows `REBASE_HEAD` or
   `MERGE_HEAD` on the sprint branch. Spawning mid-rebase produces undefined
   teammate branch state.
7. **Teammate API invoked from inside a teammate** — nested teams are forbidden
   (D-API §12). If this command fires inside a teammate session, refuse immediately.

For cases 4–7, emit a specific refusal with resolution steps (same pattern as
Preflight Check 1–3 errors above).

---

## § Open questions

These questions are unresolved by the D-API report and must be confirmed before
relying on the spawn dispatch shape. They are flagged here for the engineer/operator.

**OQ-1 (CRITICAL): `subagent_type` value for the conductor teammate.**
D-API §6 documents that the lead calls `Agent({ subagent_type: X, prompt: P })`.
The D-API report does NOT pin the exact string value of `subagent_type` when spawning
a shepherd-profile teammate. Options:
  - `"claude-sonnet-4-5"` (or the operator's preferred model slug) — model-pinned spawn
  - A custom agent-type string (e.g., `"conductor"`) referencing `agents/conductor.md`
  - The default (omit `subagent_type`; teammate inherits lead's model)

D-API §4 notes that `teammateDefaultModel` is absent from the operator's settings,
meaning teammates do NOT inherit the lead's model by default. D-API "Likely Behavior"
#5 says agent frontmatter `model:` is honored at spawn since v2.1.47 — but this
applies to agents dispatched via Agent tool where the file is referenced, not to a
spawn where the profile is injected via `prompt:`.

**Resolution needed**: engineer must confirm the spawn call shape via a live test.
Until confirmed, use the operator's intended model string (e.g., `"claude-sonnet-4-5"`)
as `subagent_type`. Document the confirmed value in `docs/configuration.md §spawn`.

**OQ-2 (MEDIUM): Teammate name propagation.**
D-API §9 says names are assigned at spawn time. The exact mechanism (a field in
the `Agent` tool call, or parsed from the prompt body) is not confirmed. If the
platform parses the name from `IDENTITY.Name:` in the prompt, the current approach
works. If it requires a dedicated `name:` field in the `Agent` call, update the
dispatch shape.

**OQ-3 (LOW): `TeammateIdle` routing when `teammate_type` is ambiguous.**
D-API Unknown #1: when a teammate is spawned, does `teammate_type` in the hook
payload show the model slug, `"conductor"`, or a custom string? Hook routing in
shepherd's `TeammateIdle` scripts should be written to match on `teammate_name`
(predictable: `shepherd-conductor-{sprint_slug}`) rather than `teammate_type`
until this is confirmed.

---

## § Open questions

**OQ-4 (MEDIUM, --parallel specific): Cross-worktree build-manifest contention.**
The collision check (Check 5) guards `file_scope.exclusive` paths. However, some build
tools (e.g., cargo with a shared registry cache, npm with a shared `node_modules`)
may still contend on paths outside the worktree. For v5.1.4, treat this as a known
gap: the collision check is sufficient for source-file collisions; build-tool-level
contention is handled by shepherd.toml `[project].build_manifest_paths` extension
once the consumer project configures it.

**OQ-5 (LOW, --auto specific): `resume auto` signal mechanism.**
The loop pause/resume uses the operator typing `'resume auto'` as the resume signal.
There is no formal tool call for this; it relies on the planter recognizing the phrase
in the conversation. A more robust mechanism (e.g., a `TaskCreate` with a resume-signal
subject) is deferred to v5.1.5.

**OQ-6 (LOW, --parallel + --auto): teammate naming collisions across sessions.**
If the operator runs `--parallel` or `--auto` twice in the same Claude Code session
without full team cleanup between runs, teammate names (`shepherd-parallel-{slug}`,
`shepherd-auto-{slug}`) may collide with existing `~/.claude/teams/` entries. The
one-team-per-lead limit (Check 3) partially guards against this, but if the prior
team's config.json was removed manually without a clean team shutdown, the check
may pass incorrectly. Mitigation: always verify `ls ~/.claude/teams/` is empty before
spawning any multi-sprint run.

---

## § See also

- `agents/planter.md` — full planter/babysitter behavioral contract; §Babysitter mode for spawn-specific behaviors; §Multi-teammate triage (--parallel mode); §Sprint rollover (--auto mode)
- `agents/conductor.md` — conductor profile; §Side-effect boundary; §Hard prohibitions #12; §Escalation protocol
- `skills/shepherd/doctrines/spawn-escalation.md` — **escalation channel contract** (file paths, payload schema, resume shape, heartbeat, wave-boundary commit discipline; §X multiplexed escalation; §XI sequential autopilot)
- `commands/start.md` — the command the teammate invokes after boot
- `commands/plant.md` — seed authorship mode (prerequisite for a well-prepared spawn)
- `docs/configuration.md` — shepherd.toml schema + Agent Teams setup section
- `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md` — D-API report (platform facts source of truth for this command)
- `.artifacts/docs/specs/2026-05-19-v514-spawn-and-profiles-design.md` — v5.1.4 design spec
