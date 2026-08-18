# v6.4.6 harness lane plan (seed deliverable 5, HIGH)

Branch v6.4.6. Lane scope: `hooks/**`, `plugins/shepherd/**`, `packages/harness-pi/**`,
`packages/harness-claude/**`, `packages/harness-codex/**`, `.shepherd/runs/v646/**`, plus
two named `content/roles/*.md` sentences (Prohibitions body prose only, never
`model:`/tier/`model_hint` fields). Forbidden: `crates/**`, `scripts/**`, `.github/**`,
`packages/component-runtime/**`, `content/skills/**`, `content/predicates/**`,
`conformance/**`.

## 1. Objective and acceptance

Every harness defines every hook; Codex and Pi are first-class, not derived. Acceptance
is a GENERATED event x harness x implementation table at
`.shepherd/runs/v646/harness-parity.md` with no blank cell that is not a documented
harness limitation, produced by a script (not typed by hand) and attached to the close
report by gate HARNESS-PARITY.

## 2. Measured baseline (MEASURED, cited, not re-verified)

- `bash scripts/gate.sh` -> exit 0, "gate (full): green in 40s". Log
  `/tmp/v646-harness-gate-baseline.log`. Must stay green through every wave.
- `hooks/tests/run.sh` currently skips 18 tests. Re-run direct: 17 PASS,
  `test_lead_workflow_tool.sh` FAILs solely on `lint_agent_capabilities.sh`'s 5
  violations (called at line 60, and via `SHEPHERD_LINT_AGENTS_DIR` at line 83).
- `hooks/scripts/conductor_write_guard.sh` does not exist, deleted in v6.4.5.
- `git show ffd9aea -- hooks/hooks.json` deleted 6 registration blocks / 7 script hooks:
  PreToolUse matcher `Write` -> `seed_preflight_check.sh`; SubagentStop ->
  `subagent_telemetry.sh`; PostToolUse matcher `Bash` -> `bash_post.sh`; PostToolUse
  matcher `Agent|Task` -> `agent_insight_capture.sh` + `discovery_capture.sh`;
  CwdChanged -> `cwd_changed.sh`; PreCompact -> `precompact_snapshot.sh`.
- `crates/core/src/dispatch/portable.rs:32-71` types `NativeEvent`: SessionStart,
  SubagentStart, SubagentResume, SubagentStop, PreToolUse, PostToolUse,
  `Other(String)`. Line 794: `Other(_) => DispatchPlan::Ignored`. `CwdChanged` and
  `PreCompact` registered at a native command are inert no-ops. Never register them
  natively.
- `crates/cli/src/cmd/native_hook.rs` refuses Codex SubagentStart/SubagentStop;
  `crates/cli/tests/codex_hook_cli.rs:223,257` pin it.
- `shepherd seed verify .shepherd/runs/v646/seed.md` -> HARD footprint 393 lines >
  cap 200 (kind=patch-seed), 1 hard failure. Do not tune the cap or edit the seed.
- `packages/harness-pi/src/extension.mjs` already binds identity
  (`pi.on("session_start")`) and guards write/edit/bash (`pi.on("tool_call")`,
  fail-closed on every path), plus a `pi.on("session_shutdown")` no-op. Pi lacks the
  manifest, not the enforcement.
- `python3 hooks/scripts/hook_authority_inventory.py --self-test` -> "self-test
  passed", exit 0.
- `7d5492e`: Claude `SubagentStart` now synthesizes a dispatch binding from what the
  host actually sends (agent id, type, model) instead of requiring a
  `shepherd_dispatch` block no host attaches. Dispatch records ARE now written.
  Measured in a clean fixture: conductor and coder both recorded; conductor may
  dispatch a coder; conductor REFUSED dispatching an engineer (wrong tier); coder
  REFUSED dispatching anything. Do not write "records nothing" as a Claude limitation.
- The honest Claude limitation for the table: write scope is recorded as `**` because
  no host declares one. Identity binding and role enforcement work on Claude;
  write-scope narrowing does not. Cite `crates/cli/src/cmd/native_hook.rs`.
- `587fcfa`: an agent shepherd never recorded is allowed with a diagnostic rather than
  denied, so pre-ledger agents keep working (a separate, already-landed fact; not the
  drift base commit, see below).
- **Drift base commit is `1f2a398`, not `587fcfa`.** Since `b992ec6` the root has
  committed only `CHANGELOG.md` and one test file, neither in lane scope. Use
  `git diff --stat 1f2a398..HEAD -- <scope>` for every drift check in this plan.
