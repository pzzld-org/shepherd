# shepherd

The umbrella SDK. Every consumer links this crate; nothing links a member crate directly.

```toml
[dependencies]
shepherd = { package = "shepherd-sdk", version = "6.5.4", features = ["json", "registry"] }
```

## Why an umbrella

Shepherd has been rewritten once, Python to Rust, and the reason was reach: the old implementation could not be embedded in a host that needed it without the CLI wrapped around it. The member split is the insurance against a third rewrite. This crate is what makes the split usable — one name, one version, one feature vocabulary, no matter how many members sit behind it.

That indirection is load-bearing. Splitting a new layer out of `shepherd-core` is an internal refactor, because no consumer was ever naming the member it depended on.

## Capabilities, not crates

Members are addressed by what they do, never by their crate name.

| Feature | Adds | Cost |
|---|---|---|
| *(none)* | the engine: domain types, run state, config schema | `thiserror`, `strum` |
| `config` | the configuration precedence chain and standard source merge | `config`, `toml`, `serde` |
| `json` | the canonical artifact codec | `serde`, `serde_json` |
| `parse` | the run-id and branch grammars | `nom` |
| `schema` | the config key universe | `schemars` |
| `registry` | the SQLite registry and migration runner | `rusqlite` |
| `render` | deterministic templating and provenance | `minijinja`, `sha2` |
| `chrono`, `uuid`, `tracing` | the named dependency, nothing more | itself |
| `full` | everything above; `native` is its alias | all of it |

Capability flags fan out **weakly** (`shepherd-registry?/json`). Asking for `json` configures the registry only if you already asked for `registry`; enabling a capability never conjures a member you did not request. A non-weak edge here would make every consumer link SQLite, which is the failure this table exists to prevent.

## Targets

`wasm` and `wasi` are not aliases of each other. `rusqlite` 0.40 selects its SQLite backend by target cfg rather than by feature, so the two need different wiring:

| Target | Backend | Flags |
|---|---|---|
| `wasm32-unknown-unknown` | `sqlite-wasm-rs` | `wasm` — `bundled` must stay **off** |
| `wasm32-wasip1` | `libsqlite3-sys` + VFS shim | `wasi` — `bundled` is **required** |
| native | `libsqlite3-sys`, bundled C | `bundled` (on by default in the CLI) |

Both wasm paths need a clang with a WebAssembly backend. Apple's system clang has none; use Homebrew's LLVM.

## Adding a member

Four mechanical steps, in this order:

1. Create `crates/<name>/` with `shepherd-core` as its only mandatory dependency.
2. Add it to `[workspace.dependencies]` in the root manifest with `default-features = false`.
3. Add it here as `optional = true`, plus a `dep:`-style capability flag and weak (`?/`) edges from `json`, `std`, `alloc`, `tracing` and both target flags.
4. Re-export it from `lib.rs` behind `#[cfg(feature = "...")]`, and add a case to `tests/default.rs`.

Do **not** glob the new member's prelude into `shepherd::prelude`. Every member defines its own `Error` and `Result`, so a second glob makes `prelude::*` ambiguous (E0659) the moment a consumer enables two capabilities. Member preludes stay addressable at `shepherd::<member>::prelude`.

Then run:

```bash
scripts/check-features.sh --targets
```

A feature flag rots silently — `cargo check --workspace` builds exactly one combination, so a flag that resolves to a dependency-not-found error keeps passing indefinitely because nothing references it. That script is what makes the flag surface falsifiable, and CI runs it on every push.

## The boundary still holds

This crate adds no dependency of its own; it is re-exports and a feature graph. `shepherd-core` remains free of `clap`, `anyhow`, a log sink, an I/O backend, and `std::process`, and the `engine-boundary` CI job proves it on every push.
