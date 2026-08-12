/*
    Appellation: shepherd-cli <library>
    Created At: 2026.08.12:14:55:18
    Contrib: @FL03
*/
//! # shepherd-cli
//!
//! The command-line adapter over [`shepherd_core`].
//!
//! Everything here is delivery: argument parsing, configuration loading and
//! layering, terminal output, exit codes. The domain types, configuration
//! schema, and run state live in the engine crate, which knows nothing about
//! any of it.
//!
//! When a second consumer arrives — a Node binding, a WebAssembly module, a
//! future harness adapter — it links [`shepherd_core`] directly and reimplements
//! only this layer. That is the arrangement that means the engine is never
//! rewritten again.
#[cfg(feature = "alloc")]
extern crate alloc;

pub use shepherd_core;

// modules (public)
pub mod cli;
// re-exports
#[doc(inline)]
pub use self::cli::ShepherdCli;
#[doc(inline)]
pub use shepherd_core::{Harness, ShepherdConfig, error, settings, types};
// prelude
#[doc(hidden)]
pub mod prelude {
    pub use crate::cli::prelude::*;
    pub use shepherd_core::prelude::*;
}
