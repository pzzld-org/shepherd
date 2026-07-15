---
name: harness
description: Claude Code platform capability map — Agent Teams, Workflow tool, /loop, /goal, ToolSearch scope, tool presence, capability enforcement. Use when reasoning about what the platform itself can do.
---

# Harness — Claude Code platform capability map

Optional load. This skill states platform FACTS only — what Claude Code itself
provides — never shepherd behavior. Shepherd's ownership/anti-pattern mapping
onto these primitives lives in `skills/shepherd/references/flock.md`
`## Teammate bridge`; load that skill for shepherd-specific rules. Every fact
below is research-verified 2026-07-06 against the live docs cited per section.

## Agent Teams

Experimental, opt-in: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (env var or
`settings.json`), platform version v2.1.32+.

As of v2.1.178+: the `TeamCreate`/`TeamDelete` tools NO LONGER EXIST. A
teammate spawns via a natural-language lead instruction referencing a
subagent definition — no setup-tool call, no per-teammate config at spawn
beyond the subagent-definition reference and model pin. The team forms when
the first teammate spawns and is cleaned up automatically on session exit.

MUST-know constraints (the 6 platform Limitations plus load-bearing facts):
- NO nested teams — one team per lead; a session that already owns a team
  refuses a second.
- The LEAD is fixed — the session that spawned the team cannot be
  reassigned; no lead handoff.
- Teammates are LOST on `/resume` — in-process teammates do not restore;
  resuming a session starts fresh with no live teammates.
- Task status CAN LAG — the platform exposes no rich, real-time teammate
  status; treat any status read as possibly stale.
- Shutdown is SLOW — tearing down a team is not instant; never assume a
  team is gone the instant a stop is issued.
- The lead's permission mode is inherited by every teammate; no
  per-teammate permission override at spawn.
- No per-teammate identity env var exists — a teammate session sees only
  `CLAUDECODE` + `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`; teammate identity
  (`teammate_name`) arrives ONLY in hook-input JSON (`TeammateIdle`, `Task*`
  events), never an env var a script reads.
- `team_name` is a dead discriminator since v2.1.178 — the platform accepts
  but ignores it.
- Lead↔teammate channel is `SendMessage` (address a teammate by name); a
  shared task list (`TaskCreate`/`TaskUpdate`/`TaskGet`/`TaskList`) is
  available but unreliable — treat it as a best-effort MIRROR, never the
  system of record. The registry (SQLite: `shctx graph`/focus) is the
  authority for sprint/lane/wave state; a `Task*` failure degrades to the
  registry and NEVER blocks progression.
- Display mode is observability-only and NEVER required: tmux is an
  optional display mode, not a dependency of teammate-spawn — enum
  `teammateMode: in-process | tmux | auto`.
- Plan approval mode for teammates is a distinct, per-teammate, read-only
  platform feature — not a sprint-level plan-approval gate a caller layers
  on top.
- Subagent-definition reference at spawn (a teammate referencing a named
  subagent def, inheriting its `tools` allowlist + `model`, body appended
  to the system prompt) does NOT apply that definition's `skills`/
  `mcpServers` frontmatter — referencing a subagent-as-teammate silently
  strips that config. Before relying on this path, verify EVERY frontmatter
  field of the subagent definition survives the platform's teammate-spawn
  transformation; never assume parity with a direct subagent dispatch.

Doc: `https://code.claude.com/docs/en/agent-teams`

## Workflow tool

A top-level tool that runs a JavaScript orchestration script (`agent()`,
`parallel()`, `pipeline()`, `phase()`) to fan out subagents in the background
and return one consolidated result. Intermediate results live in script
variables, not conversation context.

Hard caps: ~16 concurrent agents; 1,000 total dispatches per run. Subagents
spawned from inside a Workflow run under `acceptEdits` (auto-approved edits)
— a read-only or scope-restricted role running inside a Workflow MUST enforce
its restriction via tool allowlist, never via permission mode (see
`## Capability enforcement`).

