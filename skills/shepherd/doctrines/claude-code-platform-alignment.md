# claude-code-platform-alignment

> Doctrine: shepherd's teammate-coordination model and Claude Code's Agent
> Teams primitive coexist. This doctrine maps the overlap, declares which
> side owns which primitive, sets the migration trajectory, and protects
> shepherd's discipline surface from being silently eroded by an
> experimental platform feature that may yet change shape.

Shepherd has run its own teammate-coordination stack since v5.1.5, refined
through v5.1.6 (root-tier + dispatch-tier separation per
`doctrines/dispatch-tier-separation.md`) and v5.1.7 (SQLite-canonical
operational state per `doctrines/sqlite-canonical-state.md`). In parallel,
Claude Code shipped an official **Agent Teams** primitive in v2.1.32
(experimental, opt-in). The two systems describe overlapping concepts —
lead, teammate, mailbox, idle, task list — but with different durability
guarantees, different liveness semantics, and different scope. Shepherd's
implementation is older, richer on operational axes (heartbeats,
escalations, deliverables, disputes, DB-backed canonical state), and
under our control. The platform's is newer, simpler, and authoritative
for the runtime substrate (process lifecycle, message delivery,
TeammateIdle hook firing).

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

**Adoption posture as of v5.1.8:**

1. **Document the mapping.** This doctrine. Every shepherd contributor and
   every operator who reaches into Claude Code's Agent Teams docs needs
   to know which side wins on which axis.
2. **Continue consuming `TeammateIdle` (already done).** The platform
   fires the event; shepherd handles it in
   `hooks/scripts/teammate_idle.sh` (registered in `hooks/hooks.json`).
3. **Track `TaskCreated` / `TaskCompleted` for v5.2.0 evaluation.** Not
   currently consumed by shepherd. Reserved for the v5.2.0 task-list
   integration decision.
4. **Do NOT depend on platform Agent Teams for shepherd's core flow.**
   The platform feature is experimental (per
   `https://code.claude.com/docs/en/agent-teams §Limitations`). Operators
   cannot rely on it being available in a given Claude Code version, on
   particular behavior surviving across versions, or on shutdown /
   resume semantics. Shepherd's coordination must work without it; the
   platform feature is a substrate, not a core dependency.

