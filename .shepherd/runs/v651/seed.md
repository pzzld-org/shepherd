---
title: v6.5.1 Seed — make the gates that already exist actually run
branch: v6.5.1
base: main
kind: sprint-seed
status: ready-for-engineer
date: 2026-08-18
author: planter @ plant-v651-2026-08-18
planter_mesh: .shepherd/runs/v651/mesh.md
prior_close_report: .shepherd/runs/v646/close.md
prior_carry_forward: .shepherd/runs/v646/carry-forward.md
milestone: 61 (v6.5.1) — exists, empty, and PR #328 is not attached to it (mesh R76)
open_pr: 328 (v6.5.1 -> main, OPEN, draft, MERGEABLE) — currently RED (mesh R10)
sprint_dependencies: []
sprint_size: M
sprint_metadata:
  expected_loc_delta: negative
  subtract_note: >-
    Every gate this sprint needs already exists and is already correct. `scripts/gate.sh`,
    `hooks/tests/run.sh`, `scripts/generate-codex-carrier.py --check` and
    `scripts/check-workflow-meta.sh` are all written, all sound, and all reachable from
    nothing automated (mesh R13, R14, R15). The work is wiring, deleting a duplicated
    resolver, and replacing an archaeology-dependent fixture. A partition proposing a new
    subsystem, a new framework, or a new gate engine has misread the mesh and is a
    critic-RED escalation.
file_scope:
  exclusive:
    - plugins/shepherd/codex
    - scripts/generate-codex-carrier.py
    - crates/cli/src/dispatch_store.rs
    - crates/cli/tests/dispatch_store.rs
    - crates/cli/src/run_store.rs
    - crates/cli/src/cmd/native_hook.rs
    - crates/cli/tests/claude_hook_cli.rs
    - crates/cli/src/cmd/wave_h_execution.rs
    - content/predicates/dispatch-scope.toml
    - content/predicates/write-boundary.toml
    - crates/core/src/guard/engine.rs
    - crates/core/tests/guard.rs
    - hooks/tests/test_native_cli_contract.sh
    - crates/cli/src/cmd/wave_a_models.rs
    - crates/cli/tests/wave_a_models_cli.rs
    - crates/cli/src/cmd/wave_b2_seed.rs
    - crates/cli/tests/wave_b2_seed_cli.rs
    - .github/workflows/rust.yml
    - scripts/check-workflow-meta.sh
    - hooks/tests/test_workflow_meta_gate.sh
    - hooks/tests/fixtures            # NEW
    - hooks/tests/lib                 # NEW
    - scripts/check-version-lag.py    # NEW
    - .gitignore
    - .shepherd/ctx/.gitkeep          # NEW
    - crates/cli/src/cmd/wave_c_bootstrap.rs
  additive:
    - CHANGELOG.md
---

# v6.5.1 — the guards are written, sound, and connected to nothing

## A. Sprint theme

This repo does not have a shortage of gates. It has a shortage of gates that run.

`hooks/tests/run.sh` executes 28 tests, discovers them by glob so a hand-written array cannot
drift, fails loudly on zero discovery — and no workflow and no git hook invokes it (R14, R15).
Two of its 28 have been red on HEAD since v6.4.6 with no red build (R16). `scripts/gate.sh:92`
runs the Codex carrier check; nothing runs `scripts/gate.sh` (R13), so this branch's own first
commit shipped a drifted carrier and reddened PR #328 (R11, R12).

The theme is **connect and subtract**. Nothing here is a new capability. The largest single
change deletes a duplicated resolver.

## B. Why this sprint

One sentence covers the board: **work verified by a script no automated path invokes is not
verified.** Three independent failures measured here are all that sentence.

Two findings constrain the plan and are not negotiable. First, ordering:
`resolve_active_run` scans `.shepherd/runs/`, sorts lexically, and propagates the read error
from the first directory lacking `run.json` (R30). Eight tracked namespaces ship without one
because `.gitignore:35` never re-includes it (R32, R33), so `v500` aborts dispatch resolution
on **every clone**. That abort preempts the lifecycle path, so #314 cannot be measured until
it is fixed (R36, R46). Scheduling them concurrently produces a partition that cannot write a
failing test.

Second, severity: the banner is a symptom, and the repair text it prints converts an allowed
session into a denied one (R36d, R36e). An operator who follows shepherd's instructions ends
up worse off than one who ignores them. That is the sprint's highest-value single fix.

