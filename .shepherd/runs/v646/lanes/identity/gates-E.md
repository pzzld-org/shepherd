# gates-E.md — Step E (errno classification) gate evidence, run v646, lane `identity`

Author: coder, Step E dispatch. Ownership: `crates/cli/src/cmd/dispatch.rs`,
`crates/cli/src/cmd/wave_f_knowledge.rs`, `crates/cli/tests/dispatch_cli.rs`,
`crates/cli/tests/wave_f_knowledge.rs`, this file.

Base commit at dispatch: `b992ec6` (verified via `git rev-parse --short HEAD` as the first
action, per the abort rule; not denied). `foreign-edits-baseline.txt` in this same directory
already records that the shared worktree carried unrelated, concurrent dirty files from other
lanes at that moment (compiler/model.rs, scripts/*, etc.) — expected, not a red flag. During this
dispatch HEAD advanced twice more (custodian commits `0623dfd`, `1f2a398`), neither of which
touched any file in this lane's ownership; confirmed by inspecting both commits' diffs before
proceeding.

## What was built

One classifier, `ReadSubject` + `classify_nofollow_open_error`, defined `pub(crate)` in
`dispatch.rs` (previously nonexistent), consumed by both `dispatch.rs::read_regular_nofollow`
(project identity only) and `wave_f_knowledge.rs::read_regular_nofollow` (now subject-parameterized,
used at all four of its call sites: `project_id()`, `dups_registry()`, `dups_check()`,
`load_insights()`). The two previously-hardcoded "cannot open ... without following symlinks"
strings collapsed into the one classifier; no second copy is kept in sync by hand.

Errno mapping, both subjects, implemented exactly as specified:
- `ENOENT` -> subject's not-found text (`project not scaffolded — run \`shepherd init\`` for
  identity, `no such file: <path>` for an ordinary file — matches the existing "no such file:"
  idiom already used at `wave_b2_seed.rs:72`)
- `ELOOP` -> the existing security refusal wording, unchanged, still gated by subject-specific
  labelling ("project identity " prefix for identity, none for a file)
- `ISDIR` -> "not a regular file" text, subject-appropriate
- anything else -> a generic "cannot open ...: <errno>" message, never the symlink wording

## Platform errno verification (not assumed)

Wrote a standalone C program (outside the repo, `/private/tmp/.../scratchpad/nofollow_errno.c`,
compiled with `clang`, run directly — no repo file touched) to observe the real kernel behaviour
on this Darwin box for `open(..., O_RDONLY | O_NOFOLLOW)`:

```
open(symlink, O_NOFOLLOW) -> fd=-1 errno=62 (Too many levels of symbolic links)
open(absent, O_NOFOLLOW) -> fd=-1 errno=2 (No such file or directory)
open(dir, O_NOFOLLOW) -> fd=3 errno=0 (Undefined error: 0)
```

errno 62 on Darwin is `ELOOP` — confirmed via `rustix::io::Errno::LOOP` mapping to `libc::ELOOP`
in `rustix-1.1.4/src/backend/libc/io/errno.rs:527`. So `O_NOFOLLOW` refusal really does surface as
`ELOOP` on this platform, matching Linux; the classifier's `Errno::LOOP` arm is correctly targeted.
Also confirmed: opening a *directory* with `O_RDONLY | O_NOFOLLOW` **succeeds** at the `open()`
level on Darwin (fd=3, no error) — `O_NOFOLLOW` only refuses symlinks, not directories. That means
the pre-existing post-`fstat` `is_file()` check (unchanged by this lane) is what actually produces
"not a regular file" for a directory in practice; the classifier's `Errno::ISDIR` arm is defensive
completeness for the "errno mapping" table the plan specifies, not something the real `open()` call
exercises on this platform. GE3 below proves the directory case through the code path that is
actually reachable (the `fstat` check), and does so with a real, on-disk directory.

## GE1 — ENOENT, identity subject

Command: `cargo test -p shepherd-cli --test dispatch_cli` (plus a unit-level companion in the same
crate's lib tests, since `read_project_id` never touches `ExecutionContext` and can be exercised
directly with a bare path).

Real condition: a scaffolded namespace (git repo + `.shepherd/runs/v645/run.json`) with
`.shepherd/project.json` never created. Verified `find . -type l` equivalent: zero symlinks
anywhere in the fixture (the helper never creates one).

**Break introduced**: reverted the `Errno::NOENT` arm of `classify_nofollow_open_error` back to
the old blanket "without following symlinks" string.

**Red, captured verbatim**:
```
thread 'dispatch_reports_missing_identity_as_unscaffolded_not_a_symlink_refusal' panicked at crates/cli/tests/dispatch_cli.rs:291:5:
stderr=ERROR: cannot open project identity /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/shepherd-dispatch-cli-missing-identity-47708-18ccc4a51aed0850/.shepherd/project.json without following symlinks: No such file or directory (os error 2)

thread 'cmd::dispatch::tests::read_project_id_reports_absence_as_not_scaffolded' panicked at crates/cli/src/cmd/dispatch.rs:461:9:
message=cannot open project identity /var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/shepherd-dispatch-identity-absent-47912/project.json without following symlinks: No such file or directory (os error 2)
```
This is the exact bug string from w0-gate.md section 8, reproduced on demand.

**Reverted the break. Green**:
```
test dispatch_reports_missing_identity_as_unscaffolded_not_a_symlink_refusal ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.35s

test cmd::dispatch::tests::read_project_id_reports_absence_as_not_scaffolded ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
```

## GE2 — ELOOP, identity subject (NEW coverage — and a correction to the seed's assumption)

**Verified, not assumed, before writing the test**: the seed says
`dispatch_cli.rs:232` pins this. Checked: that line sits inside
`linked_worktree_uses_only_the_primary_project_and_active_run_store`, and asserts
`record["project_id"] == "018f47ce-..."` (primary-root precedence across a linked git worktree),
never a symlink refusal. Confirmed by reading the test in full. **dispatch.rs's symlink path had
no test before this lane.**

**A second, more important discovery, made only by testing the CLI end to end rather than
reasoning about it**: a literal symlink at `.shepherd/project.json` does **not** reach
`dispatch.rs::read_regular_nofollow`'s `ELOOP` arm through the CLI at all. `context.rs`'s
`validate_resolved_project_paths` (called unconditionally inside `ExecutionContext::discover`,
*before* `dispatch.rs::read_project_id` ever runs) already walks `project_id_path` and any symlink
sitting exactly there trips `ContextError::NonCanonicalProjectPath` first, with its own message
("`project_id: resolved project path is not canonical: <path>`"). First attempt at the CLI-level
GE2 test asserted the old assumption (`stderr.contains("without following symlinks")`) and failed
for real, for this reason — not a mistake in the fix, a mistake in the assumption:
```
thread 'dispatch_refuses_a_symlinked_project_identity' panicked at crates/cli/tests/dispatch_cli.rs:328:5:
stderr=ERROR: project_id: resolved project path is not canonical: /private/var/folders/.../.shepherd/project.json
```
This is analogous to the plan's own section 2 correction of the seed's `dispatch_cli.rs:232`
citation — verified by running the instrument, not by re-reasoning from the spec.

Consequence: dispatch.rs's own `NOFOLLOW`-refusal branch for the **identity subject** is
unreachable via the CLI (the earlier, out-of-scope `context.rs` guard always wins). It **is**
reachable directly, because `read_project_id`/`read_regular_nofollow` take a bare `&Path` and never
touch `ExecutionContext`. Two tests now cover GE2 honestly:

1. `read_project_id_refuses_a_symlinked_identity_with_the_security_wording` (unit level, in
   `dispatch.rs`'s own `#[cfg(test)] mod tests`) — constructs a real on-disk symlink, calls
   `read_project_id` directly, and lets the kernel produce a real `ELOOP`. This is the exact code
   this lane changed, exercised with a real symlink, with no hand-built errno.
2. `dispatch_refuses_a_symlinked_project_identity` (CLI level, `dispatch_cli.rs`) — kept and
   corrected to assert what the CLI genuinely does: refuse a symlinked identity file, with a
   security-shaped message, and — the assertion that matters for this lane's subject-awareness
   claim — **never** the "not scaffolded" remediation a plain absence gets.

**Break 1 (unit level)**: pointed the fixture at the regular target file instead of the symlink.
**Red**:
```
thread 'cmd::dispatch::tests::read_project_id_refuses_a_symlinked_identity_with_the_security_wording' panicked at crates/cli/src/cmd/dispatch.rs:430:46:
symlinked identity must be refused: ProjectId("018f47ce-72d7-7f64-9eb1-2f651d521c2a")
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 18 filtered out; finished in 0.01s
```
**Reverted. Green**:
```
test cmd::dispatch::tests::read_project_id_refuses_a_symlinked_identity_with_the_security_wording ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 18 filtered out; finished in 0.00s
```

**Break 2 (CLI level)**: replaced `symlink(&target, ...)` with `fs::copy(&target, ...)` in the
fixture (a real regular file, not a symlink). **Red**:
```
thread 'dispatch_refuses_a_symlinked_project_identity' panicked at crates/cli/tests/dispatch_cli.rs:331:5:
assertion failed: !start.status.success()
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.50s
```
**Reverted. Green**:
```
test dispatch_refuses_a_symlinked_project_identity ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.31s
```

## GE3 — EISDIR, identity subject

Command: `cargo test -p shepherd-cli --test dispatch_cli`. Real condition: `.shepherd/project.json`
created as an actual directory (`fs::create_dir`), exercising the pre-existing post-`fstat`
`is_file()` check (the code path the platform actually uses for this case, per the C-program
verification above).

**Break introduced**: fixture writes a regular file instead of creating a directory.
**Red, captured verbatim** (note: a *different* failure mode than "not a regular file", proving
the test is real and would not pass by accident):
```
thread 'dispatch_refuses_a_directory_in_place_of_project_identity' panicked at crates/cli/tests/dispatch_cli.rs:356:5:
stderr=ERROR: invalid project identity document /private/var/folders/.../.shepherd/project.json: expected ident at line 1 column 2
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.48s
```
**Reverted. Green**:
```
test dispatch_refuses_a_directory_in_place_of_project_identity ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.31s
```

## GE4 — subject awareness (the crux)

Command: `cargo test -p shepherd-cli --test wave_f_knowledge`. Real condition: an already
scaffolded project (`shepherd init --confirm` succeeded) where `dups check
definitely-missing.rs` names a file that plainly does not exist. Reproduces w0-gate.md section 9
(`dups check src/lib.rs` on an absent file), and additionally proves the fix is not a blanket
string swap: the ordinary-file subject must not say "run `shepherd init`" either.

**Break introduced**: collapsed `ReadSubject::not_found_message` to return the identity wording for
both subjects (`let _ = self; format!("project not scaffolded ...")`).
**Red, captured verbatim**:
```
thread 'dups_check_on_a_missing_file_does_not_suggest_init' panicked at crates/cli/tests/wave_f_knowledge.rs:150:5:
stderr=ERROR: project not scaffolded — run `shepherd init`: definitely-missing.rs
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.37s
```
**Reverted. Green**:
```
test dups_check_on_a_missing_file_does_not_suggest_init ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.43s
```

## GE5 — pinned, zero edits

`dups_check_rejects_symlinks_and_oversized_files` at `crates/cli/tests/wave_f_knowledge.rs`
(now line 101, was 111 in the seed's stale citation — the file only grew by appended tests, this
one was never touched). Confirmed via `git diff crates/cli/tests/wave_f_knowledge.rs`: the diff is
24 insertions, 0 deletions, and the diff hunks contain zero occurrences of
`dups_check_rejects_symlinks_and_oversized_files`. This test's subject is a `File` (an arbitrary
`dups check` path, not project identity), so its `ELOOP` wording is unaffected by the
subject-label change (a `File` subject's label is the empty string, matching the original
"cannot open {} without following symlinks" verbatim).
```
test dups_check_rejects_symlinks_and_oversized_files ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.40s
```

## GX — companion checks pinned by the brief

`linked_worktree_uses_only_the_primary_project_and_active_run_store` (`dispatch_cli.rs`), untouched,
still green:
```
test linked_worktree_uses_only_the_primary_project_and_active_run_store ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.37s
```

## Final verification

`cargo build -p shepherd-cli`: clean.
```
   Compiling shepherd-cli v6.4.6 (/Users/jo3/src/fl03/shepherd/crates/cli)
    Finished `dev` profile [optimized + debuginfo] target(s) in 2.34s
```

Scoped run, this lane's exact files:
```
cargo test -p shepherd-cli --test dispatch_cli --test wave_f_knowledge --lib
running 19 tests ... test result: ok. 19 passed; 0 failed
running 6 tests  ... test result: ok. 6 passed; 0 failed   (dispatch_cli.rs)
running 6 tests  ... test result: ok. 6 passed; 0 failed   (wave_f_knowledge.rs)
```

Full-crate run, `cargo test -p shepherd-cli` (and `--no-fail-fast` to see past the first
failure): three targets fail, **none of them in this lane's ownership, none touched by this
lane's diff**:
```
error: 3 targets failed:
    `-p shepherd-cli --test content_compiler`
    `-p shepherd-cli --test wave_g_coordination`
    `-p shepherd-cli --test wave_h_execution_cli`
```
Root-caused, not assumed:
- `content_compiler.rs::live_content_matches_the_frozen_target_final_oracle` — a frozen-hash
  oracle test comparing against `content/roles/*.md`. `git status` shows `content/roles/engineer.md`
  and `content/roles/planter.md` modified, uncommitted, by another lane (not `identity`, not this
  dispatch — `content/**` is explicitly forbidden to this lane). The failing assertion is a SHA256
  mismatch on the compiled "claude" harness content, consistent with an in-flight role-content edit
  whose frozen oracle has not been regenerated yet.
- `wave_g_coordination.rs::teammate_state_status_and_liveness_share_typed_registry_state` and
  `wave_h_execution_cli.rs::{report_escalation_and_teammates_have_registry_backed_output,
  deliverables_and_issue_cache_use_the_typed_registry}` — reran each in isolation (not just under
  the full suite) and they still fail; `wave_h_execution_cli`'s failure is a literal Markdown-text
  mismatch on escalation/role rendering ("`# Escalations\n\n- **#1 [reviewer/verify]** ...`"),
  which plausibly traces to the same in-flight `content/roles/*.md` edit (role names/labels feed
  that rendering). Neither file is in this lane's ownership; neither was read, let alone edited, by
  this dispatch's diff (`git diff --stat` confirms the only files touched are the four in this
  lane's ownership block).

## Files touched by this dispatch

- `crates/cli/src/cmd/dispatch.rs`
- `crates/cli/src/cmd/wave_f_knowledge.rs`
- `crates/cli/tests/dispatch_cli.rs`
- `crates/cli/tests/wave_f_knowledge.rs`
- `.shepherd/runs/v646/lanes/identity/gates-E.md` (this file)

No other file was written by this dispatch. `crates/cli/Cargo.toml` (I4) and
`crates/cli/src/cmd/wave_c_bootstrap.rs` (Step I) show as modified in `git status` but were never
opened or edited by this dispatch — that is the other implementer's exclusive scope, verified by
inspecting `git diff` for those paths (real content, consistent with the plan's Step I) rather than
assumed.