The `/shepherd:spawn` command already enforces the platform substrate
prerequisites (per `commands/spawn.md §Preflight`): Check 1 verifies
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true`; Check 2 verifies Claude Code
v2.1.32 or later; Check 3 verifies no active team owns the lead. Those
checks are the boundary at which shepherd's enforcement begins — they
gate spawn entry, not core shepherd discipline.

> **Open investigation (#93, v6.0.2).** Live Agent Teams docs (verified 2026-05-29)
> spawn teammates via a **natural-language lead instruction**, *not* `Agent({team_name})`,
> and document **no per-teammate identity env var**. Shepherd's spawn convention — and
> the v6.0.2 `hooks/scripts/dispatch_guard.sh` — assume the `Agent({team_name})` +
> `CLAUDE_TEAMMATE_NAME` model, internally consistent with shepherd's existing telemetry/
> idle hooks but **unverified against the platform**. The rows in §II–§III below describe
> shepherd's convention; treat the **spawn-call shape and the teammate-identity signal as
> under-test** until #93 closes (empirical spawn test → keep / migrate / hybrid). #93
> **gates v6.0.2 Wave 2 (#78, Agent Teams wiring)**.

---

## II. Primitive map

The table below is the canonical overlap record. Every row maps a single
concept to its shepherd implementation, its platform implementation
(when one exists), and the owner-of-truth in the current adoption
posture. Subsequent sections cite individual rows for detailed bridging
rules.

| Concept | Shepherd primitive | Claude Code Agent Teams | Owner of truth | Notes |
|---|---|---|---|---|
| Lead | `agents/shepherd.md` (root-tier; v5.1.6+) ambient identity of main chat under `/shepherd:spawn` | "team lead" — the main session that creates the team and coordinates work | shepherd | Shepherd's lead carries doctrine + dispatch tier discipline; platform's lead is the process-lifecycle owner. They coexist — shepherd lead behavior is layered onto the platform lead session. |
| Teammate | Spawned teammate-conductor (`agents/conductor.md` in TEAMMATE mode) via `commands/spawn.md §Spawn dispatch` | "teammate" Claude Code session spawned by the lead | shepherd | Shepherd's teammate is a conductor profile with restricted dispatch surface per `doctrines/dispatch-tier-separation.md §II`. Platform teammates are generic Claude Code sessions. |
| Teammate naming | `shepherd-{lane\|parallel\|auto}-{sprint_slug}[-{lane_id}]` per `commands/spawn.md §Spawn dispatch` | Name assigned at spawn; lead chooses or generates per `https://code.claude.com/docs/en/agent-teams §Specify teammates and models` | DUAL | Shepherd assigns predictable names so the `TeammateIdle` hook can route via the `shepherd-` prefix; platform owns the actual name persistence in `~/.claude/teams/{team-name}/config.json`. |
| Teammate status | `teammates` table (`booting` → `active` → `idle` / `crashed` / `retired`) per `skills/context/scripts/cmd_teammate.sh` | Implicit; in-process or tmux process state with no explicit status column exposed to hooks | shepherd | Per `https://code.claude.com/docs/en/agent-teams §Limitations` the platform has no rich status; shepherd's richer model is the only liveness index. |
| Heartbeat | `heartbeats` table + `cmd_teammate.sh heartbeat`; emitted from `hooks/scripts/subagent_telemetry.sh` when `CLAUDE_TEAMMATE_NAME` is set | Not exposed | shepherd | Platform has no heartbeat primitive. Shepherd's `cmd_teammate.sh liveness --stale-mins=N` is the only stale-teammate detector. See `doctrines/sqlite-canonical-state.md §Allow-list`. |
| Mailbox | `mailbox` table + `cmd_mailbox.sh {send,recv,ack,stale}` per `skills/context/scripts/cmd_mailbox.sh` | `SendMessage` tool — direct message between live teammates per `https://code.claude.com/docs/en/agent-teams §Talk to teammates directly` | DUAL — see §IV | Both work. Shepherd's mailbox persists across sessions; platform's `SendMessage` is in-session and is not durable across teammate restart. |
| Task list | NOT a first-class shepherd primitive. Shepherd's task surface is the engineer plan (`{paths.plans}/<sprint>.plan.md`) + GH issue tree | Shared task list at `~/.claude/tasks/{team-name}/` per `https://code.claude.com/docs/en/agent-teams §Architecture` | platform (when Agent Teams enabled) | Shepherd lanes are not platform tasks. A v5.2.0 evaluation may mirror them — see §VII. |
| TeammateIdle event | Hooked by `hooks/scripts/teammate_idle.sh` (registered `TeammateIdle` in `hooks/hooks.json`) | Fired by platform; payload schema per `https://code.claude.com/docs/en/hooks#teammateidle` | platform fires; shepherd handles | Already integrated in v5.1.7. Shepherd marks the teammate idle in DB; lists open escalations + stalled deliverables to stderr. |
| TaskCreated event | NOT consumed | Fired by platform when `TaskCreate` runs; payload schema per `https://code.claude.com/docs/en/hooks#taskcreated` | platform (when consumed) | Reserved for v5.2.0 — see §VII. |
| TaskCompleted event | NOT consumed | Fired by platform when a task is marked complete; payload schema per `https://code.claude.com/docs/en/hooks#taskcompleted` | platform (when consumed) | Reserved for v5.2.0. Note: shepherd's wave-boundary commits are governed by `doctrines/spawn-escalation.md §VI`, not by this hook. |
| SubagentStop event | Hooked by `hooks/scripts/subagent_telemetry.sh` (cache telemetry); also feeds `cmd_teammate.sh heartbeat` when `CLAUDE_TEAMMATE_NAME` is set | Fired per `https://code.claude.com/docs/en/hooks` (event #13) | shepherd | Pre-Agent-Teams shepherd primitive; behavior under test for whether it coexists cleanly with `TeammateIdle` for spawned teammates. |
| Escalation | `escalations` table + `cmd_escalate.sh {create,list,resolve}` per `skills/context/scripts/cmd_escalate.sh` | None | shepherd-only | The escalation contract (`PLAN-AUTHORSHIP-REQUEST`, `PLAN-GATE-REQUEST`, `WRONG-TIER-DISPATCH`, `CROSS-TEAMMATE-DISPUTE`, etc.) per `doctrines/dispatch-tier-separation.md §IV` and `doctrines/spawn-escalation.md` has no platform counterpart. |
| Deliverable | `deliverables` table + `cmd_deliverable.sh {promise,complete,stalled}` per `skills/context/scripts/cmd_deliverable.sh` | None | shepherd-only | The promise/complete pattern (stalled-detector via `Stop` hook `hooks/scripts/deliverable_check.sh`) per `doctrines/sqlite-canonical-state.md §Allow-list` has no platform counterpart. |
| Dispatch tier | `doctrines/dispatch-tier-separation.md §I-II` — three-tier hierarchy (root / meta / flock) | None | shepherd-only | Platform's lead/teammate split is two-tier; shepherd adds a flock tier underneath the conductor. Tier discipline is core shepherd value-add, NOT inherited from platform. |
| Dispute resolution | `agents/shepherd.md §Hard prohibitions #5` + `doctrines/root-shepherd-orchestration.md §VII` (quarantine → aggregate → `@critic` → operator) | None | shepherd-only | Platform's parallel-investigation pattern (per `https://code.claude.com/docs/en/agent-teams §Investigate with competing hypotheses`) is operator-prompted; shepherd's dispute loop is mechanically triggered on conflicting teammate findings. |
| Subagent definitions for teammates | Conductor profile loaded via boot prompt per `commands/spawn.md §Build the teammate prompt` | Subagent type referenceable when spawning per `https://code.claude.com/docs/en/agent-teams §Use subagent definitions for teammates` | DUAL | Behavior under test: whether shepherd should switch from prompt-injected profile to platform's subagent-type-referenced teammate when the platform feature stabilizes. Currently the conductor profile is loaded inline via boot prompt, not by platform subagent reference. |
| Display mode | Tmux always (recommended by `commands/spawn.md §Platform compatibility`); in-process degraded by upstream issue #31977 | `teammateMode: in-process \| tmux \| auto` per `https://code.claude.com/docs/en/agent-teams §Choose a display mode` | platform | Shepherd's recommendation tracks platform's current limitations; if in-process gains Agent-tool parity post-#31977 it becomes equally viable. |
| Plan approval mode | Shepherd plan + `@critic` gate at the root tier per `agents/shepherd.md §Step 1 — INTRODUCTION` | Plan approval mode for teammates per `https://code.claude.com/docs/en/agent-teams §Require plan approval for teammates` | shepherd-only for sprint plans | Platform's plan-approval is per-teammate read-only mode; shepherd's plan-approval is sprint-level via `@critic`. Different scope; no overlap in practice. |
| Cleanup | Per `agents/shepherd.md §Side-effect boundary` (root) + `agents/planter.md §Babysitter mode §3` (delegated planter); also `/shepherd:cleanup` command via `cmd_teammate.sh prune` (v5.1.7+) | "Clean up the team" lead instruction per `https://code.claude.com/docs/en/agent-teams §Clean up the team` | DUAL | Shepherd cleanup is repo-state-aware (worktrees, branches, lock); platform cleanup is team-resource-aware (`~/.claude/teams/`, `~/.claude/tasks/`). Both must run; neither subsumes the other. |
| Permissions | Inherited from lead per `commands/spawn.md §Teammate tool feed` ("the teammate inherits the lead session's permission mode") | Inherited from lead per `https://code.claude.com/docs/en/agent-teams §Permissions` | platform | Identical posture by design; no shepherd override needed. |
| Nested teams | Refused by `/shepherd:spawn` Check 0 per `commands/spawn.md §Preflight` | Forbidden per `https://code.claude.com/docs/en/agent-teams §Limitations` ("No nested teams") | DUAL | Both layers refuse independently. Shepherd's refusal cites platform's limitation but also enforces the doctrine reason (tier separation). |

The table is the seed. Future shepherd revisions may add rows as platform
capabilities expand; the column structure is binding.

---

## III. Overlap rules

For each row in §II where shepherd and platform offer overlapping
implementations, this section declares the **owner**, the **bridge**, and
the **failure mode** when the two diverge.

### Rule 1 — Lead identity

The platform's lead is the Claude Code session that ran `Agent({...})` to
spawn the teammates. Shepherd's lead is the same session, but its
ambient identity is `agents/shepherd.md` (root-tier).

**Owner:** Both. They are the same process; only the identity layer
differs.

**Bridge:** `/shepherd:spawn` adopts `agents/shepherd.md` as the
system-prompt addendum before calling `Agent`. The platform sees a
generic lead; shepherd sees a root-tier orchestrator. Operators must
not load `agents/shepherd.md` outside `/shepherd:spawn` (per
`agents/shepherd.md` Hard prohibition #1 and
`doctrines/root-shepherd-orchestration.md §I`).

**Failure mode:** If a user runs `/shepherd:start` (solo) and then asks
Claude to "create an agent team" via natural language without invoking
`/shepherd:spawn`, the platform may attempt to spawn teammates with no
shepherd identity layer. Result: split-brain — platform-managed
teammates with no conductor profile, no dispatch-tier discipline, no
canonical-state participation. **Operators MUST use `/shepherd:spawn`
to enter shepherd's coordination flow.** Spawning teammates via natural
language is unsupported.

### Rule 2 — Teammate naming

Shepherd's predictable naming convention (`shepherd-{lane|parallel|auto}-{sprint_slug}`)
is essential because:

- `hooks/scripts/teammate_idle.sh` routes by `teammate_name` from the
  hook payload (per `https://code.claude.com/docs/en/hooks#teammateidle`),
  which it then passes to `cmd_teammate.sh heartbeat <name>`. Names not
  matching the `shepherd-` prefix produce no DB row.
- `cmd_teammate.sh liveness` queries the DB by registered name. Platform
  teammates not registered (`cmd_teammate.sh register`) are invisible to
  the liveness index.

**Owner:** Shepherd, because shepherd's downstream consumers (hook,
liveness, escalation routing) depend on names being registered in the
DB.

