---
name: spawn
description: |
  Spawn a teammate-conductor to run a sprint while main chat stays lean as the
  planter/babysitter. Requires the Agent Teams feature (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true,
  Claude Code ≥ v2.1.32, teammateMode configured). Main chat adopts the planter profile;
  the teammate's first action is /shepherd:start against the active sprint scope.
argument-hint: "[ sprint_slug ]   defaults to next unstarted dev.N in shepherd.toml"
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

## § See also

- `agents/planter.md` — full planter/babysitter behavioral contract; §Babysitter mode for spawn-specific behaviors
- `agents/conductor.md` — conductor profile; §Side-effect boundary; §Hard prohibitions #12; §Escalation protocol
- `skills/shepherd/doctrines/spawn-escalation.md` — **escalation channel contract** (file paths, payload schema, resume shape, heartbeat, wave-boundary commit discipline)
- `commands/start.md` — the command the teammate invokes after boot
- `commands/plant.md` — seed authorship mode (prerequisite for a well-prepared spawn)
- `docs/configuration.md` — shepherd.toml schema + Agent Teams setup section
- `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md` — D-API report (platform facts source of truth for this command)
- `.artifacts/docs/specs/2026-05-19-v514-spawn-and-profiles-design.md` — v5.1.4 design spec
