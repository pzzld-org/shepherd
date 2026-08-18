# gates-G.md — Step G (dedup wave 1's review flagged), run v646, lane `identity`, wave 2

Author: coder, Step G dispatch. Ownership: `crates/cli/src/cmd/dispatch.rs`,
`crates/cli/src/cmd/wave_f_knowledge.rs`, `crates/cli/tests/dispatch_cli.rs`,
`crates/cli/tests/wave_f_knowledge.rs`, this file.

Base commit at dispatch: `280f6b6` (verified via `git rev-parse --short HEAD` as the first
action, per the abort rule; not denied). During this dispatch HEAD advanced once more to
`5bb7bdb` (a docs-only custodian commit). Confirmed via
`git diff --stat 280f6b6..5bb7bdb -- <this lane's four owned files>` that the commit touched
none of them — empty diff, no drift.

## The finding (from wave 1's review gate, restated)

Wave 1 introduced `ReadSubject` with a `not_a_regular_file_message(path)` helper on
`dispatch.rs`, subject-aware by construction, but two post-`fstat` "not a regular file" call
sites did not route through it and kept a hand-written string instead:

- `dispatch.rs`'s own `read_regular_nofollow` (the project-identity reader) hardcoded
  `"project identity is not a regular file: {}"` at the post-`fstat` `is_file()` check, instead
  of calling `ReadSubject::ProjectIdentity.not_a_regular_file_message(path)` — the exact method
  defined one function away for this exact purpose.
- `wave_f_knowledge.rs`'s `read_regular_nofollow` (the `#[cfg(unix)]` arm, the one actually
  compiled and exercised on this Darwin box) hardcoded `"not a regular file: {}"` at its own
  post-`fstat` check, ignoring the `subject: ReadSubject` parameter it already receives and
  already threads into `classify_nofollow_open_error` two lines above.

Two strings, two files, kept in step by hand — the exact duplication shape the lane plan told
wave 1 to delete (plan.md section 4, Step E, point 4: "Delete the duplication; do not leave two
copies in sync by hand").

## What was changed

1. `dispatch.rs` (`read_regular_nofollow`, `#[cfg(unix)]` arm): the post-`fstat` `is_file()`
   branch now calls `ReadSubject::ProjectIdentity.not_a_regular_file_message(path)` instead of
   formatting its own copy of the string. Observable wording is byte-for-byte unchanged
   (`"project identity is not a regular file: {path}"`), because that is exactly the string the
   helper already produces for that subject — this is a pure duplication removal, not a wording
   change.
2. `wave_f_knowledge.rs` (`read_regular_nofollow`, `#[cfg(unix)]` arm): the post-`fstat`
   `is_file()` branch now calls `subject.not_a_regular_file_message(path)` instead of formatting
   its own copy. For `ReadSubject::File` (every call site on this crate today) the wording is
   unchanged (`"not a regular file: {path}"`); for `ReadSubject::ProjectIdentity` (the
   `project_id()` call site) it now correctly says `"project identity is not a regular file:
   {path}"` instead of the previously-wrong subject-blind plain wording — this is the actual bug
   the duplication was hiding, not just a style cleanup.
3. Re-read both files end to end (brief's instruction: "fix those too", not just the two cited
   lines) and found one MORE hand-synced copy of the same pattern, not cited in the finding:
   `wave_f_knowledge.rs`'s `#[cfg(not(unix))]` arm of `read_regular_nofollow` (compiled only on
   non-Unix targets, so untested on this Darwin box, but part of the same function pair and
   carrying the identical subject-blind `"not a regular file: {}"` string). Routed it through
   `subject.not_a_regular_file_message(path)` too, for the same reason: leaving it hand-synced
   would have reintroduced exactly this bug the next time someone edits the Unix arm and forgets
   the non-Unix twin. `cfg(not(unix))`'s ENOENT arm already called
   `subject.not_found_message(path)` before this dispatch (wave 1 got that one right); only the
   not-a-regular-file arm was missed there too.
4. Grepped both files in full for every other occurrence of `"not a regular file"`,
   `"not scaffolded"`, `"no such file"`, and `"without following symlinks"` after the above
   changes to confirm no fourth copy exists. Result: every remaining occurrence of these strings
   is either inside `ReadSubject`'s own two methods (the single source of truth) or inside a test
   assertion. None is a second hand-written copy.

