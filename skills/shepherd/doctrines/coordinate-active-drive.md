---
name: coordinate-active-drive
description: |
  Binding contract for the dispatch→coordinate transition under /shepherd:spawn.
  On team initialization (liveness confirmed), the root shepherd ENTERS THE
  FOCUS-LOOP (Pattern 6 composite; wake → act → probe) as its DEFAULT PRIMARY
  OPERATING MODE — it does not merely avoid stopping, it OPERATES the loop until
  CLOSE-FINALIZE. Long-running conductors adopt their own scoped FOCUS-LOOP for
  the same reason. coordinate_drive_guard.sh is the backstop that catches lapses;
  the behavioral contract here is the primary mechanism. Config gate:
  [focus].loop_default (default "on"). Closes the "spawn pauses at the dispatch
  boundary" failure (root waits passively for TeammateIdle; flock stalled for the
  whole wave). Source of truth for spawn-pause / passive-wait bugs.
introduced: v6.0.5
updated: v6.1.2
closes: ["#113", "#98", "#112"]
related: ["#70", "#86", "#66", "#58"]
---

# Doctrine — COORDINATE-ACTIVE-DRIVE

## I. Why this doctrine exists

The single most expensive failure mode observed in `/shepherd:spawn` is **the
root pausing at the dispatch boundary**. The sequence:

1. Root finishes INTRODUCTION (engineer + critic + plan + operator approval).
2. Root issues `TeamCreate`, spawning one teammate-conductor per lane.
3. Root's turn **ends**. The model treats "I spawned the team" as a terminal
   action and yields — implicitly, to the operator.
4. The teammates are either (a) waiting for a go-signal that never arrives, or
   (b) working but invisible. Either way the root does **nothing** until a
   `TeammateIdle` fires — which, per #113, "only fires when a conductor goes
   idle — typically at the END of its work."
5. The operator, who chose `/shepherd:spawn` precisely so they could step away,
   returns hours (a full day, in the field report that motivated this doctrine)
   later to find the session paused at the dispatch boundary, nothing shipped.

This is not one bug; it is a **missing contract**. The framework specified the
event-driven channel (`doctrines/spawn-escalation.md`) and the wave-gate
mechanics (`#100`), but never specified what the root *does* between "team
spawned" and "first teammate event." The default LLM behavior in that gap is to
stop. This doctrine fills the gap: **dispatch is the START of active
coordination, never a hand-off to the human.**

It is the unifying fix behind a cluster of field issues:

| Issue | Symptom | This doctrine's remedy |
|---|---|---|
| #113 | Root waits passively for `TeammateIdle`; scope-creep/Cargo drift invisible until wave end | §V active inspection sweep at every wake + before every yield |
| #98 | Teammate goes idle with no escalation payload; root left blind, must manually probe | §VI proactive status probe on idle-without-`WAVE-COMPLETE` |
| #112 | Conductors sit idle 10–30 min post-`WAVE-COMPLETE` while root "plans"; delayed prune | §IV-b act-on-idle-immediately (prune + refresh in the same wake) |
| #58 | Idle teammates reused context-starved instead of pruned + refreshed | §IV-b pruning is an action, not a deferral |

---

## II. Two kinds of "stop" — distinguish them rigorously

The root has exactly **one legitimate reason** to end its turn and hand control
to the human: a **decision only the operator can make**. Everything else is the
event loop, and the event loop is not the operator.

### Operator-pause (legitimate — ENUMERATED, closed set)

The root ends its turn **for the operator** only at these points:

1. **Pre-spawn approval gate** — the plan summary + `proceed` prompt, BEFORE any
   `TeamCreate` (per `agents/shepherd.md §Step 1`). This is the one pause the
   operator expects.
2. **`HARD-STOP` escalation** — a teammate surfaced a terminal halt; the
   operator must choose kill/rollback/manual.
3. **operator-question escalation** — a teammate's `suggested_resolution` is
   `operator-question`; the answer is the operator's to give.
4. **`CROSS-TEAMMATE-DISPUTE`** awaiting the operator's adjudication after the
   `@critic` verdict is surfaced.
5. **Scope-confirmation gates** (`confirm minor` / `confirm version`).
6. **End-of-scope ROOT CLOSE REPORT** — the terminal `PAUSE` after the last
   sprint closes (per `agents/shepherd.md §Step 3`).
7. **Explicit operator interrupt** — operator typed pause/stop/exit
   (`OPERATOR-INTERRUPT`).

