---
title: v6.5.1 Sprint Plan — connect the gates that already exist
run: v651
runId: v651
branch: v6.5.1
base: main
seed: .shepherd/runs/v651/seed.md
mesh: .shepherd/runs/v651/mesh.md
author: shepherd-engineer-v651
date: 2026-08-18
plan_base_commit: 0e2d27b
sprint_size: M
waves: 4
lanes: 7
milestone: 61
max_parallel: 3
status: draft-pre-critic
---

# v6.5.1 Implementation Plan

**Goal:** Make every gate this repository already owns reachable from an automated path,
and delete the duplication and the archaeology that keep three of them from running at
all. Nothing here is a new capability.

**Architecture:** No new subsystem, no new framework, no new gate engine. Seven
file-disjoint lanes over the seed's `file_scope.exclusive` partition, three waves bounded
by `[spawn] max_parallel = 3` in `.shepherd/shepherd.toml`, then a close wave.

**The theme, restated as the plan's own test:** work verified by a script no automated path
invokes is not verified. This plan is graded by whether a v6.5.2 author can reintroduce any
of these thirteen defects and be stopped by a machine rather than by memory.

---

## Verified baseline (engineer-run, central)

Measured directly at `0e2d27b`, not inherited from the seed. Every row is a command this
engineer ran in this tree.

| Check | Result | Bears on |
|---|---|---|
| `gh pr checks 328` | **22 rows, all `pass`, 0 `fail`** | **D1 already satisfied** |
| `gh pr view 328 --json headRefOid` | `0e2d27b8704d…` = local `HEAD` | evidence is current |
| `./scripts/generate-codex-carrier.py --check` | `ok: … byte-exact regular-file projection`, exit 0 | D1 |
| `./scripts/check-plugin.py` | `ok: all 10 plugin contract rules hold.`, exit 0 | D1 |
| `bash hooks/tests/run.sh` | **`FAIL: … (29/29 tests ran, 2 failed)`** | **seed says 28 — wrong** |
| failing tests | `test_native_cli_contract.sh`, `test_workflow_meta_gate.sh` | L2, L6 |
| `shepherd ready --run dummy` | `ERROR: open state directory …: No such file or directory (os error 2)`, `EXIT=5` | D4 |
| `shepherd models resolve shepherd --harness claude` | `ERROR: unknown role: shepherd (valid: root planter …)`, exit 2 | D10 |
| `which shepherd` / `shepherd --version` | `/Users/jo3/.cargo/bin/shepherd` / **`shepherd-cli 6.5.0`** | **stale vs manifest 6.5.1** |
| `grep -c "fn resolve_active_run" crates/cli/src/dispatch_store.rs` | `3` (`:98`, `:236`, `:888`) | D2 |
| `diff content/predicates/dispatch-scope.toml crates/compiler/package-content/…` | identical | L2 |
| `git check-ignore -v .shepherd/ctx/.gitkeep` | exit 1 — **not ignored** | D12 |
| `git status --ignored --short .shepherd/runs/` | only `v651/run.json`, `v651/run.lock` | D12 |
| npm `@pzzld/{component-runtime,pi-shepherd,pi-claude,pi-codex}` | all `6.4.5`, published 2026-08-15 | D5 (out of scope) |
| `gh api …/branches/main/protection` | **HTTP 404 `Branch not protected`** | CLOSE gate |

---

## Seed corrections — claims this wave contradicted

A seed is evidence, not instruction. Six claims did not survive measurement. Each is
corrected here and the correction binds the lane that inherits it.

| # | Seed claim | Measured | Consequence |
|---|---|---|---|
| C1 | `open_pr: 328 … currently RED (mesh R10)`; deliverable D1 "Codex carrier projection is regenerated and CI goes green" is CRITICAL and "blocks every other item's evidence" | **PR #328 is GREEN — 22/22 checks pass at `0e2d27b`.** `generate-codex-carrier.py --check` and `check-plugin.py` both exit 0 | **D1 is satisfied at plan base.** The `carrier` partition has no repair left and is dissolved; its files become read-only context for L6, which supplies the missing *wiring*. The seed's "carrier first" ordering is void |
| C2 | `bash hooks/tests/run.sh` exits 0 and prints **`28/28 tests ran, 0 failed`** (D8 acceptance) | **`29/29 tests ran, 2 failed`.** `0e2d27b` added `hooks/tests/test_plugin_contract.sh`; discovery is `find . -maxdepth 1 -name '*.sh' ! -name run.sh` (`hooks/tests/run.sh:18`), so it also counts `lint_agent_capabilities.sh` | A hardcoded `28/28` acceptance is unsatisfiable **and** is the v646 carry-forward §4g anti-pattern (a gate fitted so tightly to the artifact that improving the artifact breaks it). D8's acceptance is restated as `0 failed` plus a **minimum** count |
| C3 | "The target-keyed restriction in `content/predicates/dispatch-scope.toml` names only `engineer` and `critic`. Extend it" | The TOML names neither. The enforced list is Rust: **`crates/core/src/guard/engine.rs:661-666`**, `matches!(… Some("engineer" \| "critic"))`. The TOML carries the rule's prose and its examples | D5 is a two-file change — the `matches!` arm **and** the TOML description plus a new `[[example]]` — followed by regenerating `crates/compiler/package-content/content/predicates/dispatch-scope.toml`. Editing only the TOML changes nothing an operator can observe |
| C4 | `sprint_metadata.expected_loc_delta: negative`, "the largest single change deletes a duplicated resolver" | The resolver deletion is ~40 lines. D9 converts **118** bare `rg -Fq` sites; the v646-prescribed `if ! rg -Fq …; then printf …; exit 1; fi` expansion is +2 lines each ≈ **+236** | Negative delta is unreachable via the prescribed expansion. **G7 below binds D9 to a one-line helper call per site**, which keeps the sprint flat. A lane that expands the sites inline violates the seed's own metadata |
| C5 | #306 and #307 are triaged as v6.5.1 work / out-of-scope-with-no-milestone | Both already carry **milestone 60 (`v6.4.6`)**, not null | The milestone lane must not silently re-file them. #306 stays in L4 as a *re-measurement*, and its milestone is left alone unless the re-measurement closes it |
| C6 | §H CLOSE: "`gh pr checks 328` reports zero `fail` rows" is the sprint's definition of done | True **today**, and `main` has **no branch protection and no required checks** (HTTP 404) | "CI green" is a discipline this repo chooses, not one GitHub enforces. Recorded as **Q3** for the critic and the operator; a red #328 can still be squash-merged by hand |

Two further findings the seed does not contain, both plan-shaping:

- **C7 — ripgrep is not preinstalled on any GitHub-hosted runner.** Exactly two hook tests
  need it: `hooks/tests/test_run_scoped_hook_state.sh` and
  `hooks/tests/test_registered_hooks_no_python.sh`. `scripts/check-workflow-meta.sh` uses
  none. D8 must therefore either install `rg` on the runner or convert those two call
  sites; L6 owns the decision and records which it took.
- **C8 — the hook tier contains a silent-skip class.** Seven tests exit 0 with a `SKIP`
  line when `jq` or `python3` is absent (`test_bash_post_ledger.sh:13`,
  `test_cwd_changed_telemetry.sh:13`, `test_description_budget.sh:28`,
  `test_pi_manifest_drift.sh:48`, `test_subagent_telemetry.sh:14`,
  `test_seed_preflight_check.sh:50`, `test_run_scoped_capture.sh:13`), and
  `test_harness_parity_generator.sh:463` skips on a missing `.shepherd/runs/v646/`
  artifact. Wiring the suite into CI without asserting its prerequisites buys a job that
  prints `29/29 tests ran, 0 failed` while eight of them checked nothing. That is the
  sprint's own theme one level out, and L6 must close it in the same change.

---

## The two failure classes this plan makes structurally unreachable

Root's own two misses this sprint are the sprint in miniature. Detecting them again is not
enough; each gets a mechanism that removes the possibility.

### Class A — an assertion measured against a target that was never built

`~/.cargo/bin/shepherd` reports **6.5.0** against a **6.5.1** manifest. Every bare
`shepherd …` acceptance in the seed therefore grades a binary that is one release behind
this tree, and can pass or fail for a reason unrelated to the change under test. The same
shape hid 123 of 126 `shepherd-core` tests behind unmet `required-features` in v6.4.6
(carry-forward §0b), and `test result: ok. 0 passed` is indistinguishable from success.

**Mechanism, binding on every lane (G3, G4):** no acceptance in this sprint invokes a
`shepherd` resolved from the ambient `PATH`. Every acceptance block begins by building this
tree and putting *that* binary first, and every Rust acceptance prints its executed test
count so a zero is visible. `scripts/check-version-lag.py` (L3) then makes the ambient-stale
condition a machine-detectable failure rather than an operator's private knowledge.

### Class B — a gate that only exists where its author cannot see it

`./scripts/check-plugin.py` ran in CI's `fmt + workspace invariants` job
(`.github/workflows/rust.yml:105-108`) and from `scripts/gate.sh:90-91`, and nothing an
author runs before pushing invoked either. `cc07276` shipped carrier drift and learned about
it from a red build. `0e2d27b` closed that one instance by adding
`hooks/tests/test_plugin_contract.sh`; the *class* is still open, because
`.github/workflows/rust.yml` hand-copies five of `scripts/gate.sh`'s ~30 steps and nothing
compares the two lists.

**Mechanism (L6-S3):** the CI shell tier stops being a hand-copied step list. CI invokes the
same named commands the project already declares — `.shepherd/shepherd.toml` `[gates] check
= "scripts/gate.sh fast"` and `[gates.extra] hooks = "bash hooks/tests/run.sh"` — so a gate
added locally is in CI by construction and a CI step that no operator can run cannot exist.
`./scripts/check-plugin.py` already verifies that `configured gates resolve`, which makes
that config the load-bearing single list rather than documentation.