**Bridge:** The teammate's boot prompt (per `commands/spawn.md §Build
the teammate prompt`) sets `IDENTITY.Name`; the teammate runs
`cmd_teammate.sh register` as part of its `/shepherd:start --teammate`
boot. Names propagate through the platform; the DB row indexes them.

**Failure mode:** If the platform changes name-assignment semantics
(open question OQ-2 in `commands/spawn.md §Open questions`), shepherd's
hook routing may break silently. The DB's `teammates` table is the only
authoritative index; if it has no row for a teammate, the teammate is
invisible to shepherd coordination even if it is running.

### Rule 3 — Teammate status

The platform has no exposed status (per
`https://code.claude.com/docs/en/agent-teams §Limitations`: "Task status
can lag"). Shepherd's `teammates.status` column (`booting` / `active` /
`idle` / `crashed` / `retired`) is the only rich liveness index.

**Owner:** Shepherd.

**Bridge:** `TeammateIdle` hook flips `status` to `idle` in DB
(`hooks/scripts/teammate_idle.sh`). `cmd_teammate.sh heartbeat` flips
`booting` → `active`. `cmd_teammate.sh liveness --stale-mins=N` returns
`presumed-crashed` rows (verdict computed against `last_seen_at` delta).
`/shepherd:cleanup` (v5.1.7+) prunes via `cmd_teammate.sh prune`.

