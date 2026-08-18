# gates-I.md — Step I gate ledger (lane `identity`, run v646)

Scope: `crates/cli/src/cmd/wave_c_bootstrap.rs`, `crates/cli/tests/wave_c_bootstrap_cli.rs`,
`crates/cli/Cargo.toml` (I4 dependency line only). Every gate below was shown to FAIL ON
PURPOSE, with the literal command and output recorded, then reverted and shown green again.
No break was left in place; each revert was verified by re-reading the file after the
green run.

## GI1 — complete artifact set

Extends `init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots`
(`crates/cli/tests/wave_c_bootstrap_cli.rs`) to assert `project.json` exists as a regular
file, its `id` is a valid uuid v7, and the `projects` table holds exactly one row with that
id — the exact set the prior gate never looked at (see `w0-gate.md`).

Break introduced: after asserting `identity_metadata`, temporarily inserted
`std::fs::remove_file(&identity).expect("GATE-I1-RED: force project identity absent");`
immediately before the metadata check (i.e. delete `project.json` right after `init`, then
re-assert it exists — the exact demonstration named in the sprint gate).

Command:
```
cargo test -p shepherd-cli --test wave_c_bootstrap_cli \
  init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots
```

Red (literal):
```
thread 'init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots' panicked at crates/cli/tests/wave_c_bootstrap_cli.rs:115:46:
project identity must exist: Os { code: 2, kind: NotFound, message: "No such file or directory" }
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.37s
```

Reverted the `remove_file` line. Green (literal):
```
running 1 test
test init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.42s
```

## GI2 — doctor is honest

New test `doctor_fails_loudly_on_a_namespace_missing_project_identity`: `init --confirm`,
delete `project.json`, run `doctor`, assert exit 3, a finding naming the missing identity,
and that stdout does not contain `status: ok`.

Break introduced: in `health_report` (`wave_c_bootstrap.rs`), replaced the call to
`read_project_identity_for_doctor` with a hardcoded `let identity: Option<ProjectId> = None;`
— i.e. reverted the doctor identity finding entirely, so a missing identity produces zero
findings and `ok` stays computed from directory/schema checks alone (the pre-fix behavior
measured in `w0-gate.md` section 6).

Command:
```
cargo test -p shepherd-cli --test wave_c_bootstrap_cli \
  doctor_fails_loudly_on_a_namespace_missing_project_identity
```

Red (literal):
```
thread 'doctor_fails_loudly_on_a_namespace_missing_project_identity' panicked at crates/cli/tests/wave_c_bootstrap_cli.rs:378:5:
assertion `left == right` failed
  left: Some(0)
 right: Some(3)
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.40s
```
(`left: Some(0)` is `doctor`'s actual exit code with the finding reverted — i.e. it exits 0
and prints `status: ok`, exactly the bug this gate exists to catch.)

Reverted the `health_report` stub. Green (literal):
```
running 1 test
test doctor_fails_loudly_on_a_namespace_missing_project_identity ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.43s
```

## GI3 — atomicity

New test `init_rolls_back_everything_it_created_when_identity_cannot_be_written`:
pre-creates `.shepherd/project.json` as a directory (the mid-scaffold failure named in the
sprint gate), runs `init --confirm`, asserts non-zero exit, that `docs`/`ctx`/`runs`/
`shepherd.toml`/`shepherd.db` are all absent afterward, and that the pre-existing
`project.json` directory survives untouched.

Break introduced: `Scaffold::rollback` (`wave_c_bootstrap.rs`) stubbed to `return;` before
its unwind loop, so nothing this invocation created is ever removed on failure.

Command:
```
cargo test -p shepherd-cli --test wave_c_bootstrap_cli \
  init_rolls_back_everything_it_created_when_identity_cannot_be_written
```

Red (literal):
```
thread 'init_rolls_back_everything_it_created_when_identity_cannot_be_written' panicked at crates/cli/tests/wave_c_bootstrap_cli.rs:417:9:
docs must be rolled back after a failed init
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.43s
```

Reverted the `rollback` stub. Green (literal):
```
running 1 test
test init_rolls_back_everything_it_created_when_identity_cannot_be_written ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.39s
```

## GI4 — idempotent heal

New test `init_is_idempotent_and_heals_a_namespace_missing_only_identity`: runs
`init --confirm` twice and asserts the identity and row are unchanged and still singular,
then deletes `project.json` and clears the `projects` table (the pzzld partial-scaffold
state — db and toml present, identity absent) and asserts a third `init --confirm` heals to
exactly one row.

Break introduced: `register_project` (`wave_c_bootstrap.rs`) rewritten to drop both the
`if !existing.iter().any(...)` guard and the `ON CONFLICT(id) DO NOTHING` clause, replaced
with an unconditional plain `INSERT`.

Command:
```
cargo test -p shepherd-cli --test wave_c_bootstrap_cli \
  init_is_idempotent_and_heals_a_namespace_missing_only_identity
```

