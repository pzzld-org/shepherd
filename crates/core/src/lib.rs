/*
    Appellation: shepherd-core <library>
    Created At: 2026.08.12:15:47:00
    Contrib: @FL03
*/
//! # shepherd-core
//!
//! The harness-agnostic shepherd engine: domain types, configuration schema,
//! and run state.
//!
//! ## The boundary
//!
//! **This crate does not know it is a CLI.** Shepherd was rewritten once, Python
//! to Rust, because the old implementation could not reach a new host. A third
//! rewrite happens the same way: some future host needs the engine without the
//! command-line interface wrapped around it.
//!
//! So nothing here may depend on `clap`, `std::process`, `anyhow`, a log sink,
//! or any harness by name. [`Harness`] is a value the engine carries, never a
//! branch the engine takes.
//!
//! The rule is enforced by CI compiling this crate to `wasm32-unknown-unknown`
//! on every push, not by this comment. A dependency that cannot reach that
//! target fails the build and names itself.
//!
//! ## Features
//!
//! Every dependency past `thiserror` and `strum` is optional, and every module
//! that needs one is gated on it. The point is not minimalism for its own sake:
//! it is that an embedder can take the run-state machine without linking a JSON
//! codec, a schema generator, a clock, or an entropy source.
//!
//! | Feature | Enables |
//! |---|---|
//! | `std` *(default)* | [`settings`], and the `std` surface of every enabled dependency |
//! | `alloc` | the `no_std` floor; [`error`] and [`types`] are available here |
//! | `config` | [`loader`], the configuration precedence chain and layering |
//! | `json` | [`run`], the canonical run-state codec (`serde` + `serde_json`) |
//! | `parse` | `nom`, for the run-id and branch grammars |
//! | `schema` | `schemars`, for the config key universe |
//! | `chrono`, `uuid`, `tracing` | the named dependency, nothing more |
//! | `full` | everything above; `native` is its alias |
//! | `wasm`, `wasi` | the target-appropriate set, deliberately without `uuid`/`chrono` |
#![cfg_attr(not(feature = "std"), no_std)]
#![cfg_attr(docsrs, feature(doc_auto_cfg))]
#![cfg_attr(feature = "nightly", feature(allocator_api))]

#[cfg(not(any(feature = "alloc", feature = "std")))]
compile_error! {
    "shepherd-core requires at least one of the `alloc` or `std` features; \
     the engine's error and domain types are allocating."
}

#[cfg(feature = "alloc")]
extern crate alloc;

// modules (public)
pub mod error;
#[cfg(all(feature = "config", feature = "std"))]
pub mod loader;
#[cfg(feature = "json")]
pub mod run;
#[cfg(feature = "std")]
pub mod settings;
// module (inline)
pub mod types {
    //! Domain types shared by every consumer of the engine.
    #[doc(inline)]
    pub use self::prelude::*;

    mod harness;

    mod prelude {
        pub use super::harness::*;
    }
}
// re-exports
#[cfg(feature = "json")]
#[doc(inline)]
pub use self::run::RunState;
#[cfg(feature = "std")]
#[doc(inline)]
pub use self::settings::ShepherdConfig;
#[doc(inline)]
pub use self::{
    error::{Error, Result},
    types::*,
};
// prelude
#[doc(hidden)]
pub mod prelude {
    #[allow(unused_imports)]
    pub use crate::error::*;
    #[cfg(feature = "json")]
    pub use crate::run::*;
    #[cfg(feature = "std")]
    pub use crate::settings::*;
    pub use crate::types::*;
}
