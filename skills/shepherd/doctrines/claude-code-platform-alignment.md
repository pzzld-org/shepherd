# claude-code-platform-alignment

> Doctrine: shepherd's teammate-coordination model and Claude Code's Agent
> Teams primitive coexist. This doctrine maps the overlap, declares which
> side owns which primitive, sets the migration trajectory, and protects
> shepherd's discipline surface from an experimental platform feature that
> may yet change shape.

Shepherd has run its own teammate-coordination stack since v5.1.5 (root-tier +
dispatch-tier separation per `doctrines/dispatch-tier-separation.md`; SQLite-canonical
operational state per `doctrines/sqlite-canonical-state.md`). Claude Code shipped an
official **Agent Teams** primitive in v2.1.32 (experimental, opt-in) covering
overlapping concepts — lead, teammate, mailbox, idle, task list — with different
durability, liveness, and scope guarantees. Shepherd's stack is older and richer on
operational axes (heartbeats, escalations, deliverables, disputes, DB-backed state)
and under our control; the platform's is newer, simpler, and authoritative for the
runtime substrate (process lifecycle, message delivery, `TeammateIdle` firing).

This doctrine is the binding map between the two.

---

## I. Status

| Surface | Source of truth | Version |
|---|---|---|
| Shepherd canonical operational state | `.artifacts/root.db` (SQLite) | v5.1.7+ per `doctrines/sqlite-canonical-state.md` |
| Shepherd root-tier orchestration | `agents/shepherd.md` + `doctrines/root-shepherd-orchestration.md` | v5.1.6+ |
| Shepherd teammate (conductor) profile | `agents/conductor.md` (TEAMMATE mode) | v5.1.6+ |
| Claude Code Agent Teams primitive | `https://code.claude.com/docs/en/agent-teams` | v2.1.32+ (experimental) |
| Claude Code TeammateIdle hook | `https://code.claude.com/docs/en/hooks#teammateidle` | v2.1.33+ |
| Claude Code TaskCreated hook | `https://code.claude.com/docs/en/hooks#taskcreated` | v2.1.33+ |
| Claude Code TaskCompleted hook | `https://code.claude.com/docs/en/hooks#taskcompleted` | v2.1.33+ |
| Opt-in flag | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (env or `settings.json`) | v2.1.32+ |

**Adoption posture as of v6.0.3:**

1. **Document the mapping** (this doctrine) — every contributor/operator needs to
   know which side wins on which axis.
2. **Continue consuming `TeammateIdle`** (done, v5.1.7) — handled in
   `hooks/scripts/teammate_idle.sh` (registered in `hooks/hooks.json`).
