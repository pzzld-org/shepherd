/*
    Appellation: error <module>
    Created At: 2026.08.12:16:20:00
    Contrib: @FL03
*/
//! Typed render errors.
#[cfg(all(feature = "alloc", not(feature = "std")))]
use alloc::string::{String, ToString};

/// The result type returned throughout the render layer.
pub type Result<T = (), E = Error> = core::result::Result<T, E>;

/// Every failure the render layer itself can produce.
#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum Error {
    /// The engine reported a domain failure.
    #[error(transparent)]
    Core(#[from] shepherd_core::Error),
    /// The template engine failed to compile or evaluate a template.
    #[error(transparent)]
    Template(#[from] minijinja::Error),
    /// A named template was not found on the resolution path.
    #[error("template not found: {0}")]
    TemplateNotFound(String),
    /// A rendered artifact did not match its recorded provenance hash.
    #[error("provenance mismatch for {artifact}: expected {expected}, produced {produced}")]
    ProvenanceMismatch {
        artifact: String,
        expected: String,
        produced: String,
    },
    /// A catch-all for render failures that do not yet warrant a variant.
    #[error("{0}")]
    Unknown(String),
}

impl Error {
    /// Build an [`Error::Unknown`] from anything displayable.
    pub fn unknown(message: impl core::fmt::Display) -> Self {
        Self::Unknown(message.to_string())
    }
}
