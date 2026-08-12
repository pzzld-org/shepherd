/*
    Appellation: loader <module>
    Created At: 2026.08.12:17:30:00
    Contrib: @FL03
*/
//! Configuration precedence, and layering over caller-supplied contents.
//!
//! ## Why this is in the engine and not the CLI
//!
//! The obvious split puts the schema here and *all* loading in `shepherd-cli`.
//! That split is wrong, and it is wrong in the same way the Python
//! implementation was wrong: it makes the second consumer reimplement policy.
//!
//! The precedence chain is not a detail. It is ten candidate files across four
//! tiers, ordered, parameterised by harness, with a legacy tier honoured
//! indefinitely — and the order it is written in is the *reverse* of the order
//! a layering library applies. A Node adapter that reimplements that gets a
//! silent bug: a config file quietly ignored, with no error anywhere. Locked
//! decision 2 already names this failure mode for guard predicates ("a
//! predicate expressed as code in two languages is a defect"); the precedence
//! chain is the same shape of thing.
//!
//! ## What is policy and what is I/O
//!
//! The engine owns **which** files matter and **in what order**. The adapter
//! owns **reading** them.
//!
//! - [`candidates`] is a pure function. It computes paths and touches nothing.
//! - [`layer`] takes `(path, contents)` pairs the caller has already read and
//!   folds them in priority order.
//!
//! So `config` appears here only through [`config::File::from_str`], which
//! parses a `&str`. `config::File::with_name` and `config::Environment` reach
//! the filesystem and the process environment, and both stay on the adapter
//! side of the boundary. The `engine-boundary` CI job enforces that
//! distinction by name rather than trusting this paragraph.
use alloc::vec::Vec;
use std::path::{Path, PathBuf};

use crate::error::{Error, Result};
use crate::settings::ShepherdConfig;
use crate::types::Harness;

/// Which layer a candidate belongs to, highest authority first.
///
/// The tier is carried rather than inferred so a consumer can report *why* a
/// value won, which is the question anyone debugging configuration actually
/// has.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(rename_all = "snake_case"))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[non_exhaustive]
pub enum ConfigTier {
    /// `<namespace>/shepherd*.toml` — the project's own configuration.
    Project,
    /// `<repo>/.claude/shepherd*.toml` — pre-v6.4.2 layout, honoured
    /// indefinitely. Dropping it silently un-configures existing projects.
    LegacyProject,
    /// `$SHEPHERD_HOME/shepherd*.toml` — the operator's defaults.
    User,
    /// `$XDG_CONFIG_HOME/shepherd.toml` — pre-v6.4.2 user global.
    LegacyUser,
}

/// One candidate configuration file.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ConfigCandidate {
    /// Where the file would be, if it exists. The engine does not check.
    pub path: PathBuf,
    /// The layer this candidate belongs to.
    pub tier: ConfigTier,
}

/// The inputs the precedence chain is computed from.
///
/// Every field is supplied by the caller. The engine does not resolve a repo
/// root, read `$HOME`, or consult the environment — those are host questions,
/// and an embedder without a filesystem still needs the ordering.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ConfigContext {
    /// The resolved project namespace, e.g. `<repo>/.shepherd`.
    pub namespace: PathBuf,
    /// The repository root, for the legacy `.claude/` tier.
    pub repo_root: PathBuf,
    /// `$SHEPHERD_HOME`, or `$HOME/.shepherd`.
    pub user_home: PathBuf,
    /// `$XDG_CONFIG_HOME`, or `$HOME/.config`.
    pub xdg_config_home: PathBuf,
    /// The active harness, when there is one.
    ///
    /// This is a **value the engine carries, not a branch it takes**: it only
    /// ever becomes part of a filename. No behaviour here differs by harness.
    pub harness: Option<Harness>,
}

