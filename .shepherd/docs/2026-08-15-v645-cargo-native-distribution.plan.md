---
title: v6.4.5 Cargo-Native Distribution Execution Plan
createdAt: 2026-08-15
version: v6.4.5
description: Publish the canonical Shepherd CLI through crates.io and Cargo Binstall, restore portable release assets, and ship normal Claude and Codex marketplace carriers.
---

# v6.4.5 Cargo-Native Distribution Execution Plan

> **For implementers:** Execute every task test-first. Preserve `content/` as the sole authored carrier, never print registry credentials, and do not publish or mutate GitHub until all local preparation gates are green.

**Goal:** A cold machine can install `shepherd` with `cargo binstall shepherd-cli` or `cargo install shepherd-cli --locked`, and both Claude and Codex can install the repository plugin through their normal marketplace commands.

**Architecture:** Rename only the public SDK Cargo package to `shepherd-sdk` while preserving the Rust crate/import name `shepherd`. Generate a byte-exact package-local compiler content projection. Use one resumable local Cargo publisher for both manual release recovery and future GitHub Actions. Keep Claude and Codex marketplace catalogs as thin carriers that invoke the installed native CLI directly.

**Release order:** local prepare and gates; publish the six crates in dependency waves; verify cold Cargo install; build and verify all sixteen GitHub release assets; publish the tag/release; verify metadata-only Cargo Binstall and both normal marketplace installs; push, review, squash-merge, and verify `origin/main`.

## Task 1: Lock GitHub Actions and restore the fast gate

**Files:** `.github/actions-lock.json`, `.github/workflows/*.yml`, `scripts/check-github-actions.py`, `scripts/tests/test-check-github-actions.py`, `scripts/gate.sh`, `services/eval/evals/*`

1. Add a failing checker test covering mutable tags, unknown actions, tag-comment drift, and a stale SHA.
2. Record every external action as `{repository, tag, sha}` using the upstream tag's exact commit.
3. Replace every workflow `uses:` with the locked 40-character SHA and matching tag comment, including `boundaries.yml`.
4. Run `python3 scripts/tests/test-check-github-actions.py`, `python3 scripts/check-github-actions.py`, and the workflow contract tests.

## Task 2: Make the Cargo package graph publishable

**Files:** `Cargo.toml`, `Cargo.lock`, `crates/sdk/Cargo.toml`, `crates/component/Cargo.toml`, package selectors in scripts/workflows, workspace/version tests, SDK docs

1. Add failing package-identity assertions for `shepherd-sdk`, the `shepherd` dependency alias, the `shepherd` library name, and `shepherd-component publish = false`.
2. Rename the SDK Cargo package to `shepherd-sdk`; keep `[lib] name = "shepherd"`; set the root dependency key to `shepherd = { package = "shepherd-sdk", ... }`.
3. Regenerate `Cargo.lock` with Cargo and update package selectors without changing Rust imports.
4. Run workspace, version-authority, feature-matrix, SDK, component, and CLI tests.

## Task 3: Package the compiler corpus without a checkout

**Files:** `crates/compiler/package-content/content/**`, `crates/compiler/build.rs`, `crates/compiler/src/content.rs`, CLI guard/handoff consumers, `scripts/generate-compiler-package-content.py`, its tests, docs and eval cases

1. Add falsification tests for missing, extra, byte-drifted, path-drifted, symlinked, and special projection entries.
2. Generate the exact 21-file roles/skills/predicates/templates projection from root `content/`.
3. Make the compiler always build from the projection while using root `content/` only as an equality oracle in a source checkout.
4. Expose guard sources and `templates/handoff.md` through the compiler/SDK and remove CLI checkout-relative `include_str!` paths.
5. Prove `cargo package --locked --allow-dirty -p shepherd-compiler` reaches Cargo's verification build and that all published crates compile from unpacked packages.

## Task 4: Add deterministic Cargo Binstall and resumable publication

**Files:** `crates/cli/Cargo.toml`, `scripts/check-cargo-distribution.py`, `scripts/cargo-publish.py`, tests, `.github/workflows/cargo-publish.yml`, release docs and eval cases

