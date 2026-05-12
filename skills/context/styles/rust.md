# Rust — project code style

This file is project-local at `.shepherd/styles/rust.md` (or `.artifacts/styles/rust.md` for legacy projects). The conductor injects its content as a `[CODE-STYLE]` block into every coder brief whose `[FILE-SCOPE]` includes Rust files. Edit freely; lives next to the project, not the user.

The bundled default reflects the operator's cross-project preferences. Project-specific deviations (e.g., a relaxed MSRV for legacy paths, project-internal weaving rules like `<project>-core` forwarding) get appended below the universal sections.

## Toolchain & edition

- **Edition: 2024.** Always. New crates start at 2024 unless there is a hard upstream-compat reason otherwise.
- **MSRV: 1.94.0.** This is the floor. Some projects pin lower (e.g. `1.91.0-msrv` for legacy paths) — defer to the project's `rust-version` field. If silent, MSRV 1.94 is the default.
- **Rustfmt + clippy are non-optional.** `cargo fmt --all` and `cargo clippy --workspace --features full -- -D warnings` must pass before any commit. If clippy flags something stylistic and the lint is wrong, justify it inline with `#[allow(clippy::lint_name)]` and a comment, not by silencing it globally.

**Why:** 2024 + 1.94 unlocks the modern feature set (let-else, async closures, `gen` blocks where applicable) without losing reach. Rustfmt + clippy as a hard gate keeps the codebase visually uniform across many sessions and many agents.

## Workspace structure

- **`workspace.package.version` is the single source of truth.** Leaf crates use `version.workspace = true`, never hard-code their own version.
- **`workspace.dependencies` is the single source of truth for dep versions.** Leaf crates use `dep = { workspace = true, features = […] }`. Adding a new dep means adding it to the workspace `Cargo.toml` first.
- **`resolver = "2"`** at the workspace root. Always.
- **One concept per workspace member.** A crate accumulating `types/`, `traits/`, AND `impls/` directories is a candidate for further split per the module convention below.

**Why:** version drift across a workspace is a class of bug not worth debugging. Centralized versioning makes upgrades one-decision events.

## Module convention

The module convention is the most-bent-and-corrected rule in this codebase. Read it carefully.

### The two patterns

**Inline modules** are reserved for two purposes only:
- **Umbrella protection** for the reserved names `impls`, `traits`, `types`, `utils`. These names get accidentally exposed through umbrella re-exports if they live as `<name>/mod.rs`; inlining at the parent prevents that.
- **Crate-internal `prelude`** modules.

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

**Named-file pattern** (`<name>.rs` + `<name>/` dir, Rust 2018+) is the **default for substantive modules** — modules that have both a file body (docs, re-exports, type aliases) AND inner sub-modules.

```
gateway/
├── handlers.rs       (module root with substantive content)
├── handlers/         (children declared inside handlers.rs)
│   └── health.rs
├── middleware.rs
└── middleware/
    └── auth.rs
```

Inside `handlers.rs`:
```rust
//! HTTP handler chain
pub use self::health::HealthHandler;
pub mod health;
```

### Hard rules

1. **Never create `{traits, types, utils, impls}/mod.rs` files.** This is the stopping-point rule. Use inline modules at the parent `mod.rs` instead.
2. **`types/*.rs` = one type per file.** No `impl` pull-out unless the file holds a cluster of related types.
3. **`impls/impl_<name>.rs` = impl blocks for a named definition file with multiple types.** Pull-out justified only when inlining would bloat the file.
4. **`utils/` is hidden.** Re-exports act as if the free functions were written in the parent. Don't expose `utils` as a public path.
5. **`pub mod foo;` for public paths; `mod foo;` for private** — consumers reach internals only via `#[doc(inline)] pub use self::foo::*;`.

**Why:** the convention exists so that crate **extraction** (lift a `mod.rs` into a new crate) and crate **collapse** (fold a crate back into its parent as a module) are both algorithmic — copy-and-rename, not graph rewrites.

**How to apply:** every time you touch a `mod.rs` or add a module, check first that the existing layout conforms. If it doesn't, flag the violation before building on top of it.

## Dependencies

- **`hashbrown::HashMap` over `std::collections::HashMap`.** Always, when the choice is available. Same for `HashSet`. The std versions stay legal for `no_std` boundaries.
- **`thiserror` for libraries, `anyhow` for binaries.** Don't mix; don't return `Box<dyn Error>` at library boundaries.
- **`tokio` for async runtimes** unless there's a compelling reason otherwise. Pin to `default-features = false` and opt into the features you actually use.
- **`serde` with `default-features = false` + `["derive"]`** — keep the dependency lean.
- **`tracing` over `log`** for new code. Old code on `log` can stay until touched.
- **`chrono` is acceptable; `time` is preferred for new code** when the choice exists.

**Why:** `hashbrown` is faster, has identical API, and unifies the no_std story. The error split keeps semver clean (libs) and ergonomic (bins). The runtime/feature picks are about minimizing compile time and binary size by default.

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

**Hard rules:**
- Features are additive. If you find yourself writing "feature A XOR feature B," refactor.
- Every new dependency gets its own named feature.
- **Umbrella-core forwarding rule.** If the project has an umbrella/core crate (e.g. `<project>-core`), every leaf crate (except `traits`, `types`, `math`, `macros`) depends on it and forwards `<core>/<feature>` for every feature it carries. Project-specific; appears in this file when applicable.

**Why:** additivity is what makes feature combinations debuggable. Per-dep features are what let downstream consumers compose without inheriting your taste.

## Imports & re-exports