At each of these the root emits a **concrete question or report** the operator
can act on. "I've spawned the team, monitoring now…" is **not** in this set — it
asks the operator nothing, so it must never be a turn-ending pause.

### Passive-wait (the bug — FORBIDDEN)

Ending the turn at the dispatch boundary, or after acknowledging a
`WAVE-COMPLETE`, or while teammates are mid-wave, **with no operator question
pending**, is the bug. The root has work to do (kickoff confirmation, wave-gate
scaffolding, materialization, gate release, prune+refresh, liveness sweep) and a
cheaper way to wait (yield to the event system, §IV-b). Passive-wait does neither.

> **The rule, one line:** *yield to events, never to the operator — unless the
> operator is the only one who can answer the open question.*

---

## III. Kickoff guarantee — teammates begin immediately

A teammate that waits for a go-signal while the root waits for a teammate event
is a **mutual-wait deadlock** that presents identically to passive-wait. Close
it from both sides:

**Root side.** The `TeamCreate` instruction MUST state that each teammate
**begins its lane immediately upon creation** and does not wait for a further
message. (Wording: `commands/spawn.md §Spawn dispatch`.) After `TeamCreate`,
before doing anything else, the root **confirms liveness**: poll
`shctx teammate liveness` (or `TaskList`) until every spawned teammate has a
`booting`→`active` transition or a first heartbeat. A teammate still `booting`
with no heartbeat after the boot window is a `TEAMMATE-BOOT-MALFORMED` /
`TEAMMATE-CRASHED` candidate — probe it (§VI), do not assume it is working.

**Teammate side.** The boot prompt's `FIRST ACTION` is `/shepherd:start
--teammate`, executed **on the first turn, without waiting for a kickoff
message** (`commands/start.md §Teammate path`, `agents/conductor.md §Lane-per-
conductor model`). The teammate does not idle waiting to be told to begin; the
lane brief in its boot prompt IS the instruction to begin.

Only once liveness is confirmed does the root set up wave-gate scaffolding
(`wave-{N}-gate-{sprint_slug}` markers + `addBlockedBy`, per `#100`) and enter
the coordinate cycle.

---

## IV. The FOCUS-LOOP — root's default coordinate engine under `/shepherd:spawn`

The coordinate cycle described below IS the root's **default FOCUS-LOOP**
(Pattern 6 composite; `references/workflow-templates.md` + `references/loop-
templates.md` — the `FOCUS-LOOP` entry). When the root adopts the
`agents/shepherd.md` profile under `/shepherd:spawn` and the team
initializes (liveness confirmed, per §III), it enters this loop as its
**primary operating mode**, not as a fallback or optional behaviour. The
loop runs until `CLOSE-FINALIZE` completes. Config gate:
`[focus].loop_default` in `shepherd.toml` (default `"on"`; set `"off"` to
suppress and rely on `coordinate_drive_guard.sh` alone — not recommended).

**The framing shift matters.** Prior to this doctrine update the root was
described as "not stopping" (a negative constraint). The correct framing is
affirmative: the root **OPERATES** the FOCUS-LOOP; the `coordinate_drive_guard.sh`
Stop hook (§VII) is the **backstop** that catches a lapse if the prose erodes —
it is not, and never was, the primary mechanism.

### Long-running conductors — own FOCUS-LOOP (B4)

A teammate-conductor assigned a **long or multi-wave lane** (typically L/XL
scope, or any lane spanning ≥ 2 waves) MUST adopt its OWN FOCUS-LOOP keyed
to its lane objective to avoid drift. The conductor does not merely walk its
graph to completion and yield; it operates a bounded loop (max from
`[focus].loop_max_default`) whose objective condition is the lane's
`CLOSE-FINALIZE` or final `WAVE-GATE` node. The same wake → act → probe
structure applies, scoped to the conductor's assigned lane rather than the
full team. Short-lived conductors (S/XS scope, single-wave lanes) are exempt
— their work terminates naturally without a loop. See `references/loop-
templates.md §FOCUS-LOOP` for the conductor-specific template.

## IV-b. The coordinate cycle — wake → act → probe → yield

While any teammate is live, the root is in **coordinate mode**
(`doctrines/root-shepherd-orchestration.md §II`). Every time the root is awake
in coordinate mode it runs the cycle, then — and only then — yields to the
event system:

