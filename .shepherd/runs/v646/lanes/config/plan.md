# v6.4.6 — lane `config` plan

- **Run:** v646 · **Lane:** `config` · **Branch:** `v6.4.6` · **Base commit at boot:** `58aadf4`
- **Conductor:** persistent lane lead (opus). Coders and auditors are sonnet, one wave at a time.
- **Deliverables:** seed E6 (configuration parsing belongs to `config`, HIGH) and E8 (the model map
  states the intended tiers, MEDIUM). Mesh ROW 0 and ROW 9.
- **Authorship note:** written by the conductor after the first two plan workers returned empty
  (killed by the `native_hook.rs` Write denial, fixed at 20:31). Every file:line below was read
  first-hand at plan time, not carried over from the seed.

---

## 1. The operator's standing rule

Verbatim, and it governs every step in this lane:

> "the next subagent to leverage `dep:toml` over the `dep:config` dependency will experience my
> wrath, the config has plenty of its own parsers built in that would prevent us from needing to
> rewrite and then maintain additional features."

The direction is **one-way: toml -> config**. A coder that moves configuration logic toward `toml`,
or reaches for `toml::` anywhere new "just to bridge", is an automatic REDO. Confirm the current
`config` API through Context7 MCP (`resolve-library-id` then `query-docs`) rather than guessing.

## 2. What stays untouched

| Path | Why it stays |
|---|---|
| `crates/core/src/guard/parser.rs` | Needs `toml::Value::Datetime` (`:548`); `config::Value` has no such variant. Does no layering, precedence, or merging. Parses `content/predicates/*.toml` domain documents with `[[rule]]`/`[[example]]` array-of-tables and an open `extra` map. A document parser, correctly gated behind the `parse` feature. |
| `crates/core/src/guard/engine.rs`, `crates/cli/src/cmd/native_hook.rs` | Changed by the root session this sprint. Not ours. |
| `crates/cli/src/cmd/wave_c_bootstrap.rs` | The third `toml::` call site. Owned by the identity lane. |
| Comment-preserving migration rewrites | A genuine `toml` use. Keep exactly those. Do not break `crates/cli/tests/migrate_layout.rs` or `crates/registry/tests/layout.rs`. |

## 3. Measured baseline (do not re-derive)

| Fact | Evidence |
|---|---|
| `bash scripts/gate.sh` green | `gate (full): green in 37s`, exit 0 → `/tmp/v646-config/gate-baseline.log` |
| Core tests | `cargo test -p shepherd-core --features="std parse json"`. `-p shepherd` FAILS: `cannot specify features for packages outside of workspace`. `shepherd` is shepherd-cli's binary name. |
| Build | `cargo build -p shepherd-cli`. Never set `CARGO_TARGET_DIR`. |
| `models show --md` before | root `inherit-caller`, conductor `standard` → `/tmp/v646-config/models-before.log` |
| `models show --harness` before | `error: unexpected argument '--harness' found` (GATE-CAN-FAIL evidence, already captured) |
| 27 role x harness resolves before | all succeed; no `economy` tier exists yet |
| `config` crate version | 0.15.25, vendored source read directly |

### `config` 0.15.25 API basis (read from the vendored source)

- `Source` (`src/source.rs`): `clone_into_box()` + `collect(&self) -> Result<Map<String, Value>>`.
- `config::File::from_str(s, format)` implements `Source`, so
  `File::from_str(contents, FileFormat::Toml).collect()` yields the parsed map in **one** parse
  with no `toml` crate involved.
- `Value::new(origin: Option<&String>, kind)` (`src/value.rs:206`) stamps a value's origin.
- `ConfigError` (`src/error.rs:43`) carries `At { error, origin, key }` and
  `Type { origin, unexpected, expected, key }` — the dotted key **and** the source origin.
- `FileParse { uri, cause }` Display is `"{cause} in {uri}"`, and `File::from_str` leaves
  `uri: None`.

