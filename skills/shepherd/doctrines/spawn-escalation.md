---
name: spawn-escalation
description: |
  Canonical return-and-resume contract between a spawned teammate-conductor and the
  root. Governs every communication path, payload
  schema, resume shape, heartbeat mechanism, and wave-boundary commit discipline for
  /shepherd:spawn sessions. Source of truth for teammate communication bugs.
introduced: v5.1.4
updated: v6.0.3
field_origin: v5.1.4 D-API discovery (.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md)
---

# Doctrine — SPAWN-ESCALATION

## I. Why this doctrine exists

Claude Code Agent Teams (v2.1.144, D-API §11) gives **no session resumption for
in-process teammates** — `/resume`/`/rewind` cannot restore a stalled, crashed, or
interrupted teammate. Every question a teammate-conductor can't resolve alone must
reach the root via the path below: channels,
payload schema, resume shape, heartbeat, failure semantics. A future communication
bug should trace to a specific broken invariant here.

> **Terminology (v5.1.6+):** authored when the receiver was always the planter.
> Under `/shepherd:spawn` the receiver is the **root shepherd profile**
> (`agents/shepherd.md`); planter may be delegated for seed-amendment per
> `doctrines/root-shepherd-orchestration.md §V`. Mechanics are identical either way.

> Platform facts: `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md`
> (D-API report). Contradictions resolve in favor of D-API; flag as Open Question in §IX.

**Shorthand:** "root" below means the root shepherd, or the planter when delegated per §Terminology above — identical mechanics either way.

---

## II. Channels

Four channels between teammate-conductor and root:

- **Primary — SendMessage mailbox.** Async; `SendMessage({ to: lead })`; delivered
  automatically, no receiver polling (D-API §8). Use for escalations, wave-complete
  notices, heartbeat lines. If the receiver session isn't running, messages queue
  with no response. Auto-resumes stopped agents in background since v2.1.77 (D-API §6),
  as long as the teammate session still exists.
- **Durable — shared filesystem.** `~/.claude/tasks/{team-name}/` (team task list)
  and `.artifacts/escalations/{sprint_slug}/` (project-local): transcripts, audit
  trail, structured escalation files, recovery state when mailbox is down. Teammate
  writes escalation files here IN ADDITION to SendMessage. Never pre-author/edit
  `~/.claude/tasks/{team-name}/config.json` — runtime-owned, overwritten every update (D-API §7).
- **Hook-driven — lifecycle events** (D-API §13). Only `TeammateIdle` has a registered handler:

