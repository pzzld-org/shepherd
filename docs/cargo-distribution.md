# Cargo distribution and recovery

The public package order is fixed:

1. `shepherd-core`, then `shepherd-compiler` in wave 1.
2. `shepherd-registry`, then `shepherd-render` after core is visible.
3. `shepherd-sdk` after all four libraries are visible.
4. `shepherd-cli` after the SDK is visible.

The SDK Cargo package is `shepherd-sdk`; its Rust crate and dependency key are
`shepherd`, so downstream source continues to use `shepherd::...`.
`shepherd-component` is not published to crates.io.

## Local preparation

Preparation verifies version authority, the generated compiler projection,
the five Binstall asset expansions, and Cargo's unpacked package builds. It
writes the immutable crate paths and SHA-256 receipts to an external state file.

```sh
VERSION=<exact-version>
STATE="/tmp/shepherd-cargo-release-v${VERSION}/state.json"
python3 scripts/cargo-publish.py prepare --version "$VERSION" --state "$STATE"
python3 scripts/cargo-publish.py status --version "$VERSION" --state "$STATE"
```

`prepare` requires a clean checkout. `--allow-dirty` exists only for local
package-gate development and must not be used for a release.

## Publication and recovery

Publication is the only mutating command and requires explicit confirmation.
Cargo reads its credential from the normal credential store or
`CARGO_REGISTRY_TOKEN`; the script has no token argument and does not persist
or print credentials.

```sh
python3 scripts/cargo-publish.py publish \
  --version "$VERSION" --state "$STATE" --confirm
```

On every run, the publisher downloads an existing exact crate version and
compares its SHA-256 with the prepared `.crate`. Equal bytes resume safely.
Different bytes stop immediately because crates.io releases are immutable.
Absent crates publish one at a time in dependency order, with bounded polling
for exact registry visibility before the next crate starts.

GitHub release publication is a later phase. It must not start until all six
crate receipts are `published`, the complete native/component asset inventory
passes, and the tag target matches the prepared source commit.