- **Role-file ownership confirmed MEASURED, file-level disjoint.** The config lane
  owns `content/roles/conductor.md` (`model_hint` frontmatter only) and
  `content/roles/shepherd.md`. This lane owns `content/roles/engineer.md` and
  `content/roles/planter.md` (Prohibitions body prose only). Neither lane can clobber
  the other even by accident.
- **`agents/` is not this lane's to write.** The root session owns regeneration at
  integration time. This lane edits `content/roles/` only and verifies with
  `SHEPHERD_LINT_AGENTS_DIR` pointed at a scratch tree, never touching tracked
  `agents/`.

### Recon done for THIS plan (file-path confirmation only, not new ground truth)

- `hooks/hooks.json:16` already registers `PreToolUse` matcher
  `"Write|Edit|Bash|Agent|Workflow"` -> `shepherd claude-hook`, already covering both
  `Write` and `Edit`. D5(a) below is already satisfied by this existing block; D5's
  fix is a single-file change to the lint.
- `hooks/tests/lint_agent_capabilities.sh` (~line 124) reads:
  `if ! grep -q "conductor_write_guard.sh" "$HOOKS_JSON"; then note "FAIL conductor: ..."`
  -- the exact line D5 re-points.
- `hooks/scripts/hook_authority_inventory.py`: `METADATA` has exactly 1 entry today
  (`crates/cli/src/cmd/claude_hook.rs`, THIN). `registrations()` recognizes the native
  `shepherd claude-hook` command and maps it to that synthetic target; `TARGET_RE`
  separately matches `hooks/scripts/*` and `packages/harness-claude/hooks/*` command
  paths for script-based registrations. `self_test()` (lines 179-255) builds a fixture
  with `thin.sh`/`telemetry.sh`/a legacy-agent entry; its `required` set (~line 237)
  does not include `"missing inventory metadata"` -- confirms D4's gap.
- `packages/harness-pi/shepherd.pi.json` already exists (contract/adapter/provider/
  component/transitions keys, no hook-event data). D8 EXTENDS this file with a new
  `hooks` block, it does not create a new file. Anchors in
  `packages/harness-pi/src/extension.mjs`: `:19` `GUARDED_TOOL_NAMES = new Set(["write",
  "edit","bash"])`, `:31` `pi.on("session_start")`, `:59` `pi.on("tool_call")`, `:58`
  `pi.on("session_shutdown")`.
- `packages/harness-claude/hooks/hooks.json` and `packages/harness-codex/hooks/hooks.json`
  already exist, event-keyed (`SessionStart`, `PreToolUse`, `SubagentStart`,
  `SubagentStop`), JS-shim based (`dispatch-lifecycle.mjs`, `guard-eval.mjs`,
  `shepherd_guard.mjs`). These are the other two of D9's three manifests; no new files
  needed for Claude or Codex, only Pi (D8).
- `packages/harness-codex/hooks/hooks.json` currently DOES register `SubagentStart`
  and `SubagentStop`, forwarding through `shepherd_guard.mjs` into the native refusal
  path. Per `native_hook.rs` this refusal for `SubagentStart` emits a non-blocking
  `additionalContext` warning (tool call proceeds); for `SubagentStop` it emits
  `block()` (a deny decision in the hook output, exit 0, per
  `codex_hook_cli.rs:223,257`). Read D1 as "no trusted-correlation support is ever
  built" (already true, already tested), not "delete this registration" -- no file
  edit is required for D1 itself. Flagged in Escalations for root-session confirmation
  because the phrase "stay unregistered" and the observed registered-but-refused state
  could be read two ways.

## 3. Decisions (ratified, recorded with forcing evidence)

**D1. Codex SubagentStart/Stop take the "unsupported" table state, no correlation
built.** Codex exposes no trusted spawn-to-child correlation; building it would mint
shadow identities, which `crates/cli/tests/dispatch_cli.rs:199` exists to prevent.
`native_hook.rs` routes a SubagentStop error to `block()`; fabricating correlation to
avoid that would be worse than the honest gap. Table cells:
`unsupported: no trusted spawn-to-child correlation (crates/cli/src/cmd/native_hook.rs)`.
No file edit. v6.4.7 item for a real fix.

**D2. Re-register the six telemetry scripts, do not retire them.** Blanket retirement
deletes four behaviours with no native successor: SEED-GATE authorship floor, #59
gates-ran ledger, discovery-report indexing, precompact cursor snapshot.
`hook_authority_inventory.py` defines `THIN`, `TELEMETRY`, `ALLOWED = {THIN, TELEMETRY}`
plus a `TELEMETRY_POLICY` regex tuple that mechanically fails any telemetry hook
emitting `emit_deny`/`permissionDecision` or a mutating sqlite statement. The category
was never removed. Register `bash_post.sh`, `agent_insight_capture.sh`,
`discovery_capture.sh`, `cwd_changed.sh`, `precompact_snapshot.sh`,
`subagent_telemetry.sh` on their original events (see baseline `ffd9aea` list), each
added to `METADATA` as `classification: TELEMETRY`.

