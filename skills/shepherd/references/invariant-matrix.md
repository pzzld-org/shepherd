---
title: invariant-matrix
description: |
  Coverage map pairing every load-bearing shepherd invariant with its
  enforcement mechanism, type, and status. Use when checking whether a
  rule has mechanical teeth.
---

# Invariant → enforcement coverage matrix

A load-bearing invariant enforced by prose alone evaporates under a
different dispatcher (a Dynamic Workflow in `acceptEdits`, a teammate with
no orchestrator in the loop). Each row pairs an invariant with its
**mechanism** and states honestly whether that mechanism is a hard block, a
softer signal, or a known gap. **An invariant with no mechanical teeth is a
liability, not a rule.**

Enforcement **types**: **hard-block** (PreToolUse denies the call) —
**flag** (hook warns, call proceeds) — **lint** (static check fails CI) —
**auditor** (a close/wave concern grades it) — **doctrine** (prose only,
the weakest, flagged for promotion).

## I. Primitive↔axis binding — `skills/shepherd/references/pipeline.md §Lane law`

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 1 | A lane (teammate) is spawned via **Agent Teams**, never a Dynamic Workflow | `bash_guard.sh` Check 0-bis denies `*.workflow.js` carrying teammate-spawn markers; platform also forbids it (workflows orchestrate subagents only) | hard-block | **live** |
| 2 | A flock role carries **no `team_name`** (a step is a subagent, not a lane) | `dispatch_guard.sh` Check 3→`DISPATCH-TEAMMATE-TYPE-MISMATCH`; floor is `subagent_type` discipline (Checks 1/5) — `team_name` is defense-in-depth (no such field on the real `Agent`/`Task` input) | hard-block (DiD) | **live (tested)** |
| 3 | A gate-free step fan-out **compiles to a Dynamic Workflow at ROOT ONLY**; a teammate-conductor's lane fan-out is in-context `Agent()`, unconditionally (`Workflow` is denied inside subagents — #220) | `dispatch_guard.sh` Check 6 (flag, root-tier)+`skills/shepherd/references/pipeline.md §Lane law` (driver-conditional); `test_v639_wiring.sh` pins the partition | flag+doctrine+test | **live (doctrine)** |
| 4 | Teammate spawns are Agent Teams; lanes counted, never "lanes per wave" | Wave-0 ontology+grep Gate 0 | doctrine+lint-candidate | **live (doctrine)** |

Rows 1-3: `hooks/tests/test_dispatch_guard.sh`; row 4: the Gate 0 grep. Row
3 is a **flag**, not a hard block — in-context dispatch is a permitted
fallback on workflow-runtime failure; the teeth are the compiler's
segment-purity + faithfulness guards.

## II. Dispatch-tier contract — `skills/shepherd/SKILL.md §Dispatch law`

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 5 | Every flock dispatch sets `subagent_type: shepherd:<role>` (no omit / general-purpose / Explore / Chat) | `dispatch_guard.sh` Check 1→`DISPATCH-MISSING-SUBAGENT-TYPE` | hard-block | **live** |
| 6 | Only `shepherd:conductor` is spawned as a teammate | `dispatch_guard.sh` Check 3 (`team_name` accepted-but-ignored; real discriminator is spawn intent) | hard-block (DiD) | **live (tested)** |
| 7 | `subagent_type` stays inside the closed flock (no `shepherd:<unknown>`) | `dispatch_guard.sh` Check 5→`DISPATCH-OFF-FLOCK` | hard-block | **live** |
| 8 | A teammate never spawns its own team | platform-structural (a non-lead cannot spawn a team)+Check 2 DiD (`.worktrees/` cwd+legacy env) | structural+hard-block (DiD) | **live (tested)** |
| 9 | A teammate never dispatches `@engineer`/`@critic` | `dispatch_guard.sh` Check 4→`WRONG-TIER-DISPATCH` (detected via `.worktrees/` cwd); engineer/critic self-halt too | hard-block | **live (tested)** |