## 4. Loader blast radius — the containment constraint

Every consumer of the loader API outside this lane:

| Call site | API used |
|---|---|
| `crates/cli/src/migrate.rs:156` | `load_for_layout_v5_migration` (single layer) |
| `crates/cli/src/context.rs:446` | `load_for_layout_v5_migration(layers)` |
| `crates/cli/src/context.rs:448` | `load(layers)` |
| `crates/cli/src/context.rs:364` | `candidates` (unchanged) |

**Constraint:** step 1A must preserve the public signatures of `load`, `load_for_layout_v5_migration`,
`validate`, `layer`, `candidates`, and the `LoadedConfig { config, sources }` shape. If an
out-of-scope file needs editing to make the design compile, the design is wrong. Redo it.

## 5. Why the per-layer decode is the defect, and why `validate()` keeps its own

`load_with_mode` (`loader.rs:142`) calls `parse_layer` (`:203`) for **every** layer. `parse_layer`
does a full `ShepherdConfig` decode plus `validate_config` (`:378`) via `deserialize_toml` (`:364`).
`ShepherdConfig::validate` (`settings.rs:695`) enforces **cross-field** invariants, so a layer that
is legal only in combination with another layer is rejected before the merge ever happens.

Concrete, reproducible case — this becomes the regression test:

```
user layer    (lower priority):  [paths]\nctx  = ".shepherd/docs"
project layer (higher priority): [paths]\ndocs = ".shepherd/documentation"
```

Today the user layer deserializes with `paths.docs` defaulting to `.shepherd/docs`, so the overlap
check at `settings.rs:712-722` fires with `paths.ctx: must not overlap paths.docs` and `load` fails.
After merge, `docs` is `.shepherd/documentation`, nothing overlaps, and the configuration is legal.

`validate(path, contents)` (`:199`) is a **single-candidate** API — per-candidate decoding is its
contract, not the defect. It keeps its decode. Only the merge path loses it.

**This is also why the existing error tests survive.** Every path-qualified assertion in
`crates/core/tests/loader.rs` (`:298`, `:308`, `:327`, `:376`, `:462`, `:476`) goes through the
single-layer entry points `validate()` or `load_for_layout_v5_migration([(path, text)])`. Nothing
pins multi-layer error provenance.

## 6. Waves

Ownership is strictly disjoint **within** a wave. Waves run in order, each gated by an auditor.

### WAVE 1 step 1A — the loader (Objective 1)

**Owns:** `crates/core/src/loader.rs`, `crates/core/Cargo.toml`, `crates/core/tests/loader.rs`.

1. Kill the double parse. `load_with_mode` currently toml-parses each layer (`:204`), re-serializes
   it with `toml::to_string` (`:155`), and hands the string to `config::File::from_str` (`:164`) to
   be parsed a second time. Feed the layer **contents** straight to `config`.
2. Move the `ShepherdConfig` decode, `validate_config`, and `validate_gate_entries` (`:313`) out of
   the merge path so they run **once, post-merge**.
3. Preserve the layout-v5 strip (`strip_retired_layout_v5`, `:215`) as a custom `config::Source`
   that collects the parsed map, removes the retired keys, and stamps each value's origin with the
   layer path. One wrapper solves the single parse, error provenance, and the migration strip
   together. Retired keys are strings and bools only, no datetimes, so `config::Value` covers them.
4. Delete `dep:toml` from the `config` feature in `crates/core/Cargo.toml`. The seed measured
   **16 compile errors** from that deletion today, all inside `loader.rs`. Zero errors afterward is
   the proof the duplication is gone.
5. Do **not** change any `ModelsConfig` default here. That is 2A.

### WAVE 1 step 1B — the tier vocabulary (Objective 2)

**Owns:** `crates/compiler/src/model.rs`, `crates/compiler/tests/compile.rs`.
**Authorized** by the root session; no other lane owns the compiler crate.

Purely additive. Add an `economy` tier to all three profiles:

