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
- `Agent(subagent_type, name)` **is** the teammate-spawn primitive — the
  lead's natural-language "spawn a teammate" instruction resolves to this
  call. `name` (not `team_name`) is the live discriminator: it "makes it
  addressable via `SendMessage`" and is what lands a dispatch as a teammate
  instead of an ephemeral subagent. There is no separate tool-free "native"
  spawn path distinct from `Agent` (DF-02, measured live this sprint).
- **Roster is FLAT — no nested teammates.** A teammate that calls
  `Agent(subagent_type, name=...)` to dispatch its own sub-flock is refused
  outright: "Teammates cannot spawn other teammates — the team roster is
  flat." A teammate MUST omit `name` when dispatching its own flock; that
  dispatch lands as an ordinary subagent, never a nested teammate (DF-02).
- **Async `Agent()` notifications route to the task-tree owner, not the
  dispatcher.** The completion `<task-notification>` for a background
  `Agent()` call delivers to whichever session owns that task tree, which
  is not always the agent that issued the call. Measured with `Workflow`
  itself absent from the dispatching teammate's own tool list, so this is a
  fact about `Agent()`/task-tree ownership, never a `Workflow`-specific
  behavior (DF-11).
- Lead↔teammate channel is `SendMessage` (address a teammate by name); a
  shared task list (`TaskCreate`/`TaskUpdate`/`TaskGet`/`TaskList`) is
  available but unreliable — treat it as a best-effort MIRROR, never the
  system of record. The registry (SQLite: `shctx graph`/focus) is the
  authority for sprint/lane/wave state; a `Task*` failure degrades to the
  registry and NEVER blocks progression.
- Display mode is observability-only and NEVER required: tmux is an
  optional display mode, not a dependency of teammate-spawn — enum
  `teammateMode: in-process | tmux | auto`. `teammateMode` is read at SPAWN
  time, never at session start: changing it in `~/.claude/settings.json`
  mid-session takes effect on the very next spawn — no lead relaunch
  required (DF-68).
- **Pane-backed teammates live on a PRIVATE tmux socket, keyed to the
  lead's OS PID — never the default socket.** Claude Code spawns them with
  `tmux -L claude-swarm-<lead-pid> new-session -d -s claude-swarm -n
  swarm-view -P -F #{pane_id} -- cat`, observed verbatim in `ps`. Bare
  `tmux ls` reads the DEFAULT socket (`/private/tmp/tmux-501/default` on
  macOS) and reports "no server running" regardless of how many pane
  teammates are live — a FALSE NEGATIVE BY CONSTRUCTION, never evidence of
  in-process fallback. The correct oracle is `tmux -L claude-swarm-<lead-
  pid> ls` plus the `backendType`/`tmuxPaneId` fields per member in
  `~/.claude/teams/<team>/config.json` (DF-68).
- **A `backendType: tmux` teammate is a separate CLI process** — its own
  `claude` invocation, its own MCP servers, its own hooks, its own
  `caffeinate` — never a subagent living inside the lead's Node process.
  That makes it a MAIN session, not a subagent (DF-68).
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

**Fan-out vehicle is SUBSTRATE-conditional, never tier-conditional (#263,
corrected).** `commands/spawn.md:73` (Check 1, substrate verification)
states the discriminator and is now canonical for the whole tree; this
section derives from it, not the reverse. The axis is the substrate a role
is actually running on when it fans out, never its tier:

- **Agent-Teams teammate** — `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` set
  in the lead's environment, spawned via `Agent(subagent_type, name=...)`
  (the normal condition for `@conductor` and `@engineer` under
  `/shepherd:spawn`): `Workflow` MAY work — run `WORKFLOW-VEHICLE-PROBE`
  and act on what it reports, never on the `tools:` frontmatter grant
  (`## Tool presence`, `DF-E1`, below). Present → fan out via a compiled
  Dynamic Workflow, the same vehicle root uses. Genuinely absent → this is
  now the EXPECTED result for a teammate, not an anomaly to explain away
  (DF-02/DF-11, measured live this sprint against `@conductor`'s and
  `@engineer`'s own frontmatter grant of `Workflow`); record
  `fanout_downgrade_reason` as routine bookkeeping and fan out via
  in-context `Agent()`, same as the subagent case below.
- **Agent-tool subagent** — dispatched via `Agent(...)`, INCLUDING a
  "teammate" spawned when the Agent-Teams substrate was absent at spawn
  time, which is silently just a subagent wearing a teammate's brief:
  `Workflow` is genuinely denied. In-context `Agent()` fan-out — the whole
  `parallel_with` clique fired in ONE `Agent` message (bounded-concurrent)
  — is correct here and is the ONLY option this substrate has. This is NOT
  a downgrade to apologize for; it is the right answer for a subagent.

**The mechanism behind "MAY work," measured not reasoned (DF-68).** A
`backendType: tmux` teammate is a separate CLI process — a MAIN session
(`## Agent Teams`, above) — which sits OUTSIDE the sub-agents-only tool
filter documented at `/docs/en/sub-agents` that strips `Workflow`; a
`backendType: in-process` teammate is a subagent living inside the lead's
own process and DOES hit that filter. So `backendType`, not "is this
nominally a teammate," is the variable that actually controls
`Workflow`/`ScheduleWakeup` availability — confirmed live: teammate
`shepherd-probe-v645-wf` (`backendType: tmux`) carried both tools and its
`Workflow` call was ACCEPTED, `Run ID: wf_020292db-fef`, no error, and the
inner `shepherd:worker` agent it dispatched returned exactly `PROBE-OK` —
a full round trip, not just an accepted-but-unverified call. This is WHY
`WORKFLOW-VEHICLE-PROBE` (`## Tool presence`, below) is correct even
though it never reasons about `backendType` directly — the visible tool
list is a faithful proxy for the backend that produced it.

**Measured, not quoted (#263).** Two genuine teammate sessions in the
`FL03/axiom` corpus (`79a8e11a`, `cfeec725`, identified by a rendered
`<teammate-message>` boot brief), on CC **2.1.210** — two patches BELOW the
2.1.212 our prior doctrine cited as the version that denies them — made 3
`Workflow` calls total, all three returning `Workflow launched in
background` with their own `subagents/workflows/wf_*` transcript dirs.
Zero denials anywhere in the corpus; the only `is_error` on any `Workflow`
call is an unrelated JavaScript parse error. The platform message
`"Workflow is not available inside subagents"` (originally logged at #220,
CC 2.1.212) is TRUE and STAYS TRUE — it is a fact about Agent-tool
subagents. Our error was generalizing it to "any spawned role," which
silently folded the teammate branch into the subagent branch and every
downstream doc inherited it. The denial and the measured working calls are
NOT in tension: they describe two different constructs, not one construct
in two states.

Agent Teams docs §Limitations: a teammate cannot spawn its own TEAM and
teams/workflows do not nest — that limitation is about the TEAM primitive
(a teammate spawning a nested TEAM), NOT about calling the `Workflow` tool,
and it stands unchanged; the main session is the fixed lead (never
reassigned, no lead handoff) — unchanged. Teammates CAN spawn nested
subagents via the `Agent` tool (up to 5 levels) — unchanged — and, on a
live Agent-Teams substrate, CAN compile their own Dynamic Workflow
directly, confirmed by their own probe (`## Tool presence`, below).
**CONSEQUENCE (#263):** root — always the top-level session, never a
subagent, so its substrate is never in question — a teammate-`@conductor`
on a live substrate, and a self-contained `@engineer` on a live substrate
each compile their OWN fan-out as a Dynamic Workflow (root drives
root-tier/cross-lane fan-out via `/shepherd:start`, `agents/shepherd.md`;
a teammate-conductor or self-contained engineer compiles its OWN lane's
Dynamic Workflow the same way). A role actually running as an Agent-tool
subagent — substrate absent at spawn, whatever its brief calls it —
dispatches in-context via `Agent()` instead; that is the correct,
first-class, ONLY vehicle available on that substrate, taken on a
confirmed genuine absence (`## Tool presence`, below) and recorded via
`fanout_downgrade_reason` for traceability — never a shortcut, and, on
this substrate, never a finding.

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
   dispatch via `Agent({subagent_type})` — add `name` to land the dispatch
   as an addressable teammate, omit it for an ephemeral subagent; there is
   no separate "native teammate-spawn" tool, only this one primitive with
   or without `name` (DF-02). `ToolSearch select:<any-agent-type>` returns
   nothing or errors by design — a nothing-result is NEVER evidence the
   agent is absent.
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
floor — no entrypoint omits it by default. That floor governs whether the
platform ships the tool at all; it does NOT settle which of the two
substrates below a given session is running on.

**The probe is the oracle — it confirms SUBSTRATE, never a dormant grant
(`WORKFLOW-VEHICLE-PROBE`, #263).** A subagent's or teammate's `tools:`
frontmatter listing `Workflow` controls what that role's DEFINITION is
offered at dispatch; whether the running session can actually invoke it is
a fact about which construct it is, and that is answered by ONE
platform-level test, run by the role itself, once per session, before its
FIRST fan-out: is the literal token `Workflow` present in YOUR OWN visible
tool list? Present means you are on a live Agent-Teams teammate substrate.
Genuinely absent means you are an Agent-tool subagent, whatever your brief
calls you. This is not "is my dormant grant live" — that framing belonged
to the retired tier axis and implied a probabilistic gap no platform
version actually has — it is "which of the two constructs am I," asked and
answered fresh by root, by a teammate-`@conductor`, and by a
self-contained `@engineer` alike (#263). The agent itself, not any hook,
is the authoritative check, for `TaskCreate`/`SendMessage` anywhere and for
`Workflow` on either substrate:

- **Present** → you are a teammate on a live Agent-Teams substrate; compile
  and dispatch a Dynamic Workflow. This is the default and the expected
  outcome for `@conductor`/`@engineer` under `/shepherd:spawn`.
- **Genuinely absent** (the token is not in the visible tool list) → you
  are an Agent-tool subagent; fan out in-context via `Agent(...)` instead —
  the whole `parallel_with` clique in ONE message — and record the
  substrate via `fanout_downgrade_reason`. On THIS substrate that is the
  correct, only-available vehicle and not a finding. `FANOUT-VEHICLE-
  DOWNGRADE` fires only for the other case: a role confirmed on a LIVE
  teammate substrate that hand-rolls in-context fan-out anyway, silently or
  not.

**Never `ToolSearch` for the answer (`WORKFLOW-SELFCHECK-TOOLSEARCH`; agrees
exactly with `## ToolSearch`, above).** `ToolSearch` resolves DEFERRED tools
only; `Workflow` is a native top-level primitive and never a `ToolSearch`
target by construction, so a `ToolSearch select:Workflow` null result is a
FALSE NEGATIVE BY CONSTRUCTION — it comes back null whether or not the tool
is actually callable, so it establishes NOTHING, neither presence nor
absence, and is not evidence the tool is "discovery-invisible." The visible
tool list is the only valid oracle, on either substrate. Past failure this
code exists to prevent: a session `ToolSearch`'d "workflow," found nothing,
and wrongly concluded the tool was absent.

**Same invalid-oracle class, one substrate probe over (DF-68).** Bare
`tmux ls` reads the DEFAULT socket and reports "no server running"
regardless of how many pane teammates are actually live — a FALSE NEGATIVE
BY CONSTRUCTION, exactly like `ToolSearch select:Workflow` above: a probe
that comes back null whether or not the thing exists, misread as absence.
Claude Code spawns pane teammates on a PRIVATE socket keyed to the lead's
OS PID (`## Agent Teams`, above); `tmux -L claude-swarm-<lead-pid> ls` plus
the `backendType` field in `~/.claude/teams/<team>/config.json` is the only
valid oracle.

**#251 resolved by #263, not open.** #251's "invisible to discovery"
measurement was taken with `ToolSearch` against a native tool (a guaranteed
null regardless of true state — see `WORKFLOW-SELFCHECK-TOOLSEARCH` just
above) AND from a generic workflow-spawned Agent-tool subagent — the one
construct where the denial IS genuinely real. Both halves of that
measurement are invalid when read onto a teammate. There is no unresolved
discovery-vs-invocation ambiguity to chase: the axis is SUBSTRATE, not
tier, and the visible-tool-list probe answers it directly regardless of
which failure mode a `Workflow` denial would otherwise present as.

**DF-E1 — `tools:` frontmatter is not authoritative, measured live (this
sprint).** `agents/engineer.md:7` grants `Workflow`, `Glob`, `Grep` in
frontmatter; a live engineer teammate's actual visible tool list carried
NONE of the three — independently reproduced a THIRD time this sprint,
including the conductor session performing this very correction probing
its OWN tool list and finding `Workflow` absent despite `agents/
conductor.md` carrying an identical grant. Frontmatter `tools:` states
what a role DEFINITION is offered at dispatch, never what a running
session actually HOLDS; only the live visible tool list is authoritative,
on either substrate. This is why `WORKFLOW-VEHICLE-PROBE` runs fresh every
session instead of trusting the grant, and why a NEGATIVE probe result on
a genuine teammate is the EXPECTED outcome to record and move past, not a
fact to reconcile against the frontmatter.

**Tool delta, tallied on both backends (DF-64/DF-65).** A `backendType:
tmux` `shepherd:conductor` teammate carries 14 of its definition's 16
granted tools — only `Glob` and `Grep` missing, `Workflow` and
`ScheduleWakeup` both present. A `backendType: in-process` teammate of the
SAME declared type diverges from the SAME 16-tool grant in BOTH
directions: it loses `Glob`/`Grep`/`Skill`/`Workflow`/`ScheduleWakeup`
(five granted tools absent) AND gains `Edit`/`Write`/`Artifact` — three
WRITE tools the definition never grants. `tools:` frontmatter is therefore
not a contract on either backend, and on in-process specifically this is a
containment breach, not just a capability gap: a role defined read-only
(`@conductor`, `@critic`) is not read-only at runtime unless the backend
happens to be tmux.

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
