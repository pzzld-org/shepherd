# Harness lane handoff — run v646, seed deliverable 5

Lane: `harness`. Base `1f2a398`. All work left UNCOMMITTED in the worktree; the root
session commits. `agents/`, `conformance/`, and the component digest are untouched.

## Verdict

DONE_WITH_CONCERNS. Every part of deliverable 5 landed. One test is deliberately RED by
the team lead's explicit ruling because it caught a real regression introduced this
sprint; leaving it red is the ruling, not an oversight.

    bash scripts/gate.sh        -> exit 0, "gate (full): green in 100s"
    bash hooks/tests/run.sh     -> exit 1, "27/27 tests ran, 1 failed"

The single failure is `test_native_cli_contract.sh`. See "The one red" below.

## What landed, by seed sub-objective

**(a) Codex SubagentStart/SubagentStop — deliberately NOT restored.**
Restoring them would have been a regression, not a fix. `crates/cli/src/cmd/native_hook.rs`
refuses both for Codex, and its error routing sends a SubagentStop failure to `block()` —
so registering SubagentStop would have BLOCKED EVERY CODEX SUBAGENT STOP. Deeper reason,
ratified by the team lead: Codex exposes no trusted spawn-to-child correlation, so binding
identity there would mint shadow identities, which is what `crates/cli/tests/dispatch_cli.rs:199`
exists to prevent. Fabricated correlation is worse than an honest gap. The parity table
carries both cells as `unsupported: no trusted spawn-to-child correlation`, cited. The
correlation contract is a v6.4.7 item.

**(b) Pi manifest — added, and the seed's premise corrected.**
mesh ROW 7 says "Pi binds no identity and guards no tool use." That is TRUE OF THE MANIFEST
and FALSE OF THE IMPLEMENTATION. `packages/harness-pi/src/extension.mjs` already binds
identity at `session_start:31` and guards write/edit/bash at `tool_call:59`, fail-closed on
every error path. Pi lacked a DECLARATION, not enforcement. `packages/harness-pi/shepherd.pi.json`
now declares all three handlers with `canonicalEvent`, `dispatch: in-process`, handler
citation, behaviour, and guarded-tool list. Record this correction in the close report so
next sprint does not re-litigate it as a security hole.

**(c) Seven inert scripts — RE-REGISTERED, not retired.**
Retiring them would have deleted four behaviours with no native successor: the SEED-GATE
authorship floor, the #59 gates-ran ledger, discovery-report indexing, and the precompact
cursor snapshot. `hook_authority_inventory.py` has always defined `ALLOWED = {THIN, TELEMETRY}`
with a `TELEMETRY_POLICY` regex set that mechanically fails any telemetry hook emitting a
policy decision; v6.4.5 collapsed the live set to one entry but never removed the category.
`hooks/hooks.json` now carries 11 registrations: the 4 native `shepherd claude-hook`
adapters preserved byte-for-byte, plus the 7 shell hooks on their original events.
`PostToolUse`, `CwdChanged`, and `PreCompact` exist again.

`CwdChanged` and `PreCompact` are registered as SHELL telemetry and must never be registered
natively: `crates/core/src/dispatch/portable.rs:810` maps every non-typed event to
`DispatchPlan::Ignored`, so a native registration there is an inert no-op. `PostToolUse`
stays shell for the same reason in spirit — after the root's `aa6dc98` fix a native
PostToolUse registration resolves identity and emits nothing observable, whereas the shell
hooks produce real artifacts.

**(d) `hooks/tests/run.sh` — 6 of 27 -> 27 of 27.**
The runner now DISCOVERS tests with `find` + `while read` rather than a hand-maintained
array. That array was the root cause of this deliverable, not a symptom: re-listing 27 names
by hand would have rebuilt the same trap. It fails loudly on zero discovery
("no test files discovered ... -- pathspec drift?") and reports the count in its summary, so
"27/27 tests ran" degrading to "6" is visible rather than silent.