3. **Use `TaskCreate`/`TaskUpdate` for lane routing and wave-gate enforcement**
   (v6.0.3, #100/#102) — every teammate uses lane-prefixed tasks; root creates and
   releases the `wave-{N}-gate-{sprint_slug}` marker. No hook script is registered
   for `TaskCreated`/`TaskCompleted`; root routes via `TeammateIdle` payloads and
   `SendMessage` WAVE-COMPLETE messages.
4. **Do NOT depend on platform Agent Teams for shepherd's core flow** — the feature
   is experimental (`.../agent-teams §Limitations`); availability across versions,
   behavior surviving version bumps, and shutdown/resume semantics are not
   guaranteed. Shepherd's coordination must work without it — the platform feature
   is a substrate, not a core dependency.

The `/shepherd:spawn` preflight (`commands/spawn.md §Preflight`) no longer
hard-gates on a setup step: as of v2.1.178 Agent Teams needs no setup tool and is
available across entrypoints (web/remote/cloud-container included), so Check 1
(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`) and Check 2 (Claude Code version) are
**advisory, not refusals** — runtime is the authority on availability. The only
hard preflight stop is Check 3 (no active team already owns the lead —
one-team-per-session limit). tmux is NOT required; it's an optional display mode.
These checks gate spawn entry, not core shepherd discipline.

> **Resolved (#93, v6.0.2) — updated for the v2.1.178 platform change (2026-06).**
> **As of Claude Code v2.1.178 the `TeamCreate` and `TeamDelete` tools NO LONGER
> EXIST** — spawning a teammate no longer needs a setup step; the team is cleaned up
> automatically on session exit. Current mechanism:
> - **Teammates spawn via the native teammate-spawn** — a natural-language lead
>   instruction to spawn one teammate per lane, each referencing the
>   **`shepherd:conductor`** subagent definition, model `sonnet`. No `TeamCreate`
>   call; the team forms when the first teammate spawns. Post-spawn, the
>   lead↔teammate channel is **`SendMessage`** (address a teammate by name). The
>   shared task list + `SendMessage` mailbox are always available.
> - **`team_name` is dead as a discriminator.** Pre-v2.1.178 it was the tell for
>   defence-in-depth; the platform now accepts but ignores it, and the `team_name`
>   field in `TaskCreated`/`TaskCompleted`/`TeammateIdle` payloads is
>   session-derived and deprecated. The real distinction is spawn INTENT: a
>   **teammate** is a long-lived session (references `shepherd:conductor`,
>   addressed via `SendMessage`); a **subagent** is an ephemeral `Agent`/`Task`
>   dispatch that returns a result. `Agent`/`Task` spawn subagents only, never a teammate.
> - **No per-teammate identity env var exists** (`anthropics/claude-code#35447`,
>   closed *not-planned*) — a teammate session sees only `CLAUDECODE` +
>   `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`. Teammate identity (`teammate_name`) is
>   delivered **only in hook-input JSON** (`TeammateIdle`, `Task*`), never as an env
>   var a script reads.
> - **Nesting is structurally impossible** ("lead is fixed", "no nested teams", "one
>   team per session"), so shepherd's operator-explicit-only rule is consistent with
>   — and largely redundant to — the platform guarantee.
>
> Reconciliation: `commands/spawn.md` + `agents/shepherd.md` (spawn the conductor
> teammates via native teammate-spawn referencing `shepherd:conductor`; teammate-mode
> detected via the boot-prompt INVOCATION-CONTEXT + `.worktrees/` cwd, NOT env vars);
> `hooks/scripts/dispatch_guard.sh` (mechanical floor is the `subagent_type` checks;
> `team_name`-keyed checks are dead now that `team_name` is ignored — retained only
> as harmless, unit-tested defence-in-depth). Where older `Agent({team_name})` /
> `TeamCreate` phrasing survives in the §II–§III rows below, THIS block is the
> authoritative correction; the durable shepherd↔platform ownership split is unchanged.

---

## II. Primitive map

Canonical overlap record. Each row maps a concept to its shepherd implementation,
platform implementation (if any), and owner-of-truth under the current posture.
Later sections cite individual rows for bridging rules.

| Concept | Shepherd primitive | Claude Code Agent Teams | Owner of truth | Notes |
|---|---|---|---|---|
| Lead | `agents/shepherd.md` (root-tier; v5.1.6+) ambient identity of main chat under `/shepherd:spawn` | "team lead" — the main session that creates the team and coordinates work | shepherd | Same process, two identity layers — see §III Rule 1. |
| Teammate | Spawned teammate-conductor (`agents/conductor.md` TEAMMATE mode) via `commands/spawn.md §Spawn dispatch` | "teammate" Claude Code session spawned by the lead | shepherd | Shepherd's teammate is a conductor profile with restricted dispatch surface per `doctrines/dispatch-tier-separation.md §II`. Platform teammates are generic sessions. |
| Teammate naming | `shepherd-{lane\|parallel\|auto}-{sprint_slug}[-{lane_id}]` per `commands/spawn.md §Spawn dispatch` | Name assigned at spawn per `.../agent-teams §Specify teammates and models` | DUAL | Predictable names drive hook routing; platform owns persistence — see §III Rule 2. |
| Teammate status | `teammates` table (`booting`→`active`→`idle`/`crashed`/`retired`) per `skills/context/scripts/cmd_teammate.sh` | Implicit; no explicit status exposed to hooks | shepherd | Platform has no rich status; shepherd's model is the only liveness index — see §III Rule 3. |
| Heartbeat | `heartbeats` table + `cmd_teammate.sh heartbeat` (called by `teammate_idle.sh` when a teammate name is present, and by `register`) | Not exposed | shepherd | No platform primitive. **v6.0.5:** the per-tool `subagent_telemetry.sh` emission (keyed on `CLAUDE_TEAMMATE_NAME`, empty live, #93) is **RETIRED** — liveness is native **`TeammateIdle`** + `cmd_teammate.sh liveness --stale-mins=N`. See `doctrines/sqlite-canonical-state.md`. |
| Mailbox | `mailbox` table + `cmd_mailbox.sh {send,recv,ack,stale}` | `SendMessage` tool per `.../agent-teams §Talk to teammates directly` | DUAL — see §IV | Shepherd's mailbox persists across sessions; platform's `SendMessage` is in-session, not durable across teammate restart. |
| Task list | Lane routing + wave-gate enforcement (v6.0.3, #100/#102) via `TaskCreate`/`TaskUpdate`; shepherd's *structural* task surface remains the engineer plan + GH issue tree. Full mechanics in §V. | Shared task list at `~/.claude/tasks/{team-name}/` per `.../agent-teams §Architecture` | DUAL | See §V — no registered `TaskCreated`/`TaskCompleted` hook. |
| TeammateIdle event | Hooked by `hooks/scripts/teammate_idle.sh` (registered in `hooks/hooks.json`) | Fired by platform per `.../hooks#teammateidle` | platform fires; shepherd handles | Full mechanics in §V. |
| TaskCreated event | Consumed for lane routing/wave-gate (v6.0.3, #100/#102); no registered hook — root observes via `TeammateIdle`/`SendMessage` payloads; `"{lane_id}: "` prefix is the routing key | Fired on `TaskCreate` per `.../hooks#taskcreated` | DUAL | Full mechanics in §V. |
| TaskCompleted event | Consumed for lane routing/wave-gate (v6.0.3, #100/#102); root routes by `"{lane_id}: "` prefix, no-prefix = root-owned terminal tasks. Wave-boundary commits trigger off `TaskCompleted` per `doctrines/spawn-escalation.md §VI` | Fired on task completion per `.../hooks#taskcompleted` | DUAL | Full mechanics in §V. |
| SubagentStop event | Hooked by `hooks/scripts/subagent_telemetry.sh` (cache telemetry only; the v5.1.7 heartbeat emission retired v6.0.5 — see Heartbeat row) | Fired per `.../hooks` (event #13) | shepherd | Full mechanics in §V. |
| Escalation | `escalations` table + `cmd_escalate.sh {create,list,resolve}` | None | shepherd-only | Contract (`PLAN-AUTHORSHIP-REQUEST`, `PLAN-GATE-REQUEST`, `WRONG-TIER-DISPATCH`, `CROSS-TEAMMATE-DISPUTE`, etc.) per `doctrines/dispatch-tier-separation.md §IV` + `doctrines/spawn-escalation.md`; no platform counterpart. |
| Deliverable | `deliverables` table + `cmd_deliverable.sh {promise,complete,stalled}` | None | shepherd-only | Stalled-detector via `Stop` hook `hooks/scripts/deliverable_check.sh` per `doctrines/sqlite-canonical-state.md §Allow-list`; no platform counterpart. |
| Dispatch tier | `doctrines/dispatch-tier-separation.md §I-II` — three-tier hierarchy (root / meta / flock) | None | shepherd-only | Platform's lead/teammate split is two-tier; shepherd adds a flock tier under the conductor. |
| Dispute resolution | `agents/shepherd.md §Hard prohibitions #5` + `doctrines/root-shepherd-orchestration.md §VII` (quarantine → aggregate → `@critic` → operator) | None | shepherd-only | Platform's parallel-investigation is operator-prompted; shepherd's dispute loop triggers mechanically on conflicting findings. |
| Subagent definitions for teammates | `shepherd:conductor` (`agents/conductor.md`) referenced at spawn; lane context via boot-prompt INVOCATION-CONTEXT per `commands/spawn.md §Build the teammate prompt` | Subagent type referenceable at spawn per `.../agent-teams §Use subagent definitions for teammates` | DUAL | **Resolved (#93):** verified spawn path IS subagent-definition reference — see §III Rule 4 for the `skills`/`mcpServers` frontmatter caveat. |
| Display mode | tmux OPTIONAL (`commands/spawn.md §Platform compatibility`); in-process (default) and remote/cloud spawn+dispatch fine | `teammateMode: in-process \| tmux \| auto` per `.../agent-teams §Choose a display mode` | platform | Display mode is observability-only; teammate-spawn doesn't depend on it. |
| Plan approval mode | Shepherd plan + `@critic` gate at root tier per `agents/shepherd.md §Step 1 — INTRODUCTION` | Plan approval mode for teammates per `.../agent-teams §Require plan approval for teammates` | shepherd-only for sprint plans | Platform's is per-teammate read-only mode; shepherd's is sprint-level via `@critic`. No overlap in practice. |
| Cleanup | `agents/shepherd.md §Side-effect boundary` (root) + `agents/planter.md §Babysitter mode §3` (delegated); `/shepherd:cleanup` via `cmd_teammate.sh prune` (v5.1.7+) | "Clean up the team" lead instruction per `.../agent-teams §Clean up the team` | DUAL | Non-overlapping scopes, both required — see §III Rule 5. |
| Permissions | Inherited from lead per `commands/spawn.md §Teammate tool feed` | Inherited from lead per `.../agent-teams §Permissions` | platform | Identical posture by design. |
| Nested teams | Refused by `/shepherd:spawn` Check 0 per `commands/spawn.md §Preflight` | Forbidden per `.../agent-teams §Limitations` ("No nested teams") | DUAL | Both layers refuse independently; shepherd cites the platform limitation but also enforces the doctrine reason (tier separation). |

Future revisions may add rows as platform capabilities expand; the column
structure is binding.

---

## III. Overlap rules

For each §II row where shepherd and platform overlap: **owner**, **bridge**, **failure mode**.

### Rule 1 — Lead identity

Platform's lead = the session that spawned teammates via native teammate-spawn
(#93; v2.1.178 — no `TeamCreate`; `Agent`/`Task` spawn subagents, never
teammates). Shepherd's lead = the same session under ambient identity
`agents/shepherd.md` (root-tier). **Owner:** both — same process, different
identity layer. **Bridge:** `/shepherd:spawn` adopts `agents/shepherd.md` as the
system-prompt addendum before spawning teammate-conductors; operators must not
load it outside `/shepherd:spawn` (Hard prohibition #1;
`doctrines/root-shepherd-orchestration.md §I`). **Failure mode:** running
`/shepherd:start` (solo) then asking Claude to "create an agent team" in natural
language instead of `/shepherd:spawn` — platform spawns teammates with no
shepherd identity layer: split-brain, no conductor profile, no dispatch-tier
discipline, no canonical-state participation. **Operators MUST use
`/shepherd:spawn`**; natural-language teammate spawning is unsupported.

### Rule 2 — Teammate naming

Shepherd's predictable naming (`shepherd-{lane|parallel|auto}-{sprint_slug}`) is
essential: `hooks/scripts/teammate_idle.sh` routes by `teammate_name` from the
hook payload into `cmd_teammate.sh heartbeat <name>` — non-`shepherd-` names
produce no DB row; `cmd_teammate.sh liveness` queries by registered name, so
unregistered platform teammates are invisible to it. **Owner:** shepherd — hook,
liveness, and escalation routing all depend on names being registered in the DB.
**Bridge:** boot prompt sets `IDENTITY.Name` (`commands/spawn.md §Build the
teammate prompt`); teammate runs `cmd_teammate.sh register` during
`/shepherd:start --teammate` boot, indexing the DB row. **Failure mode:** if the
platform changes name-assignment semantics (OQ-2, `commands/spawn.md §Open
questions`), hook routing may break silently — the `teammates` table is the only
authoritative index; no row means invisible to shepherd coordination even if running.

### Rule 3 — Teammate status

Platform exposes no status (`.../agent-teams §Limitations`: "Task status can
lag"). Shepherd's `teammates.status` column
(`booting`/`active`/`idle`/`crashed`/`retired`) is the only rich liveness index.
**Owner:** shepherd. **Bridge:** `TeammateIdle` hook flips `status` to `idle`
(`hooks/scripts/teammate_idle.sh`); `cmd_teammate.sh heartbeat` flips
`booting`→`active`; `cmd_teammate.sh liveness --stale-mins=N` returns
`presumed-crashed` rows against `last_seen_at`; `/shepherd:cleanup` (v5.1.7+)
prunes via `cmd_teammate.sh prune`. **Failure mode:** a teammate that never
heartbeats (spawned outside `/shepherd:spawn`) shows no liveness and is never
detected as crashed, since no `teammates` row exists — `agents/shepherd.md
§Crashed-teammate detection` polls for `presumed-crashed` after each wave-gate,
and that depends on the row existing.

### Rule 4 — Subagent definitions

Platform supports referencing a subagent definition by name at teammate spawn
(`.../agent-teams §Use subagent definitions for teammates`) — the teammate
inherits the definition's `tools` allowlist + `model`, body appended to the
system prompt. Shepherd currently loads `agents/conductor.md` via prompt
injection in the boot prompt (`commands/spawn.md §Build the teammate prompt >
FIRST ACTION`). **Owner:** shepherd today; under test for v5.2.0+. **Bridge:**
none active — the two mechanisms produce similar end-states but the platform
path isn't currently exercised. **Failure mode:** switching to platform
subagent reference would hit the platform's note that `skills`/`mcpServers`
frontmatter is NOT applied to a subagent-as-teammate, silently stripping
per-skill MCP config — the current prompt-injection path avoids this. Adoption
requires verifying every frontmatter field of `agents/conductor.md` survives
the platform's transformation.

### Rule 5 — Cleanup

Platform cleanup ("Clean up the team") handles `~/.claude/teams/{team-name}/`
and `~/.claude/tasks/{team-name}/`. Shepherd's handles git worktrees, agent
branches, `.artifacts/shepherd.lock`, and (via `/shepherd:cleanup`, v5.1.7+)
prunes stale `teammates` rows. **Owner:** both, non-overlapping scopes.
**Bridge:** operator runs all three at session close: (1) root or delegated
planter runs cleanup stewardship per `agents/planter.md §Babysitter mode §3` —
`git worktree remove`, `agent-*` branch deletion, lock release; (2)
`/shepherd:cleanup` prunes stale DB rows (v5.1.7+; closes #51); (3) lead
instructs the platform to "clean up the team." **Failure mode:** missing step 3
leaves stale `~/.claude/teams/` entries; missing step 1 leaves orphan
worktrees; missing step 2 leaves stale `teammates` rows — each is independent, run all three.

---

## IV. Mailbox bridging

The mailbox row in §II is the most live overlap. Shepherd's `mailbox` table
(`skills/context/scripts/cmd_mailbox.sh`, schema per
`doctrines/sqlite-canonical-state.md §Allow-list`) persists across sessions.
Platform `SendMessage` (`.../agent-teams §Talk to teammates directly`) is
in-session and does not survive teammate restart.

| Use case | Use which | Why |
|---|---|---|
| Cross-session message (teammate crashes mid-sprint; root responds on respawn) | Shepherd mailbox | `SendMessage` is in-session; a respawned teammate has a new session and can't read pre-crash messages. |
| In-session message between live sibling teammates in same wave | Platform `SendMessage` when Agent Teams enabled; shepherd mailbox fallback | Per `agents/conductor.md §Teammate-to-teammate communication`, peer messaging is opportunistic; shepherd mailbox is the platform-independent path. |
| Escalation (teammate → root) | Shepherd mailbox + `cmd_escalate.sh create` | The escalation contract (`doctrines/spawn-escalation.md`) requires a persisted row + structured payload; `SendMessage` has neither. |
| Heartbeat-payload auto-relay (deferred #53) | Shepherd mailbox is the natural carrier when implemented | Payloads must persist for root to read on next poll; in-session `SendMessage` would lose them on teammate restart. |
| Operator notification (root → operator) | Neither — stderr emission in main chat | Operators read main chat; mailbox + `SendMessage` are agent-to-agent only. |

**Behavior when both are available:** if an in-session `SendMessage` to a live
peer succeeds, the same payload SHOULD also be written to the shepherd mailbox
when it carries durable significance (a finding, a halt-code surface, a
deliverable promise). Whether dual-write is mechanical or convention is under test
for v5.1.8. The conservative default: **for any cross-session-relevant message,
write to shepherd mailbox; in-session peer messages MAY also use `SendMessage`**
for low-latency surface. Shepherd mailbox is the audit trail; `SendMessage` is the live wire.

---

## V. Hook integration

Three platform hooks matter to shepherd: `TeammateIdle`, `TaskCreated`,
`TaskCompleted`. `SubagentStop` is shepherd's pre-Agent-Teams primitive that
overlaps with them.

### `TeammateIdle` — adopted v5.1.7

Platform schema (`.../hooks#teammateidle`):
```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "TeammateIdle",
  "agent_id": "string (optional)",
  "agent_type": "string (optional)"
}
```
Fires "when a teammate is about to go idle"; exit code 2 with stderr blocks the
idle state. **Resolved (live-docs-verified 2026-06-02):** the payload carries
`session_id` (+ optional `agent_id`/`agent_type`) but does **NOT** list
`teammate_name`. The handler routes by `teammate_name` when present and **falls
back to `session_id`** (registered via `cmd_teammate.sh register --session=`),
failing loud to stderr on no match — so payload-schema drift can't silently no-op
the idle flip the coordinate-drive backstop
(`hooks/scripts/coordinate_drive_guard.sh`) depends on. See
`hooks/scripts/teammate_idle.sh` (routing hardened v6.0.5).

**Handler:** `hooks/scripts/teammate_idle.sh` (registered `TeammateIdle`).

**Effect:** (1) marks the teammate `idle` in `teammates` table via
`cmd_teammate.sh heartbeat <name> --note=idle` + direct UPDATE; (2) counts open
escalations (`cmd_escalate.sh list --open-only`) and stalled deliverables
(`cmd_deliverable.sh stalled --since-mins=10`); (3) surfaces a one-line stderr
warning if either count is non-zero: `[shctx] teammate <name> idle |
open-escalations=N | stalled-deliverables=N`; (4) never blocks (exits 0 unconditionally).

Per `doctrines/sqlite-canonical-state.md §Cited from`, this hook closes #49
(TEAMMATE-CRASHED halt code + crashed-teammate detection in `agents/shepherd.md`).

### `TaskCreated` — consumed for lane routing/wave-gate (v6.0.3, #100/#102)

Platform schema (`.../hooks#taskcreated`) is identical to `TeammateIdle`'s; fires
on `TaskCreate`, exit code 2 rolls back the creation.

**Handler:** none registered in `hooks/hooks.json`. Root observes indirectly via
`TeammateIdle` payload + `SendMessage` WAVE-COMPLETE payloads; the `"{lane_id}: "`
title prefix is the routing key.

**How shepherd uses it (v6.0.3):** every teammate-conductor calls `TaskCreate`
with a `"{lane_id}: "` prefix for each wave-scope work unit, then
`TaskUpdate(owner: <self>)`. Root creates a `wave-{N}-gate-{sprint_slug}` marker
at each wave start; each lane's wave-(N+1) IMPL task carries `addBlockedBy` on it.
Root releases the gate via `TaskUpdate(status: completed)` after it passes (per
`doctrines/spawn-escalation.md §VI`). No hook script fires; root reasons from the
platform task list via tool calls.

### `TaskCompleted` — consumed for lane routing/wave-gate (v6.0.3, #100/#102)

Platform schema (`.../hooks#taskcompleted`) is identical; fires when a task is
being marked complete, exit code 2 prevents completion.

**Handler:** none registered. Root observes via `SendMessage` WAVE-COMPLETE
payloads from the teammate-conductor.

**How shepherd uses it (v6.0.3):** the wave-complete signal is
`SendMessage(to: lead, halt_code: null, blocking: false, context_files: [<wave-gate-output>])`
per `doctrines/spawn-escalation.md §VI`; `TaskCompleted` fires automatically when
the conductor completes its wave-scope task. Root routes by the `"{lane_id}: "`
prefix; terminal tasks (e.g. `shepherd-{sprint_slug}-close`) carry no prefix,
distinguishing them from wave-scope tasks. The `wave-{N}-gate-{sprint_slug}`
marker is released by root via `TaskUpdate(status: completed)` only after the wave
gate passes — a blocked IMPL task can't be claimed until release, enforced by the
task list, not prose. No hook script fires; root reacts to the `SendMessage`
WAVE-COMPLETE payload sent immediately before task completion.

### `SubagentStop` — shepherd primitive, predates Agent Teams

**Handler:** `hooks/scripts/subagent_telemetry.sh` (registered `SubagentStop`).

**Effect:** captures per-dispatch cache telemetry (input/output tokens,
cache read/creation) to `<ns>/logs/events-YYYY-MM-DD.jsonl` per
`doctrines/cache-telemetry.md`. (The v5.1.7 teammate-heartbeat emission was
**retired in v6.0.5** — keyed on `CLAUDE_TEAMMATE_NAME`, empty on the live
platform, never fired; liveness is native `TeammateIdle`-driven.)

**Overlap with `TeammateIdle`:** `SubagentStop` fires when any subagent finishes
(main session, teammate session, nested dispatch); `TeammateIdle` fires
specifically when a teammate is about to go idle. Whether both fire for the same
event is under test; shepherd code assumes they MAY both fire, and the heartbeat
extension is intentionally idempotent on `last_seen_at` to handle the overlap.

### Future hooks — not yet consumed

Per `.../hooks` the platform exposes additional hooks not yet consumed:

- **`SubagentStart`** (event #12) — fires on subagent spawn; payload carries
  `agent_id`, `agent_type`. Could replace `subagent_telemetry.sh`'s
  spawn-time-via-Stop inference with a real spawn event. Likely v5.1.8+
  candidate; non-blocking for v5.1.8 release.
- **`WorktreeCreate`/`WorktreeRemove`** (events #23, #24) — already consumed by
  `hooks/scripts/worktree_lifecycle.sh`. Git-substrate hooks, not Agent Teams
  hooks; included for completeness.
- **`Stop`** (event #16) — consumed by three registered hooks:
  `hooks/scripts/coordinate_drive_guard.sh` (v6.0.5 — coordinate-mode active-drive
  backstop; blocks a premature root halt while a spawn session has idle teammates
  / unread lead mail, per `doctrines/coordinate-active-drive.md §VII`; fast-paths
  to exit 0 outside spawn sessions, runaway-bounded, config via
  `[spawn].coordinate_drive_guard`), `hooks/scripts/deliverable_check.sh` (v5.1.7
  — stalled-deliverable detection), and two `type: "agent"` hooks (wave-gate
  cherry-pick #21, close-finalize #60). Distinct from `SubagentStop`. The
  `coordinate_drive_guard.sh` block is the ONLY shepherd `Stop` consumer that
  returns `{"decision":"block"}` from a command hook; bounded by a 2-nudge cap and
  fails open on any error.

Adoption of any of these is documented here when it lands; contributors should NOT
add new hook consumers without amending §V.

---

## VI. User opt-in matrix

The operator chooses an operating mode at session start:

| Mode | When to use | What you get | Limitations |
|---|---|---|---|
| **shepherd-only (default)** | Always works; recommended for production sprint work | Full conductor profile + lane brief in every teammate; dispatch-tier discipline; canonical SQLite state; escalation contract; deliverable ledger; dispute resolution loop | Heavier teammate context (whole conductor profile + lane brief); each teammate is a full Claude Code session, not a lightweight platform task |
| **Platform Agent Teams (manual natural-language prompt)** | Research/review tasks where parallel exploration matters more than disciplined dispatch (`.../agent-teams §Use case examples`) | Lightweight parallel exploration; `SendMessage` between teammates; platform-managed task list; shorter cycle for ad-hoc parallel work | Experimental (`.../agent-teams §Limitations`); limited resume (`/resume`/`/rewind` don't restore in-process teammates); no escalations/deliverables/dispute resolution; no canonical state row in shepherd DB |
| **Hybrid (operator manually invokes both)** | NOT SUPPORTED in v5.1.8 | n/a | Split-brain risk on liveness (platform and shepherd see different teammate sets); naming conflicts in `~/.claude/teams/`; doubled cleanup burden |

**Entering shepherd-only mode:** invoke `/shepherd:spawn` (`commands/spawn.md
§Smooth path`) — main chat adopts `agents/shepherd.md`; teammate boots with
`agents/conductor.md` (TEAMMATE mode); all coordination flows through shepherd primitives.

**Entering platform mode:** ask Claude Code in natural language to create an agent
team (`.../agent-teams §Start your first agent team`). Do NOT also invoke
`/shepherd:spawn` — nesting a shepherd team inside a platform team is undefined
behavior, and `/shepherd:spawn` Check 3 ("No active team") refuses if a platform
team is already running.

**Why hybrid is unsupported:** the two systems' liveness indices aren't
synchronized. A teammate visible to the platform
(`~/.claude/teams/{team-name}/config.json#members[]`) but not registered to the
`teammates` table is invisible to `cmd_teammate.sh liveness`; a teammate
registered to `teammates` but absent from the platform's team config is
unreachable via `SendMessage`. The escalation contract assumes the same teammate
exists in both indices — mixing without explicit synchronization (deferred to
v6.0.0 evaluation, §VII) leaves shepherd unable to reason about team state.

---

## VII. Migration roadmap

Trajectory from "two systems coexist" to "one preferred backend," multi-version;
each step independently shippable and reversible.

| Step | Status | What it does |
|---|---|---|
| v5.1.8 — document the mapping | Done | This doctrine; no behavioral change. `TeammateIdle` consumption continues (v5.1.7); `commands/spawn.md` already cites platform prerequisites via Checks 1–3. |
| v6.0.3 — `TaskCreated`/`TaskCompleted` for wave-gate | Done | Shepherd uses `TaskCreate`/`TaskUpdate` for lane-prefixed tasks and the `wave-{N}-gate-{sprint_slug}` marker (`doctrines/spawn-escalation.md §VI`); no hook scripts registered, root routes via `SendMessage` WAVE-COMPLETE + platform task-list calls. Optional future step: register `task_created.sh`/`task_completed.sh` to mirror tasks into a `tasks` table — deferred past v6.0.3. |
| `--auto` alias | Preserved | Stable alias for `--scope patch` per PINNED policy (rescinded removal timeline); unrelated to platform alignment. `commands/autorun.md` is a thin delta reference. |
| v6.0.0 — evaluate platform backend toggle | Conditional | IF Agent Teams exits experimental status AND covers shepherd's needs (richer status, persistent mailbox, escalation-equivalent, dependency-aware task graph) AND operators want it: evaluate `[teams].platform_backend = true` in `shepherd.toml` — `teammates` becomes a view over `~/.claude/teams/`, `mailbox` wraps `SendMessage`, §III rules invert per delegating surface. IF NOT: coordination stays independent. v6.0.0 is a MAJOR version per `CLAUDE.md §Versioning` regardless of flock changes. |

**Orthogonal execution axis (v6.0.1) — Dynamic Workflows.** The toggle above is
the *teammate-state* backend. A second, orthogonal *execution* axis is evaluated
in `doctrines/workflow-compile-down.md`: compiling the critic-gated Stage Graph's
gate-free, agent-fanout segments to Claude Code **Dynamic Workflows** the
platform runs out-of-context. Agent Teams owns teammate-state; a compiled
workflow owns a segment's execution — **neither subsumes the other**, they
compose. See that doctrine §IV (faithfulness bar: soundness/completeness/determinism),
§VI (canonical-state seam), §IX (decision criterion). `doctrines/native-coordination.md`
(v6.0.1) maps how these two axes plus the subagent primitive replace the
hand-rolled coordination mechanics (pause-for-dependency/heartbeat/idle-prune).

> **Canonical binding (v6.0.2, #89).** `doctrines/primitive-axis-binding.md` pins
> each axis to its primitive and ontology unit: planning → none → `waves × steps`;
> teammate-state/parallelization → **Agent Teams** → one teammate-conductor per
> **lane**; execution → **Dynamic Workflows** → compiled script over
> **subagents**; worker → **subagents** → **steps**. Fixes the v6.0.1 regression
> where a Dynamic Workflow spawned the conductor wave and teammates failed to
> compile their fan-out (each primitive used for the other's job). §II and the
> execution-axis doctrine both obey it.

---

## VIII. Anti-patterns

Operator/contributor patterns producing split-brain or silent erosion of shepherd
discipline. Each is a process violation catchable by operators or code review.

1. **Spawning teammates via natural language while in a `/shepherd:start`
   session** — bypasses `agents/shepherd.md` root-tier identity; platform-managed
   teammates get no conductor profile, no dispatch-tier discipline (§III Rule 1).
2. **Reading `~/.claude/teams/{team-name}/config.json` as source of truth for
   teammate liveness** — it's platform runtime state, excludes shepherd-specific
   status. Query `teammates` table directly per
   `doctrines/sqlite-canonical-state.md §Anti-patterns #3`.
3. **Adding a new shepherd hook consumer without amending §V** — hooks are part of
   the platform contract; hidden additions make this doctrine wrong.
4. **Calling platform `SendMessage` for cross-session messages** — in-session
   only; a respawned teammate can't read it. Use shepherd mailbox (§IV).
5. **Skipping `cmd_teammate.sh register` in the teammate boot** — the teammate
   becomes invisible to shepherd liveness. Required per `commands/spawn.md §Build
   the teammate prompt > FIRST ACTION` (implicit via `/shepherd:start --teammate`
   flow); whether all boot paths run it is under test.
6. **Treating `TaskCreated`/`TaskCompleted` as a registered shepherd hook that
   fires into a script** — no hook script is registered for these events
   (v6.0.3); root observes via `SendMessage` WAVE-COMPLETE payloads and platform
   tool calls, not a hook invocation. If a future version registers handlers, they
   MUST write to the canonical `tasks` table (schema TBD) — markdown-only logging
   is an anti-pattern per `doctrines/sqlite-canonical-state.md §Anti-patterns #2`.
7. **Nesting `/shepherd:spawn` from within a platform-spawned teammate** —
   refused by `commands/spawn.md` Check 0 and by the platform
   (`.../agent-teams §Limitations`, "No nested teams"); either refusal alone is sufficient.
8. **Loading `agents/shepherd.md` under `/shepherd:start`** — per
   `doctrines/root-shepherd-orchestration.md §I` the root tier exists only under
   `/shepherd:spawn`; in solo mode the conductor is its own root, no separate
   `shepherd` profile loads. Mis-loading produces conflicting Hard prohibitions
   (solo conductor permits `@engineer`/`@critic`; root forbids `@coder`).

---

## IX. References

### Shepherd-side

- `agents/shepherd.md` — root-tier profile; mode cycle; ROOT CLOSE REPORT
- `agents/conductor.md` — TEAMMATE mode behaviors; side-effect boundary; mode detection
- `agents/planter.md` — babysitter mode; cleanup stewardship; multi-teammate triage
- `commands/spawn.md` — preflight Checks 0–8; platform prerequisites; teammate boot prompt; OQ-1..OQ-6
- `hooks/hooks.json` — registered hook entries (`TeammateIdle`, `Stop`, `SubagentStop`, `WorktreeCreate`, etc.)
- `hooks/scripts/teammate_idle.sh` — `TeammateIdle` handler (v5.1.7+)
- `hooks/scripts/subagent_telemetry.sh` — `SubagentStop` handler (cache telemetry; teammate-heartbeat emission retired v6.0.5)
- `hooks/scripts/deliverable_check.sh` — `Stop` hook stalled-deliverable detector
- `hooks/scripts/coordinate_drive_guard.sh` — `Stop` hook coordinate-mode active-drive backstop (v6.0.5)
- `doctrines/coordinate-active-drive.md` — dispatch→coordinate active-drive contract (v6.0.5; #113/#98/#112)
- `skills/context/scripts/cmd_teammate.sh` — register / heartbeat / status / liveness / prune / retire
- `skills/context/scripts/cmd_mailbox.sh` — send / recv / ack / stale
- `skills/context/scripts/cmd_escalate.sh` — create / list / resolve
- `skills/context/scripts/cmd_deliverable.sh` — promise / complete / stalled
- `doctrines/sqlite-canonical-state.md` — canonical store rules; allow-list; anti-patterns
- `doctrines/dispatch-tier-separation.md` — three-tier matrix; mode detection; escalation patterns
- `doctrines/root-shepherd-orchestration.md` — root-tier behavioral contract; three modes
- `doctrines/spawn-escalation.md` — escalation channel mechanics; wave-boundary commits
- `doctrines/cache-telemetry.md` — cache-event schema for `subagent_telemetry.sh`
- `doctrines/scope-scale-workload.md` — `--scope` flag composition; sprint enumeration
- `doctrines/stage-graph.md` — node / edge / predicate rules for sprint plans
- `doctrines/intro-combo-wave.md` — INTRO-COMBO-WAVE dispatch under spawn
- `CHANGELOG.md` v5.1.7 — defect cluster #43, #44, #49, #50, #51, #52, #54; deferred #47, #53

### Platform-side

- `https://code.claude.com/docs/en/agent-teams` — Agent Teams primitive (architecture, hooks, team config, mailbox, task list, v2.1.32+, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` flag)
- `https://code.claude.com/docs/en/agent-teams#choose-a-display-mode` — `teammateMode: in-process | tmux | auto`
- `https://code.claude.com/docs/en/agent-teams#use-subagent-definitions-for-teammates` — subagent-type reference at spawn; `skills` / `mcpServers` frontmatter behavior
- `https://code.claude.com/docs/en/agent-teams#limitations` — experimental limitations (no resume, task lag, slow shutdown, one-team-per-lead, no nested teams, lead is fixed)
- `https://code.claude.com/docs/en/hooks#teammateidle` — `TeammateIdle` payload + decision control
- `https://code.claude.com/docs/en/hooks#taskcreated` — `TaskCreated` payload + decision control
- `https://code.claude.com/docs/en/hooks#taskcompleted` — `TaskCompleted` payload + decision control
- `https://code.claude.com/docs/en/hooks` — complete hook event list (31 events, live-docs-verified 2026-06-02)

### Issue references (GitHub)

- Closed in v5.1.7 via SQLite-canonical state: #43, #44, #49, #51, #52 (per `CHANGELOG.md` v5.1.7)
- Deferred to v5.2.0+: #53 — `SendMessage heartbeat_payload` first-class runtime primitive (shctx infrastructure ready; upstream-dependent)
- Upstream Claude Code: anthropics/claude-code#31977 (in-process teammateMode Agent-tool restriction; tracked in `commands/spawn.md §Platform compatibility`)
