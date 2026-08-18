# Lane `identity`, Step F — gate evidence (run v646)

Owner: implementer, wave 2 lane `identity`, Step F.
Base commit at boot: 280f6b6, branch v6.4.6.
Scope: `crates/cli/tests/wave_g_coordination.rs`, `crates/cli/tests/wave_h_execution_cli.rs`.
Production code (`crates/cli/src/cmd/wave_g_coordination.rs`,
`crates/cli/src/cmd/wave_h_execution.rs`) was read only, never written.

## 1. Root cause, confirmed against the source (not re-litigated, verified)

Both fixtures call `init --confirm`, which since wave 1 mints a uuid-v7 project identity
(`.shepherd/project.json`) and inserts a matching `projects` row
(`crates/cli/src/cmd/wave_c_bootstrap.rs::register_project`). Both fixtures then hand-inserted a
SECOND `projects` row with a fixed literal id (`'project-g'`, `'project-h'`) and keyed every other
fixture row (`teammates`, `index_issues`, `escalations`) to that literal.

Every production call site that needs "the project" resolves it with
`SELECT id FROM projects ORDER BY id LIMIT 1`:
- `crates/cli/src/cmd/wave_g_coordination.rs:541` (`project_id`, used by `signal send/poll`,
  `teammate liveness`)
- `crates/cli/src/cmd/wave_h_execution.rs:561` (`project_id`, used by `deliverable promise`,
  `issues classify/list`)
- `crates/cli/src/cmd/wave_d_planning.rs:781` (`report_project_id`, used by `report escalation`,
  `report teammates`)

A uuid v7 begins `01...`, which sorts before `project-g` / `project-h`. Once `init` inserts its own
row, `ORDER BY id LIMIT 1` now returns the uuid, not the fixture's literal id, so every fixture row
hand-keyed to the literal id becomes unreachable by the commands under test.

## 2. Fix

Removed the competing hand-inserted `projects` row from both fixtures. Added a small helper in each
test file, `project_id(root: &Path) -> String`, that reads the id `init` actually minted from
`.shepherd/project.json` (the same document `wave_c_bootstrap.rs::resolve_project_identity` writes).
Every fixture row that used to key to a literal id (`'project-g'`, `'project-h'`) now keys to that
real id instead, via a bound `?N` parameter. No row deletion, no id engineered to sort before a
uuid — both would re-hide the real behavior per the brief's instruction.

Diff: `git diff -- crates/cli/tests/wave_g_coordination.rs crates/cli/tests/wave_h_execution_cli.rs`
(full diff in the session transcript; summary below).

`wave_g_coordination.rs`:
- `initialized()` no longer inserts a `projects` row (init already does).
- new `project_id(root: &Path) -> String` helper, reads `.shepherd/project.json`.
- `teammate_state_status_and_liveness_share_typed_registry_state` now inserts its `teammates` row
  keyed to `project_id(&root)` instead of the literal `'project-g'`.

`wave_h_execution_cli.rs`:
- `register_project()` replaced by the same `project_id(root: &Path) -> String` helper (reads
  `.shepherd/project.json` instead of inserting a second row).
- `deliverables_and_issue_cache_use_the_typed_registry`: the hand-inserted `index_issues` row keys
  to `project_id(&root)` via `?1` instead of the literal `'project-h'`.
- `report_escalation_and_teammates_have_registry_backed_output`: the hand-inserted `escalations`
  and `teammates` rows key to `project_id(&root)` via `?1` instead of the literal `'project-h'`.

## 3. Green, after the fix

```
$ cargo test -p shepherd-cli --test wave_g_coordination
running 7 tests
test unsupported_host_routes_fail_closed_without_shell_authority ... ok
test signal_rejects_invalid_json_without_inserting_state ... ok
test signal_rejects_symlinked_registry_path ... ok
test concurrent_signal_sends_preserve_distinct_registry_rows ... ok
test signal_rejects_oversized_payload_before_registry_insert ... ok
test teammate_state_status_and_liveness_share_typed_registry_state ... ok
test signal_send_poll_json_and_consume_are_scoped_and_bounded ... ok

test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.62s

$ cargo test -p shepherd-cli --test wave_h_execution_cli
running 3 tests
test report_escalation_and_teammates_have_registry_backed_output ... ok
test deliverables_and_issue_cache_use_the_typed_registry ... ok
test sprint_transitions_are_locked_and_close_requires_every_lane ... ok

test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.67s
```

## 4. Gate GF1 — repair shown load-bearing, both fixtures

Per the brief: reverted each fixture change back to the hand-inserted-competing-row shape (edits
only, no `git` command was used to do the revert or restore — a `git apply -R` attempt was tried
first and was correctly denied by the shepherd guard hook as a version-control write; the revert
below was instead done with direct file edits and confirmed byte-identical to base by
`git diff --stat` reading empty before the red run).

### 4a. `wave_g_coordination.rs`

Reverted `initialized()` to hand-insert `'project-g'` again and the teammate test to key its insert
to the literal `'project-g'` (exact base text, confirmed with `git diff -- crates/cli/tests/wave_g_coordination.rs`
returning identical to the pre-repair patch).

```
$ cargo test -p shepherd-cli --test wave_g_coordination -- --test-threads=1
...
thread 'teammate_state_status_and_liveness_share_typed_registry_state' panicked at crates/cli/tests/wave_g_coordination.rs:261:5:
assertion `left == right` failed
  left: Null
 right: "ok"

failures:
    teammate_state_status_and_liveness_share_typed_registry_state

test result: FAILED. 6 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.31s
```

