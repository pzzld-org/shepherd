# v651 planter mesh — evidence table

Run: `v651` · branch `v6.5.1` · base `main` · draft PR #328
Author: planter, 2026-08-18
Every row is a fact verified at seed time. Claims carry a `file:line` or a command plus its
literal output. Nothing in this file is inference unless the row says so.

Repo state at mesh time: `git rev-parse --short HEAD` -> `1c39f4c`, `git status --short` ->
empty, `git rev-list --count HEAD` -> `93`.

---

## Section 1 — what landed on the branch (verify the operator's account)

| ROW | Claim | Evidence |
|---|---|---|
| R01 | Branch carries exactly 2 commits above `d666aeb`. | `git log --oneline -4` -> `1c39f4c` / `cc07276` / `d666aeb` / `4a02a88`. |
| R02 | `cc07276` touched 10 files, +315/-6. | `git show --stat --oneline cc07276` -> `10 files changed, 315 insertions(+), 6 deletions(-)`. Files: `CHANGELOG.md`, `crates/cli/src/cmd/dispatch.rs`, `wave_b1_mem.rs`, `wave_b1_status_handoff.rs`, `wave_e_coordination.rs`, `wave_g_coordination.rs`, `crates/cli/tests/dispatch_cli.rs`, `hooks/scripts/remediation_flag_lint.py`, `hooks/tests/test_remediation_flags.sh`, `skills/shepherd/SKILL.md`. |
| R03 | The five remediation sites now name the flag. | `crates/cli/src/cmd/dispatch.rs:185` -> ``"project not scaffolded — run `shepherd init --confirm`: {}",``; `crates/cli/src/cmd/wave_b1_status_handoff.rs:121` -> ``"no DB at {} — run 'shepherd init --confirm'",``. Repo-wide: `git grep -c "shepherd init --confirm"` -> 29 hits. |
| R04 | Every remaining bare `shepherd init` is a historical run artifact, a doc comment, a deliberate negative fixture, or a negative assertion — none is a live operator-facing message. | 37 bare hits; all under `.shepherd/runs/v64*/`, `CHANGELOG.md` prose, `crates/cli/src/cmd/dispatch.rs:157,163` (doc comments), `hooks/tests/test_remediation_flags.sh:58,76` (fixtures the lint must reject), `crates/cli/tests/wave_f_knowledge.rs:151` (`assert!(!stderr.contains("shepherd init"))`). |
| R05 | The new lint gate passes and is falsifiable three ways. | `bash hooks/tests/test_remediation_flags.sh` -> `PASS every remediation naming a gated subcommand carries its authorization flag (3 gated subcommand(s), 8 remediation mention(s) checked)` / `PASS falsification: the reintroduced v6.5.0 wording is detected` / `PASS gate-map drift: deriving zero gated subcommands fails loudly` / `3/3 passed`, exit 0. |
| R06 | `skills/shepherd/SKILL.md` gained `## Preconditions` at line 10. | `sed -n '10,21p' skills/shepherd/SKILL.md` -> `## Preconditions` … two command-shaped bullets naming `shepherd doctor` and `shepherd init --confirm`. |
| R07 | CHANGELOG carries the v6.5.1 entry. | `CHANGELOG.md:7` -> `## v6.5.1 — unreleased`, followed by three `### Fixed` blocks. |
| R08 | `1c39f4c` fixed the CI-caught pin. | `git show --stat --oneline 1c39f4c` -> `crates/cli/tests/wave_b1_status_handoff_cli.rs | 10 +++++++++-`. `sed -n '114p'` -> `// The remediation must be runnable as printed: \`init\` refuses without`. |

**R01–R08 verdict: the operator's account of the branch is accurate in every particular.**

---

## Section 2 — CI is RED right now, and the branch caused it

