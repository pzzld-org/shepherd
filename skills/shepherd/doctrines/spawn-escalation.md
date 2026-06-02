---
name: spawn-escalation
description: |
  Canonical return-and-resume contract between a spawned teammate-conductor and the
  root shepherd (or planter when delegated). Governs every communication path, payload
  schema, resume shape, heartbeat mechanism, and wave-boundary commit discipline for
  /shepherd:spawn sessions. Source of truth for teammate communication bugs.
introduced: v5.1.4
updated: v6.0.3
field_origin: v5.1.4 D-API discovery (.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md)
---

# Doctrine — SPAWN-ESCALATION

## I. Why this doctrine exists

Claude Code Agent Teams (v2.1.144, D-API §11) provides **no session resumption for
in-process teammates** — `/resume` and `/rewind` cannot restore a stalled, crashed,
or interrupted teammate. The escalation channel is therefore load-bearing: every
question the teammate-conductor cannot resolve on its own must reach the root shepherd
(or planter when delegated) through a specified path. This doctrine specifies that
path — channels, payload schema, resume shape, heartbeat, and failure semantics — in
enough detail that any future communication failure traces to a specific broken
invariant here.

> **Terminology note (v5.1.6+):** this doctrine was authored in v5.1.4 when the
> main-chat receiver was always the planter. Under `/shepherd:spawn` (v5.1.6+) the
> main-chat receiver is the **root shepherd profile** (`agents/shepherd.md`). The
> planter may be delegated for seed-amendment work per
> `doctrines/root-shepherd-orchestration.md §V`. All escalation mechanics are
> identical regardless of which profile is active.

> Platform-facts source of truth:
> `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md` (D-API report).
> Contradictions resolved in favor of D-API; flag as Open Question in §IX.

---

## II. Channels

Four complementary channels between teammate-conductor and root shepherd (or planter when delegated).

**Primary: SendMessage mailbox.** Asynchronous; teammate calls
`SendMessage({ to: lead })`; delivered automatically — no polling on receiver
(D-API §8). Use for escalation payloads, wave-complete notifications, heartbeat
status lines. If the root shepherd (or planter when delegated) session is not
running, messages queue but no response is possible. `SendMessage` auto-resumes
stopped agents in background since v2.1.77 (D-API §6) — as long as the teammate
session still exists.

**Durable: shared filesystem.** `~/.claude/tasks/{team-name}/` (team task list)
and `.artifacts/escalations/{sprint_slug}/` (project-local). Use for transcripts,
audit trail, structured escalation files, recovery state when mailbox is
unavailable. **Write contract**: teammate-conductor writes escalation files here
IN ADDITION to the SendMessage call. Do NOT pre-author or edit
`~/.claude/tasks/{team-name}/config.json` — runtime-owned, overwritten on every
state update (D-API §7).

**Hook-driven: lifecycle events.** The following platform events are relevant
to shepherd (D-API §13). Only `TeammateIdle` has a registered shepherd hook script:

| Event | When | Can block? | Shepherd handler |
|---|---|---|---|
| `TeammateIdle` | Teammate about to idle | Yes (exit 2 / `{continue: false}`) | `hooks/scripts/teammate_idle.sh` (registered in `hooks/hooks.json`) |
| `TaskCreated` | Task created via `TaskCreate` | Yes (platform) | **No registered hook script.** Root observes via `TeammateIdle` payload and `SendMessage` WAVE-COMPLETE payloads. |
| `TaskCompleted` | Task marked complete | Yes (platform) | **No registered hook script.** Root reacts via `SendMessage` WAVE-COMPLETE payloads sent by the conductor before completing the task. |

