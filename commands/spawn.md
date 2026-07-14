---
name: spawn
description: Spawn teammate-conductor lanes to run a sprint while main chat drives as root-shepherd. Use when starting substantive sprint work. Operator-only; refuses from teammate sessions.
argument-hint: "[ sprint_slug ] [ --scope sprint|patch|minor|version ] [ --parallel <N> | --auto ] [ --staged ]"
allowed-tools: Agent, Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, SendMessage, WebFetch, WebSearch
---

# /shepherd:spawn — teammate-conductor dispatch

The primary command for substantive sprint work. Spawn one teammate-conductor per lane
while main chat stays lean as root shepherd — root owns `@engineer`/`@critic` dispatch,
materializes teammate payloads as artifacts, runs every git operation, and executes the
post-sprint merge; teammates execute lanes and report up.

Escalation contract (paths, cadence, halt-code map, heartbeat, triage):
`skills/shepherd/references/escalation.md §Escalation payload`. Dispatch tier law:
`skills/shepherd/SKILL.md §Dispatch law`.

## Root profile

Main chat adopts `agents/shepherd.md` (full file) as a system-prompt addendum for the
spawn — the root-shepherd tier. Two-meta-loading: if `agents/planter.md` is
already loaded (operator ran `/shepherd:plant`), shepherd AUGMENTS as the outer frame while
planter stays the inner frame, regaining primary write authority for cleanup on spawn close
— `agents/shepherd.md §Two-meta-loading`.

Root runs the intro combo wave (`@discovery` + intro-`@auditor`) → `@engineer` →
`@critic` gate, then projects the approved plan into vertical LANES and spawns one
teammate-conductor per lane — lane count constant across waves, never per-wave
(`skills/shepherd/references/pipeline.md §Lane law`).

## Preflight

Run every check before the spawn instruction. Refuse with a clear error on any HARD gate;
Check 0 runs FIRST.

| Check | Gate | Rule |
|---|---|---|
| 0 | Operator-only invocation | HARD. Refuse if invoked from a teammate session (detail below). |
| 1 | Agent Teams availability | ADVISORY. NEVER hard-refuse on `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` unset — the runtime is the authority. |
| 2 | Claude Code version | ADVISORY. NEVER hard-refuse on version; act on the real runtime signal. |
| 3 | No active team | HARD. `ls ~/.claude/teams/` non-empty with a `config.json` carrying `members[]` → refuse. One team per lead. |
| 4 | shepherd.toml | Scaffold-then-proceed: `shctx config init` if missing, emit `[CONFIG] scaffolded`, PROCEED. Non-blocking. |
| 5 | Flag preflight | `--parallel`/`--auto`/`--scope` gates — `skills/shepherd/references/spawn-flags.md`. |
| 6 | Scope enumeration | Enumerate the concrete sprint list. A multi-sprint scope with a missing seed REFUSES (route to `/shepherd:plant`). A single `--scope sprint` plants inline. |
| 7 | Scope confirmation | `--scope minor` requires the exact phrase `confirm minor`; `--scope version` requires `confirm version` + resource-warning block. |
| 8 | Resource estimate | Info-only, ALWAYS surfaced. Reads `shctx adapt priors --metrics`; labels the block `(from priors: N sprints)` or `(defaults — no priors yet)`. |

### Check 0 — operator-only invocation

`/shepherd:spawn` is operator-explicit-only; nested spawn from a teammate session is
forbidden. The guarantee is structural: the Agent Teams platform forbids a non-lead from
creating a team (no nested teams; one team per lead), so a nested spawn cannot occur.
Secondary signals (ANY positive → refuse): current cwd under a `.worktrees/` path; the
session's system-prompt addendum carries `INVOCATION-CONTEXT.dispatcher: teammate-conductor`. On refuse, route plan-amendment requests to `SendMessage(to: lead,
halt_code: PLAN-AUTHORSHIP-REQUEST)`. A refused nested spawn raises `TEAMMATE-NESTING-ATTEMPT`.

### Cache-TTL nudge

For `--scope patch` and long `--auto` loops, root MUST surface a one-line nudge to set
`ENABLE_PROMPT_CACHING_1H=1` (1-hour prompt-cache TTL). A multi-wave run outlives the
5-minute default between waves; without the flag the cached brief and system prefixes
expire and re-bill at full input rate. Claude subscriptions request 1h automatically;
API-key / Bedrock / Vertex / Foundry need the flag.

## Teammate prompt

Build each teammate's boot prompt before the spawn instruction. It carries every inherited
fact so the teammate never re-asks main chat.

```
You are a spawned teammate-conductor.