| ROW | Claim | Evidence |
|---|---|---|
| R09 | PR #328 is open, draft, `v6.5.1` -> `main`, MERGEABLE. | `gh pr view 328 --json ...` -> `{"baseRefName":"main","headRefName":"v6.5.1","isDraft":true,"mergeable":"MERGEABLE","number":328,"state":"OPEN","title":"release: v6.5.1"}`. |
| R10 | One check FAILS: `fmt + workspace invariants`. 21 other checks pass, including `test (windows-latest, default)` and `test (windows-latest, full)`. | `gh pr checks 328` -> `fmt + workspace invariants	fail	26s	.../job/95926879895`; every other row `pass`. |
| R11 | The failure is Codex-carrier projection drift caused by `cc07276`. | `gh run view 32205164985 --log-failed` -> `codex carrier is regular and canonical  FAILED` / `plugins/shepherd/codex/skills/shepherd/SKILL.md differs from skills/shepherd/SKILL.md` / `##[error]1 plugin contract violation(s).` |
| R12 | Reproduced locally, and the diff is exactly the `## Preconditions` block from R06. | `python3 scripts/check-plugin.py` -> same `FAILED` line. `diff skills/shepherd/SKILL.md plugins/shepherd/codex/skills/shepherd/SKILL.md` -> `10,21d9` removing precisely the 12 `## Preconditions` lines. |
| R13 | The projector exists and has a `--check` mode; it is invoked only from `scripts/gate.sh`, which nothing automated runs. | `scripts/gate.sh:92` -> `step "Codex regular carrier projection" python3 scripts/generate-codex-carrier.py --check`. `grep -rn "generate-codex-carrier" .github/` -> no hits. |

**R09–R13 verdict: the sprint's own first commit is the current CI red. It is a one-command
regeneration, and it is the gating item for everything else.**

---

## Section 3 — the through-line: gates that exist but are wired to nothing

| ROW | Claim | Evidence |
|---|---|---|
| R14 | `hooks/tests/run.sh` is invoked by **no** GitHub workflow and **no** git hook. | `grep -rn "hooks/tests" .github/` -> two hits, both prose inside `claude-review.yml:83` and `release.yml:548`, neither an invocation. `git config core.hooksPath` -> empty. `ls .git/hooks/ \| grep -v sample` -> empty. `.githooks/` contains only `commit-msg`, `open-sprint-pr`, `pre-push`. |
| R15 | `.githooks/pre-push` is deliberately inert. | `.githooks/pre-push` -> `printf 'pre-push: no local gate or PR automation ran; use scripts/gate.sh explicitly when needed.\n' >&2` / `exit 0`. |
| R16 | Consequence: 2 of 28 hook tests are red on clean HEAD and no build ever went red. | `bash hooks/tests/run.sh` -> `FAIL: hooks/tests/run.sh (28/28 tests ran, 2 failed)`. Failures: `test_native_cli_contract.sh`, `test_workflow_meta_gate.sh`. |
| R17 | The Rust suite is green, so the red is confined to the unwired shell tier. | `cargo test --workspace` -> 30 suites `ok`, 222 passed, 0 failed, exit 0. |

**R14–R17 verdict: this repo has a complete, well-written gate tier that no automated path
executes. That is the single cause behind R11, R18 and R21 simultaneously.**

---

## Section 4 — failing hook test #1: `test_native_cli_contract.sh`

| ROW | Claim | Evidence |
|---|---|---|
| R18 | The assertion fails with `allow` where it demands `unresolved`. | `bash hooks/tests/test_native_cli_contract.sh` -> `FAIL  native-workflow-script-only-unresolved-fail-closed: {"decision": "allow"}`; 14 of 15 assertions pass. |
| R19 | The assertion is at `hooks/tests/test_native_cli_contract.sh:82-88` and demands both `"decision": "unresolved"` and the substring `cannot determine the dispatch target role`. | `:82` payload `{"tool_name":"Workflow","role":"shepherd","tool_input":{"script":"const r = await agent(\"x\")"}}`; `:84-85` the two `grep -q` conditions. |
| R20 | Reproduced standalone. | `printf '<that payload>' \| cargo run -q -p shepherd-cli -- guard eval` -> `{"decision": "allow"}`, exit 0. |
| R21 | **Root cause: a deliberate carve-out added in v6.4.6, with the assertion left un-updated.** | `crates/core/src/guard/engine.rs:401` -> `if target.is_none() && tool_name != "Workflow" {`. `git blame` -> line 401 and the explaining comment at `:398-400` are `f3d44b0f` (2026-08-18, v6.4.6); the `Verdict::unresolved` body at `:402-404` is `ee682ecf` (2026-08-15, v6.4.5). `git log --oneline -3 -- hooks/tests/test_native_cli_contract.sh` -> `ee682ec v6.4.5 (#273)` — the test has not been touched since v6.4.5. |
| R22 | **The guard is NOT failing open in general.** A tier sweep proves it denies every restricted role and allows only root-tier roles. | Sweep over the same script-only payload: `shepherd` -> `allow`; `engineer` -> `allow`; `planter` -> `allow`; `conductor` -> `deny` `plan-authorship-and-gating-are-root-tier-exclusive` `WRONG-TIER-DISPATCH`; `coder` -> `deny` `implementer-roles-never-dispatch`; `auditor` -> `deny` `implementer-roles-never-dispatch`. |
| R23 | The allow arises from `restricted_by_target_rule(tier)` being false for root tier. | `crates/core/src/guard/engine.rs:424-430` — deny fires only when `target.is_none() && restricted_by_target_rule(tier)`; otherwise flow reaches the normal `decide` path. |
| R24 | Two written contracts contradict each other. | Test comment `hooks/tests/test_native_cli_contract.sh:77-81`: "a script-only payload is unresolved and the Claude adapter translates unresolved verdicts to a fail-closed denial". Implementation comment `crates/core/src/guard/engine.rs:398-400`: "`Workflow` fans out inside its own script, so its `tool_input` carries no single target role." |

