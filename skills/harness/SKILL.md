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

**Now more load-bearing, unchanged in substance (#255, #263).** The #263
inversion means more tiers author `agent()` calls directly — root, a
teammate-`@conductor`, and a self-contained `@engineer` alike, not root
only — so this pin discipline widens with them rather than relaxing:
`workflow_model_guard.sh`'s refusal reach widens from root-only to root +
conductor + engineer, i.e. every tier that may now compile a Workflow
script (`DISPATCH-MODEL-UNPINNED`, `DISPATCH-MISSING-SUBAGENT-TYPE`,
`WORKFLOW-OFF-FLOCK` all widen the same way). Author every call through the
`flockAgent()` wrapper (`skills/shepherd/SKILL.md §Dispatch law`).

The Workflow tool is top-level, NOT deferred and NOT an MCP tool — see
`## ToolSearch` for why it is never a `ToolSearch` target.

**Fan-out vehicle: the Dynamic Workflow, at every tier holding the grant
(#263).** `Workflow` ships in the `tools:` frontmatter of `@conductor` and
`@engineer` (#233) and that grant is LIVE: the 6.3.9-era reading of
`Workflow` as a TOP-LEVEL-SESSION-only primitive — "hard-denied inside a
subagent," REGARDLESS of `tools:` frontmatter — is RETIRED as the standing
instruction (#263). A team lead — root, a teammate-`@conductor`, or a
self-contained `@engineer` — drives its OWN fan-out, and the vehicle is a
compiled Dynamic Workflow, never a hand-rolled batch of individual
`Agent()` calls, at any tier whose probe (`## Tool presence`, below) finds
the literal token `Workflow` present in its own visible tool list. Agent
Teams docs §Limitations: a teammate cannot spawn its own TEAM and teams/
workflows do not nest — re-scoped per #263, that limitation is about the
TEAM primitive (a teammate spawning a nested TEAM), NOT about calling the
`Workflow` tool, and it stands unchanged; the main session is the fixed
lead (never reassigned, no lead handoff) — unchanged. Teammates CAN spawn
nested subagents via the `Agent` tool (up to 5 levels) — unchanged — and,
separately, CAN now compile their own Dynamic Workflow once their own probe
confirms the grant is live. CONSEQUENCE (#263): every lead tier holding the
grant compiles its own fan-out — root drives root-tier/cross-lane
Dynamic-Workflow fan-out (`/shepherd:start`, `agents/shepherd.md`); a
teammate-conductor or self-contained engineer compiles its OWN lane's
Dynamic Workflow the same way. In-context `Agent()` fan-out — the whole
`parallel_with` clique fired in ONE `Agent` message (bounded-concurrent),
the same batch shape `shctx graph compile` would emit — is now the
DOWNGRADE path: taken only on a confirmed genuine absence (`## Tool
presence`, below) and always recorded with a `fanout_downgrade_reason`,
never the default first-class teammate-tier mode it was read as under the
pre-#263 doctrine.

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

**The probe is the oracle, at every tier (`WORKFLOW-VEHICLE-PROBE`, #263).**
A subagent's or teammate's `tools:` frontmatter listing `Workflow` controls
what the platform OFFERS that role at dispatch; whether the role may
actually invoke it at runtime is answered by ONE platform-level test, run
by the role itself, once per session, before its FIRST fan-out: is the
literal token `Workflow` present in YOUR OWN visible tool list? That
question — not the 6.3.9-era standing assumption that a spawned role is
hard-denied regardless of frontmatter — is the oracle, at root, at a
teammate-`@conductor`, and at a self-contained `@engineer` alike (#263).
The agent itself, not any hook, is the authoritative check, for
`TaskCreate`/`SendMessage` anywhere and for `Workflow` at every tier:

- **Present** → the grant is live; compile and dispatch a Dynamic Workflow.
  This is the default and the expected outcome at every lead tier holding
  the grant.
- **Genuinely absent** (the token is not in the visible tool list) → fan
  out in-context via `Agent(...)` instead — the whole `parallel_with`
  clique in ONE message — and record the downgrade with a reason
  (`fanout_downgrade_reason`); a SILENT downgrade at a grant-holding tier
  is a wave-review finding (`FANOUT-VEHICLE-DOWNGRADE`).

**Never `ToolSearch` for the answer** (`WORKFLOW-PROBE-WRONG-INDEX`; agrees
exactly with `## ToolSearch`, above). `ToolSearch` resolves DEFERRED tools
only; `Workflow` is a native top-level primitive, so a `ToolSearch`
nothing-result on it means the wrong index was queried, NEVER that the
tool is absent. The visible tool list is the only valid oracle, at any
tier — this code REPLACES `WORKFLOW-SELFCHECK-TOOLSEARCH`: what was and
remains forbidden is the WRONG PROBE, never the act of probing.

Note on #251 (open, NOT resolved by #263): whether an unavailable
`Workflow` would present as "denied at invocation" or "invisible to
discovery" is still an unsettled measurement dispute. The probe above is
deliberately agnostic to that answer — it tests the visible tool list,
which is correct under either reading — and the downgrade path handles the
negative case with a recorded reason regardless of which failure mode is
eventually confirmed. Do not assert either reading as settled fact anywhere
in this file.

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