No other hand-synced string was found. The `not_found_message` ENOENT paths (`dispatch.rs:216`,
`wave_f_knowledge.rs:974` via `classify_nofollow_open_error`, and the `#[cfg(not(unix))]` arm's
own `ENOENT` branch) already routed through the helper before this dispatch; only the
not-a-regular-file paths were left hand-synced.

## Gate GG1 — subject-varying "not a regular file" wording, both subjects, real on-disk directory

Required: a test (or tests) pinning that the two subjects still diverge in wording, exercised by
a REAL on-disk directory so the kernel (not a hand-built error) produces the post-`fstat`
`is_file()` failure — the same platform fact wave 1 already established (`O_NOFOLLOW` on a
directory succeeds at `open()` on Darwin; the "not a regular file" outcome comes from the
post-`fstat` check, never from an `open()`-level `EISDIR`).

Two new tests, one per subject, one per file (the two subjects are only reachable through two
different CLI binaries' code paths — `dispatch start` for identity, `dups check` for an ordinary
file — so one shared test cannot exercise both):

1. **`dispatch_directory_identity_gets_the_identity_specific_not_a_regular_file_wording`**
   (`crates/cli/tests/dispatch_cli.rs`, new, appended after the existing wave 1
   `dispatch_refuses_a_directory_in_place_of_project_identity`). Real condition: a git repo with
   `.shepherd/runs/v645/run.json` present and `.shepherd/project.json` created as an actual
   directory via `std::fs::create_dir`. Runs `shepherd dispatch start` end to end. Asserts stderr
   contains the exact identity-specific prefix `"project identity is not a regular file:"` — a
   strictly stronger assertion than wave 1's own `dispatch_refuses_a_directory_in_place_of_project_identity`,
   which only checks the shared substring `"not a regular file"` and so would NOT catch a
   regression that collapsed both subjects onto one string.
2. **`dups_check_on_a_directory_gets_the_plain_not_a_regular_file_wording`**
   (`crates/cli/tests/wave_f_knowledge.rs`, new, appended after the existing wave 1
   `dups_check_on_a_missing_file_does_not_suggest_init`). Real condition: an initialized project
   (`shepherd init --confirm`) with a real on-disk directory `a-directory/` created via
   `std::fs::create_dir`. Runs `shepherd dups check a-directory --json`. Asserts stderr contains
   the plain `"not a regular file:"` wording AND does **not** contain `"project identity"` —
   proving the File subject's wording stays unprefixed after both call sites route through the
   same helper.

Neither test hand-constructs a `CliError` or calls `not_a_regular_file_message` directly; both
go through the full CLI binary against a directory the test itself created on disk, so the
kernel produces the condition exactly as the brief requires.

### Green, before the break

```
$ cargo test -p shepherd-cli --test dispatch_cli --test wave_f_knowledge
running 7 tests
test dispatch_refuses_a_symlinked_project_identity ... ok
test dispatch_reports_missing_identity_as_unscaffolded_not_a_symlink_refusal ... ok
test dispatch_directory_identity_gets_the_identity_specific_not_a_regular_file_wording ... ok
test dispatch_refuses_a_directory_in_place_of_project_identity ... ok
test malformed_requests_and_ambiguous_runs_fail_without_publishing ... ok
test linked_worktree_uses_only_the_primary_project_and_active_run_store ... ok
test binary_start_resolve_and_stop_use_the_primary_active_run ... ok

test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.42s

running 7 tests
test dups_check_on_a_missing_file_does_not_suggest_init ... ok
test dups_check_on_a_directory_gets_the_plain_not_a_regular_file_wording ... ok
test knowledge_leaves_do_not_fallback_to_an_interpreter ... ok
test query_allowlist_and_schema_absence_fail_closed ... ok
test dups_check_rejects_symlinks_and_oversized_files ... ok
test query_existing_but_unmigrated_database_fails_closed ... ok
test search_scope_and_limit_are_rejected_before_query ... ok

test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.27s
```

### Break introduced

Collapsed `ReadSubject::not_a_regular_file_message` to return the `File`-subject string for
*both* subjects (`let _ = self; match Self::File { ... }` — the same shape the plan's own gate
table (GE4) used for the ENOENT case, applied here to the not-a-regular-file case):

```rust
pub(crate) fn not_a_regular_file_message(self, path: &Path) -> String {
    let _ = self;
    match Self::File {
        Self::ProjectIdentity => {
            format!("project identity is not a regular file: {}", path.display())
        }
        Self::File => format!("not a regular file: {}", path.display()),
    }
}
```