**R18–R24 verdict: this is NOT a fail-open hole for restricted tiers. It is one un-reconciled
contract: v6.4.6 changed the Workflow semantics on purpose and the v6.4.5 assertion still
encodes the replaced rule. Which contract wins is a decision, not a repair — see seed §D.
The residual real question is whether `planter` -> `allow` is correct, given that the planter's
only sanctioned dispatch is `shepherd:discovery`. That connects R28 directly.**

---

## Section 5 — failing hook test #2: `test_workflow_meta_gate.sh`

| ROW | Claim | Evidence |
|---|---|---|
| R25 | The NEGATIVE control cannot run; 2 assertions fail. | `bash hooks/tests/test_workflow_meta_gate.sh` -> `FAIL  NEGATIVE control: could not recover 686084d:workflows/wave.js from git history`; `FAIL  2 workflow-meta-gate assertion(s) failed`. The POSITIVE control, the false-positive guard, and the DF-59 zero-files guard all PASS. |
| R26 | The dependency is a literal `git show` against a commit this clone does not contain. | `scripts/check-workflow-meta.sh:259` -> `if ! git -C "${ROOT}" show 686084d:workflows/wave.js >"${negative}" 2>/dev/null; then`. `git cat-file -t 686084d` -> `fatal: Not a valid object name 686084d`. `git rev-list --count HEAD` -> `93`. |
| R27 | The gate itself is sound; only its control is fragile. `scripts/check-workflow-meta.sh:242` documents the intent. | `:242` -> `#   NEGATIVE          — the real 686084d concatenated form must be REJECTED.` Normal-mode scan passes: test output line `PASS  normal-mode scan of the real workflows/*.js exits 0`. |

**R25–R27 verdict: a control that depends on git archaeology is unrunnable the moment history
is rewritten, transferred, or shallow-cloned — which already happened. The gate's logic is
proven correct by its three surviving controls; only the corpus needs to become in-repo.**

---

## Section 6 — issue #330, run-namespace resolution: CONFIRMED, and sharper than filed

| ROW | Claim | Evidence |
|---|---|---|
| R28 | The banner fires on every tool call in this very session. | Live PreToolUse additionalContext on each Bash/Agent call: `[shepherd] no usable run namespace (dispatch filesystem operation \`open regular file\` failed for /Users/jo3/src/pzzld/shepherd/.shepherd/runs/v500/run.json: No such file or directory (os error 2)); tool allowed.` |
| R29 | `v651` is correctly registered and claimed. | `.shepherd/runs/v651/run.json` -> `{"base":"main","branch":"v6.5.1","kind":"sprint","run":"v651","status":"planted",...}`; `dispatch/` and `lanes/` exist. |
| R30 | **HYPOTHESIS CONFIRMED: resolution scans the runs directory and never consults the claim.** | `crates/cli/src/dispatch_store.rs:235-273` `resolve_active_run`: `read_dir(&store.runs_root)` at `:239`, collect every name that parses as a `RunId`, `names.sort()` at `:258` (**lexical**), then `for run in names { read_run_document(store, &run)? }` at `:263-265`. The `?` propagates, so the first namespace lacking `run.json` aborts the entire resolution. `v500` sorts first. No registry, claim, or lock file is read anywhere in this function. |
| R31 | The same function is duplicated for the non-unix platform, with the identical defect. | `crates/cli/src/dispatch_store.rs:220` `#[cfg(unix)] mod platform`, `:865` `#[cfg(not(unix))] mod platform`; `grep -c "fn resolve_active_run"` -> `3`. Second copy at `:888-925`, same `read_dir` / `sort` / `?` shape at `:891`, `:911`, `:916`. |
| R32 | **This is structural, not a local artifact: every clone reproduces it.** All 8 tracked run namespaces ship without a `run.json`. | Detached worktree at `HEAD`: `v500`, `v512-dev0`, `v514`, `v516`, `v517`, `v641-dev0`, `v645`, `v646` — each `run.json NO`. |
| R33 | Cause of R32: `.gitignore` ignores `.shepherd/runs/**` and its 20-entry re-include allowlist omits `run.json`. | `.gitignore:35` -> `.shepherd/runs/**`; `:36-63` re-include `seed.md`, `mesh.md`, `plan.md`, `close.md`, `handoff.md`, `carry-forward.md`, `lanes/`, `reports/`, `audits/` … and no `run.json`. `git check-ignore -v .shepherd/runs/v651/run.json` -> `.gitignore:35`. |
| R34 | The second, independent gate is a status check the claimed run cannot satisfy. | `crates/cli/src/cmd/native_hook.rs:549-563` `run_namespace_is_usable` requires some run with `dispatch/` **and** `run.json["status"] == "executing"`. `v651` is `planted`, so this returns false even once R30 is fixed. |
| R35 | The banner is emitted by the hook, not by the read-only commands. Issue #330's framing is off by one layer. | `crates/cli/src/cmd/native_hook.rs:536-542` builds the string. It reaches the operator via `HookOutput::Context` on PreToolUse — it fires for `ls`, for `Agent`, for every tool, not only for `shepherd` subcommands. |
| R36 | **#330 MASKS #315 and #314: neither is currently observable.** | `printf '{"hook_event_name":"PreToolUse","session_id":"stranger-v651",...}' \| shepherd claude-hook` -> the v500 banner, **not** the unbound-session denial #315 describes. `printf '{"hook_event_name":"SessionStart","session_id":"replay-v651-probe"}' \| shepherd claude-hook`, run twice -> byte-identical v500 rejection both times, **not** the `dispatch record already exists` rejection #314 describes. |

