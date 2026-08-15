# v6.0.3 — substrate-defect fix spec (Family A + Family B)

- **Branch:** `v6.0.3-dev.0`  ·  **Scope:** patch (dispatch-logic / brief-template fixes)
- **Date:** 2026-05-30  ·  **Author:** root (opus[1m] main session)
- **Issues:** Family A — #103 · Family B — #97, #98, #99, #100, #102

## Probe finding (gates #103)

A 4-cell Dynamic-Workflow dispatch probe (`opus1m-dispatch-probe`, wv1e7fgor) returned
**all green**: `sonnet`, `opus`, inherited-session `opus[1m]`, and explicit
`model:'opus[1m]'` override all resolved cleanly. **opus[1m] does NOT fail in DW
subagent dispatch at small scale.** Therefore #103's literal premise ("the `agent()`
call fails") is not reproduced. `@engineer` is a *single* once-per-sprint dispatch —
NOT a large-set fan-out — so the "large sets of subagents" risk surface does not apply
to it either. Consequence: the model-drop is **reframed from bugfix to operator choice**
(cost/headroom), while the *defensive* hardening (surface errors, never stall silently)
is applied regardless.

## Shared vocabulary (PINNED — copy these strings verbatim across files)

| Halt code | Tier | Meaning |
|---|---|---|
| `TEAMMATE-GIT-WRITE` | teammate | About to run `git rebase`/`merge`/`push`/`worktree` outside own commit scope. (Already defined in `commands/spawn.md`; propagated here.) |
| `TASK-LANE-MISMATCH` | teammate | Task created without `{lane_id}:` prefix/owner, or claimed outside own lane. **NEW.** |
| `ENGINEER-MODEL-FAIL` | root | `@engineer` dispatch returned a model-resolution / API error. **NEW.** |
| `WAVE-GATE-NOT-RELEASED` | root | A `wave-{N}-gate-{sprint_slug}` marker was never `TaskUpdate`'d to completed; lanes starving on `addBlockedBy`. **NEW.** |

- **Conductor Hard prohibitions:** existing last is **#18**. New: **#19 = git-write** (`TEAMMATE-GIT-WRITE`), **#20 = lane-task** (`TASK-LANE-MISMATCH`).
- **Wave-gate task naming:** `wave-{N}-gate-{sprint_slug}` (e.g. `wave-0-gate-v603-dev0`).
- **Mechanical gate API (correct):** `TaskCreate(subject,description)` → `TaskUpdate(taskId, addBlockedBy:["<gateId>"])`. Release: `TaskUpdate(taskId:"<gateId>", status:"completed")`. A task with unresolved `blockedBy` cannot be claimed.
- **Task ownership API (correct):** `TaskUpdate(owner:"<teammate-name>")` (NOT a `TaskCreate` arg). Hook event surfaces it as `assignee`.
- **Lane routing key:** task title prefix `"{lane_id}: "`. Terminal task `shepherd-{sprint_slug}-close` carries **no** prefix (that absence is the signal).
- **Heartbeat phrase:** "status-check required within 1 turn"; wake-status SendMessage payload `{phase, last_node, in_flight_task}`; idle-without-`WAVE-COMPLETE` → existing `TEAMMATE-STALL` (no new code).
- **Worktree:** root pre-creates `git worktree add .worktrees/{sprint_slug}-{lane_id} {sprint_branch}` BEFORE `TeamCreate`; emits `[WORKTREE-READY]`; INHERITED CONTEXT gains `worktree_status: pre-created`.

## #103 decision split

- **APPLY now (model-agnostic hardening):** `agents/shepherd.md` — `ENGINEER-MODEL-FAIL` halt-code row + dispatch-checklist guard.
- **HELD (operator decision):** `agents/engineer.md` line 4 `opus[1m]`→`opus`; `skills/shepherd/SKILL.md` line 133 prose. **Recommendation: KEEP `opus[1m]`** — probe-cleared, single dispatch (not large-set), 1M gives headroom for XL-sprint plan authorship. Operator may override for cost.
- **Out of scope (do NOT touch):** `agents/planter.md` opus[1m] (always main-chat session); `SKILL.md` line 84 / `flock.md` line 431 / `dispatch-tier-separation.md` line 51 planter rows.

---

## FILE: commands/spawn.md  (#97, #98, #100, #102)

