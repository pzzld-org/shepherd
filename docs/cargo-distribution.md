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

Ordering is **crates first, tag second**, and it is enforced twice: once
structurally, once by an independent check.

**Structurally.** Since the pipeline split, `release.yml` calls
`cargo-publish.yml` through `workflow_call`, and that call declares
`needs: [release-metadata, build]`. Publication therefore cannot begin until
every asset job in `cargo-build.yml` has succeeded, and the tag step in turn
declares `needs: [release-metadata, build, publish-crates]`. The dependency
graph, not a timing assumption, is what orders the three.

This ordering was bought with two burned patch versions. Publication once ran as
its own workflow on the same push event, raced the asset builds, and won: crates
uploaded, a native target failed minutes later, and no tag or release followed. A
crates.io version is not reissuable, so a failed asset build must cost a re-run,
never a version.

**Independently.** `release.yml`'s "Verify crates.io publication precedes the
tag" step still runs immediately before tagging. It queries
`https://crates.io/api/v1/crates/shepherd-cli` and requires the exact release
version to appear in `.versions[].num`, with a bounded retry ceiling. It fails
closed — non-zero exit — on every uncertainty: the version still absent after the
retry ceiling, an HTTP error, a body it cannot parse as JSON, or a request
timeout all end the same way, with the recovery command named in the failure:
`gh workflow run cargo-publish.yml -f version=X.Y.Z -f publish=true`.

That check is now redundant with the dependency graph, and it is kept anyway. It
is the assertion that would still hold if someone re-ordered the jobs.

Publication is idempotent against an already-published version: the publisher
downloads the existing exact crate version on every run and compares its SHA-256
with the prepared `.crate`, so a version already on crates.io resumes safely
instead of erroring.

## Reaching cargo-publish.yml directly

`cargo-publish.yml` is reachable three ways, and `release.yml`'s `workflow_call`
is only the first:

| Trigger | Version comes from | Publishes? |
| --- | --- | --- |
| `workflow_call` (release.yml) | `release-metadata` output | yes |
| `workflow_dispatch` | `inputs.version`, required | only with `publish=true` |
| `repository_dispatch` | `client_payload.version`, or `detect-release-commit.sh` when the payload omits it | yes |

There is deliberately **no `push` trigger.** Publication once had one, on the
same event `release.yml` triggers on, which is precisely how it raced the asset
builds and burned two patch versions. Restoring it would restore the race, since
a push-triggered run has no `needs:` edge to the build. Ordinary releases reach
this workflow through `release.yml`'s call and no other way.

`workflow_dispatch` is the recovery path: a release commit that already merged
and moved on, or a call that failed partway. It defaults `publish` to **false**,
so a recovery run verifies the prepared crate bytes without uploading anything
until the operator asks for it explicitly. Recover with
`gh workflow run cargo-publish.yml -f version=X.Y.Z -f publish=true` and confirm
all six crates are visible on crates.io.

A version supplied by a caller, an operator, or a dispatch payload skips
`detect-release-commit.sh` deliberately — a recovery run may legitimately target
a version whose release commit has already merged and moved on — but it is still
checked against `.claude-plugin/plugin.json` by `version-bump.py check`, and
rejected outright if it is not `MAJOR.MINOR.PATCH`.

`repository_dispatch` payloads are attacker-controlled and that permission is
grantable **without** `contents: write`, so the checkout ref is resolved through
a fail-closed allowlist passed via `env:`, never spliced into a shell command.
