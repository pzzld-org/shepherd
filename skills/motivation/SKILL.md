---
name: motivation
description: Focus record, FOCUS-HEARTBEAT drift guard, /goal templates, loop discipline, drive contract, SOAK, and SENTINEL. Use when running a FOCUS-LOOP, arming /goal, or auditing a soak/sentinel loop.
---

# Motivation — focus, drive, loops, outcomes

Time, for a computer, is irrelevant — outcomes only.

## Focus record

The focus record is the durable north-star artifact in `root.db` (migration `0013_focus.sql`), surviving compaction — `hooks/scripts/focus_rehydrate.sh` denormalizes it into a rehydration digest on `/compact`. Primary key `(sprint, lane)`: omit `lane` for the sprint record, pass it for a teammate-conductor's own lane.

Fields: `objective` (SEED-VERIFY), `active_node` (Stage-Graph cursor, per WAVE-GATE), `ready_set`, `obligations` (open lanes/mail/gates, JSON), `invariants` (hold-true rules, JSON), `updated_at` — via `shctx loop focus upsert`/`show --sprint=<branch>` (operator entry: `commands/focus.md`). Seeded acceptance predicates ride in `objective`/`obligations` ([SOAK](#soak)), so rehydration restores not just *where* but *what outcome*.

## FOCUS-HEARTBEAT

The FOCUS-LOOP re-anchors every wake ([Drive contract](#drive-contract)); a long stretch with no teammate event has no wake, so the north-star recedes. On `--heartbeat`, and every `[focus].heartbeat_actions` or `[focus].heartbeat_interval`, the orchestrator re-reads the record and emits:

```
[FOCUS-HEARTBEAT] iter=<i> · since-anchor=<N actions | Tm>
objective:   <the sprint / lane north-star, one line>
active_node: <id> — <short label>
invariants:  <hold-true rules, comma-joined>
next_action: <the single next concrete step toward active_node>
drift:       on-node | [DRIFT-WARN] self → <correction>
```

Self-drift-check: did the last stretch advance `active_node` within `invariants`? On-node → resume; wandered → `[DRIFT-WARN] self`: stop, return to `active_node`, file the digression rather than chase it (bounded — `skills/shepherd/SKILL.md §Principles`). Read the record fresh, never from memory.

The two cadence legs are not equal. `[focus].heartbeat_interval` is the **deterministic** leg: it delegates the clock to the native `/loop` (`commands/focus.md`), so a real wake fires on a real schedule — the only leg that *guarantees* a re-anchor on a long unattended stretch, and the right one to set because timing belongs in a mechanism, not an in-reply estimate (`skills/shepherd/references/operating-philosophy.md`). `[focus].heartbeat_actions` is a **soft, best-effort self-prompt** (default on): the orchestrator re-anchors after roughly N significant actions. It is a latent estimate, not a counted guarantee (nothing backs it but your own judgement), so treat it as a zero-cost nudge and rely on `heartbeat_interval` when a guarantee matters.

## Goals

`/goal` is operator-armed, lead-only — sessions emit copy-paste lines, never self-arm (`skills/harness/SKILL.md §Goals`).

- Root at PLAN-GATE: `/goal all lanes of <branch> report CLOSE-FINALIZE, all test suites pass, and the ROOT CLOSE REPORT has been emitted`
- Planter at start: `/goal <slug>.seed.md exists, passes shctx seed verify, and SEED-READY has been emitted`
- Teammates carry no goal — they run the focus record + FOCUS-HEARTBEAT instead.

## Loop discipline

Every loop MUST be bounded, role-shaped, and terminate on a measurable predicate. **Bounded**: `--max` set before iteration 1; missing = `PLAN-MISSING-LOOP-CAP` (`shctx doctor` preflight, PLAN-GATE) — default 5, >5 needs engineer justification, >10 needs critic sign-off. **Role-shaped**: the iterator fixes the contract — `@coder` converges a gate, `@discovery` exhausts a research question, `@worker` reconciles/monitors, `@auditor` refines a hypothesis chain, `@engineer` converges a plan via critic, orchestrator drives FOCUS-LOOP; wrong agent = `DISPATCH-WRONG-ROLE`. Full catalog: `skills/harness/references/loop-templates.md` — apply, never re-derive. **Measurable predicate**: the brief MUST specify `new_findings: true|false` as a top-level field; unstructured prose = `LOOP-REPORT-INVALID`; the conductor evaluates independently; cap-exceeded (`i >= max`) = `LOOP-CAP`, never a silent exit.

**Pacing** (orthogonal; all delegate the wake clock to native `/loop`, NEVER `Bash sleep`): **self-paced** ends early on `false` (convergent templates only); **fixed interval** required for WATCH templates (self-paced would stop the watch exactly when healthy); **in-session** drives `wake → act → probe → yield` directly. Wrong pacing = `PLAN-INVALID-INTERVAL`.

An iteration with no measurable progress is `LOOP-STALL` (audit finding, not a halt code) — a CODER-CONVERGENCE loop iterating 5 rounds with unchanged gate failures MUST be filed HIGH: halt and escalate.

Also not authorized: reusing a loop ID across nested instances; AUDITOR-REFINE replacing a Pattern-3 swarm; ENGINEER-PLAN-REFINE from teammate-conductor tier (root-tier-exclusive).

## Drive contract

Once `/shepherd:spawn` team liveness is confirmed, root ENTERS THE FOCUS-LOOP as its default primary operating mode until CLOSE-FINALIZE — dispatch is the start of active coordination, never a hand-off to the human. `skills/harness/SKILL.md §Stop hook` backstops a lapse, NEVER the primary mechanism. A teammate-conductor on an L/XL or multi-wave lane MUST run its own FOCUS-LOOP to CLOSE-FINALIZE/final WAVE-GATE; single-wave conductors exempt.

**Two kinds of stop.** Operator-pause is a legitimate, closed set of 7 — the CANONICAL enumeration; `skills/shepherd/SKILL.md §Operator surface` and `agents/shepherd.md §Operator surface` point here, never restate it — (pre-spawn approval gate; `HARD-STOP`; operator-question escalation; `CROSS-TEAMMATE-DISPUTE` adjudication; scope-confirmation `confirm minor`/`confirm version`; end-of-scope ROOT CLOSE REPORT; explicit `OPERATOR-INTERRUPT`), each emitting a concrete, actionable question. Passive-wait (ending the turn at the dispatch boundary, post-WAVE-COMPLETE, or mid-wave, with no question pending) is forbidden. Yield to events, never the operator, unless only the operator can answer.

**The cycle, every wake:** WAKE (`TeammateIdle`, `SendMessage`, `TaskCompleted`, or root's own continuation) → ACT (drain the lead's native SendMessage queue, route by `halt_code`, release the next wave gate on `WAVE-COMPLETE`, prune a materialized idle teammate; idle teammate with NO `WAVE-COMPLETE` → `SendMessage` a status query, mark `TEAMMATE-STALL` candidate, start a 5-min staleness timer — silent past threshold surfaces `TEAMMATE-STALL`, NEVER auto-recover) → PROBE (`shctx teammate liveness --stale-mins=5`; `git diff --stat` per live lane, changed-file count > ~1.5x the brief's `[FILE-SCOPE]` → `[DRIFT-WARN]`, `SendMessage` the lane to confirm; run the FOCUS-HEARTBEAT self-drift-check) → YIELD (one status line; never `Bash sleep`-spin or an operator prompt).

**Scoped per-lane removal only** (v6.0.9 regression). Prune ONE idle teammate = `git worktree remove .worktrees/{sprint_slug}-{that_lane}` for that lane only. NEVER run the blanket `git worktree list | grep agent- | ... remove` loop or `git worktree prune` while siblings are live — that kills every in-flight lane at once. The blanket sweep is CLOSE-FINALIZE's RF-5 (`skills/shepherd/references/pipeline.md §CLOSE-FINALIZE`), run only after `v_teammates_live` hits zero.

## SOAK

A green CLOSE-FINALIZE certifies a seeded outcome only at delivery; a deploy can still degrade afterward. SOAK-LOOP re-runs every seeded acceptance predicate (seed §6) on a post-close interval (T+1d, T+7d) via native `/loop` + `Monitor`, surfacing `OUTCOME-REGRESSION` (owned by `skills/shepherd/references/pipeline.md §Gates`) on a break. Detection-only by default: a regression opens a new operator decision, never auto-remediation.

```
/shepherd:loop "soak outcomes for <sprint>" --agent worker --interval 1d --max 6
```

The only exception is [Sentinel](#sentinel).

## Sentinel

AUTONOMOUS-SENTINEL is SOAK-LOOP's supervised-remediation superset: an operator has explicitly empowered the conductor to FIX live regressions, not merely report them — strip the ACT stage and rails block and it is exactly SOAK-LOOP. It can NEVER fire by default: ALL THREE gates below MUST hold before a single ACT fires; absent any one, SOAK-LOOP runs instead:

1. `[close].autonomous_sentinel` is `"on"` (default `"off"`).
2. Seed declares `close: autonomous-sentinel`.
3. A complete `sentinel_rails` block — missing it is a seed defect, `@critic` rejects at PLAN-GATE with `SENTINEL-RAILS-MISSING`.

**The stage walk:**

```
PROBE:     Run each seeded acceptance predicate against live state — read-only, no mutation.
CLASSIFY:  HOLD (still true) | REGRESSED (now false) | NEW (no seeded baseline — surface only)
ACT:       For each REGRESSED predicate only (NEW is never auto-remediated):
             1. Cluster file-disjoint → H clusters; each MUST be ≤S scope or
                SENTINEL-SCOPE-EXCEEDED, surface, never widen.
             2. Dispatch through the hotfix-dispatch ladder: H=1 → one @coder dynamic-
                workflow step; (1,3] → one batched workflow, ≤3 concurrent; over
                caps → SENTINEL-HF-CAP.
             3. GATES-BEFORE-DEPLOY: full gate set + regressed predicates before any deploy;
                a failed gate is AUTO-ROLLBACK — revert, don't deploy, surface.
             4. Deploy only if gates green AND rails permit a live flip (paper-only by
                default); else stop at the gate-green artifact and surface.
             5. RE-PROBE the regressed predicate(s); still REGRESSED counts as one failed
                cycle.
TERMINATE: K consecutive clean ticks       → SENTINEL-DONE (converged)
           N total hot-fixes in window     → SENTINEL-HF-CAP hard-stop
           --max ticks reached             → SENTINEL-LOOP-CAP (LOOP-CAP shape)
           any hard rail tripped           → SENTINEL-HARD-STOP (operator decision)
```

`@worker` owns PROBE/CLASSIFY; ACT dispatches `@coder` through the ladder.

On `SENTINEL-DONE`, MUST emit `## Sentinel summary` with the full predicate roster, per-tick CLASSIFY history, every ACT cycle (dispatch → gate → deploy/rollback → re-probe), and the final verdict.

**The hard rails** (all REQUIRED in `sentinel_rails`; missing = `SENTINEL-RAILS-MISSING`):

| Rail | Binding rule | Trip → halt code |
|------|--------------|------------------|
| gates-before-deploy | The full gate set runs on every fix BEFORE any deploy/promotion. No deploy on red. | `SENTINEL-HARD-STOP` |
| auto-rollback | A failed gate reverts the fix automatically — never ships a red fix, never leaves a half-applied change. | `SENTINEL-ROLLBACK` (logged; counts toward the HF cap) |
| ≤S severity cap | Every remediation cluster is ≤S scope (`skills/shepherd/references/pipeline.md §Hotfix ladder`). A larger fix is out of sentinel scope — surface, never widen. | `SENTINEL-SCOPE-EXCEEDED` |
| ≤3 concurrent | At most 3 concurrent `@coder` clusters per ACT (the standing HOTFIX concurrency cap, `skills/shepherd/references/pipeline.md §Hotfix ladder`). | `SENTINEL-HARD-STOP` |
| ≤N total HF cap | At most N hot-fixes across the whole soak window (`hf_cap`, default small). The N+1th regression hard-stops to the operator. | `SENTINEL-HF-CAP` |
| no destructive DB ops | No `DROP`/`TRUNCATE`/destructive migration, no irreversible data mutation, ever — regardless of authorization. | `SENTINEL-HARD-STOP` |
| paper-only / never-flip-to-live | Remediation stops at the gate-green artifact and does NOT flip to live/production unless the operator authorized a live flip in `sentinel_rails` (`live_flip: authorized`). Default is paper-only. | `SENTINEL-HARD-STOP` |
| operator-override-each-tick | The operator can halt the loop at any tick (native `/loop` is cancelable; an operator HALT message is honored before the next ACT). The sentinel never becomes un-stoppable. | n/a (always honored) |
| full audit trail | Every PROBE result, CLASSIFY bucket, ACT dispatch, gate outcome, deploy decision, and re-probe is recorded via `shctx loop record` + the hook event log (`skills/context/SKILL.md §Event log`). A tick that mutated state without an audit row is a framework violation. | `SENTINEL-HARD-STOP` |

A `SENTINEL-ROLLBACK` is logged, not fatal — the rails working as designed; repeated rollbacks that exhaust the HF cap escalate to `SENTINEL-HF-CAP`. These caps compose with, never replace, the standing HOTFIX caps (`skills/shepherd/references/pipeline.md §Hotfix ladder`).