1. Add failing metadata-expansion tests for all five targets and the exact versioned release inventory.
2. Add Binstall metadata mapping `shepherd-cli` to root-level `shepherd{binary-ext}` in immutable `shepherd-{version}-{target}` archives.
3. Add a cold local HTTP fixture that forces Cargo Binstall's crate-metadata strategy and forbids compilation/quick-install fallback.
4. Implement prepare/check plus explicit `publish --version 6.4.5 --confirm`; compare existing registry package checksums before resuming, publish in dependency waves, and poll exact registry visibility.
5. Add a future protected `crates-io` workflow that verifies exact SHA custody and invokes the same script with `CARGO_REGISTRY_TOKEN` only through the environment.

## Task 5: Add normal Codex marketplace installation

**Files:** `.agents/plugins/marketplace.json`, `plugins/shepherd/.codex-plugin/plugin.json`, Codex hook manifest, native CLI hook module/tests, plugin/version checkers, docs and plugin-distribution evals

1. Add a failing isolated `HOME`/`CODEX_HOME` test for `codex plugin marketplace add <repo>` and `codex plugin add shepherd@shepherd`.
2. Add the repository marketplace catalog pointing to `./plugins/shepherd` and a regular Codex manifest.
3. Add a native `shepherd codex-hook` bridge sharing guard logic with the Claude bridge; no Python, Node, npm, or Wasm dependency may exist in the installed carrier.
4. Inspect the isolated installed cache and exercise SessionStart plus a fail-closed PreToolUse decision through the installed native binary. Do not register Codex subagent lifecycle hooks until the host exposes trusted spawn-to-child correlation.
5. Extend version and plugin projection checks so Claude and Codex manifests cannot drift.

## Task 6: Fix the two failed native release jobs

**Files:** `scripts/create-release-tar.sh`, `scripts/tests/test-release-tar-portability.sh`, `scripts/tests/test-release-installer-windows.ps1`, release portability evals

1. Reproduce the compact `--owner=0`/`--group=0` macOS tar rejection in the fake-tar boundary.
2. Use the GNU/BSD-compatible separate-argument ownership flags and prove deterministic archive bytes/metadata.
3. Construct the Windows PowerShell 5.1 dangling link by creating the target, linking it, deleting the target, and asserting the intended fixture before installer execution.
4. Run shell/static tests locally and the PowerShell recovery suite where PowerShell is available.

## Task 7: Prepare and verify the release locally

**Files:** release scripts, documentation, generated legal material, evaluation fixtures

1. Run `scripts/gate.sh all`, all deterministic release tests, Cargo deny, package checks, and the content/plugin/Cargo distribution evals.
2. Build all five target archive pairs plus the component/npm assets locally from the exact release commit; verify exact 16 payloads and 16 checksums, legal trees, embedded versions, and reproducibility.
3. Run cold `cargo install --path crates/cli --locked` and local metadata-only Binstall smoke tests before any external publication.
4. Obtain two independent code reviews and fix every P0/P1 finding before continuing.

## Task 8: Publish, integrate, and close

1. Confirm `CARGO_REGISTRY_TOKEN` is present without printing it; publish the six crates with the resumable script and verify exact crates.io checksums.
2. From empty Cargo homes, run `cargo install shepherd-cli --version '=6.4.5' --locked` and assert `shepherd --version` plus a read-only command.
3. Push `codex/v645-cargo-native-distribution`, open a PR, wait for available checks, obtain review, and squash-merge to `main` without force-pushing.
4. Rebuild or verify release assets against the exact squash-merge SHA, create `v6.4.5` and its GitHub release locally, and prove metadata-only `cargo binstall shepherd-cli --version 6.4.5` from an empty cache.
5. Run isolated normal Claude and Codex marketplace add/install tests with the published CLI on `PATH`.
6. Verify `origin/main`, tag, release asset inventory, crates.io package graph, absence of stray remote worktree branches, and native sprint state; close only through Shepherd lifecycle commands after all release evidence is durable.

## Final evidence

The task is DONE only when the exact published version is independently installable through both Cargo commands, both marketplace installs work without hidden runtimes, `origin/main` contains the squash merge, the GitHub tag/release point at that merge, and every deterministic gate/eval is green. No service restart is required; Codex and Claude must restart only to reload newly installed plugin manifests.
