# Handoff — run v646, lane `config`

## 1. Verdict

Both deliverables are **complete and conductor-verified**: deliverable 6 (configuration parsing
belongs to `config`, HIGH, seed E6) and deliverable 8 (the model map states the intended tiers,
MEDIUM, seed E8). Every gate in this lane was re-broken by the conductor and shown red before
green — none was accepted from a coder's self-report (`wave1-1a.md`, `wave1-1b.md`, `wave2.md`).

**Nothing in this lane is committed.** All 10 files listed below are working-tree modifications
against a shared worktree. The root session commits.

## 2. What landed

```
$ git diff --stat HEAD -- <lane's 10 files>
content/roles/conductor.md            |   2 +-
crates/cli/src/cmd/wave_a_models.rs   |  64 ++---
crates/cli/src/context.rs             |   9 +
crates/cli/tests/wave_a_models_cli.rs | 246 ++++++++++++++++++-
crates/compiler/src/model.rs          |  22 ++
crates/compiler/tests/compile.rs      |  40 ++++
crates/core/Cargo.toml                |   1 -
crates/core/src/loader.rs             | 438 +++++++++++++++++++++++++---------
crates/core/src/settings.rs           |   4 +-
crates/core/tests/loader.rs           |  74 +++++-
10 files changed, 747 insertions(+), 153 deletions(-)
```

| File | +/- | What changed and why |
|---|---|---|
| `crates/core/src/loader.rs` | +438/-? | Loader rewritten to parse each layer once via `config::Format::parse` instead of parsing to `toml::Value` then re-serializing into `config::File::from_str`. Adds `LayerSource` (`impl config::Source`), moves the `ShepherdConfig` decode + validation to run once post-merge, and adds `LoadedConfig::explicit_keys` for exact key provenance. |
| `crates/core/Cargo.toml` | -1 | Removes `dep:toml` from the `config` feature (`config = ["dep:config", "std", "json"]`). `toml` stays under `parse = ["alloc", "dep:nom", "dep:toml"]`, unaffected. |
| `crates/core/tests/loader.rs` | +74 | New gate tests: merge-legality (`a_layer_illegal_alone_but_legal_after_merge_still_loads`) and the explicit-key-provenance regression case. |
| `crates/core/src/settings.rs` | +4/-? | `ModelsConfig::root` and `::conductor` defaults changed to `"reasoning-high"` (was `standard`/lower). |
| `crates/compiler/src/model.rs` | +22, 0 deletions | Adds an `economy` tier entry to all three harness profiles (claude, codex, pi) in `HarnessProfile::model_by_hint`. Purely additive. |
| `crates/compiler/tests/compile.rs` | +40 | New test asserting the `economy` hint resolves to the correct per-target shape on all three canonical profiles. |
| `crates/cli/src/context.rs` | +9 | `ExecutionContext` gains `explicit_keys`, populated from `LoadedConfig::explicit_keys`, so downstream commands can read real provenance instead of re-parsing config files. |
| `crates/cli/src/cmd/wave_a_models.rs` | 64 changed | Deletes the `fs::read_to_string` + `toml::from_str` re-read at the old `:279-290`; `explicit_models` now reads `ExecutionContext::explicit_keys`. Adds `--harness <claude|codex|pi>` to `models show`, reusing `translate_for_harness`. |
| `crates/cli/tests/wave_a_models_cli.rs` | +246 | Tests for the `--harness` table (all three harnesses), the explicit-default-value provenance case, and `codex_agent_types_never_names_root`. |
| `content/roles/conductor.md` | 2 changed lines | Frontmatter only: `model_hint: standard` -> `model_hint: reasoning-high` (verified: line 5 currently reads `model_hint: reasoning-high`). |

## 3. Deliverable 6 — evidence

`toml::` scoreboard, measured directly:

```
$ grep -c "toml::" crates/core/src/loader.rs
0          # was 15
$ grep -c "toml::" crates/cli/src/cmd/wave_a_models.rs
0          # was 2
$ grep -c "toml::" crates/core/src/guard/parser.rs
22         # unchanged, correctly untouched
```

`guard/parser.rs` is correctly untouched: it needs `toml::Value::Datetime` at `parser.rs:548`
(verified — `toml::Value::Datetime(value) => GuardValue::String(value.to_string())`), for which
`config::Value` has no variant, and it does no layering, precedence, or merging. It is a document
parser (`content/predicates/*.toml`) behind the `parse` feature, out of scope by plan §2.

`dep:toml` removed from the `config` feature:

```
config = ["dep:config", "std", "json"]     # crates/core/Cargo.toml:157
parse  = ["alloc", "dep:nom", "dep:toml"]  # crates/core/Cargo.toml:96 — toml stays here, untouched
```

Acceptance met: the double parse is gone (layer contents feed `config::Format::parse` once,
not toml-parsed then re-serialized then config-parsed a second time). Per-layer `ShepherdConfig`
decode and validation moved out of `parse_layer` to run once post-merge. Existing loader and
migration tests pass unchanged: `cargo test -p shepherd-cli --test migrate_layout` = 9 passed;
`cargo test -p shepherd-registry` = 12/4/16/8 passed.

