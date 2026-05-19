---
name: spawn-escalation
description: |
  Canonical return-and-resume contract between a spawned teammate-conductor and the
  main-chat planter/babysitter. Governs every communication path, payload schema,
  resume shape, heartbeat mechanism, and wave-boundary commit discipline for
  /shepherd:spawn sessions. Source of truth for teammate communication bugs.
introduced: v5.1.4
field_origin: v5.1.4 D-API discovery (.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md)
---

# Doctrine — SPAWN-ESCALATION

## I. Why this doctrine exists

The Claude Code Agent Teams platform (as of v2.1.144, per D-API report §11) has a
hard limitation: **there is no session resumption for in-process teammates**. If a
spawned teammate stalls, crashes, or is interrupted, `/resume` and `/rewind` will not
restore it. The lead session may hold stale teammate references that no longer
correspond to living sessions.

This makes the escalation channel load-bearing. Any question the teammate-conductor
cannot resolve on its own must reach the planter (main chat) through a well-specified
path — so the planter can answer it, route it to the operator, or trigger a controlled
recovery. Ad-hoc escalation drifts under pressure: teammates add free-form notes,
planters scan for them inconsistently, and the resulting ambiguity is exactly the
environment in which work is silently lost.

This doctrine specifies the channel, the payload shape, the resume shape, and the
failure semantics in enough detail that a future debugging session can trace a
communication failure to a specific broken invariant here.

> Source of truth for all platform facts cited in this doctrine:
> `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md` (D-API report).
> Any contradiction between this doctrine and the D-API report should be resolved
> in favor of the D-API report, and flagged as an Open Question (§IX below).

---

## II. Channels

Three communication channels exist between the teammate-conductor and the planter.
They are complementary, not redundant: use the right channel for the right purpose.

### Primary: SendMessage mailbox

The platform provides an asynchronous mailbox. The teammate calls
`SendMessage({ to: lead })` and the message is delivered automatically — no polling
required on the receiving side (D-API §8).

Use for: escalation payloads, wave-complete notifications, heartbeat status lines.

**Limitation**: if the planter session is not running (operator interruption, dropped
main-chat session), messages queue but no response is possible. The planter will read
queued messages on re-attach, but if the teammate's `TeammateIdle` timeout passes
first, the work may stall waiting for a reply that never came.

`SendMessage` auto-resumes stopped agents in the background (since v2.1.77, D-API §6).
If the teammate stops between pipeline stages, the planter can message it and it will
re-activate without manual intervention — as long as the teammate session still exists.

### Durable: shared filesystem

Path: `~/.claude/tasks/{team-name}/` (team task list) and the project-local escalation
tree (`.artifacts/escalations/{sprint_slug}/`).

Use for: transcripts, audit trail, structured escalation files written by the conductor,
recovery state when the mailbox path is unavailable.

**Write contract**: the teammate-conductor writes escalation files here in addition to
(not instead of) the SendMessage call. The planter reads here when the mailbox is
unavailable or when verifying a prior escalation.

Do NOT pre-author or edit `~/.claude/tasks/{team-name}/config.json` — it is owned by
the runtime and overwritten on every state update (D-API §7).

### Hook-driven: lifecycle events

Three hook events fire in the **lead's context** (D-API §13):

| Event | When | Can block? | Payload fields |
|---|---|---|---|
| `TeammateIdle` | Teammate about to go idle | Yes (exit 2 or `{continue: false}`) | `teammate_name`, `teammate_type` |
| `TaskCreated` | Task being created via `TaskCreate` | Yes | `task_id`, `task_title`, `task_description`, `assignee` |
| `TaskCompleted` | Task being marked complete | Yes | `task_id`, `task_title`, `task_result`, `assignee` |

`TeammateIdle` fires in the lead context and can block the teammate from idling (exit 2).
This is the primary pause point for operator-mediated escalation response.

`TaskCompleted` is the trigger for wave-boundary commits (see §VII).