**Failure mode:** A teammate that does not run heartbeat (e.g., platform
spawned outside `/shepherd:spawn`) shows no liveness; shepherd will not
detect it as crashed because there is no `teammates` row.
`agents/shepherd.md §Crashed-teammate detection` polls for
`presumed-crashed` after each wave-gate; operator surface depends on
the row existing.

### Rule 4 — Subagent definitions

The platform supports referencing a subagent definition by name when
spawning a teammate (per
`https://code.claude.com/docs/en/agent-teams §Use subagent definitions
for teammates`). The teammate inherits the definition's `tools`
allowlist and `model`; the definition's body is appended to the
teammate's system prompt.

Shepherd currently loads `agents/conductor.md` via prompt injection in
the teammate boot prompt (per `commands/spawn.md §Build the teammate
prompt > FIRST ACTION`).

**Owner:** Shepherd today; behavior under test for v5.2.0+.

**Bridge:** None active. The two mechanisms produce similar end-states
(conductor profile + tool restrictions), but the platform's
subagent-reference path is not currently exercised by `/shepherd:spawn`.

**Failure mode:** If shepherd switched to platform subagent reference,
the platform's note that `skills` and `mcpServers` frontmatter fields
are NOT applied when running as a teammate (per
`https://code.claude.com/docs/en/agent-teams §Use subagent definitions
for teammates`) would silently strip per-skill MCP configuration. The
current prompt-injection path avoids this risk. Adoption requires
verifying every frontmatter field of `agents/conductor.md` survives the
platform's subagent-as-teammate transformation.

### Rule 5 — Cleanup

The platform's cleanup ("Clean up the team" instruction) handles
`~/.claude/teams/{team-name}/` and `~/.claude/tasks/{team-name}/`.
Shepherd's cleanup handles git worktrees, agent branches,
`.artifacts/shepherd.lock`, and via `/shepherd:cleanup` (v5.1.7+) prunes
stale `teammates` rows.

**Owner:** Both, with non-overlapping scopes.

**Bridge:** The operator must run BOTH at session close:
1. The root shepherd (or planter when delegated) runs cleanup
   stewardship per `agents/planter.md §Babysitter mode §3` —
   `git worktree remove`, `agent-*` branch deletion, lock release.
2. `/shepherd:cleanup` prunes stale DB rows (v5.1.7+; closes #51).
3. The lead instructs the platform to "clean up the team" per the
   Agent Teams docs.

**Failure mode:** Missing step 3 leaves stale `~/.claude/teams/`
entries; missing step 1 leaves orphan worktrees; missing step 2 leaves
stale `teammates` rows. Each failure mode is independent. Operators
must run all three.

---

## IV. Mailbox bridging

The mailbox row in §II is the most live overlap and warrants its own
section. Shepherd's `mailbox` table (`skills/context/scripts/cmd_mailbox.sh`,
schema per `doctrines/sqlite-canonical-state.md §Allow-list`) persists
across sessions. Platform `SendMessage` (per
`https://code.claude.com/docs/en/agent-teams §Talk to teammates directly`)
is in-session and does not survive teammate restart.

### Rules