## C. Priors and lessons carried forward

1. **"Gates that cannot fail" was v6.4.6's named failure class. It recurred one level out.**
   v646 prior C2 made every gate prove it could fail, and it worked — the three surviving
   controls in `check-workflow-meta.sh` are that discipline (R27). The class mutated: these
   gates *can* fail and are never asked to. Provable failure is necessary, not sufficient; the
   gate must also be reachable from CI.
2. **v6.4.6 deleted `bin/` by its decision D4, making its own shipped seed unverifiable.**
   `shepherd seed verify .shepherd/runs/v646/seed.md` hard-fails on a `file_scope` path that
   sprint removed (R43). A gate validating against the live tree cannot validate a historical
   artifact. This is half of #319, and the half nobody filed.
3. **A remediation string is a contract, and this repo keeps breaking it.** `cc07276` fixed
   five that named a command exiting 2. R36d found one that runs, exits 0, and escalates the
   failure. The lint from `cc07276` cannot catch it (R36f).
4. **Do not trust an issue's own numbers.** #318 says 52 bare `rg -Fq`; measured 118 (R44).
   The brief says 52 open issues; measured 50 (R75). Every count here was re-measured.

## D. Engineering decisions (locked)

Changing one of these is a critic-RED escalation, not a sprint-time judgement.

1. **The Workflow guard is not fail-open; the fix is test-side.** The assertion at
   `hooks/tests/test_native_cli_contract.sh:82-88` is `ee682ec` (v6.4.5). The carve-out it
   contradicts, `crates/core/src/guard/engine.rs:401` `&& tool_name != "Workflow"`, is
   `f3d44b0` (v6.4.6), deliberate and commented; the test was never updated (R21). A tier
   sweep proves the guard denies `conductor`, `coder`, `auditor` and allows only root tier
   (R22). Do not remove the carve-out — rewrite the assertion to the v6.4.6 contract and add
   the restricted-tier denial as its negative control.
2. **`planter -> allow` for an undeclared-target Workflow belongs to #323, not to D1.** The
   planter's only sanctioned dispatch is `shepherd:discovery`, yet a conductor may dispatch
   `planter` and `shepherd` outright (R41). Fix it in
   `content/predicates/dispatch-scope.toml` by extending the target-keyed restriction, not by
   touching the Workflow branch.
3. **Replace the git-archaeology control with an in-repo fixture; do not restore the commit.**
   `scripts/check-workflow-meta.sh:259` shells `git show 686084d:workflows/wave.js`; the
   object is absent from a 93-commit clone (R26) and restoring it would not survive the next
   transfer. The rejected corpus becomes a checked-in file.
4. **`shepherd ready`'s errno is one helper pair, not N call sites.** `errno` and `errno_path`
   in `crates/cli/src/run_store.rs` govern 16 sites (R38). Fix the helpers, not `ready`.
5. **Publishing to npm is an operator action, not a partition.** `component-runtime@6.5.1`
   gates `pi-claude`, `pi-codex` and `pi-shepherd` at once (R53, R54). This sprint ships the
   detector; the operator ships the packages.

## E. Deliverables

### Codex carrier projection is regenerated and CI goes green

**Priority:** CRITICAL
**GH:** none — regression introduced by this branch's own `cc07276` (mesh R11, R12)

`plugins/shepherd/codex/skills/shepherd/SKILL.md` is missing the 12-line `## Preconditions`
block that `cc07276` added to `skills/shepherd/SKILL.md`. This is the only red check on
PR #328 and it blocks every other item's evidence.

- **Acceptance:** `python3 scripts/generate-codex-carrier.py --check` exits 0.
- **Acceptance:** `python3 scripts/check-plugin.py` exits 0.

### Dispatch resolution stops aborting on a directory that is not a run

**Priority:** CRITICAL
**GH:** #330

`resolve_active_run` propagates the `run.json` read error instead of skipping a namespace that
is not a run, in both platform modules (R30, R31). A directory without `run.json` is not a run
and must be skipped exactly as a non-conforming name already is; the two duplicated copies
collapse to one implementation. Not cosmetic: on `SubagentStop` the same error becomes a
blocking decision at `crates/cli/src/cmd/native_hook.rs:147-153` while every other event
degrades to advisory context at `:154-163` (R36b), and it rejected both the `SubagentStart`
opening and the `Stop` closing of the session that authored this seed (R36a).