Rows 5-9: `hooks/tests/test_dispatch_guard.sh`.

> **Teammate-spawn mechanism.** Teammates spawn via native teammate-spawn: a
> natural-language lead instruction citing the `shepherd:conductor` subagent
> definition, NOT `Agent({team_name})` (accepted but ignored). The
> always-fires floor is `subagent_type` discipline (rows 5/7); rows 2/6/8
> are defense-in-depth; row 9 detects via `.worktrees/` cwd. See
> `skills/harness/SKILL.md §Agent Teams`.

## III. The eight field violations

| # | Violation | Mechanism | Type | Status |
|---|---|---|---|---|
| 1 | coders dispatched as teammates | `dispatch_guard.sh` Check 3 | hard-block | **live, tested** |
| 2 | missing `CARGO_TARGET_DIR` per parallel lane | `bash_guard.sh` parallel-cargo path (warn-candidate) | flag | **gap** — tracked |
| 3 | missing `--frozen`/`--locked` on auditor cargo | `bash_guard.sh` (auditor-cargo warn-candidate) | flag | **gap** — tracked |
| 4 | parallel cargo instead of sequential | `bash_guard.sh` Check 3-bis (`run_in_background`→deny)+Check 4 (`&`→warn) | hard-block+flag | **live, tested** |
| 5 | contradictory file scope in a brief | DEDUP-GATE / Brief-Validity Checklist (`skills/shepherd/references/flock.md §@coder`); completeness auditor | auditor | **existing** |
| 6 | failed to kill dead tmux panes | cleanup stewardship (`agents/planter.md`, `worktree_lifecycle.sh`) | doctrine+cleanup | **existing** (Stop-hook prune candidate) |
| 7 | missed blast-radius files from a trait change | engineer Phase-0 mesh+auditor `dependency-topology` | auditor | **existing** |
| 8 | ran whole waves as direct subagents instead of teammate-conductors | `skills/shepherd/SKILL.md §Root contract`+`dispatch_guard.sh` (shape-blocked; phase-contextual) | doctrine+partial hard-block | **partial** |

Rows 1/4: dispatch/exec *shape*, hard-blocked and tested. 2/3/6: flag/
cleanup candidates (low risk). 5/7: content-quality, auditor-owned, not a
pre-dispatch hook. 8: doctrine plus a partial shape-block.

## IV. Capability / least-privilege — `hooks/tests/lint_agent_capabilities.sh`

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 10 | Read-only reviewers (auditor/discovery/critic) carry no un-scoped mutating verb | `lint_agent_capabilities.sh` (read-only set) | lint | **live** |
| 11 | `Write` on a read-only role is path-scoped by `lock_guard.sh` (PreToolUse Write) | lint asserts the hook is registered+a `Write` matcher | lint+hard-block | **live** |
| 12 | No agent carries a **gratuitously broad** mutating verb under `acceptEdits` (least-privilege, nine roles) | `lint_agent_capabilities.sh` writer-role sweep (forbids `*delete*`/`*merge*`/`*deploy*` outside documented need) | lint | **live (extended)** |

> Under a Dynamic Workflow every agent runs in `acceptEdits` with **no
> orchestrator in the loop**, so `tools:` is the *only* capability boundary.
> Dual-use verbs (e.g. `execute_sql` on `@engineer`/`@worker` for read
> queries) are deliberate; the lint forbids only clearly-gratuitous mutating
> verbs. See `skills/harness/SKILL.md §Capability enforcement`.

## V. Gate / close discipline and spawn-prompt hygiene

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 13 | cargo gates run sequentially (one `&&`-chain, foreground) | `bash_guard.sh` Check 3-bis (`run_in_background` deny)+`skills/shepherd/references/pipeline.md §Gates` | hard-block+doctrine | **live** |
| 14 | `cargo test --workspace --features full` runs before close | `Stop` close-finalize agent-hook (`hooks.json`) — extend with a since-last-commit gate check | flag→hard | **gap** — follow-up |
| 15 | Conductor boot prompt's INHERITED CONTEXT carries no implementation steps | `commands/spawn.md` boot-prompt SCOPE RULE+conductor first-action check | doctrine | **gap** — follow-up |