| Profile | Entry |
|---|---|
| claude (`model.rs:122`) | `model: "haiku"` |
| pi (`model.rs:201`) | `model: "haiku"` |
| codex (`model.rs:155`) | `profile: "economy"` **and** `reasoning_effort: "low"` |

Codex needs **both** or `validate_model_resolution` (`compiler.rs:151-195`) rejects it. Change no
existing hint.

### WAVE 2 step 2A — the models vertical (Objective 2)

**Owns:** `crates/core/src/settings.rs`, `crates/core/tests/loader.rs` (the default assertions at
`:141-144` only), `crates/cli/src/cmd/wave_a_models.rs`, `crates/cli/tests/wave_a_models_cli.rs`,
`content/roles/conductor.md` (the `model_hint` frontmatter line only).

1. `ModelsConfig::root` and `ModelsConfig::conductor` -> `reasoning-high`.
2. `content/roles/conductor.md:5` `model_hint: standard` -> `reasoning-high`.
3. Delete the `fs::read_to_string` + `toml::from_str` re-read at `wave_a_models.rs:279-290`; derive
   `configured_roles` from what `ExecutionContext` already parsed (see §8).
4. Add `--harness <claude|codex|pi>` to `models show`, reusing `translate_for_harness` (`:319`).
   Update `USAGE` (`:33`).

**One step, not three parallel ones.** The models table test spans core defaults, the compiler tier
vocabulary, and CLI rendering. Split three ways, each part is green only after the other two land,
so every split would report a false red. It is one semantically atomic change.

### WAVE 3 — regeneration and drift report

```
python3 scripts/generate-compiler-package-content.py --write
cargo build -p shepherd-cli
./target/debug/shepherd compile --target claude --out "$PWD"
python3 scripts/generate-codex-carrier.py
./target/debug/shepherd compile --target claude --out "$PWD" --check
```

## 7. Locked decision — root is advisory

`content/roles/shepherd.md` **keeps** `model_hint: inherit-caller` even though root's table row
becomes the opus tier.

Mechanism: `shepherd.md` is `dispatchable: false`, and `compiler.rs:367` uses
`model_hint == "inherit-caller"` as the exact predicate that **excludes** root from the codex
`[agent_types]` table. Flipping the frontmatter would silently enroll root as a spawnable codex
agent — a real regression traded for a cosmetic table fix. `MD_FOOTER` (`wave_a_models.rs:35`)
already states root's row is advisory.

"One authority" means the two maps agree on **intent**, with root's compile-time `inherit` a
documented and **tested** exception. Required: a test that fails if root ever appears in the codex
`[agent_types]` table.

## 8. Known limitation — decided, not hidden

Removing the re-read costs exact key-presence provenance. `ShepherdConfig` cannot report **which**
keys a file set, and `crates/cli/src/context.rs` is outside this lane's scope (asked for, not
granted). So `configured_roles` is derived by comparing the merged `ModelsConfig` against
`ModelsConfig::default()`.

**Consequence:** a config that explicitly sets a role to a value equal to the default renders
`source: default` instead of `source: config`. The existing test at
`crates/cli/tests/wave_a_models_cli.rs:102` uses `coder = "native-coder"` and is unaffected.

Required: a test pinning this edge so it is visible. Named follow-up: thread explicit-key
provenance through `LoadedConfig` and `ExecutionContext`.

## 9. Gates — GATE-CAN-FAIL is non-negotiable

For **every** test added or changed, record: the exact command, the failing output **before** the
fix (or with the fix reverted / the assertion inverted), and the passing output after. A gate never
seen red does not count as a gate. Nine inert gates were measured in one prior sprint of this
project — all green, all inert.