**The remediation this defect prints is actively harmful and is fixed in the same change.**
Running the two commands the banner names flips `run_namespace_is_usable` (`:549-563`) true,
routing the same unchanged error to the deny arm at `:532-535`: allowed-with-a-banner becomes
every tool denied, and `v500` never gains a `run.json` (R36d, R36e). The lint from `cc07276`
cannot catch it — the command is runnable, just wrong (R36f).

- **Acceptance:** in a tree containing `.shepherd/runs/v500/` with only `plan.md` and one
  namespace with `status: executing`, `shepherd claude-hook` fed a PreToolUse envelope emits
  no `no usable run namespace` text; exit 0.
- **Acceptance:** the same tree fed a `SubagentStop` envelope carrying a valid dispatch
  binding does not emit `"decision":"block"`; the probe script exits 0.
- **Acceptance:** following the remediation text the hook prints, verbatim and in order,
  never converts an allowed decision into `"permissionDecision":"deny"`; the sandbox script
  from R36c asserts this and exits 0.
- **Acceptance:** `grep -c "fn resolve_active_run" crates/cli/src/dispatch_store.rs` returns
  a value strictly less than 3.
- **Acceptance:** `cargo test -p shepherd-cli --test dispatch_store` exits 0, with a new case
  that fails against `1c39f4c`.

### The unbound-session and SessionStart lifecycle defects are measured and fixed

**Priority:** HIGH
**GH:** #315, #314, #306

#314 remains unobservable in this repo because the previous deliverable's defect preempts it
(R36, R46). #315 is now **measured**: the R36c sandbox unmasks it, and its denial reason is
`dispatch filesystem operation \`open regular file\` failed for …/runs/<run>/dispatch/
.root-session.<id>.json: No such file or directory (os error 2)` — correctly fail-closed, with
a bare errno naming an internal dispatch file (R36g). Use that sandbox as the harness. #306
may already be satisfied by `crates/cli/src/cmd/native_hook.rs:521-531`; re-measure before
writing code.

- **Acceptance:** the #315 denial reason names the session-binding condition and a command;
  `printf '{"hook_event_name":"PreToolUse","session_id":"stranger",...}' | shepherd
  claude-hook | grep -qv 'os error'` exits 0.
- **Acceptance:** a `SessionStart` envelope replayed twice for one session id produces
  identical non-rejection output both times; the replay probe script exits 0.
- **Acceptance:** `cargo test -p shepherd-cli --test claude_hook_cli` exits 0.

### Operator-facing errors name an action, not an errno

**Priority:** HIGH
**GH:** #331

`shepherd ready --run dummy` exits 5 with `open state directory ...: No such file or directory
(os error 2)` (R37). Fix `errno` and `errno_path` in `crates/cli/src/run_store.rs` so all 16
call sites carry a command-level diagnostic naming the run and the way to list runs.

- **Acceptance:** `shepherd ready --run dummy 2>&1 | grep -q 'os error'` exits 1.
- **Acceptance:** `shepherd ready --run dummy` still exits 5.

### A lane lead cannot dispatch the root orchestrator or the planter

**Priority:** HIGH
**GH:** #323

`conductor -> planter` and `conductor -> shepherd` both return `allow` (R41). The
target-keyed restriction in `content/predicates/dispatch-scope.toml` names only `engineer`
and `critic`. Extend it, and regenerate the compiler projection.

- **Acceptance:** for each of `planter`, `shepherd`, `root`, printing
  `{"tool_name":"Agent","role":"conductor","tool_input":{"subagent_type":"<t>"}}` into
  `shepherd guard eval` yields `"decision": "deny"`; the sweep script exits 0.
- **Acceptance:** `conductor -> coder` still returns `allow`.
- **Acceptance:** `cargo test -p shepherd-core --test guard` exits 0.

### The Workflow contract has exactly one written definition

**Priority:** HIGH
**GH:** #320

Per decision D1, reconcile `hooks/tests/test_native_cli_contract.sh:82-88` to the v6.4.6
semantics and add the restricted-tier denial as its negative control. Reproduce #320's
`Write`-versus-`Bash` asymmetry in the same pass — it is the same predicate tier and the same
file scope (R48) — then fix or close it with the measurement.

