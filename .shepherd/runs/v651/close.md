# v651 — close

Run `v651`, branch `v6.5.1`, base `main`. Closed 2026-08-19.

## Verdict

The sprint shipped. Every lane merged, every gate is green, and the defect that
started it — `shepherd init` printing a remediation that refuses to run — is
fixed with a lint that derives the gated-subcommand map from the CLI's own
refusal text rather than a hardcoded list, so the class cannot recur silently.

What the sprint actually turned out to be about was not the founding bug. It was
about **gates that existed and did not gate**. Fifteen were found. Three of them
I authored during this sprint, which is the part worth remembering.

## Measured against plan

| | Planned | Actual |
| --- | --- | --- |
| Lanes | 7 | 13 |
| LOC | +465 | +13396 / −1131 across 152 files |

The plan gated at 7 lanes and 13 ran. That is the honest cause of the delta, not
scope creep in the code: **46% of insertions are `.shepherd/` run artifacts**
(6220 lines across 32 files) — lane plans, evidence dumps, worklists. Production
and tooling changes are `scripts/` (+2268), `crates/` (+1956), `hooks/` (+1164),
`.github/` (+965).

The plan's +465 estimate was written against 7 lanes with no allowance for run
artifacts at all. A plan that estimates only production lines will always
under-report a sprint that keeps its evidence on disk. Next plan states both
numbers separately.

## Gates that existed and did not gate

The recurring shape: a check that is correct, falsifiable, and **executed by
nothing**, or one whose assertion cannot fail on the platform where development
happens.

- **`scripts/tests/test_cli_authority_gate.sh`** — referenced by no runner, no
  workflow, no suite. Running it for the first time found it **red**, with three
  independent failures accumulated undisturbed: an `rg` sweep over `$ROOT/bin`
  (a directory D4 retired, so rg exited 2, and inside an `if` that took the same
  branch as "clean"); a `hooks.json` assertion demanding the native shape for
  every hook, false since the seven carrier scripts were restored; and three
  lifecycle assertions still aimed at `claude_hook.rs` after the lifecycle moved
  to `native_hook.rs`. An unwired gate does not stay merely useless. It rots
  until it is wrong.
- **80 shell assertions** that could not say what they enforced, **10 of which
  could not fail at all** — bash 3.2 ignores `set -e` for a failing `[[ ]]`, and
  macOS cannot ship newer, so they were inert on the development platform.
- **`test-codex-marketplace.sh`** pinned a third-party CLI to an exact version.
  Codex shipping 0.148.0 turned it red with nothing here regressed — and the
  pin was short-circuiting three later assertions that were all wrong.
- **`hooks/tests/test_plugin_contract.sh`**, which I wrote in `0e2d27b` claiming
  it "falsifies itself by drifting a scratch carrier." Its scratch copy omitted
  `.agents/` and `content/`, so the checker exited non-zero on the **undrifted**
  copy. It was vacuous from the hour it was written and would have stayed green
  had the checker stopped comparing bytes entirely.
- **`scripts/check-plugin.py`** scanned only the root `hooks/hooks.json`, never
  the carrier's — which is why the shipped plugin registered seven hook scripts
  it did not ship, for four releases.
- **`owned by the Rust CLI in vX.Y.Z`** in the README was listed as a *historical
  marker* in `version-bump.py`, exempting it from the residual version scan. No
  rule rewrote it and no scan complained, so it sat at v6.4.5 across two
  releases.
- **`## v6.5.0 — unreleased`** was tagged and released on 2026-08-18 with that
  header intact. `release.yml` extracts release notes verbatim from CHANGELOG.md,
  so the published release announced the shipped version as unreleased.

Each is now closed structurally rather than by fixing the instance:
`scripts/check-gate-wiring.py` asserts every test file is reachable from a
runner (transitively, treating glob discovery as first-class wiring);
`hooks/tests/lint_shell_assertions.sh` bans both bare forms;
`test_changelog_current.sh` uses git tags as the oracle for what shipped.

## The near-miss

Three sites in `hooks/scripts/_lib.sh` were on my conversion list and I called
them "the priority." They are the final expression of predicate functions, where
the exit status **is** the boolean result. Guarding them would hard-exit on the
negative branch — `quiet_warnings` defaults to false, so every hook would have
died for every operator who had not opted in. Because l12 made that file ship in
the carrier, it would have reached the delivered plugin.

They were left untouched and the lint carries the exclusion. This is recorded
because the conversion was mechanical and correct 80 times, and wrong 3 times
for a reason no count would surface.

## Deviations

- **l7** was told to build a shared helper under `hooks/tests/lib/` and did not:
  a `[[ ]]` condition cannot be passed to a helper without `eval`. Two
  acceptance lines are therefore unsatisfied. The lane did **not** paper over
  this by creating an empty directory, which is the move this sprint spent the
  day deleting.
- **#332** barred dispatching gate roles, so several lanes were reviewed by
  their own lead read-only and gated at root instead.

## Seed verification

```
shepherd seed verify .shepherd/runs/v646/seed.md   rc=0  (0 hard failures, 2 warnings)
shepherd seed verify .shepherd/runs/v651/seed.md   rc=0  (0 hard failures, 1 warning)
```

## Final state

```
cargo test --workspace --locked   435 passed, 0 failed, 53 suites
hooks/tests/run.sh                30/30 ran, 0 failed
scripts/gate.sh fast              green in 18s
scripts/check-plugin.py           10/10 rules
scripts/check-gate-wiring.py      57 test files, all reachable
actionlint                        9/9 workflows clean
shepherd seed verify              v646 rc=0, v651 rc=0
```

`gate.sh fast` is green in a single tree for the first time this sprint.

## Carried forward

- **Dependabot: 3 open alerts on `decompress` (1 critical, 2 medium), no patch
  available upstream.** Contained, and verified so rather than assumed: the root
  package is `private: true`, `@bytecodealliance/jco` is a devDependency of that
  private root only, and the chain is `jco → componentize-js → weval →
  decompress`. None of the four published packages reference it — each declares
  exactly one dependency. Exposure is the build machine extracting archives
  during component generation, not any user of a published package. Revisit when
  upstream publishes a fix.
- Splitting `rust.yml` into `cargo-check.yml` / `cargo-test.yml`, following the
  `cargo-build.yml` pattern established here.