| # | Gate | How it fails today |
|---|---|---|
| G1 | Deleting `dep:toml` from the `config` feature leaves the crate compiling | 16 compile errors, all in `loader.rs` |
| G2 | A config legal only after merge loads successfully | `paths.ctx`/`paths.docs` case in §5 fails with `must not overlap` |
| G3 | `models show --harness <h> --md` renders the table for all three harnesses | `error: unexpected argument '--harness' found` (captured) |
| G4 | All 9 roles x 3 harnesses resolve without error | fails once `economy` is a value absent from a profile |
| G5 | Root never appears in the codex `[agent_types]` table | invert by setting `shepherd.md` to `reasoning-high` |
| G6 | `bash scripts/gate.sh` stays green | baseline recorded above |

## 10. Acceptance

- **Objective 1:** the double-parse is gone, per-layer validation moved post-merge, and the existing
  loader and migration tests pass **unchanged**.
- **Objective 2:** `shepherd models show --md` renders the operator's table exactly, for all three
  harnesses.
- **Tier intent:** root, planter, engineer, conductor = opus; coder, worker, auditor, critic =
  sonnet; discovery = sonnet or haiku. The axis is persistence and authority, not cost.
- Per seed E8 "add the tier, set the two values", the two values are **root** and **conductor**.
  `discovery` stays `standard`; `economy` is added so a project can opt discovery down via
  `[models]`. "Sonnet or haiku" is a permission, not a default.

## 11. Out of scope — report, do not reconcile

`conformance/content-target-final.json` and the digest asserted in
`crates/component/tests/component.rs` **will** move when conductor's hint changes
(`agents/conductor.md` goes `model: sonnet` -> `model: opus[1m]`). Record exact diffs; the root
session regenerates both from the compiler.

**Do not touch:** `crates/core/src/guard/**`, `crates/cli/src/cmd/wave_c_bootstrap.rs`,
`native_hook.rs`, `dispatch.rs`, `wave_b2_run.rs`, `crates/component/**`, `hooks/**`, `scripts/**`,
`.github/**`, `packages/**`, `conformance/**`.

`content/roles/*.md` is **shared** with the harness lane: `model_hint` frontmatter edits only, never
tools or capability lines.

## 12. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | `File::from_str` leaves `uri: None`, so post-merge errors lose the file name that `:376`/`:462`/`:476` assert | the custom `Source` stamps origin with the layer path |
| R2 | `ConfigError::FileParse` Display is `"{cause} in {uri}"` and the TOML cause may echo source text, breaking `malformed_toml_names_the_candidate_without_echoing_other_inputs` (`:473`), which requires the message **not** contain `never-echo-this` | build the message from `uri` plus a sanitized cause, never the raw Display |
| R3 | `deny_unknown_fields` interacting with post-merge-only validation | G2 plus the unchanged existing tests |
| R4 | The harness lane regenerates the same `agents/` tree and clobbers Wave 3 | coordinate through the root session; never re-run blindly |
| R5 | Shared worktree — other lanes are editing `crates/core/src/dispatch/portable.rs` concurrently | audits scope their diff to this lane's files only |

## 13. Constraints

Rust-native only; no new Python. Rust tests inline in `#[cfg(test)] mod tests` or under
`crates/*/tests/` — **never** a `tests.rs` inside `src/`. No installers, no publish, no `git commit`,
no `git push`. The root session commits.

## 14. Correction for the next sprint

Seed E8 locates the portable tier vocabulary at `crates/core/src/settings.rs:557-570`. That range is
only `impl Default for ModelsConfig` — nine plain `String` fields. The actual vocabulary is
`HarnessProfile::model_by_hint` in `crates/compiler/src/model.rs` (claude `:122`, codex `:155`,
pi `:201`), fail-closed at `wave_a_models.rs:324` and `compiler.rs:78-88`.

---

## 15. Appendix — the loader design, resolved

Added by the conductor after reading the vendored `config` 0.15.25 source. This is not a sketch;
it is the design step 1A implements. It removes `toml` from `loader.rs` entirely while keeping
every error assertion in `crates/core/tests/loader.rs` intact.

### The key discovery

