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
#[cfg(feature = "alloc")]
extern crate alloc;
// modules (public)
pub mod error;
pub mod settings;
// module (inline)
pub mod types {
    #[doc(inline)]
    pub use self::prelude::*;

    mod harness;

    mod prelude {
        pub use super::harness::*;
    }
}
// re-exports
#[doc(inline)]
pub use self::{
    error::{Error, Result},
    settings::ShepherdConfig,
    types::*,
};
// prelude
#[doc(hidden)]
pub mod prelude {
    pub use crate::error::*;
    pub use crate::settings::*;
    pub use crate::types::*;
}
