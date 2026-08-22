---
title: v6.5.6 Sprint Plan — truthful lifecycle under Claude, Codex, and Pi
run: v656
runId: v656
branch: v6.5.6
base: main
seed: .shepherd/runs/v656/seed.md
mesh: .shepherd/runs/v656/mesh.md
planning_evidence: .shepherd/runs/v656/phase0.md
author: shepherd-engineer-v656-via-worker-fallback
date: 2026-08-22
plan_base_commit: 8d60002bd6fccc51911629526537eeda624c04d9
sprint_size: M
waves: 5
lanes: 6
max_parallel: 3
status: draft-pre-critic
---

# v6.5.6 implementation plan

## Goal

Prove one native Rust and Component Model policy core completes truthful
role → dispatch → guard → report lifecycles through Claude, Codex, and Pi. Fix only
reproduced defects. Preserve installation, configuration, artifact, and release mechanisms
when their current regression probes pass.

## Planning transport disclosure

The Pi provider exposed no `shepherd:engineer`, `auditor`, or `discovery`. This plan was
prepared through one worker transport plus concurrent read-only inspection. That mismatch is
#370 evidence. Pi also rejected normal shell and artifact-write calls with the live #368
`call_*|fc_*` identifier. Root persisted this plan and owns its gate.

## Seed corrections

| ID | Seed claim | Measured correction |
|---|---|---|
| C1 | Pi exposes nine dispatchable roles. | Seven roles are dispatchable. `shepherd` and `planter` remain top-level but retain canonical identities. |
| C2 | #367 requires compatibility implementation. | Typed legacy removal exists in `loader.rs`; first run a live regression and change production only if it fails. |
| C3 | Seed scope covers #369. | The authored source is `content/skills/spawn/SKILL.md`; generated carriers follow from it. |
| C4 | Replace every FL03 string. | Replace current runtime/install URLs only; preserve historical records and attribution. |
| C5 | A normal composite role wave ran. | #370 prevented role dispatch; concurrent read-only inspection was the fallback. |
| C6 | Planning writes work despite #368. | Pi blocked Bash and artifact writes; #368 is the sole first implementation partition. |

## Global constraints

1. No implementation outside `pi-bootstrap` begins until a normal Pi Write/Edit and guard call
   succeeds with a standard `call_*|fc_*` identifier.
2. Rust core and Component Model remain policy authority. Harness adapters translate.
3. General configuration stays on `dep:config`. Direct `dep:toml` remains limited to typed,
   non-configuration guard predicate objects.
4. No new dependency without a measured gap and critic approval. Standard library and installed
   dependencies come first.
5. No shell-language parser. Unknown shell effects fail closed.
6. No tracked build output, repo launcher, committed generated carrier, or new artifact service.
7. Every partition has one deterministic regression, one negative control, one periodic eval
   pair, one gate, and one measurable outcome.
8. Every test command reports a non-zero executed-case count. Zero discovery fails.
9. PR #372 remains draft. No publish, tag, release, merge, milestone mutation, or permission
   change runs without operator confirmation.
10. Cargo work uses isolated temporary target directories where needed and is serialized at
    integration. No production credentials are read or printed.
11. Partitions own exact files. Root integrates shared release notes after review.
12. A green historical v6.4.6 regression means no implementation change.

## Wave topology

| Wave | Partitions | Release condition |
|---|---|---|
| 0 | `pi-bootstrap` alone | Normal Pi writes work and seven dispatchable roles are provider-visible. |
| 1 | `least-authority`, `first-run`, `gate-provenance` concurrently | All three gates and adversarial reviews pass. |
| 2 | `release-trust` alone | Runtime URLs, security posture, dependency ownership, and version scanning pass. |
| 3 | `harness-semantics` alone | Claude, Codex, and Pi complete the lifecycle matrix. |
| 4 | Root integration and concern-split review | Full gates pass on one exact commit; PR #372 remains draft. |

## Lane: Pi bootstrap

lane: pi-bootstrap

**Issues:** #368, #370
**Wave:** 0, exclusive blocker

### Scope

