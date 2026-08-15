# v6.4.5 migration and lock proof lane

Status: GREEN for the owned proof corpus. No source, runner, authority manifest, checksum, live state, or existing case was changed.

## Scope

This lane added four native-v6.4.5 cases:

- `conformance/cases/core/migrate/top-level-dry-run`: a top-level project `migrate --dry-run` against a nested `docs/specs` fixture. The captured manifest plans the flattening, while the captured filesystem proves `docs/specs/legacy.md` remains and `docs/legacy.md` is absent.
- `conformance/cases/core/lock/acquire`: a named `parallel` lock acquisition against a seeded canonical registry project. The real native command must create the lock and write its audit row for the success result.
- `conformance/cases/core/lock/release`: the setup step acquires a real native lock, then the captured release removes it. The captured `shepherd.lock` is `<MISSING>` after release.
- `conformance/cases/core/lock/reap`: a valid lock file with a dead PID is provided as an input fixture. The real native PID probe reaps it, and the captured `shepherd.lock` is `<MISSING>` afterward.

The reap fixture uses `i64::MIN` for `acquired_at` so the native saturating age arithmetic produces a byte-stable age bucket. This preserves the actual dead-PID branch and removal behavior without making a golden output expire as wall-clock time advances. The existing native unit test remains the proof for the live recent-holder refusal branch.

## Evidence

The current debug binary was rebuilt before recording:

```text
cargo build --locked -p shepherd-cli --bin shepherd
Finished `dev` profile
```

Owned migration replay:

```text
python3 conformance/runner.py --cases-dir conformance/cases/core/migrate --impl rust --rust-bin target/debug/shepherd
PASS  top-level-dry-run
conformance: 1/1 passed (suite=ALL)
```

Owned plus existing lock replay:

```text
python3 conformance/runner.py --cases-dir conformance/cases/core/lock --impl rust --rust-bin target/debug/shepherd
PASS  acquire
PASS  invalid-mode
PASS  json-free
PASS  reap
PASS  release
PASS  show-free
conformance: 6/6 passed (suite=ALL)
```

The migration case was replayed once after recording. The reap case was replayed twice, with a delay between replays, to verify its output remains deterministic. Both replays passed.

No route was promoted in the authority manifest and no `conformance/CHECKSUM` update was made, per lane scope.