ROOT-SESSION-NAME: shepherd-root @ {main_chat_session_id}

INVOCATION-CONTEXT:
  dispatcher: teammate-conductor
  spawn_session: {team_id}
  scope: {sprint|patch|minor|version}
  fanout_mode: {lane|sprint}          # lane-per-conductor (default) | concurrent sprints
  lane_index: {i_of_L_w}              # lane mode only
  wave_index: {w_of_W}                # lane mode only
  parallel_index: {i_of_N}            # sprint-fanout index (sprint mode only)
  peer_teammate_names: [list]         # siblings, for peer SendMessage

INHERITED CONTEXT
  Profile:              ${CLAUDE_PLUGIN_ROOT}/agents/conductor.md
  Model pin:            {resolved via shctx models resolve conductor}
  CLAUDE.md path:       {project_claude_md_path}
  Active seed:          {paths.plans}/{sprint_slug}.seed.md
  Active plan:          {paths.plans}/{sprint_slug}.plan.md
  Lane brief:           {paste the lane's seven-bracketed brief slice + steps}
  Prior close handoff:  {paths.docs}/{prior_handoff_filename}
  Carry-forward issues: {comma-separated #NNN from handoff}
  Worktree path:        {abs}/.worktrees/{sprint_slug}-{lane_id}   (root pre-created it)
  [BASE-COMMIT-EXPECTED]: {sprint_branch HEAD sha}
  shepherd.toml snapshot: inline below

BOOT INSTRUCTION
  On your FIRST turn, load ${CLAUDE_PLUGIN_ROOT}/agents/conductor.md §Boot verification
  and begin — do NOT wait for a kickoff message. Your lane brief IS the instruction.
  conductor.md owns the boot checklist (§Boot verification), the lane micro-Stage-Graph
  walk (§Lane walk), and the WAVE-COMPLETE payload schema you emit (§WAVE-COMPLETE + resume).

HARD PROHIBITIONS (each BINDING; on any, REFUSE and
SendMessage(to: lead, halt_code: <code>, blocking: true)):
  - @engineer dispatch → WRONG-TIER-DISPATCH  (escalate PLAN-AUTHORSHIP-REQUEST)
  - @critic dispatch   → WRONG-TIER-DISPATCH  (escalate PLAN-GATE-REQUEST)
  - flock dispatch missing subagent_type: "shepherd:<role>" or set to
    general-purpose/Explore/Chat → DISPATCH-MISSING-SUBAGENT-TYPE
  - flock dispatch outside the closed six-role flock → DISPATCH-OFF-FLOCK
  - spawning a teammate (you are not a lead) → TEAMMATE-NESTING-ATTEMPT
  - git commit/push/branch -d/rebase/worktree add/remove → TEAMMATE-GIT-WRITE
  Full contract: agents/conductor.md §Hard prohibitions.
```

**Non-canonical brief? Attest it.** The bracketed template above is the default and passes the
conductor's strict shape check. If a lead deliberately hand-authors a brief in a different shape
(ad-hoc headers, prose lane brief) while carrying every required fact, add a
`BOOT-FORMAT: lead-attested` line beside `ROOT-SESSION-NAME`. The conductor then substance-checks the required
facts (worktree path, base commit, step queue, acceptance source, prohibitions, root routing)
instead of hard-halting on header shape (`agents/conductor.md §Boot verification`). Only a lead adds
the marker — never a teammate to its own boot.

The teammate inherits NONE of the lead's session state — this is WHY the boot prompt MUST
carry every inherited fact above:

- Conversation history: it boots fresh; every needed fact MUST be in the block.
- Open file context: it MUST `Read` any file it needs; the lead's buffers do not carry over.
- Permission grants beyond default mode: the lead's auto-approved tool calls do NOT propagate.

Gate discipline (cargo `--frozen`, `CARGO_TARGET_DIR=target/.lanes/<lane-slug>`, gates
SERIAL, `cargo fix` FORBIDDEN) is owned by `agents/conductor.md §Boot verification` and
`skills/shepherd/references/pipeline.md §Gates`. The teammate returns structured payloads;
root materializes every artifact.

### Pre-spawn tool check

Before the spawn instruction fires, root MUST verify the `Agent` tool is registered in the
lead session — the spawned teammate inherits it to dispatch the flock (`Agent` spawns
subagents, NOT teammates). If it is absent, HALT and surface:

```
/shepherd:spawn — REFUSED: Agent tool not registered in lead session.
The teammate-conductor needs Agent tool inheritance to dispatch the flock.
Run /reload-plugins, verify, and re-invoke.
```

### Pre-spawn worktree creation

Root MUST create every lane worktree BEFORE spawning teammates:
`git worktree add .worktrees/{sprint_slug}-{lane_id} {sprint_branch}` per lane, `git worktree
list` to verify, then emit `[WORKTREE-READY]`. The spawn instruction MUST NOT fire until all
lane worktrees exist. A teammate that creates its own worktree raises `TEAMMATE-GIT-WRITE`.

## Spawn dispatch

The lead spawns teammates via the native teammate-spawn — a natural-language instruction to
spawn one teammate per lane, each referencing the `shepherd:conductor` subagent definition as
its agent type. NEVER call a `TeamCreate` tool — it does not exist. The team forms on the
first spawn; the channel is `SendMessage` plus the shared task list.

```
"Spawn one teammate per lane to run sprint {sprint_slug}, each of agent type
 shepherd:conductor, model: sonnet, named shepherd-conductor-{sprint_slug}[-{lane_id}].
 Give each the boot prompt above as its instructions. Each teammate BEGINS ITS LANE
 IMMEDIATELY on spawn — it does NOT wait for a go-signal."
```

### Register teammates (mandatory)

Immediately after the spawn instruction — BEFORE polling liveness — root writes each teammate's
row into the canonical store, once per spawned teammate:

```
shctx teammate register <name> --team={team_id} --type=conductor [--session={team_session}]
# and, for the self-contained engineer teammate:
shctx teammate register {engineer_name} --team={team_id} --type=engineer
```

This is the row the `TeammateIdle` hook (`hooks/scripts/teammate_idle.sh`) matches by NAME to flip
idle status, and the row `shctx teammate liveness` reads. Native-Agent teammates boot fresh and do
NOT self-register, so WITHOUT this step the `teammates` table stays empty: `liveness` returns
nothing for live lanes and every `TeammateIdle` fires unmatched, flooding the lead with idle noise
that masks real stalls (#183). Registration is idempotent (upsert on `(team, name)`), so a refresh
or a teammate's own late self-register is safe.

**Declare progress, don't infer it (#193/#197).** Liveness derives "crashed" from the heartbeat
gap, but teammates don't heartbeat on a cadence, so a healthy long-running lane reads
`presumed-crashed` after 5 min and root wrongly cancels it. Set the explicit `declared_state`
(migration 0019) instead — mark each teammate `in-progress` right after registering, `complete`
when you materialize its `LANE-COMPLETE` (before prune), `error` on a returned HALT:

```
shctx teammate state <name> --set=in-progress|complete|error   # heartbeat --state=<s> does both in one call
```

`in-progress` is never presumed-crashed regardless of the gap; `complete`/stale-ghost rows drop out
of the live set that `shctx teammate liveness` and the coordinate-drive Stop hook read. That Stop
hook is now root-only — it never fires on a teammate's own session (#197), so a self-contained
`@engineer` is no longer trapped in root's drain loop.

After registering, root confirms liveness (`shctx teammate liveness` until each lane is
`active`/heartbeating) before the dispatch is complete. `hooks/scripts/dispatch_guard.sh`
enforces dispatch discipline — off-tier or off-flock dispatches raise
`WRONG-TIER-DISPATCH`, `DISPATCH-MISSING-SUBAGENT-TYPE`, `DISPATCH-OFF-FLOCK`, or
`DISPATCH-TEAMMATE-TYPE-MISMATCH`.

### Model pin (mandatory)

Every teammate MUST be spawned with an explicit model pin resolved from the single map —
`shctx models resolve conductor` (`skills/context/references/model-map.md`; default `sonnet`).
NEVER rely on subagent-definition frontmatter to propagate: teammates inherit the lead
session's model instead, so an Opus lead drove every teammate to Opus and multiplied cost by
the lane count — that regression is WHY this pin is mandatory. `shctx models resolve <role>`
gives each role's pin; `shctx models show` renders the resolved 9-role table as the pre-spawn
preflight. Root's own model is advisory — a config key cannot rebind a running session. If the
lead is Opus and no pin is present, REFUSE to spawn until the pin is present or the operator
records an explicit override.

### Self-contained engineer

Root spawns `@engineer` as a self-contained teammate (the DEFAULT) via the native
teammate-spawn, NEVER the Agent/Task tool (`skills/shepherd/references/pipeline.md §INTRO`).
Its brief carries `mode: self-contained` and `dispatcher: root-shepherd` (the
`engineer-self-contained` marker is what the ENGINEER tags on its own sub-flock dispatches,
never what root puts on the engineer's brief). The engineer's sub-flock is the three
read-only / adversarial roles ONLY — `@discovery`, intro-mode `@auditor`, `@critic` — with a
MINIMUM 5-subagent intro wave (2 `@discovery` + 3 intro-`@auditor`, scaled upward at the
engineer's discretion), then its own critic gate looped until GREEN, returning ONE finalized
plan + a hash-tied critic-proof; no code is touched. Root accepts via a thin gate (`shctx
seed verify` + `shctx plan verify --plan <plan>` + a lane-count sanity check) and runs NEITHER
its own intro wave NOR `@critic` (`ROOT-INTRO-USURPED`). Only ROOT spawns the engineer
teammate; a self-contained engineer dispatched as an Agent/Task subagent →
`ENGINEER-TOPOLOGY-MISMATCH`.

### Post-spawn confirmation

```
[SPAWN] teammate shepherd-conductor-{sprint_slug} dispatched.
        Babysitter mode: active. Monitoring TeammateIdle + TaskCompleted hooks.
        Heartbeat threshold: 5 min — alert on staleness.
        Sprint: {sprint_slug}
        Operator dashboard: /shepherd:loop {dashboard_cadence} shctx dash
```

`{dashboard_cadence}` resolves via `shctx config get dashboard_cadence 3m`. This confirmation
is NEVER a turn-end: root proceeds in the SAME flow into the coordinate cycle (confirm liveness
→ scaffold wave-gates → wake → act → probe → yield-to-events) until CLOSE-FINALIZE, and NEVER
passive-waits at the dispatch boundary (`skills/motivation/SKILL.md §Drive contract`;
backstopped by `hooks/scripts/coordinate_drive_guard.sh`).

### Root responsibilities while spawned

Full contract: `agents/shepherd.md §Mandatory protocol`. Root drives the active-drive loop
(wake → act → probe; NEVER passive-wait), monitors `TeammateIdle`/`TaskCompleted`, triages
escalations by `halt_code`, alerts on >5 min heartbeat staleness, runs cleanup at
CLOSE-FINALIZE, and commits every wave boundary immediately (`git commit -m
"chore(dev.N/wave-K): wave-complete via spawn"`) — the one-wave loss horizon holds ONLY if a
commit lands at every boundary.

## Hard stops

`/shepherd:spawn` MUST refuse when:

1. Check 3 fails (an active team is already running). Checks 1-2 are advisory and NEVER hard-stop.
2. A seed is missing for `--parallel` or a multi-sprint `--scope` (patch/minor/version) walk —
   route to `/shepherd:plant` per gap. A single `--scope sprint` does NOT refuse: it plants
   inline via the `SEED-AUTHOR` node, gated by `shctx seed verify` before the intro combo wave.
3. Corrupted `.artifacts/shepherd.lock` — non-empty, timestamp < 30 min, matching an active process.
4. Active rebase — `REBASE_HEAD` or `MERGE_HEAD` present.
5. Nested-team attempt (Check 0) → `TEAMMATE-NESTING-ATTEMPT`.

## Flags

Each flag composes with the base spawn. Full semantics per section of
`skills/shepherd/references/spawn-flags.md`.

- `--scope <sprint|patch|minor|version>` (default `sprint`) — declares workload scale.
  `sprint` = one `dev.N`; `patch` = full patch `dev.0..dev.LAST`; `minor`/`version` are
  experimental and require the confirm phrase. `--auto` is the stable alias for `--scope patch`.
  Lane-per-conductor fanout applies within EVERY sprint. `spawn-flags.md §--scope`.
- `--parallel <N>` — fan out N sibling teammates. N = 2..`[spawn].max_parallel` (default cap
  4), valid for `--scope sprint`/`patch` only, REFUSED for `minor`/`version`. Worktree-per-
  teammate; a collision pre-check over `file_scope.exclusive` + shared build manifests HARD-
  STOPs; dev-order merge gate — `dev.N+1` MUST NOT merge before `dev.N`. `spawn-flags.md
  §--parallel`.
- `--auto` — alias for `--scope patch`; sequential autopilot spawning one fresh-context
  teammate per sprint with root-authored inter-sprint handoffs, until `dev.LAST` or a
  termination condition fires. `spawn-flags.md §--auto`.
- `--staged` — two-session overlap: root orients/discovers NOW, then arms a delayed start and
  WAITS for a `seed-ready` mailbox signal from a concurrent `/shepherd:plant` session before
  authoring the plan (poll `shctx mailbox recv --kind=seed-ready` via ScheduleWakeup ≤270s;
  timeout `[spawn].staged_timeout_minutes` default 90 → `STAGED-TIMEOUT`). A missing seed is
  the EXPECTED start state, NOT a seedless-run trigger. `spawn-flags.md §--staged`.
