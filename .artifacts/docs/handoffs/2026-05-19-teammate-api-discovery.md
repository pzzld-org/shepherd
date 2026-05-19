---
title: Teammate / Agent-Teams API Discovery
date: 2026-05-19
status: complete
author: discovery-agent (main-chat)
gates: v5.1.4 Phase 0 — mandatory before plan authoring
---

# Teammate / Agent-Teams API Discovery

> Phase 0 of the v5.1.4 seed. This report gates the engineer's plan.
> Sources: `/Users/jo3/.claude/cache/changelog.md`, `/Users/jo3/.claude/settings.json`,
> `/Users/jo3/.claude/.env`, `/Users/jo3/.claude/daemon/roster.json`,
> `https://code.claude.com/docs/en/agent-teams`, `https://code.claude.com/docs/en/hooks`.

---

## Confirmed Facts

### 1. Env vars and feature flag

| Variable | Value in operator's env | Effect |
|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | `true` (set in `~/.claude/.env`) | Enables the agent-teams feature globally |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | `50` (set in `~/.claude/.env`) | Unrelated to teams; controls compaction threshold |

The env var accepts `"1"` or `"true"`. It can alternatively live in `settings.json` under `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`. The operator has it set in `~/.claude/.env`, so it is **active for all sessions**.

Source: `~/.claude/.env` (directly read), `code.claude.com/docs/en/agent-teams`.

### 2. Local state

`~/.claude/.env` contents (secrets redacted):

```
CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=50
CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true
GITHUB_PERSONAL_ACCESS_TOKEN=<redacted>
```

No other agent-teams env vars are set in the operator's environment.

### 3. Feature introduction version

Agent teams shipped in Claude Code **v2.1.32** (changelog entry: "Added research preview agent teams feature for multi-agent collaboration").
Operator runs **v2.1.144** — well above the minimum.

Source: `~/.claude/cache/changelog.md` lines 2239-2240.

### 4. Settings keys confirmed in settings.json

From `~/.claude/settings.json`:

```json
"teammateMode": "in-process",
"agentPushNotifEnabled": true
```

The `teammateMode` key accepts `"auto"` (default), `"in-process"`, or `"tmux"`.
- `"auto"`: split panes if inside tmux, in-process otherwise
- `"in-process"`: all teammates run in the same terminal; navigate with Shift+Down
- `"tmux"`: each teammate gets its own tmux pane (requires tmux or iTerm2)

A per-session CLI override also exists: `claude --teammate-mode in-process`.

A second settings key, `teammateDefaultModel`, controls the default model for spawned teammates. It is not present in operator's settings — teammates currently default to inheriting nothing from the lead (the lead's current `/model` selection only carries over if you set this to `null` explicitly in `/config`).

Source: `code.claude.com/docs/en/settings`, `~/.claude/settings.json`.

### 5. Spawn lifecycle — how teammates are created

There are **two** spawn paths:

1. **Natural-language dispatch**: the operator (or lead) tells Claude in plain text to create a team. Claude proposes the team; the operator confirms; the lead spawns teammates. The lead calls the `Task`/`Agent` tool internally, not a new external CLI.
2. **Claude-initiated proposal**: if Claude judges the task benefits from parallel work, it may propose a team. Operator must confirm before spawning proceeds.

There is no "spawn teammate by name" slash command exposed to the user today. Spawning is mediated through the lead session's natural-language conversation.

Teammates are full, independent Claude Code sessions. Each has its own context window. Each loads project context (CLAUDE.md, MCP servers, skills) fresh — the lead's conversation history does NOT carry over.

Source: `code.claude.com/docs/en/agent-teams`.

### 6. Dispatch shape (from lead's perspective)

Internally the lead uses the **`SendMessage`** tool to communicate with running teammates, and **`Agent`/`Task`** tool calls to spawn new ones. From the changelog (v2.1.77):

> "The Agent tool no longer accepts a `resume` parameter — use `SendMessage({to: agentId})` to continue a previously spawned agent."
> "`SendMessage` now auto-resumes stopped agents in the background instead of returning an error."

The dispatch shape visible to a plugin/skill is:
- Spawn: lead calls `Agent({ subagent_type: X, prompt: P })` — always creates a new session
- Message: lead calls `SendMessage({ to: agentId, message: M })` — delivers to a running teammate
- Teammates are identified by **name** (lead assigns names at spawn time) and by session ID

