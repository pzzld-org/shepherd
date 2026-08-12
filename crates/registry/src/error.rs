/*
    Appellation: error <module>
    Created At: 2026.08.12:16:20:00
    Contrib: @FL03
*/
//! Typed registry errors.
//!
//! `rusqlite::Error` is wrapped rather than leaked so that a consumer can match
//! on registry semantics (a migration failed, the schema is ahead of this
//! binary) without matching on SQLite internals.
#[cfg(all(feature = "alloc", not(feature = "std")))]
use alloc::string::{String, ToString};

/// The result type returned throughout the registry.
pub type Result<T = (), E = Error> = core::result::Result<T, E>;

/// Every failure the registry itself can produce.
#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum Error {
    /// The engine reported a domain failure.
    #[error(transparent)]
    Core(#[from] shepherd_core::Error),
    /// SQLite reported a failure.
    #[error(transparent)]
    Sqlite(#[from] rusqlite::Error),
    /// A migration failed to apply; carries the version that broke.
    #[error("migration {version} failed: {message}")]
    Migration { version: i64, message: String },
    /// The database schema is newer than this binary understands.
    #[error("registry schema version {found} is ahead of the supported {supported}")]
    SchemaAhead { found: i64, supported: i64 },
    /// A catch-all for registry failures that do not yet warrant a variant.
    #[error("{0}")]
    Unknown(String),
}

impl Error {
    /// Build an [`Error::Unknown`] from anything displayable.
    pub fn unknown(message: impl core::fmt::Display) -> Self {
        Self::Unknown(message.to_string())
    }
}