- `crates/core/src/dispatch/identifier.rs`
- `crates/core/src/dispatch/portable.rs`
- `crates/core/tests/portable_dispatch.rs`
- `crates/component/src/lib.rs`
- `crates/component/tests/component.rs`
- `crates/compiler/src/compiler.rs`
- `crates/compiler/tests/compile.rs`
- `packages/harness-pi/src/**`
- `packages/harness-pi/test/**`
- `packages/harness-pi/shepherd.pi.json`
- `scripts/stage-pi-carrier.sh`
- `scripts/tests/test-pi-package-surface.sh`
- `scripts/tests/test-generated-carrier-authority.sh`
- `services/eval/evals/cases/v656/pi-bootstrap_good.txt` (NEW)
- `services/eval/evals/cases/v656/pi-bootstrap_bad.txt` (NEW)

### Work

1. Reproduce the exact `call_*|fc_*` failure through the Pi extension test harness.
2. Add a Pi adapter-boundary tool-call normalizer using Node standard library only. Produce a
   bounded collision-resistant correlation token while leaving project, session, run, lane,
   role, and agent validation unchanged.
3. Compare native responses to the normalized token, not the raw provider value.
4. Add malformed, oversized, control-character, cross-session, cross-agent, and deliberate
   collision negative cases.
5. Locate and document the installed `pi-subagents` registration contract before editing. Do
   not guess a manifest key.
6. Generate provider-visible profiles from compiler-owned role data for exactly the seven
   `dispatchable: true` roles. Keep `shepherd` and `planter` canonical but top-level.
7. Prove staged carriers contain seven provider registrations, nine canonical identities, all
   supported skills/prompts, and no committed generated tree.

### Deterministic test

Rust component/core tests cover normalized correlation and strict sibling identifiers.
`node packages/harness-pi/test.mjs` covers the live adapter. Package staging tests count seven
provider-visible profiles and fail at zero.

### Negative control

Restore raw compound forwarding in a scratch mutation and require `invalid-identifier`. Remove
one generated dispatchable role and require the stage gate to name it.

### Periodic eval

`pi-bootstrap_good.txt` requires adapter-boundary normalization and generated seven-role
registration. `pi-bootstrap_bad.txt` proposes relaxing `SessionId`, hand-copying agents, or
claiming nine spawnable roles.

### Gate

```sh
cargo test -p shepherd-core --features full --test portable_dispatch
cargo test -p shepherd-component
cargo test -p shepherd-compiler
node packages/harness-pi/test.mjs
bash scripts/tests/test-pi-package-surface.sh
bash scripts/tests/test-generated-carrier-authority.sh
```

### Acceptance

- A real Pi Write/Edit with a standard compound tool-call ID reaches native guard policy.
- Session IDs containing `|` still fail.
- Seven dispatchable roles appear through the provider with literal role identity.
- `shepherd` and `planter` remain non-spawnable top-level roles.
- No generated Pi role tree is tracked.

### Measurable outcome

Pi normal tool execution moves from blocked to passing; provider coverage moves from worker-only
fallback to 7/7 dispatchable Shepherd roles.

## Lane: Native least authority

lane: least-authority

**Issues:** #320, #334
**Wave:** 1

### Scope

- `crates/cli/src/dispatch_service.rs`
- `crates/cli/tests/dispatch_cli.rs`
- `crates/cli/tests/claude_hook_cli.rs`
- `crates/core/src/guard/engine.rs`
- `crates/core/src/guard/model.rs`
- `crates/core/tests/guard.rs`
- `content/predicates/write-boundary.toml`
- `crates/compiler/package-content/content/predicates/write-boundary.toml`
- `services/eval/evals/cases/v656/least-authority_good.txt` (NEW)
- `services/eval/evals/cases/v656/least-authority_bad.txt` (NEW)

### Work

1. Reproduce identical out-of-scope effects through Write, Edit/patch, and Bash.
2. Replace root fallback `lane: None` plus `["**"]` with truthful role-derived facts.
3. Represent read-only dispatch as explicitly non-writable.
4. Missing or empty Bash command input returns unresolved/deny.
5. Bounded or read-only dispatches fail closed for arbitrary shell effects. Do not infer safety
   by token scanning.
6. Run real role workflows. If required shell work becomes impossible, keep the partition RED
   and escalate the capability conflict instead of adding a parser.

### Deterministic test

Table-driven native tests cover root, bounded writer, read-only reviewer, sibling partition,
missing Bash input, structured write, patch, and unknown shell effect.