### Red, captured verbatim

```
$ cargo test -p shepherd-cli --test dispatch_cli
running 7 tests
...
failures:

---- dispatch_directory_identity_gets_the_identity_specific_not_a_regular_file_wording stdout ----

thread 'dispatch_directory_identity_gets_the_identity_specific_not_a_regular_file_wording' panicked at crates/cli/tests/dispatch_cli.rs:380:5:
stderr=ERROR: not a regular file: /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/shepherd-dispatch-cli-directory-identity-wording-72919-18ccc5d97667ab88/.shepherd/project.json

failures:
    dispatch_directory_identity_gets_the_identity_specific_not_a_regular_file_wording

test result: FAILED. 6 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.89s
```

This is the exact failure mode GG1 exists to catch: with the collapse in place, the identity
subject silently loses its `"project identity "` prefix and reads exactly like an ordinary
missing-knowledge-file error — the same class of subject-blindness bug this lane already fixed
once for the ENOENT case (GE4 in `gates-E.md`), now shown to be equally real for the
not-a-regular-file case and equally caught.

(`dups_check_on_a_directory_gets_the_plain_not_a_regular_file_wording` stayed green under this
same break, as expected: the collapse makes `not_a_regular_file_message` always return the
`File`-subject string, which is exactly what that test already asserts. That asymmetry is the
point — it is the dispatch_cli test, not the wave_f_knowledge test, that proves the two subjects
still diverge, which is why both were written rather than just one.)

### Reverted. Green again

```
$ cargo test -p shepherd-cli --test dispatch_cli --test wave_f_knowledge --lib
running 19 tests (crate lib)
test result: ok. 19 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.04s

running 7 tests (dispatch_cli.rs)
test dispatch_reports_missing_identity_as_unscaffolded_not_a_symlink_refusal ... ok
test dispatch_directory_identity_gets_the_identity_specific_not_a_regular_file_wording ... ok
test dispatch_refuses_a_symlinked_project_identity ... ok
test dispatch_refuses_a_directory_in_place_of_project_identity ... ok
test linked_worktree_uses_only_the_primary_project_and_active_run_store ... ok
test malformed_requests_and_ambiguous_runs_fail_without_publishing ... ok
test binary_start_resolve_and_stop_use_the_primary_active_run ... ok

test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.68s

running 7 tests (wave_f_knowledge.rs)
test dups_check_on_a_missing_file_does_not_suggest_init ... ok
test query_allowlist_and_schema_absence_fail_closed ... ok
test dups_check_on_a_directory_gets_the_plain_not_a_regular_file_wording ... ok
test knowledge_leaves_do_not_fallback_to_an_interpreter ... ok
test dups_check_rejects_symlinks_and_oversized_files ... ok
test query_existing_but_unmigrated_database_fails_closed ... ok
test search_scope_and_limit_are_rejected_before_query ... ok

test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.27s
```

Diff confirmed identical to pre-break (`git diff -- crates/cli/src/cmd/dispatch.rs` shows the
`not_a_regular_file_message` body back to its wave-1-plus-untouched `match self { ... }` form;
no residue from the break).

## Regression check — nothing this dispatch was told to protect moved