| R36a | **The preemption reaches the lifecycle surface, not just tool calls. Observed twice in the wild during this very planting session.** | Session open, real harness `SubagentStart` payload -> `[shepherd] native lifecycle hook rejected: dispatch filesystem operation \`open regular file\` failed for …/runs/v500/run.json: No such file or directory (os error 2)`. Session close, real harness `Stop` payload -> byte-identical text. Synthetic minimal payloads do NOT reproduce it (`printf '{"hook_event_name":"Stop","session_id":"v651-probe"}' \| shepherd claude-hook` -> empty), because the binding lookup that reaches `resolve_active_run` only runs when the envelope carries a dispatch binding. Synthetic sweep with a tool-shaped payload: `PreToolUse`, `PostToolUse`, `SessionStart` -> PREEMPTED; `Stop`, `SubagentStop`, `SubagentStart`, `SessionEnd`, `UserPromptSubmit`, `PreCompact`, `Notification` -> clean at that payload shape only. |
| R36b | **On `SubagentStop` this same error is a HARD BLOCK, not an advisory banner.** | `crates/cli/src/cmd/native_hook.rs:147-153` -> `Err(error) if hook_event_name == "SubagentStop" => emit_json(&block(&format!("native lifecycle hook rejected: {}", cli_error_detail(&error))), host)`. Every other event falls to `:154-163`, which emits advisory `context`. Demonstrated shape: `printf '{"hook_event_name":"SubagentStop","session_id":"v651-probe"}' \| shepherd claude-hook` -> `{"decision":"block","reason":"[shepherd] native lifecycle hook rejected: missing dispatch binding"}`. The `v500` read failure is the same `Err` value on the same branch, so a stale directory that is not a run can hard-block subagent completion. |

