/*
    Appellation: shepherd-cli <library>
    Created At: 2026.08.12:14:55:18
    Contrib: @FL03
*/
//! # shepherd-cli
//!
//! The command-line adapter over the [`shepherd`] SDK.
//!
//! Everything here is delivery: argument parsing, configuration loading and
//! layering, terminal output, exit codes, and the tracing subscriber. The
//! domain types, configuration schema, and run state live behind the umbrella,
//! which knows nothing about any of it.
//!
//! When a second consumer arrives — a Node binding, a WebAssembly module, a
//! future harness adapter — it links [`shepherd`] with the capabilities it
//! wants and reimplements only this layer. That is the arrangement that means
//! the engine is never rewritten again.
//!
//! Note the direction of the dependency: this crate names [`shepherd`], never
//! `shepherd-core`, `shepherd-registry`, or `shepherd-render`. Splitting a new
//! member out of the engine is then an internal refactor rather than a change
//! every adapter has to absorb.
#[cfg(feature = "alloc")]
extern crate alloc;

pub use shepherd;

// modules (public)
pub mod cmd;
mod interface;
// re-exports
#[doc(inline)]
pub use self::interface::ShepherdCli;
#[doc(inline)]
pub use shepherd::{Harness, ShepherdConfig, error, settings, types};
// prelude
#[doc(hidden)]
pub mod prelude {
    pub use crate::cmd::prelude::*;
    pub use crate::interface::ShepherdCli;
    pub use shepherd::prelude::*;
}
