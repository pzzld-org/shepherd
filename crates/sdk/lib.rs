/*
    Appellation: shepherd <library>
    Created At: 2026.08.12:16:20:00
    Contrib: @FL03
*/
//! # shepherd
//!
//! The umbrella SDK. Every consumer links this crate; nothing links a member
//! crate directly.
//!
//! ## Why an umbrella
//!
//! Shepherd has been rewritten once, Python to Rust, and the reason was reach:
//! the old implementation could not be embedded in a host that needed it
//! without the CLI wrapped around it. The member split is the insurance against
//! a third rewrite, and this crate is what makes the split usable -- one name,
//! one version, one feature vocabulary, regardless of how many members exist
//! behind it.
//!
//! That indirection is load-bearing. Splitting a new layer out of
//! [`shepherd_core`] is then an internal refactor, because consumers were never
//! naming the member they depended on.
//!
//! ## Capabilities, not crates
//!
//! Members are addressed by what they *do*, never by their crate name:
//!
//! | Feature | Adds | Cost |
//! |---|---|---|
//! | *(none)* | the engine: domain types, run state, config schema | `thiserror`, `strum` |
//! | `json` | the canonical artifact codec | `serde`, `serde_json` |
//! | `parse` | the run-id and branch grammars | `nom` |
//! | `schema` | the config key universe | `schemars` |
//! | `registry` | the SQLite registry and migration runner | `rusqlite` |
//! | `render` | deterministic templating and provenance | `minijinja`, `sha2` |
//! | `full` | everything; `native` is its alias | all of the above |
//!
//! Capability flags fan out weakly (`?/`), so asking for `json` configures the
//! registry only if you already asked for `registry`. Enabling a capability
//! never conjures a member you did not request.
//!
//! ## The boundary still holds
//!
//! This crate adds no dependency of its own -- it is re-exports and a feature
//! graph. `shepherd-core` remains free of `clap`, `anyhow`, a log sink, an I/O
//! backend, and `std::process`, and CI proves it on every push by compiling it
//! to `wasm32-unknown-unknown` alongside a forbidden-dependency gate.
#![cfg_attr(not(feature = "std"), no_std)]
#![cfg_attr(docsrs, feature(doc_auto_cfg))]
#![cfg_attr(feature = "nightly", feature(allocator_api))]

#[cfg(not(any(feature = "alloc", feature = "std")))]
compile_error! {
    "shepherd requires at least one of the `alloc` or `std` features."
}

#[cfg(feature = "alloc")]
extern crate alloc;

// re-exports — the engine is flattened, capabilities are namespaced
#[doc(inline)]
pub use shepherd_core::*;

/// The SQLite registry: schema, migration runner, and query surface.
#[cfg(feature = "registry")]
#[doc(inline)]
pub use shepherd_registry as registry;

/// Template resolution, deterministic rendering, and artifact provenance.
#[cfg(feature = "render")]
#[doc(inline)]
pub use shepherd_render as render;

// prelude
//
// Only the engine is glob-re-exported here. Every member defines its own
// `Error` and `Result`, so globbing all three would make `shepherd::prelude::*`
// ambiguous at the use site (E0659) the moment a consumer enabled two
// capabilities. Member preludes stay addressable at `shepherd::registry::prelude`.
#[doc(hidden)]
pub mod prelude {
    #[allow(unused_imports)]
    pub use shepherd_core::prelude::*;
}