**E1 (#97) — new section** between `## § Build the teammate prompt` and `## § Spawn dispatch`:
```
### Pre-spawn worktree creation (v6.0.3 — #97)

Root MUST create every lane worktree on disk BEFORE issuing `TeamCreate`. Path +
branch are deterministic from `lane_id`:

    for each lane:  git worktree add .worktrees/{sprint_slug}-{lane_id} {sprint_branch}
    git worktree list      # verify every lane worktree exists

Emit a `[WORKTREE-READY]` block (lane → worktree path). `TeamCreate` is GATED on it:
it MUST NOT fire until all lane worktrees exist. A teammate never creates its own
worktree — that is a `TEAMMATE-GIT-WRITE` violation. Eliminates the boot-time
`ANOMALY: worktree missing` round-trip.
```

**E2 (#97)** — in the INHERITED CONTEXT block, add immediately after the `Worktree path:` line:
```
  worktree_status:         pre-created   # root created this before you booted (#97); do NOT git worktree add
```

**E3 (#97)** — in `## § Smooth path`, insert between `[4]` and `[5]`:
```
[4.5] main chat      pre-creates all lane worktrees (git worktree add) and emits
                     [WORKTREE-READY] BEFORE TeamCreate (#97)
```

**E4 (#98)** — replace ESCALATION RULES bullet `5. Heartbeat: emit a status row at every phase boundary.` with:
```
    5. Heartbeat (v6.0.3 — #98):
       a. SendMessage a one-line status at EVERY major phase boundary — even when
          blocked on a background task (e.g. a long cargo test).
       b. If you go idle WITHOUT having sent WAVE-COMPLETE, then on your next wake
          SendMessage(to: lead) a status within 1 turn carrying
          {phase, last_node, in_flight_task}. Canonical rule: spawn-escalation §V
          "Idle-without-WAVE-COMPLETE".
```

**E5 (#100)** — append to the WAVE-BOUNDARY COMMIT PROTOCOL block:
```
  WAVE-GATE MECHANICAL DEPENDENCY (v6.0.3 — #100):
    Root TaskCreates a "wave-{N}-gate-{sprint_slug}" marker per wave boundary at
    spawn. Each lane's wave-(N+1) IMPL task is then TaskUpdate'd with
    addBlockedBy:["<gate task id>"] (addBlockedBy is a TaskUpdate field, NOT a
    TaskCreate arg). A task with unresolved blockedBy CANNOT be claimed, so no lane
    starts wave N+1 until root releases the gate via
    TaskUpdate(taskId:"<gate>", status:"completed") after the wave-N gate passes.
    Do NOT begin a next-wave step whose task is still blocked.
```

**E6 (#102)** — replace the `- **Task list.** The teammate creates its own via `TaskCreate`.` note with:
```
- **Task list.** Teammates share ONE team list. Every TaskCreate title MUST be
  prefixed "{lane_id}: <description>" and you MUST TaskUpdate(owner: <your-teammate-name>)
  immediately after creating it. Only claim/work/complete tasks whose title prefix
  matches YOUR lane id. Violations: TASK-LANE-MISMATCH. Canonical:
  doctrines/lane-task-ownership.md.
```

---

## FILE: agents/conductor.md  (#98, #99, #100, #102)

**E1 (#99) — Hard prohibitions, add #19** after #18:
```
19. **(v6.0.3, TEAMMATE MODE ONLY) NEVER run git writes outside your commit scope.** If you are about to run `git rebase`, `git merge`, `git push`, or `git worktree` (add/remove): STOP. `SendMessage(to: lead, halt_code: TEAMMATE-GIT-WRITE, blocking: true)`. Root handles ALL git ops outside your worktree's own commit/branch scope — including rebasing your branch onto the sprint branch at every wave-gate. Even if you are behind, do NOT rebase; root does it.
```

**E2 (#102) — Hard prohibitions, add #20**:
```
20. **(v6.0.3, TEAMMATE MODE ONLY) Lane-scope your tasks.** Every `TaskCreate` title MUST be prefixed `"{lane_id}: "` and you MUST `TaskUpdate(owner: <your-teammate-name>)` immediately. NEVER claim or complete a task whose title prefix is not your `lane_id` — it belongs to a sibling lane. Violation: `TASK-LANE-MISMATCH`. Per `doctrines/lane-task-ownership.md`.
```

**E3 (#99) — Halt codes table**, add row after the `WRONG-TIER-DISPATCH` row:
```
| `TEAMMATE-GIT-WRITE` (TEAMMATE mode only) | About to run `git rebase`/`merge`/`push`/`worktree` outside your commit scope. STOP; `SendMessage(to: lead, halt_code: TEAMMATE-GIT-WRITE, blocking: true)`. Root owns all out-of-scope git ops. Per `dispatch-tier-separation.md §IV-bis.8`. |
```

**E4 (#102) — Halt codes table**, add row:
```
| `TASK-LANE-MISMATCH` (TEAMMATE mode only) | Created/claimed a task outside your `lane_id` prefix, or omitted prefix/owner. Re-title `"{lane_id}: "`, `TaskUpdate(owner: <self>)`, release sibling tasks. Per `doctrines/lane-task-ownership.md`. |
```

**E5 (#98) — §Escalation protocol**, replace bullet `- Heartbeats: emit a one-line status row at every phase boundary so the planter knows you're alive.` with:
```
- Heartbeats (v6.0.3 — #98):
  - Fire a SendMessage status at EVERY major phase boundary — even while blocked on a
    background task (e.g. a long `cargo test`). A silent block reads as a stall.
  - If you go idle WITHOUT having emitted `WAVE-COMPLETE`, then on your next wake send a
    status `SendMessage(to: lead)` within 1 turn carrying `{phase, last_node, in_flight_task}`.
    Root treats a `TeammateIdle` with no prior `WAVE-COMPLETE` as a `TEAMMATE-STALL`
    indicator. Canonical: `spawn-escalation.md §V "Idle-without-WAVE-COMPLETE"`.
```

**E6 (#100) — §Lane-per-conductor model**, replace `ROOT runs the wave-gate sequence on the rebased sprint branch, then advances all lanes to wave w+1.` with:
```
  ROOT runs the wave-gate sequence on the rebased sprint branch. Lane advancement is
  MECHANICAL, not prose: root TaskCreates a `wave-{w}-gate-{sprint_slug}` marker at spawn
  and each lane's wave-(w+1) IMPL task carries `addBlockedBy` on it (set via `TaskUpdate`),
  so a blocked task cannot be claimed until root releases the gate via
  `TaskUpdate(status: completed)` after the gate passes. No lane can jump the gate.
  Per `doctrines/root-shepherd-orchestration.md §I-bis`.
```

**E7 (#99) — §Side-effect boundary (TEAMMATE)**, append after `...preserves teammate context for cache hits.`:
```
Do NOT rebase your branch onto the sprint branch — even if you are behind. Root rebases
every lane at each wave-gate. A teammate `git rebase`/`merge`/`push`/`worktree` is
`TEAMMATE-GIT-WRITE` (Hard prohibition #19).
```

---

## FILE: agents/shepherd.md  (#97, #100, #102, #103-hardening)

**E1 (#97) — §Dispatch mode** activity: insert `pre-create all lane worktrees (`git worktree add`) and emit `[WORKTREE-READY]` BEFORE issuing the `TeamCreate` instruction (#97),` immediately before `issue the `TeamCreate` instruction`.

**E2 (#102) — §Coordinate mode** activity: after `respond to `TeammateIdle`/`TaskCompleted` hooks,` add `route each `TaskCompleted` to its lane by the `"{lane_id}: "` title prefix (a task with no prefix is root-owned, e.g. terminal `shepherd-{sprint_slug}-close`),`.

**E3 (#100) — §Step 2 BODY**: replace the sentence `root runs the wave-N gate, then the lanes advance to wave-N+1` with `root runs the wave-N gate on the rebased sprint branch, then releases the next wave by `TaskUpdate(status: completed)` on the `wave-N-gate-{sprint_slug}` marker — lanes' wave-(N+1) IMPL tasks carry `addBlockedBy` on it and cannot be claimed until release (#100)`.

**E4 (#103 + #100) — Halt codes table**, add two rows after the `TEAMMATE-CRASHED` row:
```
| `ENGINEER-MODEL-FAIL` (v6.0.3) | The `@engineer` dispatch returned a model-resolution or API error (Opus tier unavailable, quota, or transport). Surface the RAW error immediately; do NOT treat a null/error return as an empty plan, do NOT silently retry or advance to the `@critic` gate. Pause for operator. |
| `WAVE-GATE-NOT-RELEASED` (v6.0.3) | A `wave-{N}-gate-{sprint_slug}` marker was never `TaskUpdate`'d to completed after its gate passed; downstream lanes starve on `addBlockedBy`. Release the gate or surface the stuck wave. Per `doctrines/root-shepherd-orchestration.md §I-bis`. |
```

**E5 (#103) — §Dispatch checklist**, append a sub-bullet under the `@engineer` dispatch item:
```
      - If the dispatch call itself errors (model unavailable / API failure): surface
        `ENGINEER-MODEL-FAIL` with the raw error and PAUSE — never treat a null/error
        return as an empty plan (#103).
```

---

## FILE: skills/shepherd/doctrines/spawn-escalation.md  (#98, #100, #102)

**E1 (#98) — §V**, append sub-section:
```
### Idle-without-WAVE-COMPLETE rule (v6.0.3 — #98)

A conductor that goes idle WITHOUT having sent `WAVE-COMPLETE` (lane not closed) MUST,
on its next wake, send a status `SendMessage(to: lead)` within 1 turn carrying
`{phase, last_node, in_flight_task}`. Root treats a `TeammateIdle` with no preceding
`WAVE-COMPLETE` as a `TEAMMATE-STALL` trigger (not a new halt code). The conductor MUST
also heartbeat at every major phase boundary even while blocked on a background task —
a silent block is indistinguishable from a stall.
```

**E2 (#100) — §VI**, append:
```
Wave-gate is mechanical (v6.0.3 — #100): root TaskCreates a `wave-{N}-gate-{sprint_slug}`
marker; each lane's wave-(N+1) IMPL task carries `addBlockedBy` on it (set via `TaskUpdate`);
root releases via `TaskUpdate(status: completed)` only after the gate passes. A blocked
task cannot be claimed, so the wait is enforced by the task list, not prose. If root never
releases: `WAVE-GATE-NOT-RELEASED`.
```

**E3 (#102) — §II hook table**, append a note after the `TaskCreated`/`TaskCompleted` rows:
```
> Lane-routing contract (v6.0.3 — #102): every teammate `task_title` is prefixed
> `"{lane_id}: "` and `assignee` (set via `TaskUpdate(owner: ...)`) is the owning teammate.
> Root routes `TaskCompleted` to a lane by the title prefix; a task with NO prefix is
> root-owned (terminal `shepherd-{sprint_slug}-close`).
```

**E4 (#102) — §VI Conductor obligation**, add sentence: `Every `TaskCreate` carries a `"{lane_id}: "` title prefix and is `TaskUpdate(owner: <self>)`'d immediately (per `lane-task-ownership.md`).`

**E5 (#102) — OQ-XI1**, append: `RESOLVED (v6.0.3 — #102): terminal tasks carry NO lane prefix; that absence is how root distinguishes them from wave-scope lane tasks. Terminal name remains `shepherd-{sprint_slug}-close`.`

---

## FILE: skills/shepherd/doctrines/dispatch-tier-separation.md  (#99)

**E1** — add a row to the §IV-bis.7 quick-reference table:
```
| Teammate runs git rebase/merge/push/worktree | `TEAMMATE-GIT-WRITE` | teammate-conductor |
```

**E2** — add subsection `### IV-bis.8` (place after §IV-bis.7):
```
### IV-bis.8. TEAMMATE-GIT-WRITE — teammate git custody (v6.0.3 — #99)

A teammate-conductor's git authority is bounded to commits on its OWN worktree branch.
It MUST NOT run `git rebase`, `git merge`, `git push`, or `git worktree` (add/remove) —
those are root-tier operations. Root rebases every lane onto the sprint branch at each
wave-gate; a teammate never rebases itself, even when behind. On reaching for any such
command: STOP and `SendMessage(to: lead, halt_code: TEAMMATE-GIT-WRITE, blocking: true)`.
Cross-ref: `agents/conductor.md §Hard prohibitions #19` + `§Side-effect boundary`.
Propagates the halt code already defined in `commands/spawn.md`.
```

---

## FILE: skills/shepherd/pipeline.md  (#100)

**E1** — in the §V walk algorithm, near the WAVE-GATE inline step, add:
```
          - WAVE-GATE (spawn mode): root releases the next wave via
            TaskUpdate(status: completed) on the wave-{N}-gate-{sprint_slug} marker;
            lanes' wave-(N+1) IMPL tasks carry addBlockedBy on it and cannot be claimed
            until release (#100). Mechanical, not prose.
```

---

## FILE: skills/shepherd/doctrines/root-shepherd-orchestration.md  (#100)

**E1 — §I-bis**, replace `Wave boundaries: each lane's teammate SendMessages WAVE-COMPLETE and goes idle; root runs the wave-gate and commits; then the lanes advance to wave w+1.` with:
```
Wave boundaries (mechanical, v6.0.3 — #100): each lane's teammate `SendMessage`s
`WAVE-COMPLETE` and goes idle; root runs the wave-gate and commits. Advancement is
enforced by the task list, not prose: root TaskCreates a `wave-{w}-gate-{sprint_slug}`
marker at spawn; each lane's wave-(w+1) IMPL task carries `addBlockedBy` on it (set via
`TaskUpdate`); root releases via `TaskUpdate(status: completed)` after the gate passes,
which unblocks the next wave. A blocked task cannot be claimed, so no lane jumps the
gate. If root fails to release: `WAVE-GATE-NOT-RELEASED`.
```

---

## FILE: skills/shepherd/doctrines/lane-task-ownership.md  (#102 — NEW FILE)

```
# Lane-task ownership (v6.0.3 — #102)

> Framework-intrinsic. Applies under `/shepherd:spawn` (Agent Teams), TEAMMATE mode.

## Problem

All teammate-conductors in a spawn share ONE team task list. The platform broadcasts
`TaskCreated`/`TaskCompleted` to every team session, so a task created by lane L2 is
visible — and claimable — by L4. Without a partition, lanes confuse ownership and root
cannot route a `TaskCompleted` to the correct lane's context.

## Rule

1. **Title prefix.** Every `TaskCreate` from a teammate-conductor MUST prefix its title
   with its lane id: `"{lane_id}: <description>"` (e.g. `"L4: W2-impl-obs-init"`).
2. **Ownership.** Immediately after creating a task, `TaskUpdate(owner: <your-teammate-name>)`.
   (The `TaskCreated`/`TaskCompleted` hook surfaces this as `assignee`. `TaskCreate` has
   no owner argument.)
3. **Claim discipline.** Only claim/work/complete tasks whose title prefix matches YOUR
   `lane_id`. A different prefix belongs to a sibling lane — leave it.
4. **Terminal tasks.** Root-owned terminal tasks (e.g. `shepherd-{sprint_slug}-close`)
   carry NO lane prefix. Root uses that ABSENCE to distinguish them from wave-scope tasks.

## Halt code

`TASK-LANE-MISMATCH` — a teammate created a task without its lane prefix/owner, or claimed
a task outside its lane. Re-title, set owner, release the sibling task.

## See also

- `agents/conductor.md §Hard prohibitions #20`, `§Halt codes`
- `commands/spawn.md §Build the teammate prompt`
- `skills/shepherd/doctrines/spawn-escalation.md §VI`
```

---

## FILE: skills/shepherd/doctrines/README.md  (#102)

**E1** — add a row to the doctrine index table (after the `zero-duplicate-tolerance.md` row):
```
| `lane-task-ownership.md` | Team task list is shared; every teammate task is lane-prefixed + owner-set; root routes by title prefix (`TASK-LANE-MISMATCH`) |
```

---

## Apply protocol (for file-disjoint apply agents)

1. Read your target file FRESH; the anchors above are approximate — match the file's
   actual current text. Use exact-string Edits.
2. Apply ONLY your file's edits. Do NOT touch any other file. Do NOT run git.
3. Copy PINNED shared strings verbatim (halt-code names, prohibition numbers, task naming).
4. After editing, run the file's acceptance greps (below) and report pass/fail + anomalies.

## Acceptance (greps)

- `grep -n 'TEAMMATE-GIT-WRITE' agents/conductor.md` ≥ 3; `… dispatch-tier-separation.md` ≥ 2
- `grep -n 'TASK-LANE-MISMATCH' agents/conductor.md` ≥ 2; `… lane-task-ownership.md` ≥ 1
- `grep -n 'ENGINEER-MODEL-FAIL' agents/shepherd.md` ≥ 2
- `grep -n 'WAVE-GATE-NOT-RELEASED' agents/shepherd.md skills/shepherd/doctrines/root-shepherd-orchestration.md` ≥ 2
- `grep -n 'worktree_status: pre-created' commands/spawn.md` ≥ 1; `[WORKTREE-READY]` in `commands/spawn.md` + `agents/shepherd.md`
- `grep -rn 'addBlockedBy' commands/spawn.md agents/conductor.md skills/shepherd/doctrines/` ≥ 3 (and NEVER as a `TaskCreate` arg)
- `grep -n 'Idle-without-WAVE-COMPLETE' skills/shepherd/doctrines/spawn-escalation.md agents/conductor.md` ≥ 2
- `test -f skills/shepherd/doctrines/lane-task-ownership.md` and it appears in `doctrines/README.md`
- HELD: `grep -n 'opus\[1m\]' agents/engineer.md` still present (operator decision pending)
