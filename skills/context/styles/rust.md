# Rust — project code style

Project-local at `.shepherd/styles/rust.md` (or legacy `.artifacts/styles/rust.md`). The conductor injects this as a `[CODE-STYLE]` block into every coder brief whose `[FILE-SCOPE]` includes Rust files. Edit freely — lives next to the project, not the user. Project-specific deviations go below the marker at the bottom.

## Toolchain & edition

- Edition 2024 for every new crate.
- MSRV 1.94.0 is the floor; a project may pin lower via its own `rust-version` (e.g. `1.91.0-msrv` for legacy paths). Silent = 1.94 applies.
- `cargo fmt --all` and `cargo clippy --workspace --features full -- -D warnings` MUST pass before every commit. A wrong clippy lint gets `#[allow(clippy::lint_name)]` + a comment inline, never a global silence.

## Workspace structure

- `workspace.package.version` is the single source of truth; leaf crates use `version.workspace = true`, never a hard-coded version.
- `workspace.dependencies` is the single source of truth for dep versions; leaf crates use `dep = { workspace = true, features = […] }`. New deps go into the workspace `Cargo.toml` first.
- `resolver = "2"` at the workspace root, always.
- One concept per workspace member — a crate holding `types/`, `traits/`, AND `impls/` is a split candidate (module convention below).

## Module convention

Most-corrected rule in this codebase.

**Inline modules** exist ONLY for two purposes: umbrella protection of the reserved names `impls`/`traits`/`types`/`utils` (they leak through umbrella re-exports if they live as `<name>/mod.rs`), and crate-internal `prelude` modules.

```rust
// Inline — umbrella protection
mod impls { pub mod impl_something; }
mod types { #[doc(inline)] pub use self::some_type::*; mod some_type; }
mod utils { #[doc(inline)] pub use self::some_util::*; mod some_util; }

// Inline — prelude
#[doc(hidden)]
#[allow(unused_imports)]
pub(crate) mod prelude {
    pub use super::{traits::*, types::*, utils::*};
}
```

**Named-file pattern** (`<name>.rs` + `<name>/` dir) is the DEFAULT for substantive modules — a file body plus inner sub-modules:

```
gateway/
├── handlers.rs       (module root with substantive content)
├── handlers/         (children declared inside handlers.rs)
│   └── health.rs
├── middleware.rs
└── middleware/
    └── auth.rs
```

**Hard rules:**
1. NEVER create `{traits, types, utils, impls}/mod.rs` files — the stopping-point rule. Use inline modules at the parent `mod.rs` instead.
2. `types/*.rs` = one type per file; no `impl` pull-out unless the file holds a cluster of related types.
3. `impls/impl_<name>.rs` = impl blocks pulled out only when inlining would bloat the definition file.
4. `utils/` is hidden — never a public path; re-exports act as if the functions were written in the parent.
5. `pub mod foo;` for public, `mod foo;` for private; consumers reach internals only via `#[doc(inline)] pub use self::foo::*;`.

Check existing layout conforms before touching a `mod.rs` or adding a module; flag violations first.

## Dependencies

- `hashbrown::HashMap`/`HashSet` over `std::collections` equivalents, always when available (`no_std` boundaries stay legal on std).
- `thiserror` for libraries, `anyhow` for binaries — never mixed, never `Box<dyn Error>` at library boundaries.
- `tokio` is the default async runtime, `default-features = false` + opt-in features. `serde` with `default-features = false` + `["derive"]`.
- `tracing` over `log` for new code (old `log` stays until touched); `chrono` acceptable, `time` preferred for new code.

## Feature gating

```toml
[features]
default = ["std"]
std = ["alloc"]
alloc = []

# Dependencies get THEIR OWN named features, never gated behind alloc/std
hashbrown = ["dep:hashbrown"]
serde = ["dep:serde"]

# Transitive forwarding when re-exporting
foo = ["dep:foo", "<core-crate>/foo"]
```