## 4. Deliverable 8 — evidence

`shepherd models show --md` / `--harness <h> --md`, rebuilt binary (`wave2.md`):

| role | portable | claude | codex | pi |
|---|---|---|---|---|
| root | `reasoning-high` | `opus[1m]` | `reasoning-high` | `opus` |
| planter | `reasoning-high` | `opus[1m]` | `reasoning-high` | `opus` |
| engineer | `reasoning-high` | `opus[1m]` | `reasoning-high` | `opus` |
| conductor | `reasoning-high` | `opus[1m]` | `reasoning-high` | `opus` |
| critic | `standard` | `sonnet` | `standard` | `sonnet` |
| discovery | `standard` | `sonnet` | `standard` | `sonnet` |
| coder | `standard` | `sonnet` | `standard` | `sonnet` |
| auditor | `standard` | `sonnet` | `standard` | `sonnet` |
| worker | `standard` | `sonnet` | `standard` | `sonnet` |

`economy` is expressible but **not a default**: `discovery` stays `standard`. With
`[models] discovery = "economy"` set explicitly, it resolves to `haiku` (claude) /
`economy` (codex) / `haiku` (pi), `source: config`. "Sonnet or haiku" in the original seed
language was read as a **permission** (a project may opt discovery down), not a default value —
plan §10 states this explicitly.

## 5. THE FINDING — this rewrite is subtraction, not a rewrite

`config` **already** deserialized the full `ShepherdConfig` before this sprint, via
`deserialize_merged` (old `loader.rs:371`) calling `try_deserialize` on the merged `Config`, with
a green suite. So `config` was already proven against the entire schema, including the
`GatesExtra` map-or-array shape (`crates/core/tests/loader.rs:270`) and every
`deny_unknown_fields` struct. Removing the double parse **deleted duplicated work**; it did not
port the schema to a new library, and it introduced no new deserialization risk. The only
genuinely new surface this sprint touched was error-message shaping (§6 below) and the layout-v5
migration strip, both already covered by existing tests plus the new gates.

## 6. The `config::Format` finding

`config::Format` is a **public** trait (`config/src/format.rs`, re-exported at `src/lib.rs:56`)
and `FileFormat` implements it (`src/file/format/mod.rs:157`). One call —
`FileFormat::Toml.parse(Some(&path_string), contents)` — gives four things at once:

1. Exactly one parse (the same parser `config` uses internally; nothing re-serializes).
2. Origins already stamped with the layer path: `config`'s own `file/format/toml.rs` calls
   `Value::new(uri, ...)` recursively through tables and arrays.