- **Acceptance:** `bash hooks/tests/test_native_cli_contract.sh` exits 0.
- **Acceptance:** reverting `crates/core/src/guard/engine.rs:401` to drop the carve-out turns
  that test red; the falsification is recorded in the partition artifact.
- **Acceptance:** a two-payload `guard eval` diff for #320 is recorded with its verdict, and
  either the asymmetry is removed or the issue is closed citing the output.

### The workflow-meta negative control runs without git history

**Priority:** HIGH
**GH:** none — carry-forward from the org transfer; enables `hooks/tests/run.sh` to reach 28/28

`scripts/check-workflow-meta.sh:259` depends on commit `686084d`, absent from this 93-commit
clone (R26). Per decision D3, check the rejected corpus into `hooks/tests/fixtures/`.

- **Acceptance:** `bash hooks/tests/test_workflow_meta_gate.sh` exits 0.
- **Acceptance:** `bash scripts/check-workflow-meta.sh --self-test` exits 0 and prints
  `PASS  NEGATIVE control`.
- **Acceptance:** `git grep -c 686084d scripts/ hooks/` returns 0 outside comments.

### CI runs the shell gate tier

**Priority:** CRITICAL
**GH:** none — root cause of this sprint (mesh R13, R14, R15, R16)

Add `hooks/tests/run.sh` and the carrier projection check to `.github/workflows/rust.yml`.
Without this, every other deliverable regresses silently the next time.

- **Acceptance:** `.github/workflows/rust.yml` contains a step invoking `hooks/tests/run.sh`;
  `grep -q 'hooks/tests/run.sh' .github/workflows/rust.yml` exits 0.
- **Acceptance:** `bash hooks/tests/run.sh` exits 0 and prints `28/28 tests ran, 0 failed`.
- **Acceptance:** `gh pr checks 328` reports zero `fail` rows.

### Shell assertions name the requirement they enforce

**Priority:** MEDIUM
**GH:** #318

118 bare `rg -Fq` assertions, not the 52 filed (R44). Under `set -e` each aborts anonymously.
Introduce one shared helper under `hooks/tests/lib/` and convert the call sites.

- **Acceptance:** `grep -rn 'rg -Fq' hooks/ scripts/ | grep -vE '\|\||if |&&|! rg' | wc -l`
  returns 0.
- **Acceptance:** a deliberately broken assertion prints its requirement text; the
  falsification run is recorded in the partition artifact.
- **Acceptance:** `bash hooks/tests/run.sh` exits 0.

### The root role has one name across every surface

**Priority:** MEDIUM
**GH:** #324

`shepherd models resolve shepherd` exits 2 naming `root`, while the guard engine accepts
`role: "shepherd"` and returns a verdict (R42). Two surfaces, two vocabularies. Pick one and
make the other an accepted alias with a stated direction.

- **Acceptance:** `shepherd models resolve shepherd --harness claude` exits 0.
- **Acceptance:** `shepherd models resolve root --harness claude` exits 0.
- **Acceptance:** `shepherd models resolve nonsense --harness claude` exits 2.

### The seed gate accepts the seeds this project actually writes

**Priority:** MEDIUM
**GH:** #319

Measured live: the v6.4.6 seed hard-fails on both footprint and a `file_scope` path v6.4.6
itself deleted (R43, prior C2). This seed is the live experiment — authored against the gate
read from source, it passes at 377 of the 400-line cap, over the 300-line smell threshold
(R63a). The cap is tight for `sprint-seed`, not only mis-tiered for `patch-seed`.

- **Acceptance:** `shepherd seed verify .shepherd/runs/v646/seed.md` exits 0, or the gate
  emits a warning rather than a HARD failure for a historical seed whose scope has since been
  removed. The chosen semantics are stated in `CHANGELOG.md`.
- **Acceptance:** `shepherd seed verify .shepherd/runs/v651/seed.md` still exits 0.
- **Acceptance:** `cargo test -p shepherd-cli --test wave_b2_seed_cli` exits 0.

### A fresh clone is a working clone

**Priority:** MEDIUM
**GH:** #316, #317

`.shepherd/ctx` is absent from a detached checkout of HEAD (R45). `run.json` is git-ignored
while its namespace directories are tracked (R33) — the same class, and the cause of the
CRITICAL above. No gate anywhere compares the binary on PATH to the manifest (R49), which is
why 6.5.0 ran against a 6.5.1 tree.