- `dups_check_rejects_symlinks_and_oversized_files` (`wave_f_knowledge.rs`): still passes,
  diff to this test is zero (only new content was appended after it, to
  `dups_check_on_a_missing_file_does_not_suggest_init`'s tail, further down the file).
- `linked_worktree_uses_only_the_primary_project_and_active_run_store` (`dispatch_cli.rs`): still
  passes, zero diff to the test body.
- All 6 wave 1 tests in `dispatch_cli.rs`: still pass (`binary_start_resolve_and_stop_...`,
  `malformed_requests_and_ambiguous_runs_fail_without_publishing`,
  `linked_worktree_uses_only_the_primary_project_and_active_run_store`,
  `dispatch_reports_missing_identity_as_unscaffolded_not_a_symlink_refusal`,
  `dispatch_refuses_a_symlinked_project_identity`,
  `dispatch_refuses_a_directory_in_place_of_project_identity`) — zero diff to any of their
  bodies; only one new test was appended after the last of them.
- All 6 wave 1 tests in `wave_f_knowledge.rs`: still pass
  (`query_allowlist_and_schema_absence_fail_closed`,
  `query_existing_but_unmigrated_database_fails_closed`,
  `search_scope_and_limit_are_rejected_before_query`,
  `dups_check_rejects_symlinks_and_oversized_files`,
  `knowledge_leaves_do_not_fallback_to_an_interpreter`,
  `dups_check_on_a_missing_file_does_not_suggest_init`) — zero diff to any of their bodies; only
  one new test was appended after the last of them.
- `dispatch.rs`'s inline `#[cfg(test)] mod tests` (crate-lib): all pass, including
  `read_subject_labels_only_project_identity`,
  `read_project_id_refuses_a_symlinked_identity_with_the_security_wording`, and
  `read_project_id_reports_absence_as_not_scaffolded` — none of these test bodies were touched.

## Final verification

`cargo build -p shepherd-cli`: clean.
```
    Finished `dev` profile [optimized + debuginfo] target(s) in 2.34s
```

`rustfmt --edition 2024 --check` on all four owned files: no diff, already formatted.

Scoped run, this lane's exact files, literal summary:
```
$ cargo test -p shepherd-cli --test dispatch_cli --test wave_f_knowledge
running 7 tests
test dispatch_refuses_a_symlinked_project_identity ... ok
test dispatch_reports_missing_identity_as_unscaffolded_not_a_symlink_refusal ... ok
test dispatch_directory_identity_gets_the_identity_specific_not_a_regular_file_wording ... ok
test dispatch_refuses_a_directory_in_place_of_project_identity ... ok
test malformed_requests_and_ambiguous_runs_fail_without_publishing ... ok
test linked_worktree_uses_only_the_primary_project_and_active_run_store ... ok
test binary_start_resolve_and_stop_use_the_primary_active_run ... ok

test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.46s

running 7 tests
test dups_check_on_a_directory_gets_the_plain_not_a_regular_file_wording ... ok
test query_allowlist_and_schema_absence_fail_closed ... ok
test knowledge_leaves_do_not_fallback_to_an_interpreter ... ok
test dups_check_on_a_missing_file_does_not_suggest_init ... ok
test dups_check_rejects_symlinks_and_oversized_files ... ok
test query_existing_but_unmigrated_database_fails_closed ... ok
test search_scope_and_limit_are_rejected_before_query ... ok

test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.27s
```

Total: 14 of 14 black-box tests pass (6 wave 1 + 1 new, per file), plus 19 of 19 crate-lib unit
tests (unchanged from wave 1's own count).

## Diff summary (this dispatch's own edits, isolated from wave 1's already-present diff)

- `crates/cli/src/cmd/dispatch.rs`: one hunk, 3 lines removed (hand-written format!) replaced by
  2 lines (`ReadSubject::ProjectIdentity.not_a_regular_file_message(path)`), inside
  `read_regular_nofollow`'s post-`fstat` check. No wording change.
- `crates/cli/src/cmd/wave_f_knowledge.rs`: two hunks, one per `read_regular_nofollow` arm
  (`#[cfg(unix)]` and `#[cfg(not(unix))]`), each replacing a 4-line hand-written `format!` with
  a 1-line call to `subject.not_a_regular_file_message(path)`. The `#[cfg(unix)]` hunk is the one
  that fixes the reported bug (the identity subject now gets its correct prefix through this
  path, which is the compiled path on this Darwin box); the `#[cfg(not(unix))]` hunk fixes the
  same latent duplication on the uncompiled arm, found by re-reading the whole file per the
  brief's instruction.
- `crates/cli/tests/dispatch_cli.rs`: append-only, one new test
  (`dispatch_directory_identity_gets_the_identity_specific_not_a_regular_file_wording`) after
  the file's last existing test. No existing test body touched.
- `crates/cli/tests/wave_f_knowledge.rs`: append-only, one new test
  (`dups_check_on_a_directory_gets_the_plain_not_a_regular_file_wording`) after the file's last
  existing test. No existing test body touched.

## Files touched by this dispatch

- `crates/cli/src/cmd/dispatch.rs`
- `crates/cli/src/cmd/wave_f_knowledge.rs`
- `crates/cli/tests/dispatch_cli.rs`
- `crates/cli/tests/wave_f_knowledge.rs`
- `.shepherd/runs/v646/lanes/identity/gates-G.md` (this file)

No other file was written by this dispatch.