---

## Global constraints

Every step's requirements implicitly include this section. Steps cite these as **G1**–**G12**
by the numbers below; a step that names `G7` means item 7 of this list.

1. **The seed's five locked decisions (§D) bind**, as corrected by C3. Changing one is a
   critic-RED escalation, not a sprint-time judgement. In particular: do **not** remove the
   `tool_name != "Workflow"` carve-out at `crates/core/src/guard/engine.rs:401`; do **not**
   restore commit `686084d`; do **not** publish to npm.
2. **No new subsystem.** The seed's `subtract_note` makes a new framework or gate engine a
   critic-RED escalation. Two new files are sanctioned by the seed's `file_scope` and no
   others: `scripts/check-version-lag.py` and the contents of `hooks/tests/fixtures/` and
   `hooks/tests/lib/`.
3. **Binary provenance (Class A).** Every acceptance block starts with:
   ```bash
   cargo build --locked -p shepherd-cli --bin shepherd
   export PATH="$PWD/target/debug:$PATH"
   ```
   and no step asserts against a `shepherd` from the ambient `PATH`. A step that cannot do
   this states why in its artifact.
4. **Every gate reports a count and fails at zero** (v646 carry-forward §0b). A Rust
   acceptance quotes its `test result: ok. N passed` line with `N > 0`. A shell gate that
   scans a set fails loudly when the set is empty. `ok` without a count is not evidence.
5. **`rg` exit 2 is an error, not a no-match** (v646 carry-forward §4e). Any assertion this
   sprint writes or touches distinguishes "found nothing" (exit 1) from "could not look"
   (exit 2) and fails on the latter.
6. **Before deleting a duplicated assertion, grep for the gates that require its presence**
   (v646 carry-forward §4g). L1 deletes a resolver copy and L7 deletes 118 bare assertion
   forms; both run the duplicate-risk grep named in their step before deleting.
7. **D9 converts, it does not expand.** Each of the 118 sites becomes a **single-line**
   helper call sourced from `hooks/tests/lib/`, never an inline three-line `if` block. This
   is what keeps `expected_loc_delta` flat (C4).
8. **`hooks/tests/run.sh` executes every `*.sh` at depth 1 of `hooks/tests/`**
   (`hooks/tests/run.sh:18`). A shared helper placed directly in `hooks/tests/` would be
   executed as a test; helpers live in `hooks/tests/lib/`, which the `-maxdepth 1` glob does
   not reach.
9. **No lane edits `skills/**` or `plugins/**`.** If a change genuinely requires it, the
   same step regenerates the carrier and proves
   `./scripts/generate-codex-carrier.py --check` exits 0 before commit. This is the exact
   regression `cc07276` shipped.
10. **`CHANGELOG.md` is additive and shared.** Each lane appends its own bullet under the
    existing `## v6.5.1 — unreleased` heading and touches no other lane's line.
11. **Coders run zero gates and zero git.** They write files and report them; the conductor
    stages after a clean wave review.
12. **At most 3 lanes in flight** (`.shepherd/shepherd.toml` `[spawn] max_parallel = 3`).

---

## Lane map

Seven lanes over the seed's `file_scope.exclusive` list. No file appears in two lanes that
are ever in flight together.

lane: l1-resolution
lane: l2-dispatch-scope
lane: l3-clone-fidelity
lane: l4-diagnostics
lane: l5-vocabulary
lane: l6-gate-wiring
lane: l7-assertions