### Negative control

Mutate root fallback back to `["**"]` and require failure. Change missing Bash input to allow
and require the guard test to fail.

### Periodic eval

The good case requires explicit non-writable scope and fail-closed unknown effects. The bad case
proposes substring parsing or universal scope.

### Gate

```sh
cargo test -p shepherd-core --features full guard
cargo test -p shepherd-cli --test dispatch_cli
cargo test -p shepherd-cli --test claude_hook_cli
```

### Acceptance

- Dispatch records carry actual partition and bounded/non-writable scope.
- Structured and shell-capable paths cannot perform equivalent unauthorized effects.
- Missing Bash input never allows.
- No shell parser or second guard authority exists.

### Measurable outcome

Vacuous dispatch scopes fall to zero; the #320 matrix denies every unauthorized carrier.

## Lane: First-run compatibility

lane: first-run

**Issues:** #367, #369
**Wave:** 1

### Scope

- `crates/core/tests/loader.rs`
- `content/skills/spawn/SKILL.md`
- `skills/spawn/SKILL.md`
- `plugins/shepherd/codex/skills/spawn/SKILL.md`
- `crates/compiler/package-content/content/skills/spawn/SKILL.md`
- `scripts/generate-content-oracle.py`
- `scripts/tests/test-generate-compiler-package-content.py`
- `services/eval/evals/cases/v656/first-run_good.txt` (NEW)
- `services/eval/evals/cases/v656/first-run_bad.txt` (NEW)

### Work

1. Run the exact legacy `paths.reports` reproduction against ordinary load and migration.
2. If it passes, add only the missing source-named regression and close #367 without production
   changes.
3. Update authored spawn guidance so absent planted state prints one action: initialize the run,
   plant the seed, then spawn.
4. Preserve that `shepherd init --confirm` never runs implicitly.
5. Regenerate canonical and Codex projections from authored content; never hand-edit drift.

### Deterministic test

Loader tests prove typed retired keys are discarded while wrong historical types fail. Content
projection tests prove the first-run action survives every carrier.

### Negative control

Use `paths.reports = false` and require failure. Remove the run-init action from a scratch source
and require projection acceptance to fail.

### Periodic eval

Good guidance distinguishes project initialization, run planting, and spawn. Bad guidance
silently retries or mutates initialization as a side effect.

### Gate

```sh
cargo test -p shepherd-core --features full loader
python3 scripts/generate-content-oracle.py --check
python3 scripts/check-plugin.py
```

### Acceptance

- Legacy typed `paths.reports` does not block doctor, migration, or spawn.
- Malformed legacy values fail loudly.
- First-run guidance provides one explicit transition without silent mutation.
- Authored and generated spawn carriers are byte-consistent.

### Measurable outcome

Both #367 and #369 reproductions end in actionable success with zero parallel config parser.

## Lane: Gate provenance

lane: gate-provenance

**Issue:** #374 A1
**Wave:** 1

### Scope

- `hooks/scripts/bash_post.sh`
- `hooks/tests/test_bash_post_ledger.sh`
- `hooks/tests/run.sh`
- `docs/integration.md`
- `services/eval/evals/cases/v656/gate-provenance_good.txt` (NEW)
- `services/eval/evals/cases/v656/gate-provenance_bad.txt` (NEW)

### Work

1. Reproduce false proof from comments, echo, printf, quoted text, concatenation, aliases,
   wrappers, missing command, and failing gate.
2. Stop naming substring observations `gates-ran`.
3. Record them as non-authoritative observations or delete the ledger.
4. Successful verification comes only from explicit invocation/result evidence owned by the
   wave artifact.
5. Do not parse shell syntax or infer execution from outer Bash status.

### Deterministic test

Hook tests cover every adversarial string and require no successful provenance row.

### Negative control

Restore substring matching and require comment, echo, and failing-gate cases to fail.

### Periodic eval

Good evidence distinguishes observed text, invoked process, and successful result. Bad evidence
uses substring presence or wrapper status.

### Gate

```sh
bash hooks/tests/test_bash_post_ledger.sh
bash hooks/tests/run.sh
```

### Acceptance

No command-text-only input satisfies a required gate; unverified, invoked, failed, and passed
states are distinguishable.

### Measurable outcome