| R36c | **Minimal reproduction, in a clean sandbox: ONE stale directory containing only `plan.md` is sufficient.** | `git init` a scratch repo, `shepherd init --confirm`, `mkdir -p .shepherd/runs/v500 && echo '# legacy' > .shepherd/runs/v500/plan.md`, create one real run -> a PreToolUse envelope yields `[shepherd] no usable run namespace (… /runs/v500/run.json: No such file or directory (os error 2)); tool allowed.` No registry corruption and no history required. |
| R36d | **THE HOOK'S OWN PRINTED REMEDIATION MAKES IT STRICTLY WORSE: advisory banner becomes a hard `deny`.** | In the R36c sandbox, running the two commands the banner prints, verbatim: `shepherd run layout v651 --repair` -> `lanes/ ok / dispatch/ ok`, exit 0; `shepherd run set v651 --status executing` -> `updated v651`, exit 0. The next PreToolUse envelope returns `{"permissionDecision":"deny","permissionDecisionReason":"[shepherd] dispatch filesystem operation \`open regular file\` failed for …/runs/v500/run.json: No such file or directory (os error 2)"}`. Before the remediation the same envelope was `additionalContext` with the tool ALLOWED. `v500` never gains a `run.json`, so the underlying failure is untouched — only its severity changes. |
| R36e | Mechanism, falsified by toggling one field. | `crates/cli/src/cmd/native_hook.rs:532-535` -> `if run_namespace_is_usable(&context.runs_root) { return HookOutput::Deny { detail: error.to_string() } }`; `run_namespace_is_usable` at `:549-563` requires some run with `dispatch/` **and** `status == "executing"`. The printed step 1 creates `dispatch/`; step 2 sets the status; together they flip the predicate true and route the same unchanged error to the deny arm. Toggle proof: `status=executing -> deny`, `status=planted -> (advisory context)`, `status=executing -> deny`, reproducible on demand. |
| R36f | **This is the same defect family that opened this branch, one degree worse.** | `cc07276` fixed remediations naming a command that refuses to run (exit 2). This remediation *runs*, exits 0 twice, reports success — and bricks the session. `hooks/scripts/remediation_flag_lint.py` derives gated-subcommand flags from refusal text (R05); it cannot detect a remediation that is runnable and wrong. The gate the branch just built does not cover this case. |
| R36g | **#315 is unmasked by the R36c sandbox and is now MEASURED, upgrading R47.** | With `status=executing` and the stale directory removed, the same envelope denies with `[shepherd] dispatch filesystem operation \`open regular file\` failed for …/runs/v651/dispatch/.root-session.p.json: No such file or directory (os error 2)`. That is the unbound-session denial #315 describes — correctly fail-closed, and its reason is a bare errno naming an internal dispatch file. The sandbox recipe is therefore the sprint's reproduction harness for #315 as well. |

| R36h | **The correct post-fix message already exists in the codebase; the fix only has to reach it.** | `crates/cli/src/dispatch_store.rs:39` -> `#[error("no executing shepherd run exists")]`, the `DispatchStoreError::NoActiveRun` variant returned at `:270` / `:922`. Demonstrated by giving the stale directory a stub `run.json`: the banner changes from `dispatch filesystem operation \`open regular file\` failed for …/v500/run.json: No such file or directory (os error 2)` to `no usable run namespace (no executing shepherd run exists); tool allowed.` Skipping a directory that is not a run therefore needs no new error type and no new string — it lets the existing `NoActiveRun` path be reached instead of being preempted by the `?`. |
| R36i | Verified safe local mitigation, for use until the fix lands. A stub `run.json` in each legacy namespace keeps the decision at ALLOW and makes the message truthful. `run.json` is git-ignored (`.gitignore:35`, R33), so it does not enter the repo. **Do not run the remediation the banner prints** (R36d). | Sandbox probe: baseline -> `ALLOW(advisory)` with the errno text; stub added -> `ALLOW(advisory)` with `no executing shepherd run exists`. Neither state denies. |

**R28–R36i verdict: confirmed with a correction and three escalations. The correction: the defect
is not "read-only commands warn", it is "the hook's dispatch resolution aborts on the first
directory that is not a run". The escalations: (a) it reproduces on every clone because
`run.json` is git-ignored while the namespace directories are tracked; (b) it preempts the
lifecycle path entirely, so #314 and #315 cannot be measured until it is fixed — a hard
ordering constraint on the sprint; (c) on `SubagentStop` it is a blocking decision, so this is
not a cosmetic banner defect. It was observed rejecting both the `SubagentStart` that opened
this planting session and the `Stop` that closed it (R36a, R36b).**

**R36c–R36g are the sharpest result of this planting and they change the sprint's priority
order. The banner is not the defect; it is the symptom of an abort, and the repair text the
abort prints converts an allowed session into a denied one (R36d, R36e). An operator who does
what shepherd tells them ends up worse off than one who ignores it. The `--confirm` lint this
branch shipped cannot catch it, because the command is runnable — it is simply wrong (R36f).
Any fix for #330 that does not also correct or remove that remediation string leaves the
harmful instruction in place.**

---

## Section 7 — issue #331 and the errno family

