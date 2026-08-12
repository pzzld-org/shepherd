/*
    Appellation: settings <module>
    Created At: 2026.08.12:14:58:31
    Contrib: @FL03
*/
//! The configuration schema.
//!
//! These types are the schema. **Precedence lives next door** in
//! [`crate::loader`], not in the CLI.
//!
//! An earlier draft of this module claimed the opposite — that "loading,
//! layering, and precedence are a consumer's concern". That was wrong, and
//! wrong in the way that causes rewrites. The precedence chain is ten
//! candidate files across four tiers, harness-parameterised, with a legacy
//! tier honoured indefinitely, written highest-priority-first while layering
//! libraries apply lowest-first. Leaving that to each adapter means every
//! adapter reimplements it, and the failure mode is a config file silently
//! ignored — no error, no log line, just a value that never takes effect.
//!
//! What genuinely is a consumer's concern is the *I/O*: resolving a repo root,
//! deciding which candidates exist, reading them, and consulting the process
//! environment. The engine says which files matter and in what order; the
//! adapter opens them. See [`crate::loader`] for where the line falls and the
//! `engine-boundary` CI job for what enforces it.
//!
//! This module is gated on `std` because it is the only part of the engine that
//! names a filesystem path. Under `alloc` alone you still get [`crate::error`]
//! and [`crate::types`]; you do not get a type that presumes a filesystem.
//!
//! Fields are `pub` because these are data-transfer types read across the crate
//! boundary by every consumer.

/// The root of `shepherd.toml`.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct ShepherdConfig {
    pub workspace: WorkspaceConfig,
}

/// Workspace-level paths and layout.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct WorkspaceConfig {
    pub workdir: std::path::PathBuf,
}

/// Project identity.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct ProjectConfig {
    pub name: String,
}
