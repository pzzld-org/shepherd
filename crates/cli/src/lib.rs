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
pub mod content_compiler;
pub mod context;
mod dispatch_scope;
mod dispatch_service;
mod dispatch_store;
mod interface;
pub mod migrate;
mod resume_context;
mod run_store;
// Non-unix only: the reparse-point-rejecting twins of the rustix
// descriptor primitives. See the module docs for what it does and does not
// guarantee relative to the unix side.
#[cfg(not(unix))]
mod safe_fs;
// re-exports
#[doc(inline)]
pub use self::context::{
    Clock, ContextEnvironment, ContextError, ContextHost, ContextInputs, ExecutionContext,
    IdentifierSource, IoBoundary, OutputFormat, RuntimeBindings, SystemEnvironment, SystemHost,
};
#[doc(inline)]
pub use self::dispatch_service::{
    BindRootDispatchRequest, DispatchResolution, DispatchService, DispatchServiceError,
    DispatchServiceResult, ResolveDispatchRequest, ResumeDispatchRequest, ResumeDispatchResponse,
    StartDispatchRequest, StopDispatchRequest,
};
#[doc(inline)]
pub use self::dispatch_store::{DispatchStore, DispatchStoreError, DispatchStoreResult};
#[doc(inline)]
pub use self::interface::{CliError, ShepherdCli};
#[doc(inline)]
pub use self::run_store::{RunStore, RunStoreError, RunStoreResult};
#[doc(inline)]
pub use shepherd::{Harness, ShepherdConfig, error, settings, types};
// prelude
#[doc(hidden)]
pub mod prelude {
    pub use crate::cmd::prelude::*;
    pub use crate::interface::ShepherdCli;
    pub use shepherd::prelude::*;
}