| Event | When | Can block? | Shepherd handler |
|---|---|---|---|
| `TeammateIdle` | Teammate about to idle | Yes (exit 2 / `{continue:false}`) | `hooks/scripts/teammate_idle.sh` (registered in `hooks/hooks.json`) |
| `TaskCreated` | Task created via `TaskCreate` | Yes (platform) | None registered. Root observes via `TeammateIdle` + `SendMessage` WAVE-COMPLETE payloads. |
| `TaskCompleted` | Task marked complete | Yes (platform) | None registered. Root reacts via `SendMessage` WAVE-COMPLETE payloads the conductor sends before completing the task. |

  Lane-routing (v6.0.3 — #102): every `task_title` is prefixed `"{lane_id}: "`,
  `assignee` set via `TaskUpdate(owner:...)`. Root routes by that prefix in
  hook/message payloads, never via a `TaskCreated`/`TaskCompleted` hook script. No
  prefix = root-owned (terminal `shepherd-{sprint_slug}-close`). `TeammateIdle` is
  BLOCKING — the primary escalation pause point — and fires on **graceful idle
  only**, not crash/SIGKILL (D-API Unknown #3; heartbeat shim in §V covers
  crashes). `TaskCompleted` fires automatically on wave-scope completion;
  wave-boundary commits trigger off the preceding WAVE-COMPLETE SendMessage (§VI).
- **Heartbeat — native `TeammateIdle` + staleness poll.** No platform heartbeat
  primitive (D-API Confirmed Facts). The v5.1.7 per-tool shim was **retired in
  v6.0.5** (keyed on `CLAUDE_TEAMMATE_NAME`, empty on the live platform, never
  fired). Liveness = `TeammateIdle` hook (routes by `teammate_name` OR `session_id`)
  + `shctx teammate liveness --stale-mins=N` (§V).

---

## III. Escalation payload shape

Every escalation — SendMessage or filesystem file — MUST conform. Planter triages
on `halt_code` + `suggested_resolution`; never free-reads `question` to categorise.

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

| Field | Constraint |
|---|---|
| `role` | One of seven; `conductor` = the conductor itself halting, not a sub-agent |
| `phase` | `intro`, `body-wave-1..N`, `close-0..2` — not free text |
| `halt_code` | Must match `agents/conductor.md §Halt codes`; non-null for escalations |
| `question` | One sentence; detail lives in `context_files` |
| `blocking` | `true` = sprint paused; `false` = non-blocking notification |
| `context_files` | 0–5 absolute paths (plan / wave-gate output / agent report) |
| `suggested_resolution` | One of four values; `null` only if conductor has none |

**Wave-complete notification** (non-escalation SendMessage): same envelope,
`halt_code: null`, `blocking: false`, `role: "conductor"`, `phase: "body-wave-N"`,
`context_files: ["<wave-gate-output>"]`. Planter reads `halt_code: null` +
`blocking: false` as a commit trigger, no operator interaction.

**Filesystem file naming:** `.artifacts/escalations/{sprint_slug}/{ISO8601-timestamp}-{role}.md`
(e.g. `.artifacts/escalations/v514-dev2/2026-05-19T14:32:00-engineer.md`). Content:
JSON payload preceded by header `# Escalation — {halt_code} — {role} @ {phase}`.
Atomic write; concurrent sub-agent escalations get separate files.

---

## IV. Resume shape

Root re-enters the teammate's conductor after
triage. Option A primary, Option B durable fallback.

**Option A (primary) — SendMessage reply:**

```json
{
  "escalation_id": "<timestamp-role from the escalation file name>",
  "resolution": "<chain-repair | operator-answer | abort>",
  "answer": "<the operator's decision or the planter's amendment>",
  "amended_files": ["<paths to files the planter changed>"],
  "resume_instruction": "<one sentence: what the conductor should do next>"
}
```

`SendMessage({ to: "shepherd-conductor-{slug}", message: <payload> })`. Teammate
reads inbox, extracts reply by `escalation_id`, resumes. Auto-resume (v2.1.77+,
D-API §6) re-activates an idled teammate without a separate signal.

**Option B (durable fallback)** — `.artifacts/escalations/{sprint_slug}/resume/{escalation_id}.md`,
same JSON. Teammate polls on next `TeammateIdle` if no SendMessage reply arrived.
Use when SendMessage errors, the teammate session is gone, or the planter is degraded.

**Option C (deferred to v5.1.5)** — in-place seed amendment + re-read signal. Works
for chain-repair but risks a write-conflict mid-read. Deferred pending lock semantics.

**Halt-code → action map** (source: `agents/planter.md §Babysitter mode §1`):

| Escalation category | Resume authority | Path |
|---|---|---|
| `chain-repair` | Planter auto-resumes after amendment | Option A, no operator |
| `operator-question` | Operator confirms; planter sends reply | Option A after operator |
| `hard-stop` | Operator chooses kill/rollback/manual | No auto-resume |

---

## V. Heartbeat mechanism

No platform heartbeat primitive (D-API Confirmed Facts, Unknown #3). **v6.0.5:**
the per-tool `SubagentStop`/`PostToolUse` shim was **retired** (keyed on
`$CLAUDE_TEAMMATE_NAME`, empty on the live platform, never fired). Liveness now
comes from native signals written to the canonical `teammates` table.

**Write path** — `teammates.last_seen_at` + `status` updated by:
- `cmd_teammate.sh register` — on spawn (status `booting`)
- `cmd_teammate.sh heartbeat <name>` — flips `booting`→`active`, appends a
  `heartbeats` row (phase/tool note); called by the `TeammateIdle` hook when a name
  is present, and available for explicit phase notes
- native **`TeammateIdle`** hook (`hooks/scripts/teammate_idle.sh`) — flips to
  `idle`, routing by `teammate_name` OR `session_id` (payload carries `session_id`,
  not always `teammate_name`); fails loud on no-match

**Read path (root side)** — poll the canonical store, not log files:
```bash
shctx teammate liveness --stale-mins=5     # per-teammate verdict: ok | presumed-crashed
shctx teammate status <name>               # one teammate's row
```

**Staleness threshold: 5 minutes** with no new heartbeat → alert (accommodates
large Agent dispatches with no intermediate tool calls; operator may extend
manually). **Beyond threshold: alert; do NOT auto-recover.**

**Idle-without-WAVE-COMPLETE rule (v6.0.3 — #98).** A conductor that idles WITHOUT
sending `WAVE-COMPLETE` MUST, on next wake, send a status `SendMessage(to: lead)`
within 1 turn carrying `{phase, last_node, in_flight_task}`. Root treats such a
`TeammateIdle` as a `TEAMMATE-STALL` trigger (not a new halt code). Conductor MUST
also heartbeat at every major phase boundary even while blocked — a silent block is
indistinguishable from a stall.

**HEARTBEAT ALERT format:**
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

Binding, non-negotiable contract limiting loss to at most one wave on stall/crash.
Mandatory for conductor and planter both.

**Conductor obligation (teammate).** At every wave completion, before next
`WAVE-IMPL`: (1) fire wave-complete SendMessage (`halt_code: null`,
`blocking: false`, `context_files: [<wave-gate-output>]`); (2) let the wave-scope
task complete (`TaskCompleted` fires automatically); (3) wait for resume signal —
timeout `[spawn].wave_ack_timeout_sec` (default 60s); on timeout, heartbeat and
continue (planter still owes the commit; loss horizon extends, sprint not
blocked). Conductor never calls git (`agents/conductor.md §Hard prohibitions #12`,
`§Side-effect boundary`). Every `TaskCreate` carries a `"{lane_id}: "` prefix and is
`TaskUpdate(owner:<self>)`'d immediately (per `lane-task-ownership.md`).

Wave-gate is mechanical (v6.0.3 — #100): root TaskCreates a
`wave-{N}-gate-{sprint_slug}` marker; each lane's wave-(N+1) IMPL task carries
`addBlockedBy` on it; root releases via `TaskUpdate(status: completed)` only after
the gate passes. A blocked task can't be claimed — enforced by the task list, not
prose. If root never releases: `WAVE-GATE-NOT-RELEASED`.

**Root shepherd obligation** (main-chat or delegated planter). On every
wave-scope `TaskCompleted`: (1) read payload for landed files; (2) `git status` —
confirm branch, no uncommitted mid-flight state; (3) commit:
```bash
git add -p   # or: git add <paths from context_files>
git commit -m "chore({sprint_branch}/wave-K): wave-complete via spawn"
```
(4) send wave-ack reply. A missed `TaskCompleted` (interrupt, slow) leaves
artifacts uncommitted; the next `TaskCompleted` is the catch-up opportunity —
commit all pending artifacts together before proceeding.

**Loss horizon:**

| Scenario | Loss |
|---|---|
| Teammate stalls in wave N+1, planter committed after wave N | Wave N+1 only |
| Teammate stalls in wave N+1, planter did NOT commit wave N | Waves N and N+1 |
| Teammate crashes before any wave completes | All work since last planter commit |
| Planter session drops while teammate is mid-wave | No commits land; full sprint lost unless planter re-attaches |

Wave-boundary discipline reduces worst case from "full sprint lost" to "one wave
lost." Both parties must honor it.

---

## VII. Failure semantics

Binding recovery rules for channel/session failure. Planter follows these without improvising.

- **Teammate stalls mid-wave.** Detect: heartbeat stale > 5 min (§V). Loss: current wave's uncommitted artifacts. Recover: note last commit SHA, `rm -rf ~/.claude/teams/{team-name}/` (one-team limit), re-invoke `/shepherd:spawn`; teammate re-reads plan + walk trace, continues from next unstarted wave.
- **Teammate session drops (no `TeammateIdle`).** Detect: session UUID absent from `~/.claude/sessions/`; heartbeat stopped. Loss: current wave + in-transit payloads. Recover: same as stall; check `.artifacts/escalations/{sprint_slug}/` for a pre-drop file.
- **SendMessage delivery fails.** Fallback: read `.artifacts/escalations/{sprint_slug}/<timestamp>-<role>.md` (conductor writes here too); if absent, treat as stall. Resume via Option B file instead of SendMessage.
- **Root session drops.** Loss: all wave artifacts since last root commit. Recover: re-attached root reads `TeammateIdle` queue + mailbox + filesystem tree, reconstructs state, catch-up commits `git status` deltas. If teammate already closed, only the git-committed portion survives — the reason for frequent wave commits.
- **Operator interrupts main chat (Ctrl-C).** Teammate orphaned: no commits, no escalations answered. Manual cleanup `~/.claude/teams/shepherd-conductor-{sprint_slug}/`. Prevention: send `SendMessage` "clean stop" before interrupting.

---

## VIII. Non-goals in v5.1.4

Deferred. Do not implement; do not design flows that assume otherwise.

- **No live RPC** — all comms async via mailbox or filesystem (D-API §8).
- **No automatic teammate restart** — operator re-invokes `/shepherd:spawn`.
- **No multi-team** — one team per lead (D-API §11); multi-team is v5.1.5+.
- **No `shctx parallel status` command** — planter reads heartbeat rows directly (§V).
- **No cross-teammate routing in single-spawn** — point-to-point conductor → planter; multiplex topology is §X.
- **No per-teammate config at spawn time** — conductor profile loaded by the teammate's own `/shepherd:start` (D-API §9).

---

## IX. Open questions (single-teammate baseline)

- **OQ-1** (D-API Unknown #1) — `teammate_type` in `TeammateIdle` may show model slug, `"conductor"`, or agent filename. Mitigation: route by `teammate_name` (`shepherd-conductor-{slug}`), never `teammate_type`.
- **OQ-2** (D-API Unknown #3) — `TeammateIdle` doesn't fire on crash; heartbeat shim (§V) is the only crash detector. Confirm `PostToolUse` wired before shipping.
- **OQ-3** (D-API Unknown #6) — `TeammateIdle` vs. `Stop` ordering unconfirmed; wave-boundary commits fire on `TaskCompleted` (§VI), not `TeammateIdle`, to dodge the race.
- **OQ-4** (D-API Unknown #4) — whether task JSON can be written directly to `~/.claude/tasks/{team-name}/` from a hook script (vs. requiring a Claude-session tool call) is unconfirmed.

---

## X. Multiplexed escalation (--parallel mode)

Under `/shepherd:spawn --parallel <N>`, N teammates may escalate concurrently.
§II–§IV mechanics are unchanged per escalation; root's **triage loop** becomes multiplexed.

**Routing keys.** Route by `teammate_name` (`shepherd-parallel-{sprint_slug}`),
carried in the `TeammateIdle` payload (D-API §13) — MUST NOT route by
`teammate_type` until OQ-1 resolves. Filesystem path encodes sprint slug:
`.artifacts/escalations/{sprint_slug}/...`, one directory per teammate; root reads
all N on each `TeammateIdle`.

**Priority rules:**

| Priority | Condition | Action |
|---|---|---|
| P0 (CRITICAL preempt) | `halt_code` in `HARD-STOP`, `TEAMMATE-GIT-WRITE`, `BASE-DRIFT`, `PARALLEL-COLLISION` | Jumps queue. Multiple simultaneous CRITICAL → operator decision (spawn.md hard stop) |
| P1 (FIFO) | All other `halt_code` values | First-in-first-out by `TeammateIdle` arrival |
| P-NOTIFY (non-blocking) | `halt_code: null`, `blocking: false` | Wave-complete; immediate commit + ack; no queue |

**Multiplex triage protocol.** Root holds `Q = [(teammate_name, payload), ...]`, triaged by `teammate_name`:
- *A triaging, B non-CRITICAL:* `Q.append(B)`; emit `[QUEUE] Teammate B escalation received (halt_code: {code}). Queued at position {len(Q)}. Completing A-triage first.` Finish A, resume, then B.
- *A triaging, B CRITICAL:* write bookmark `.artifacts/escalations/{sprint_A}/triage-suspended.md` (`{suspended_at, triage_stage, reason}`); emit `[QUEUE PREEMPT] Interrupting {sprint_A} triage for CRITICAL halt in {sprint_B}`; process B to resolution; resume A from bookmark; delete bookmark.
- *Root busy, queue deep:* `TeammateIdle` is BLOCKING (exit 2); if `len(Q) > 1`, exit 2 to hold the idle teammate while clearing queue head — not beyond 2 min; emit `[QUEUE WARNING] {N} escalations pending; teammate {name} held for {elapsed}s`.

**Cross-teammate dependency halts.** When A's sprint declares `sprint_dependencies`
on B's output, A may halt `halt_code: CROSS-DEP-WAIT` (`role: coder`,
`phase: body-wave-N`, `blocking: true`, `suggested_resolution: operator-question`,
`context_files` naming A's import site). Resolution: (1) if B's relevant wave
completed, read its wave-gate output for the artifact path and reply via Option A
(`{resolution: "operator-answer", answer: "Artifact available at {path}.",
amended_files: ["{path}"]}`) — A resumes, no operator needed; (2) if B hasn't
produced, notify A "B's artifact not yet ready. Stand by.", track
`blocked_by: {sprint_B}`, re-check each subsequent `TeammateIdle`; (3) if
`[spawn].cross_dep_timeout_sec` (default 300) expires, escalate to operator as
`ESCALATION — operator question` with B's phase + heartbeat in context.

**PARALLEL-COLLISION halt.** A coder finding a runtime file collision missed by
the pre-spawn check surfaces `halt_code: PARALLEL-COLLISION`. Response: (1)
identify the two colliding sprints from the payload; (2) `SendMessage` to ALL
affected teammates: "PARALLEL-COLLISION received. Halting pending conflict
resolution. Do NOT proceed."; (3) surface to operator:
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
(4) on operator choice, execute amendment or serialization, then resume.

**Open questions — §X.** **OQ-X1** (MEDIUM) — D-API §13 documents `TeammateIdle`
as BLOCKING, but whether the platform queues or fires two simultaneous instances
in parallel is undocumented. Until confirmed: treat each `TeammateIdle` as atomic.

---

## XI. Sequential autopilot (--auto mode)

Under `/shepherd:spawn --auto` the root runs a sequential loop. Channel mechanics
(§II–§IV) match single-spawn — one teammate active at a time, no multiplexed
queue. This section governs the **loop boundary**: inter-spawn behavior,
patch-end detection, next-teammate context inheritance.

**`TaskCompleted` → root-takes-over → spawn-next contract:** (1) `TaskCompleted`
fires for the terminal task (conductor's close-synthesis, named
`shepherd-{sprint_slug}-close`) — authoritative, not `TeammateIdle` (which can
fire mid-sprint); (2) root takes over: `TeammateIdle` fires after the terminal
`TaskCompleted`, root reads the mailbox for CONDUCTOR CLOSE REPORT, verifies,
begins inter-sprint work (`commands/spawn.md §--auto flag`); (3) spawn-next:
after all 10 inter-sprint steps complete cleanly, root dispatches via `Agent`;
the new teammate receives the handoff doc path in its boot prompt.

**Critical invariant:** root MUST NOT spawn next until inter-sprint work is fully
committed to git — incomplete commit state at spawn-next starts the new teammate
on an inconsistent patch branch.

**Patch boundary detection:**

| Source | How | Precedence |
|---|---|---|
| `shepherd.toml [version].dev_total` | Direct config value | 1 (highest) |
| Seed count on patch branch | `ls {paths.plans}/{patch_slug}-dev*.seed.md \| wc -l` | 2 |
| Operator input during preflight Check 5 | Interactive prompt | 3 (fallback) |

Once `dev.LAST` is determined it is locked for the loop — no dynamic re-detection
mid-loop. If the operator amends scope, they must interrupt, update
`shepherd.toml`, and re-invoke `--auto` from the current sprint.

**Loop-termination payload** (terminal `TaskCompleted` from the closing teammate):
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
Planter reads `task_result.grade` for GRADE-FLOOR and
`task_result.error_budget_consumed` for BUDGET-ZERO. Missing/malformed
`task_result` → treat as GRADE-FLOOR (fail-safe); AUTO ABORT with `grade: UNKNOWN`.

**Context the next teammate inherits** — three documents in the boot prompt: the
active seed, the **auto-handoff doc**
(`{paths.docs}/<date>-{sprint_slug_N+1}-auto-handoff.md`, authored by planter at
inter-sprint step 7 — the teammate's only history window), and the carry-forward
ledger. Seed alone is NOT sufficient; missing handoff at spawn-next → hard stop.

**Operator pause window.** After the 5-second countdown in `commands/spawn.md`,
any message is an interrupt unless it's exactly `'continue'` or `'ok'`. On
interrupt, the loop pauses at the last-completed inter-sprint state (all commits
landed, no work lost): `'resume auto'` continues from next sprint; `'abort'`
terminates with an AUTO ABORT REPORT; anything else prompts
`"Auto-loop is paused. Resume with 'resume auto' or abort with 'abort'."`.

**Open questions — §XI.**
- **OQ-XI1** (MEDIUM) — terminal `TaskCompleted` naming: close-synthesis task
  needs a predictable name so planter distinguishes it from wave-scope
  `TaskCompleted`. RESOLVED (v6.0.3 — #102): terminal tasks carry NO lane prefix;
  that absence is the distinguishing signal. Name remains `shepherd-{sprint_slug}-close`.
- **OQ-XI2** (LOW) — the 5-second countdown is approximated (no daemon timer); a
  fast operator interrupts before the next turn, a slow one may not. Acceptable
  for v5.1.4.

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
