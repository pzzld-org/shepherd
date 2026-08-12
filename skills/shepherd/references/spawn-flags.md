---
name: spawn-flags
description: Semantics for /shepherd:spawn's --scope, --parallel, --auto, and --staged flags. Use when invoking spawn with a flag, or documenting flag behavior.
---

# Spawn flags

## --scope

`--scope` declares workload SCALE: `sprint` (default) | `patch` | `minor` |
`version`. Composes with `--parallel <N>`; `--auto` = alias for
`--scope patch`.

**Scope is workload-scale, NEVER a quality bar** — HOW MANY sprints walked,
NEVER license to downscope seed content or under-deliver on lane
completeness, gate honesty, or close-grade thresholds. "It's just a patch"
justifies nothing.

| Value | Sprint count | Preflight |
|---|---|---|
| `sprint` | 1 | Checks 1-5 only |
| `patch` | `sprints_per_patch` (default 10) | resolve `dev.LAST`: `[version].dev_total` → seed count → operator prompt |
| `minor` | `patches_per_minor × sprints_per_patch` (~100) | MUST type `confirm minor`; experimental |
| `version` | `minors_per_major × patches_per_minor × sprints_per_patch` (~1000) | MUST type `confirm version` + resource warning; experimental |

The confirmation phrase is case-insensitive but MUST be exact — no punctuation, no extra words.

`--parallel` composition: `sprint`/`patch` allow `2..4`; `minor` caps `≤2`
sequential-only; `version` MUST refuse `--parallel >1`.

Before every spawn, enumerate the sprint list (patch boundary, seed path,
present/MISSING, total, missing count). A missing seed on a multi-sprint
scope MUST refuse, routing the operator to `/shepherd:plant` per gap; a
single `--scope sprint` walk MUST NOT refuse — `SEED-AUTHOR` plants inline
instead. Always show a resource estimate (sprints, time, API calls,
worktree peak) from priors, else defaults.

Root cycles idle → dispatch → coordinate once per sprint: spawn →
babysit/wave-complete/materialize → close-swarm → cleanup (planter's,
past 1 sprint) → next.

Failure modes: `SCOPE-SEED-GAP` (seed missing for a sprint),
`SCOPE-CONFIRMATION-MISSING` (minor/version, no confirm phrase),
`SCOPE-VERSION-OVER-BUDGET` (estimate exceeds `[autorun].max_token_budget`;
operator opts in or narrows), `SCOPE-PARALLEL-OVERREACH` (minor/version +
`--parallel >1`), `SCOPE-DEV-LAST-UNKNOWN` (`dev.LAST` unresolvable,
operator declines).

## --parallel

`--parallel <N>` fans N teammates, each in
`.worktrees/{sprint_slug_i}`, named `shepherd-parallel-{sprint_slug}`. N:
`2..[spawn].max_parallel` (default 4).

Preflight (HARD-STOP): `file_scope.exclusive` + shared build-manifest
paths (`Cargo.toml`/`package.json`/`pyproject.toml`/`go.mod`/`*.lock`/
`*.sum`/`build.gradle`) MUST be file-disjoint across all N seeds; exactly
N MUST exist (gap → `/shepherd:plant`); `sprint_dependencies` MUST NOT
cycle. **Dev-order merge gate**: `dev.N+1` MUST NOT merge before
`dev.N`'s PR merges, even if `N+1` closes first.

Cleanup per close: verify report → merge gate → rebase-merge if unheld →
remove worktree → update status board + carry-forward ledger;
stewardship (agent-* branches, `shepherd.lock`) waits for all N to close.

### Multiplexed escalation