1. **WAKE.** Triggered by `TeammateIdle`, an inbound `SendMessage`
   (`WAVE-COMPLETE` / escalation), `TaskCompleted`, or the root's own
   continuation. The wake is not a prompt to the operator.
2. **ACT (drain all actionable state — do not defer).**
   - **Unread lead mailbox** → read every message; route by `halt_code`
     (`doctrines/root-shepherd-orchestration.md §VI`). A `WAVE-COMPLETE`
     (`halt_code: null`) → materialize the payload, commit the wave on the
     sprint branch, release the next `wave-N-gate` marker. Drain to empty; never
     leave a `WAVE-COMPLETE` sitting unread (#112).
   - **Idle teammate whose wave payload is materialized** → **prune it now**
     (`shctx teammate prune`/shutdown request) and **refresh** the lane with a
     fresh teammate at the next wave boundary (#58 / #112). Pruning is an action
     taken in this wake, not a plan for later.

     > **WARNING — scoped per-lane removal only (v6.0.9 pane-massacre
     > regression).** Pruning ONE idle teammate means removing ONLY that lane's
     > worktree: `git worktree remove .worktrees/{sprint_slug}-{that_lane}`.
     > **NEVER** run the blanket `git worktree list | grep agent- | ... remove`
     > loop, and **NEVER** run `git worktree prune`, while sibling teammates are
     > still live — doing so removes every in-flight lane's worktree and kills
     > all active sessions simultaneously. The blanket loop is a CLOSE-FINALIZE
     > sweep run by RF-5 in `agents/shepherd.md` AFTER `v_teammates_live` reaches
     > zero, not a per-idle-prune tool. Coordinate_drive_guard re-engaging the
     > root with "prune each idle teammate" means prune that ONE lane — scoped,
     > targeted, never bulk.
   - **Idle teammate with no `WAVE-COMPLETE`** → §VI proactive probe.
   - **Open `operator-question` / `HARD-STOP`** → surface to the operator with a
     concrete question (this is the legitimate §II pause — take it).
3. **PROBE (close the visibility gap, #113/#98).** Before yielding, sweep
   liveness + drift across live teammates:
   - `shctx teammate liveness --stale-mins=5` — any `presumed-crashed` →
     surface + offer re-spawn (`agents/shepherd.md §Crashed-teammate detection`).
   - `git -C .worktrees/{sprint_slug}-{lane} diff --stat` per live lane — if a
     lane's changed-file count exceeds ~1.5× its brief `[FILE-SCOPE]`, emit
     `[DRIFT-WARN]` and `SendMessage` the lane to confirm scope before it
     compounds (#113). Cheap, read-only, catches scope-creep mid-wave instead of
     at wave end.
4. **YIELD (to events, not the operator).** With actionable state drained and
   the probe clean, the root has nothing to *do* until the next teammate event.
   It yields — ends the turn so the platform can wake it on the next
   `TeammateIdle`/`SendMessage`/`TaskCompleted`. This is correct and cheap; do
   NOT spin a `Bash sleep` loop (forbidden — `doctrines/native-coordination.md`)
   and do NOT emit an operator prompt. The yield is silent except for a single
   coordinate status line (`[ROOT] coordinate → N live / M idle / wave-K | next:
   <event>`).

The distinction that makes this safe: **yield is cheap and auto-resumes**
(`SendMessage` auto-resumes a stopped lead since v2.1.77 — `spawn-escalation.md
§II`); **passive-wait is the same yield but with un-drained actionable state and
an implicit ask of the operator.** Same turn-end mechanic, opposite correctness.

---

## V. Active inspection cadence (realizable subset of #113)

#113 asks for wall-clock polling (T+3/T+6/T+10). A lead session has no
self-scheduling timer and **must not** `sleep`-spin to fake one. The realizable,
honest cadence is **event-anchored**:

- The root runs the §IV-b.3 PROBE **at every wake and before every yield** — so a
  drift/liveness check lands on every `TeammateIdle`, every `WAVE-COMPLETE`, and
  every heartbeat-driven wake. In a healthy wave the teammate heartbeats per
  major phase boundary (`spawn-escalation.md §V`), giving the root multiple
  intra-wave wakes to sweep.
- True wall-clock cadence (a sweep at fixed minutes regardless of teammate
  activity) requires a scheduler primitive shepherd does not yet own. Until then
  the **heartbeat-staleness alert** (`spawn-escalation.md §V`, 5-min threshold)
  plus the operator nudge cover the silent-teammate case. A wall-clock daemon is
  a deferred enhancement (track under #113); this doctrine ships the
  event-anchored subset, which already closes the "drift invisible until wave
  END" gap.

---

## VI. Idle-without-signal — proactive probe (#98)

A `TeammateIdle` with **no preceding `WAVE-COMPLETE`** means the teammate stopped
mid-lane (often blocked on a background `cargo test`, #108) and dropped its
heartbeat. The root MUST NOT sit on it. On that wake:

1. `SendMessage(to: <teammate>, "status? phase / last_node / in_flight_task")` —
   one probe.
2. Mark the teammate a `TEAMMATE-STALL` candidate; start the 5-min staleness
   timer (`spawn-escalation.md §V`).
3. If the teammate answers → resume the cycle. If it stays silent past the
   threshold → surface `TEAMMATE-STALL` to the operator with the last phase +
   heartbeat; do NOT auto-recover.

The teammate side is bound symmetrically: a conductor that goes idle without
`WAVE-COMPLETE` sends a `{phase, last_node, in_flight_task}` status within one
turn of its next wake (`agents/conductor.md §Escalation protocol`,
`spawn-escalation.md §V`). Both sides moving toward each other closes the blind
window.

---

## VII. Mechanical backstop — `coordinate_drive_guard.sh`

Per `doctrines/invariant-enforcement-matrix.md` and the #86/#66 lesson that
**prose-only invariants erode under load**, the no-passive-wait rule is backed by
a `Stop` hook, not left to prose alone.

**Hook:** `hooks/scripts/coordinate_drive_guard.sh`, registered on `Stop` in
`hooks/hooks.json` (documented in `claude-code-platform-alignment.md §V`).

**What it does.** At end-of-turn (root about to stop), it reads the canonical DB:

- **Fast-path (the common case):** no `root.db`, or zero live teammates
  (`v_teammates_live` empty) → exit 0 silently. Solo `/shepherd:start`,
  `/shepherd:plant`, and all non-spawn work are untouched — the guard only ever
  engages inside an active spawn session.
- **Engaged (live teammates present):** if there is **actionable, root-clearable
  coordinate state** — an `idle` teammate, or lead-bound unread mail — the root
  is trying to stop with work undrained (the passive-wait bug). The hook emits
  `{"decision":"block","reason": <the §IV-b cycle, abbreviated>}` so the platform
  re-engages the root to drain it instead of pausing.
- **Legitimate-pause aware:** the block `reason` explicitly authorizes the §II
  operator-pauses ("if you are stopping to surface a HARD-STOP or
  operator-question, emit that question and stop — that is correct"). The guard
  nudges the root to *act or ask*, never to sit.

**Runaway safety (non-negotiable).** A `Stop` hook that blocks indefinitely is
itself a hazard (cf. the runaway-loop class, #114). The guard is bounded:

- **2-nudge cap.** A per-session counter (`<ns>/tmp/coordinate_drive_guard.*`)
  increments per consecutive block; past the cap the guard **fails open** (exit
  0) so a legitimate "stop with idle teammates" (e.g. operator ending the day)
  is never trapped. The counter resets the moment actionable state clears.
- **Fail-open on everything.** Missing DB, `sqlite3` absent, malformed payload,
  any error → exit 0. The guard never blocks on uncertainty.
- **Config override.** `[spawn].coordinate_drive_guard` in `shepherd.toml`:
  `block` (default), `warn` (stderr nudge only, never blocks), `off` (fast-path
  exit). Operators tune to taste; the safe default mechanizes the fix.

The hook is a **backstop**, not the mechanism. The §I–§VI behavioral contract is
the fix; the hook catches the regression when the prose erodes.

---

## VIII. What is NOT a violation

To keep the guard and the contract from over-firing, these are explicitly fine:

- **Yielding while teammates are genuinely `active`** (recent heartbeats, mailbox
  drained, probe clean). That is §IV-b.4 working as designed — the guard does not
  block it (no `idle` row, no unread).
- **The enumerated §II operator-pauses.** Surfacing a `HARD-STOP`,
  operator-question, dispute verdict, or the ROOT CLOSE REPORT and stopping is
  correct. The guard's `reason` authorizes it; the operator-question itself is
  the drained state.
- **Solo `/shepherd:start`.** No team, no root tier — the guard fast-paths out.
- **Pre-spawn.** Before `TeamCreate` there are no live teammates; the approval
  gate pause is legitimate and guard-invisible.

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