**D3. `seed_preflight_check.sh` classified THIN.** It emits
`permissionDecision: deny`, so telemetry classification would wrongly reject it, but
the verdict is computed by `shepherd seed verify`; the script only transports it.
`METADATA`: `classification: THIN`, `native_surface: ["shepherd seed verify"]`.
Register on PreToolUse matcher `Write`. Live consequence: this makes SEED-GATE real,
and `.shepherd/runs/v646/seed.md` HARD-fails it today (393 vs 200 cap). That is the
gate working correctly on a seed marked ready-for-engineer without ever passing it.
Do not tune the cap, add an exemption, or edit the seed. v6.4.7 item.

**D4. Three tests updated together**, each still pinning an exact reviewed set:
- `test_registered_hooks_no_python.sh`: reframe from "command set is exactly
  `{("shepherd",("claude-hook",))}`" to the test's own stated purpose: no registered
  hook resolves policy through shell or node; every non-native registration is
  classified telemetry-only or THIN.
- `test_registered_hook_authority.sh`: `len(entries) == 1` -> `len(entries) == 8`
  (1 pre-existing native + 6 telemetry + 1 THIN from D2/D3); counts string
  `'1 thin, 0 telemetry, ...'` -> `'2 thin, 6 telemetry, 0 independent, 0 nondeterministic'`.
- `test_legacy_policy_retirement.sh`: its `retired=()` / length-4 conductor-era set
  stays (that batch is genuinely gone, D5 fixes the stale reader, not this list);
  update its own copy of the counts string to match the new
  `2 thin, 6 telemetry, ...` shape.