N escalations multiplex root's triage (`skills/shepherd/references/
escalation.md §Escalation payload`), routed by `teammate_name`
(`shepherd-parallel-{sprint_slug}`) — never by `teammate_type`, whose
`TeammateIdle` value may show a model slug, `"conductor"`, or an agent
filename instead of a stable key.

| Priority | Condition | Action |
|---|---|---|
| P0 (CRITICAL preempt) | `halt_code` in `HARD-STOP`, `TEAMMATE-GIT-WRITE`, `BASE-DRIFT`, `PARALLEL-COLLISION` | Jumps queue; >1 simultaneous → operator decides |
| P1 (FIFO) | Any other `halt_code` | FIFO by `TeammateIdle` arrival |
| P-NOTIFY (non-blocking) | `halt_code: null`, `blocking: false` | Immediate commit + ack, no queue |

A CRITICAL arrival mid-triage bookmarks it
(`triage-suspended.md`); `TeammateIdle` is BLOCKING — root MAY hold a
teammate ≤2 minutes. `CROSS-DEP-WAIT`: producing
wave done → reply with the artifact path, resume; not yet produced →
notify to wait, re-check each `TeammateIdle`;
`[spawn].cross_dep_timeout_sec` (default 300) expires → escalate with its
phase + heartbeat. `PARALLEL-COLLISION`: root halts
every affected teammate, surfaces four options — amend A; amend B;
serialize (A first, B reads A's output); or abort/re-scope — then
resumes.

Hard stops beyond base: teammate count drops to 0; a dev-order
cycle refused at preflight.

## --auto

`--auto` (alias `--scope patch`) runs one teammate per sprint, sequentially;
root does all inter-sprint work between spawns.

Loop: `[AUTO INIT]` resolves `dev.N..dev.LAST`, confirms
`[autorun].min_grade`, a 10-second interruptible countdown → per `dev.N`:
SPAWN → BABYSIT (`operator-question`/`hard-stop` PAUSES the loop, never
ends it; a stalled teammate PAUSES too, at an auto-specific >10 min
threshold — vs. the 5 min base) → SPRINT CLOSE (verify close report,
catch-up commit, rebase-merge, open/accumulate PR, delete `dev.N`, cut
`dev.N+1`, author handoff at 60-120 lines, update carry-forward ledger +
error budget, apply `[autorun].inter_sprint_pause`: `brief` (default, ~5s
then proceeds) | `signoff` (pauses for operator `resume auto`) | `none`
(immediate)) → TERMINATION CHECK.

**Patch-boundary lock-in.** Once `dev.LAST` is determined it's locked —
root MUST NOT re-detect it mid-loop; changing it requires an operator
interrupt, `shepherd.toml` update, and `--auto` re-invoke.

**Loop-termination payload** (terminal `TaskCompleted`, `task_id:
shepherd-{sprint_slug}-close`): `task_result` carries `grade`,
`carry_forwards`, `handoff_path`, `error_budget_consumed`,
`open_questions`.

Termination codes: `LAST-DEV` (clean finish, full cleanup),
`GRADE-FLOOR` (grade below `[autorun].min_grade`, action per
`[autorun].on_grade_floor` — `abort` default/`pause`/`continue`; also the
fail-safe for a missing/malformed `task_result`, forcing AUTO ABORT with
`grade: UNKNOWN`), `BUDGET-ZERO` (error budget exhausted),
`OPERATOR-INTERRUPT`, `ESCALATION-PAUSE` (pauses, never terminates). Any
inter-sprint step that fails halts `[AUTO PAUSE]` naming the failed step —
never re-attempt without confirmation.

**AUTO ABORT REPORT** shape (every `abort`-path exit): termination code;
sprint at termination (`dev.{N}` of `dev.{LAST}`); grade at termination;
error budget remaining; handoff doc path; last committed SHA on the patch
branch; carry-forwards pending; recommended action — manual
`/shepherd:spawn dev.{N+1}`, or `--auto dev.{N+1}..dev.{LAST}` to resume.

Root MUST NOT spawn next sprint until inter-sprint work is committed. The
next teammate inherits exactly three documents — active seed, auto-handoff
doc, carry-forward ledger; a missing handoff at spawn-next is a hard stop.

**Operator pause window.** After the countdown, any message but exactly
`continue`/`ok` is an interrupt: the loop pauses at last commit (no work
lost); `resume auto` continues; `abort` terminates with an AUTO ABORT
REPORT; anything else re-prompts to resume or abort.

## --staged

`--staged` overlaps seed authorship with pre-seed orientation across two
sessions: Session A (`/shepherd:spawn <slug> --staged`) orients
immediately, then WAITS; Session B (`/shepherd:plant <slug>`)
authors it and signals readiness on the dedicated CROSS-SESSION channel
(`shctx signal`, migration 0020's `session_signals`). These are two
INDEPENDENT operator sessions sharing a repo but no team graph, so native
SendMessage (intra-session only) cannot bridge them — `shctx signal` is the
purpose-built durable handoff. It is NOT a teammate inbox.

**Session A — orientation wave.** MUST dispatch a repo/ledger-general
`@discovery` pass (and MAY dispatch intro-mode `@auditor`),
scope-partitioned like the planter's optional wave — orientation
against the repo as-is, not a delta-check against a nonexistent seed. Cache
findings for the engineer's later `[DISCOVERY-CONTEXT]`.

**Session B — the signal.** After the seed passes `shctx seed verify` and
commits, planter runs `shctx signal send --to="spawn-<slug>"
--kind=seed-ready` (recipient `spawn-<slug>` and kind `seed-ready` are EXACT
strings — `test_staged_handoff.sh` asserts both), emits its SEED-READY
banner, continues its report.

**Session A — the wait gate.** After orienting, arm a `ScheduleWakeup` poll
≤270s apart. Poll the dedicated channel with `--consume` (a one-shot: the
matched signal is stamped `consumed_at` so a re-nudged Session A never
re-processes it):
```bash
shctx signal poll --as="spawn-<slug>" --kind=seed-ready --consume --json \
  | jq -r '.[] | select(.kind=="seed-ready")'
```
A hit → read the committed seed, `shctx seed verify` it (the seed FILE, not
the signal, is the source of truth — a signal without a committed, verifying
seed MUST be ignored), fall through to normal pipeline (INTRO-COMBO-WAVE
re-meshes as the delta-check). Timeout `[spawn].staged_timeout_minutes`
(default 90) → halt `STAGED-TIMEOUT`.

**Seedless abandonment.** If planting is abandoned, the seedless ladder
applies to any missing-seed spawn: orientation is already done,
so `SEED-AUTHOR` emits its one turn-ending confirm, plants inline (planter
frame, `shctx seed verify`) or routes to `/shepherd:plant` — never
a best-effort default run.

A signal without a committed seed MUST be ignored — the seed file, not the
message, is the source of truth. `--staged` is opt-in; a plain
`/shepherd:spawn` with a pre-existing seed is unchanged.
