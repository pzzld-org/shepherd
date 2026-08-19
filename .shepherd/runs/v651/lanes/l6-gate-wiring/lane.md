# Lane `l6-gate-wiring` — run v651, wave 2

Self-healed by the lane conductor from the master plan's lane projection
(`.shepherd/runs/v651/plan.md` §Lane map, L6-S1/L6-S2/L6-S3); the lane directory was
empty at boot.

- **branch:** `v651-l6-gate-wiring`  **base:** `b0ad8aa`  **worktree:** `.worktrees/v651-l6-gate-wiring`
- **deliverables:** D7, D8, D1 residual wiring
- **file_scope.exclusive:** `.github/workflows/rust.yml`, `scripts/check-workflow-meta.sh`,
  `hooks/tests/test_workflow_meta_gate.sh`, `hooks/tests/fixtures/`

## Steps

| Step | Owner | Status |
|---|---|---|
| `L6-S1` negative control stops needing git history | coder `l6s1-fixture` | dispatched |
| `L6-S2` shell gate tier runs in CI, a skip in CI is a failure | coder `l6s23-ci` | dispatched |
| `L6-S3` CI stops hand-copying the gate list | coder `l6s23-ci` | dispatched |

## Verified baselines at `b0ad8aa`

- `cargo test --workspace --locked` — 417 passed, 53 test targets executed.
- `bash hooks/tests/run.sh` — `FAIL: hooks/tests/run.sh (29/29 tests ran, 1 failed)`;
  the single failure is `test_workflow_meta_gate.sh` (L6-S1's defect).
- `bash scripts/gate.sh fast` — `gate (fast): 5 check(s) failed in 16s`, exit 1. See below.

## Measurement — `scripts/gate.sh:110`

Conclusion: **delete `:110` and correct the stale comment at `:102-109`.** No corrected step
is warranted; none could be justified by measurement.

1. `cargo test --workspace --locked --all-features` → `error[E0554]`, does not compile.
   `--all-features` enables `nightly` (`crates/core/Cargo.toml:111`), which gates
   `#![cfg_attr(feature = "nightly", feature(allocator_api))]` (`crates/core/src/lib.rs:46`);
   `rust-toolchain.toml` pins stable `1.97.0`. The step has never run.
2. The comment at `:102-109` claims `:101` executes 3 of 126 core tests, "including none of
   the guard engine's 66". Measured under plain `cargo test --workspace --locked`:

   | core target | tests executed |
   |---|---|
   | `shepherd_core` (lib) | 5 |
   | `tests/dispatch.rs` | 15 |
   | `tests/guard.rs` | 69 |
   | `tests/loader.rs` | 25 |
   | `tests/portable_dispatch.rs` | 7 |
   | `tests/run_state.rs` | 6 |
   | **total** | **127** |

   All five feature-gated targets run, including every guard-engine test. The comment is
   stale in every particular for the invocation it annotates.
3. The 3-of-126 skip reproduces ONLY single-crate: `cargo test -p shepherd-core --locked`
   → 3 passed.
4. No target `:101` misses could be constructed. Every `required-features` in the workspace
   is `std` / `parse` / `json` / `bundled` / `layout`, all satisfied by workspace feature
   unification (`shepherd-cli` pulls `full` into `shepherd-core`); `registry`, `layout` and
   `migrate_layout` all execute. `nightly` is the only feature `--all-features` adds beyond
   unification, and it is precisely the one that cannot compile on the pinned toolchain.

`scripts/gate.sh` is outside this lane's file scope (L6-S3 declares
`must_not_touch: scripts/**`). Escalated to root for routing.

## Blocker — `gate.sh fast` is red at base, and CI cannot see it

Reproduced on the `v6.5.1` integration checkout as well as at `b0ad8aa`.

