/*
    Appellation: shepherd-render <library>
    Created At: 2026.08.12:16:20:00
    Contrib: @FL03
*/
//! # shepherd-render
//!
//! Template resolution, deterministic rendering, and artifact provenance.
//!
//! ## Why this is a crate and not a module
//!
//! Rendering is the one place shepherd emits bytes that another tool later
//! diffs. `render.py`'s manifest pins `template_sha256`, `vars_sha256` and
//! `output_sha256`, and the conformance oracle asserts all three reproduce
//! byte-identically across implementations. Holding that in its own crate lets
//! the property be tested without a database, a config loader, or a terminal --
//! and keeps a template engine out of [`shepherd_core`].
//!
//! ## The contract this crate owes
//!
//! Rendering is a pure function of (template bytes, variables). Anything that
//! varies per run -- a clock, a path, an environment variable, iteration order
//! over a hash map -- is a defect, because it makes the manifest hashes
//! unreproducible and the oracle unfalsifiable.
#![cfg_attr(not(feature = "std"), no_std)]
#![cfg_attr(docsrs, feature(doc_auto_cfg))]
#![cfg_attr(feature = "nightly", feature(allocator_api))]

#[cfg(not(any(feature = "alloc", feature = "std")))]
compile_error! {
    "shepherd-render requires at least one of the `alloc` or `std` features."
}

#[cfg(feature = "alloc")]
extern crate alloc;

pub use shepherd_core as core;

// modules (public)
pub mod error;

// re-exports
#[doc(inline)]
pub use self::error::{Error, Result};

// prelude
#[doc(hidden)]
pub mod prelude {
    #[allow(unused_imports)]
    pub use crate::error::*;
}
