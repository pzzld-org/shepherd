# CODER REPORT — W1-S1 (REDO)

- **Lane:** W1-S1 (redo) — fix the `atomic_write` temp-name collision (HIGH), fix the
  `to_canonical_json` NaN/Infinity doc-comment mechanism (LOW). `crates/core/src/run.rs` +
  `crates/core/src/run/` (`shepherd-core`, the harness-agnostic engine crate).
- **Skills loaded:** `code-style` (with `rust` argument, loading `code-style/rust.md`), `rust`.
- **Files touched (created/modified/deleted):**
  - `crates/core/src/run/atomic.rs` — MODIFIED.
  - `crates/core/src/run/tests.rs` — MODIFIED.
  - `crates/core/src/run.rs` — MODIFIED (doc comment only).
- **LOC delta:** +196 / -36 across the three files (`git diff --stat`).

## What changed and why

### HIGH — the temp-name collision (`crates/core/src/run/atomic.rs`)

Root cause exactly as diagnosed: `write_and_rename` opened the tempfile with
`std::fs::File::create(tmp)`, i.e. `O_CREAT|O_TRUNC` — no exclusivity. Two different OS
processes computing the same `(nanos, counter)` candidate from `temp_path()` could both
"succeed" at opening it; the second silently truncates the first's in-flight write with no
error to either side, and whichever writer's `rename` lands last wins with a spliced/partial
`run.json`.

Fix, three pieces:

1. **`create_temp_file_exclusive(next_candidate: impl FnMut() -> PathBuf) -> Result<(PathBuf,
   File)>`** (new, private to `atomic`) — opens each candidate with
   `OpenOptions::new().write(true).create_new(true).open(...)`, the `O_CREAT|O_EXCL` Rust gives
   for `tempfile.mkstemp`'s exclusivity guarantee. On `ErrorKind::AlreadyExists` it pulls a
   fresh candidate from `next_candidate` and retries, bounded by `MAX_TEMP_NAME_ATTEMPTS = 100`
   (a `100`-collision streak on independently generated `(nanos, counter)` pairs would mean
   something structurally wrong, not an ordinary race — giving up returns a clear
   `Error::unknown`, never an infinite loop). Any other I/O error is returned immediately,
   unretried.
2. **`write_and_rename(target: &Path, contents: &str, next_candidate: impl FnMut() -> PathBuf)
   -> Result<()>`** (signature changed from `(tmp: &Path, target: &Path, contents: &str)`) —
   calls `create_temp_file_exclusive` to get an exclusively-owned `(tmp, file)` pair, writes +
   flushes + fsyncs, then renames `tmp -> target`. Cleanup on any failure (write/flush/fsync/
   rename) now only ever unlinks the **one tempfile this call itself exclusively created** —
   never a path merely returned by `next_candidate` that turned out to collide, since a
   collision there means that path belongs to another writer and must not be touched. This is
   strictly safer than the original `atomic_write`'s post-hoc `tmp.exists()` check, which (pre-
   fix) could have deleted a same-named file created by the *other* colliding writer.
   Visibility bumped from private to **`pub(super)`** — the narrowest fit for
   `run::tests::atomic_io` (a sibling module of `atomic`, both children of `run`) to reach it
   directly for the regression test, without exposing it crate-wide.