Source: `~/.claude/plugins/marketplaces/fl03/skills/shepherd/pipeline.md` §XV-ter,
`~/.claude/cache/changelog.md` (v2.1.77 entry).

### 7. Team config storage — filesystem locations

```
~/.claude/teams/{team-name}/config.json   — team config + runtime state
~/.claude/tasks/{team-name}/              — per-task JSON files
```

The `config.json` holds: `members[]` (name, agent ID, agent type), session IDs, tmux pane IDs.
Tasks are JSON files with fields: `id`, `subject`, `description`, `activeForm`, `status`, `blocks[]`, `blockedBy[]`.

**Critical**: the team config is owned by the runtime. Do NOT pre-author or edit it by hand — it is overwritten on every state update. There is no project-level equivalent; `.claude/teams/` in a repo is treated as an ordinary directory.

Tasks directory (`~/.claude/tasks/`) is used by shepherd today for shctx-style task tracking. The operator's actual task files were confirmed at `/Users/jo3/.claude/tasks/d79fb2bf-.../`.

Source: `code.claude.com/docs/en/agent-teams` §Architecture, operator filesystem directly read.

### 8. Communication between teammates

- **Mailbox**: the platform provides a messaging system. Teammates send messages by calling `SendMessage({ to: name })`. Messages are delivered automatically to recipients — no polling required.
- **Shared task list**: all agents can read task status. Task claiming uses **file locking** to prevent race conditions when multiple teammates try to claim the same task simultaneously.
- **Idle notifications**: when a teammate finishes and stops, it automatically notifies the lead.
- **No live RPC**: there is no shared memory or live RPC bus. Communication is asynchronous via the mailbox and the task list.

Source: `code.claude.com/docs/en/agent-teams` §Context and communication.

### 9. Identity and lifecycle

- The lead assigns each teammate a **name** at spawn time. Names are predictable if you specify them in the spawn instruction.
- Teammates appear in the team config's `members[]` array with `name`, `agent_id`, and `agent_type`.
- Teammate session IDs are full UUIDs (same format as regular sessions — visible in `~/.claude/sessions/`).
- There are **no per-teammate config files** beyond the team config. Teammates cannot have different `settings.json` sections; they inherit the lead's permission mode.
- You can change individual teammate permission modes **after spawn** but not at spawn time.

Source: `code.claude.com/docs/en/agent-teams` §Architecture, §Permissions.

### 10. Logs and transcripts per teammate

Each teammate is a full Claude Code session. Its transcript lives in the standard location:
`~/.claude/projects/<project-path>/<session-uuid>.jsonl`

There is no separate log namespace for teammates vs. regular sessions. Shepherd's ctx shctx event logs would need to key on session ID to distinguish teammate transcripts from non-teammate ones.

Source: inferred from daemon roster (`~/.claude/daemon/roster.json`), which shows `sessionId` per worker.

### 11. Failure modes

From the official limitations section:

- **No session resumption with in-process teammates**: `/resume` and `/rewind` do not restore in-process teammates. After resuming, the lead may attempt to message teammates that no longer exist. Platform offers no auto-recovery.
- **Task status can lag**: teammates sometimes fail to mark tasks as completed, which blocks dependent tasks. Manual nudge or lead intervention required.
- **Shutdown is slow**: teammates finish their current request before shutting down. No hard kill is available from the lead.
- **One team at a time**: a lead can only manage one team. Must clean up before creating another.
- **Orphaned tmux sessions**: if a tmux session persists after team ends, must be killed manually.

From the changelog (v2.1.50): "Fixed memory leak in agent teams where completed teammate tasks were never garbage collected from session state." This is fixed in current version.

Source: `code.claude.com/docs/en/agent-teams` §Limitations.

### 12. Nesting — can a teammate spawn its own teammates?

**No.** Explicitly listed as a hard limitation:

> "No nested teams: teammates cannot spawn their own teams or teammates. Only the lead can manage the team."

Teammates CAN dispatch regular subagents via the `Agent` tool. The changelog explicitly patched this: "Fixed teammates accidentally spawning nested teammates via the Agent tool's `name` parameter" (v2.1.xx). The fix prevents accidental nesting; intentional nesting was never allowed.

Source: `code.claude.com/docs/en/agent-teams` §Limitations, `~/.claude/cache/changelog.md` line 1829.

### 13. Hooks available for teammate lifecycle

Three hook events exist:

