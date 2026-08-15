---
title: v6.4.5 Cargo-Native Distribution Design
createdAt: 2026-08-15
version: v6.4.5
description: Publish the Shepherd CLI through Cargo Binstall and Cargo Install while retaining verified release-archive fallbacks.
---

# Cargo-Native Distribution Design

Status: Approved direction; implementation pending

## Outcome

A clean user machine can install the canonical `shepherd` executable with either:

```sh
cargo binstall shepherd-cli
cargo install shepherd-cli --locked
```

`cargo binstall` consumes the versioned native archives from the matching GitHub release. `cargo install` builds the same CLI from crates.io. The existing checksum-first shell and PowerShell installers remain supported fallbacks, not the primary installation path.

The release is successful only when an external, empty installation root can run `shepherd --version` through both Cargo paths. Building archives, publishing crates, or creating a GitHub release alone is not completion evidence.

## Package Identity

The crates.io name `shepherd` belongs to an unrelated project. Shepherd therefore uses these public identities:

| Concern | Identity |
| --- | --- |
| SDK Cargo package | `shepherd-sdk` |
| SDK Rust crate/import | `shepherd` |
| CLI Cargo package | `shepherd-cli` |
| Installed executable | `shepherd` |
| GitHub release tag | `v{version}` |

Only the SDK package name changes. Dependants alias `package = "shepherd-sdk"` to the existing dependency key `shepherd`, preserving `use shepherd::...` and avoiding runtime or source-level API churn.

The crates.io publication set required for the CLI is:

1. `shepherd-core` and `shepherd-compiler`.
2. `shepherd-registry` and `shepherd-render` after `shepherd-core` is indexed.
3. `shepherd-sdk` after all four libraries are indexed.
4. `shepherd-cli` after `shepherd-sdk` is indexed.

`shepherd-component` continues to ship as the versioned WebAssembly/npm release carrier and is not part of the CLI's crates.io dependency closure. Its manifest must state that publication boundary explicitly rather than relying on Cargo's default.

## Compiler Package Boundary

`shepherd-compiler` currently reads the repository-root `content/` tree from its build script. That path does not exist after Cargo unpacks the crate, so the package cannot verify or publish.

The root `content/` tree remains the only authored authority. A deterministic generator produces a package-local compiler projection containing the exact source bytes and paths required by the build. The projection is generated, never hand-authored, and the gate fails on missing files, extra files, byte drift, path drift, or stale digests. The compiler build reads the package-local projection in both workspace and packaged builds so publication does not depend on a checkout-relative path.

The package gate must unpack and compile the `.crate` artifact. `cargo package --list` is insufficient because it does not prove the packaged build script works.

## Binstall Contract

`shepherd-cli` publishes explicit Cargo Binstall metadata. It does not rely on filename heuristics because the package is `shepherd-cli` while the binary and release archives are named `shepherd`.

The mapping uses immutable versioned assets:

```text
Unix:    shepherd-{version}-{target}.tar.gz
Windows: shepherd-{version}-{target}.zip
Binary:  shepherd{binary-ext} at archive root
```

The metadata selects `tgz` on Unix, `zip` on Windows, and `bin-dir = "{ bin }{ binary-ext }"`. Stable versionless archives remain only for the curl installers' latest-release URLs.

Tests expand the metadata for every supported target and compare it with the release asset inventory. A local HTTP fixture proves Cargo Binstall selects, extracts, and executes the root-level binary without compile or third-party quick-install fallback.

## Publication Transaction

Crates.io releases are immutable and cannot be rolled back. Publication therefore has four phases:

1. **Prepare:** package and verify every crate locally, verify the dependency order, build and inspect every native archive, and run local source-install and Binstall fixtures. No external state changes.
2. **Publish crates:** run the local release command, publish one dependency wave at a time, wait for the exact version to become available through the crates.io index/API, and stop on any mismatch. Re-running downloads an existing version and treats it as complete only when its package checksum matches the locally verified `.crate` artifact.
3. **Publish GitHub release:** create the tag and release only after the exact native assets pass the release inventory and the CLI crate is visible through crates.io.
4. **Evaluate:** after both registries are visible, run clean external `cargo install` and `cargo binstall` smoke tests before the release workflow can report success.

The repository already carries `CARGO_REGISTRY_TOKEN` as a GitHub Actions secret, but the v6.4.5 release cannot depend on GitHub-hosted Actions capacity. The local publication command accepts the token only through Cargo's normal credential store or the operator environment and never prints or persists it. Production publication still requires an explicit operator-confirmed invocation. GitHub's encrypted repository secret cannot be read back for local use.

If a crate wave publishes but a later wave fails, the version is not deleted or overwritten. The rerun verifies the already-published crate and resumes at the first absent package. A failed GitHub publication leaves no public release unless the complete asset set is present.

## Release Workflow Boundary

For v6.4.5, the local release command is the execution authority because the repository's GitHub Actions quota is exhausted. It packages and verifies crates, publishes the dependency waves, verifies the release assets, creates the tag and GitHub release with `gh`, and runs the external Cargo installation evaluation. Each phase is individually resumable and fail-closed.

`.github/workflows/cargo-publish.yml` is still added for future tagged releases, following the proven local Concision contract: protected `crates-io` environment, `CARGO_REGISTRY_TOKEN`, serialized publication, non-cancelling concurrency, manual recovery dispatch, and exact checkout custody. It is not required to finish this sprint. Cargo publication remains separate from version-bump Git operations, and `gitflow.yml` remains responsible only for post-release version and branch administration.

The two current cross-platform release failures are fixed as prerequisites:

- Unix archive creation must pass on the actual GNU tar and macOS tar implementations used by the matrix.
- The Windows PowerShell 5.1 dangling-link regression must construct its fixture successfully before it invokes the installer.

These fixes retain deterministic archive and installer tests. Cargo-native installation does not justify deleting checksum, legal-material, fallback-installer, or asset-bijection gates.

## Verification and Evaluation

Fast deterministic gates:

- Cargo package-name and dependency-alias contract.
- Generated compiler projection equality and falsification test.
- `cargo package` plus unpacked package compilation for every published crate.
- Exact crates.io dependency-order resolver test.
- Cargo Binstall metadata expansion for all five native targets.
- Local cold Binstall fixture with compilation and quick-install fallback disabled.
- Local `cargo install --path crates/cli --locked` smoke test.
- GNU/macOS archive and PowerShell fixture regressions.

Release evaluation:

- From clean temporary Cargo homes, install `shepherd-cli@{version}` through crates.io and through Cargo Binstall.
- Assert the installed executable reports the exact version and runs a read-only command.
- Verify the normal Claude marketplace installation can invoke that executable through `shepherd claude-hook`.

The release cannot report success when either Cargo installation path silently falls back to another strategy or resolves a different version.

## Documentation

Installation documentation is ordered as:

1. `cargo binstall shepherd-cli` for prebuilt native installation.
2. `cargo install shepherd-cli --locked` for a source build.
3. Checksum-first curl or PowerShell installer for environments without Cargo Binstall.
4. Normal Claude marketplace installation after `shepherd` is present on `PATH`.

The future consolidation of these deterministic operations under `cargo xtask` is tracked separately in GitHub issue #301 and does not block the v6.4.5 recovery.