**Model pin, mandatory (#178).** The platform default is to OMIT `model:` on
`agent()` and let the call inherit the main-loop model — shepherd's operator
law inverts that: every dispatched subagent = sonnet unless explicitly
overridden. Every `agent()` call MUST carry `model:` or
`agentType: "shepherd:<role>"` resolved from the single `[models]` map
(`skills/context/references/model-map.md`), mechanically enforced by
`hooks/scripts/workflow_model_guard.sh` (`PreToolUse(Workflow)`,
`WORKFLOW-MODEL-PIN-MISSING`) — the same discipline `dispatch_guard.sh`
already holds Agent/Task dispatches to, extended to the one primitive it
cannot see (a Workflow script's internal spawns never re-enter that hook).

The Workflow tool is top-level, NOT deferred and NOT an MCP tool — see
`## ToolSearch` for why it is never a `ToolSearch` target.

Doc: `https://code.claude.com/docs/en/workflows`

## Loops

`/loop` runs a prompt or command on a recurring interval. Two pacing modes:
- Fixed interval: 30 seconds to 1 day.
- Self-paced (dynamic): the harness computes the next wake via
  `ScheduleWakeup`, cache-window-aware, in the 1-minute-to-1-hour range.

Self-paced loops expire after 7 days. Loop state persists at `.claude/loop.md`
and MUST stay ≤25KB.

Per-role loop templates (which agent runs which loop shape, with what cap)
are cataloged in `skills/harness/references/loop-templates.md`; the
discipline contract governing when/how a flock agent iterates lives in
`skills/motivation/SKILL.md` `## Loop discipline` — one-line restatement
only, not duplicated here.

Doc: `https://code.claude.com/docs/en/scheduled-tasks`

## Goals

`/goal` (v2.1.139+) arms one durable objective the harness's small-model
evaluator checks against every turn. Hard limits: ONE goal per session; text
capped at 4000 characters. A goal survives `--resume` and auto-clears on
completion. `/goal` is LEAD-SESSION ONLY — it is never available to a
teammate or a subagent; a spawned session cannot arm its own `/goal`.

Doc: `https://code.claude.com/docs/en/goal`

## ToolSearch

`ToolSearch` resolves DEFERRED tool calls only — MCP tools
(`mcp__github__*`, `mcp__sentry__*`, …) and on-demand utility tools the
harness surfaces on request. That is its entire job. Two categories are
NEVER `ToolSearch` targets:

1. **Subagents, teammates, specialists.** An agent type is not a tool.
   Discover it from the visible available-agents system-reminder list;
   dispatch via `Agent({subagent_type})` or the native teammate-spawn
   instruction. `ToolSearch select:<any-agent-type>` returns nothing or
   errors by design — a nothing-result is NEVER evidence the agent is
   absent.
2. **Native orchestration primitives** — `Agent`, `Workflow`,
   `TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate`, `SendMessage`, plus
   `Bash`/`Edit`/`Read`/etc. All top-level, called directly.
   `ToolSearch select:TaskCreate` even errors — expected, because
   `TaskCreate` is native, not deferred.

Rule of thumb: agents come from the visible available-agents list; native
primitives are called directly; `ToolSearch` is only for deferred MCP/utility
tool calls. A `ToolSearch` nothing-result on an agent type or a native verb
means the wrong index was queried — NEVER absence.

## Tool presence

NEVER `ToolSearch` for `Workflow`, `TaskCreate`, or `SendMessage` — restated
here because this is the single most consequential absence-vs-wrong-index
confusion on the platform. The `Workflow` tool is enabled across every
entrypoint (CLI, web, remote, cloud-container) as of the v2.1.154 floor.
Genuine absence exists ONLY on an explicit disable
(`disableWorkflows` / `CLAUDE_CODE_DISABLE_WORKFLOWS`) or a build below that
floor — no entrypoint omits it by default.

The agent itself, not any hook, is the authoritative check: is the literal
token `Workflow` (or `TaskCreate`, `SendMessage`) present in your visible
tool list? If yes, call it directly. Only a CONFIRMED genuine absence
degrades to an in-context `Agent(...)` fan-out as fallback.

## Lazy-load economics

Skill, agent, and command BODIES load only on invoke or dispatch. At session
start, only their frontmatter `description` field is resident — that is the
entire startup cost of an unused skill or agent. A skill split into six
narrow files (shepherd/adaptation/motivation/harness/thinking/context) costs
one description line per unused skill, not six bodies. This is why
frontmatter `description` MUST stay ≤200 chars and load-bearing: it is the
only text every session pays for, whether or not the skill is ever used.

Doc: `https://code.claude.com/docs/en/skills`,
`https://code.claude.com/docs/en/sub-agents`

## Capability enforcement

The canonical 3-layer pattern any read-only or scope-restricted role (e.g.
`@auditor`, `@discovery`) composes to enforce its restriction — do not invent
a fourth mechanism:

1. **Allowlist** — the role's `tools:` frontmatter grants only the verbs it
   needs; a read-only role's `tools:` list MUST NOT include `Write`/`Edit`.
2. **Path-scope PreToolUse hook** — a hook (e.g. `lock_guard.sh`) denies
   writes outside the role's declared write-path convention, independent of
   what the allowlist alone would permit. This is what catches a write
   inside a Workflow's `acceptEdits` context, where permission mode alone
   would not stop it (see `## Workflow tool`).
3. **Lint** — a static check (e.g. `lint_agent_capabilities.sh`) verifies an
   agent file's `tools:` grant matches its actual tool usage, catching drift
   between the two over time.

Which roles run which hook, and the per-role write-path conventions
themselves, are owned by `skills/shepherd/references/flock.md` `## @auditor`
and `## @discovery` — this section owns only the generic 3-layer shape.

Doc: `https://code.claude.com/docs/en/hooks`

## Stop hook

`hooks/scripts/coordinate_drive_guard.sh` registers on the `Stop` event. It is
the ONLY shepherd `Stop` consumer that returns `{"decision":"block"}` from a
command hook — every other shepherd `Stop` consumer (`deliverable_check.sh`,
plus two `type: "agent"` hooks for wave-gate cherry-pick and close-finalize)
either warns or lets the stop proceed.

Mechanics, exact:
- Fast-path: outside a spawn session (no live teammates), the hook exits 0
  immediately — zero cost when spawn is not in play.
- Runaway-bounded: a 2-nudge cap per session. Past the cap the hook fails
  open (exit 0) regardless of state; the counter resets once the actionable
  state clears.
- Fails open on any error: a missing DB, missing `sqlite3`, malformed
  payload, or any other error → exit 0, never a block.
- Config: `[spawn].coordinate_drive_guard` — `block` (default) / `warn`
  (stderr only, never blocks) / `off` (fast-path exit always).

The behavioral drive contract this hook backstops (wake→act→probe→yield,
FOCUS-HEARTBEAT) is owned by `skills/motivation/SKILL.md` `## Drive contract`
— this section owns only the hook's own mechanics.

Doc: `https://code.claude.com/docs/en/hooks`