| Hook event | When it fires | Can block? | Payload fields added |
|---|---|---|---|
| `TeammateIdle` | Teammate about to go idle | Yes (exit 2 or `{continue:false}`) | `teammate_name`, `teammate_type` |
| `TaskCreated` | Task being created via `TaskCreate` | Yes | `task_id`, `task_title`, `task_description`, `assignee` |
| `TaskCompleted` | Task being marked complete | Yes | `task_id`, `task_title`, `task_result`, `assignee` |

These hooks were added in v2.1.33: "Added `TeammateIdle` and `TaskCompleted` hook events for multi-agent workflows."

Source: `code.claude.com/docs/en/hooks`, `~/.claude/cache/changelog.md` line 2222.

### 14. Operator's current setup

- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true` — **active**
- `"teammateMode": "in-process"` — **active** (in `~/.claude/settings.json`)
- `"agentPushNotifEnabled": true` — **active** (push notifications for agent completion)
- Claude Code v2.1.144 — well above minimum v2.1.32
- Agent teams feature is **enabled and configured** but has never been exercised in shepherd flows (confirmed by seed file line 22: "configured locally but not yet exercised in shepherd flows")
- No `~/.claude/teams/` directory exists — confirms no team has been created yet

---

## Likely Behaviors

These are inferred from documentation + changelog but not directly observed via a live team session:

1. **Task file locking is the native concurrency primitive** for cross-session coordination. Shepherd's shctx lock primitives (SQLite-based, `cmd_lock.sh`) are orthogonal to the platform's task file locking. Both can coexist — they lock different resources.

2. **In-process mode is the right default for shepherd's use case**. Split-pane mode adds tmux dependency; the operator's current setting of `"in-process"` is appropriate.

3. **Session resume is broken for in-process teammates**. This is a hard limitation. If a shepherd sprint is interrupted mid-parallel-run and the operator resumes, orphaned teammate references will exist in the lead's context but the actual sessions will be gone. A recovery path is needed.

4. **The `agent_type` field controls persona, not tool access** (except for the `tools` allowlist in subagent definitions). For shepherd's flock (engineer, critic, coder, auditor, worker, discovery), these agent definitions (`agents/*.md`) can be referenced in the spawn instruction and will be loaded as the teammate's system prompt extension.

5. **Custom agent `model` frontmatter is now honored** at spawn time (fixed in v2.1.47, changelog line 2089). Shepherd's agents that declare `model: opus` in their frontmatter will get that model when spawned as teammates — this is good for the engineer agent.

6. **`SendMessage` auto-resumes stopped agents** (since v2.1.77). If a teammate stops between shepherd pipeline stages, the lead can resume it with `SendMessage` without manual intervention.

---

## Unknowns

These questions could not be resolved from available sources:

1. **What is the exact `agent_type` value for shepherd's named agents?** When the lead spawns "an engineer teammate using the engineer agent definition," does `teammate_type` in the `TeammateIdle` hook payload show `"engineer"` or the full qualified name? This matters for hook routing.

2. **Task file format stability**. The task JSON schema visible in `~/.claude/tasks/` uses fields (`id`, `subject`, `description`, `activeForm`, `status`, `blocks`, `blockedBy`). Are these the same fields as the agent-teams task list, or is the agent-teams task list a different format stored in `~/.claude/tasks/{team-name}/`? The docs say team tasks live at `~/.claude/tasks/{team-name}/` — shepherd's shctx tasks live at `~/.claude/tasks/{project-uuid}/`. They likely do not conflict, but this should be verified.

3. **Heartbeat / stale-teammate detection**. The docs mention teammates notify the lead when they go idle, but there is no documented heartbeat mechanism. If a teammate crashes (SIGKILL, OOM), the lead may not get notified. The `TeammateIdle` hook fires on graceful idle, not on crash. This is a failure-mode gap.

4. **Can the `TaskCreate` tool be called from a shepherd hook script** (bash, not Claude context)? The docs describe teammates calling `TaskCreate` tool, not bash calling an API. For shctx integration, tasks may need to be written directly to the task JSON files rather than via the tool.

5. **Cross-project team configs**. If two shepherd sprints run in different worktrees of the same project, do they share the same `~/.claude/teams/{name}/` namespace? The team name is presumably set by the lead at creation time. Namespace collisions are possible.

6. **`TeammateIdle` vs. `Stop` hook ordering**. When a teammate finishes its work and goes idle, does `TeammateIdle` fire before or after the teammate's own `Stop` hook? The dev-order merge gate in the seed proposes hooking `Stop` to write a `ready` row — is `TeammateIdle` a better trigger point (runs in the lead's context) vs. `Stop` (runs in the teammate's context)?

---

## Recommended Escalation Channel Design

Given these findings, the seed's "registry-mediated async coordination" design is validated. Refined recommendation:

### Primary coordination: shctx SQLite registry (as seeded)

The `parallel_assignments`, `parallel_locks`, and `parallel_ready` tables proposed in the seed are the right design. Platform provides no cross-session shared memory or database. The operator's SQLite registry is the correct canonical store.

### Teammate identity in the registry

Use the teammate's **name** (assigned by the lead at spawn time) as the `teammate_id` in the registry. This is the stable identifier that persists for the lifetime of the team session. Session UUIDs change on resume; names do not.

### Hook integration: use `TeammateIdle` at the lead level

For the dev-order merge gate, **`TeammateIdle`** (firing in the lead's context) is preferable over a `Stop` hook in the teammate's context because:

- It fires in the lead — the entity that manages the team and has authority to trigger merges
- It receives `teammate_name` and `teammate_type`, which map directly to the sprint slot in the registry
- It can block the idle (exit 2) to send feedback, which is cleaner than a Stop hook that can't message the lead

**Recommended gate script pattern:**

```bash
# TeammateIdle hook
#!/usr/bin/env bash
# Fires in the LEAD's context when a teammate goes idle
teammate_name=$(echo "$CLAUDE_HOOK_INPUT" | jq -r '.teammate_name')
# 1. shctx parallel ready --sprint="${teammate_name}"
# 2. Check if predecessors are all merged
# 3. If yes: exit 0 (allow idle, lead handles merge)
# 4. If no: echo "Predecessor sprints not yet merged" >&2; exit 2 (keep working)
```

### Failure recovery path (unknown #3 gap)

Because there is no heartbeat and crashes do not trigger `TeammateIdle`, add a `heartbeat` column to `parallel_assignments`. Each teammate's conductor should write a heartbeat row on every subagent dispatch (via a `PostToolUse` hook, not `Stop`). The lead's `TeammateIdle` gate should reject idle if the last heartbeat is stale beyond threshold. This does not cover crash — but it surfaces staleness.

### Resume recovery

Since in-process teammate sessions do not survive `/resume` (confirmed limitation), add a `status=orphaned` sentinel to `parallel_assignments` when the registry detects that a teammate's session ID no longer exists in `~/.claude/sessions/`. The lead's next `TeammateIdle` or recovery run can detect orphaned rows and spawn replacement teammates at the same slot.

---

## Maturity Verdict

**The agent-teams API is real, enabled, and partially usable — but carries experimental caveats that constrain the v5.1.4 scope.**

**What is mature enough to ship:**

- Registry-mediated coordination (shctx `parallel_assignments`, `parallel_locks`, `parallel_ready`) — this is fully under shepherd's control and does not depend on any experimental API
- `shctx parallel propose` / `parallel join` / `parallel status` commands — useful even without teammates, and future-safe when teammates mature
- `TeammateIdle`, `TaskCreated`, `TaskCompleted` hooks — stable hook events (added v2.1.33, multiple fixes shipped since, present in v2.1.144)
- `SendMessage` auto-resume (v2.1.77+) — makes conductor→teammate messaging reliable

**What is not yet mature enough to depend on:**

- **Session resumption across teammate sessions** — explicitly broken (no `/resume` support for in-process teammates). A shepherd sprint that spans hours with operator interruptions WILL leave orphaned teammate references. The registry must carry recovery state.
- **Heartbeat / crash detection** — no platform support. Must be shimmed in shctx.
- **Nested teammate dispatch** — hard no (explicit limitation). Shepherd's sub-sprint dispatch from a coder stays as subagents via `Agent` tool, not nested teammates.
- **One-team-at-a-time constraint** — a shepherd session cannot have two parallel team sessions running simultaneously. This limits `/shepherd:parallel` to one active manifest per lead session.

**Bottom line:** Ship the `propose`/`join`/`status` command rework + registry schema extension as v5.1.4. Wire the `TeammateIdle`/`TaskCompleted` hooks. Add orphan-recovery logic. Do NOT depend on in-process teammate session durability — use the registry as the source of truth, not teammate process continuity. The seed's "No live RPC between teammates" non-goal is correct and should be held.

The v5.1.4 sprint can proceed to plan authoring. The engineer should treat in-process session fragility as a design constraint, not a blocker.