| Use case | Use which | Why |
|---|---|---|
| Cross-session message (teammate crashes mid-sprint; root responds when teammate respawns) | Shepherd mailbox | Platform `SendMessage` is in-session; a respawned teammate has a new session and cannot read pre-crash messages. |
| In-session message between live sibling teammates in same wave (e.g., lane-A finished its DEDUP-GATE; informs lane-B which was waiting for symbol) | Platform `SendMessage` when Agent Teams enabled; shepherd mailbox fallback | Per `agents/conductor.md §Teammate-to-teammate communication` peer messaging is opportunistic; shepherd mailbox is the platform-independent path. |
| Escalation (teammate → root) | Shepherd mailbox + `cmd_escalate.sh create` | The escalation contract (per `doctrines/spawn-escalation.md`) requires persisted row + structured payload. Platform `SendMessage` has neither. |
| Heartbeat-payload auto-relay (deferred #53 in CHANGELOG.md v5.1.7) | Shepherd mailbox is the natural carrier when implemented | Heartbeat payloads must persist for root to read on next poll; in-session `SendMessage` would lose them on teammate restart. |
| Operator notification (root → operator) | Neither — stderr emission in main chat | Operators read main chat; mailbox + `SendMessage` are agent-to-agent only. |

### Behavior when both are available

When the platform is fully enabled and an in-session `SendMessage` to a
live peer succeeds, the same payload SHOULD also be written to the
shepherd mailbox if the message carries durable significance (e.g., a
finding, a halt-code surface, a deliverable promise). Behavior under
test for v5.1.8: whether dual-write is mechanical (shepherd posts to
both rails) or convention (agents are taught to post to both).

The conservative default in v5.1.8 is: **for any cross-session-relevant
message, write to shepherd mailbox; in-session peer messages MAY also
use `SendMessage` for low-latency surface**. Shepherd mailbox is the
audit trail; `SendMessage` is the live wire.

---

## V. Hook integration

Three platform hooks are relevant to shepherd: `TeammateIdle`,
`TaskCreated`, `TaskCompleted`. One additional hook (`SubagentStop`) is
shepherd's pre-Agent-Teams primitive that overlaps with the platform
ones.

### `TeammateIdle` — adopted v5.1.7

**Platform schema** (per `https://code.claude.com/docs/en/hooks#teammateidle`):

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

Per the docs, the platform fires `TeammateIdle` "when a teammate is
about to go idle"; exit code 2 with stderr blocks the idle state and
keeps the teammate working. Behavior under test: whether the hook
payload always carries `teammate_name` (the shepherd handler reads
`.teammate_name` from stdin JSON per `hooks/scripts/teammate_idle.sh`
line 22); the documented schema does not list `teammate_name`
explicitly.

**Shepherd handler:** `hooks/scripts/teammate_idle.sh` (registered as
`TeammateIdle` in `hooks/hooks.json`).

**Effect:**
1. Marks the teammate `idle` in `teammates` table via `cmd_teammate.sh
   heartbeat <name> --note=idle` and direct UPDATE.
2. Counts open escalations (`cmd_escalate.sh list --open-only`) and
   stalled deliverables (`cmd_deliverable.sh stalled --since-mins=10`).
3. Surfaces a one-line warning to stderr (operator-visible) if either
   count is non-zero: `[shctx] teammate <name> idle |
   open-escalations=N | stalled-deliverables=N`.
4. Never blocks (exits 0 unconditionally).

Per `doctrines/sqlite-canonical-state.md §Cited from`, this hook closes
issue #49 (TEAMMATE-CRASHED halt code + crashed-teammate detection in
`agents/shepherd.md`).

### `TaskCreated` — NOT consumed; v5.2.0 evaluation

**Platform schema** (per `https://code.claude.com/docs/en/hooks#taskcreated`):
identical to `TeammateIdle` schema. Fires when a task is created via
`TaskCreate`; exit code 2 rolls back the task creation.

**Shepherd handler:** None.

**Why not consumed in v5.1.8:** Shepherd's task surface is the engineer
plan (`{paths.plans}/<sprint>.plan.md`) + GH issue tree per
`doctrines/issue-ledger-awareness.md`. Platform tasks (stored at
`~/.claude/tasks/{team-name}/`) are not a shepherd primitive. Shepherd
teammates do call `TaskCreate` (the `tools:` frontmatter on
`agents/conductor.md` lists it), but those tasks are internal to the
teammate session for its own walk tracking; they do not flow into
shepherd's canonical state.

**v5.2.0 evaluation:** if shepherd adopts the platform task list as a
co-canonical surface, `TaskCreated` would write a row to a new
`tasks` table (schema TBD; would respect
`doctrines/sqlite-canonical-state.md`); a new `shctx tasks {sync,list}`
subverb would query/materialize. Decision criteria:
1. Does the platform task list survive teammate crash? (Per the docs,
   "Task status can lag" suggests no strong guarantee.)
2. Does the platform expose a dependency graph rich enough to encode
   the Stage Graph? (Current docs describe pending/in-progress/completed
   with simple dependencies — likely insufficient for shepherd's edge
   predicates per `doctrines/stage-graph.md`.)
3. Does a hybrid (platform tasks for atomic units + shepherd plan for
   structure) reduce operator cognitive load or increase it?

Until the v5.2.0 evaluation closes, shepherd does not consume
`TaskCreated`.

### `TaskCompleted` — NOT consumed; v5.2.0 evaluation

**Platform schema** (per `https://code.claude.com/docs/en/hooks#taskcompleted`):
identical schema. Fires when a task is being marked complete; exit
code 2 prevents completion.

**Shepherd handler:** None in v5.1.8.

**Relation to wave-boundary commits:** `commands/spawn.md §Platform
compatibility` states that `TaskCompleted` "arrived in v2.1.33 and is
required for the wave-boundary commit discipline". However, the
current implementation in `doctrines/spawn-escalation.md §VI` uses
`SendMessage(to: lead, halt_code: null, blocking: false)` as the
wave-complete signal, not `TaskCompleted`. Behavior under test:
whether `TaskCompleted` and the `SendMessage` wave-complete signal
both fire, or whether one supersedes the other. The current shepherd
posture uses `SendMessage` as canonical; `TaskCompleted` is an
adjacent signal that shepherd does not yet consume.

