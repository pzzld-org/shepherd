/*
    Appellation: settings <module>
    Created At: 2026.08.12:14:58:31
    Contrib: @FL03
*/
//! The configuration schema.
//!
//! These types are the schema only. Loading, layering, and precedence are a
//! consumer's concern: `shepherd-cli` owns that and resolves the six tiers with
//! the `config` crate. Keeping the schema here means an embedder can validate
//! or generate configuration without linking a file loader.
//!
//! Fields are `pub` because these are data-transfer types read across the crate
//! boundary by every consumer.

/// The root of `shepherd.toml`.
#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, serde::Deserialize, serde::Serialize,
)]
pub struct ShepherdConfig {
    pub workspace: WorkspaceConfig,
}

/// Workspace-level paths and layout.
#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, serde::Deserialize, serde::Serialize,
)]
pub struct WorkspaceConfig {
    pub workdir: std::path::PathBuf,
}

/// Project identity.
#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, serde::Deserialize, serde::Serialize,
)]
pub struct ProjectConfig {
    pub name: String,
}