| failed step | cause | owner |
|---|---|---|
| `npm adapter dependency rules are falsifiable` | `ERR_MODULE_NOT_FOUND`, no `node_modules/` | environmental; lint job gains an install step |
| `npm adapter dependency rules` | same | same |
| `release distribution legal material` | needs `node_modules/@bytecodealliance/preview2-shim` | same |
| `Cargo publisher recovery contract` | fails because of the row below | l2 / l3 |
| `release version authority` | `version-bump.py` reports three `unclassified 6.5.1 version surface` errors | l2 / l3 |

The three unclassified surfaces: `content/predicates/write-boundary.toml` (l2),
`crates/compiler/package-content/content/predicates/write-boundary.toml` (l2, projection),
`scripts/check-version-lag.py` (l3). Classifier: `scripts/version-bump.py:672`, error at `:699`.

`grep -n 'version-bump\|check-cargo-distribution\|check-deps\|distribution-license'
.github/workflows/rust.yml` returns nothing — the lint job hand-copies 5 of `gate_fast`'s
~35 steps and none of these is among them. #328 is green while the declared tier is red.
That is the Class B defect this lane exists to close, live at plan base.

## Plan claims contradicted

1. **L6-S2 action 2 is unexecutable as written.** It directs edits to eight `hooks/tests/*.sh`
   skip branches that L6-S2's own `file_scope.must_not_touch: hooks/tests/**` forbids and
   that this lane does not own. Enforced instead inside `.github/workflows/rust.yml`: install
   `jq`/`python3` so no skip fires legitimately, then assert zero `SKIP` lines, `0 failed`,
   and a count `>= 29`. One enforcement point rather than nine hand-copied ones.
2. **The skip class is 9 sites, not 8.** The plan misses
   `hooks/tests/test_harness_parity_generator.sh:55` (a second `jq` skip, distinct from the
   `:463` artifact skip it does list). 8 files, 9 sites.
3. **L6-S1 prose contradicts its own acceptance.** Prose says remove `686084d` references
   "outside comments"; the acceptance `git grep -c 686084d scripts/ hooks/ | wc -l` = 0
   cannot hold while a comment carries the string. Resolved in the stricter direction.
4. **`gh pr checks 328` is not dischargeable by this lane.** It appears in L6-S2 and L6-S3
   acceptance, but this lane commits to `v651-l6-gate-wiring` and is instructed not to touch
   #328. Owned by root at integration.

## ripgrep

Exactly two dependents, confirming root's finding:
`hooks/tests/test_run_scoped_hook_state.sh:36` and
`hooks/tests/test_registered_hooks_no_python.sh:27`. `scripts/check-workflow-meta.sh` uses
none. Both call sites are outside this lane's file scope, so a `grep` conversion is not
available; ripgrep is installed in the `lint` job instead.

## GATE-REACHABILITY

Seed gate 2 discharged as one table. Every gate this lane touched or added, with the
command that runs it in CI **and** the falsification proving it fails on purpose.

The `evidence` column is the distinction that matters and is stated per row: **live** means
the failure was observed at this lane's base commit without contrivance; **contrived** means
the assertion was proven able to fire by constructing an input. A contrived falsification is
a regression guard, not a repair. Five gates in this repository failed exactly this
distinction, so it is not left implicit.

