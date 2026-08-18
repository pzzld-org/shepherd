# Step D — doctor reports install integrity (wave 2, evidence)

Owner: lane `identity`, wave 2, step D. Files touched: `crates/cli/src/cmd/wave_c_bootstrap.rs`,
`crates/cli/tests/wave_c_bootstrap_cli.rs`. Base commit checked at dispatch: `280f6b6`.

## 0. Context-inventory note

The dispatch brief cited "`plan.md` section 11 is the doctor scope addition." `plan.md` in
this lane has ten sections, not eleven; there is no section 11. Before writing any code this
was cross-checked against the rest of the run's artifacts rather than treated as a guess:

- `.shepherd/runs/v646/lanes/distribution/plan.md` (Wave 1 escalations, resolved 2026-08-17):
  *"Doctor check -> IDENTITY LANE. The `shepherd doctor` half of deliverable 2 ... is REMOVED
  from this lane and assigned to the identity lane ... `doctor` should report the resolved
  path, whether it is the native binary, AND the version skew against the checkout."*
- `.shepherd/runs/v646/lanes/distribution/blocker-stale-binary.md`: the measured incident (a
  binary built 20:31:38 predating fixes at 20:39:06/20:41:07, both reporting `shepherd-cli
  6.4.6`) that this check exists to catch, with the exact remediation command
  (`cargo install --path crates/cli --locked --force`).
- `.shepherd/runs/v646/seed.md:225-226` and `.shepherd/runs/v646/carry-forward.md:95-108`: the
  same three facts (resolved path, native-vs-launcher, skew) stated independently.

All three agree with the dispatch brief verbatim. The plan.md section number is stale — the
lane's own plan.md was never amended for this handoff — but the work itself is doubly
authorized (team-lead ruling + carry-forward) and fully specified without it, so this did not
halt. Wave 1's landed state (`.shepherd/project.json`, the `projects` row, `doctor` failing
loudly on missing identity) was independently re-verified by reading the current source before
any edit — see section 1.

## 1. Pre-flight verification

- `git -C /Users/jo3/src/fl03/shepherd rev-parse --short HEAD` -> `280f6b6`, not denied.
- `crates/cli/src/cmd/wave_c_bootstrap.rs` and `crates/cli/tests/wave_c_bootstrap_cli.rs` exist
  and match the brief's description of wave 1's landed state exactly: `initialize_project`,
  `Scaffold`/`ScaffoldArtifact` rollback set, `resolve_project_identity`, `register_project`,
  `health_report`, `read_project_identity_for_doctor`, and the 10 passing tests listed in
  `gates-I.md` were all present before this wave's first edit.
- Dedup / duplication check: no existing `resolved_shepherd`, `BinaryFormat`, PATH-resolution,
  or binary-skew logic anywhere in `crates/cli/src` or `crates/core/src`
  (`grep -rn "resolved_shepherd\|BinaryFormat\|classify_binary" crates/` -> zero hits before
  this change).

## 2. What's already available, checked before inventing anything

- `find . -name build.rs` (excluding `target/`): `crates/core`, `crates/render`, `crates/sdk`,
  `crates/registry`, `crates/compiler`. **`crates/cli` has no `build.rs`.**
- `grep -rn "vergen\|VERGEN\|option_env!(\"GIT" --include='*.rs' --include='*.toml' .`: zero
  hits anywhere in the workspace. No embedded build/commit stamp exists to reuse.
- `grep -n "CARGO_PKG_VERSION\|env!(\"" crates/cli/src`: only `CARGO_MANIFEST_DIR` in
  `guard.rs`, unrelated. No existing version-skew helper to reuse or extend.
- `crates/cli/Cargo.toml` is **outside this step's ownership** (only `wave_c_bootstrap.rs` and
  `wave_c_bootstrap_cli.rs` were assigned), so adding a dependency (`vergen`, `built`,
  `same-file`) or a `build.rs` was never an option here regardless of merit — confirmed via
  `SCOPE OVERFLOW` self-check before design, not after.
- `Command::new("git")` is an established pattern in this crate (`context.rs:178`,
  `wave_b2_seed.rs:418`, `wave_b1_status_handoff.rs:428/443`, `wave_b2_run.rs:874/1150`), so
  shelling to `git` was available in principle. It was considered and rejected — see section 3.

Conclusion: no existing mechanism to reuse. A new, self-designed signal was required, per the
brief's own instruction ("Design the skew signal yourself").

## 3. Design

### Fact 1 — resolved PATH