> Lane-routing contract (v6.0.3 — #102): every teammate `task_title` is prefixed
> `"{lane_id}: "` and `assignee` (set via `TaskUpdate(owner: ...)`) is the owning teammate.
> Root routes by the title prefix observed in `TeammateIdle` / `SendMessage` WAVE-COMPLETE
> payloads — NOT via a `TaskCreated`/`TaskCompleted` hook. A task with NO prefix is
> root-owned (terminal `shepherd-{sprint_slug}-close`).

`TeammateIdle` is BLOCKING — primary pause point for operator-mediated escalation.
`TaskCompleted` fires automatically when the conductor marks its wave-scope task done;
wave-boundary commits are triggered by the WAVE-COMPLETE `SendMessage` that precedes it (§VI).
`TeammateIdle` fires on **graceful idle only** — NOT on crash/SIGKILL (D-API Unknown #3);
crash detection is the heartbeat shim (§V).

**Heartbeat: shctx PostToolUse row.** No platform heartbeat primitive exists
(D-API Confirmed Facts); shimmed via a `PostToolUse` hook writing a shctx row per
teammate tool call. Mechanism in §V.

---

## III. Escalation payload shape

Every escalation — via SendMessage or filesystem file — MUST conform. Planter
triages on `halt_code` and `suggested_resolution`; does NOT free-read `question`
to categorise.

```json
{
  "role": "<engineer | critic | coder | auditor | worker | discovery | conductor>",
  "phase": "<intro | body-wave-N | close-N>",
  "halt_code": "<one of agents/conductor.md §Halt codes>",
  "question": "<one sentence — the specific question or condition>",
  "blocking": true,
  "context_files": ["<absolute path>", "..."],
  "suggested_resolution": "<chain-repair | operator-question | hard-stop | null>"
}
```

**Field constraints** (all required):

- `role` — one of seven; `conductor` means the conductor itself is halting (not a sub-agent).
- `phase` — `intro`, `body-wave-1..N`, `close-0..2`; not free text.
- `halt_code` — must match `agents/conductor.md §Halt codes`. Non-null for escalations.
- `question` — one sentence; detail goes in `context_files`.
- `blocking` — `true` if sprint paused; `false` for non-blocking notifications.
- `context_files` — 0–5 absolute paths (plan / wave-gate output / agent report).
- `suggested_resolution` — one of four values; `null` only when conductor has no suggestion.

### Wave-complete notification (non-escalation SendMessage)

Wave completions use the same envelope with `halt_code: null` and `blocking: false`,
`role: "conductor"`, `phase: "body-wave-N"`, `context_files: ["<wave-gate-output>"]`.
Planter reads `halt_code: null` + `blocking: false` as a commit trigger — no
operator interaction.

### Filesystem file naming

```
.artifacts/escalations/{sprint_slug}/{ISO8601-timestamp}-{role}.md
```
Example: `.artifacts/escalations/v514-dev2/2026-05-19T14:32:00-engineer.md`

Content: JSON payload preceded by one markdown header line
`# Escalation — {halt_code} — {role} @ {phase}`. Atomic write. Multiple concurrent
sub-agent escalations are separate files (one timestamp each).

---

## IV. Resume shape

After triage, the root shepherd (or planter when delegated) re-enters the teammate's
conductor. Two recommended options; Option A primary, Option B durable fallback.

### Option A (primary): SendMessage reply payload

```json
{
  "escalation_id": "<timestamp-role from the escalation file name>",
  "resolution": "<chain-repair | operator-answer | abort>",
  "answer": "<the operator's decision or the planter's amendment>",
  "amended_files": ["<paths to files the planter changed>"],
  "resume_instruction": "<one sentence: what the conductor should do next>"
}
```

Planter calls `SendMessage({ to: "shepherd-conductor-{slug}", message: <payload> })`.
Teammate-conductor reads its inbox, extracts the reply by `escalation_id`, resumes.
Auto-resume (v2.1.77+, D-API §6) means delivery re-activates an idled teammate
without a separate resume signal — synchronous, low-latency.

### Option B (durable fallback): filesystem resume path

`.artifacts/escalations/{sprint_slug}/resume/{escalation_id}.md`, same JSON.
Teammate polls on next `TeammateIdle` if no SendMessage reply arrived. Use when
SendMessage errors, the teammate session is no longer active, or the planter is
degraded.

### Option C (deferred to v5.1.5)

In-place seed amendment + re-read signal. Works for chain-repair but introduces a
write-conflict hazard if teammate is mid-read. Deferred pending lock semantics.

### Halt-code → action map

| Escalation category | Resume authority | Path |
|---|---|---|
| `chain-repair` | Planter auto-resumes after amendment | Option A, no operator |
| `operator-question` | Operator confirms; planter sends reply | Option A after operator |
| `hard-stop` | Operator chooses kill/rollback/manual | No auto-resume |

Source: `agents/planter.md §Babysitter mode §1`.

---

## V. Heartbeat mechanism

No platform primitive (D-API Confirmed Facts, Unknown #3). Shimmed via shepherd's
`PostToolUse` hook.

**Write path (teammate side).** `PostToolUse` fires after every teammate tool call:

```sql
INSERT OR REPLACE INTO teammate_heartbeats
  (team_name, role, phase, last_seen, session_id)
VALUES (:team_name, :role, :phase, strftime('%s','now'), :session_id);
```

- `team_name` = `shepherd-conductor-{sprint_slug}` (env or hook input)
- `role` = active sub-agent role (last `TaskCreate`, or `conductor`)
- `phase` = current graph phase (conductor status line)
- `session_id` = teammate's session UUID

> v5.1.4 addition; migration in `skills/context/schema/`. Until migrated, hook
> writes to `.artifacts/logs/heartbeat-{team_name}.jsonl` (append). Planter reads
> whichever exists.

**Read path (root shepherd / planter side).** Manual polling for v5.1.4: after each `TeammateIdle`
or operator interaction.

```bash
tail -1 .artifacts/logs/heartbeat-shepherd-conductor-{sprint_slug}.jsonl
# Or post-migration:
shctx query --team=shepherd-conductor-{sprint_slug} last_heartbeat
```

`shctx parallel status` (auto-surfacing) is v5.1.5.

**Staleness threshold: 5 minutes** of no new heartbeat → alert. Window
accommodates large Agent dispatches that produce no intermediate tool calls.
Operator may extend manually. **Beyond threshold: alert; do NOT auto-recover.**

### Idle-without-WAVE-COMPLETE rule (v6.0.3 — #98)

A conductor that goes idle WITHOUT having sent `WAVE-COMPLETE` (lane not closed) MUST,
on its next wake, send a status `SendMessage(to: lead)` within 1 turn carrying
`{phase, last_node, in_flight_task}`. Root treats a `TeammateIdle` with no preceding
`WAVE-COMPLETE` as a `TEAMMATE-STALL` trigger (not a new halt code). The conductor MUST
also heartbeat at every major phase boundary even while blocked on a background task —
a silent block is indistinguishable from a stall.

### HEARTBEAT ALERT format

```
[HEARTBEAT ALERT] shepherd-conductor-{sprint_slug}
  Last heartbeat: {timestamp} ({elapsed} min ago)
  Phase at last heartbeat: {phase} | Session: {uuid}

No /resume for in-process teammates (D-API §11). Options:
  (1) Wait — may be in long Agent dispatch; re-check in 3 min.
  (2) Probe: SendMessage(to: shepherd-conductor-{slug}, "heartbeat?")
  (3) Declare stall — roll back to last wave-boundary commit; respawn.
```

---

## VI. Wave-boundary commit discipline

The binding contract that limits loss to at most one wave on stall/crash.
Mandatory for both conductor and planter. Non-negotiable.

**Conductor obligation (teammate).** At every wave completion (before next
`WAVE-IMPL`): (1) fire wave-complete SendMessage (`halt_code: null`,
`blocking: false`, `context_files: [<wave-gate-output>]`); (2) let the wave-scope
task complete (`TaskCompleted` fires automatically); (3) wait for resume signal
before next wave — timeout `[spawn].wave_ack_timeout_sec` (default 60s); on
timeout, emit heartbeat and continue (planter is responsible for committing; loss
horizon extends but sprint not blocked). Conductor does NOT call git operations
(`agents/conductor.md §Hard prohibitions #12`, `§Side-effect boundary`). Every
`TaskCreate` carries a `"{lane_id}: "` title prefix and is `TaskUpdate(owner: <self>)`'d
immediately (per `lane-task-ownership.md`).

Wave-gate is mechanical (v6.0.3 — #100): root TaskCreates a `wave-{N}-gate-{sprint_slug}`
marker; each lane's wave-(N+1) IMPL task carries `addBlockedBy` on it (set via `TaskUpdate`);
root releases via `TaskUpdate(status: completed)` only after the gate passes. A blocked
task cannot be claimed, so the wait is enforced by the task list, not prose. If root never
releases: `WAVE-GATE-NOT-RELEASED`.

**Root shepherd obligation (main-chat; or planter when delegated).** On every wave-scope `TaskCompleted`:
(1) read payload — identify files landed; (2) `git status` — confirm branch + no
uncommitted mid-flight state; (3) stage and commit:
```bash
git add -p   # or: git add <paths from context_files>
git commit -m "chore({sprint_branch}/wave-K): wave-complete via spawn"
```
(4) send wave-ack reply via SendMessage. Missed `TaskCompleted` (interrupt, slow)
→ wave artifacts sit uncommitted; next `TaskCompleted` is the recovery
opportunity — catch-up commit all uncommitted artifacts together before proceeding.

### Loss horizon

| Scenario | Loss |
|---|---|
| Teammate stalls in wave N+1, planter committed after wave N | Wave N+1 only |
| Teammate stalls in wave N+1, planter did NOT commit wave N | Waves N and N+1 |
| Teammate crashes before any wave completes | All work since last planter commit |
| Planter session drops while teammate is mid-wave | No commits land; full sprint lost unless planter re-attaches |

Wave-boundary discipline reduces worst case from "full sprint lost" to "one wave
lost". Both parties must honor it.

---

## VII. Failure semantics

Binding recovery rules when the channel or session fails. Planter operates on
these without improvising.

- **Teammate stalls mid-wave.** Detection: heartbeat stale > 5 min (§V). Loss: current wave's uncommitted artifacts. Recovery on operator restart: note last commit SHA, `rm -rf ~/.claude/teams/{team-name}/` (one-team limit), re-invoke `/shepherd:spawn`; teammate re-reads plan + walk trace and continues from next unstarted wave.
- **Teammate session drops (no TeammateIdle).** Detection: session UUID absent from `~/.claude/sessions/`; heartbeat stopped. Loss: current wave + in-transit payloads. Recovery: same as stall; check `.artifacts/escalations/{sprint_slug}/` for any file written before the drop.
- **SendMessage delivery fails.** Primary fallback: read `.artifacts/escalations/{sprint_slug}/<timestamp>-<role>.md` (conductor writes here too). Secondary fallback: treat as stall. Resume: write Option B file instead of SendMessage.
- **Root shepherd session drops (or planter session drops when delegated).** Teammate continues but no commits land; no escalations answered. Loss: all wave artifacts since last root commit. Recovery: re-attached root shepherd (or planter) reads `TeammateIdle` queue + mailbox + filesystem tree; reconstructs state; catch-up commits `git status` deltas. **Hard case**: if teammate already closed, only git-committed portion survives — primary motivation for frequent wave commits.
- **Operator interrupts main chat (Ctrl-C).** Teammate orphaned: no commits land, no escalations answered. Manual cleanup: `~/.claude/teams/shepherd-conductor-{sprint_slug}/`. Prevention: send `SendMessage` "clean stop" before interrupting.

---

## VIII. Non-goals in v5.1.4

Explicitly deferred. Do not implement; do not design flows that assume.

- **No live RPC** — all communication async via mailbox or filesystem (D-API §8).
- **No automatic teammate restart** — operator must re-invoke `/shepherd:spawn`.
- **No multi-team** — one team per lead (D-API §11). Multi-team is v5.1.5+.
- **No `shctx parallel status` command** — planter reads heartbeat rows directly (§V).
- **No cross-teammate routing in single-spawn** — point-to-point conductor → planter. Multiplex topology is §X.
- **No per-teammate config at spawn time** — conductor profile loaded by the teammate's own `/shepherd:start` (D-API §9).

---

## IX. Open questions (single-teammate baseline)

- **OQ-1 (D-API Unknown #1): `teammate_type` in TeammateIdle payload.** May show model slug, `"conductor"`, or agent filename. Mitigation: route by `teammate_name` (`shepherd-conductor-{slug}` — predictable), not `teammate_type`.
- **OQ-2 (D-API Unknown #3): TeammateIdle vs. crash.** `TeammateIdle` does not fire on crash; heartbeat shim (§V) is the only crash detector. Confirm `PostToolUse` is wired before shipping.
- **OQ-3 (D-API Unknown #6): TeammateIdle vs. Stop ordering.** Wave-boundary commits fire on `TaskCompleted` (§VI), not `TeammateIdle`, to avoid the race.
- **OQ-4 (D-API Unknown #4): TaskCreate from a hook script.** Whether the task JSON can be written directly to `~/.claude/tasks/{team-name}/` (vs. requiring a Claude-session tool call) is unconfirmed.

---

## X. Multiplexed escalation (--parallel mode)

Under `/shepherd:spawn --parallel <N>`, N teammates may escalate concurrently.
Base mechanics (§II–§IV) are unchanged per escalation; the root shepherd's (or planter's when delegated) **triage loop** becomes multiplexed.

**Routing keys.** Each escalation routes by `teammate_name`
(`shepherd-parallel-{sprint_slug}` — predictable). `TeammateIdle` payload carries
`teammate_name` (D-API §13). MUST NOT route by `teammate_type` until OQ-1 resolves.
Filesystem path encodes sprint slug: `.artifacts/escalations/{sprint_slug}/...`.
With N teammates, N separate directories; root shepherd (or planter when delegated) reads all N on each
`TeammateIdle`.

### Priority rules

| Priority | Condition | Action |
|---|---|---|
| P0 (CRITICAL preempt) | `halt_code` is one of: `HARD-STOP`, `TEAMMATE-GIT-WRITE`, `BASE-DRIFT`, `PARALLEL-COLLISION` | Jumps queue. Multiple simultaneous CRITICAL → operator decision (spawn.md hard stop) |
| P1 (FIFO) | All other `halt_code` values | First-in-first-out by `TeammateIdle` arrival |
| P-NOTIFY (non-blocking) | `halt_code: null`, `blocking: false` | Wave-complete; immediate commit + ack; no queue |

### Multiplex triage protocol

Root shepherd (or planter when delegated) holds `Q = [(teammate_name, payload), ...]`. Triage by `teammate_name`:

- *Scenario A* (triaging A; B non-CRITICAL): `Q.append(B)`; emit
  `[QUEUE] Teammate B escalation received (halt_code: {code}). Queued at position {len(Q)}. Completing A-triage first.`
  Finish A, resume, then B.
- *Scenario B* (triaging A; B CRITICAL): write bookmark
  `.artifacts/escalations/{sprint_A}/triage-suspended.md`
  (`{suspended_at, triage_stage, reason}`); emit
  `[QUEUE PREEMPT] Interrupting {sprint_A} triage for CRITICAL halt in {sprint_B}`;
  process B to resolution; resume A from bookmark; delete bookmark.
- *Scenario C* (root shepherd / planter busy): `TeammateIdle` is BLOCKING (exit 2); if `len(Q) > 1`,
  exit 2 to hold the idle teammate while clearing queue head. Do NOT hold beyond
  2 min. Deep queue: emit
  `[QUEUE WARNING] {N} escalations pending; teammate {name} held for {elapsed}s`.

### Cross-teammate dependency halts

When A's sprint declares `sprint_dependencies` to B's output, A may halt with
`halt_code: CROSS-DEP-WAIT` (`role: coder`, `phase: body-wave-N`,
`blocking: true`, `suggested_resolution: operator-question`, `context_files`
naming A's import site).

**Planter resolution:**

1. Check B's heartbeat for phase. If B's relevant wave completed: read B's
   wave-gate output for the artifact path; deliver via Option A reply
   (`{ resolution: "operator-answer", answer: "Artifact available at {path}.",
   amended_files: ["{path}"] }`). A resumes — no operator input needed.
2. If B has not produced: notify A `"B's artifact not yet ready. Stand by."`
   Track in status board: `blocked_by: {sprint_B}`. Re-check on each subsequent
   `TeammateIdle`.
3. If `[spawn].cross_dep_timeout_sec` (default 300) expires: escalate to operator
   as `ESCALATION — operator question` with B's phase + heartbeat in context.

### PARALLEL-COLLISION halt

A coder discovering a runtime file collision not caught by the pre-spawn check
surfaces `halt_code: PARALLEL-COLLISION`. **Planter response:**

1. Identify the two colliding sprints from the payload.
2. `SendMessage` to ALL affected teammates: `"PARALLEL-COLLISION received. Halting
   pending conflict resolution. Do NOT proceed."`
3. Surface conflict summary to operator:
   ```
   [PARALLEL-COLLISION]
   Conflicting path: {path}
   Sprint A (shepherd-parallel-{slugA}): wave {N}, role {roleA}
   Sprint B (shepherd-parallel-{slugB}): wave {M}, role {roleB}

   Options:
   (1) Amend sprint A's scope to avoid {path} — planter chain-repair
   (2) Amend sprint B's scope to avoid {path} — planter chain-repair
   (3) Serialize: A finishes {path} first, B reads A's output (cross-dep)
   (4) Abort --parallel run; re-scope manually
   ```
4. On operator choice: execute amendment or serialization, then resume.

### Open questions — §X

**OQ-X1 (MEDIUM): Exit-2 semantics for concurrent TeammateIdle.** D-API §13
documents `TeammateIdle` as BLOCKING. If two teammates fire simultaneously,
whether the platform queues or fires in parallel is undocumented. Until
confirmed: treat each `TeammateIdle` as atomic.

---

## XI. Sequential autopilot (--auto mode)

Under `/shepherd:spawn --auto` the root shepherd (or planter when delegated) runs
a sequential loop. Channel mechanics (§II–§IV) are identical to single-spawn — one
teammate active at a time, no multiplexed queue. This section governs the **loop
boundary**: inter-spawn behavior, patch-end detection, next-teammate context inheritance.

**`TaskCompleted` → root-shepherd-takes-over → spawn-next contract.**

1. `TaskCompleted` fires for the terminal task (conductor's close-synthesis,
   named `shepherd-{sprint_slug}-close`). Authoritative — not `TeammateIdle`,
   which can fire mid-sprint.
2. Root shepherd takes over: `TeammateIdle` fires after the terminal `TaskCompleted`.
   Root shepherd reads the mailbox for CONDUCTOR CLOSE REPORT, verifies, begins
   inter-sprint work (`commands/spawn.md §--auto flag`).
3. Spawn-next: after all 10 inter-sprint steps complete cleanly, root shepherd
   dispatches via `Agent`; new teammate receives the handoff doc path in its
   boot prompt.

**Critical invariant**: root shepherd MUST NOT spawn next until inter-sprint work is
fully committed to git. Incomplete commit state at spawn-next means the new
teammate starts on an inconsistent patch branch.

**Patch boundary detection.**

| Source | How | Precedence |
|---|---|---|
| `shepherd.toml [version].dev_total` | Direct config value | 1 (highest) |
| Seed count on patch branch | `ls {paths.plans}/{patch_slug}-dev*.seed.md \| wc -l` | 2 |
| Operator input during preflight Check 5 | Interactive prompt | 3 (fallback) |

Once `dev.LAST` is determined, it is locked for the loop. No dynamic re-detection
mid-loop — if operator amends scope, they must interrupt, update `shepherd.toml`,
re-invoke `--auto` from the current sprint.

**Loop-termination payload.** Terminal `TaskCompleted` from the closing teammate
carries:

```json
{
  "task_id": "shepherd-{sprint_slug}-close",
  "task_title": "Sprint close — {sprint_slug}",
  "task_result": {
    "grade": "A",
    "carry_forwards": ["#NNN (deferred)", "#MMM (resolved)"],
    "handoff_path": "{paths.docs}/<date>-{sprint_slug}-close-handoff.md",
    "error_budget_consumed": 1,
    "open_questions": []
  },
  "assignee": "shepherd-auto-{sprint_slug}"
}
```

Planter reads `task_result.grade` for GRADE-FLOOR check and
`task_result.error_budget_consumed` for BUDGET-ZERO check. Missing or malformed
`task_result` → treat as GRADE-FLOOR (fail-safe); AUTO ABORT with `grade: UNKNOWN`.

**Context the next teammate inherits.** Three documents in the boot prompt:
the active seed, the **auto-handoff doc** (`{paths.docs}/<date>-{sprint_slug_N+1}-auto-handoff.md`
— authored by planter at inter-sprint step 7; teammate's only history window), and
the carry-forward ledger. Seed alone is NOT sufficient. Missing handoff at
spawn-next → hard stop.

**Operator pause window.** After the 5-second countdown in `commands/spawn.md`,
operator may interrupt by Ctrl-C or any message. Any message during the countdown
is an interrupt unless it equals `'continue'` or `'ok'`. On interrupt, the loop
pauses at the last-completed inter-sprint state — all commits landed, no work lost.
Operator: `'resume auto'` continues from next sprint; `'abort'` terminates with
AUTO ABORT REPORT; any other instruction is manual interaction followed by the
prompt `"Auto-loop is paused. Resume with 'resume auto' or abort with 'abort'."`.

### Open questions — §XI

**OQ-XI1 (MEDIUM): Terminal `TaskCompleted` naming.** Close-synthesis task must
have a predictable name for the planter to distinguish from wave-scope
`TaskCompleted`. Current proposal: `shepherd-{sprint_slug}-close`. If conductor
names differently, planter mis-classifies as wave-complete and commits rather
than triggering inter-sprint work. Confirm with conductor profile author.
RESOLVED (v6.0.3 — #102): terminal tasks carry NO lane prefix; that absence is how root
distinguishes them from wave-scope lane tasks. Terminal name remains `shepherd-{sprint_slug}-close`.

**OQ-XI2 (LOW): Operator interrupt during countdown.** 5-second countdown is
approximated (no daemon timer); a fast operator interrupts before the next turn,
a slow one may not. Acceptable for v5.1.4.

---

## XII. See also

- `skills/shepherd/doctrines/coordinate-active-drive.md` — the root's no-passive-wait coordinate contract (v6.0.5, #113/#98/#112); this doctrine specifies the CHANNEL, that one specifies the root's DRIVE of it (wake→act→probe→yield-to-events; never pause for the operator at dispatch)
- `skills/shepherd/doctrines/native-coordination.md` — native coordination (the pause-for-dependency satellite is retired, #70)
- `skills/shepherd/doctrines/chain-repair.md` — chain-repair amend-and-resume protocol
- `skills/shepherd/doctrines/conductor-cwd.md` — conductor git prohibition
- `agents/conductor.md` — §Escalation protocol, §Side-effect boundary
- `agents/planter.md` — §Babysitter mode (§1 triage, §2 git custody), §Multi-teammate triage (§X implementation), §Sprint rollover (§XI implementation)
- `commands/spawn.md` — §--parallel flag, §--auto flag (operator-facing surfaces)
- `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md` — D-API report