HARD CONDITION: `test_registered_hooks_no_python.sh` must be SHOWN TO FAIL two ways,
both recorded: (1) a telemetry-classified hook emitting `permissionDecision` turns it
red; (2) an unclassified shell registration turns it red. If either cannot fail,
ABANDON D2/D3, retire all seven, document the four losses (SEED-GATE authorship
floor, #59 gates-ran ledger, discovery-report indexing, precompact cursor snapshot).
Condition (1) is already live: `self_test()`'s TELEMETRY fixture contains `emit_deny`
+ a mutating sqlite UPDATE and requires `telemetry_policy_authority`;
`--self-test` passes today. Condition (2) is mechanized (`audit()` emits
`missing inventory metadata`, `registrations()` raises on an unmatched target) but not
covered by `self_test()`'s `required` set. Required step: extend the fixture with a
third registration pointing at an unclassified `hooks/scripts/unclassified.sh` absent
from fixture `METADATA`, add `"missing inventory metadata"` to `required`, prove it
fails on purpose (temporarily add that target to `METADATA`, show
`--self-test` reports `self-test failed to detect: missing inventory metadata` and
exits 1), then remove the temporary addition so the fixture stays honest.
`hook_authority_inventory.py` needs no structural change beyond `METADATA`;
`TARGET_RE` and the fixture registration format already fit. `main()` takes `--root`,
so fail-on-purpose proofs use a temp fixture, never a mutated tracked file.

**D5. The conductor lint assertion is re-pointed, forced by a proven contradiction.**
`test_legacy_policy_retirement.sh` asserts `conductor_write_guard.sh` is BOTH
unregistered AND source-deleted. `lint_agent_capabilities.sh:~124` asserts the
opposite (greps `hooks.json` for the literal string `conductor_write_guard.sh` and
FAILs when absent). Satisfying the lint literally turns a currently-green shipped
gate red. That proves the lint line is stale. Replacement, at least as strong: (a)
`hooks/hooks.json:16` already registers a PreToolUse hook whose matcher covers both
`Write` and `Edit` (`"Write|Edit|Bash|Agent|Workflow"` -> `shepherd claude-hook`), so
the lint's new check greps for that matcher instead of the deleted script name; (b)
the existing conductor loop banning Edit/Write/NotebookEdit/MultiEdit grants stays
untouched; (c) the native authority exists at `content/predicates/write-boundary.toml`
(`role-write-eligibility`, `path-in-declared-scope`), cited READ-ONLY, never edited
(forbidden path). Trap: `content/roles/conductor.md` declares `write_eligible: true`
with a documented exception; keying the check on `write_eligible: false` is wrong.
Key it on absence of a write TOOL grant plus presence of the PreToolUse `Write|Edit`
matcher. Forbidden: deleting the lint, deleting the assertion, or making it
unconditionally pass.

**D6. The 4 scope-bound lint violations.** Exact sites, Prohibitions body prose only:
- `content/roles/engineer.md`: "in self-contained mode dispatches only its own
  read-only research pass plus the `critic` gate" -> name `shepherd:discovery`,
  `shepherd:auditor`, `shepherd:critic`.
- `content/roles/planter.md`: "this role's only permitted dispatch is a bounded,
  read-only research pass" -> name `shepherd:discovery`.
Both already describe this in prose; they never use the carrier-form token the lint
greps. Config lane owns `conductor.md`/`shepherd.md`; this split is file-disjoint and
confirmed MEASURED. Do not regenerate `agents/`; verify per the baseline note above.

**D7. PostToolUse stays shell telemetry, not native.** The root session fixed native
PostToolUse (`aa6dc98`) so it no longer consults the pre-flight guard, and `deny()`
takes the event name; but a native PostToolUse registration now has no observable
effect (resolves identity, emits nothing). The shell hooks registered there in D2
(`bash_post.sh`, `agent_insight_capture.sh`, `discovery_capture.sh`) produce real
artifacts (#59 ledger, `## INSIGHTS`, discovery records) and earn the slot. No
separate file work beyond D2's registration; this is the justification for it.

**D8. Pi gets a real hook manifest.** Extend the existing
`packages/harness-pi/shepherd.pi.json` with a new `hooks` block (mirrors the
event-keyed shape already used in `packages/harness-claude/hooks/hooks.json`, adapted
to Pi's JS event names): `session_start` -> SessionStart identity bind,
`tool_call` -> PreToolUse guard over write/edit/bash, `session_shutdown` -> no-op.
Each entry cites the `pi.on(...)` call and behavior in `src/extension.mjs` it
represents (anchors above: `:31`, `:59`, `:58`, guard set at `:19`). Required
companion: a test asserting the manifest and `extension.mjs` cannot drift apart (the
manifest claims an event or a guarded tool; the file must still register a matching
`pi.on()` handler / `GUARDED_TOOL_NAMES` entry, and vice versa).

**D9. Parity generator.** Bash-3.2-safe shell at `hooks/scripts/generate_harness_parity.sh`
(alongside `hook_authority_inventory.py` and the other operational scripts already in
`hooks/scripts/`, subject to the same `test_exec_bits.sh` gate as every other script
there; no new top-level `hooks/` subdirectory). No new Python. Reads the three JSON
manifests (`hooks/hooks.json` + `packages/harness-claude/hooks/hooks.json` for Claude,
`packages/harness-codex/hooks/hooks.json` for Codex, `packages/harness-pi/shepherd.pi.json`
for Pi) plus `python3 hooks/scripts/hook_authority_inventory.py --json` for
classification, and emits `.shepherd/runs/v646/harness-parity.md`. Own test, shown to
fail on purpose (stale/missing table vs. regenerated table differ). Wired into
`hooks/tests/run.sh` as a regenerate-and-diff drift check.
The table uses THREE states, not two, this is required, it is what makes the artifact
honest:
  - implemented and effective
  - registered but inert, with reason and citation
  - unsupported harness limitation, with reason and citation
Codex SubagentStart/Stop take the third (D1). Claude write-scope narrowing takes the
third (`**` recorded, cite `native_hook.rs`). Claude SubagentStart is now the FIRST
state after `7d5492e`. CwdChanged/PreCompact registered at a native command anywhere
take the second state (inert, cite `portable.rs:794`); Codex's currently-registered
but native-refused SubagentStart/Stop (see Recon note above) also take the second or
third state, whichever the root session confirms (see Escalations).
The three qualitative citation rows (D1 Codex, Claude write-scope, native-inert
CwdChanged/PreCompact) are not mechanically derivable from the JSON manifests alone;
the generator carries them as a small inline LIMITATIONS table (event, harness,
reason, citation) it merges into the generated output, so the artifact is still fully
regenerated, not hand-typed, and the limitations are versioned with the script.

**D10. Wire the passing tests into `hooks/tests/run.sh`.** The 17 that already pass,
plus `lint_agent_capabilities.sh` and `test_lead_workflow_tool.sh` once D5/D6 make
them green. Because D2 re-registers rather than retires, no test dies; the
retire-path collision D4's HARD CONDITION worried about is dissolved. Tests that
would have died under the abandoned retire-everything path: any test asserting the
four lost behaviours (SEED-GATE authorship floor check, #59 gates-ran ledger check,
discovery-report indexing check, precompact cursor snapshot check) if such tests
exist under those four scripts' own coverage; enumerate and name them explicitly at
execution time from `hooks/tests/test_bash_post_ledger.sh`,
`hooks/tests/test_cwd_changed_telemetry.sh`,
`hooks/tests/test_subagent_telemetry.sh`,
`hooks/tests/test_seed_preflight_check.sh`, `hooks/tests/test_run_scoped_capture.sh`,
`hooks/tests/test_run_scoped_hook_state.sh` (all present in `hooks/tests/` today,
already exercising the scripts D2 re-registers).

## 4. Escalations and out-of-scope

- **D1 correlation contract (v6.4.7).** Building real Codex spawn-to-child
  correlation is out of scope for this lane; recorded as a v6.4.7 item.
- **D3 seed footprint (v6.4.7).** `.shepherd/runs/v646/seed.md` HARD-fails SEED-GATE
  at 393 vs 200 lines once D3 lands. Do not fix in this lane. Report at close.
- **Claude write-scope narrowing.** `**` is the honest recorded scope because no host
  declares one; making Claude declare a narrower scope is a host-side change, out of
  scope here.
- **`agents/`, `conformance/content-target-final.json`,
  `crates/component/tests/component.rs` are the root's.** The root regenerates the
  compiled tree and the conformance oracle from the compiler manifest as established
  procedure, after merging this lane's `content/roles/` edits. This lane does not
  touch any of the three and does not need to report drift on them; it only needs to
  leave `content/roles/engineer.md` and `content/roles/planter.md` correctly edited
  for the root's single regeneration run, and to state (per D6) exactly what the
  regenerated `agents/engineer.md` / `agents/planter.md` Prohibitions sections are
  expected to contain.
- **Codex `packages/harness-codex/hooks/hooks.json` SubagentStart/Stop framing.**
  Recon (section 2) found these two events currently REGISTERED (not absent),
  forwarding into a native refusal path that already behaves correctly per the pinned
  tests. D1 says "stay unregistered"; the filesystem shows "registered, but refused."
  These are compatible readings (no new correlation is ever built) but the wording
  gap is worth a one-line confirmation from the root session before Wave 3 hardcodes
  the table's Codex row. Not a blocker: proceed with the "registered but refused,
  cite `native_hook.rs` + `codex_hook_cli.rs:223,257`" framing unless corrected.

## 5. Waves

Each step lists exact owned files; no two steps in the same wave share a file.

### Wave 1 (depends on: baseline only)

**W1.1 - D6 role prose fix, verified without touching `agents/`.**
Objective: name the carrier-form skill tokens the lint greps for, in the two
Prohibitions sentences, in `content/roles/` only.
Owned files: `content/roles/engineer.md`, `content/roles/planter.md`. `agents/*.md` is
NOT owned or written by this step.
Test: `hooks/tests/lint_agent_capabilities.sh` (existing, unchanged), run against a
scratch tree via `SHEPHERD_LINT_AGENTS_DIR`, the pattern
`test_lead_workflow_tool.sh:83` already proves works: `cp -r agents/ <tmp>/agents`,
apply the identical prose edit to `<tmp>/agents/engineer.md` and
`<tmp>/agents/planter.md` (same old-string/new-string as the `content/roles/` edit),
then `SHEPHERD_LINT_AGENTS_DIR=<tmp>/agents bash hooks/tests/lint_agent_capabilities.sh`.
Fails on purpose (before): `SHEPHERD_LINT_AGENTS_DIR=<tmp>/agents bash
hooks/tests/lint_agent_capabilities.sh` on an UNPATCHED `<tmp>/agents` copy exits 1,
2 of the baseline 5 violations are the missing carrier-form tokens.
Proves pass (after): the same command against the PATCHED `<tmp>/agents` copy exits 0
for these two checks; tracked `agents/` is never touched, `git status -- agents/`
shows no change from this step.
Review: report which two role files were edited and paste the exact new Prohibitions
sentences, so the root can verify its own regeneration matches; do not run any
generator command against the tracked tree.

**W1.2 - D5 lint re-point.**
Objective: replace the stale `conductor_write_guard.sh` grep with a check for the
existing native PreToolUse `Write|Edit` matcher registration at `hooks/hooks.json:16`.
Owned files: `hooks/tests/lint_agent_capabilities.sh`.
Test: `hooks/tests/lint_agent_capabilities.sh` (self) and
`hooks/tests/test_legacy_policy_retirement.sh` (must stay green throughout, proving
the two were in contradiction before this fix).
Fails on purpose (before): `bash hooks/tests/lint_agent_capabilities.sh` exits 1 on
the conductor check (1 of the baseline 5) while
`bash hooks/tests/test_legacy_policy_retirement.sh` exits 0 at the same time,
demonstrating the contradiction. Pre-verified falsification for the NEW assertion:
temporarily strip `Write` from the `"Write|Edit|Bash|Agent|Workflow"` matcher string
in `hooks/hooks.json`, run the new lint check, confirm it goes red citing the missing
`Write` coverage, then revert the temporary edit.
Proves pass (after): both commands exit 0 in the same tree state, with
`hooks/hooks.json:16` unmodified (matcher already covers `Write` and `Edit` on the
real tree, no `hooks.json` edit needed for D5 itself).
Review: cite `content/predicates/write-boundary.toml` (`role-write-eligibility`,
`path-in-declared-scope`) in a comment, read-only, file never touched (forbidden
path). Check keys on absence of a write-tool grant plus presence of the matcher, not
on `write_eligible: false`.

**W1.3 - D2+D3 re-register 7 hooks.**
Objective: restore the 6 deleted telemetry registrations plus `seed_preflight_check.sh`
(THIN) to `hooks/hooks.json`, and add all 7 to `METADATA` in
`hook_authority_inventory.py`.
Owned files: `hooks/hooks.json`, `hooks/scripts/hook_authority_inventory.py`.
Test: `python3 hooks/scripts/hook_authority_inventory.py --self-test` (must keep
passing unchanged, fixture untouched this wave) and
`python3 hooks/scripts/hook_authority_inventory.py --check` against the real tree.
Fails on purpose (before): `python3 hooks/scripts/hook_authority_inventory.py --check`
on the real tree today reports 1 entry only (no failures, but incomplete coverage);
running any of `hooks/tests/test_bash_post_ledger.sh`,
`hooks/tests/test_cwd_changed_telemetry.sh`, `hooks/tests/test_subagent_telemetry.sh`,
`hooks/tests/test_seed_preflight_check.sh` directly shows them exercising scripts that
are not currently reachable via `hooks.json` (no Claude-side trigger).
Proves pass (after): `python3 hooks/scripts/hook_authority_inventory.py --json` shows
8 entries, `counts` = `{THIN: 2, TELEMETRY: 6, ...: 0, ...: 0}`; the four tests above
now exercise a live registration path; `bash scripts/gate.sh` still green.
Review: PostToolUse is a NEW top-level key (was absent); CwdChanged and PreCompact are
NEW top-level keys; never register these two at a native command (cite
`portable.rs:794`, `Other(_) => DispatchPlan::Ignored`). Every new `METADATA` entry
gets `classification: TELEMETRY` except `seed_preflight_check.sh`
(`classification: THIN`, `native_surface: ["shepherd seed verify"]`).

**W1.4 - D8 Pi manifest + drift test.**
Objective: extend `packages/harness-pi/shepherd.pi.json` with the `hooks` block and
add a test that fails if the manifest and `extension.mjs` drift apart.
Owned files: `packages/harness-pi/shepherd.pi.json`,
`hooks/tests/test_pi_manifest_drift.sh` (new).
Test: `hooks/tests/test_pi_manifest_drift.sh` (new).
Fails on purpose (pre-verified scenario): declare a fifth guarded tool (e.g.
`notebook_edit`) in the manifest's `tool_call` guard list that `extension.mjs:19`'s
`GUARDED_TOOL_NAMES` does not contain, run the new test, confirm it fails citing the
mismatch, then revert. Secondary check: remove one `hooks` entry (e.g. `tool_call`)
from the manifest and confirm the test also fails citing the orphaned
`pi.on("tool_call")` handler at `:59`.
Proves pass: `bash hooks/tests/test_pi_manifest_drift.sh` exits 0 against the real
tree.
Review: `chmod +x hooks/tests/test_pi_manifest_drift.sh` before `git add`, or
`git update-index --chmod=+x` if already staged (exec-bit sub-task; not gated by
`test_exec_bits.sh`, scoped to `hooks/scripts/*.sh`, but must be runnable).

Wave 1 review criteria: `bash hooks/tests/lint_agent_capabilities.sh` and
`bash hooks/tests/test_lead_workflow_tool.sh` both exit 0 against the tracked tree
plus W1.1's scratch-tree proof (the baseline 5 violations are now 0);
`python3 hooks/scripts/hook_authority_inventory.py --self-test` still passes;
`bash scripts/gate.sh` still green; `git status -- agents/` is clean.

### Wave 2 (depends on: Wave 1 / W1.3)

**W2.1 - D4a self-test hardening.**
Objective: extend `self_test()`'s fixture with an unclassified registration and prove
condition (2) of D4's HARD CONDITION.
Owned files: `hooks/scripts/hook_authority_inventory.py`.
Test: `python3 hooks/scripts/hook_authority_inventory.py --self-test` (extended).
Fails on purpose: temporarily add the new fixture target
(`hooks/scripts/unclassified.sh`) to `METADATA` inside the fixture setup and show
`--self-test` reports `self-test failed to detect: missing inventory metadata` and
exits 1; then remove that temporary addition.
Proves pass: `python3 hooks/scripts/hook_authority_inventory.py --self-test` exits 0
with the new fixture registration present and NOT added to fixture `METADATA`.
Review: if condition (2) cannot be made to fail on purpose this way, STOP, do not
proceed to W2.2/Wave 3/Wave 4/Wave 5 under D2/D3; execute the D4 HARD CONDITION
fallback instead (retire all seven scripts, document the four lost behaviours named
in D10, revert W1.3's `hooks.json` registrations, keep W1.3's `METADATA` reduced to
the original 1 entry). Record which branch was taken in the close report.

**W2.2 - D4b pinned-test count updates.**
Objective: update the three tests pinning the registration/classification set to the
new shape (8 entries, 2 THIN / 6 TELEMETRY).
Owned files: `hooks/tests/test_registered_hooks_no_python.sh`,
`hooks/tests/test_registered_hook_authority.sh`,
`hooks/tests/test_legacy_policy_retirement.sh`.
Test: the three files themselves.
Fails on purpose (before): all three currently fail against the W1.3 tree (they still
assert 1 entry / the old command-set shape) - `bash hooks/tests/test_registered_hook_authority.sh`
exits 1 citing the stale `len(entries) == 1`.
Proves pass (after): all three exit 0 against the W1.3 tree; the reframed
`test_registered_hooks_no_python.sh` still fails if a raw `python3`/`node`
policy-resolving command is registered (spot-check: temporarily add one, show it
fails, revert).
Review: `test_legacy_policy_retirement.sh`'s own `retired=()` / length-4 conductor-era
list is untouched (that batch is genuinely retired); only its counts-string copy
changes.

Wave 2 review criteria: `bash hooks/tests/run.sh` run directly against every test
touched in Waves 1-2 (not yet wired into the runner) all exit 0; `bash scripts/gate.sh`
still green.

### Wave 3 (depends on: Wave 1 only, may run parallel to Wave 2)

**W3.1 - D9 generator authorship.**
Objective: write the parity-table generator and its own drift test.
Owned files: `hooks/scripts/generate_harness_parity.sh` (new),
`hooks/tests/test_harness_parity_generator.sh` (new).
Test: `hooks/tests/test_harness_parity_generator.sh` (new).
Fails on purpose: run the generator once to produce a baseline
`.shepherd/runs/v646/harness-parity.md`-equivalent temp file, then hand-edit one cell
in a copy and show the new test detects the diff and exits 1 (regenerate-and-diff);
separately, delete one manifest's `hooks` key in a scratch copy and show the generator
either errors or marks every event for that harness "unsupported: manifest missing
hooks data" rather than silently leaving blank cells.
Proves pass: `bash hooks/tests/test_harness_parity_generator.sh` exits 0 against the
real tree.
Review: three-state table only (implemented/inert/unsupported), each non-"implemented"
cell carries a citation; `chmod +x hooks/scripts/generate_harness_parity.sh` before
`git add` (exec-bit sub-task, gated by `test_exec_bits.sh`); also
`chmod +x hooks/tests/test_harness_parity_generator.sh`.

Wave 3 review criteria: `bash hooks/scripts/generate_harness_parity.sh` runs clean
against the Wave-1 tree state and produces a table with zero unexplained blank cells;
`bash scripts/gate.sh` still green.

### Wave 4 (depends on: Wave 2 and Wave 3)

**W4.1 - D10 test-runner wiring.**
Objective: un-skip the 17 previously-passing tests plus
`lint_agent_capabilities.sh`/`test_lead_workflow_tool.sh` (Wave 1) and the three
D4-updated tests (Wave 2), and wire in the new parity-generator drift test (Wave 3).
Owned files: `hooks/tests/run.sh`.
Test: `hooks/tests/run.sh` itself.
Fails on purpose (before): `bash hooks/tests/run.sh` today reports 18 skipped; grep
its output for the skip list to show the exact set being un-skipped.
Proves pass (after): `bash hooks/tests/run.sh` exits 0 with 0 skips beyond any
explicitly-justified remainder (none expected; if any test must stay skipped, name it
and cite why in this file's Risks section, not silently).
Review: confirm no test named in D10's "would have died" enumeration is missing from
the runner; confirm the parity-generator test runs as a regenerate-and-diff step, not
a static snapshot compare.

### Wave 5 (depends on: Wave 4)

**W5.1 - generate the deliverable artifact.**
Objective: run the generator against the fully-landed tree to emit the real
`.shepherd/runs/v646/harness-parity.md`.
Owned files: `.shepherd/runs/v646/harness-parity.md` (generated).
Test: `hooks/tests/test_harness_parity_generator.sh` (rerun, confirms the committed
artifact matches a fresh regeneration, i.e. it is not stale the moment it lands).
Fails on purpose: n/a (covered in W3.1); rerun here only to prove no drift crept in
between Wave 3 and Wave 5.
Proves pass: `bash hooks/scripts/generate_harness_parity.sh --check` (or equivalent
diff-against-committed mode) exits 0.
Review: no blank cell without a documented limitation citation; Codex
SubagentStart/Stop and Claude write-scope both present as "unsupported" with
citations; Claude SubagentStart present as "implemented and effective" citing
`7d5492e`.

**W5.2 - full verification, no file edits.**
Objective: confirm the full gate suite and hook test runner are green end to end, and
confirm every change stayed inside the lane's allowed paths.
Owned files: none (verification only).
Test: `bash hooks/tests/run.sh`, `bash scripts/gate.sh`.
Fails on purpose: n/a, this step is the final proof, not a new gate.
Proves pass: `bash hooks/tests/run.sh` exits 0, `bash scripts/gate.sh` exits 0 and
still reports green.
Review: `git diff --stat 1f2a398..HEAD -- hooks/ plugins/shepherd/ packages/harness-pi/
packages/harness-claude/ packages/harness-codex/ .shepherd/runs/v646/
content/roles/engineer.md content/roles/planter.md` shows only this lane's own edits;
confirm no change outside the lane's allowed paths plus the two named
`content/roles/*.md` files; `agents/`, the conformance oracle, and the component
digest are untouched (the root's responsibility, per section 4).

## 6. Wave dependency graph

| Wave | Steps | Depends on | Can run parallel to |
|---|---|---|---|
| 1 | W1.1, W1.2, W1.3, W1.4 | baseline only | - |
| 2 | W2.1, W2.2 | Wave 1 (W1.3) | Wave 3 |
| 3 | W3.1 | Wave 1 | Wave 2 |
| 4 | W4.1 | Wave 2, Wave 3 | - |
| 5 | W5.1, W5.2 | Wave 4 | - |

## 7. Risks

- **Config-lane regeneration collision.** This lane never regenerates `agents/` (see
  section 4). If W1.1's scratch-tree verification is somehow insufficient and a real
  regeneration becomes unavoidable, stop and coordinate through the root session
  before running any generator against the tracked tree.
- **Drift rule for every check in this plan.** A non-empty diff is only drift if
  content this lane did NOT write replaced content it DID write. If the diff is this
  lane's own in-flight work committed underneath it by the root, proceed; check
  `git diff -- <file>` before halting on any diff. Base commit for all drift checks is
  `1f2a398` (see section 2), not `587fcfa`.
- **`agents/`, conformance oracle, and component digest are the root's.** No report or
  fix obligation on this lane for those three; do not touch them.
- **D4 fallback branch.** If W2.1 cannot prove condition (2) of the HARD CONDITION on
  purpose, the entire D2/D3 registration path is abandoned per the seed's own rule:
  retire all seven scripts, document the four lost behaviours (SEED-GATE authorship
  floor, #59 gates-ran ledger, discovery-report indexing, precompact cursor snapshot),
  and W1.3/W2.2/Wave 3/Wave 4/Wave 5 all change shape. Detect this as early as
  possible (Wave 2, step 1) precisely so the expensive downstream waves are not built
  on a branch about to be discarded.
- **SEED-GATE live against a failing seed.** Once D3 lands, `shepherd seed verify` on
  `.shepherd/runs/v646/seed.md` HARD-fails (393 vs 200 line cap). This is correct
  behavior, not a regression to fix in this lane. Report it plainly at close; do not
  let it block Wave 3-5 (SEED-GATE gates future seeds going through the tool, it does
  not block this lane's own file edits).
- **Codex SubagentStart/Stop wording gap.** See Escalations section 4. Proceed on the
  "registered but refused" framing for the table unless the root session corrects it
  before Wave 3 finalizes the LIMITATIONS data in the generator.