| ROW | Claim | Evidence |
|---|---|---|
| R37 | Reproduced verbatim, exit 5. | `shepherd ready --run dummy` -> `ERROR: open state directory /Users/jo3/src/pzzld/shepherd/.shepherd/runs/dummy: No such file or directory (os error 2)`, `EXIT=5`. |
| R38 | **The fix generalizes: 16 sites share two helpers in one file.** | `crates/cli/src/run_store.rs:463` -> `.map_err(\|error\| errno(store, "open state directory", error))?`; `:465` -> `Err(error) => return Err(errno_path("open state directory", seen, error))`. `grep -c "errno("` -> 13, `grep -c "errno_path("` -> 3, all in `crates/cli/src/run_store.rs`. |
| R39 | Same defect family as the just-fixed `--confirm` bug: a message that names no action the operator can take. | `shepherd ready --run dummy` names a path, not the fact that `dummy` is not a run, nor `shepherd run list` as the way to find one. Compare the corrected shape at `crates/cli/src/cmd/dispatch.rs:185`. |
| R40 | Issue #315 is the same shape one layer out, and #306 is the same shape again. | #315 body: `PreToolUse` denial reason "is a filesystem error". #306 body: `[shepherd] native lifecycle hook rejected: cannot open project identity …/.shepherd/project.json without following symlinks: No such file or directory (os error 2)`. |

**R37–R40 verdict: one helper pair in one file governs 16 call sites. The operator's instinct
that the fix generalizes is correct and measurable.**

---

## Section 8 — the remaining triage candidates, each measured

| ROW | Issue | Measured result |
|---|---|---|
| R41 | #323 | **CONFIRMED, and worse than filed.** Sweep of `Agent` dispatch from `role: conductor` with a declared target: `-> planter` **allow**, `-> shepherd` **allow**, `-> conductor` allow, `-> coder` allow, `-> engineer` deny, `-> critic` deny. A lane lead can dispatch the root orchestrator and the planter that solely holds `ask-operator`. `content/predicates/dispatch-scope.toml` is the rule source; `crates/compiler/package-content/content/predicates/dispatch-scope.toml` is its generated projection. |
| R42 | #324 | **CONFIRMED.** `shepherd models resolve shepherd --harness claude` -> `ERROR: unknown role: shepherd (valid: root planter engineer conductor critic discovery coder auditor worker)`, exit 2. Control: `models resolve conductor --harness claude` -> `inherit`, exit 0. Emitted at `crates/cli/src/cmd/wave_a_models.rs:182`. **The split is real:** the guard engine accepts `role: "shepherd"` (R22 returned a verdict, not `unknown role`), so two surfaces disagree on the root role's name. |
| R43 | #319 | **CONFIRMED live, and this seed is the experiment.** `shepherd seed verify .shepherd/runs/v646/seed.md` -> `HARD footprint 393 lines > cap 200 (kind=patch-seed)` / `HARD file_scope path does not resolve and is not marked (NEW): bin` / `FAIL: 2 hard failure(s)`, exit 1. Note the second failure is self-inflicted by design: v646 decision D4 deleted `bin/`, so a shipped seed is now unverifiable against the tree it produced. Caps: `crates/cli/src/cmd/wave_b2_seed.rs:13-14` -> `SPRINT_FOOTPRINT_CAP = 400`, `PATCH_FOOTPRINT_CAP = 200`. |
| R44 | #318 | **CONFIRMED and undercounted.** The issue reports 52 from `scripts/` only. `grep -rn 'rg -Fq' hooks/ scripts/ \| wc -l` -> **118**. Example `scripts/tests/test-release-installer-powershell-contract.sh:15-17`, three consecutive bare assertions with no message. |
| R45 | #316 | **CONFIRMED structurally.** `git ls-files .shepherd/ctx` -> 0 files; `ls -la .shepherd/ctx/` -> empty. Detached worktree at `HEAD`: `.shepherd/ctx` **ABSENT**. `.gitignore:85` re-includes `**/.shepherd/.gitkeep` but there is no `.shepherd/ctx/.gitkeep`. Local `shepherd doctor` -> `status: ok` only because this working copy is the registered primary and `init` created the directory. |
| R46 | #314 | **UNMEASURABLE TODAY** — preempted by #330 (R36). The filed behaviour is plausible and the issue body quotes `dispatch record already exists`, but it cannot be reproduced on this branch until R30 is fixed. |
| R47 | #315 | **UNMEASURABLE TODAY** — preempted by #330 (R36). Same reasoning; the code shape at `crates/cli/src/cmd/native_hook.rs` and the `run_store.rs` errno helpers (R38) make it the same family as #331. |
| R48 | #320 | Not reproduced this pass. The rule source is `content/predicates/write-boundary.toml`; the asymmetry claim is that `Write` to an absolute out-of-repo path denies while `Bash` performing the identical write allows. Reproduction is a two-payload `guard eval` diff and belongs in the sprint's own W0 gate, not in a seed assertion. |
| R49 | #317 | **CONFIRMED.** `~/.cargo/bin/shepherd --version` -> `shepherd-cli 6.5.0`. `.claude-plugin/plugin.json` -> `6.5.1`. Installed marketplace copy `~/.claude/plugins/marketplaces/shepherd/.claude-plugin/plugin.json` -> `6.5.0`. `git grep -rn "shepherd --version" hooks/ scripts/` -> **no version-lag guard exists anywhere.** |
| R50 | #307 | Refers to a resolution path absent from this tree: `git grep -n "\.local/target"` -> **no hits**. Same distribution family as #317. |
| R51 | #306 | Filed against a different project (`~/Documents/vaults/pzzld`). `crates/cli/src/cmd/native_hook.rs:521-531` now converts a never-recorded agent to `HookOutput::Context` (allow), which is the shape #306 asked for. Needs re-measurement after R30, not a fresh fix. |