**(e) All 5 `lint_agent_capabilities.sh` violations — fixed, none by weakening.**
Four were missing carrier-form scope tokens; `content/roles/{engineer,planter}.md` now name
`shepherd:discovery` / `shepherd:auditor` / `shepherd:critic` in prose that was already true.
The fifth was structural: `lint_agent_capabilities.sh:127` demanded `conductor_write_guard.sh`
be registered, while `test_legacy_policy_retirement.sh` demands it be unregistered AND
source-deleted. Satisfying the lint literally would have turned a green shipped gate red,
proving the lint was the stale side. It is re-pointed at the current authority (the native
PreToolUse `Write|Edit` matcher plus `content/predicates/write-boundary.toml`) and is
strictly falsifiable. The lint was NOT deleted and NOT weakened.

    bash hooks/tests/lint_agent_capabilities.sh   -> OK
    bash hooks/tests/test_lead_workflow_tool.sh   -> exit 0

**(f) Acceptance artifact — GENERATED at `.shepherd/runs/v646/harness-parity.md`.**
Produced by `hooks/scripts/generate_harness_parity.sh` from the three JSON manifests. Never
hand-edited; `--check` reports it matches a fresh regeneration. THREE states, not two:
implemented and effective / registered but inert / unsupported harness limitation. Every
non-implemented cell carries a file:line citation. Zero blank cells.

## What each gate PROVED (every one shown to fail on purpose)

| Gate | Falsified by | Result |
|---|---|---|
| `hook_authority_inventory.py --check` | unclassified shell registration | `FAIL: missing inventory metadata` exit 1 |
| same | telemetry hook emitting `permissionDecision` | `FAIL: telemetry_policy_authority` exit 1 |
| `--self-test` | classifying the fixture's unclassified hook | `self-test failed to detect: missing inventory metadata` exit 1 |
| `test_registered_hooks_no_python.sh` | registering a raw Node policy command | 2 failures, exit 2 |
| same | registering an unclassified shell script | exit 1 |
| `lint_agent_capabilities.sh` | stripping `Write` from the matcher | precise FAIL, 4 -> 5 violations |
| `test_pi_manifest_drift.sh` | manifest declares a tool the extension does not guard | exit 1 |
| same | orphaned `pi.on()` handler | exit 1 |
| `test_harness_parity_generator.sh` | hand-edited cell | `--check` exit 1 |
| same | manifest `hooks` key deleted | every row "manifest missing hooks data" (9/9), zero blanks |
| same | zero-row table | `FAIL: zero data rows` |
| same | mistyped flag `--chekc` | rejected, creates no file (dir count 0 -> 0) |
| `run.sh` | zero tests discovered | `FAIL ... pathspec drift?` |

All falsifications ran against `/tmp` copies or `--root`/env-override fixtures. The tracked
tree was never mutated to force a failure.

`test_registered_hooks_no_python.sh` consults the inventory PROGRAMMATICALLY — it subprocesses
`hook_authority_inventory.py --root <root> --json` and reads `classification` back. A filename
allowlist would have looked correct and proved nothing.

## The one red — `test_native_cli_contract.sh`

It caught a real guard regression introduced by this sprint:

    conductor + {"target_role":"engineer"}   -> deny  WRONG-TIER-DISPATCH
    conductor + {"script":"...engineer..."}  -> allow          <-- bypass

A lane-executor lead can bypass `plan-authorship-and-gating-are-root-tier-exclusive` by
expressing the dispatch as a script string instead of a typed field. `implementer-roles-never-dispatch`
is NOT affected (it keys on the acting role and denies under both shapes). Only the
target-keyed rules fall.

Team lead confirmed it as their regression, recorded it at `94a75f4` as carry-forward 0a, and
ruled the test STAYS RED and STAYS WIRED — no skip, no known-gap marker, no inverted
assertion, all three of which would make it inert. It is not special-cased anywhere in
`run.sh`.

## Concerns for the root session

1. **`scripts/gate.sh` does not invoke `hooks/tests/run.sh`.** All 27 hook tests, including
   every gate built in this lane, are run by nothing in the repo's own gate. `scripts/gate.sh`
   is outside this lane's scope, so this is reported, not fixed. Structurally this is the
   largest remaining instance of the sprint's own theme.
