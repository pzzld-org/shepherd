/*
    Appellation: shepherd-registry <library>
    Created At: 2026.08.12:16:20:00
    Contrib: @FL03
*/
//! # shepherd-registry
//!
//! The SQLite registry: schema, migration runner, and query surface.
//!
//! ## Why this is a crate and not a module
//!
//! **The registry schema is the cross-harness contract, not CLI stdout.** All 32
//! guard scripts open `shepherd.db` directly and none of them shell out to a
//! binary, so row shapes are the compatibility surface every implementation
//! must honor. Isolating that surface in its own crate means a consumer can
//! link the schema without linking the command-line interface, and means
//! `shepherd-core` never acquires an I/O backend.
//!
//! ## The contract this crate owes
//!
//! - **21** migration files port **verbatim**: `0001_init.sql` (the baseline
//!   schema, applied first) plus the 20 files under `migrations/`
//!   (`0002`-`0021`). `0001_init.sql` sits at the schema-dir TOP LEVEL, not
//!   under `migrations/`, and is applied by a separate path in the existing
//!   bash/Python runners (`shctx init`) -- a runner that globs only
//!   `migrations/*.sql` silently skips the baseline. [`migrate::apply_all`]
//!   applies both, in order, and never skips version 1. Migration SQL is the
//!   portable artifact; only the runner is rewritten. `rusqlite_migration` is
//!   rejected: it tracks state in `user_version`, while this schema uses a
//!   `schema_versions` table that both existing runners already read.
//! - FTS5 external-content tables keep the `unicode61 remove_diacritics 2`
//!   tokenizer and all 6 sync triggers.
//! - `json_valid()` CHECK constraints are asserted by **behavior**, never by
//!   probing `PRAGMA compile_options` for `ENABLE_JSON1`. That flag is absent
//!   on 3.53.2 and `json_valid` still works, because JSON went core in 3.38.
//!
//! Acceptance for the port is an order-normalized `sqlite_master` dump that is
//! byte-identical between the Python and Rust implementations.
#![cfg_attr(not(feature = "std"), no_std)]
#![cfg_attr(docsrs, feature(doc_auto_cfg))]
#![cfg_attr(feature = "nightly", feature(allocator_api))]

#[cfg(not(any(feature = "alloc", feature = "std")))]
compile_error! {
    "shepherd-registry requires at least one of the `alloc` or `std` features."
}

#[cfg(feature = "alloc")]
extern crate alloc;

pub use shepherd_core as core;

// modules (public)
pub mod error;
#[cfg(feature = "std")]
pub mod migrate;

// re-exports
#[doc(inline)]
pub use self::error::{Error, Result};

// prelude
#[doc(hidden)]
pub mod prelude {
    #[allow(unused_imports)]
    pub use crate::error::*;
}