3. Zero `toml` crate in our code (the dependency lives inside `config`'s own toml feature).
4. Full control of the error text: the error returns as a bare `Box<dyn Error>`, NOT wrapped in
   `ConfigError::FileParse`, whose `"{cause} in {uri}"` Display would otherwise apply.

**The trap, recorded explicitly:** `config::File::from_str` hardcodes `uri: None`
(`config/src/file/mod.rs:146`). Using it would have silently dropped the layer filenames that
`crates/core/tests/loader.rs` asserts on at `:376`, `:462`, `:476`. This is the concrete meaning
of the operator's standing rule: "the config has plenty of its own parsers built in."

## 7. Seed correction — must not be re-derived next sprint

Seed E8 locates the portable tier vocabulary at `crates/core/src/settings.rs:557-570`. That range
is only `impl Default for ModelsConfig` — nine plain `String` fields (confirmed: `root` at
`:560`, `conductor` at `:563` both now `"reasoning-high".into()`). The real vocabulary is
`HarnessProfile::model_by_hint` in `crates/compiler/src/model.rs`, built three times (claude,
codex, pi), and fail-closed on both sides: `wave_a_models.rs:324` returns `unknown model hint`
exit 2, and `compiler.rs:78-88` aborts compilation. Adding a tier to `ModelsConfig` without adding
it to `model_by_hint` turns `models resolve` into a hard error.

## 8. Locked decision — root stays `inherit-caller`, now with a test

`content/roles/shepherd.md` keeps `model_hint: inherit-caller` (confirmed unchanged, `:5`) while
`ModelsConfig::root` moved to `reasoning-high`. `compiler.rs:367` uses that exact hint string
(`if role.model_hint == "inherit-caller" { continue; }`) as the predicate excluding root from
the codex `[agent_types]` table, and `shepherd.md:7` is `dispatchable: false`. Falsification
proved the harm concretely: flipping the hint makes the generated codex carrier contain
`shepherd = "worker"` (`wave2.md` RED output, reproduced there verbatim). With role guard rules
now live (commits 7d5492e, 587fcfa) this is an **enforcement change**, not a cosmetic one. Pinned
by `codex_agent_types_never_names_root`, which compiles from the live `content/` tree rather than
a frozen fixture.

## 9. Gates, each shown to fail on purpose

| Gate | How falsified | RED (verbatim) | GREEN |
|---|---|---|---|
| G1 — `dep:toml` removed, crate still compiles | old loader + new `Cargo.toml`, `--no-default-features --features="std json config"` | `error[E0433]: cannot find module or crate 'toml'... loader.rs:276:17` / `could not compile 'shepherd-core' (lib) due to 16 previous errors` — exactly the 16 the seed measured; gate only isolates because `parse` supplies `dep:toml` independently and the command excludes `parse` | `Compiling shepherd-core v6.4.6 / Finished 'dev' profile in 0.32s` |
| G2 — merge-legal config that's illegal alone still loads | old loader, new test, `config` feature ON | `a_layer_illegal_alone_but_legal_after_merge_still_loads ... FAILED: Config("...shepherd.toml: paths.ctx: must not overlap paths.docs")` — 21 passed, 1 failed | 22 passed, 0 failed |
| economy tier | reverted `model.rs` to committed state, `grep -c "economy"` = 0 | `economy_hint_resolves_and_matches_target_shape_on_all_canonical_profiles ... FAILED. 0 passed; 1 failed` | 5/7/4 passed across compiler's budget/compile/content suites |
| `models_show_explicit_default_value_still_reports_source_config` | swapped `explicit_models` to the banned default-comparison approach | `FAILED: an explicitly configured role must report source: config even when its value equals the default` | `ok. 1 passed` |
| `codex_agent_types_never_names_root` | flipped `content/roles/shepherd.md` to `reasoning-high`, ran the prebuilt test binary directly (so `build.rs` couldn't mask the result) | `FAILED: root (role id 'shepherd') must never appear in the codex [agent_types] table: shepherd = "worker"` | passed after restore |

**Method note:** the conductor re-broke every gate independently — reverted the file, ran the
test, confirmed red, restored, confirmed green — rather than accepting any coder's recording of
red/green as sufficient.

## 10. Two gate-discipline findings for the carry-forward

**(a) A gate is not proven by a red test; the test must be shown to RUN, then shown to go red.**
`crates/core/tests/loader.rs:7` is `#![cfg(all(feature = "config", feature = "std"))]`. The
briefed command `cargo test -p shepherd-core --features="std parse json"` ran **0** loader tests
and printed `test result: ok. 0 passed`, which is indistinguishable from success. With `config`
added, **22** run (24 after Wave 2). All of deliverable 6's acceptance was being checked by a
suite that never executed. **Correct command:**
`cargo test -p shepherd-core --features="std parse json config"`.

**(b) Rebuild before any behavioural check while coders are in flight.** The conductor's first
provenance check rendered `source: "default"` for a role explicitly set to its default — the
exact banned behaviour — and nearly triggered a wrong REDO on correct work. The binary was stale;
after `cargo build -p shepherd-cli` it rendered `source: "config"`. A stale artifact attributes a
build state to a coder's work.

**Also note the smaller instance:** counting compile errors with `grep -cE "^error"` returned 0
against a build that had genuinely failed, because cargo prefixes error lines with ANSI colour. A
grep that silently returns zero is indistinguishable from a passing gate. Raw output was
inspected instead.

## 11. What root must do at integration

1. **Regenerate `agents/` and the codex carrier** — the conductor did NOT, per root's ruling
   (plan §18). The only expected role delta is `agents/conductor.md` `model: sonnet` ->
   `model: opus[1m]`; `agents/shepherd.md` must stay `model: inherit` with root still ABSENT from
   the codex `[agent_types]` table.
2. `conformance/content-target-final.json` (both `targets` AND `roles` sections), the
   `crates/component/tests/component.rs` digest, and `crates/cli/tests/content_compiler.rs`
   (which freezes the codex config bytes) are root's to regenerate.
3. The conductor DID run `python3 scripts/generate-compiler-package-content.py --write` under
   root's bounded carve-out, and `--check` reports `ok: compiler package content has 23
   byte-exact sources`.

## 12. Known follow-ups / not done

Nothing was committed or pushed. `cargo fmt --all -- --check` currently lists only
`crates/cli/src/cmd/wave_c_bootstrap.rs` (lines 332, 365, 889, 921) and
`crates/cli/tests/wave_c_bootstrap_cli.rs` (line 388) — verified directly, both the identity
lane's in-flight files, deliberately untouched by this lane, so `scripts/gate.sh` will be red on
fmt until identity clears them.
`crates/cli/tests/wave_g_coordination.rs::teammate_state_status_and_liveness_share_typed_registry_state`
fails; it is not this lane's file (also present in the working tree diff outside this lane's
10-file scope) and was failing independently.

The named follow-up from plan §16 (thread explicit-key provenance through `LoadedConfig` and
`ExecutionContext`) is DONE, not deferred — see §2 and §9 above; the original §8 approximation was
superseded and withdrawn before this lane shipped.