`resolve_shepherd_on_path()` walks `std::env::split_paths(PATH)` in order and returns the
first `<dir>/shepherd` (`shepherd.exe` tried first on Windows) that is a regular file with an
execute bit set. This is exactly `command -v shepherd` / first-match shell resolution — no
symlink canonicalization, because a shell does not canonicalize either; it reports the literal
`PATH` entry it would exec.

### Fact 2 — native binary vs. launcher/wrapper

`classify_binary_format()` sniffs the first 4 bytes of the resolved file:
- `#!` -> `Script` (a shebang launcher — this is exactly what `bin/shepherd` was, and what the
  distribution lane's S5 step deletes from the repo; a user-authored wrapper on `PATH` is the
  same problem class).
- ELF (`\x7fELF`), Mach-O (all 6 magic byte orders: 32/64-bit, byte-swapped, universal), or PE
  (`MZ`) -> `Native`.
- Anything else (including a 0-3 byte or unreadable file) -> `Unknown`.

This never reads a version string. A launcher and the native binary it wraps can both print
the identical `shepherd-cli --version` — that is the whole reason a magic-byte sniff is used
instead.

### Fact 3 — skew

`compare_binary_freshness()` compares the resolved binary's mtime against
`std::env::current_exe()`'s mtime — the binary that is running `doctor` itself right now.
`skew_seconds = resolved_mtime - current_mtime`; negative means the resolved binary predates
the one currently running the check.

**Two designs were considered and the git one was rejected:**

1. **Resolved-binary mtime vs. `git log -1 --format=%ct` at `context.primary_root`.** Rejected.
   `primary_root` is the *namespace doctor was asked to check*, not necessarily this tool's own
   source checkout. For any project that merely *uses* the `shepherd` CLI (the common case —
   this tool is not always run from within its own source tree), that project's HEAD commit
   date has no relationship to when the `shepherd` binary on `PATH` was built; the comparison
   would produce a confident-looking but meaningless number. It also depends on the diagnosed
   directory being a git repository with at least one commit at all.
2. **Resolved-binary mtime vs. `std::env::current_exe()` mtime. Chosen.** `current_exe()` is,
   by construction, the most recent compile of *this exact source tree* — it needs no git
   repository, no dependency, and no build script. It reproduces the actual incident precisely:
   run `cargo build` (or `cargo test`, which rebuilds if stale) from the checkout, and the
   binary that just got compiled is definitionally fresher than any file abandoned earlier on
   `PATH`. Comparing a binary to itself (same `(dev, ino)`, via `same_binary()`) short-circuits
   to `skew_seconds = Some(0)` so a binary is never flagged as its own skew.

### ok=false (exit 3) vs. warning — decision and justification

**Decision: all three PATH-binary facts are reported (rendered in both `--json` and text) but
never flip `ok`/exit 3.** They land in a new `warnings: Vec<String>` field, kept separate from
`findings` (which is what `ok = findings.is_empty()` is computed from, unchanged from wave 1).

Justification:

1. **It is measured, not hypothetical, that this must not gate `ok`.** None of the pinned wave
   1 tests (`home_and_doctor_are_read_only_until_explicitly_confirmed`, and the other 9 in
   `wave_c_bootstrap_cli.rs`) override `PATH` — they inherit whatever is genuinely installed on
   *this* machine. This machine has a real `~/.cargo/bin/shepherd` from prior `cargo install`
   runs (per `blocker-stale-binary.md`), whose freshness relative to `current_exe()` at any
   given test run is not controlled by the test. If PATH-binary findings flipped `ok`, the
   pinned assertion `assert_eq!(report["ok"], true)` in the "healthy" branch of
   `home_and_doctor_are_read_only_until_explicitly_confirmed` would be at the mercy of whether
   this developer happened to have reinstalled recently — nondeterministic, environment-
   dependent, and exactly the kind of flake this codebase's own memory (`gates_that_cannot_fail`)
   warns against. This was confirmed empirically: all 10 pre-existing tests plus the 2 new ones
   pass unmodified and un-flaked across three consecutive runs (see section 5) precisely
   because PATH state cannot move `ok`.
2. **`ok`/exit 3 is load-bearing elsewhere in this same file.** `WaveCInitCmd::run` (`:176-180`)
   aborts `init --confirm` itself when `health_report(&context).ok` is false. Folding PATH
   findings into `ok` would make `shepherd init --confirm` fail for a developer who has simply
   never installed the CLI system-wide (a normal `cargo run -- init --confirm` workflow) —
   regressing a currently-green, unrelated code path for an environment fact that has nothing
   to do with whether the namespace it just created is sound.