If the v5.2.0 task-list adoption evaluation concludes positively,
`TaskCompleted` becomes the trigger for wave-boundary commit; the
`SendMessage`-based path remains as fallback for non-platform deployments.

### `SubagentStop` — shepherd primitive, predates Agent Teams

**Shepherd handler:** `hooks/scripts/subagent_telemetry.sh` (registered
as `SubagentStop` in `hooks/hooks.json`).

**Effect:** Captures per-dispatch cache telemetry (input/output tokens,
cache read/creation tokens) to `<ns>/logs/events-YYYY-MM-DD.jsonl` per
`doctrines/cache-telemetry.md`. When `CLAUDE_TEAMMATE_NAME` is set, also
emits a teammate heartbeat to the DB (v5.1.7 extension).

**Overlap with `TeammateIdle`:** Per `commands/spawn.md`,
`SubagentStop` fires when a subagent finishes (anywhere — main session,
teammate session, nested dispatch). `TeammateIdle` fires specifically
when a teammate is about to go idle. Behavior under test: whether both
hooks fire for the same event (a teammate finishing its current turn
that also triggers idle), or whether they are disjoint. The current
shepherd code assumes they MAY both fire; the v5.1.7 heartbeat
extension is intentionally idempotent on `last_seen_at` to handle the
overlap.

### Future hooks — not yet consumed

Per `https://code.claude.com/docs/en/hooks` the platform exposes
additional hooks not currently consumed by shepherd. Of note:

