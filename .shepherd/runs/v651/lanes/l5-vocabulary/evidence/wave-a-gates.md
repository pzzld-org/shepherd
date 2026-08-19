# l5-vocabulary — wave A gate evidence (successor conductor)

worktree: .worktrees/v651-l5-vocabulary   base: b0ad8aa99abf1490e27ee8880dba9fe405ae165c
binary:   target/debug/shepherd, `cargo build --locked -p shepherd-cli --bin shepherd` (exit 0)
pre-fix:  scratchpad/shepherd-prefix-b0ad8aa, built at base, retained for falsification

## GATE-EXECUTION — every count quoted, every count > 0

```
$ cargo test -p shepherd-cli --test wave_a_models_cli --locked
test result: ok. 11 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.91s

$ cargo test -p shepherd-cli --test wave_b2_seed_cli --locked
test result: ok. 14 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.37s

$ cargo test -p shepherd-cli --locked
214 passed / 0 failed   (fork-point baseline 203, delta +11)

$ cargo test --workspace --locked            # exit 0
428 passed / 0 failed over 53 `test result:` lines   (baseline 417, delta +11)

$ cargo test -p shepherd-core --features full --locked
131 passed / 0 failed  (5+4+15+69+25+7+6+0 — run explicitly because
                        `cargo test -p <crate>` skips required-features targets
                        and still prints `ok`)

$ bash hooks/tests/run.sh                    # exit 1
FAIL: hooks/tests/run.sh (29/29 tests ran, 1 failed)
  -> test_workflow_meta_gate.sh, owned by lane l6-gate-wiring. Identical to the
     fork-point baseline; untouched by this lane.
```

The +11 workspace delta is exactly this lane's new tests: 3 unit tests in
`wave_a_models.rs`, 2 in `wave_a_models_cli.rs`, 6 in `wave_b2_seed_cli.rs`.

## D10 (#324) — before / after

```
$ [pre-fix]  shepherd models resolve shepherd --harness claude
ERROR: unknown role: shepherd (valid: root planter engineer conductor critic discovery coder auditor worker)
exit=2
$ [fixed]    shepherd models resolve shepherd --harness claude
opus[1m]
exit=0
$ [fixed]    shepherd models resolve root --harness claude
opus[1m]
exit=0
$ [fixed]    shepherd models resolve nonsense --harness claude
ERROR: unknown role: nonsense (valid: root planter engineer conductor critic discovery coder auditor worker; alias: shepherd -> root)
exit=2
```

`ROLES` stays 9 entries; the alias is input-only and `models show` grows no
`shepherd` row in any of text / `--md` / `--json` / `--harness` renderings.

## D11 (#319) — the whole seed corpus, both binaries

| seed | pre-fix | fixed |
|---|---|---|
| v645 | exit 1, 2 HARD, 1 warn | exit 1, 2 HARD, 1 warn — **byte-identical** |
| v646 | exit 1, 2 HARD, 0 warn | exit 0, 0 HARD, 2 warn |
| v651 | exit 0, 0 HARD, 1 warn | exit 0, 0 HARD, 1 warn — **byte-identical** |

v645 is the load-bearing row: it is just as historical as v646, but no
`close.md` exists beside it, so it keeps both HARD failures. "Historical" is
not a bypass; "closed" is a fact on disk.

## Falsification — sandbox.sh, all three configurations

```
$ bash sandbox.sh --mode expect-abort <pre-fix binary>
OK: mode=expect-abort — 28 assertion(s) held, 0 failed.          exit=0

$ bash sandbox.sh --mode expect-fixed <fixed binary>
OK: mode=expect-fixed — 29 assertion(s) held, 0 failed.          exit=0

$ bash sandbox.sh --mode expect-abort <fixed binary>             # the falsification
FAIL: mode=expect-abort — 10 assertion(s) failed, 18 held.       exit=1
```

The 18 that still hold in the third run are precisely the mode-independent
negative controls. The 10 that fail are precisely the defect reproductions.
The harness also refuses a zero-assertion run rather than reporting OK.

## The safety hardening, and its negative control

`hooks/scripts/seed_preflight_check.sh:59-64` runs the live SEED-GATE against a
bare `mktemp -t shep-seed.XXXXXX` file in `$TMPDIR`. A sibling-`close.md` test
alone would let any stray `close.md` in `$TMPDIR` silently downgrade that gate
for every seed a planter writes. The `runs/<id>/seed.md` path-shape half is
what prevents it, and it survives in `is_run_scoped_seed_path`
(`crates/cli/src/cmd/wave_b2_seed.rs`).

Mutation proof, run in a scratch copy outside the repository — forcing the
predicate to `true` (dropping the path-shape half, leaving only the close.md
test):

```
test close_md_beside_a_non_run_shaped_seed_path_does_not_relax_anything ... FAILED
  left: Some(0)   right: Some(1)
test result: FAILED. 13 passed; 1 failed
```

Exactly one test goes red, and it is the negative control for exactly this
half. `sandbox.sh` NC1 and NC2 assert the same property from the shell, NC2 by
driving `TMPDIR=<scratch> mktemp -t shep-seed.XXXXXX` literally with a hostile
`close.md` planted beside it.

## Adversarial path-shape sweep (fixed binary, scratch dir)

| input | verdict |
|---|---|
| `runs/<id>/seed.md` + `close.md` | warn (relaxed) — intended |
| `runs/<id>/./seed.md` | warn — `.` is normalized out of `Components`; same file |
| `runs/<id>/../<id>/seed.md` | HARD — `..` is never normalized (symlink safety) |
| absolute `/…/runs/<id>/seed.md` | warn — intended |
| `runs/<id>/SEED.MD` | HARD — byte-compare, fail-closed on case-insensitive APFS |
| `RUNS/<id>/seed.md` | HARD — fail-closed |
| `close.md` is a directory | HARD — `is_file()`, fail-closed |
| `runs/<id>/sub/seed.md` | HARD — grandparent is `<id>`, not `runs` |
| `close.md` is a symlink to a file | warn — `is_file()` follows the link |
| `runs/<id>/seed.md`, no `close.md` | HARD — both halves required |

Every deviation fails closed (stays HARD). No input was found that wins a
relaxation it should not. The rule fires for any `*/runs/*/seed.md`, not only
`.shepherd/runs/`, which matches the path pattern
`seed_preflight_check.sh:42-46` already gates its own input on; the hook's temp
copy is immune under EITHER half alone, because it is neither named `seed.md`
nor inside a `runs/<id>/` directory.