`TeammateIdle` fires on **graceful idle only** — it does NOT fire on crash or SIGKILL
(D-API Unknown #3). Crash detection relies on the heartbeat shim (§VI).

### Heartbeat: shctx PostToolUse row

There is **no platform heartbeat primitive** for teammates (D-API §Confirmed Facts,
Heartbeat row). Staleness detection is shimmed via a `PostToolUse` hook that writes
a row to the shctx registry on every teammate tool call.

See §VI for the exact mechanism.

---

## III. Escalation payload shape

Every escalation the teammate surfaces — whether via SendMessage or the filesystem
file — MUST conform to this schema. The planter triages on `halt_code` and
`suggested_resolution`; it does NOT free-read the `question` to determine category.

```json
{
  "role": "<one of: engineer | critic | coder | auditor | worker | discovery | conductor>",
  "phase": "<one of: intro | body-wave-N | close-N>",
  "halt_code": "<one of the halt codes from agents/conductor.md §Halt codes>",
  "question": "<one sentence — the specific question or condition that caused the halt>",
  "blocking": true,
  "context_files": [
    "<absolute path to file 1>",
    "<absolute path to file 2>"
  ],
  "suggested_resolution": "<one of: chain-repair | operator-question | hard-stop | null>"
}
```

### Field constraints

| Field | Required | Constraint |
|---|---|---|
| `role` | YES | Must be one of the eight named roles. `conductor` means the conductor itself is halting (not a sub-agent). |
| `phase` | YES | `intro`, `body-wave-1` through `body-wave-N`, `close-0` through `close-2`. Not free text. |
| `halt_code` | YES | Must match a halt code in `agents/conductor.md §Halt codes`. Non-null. |
| `question` | YES | One sentence. If the question needs more, put detail in `context_files`. |
| `blocking` | YES | `true` if the sprint is paused waiting for this answer; `false` for non-blocking wave-complete notifications (which use `halt_code: null`). |
| `context_files` | YES | 0–5 paths. Include the plan, the wave-gate output, and the relevant agent report. Do not include the full sprint plan if a section is sufficient. |
| `suggested_resolution` | YES | One of the four values. `null` only when the conductor has no suggestion. |

### Wave-complete notification (non-escalation SendMessage)

Wave completions are sent as SendMessage but are NOT escalations. Distinguish them
by `halt_code: null` and `blocking: false`:

```json
{
  "role": "conductor",
  "phase": "body-wave-N",
  "halt_code": null,
  "question": null,
  "blocking": false,
  "context_files": ["<path to wave-gate output>"],
  "suggested_resolution": null
}
```

The planter reads `halt_code: null` + `blocking: false` as a commit trigger, not
a question. No operator interaction required — just commit.

### Filesystem file naming

```
.artifacts/escalations/{sprint_slug}/{ISO8601-timestamp}-{role}.md
```

Example: `.artifacts/escalations/v514-dev2/2026-05-19T14:32:00-engineer.md`

File content: the JSON payload above, preceded by a single markdown header line:
```
# Escalation — {halt_code} — {role} @ {phase}
```

The file is written atomically. The planter reads it by parsing the JSON block.
Multiple concurrent escalations from different sub-agents are separate files (each
sub-agent produces its own file with its own timestamp).

---

## IV. Resume shape

After the planter triages an escalation and has an answer, it must re-enter the
teammate's conductor. Three options exist; this doctrine recommends Option A as
primary with Option B as durable fallback.

### Option A (primary): planter SendMessages a reply payload

```json
{
  "escalation_id": "<timestamp-role from the escalation file name>",
  "resolution": "<chain-repair | operator-answer | abort>",
  "answer": "<the operator's decision or the planter's amendment>",
  "amended_files": ["<paths to files the planter changed>"],
  "resume_instruction": "<one sentence: what the conductor should do next>"
}
```

The planter calls `SendMessage({ to: "shepherd-conductor-{sprint_slug}", message: <payload> })`.
The teammate-conductor reads its inbox, extracts the reply by `escalation_id`, and
resumes from the halted node.

`SendMessage` auto-resumes stopped agents (v2.1.77+, D-API §6), so even if the
teammate went idle while waiting, the message delivery re-activates it.

**Why Option A is primary**: synchronous from the planter's perspective; no file polling
latency; the platform's auto-resume behavior means the reply is sufficient to restart
the teammate without a separate resume signal.

### Option B (durable fallback): planter writes to filesystem resume path

Path: `.artifacts/escalations/{sprint_slug}/resume/{escalation_id}.md`

Content: same JSON payload as Option A, written as a file.

The teammate-conductor polls this directory after waking from `TeammateIdle` if no
SendMessage reply arrived. Poll interval: on every `TeammateIdle` fire (natural pace;
not a busy loop).

Use Option B when: the primary `SendMessage` call returns an error; the team config
shows the teammate session is no longer active (possible after a restart); or the
planter is operating in a degraded session that cannot call SendMessage.

### Option C (NOT recommended for v5.1.4): planter modifies seed in-place

The planter could amend the seed or plan file and signal the teammate to re-read on
next `TeammateIdle`. This works for chain-repair amendments but introduces a
write-conflict hazard if the teammate is mid-read. Option C is deferred to v5.1.5
with proper lock semantics. Do not use in v5.1.4.

### Auto-resume vs. operator-confirmed resume

| Escalation category | Resume authority | Resume path |
|---|---|---|
| `chain-repair` | Planter may auto-resume after amendment | Option A, no operator input required |
| `operator-question` | Operator must confirm answer; planter sends reply | Option A after operator confirms |
| `hard-stop` | Operator must choose kill/rollback/manual | No auto-resume; operator decides |

Source: `agents/planter.md §Babysitter mode §1` (escalation triage protocol).

---

## V. Heartbeat mechanism

There is no platform heartbeat primitive (D-API §Confirmed Facts, D-API Unknown #3).
Staleness detection is entirely shimmed in shepherd's `PostToolUse` hook.

### Write path (teammate side)

A `PostToolUse` hook fires after every tool call in the teammate's session. The hook
script writes a row to the shctx registry:

```sql
INSERT OR REPLACE INTO teammate_heartbeats
  (team_name, role, phase, last_seen, session_id)
VALUES
  (:team_name, :role, :phase, strftime('%s', 'now'), :session_id);
```

Where:
- `team_name` = `shepherd-conductor-{sprint_slug}` (from env or hook input)
- `role` = current active sub-agent role (from last `TaskCreate` payload, or `conductor`)
- `phase` = current graph phase (from the conductor's emitted status line)
- `session_id` = the teammate's session UUID

> Note: the `teammate_heartbeats` table is a v5.1.4 addition. The shctx schema
> migration is tracked in `skills/context/schema/`. Until the migration runs, the
> hook writes to a flat file at `.artifacts/logs/heartbeat-{team_name}.jsonl`
> (append-mode). The planter reads whichever exists.

### Read path (planter side)

The planter polls for staleness. For v5.1.4, polling is manual: the planter reads
the heartbeat row (or flat file) after each `TeammateIdle` fire or after each
operator interaction.

```bash
# Fast-path: read the flat file if table not yet migrated
tail -1 .artifacts/logs/heartbeat-shepherd-conductor-{sprint_slug}.jsonl
# Or via shctx (when table is available):
shctx query --team=shepherd-conductor-{sprint_slug} last_heartbeat
```

Note: `shctx parallel status` (which would surface this automatically) is planned
for v5.1.5. In v5.1.4, the planter reads the row directly.

### Staleness threshold

**5 minutes** of no new heartbeat row → alert the operator.

A 5-minute window accommodates large Agent dispatches (e.g., a full Opus engineer
run) that produce no intermediate tool calls visible to the hook. If the operator
knows a large dispatch is in flight, they may extend the threshold manually.

Beyond the threshold: **alert operator; do NOT auto-recover**.

```
[HEARTBEAT ALERT] shepherd-conductor-{sprint_slug}
  Last heartbeat: {timestamp} ({elapsed} min ago)
  Phase at last heartbeat: {phase}
  Session ID: {uuid}

The teammate may be stalled. There is no /resume for in-process teammates (D-API §11).

Options:
  (1) Wait — the teammate may be in a long Agent dispatch. Check again in 3 min.
  (2) Send a probe: SendMessage(to: shepherd-conductor-{sprint_slug}, message: "heartbeat?")
  (3) Declare stall — roll back to last wave-boundary commit; restart with /shepherd:spawn.
```

---

## VI. Wave-boundary commit discipline

This is the binding contract that limits loss to at most one wave when a teammate
stalls or crashes. Mandatory for both the conductor and the planter. Non-negotiable.

### Conductor obligation (teammate side)

At the completion of every wave (before moving to the next wave's `WAVE-IMPL` batch):

1. **Fire the wave-complete SendMessage** with `halt_code: null`, `blocking: false`,
   `context_files: [<wave-gate-output-path>]`.
2. **Let the wave-scope task complete** (the `TaskCompleted` hook fires automatically
   when the task is marked done).
3. **Wait for a resume signal** from the planter before dispatching the next wave.
   Wait duration: configurable via `shepherd.toml [spawn].wave_ack_timeout_sec`
   (default: 60 seconds). After timeout without a resume: emit a heartbeat line and
   continue. The planter is responsible for committing; if it doesn't, the
   loss horizon extends but the sprint is not blocked.

The conductor does NOT call git operations (commit, push, branch). See
`agents/conductor.md §Hard prohibitions #12` and `§Side-effect boundary`. All git
writes are the planter's exclusive domain.

### Planter obligation (main-chat side)

On every `TaskCompleted` hook fire that corresponds to a wave-scope task:

1. **Read the wave-complete SendMessage payload** to identify which files landed.
2. **Run `git status`** on the sprint branch. Confirm the branch is correct and
   no uncommitted mid-flight state would be overwritten.
3. **Stage and commit**:
   ```bash
   git add -p   # or git add <specific-paths from payload context_files>
   git commit -m "chore({sprint_branch}/wave-K): wave-complete via spawn"
   ```
4. **Send a wave-ack reply** via SendMessage so the teammate knows the commit landed
   and can continue to the next wave.

If the planter misses a `TaskCompleted` fire (interrupted, slow, etc.), the wave's
artifacts sit uncommitted. The next `TaskCompleted` is a recovery opportunity — commit
all uncommitted wave artifacts together in one catch-up commit before proceeding.

### Loss horizon

| Scenario | Loss |
|---|---|
| Teammate stalls in wave N+1, planter committed after wave N | Wave N+1 work only |
| Teammate stalls in wave N+1, planter did NOT commit wave N | Waves N and N+1 |
| Teammate crashes before any wave completes | All work since last planter commit |
| Planter session drops while teammate is mid-wave | Teammate continues; no commits land; full sprint lost unless planter re-attaches |

The wave-boundary commit discipline reduces the worst case from "full sprint lost"
to "one wave lost". Both parties must honor it for the guarantee to hold.

---

## VII. Failure semantics

These are the binding recovery rules when the escalation channel or the session
itself fails. The planter operates on these rules without improvising.

### Teammate stalls mid-wave

- **Detection**: heartbeat stale > 5 min (§V).
- **Loss**: current wave's uncommitted artifacts.
- **Recovery**: operator decision required (§V options). If operator chooses restart:
  1. Note the sprint branch's last commit SHA: `git log {sprint_branch} --oneline | head -1`.
  2. That commit is the recovery point.
  3. Remove the stale team config: `rm -rf ~/.claude/teams/{team-name}/` (one-team limit).
  4. Re-invoke `/shepherd:spawn`. Teammate re-reads the plan, finds walk position from
     git log + walk trace, and continues from the next unstarted wave.

### Teammate session drops (no TeammateIdle)

- **Detection**: session UUID absent from `~/.claude/sessions/`; heartbeat stopped.
- **Loss**: current wave + any SendMessage payloads in transit.
- **Recovery**: same as stall recovery above. Transit messages are lost — if an
  escalation was in-flight, its content is gone. The planter should check the
  filesystem path (`.artifacts/escalations/{sprint_slug}/`) for any file the conductor
  may have written before the drop.

### SendMessage delivery fails

- **Primary fallback**: read the filesystem path
  `.artifacts/escalations/{sprint_slug}/<timestamp>-<role>.md`.
  The conductor writes here in addition to the mailbox call.
- **Secondary fallback**: if filesystem also shows no file, treat as a stall and alert.
- **Resume path**: write the reply to `.artifacts/escalations/{sprint_slug}/resume/{id}.md`
  (Option B from §IV) instead of SendMessage.

### Planter session drops

- **Effect**: teammate-conductor continues running but no commits land on wave
  boundaries. No escalations are answered. The team will eventually idle.
- **Loss**: any wave artifacts produced after the last planter commit. The teammate's
  work exists in its session but is not persisted to the sprint branch.
- **Recovery**: the planter session that re-attaches (same or new main-chat session)
  reads the `TeammateIdle` queue, the mailbox, and the filesystem escalation tree to
  reconstruct the state. Then issues catch-up commits for any uncommitted wave
  artifacts visible in `git status`.
- **Hard case**: if the teammate has already closed before the planter re-attaches,
  its artifacts are gone. Only the git-committed portion survives. This is the
  most dangerous failure mode and is the primary motivation for frequent
  wave-boundary commits.

---

## VIII. Non-goals in v5.1.4 (single-teammate baseline)

These are explicitly deferred. Do not implement them in this patch; do not design
escalation flows that assume them.

- **No live RPC between teammates.** There is no shared memory or synchronous
  inter-session call. All communication is asynchronous via the mailbox or filesystem.
  D-API §8: "No live RPC: there is no shared memory or live RPC bus."
- **No automatic teammate restart.** If the teammate dies, the operator must
  explicitly invoke `/shepherd:spawn` again. No auto-recovery logic in this patch.
- **No multi-team.** One team per lead session — D-API §11 confirmed hard limit.
  Multi-team support is a v5.1.5+ concern.
- **No `shctx parallel status` command** (v5.1.5 addition). For v5.1.4, the planter
  reads heartbeat rows directly (§V). When `shctx parallel status` ships, replace the
  manual read with the command.
- **No cross-teammate escalation routing.** In v5.1.4 there is exactly one teammate.
  The escalation channel is point-to-point: conductor → planter. Multi-teammate
  routing topology is v5.1.5+.
- **No per-teammate config at spawn time.** The conductor profile is loaded by the
  teammate's own `/shepherd:start` invocation, not injected by the spawner.
  D-API §9: "there are no per-teammate config files beyond the team config."

---

## IX. Open questions (single-teammate baseline)

These questions were raised by the D-API report and are not yet resolved.
The engineer's plan must address them before the escalation channel can be
considered fully specified.

**OQ-1 (from D-API Unknown #1): `teammate_type` in TeammateIdle payload.**
When a shepherd conductor teammate is spawned, does `teammate_type` in the hook
payload show the model slug, `"conductor"`, or the filename of the agent definition
used? This matters for hook routing scripts. Mitigation for v5.1.4: route by
`teammate_name` (predictable: `shepherd-conductor-{sprint_slug}`), not `teammate_type`.

**OQ-2 (from D-API Unknown #3): TeammateIdle vs. crash.**
`TeammateIdle` does not fire on teammate crash. The heartbeat shim (§V) is the only
crash-detection mechanism. If the `PostToolUse` hook is not wired, staleness goes
undetected. Confirm that the hook is wired before shipping. If not wired, operator
must check heartbeat manually.

**OQ-3 (from D-API Unknown #6): TeammateIdle vs. Stop hook ordering.**
Which fires first in the lead context: `TeammateIdle` or the teammate's own `Stop`
hook? If `Stop` fires first (in teammate context), a heartbeat row written in `Stop`
may be the first signal of clean completion. If `TeammateIdle` fires first (in lead
context), the heartbeat row the `Stop` hook would write may not have landed yet.
Wave-boundary commits should fire on `TaskCompleted` (§VI), not on `TeammateIdle`,
to avoid this race.

**OQ-4 (from D-API Unknown #4): Can TaskCreate be called from a hook script?**
The wave-boundary task management uses `TaskCreate` tool (Claude context) not a bash
API. If shepherd's hook scripts need to create tasks programmatically, confirm whether
the task JSON can be written directly to `~/.claude/tasks/{team-name}/` or if the
tool must be called from a Claude session.

---

---

## X. Multiplexed escalation (--parallel mode)

When `/shepherd:spawn --parallel <N>` is active, N teammates may surface escalations
concurrently. The base channel mechanics (§II–§IV) remain identical for each
individual escalation — one payload per teammate, one resume reply per payload. The
planter's **triage loop** is what changes: it becomes a multiplexed queue.

### Routing keys

Each escalation is routed by `teammate_name` (the predictable `shepherd-parallel-{sprint_slug}`
string). The `TeammateIdle` hook payload carries `teammate_name` (D-API §13), which is
the unambiguous key. The planter MUST NOT route by `teammate_type` until OQ-1 is
resolved (§IX).

The escalation filesystem path encodes the sprint slug:
```
.artifacts/escalations/{sprint_slug}/{timestamp}-{role}.md
```

When N teammates are active, N separate `{sprint_slug}/` directories exist. The
planter reads all N directories on each `TeammateIdle` fire; a new file in any
directory is a pending escalation.

### Priority rules

| Priority | Condition | Action |
|---|---|---|
| P0 (CRITICAL preemption) | `halt_code` is a CRITICAL-tier code per `agents/conductor.md §Halt codes` | Jumps queue immediately. Multiple simultaneous CRITICAL halts → operator decision (§Hard stops #9 in spawn.md) |
| P1 (FIFO) | All other `halt_code` values | Processed first-in-first-out by `TeammateIdle` arrival time |
| P-NOTIFY (non-blocking) | `halt_code: null`, `blocking: false` | Wave-complete notification; processed immediately (no queue); triggers a commit and wave-ack |

### Queue state during mid-triage arrival

The planter holds an in-memory queue. Notation: `Q = [(teammate_name, payload), ...]`.

**Scenario A: planter is mid-triaging teammate A; teammate B fires a non-CRITICAL halt.**
- Enqueue B: `Q.append((B, payload_B))`.
- Emit: `[QUEUE] Teammate B escalation received (halt_code: {code}). Queued at position {len(Q)}. Completing A-triage first.`
- Finish A-triage. Call SendMessage to resume A. Then process B.

**Scenario B: planter is mid-triaging teammate A; teammate B fires a CRITICAL halt.**
- Suspend A-triage: write bookmark to `.artifacts/escalations/{sprint_A}/triage-suspended.md`:
  ```json
  { "suspended_at": "<ISO-timestamp>", "triage_stage": "<stage>", "reason": "CRITICAL preempt from {sprint_B}" }
  ```
- Emit: `[QUEUE PREEMPT] Interrupting {sprint_A} triage for CRITICAL halt in {sprint_B}`.
- Process B to resolution. Send B's resume signal.
- Return to A: re-read the suspension bookmark, continue A-triage from the bookmark stage.
- Delete the suspension bookmark after A-triage completes.

**Scenario C: planter's own main-chat session is slow/busy while escalations queue.**
- The TeammateIdle hook is BLOCKING (can exit 2). Use this: if the planter has >1
  queued item, exit 2 on the current TeammateIdle to hold the idle teammate while
  the planter clears the queue head first.
- Do NOT hold a teammate idle beyond 2 minutes. If the queue is deep: emit
  `[QUEUE WARNING] {N} escalations pending; teammate {name} held for {elapsed}s`.

### Cross-teammate dependency halts

When teammate A's sprint declares a `sprint_dependencies` link to teammate B's output
(e.g., B generates a type definition that A imports), A may halt with:

```json
{
  "halt_code": "CROSS-DEP-WAIT",
  "role": "coder",
  "phase": "body-wave-2",
  "question": "Waiting for {path} from sprint {sprint_B}. Not yet produced.",
  "blocking": true,
  "context_files": ["path/to/A/import_site.rs"],
  "suggested_resolution": "operator-question"
}
```

**Planter resolution procedure:**

1. Check teammate B's heartbeat row for phase. If B's relevant wave has completed:
   - Read B's wave-gate output for the artifact path.
   - Deliver via resume reply (§IV Option A):
     ```json
     { "resolution": "operator-answer",
       "answer": "Artifact available at {path}. Proceed.",
       "amended_files": ["{path}"] }
     ```
   - A resumes immediately (no operator input needed for this case).

2. If B has not yet produced the artifact:
   - Notify A: `SendMessage(to: A, "B's artifact not yet ready. Stand by — planter will
     notify when available.")` Do NOT mark A as resumed yet; let it stay idle.
   - Re-check after each subsequent `TeammateIdle` fire. When B's wave completes,
     deliver the artifact path to A.
   - Track in the status board under A's row: `blocked_by: {sprint_B}`.

3. If `[spawn].cross_dep_timeout_sec` (default 300) expires without B producing the artifact:
   - Escalate to operator as `ESCALATION — operator question`.
   - Include B's current phase and heartbeat data in the context_files.

### PARALLEL-COLLISION halt

If, after spawn, a coder in any teammate discovers a runtime file collision (shared
path not detected by the pre-spawn check), it surfaces `halt_code: PARALLEL-COLLISION`.

**Planter response:**

1. Receive the PARALLEL-COLLISION payload. Identify which two sprints collide.
2. Immediately send `SendMessage` to ALL affected teammates: `"PARALLEL-COLLISION halt
   received. Halting your sprint pending conflict resolution. Do NOT proceed to the next
   node."` Do not resume any affected teammate until the conflict is resolved.
3. Surface to operator with a conflict summary:
   ```
   [PARALLEL-COLLISION]
   Conflicting path: {path}
   Sprint A (shepherd-parallel-{slugA}): wave {N}, role {roleA}
   Sprint B (shepherd-parallel-{slugB}): wave {M}, role {roleB}

   Options:
   (1) Amend sprint A's scope to avoid {path} — planter can chain-repair
   (2) Amend sprint B's scope to avoid {path} — planter can chain-repair
   (3) Serialize: let A finish {path} first, then B reads A's output (sets cross-dep)
   (4) Abort the --parallel run; re-scope manually
   ```
4. On operator choice: execute the amendment or serialization, then resume affected teammates.

### Open questions — §X

**OQ-X1 (MEDIUM): Exit-2 semantics for multiple concurrent TeammateIdle events.**
D-API §13 documents `TeammateIdle` as BLOCKING (exit 2 = keep working). If two
teammates fire `TeammateIdle` at the same time and the planter's hook scripts are
executed in sequence, the second hook may fire before the first is resolved. Whether
the platform queues these or fires them in parallel is not documented. Until confirmed:
treat each `TeammateIdle` as atomic (the planter handles only one at a time); the queue
above is the in-memory representation, not a platform primitive.

---

## XI. Sequential autopilot (--auto mode)

When `/shepherd:spawn --auto` is active, the planter runs a sequential loop. The
escalation channel (§II–§IV) is the same as single-spawn — only one teammate is
active at a time, so there is no multiplexed queue. The additions in this section
govern the **loop boundary** behavior: what the planter does between spawns, how it
detects the patch end, and what context the next teammate inherits.

### `TaskCompleted` → planter-takes-over → spawn-next contract

The binding transition between two auto-loop iterations:

1. **`TaskCompleted` fires** for the terminal task of the sprint (the conductor's close
   synthesis task). This is the authoritative signal that the sprint is done —
   not just `TeammateIdle`, which can fire mid-sprint when the teammate is waiting.
   The conductor MUST complete a named task (e.g., `shepherd-{sprint_slug}-close`)
   to signal loop completion.

2. **Planter takes over**: the `TeammateIdle` hook fires immediately after the
   terminal `TaskCompleted`. The planter reads the mailbox for the CONDUCTOR CLOSE
   REPORT envelope, verifies it, and begins the inter-sprint work checklist
   (`commands/spawn.md §--auto flag, Inter-sprint work`).

3. **Spawn-next**: after inter-sprint work completes cleanly (all 10 steps verified),
   the planter dispatches the next teammate via `Agent`. The new teammate receives the
   handoff doc path in its boot prompt (§ Build the teammate prompt, `commands/spawn.md`).

**Critical invariant**: the planter MUST NOT spawn the next teammate until the
inter-sprint work is fully committed to git. An incomplete commit state at spawn-next
means the new teammate starts with an inconsistent patch branch.

### Patch boundary detection

The planter determines `dev.LAST` from three sources (in precedence order):

| Source | How | Precedence |
|---|---|---|
| `shepherd.toml [version].dev_total` | Direct config value | 1 (highest) |
| Seed count on the patch branch | `ls {paths.plans}/{patch_slug}-dev*.seed.md \| wc -l` | 2 |
| Operator input during preflight Check 5 | Interactive prompt | 3 (fallback) |

Once `dev.LAST` is determined, it is locked for the lifetime of the auto-loop. The
planter does NOT dynamically re-detect `dev.LAST` mid-loop. If the operator amends
the scope mid-loop (e.g., "add one more sprint"), they must interrupt the loop,
update `shepherd.toml`, and re-invoke `--auto` from the current sprint.

### Loop-termination payload shape

When the auto-loop terminates (any condition), the final `TaskCompleted` from the
closing teammate carries the terminal sprint's grade and carry-forwards. The planter
reads this to produce the termination report.

Expected `TaskCompleted` payload (produced by the conductor at close synthesis):

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

The planter reads `task_result.grade` for the GRADE-FLOOR termination check and
`task_result.error_budget_consumed` for the BUDGET-ZERO check.

If `task_result` is missing or malformed, the planter treats it as a GRADE-FLOOR
event (fail-safe) and emits an AUTO ABORT REPORT with `grade: UNKNOWN`.

### Context the next teammate inherits

The next teammate (context window = zero prior sprint history) receives three
documents in its boot prompt:

1. **Active seed**: `{paths.plans}/{sprint_slug_N+1}.seed.md` — the plan.
2. **Auto-handoff doc**: `{paths.docs}/<date>-{sprint_slug_N+1}-auto-handoff.md` —
   authored by the planter during inter-sprint step 7. Contains prior sprint summary,
   carry-forwards, branch state, error budget. This is the teammate's only window
   into what happened before it woke up.
3. **Carry-forward ledger**: `{ledger.carry_forward_file}` — chronic items.

The seed alone is NOT sufficient. The handoff doc is mandatory. If the handoff doc
is missing when spawn-next fires, the planter emits hard stop #13
(`commands/spawn.md §--auto flag, Hard stops specific to --auto`).

### Operator pause window

Between each spawn (after the 5-second countdown in `commands/spawn.md §--auto flag`),
the operator may interrupt by pressing Ctrl-C or sending any message. The planter
treats any message during the countdown as an interrupt unless the message is exactly
`'continue'` or `'ok'`.

When interrupted, the loop pauses at the most recently completed inter-sprint work
state. All git commits from the inter-sprint checklist have already landed — no work
is lost. The operator can:
- `'resume auto'` — continue the loop from the next sprint.
- `'abort'` — terminate the loop; planter emits AUTO ABORT REPORT.
- Any other instruction — the planter treats it as a manual operator interaction,
  executes it, then asks: `"Auto-loop is paused. Resume with 'resume auto' or abort with 'abort'."`.

### Open questions — §XI

**OQ-XI1 (MEDIUM): `TaskCompleted` for terminal task — naming convention.**
The close synthesis task must have a predictable name for the planter to distinguish
it from wave-scope `TaskCompleted` events. Current proposal: `shepherd-{sprint_slug}-close`.
If the conductor names this task differently, the planter will mis-classify the
terminal signal as a wave-complete notification and commit rather than trigger the
inter-sprint work. Confirm the task name with the conductor profile author before
the first auto-loop runs.

**OQ-XI2 (LOW): Operator interrupt via message vs. Ctrl-C during countdown.**
The 5-second countdown is described as a wait, but in the Claude Code model, there
is no true "timer" — the planter is not a daemon with a sleep loop. The countdown is
approximated by the planter emitting the countdown message and checking for operator
input on its next turn. A very fast operator can interrupt before the next turn; a
slow operator may not. This asymmetry is acceptable for v5.1.4 but may need a more
robust mechanism in v5.1.5.

---

## XII. See also

- `skills/shepherd/doctrines/pause-for-dependency.md` — mid-sprint satellite dispatch contract (conductor-side pause for dependency resolution; uses `SendMessage` at Step 5)
- `skills/shepherd/doctrines/chain-repair.md` — when a planter triage determines chain-repair category; amend-and-resume protocol
- `skills/shepherd/doctrines/conductor-cwd.md` — conductor git prohibition (the other side of the side-effect boundary)
- `agents/conductor.md §Escalation protocol` — conductor-side summary; full contract here
- `agents/conductor.md §Side-effect boundary` — what the conductor does NOT do (git, cleanup, lock)
- `agents/planter.md §Babysitter mode §1` — escalation triage categories (chain-repair, operator-question, hard-stop)
- `agents/planter.md §Babysitter mode §2` — git custody during spawn
- `agents/planter.md §Multi-teammate triage (--parallel mode)` — planter-side implementation of §X; collision detection, status board, per-teammate state
- `agents/planter.md §Sprint rollover (--auto mode)` — planter-side implementation of §XI; inter-sprint checklist, handoff authorship, termination
- `commands/spawn.md §--parallel flag` — spawn command parallel behaviors (collision check, worktree setup, merge gate, cleanup per teammate)
- `commands/spawn.md §--auto flag` — spawn command auto-loop semantics (loop structure, inter-sprint work, termination conditions)
- `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md` — D-API report (all platform facts sourced here)
