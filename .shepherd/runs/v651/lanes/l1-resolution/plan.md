# Lane `l1-resolution` — run `v651`

Projection of `.shepherd/runs/v651/plan.md` §`L1-S1`, §`L1-S2`, §`Lane map`,
§`Global constraints`, §`Gates`. The master plan is the authority; this file is the
lane's live execution ledger, self-healed by the conductor at boot because
`.shepherd/runs/v651/lanes/l1-resolution/` was empty.

- **Deliverable:** D2 — issue #330
- **Worktree:** `.worktrees/v651-l1-resolution` · **branch:** `v651-l1-resolution`
- **Base commit:** `c7cc9c0`
- **Integration owner:** root (`shepherd`) — root gates and closes this lane.
- **`file_scope.exclusive`:** `crates/cli/src/dispatch_store.rs`,
  `crates/cli/tests/dispatch_store.rs`, plus this lane namespace.

## Steps

| Step | State | Evidence |
|---|---|---|
| `L1-S1` reproduce #330 and record the abort | done | `sandbox.sh`, `evidence/pre-fix.txt` |
| `L1-S2` a directory without `run.json` is not a run, and there is one resolver | done | `evidence/red-test.txt`, `evidence/post-fix.txt` |

## What landed

`resolve_active_run` is now one shared implementation in the outer module
(`crates/cli/src/dispatch_store.rs`). `grep -c 'fn resolve_active_run'` = **2**
(the public method plus the shared body), down from 3.

Per-platform residue, behind the narrowest `cfg` that still works:

| Hook | `#[cfg(unix)]` | `#[cfg(not(unix))]` |
|---|---|---|
| `platform::open_runs_root` | returns `OwnedFd`, the anchor held across enumeration | returns `()`; anchoring is per-component and re-checked at each open |
| `platform::read_run_document` | `openat` through the anchor; absorbs `open_run_dir` | path-based via `safe_fs`, anchor is unit |

Enumeration, name filtering, sort/dedup, and the `0 => NoActiveRun / 1 => Ok /
_ => AmbiguousActiveRuns` decision are platform-free and exist once.

The skip is **absence only**. `is_not_found` was hoisted out of both platform
modules into one outer-module helper. A corrupt document still raises
`InvalidRunDocument`; a linked or non-regular one still raises `UnsafePath`,
because `unsafe_path_or_io` sends `ELOOP`/`ENOTDIR` there before absence is ever
considered. No new error variant and no new message string: the fix reaches the
pre-existing `DispatchStoreError::NoActiveRun`, exactly as mesh R36h predicted.

## Gate ledger

| Gate | Result |
|---|---|
| `W0-GATE` reproduce before repair | PASS — `evidence/pre-fix.txt`, advisory -> deny -> advisory |
| `GATE-EXECUTION` `test result: ok. N passed`, N > 0 | PASS — lane suite `ok. 12 passed; 0 failed` |
| `cargo test -p shepherd-cli --locked` (whole package) | PASS — exit 0, 26 binaries, 202 passed, 0 failed |
| `cargo test --workspace --locked` | PASS — exit 0, 53 binaries, 414 passed, 0 failed |
| `cargo clippy -p shepherd-cli --all-targets -- -D warnings` | PASS — exit 0 |
| `bash hooks/tests/run.sh` | UNCHANGED from base — `29/29 tests ran, 2 failed`, both in `test_workflow_meta_gate.sh` (lane `l6-gate-wiring`) |
| `./scripts/check-plugin.py` | PASS — all 10 rules hold |

## Deviations

(append-only)