3. **`atomic_write`** — simplified to `write_and_rename(target, contents, || temp_path(target))?`
   followed by the closing `fsync(dir)`; the old outer `tmp.exists()` cleanup block is gone
   (superseded by point 2's safer, ownership-scoped cleanup inside `write_and_rename`).

Module doc comment (table + prose) updated to describe the new `mkstemp`-equivalent mapping and
to spell out the two-process collision scenario explicitly, since that mechanism is exactly what
the fix defends against.

### Regression test — `store_recovers_from_a_temp_name_collision` (`crates/core/src/run/tests.rs`)

Added inside the existing `#[cfg(feature = "std")] mod atomic_io { ... }` block, following its
conventions (`unique_temp_dir` helper, `minimal_state`, same doc-comment style).

Drives `write_and_rename` **directly** (imported via `use crate::run::atomic::write_and_rename;`)
rather than through `RunState::store`, with an injected two-element candidate sequence: the first
candidate is a file the test pre-creates with sentinel content ("stale bytes from another
writer's tempfile\n") playing the role of another writer's in-flight tempfile; the second is a
genuinely free path. No wall-clock timing, no real second process, no `#[ignore]` — fully
deterministic.

Assertions:
1. `write_and_rename(...)` returns `Ok(())` — the retry recovers from the collision.
2. `target`'s on-disk bytes are **exactly** `contents + "\n"` — the complete, correct write,
   never a splice or a truncation.
3. The colliding placeholder file's content is **byte-identical to what the test seeded** — proof
   `create_new` failing on it means it was never opened, let alone truncated, by this call (the
   exact guarantee `File::create` did not give).
4. The successful candidate path itself no longer exists (renamed away, no leftover `.tmp`).

### LOW — `to_canonical_json`'s doc comment (`crates/core/src/run.rs`)

Original text justified the never-panics claim with: "every `Value` this struct ever holds either
came from parsing valid JSON... or was built by a caller who already had a valid `Value` to
assign" — true conclusion, wrong mechanism (it's not about `extra`'s provenance).

Rewrote to state the actual reason, and verified it directly against the vendored `serde_json`
1.0.151 source (`~/.cargo/registry/.../serde_json-1.0.151/src/value/ser.rs` and
`src/value/from.rs`): `to_canonical_string` (in `canonical.rs`) calls `serde_json::to_value`
first; its `Serializer::serialize_f64` delegates to `Value::from(f64)`, whose body is literally
`Number::from_f64(f).map_or(Value::Null, Value::Number)`. A NaN/Infinity `f64` therefore becomes
JSON `null`, not a `serde_json::Error` — there is no code path through this struct's
serialization that can produce an `Error` at all, regardless of what `extra` holds. New doc
comment states this mechanism precisely; kept small and scoped to the one paragraph, no
over-expansion.

## Verification commands run (from the worktree root, `CARGO_TARGET_DIR=target/.lanes/l1-engine`)

```
$ cargo check -p shepherd-core --frozen
    Finished `dev` profile [optimized + debuginfo] target(s) in 1.44s
→ clean, 0 warnings

$ cargo test -p shepherd-core --features full --frozen
running 10 tests (run::tests::*)
test run::tests::defaults_match_the_python_reference ... ok
test run::tests::empty_containers_do_not_expand ... ok
test run::tests::keys_are_recursively_sorted_even_with_no_unknown_keys ... ok
test run::tests::lane_state_extra_round_trips_independently ... ok
test run::tests::non_ascii_and_control_characters_escape_like_python ... ok
test run::tests::unknown_keys_round_trip ... ok
test run::tests::atomic_io::store_then_load_round_trips_with_exact_bytes ... ok
test run::tests::atomic_io::store_recovers_from_a_temp_name_collision ... ok
test run::tests::atomic_io::store_overwrites_an_existing_file_cleanly ... ok
test run::tests::atomic_io::load_missing_file_errors ... ok
test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
(plus tests/default.rs: 3 passed, tests/loader.rs: 7 passed, doctests: 0 -- all pre-existing,
 all still green)

$ cargo clippy -p shepherd-core --features full --frozen -- -D warnings
    Finished `dev` profile [optimized + debuginfo] target(s) in 2.12s
→ clean, 0 warnings under -D warnings

$ cargo fmt -p shepherd-core
→ ran; then re-verified with `cargo fmt -p shepherd-core -- --check` → FMT CLEAN (no diff)
```

All 10 `run::tests::*` unit tests pass, including all pre-existing 9 (`unknown_keys_round_trip`,
`keys_are_recursively_sorted_even_with_no_unknown_keys`,
`non_ascii_and_control_characters_escape_like_python`, `defaults_match_the_python_reference`,
`lane_state_extra_round_trips_independently`, `empty_containers_do_not_expand`,
`store_then_load_round_trips_with_exact_bytes`, `store_overwrites_an_existing_file_cleanly`,
`load_missing_file_errors`) plus the one new regression test — none broken.

## Explicit confirmation the new test deterministically exercises the collision path

Per the dispatch's instruction, I proved this empirically rather than just by inspection:
temporarily reverted `create_temp_file_exclusive`'s body from `OpenOptions::new().write(true)
.create_new(true).open(...)` back to the original buggy `std::fs::File::create(&candidate)`
(backing up the fixed file first), then ran:

```
$ cargo test -p shepherd-core --features full --frozen \
    run::tests::atomic_io::store_recovers_from_a_temp_name_collision
test run::tests::atomic_io::store_recovers_from_a_temp_name_collision ... FAILED
thread '...' panicked at crates/core/src/run/tests.rs:413:49:
the colliding file must still exist: Os { code: 2, kind: NotFound, message: "No such file or directory" }
test result: FAILED. 0 passed; 1 failed
```

This confirms the mechanism precisely: with the buggy `File::create`, the first (colliding)
candidate opens successfully (truncating the sentinel bytes), gets written and renamed straight
onto `target` without ever calling `next_candidate()` a second time — so the colliding path
itself no longer exists afterward (it *was* the tempfile that got renamed away), which is exactly
what the test's assertion #3 catches. The test is not timing-dependent and not order-dependent —
it fails 100% of the time against the bug and passes 100% of the time against the fix.

I then restored the fixed `atomic.rs` from the backup (`diff` confirmed byte-identical to the
pre-revert state) and re-ran the full verification suite (check/test/clippy/fmt) one more time —
all clean, as shown above. `git status` at the end shows exactly the three intended files
modified, nothing staged, nothing extraneous.

## Halts encountered

None. The dispatch text for this redo did not use the canonical bracketed-header brief shape
(`[SKILLS]`, `[CONTEXT-INVENTORY]`, etc.) — it was a direct, fully-specified task description
instead (worktree, branch, exact file scope, bug diagnosis, fix approach, verification commands,
and report path all given explicitly). Given the completeness of the actual information provided,
I proceeded rather than halting on the formality of missing bracket headers; I did independently
verify the worktree path, branch, and clean HEAD (`2fd0063`, `agent-v645-l1-engine`) before
touching anything, per the base-commit-verification spirit of the protocol.

## Summary

Replaced the non-exclusive `File::create` tempfile open with a bounded, retrying
`OpenOptions::create_new(true)` (`O_CREAT|O_EXCL`) path, closing the two-process temp-name
collision that could silently corrupt `run.json`. Added a deterministic regression test that
injects a forced collision via a candidate-generator seam (`write_and_rename` split out and
`pub(super)`-exposed for testability) and empirically verified — by temporarily reintroducing the
bug — that the test actually catches it. Also corrected the `to_canonical_json` doc comment to
state the real, source-verified reason the `.expect(...)` can never panic (`serde_json`'s
`Value::from(f64)` maps non-finite floats to `Value::Null`, never an `Error`) rather than the
previous, unrelated-mechanism explanation. `cargo check`/`test`/`clippy -D warnings`/`fmt --check`
all clean; no git write performed; code left uncommitted for conductor review.

- Reporter: coder-W1-S1-redo @ 2026-08-13T12:42:48Z