This is the exact `left: Null / right: "ok"` failure recorded in the brief, reproduced live before
restoring the fix.

Restored the fix (`initialized()` no longer inserts a row; teammate test keys to
`project_id(&root)`). Re-ran: 7 passed; 0 failed — reproduced in section 3 above. The restored file
diffs byte-identical to the pre-revert fixed-and-formatted version (`diff` of the two patches
produced no output).

### 4b. `wave_h_execution_cli.rs`

Reverted `project_id()` back to `register_project()` (hand-inserts `'project-h'`) and both call
sites (`deliverables_and_issue_cache_use_the_typed_registry`,
`report_escalation_and_teammates_have_registry_backed_output`) back to the literal `'project-h'`
inserts. `git diff -- crates/cli/tests/wave_h_execution_cli.rs` was empty at this point, confirming
byte-identical to the base commit.

```
$ cargo test -p shepherd-cli --test wave_h_execution_cli -- --test-threads=1
...
thread 'deliverables_and_issue_cache_use_the_typed_registry' panicked at crates/cli/tests/wave_h_execution_cli.rs:181:5:
assertion `left == right` failed
  left: Null
 right: "blocking-this-sprint"
...
thread 'report_escalation_and_teammates_have_registry_backed_output' panicked at crates/cli/tests/wave_h_execution_cli.rs:209:5:
assertion failed: text(&escalation.stdout).contains("# Escalations\n\n- **#1 [reviewer/verify]** Is the output safe? (raised: 42)")

failures:
    deliverables_and_issue_cache_use_the_typed_registry
    report_escalation_and_teammates_have_registry_backed_output

test result: FAILED. 1 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.93s
```

Both hand-inserted-row tests in this file go red on revert, confirming both repairs are
load-bearing, not incidental.

Restored the fix. Re-ran: 3 passed; 0 failed — reproduced in section 3 above. `git diff` of the
restored file is byte-identical to the pre-revert fixed-and-formatted version (`diff` of the two
patches produced no output).

## 5. `crates/cli/tests/wave_e_coordination.rs` — checked, NOT changed

This file has the same textual shape (`init --confirm` then a hand `INSERT INTO projects` with a
literal id, `'project-lock'`, in its `register_project` helper) and currently PASSES:

```
$ cargo test -p shepherd-cli --test wave_e_coordination
running 6 tests
test lock_show_defaults_to_free_without_creating_state ... ok
test injected_history_failure_compensates_the_lock_file ... ok
test invalid_mode_is_rejected_before_any_lock_state_is_created ... ok
test lock_acquire_is_atomic_and_second_holder_is_refused ... ok
test reap_uses_native_pid_probe_when_path_has_git_but_no_kill ... ok
test lock_release_updates_audit_and_refuses_symlink_paths ... ok

test result: ok. 6 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.75s
```

**Why it passes.** `crates/cli/src/cmd/wave_e_coordination.rs:119` has the identical
`project_id(registry)` helper (`SELECT id FROM projects ORDER BY id LIMIT 1`), used by
`lock acquire`/`lock release`/`lock reap` (`:198`, `:224`, `:247`) purely to satisfy the
`project_id` foreign key on `locks_history` INSERT/UPDATE statements (`:214`, `:233`, `:265`). Since
`init` now also inserts a row, `project_id()` resolves to the uuid instead of the fixture's
`'project-lock'`, exactly like the wave_g/wave_h regression. But no test in this file ever reads
`locks_history`, and no test asserts on which project id a lock write used — every assertion is
against `.shepherd/shepherd.lock` file state, the `lock show`/`lock acquire` stdout, or exit codes,
none of which depend on the resolved project id's value, only on `project_id()` resolving to SOME
row without erroring. The competing `'project-lock'` row is now dead weight (it never wins the
`ORDER BY`), but nothing in the file depends on it winning, so nothing breaks.

**Is it latently fragile?** Yes, structurally: this is the exact same anti-pattern that broke
`wave_g_coordination.rs` and `wave_h_execution_cli.rs` (hand-insert a competing `projects` row with
a literal id after `init`, which now always loses the `ORDER BY id LIMIT 1` race to the uuid).
Nothing here currently asserts on the resolved id, but any future test added to this file that
inserts a `locks_history`-adjacent row keyed to `'project-lock'` and then asserts on it would hit
the identical failure this step just fixed. Flagging for awareness; NOT changed, per the brief's
instruction to leave it alone unless it is actually failing, and it is out of this step's file
scope (`crates/cli/tests/wave_e_coordination.rs` is not in Step F's ownership block).

## 6. Full result

```
$ cargo test -p shepherd-cli --test wave_g_coordination --test wave_h_execution_cli
...
test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.72s
...
test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.35s
```

`cargo build -p shepherd-cli` — Finished, no errors, no warnings from these files.

Files touched by this step, exact paths:
- `/Users/jo3/src/fl03/shepherd/crates/cli/tests/wave_g_coordination.rs`
- `/Users/jo3/src/fl03/shepherd/crates/cli/tests/wave_h_execution_cli.rs`
- `/Users/jo3/src/fl03/shepherd/.shepherd/runs/v646/lanes/identity/gates-F.md` (this file)

No other file was written. `crates/cli/src/cmd/wave_g_coordination.rs` and
`crates/cli/src/cmd/wave_h_execution.rs` were read only, confirmed unmodified
(`git status --short` shows no change from this session for either).