1. **`L1-S2`'s throwaway-worktree falsification is unexecutable and was substituted.**
   The acceptance block calls `git worktree add --detach "$wt" 1c39f4c` and
   `git worktree remove --force`. Worktree add/remove/prune is hook-denied to every
   role except the top-level orchestrator, and G11 bars implementers from git
   entirely, so no role in this lane can run it. Substituted an
   evidence-equivalent test-first RED capture at `HEAD`: the regression tests were
   authored and measured against the unmodified resolver *before* the fix was
   dispatched. This is exactly equivalent because
   `git diff 1c39f4c HEAD -- crates/cli/src/dispatch_store.rs crates/cli/tests/dispatch_store.rs`
   is empty — both files are byte-identical between `1c39f4c` and `c7cc9c0`.
   Recorded in `evidence/red-test.txt`.

2. **`L1-S2`'s final acceptance clause does not measure #330 and cannot be repaired
   in this lane.** The clause is
   `bash .../sandbox.sh 2>&1 | grep -qv 'os error 2'`. Two independent problems:
   - Under POSIX `grep`, `-qv` succeeds when *any* line lacks the string, which is
     true of every heading the script prints. It passes against the broken build and
     can never fail — a gate in the exact Class B family this sprint exists to close.
   - On this host `grep` resolves to **ugrep 7.5.0**, which shadows `/usr/bin/grep`
     and disagrees with POSIX here: with 88 non-matching lines present,
     `/usr/bin/grep -qv` exits 0 while `ugrep -qv` exits 1. ugrep appears to apply
     the inversion to the overall found/not-found result rather than to line
     selection.
   - Independently of which `grep` wins, the clause is wrong for D2: post-fix the
     sandbox output still legitimately contains `os error 2`, from the **#315** deny
     over `runs/<run>/dispatch/.root-session.*.json`, which lane `l4-diagnostics`
     owns.
   Replaced with a positive assertion, in `sandbox.sh --mode expect-fixed`: no probe
   names a path under `runs/v500/`, and the advisory probes read
   `no executing shepherd run exists`.

3. **`estimated_loc: -40` not met as written.** `crates/cli/src/dispatch_store.rs` is
   `+124 / -100`, net **+24**. Duplicated logic did shrink (~80 lines of twinned
   resolver deleted, ~45 lines of shared body added); the surplus is doc comments
   explaining why absence is the only tolerated failure and why the resolver is
   deliberately not twinned. Net code shrank; net lines did not.

4. **`W1-GATE`'s failure budget is stated in a unit the runner does not report.**
   The gate allows "at most 1 failure (`test_workflow_meta_gate.sh`)".
   `hooks/tests/run.sh` reports `29/29 tests ran, 2 failed` — 2 failing *assertions*
   inside that 1 file. Identical to the `c7cc9c0` baseline in
   `evidence/baseline-hooks.txt`, so this lane regresses nothing, but the gate needs
   a unit before it can be evaluated literally.

5. **#315 is now unmasked and is NOT closed by this lane.** With the run at
   `status=executing` the PreToolUse envelope still denies, now over
   `runs/<run>/dispatch/.root-session.<session>.json`. That is issue #315,
   correctly fail-closed, owned by `l4-diagnostics`. Mesh R36g predicted it and
   `L1-S1`'s interfaces name `L4-S1` as this sandbox's consumer. `sandbox.sh`
   reports it as a labelled non-fatal NOTE, not a failure.

6. **The lane plan did not exist.** `.shepherd/runs/v651/lanes/l1-resolution/` was
   empty at boot; this file was self-healed from the master plan's lane projection.

7. **`resolve_primary` does not affect this lane** (finding relayed from
   `conductor-l3`, `crates/cli/src/context.rs:608-612`: in a linked worktree the
   primary root resolves to the main checkout). The Rust tests never call it — they
   hand `DispatchStore::new` an absolute canonical path under `std::env::temp_dir()`
   — and `sandbox.sh` builds a standalone `git init` repo under `mktemp -d`, not a
   linked worktree, so `git_dir == common` and the primary resolves to the sandbox
   itself. Confirmed empirically: every recorded banner names a sandbox path. The
   fix's correctness is independent of which tree is primary, because
   `resolve_active_run` operates on the runs root it is handed.