---

## Section 9 — version and publish drift

| ROW | Claim | Evidence |
|---|---|---|
| R52 | The repo declares 6.5.1 uniformly across all five npm manifests. | `package.json` -> `@pzzld/shepherd-workspace 6.5.1`; `packages/component-runtime/package.json` -> `6.5.1`; `packages/harness-claude/package.json` -> `@pzzld/pi-claude 6.5.1`; `packages/harness-codex/package.json` -> `@pzzld/pi-codex 6.5.1`; `packages/harness-pi/package.json` -> `@pzzld/pi-shepherd 6.5.1`. |
| R53 | **All four published npm packages are stuck at 6.4.5 — three harness packages are unpublishable, not one.** | `npm view` -> `@pzzld/pi-claude 6.4.5`, `@pzzld/pi-codex 6.4.5`, `@pzzld/pi-shepherd 6.4.5`, `@pzzld/component-runtime 6.4.5`. |
| R54 | Each harness package pins the exact unpublished runtime version. | `packages/harness-claude/package.json:10`, `packages/harness-codex/package.json:10`, `packages/harness-pi/package.json:10` -> `"@pzzld/component-runtime": "6.5.1"`. |
| R55 | Three intermediate releases never reached npm. | Published `6.4.5` vs tags through `6.5.0`; `git log --oneline` shows `f3d44b0 v6.4.6`, `f089c81 v6.4.7`, `dc5f047 v6.4.8`, `75d2323 v6.4.9`, `4a02a88 v6.5.0` all merged. |
| R56 | The Rust binary on PATH is one minor behind the manifest. | `~/.cargo/bin/shepherd --version` -> `shepherd-cli 6.5.0` against `.claude-plugin/plugin.json` `6.5.1`. |

**R52–R56 verdict: the operator's account is correct and understates the blast radius —
`component-runtime@6.5.1` gates three packages, not one. No gate anywhere detects the lag
(R49), which is why it survived three releases.**

---

## Section 10 — the seed gate contract, read from source

Read at `crates/cli/src/cmd/wave_b2_seed.rs` so this run's own seed can be authored to pass.

| ROW | Rule | Source |
|---|---|---|
| R57 | HARD: footprint over cap. `patch-seed` -> 200, anything else -> 400. Warn at 3/4 cap. | `:13-14`, `:152-168`. |
| R58 | HARD: a `TODO:` or `FIXME:` word-boundary marker. | `:170-172`, `contains_word_marker` at `:261`. |
| R59 | HARD: prescriptive `Lane` + whitespace + digit. Case-sensitive; the bare word `Lane` is fine. | `:173-177`, `contains_lane_number` at `:270`. |
| R60 | HARD: a `file_scope:` entry that does not resolve on disk and carries none of the 7 NEW markers. | `:186-196`, `NEW_MARKERS` at `:17`, `resolves` at `:396`. Repo root from `git rev-parse --show-toplevel` at `:416`. |
| R61 | HARD: a `### ` block carrying `**Priority:**` or a `[CRITICAL\|HIGH\|MEDIUM\|LOW]` tag but no `**GH:**`. | `:207-217`, `deliverable_blocks` at `:441`. |
| R62 | Warnings only (exit stays 0): `Sequencing:`, semver-content judgment, fewer than 8 mesh rows, no CRITICAL/HIGH, missing `milestone:`, missing `kind:`. | `:178-185`, `:219-234`, `MIN_MESH_ROWS = 8` at `:12`. |
| R63 | A "mesh row" is a table line whose first cell is pure digits. `\| R01 \|` does not count. | `is_mesh_row` at `:485`. |
| R63a | **This seed is the #319 experiment and its result is a data point.** `shepherd seed verify .shepherd/runs/v651/seed.md` -> `warn  footprint 388 lines > smell threshold 300` / `OK: 0 hard failures, 1 warning(s)`, exit 0. A 13-deliverable repair sprint authored against the gate read from source saturates the 400-line `sprint-seed` cap at 97%, leaving 12 lines. It reached 401 — a HARD failure — mid-authoring and had to be compressed twice: §F's topology table was deleted as a duplicate of this mesh's R64–R71, and four prose sections were tightened. The cap is not merely mis-tiered for `patch-seed` (R43); it is binding for a real `sprint-seed` and it pressures the author to delete evidence pointers to stay under it. Warnings are non-blocking by design (`crates/cli/src/cmd/wave_b2_seed.rs` USAGE at `:15` -> "Exit 1 on >=1 HARD failure … 0 otherwise (warnings allowed)"). |