- **Acceptance:** in a detached worktree of HEAD, `test -d .shepherd/ctx` exits 0.
- **Acceptance:** `shepherd doctor` in an unregistered fresh checkout exits 0.
- **Acceptance:** `python3 scripts/check-version-lag.py` exits non-zero while
  `~/.cargo/bin/shepherd --version` reports `6.5.0` against a `6.5.1` manifest, and exits 0
  once they agree.

### PR #328 and the triaged issues are attached to milestone 61

**Priority:** LOW
**GH:** #317 (tracking); milestone 61 `v6.5.1` exists and is empty (mesh R76)

- **Acceptance:** `gh pr view 328 --json milestone --jq '.milestone.title'` prints `v6.5.1`.
- **Acceptance:** every issue this sprint closes carries milestone `v6.5.1`.

## F. Recommended topology

Recommendation only. The Stage Graph is binding, and partition-to-executor mapping is the
engineer's call, not this seed's.

Seven file-disjoint partitions — **carrier**, **resolution**, **diagnostics**,
**dispatch-scope**, **vocabulary**, **gate-wiring**, **clone-fidelity**. Their exact exclusive
file lists are enumerated once in mesh R64–R71 and are not restated here, so the scope has a
single source of truth. No file appears in two partitions; `CHANGELOG.md` is additive and
shared by convention.

Only two orderings are real. **carrier first** — its red hides every other partition's CI
evidence. **resolution before diagnostics** — #330 preempts #314 (R36, R46), and it is what
makes the harmful remediation reachable at all. Everything else is parallel-safe;
gate-wiring lands last because it needs the other partitions green to go green itself.

## G. Explicitly out of scope, each with its reason

- **#327 shepherd-agents Rust framework** — net-new subsystem; contradicts the negative-LOC
  premise outright.
- **#325 GitHub Pages site** — net-new surface, not a correctness defect reachable in v6.5.1.
- **#326 FL03 -> pzzld-org URL flip** — gated on an external org-transfer step this sprint
  does not control; flipping early breaks both install paths.
- **#321 Windows 94/384 failures** — refuted as a blocker: both `test (windows-latest, …)`
  jobs PASS on #328 (R10). Needs its own sprint on a real host.
- **#308 obsidian-vault nightly.yml** — filed against a different repository.
- **#301 cargo xtask consolidation** — net-new build-orchestration subsystem; same premise
  violation as #327.
- **#298 denied dispatch reserves task_name** — state-machine change, not a repair; no
  reproduction exists on this branch and producing one is itself a sprint.
- **#307 `~/.local/target/debug/shepherd`** — refuted: `git grep "\.local/target"` returns no
  hits (R50). Describes an artifact absent from this tree; re-file where it reproduces.
- **#284–#298 SQL-injection cluster (15 issues)** — real, scoped to retired shell surfaces the
  native CLI replaced; folding them in triples the sprint and reopens deleted code.
- **npm publication of `component-runtime@6.5.1` and the three harness packages** — operator
  release action per D5.

## H. Gates

1. **W0-GATE** — the CRITICAL and HIGH deliverables each reproduce as a failure, with the
   exact failing output recorded, before any fix lands. #314 reproduces only after the
   resolution deliverable, which is why the §F ordering is binding rather than advisory. The
   R36c sandbox is the harness for #330, #315 and the harmful remediation.
2. **GATE-REACHABILITY** — for every gate this sprint touches or adds, the artifact records
   both the command that runs it in CI and the falsification proving it fails on purpose.
   Proving a gate can fail is not sufficient; unreachable from CI, it is not a gate. This is
   the sprint's own theme applied to itself.
3. **FULL-SUITE** — `bash hooks/tests/run.sh` prints `28/28 tests ran, 0 failed` and
   `cargo test --workspace` exits 0, both on the merge candidate.
4. **CLONE-FIDELITY** — a detached worktree of the merge candidate carries `.shepherd/ctx`,
   and a PreToolUse envelope against it emits no run-namespace banner.
5. **CLOSE** — `gh pr checks 328` reports zero `fail` rows, and the close report records the
   result of `shepherd seed verify` against both this seed and the v6.4.6 seed. "Done" is CI
   green on #328, not code written.
