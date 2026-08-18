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

## GitHub release ordering (release.yml)

`release.yml`'s "Verify crates.io publication precedes the tag" step enforces
that ordering mechanically. Immediately before the tag step, it queries
`https://crates.io/api/v1/crates/shepherd-cli` and requires the exact release
version to appear in `.versions[].num`, with a bounded retry ceiling. It fails
closed — non-zero exit — on every uncertainty: the version still absent after
the retry ceiling, an HTTP error, a body it cannot parse as JSON, or a request
timeout all end the same way, with the recovery command named in the failure:
`gh workflow run cargo-publish.yml -f version=X.Y.Z -f publish=true`. With this
gate in place, the enforced ordering is **crates first, tag second**:
`release.yml` will not tag or publish a GitHub release ahead of crates.io.

Publication is automatic and runs ahead of the tag. `cargo-publish.yml`
triggers on `push: branches: [main, master]` (`cargo-publish.yml:3-5`), the
same push event `release.yml` triggers on, and gates its work on the same
predicate: `scripts/detect-release-commit.sh` run against the pushed
commit's subject and `.claude-plugin/plugin.json`. When that predicate calls
the commit a genuine release, `cargo-publish.yml` runs `cargo-publish.py
prepare` and then `cargo-publish.py publish --confirm` unattended, with no
operator step and no `workflow_dispatch` call. Publication is idempotent
against an already-published version: as described above, the publisher
downloads the existing exact crate version on every run and compares its
SHA-256 with the prepared `.crate`, so a version already on crates.io resumes
safely instead of erroring.

The two workflows are independent Actions runs triggered by the same push,
not chained with `needs:`, so nothing here structurally forces
`cargo-publish.yml` to finish before `release.yml` reaches its tag step. The
crates.io gate above is what makes "crates first, tag second" real rather
than accidental: `release.yml` polls crates.io itself and refuses to cut the
tag until it observes the exact version published, regardless of how the two
runs interleave. This is also why the pipeline no longer depends on the tag
push to start `cargo-publish.yml`: a `GITHUB_TOKEN`-authored tag push cannot
fire another workflow, and moving the trigger to the release commit's push
to `main`/`master` removed that dependency entirely.

`workflow_dispatch` on `cargo-publish.yml` is a recovery path only, for a
release commit that already merged and moved on, or a push-triggered run
that failed partway. In that mode, version resolution takes `inputs.version`
directly instead of deriving it from `detect-release-commit.sh`. Recover
with `gh workflow run cargo-publish.yml -f version=X.Y.Z -f publish=true`
and confirm all six crates are visible on crates.io before the release
commit's `release.yml` run reaches its crates.io gate.
