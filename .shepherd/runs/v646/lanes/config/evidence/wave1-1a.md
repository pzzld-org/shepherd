# Wave 1 step 1A — loader double-parse removal — CONDUCTOR-VERIFIED PASS

Every gate below was re-broken by the conductor. None was accepted from the coder's report.

## Containment

```
$ git status --short -- crates/core/ crates/cli/src/context.rs crates/cli/src/migrate.rs
 M crates/core/Cargo.toml
 M crates/core/src/loader.rs
 M crates/core/tests/loader.rs
```
Exactly the three owned files. `crates/cli/src/context.rs` and `crates/cli/src/migrate.rs` — the
out-of-scope loader consumers named in plan §4 — are untouched, so the public signatures held.

## The operator's rule

```
$ grep -c "toml::" crates/core/src/loader.rs
0
```
Was 15. The `toml` crate is gone from the loader. It remains an optional dependency for
`guard/parser.rs` behind the `parse` feature, which is correct and required.

## Design conformance to plan §15

`loader.rs:21` imports `FileFormat, Format, Map, Source, Value, ValueKind`. `:245` uses
`FileFormat::Toml.parse(...)` through the public `Format` trait, NOT `File::from_str`. `:237`
implements `Source for LayerSource`. `:290` sanitizes the parse error with
`rendered.lines().next()`, which is the R2 mitigation. `:490` does the single post-merge
`try_deserialize::<ShepherdConfig>()`.

## GATE G1 — `dep:toml` removed from the `config` feature

The correct feature set matters: `parse = ["alloc", "dep:nom", "dep:toml"]`, so `parse` supplies
`toml` independently. The gate must isolate `config` from `parse`.

RED (old loader, new Cargo.toml, `--no-default-features --features="std json config"`):
```
error[E0433]: cannot find module or crate `toml` in this scope
   --> crates/core/src/loader.rs:276:17
error: could not compile `shepherd-core` (lib) due to 16 previous errors
```
**Exactly the 16 errors the seed measured.**

GREEN (new loader, same feature set):
```
   Compiling shepherd-core v6.4.6
    Finished `dev` profile in 0.32s
```

## GATE G2 — a config legal only after merge now loads

RED (old loader, old Cargo.toml, new test, `config` feature ON):
```
test a_layer_illegal_alone_but_legal_after_merge_still_loads ... FAILED
a layer illegal alone but legal after merge must still load:
  Config("/home/jo3/.shepherd/shepherd.toml: paths.ctx: must not overlap paths.docs")
test result: FAILED. 21 passed; 1 failed
```
GREEN (new loader): 22 passed, 0 failed.

## Acceptance — existing loader and migration tests pass UNCHANGED

```
$ cargo test -p shepherd-core --features="std parse json config"
5, 4, 15, 66, 22, 7, 6 passed — 8 targets green, 0 failures
$ cargo test -p shepherd-cli --test migrate_layout
test result: ok. 9 passed; 0 failed
$ cargo test -p shepherd-registry
12, 4, 16, 8 passed; 0 failed
$ cargo build -p shepherd-cli
    Finished
```

## FINDING — the loader test suite was inert under the briefed command

`crates/core/tests/loader.rs:7` is `#![cfg(all(feature = "config", feature = "std"))]`. The command
in the lane brief, `cargo test -p shepherd-core --features="std parse json"`, does NOT enable
`config`:

| Command | loader.rs tests run |
|---|---|
| `--features="std parse json"` | **0** |
| `--features="std parse json config"` | **22** |

All 22 loader tests, including this step's new gate, silently did not run under the documented
command. `test result: ok. 0 passed` is indistinguishable from success when skimming. This is the
project's own "gates that cannot fail" class, sitting on this lane's primary acceptance criterion.

**Correct command for any loader work: `cargo test -p shepherd-core --features="std parse json config"`.**

## Conductor method note

An early count of compile errors with `grep -cE "^error"` returned 0 against a build that had in
fact failed, because cargo prefixes error lines with ANSI colour codes. A grep that silently
returns zero is indistinguishable from a passing gate. Raw output was inspected instead.

## Verdict

**PASS.** Both gates proven red then green, containment exact, acceptance met.