3. **The incident this exists to catch was invisibility, not exit-code semantics.** The
   original defect was `doctor` printing `status: ok` with *zero* mention of the stale binary.
   A `warning:` line printed unconditionally on every `doctor` invocation — JSON or text —
   closes that gap completely: the operator now sees the fact every single time, independent of
   whether the rest of the namespace happens to be healthy. A dedicated CI/script-level gate
   that *fails the run* on a stale install is explicitly named as still-missing, separate,
   future work in `carry-forward.md:106-108` ("What is still missing is a GATE that fails...")
   — it is not this step's job to invent that gate by silently repurposing `doctor`'s exit code.
4. **"a developer running doctor from a checkout with no installed binary at all must still get
   a sensible report rather than a crash"** (brief, verbatim) is read as requiring a sane,
   non-fatal *result*, not merely a non-panicking process. Keeping missing/stale/non-native
   PATH state out of `ok` is what makes that developer's `doctor` run exit 0 with a clear
   warning, rather than exit 3 for a namespace that is, in every way this lane's earlier work
   defined "sound," actually sound.

### `write_no_clobber`/rollback/init/dispatch behavior — unchanged

This step touches only `health_report`, `DoctorReport`, and adds new free functions after
`read_project_identity_for_doctor`. `initialize_project`, `resolve_project_identity`,
`register_project`, the `Scaffold` rollback set, and `typed_config_value` are untouched —
confirmed by `git diff` showing no edits inside those function bodies.

## 4. Locked directions honored

1. `init` remains the only `--confirm`-gated identity-creation path — untouched.
2. Dispatch still hard-fails on missing identity — `dispatch.rs` is outside this step's scope
   and was not touched.
3. `doctor` stays read-only: `inspect_resolved_shepherd` and everything it calls only reads
   (`std::fs::metadata`, `std::fs::File::open`, `std::env::*`); nothing under this step writes.
4. NOFOLLOW is untouched — this step never opens `.shepherd/*`; it only inspects whatever
   `PATH` resolves and the currently-running executable.

## 5. Test evidence

### Unit tests (pure logic, `#[cfg(all(test, unix))] mod tests` in `wave_c_bootstrap.rs`)

```
$ cargo test -p shepherd-cli --lib wave_c_bootstrap
running 3 tests
test cmd::wave_c_bootstrap::tests::classify_binary_format_tells_a_shebang_launcher_from_the_native_test_binary ... ok
test cmd::wave_c_bootstrap::tests::same_binary_matches_a_hard_link_and_rejects_distinct_files ... ok
test cmd::wave_c_bootstrap::tests::no_clobber_publication_keeps_one_racing_writer_and_leaves_no_temp ... ok

test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 18 filtered out; finished in 0.02s
```

`classify_binary_format_tells_a_shebang_launcher_from_the_native_test_binary` proves the format
sniff against a real `#!/bin/sh` file, an empty file, and the running test binary itself (a
genuine native Mach-O executable on this machine — verified independently:
`xxd target/debug/shepherd | head -1` -> `cffaedfe ...`, i.e. Mach-O 64-bit little-endian,
one of the six magics `classify_binary_format` checks).
`same_binary_matches_a_hard_link_and_rejects_distinct_files` proves the `(dev, ino)` comparison
against a real hard link versus a byte-identical-but-distinct file.

### GD1 — the required gate, shown red on purpose, then reverted to green

**Red capture.** `compare_binary_freshness` was temporarily replaced with a version-only
equivalent — it always returns `Some(0)`, mirroring the actual defect (`shepherd-cli
--version` is identical for the stale copy and the running binary, so a version-only check
always reports "no skew"):

```rust
fn compare_binary_freshness(_resolved: &Path, _warnings: &mut Vec<String>) -> Option<i64> {
    // GD1 FALSIFICATION (temporary, reverted immediately after capture):
    // a version-only comparison. `shepherd-cli --version` is identical for
    // the stale copy and the binary running this check, so this always
    // reports "no skew" — exactly the defect this check exists to catch.
    Some(0)
}
```

Running the GD1 test against this falsified version produced the literal red output (captured
verbatim, panic message plus the full offending JSON report):

```
$ cargo test -p shepherd-cli --test wave_c_bootstrap_cli doctor_reports_a_stale_shepherd_resolved_from_path
running 1 test
test doctor_reports_a_stale_shepherd_resolved_from_path ... FAILED

thread 'doctor_reports_a_stale_shepherd_resolved_from_path' panicked at crates/cli/tests/wave_c_bootstrap_cli.rs:581:5:
a binary back-dated to 2001 must read as stale relative to the freshly built test binary: {
  "ok": true,
  "resolved_shepherd_native": true,
  "resolved_shepherd_path": ".../scratch-path/shepherd",
  "resolved_shepherd_skew_seconds": 0,
  "warnings": [],
  ...
}

test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 11 filtered out; finished in 0.42s
error: test failed, to rerun pass `-p shepherd-cli --test wave_c_bootstrap_cli`
```