```rust
// at module root
#[doc(inline)]
pub use self::{
    iter::SomethingIter,
    something::*,
    traits::*,
    types::*,
    utils::*,
};

pub mod iter;
mod something;
mod impls { pub mod impl_something; }
mod types { #[doc(inline)] pub use self::some_trait::*; mod some_trait; }
mod utils { #[doc(inline)] pub use self::some_util::*; mod some_util; }
```

- **`#[doc(inline)]`** on re-exports so docs render the type at the re-export path, not the original.
- **Group re-exports by source module** with `pub use self::{ … }` braces.
- **Avoid `pub use` of external crate symbols** at your crate root unless you genuinely intend to re-export the dependency.

## Naming idioms

- **Types: `PascalCase`, no prefixes** (`Feed`, not `IFeed` or `TFeed`).
- **Traits: `PascalCase`, verb-or-capability** (`Compute`, `Forward`, `Actor`, not `Computable` unless the suffix carries meaning).
- **Modules / files: `snake_case`** (`btc_5m.rs`, `hawkes_tick.rs`).
- **Constants: `SCREAMING_SNAKE_CASE`** with units in the name (`ORACLE_STALE_SECONDS`, `MAX_BACKLOG_BYTES`).
- **Generic params: single uppercase** (`T`, `U`) for general; descriptive (`Ctx`, `Sig`) when the role is specific. Avoid `T1, T2` — it reads like fortran.

## Service / lifecycle pattern

For long-running services, the contract is `<Service>::start(...) -> Result<…>` (or `::serve` for things that block until shutdown). Keep this contract stable across extractions; it's the API surface that future re-extractions and re-folds depend on.

```rust
pub struct Gateway { /* … */ }

impl Gateway {
    pub async fn serve(self, addr: SocketAddr) -> anyhow::Result<()> { /* … */ }
}
```

**Why:** the `::start` / `::serve` contract is what makes the collapse-as-inverse-of-extraction rule operationally cheap. If you keep the entry point identical, folding a crate into a module changes only the `use` path, not the call site.

## Wrapper discipline — every struct earns its existence

A struct must justify itself by carrying one of:

1. **A type-system-enforced invariant** — `NonEmptyVec<T>`, `Permille(u16)`, `Validated<T>`. Makes an illegal state unrepresentable.
2. **A lifetime borrow** that composes references to live state — `Step<'a> { bot: &'a Bot, signal: &'a Signal }`. The lifetime IS the value-add.
3. **An owned heap allocation that's the unit of sharing** — `#[repr(transparent)] struct Outer { inner: Arc<Inner> }` with `Deref<Target=Inner>` + cheap `Clone`. The wrapper IS the handle.
4. **A substantive trait-receiver role** — associated types, generic parameters, or genuine implementor identity. Not a method-bag.

A struct that holds a single owned-clone of a params shape and exists only to host an `evaluate()` method is **not** a wrapper. It's a hollow type. Replace with:

- **Methods on the params type** (struct-as-compute, chainable): `impl XParams { pub fn evaluate(&self, signal: &XSignal) -> Result<XDecision, &'static str> }`.
- **Free fns** in a `gates/` or `compute/` module when no chaining benefit.
- **A lifetime-composing Step**: `pub struct XStep<'a> { bot: &'a XBot, signal: &'a XSignal }`. This is what hollow wrappers SHOULD have been when the operation legitimately borrows live runtime state.

**Smell-test grep:**

```sh
rg -n 'pub struct \w+ \{[\s\n]*pub params: \w+,?\s*\}' --type rust
```

Any hit is a hollow wrapper. The auditor runs this at every sprint close.

**Why:** hollow wrappers proliferate because "anchor a method on a named type" is one of the first Rust patterns reached for. Cheap to write, expensive to read — every reader chases the wrapper's body to learn it adds nothing. The substantive forms (`Step<'a, T>` with borrowed live state, `Arc<Inner>` with shared identity) ARE what justifies wrappers existing at all.

**How to apply:** before introducing a new wrapper, run the four-justification test. When refactoring a hollow wrapper, look for the lifetime-borrow form first — that's usually what the wrapper SHOULD have been.

## Tests

- **Unit tests in-module**, gated `#[cfg(test)]`, `mod tests { use super::*; … }` at the bottom of the file.
- **Integration tests in `tests/`** at the crate root — only public API.
- **Compile-time assertions** for invariants the type system can enforce (`static_assertions::assert_impl_all!(MyType: Send + Sync)`). Cheap, run at `cargo check`, catch regressions early.
- **Doc tests** for every non-trivial public function. Hidden setup with `#` prefix.
- **No `unwrap()` in tests outside the assertion itself.** Use `expect("reason")` or `?` with `Result<(), Box<dyn Error>>` test signatures.

## What never to do

- **No dead code.** Delete unused functions, unused types, unused imports. `git log` is the archive.
- **No commented-out code blocks.** Same reason.
- **No `pub` on a name that doesn't need to be public.** Default to `pub(crate)`; widen only when a downstream consumer actually needs it.
- **No `#[allow(dead_code)]` without a justifying comment** describing why the code is here and when it should be deleted.
- **No silent error swallowing.** A `let _ = …` discarding a `Result` is a bug unless paired with a comment explaining why the failure is genuinely OK.
- **No `.clone()` to dodge a borrow error** without first asking whether the design wants a different ownership shape. Clones are cheap to write, expensive to discover later.

## Cross-references

When this file disagrees with the universal `code-style:rust.md` skill, name the disagreement explicitly and let the operator decide. Don't paper over it. Project-specific overrides go below this line.

<!-- project-specific Rust rules begin here -->