Substring-only successful gate records fall from reproducible positives to zero.

## Lane: Release trust and identity

lane: release-trust

**Issues:** #326, #351, #374 A2/A5
**Wave:** 2

### Scope

- `scripts/version-bump.py`
- `scripts/tests/test-version-bump.py`
- `scripts/check-deps.mjs`
- `scripts/tests/test-dependency-policy.py` (NEW)
- `.github/dependabot.yml`
- `.claude/settings.json`
- `SECURITY.md` (NEW)
- `Cargo.toml`
- `package.json`
- `package-lock.json`
- `README.md`
- `QUICKSTART.md`
- `.claude-plugin/plugin.json`
- `plugins/shepherd/.claude-plugin/plugin.json`
- `plugins/shepherd/.codex-plugin/plugin.json`
- `.github/workflows/release.yml`
- `services/eval/evals/cases/v656/release-trust_good.txt` (NEW)
- `services/eval/evals/cases/v656/release-trust_bad.txt` (NEW)

### Work

1. Make version authority inspect tracked source or explicitly exclude ignored `.pi` runtime
   state without excluding a future tracked `.pi` authority.
2. Add fixtures for ignored runtime state and tracked unclassified surfaces.
3. Replace current install/runtime FL03 URLs with `pzzld-org`; preserve history/attribution.
4. Establish one compatibility report across native CLI, component, package manifests, and
   staged carrier versions.
5. Remove unsafe shared Claude permission defaults and personal automation preferences.
6. Add `SECURITY.md`; extend Dependabot to npm and Cargo.
7. Add deterministic reachability/waiver policy for shipped high/critical findings.
8. Upgrade only measured reachable findings, never speculatively.

### Deterministic test

Version fixtures, URL inventory, shared-settings rejection, dependency ecosystem inventory,
and waiver-expiry checks fail on synthetic violations.

### Negative control

Add ignored `.pi/tasks/current.json` and require no failure; add the same unclassified version
to tracked source and require failure. Reintroduce bypass mode and require rejection.

### Periodic eval

Good release posture classifies reachability, fixed version, waiver expiry, and shipped artifact.
Bad posture suppresses raw audit counts without ownership.

### Gate

```sh
python3 scripts/tests/test-version-bump.py
python3 scripts/tests/test-dependency-policy.py
node scripts/check-deps.mjs
python3 scripts/check-github-actions.py
python3 scripts/check-plugin.py
cargo deny --workspace --all-features check
```

### Acceptance

- Ignored runtime state cannot create false version drift; tracked references still fail.
- Current install/runtime URLs use `pzzld-org`.
- Shared settings contain no bypass mode, unrestricted Bash, or prompt suppression.
- npm, Cargo, and GitHub Actions receive update coverage.
- No reachable production high/critical remains unwaived.

### Measurable outcome

One compatibility report is green; unsafe defaults and unowned reachable highs/criticals reach zero.

## Lane: Cross-harness semantics and eval integration

lane: harness-semantics

**Issue:** #374
**Wave:** 3

### Scope

- `packages/harness-claude/**`
- `packages/harness-codex/**`
- `packages/component-runtime/**`
- `scripts/test-active-adapters.mjs`
- `scripts/test-adapters-component.mjs`
- `scripts/tests/test-harness-surface-parity.sh`
- `hooks/scripts/generate_harness_parity.sh`
- `hooks/tests/test_harness_parity_generator.sh`
- `services/eval/evals/run_eval.sh`
- `services/eval/evals/cases/v656/harness-semantics_good.txt` (NEW)
- `services/eval/evals/cases/v656/harness-semantics_bad.txt` (NEW)
- `services/eval/evals/v656-manifest.tsv` (NEW)
- `services/eval/tests/test-v656-manifest.sh` (NEW)

### Work

1. Consume completed contracts without reimplementing policy.
2. Generate one supported event × harness matrix for identity, lifecycle, dispatch, guard,
   report, compaction, failure, and host limitations.
3. Complete one clean role → dispatch → guard → report lifecycle on each harness.
4. Record native input/result, adapter translation, artifact path, and negative control per cell.
5. Register all v656 eval pairs in one deterministic manifest runner.
6. Fail on zero evals, missing sibling, duplicate ownership, or unsupported capability claimed.
7. Prove both Cargo install paths only after doctor, identity, and hook preflight pass.

