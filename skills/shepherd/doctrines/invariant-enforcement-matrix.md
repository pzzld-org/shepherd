---
title: invariant-enforcement-matrix
status: binding
since: v6.0.2
description: |
  The coverage map (#86): every load-bearing shepherd invariant paired with the
  MECHANISM that enforces it, the enforcement TYPE (hard-block / flag / lint /
  auditor / doctrine), and its STATUS (live / deferred / gap). The root cause
  behind #66, #59, and #74 was prose-only enforcement of load-bearing rules; this
  matrix makes that visible and is the contract Wave 1 guards implement.
---

# Invariant → enforcement coverage matrix (#86)

A load-bearing invariant enforced by prose alone evaporates the moment a
different dispatcher (a Dynamic Workflow runtime in `acceptEdits`, a teammate with
no orchestrator in the loop) executes the work. v6.0.1 proved this in the field
(#66, #89, #59, #74). This matrix pairs each invariant with a **mechanism** and
states honestly whether that mechanism is a hard block today, a softer signal, or
a known gap. **An invariant with no mechanical teeth is a liability, not a rule.**

Enforcement **types**:
- **hard-block** — a PreToolUse hook emits `permissionDecision: deny`; the call cannot fire.
- **flag** — a hook emits `additionalContext` (operator-visible warning); the call proceeds.
- **lint** — a static check (`hooks/tests/*`) fails CI / the test harness.
- **auditor** — a close/wave auditor concern grades it (post-hoc).
- **doctrine** — prose contract only (the weakest; flagged for promotion).

---

## I. Primitive↔axis binding (#89) — `doctrines/primitive-axis-binding.md`

| # | Invariant | Mechanism | Type | Status | Test |
|---|---|---|---|---|---|
| 1 | A lane (teammate) is spawned via **Agent Teams**, never a Dynamic Workflow (inversion 1) | `bash_guard.sh` Check 0-bis: a `*.workflow.js` carrying teammate-spawn markers is denied; **platform also forbids it** (workflows orchestrate subagents only) | hard-block | **live** | `test_dispatch_guard.sh` ("inverted workflow") |
| 2 | A flock role carries **no `team_name`** (a step is a subagent, not a lane) | `dispatch_guard.sh` Check 3 → `DISPATCH-TEAMMATE-TYPE-MISMATCH`; the **mechanical floor is the `subagent_type` discipline (Check 1/5)** — the `team_name` branch is unit-tested defence-in-depth (no such field on real `Agent`/`Task` input, #93) | hard-block (DiD) | **live (tested)** | `test_dispatch_guard.sh` ("coder/auditor-as-teammate") |
| 3 | A gate-free step fan-out **compiles to a Dynamic Workflow**, not hand-rolled dispatch (inversion 2) | `dispatch_guard.sh` Check 6 (flag) + `dispatch-cascade.md §IV-bis` PRIMARY-path doctrine; **hard compile-correctness is #85 / Wave 2** | flag → (Wave 2 hard) | **partial** | flag asserted; hard block deferred to #85 |
| 4 | Teammate spawns are Agent Teams; lanes counted, never "lanes per wave" | Wave 0 ontology rewrite + grep Gate 0 | doctrine + lint-candidate | **live (doctrine)** | Gate 0 grep (Wave 0) |

> Inversion 2 is intentionally a **flag**, not a hard block: the doctrine permits
> in-context dispatch as a **fallback** on workflow-runtime failure
> (`workflow-compile-down.md §VI`), so hard-refusing hand-rolled fan-out would break a
> legitimate path. The teeth for inversion 2 are the compiler's segment-purity +
> faithfulness guards (#85), which ensure that *when* you compile, the result is correct.

## II. Dispatch-tier contract (#66, #61) — `doctrines/dispatch-tier-separation.md §IV-bis`

| # | Invariant | Mechanism | Type | Status | Test |
|---|---|---|---|---|---|
| 5 | Every flock dispatch sets `subagent_type: shepherd:<role>` (no omit / general-purpose / Explore / Chat) | `dispatch_guard.sh` Check 1 → `DISPATCH-MISSING-SUBAGENT-TYPE` | hard-block | **live** | `test_dispatch_guard.sh` |
| 6 | Only `shepherd:conductor` is spawned as a teammate (lane→teammate-conductor) | `dispatch_guard.sh` Check 3 (vestigial defence-in-depth; `team_name` is accepted-but-ignored since v2.1.178, so the real discriminator is the spawn intent — `Agent`/`Task`=ephemeral subagent vs the native teammate-spawn=teammate, #93) | hard-block (DiD) | **live (tested)** | `test_dispatch_guard.sh` |
| 7 | `subagent_type` stays inside the closed flock (no `shepherd:<unknown>`) | `dispatch_guard.sh` Check 5 → `DISPATCH-OFF-FLOCK` | hard-block | **live** | `test_dispatch_guard.sh` |
| 8 | A teammate never spawns its own team | **platform-structural** (a non-lead cannot spawn a team; "no nested teams", #93) + `dispatch_guard.sh` Check 2 as defence-in-depth (best-effort teammate detection via `.worktrees/` cwd + legacy env) | structural + hard-block (DiD) | **live (tested)** | `test_dispatch_guard.sh` |
| 9 | A teammate never dispatches `@engineer`/`@critic` | `dispatch_guard.sh` Check 4 → `WRONG-TIER-DISPATCH` (teammate detected env-independently via `.worktrees/` cwd, #93); engineer/critic also self-halt on the brief field | hard-block | **live (tested)** | `test_dispatch_guard.sh` |

> **Teammate-spawn mechanism (#93; v2.1.178 update).** Teammates spawn via the **native
> teammate-spawn** — a natural-language lead instruction referencing the `shepherd:conductor`
> subagent definition (NO `TeamCreate`/`TeamDelete` tool — removed v2.1.178; no setup step).
> NOT `Agent({team_name})` (that parameter is accepted but ignored) — and a teammate session carries NO
> identity env var (`anthropics/claude-code#35447`, closed not-planned). Net for this matrix:
> the **mechanical, always-fires floor** is the `subagent_type` discipline (#5/#7, Check 1/5).
> The `team_name`-keyed and teammate-mode rows (#2/#6/#8) are **defence-in-depth** — unit-tested,
> but layered over the platform's own structural guarantees (Dynamic Workflows orchestrate
> subagents only; teammates cannot nest). Teammate detection for #9 is env-independent via the
> `.worktrees/` cwd. See `doctrines/claude-code-platform-alignment.md §I (Resolved #93)`.

## III. The eight #66 field violations — explicit status

| #66 | Violation | Mechanism | Type | Status |
|---|---|---|---|---|
| 1 | coders dispatched as teammates | `dispatch_guard.sh` Check 3 | hard-block | **live, tested** |
| 2 | missing `CARGO_TARGET_DIR` per parallel lane | `bash_guard.sh` parallel-cargo path (warn-candidate) | flag | **gap** — warn not yet wired; tracked for Wave 1 follow-up |
| 3 | missing `--frozen`/`--locked` on auditor cargo | `bash_guard.sh` (auditor-cargo warn-candidate) | flag | **gap** — tracked |
| 4 | parallel cargo instead of sequential | `bash_guard.sh` Check 3-bis (`run_in_background` → deny) + Check 4 (`&` → warn) | hard-block + flag | **live, tested** (#91) |
| 5 | contradictory file scope in a brief | DEDUP-GATE / Brief-Validity Checklist (`flock.md §@coder`); completeness auditor | auditor | **existing** (conductor-run, not a new hook) |
| 6 | failed to kill dead tmux panes | cleanup stewardship (`planter.md §3`, `worktree_lifecycle.sh`) | doctrine + cleanup | **existing** (Stop-hook prune is a candidate) |
| 7 | missed blast-radius files from a trait change | engineer Phase-0 mesh + auditor `dependency-topology` | auditor | **existing** |
| 8 | ran whole waves as direct subagents instead of teammate-conductors | `root-shepherd-orchestration.md §I-bis` + `dispatch_guard.sh` (blocks the shape; "root must spawn conductors for BODY" is phase-contextual) | doctrine + partial hard-block | **partial** |

Violations 1 and 4 — the two that cleanly reduce to a dispatch/exec *shape* — are now
hard-blocked and tested. 2/3/6 are flag/cleanup candidates (documented gaps, low risk).
5/7 are inherently *content/analysis* quality and belong to the auditor swarm, not a
pre-dispatch hook. 8 is doctrine + a partial shape-block. **This row-by-row honesty is
the point of #86** — it converts "we have a rule" into "here is the rule's teeth, or its
absence."

## IV. Capability / least-privilege (#74, #84) — `hooks/tests/lint_agent_capabilities.sh`

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 10 | Read-only reviewers (auditor/discovery/critic) carry no un-scoped mutating verb | `lint_agent_capabilities.sh` (read-only set) | lint | **live** (#74) |
| 11 | `Write` on a read-only role is path-scoped by `lock_guard.sh` (PreToolUse Write) | lint asserts the hook is registered + a `Write` matcher exists | lint + hard-block | **live** (#74) |
| 12 | No agent carries a **gratuitously broad** mutating verb under `acceptEdits` (least-privilege, all nine) | `lint_agent_capabilities.sh` writer-role sweep (forbids `*delete*`/`*merge*`/`*deploy*` outside a role's documented need) | lint | **live (extended)** (#84) |

> Under a Dynamic Workflow runtime every spawned agent runs in `acceptEdits` with **no
> orchestrator in the loop** (`workflow-compile-down.md §VII`), so the `tools:` allowlist
> is the *only* capability boundary. Retained dual-use verbs (e.g. `execute_sql` on
> `@engineer`/`@worker` for read queries) are deliberate, documented retentions — the lint
> forbids the clearly-gratuitous mutating verbs and pins the read-only set.

## V. Gate / close discipline (#59) and spawn-prompt hygiene (#90, #91)

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 13 | cargo gates run sequentially (one `&&`-chain, foreground) | `bash_guard.sh` Check 3-bis (`run_in_background` deny) + `cargo-sequential-gates.md` execution pattern | hard-block + doctrine | **live** (#91) |
| 14 | `cargo test --workspace --features full` runs before close | `Stop` close-finalize agent-hook (`hooks.json`) — extend with a since-last-commit gate check | flag → hard | **gap** — close-finalize check is a Wave-1 follow-up (#59) |
| 15 | Conductor boot prompt's INHERITED CONTEXT carries no implementation steps | `commands/spawn.md` boot-prompt SCOPE RULE + conductor first-action check | doctrine | **gap** — SCOPE RULE is a Wave-1 follow-up (#90) |

## V-bis. Flock-output review + redo (#167) — `doctrines/flock-output-review.md`

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 16 | A conductor holds a `review_verdict: PASS` from a wave-review `@auditor` before emitting `WAVE-COMPLETE` (no forwarding on a coder's self-gate-green claim) | TEAMMATE: root refuses a `WAVE-COMPLETE` lacking `review_verdict`+`reviewer` → `DISPATCH-CONTRACT-VIOLATION` (`agents/shepherd.md §Escalation triage`). SOLO: the close `completeness` auditor verifies every wave recorded a PASS, capping the grade otherwise | auditor + hard-block (teammate) / auditor (solo) | **live** |
| 17 | A `REDO` verdict re-dispatches the **named** author on the **named** scope (never a blanket wave re-run), via the hot-fix vehicle ladder, capped at 3 iterations | conductor REDO loop reuses `doctrines/hotfix-dispatch.md` ladder + `REDO-CAP-EXCEEDED` HARD-STOP at iteration 3 | doctrine + halt-code | **live** |
| 18 | Root delegates the diff-review verdict to an `@auditor` at `LANE-INTEGRATE` and forces `REDO-DIRECTIVE` through the owning teammate; root never edits teammate source | root prohibition #2 (no source writes) + `teammate_git_guard.sh` + `GATES-BROKEN` "via owning teammate" path | hard-block + doctrine | **live** |

> Enforcement honesty (per this matrix's purpose): row 16's teammate leg is a hard
> refusal (root rejects the wave); its solo leg is the close `completeness` auditor
> (grade-capping, post-hoc), a promotion candidate for a wave-time `close_finalize_check.sh`
> assertion. Rows 17–18 reuse existing teeth (the hot-fix ladder, the git guard, root's
> source-write prohibition); the new surface is the proactive review *trigger*, not a new mechanism.

## V-ter. Self-contained engineer + critic-proof; model map; workdir prune (v6.2.5) — `doctrines/engineer-self-contained-plan.md`, `doctrines/model-map.md`, `doctrines/workdir-prune.md`

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 19 | A self-contained engineer teammate's plan is accepted by root WITHOUT re-critique — but only against a hash-tied **critic-proof** proving the plan was critiqued AND edited ≥1 time | `shctx plan verify` re-hashes the live plan and requires `edited=true` + `post==current-bytes` + verdict + iterations≥1, else `CRITIC-PROOF-MISSING` / `PLAN-UNEDITED` / `CRITIC-PROOF-STALE` / `PLAN-UNCRITIQUED`; root's thin gate = `seed verify` + `plan verify` + lane sanity | CLI gate + doctrine | **live** |
| 20 | A self-contained engineer dispatches ONLY its read-only sub-flock (`@discovery` + intro-`@auditor` + its own `@critic` self-gate) — never `@coder`/`@worker`, never a nested `@engineer`, never a nested teammate; and it is spawned as a NAMED teammate, never an Agent/Task subagent | `dispatch_guard.sh`: Check 4 blocks teammate→`@engineer` unconditionally + teammate→`@critic` unless brief carries `dispatcher: engineer-self-contained`; Check 4b `ENGINEER-TOPOLOGY-MISMATCH` blocks a self-contained engineer dispatched as a subagent; Check 4c `ENGINEER-SUBFLOCK-VIOLATION` blocks a marked (`dispatcher: engineer-self-contained`) dispatch to any non-read-only role (`@coder`/`@worker`/nested `@engineer`) — "no code is touched" with mechanical teeth; the engineer `Agent` grant is pinned to the `{discovery,auditor,critic}` read-only scope by `lint_agent_capabilities.sh` (#119/#169/#172) | hard-block + lint | **live** |
| 21 | Every dispatching tier injects each role's model from the single `[models]` map; root is advisory (preflight warn, not a rebind) | `shctx models resolve <role>` (config → built-in default) injected as the Agent `model:` pin at each tier; `shctx models show` preflight | CLI + doctrine | **live** |
| 22 | `shctx prune` reclaims only non-current ∧ terminal ∧ aged state; `--dry-run` default, `--confirm` moves to /tmp (reversible), every DB DELETE table-guarded; never touches releases / current focus / sprint_metrics / pinned memory / active locks | fence (branch≠current ∧ terminal ∧ aged) + move-not-delete snapshot + `sqlite_master` existence guard; DB-row deletes preview-only in v6.2.5 | CLI + doctrine | **live (on-disk) / preview (DB rows)** |

## VI. Promotion backlog (gaps → mechanisms)

The **gap** rows above are this matrix's live to-do. Each names its target mechanism so
the promotion is a bounded change, not a redesign:
- **#66.2 / #66.3** → a `bash_guard.sh` warn for parallel cargo lacking `CARGO_TARGET_DIR`, and for auditor cargo lacking `--frozen`/`--locked`.
- **#59** → a `Stop`-hook check: if a close report is being written but no `cargo test --workspace --features full` ran since the latest commit, flag/deny CLOSE-FINALIZE.
- **#90** → a `commands/spawn.md` boot-prompt SCOPE RULE forbidding implementation steps in INHERITED CONTEXT + a conductor first-action `SCOPE-VIOLATION` halt.
- **#66.6** → a `Stop`-hook dead-pane / orphan-worktree prune.
- **inversion 2 (#3)** → the #85 compiler segment-purity + §IV faithfulness diff (Wave 2).

## VII. See also

- `doctrines/primitive-axis-binding.md` — the axis↔primitive↔unit binding the guards enforce.
- `doctrines/dispatch-tier-separation.md §IV-bis` — the forbidden-dispatch halt-code contract.
- `hooks/scripts/dispatch_guard.sh` — checks 1–6 (dispatch shape).
- `hooks/scripts/bash_guard.sh` — workflow-inversion + cargo-sequential checks.
- `hooks/tests/test_dispatch_guard.sh` — the Gate 1 reproduction-and-block test.
- `hooks/tests/lint_agent_capabilities.sh` — the #74/#84 capability lint.
- `doctrines/workflow-compile-down.md §VII` — why allowlists are the only `acceptEdits` boundary.