- **`SubagentStart`** (event #12) — fires when a subagent is spawned;
  payload carries `agent_id`, `agent_type`. Behavior under test:
  whether this would let shepherd replace the
  `subagent_telemetry.sh`'s current spawn-time-via-Stop inference with
  a real spawn event. Likely v5.1.8+ adoption candidate; non-blocking
  for v5.1.8 release.
- **`WorktreeCreate` / `WorktreeRemove`** (events #23, #24) — already
  consumed by `hooks/scripts/worktree_lifecycle.sh` (per
  `hooks/hooks.json`). These are git-substrate hooks, not Agent Teams
  hooks; included here for completeness.
- **`Stop`** (event #16) — already consumed by
  `hooks/scripts/deliverable_check.sh` for stalled-deliverable
  detection (v5.1.7). Distinct from `SubagentStop`.

Adoption of any of these is documented here when it lands; shepherd
contributors should NOT add new hook consumers without amending §V of
this doctrine.

---

## VI. User opt-in matrix

The operator chooses an operating mode at session start. The matrix
below describes the three valid choices and their tradeoffs.

| Mode | When to use | What you get | Limitations |
|---|---|---|---|
| **shepherd-only (default)** | Always works; recommended for production sprint work | Full conductor profile + lane brief in every teammate; dispatch-tier discipline; canonical SQLite state; escalation contract; deliverable ledger; dispute resolution loop | Heavier teammate context (whole conductor profile + lane brief); each teammate is a full Claude Code session, not a lightweight platform task |
| **Platform Agent Teams (manual prompt to Claude in plain language)** | Research/review tasks where parallel exploration matters more than disciplined dispatch (per `https://code.claude.com/docs/en/agent-teams §Use case examples`) | Lightweight parallel exploration; SendMessage between teammates; platform-managed task list; shorter cycle for ad-hoc parallel work | Experimental (per `https://code.claude.com/docs/en/agent-teams §Limitations`); limited resume semantics (`/resume` and `/rewind` do not restore in-process teammates); no escalations / deliverables / dispute resolution; no canonical state row in shepherd DB |
| **Hybrid (operator manually invokes both)** | NOT SUPPORTED in v5.1.8 | n/a | Risk of split-brain on liveness (platform sees one set of teammates, shepherd sees a different set); naming conflicts in `~/.claude/teams/`; doubled cleanup burden |

**Entering shepherd-only mode:** invoke `/shepherd:spawn` (per
`commands/spawn.md §Smooth path`). Main chat adopts `agents/shepherd.md`;
teammate boots with `agents/conductor.md` (TEAMMATE mode); all
coordination flows through shepherd primitives.

**Entering platform mode:** type a natural-language prompt to Claude
Code asking it to create an agent team (per
`https://code.claude.com/docs/en/agent-teams §Start your first agent
team`). Do NOT also invoke `/shepherd:spawn` — that would attempt to
nest a shepherd team inside a platform team, which is undefined
behavior. `/shepherd:spawn` Check 3 ("No active team") refuses if a
platform team is already running.

**Why hybrid is not supported:** the two systems' liveness indices are
not synchronized. A teammate visible to the platform (via
`~/.claude/teams/{team-name}/config.json#members[]`) but not registered
to `teammates` table is invisible to `cmd_teammate.sh liveness`. A
teammate registered to `teammates` table but not in the platform's
team config is unreachable via platform `SendMessage`. The escalation
contract assumes the same teammate exists in both indices. Mixing the
two without explicit synchronization (deferred to v6.0.0 evaluation,
§VII) leaves shepherd unable to reason about the team's state.

---

## VII. Migration roadmap

The trajectory from "two systems coexist" to "one preferred backend"
is multi-version. Each step is independently shippable and reverts
cleanly.

### v5.1.8 — Document the mapping (this doctrine)

- This doctrine lands at `skills/shepherd/doctrines/claude-code-platform-alignment.md`.
- No behavioral change. `TeammateIdle` consumption continues (v5.1.7).
- `commands/spawn.md` already cites the platform substrate
  prerequisites via Checks 1–3; no change.
- Operators can read this doctrine to understand the boundary; no new
  flags or configuration.

**Acceptance:** doctrine exists; CHANGELOG entry (handled separately by
release manager); v5.1.8 plugin manifest references the doctrine in
SKILL.md doctrines map.

### v5.2.0 — Evaluate consuming `TaskCreated` / `TaskCompleted`

- Spike: implement `hooks/scripts/task_created.sh` and
  `hooks/scripts/task_completed.sh` against a v5.1.8 fork. Mirror
  platform tasks into a new `tasks` table (additive schema migration,
  per `doctrines/sqlite-canonical-state.md §Migration guidance`).
- New `shctx tasks {sync,list,status}` subverb.
- Decision criterion: does the platform task list improve walk
  visibility for operators? If yes, ship as co-canonical (mirror, not
  replace). If no, leave the spike as a documented evaluation only.
- If shipped: `commands/spawn.md` Check 2 minimum version may rise to
  the Claude Code version that stabilizes `TaskCreated` /
  `TaskCompleted` (currently v2.1.33; behavior under test).

**Acceptance:** v5.2.0 release notes carry the decision either way.
No commitment is made in this doctrine.

### v5.2.0 — Deprecate `--auto` alias

Already scheduled per `commands/spawn.md §--scope flag` ("`--auto` is
preserved as an alias for `--scope patch`. Deprecation in v5.2.0,
removal in v6.0.0."). Unrelated to platform alignment except that
post-removal `commands/autorun.md` (thin delta) can also be retired.

### v6.0.0 — Evaluate platform backend toggle

- IF Claude Code Agent Teams exits experimental status AND the
  primitive surface covers shepherd's needs (richer status, persistent
  mailbox, escalation-equivalent, dependency-aware task graph) AND
  operators have indicated demand:
  - Evaluate offering a `[teams].platform_backend = true` toggle in
    `shepherd.toml`.
  - When enabled, shepherd delegates teammate state to the platform.
    The `teammates` table becomes a view over `~/.claude/teams/`;
    `mailbox` becomes a wrapper over `SendMessage`; etc.
  - Doctrine update mandatory: §III rules invert per surface (platform
    wins on each row that delegates).
- IF NOT: shepherd's coordination layer stays independent. Platform
  hooks continue to be consumed where they add value.

**Acceptance:** v6.0.0 release notes carry the decision. v6.0.0 is a
MAJOR version per `CLAUDE.md §Versioning` ("MAJOR = closed-flock
contract change"); the platform-backend toggle is the kind of
contract-shift that justifies the bump regardless of any flock
changes.

### Orthogonal execution axis (v6.0.1) — Dynamic Workflows

The toggle above concerns the *teammate-state* backend (Agent Teams). A
**second, orthogonal** backend axis — *execution* — is evaluated in
`doctrines/workflow-compile-down.md`: compiling the critic-gated Stage Graph's
gate-free, agent-fanout segments to Claude Code **Dynamic Workflows** that the
platform runtime executes out-of-context. Agent Teams owns teammate-state; a
compiled workflow owns a segment's execution; **neither subsumes the other**,
and the two compose. See that doctrine §IV for the faithfulness bar
(soundness / completeness / determinism), §VI for the canonical-state seam, and
§IX for the decision criterion. This doctrine's §VII is the teammate-state axis;
that doctrine is the execution axis. `doctrines/native-coordination.md` (v6.0.1)
maps how these two axes plus the subagent primitive jointly replace the
hand-rolled coordination mechanics (pause-for-dependency / heartbeat / idle-prune).

> **Canonical binding (v6.0.2, #89).** The single source of truth that pins **each
> axis to its primitive and its ontology unit** is `doctrines/primitive-axis-binding.md`:
> planning → none → `waves × steps`; teammate-state/parallelization → **Agent Teams** →
> one teammate-conductor per **lane**; execution → **Dynamic Workflows** → the compiled
> script over **subagents**; worker → **subagents** → the **steps**. That doctrine is the
> fix for the v6.0.1 field regression in which a Dynamic Workflow spawned the conductor
> wave and teammates failed to compile their fan-out (each primitive used for the OTHER's
> job). The §II primitive map here and the execution-axis doctrine both obey it.

---

## VIII. Anti-patterns

The following operator and contributor patterns produce split-brain or
silent erosion of shepherd discipline. Each one is a process violation;
all are catchable by operators or code review.

1. **Spawning teammates via natural language while in a `/shepherd:start`
   session.** Bypasses `agents/shepherd.md` root-tier identity;
   platform-managed teammates have no conductor profile, no
   dispatch-tier discipline. Per §III Rule 1 failure mode.
2. **Reading `~/.claude/teams/{team-name}/config.json` as source of
   truth for teammate liveness.** That file is platform runtime state;
   it does not include shepherd-specific status (`booting` / `active` /
   `idle` / `crashed` / `retired`). Query `teammates` table directly per
   `doctrines/sqlite-canonical-state.md §Anti-patterns #3`.
3. **Adding a new shepherd hook consumer without amending this
   doctrine's §V.** Hooks are part of the platform contract; every
   addition shifts the platform-alignment boundary. Hidden additions
   make this doctrine wrong, which makes operators uncertain about
   which side owns what.
4. **Calling platform `SendMessage` for cross-session messages.** Per
   §IV: `SendMessage` is in-session. A respawned teammate cannot read
   it. Use shepherd mailbox.
5. **Skipping `cmd_teammate.sh register` in the teammate boot.** The
   teammate becomes invisible to shepherd liveness. Required step per
   `commands/spawn.md §Build the teammate prompt > FIRST ACTION`
   (implicit via `/shepherd:start --teammate` flow). Behavior under
   test: whether the flow always runs register, or whether some boot
   paths skip it.
6. **Treating `TaskCreated` / `TaskCompleted` hook payload as
   shepherd-canonical without writing to the DB.** Per §V the hooks
   are NOT consumed in v5.1.8. If they become consumed in v5.2.0+, the
   handler MUST write to the canonical `tasks` table (schema TBD).
   Markdown-only logging of task lifecycle is an anti-pattern per
   `doctrines/sqlite-canonical-state.md §Anti-patterns #2`.
7. **Nesting `/shepherd:spawn` from within a platform-spawned
   teammate.** Refused by `commands/spawn.md` Check 0; refused by the
   platform per `https://code.claude.com/docs/en/agent-teams §Limitations`
   ("No nested teams"). Both layers refuse; either failure alone is
   sufficient.
8. **Loading `agents/shepherd.md` under `/shepherd:start`.** Per
   `doctrines/root-shepherd-orchestration.md §I` the root tier exists
   "only under `/shepherd:spawn`. In solo mode the conductor is its
   own root — no separate `shepherd` profile is loaded." Mis-loading
   produces conflicting Hard prohibitions (the solo conductor permits
   `@engineer` / `@critic`; the root forbids `@coder`).

---

## IX. References

### Shepherd-side citations

- `agents/shepherd.md` — root-tier profile; mode cycle; ROOT CLOSE REPORT
- `agents/conductor.md` — TEAMMATE mode behaviors; side-effect boundary; mode detection
- `agents/planter.md` — babysitter mode; cleanup stewardship; multi-teammate triage
- `commands/spawn.md` — preflight Checks 0–8; platform prerequisites; teammate boot prompt; OQ-1..OQ-6
- `hooks/hooks.json` — registered hook entries (`TeammateIdle`, `Stop`, `SubagentStop`, `WorktreeCreate`, etc.)
- `hooks/scripts/teammate_idle.sh` — `TeammateIdle` handler (v5.1.7+)
- `hooks/scripts/subagent_telemetry.sh` — `SubagentStop` handler (cache + heartbeat v5.1.7)
- `hooks/scripts/deliverable_check.sh` — `Stop` hook stalled-deliverable detector
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

### Platform-side citations

- `https://code.claude.com/docs/en/agent-teams` — Agent Teams primitive (architecture, hooks, team config, mailbox, task list, v2.1.32+, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` flag)
- `https://code.claude.com/docs/en/agent-teams#choose-a-display-mode` — `teammateMode: in-process | tmux | auto`
- `https://code.claude.com/docs/en/agent-teams#use-subagent-definitions-for-teammates` — subagent-type reference at spawn; `skills` / `mcpServers` frontmatter behavior
- `https://code.claude.com/docs/en/agent-teams#limitations` — experimental limitations (no resume, task lag, slow shutdown, one-team-per-lead, no nested teams, lead is fixed)
- `https://code.claude.com/docs/en/hooks#teammateidle` — `TeammateIdle` payload + decision control
- `https://code.claude.com/docs/en/hooks#taskcreated` — `TaskCreated` payload + decision control
- `https://code.claude.com/docs/en/hooks#taskcompleted` — `TaskCompleted` payload + decision control
- `https://code.claude.com/docs/en/hooks` — complete hook event list (29 events as of fetch date)

### Issue references (GitHub)

- Closed in v5.1.7 via SQLite-canonical state: #43, #44, #49, #51, #52 (per `CHANGELOG.md` v5.1.7)
- Deferred to v5.2.0+: #53 — `SendMessage heartbeat_payload` first-class runtime primitive (shctx infrastructure ready; upstream-dependent)
- Upstream Claude Code: anthropics/claude-code#31977 (in-process teammateMode Agent-tool restriction; tracked in `commands/spawn.md §Platform compatibility`)