### Deterministic test

Active-adapter tests and matrix generation cover all supported cells and fail on zero. Eval
manifest tests prove every implementation partition contributed one good/bad pair.

### Negative control

Delete one matrix cell, duplicate one event, claim unsupported Codex correlation, and remove one
bad eval sibling. Every mutation must fail.

### Periodic eval

Run all v656 pairs through local Claude Code. Good cases pass, bad cases fail, and every pair
clears the configured margin.

### Pre-release cold install gate

Use only local source and fixture assets before publication:

```sh
tmp_root="$(mktemp -d /tmp/shepherd-v656-install.XXXXXX)"
CARGO_HOME="$tmp_root/cargo-home" CARGO_TARGET_DIR="$tmp_root/target" \
  cargo install --path crates/cli --locked --root "$tmp_root/install"
"$tmp_root/install/bin/shepherd" --version
python3 scripts/tests/test-cargo-binstall-local.py
```

Both commands must report non-zero executed checks and the exact candidate version.

### Gate

```sh
node scripts/test-adapters-component.mjs
node scripts/test-active-adapters.mjs
bash scripts/tests/test-harness-surface-parity.sh
bash hooks/tests/test_harness_parity_generator.sh
bash services/eval/tests/run.sh
SHEPHERD_EVAL_LIVE=1 bash services/eval/evals/run_eval.sh
```

### Acceptance

- 3/3 harnesses complete the lifecycle.
- Every supported matrix cell has behavioral evidence; limitations are explicit.
- Every fixed defect has a regression and registered eval pair.
- Cold Cargo install and metadata-only Binstall report `6.5.6` without checkout state.

### Measurable outcome

Clean lifecycle completion reaches 3/3 and supported matrix coverage reaches 100%.

## Wave 4 root integration

Root integrates only after every partition has a clean independent audit.

1. Confirm exact branch, HEAD, clean tree, native CLI, doctor, identity, version, dependency,
   and artifact preflight.
2. Confirm #368 normal Pi tools before accepting later evidence.
3. Run `shepherd plan verify --run v656` and all targeted gates.
4. Run repository fast/full gates serially against one exact commit.
5. Run Rust, Node, hooks, component, package, archive, supply-chain, Linux, Windows, and evals.
6. Before publication, run the local isolated source-install and Binstall fixture commands from
   the harness-semantics gate. They must report the exact candidate version.
7. Verify no tracked output, generated carrier, repo launcher, or mutable legal payload.
8. Verify PR #372 remains draft.
9. After explicit operator confirmation, create milestone `v6.5.6` and attach #374 plus PR #372:

   ```sh
   gh api repos/pzzld-org/shepherd/milestones --method POST -f title=v6.5.6
   gh issue edit 374 --repo pzzld-org/shepherd --milestone v6.5.6
   gh pr edit 372 --repo pzzld-org/shepherd --milestone v6.5.6
   ```

   If the milestone already exists, query and reuse it rather than creating a duplicate.
10. Only after operator-approved publication makes immutable 6.5.6 registry artifacts visible,
    run external smoke tests from isolated Cargo homes:

    ```sh
    install_home="$(mktemp -d /tmp/shepherd-v656-registry-install.XXXXXX)"
    CARGO_HOME="$install_home/cargo-home" cargo install shepherd-cli --version '=6.5.6' --locked
    "$install_home/cargo-home/bin/shepherd" --version
    binstall_home="$(mktemp -d /tmp/shepherd-v656-registry-binstall.XXXXXX)"
    CARGO_HOME="$binstall_home/cargo-home" cargo binstall shepherd-cli --version 6.5.6
    "$binstall_home/cargo-home/bin/shepherd" --version
    ```
11. Dispatch concern-split review for correctness, security, test integrity, subtraction,
    parity, dependency policy, and release custody.
12. Return RED findings to their owning partition. Root does not patch product source.

## Plan gate

```sh
shepherd plan verify --run v656
```

The critic rejects the plan if #368 is not the sole Wave 0 work, provider registration is
guessed, root/planter become spawnable, shell safety uses token parsing, `dep:toml` gains config
ownership, generated carriers are committed, production writes lack confirmation, or any
partition lacks a negative control, deterministic test, periodic eval, gate, or outcome.