| # | Gate | Command that runs it in CI | Falsification | evidence |
|---|---|---|---|---|
| 1 | workflow-meta pure-literal `meta` check (`scripts/check-workflow-meta.sh --self-test`) | `carrier` job -> `bash hooks/tests/run.sh` -> `test_workflow_meta_gate.sh` | NEGATIVE control rejects `hooks/tests/fixtures/df69-concatenated-meta.js`, naming the reason: `BinaryExpression: a '+' operator is present outside any string literal`. At base the self-test itself failed: `FAIL  --self-test exited 1` | **live** |
| 2 | hook carrier suite (`bash hooks/tests/run.sh`) | `carrier` job, step 7 | At base `b0ad8aa`: `FAIL: hooks/tests/run.sh (29/29 tests ran, 1 failed)`, exit 1. `run.sh:22-25` additionally fails loudly on zero discovered tests | **live** |
| 3 | no-SKIP assertion (the silent-skip class) | `carrier` job, step 7 — greps the captured log, `grep` exit 2 handled separately from exit 1 | With `jq` removed from `PATH` the suite emits 7 `SKIP` lines and 7 tests pass vacuously | **contrived** |
| 4 | hook-count floor (`>= 29`, `MIN_HOOK_TESTS`) | `carrier` job, step 7 | Parsed from the summary line; fires when discovery loses files. Historical precedent is real: `ffd9aea` shipped a hand-maintained array covering 6 of 27 files (`run.sh:4-9`) | **contrived** |
| 5 | gate toolchain resolves (`jq python3 node npm rg`) | `lint` step 5 and `carrier` step 5 | Remove any one tool from `PATH`; the step exits 1 rather than letting a downstream gate skip | **contrived** |
| 6 | `scripts/gate.sh fast` — the declared tier, replacing five hand-copied steps | `lint` job, step 6 | At base: `gate (fast): 5 check(s) failed in 16s`, exit 1 — including two failures CI structurally could not see | **live** |
| 7 | compiler package projection (`generate-compiler-package-content.py --check`) | `lint` job, step 7 | `scripts/tests/test-generate-compiler-package-content.py`, 3 tests, itself run by `gate_fast`. Holds with a count: `ok: compiler package content has 23 byte-exact sources` | falsification test exists and runs |
| 8 | version authority (`scripts/check-version-lag.py`) | `carrier` steps 8 (`--self-test`) and 9 (holds) | `self-test: 14 cases passed`; and the step fails on `checked: 0`, plus exit 2 reported as "could not look" rather than folded into the verdict | self-test proven; see caveat |

**Caveat on row 8, disclosed rather than buried.** The binary is built from this tree, so its
version equals the manifest version by construction and the comparison cannot fail on a
runner. What the CI step genuinely enforces is that the check RAN and compared something
(`checked:` non-zero). The lag the tool was written for — a developer's installed binary from
a previous release — is caught by the local hook, not by CI. This is stated in a comment in
`.github/workflows/rust.yml` above the step.

**Carry-forward, not built here.** The only variant that would catch a real lag in CI is
comparing the **published** (crates.io) binary against the tree's manifest, which would catch
"manifest bumped but crate never published". That is genuinely valuable and is the same
defect class as this plan's Q4 (four npm packages stuck at 6.4.5 across three releases with
nothing noticing). It needs network and it changes what the gate means, so G2 ("no new
subsystem") puts it out of scope for this sprint. Recorded for the next one.

## Integration posture

This lane did **not** merge `v6.5.1` (`6e01672`) into `v651-l6-gate-wiring`. Cross-lane
version-control integration is the integration owner's exclusive job, and the repository's
dispatch hook denies merge/rebase to every role except the top-level orchestrator. The lane
branch therefore still forks from `b0ad8aa` and its own CI will show the two version-authority
failures that `l8-version-surfaces` already fixed upstream. **A CI result on this branch in
isolation is not meaningful for those two steps.** Root resolves at integration.

The two facts compose without a merge, and the arithmetic closes exactly:

| state | `gate.sh fast` failures | which |
|---|---|---|
| base `b0ad8aa`, no `node_modules/` | **5** | 3 node + 2 version surfaces |
| `6e01672`, no `node_modules/` (root measured) | **3** | the 3 node ones |
| base `b0ad8aa`, after `npm ci --ignore-scripts` (this lane measured) | **2** | `Cargo publisher recovery contract`, `release version authority` — the 2 version surfaces |
| both together | **0 expected** | `l8` cleared 2, this lane's install step clears 3 |

5 = 3 + 2 with no overlap, so the tier reaches green on the merge candidate without either
change being weakened. Neither half was verified in the same tree as the other; that
composition is root's to confirm at integration.