`config::Format` is a **public** trait (`config/src/format.rs`, re-exported at `src/lib.rs:56`) and
`FileFormat` implements it (`src/file/format/mod.rs:157`):

```rust
fn parse(&self, uri: Option<&String>, text: &str)
    -> Result<Map<String, Value>, Box<dyn Error + Send + Sync>>;
```

So a layer is parsed with:

```rust
use config::{Format, FileFormat, Map, Value};
let origin = path.display().to_string();
let map: Map<String, Value> = FileFormat::Toml.parse(Some(&origin), contents)?;
```

That single call gives all four properties this step needs:

| Property | Why it holds |
|---|---|
| Exactly one parse | `Format::parse` is the same parser `config` uses internally; nothing re-serializes |
| Origins stamped with the layer path | `config/src/file/format/toml.rs` calls `Value::new(uri, ...)` on every value, recursively through tables and arrays |
| Zero `toml` crate in `loader.rs` | the `toml` dependency lives inside `config`'s own toml feature, not in our code |
| Full control of the error message | the error comes back as a bare `Box<dyn Error>`, NOT wrapped in `ConfigError::FileParse`, so its `"{cause} in {uri}"` Display never applies |

`File::from_str` is the wrong tool here precisely because it hardcodes `uri: None`
(`src/file/mod.rs:146`), which is what would have lost the file name that `:376`, `:462`, and
`:476` assert.

### Shape

1. `parse_layer(path, contents, mode) -> Result<Map<String, Value>>`
   - `FileFormat::Toml.parse(Some(&origin), contents)`, mapping the error to
     `Error::config(format!("{}: {}", path.display(), first_line(&cause)))`.
   - **`first_line` is what satisfies R2.** `toml`'s Display renders as
     `"TOML parse error at line 1, column 9"` followed by a snippet block. Taking only the text up
     to the first `\n` keeps `shepherd.local.toml` in the message and keeps `never-echo-this` out of
     it, which is exactly what `malformed_toml_names_the_candidate_without_echoing_other_inputs`
     (`:473`) requires. Do not use the full Display.
   - In `LoadMode::LayoutV5Migration`, run the retired-key strip over the `Map<String, Value>`.
2. `strip_retired_layout_v5` ports from `toml::Value` to `config::Value`. `ValueKind`
   (`src/value.rs:16`) is public with `Nil`, `Boolean`, `I64`, `I128`, `U64`, `U128`, `Float`,
   `String`, `Table(Map<String, Value>)`, `Array(Vec<Value>)`. The retired keys are strings and
   bools only, so `is_str` becomes `matches!(v.kind, ValueKind::String(_))` and `is_bool` becomes
   `matches!(v.kind, ValueKind::Boolean(_))`. No datetime is involved anywhere in this function.
3. A small `LayerSource` implementing `config::Source` holds the already-parsed
   `Map<String, Value>` and returns a clone from `collect()`. `Source` needs only `clone_into_box`
   and `collect`. The builder then merges layers in reverse order exactly as it does today
   (`loader.rs:154`), preserving both Shepherd's provenance order and the builder's override
   semantics.
4. Decode and validate **once**, post-merge: `merged.try_deserialize()` then `validate_config`
   then `validate_gate_entries`, the last of which ports to walking `config::Value` instead of
   `toml::Value`.
5. `validate(path, contents)` keeps decoding its single candidate: parse, strip nothing, decode,
   `validate_config`, `validate_gate_entries`. Its contract is per-candidate validation and every
   path-qualified error test routes through it.

### Already retired risks

`config` **already** deserializes the full `ShepherdConfig` today — `deserialize_merged`
(`loader.rs:371`) calls `try_deserialize` on the merged `Config`, and the suite is green. That
means `config` is already proven against the whole schema including the `GatesExtra` map-or-array
shape (`crates/core/tests/loader.rs:270`) and every `deny_unknown_fields` struct. This redesign
therefore introduces no new deserialization risk. The only genuinely new surface is error message
shaping and the migration strip, both handled above.
