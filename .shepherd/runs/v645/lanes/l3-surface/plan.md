# Lane l3-surface: native CLI and rendering surface

**Run:** v645
**Canonical plan:** `.shepherd/runs/v645/plan.md`
**Owned surface:** `crates/cli/**`, `crates/render/**`

## Objective

Expose the Rust engine, registry, compiler, and renderer through the single
native `shepherd` CLI. Preserve the frozen behavior that remains supported,
make retired behavior explicitly unsupported, and keep all filesystem writes
behind the descriptor-safe native boundaries.

## Steps

- [x] W2-S1: establish MiniJinja environment parity in `crates/render`.
- [x] W2-S2: emit reproducible render manifests and content digests.
- [x] W2-S3..S16: port the mechanically portable command groups to clap.
- [x] W3-S1..S29: disposition and port the parity-hostile command groups.
- [x] W3-S30: implement the confirmed layout-v5 migration command.
- [x] Publish only one Rust binary and retire the Python/Bash CLI surfaces.

The detailed actions, acceptance predicates, and dependencies remain in
`plan.md` sections “Wave 2”, “Wave 3”, and “Lane projection”. This lane file is
the stable run-scoped index required by `run.json`; it does not duplicate those
long-form specifications.

## Acceptance

- `cargo test --locked -p shepherd-cli` passes.
- `cargo test --locked -p shepherd-render` passes.
- `cargo clippy --locked -p shepherd-cli -p shepherd-render --all-targets -- -D warnings` passes.
- `python3 scripts/check-cli-authority.py` reports every legacy route as native
  or explicitly retired.
- `bash scripts/tests/test_shepherd_native_launcher.sh` proves `bin/shepherd`
  delegates only to the native binary.
- `scripts/gate.sh full` passes before release.

## Non-goals

- No second adapter CLI or JavaScript/Python policy implementation.
- No branch-keyed state or artifacts outside `.shepherd/runs/v645`.
- No reintroduction of retired nested docs, plan, report, or log roots.