That is the exact shape of the real incident, reproduced deterministically: a binary
back-dated to 2001-09-09 (`SystemTime::UNIX_EPOCH + 1_000_000_000s`), correctly classified as
`native` (it's a byte-for-byte copy of the real binary), reported with `resolved_shepherd_skew_seconds: 0`
and `warnings: []` — wrongly healthy, exactly what a version-only check produced twice in one
session per `blocker-stale-binary.md`.

**Reverted, confirmed green.** The falsification was reverted (`diff` against the pre-mutation
copy showed byte-identical restoration), and the full suite re-run:

```
$ cargo test -p shepherd-cli --test wave_c_bootstrap_cli
running 12 tests
test init_refuses_an_existing_config_symlink_instead_of_reporting_success ... ok
test init_refuses_a_symlink_namespace_without_touching_its_target ... ok
test top_level_migrate_stays_an_explicit_dry_run_until_confirmation ... ok
test init_rolls_back_everything_it_created_when_identity_cannot_be_written ... ok
test config_reads_typed_defaults_and_requires_confirmation_to_create_its_document ... ok
test init_user_option_bootstraps_only_the_separately_resolved_user_home ... ok
test doctor_reports_a_sensible_result_when_nothing_answers_shepherd_on_path ... ok
test init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots ... ok
test doctor_fails_loudly_on_a_namespace_missing_project_identity ... ok
test doctor_reports_a_stale_shepherd_resolved_from_path ... ok
test home_and_doctor_are_read_only_until_explicitly_confirmed ... ok
test init_is_idempotent_and_heals_a_namespace_missing_only_identity ... ok

test result: ok. 12 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.62s
```

Re-run twice more (flake check on the timing-sensitive new tests): identical `12 passed; 0
failed` both times.

### GD1's companion test — no crash, sensible report, with nothing on `PATH`

`doctor_reports_a_sensible_result_when_nothing_answers_shepherd_on_path` filters this
machine's real `PATH` down to remove any directory that already answers `shepherd` (rather
than handing `doctor` an empty `PATH`, which would also break its own internal
`git rev-parse` call inside `ExecutionContext::discover` and turn the test into a false
negative about `context()` failing, not about the fact under test). It asserts:
`ok == true`, `resolved_shepherd_path == null`, and a `warnings` entry mentioning `PATH` is
present. Passing, per the run above.

### Every pinned test named in the brief, individually confirmed still green

`home_and_doctor_are_read_only_until_explicitly_confirmed`,
`init_refuses_a_symlink_namespace_without_touching_its_target`,
`init_refuses_an_existing_config_symlink_instead_of_reporting_success`, and all 10 wave 1 tests
in `wave_c_bootstrap_cli.rs` — all 10 present in the `12 passed` run above, unmodified in
behavior (their bodies were not edited by this step).

### Build

```
$ cargo build -p shepherd-cli
    Finished `dev` profile [optimized + debuginfo] target(s) in 1.18s
```
Zero warnings.

### Whole-crate `cargo test -p shepherd-cli --no-fail-fast`

Every target passes, including `content_compiler`, `wave_g_coordination`, and
`wave_h_execution_cli`, which `gates-I.md` (wave 1 evidence, captured 21:19) recorded as
failing for reasons outside this lane's scope (foreign, concurrently-edited files in
`content/**`, `crates/compiler/**`, `crates/registry/**`). Those lanes have since landed their
own fixes in this shared worktree; nothing in this step touched any of those files. Full
literal summary line for the target this step owns:

```
test result: ok. 12 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.62s
```

(`wave_c_bootstrap_cli`, from the full run.)

## 6. Formatting

`rustfmt --edition 2024 crates/cli/src/cmd/wave_c_bootstrap.rs crates/cli/tests/wave_c_bootstrap_cli.rs`
run on only the two owned files, exit 0. `cargo fmt` was never run on the workspace. Rebuilt
and re-ran the full test suite after formatting to confirm no behavior change (section 5's
final `12 passed` run is post-format).

## 7. Files touched (verbatim, for handoff)

- `/Users/jo3/src/fl03/shepherd/crates/cli/src/cmd/wave_c_bootstrap.rs`
- `/Users/jo3/src/fl03/shepherd/crates/cli/tests/wave_c_bootstrap_cli.rs`
- `/Users/jo3/src/fl03/shepherd/.shepherd/runs/v646/lanes/identity/gates-D.md` (this file, new)

No other file was written, staged, or committed. No dependency was added; `crates/cli/Cargo.toml`
was not touched (it is outside this step's ownership).
