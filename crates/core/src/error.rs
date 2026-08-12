/*
    Appellation: error <module>
    Created At: 2026.08.12:15:47:00
    Contrib: @FL03
*/
//! Typed engine errors.
//!
//! This crate returns typed errors, never `anyhow`. A caller that wants
//! contextual strings adds them at its own boundary; an embedder that wants to
//! match on a variant can.

/// The result type returned throughout the engine.
pub type Result<T = (), E = Error> = core::result::Result<T, E>;

/// Every failure the engine itself can produce.
#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum Error {
    /// A configuration value was absent, malformed, or of the wrong type.
    #[error("invalid configuration: {0}")]
    Config(String),
    /// A run id violated the canonical slug grammar.
    #[error("invalid run id: {0}")]
    InvalidRunId(String),
    /// A branch or slug did not match the configured `[branching]` pattern.
    #[error("unrecognized branch or slug: {0}")]
    UnrecognizedPattern(String),
    /// Serialization or deserialization of an artifact failed.
    #[error("serialization failure: {0}")]
    Serialization(String),
    /// A catch-all for engine failures that do not yet warrant a variant.
    #[error("{0}")]
    Unknown(String),
}

impl Error {
    /// Build a [`Error::Config`] from anything displayable.
    pub fn config(message: impl core::fmt::Display) -> Self {
        Self::Config(message.to_string())
    }
    /// Build a [`Error::Unknown`] from anything displayable.
    pub fn unknown(message: impl core::fmt::Display) -> Self {
        Self::Unknown(message.to_string())
    }
}