- Features are additive only — a feature-A-XOR-feature-B design MUST be refactored. Every new dependency gets its own named feature.
- Umbrella-core forwarding: if the project has an umbrella/core crate (e.g. `<project>-core`), every leaf crate except `traits`/`types`/`math`/`macros` forwards `<core>/<feature>` for every feature it carries.

## Imports & re-exports

```rust
#[doc(inline)]
pub use self::{iter::SomethingIter, something::*, traits::*, types::*, utils::*};
pub mod iter;
mod something;
```

- `#[doc(inline)]` on re-exports so docs render at the re-export path.
- Group re-exports by source module with `pub use self::{ … }`.
- Never `pub use` external crate symbols at the crate root unless intentionally re-exporting.

## Naming idioms

- Types `PascalCase`, no `I`/`T` prefixes (`Feed`, not `IFeed`); traits `PascalCase`, verb-or-capability (`Compute`, `Forward`, `Actor`).
- Modules/files `snake_case` (`btc_5m.rs`); constants `SCREAMING_SNAKE_CASE` with units in the name (`ORACLE_STALE_SECONDS`).
- Generic params: single uppercase (`T`, `U`) for general roles, descriptive (`Ctx`, `Sig`) for specific roles. Never `T1, T2`.

## Service / lifecycle pattern

`<Service>::start(...) -> Result<…>` (or `::serve` for anything blocking-until-shutdown), e.g. `impl Gateway { pub async fn serve(self, addr: SocketAddr) -> anyhow::Result<()> }`. Keep this contract stable across extractions — it's the API surface future re-extractions and re-folds depend on.

## Wrapper discipline — every struct earns its existence

A struct MUST justify itself by carrying one of:
1. A type-system-enforced invariant — `NonEmptyVec<T>`, `Permille(u16)`, `Validated<T>`.
2. A lifetime borrow composing references to live state — `Step<'a> { bot: &'a Bot, signal: &'a Signal }`.
3. An owned heap alloc that's the unit of sharing — `#[repr(transparent)] struct Outer { inner: Arc<Inner> }` + `Deref` + cheap `Clone`.
4. A substantive trait-receiver role — associated types, generic parameters, genuine implementor identity.

A struct holding a single owned-clone of a params shape that exists only to host an `evaluate()` method is a hollow wrapper. Replace with methods on the params type, free functions in a `gates/`/`compute/` module, or a lifetime-composing step (`XStep<'a> { bot: &'a XBot, signal: &'a XSignal }`) when the operation borrows live runtime state.

**Smell-test grep** (the auditor runs this at every sprint close):
```sh
rg -n 'pub struct \w+ \{[\s\n]*pub params: \w+,?\s*\}' --type rust
```
Any hit is a hollow wrapper.

## Tests

- Unit tests in-module, `#[cfg(test)] mod tests { use super::*; … }` at the bottom of the file. Integration tests in `tests/` at the crate root — public API only.
- Compile-time assertions for type-system-enforceable invariants (`static_assertions::assert_impl_all!(MyType: Send + Sync)`). Doc tests for every non-trivial public function, hidden setup with `#` prefix.
- No `unwrap()` in tests outside the assertion itself — `expect("reason")` or `?` with `Result<(), Box<dyn Error>>` signatures.

## What never to do

- No dead code, no commented-out code blocks — delete unused functions/types/imports; `git log` is the archive.
- No `pub` beyond need — default `pub(crate)`, widen only for an actual downstream consumer.
- No `#[allow(dead_code)]` without a comment naming why the code exists and when it gets deleted.
- No silent error swallowing — a `let _ = …` discarding a `Result` needs a comment explaining why the failure is OK.
- No `.clone()` to dodge a borrow error without first asking whether the design wants a different ownership shape.

## Cross-references

When this file disagrees with the universal `code-style:rust.md` skill, name the disagreement and let the operator decide.

<!-- project-specific Rust rules begin here -->