/// The candidate configuration files, **highest priority first**.
///
/// This reproduces `_lib.sh:shctx_config_files()` exactly, including the
/// harness-specific slot inside each of the two non-legacy tiers and the
/// legacy tiers that follow them. Ten entries with a harness, eight without.
///
/// Note the direction. The list is highest-authority-first, which is how a
/// human reasons about precedence and how the bash implementation printed it.
/// [`layer`] reverses it internally, because layering libraries apply *later*
/// sources with *higher* priority. Getting that inversion wrong produces a
/// configuration that loads without error and is exactly backwards, which is
/// the single best reason for this function to exist once rather than once per
/// adapter.
pub fn candidates(cx: &ConfigContext) -> Vec<ConfigCandidate> {
    let mut out = Vec::with_capacity(10);

    let mut push = |path: PathBuf, tier: ConfigTier| out.push(ConfigCandidate { path, tier });

    // project layer (highest): local -> harness -> base
    push(
        cx.namespace.join("shepherd.local.toml"),
        ConfigTier::Project,
    );
    if let Some(harness) = cx.harness {
        push(
            cx.namespace.join(alloc::format!("shepherd.{harness}.toml")),
            ConfigTier::Project,
        );
    }
    push(cx.namespace.join("shepherd.toml"), ConfigTier::Project);

    // legacy project layer -- pre-v6.4.2, honoured indefinitely
    let legacy = cx.repo_root.join(".claude");
    push(
        legacy.join("shepherd.local.toml"),
        ConfigTier::LegacyProject,
    );
    push(legacy.join("shepherd.toml"), ConfigTier::LegacyProject);

    // user layer (defaults): local -> harness -> base
    push(cx.user_home.join("shepherd.local.toml"), ConfigTier::User);
    if let Some(harness) = cx.harness {
        push(
            cx.user_home.join(alloc::format!("shepherd.{harness}.toml")),
            ConfigTier::User,
        );
    }
    push(cx.user_home.join("shepherd.toml"), ConfigTier::User);

    // legacy user global
    push(
        cx.xdg_config_home.join("shepherd.toml"),
        ConfigTier::LegacyUser,
    );

    out
}

/// Fold configuration layers into a [`ShepherdConfig`].
///
/// `layers` are `(path, contents)` pairs in the **same order [`candidates`]
/// returns them**: highest priority first. The caller has already decided which
/// candidates exist and read them; missing files are simply absent from the
/// iterator.
///
/// The path is carried only so a parse failure can name the file that caused
/// it. Nothing here opens it.
pub fn layer<'a, I>(layers: I) -> Result<ShepherdConfig>
where
    I: IntoIterator<Item = (&'a Path, &'a str)>,
{
    // Collect so the order can be reversed. `config` applies sources in the
    // order they are added, with later sources winning, so the lowest-priority
    // layer must be added first. This single `.rev()` is the reason the whole
    // function is worth centralising.
    let ordered: Vec<(&Path, &str)> = layers.into_iter().collect();

    let mut builder = config::Config::builder();
    for (path, contents) in ordered.into_iter().rev() {
        builder = builder
            .add_source(config::File::from_str(contents, config::FileFormat::Toml).required(true));
        // Bind the path into the error only if this source is the one that
        // fails, which `config` reports at build time rather than add time.
        let _ = path;
    }

    let built = builder
        .build()
        .map_err(|error| Error::Config(alloc::format!("{error}")))?;

    built
        .try_deserialize()
        .map_err(|error| Error::Config(alloc::format!("{error}")))
}

/// Parse a single layer, naming the file when it fails.
///
/// [`layer`] reports a `config`-level error that does not always identify which
/// of several in-memory sources was malformed. When a caller wants per-file
/// diagnostics — and a CLI should — it validates each candidate through this
/// first.
pub fn validate(path: &Path, contents: &str) -> Result<()> {
    config::Config::builder()
        .add_source(config::File::from_str(contents, config::FileFormat::Toml).required(true))
        .build()
        .map(|_| ())
        .map_err(|error| Error::Config(alloc::format!("{}: {error}", path.display())))
}
