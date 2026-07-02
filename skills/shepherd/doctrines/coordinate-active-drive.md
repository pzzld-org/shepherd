---
name: coordinate-active-drive
description: |
  Binding contract for the dispatch→coordinate transition under /shepherd:spawn.
  On team initialization (liveness confirmed), the root shepherd ENTERS THE
  FOCUS-LOOP (Pattern 6 composite; wake → act → probe) as its DEFAULT PRIMARY
  OPERATING MODE — it operates the loop until CLOSE-FINALIZE. Long-running
  conductors adopt their own scoped FOCUS-LOOP for the same reason.
  coordinate_drive_guard.sh is the backstop; the behavioral contract here is
  the primary mechanism. Config gate: [focus].loop_default (default "on").
  Closes the "spawn pauses at the dispatch boundary" failure (root waits
  passively for TeammateIdle; flock stalled for the whole wave).
introduced: v6.0.5
updated: v6.1.2
closes: ["#113", "#98", "#112"]
related: ["#70", "#86", "#66", "#58"]
---

# Doctrine — COORDINATE-ACTIVE-DRIVE

## I. Why this doctrine exists

The most expensive `/shepherd:spawn` failure: root pauses at the dispatch
boundary. Root spawns teammates, treats "spawned" as a terminal action, and
yields. Teammates then wait or work invisibly, and root does nothing until a
`TeammateIdle` fires — which (#113) "only fires when a conductor goes idle —
typically at the END of its work." The operator, who chose `/shepherd:spawn`
to step away, returns hours later to a stalled session.

This is a missing contract: the event channel (`spawn-escalation.md`) and
wave-gate mechanics (#100) were specified, but never what root *does* between
"team spawned" and "first teammate event." Fix: **dispatch is the start of
active coordination, never a hand-off to the human.**

Field issues resolved:

| Issue | Symptom | Remedy |
|---|---|---|
| #113 | Root waits passively for `TeammateIdle`; drift invisible until wave end | §V inspection sweep every wake/yield |
| #98 | Idle teammate, no escalation payload; root blind | §VI proactive probe |
| #112 | Conductors idle 10–30 min post-`WAVE-COMPLETE` while root "plans" | §IV-b act-on-idle-immediately |
| #58 | Idle teammates reused context-starved instead of pruned | §IV-b pruning is an action |
| v6.2.2 | Root drifts off-task during a long ACT stretch, no wake to re-anchor | §IV-b.3 FOCUS-HEARTBEAT self-drift leg |

---

## II. Two kinds of "stop" — distinguish rigorously

Root ends its turn for the operator only for **a decision only the operator
can make**. Everything else is the event loop.

**Operator-pause (legitimate, closed set):**

1. Pre-spawn approval gate (`agents/shepherd.md §Step 1`) — the one pause the
   operator expects.
2. `HARD-STOP` escalation — operator chooses kill/rollback/manual.
3. operator-question escalation (`suggested_resolution: operator-question`).
4. `CROSS-TEAMMATE-DISPUTE` awaiting adjudication post-`@critic`.
5. Scope-confirmation gates (`confirm minor`/`confirm version`).
6. End-of-scope ROOT CLOSE REPORT (`agents/shepherd.md §Step 3`).
7. Explicit operator interrupt (`OPERATOR-INTERRUPT`).

Each emits a concrete question the operator can act on. "Spawned, monitoring
now…" is not in this set.

**Passive-wait (the bug, forbidden):** ending the turn at the dispatch
boundary, after a `WAVE-COMPLETE`, or mid-wave, with no operator question
pending. Root has work to do (§IV-b) and a cheaper way to wait (yield to
events); passive-wait does neither.

> **One line:** yield to events, never to the operator, unless the operator
> alone can answer the open question.

---

## III. Kickoff guarantee — teammates begin immediately

A teammate waiting for a go-signal while root waits for a teammate event is a
mutual-wait deadlock indistinguishable from passive-wait.

- **Root side.** The teammate-spawn instruction states each teammate begins
  its lane immediately on creation (`commands/spawn.md §Spawn dispatch`).
  After spawning, before anything else, root confirms liveness — poll `shctx
  teammate liveness` (or `TaskList`) until every teammate shows
  `booting`→`active` or a first heartbeat. Still-`booting`-with-no-heartbeat
  past the boot window is a `TEAMMATE-BOOT-MALFORMED`/`TEAMMATE-CRASHED`
  candidate — probe it (§VI).
- **Teammate side.** `FIRST ACTION` is `/shepherd:start --teammate`, run on
  the first turn without waiting for a kickoff message (`commands/start.md
  §Teammate path`, `agents/conductor.md §Lane-per-conductor model`). The lane
  brief in the boot prompt IS the instruction to begin.

Only once liveness is confirmed does root set up wave-gate scaffolding
(`wave-{N}-gate-{sprint_slug}` markers + `addBlockedBy`, #100) and enter the
coordinate cycle.

---

## IV. The FOCUS-LOOP — root's default coordinate engine under `/shepherd:spawn`

The cycle below IS root's default FOCUS-LOOP (Pattern 6 composite;
`references/workflow-templates.md` + `references/loop-templates.md
§FOCUS-LOOP`). Once the team initializes (liveness confirmed, §III), root
enters it as its **primary operating mode** until `CLOSE-FINALIZE`. Config
gate: `[focus].loop_default` (default `"on"`; `"off"` relies on
`coordinate_drive_guard.sh` alone — not recommended). Root **operates** the
loop affirmatively; the Stop hook (§VII) is the backstop for a lapse, not the
primary mechanism.

**Long-running conductors — own FOCUS-LOOP (B4).** A teammate-conductor on an
L/XL or multi-wave (≥2 wave) lane MUST run its own FOCUS-LOOP keyed to the
lane's `CLOSE-FINALIZE`/final `WAVE-GATE`, bounded by
`[focus].loop_max_default`. Same wake → act → probe structure, scoped to the
lane. Short-lived (S/XS, single-wave) conductors are exempt. Template:
`references/loop-templates.md §FOCUS-LOOP`.

## IV-b. The coordinate cycle — wake → act → probe → yield

While any teammate is live, root is in coordinate mode
(`root-shepherd-orchestration.md §II`). Every wake runs this cycle, then
yields:

1. **WAKE.** Triggered by `TeammateIdle`, inbound `SendMessage`
   (`WAVE-COMPLETE`/escalation), `TaskCompleted`, or root's own continuation.
   Not a prompt to the operator.
2. **ACT — drain all actionable state, don't defer.**
   - Unread lead mailbox → read every message, route by `halt_code`
     (`root-shepherd-orchestration.md §VI`). `WAVE-COMPLETE` → materialize,
     commit the wave, release the next `wave-N-gate`. Drain to empty; never
     leave one unread (#112).
   - Idle teammate with materialized wave payload → prune it now (`shctx
     teammate prune`) and refresh the lane with a fresh teammate at the next
     wave boundary (#58/#112). Pruning is an action taken this wake.
     > **Scoped per-lane removal only** (v6.0.9 regression). Prune ONE idle
     > teammate = `git worktree remove
     > .worktrees/{sprint_slug}-{that_lane}` for that lane only. NEVER run the
     > blanket `git worktree list | grep agent- | ... remove` loop or `git
     > worktree prune` while siblings are live — that kills every in-flight
     > lane at once. The blanket sweep is CLOSE-FINALIZE's RF-5
     > (`agents/shepherd.md`), run only after `v_teammates_live` hits zero.
   - Idle teammate with no `WAVE-COMPLETE` → §VI proactive probe.
   - Open `operator-question`/`HARD-STOP` → surface with a concrete question
     (the legitimate §II pause).
3. **PROBE (close the visibility gap, #113/#98).** Before yielding:
   - `shctx teammate liveness --stale-mins=5` — `presumed-crashed` → surface +
     offer re-spawn (`agents/shepherd.md §Crashed-teammate detection`).
   - `git -C .worktrees/{sprint_slug}-{lane} diff --stat` per live lane —
     changed-file count > ~1.5x the brief's `[FILE-SCOPE]` → `[DRIFT-WARN]`,
     `SendMessage` the lane to confirm scope (#113).
   - **Root self-drift (v6.2.2, FOCUS-HEARTBEAT).** Re-read `shctx loop focus
     show`; confirm root's own last stretch advanced `active_node` within
     `invariants`. Drifted → `[DRIFT-WARN] self`: stop, return to
     `active_node`, file the digression rather than chase it
     (`subtract-dont-add.md`). Per-wake re-anchor covers the common case; a
     long uninterrupted ACT stretch (big materialization/merge run, solo
     conductor inline work) self-fires every `[focus].heartbeat_interval`
     wall-clock or ~`[focus].heartbeat_actions` actions. Full ritual:
     `references/workflow-templates.md §FOCUS-LOOP`.
4. **YIELD (to events, not the operator).** Drained + clean → nothing to do
   until the next teammate event. Root yields silently except for one status
   line (`[ROOT] coordinate → N live / M idle / wave-K | next: <event>`). Do
   NOT `Bash sleep`-spin (forbidden — `native-coordination.md`) and do NOT
   emit an operator prompt.

`SendMessage` auto-resumes a stopped lead (since v2.1.77,
`spawn-escalation.md §II`), so yield is cheap. Passive-wait is the same
turn-end mechanic but with undrained state and an implicit ask of the
operator — same mechanic, opposite correctness.

---

## V. Active inspection cadence (realizable subset of #113)

#113 asked for wall-clock polling; a lead session has no self-scheduling
timer and must not `sleep`-spin to fake one. The realizable cadence is
event-anchored: the §IV-b.3 PROBE runs at every wake and before every yield,
so a drift/liveness check lands on every `TeammateIdle`, `WAVE-COMPLETE`, and
heartbeat wake (a healthy wave heartbeats per phase boundary —
`spawn-escalation.md §V` — giving multiple intra-wave wakes). True wall-clock
cadence needs a scheduler primitive shepherd doesn't own yet; until then the
heartbeat-staleness alert (5-min threshold) plus operator nudge cover the
silent-teammate case. A wall-clock daemon is a deferred enhancement (#113);
this ships the event-anchored subset, which already closes the "drift
invisible until wave end" gap.

---

## VI. Idle-without-signal — proactive probe (#98)

A `TeammateIdle` with no preceding `WAVE-COMPLETE` means the teammate stopped
mid-lane (often blocked on a background `cargo test`, #108) and dropped its
heartbeat. Root must not sit on it:

1. `SendMessage(to: <teammate>, "status? phase / last_node / in_flight_task")`.
2. Mark it a `TEAMMATE-STALL` candidate; start the 5-min staleness timer
   (`spawn-escalation.md §V`).
3. Answers → resume. Silent past threshold → surface `TEAMMATE-STALL` to the
   operator with last phase + heartbeat; do NOT auto-recover.

Symmetric on the teammate side: a conductor idle without `WAVE-COMPLETE`
sends a `{phase, last_node, in_flight_task}` status within one turn of its
next wake (`agents/conductor.md §Escalation protocol`, `spawn-escalation.md
§V`).

---

## VII. Mechanical backstop — `coordinate_drive_guard.sh`

Per `invariant-enforcement-matrix.md` and the #86/#66 lesson that prose-only
invariants erode under load, the no-passive-wait rule is backed by a `Stop`
hook, not left to prose alone.

**Hook:** `hooks/scripts/coordinate_drive_guard.sh`, registered on `Stop`
(`hooks/hooks.json`, `claude-code-platform-alignment.md §V`).

- **Fast-path:** no `root.db`, or zero live teammates (`v_teammates_live`
  empty) → exit 0 silently. Solo work untouched.
- **Engaged:** live teammates + actionable root-clearable state (an `idle`
  teammate, unread lead mail) → root is stopping with work undrained. Hook
  emits `{"decision":"block","reason": <the §IV-b cycle, abbreviated>}`.
- **Legitimate-pause aware:** the `reason` explicitly authorizes §II
  operator-pauses — nudges root to act or ask, never to sit.

**Runaway safety.** A `Stop` hook that blocks indefinitely is itself a hazard
(#114):

- **2-nudge cap.** Per-session counter (`<ns>/tmp/coordinate_drive_guard.*`)
  increments per consecutive block; past cap → fails open (exit 0). Resets
  when actionable state clears.
- **Fail-open on everything** — missing DB, no `sqlite3`, malformed payload,
  any error → exit 0.
- **Config override.** `[spawn].coordinate_drive_guard`: `block` (default),
  `warn` (stderr only), `off` (fast-path exit).

The hook is a backstop — the §I–VI behavioral contract is the fix.

---

## VIII. What is NOT a violation

- Yielding while teammates are genuinely `active` (recent heartbeats, mailbox
  drained, probe clean) — §IV-b.4 working as designed.
- The enumerated §II operator-pauses — surfacing and stopping is correct.
- Solo `/shepherd:start` — no team, no root tier, guard fast-paths out.
- Pre-spawn — no live teammates yet; the approval-gate pause is legitimate.

---

## IX. See also

- `agents/shepherd.md` — root profile; §Step 2 BODY active-drive; Hard prohibition (no dispatch-boundary operator-pause)
- `doctrines/root-shepherd-orchestration.md §II` — coordinate mode (active-drive)
- `doctrines/spawn-escalation.md` — channel mechanics; §V heartbeat/staleness; §VI wave-boundary commits
- `doctrines/native-coordination.md` — no `sleep`-spin; event-driven coordination
- `doctrines/claude-code-platform-alignment.md §V` — `Stop` hook registration (`coordinate_drive_guard.sh`)
- `doctrines/invariant-enforcement-matrix.md` — prose→mechanism coverage (#86)
- `references/loop-templates.md §FOCUS-LOOP` — per-role loop catalog; root FOCUS-LOOP entry + conductor-specific template (long-running lane variant, B4)
- `doctrines/loop-templates.md` — binding loop doctrine: bounded, role-shaped, terminates on measurable predicate
- `docs/configuration.md §[focus]` — `loop_default` key; `loop_max_default`
- `commands/spawn.md` — §Spawn dispatch (kickoff wording); §Root-shepherd responsibilities
- `commands/start.md` — §Teammate path (begin-immediately)
- `hooks/scripts/coordinate_drive_guard.sh` — the backstop implementation
- `hooks/tests/test_coordinate_drive_guard.sh` — guard test (fast-path / block / runaway cap)