## V-bis. Flock-output review + redo — `skills/shepherd/references/pipeline.md §Wave review + REDO`

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 16 | A conductor holds a `review_verdict: PASS` from a wave-review `@auditor` before emitting `WAVE-COMPLETE` (never forwarding a coder's self-gate-green claim) | TEAMMATE: root refuses `WAVE-COMPLETE` lacking `review_verdict`+`reviewer`→`DISPATCH-CONTRACT-VIOLATION`. SOLO: close `completeness` auditor verifies every wave recorded a PASS | auditor+hard-block (teammate) / auditor (solo) | **live** |
| 17 | A `REDO` verdict re-dispatches the **named** author on the **named** scope (never a blanket re-run), via the hot-fix ladder, capped at 3 iterations | conductor REDO loop reuses `skills/shepherd/references/pipeline.md §Hotfix ladder`+`REDO-CAP-EXCEEDED` HARD-STOP at iteration 3 | doctrine+halt-code | **live** |
| 18 | Root delegates the diff-review verdict to an `@auditor` at `LANE-INTEGRATE` and forces `REDO-DIRECTIVE` through the owning teammate; root never edits teammate source | root prohibition #2 (no source writes)+`teammate_git_guard.sh`+`GATES-BROKEN` path | hard-block+doctrine | **live** |

> Row 16's teammate leg is a hard refusal; its solo leg is the close
> `completeness` auditor, grade-capping post-hoc. Rows 17-18 reuse existing
> teeth; the new surface is the review *trigger*.

## V-ter. Self-contained engineer, model map, workdir prune

`skills/shepherd/references/pipeline.md §INTRO` / `skills/context/references/model-map.md` / `skills/context/SKILL.md`

| # | Invariant | Mechanism | Type | Status |
|---|---|---|---|---|
| 19 | A self-contained engineer teammate's plan is accepted by root WITHOUT re-critique — only against a hash-tied **critic-proof** proving the plan was critiqued AND edited at least once | `shctx plan verify` re-hashes the plan, requires `edited=true`+`post==current-bytes`+verdict+iterations≥1, else `CRITIC-PROOF-MISSING`/`PLAN-UNEDITED`/`CRITIC-PROOF-STALE`/`PLAN-UNCRITIQUED`; root's gate = `seed verify`+`plan verify`+lane sanity | CLI gate+doctrine | **live** |
| 20 | A self-contained engineer dispatches ONLY its read-only sub-flock (`@discovery`+intro-`@auditor`+`@critic` self-gate) — never `@coder`/`@worker`/nested `@engineer`/teammate; spawned as a NAMED teammate only | `dispatch_guard.sh` Check 4 blocks teammate→`@engineer`, and teammate→`@critic` unless marked `dispatcher: engineer-self-contained`; Check 4b `ENGINEER-TOPOLOGY-MISMATCH` blocks subagent dispatch; Check 4c `ENGINEER-SUBFLOCK-VIOLATION` blocks dispatch outside the trio; `lint_agent_capabilities.sh` pins `Agent` to `{discovery,auditor,critic}` | hard-block+lint | **live** |
| 21 | Every dispatching tier injects each role's model from the single `[models]` map; root is advisory only | `shctx models resolve <role>` pins the Agent `model:` at each tier; `shctx models show` preflight | CLI+doctrine | **live** |
| 22 | `shctx prune` reclaims only non-current∧terminal∧aged state; `--dry-run` default, `--confirm` moves to /tmp (reversible); never touches releases / current focus / metrics / pinned memory / active locks | fence (branch≠current∧terminal∧aged)+move-not-delete snapshot+`sqlite_master` guard; DB-row deletes preview-only | CLI+doctrine | **live (on-disk) / preview (DB)** |
| 23 | A Dynamic Workflow's `agent()` calls carry an explicit `model:`/`agentType:` pin — omitting BOTH silently inherits the MAIN-LOOP model, the one dispatch primitive row 21 doesn't reach (`dispatch_guard.sh` fires on `Agent`/`Task`, never on the internal spawns a Workflow script makes) | `workflow_model_guard.sh` `PreToolUse(Workflow)`→`WORKFLOW-MODEL-PIN-MISSING`; string-content-blind static scan (`workflow_model_lint.py`); `[hooks].workflow_model_guard`=block\|warn\|off; `// shepherd:model-pin-override` marker escape hatch (#178) | hard-block | **live (tested)** |
| 24 | The `Workflow` tool is a TOP-LEVEL primitive: ROOT (`shepherd`) GRANTS it and drives Dynamic Workflows directly, while the teammate-tier leads (`@engineer`/`@conductor`) are subagents where `Workflow` is hard-denied (CC 2.1.212), so they MUST NOT carry the inert grant — their first-class fan-out is in-context `Agent()` (supersedes the v6.3.6 "both leads grant Workflow" claim) | `lint_agent_capabilities.sh` (`LEAD_MANDATED_WORKFLOW="shepherd"` + `WORKFLOW_TEAMMATE_DENIED` inverse) + `hooks/tests/test_lead_workflow_tool.sh` (root-strip fails / teammate-add fails); `auditor.md §Dispatch-substrate` grades teammate `absent` as correct (#220, was #207) | lint+test+auditor | **live** |
| 25 | The "one dispatcher, waves of dynamic workflows" routine has ONE canonical definition (`wave-routine.md`): root drives it directly (`/shepherd:start`, the agent-teams fallback), a `@conductor` runs it abbreviated per-lane — same per-wave compile / hard-rule preamble / serial root gate, differing only in scope + git authority | `lint_agent_capabilities.sh` `LEAD_MANDATED_WORKFLOW` now includes `shepherd` (root GRANTS `Workflow` or it cannot drive a wave) + `hooks/tests/test_v638_wiring.sh` pins every reference leg (#217) | lint+test+doctrine | **live** |
| 26 | Wave-gate facts are computed in deterministic space, never latent: production LOC by `scripts/loc-count.py` (brace-matched `cfg(test)` exclusion — #216), wave-return by polling `scripts/journal-status.sh` on the run's `journal.jsonl` not the blind task registry (#213), disk headroom by `scripts/df-guard.sh --min=12` before any cargo (#214) | `hooks/tests/test_loc_count.sh` / `test_journal_status.sh` / `test_df_guard.sh` pin behavior; `test_exec_bits.sh` pins the exec bit; `pipeline.md §Gates` + `wave-routine.md` cite them | test+doctrine | **live (tested)** |
| 27 | Every read-only reviewer whose prose writes registry rows via `shctx` GRANTS `Bash` — read-only-on-SOURCE, not no-Bash; the critic shipped without it and could not register its Step 0.5 verdict deliverable (a #207-class no-fallback gap) | `lint_agent_capabilities.sh` read-only-role Bash-presence block (auditor/critic/discovery) | lint | **live** |
| 28 | `Workflow` is denied inside any spawned subagent/teammate (CC 2.1.212); root drives Dynamic Workflows, a teammate-conductor/engineer fans out in-context via `Agent()` (first-class, not a fallback) | platform fact canonical in `skills/harness/SKILL.md §Workflow tool`; `conductor.md §DISPATCH MODE` + `engineer.md` + `wave-routine.md`/`pipeline.md`/`workflow-templates.md` driver-conditional; `test_v639_wiring.sh` (#220) | doctrine+test | **live** |
| 29 | The shctx registry (SQLite DB + config) resolves to the SHARED MAIN worktree from any linked worktree — never a stray empty per-worktree DB under concurrent `/shepherd:spawn` lanes | `_lib.sh:shctx_repo_root` via `git rev-parse --git-common-dir`; `shctx_in_subworktree` + `cmd_doctor.sh` stray-DB warn; `skills/context/tests/test_worktree_root_resolution.sh` (#221) | fix+test | **live (tested)** |
| 30 | A teammate-conductor COMMITS and PUSHES its OWN lane branch (a detached manager handing root a clean product); only cross-lane integration (merge/rebase/cherry-pick onto dev, worktree lifecycle) is root's `TEAMMATE-GIT-WRITE` | `teammate_git_guard.sh` allows commit+push, blocks merge/rebase/cherry-pick/worktree; `spawn.md` boot-brief + `conductor.md §Hard prohibitions` agree; WAVE-COMPLETE `git_custody` attestation cross-checked in `escalation.md`; `test_teammate_git_guard.sh` (#222) | guard+test+doctrine | **live (tested)** |
| 31 | The coordinate-drive Stop guard re-engages ONLY the recorded spawn LEAD, never a concurrent bystander session sharing the per-repo DB | `spawn_leads` table (migration 0021) + `shctx teammate register-lead` (wired at spawn) + `coordinate_drive_guard.sh` conservative `MY_LEAD`/`OTHER_LEAD` gate; `test_coordinate_drive_guard.sh` bystander-exempt/lead-blocks cases (#223) | fix+test | **live (tested)** |
| 32 | A misrouted in-context `Agent()` sub-dispatch completion is bounded: the conductor defensive-polls past the step's expected runtime, and root RELAYS a leaked sub-flock completion to the owning conductor the same wake (matched via the `shctx teammate` registry + WORKER/CODER `Lane:`) | `conductor.md §Lane walk (Defensive poll)` + `shepherd.md §Coordinate RELAY` + `worker.md` `Lane:` line; `test_v639_wiring.sh` (#224) | doctrine+test | **live** |
| 33 | Stage-Graph `agents:` entries are normalized/validated at extract and every graph reader guards a non-dict entry — the bare-string shorthand `agents: [role]` never crashes `graph next` with an AttributeError | `cmd_plan.sh` `_cmd_extract` normalize + `_cmd_validate` check #5; `cmd_graph.sh` `isinstance(a, dict)` guards; `skills/context/tests/test_graph_next.sh` (#225) | fix+test | **live (tested)** |

## VI. Promotion backlog (gaps → mechanisms)

The **gap** rows are this matrix's live to-do; each names its target
mechanism, so promotion is bounded, not a redesign:
- **row 2/3** → `bash_guard.sh` warn: parallel cargo lacking `CARGO_TARGET_DIR`; auditor cargo lacking `--frozen`/`--locked`.
- **row 14** → `Stop`-hook: deny CLOSE-FINALIZE if no `cargo test --workspace --features full` ran since the latest commit.
- **row 15** → `commands/spawn.md` SCOPE RULE forbidding implementation steps in INHERITED CONTEXT + conductor `SCOPE-VIOLATION` halt.
- **§III row 6** → `Stop`-hook dead-pane / orphan-worktree prune.
- **§I row 3** → compiler segment-purity + faithfulness diff.

## VII. See also

- `skills/shepherd/references/pipeline.md §Lane law` — axis↔primitive↔unit binding
- `skills/shepherd/SKILL.md §Dispatch law` — the forbidden-dispatch halt codes
- `hooks/scripts/dispatch_guard.sh` — checks 1-6 (dispatch shape)
- `hooks/scripts/bash_guard.sh` — workflow-inversion + cargo-sequential checks
- `hooks/scripts/workflow_model_guard.sh` — row 23, the Workflow-tool model-pin gate (#178)
- `hooks/tests/test_dispatch_guard.sh` — the Gate 1 block test
- `hooks/tests/test_workflow_model_guard.sh` — row 23's block test
- `hooks/tests/lint_agent_capabilities.sh` — the capability lint
- `skills/harness/references/workflow-templates.md` — why allowlists are the only `acceptEdits` boundary
