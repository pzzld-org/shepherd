# gates-H.md — Step H gate ledger (lane `identity`, run v646)

Scope: `crates/cli/tests/wave_c_bootstrap_cli.rs` (one appended test). The gate below was
shown to FAIL ON PURPOSE, with the literal command and output recorded, then reverted and
shown green again. No break was left in place; the revert was verified with `git diff`
returning empty for the touched production file before the suite was re-run.

## Why this test exists

Five PRODUCTION call sites resolve "the current project" with
`SELECT id FROM projects ORDER BY id LIMIT 1`:

- `crates/cli/src/cmd/wave_h_execution.rs:563`
- `crates/cli/src/cmd/wave_d_planning.rs:785`
- `crates/cli/src/cmd/wave_e_coordination.rs:121`
- `crates/cli/src/cmd/wave_g_coordination.rs:541`
- `crates/cli/src/cmd/wave_f_knowledge.rs:409`

That resolves identity by alphabetical accident, not by identity. It is safe today only
because `crates/cli/src/cmd/wave_c_bootstrap.rs:462` is the sole `INSERT INTO projects`
anywhere under `crates/*/src/` (verified by grep before writing the test), and no SQL
migration under `crates/registry/src/migrate/sql/` seeds one either — so a real namespace
holds at most one row and the `ORDER BY` never has more than one candidate. The moment a
second inserter appears anywhere, all five call sites silently start picking a project
alphabetically. New test
`wave_c_bootstrap_remains_the_sole_production_inserter_of_projects` makes that invariant
load-bearing: it walks every `*.rs` file under `crates/*/src/` (workspace root resolved
from `env!("CARGO_MANIFEST_DIR")` + `../..`, canonicalized — no hardcoded path), matches
the substring `INSERT INTO PROJECTS` case-insensitively (tolerant of the existing
statement's line break), and asserts the matching set is exactly
`{crates/cli/src/cmd/wave_c_bootstrap.rs}`. `crates/*/tests/` is never walked, since
fixtures legitimately insert rows.

## GH1 — the invariant test fails the moment a second production inserter exists

Break introduced: appended one line to `crates/registry/src/lib.rs` (a file otherwise
untouched by this lane and outside my declared scope, restored immediately after capture)
containing a second `INSERT INTO projects` occurrence, simulating exactly the scenario the
test exists to catch:

```rust
// TEMPORARY GATE-GH1 TEST INJECTION: registry.execute("INSERT INTO projects (id, created_at, updated_at) VALUES (?1, ?2, ?2)", params![]).unwrap();
```

Command:

```
cargo test -p shepherd-cli --test wave_c_bootstrap_cli \
  wave_c_bootstrap_remains_the_sole_production_inserter_of_projects -- --nocapture
```

Red (literal, `RUST_BACKTRACE=0`):

```
running 1 test

thread 'wave_c_bootstrap_remains_the_sole_production_inserter_of_projects' (19371246) panicked at crates/cli/tests/wave_c_bootstrap_cli.rs:711:5:
assertion `left == right` failed: found 2 production `INSERT INTO projects` writer(s): ["crates/cli/src/cmd/wave_c_bootstrap.rs", "crates/registry/src/lib.rs"]. Five commands resolve "the current project" with `SELECT id FROM projects ORDER BY id LIMIT 1` (crates/cli/src/cmd/wave_h_execution.rs:563, crates/cli/src/cmd/wave_d_planning.rs:785, crates/cli/src/cmd/wave_e_coordination.rs:121, crates/cli/src/cmd/wave_g_coordination.rs:541, crates/cli/src/cmd/wave_f_knowledge.rs:409), so a second inserter makes all five pick a project alphabetically instead of by identity. The correct fix is a shared resolver keyed to `.shepherd/project.json`, not another `INSERT INTO projects` call site.
  left: ["crates/cli/src/cmd/wave_c_bootstrap.rs", "crates/registry/src/lib.rs"]
 right: ["crates/cli/src/cmd/wave_c_bootstrap.rs"]
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
test wave_c_bootstrap_remains_the_sole_production_inserter_of_projects ... FAILED

failures:

failures:
    wave_c_bootstrap_remains_the_sole_production_inserter_of_projects

test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 12 filtered out; finished in 0.00s

error: test failed, to rerun pass `-p shepherd-cli --test wave_c_bootstrap_cli`
```

The failure message named both offending files by exact relative path and carried the full
rationale (all five call sites, the alphabetical-pick consequence, and the correct fix) —
useful to whoever trips it in the future.

Reverted `crates/registry/src/lib.rs` to its exact original content (byte-for-byte, copied
back from a pre-edit backup). Confirmed clean:

```
$ diff <backup> crates/registry/src/lib.rs
(no output — identical)
$ git diff --stat crates/registry/src/lib.rs
(no output — clean)
$ git status --short crates/registry/src/lib.rs
(no output — clean)
```

Green (literal, full suite re-run after the revert):

```
running 13 tests
test init_refuses_a_symlink_namespace_without_touching_its_target ... ok
test init_refuses_an_existing_config_symlink_instead_of_reporting_success ... ok
test top_level_migrate_stays_an_explicit_dry_run_until_confirmation ... ok
test config_reads_typed_defaults_and_requires_confirmation_to_create_its_document ... ok
test wave_c_bootstrap_remains_the_sole_production_inserter_of_projects ... ok
test init_rolls_back_everything_it_created_when_identity_cannot_be_written ... ok
test init_user_option_bootstraps_only_the_separately_resolved_user_home ... ok
test doctor_reports_a_sensible_result_when_nothing_answers_shepherd_on_path ... ok
test init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots ... ok
test doctor_reports_a_stale_shepherd_resolved_from_path ... ok
test doctor_fails_loudly_on_a_namespace_missing_project_identity ... ok
test init_is_idempotent_and_heals_a_namespace_missing_only_identity ... ok
test home_and_doctor_are_read_only_until_explicitly_confirmed ... ok

test result: ok. 13 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.68s
```

## Format check

```
$ rustfmt --edition 2024 --check crates/cli/tests/wave_c_bootstrap_cli.rs
(exit 0)
```

## Final state

- `crates/cli/tests/wave_c_bootstrap_cli.rs`: one test appended
  (`wave_c_bootstrap_remains_the_sole_production_inserter_of_projects`), plus one private
  helper (`collect_rs_files`). 12 tests before, 13 after.
- `crates/registry/src/lib.rs`: touched only transiently for GH1, byte-identical to its
  pre-gate state afterward, `git diff`/`git status --short` both empty for it.
- No other file touched.