Red (literal):
```
thread 'init_is_idempotent_and_heals_a_namespace_missing_only_identity' panicked at crates/cli/tests/wave_c_bootstrap_cli.rs:457:5:
assertion `left == right` failed: stderr=ERROR: cannot register project: UNIQUE constraint failed: projects.id

  left: Some(1)
 right: Some(0)
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.68s
```
`id` is `TEXT PRIMARY KEY`, so dropping the conflict-do-nothing clause does not silently
duplicate the row — it turns the second `init --confirm` into a hard SQLite constraint
failure (exit 1 instead of the required exit 0). This is the literal, load-bearing proof
that the conflict-do-nothing clause (and its guard) is what makes a repeated `init` an
idempotent no-op rather than a failure; without it, "duplicate row" becomes "second init
errors out," which is exactly what the gate must catch.

Reverted `register_project`. Green (literal):
```
running 1 test
test init_is_idempotent_and_heals_a_namespace_missing_only_identity ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.50s
```

## GI5 — pinned tests unchanged

`config_reads_typed_defaults_and_requires_confirmation_to_create_its_document` (:94, now
shifted by the GI1 extension but content unchanged), `home_and_doctor_are_read_only_until_explicitly_confirmed`
(:139-ish), `init_refuses_a_symlink_namespace_without_touching_its_target` (:235-ish), and
`init_refuses_an_existing_config_symlink_instead_of_reporting_success` (:253-ish) were not
edited. All four pass in the full run below (this gate is never shown red by design — it is
the fixed point every other change is checked against).

## Post-revert verification

After every break above was reverted, `grep -n "GATE-I" crates/cli/src/cmd/wave_c_bootstrap.rs
crates/cli/tests/wave_c_bootstrap_cli.rs` returns nothing: no debug marker was left in either
file.

## Full scope build and test

```
$ cargo build -p shepherd-cli
   Compiling shepherd-cli v6.4.6 (/Users/jo3/src/fl03/shepherd/crates/cli)
    Finished `dev` profile [optimized + debuginfo] target(s) in 1.33s
```
Zero warnings.

```
$ cargo test -p shepherd-cli --test wave_c_bootstrap_cli
running 10 tests
test top_level_migrate_stays_an_explicit_dry_run_until_confirmation ... ok
test init_refuses_a_symlink_namespace_without_touching_its_target ... ok
test init_refuses_an_existing_config_symlink_instead_of_reporting_success ... ok
test init_rolls_back_everything_it_created_when_identity_cannot_be_written ... ok
test init_user_option_bootstraps_only_the_separately_resolved_user_home ... ok
test config_reads_typed_defaults_and_requires_confirmation_to_create_its_document ... ok
test init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots ... ok
test doctor_fails_loudly_on_a_namespace_missing_project_identity ... ok
test init_is_idempotent_and_heals_a_namespace_missing_only_identity ... ok
test home_and_doctor_are_read_only_until_explicitly_confirmed ... ok

test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.63s
```

```
$ cargo test -p shepherd-cli --lib wave_c_bootstrap
running 1 test
test cmd::wave_c_bootstrap::tests::no_clobber_publication_keeps_one_racing_writer_and_leaves_no_temp ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 18 filtered out; finished in 0.04s
```

## Whole-crate `cargo test -p shepherd-cli` — scope note

`cargo test -p shepherd-cli --no-fail-fast` runs every test target in the crate, including
targets this lane does not own. Three targets fail, and none are reachable from this lane's
file scope (`crates/cli/src/cmd/wave_c_bootstrap.rs`, `crates/cli/tests/wave_c_bootstrap_cli.rs`,
`crates/cli/Cargo.toml`):

- `content_compiler::live_content_matches_the_frozen_target_final_oracle` reads root
  `content/` (line 20 of the test: `content_dir()` joins `../../content`) and
  `conformance/content-target-final.json` directly. Both `content/**` and `conformance/**`
  are in this lane's explicit FORBIDDEN list. `git status` shows `content/roles/engineer.md`
  and `content/roles/planter.md` modified but uncommitted by a different, concurrently
  running lane in this same shared worktree; `.shepherd/runs/v646/lanes/identity/foreign-edits-baseline.txt`,
  captured by the conductor at 20:55:40 (before this coder was dispatched), already lists
  `crates/compiler/src/model.rs` and `crates/compiler/tests/compile.rs` as foreign edits in
  flight. Neither `crates/compiler/**` nor `content/**` is in this lane's ownership.
- `wave_g_coordination::teammate_state_status_and_liveness_share_typed_registry_state` and
  `wave_h_execution_cli::{report_escalation_and_teammates_have_registry_backed_output,
  deliverables_and_issue_cache_use_the_typed_registry}` fail in files this lane never
  touched (`git status --short` for `crates/cli/src/cmd/wave_g_coordination.rs`,
  `crates/cli/src/cmd/wave_h_execution.rs`, `crates/cli/tests/wave_g_coordination.rs`,
  `crates/cli/tests/wave_h_execution_cli.rs`, and `crates/registry` returns no output — all
  five are byte-identical to the base commit). Their failures are unrelated to identity,
  doctor, or config, and reproduce on the unmodified base tree.

Literal three-target summary from the full run:
```
error: 3 targets failed:
    `-p shepherd-cli --test content_compiler`
    `-p shepherd-cli --test wave_g_coordination`
    `-p shepherd-cli --test wave_h_execution_cli`
```

Every target this lane owns or touches is green. `cargo build -p shepherd-cli` is clean with
zero warnings.