| Lane | Wave | Deliverables | `file_scope.exclusive` |
|---|---|---|---|
| `l1-resolution` | 1 | D2 (#330) | `crates/cli/src/dispatch_store.rs`, `crates/cli/tests/dispatch_store.rs` |
| `l2-dispatch-scope` | 1 | D5 (#323), D6 (#320) | `content/predicates/dispatch-scope.toml`, `content/predicates/write-boundary.toml`, `crates/compiler/package-content/**` (as produced by `scripts/generate-compiler-package-content.py --write`), `crates/core/src/guard/engine.rs`, `crates/core/tests/guard.rs`, `crates/cli/tests/guard_cli.rs`, `hooks/tests/test_native_cli_contract.sh` |
| `l3-clone-fidelity` | 1 | D12 (#316, #317) | `.gitignore`, `.shepherd/ctx/.gitkeep`, `crates/cli/src/cmd/wave_c_bootstrap.rs`, `scripts/check-version-lag.py` |
| `l4-diagnostics` | 2 | D3 (#315, #314, #306), D4 (#331) | `crates/cli/src/cmd/native_hook.rs`, `crates/cli/src/run_store.rs`, `crates/cli/src/cmd/wave_h_execution.rs`, `crates/cli/tests/claude_hook_cli.rs` |
| `l5-vocabulary` | 2 | D10 (#324), D11 (#319) | `crates/cli/src/cmd/wave_a_models.rs`, `crates/cli/tests/wave_a_models_cli.rs`, `crates/cli/src/cmd/wave_b2_seed.rs`, `crates/cli/tests/wave_b2_seed_cli.rs` |
| `l6-gate-wiring` | 2 | D7, D8 | `.github/workflows/rust.yml`, `scripts/check-workflow-meta.sh`, `hooks/tests/test_workflow_meta_gate.sh`, `hooks/tests/fixtures/` |
| `l7-assertions` | 3 | D9 (#318) | `hooks/tests/lib/`, and every `hooks/**` + `scripts/**` assertion call site |

**Three partition corrections against mesh R64–R71.**

- `crates/cli/src/cmd/wave_h_execution.rs` is in the seed's `file_scope.exclusive` and is
  assigned to **no** partition in R64–R71. It holds `WaveHReadyCmd` (`:331`) and
  `run_error` (`:467-469`), which maps every `RunStoreError` to exit 5 — the exact code D4's
  second acceptance pins. It belongs to `l4-diagnostics`. R71's disjointness claim is true;
  its coverage claim was never made and does not hold.
- `crates/compiler/package-content/content/predicates/dispatch-scope.toml` is the generated
  projection of an in-scope source and is byte-identical to it today. It is named in
  `l2-dispatch-scope` explicitly so the regeneration is owned rather than incidental.
**Two further scope amendments by root, at l2's escalation (2026-08-19).** Both are the
same shape as the `wave_h_execution.rs` correction below: disjointness held, coverage was
never actually claimed.

- **`crates/compiler/package-content/**` replaces the single enumerated projection file.**
  `scripts/generate-compiler-package-content.py --write` emits the projection AND
  `SHA256SUMS` in one write (`:52` builds the lines, `:64` writes the manifest, `:79`
  re-derives it for `--check`). The manifest is a pure function of the projected content,
  so naming two of a generator's three outputs and omitting the third is the Class B defect
  this sprint exists to kill — the same shape as CI hand-copying `scripts/gate.sh`'s step
  list. Verified by l2: `shasum -a 256` of the new projection equals its `SHA256SUMS` row,
  the other 22 rows are byte-unchanged, and `--check` reports `23 byte-exact sources`,
  exit 0. Wave 2's `l6` and `l7` touch generated surfaces and inherit this rule.
- **`crates/cli/tests/guard_cli.rs` is granted to `l2-dispatch-scope`.** It is assigned to
  no lane anywhere in this map, and `l4`/`l5` own different `crates/cli` files in wave 2, so
  there is no live conflict. L2-S1 action 2 adds an `[[example]]`, taking the corpus 17 → 18,
  and that count is hardcoded in FOUR places across TWO crates — `crates/core/tests/guard.rs:567`
  and `:988` (in scope) plus `guard_cli.rs:456` and `:544` (previously unowned). The
  prescribed action therefore necessarily broke two tests the lane was forbidden to fix.
  Root's ruling: do NOT bump `17` to `18`. Parse the `N/M examples passed` line and assert
  `N == M` and `N > 0`. A literal count is a gate fitted so tightly to the artifact that
  improving the artifact breaks it, and bumping it merely re-arms the trap for example 19.
  `GATE-EXECUTION` is satisfied better by the parse, not worse: `crates/cli/src/cmd/guard.rs:424-430`
  already fails closed on `total == 0` with an explicit refusal, and `guard_cli.rs:502-523`
  pins that, so "checked nothing" stays distinguishable from "checked everything and passed".

- `hooks/tests/lib/` is mesh R69's `gate-wiring` file, but the lane map above assigns it to
  `l7-assertions`, because the shared assertion helper it holds is what D9's 118 call sites
  consume. Recording it here rather than leaving it to Q1: a reassignment that appears only
  as an open question is a reassignment nobody agreed to. `l6-gate-wiring` does not touch
  `hooks/tests/lib/`, and `l7-assertions` runs alone after every other lane merges, so the
  move costs no disjointness.

`l7-assertions` claims `hooks/**` and `scripts/**` wholesale and therefore runs **alone**,
after every other lane has merged. Its disjointness is temporal, which is exactly the
condition `skills/start/SKILL.md` states: *"The lane's file scope is disjoint from every
lane currently in flight."*

---

## Wave 1 — the resolver, the guard, and the clone

**Wave gate (`W1-GATE`):** `cargo test --workspace --locked` exits 0 and prints a non-zero
total; `bash hooks/tests/run.sh` reports at most **1** failure
(`test_workflow_meta_gate.sh`, which L6 owns); `./scripts/check-plugin.py` reports 10/10.

**`W0-GATE` applies inside each lane, not as a separate wave.** The seed §H.1 requires every
CRITICAL and HIGH deliverable to reproduce as a failure with its exact output recorded
before any fix lands. Each lane's `S1` is that reproduction and its artifact carries the
literal failing output. A lane whose `S1` cannot reproduce the defect halts and escalates
rather than writing a fix for a defect it has not seen.

### L1-S1 — reproduce #330 in a clean sandbox and record the abort

- **step_id:** `L1-S1` · **predecessors:** none · **estimated_loc:** 0 (artifact only)
- **file_scope.exclusive:** `.shepherd/runs/v651/lanes/l1-resolution/` (lane artifact)
- **file_scope.may_read:** `crates/cli/src/dispatch_store.rs`,
  `crates/cli/src/cmd/native_hook.rs`, `.shepherd/runs/v651/mesh.md`
- **file_scope.must_not_touch:** everything else
- **interfaces — Produces:** the R36c sandbox recipe as a re-runnable `.sh` under the lane
  namespace, plus the literal pre-fix output. Consumed by `L1-S2`'s falsification and by
  `L4-S1`, which needs the same sandbox to observe #315.

**[SKILLS]** `shell`
**[CONTEXT-INVENTORY]** Mesh R36c gives the recipe: `git init` a scratch repo,
`shepherd init --confirm`, `mkdir -p .shepherd/runs/v500 && echo '# legacy' >
.shepherd/runs/v500/plan.md`, create one real run, feed a PreToolUse envelope to
`shepherd claude-hook`. Synthetic minimal payloads do **not** reproduce it (R36a) — the
binding lookup that reaches `resolve_active_run` only runs when the envelope carries a
dispatch binding, so the envelope shape matters and must be recorded verbatim.
**[DO-NOT-DUPLICATE]** `ls .shepherd/runs/v651/lanes/` (expected: empty before this step) —
one sandbox script for the whole sprint, not one per lane. L4 sources this one.
**[USER-STYLE]** bash 3.2 compatible; `set -euo pipefail`; the script must be re-runnable
and must clean up after itself.
**[NON-GOALS]** Do not fix anything. Do not run the two commands the banner prints against
the real repository — per R36d they escalate an allowed session into a denied one.
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
# the sandbox script reproduces the abort and says so on stdout
bash .shepherd/runs/v651/lanes/l1-resolution/sandbox.sh 2>&1 | grep -q 'no usable run namespace'
# and the recorded output names the stale directory, not a generic error
grep -q 'runs/v500/run.json' .shepherd/runs/v651/lanes/l1-resolution/evidence/pre-fix.txt
```

**Actions**

1. Write `sandbox.sh` under the lane namespace implementing the R36c recipe end to end,
   parameterised by the binary under test so `L4` can reuse it unchanged.
2. Run it against `target/debug/shepherd` and capture stdout+stderr verbatim into
   `evidence/pre-fix.txt`.
3. Record, in the same artifact, the three-way severity sweep R36e proves:
   `status=planted` → advisory context; `status=executing` → deny. Do not apply either to
   the real repository.

### L1-S2 — a directory without `run.json` is not a run, and there is one resolver

- **step_id:** `L1-S2` · **predecessors:** `L1-S1` · **estimated_loc:** −40
- **file_scope.exclusive:** `crates/cli/src/dispatch_store.rs`,
  `crates/cli/tests/dispatch_store.rs`
- **file_scope.may_read:** `crates/cli/src/cmd/native_hook.rs`, `crates/core/src/dispatch/`
- **file_scope.must_not_touch:** `crates/cli/src/cmd/**`, `crates/core/**`
- **interfaces — Consumes:** `L1-S1`'s sandbox. **Produces:** `resolve_active_run` reaching
  its existing `DispatchStoreError::NoActiveRun` arm instead of aborting. Consumed by
  `L4-S1`, which cannot observe #314 or #315 until this lands (mesh R36, R46).

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** `crates/cli/src/dispatch_store.rs:236-273` (`#[cfg(unix)] mod
platform`) and `:888-925` (`#[cfg(not(unix))] mod platform`) are the two copies; `:98` is
the public method that delegates. Inside the unix copy, the loop already skips a
non-conforming directory name — `if let Ok(run) = RunId::new(name) { names.push(run) }` —
and then aborts on the next line for a *different* non-run condition:
`let run_fd = open_run_dir(store, &root, &run)?;` / `let state = read_run_document(store,
&run_fd, &run)?;`. **The correct error already exists**: `DispatchStoreError::NoActiveRun`
at `:39` renders `no executing shepherd run exists` and is returned at `:270`. Mesh R36h
proves that giving `v500` a stub `run.json` changes the banner to exactly that string, so
this fix needs no new error type and no new message — only for the `?` to stop preempting
the arm that is already written.
**[DO-NOT-DUPLICATE]** `grep -c "fn resolve_active_run" crates/cli/src/dispatch_store.rs`
(expected **3** before, **2** after) and
`grep -rn "resolve_active_run" crates/ --include='*.rs'` — enumerate every caller before
changing the signature. Per G6, also `grep -rn "AmbiguousActiveRuns\|NoActiveRun" crates/`
to find any gate that pins the current arm before you move it.
**[USER-STYLE]** `thiserror` in libraries; no new error variant; no `anyhow` here.
**[FILE-SCOPE]** as above.
**[NON-GOALS]** Do **not** change the `status == "executing"` predicate — that is
`run_namespace_is_usable`'s business and belongs to L4. Do **not** make the resolver consult
a registry, a claim, or a lock file; that is a larger design and is unseeded. Do **not**
change `AmbiguousActiveRuns` behaviour.
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
# one resolver, not two platform copies
test "$(grep -c 'fn resolve_active_run' crates/cli/src/dispatch_store.rs)" -lt 3
# the suite runs and its count is visible (G4)
cargo test -p shepherd-cli --test dispatch_store --locked 2>&1 | tee /dev/stderr \
  | grep -E 'test result: ok\. [1-9][0-9]* passed'
# the new case fails against the pre-fix resolver, measured in a throwaway worktree
# (never by stashing the live tree — G11 keeps git out of an implementer's hands)
wt=$(mktemp -d) && git worktree add --detach "$wt" 1c39f4c >/dev/null
cp crates/cli/tests/dispatch_store.rs "$wt/crates/cli/tests/dispatch_store.rs"
(cd "$wt" && ! cargo test -p shepherd-cli --test dispatch_store --locked)
git worktree remove --force "$wt"
# and the sandbox no longer aborts
# ROOT FIX: was `| grep -qv 'os error 2'`, which passes when ANY line differs
# from the pattern -- true of almost any output -- and which also discards the
# script's exit code. Capture both.
l1out=$(bash .shepherd/runs/v651/lanes/l1-resolution/sandbox.sh 2>&1); test $? -eq 0
printf '%s' "$l1out" | { ! grep -q 'os error 2'; }
```

**Actions**

1. In the unix copy, replace the two propagating `?` calls with a skip: a namespace whose
   `run.json` cannot be opened is not a run and is passed over exactly as a non-conforming
   name already is. A read error that is **not** "absent" — a corrupt or unreadable
   document — must still propagate; skipping every error would convert this into a silent
   swallow, which is the defect one direction over.
2. Collapse the `#[cfg(not(unix))]` copy onto the same implementation so
   `grep -c "fn resolve_active_run"` returns 2, not 3. Keep whatever genuinely differs per
   platform behind the narrowest possible `cfg`, and state in the lane artifact what that
   residue is.
3. Add a `crates/cli/tests/dispatch_store.rs` case that builds a runs root containing one
   `executing` run plus a `v500`-shaped directory holding only `plan.md`, and asserts the
   resolver returns the real run. Prove it fails against `1c39f4c`'s resolver and record the
   failing output in the lane artifact.
4. Add the negative control: a runs root with **no** executing run returns
   `NoActiveRun`, not an io error.

### L2-S1 — reproduce #323 and #320, and reconcile the Workflow contract

- **step_id:** `L2-S1` · **predecessors:** none · **estimated_loc:** +45
- **file_scope.exclusive:** `content/predicates/dispatch-scope.toml`,
  `crates/compiler/package-content/content/predicates/dispatch-scope.toml`,
  `crates/core/src/guard/engine.rs`, `crates/core/tests/guard.rs`,
  `hooks/tests/test_native_cli_contract.sh`
- **file_scope.may_read:** `content/predicates/write-boundary.toml`, `agents/*.md`,
  `skills/shepherd/SKILL.md`
- **file_scope.must_not_touch:** `crates/cli/**`, `hooks/tests/` other than the named file
- **interfaces — Produces:** `hooks/tests/test_native_cli_contract.sh` exiting 0, which is
  one of the two failures standing between `hooks/tests/run.sh` and green. Consumed by
  `L6-S2`, which cannot wire the suite into CI until this lands.

**[SKILLS]** `code-style`, `rust`, `shell`
**[CONTEXT-INVENTORY]** The enforced target list is **not** in the TOML (correction C3). It
is `crates/core/src/guard/engine.rs:661-666`:
```rust
"deny_if_dispatcher_is_lane_lead_and_target_is_plan_or_gate_role" => {
    context.get("dispatcher_tier").and_then(GuardValue::as_str) == Some("lane-lead")
        && matches!(
            context.get("target_role").and_then(GuardValue::as_str),
            Some("engineer" | "critic")
        )
}
```
`role_tier` at `:538-547` maps `conductor` → `lane-lead` and `shepherd` → `root`; there is
no `root` role id, so `conductor -> root` is already refused by
`deny_if_target_outside_flock` at `:657-660` rather than by this rule — say which rule
denies which target in the artifact, because the seed's acceptance lists all three together.
The carve-out D1 protects is `:401` `if target.is_none() && tool_name != "Workflow"`, added
by `f3d44b0` (v6.4.6) with its explaining comment at `:398-400`; the assertion contradicting
it at `hooks/tests/test_native_cli_contract.sh:82-88` is `ee682ec` (v6.4.5) and has not been
touched since. The test shells `cargo run --quiet --locked -p shepherd-cli -- guard eval`
(`:70`, `:83`, `:92`), so it already measures this tree and not an installed binary —
preserve that property.
**[DO-NOT-DUPLICATE]** `grep -rn 'engineer" | "critic"' crates/core/src/` (expected 1) and
`grep -rn "plan-authorship-and-gating-are-root-tier-exclusive" crates/ content/` — the rule
id appears in the engine's deny message, in the TOML, and in `crates/core/tests/guard.rs:218`;
all three must agree after the change.
**[USER-STYLE]** Extend the existing `matches!` arm; do not add a second rule or a second
effect string for the same intent.
**[NON-GOALS]** Do **not** remove the `tool_name != "Workflow"` carve-out (seed decision D1
— removing it is critic-RED). Do **not** touch the `Verdict::unresolved` body at `:402-404`.
Do not rewrite the whole assertion file; change the one contradicted assertion and add the
negative control beside it.
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
# #323: a lane lead may not reach the root orchestrator or the planter
for t in planter shepherd root; do
  printf '{"tool_name":"Agent","role":"conductor","tool_input":{"subagent_type":"%s"}}' "$t" \
    | shepherd guard eval | grep -q '"decision": *"deny"' || { echo "FAIL: conductor -> $t"; exit 1; }
done
# and the sanctioned dispatch still works
printf '{"tool_name":"Agent","role":"conductor","tool_input":{"subagent_type":"coder"}}' \
  | shepherd guard eval | grep -q '"decision": *"allow"'
# the projection is regenerated, not drifted
python3 scripts/generate-compiler-package-content.py --check
# both suites run, with visible counts (G4)
cargo test -p shepherd-core --test guard --locked --features std,parse,json 2>&1 \
  | grep -E 'test result: ok\. [1-9][0-9]* passed'
bash hooks/tests/test_native_cli_contract.sh; test $? -eq 0
```

**Actions**

1. Extend the `matches!` arm at `crates/core/src/guard/engine.rs:664-666` to refuse
   `planter` and `shepherd` in addition to `engineer` and `critic`. Confirm by measurement
   which rule already refuses `root`, and record it rather than adding a redundant arm.
2. Update the rule description in `content/predicates/dispatch-scope.toml:21` so the prose
   matches the enforced list, and add a `[[example]]` for `conductor -> planter` with
   `result = "deny"` and `halt_code = "WRONG-TIER-DISPATCH"`, mirroring the existing
   `conductor-attempts-to-dispatch-engineer` example at `:51-59`.
3. Regenerate the projection with
   `python3 scripts/generate-compiler-package-content.py --write` and prove `--check` exits 0.
4. Rewrite `hooks/tests/test_native_cli_contract.sh:82-88` to the v6.4.6 contract: a
   script-only `Workflow` payload from a root-tier role resolves rather than returning
   `unresolved`. Add the negative control immediately beside it — the same payload from
   `conductor` must deny with `WRONG-TIER-DISPATCH`. Per G4, the file's final line must
   report how many assertions ran.
5. Record the falsification: revert `:401` in a scratch worktree, show the rewritten test
   goes red, restore. Put the literal output in the lane artifact.
6. Add `crates/core/tests/guard.rs` cases for `conductor -> planter` and
   `conductor -> shepherd` deny, and for `conductor -> coder` allow.

### L2-S2 — measure #320's Write-versus-Bash asymmetry and dispose of it

- **step_id:** `L2-S2` · **predecessors:** `L2-S1` · **estimated_loc:** +15
- **file_scope.exclusive:** `content/predicates/write-boundary.toml`,
  `crates/core/tests/guard.rs`
- **file_scope.may_read:** `crates/core/src/guard/engine.rs`
- **file_scope.must_not_touch:** `crates/cli/**`, `.github/**`
- **interfaces — Produces:** a recorded two-payload verdict diff and either a removed
  asymmetry or a closing comment on #320 citing the measurement.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** Mesh R48 did not reproduce this; the rule source is
`content/predicates/write-boundary.toml` and the effect evaluator is
`crates/core/src/guard/engine.rs:647-649`
(`"deny_if_path_outside_scope" => context.get("path_in_dispatch_write_scope")…`). **This
sprint has a live reproduction to cite:** five `shepherd:auditor` agents in this plan's own
orientation wave were denied `Write` to an absolute path outside the repository while the
identical write through `Bash` succeeded — the asymmetry is real and it silently cost this
engineer five reports. Record that as the reproduction context; the two-payload `guard eval`
diff is the formal measurement.
**[DO-NOT-DUPLICATE]** `grep -rn "path_in_dispatch_write_scope" crates/ content/` — one
predicate feeds this decision; do not add a second path-scope rule.
**[USER-STYLE]** Truth over politeness: if the asymmetry is intended, say so in the issue
and close it with the output; do not leave it half-measured.
**[NON-GOALS]** Do not widen `Write` to permit out-of-repo absolute paths as a convenience.
The disposition is either "`Bash` is narrowed to match `Write`" or "the asymmetry is
intended and #320 closes citing the verdicts" — not "`Write` is loosened".
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
# the two payloads, same role, same destination, recorded verbatim
printf '{"tool_name":"Write","role":"auditor","tool_input":{"file_path":"/tmp/x/out.md"}}' \
  | shepherd guard eval | tee /tmp/v651-write.json
printf '{"tool_name":"Bash","role":"auditor","tool_input":{"command":"echo hi > /tmp/x/out.md"}}' \
  | shepherd guard eval | tee /tmp/v651-bash.json
# the verdict diff is recorded in the lane artifact either way
grep -q 'decision' .shepherd/runs/v651/lanes/l2-dispatch-scope/evidence/issue-320.md
cargo test -p shepherd-core --test guard --locked --features std,parse,json 2>&1 \
  | grep -E 'test result: ok\. [1-9][0-9]* passed'
```

**Actions**

1. Run both payloads and record both verdicts verbatim in `evidence/issue-320.md`, together
   with the live orientation-wave denial text as corroboration.
2. Decide the disposition and state it in one sentence with its reason.
3. If the asymmetry is removed, add a `crates/core/tests/guard.rs` case pinning the new
   symmetric behaviour. If it is intended, add a case pinning the *intended* asymmetry so a
   future author cannot "fix" it by accident, and close #320 citing the output.

### L3-S1 — a fresh clone carries its context directory and knows its binary is stale

- **step_id:** `L3-S1` · **predecessors:** none · **estimated_loc:** +95
- **file_scope.exclusive:** `.gitignore`, `.shepherd/ctx/.gitkeep`,
  `crates/cli/src/cmd/wave_c_bootstrap.rs`, `scripts/check-version-lag.py`
- **file_scope.may_read:** `.claude-plugin/plugin.json`, `Cargo.toml`, `package.json`,
  `scripts/check-plugin.py`, `.github/workflows/rust.yml`
- **file_scope.must_not_touch:** `.github/**` (L6 owns every workflow edit),
  `crates/cli/src/dispatch_store.rs`
- **interfaces — Produces:** `scripts/check-version-lag.py` with a stable CLI contract —
  exit 0 when the resolved `shepherd` version equals `.claude-plugin/plugin.json`, exit 1
  when it lags, exit 0 with a stated skip when no binary is resolvable, and `--self-test`
  proving it can fail. **Consumed by `L6-S3`, which wires it into CI.** L6 sees only this
  sentence, so the contract is stated here in full.

**[SKILLS]** `code-style`, `python`, `shell`
**[CONTEXT-INVENTORY]** `.gitignore:35` is `.shepherd/runs/**` with a 28-entry re-include
allowlist at `:36-63`; `run.json` is absent from it, and
`git status --ignored --short .shepherd/runs/` shows only `v651/run.json` and
`v651/run.lock` ignored in this tree. `.gitignore:85` re-includes `**/.shepherd/.gitkeep`,
which does **not** match `.shepherd/ctx/.gitkeep`; measured,
`git check-ignore -v .shepherd/ctx/.gitkeep` exits 1, so the path is already un-ignored and
the file only needs to be created and committed. `git ls-files .shepherd/ctx` returns zero
files today. The version facts: `~/.cargo/bin/shepherd` reports `shepherd-cli 6.5.0` against
`.claude-plugin/plugin.json` `6.5.1`. Structural precedent for the new script is
`scripts/check-plugin.py`, which pairs a real check with a `--self-test` flag and is invoked
in that pair by both `scripts/gate.sh:90-91` and `.github/workflows/rust.yml:105-108`.
**[DO-NOT-DUPLICATE]** `git grep -n "shepherd --version" hooks/ scripts/ .github/`
(expected: no version-lag guard exists — mesh R49). `grep -rn "plugin.json" scripts/` to
find how the existing scripts read the manifest version; read it the same way.
**[USER-STYLE]** `argparse`, `pathlib`, explicit exit codes, no third-party dependency. A
remediation string must be runnable verbatim — that is the defect family this branch opened
with (`cc07276`).
**[NON-GOALS]** Do **not** re-include `run.json` in `.gitignore`. `L1-S2` makes a namespace
without `run.json` harmless, so tracking live mutable run status would trade a fixed bug for
permanent working-tree churn and merge conflicts on every `shepherd run set`. State this
decision in the lane artifact, because the seed's D12 names R33 and invites the opposite
reading. Do **not** make the version check fail a fresh CI runner that has never installed a
release binary (see the contract above).
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
# .shepherd/ctx survives a clone
git ls-files .shepherd/ctx/.gitkeep | grep -q .
# ROOT AMENDMENT (l3 escalation, 2026-08-19). This block used a linked
# worktree and was VACUOUS: `resolve_primary` (crates/cli/src/context.rs:608-612)
# returns `common.parent()` -- the MAIN checkout -- for any linked worktree, so
# `cd "$wt" && shepherd doctor` never inspected $wt. It reported the registered,
# healthy root checkout and exited 0 pre-fix, so the clause could not fail.
# That is a Class A defect inside the gate this plan added to prevent Class A
# defects. Only a standalone clone makes resolve_primary land on the new tree.
# The worktree form also could not be run by the lane at all: the guard reserves
# `git worktree add/remove/prune` to the top-level orchestrator.
cl=$(mktemp -d)/clone && git clone --no-local -q . "$cl"
test -d "$cl/.shepherd/ctx"; echo "ctx=$?"
# Exit stays 3 and that is CORRECT: .shepherd/shepherd.db and
# .shepherd/project.json are git-ignored (.gitignore:26,31), so a fresh clone
# genuinely needs `shepherd init --confirm`. Demoting those two findings would
# break crates/cli/tests/wave_c_bootstrap_cli.rs:259-266, which pins doctor to
# exit 3 on an unregistered checkout and is outside this lane's file scope.
# The load-bearing assertion is that `ctx` is no longer among the findings.
(cd "$cl" && shepherd doctor 2>&1) | tee /dev/stderr | grep -q 'ctx directory is absent' && exit 1
rm -rf "$(dirname "$cl")"
# the version-lag gate is falsifiable and correct in both directions
python3 scripts/check-version-lag.py --self-test; test $? -eq 0
SHEPHERD_BIN=$PWD/target/debug/shepherd python3 scripts/check-version-lag.py; test $? -eq 0
SHEPHERD_BIN=$HOME/.cargo/bin/shepherd python3 scripts/check-version-lag.py; test $? -eq 1
```

**Actions**

1. Create `.shepherd/ctx/.gitkeep` and confirm it is tracked; add a `.gitignore` re-include
   only if measurement shows one is needed (it is not needed today — prove it either way in
   the artifact).
2. Read `crates/cli/src/cmd/wave_c_bootstrap.rs` and make `shepherd doctor` treat an absent
   `.shepherd/ctx` in an unregistered checkout as a scaffolded condition rather than a
   failure, matching the shape #316 asks for. Prove it against the detached worktree above,
   before and after.
3. Write `scripts/check-version-lag.py` to the contract in **interfaces**. Resolve the
   binary from `SHEPHERD_BIN`, else `PATH`; compare against `.claude-plugin/plugin.json`;
   exit 1 with a message naming both versions and the command that reinstalls; exit 0 with
   an explicit `skip:` line when no binary resolves, so a fresh runner is not failed for a
   condition it cannot have.
4. Add `--self-test` that synthesises a lagging pair and a matching pair and asserts both
   verdicts, per v646 carry-forward §6b: pin against a **synthetic** version, never the
   current release.

---

## Wave 2 — the hook lifecycle, the vocabulary, and the wiring

**Wave gate (`W2-GATE`):** `bash hooks/tests/run.sh` exits 0 with `0 failed` and a count of
at least 29; `cargo test --workspace --locked` exits 0 with a non-zero total;
`python3 scripts/check-version-lag.py --self-test` exits 0; `gh pr checks 328` reports zero
`fail` rows.

### L4-S1 — measure #315, #314 and #306 now that the abort is gone

- **step_id:** `L4-S1` · **predecessors:** `L1-S2` · **estimated_loc:** 0 (artifact only)
- **file_scope.exclusive:** `.shepherd/runs/v651/lanes/l4-diagnostics/`
- **file_scope.may_read:** `crates/cli/src/cmd/native_hook.rs`,
  `.shepherd/runs/v651/lanes/l1-resolution/sandbox.sh`
- **file_scope.must_not_touch:** `crates/**`
- **interfaces — Consumes:** `L1-S1`'s sandbox script and `L1-S2`'s landed fix.
  **Produces:** the pre-fix denial text for each of #315, #314 and #306, which is what the
  fixes in `L4-S2` and `L4-S3` are graded against.

**[SKILLS]** `shell`
**[CONTEXT-INVENTORY]** Both #314 and #315 were unmeasurable at seed time because #330
preempted them (mesh R36, R46, R47). Mesh R36g gives #315's expected shape once the stale
directory is gone: a denial naming `…/runs/<run>/dispatch/.root-session.<id>.json: No such
file or directory (os error 2)` — correctly fail-closed, with a bare errno naming an
internal file. #314's expected string is `dispatch record already exists`, which exists as
`DispatchStoreError::AlreadyExists` at `crates/cli/src/dispatch_store.rs:45`. #306 may
already be satisfied by `crates/cli/src/cmd/native_hook.rs:521-531` (mesh R51) — re-measure
before writing any code, and note that #306 carries milestone 60, not 61 (correction C5).
**[DO-NOT-DUPLICATE]** Do not write a second sandbox; source `L1-S1`'s.
**[NON-GOALS]** Write no production code in this step.
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
# each of the three issues has a recorded verdict: REPRODUCED or REFUTED, with output
for n in 315 314 306; do
  grep -qE "^#$n +(REPRODUCED|REFUTED)" \
    .shepherd/runs/v651/lanes/l4-diagnostics/evidence/pre-fix.md || exit 1
done
```

**Actions**

1. Re-run the sandbox with the fixed resolver, remove the stale `v500` directory, set the
   real run `executing`, and feed a PreToolUse envelope with a stranger `session_id`.
   Record the literal denial.
2. Feed a `SessionStart` envelope twice for one session id; record whether the two outputs
   are byte-identical and whether the second is a rejection.
3. Re-measure #306 against `native_hook.rs:521-531`; if it is already satisfied, record the
   output that proves it and mark it REFUTED rather than writing a fix.

### L4-S2 — the hook's remediation stops making the failure worse

- **step_id:** `L4-S2` · **predecessors:** `L4-S1` · **estimated_loc:** +60
- **file_scope.exclusive:** `crates/cli/src/cmd/native_hook.rs`,
  `crates/cli/tests/claude_hook_cli.rs`
- **file_scope.may_read:** `crates/cli/src/dispatch_store.rs`,
  `hooks/scripts/remediation_flag_lint.py`
- **file_scope.must_not_touch:** `crates/cli/src/dispatch_store.rs`,
  `crates/cli/src/run_store.rs` (`L4-S3` owns the latter)
- **interfaces — Produces:** a PreToolUse denial reason that names the session-binding
  condition and a command, and a printed remediation that cannot convert an allowed session
  into a denied one.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** `crates/cli/src/cmd/native_hook.rs:536-542` builds the banner;
`:532-535` routes the same error to `HookOutput::Deny` when
`run_namespace_is_usable(&context.runs_root)` is true; that predicate at `:549-563` requires
some run with `dispatch/` **and** `status == "executing"`. The two commands the banner
prints create exactly those two conditions, which is why following the instruction flips
allow into deny (mesh R36d, R36e) while `v500` never gains a `run.json`. `:147-153` makes
this a hard `"decision":"block"` on `SubagentStop` while every other event degrades to
advisory context at `:154-163`. `hooks/scripts/remediation_flag_lint.py` derives gated
subcommand flags from refusal text and structurally cannot catch this case, because the
printed command **runs** and exits 0 (mesh R36f).
**[DO-NOT-DUPLICATE]** `grep -rn "run layout .* --repair" crates/ hooks/` — find every place
that prints this remediation before editing one of them.
**[USER-STYLE]** A remediation string is a contract. If the tool cannot name a command that
improves the situation, it must name none.
**[NON-GOALS]** Do not delete the `SubagentStop` hard-block arm — fail-closed on a genuinely
unresolvable binding is correct. Do not widen `run_namespace_is_usable`.
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
# following the printed remediation verbatim never turns allow into deny
# ROOT FIX: `--follow-remediation` does NOT exist in l1's sandbox.sh -- it hits
# `die "unknown option"` and exits 2, and `grep -qv` then returned 0, so this
# acceptance PASSED WITHOUT THE SCRIPT EVER RUNNING. Class A, in this plan.
# l4 implements the flag in its OWN sandbox; point at that and check the exit.
remout=$(bash .shepherd/runs/v651/lanes/l4-diagnostics/sandbox.sh --follow-remediation 2>&1); test $? -eq 0
printf '%s' "$remout" | { ! grep -q '"permissionDecision": *"deny"'; }
# the unbound-session denial names a condition and a command, not only an errno
printf '{"hook_event_name":"PreToolUse","session_id":"stranger","tool_name":"Bash","tool_input":{}}' \
  | shepherd claude-hook | { ! grep -q 'os error'; }   # ROOT FIX: was `grep -qv`
cargo test -p shepherd-cli --test claude_hook_cli --locked 2>&1 \
  | grep -E 'test result: ok\. [1-9][0-9]* passed'
```

**Actions**

1. Rewrite the remediation the banner prints so it names a step that actually repairs the
   condition, or prints none. Whichever is chosen, add a `claude_hook_cli.rs` case that
   executes the printed text and asserts the resulting decision is no worse than before.
2. Replace the bare-errno denial reason for an unbound session with one that names the
   session-binding condition and the command that establishes it, keeping the decision
   fail-closed.
3. Apply `L4-S1`'s #314 verdict: if `SessionStart` replay is a rejection, make the second
   replay for one session id produce identical non-rejection output, and pin it with a test.

### L4-S3 — operator-facing errors name an action, in one helper pair

- **step_id:** `L4-S3` · **predecessors:** none · **estimated_loc:** +35
- **file_scope.exclusive:** `crates/cli/src/run_store.rs`,
  `crates/cli/src/cmd/wave_h_execution.rs`
- **file_scope.may_read:** `crates/cli/src/cmd/dispatch.rs`, `crates/cli/tests/`
- **file_scope.must_not_touch:** `crates/cli/src/cmd/native_hook.rs`
- **interfaces — Produces:** every `run_store` errno carrying a command-level diagnostic,
  while `shepherd ready --run dummy` keeps exit code 5.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** Seed decision D4: fix the helpers, not the 16 call sites.
`crates/cli/src/run_store.rs` holds `errno` (13 uses) and `errno_path` (3 uses); measured,
`shepherd ready --run dummy` prints `ERROR: open state directory
/Users/jo3/src/pzzld/shepherd/.shepherd/runs/dummy: No such file or directory (os error 2)`
and exits 5. The exit code comes from a **different** file:
`crates/cli/src/cmd/wave_h_execution.rs:467-469` maps every `RunStoreError` to code 5 —
which is why that file is in this lane despite mesh R64–R71 assigning it to nothing. The
corrected message shape to imitate is `crates/cli/src/cmd/dispatch.rs:185`.
**[DO-NOT-DUPLICATE]** `grep -c "errno(" crates/cli/src/run_store.rs` (expected 13) and
`grep -c "errno_path(" crates/cli/src/run_store.rs` (expected 3) — change the two helpers,
not the sites. Per G6, `grep -rn "os error" crates/cli/tests/` first: any test pinning the
current wording must move in the same commit.
**[USER-STYLE]** Name the run, and name `shepherd run list` as the way to find one.
**[NON-GOALS]** Do not change the exit code. Do not touch the 16 call sites individually.
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
shepherd ready --run dummy 2>&1 | grep -q 'os error'; test $? -eq 1
shepherd ready --run dummy; test $? -eq 5
shepherd ready --run dummy 2>&1 | grep -q 'shepherd run list'
cargo test -p shepherd-cli --locked 2>&1 | grep -E 'test result: ok\. [1-9][0-9]* passed'
```

**Actions**

1. Rewrite `errno` and `errno_path` so each message names the operation, the run, and the
   command that lists runs, and carries no bare `os error N`.
2. Sweep the 16 sites only to confirm each resulting message reads correctly; change no
   site's call shape.
3. Add a regression test asserting both the absence of `os error` and the retention of
   exit 5.

### L5-S1 — the root role has one name, with a stated direction

- **step_id:** `L5-S1` · **predecessors:** none · **estimated_loc:** +30
- **file_scope.exclusive:** `crates/cli/src/cmd/wave_a_models.rs`,
  `crates/cli/tests/wave_a_models_cli.rs`
- **file_scope.may_read:** `crates/core/src/guard/engine.rs`, `agents/*.md`,
  `.shepherd/shepherd.toml`
- **file_scope.must_not_touch:** `crates/core/**`, `content/**`
- **interfaces — Produces:** `shepherd models resolve shepherd` and
  `shepherd models resolve root` both exiting 0, `nonsense` still exiting 2.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** The split is two hardcoded vocabularies in two crates.
`crates/cli/src/cmd/wave_a_models.rs:20` `const ROLES: [&str; 9]` uses **`root`**, and the
error is emitted at `:180-184`. `crates/core/src/guard/engine.rs:538-547` `role_tier` uses
**`shepherd`** and has no `root` arm at all — which is why `conductor -> root` is refused as
off-flock rather than by the tier rule. `crates/cli/src/cmd/wave_a_models.rs:32` USAGE
restates the nine names a third time, and `crates/cli/tests/wave_a_models_cli.rs:202` pins
the exact error string `unknown role: invalid (valid: root planter engineer conductor
critic discovery coder auditor worker)`. Four surfaces, two vocabularies.
**[DO-NOT-DUPLICATE]** `grep -rn "root planter engineer conductor" crates/` (expected 3:
the const, the USAGE text, the pinned test) — an alias added in one place and not the others
reproduces the split it is meant to close.
**[USER-STYLE]** Pick one canonical name, accept the other as an alias, and say which
direction is canonical in `CHANGELOG.md`. Do not add a bidirectional silent equivalence
with no stated owner.
**[NON-GOALS]** Do not rename the role in `crates/core` — that is `content/` and guard
territory and would ripple into every predicate and every agent file. The alias belongs on
the `models` surface.
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
shepherd models resolve shepherd --harness claude; test $? -eq 0
shepherd models resolve root --harness claude;     test $? -eq 0
shepherd models resolve nonsense --harness claude; test $? -eq 2
cargo test -p shepherd-cli --test wave_a_models_cli --locked 2>&1 \
  | grep -E 'test result: ok\. [1-9][0-9]* passed'
```

**Actions**

1. Accept `shepherd` as an alias for the canonical `root` on the `models` surface, resolving
   both to the same hint.
2. Update the USAGE text at `:32` and the pinned assertion at
   `crates/cli/tests/wave_a_models_cli.rs:202` in the same commit, so all three enumerations
   agree.
3. Add cases for the alias, the canonical name, and an unknown role, and state the canonical
   direction in `CHANGELOG.md`.

### L5-S2 — the seed gate accepts the seeds this project actually writes

- **step_id:** `L5-S2` · **predecessors:** none · **estimated_loc:** +45
- **file_scope.exclusive:** `crates/cli/src/cmd/wave_b2_seed.rs`,
  `crates/cli/tests/wave_b2_seed_cli.rs`
- **file_scope.may_read:** `.shepherd/runs/v646/seed.md`, `.shepherd/runs/v651/seed.md`
- **file_scope.must_not_touch:** `crates/cli/src/cmd/wave_a_models.rs`
- **interfaces — Produces:** `shepherd seed verify` that does not HARD-fail a historical
  seed for a path the sprint it planned has since deleted, while still HARD-failing a live
  seed that names a path that never existed.

**[SKILLS]** `code-style`, `rust`
**[CONTEXT-INVENTORY]** `crates/cli/src/cmd/wave_b2_seed.rs:12-17` holds
`MIN_MESH_ROWS = 8`, `SPRINT_FOOTPRINT_CAP = 400`, `PATCH_FOOTPRINT_CAP = 200`,
`MAX_SEED_BYTES`, and `NEW_MARKERS`. The severity split is `Report::hard` at `:106-111` and
`Report::warn` at `:113`; the `file_scope` resolution check calls `report.hard` at
`:192-196` with `file_scope path does not resolve and is not marked (NEW)`. Measured:
`shepherd seed verify .shepherd/runs/v646/seed.md` fails on `footprint 393 lines > cap 200
(kind=patch-seed)` **and** on `bin` — a directory v6.4.6's own decision D4 deleted. Both are
the same underlying fact: the gate validates a historical artifact against the live tree.
**[DO-NOT-DUPLICATE]** `grep -n "report.hard" crates/cli/src/cmd/wave_b2_seed.rs` — change
severity at the one `file_scope` site, not by adding a global "historical" bypass that
disables every rule at once.
**[USER-STYLE]** State the chosen semantics in `CHANGELOG.md`; a gate whose severity changed
without a written rule is worse than one that is too strict.
**[NON-GOALS]** Do not raise `SPRINT_FOOTPRINT_CAP` — this sprint's own seed passes at 388
of 400 and the cap is doing real work. Do not disable the `file_scope` check.
**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
shepherd seed verify .shepherd/runs/v646/seed.md; test $? -eq 0
shepherd seed verify .shepherd/runs/v651/seed.md; test $? -eq 0
# a live seed naming a path that never existed must still HARD-fail
cargo test -p shepherd-cli --test wave_b2_seed_cli --locked 2>&1 \
  | grep -E 'test result: ok\. [1-9][0-9]* passed'
grep -q 'seed verify' CHANGELOG.md
```

**Actions**

1. Choose and implement one semantics: either an unresolved `file_scope` path degrades to a
   warning for a seed whose front matter dates it before the current run, or the check
   resolves paths against the commit the seed names rather than the live tree. State which,
   and why, in `CHANGELOG.md`.
2. Resolve the `kind=patch-seed` mis-tiering that makes a 393-line v6.4.6 seed fail a 200-line
   cap, without raising the sprint cap.
3. Add a case that a live seed naming a genuinely nonexistent path still HARD-fails, so the
   relaxation cannot be mistaken for a disabled check. Prove it fails before the change.

### L6-S1 — the workflow-meta negative control stops needing git history

- **step_id:** `L6-S1` · **predecessors:** none · **estimated_loc:** +70
- **file_scope.exclusive:** `scripts/check-workflow-meta.sh`,
  `hooks/tests/test_workflow_meta_gate.sh`, `hooks/tests/fixtures/`
- **file_scope.may_read:** `workflows/*.js`
- **file_scope.must_not_touch:** `.github/**` (`L6-S3` owns it), `hooks/tests/lib/`
- **interfaces — Produces:** `bash scripts/check-workflow-meta.sh --self-test` printing
  `PASS  NEGATIVE control` with no dependency on any git object. Consumed by `L6-S2`, which
  cannot reach a green suite until this lands.

**[SKILLS]** `shell`
**[CONTEXT-INVENTORY]** `scripts/check-workflow-meta.sh:259` shells
`git -C "${ROOT}" show 686084d:workflows/wave.js`; `git cat-file -t 686084d` fails in this
93-commit clone (mesh R26). The gate's own comment at `:242` states the intent: *"NEGATIVE —
the real 686084d concatenated form must be REJECTED."* The three surviving controls pass, so
only the corpus is missing. **This is worse than a transferred clone:** `actions/checkout`
defaults to `fetch-depth: 1` and `.github/workflows/rust.yml:81-86` uses that default, so
`git show <old-sha>` cannot work in CI even in a repository that still has the object.
Restoring the commit would not survive the next transfer and would not help CI at all.
**[DO-NOT-DUPLICATE]** `git grep -n 686084d scripts/ hooks/` (expected 2 before, 0 outside
comments after) — every reference goes, not just the one that fails.
**[USER-STYLE]** bash 3.2 compatible. Per G5, distinguish `rg`/`grep` exit 1 from exit 2.
**[NON-GOALS]** Do not restore commit `686084d` (seed decision D3). Do not weaken the
negative control to make it pass — the fixture must still be REJECTED for the same reason.
**[ACCEPTANCE]**
```bash
bash scripts/check-workflow-meta.sh --self-test 2>&1 | grep -q 'PASS  NEGATIVE control'
bash scripts/check-workflow-meta.sh --self-test; test $? -eq 0
bash hooks/tests/test_workflow_meta_gate.sh; test $? -eq 0
test "$(git grep -c 686084d scripts/ hooks/ | wc -l)" -eq 0
# the gate still refuses an empty scan set (DF-59, G4)
bash scripts/check-workflow-meta.sh --self-test 2>&1 | grep -q 'empty scan set'
```

**Actions**

1. Check the rejected corpus into `hooks/tests/fixtures/` as a regular file, reproducing the
   concatenated form the gate must reject. Derive it from the gate's own rejection criteria
   at `scripts/check-workflow-meta.sh:242` and prove the gate rejects it for that reason.
2. Repoint `:259` at the fixture and remove every `686084d` reference outside comments.
3. Keep all four controls — POSITIVE, NEGATIVE, false-positive guard, DF-59 empty-set guard
   — and confirm the suite still reports how many it ran.

### L6-S2 — the shell gate tier runs in CI, and a skip in CI is a failure

- **step_id:** `L6-S2` · **predecessors:** `L2-S1`, `L6-S1` · **estimated_loc:** +45
- **file_scope.exclusive:** `.github/workflows/rust.yml`
- **file_scope.may_read:** `hooks/tests/run.sh`, `scripts/gate.sh`, `.shepherd/shepherd.toml`
- **file_scope.must_not_touch:** `hooks/tests/**`, `scripts/**`
- **interfaces — Consumes:** `L2-S1`'s green `test_native_cli_contract.sh` and `L6-S1`'s
  green `test_workflow_meta_gate.sh`. **Produces:** a CI job that fails when the shell tier
  fails and when the shell tier silently skips.

**[SKILLS]** `shell`
**[CONTEXT-INVENTORY]** `.github/workflows/rust.yml:76-108` is the `lint` job
(`fmt + workspace invariants`), `runs-on: ubuntu-latest`, `fetch-depth: 1`, and it hand-copies
five `scripts/gate.sh` steps. The `test` job at `:109-179` is matrixed across
`[ubuntu-latest, windows-latest] × [default, full]`, so a bash step added there would run on
Windows, where `bash` is Git Bash and several hook tests assume a POSIX environment — put the
shell tier in the `lint` job, not the matrix. Two constraints from measurement:
**ripgrep is not preinstalled on any GitHub-hosted runner** and exactly two hook tests need
it (`hooks/tests/test_run_scoped_hook_state.sh`, `hooks/tests/test_registered_hooks_no_python.sh`);
and **eight hook tests exit 0 with a `SKIP` line** when `jq`, `python3`, or a prior run's
artifact is absent (correction C8). A CI job that inherits those skips reports success for
work it did not do — this sprint's own theme.
**[DO-NOT-DUPLICATE]** `grep -rn "hooks/tests" .github/` (expected 2, both prose inside
`claude-review.yml:83` and `release.yml:548`, neither an invocation) — add an invocation,
do not add a third mention.
**[USER-STYLE]** A CI step that can silently check nothing is not a gate.
**[NON-GOALS]** Do not add the step to the `test` matrix job. Do not paper over C8 by
deleting the skip branches — a skip is correct locally; it is only wrong in CI.
**[ACCEPTANCE]**
```bash
grep -q 'hooks/tests/run.sh' .github/workflows/rust.yml
bash hooks/tests/run.sh 2>&1 | tail -1 | grep -qE '\(([0-9]+)/\1 tests ran, 0 failed\)'
test "$(bash hooks/tests/run.sh 2>&1 | tail -1 | sed -E 's#.*\(([0-9]+)/.*#\1#')" -ge 29
# no test silently skipped in a CI-shaped environment
SHEPHERD_CI_STRICT=1 bash hooks/tests/run.sh 2>&1 | grep -c 'SKIP' | grep -qx 0
gh pr checks 328 | awk -F'\t' '$2=="fail"' | wc -l | grep -qx 0
```

**Actions**

1. Add a step to the `lint` job invoking `bash hooks/tests/run.sh`, after the existing
   plugin-contract steps. Give it whatever tool setup measurement shows it needs — either an
   `rg` install step or a `grep` conversion of the two call sites; record which was chosen
   and why in the lane artifact.
2. Make a `SKIP` a failure under CI: introduce one environment flag the runner sets, and
   have the eight skip branches fail rather than pass when it is set. The local behaviour is
   unchanged.
3. Confirm the suite's final line reports a count and that the count is at least 29, per G4
   and correction C2. Do not assert an exact number.

### L6-S3 — CI stops hand-copying the gate list

- **step_id:** `L6-S3` · **predecessors:** `L6-S2`, `L3-S1` · **estimated_loc:** +25
- **file_scope.exclusive:** `.github/workflows/rust.yml`
- **file_scope.may_read:** `scripts/gate.sh`, `.shepherd/shepherd.toml`,
  `scripts/check-plugin.py`, `scripts/check-version-lag.py`
- **file_scope.must_not_touch:** `scripts/**`, `hooks/**`
- **interfaces — Consumes:** `scripts/check-version-lag.py`'s contract as stated in
  `L3-S1`'s **interfaces**. **Produces:** class B closed — every gate the project declares
  is reachable from CI, and every CI shell step is runnable by an operator.

**[SKILLS]** `shell`
**[CONTEXT-INVENTORY]** `.shepherd/shepherd.toml` already declares the tier:
`[gates] check = "scripts/gate.sh fast"`, `[gates.extra] hooks = "bash hooks/tests/run.sh"`,
`full`, `wasm`, `release`. `./scripts/check-plugin.py` already verifies
`configured gates resolve` (measured: rule present, 10/10 ok), so that config is enforced
rather than decorative. Meanwhile `.github/workflows/rust.yml:92-108` re-states five of
`scripts/gate.sh`'s steps by hand, and `scripts/gate.sh:55` runs only the *falsification*
test for the compiler projection — `python3 scripts/generate-compiler-package-content.py
--check` itself is in no gate and no workflow, which is how a projection could drift
unnoticed.
**[DO-NOT-DUPLICATE]** `grep -n "check-workspace\|check-plugin" .github/workflows/rust.yml
scripts/gate.sh` — after this step each named gate is invoked from one list, not two.
**[USER-STYLE]** One list. A second copy of a list is a future divergence with a date on it.
**[NON-GOALS]** Do not move the Rust jobs into `gate.sh`; the matrix, caching, and MSRV jobs
stay exactly as they are. This step is about the shell tier only. Do not add a new gate
engine — the runner is `scripts/gate.sh`, which already exists.
**[ACCEPTANCE]**
```bash
# the projection check is now a real gate, not only its own falsification
grep -q 'generate-compiler-package-content.py --check' .github/workflows/rust.yml
# the version-lag gate is reachable from CI and falsifiable there
grep -q 'check-version-lag.py' .github/workflows/rust.yml
python3 scripts/check-version-lag.py --self-test; test $? -eq 0
# every shell step named in the workflow is runnable by an operator, verbatim
./scripts/check-plugin.py | grep -q 'configured gates resolve'
gh pr checks 328 | awk -F'\t' '$2=="fail"' | wc -l | grep -qx 0
```

**Actions**

1. Replace the hand-copied shell steps in the `lint` job with an invocation of the
   project-declared tier, so the workflow names the gate runner rather than its contents.
   Keep the falsifiable/holds pairing that `:97-108` established — a gate and its
   self-test both run.
2. Add `python3 scripts/generate-compiler-package-content.py --check` and
   `python3 scripts/check-version-lag.py` as steps, per their contracts.
3. Record in the lane artifact, for every gate this sprint touched or added, the command
   that runs it in CI and the falsification proving it fails on purpose. That is the seed's
   `GATE-REACHABILITY` gate discharged in one table.

---

## Wave 3 — the assertion sweep

**Wave gate (`W3-GATE`):** `bash hooks/tests/run.sh` exits 0 with `0 failed`;
`cargo test --workspace --locked` exits 0; `gh pr checks 328` reports zero `fail` rows.

`l7-assertions` runs **alone**. Its file scope is `hooks/**` and `scripts/**` wholesale, so
no other lane may be in flight.

### L7-S1 — every shell assertion names the requirement it enforces

- **step_id:** `L7-S1` · **predecessors:** every other lane merged · **estimated_loc:** +40
- **file_scope.exclusive:** `hooks/tests/lib/`, and every `rg -Fq` call site under `hooks/`
  and `scripts/`
- **file_scope.may_read:** `hooks/tests/run.sh`, `.shepherd/runs/v646/carry-forward.md`
- **file_scope.must_not_touch:** `crates/**`, `.github/**`, `content/**`
- **interfaces — Produces:** one shared assertion helper under `hooks/tests/lib/`, sourced
  by every converted call site.

**[SKILLS]** `shell`
**[CONTEXT-INVENTORY]** Measured 118 `rg -Fq` occurrences under `hooks/` and `scripts/`, not
the 52 the issue reports (mesh R44). Under `set -euo pipefail` a bare `rg -Fq PATTERN FILE`
exits 1 and prints nothing, so the script dies without naming the requirement. Two
constraints bind the helper's location and shape: `hooks/tests/run.sh:18` globs every `*.sh`
at depth 1 of `hooks/tests/`, so a helper placed directly there would be **executed as a
test** — it must live in `hooks/tests/lib/` (G8). And per G7 each site becomes a
single-line call, not an inline three-line `if`, or the sprint's `expected_loc_delta` goes
positive by ~236 lines (correction C4). Per G5 the helper must treat exit 2 as an error, not
as a clean no-match — that is v646 carry-forward §4e, which turned a live scanner into a
no-op.
**[DO-NOT-DUPLICATE]** `grep -rn 'rg -Fq' hooks/ scripts/ | wc -l` before and after
(expected 118 → the seed's filtered count of 0), and
`ls hooks/tests/lib/ 2>/dev/null` (expected: absent before this step) — one helper, sourced
everywhere, never a second copy per file.
**[USER-STYLE]** bash 3.2 compatible. Diagnostics, not relaxation: each converted assertion
must still fail on exactly the input it failed on before.
**[NON-GOALS]** Do not change what any assertion asserts. Do not convert a site whose
current `rg` usage is already guarded (`if`, `&&`, `||`, `! rg`) — the seed's acceptance
filter excludes those deliberately.
**[ACCEPTANCE]**
```bash
grep -rn 'rg -Fq' hooks/ scripts/ | grep -vE '\|\||if |&&|! rg' | wc -l | grep -qx 0
# the helper is not itself collected as a test
bash hooks/tests/run.sh 2>&1 | { ! grep -q '== lib'; }   # ROOT FIX: was `grep -qv`
bash hooks/tests/run.sh; test $? -eq 0
# a deliberately broken assertion prints its requirement text
bash .shepherd/runs/v651/lanes/l7-assertions/evidence/falsify.sh 2>&1 \
  | grep -q 'requirement'
# exit 2 fails the gate rather than passing it
bash .shepherd/runs/v651/lanes/l7-assertions/evidence/exit2.sh; test $? -ne 0
```

**Actions**

1. Write `hooks/tests/lib/assert.sh` exposing one function that takes a pattern, a file, and
   a requirement string; prints the requirement to stderr and exits non-zero on no-match;
   and fails distinctly when the search tool could not read its input (exit 2).
2. Convert the unguarded call sites to single-line calls. Work file by file and record the
   per-file before/after count so the total is auditable.
3. Record two falsifications in the lane artifact: a deliberately broken assertion printing
   its requirement, and an unreadable input failing rather than passing.

---

## Close wave

### CLOSE-S1 — milestone 61 carries this sprint's work

- **step_id:** `CLOSE-S1` · **predecessors:** every lane merged · **estimated_loc:** 0
- **file_scope.exclusive:** none — `gh` state only
- **interfaces — Produces:** PR #328 and every issue this sprint closes attached to
  milestone `v6.5.1`.

**[CONTEXT-INVENTORY]** Milestone 61 `v6.5.1` exists, is open, and holds 0 issues; PR #328's
milestone is `null`. `gh auth status` reports the `repo` scope, so the edits are permitted.
The commands are `gh pr edit 328 --milestone "v6.5.1"` and
`gh issue edit <n> --milestone "v6.5.1"`. Per correction C5, #306 and #307 already carry
milestone 60 — do not move them without a stated reason.
**[NON-GOALS]** Do not close an issue this sprint did not measurably fix. Do not re-milestone
#306 or #307 silently.
**[ACCEPTANCE]**
```bash
gh pr view 328 --json milestone --jq '.milestone.title' | grep -qx 'v6.5.1'
# Root/critic trivial fix: this loop printed for a human to read, so half of D13
# was a judgement rather than a command with an expected exit code. It now
# asserts. `number` is also requested explicitly -- the previous --json list
# omitted it while the --jq referenced `.number`, so that field rendered null.
for n in 330 331 323 324 320 319 318 317 316 315 314; do
  gh issue view "$n" --json number,state,milestone \
    --jq '"\(.number) \(.state) \(.milestone.title // "NONE")"' \
    | grep -q 'v6.5.1' || exit 1
done
```

### CLOSE-S2 — the close report

- **step_id:** `CLOSE-S2` · **predecessors:** `CLOSE-S1` · **estimated_loc:** 0
- **file_scope.exclusive:** `.shepherd/runs/v651/close.md`,
  `.shepherd/runs/v651/carry-forward.md`, `CHANGELOG.md`
- **interfaces — Produces:** the close report, recording the result of `shepherd seed verify`
  against both this seed and the v6.4.6 seed, and the measured LOC delta.

**[ACCEPTANCE]**
```bash
cargo build --locked -p shepherd-cli --bin shepherd
export PATH="$PWD/target/debug:$PATH"
shepherd seed verify .shepherd/runs/v651/seed.md;  test $? -eq 0
shepherd seed verify .shepherd/runs/v646/seed.md;  test $? -eq 0
bash hooks/tests/run.sh; test $? -eq 0
cargo test --workspace --locked 2>&1 | grep -E 'test result: ok\. [1-9][0-9]* passed'
gh pr checks 328 | awk -F'\t' '$2=="fail"' | wc -l | grep -qx 0
git diff --shortstat main...HEAD
```

**[LOC DELTA — seed correction, root/critic trivial fix]** The seed locks
`expected_loc_delta: negative` (seed.md:17-18). Summing this plan's own per-step
`estimated_loc` figures nets roughly **+465**, so the seed's expectation is wrong and is
corrected here rather than quietly missed. The reason is that the seed itself sanctions four
NEW paths in `file_scope.exclusive` — `hooks/tests/fixtures/`, `hooks/tests/lib/`,
`scripts/check-version-lag.py`, `.shepherd/ctx/.gitkeep` — and the sprint's subtraction is
duplicate *authority* (one resolver, one Workflow definition, one gate list), not line count.
Deleting a duplicated resolver removes far fewer lines than wiring four gates adds.

The bare `git diff --shortstat` above reports the delta without asserting anything, which is
the same judgement-not-a-command defect corrected in CLOSE-S1. It is deliberately left
unasserted here: a threshold picked now would be invented, not measured. CLOSE-S2's report
must state the measured delta against this +465 estimate and explain any gap over 25%.

---

## Gates

1. **`W0-GATE` — reproduce before repair.** Every CRITICAL and HIGH deliverable reproduces
   as a failure with its literal output recorded before its fix lands. Discharged per lane
   by `L1-S1`, `L2-S1`, `L4-S1`, `L6-S1`. A lane that cannot reproduce its defect halts and
   escalates instead of writing a speculative fix. #314 and #315 reproduce only after
   `L1-S2`, which is why `l4-diagnostics` is in wave 2 and not wave 1.
2. **`GATE-REACHABILITY`.** For every gate this sprint touches or adds, the lane artifact
   records **both** the command that runs it in CI **and** the falsification proving it
   fails on purpose. Proving a gate can fail is not sufficient; unreachable from CI it is
   not a gate. Discharged as one table by `L6-S3`.
3. **`GATE-EXECUTION`** (new, from v646 carry-forward §0b and Class A). Every gate states
   how many things it checked and fails when that number is zero. A Rust acceptance quotes
   its `test result: ok. N passed` line with `N > 0`; a shell gate refuses an empty scan set.
   `ok` without a count is not evidence.
4. **`FULL-SUITE`.** On the merge candidate: `bash hooks/tests/run.sh` exits 0 reporting
   `0 failed` with a count of at least 29, and `cargo test --workspace --locked` exits 0 with
   a non-zero total.
5. **`CLONE-FIDELITY`** (amended by root at l3's escalation, 2026-08-19). A fresh
   `git clone --no-local` of the merge candidate carries `.shepherd/ctx`, `shepherd doctor`
   run inside that clone does **not** report `ctx directory is absent`, and a PreToolUse
   envelope against it emits no run-namespace banner. The original wording said "a detached
   worktree ... `shepherd doctor` exits 0 there" and was vacuous in both halves:
   `resolve_primary` (`crates/cli/src/context.rs:608-612`) resolves any linked worktree back
   to the main checkout, so doctor inspected the registered root tree and exited 0 before any
   fix existed. Exit 0 is also the wrong bar — a fresh clone lacks the git-ignored
   `shepherd.db` and `project.json` and must exit 3 until `shepherd init --confirm` runs, a
   behavior pinned by `crates/cli/tests/wave_c_bootstrap_cli.rs:259-266`. The absence of the
   `ctx` finding is what actually measures the carry.
6. **`CLOSE`.** `gh pr checks 328` reports zero `fail` rows, and the close report records
   `shepherd seed verify` against both this seed and the v6.4.6 seed. Note Q3: `main` has no
   branch protection, so this gate is enforced by this plan and by nothing else.

---

## Open questions for the critic

- **Q1 — the carrier lane is dissolved.** D1 is satisfied at plan base (correction C1), so
  seven seed partitions become seven lanes with a different membership: `carrier` is gone
  and `l7-assertions` is split out of `gate-wiring` because #318's 118 call sites span
  `hooks/**` and `scripts/**` and cannot be file-disjoint from `l2` or `l6` while they are in
  flight. Is splitting on that basis the right call, or should #318 be narrowed to the files
  already owned by `l6` and the repo-wide acceptance relaxed?
- **Q2 — `run.json` stays git-ignored.** `L3-S1`'s NON-GOALS refuse to re-include it, on the
  grounds that `L1-S2` makes an unregistered namespace harmless and tracking live run status
  would trade a fixed bug for permanent working-tree churn. The seed's D12 cites R33 and
  invites the opposite reading. If the critic disagrees, this is a one-line change in a lane
  that is already open.
- **Q3 — "CI green" is unenforced.** `main` has no branch protection and no required checks
  (HTTP 404). The sprint's own CLOSE gate is therefore a discipline, not a mechanism, and a
  red #328 can be squash-merged by hand. Turning on required checks is a repository setting,
  not a file in any lane's scope; it is an operator action in the same class as seed decision
  D5's npm publication. Flagged, not absorbed.
- **Q4 — npm has no publication path at all.** Beyond D5's "the operator ships the packages":
  there is no `npm publish` step and no `NPM_TOKEN` in any workflow, while `release.yml`
  verifies crates.io publication before tagging. Four packages have been stuck at 6.4.5 since
  2026-08-15 across three releases and nothing notices. Out of scope by D5, recorded for
  carry-forward as the same defect class as this sprint's theme.

---

## Deviations

(append-only; entries added by conductors as they occur)