---

## Section 11 — scope-partition disjointness check

Every path proposed for the seed's `file_scope` was resolved at mesh time; `shepherd seed
verify` re-checks this independently (R60). Ownership below is stated so that no two
partitions name the same file.

| ROW | Partition | Exclusive files |
|---|---|---|
| R64 | carrier | `plugins/shepherd/codex`, `scripts/generate-codex-carrier.py` |
| R65 | resolution | `crates/cli/src/dispatch_store.rs`, `crates/cli/tests/dispatch_store.rs` |
| R66 | diagnostics | `crates/cli/src/run_store.rs`, `crates/cli/src/cmd/native_hook.rs`, `crates/cli/tests/claude_hook_cli.rs` |
| R67 | dispatch-scope | `content/predicates/dispatch-scope.toml`, `content/predicates/write-boundary.toml`, `crates/core/src/guard/engine.rs`, `crates/core/tests/guard.rs`, `hooks/tests/test_native_cli_contract.sh` |
| R68 | vocabulary | `crates/cli/src/cmd/wave_a_models.rs`, `crates/cli/tests/wave_a_models_cli.rs`, `crates/cli/src/cmd/wave_b2_seed.rs`, `crates/cli/tests/wave_b2_seed_cli.rs` |
| R69 | gate-wiring | `.github/workflows/rust.yml`, `scripts/check-workflow-meta.sh`, `hooks/tests/test_workflow_meta_gate.sh`, `hooks/tests/fixtures` (NEW), `hooks/tests/lib` (NEW) |
| R70 | clone-fidelity | `.gitignore`, `.shepherd/ctx/.gitkeep` (NEW), `crates/cli/src/cmd/wave_c_bootstrap.rs`, `scripts/check-version-lag.py` (NEW) |
| R71 | No file appears in two partitions. `CHANGELOG.md` is additive and shared by convention; it is the only shared path. | Verified by inspection of R64–R70. |

---

## Section 12 — signals swept and found empty

| ROW | Source | Result |
|---|---|---|
| R72 | Prior close report | `.shepherd/runs/v646/close.md` exists (8134 bytes) and is the most recent close. `.shepherd/runs/v651/` had no `seed.md`, `mesh.md`, or `plan.md` before this run. |
| R73 | Carry-forward ledger | `.shepherd/runs/v646/carry-forward.md` exists (33623 bytes). `.shepherd/runs/v645/carry-forward.md` also present. |
| R74 | Adaptation store | `.shepherd/` contains `ctx/` (empty), `docs/`, `runs/`, `project.json`, `shepherd.db`, `shepherd.toml`. No standalone lessons or adaptation markdown file. |
| R75 | Open issue roster | `gh issue list --state open --limit 200 --json number --jq 'length'` -> **50** open (the issue-body text of #318 and the task brief both say 52; 50 is the measured count). The 20 named in the task plus 30 older ones, the largest cluster being #284–#298 (SQL-injection and guard defects in retired shell surfaces). |
| R76 | Milestone | **Milestone 61 `v6.5.1` EXISTS** — `gh api repos/:owner/:repo/milestones --paginate` -> `61 v6.5.1 open=0 closed=0`. It is empty, and `gh pr view 328 --json milestone` -> null. Contrast milestone `60 v6.4.6 open=2 closed=1`. |

**R76 correction: an earlier draft of this row asserted the milestone was missing, repeating
the v646 seed's finding. That was wrong — `gitflow.yml` did create it this time. The real gap
is narrower: the milestone exists, PR #328 is not attached to it, and no triaged issue is
filed under it. Recorded as a LOW deliverable, not as a workflow failure.**