2. **Guard enforcement was NOT live for most of this run.** Leads ran unguarded (identity
   normalize rejected a lone `agent_id` and the PreToolUse arm converted that to "tool
   allowed"), and subagents were hard-denied for want of a dispatch record. Both are fixed
   (`7e63628`, `587fcfa`, `7d5492e`), but for the earlier part of the run `write_scope` was not
   enforced, so lane file-disjointness was prose, not a gate. No lane should cite "the guard
   allowed it" as evidence for work done before those commits.
3. **The installed binary went stale silently** and served retired policy for ~20 minutes
   while the source fix was believed live. Worth a gate asserting the installed `shepherd`
   matches the built one.
4. **Exec bits:** the three new scripts are `755` on disk. Preserve the mode when staging, or
   `test_exec_bits.sh` will go red on `hooks/scripts/generate_harness_parity.sh`.
5. **`content/roles/` regeneration is yours.** This lane edited `engineer.md` and `planter.md`
   only, and never ran `shepherd compile` or touched `agents/`. Expect `agents/engineer.md`
   and `agents/planter.md` to gain the carrier-form scope tokens.
6. **`content/roles/conductor.md` in the worktree is the CONFIG lane's**, not this one's.

## Files this lane owns

Modified: `hooks/hooks.json`, `hooks/scripts/hook_authority_inventory.py`, `hooks/tests/run.sh`,
`hooks/tests/lint_agent_capabilities.sh`, `hooks/tests/test_legacy_policy_retirement.sh`,
`hooks/tests/test_registered_hook_authority.sh`, `hooks/tests/test_registered_hooks_no_python.sh`,
`packages/harness-pi/shepherd.pi.json`, `content/roles/engineer.md`, `content/roles/planter.md`.

New: `hooks/scripts/generate_harness_parity.sh`, `hooks/tests/test_pi_manifest_drift.sh`,
`hooks/tests/test_harness_parity_generator.sh`, `.shepherd/runs/v646/harness-parity.md`,
`.shepherd/runs/v646/lanes/harness/{plan,wave1-evidence,handoff}.md`.

Zero forbidden paths modified. `agents/` shows 0 changed files.

## Process note

All seven coders dispatched in this lane returned empty or self-cancelling final messages
("(no action needed)", "(no action taken)", ".", "DONE.") while having done correct work.
Every result in this handoff was verified by the conductor against the worktree. A lane lead
that trusted subagent reports on this substrate would have concluded every wave failed and
redone work that was already correct.

---

## OPEN — `scripts/tests/test_cli_authority_gate.sh` (granted file, work INCOMPLETE)

Team lead granted this ONE file under an explicit narrow exception to the `scripts/`
prohibition. The dispatched coder made a partial edit (10 insertions) and **fixed neither
defect**. Verified by the conductor, not taken from its report:

    bash scripts/tests/test_cli_authority_gate.sh   -> exit 1, same AssertionError
    grep 'hook_authority_inventory|--json'          -> no match (does NOT consult the inventory)
    grep 'rg exit-code discrimination'              -> no match

This is a REDO, not a completion. Both defects remain:

1. **Line ~55** still asserts every registration equals the exact native shape
   `{"type":"command","command":"shepherd","args":["claude-hook"]}`. Must be reframed to
   consult `hook_authority_inventory.py --json` programmatically, mirroring
   `hooks/tests/test_registered_hooks_no_python.sh`, while still pinning an exact count and
   shape (4 native adapters; every other registration classified). A filename allowlist is
   not acceptable.
2. **Lines ~34-37** still cannot distinguish rg exit 1 (clean no-match) from exit 2 (could
   not search). `bin/` is deleted, so this check is INERT today: a match is found, printed,
   and ignored because `if` reads exit 2 as false. Required fix is `case` on the captured
   status — 0 fail, 1 pass, 2 fail with a distinct "scan failed" message. Dropping the dead
   path alone is NOT sufficient.

Four falsifications still owed: telemetry-hook-emits-permissionDecision; unclassified shell
registration; `session_venv` planted in a scratch `hooks/scripts`; a missing scanned path
turning the gate RED rather than passing.

**Do not wire this gate into `gate.sh fast` until it is green** — wiring it now would give a
dead check the appearance of coverage, which is the defect it already has.

Rest of the lane is unaffected and stands as handed off above:
`bash hooks/tests/run.sh` -> 27/27 tests ran, 1 failed (the ruled-red `test_native_cli_contract.sh`).
