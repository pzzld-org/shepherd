# Wave 1 step 1B — economy tier — CONDUCTOR-VERIFIED PASS

Verified by the conductor against ground truth, not accepted from the coder's self-report.

## Scope containment

`crates/compiler/src/model.rs` and `crates/compiler/tests/compile.rs` only. Every other modified
path in the worktree belongs to the distribution lane (`scripts/**`, `.github/workflows/release.yml`,
`bin/shepherd`, `crates/cli/tests/wave_b1_status_handoff_cli.rs`).

## Additive-only proof

`git diff crates/compiler/src/model.rs` contains **zero `-` lines**. The three pre-existing hints
(`inherit-caller`, `reasoning-high`, `standard`) are byte-identical on all three profiles. Only
three `economy` entries were added.

| Profile | Entry | Shape rule (compiler.rs:151-195) |
|---|---|---|
| claude `:145` | `model: Some("haiku")` | model set, profile/effort None — correct |
| codex `:181` | `profile: Some("economy")`, `reasoning_effort: Some("low")` | both set, model None — correct |
| pi `:233` | `model: Some("haiku")` | model set, profile/effort None — correct |

## GATE-CAN-FAIL — proven red by the conductor

The coder's own recording was not taken as sufficient. The gate was re-broken independently:

```
$ cp crates/compiler/src/model.rs /tmp/v646-config/model.rs.bak
$ git checkout -- crates/compiler/src/model.rs      # revert to committed state
$ grep -c "economy" crates/compiler/src/model.rs
0
$ cargo test -p shepherd-compiler economy
failures:
    economy_hint_resolves_and_matches_target_shape_on_all_canonical_profiles
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 6 filtered out
```

Restored, then green:

```
$ cp /tmp/v646-config/model.rs.bak crates/compiler/src/model.rs
$ cargo test -p shepherd-compiler
test result: ok. 5 passed  (budget)
test result: ok. 7 passed  (compile, includes the economy test)
test result: ok. 4 passed  (content)
```

## Test quality

`economy_hint_resolves_and_matches_target_shape_on_all_canonical_profiles` iterates
`HarnessProfile::canonical()` and asserts the per-target shape rule for each of claude, codex, and
pi, rather than asserting only that resolution succeeds. It would catch a codex entry missing
`reasoning_effort`, which is the specific way this change fails.

## Verdict

**PASS.** No REDO. Wave 1 step 1B is complete and independently verified.
