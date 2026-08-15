/*
    Appellation: loader <module>
    Created At: 2026.08.12:17:30:00
    Contrib: @FL03
*/
//! Fixed configuration precedence with standards-backed source layering.
//!
//! This module never reads a file, an environment variable, or a git process.
//! Hosts provide already-read `(path, contents)` pairs in the same
//! highest-priority-first order returned by [`candidates`]. The `config`
//! crate owns TOML source merge and typed deserialization; Shepherd owns only
//! its closed candidate policy and migration compatibility boundary.

use alloc::{
    string::{String, ToString},
    vec::Vec,
};
use std::path::{Path, PathBuf};

use config::{Config as SourceConfig, File, FileFormat};

use crate::{Error, Result, settings::ShepherdConfig, types::Harness};

/// The only ordinary-runtime configuration tiers.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(rename_all = "snake_case"))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub enum ConfigTier {
    Project,
    User,
}

/// One possible configuration file, without an existence check.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ConfigCandidate {
    pub path: PathBuf,
    pub tier: ConfigTier,
}

/// Pure inputs to the canonical candidate policy.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct ConfigContext {
    pub primary_root: PathBuf,
    pub user_home: Option<PathBuf>,
    pub harness: Option<Harness>,
}

/// One layer that contributed to a resolved configuration.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ConfigSource {
    pub path: PathBuf,
}

/// A resolved configuration and its highest-priority-first provenance.
#[derive(Clone, Debug, PartialEq)]
pub struct LoadedConfig {
    pub config: ShepherdConfig,
    pub sources: Vec<ConfigSource>,
}

/// The validation policy used while resolving configuration layers.
///
/// Ordinary commands use [`LoadMode::Strict`]. Layout-v5 migration is the
/// only compatibility boundary: it recognizes a closed, typed set of retired
/// keys, removes those keys before the ordinary schema is decoded, and leaves
/// every other typo or unknown field to the strict schema.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum LoadMode {
    #[default]
    Strict,
    LayoutV5Migration,
}

/// Return the canonical candidates, highest priority first.
///
/// There are six candidates with a harness and four without one when a user
/// home is available. A missing optional user home produces only the project
/// candidates. Legacy `.claude`, `.artifacts`, and XDG paths are migration
/// inputs and never enter this function.
pub fn candidates(cx: &ConfigContext) -> Vec<ConfigCandidate> {
    let namespace = cx.primary_root.join(".shepherd");
    let capacity = if cx.harness.is_some() { 6 } else { 4 };
    let mut out = Vec::with_capacity(capacity);
    push_tier(&mut out, &namespace, ConfigTier::Project, cx.harness);
    if let Some(user_home) = &cx.user_home
        && user_home != &namespace
    {
        push_tier(&mut out, user_home, ConfigTier::User, cx.harness);
    }
    out
}

fn push_tier(
    out: &mut Vec<ConfigCandidate>,
    root: &Path,
    tier: ConfigTier,
    harness: Option<Harness>,
) {
    out.push(ConfigCandidate {
        path: root.join("shepherd.local.toml"),
        tier,
    });
    if let Some(harness) = harness {
        out.push(ConfigCandidate {
            path: root.join(alloc::format!("shepherd.{harness}.toml")),
            tier,
        });
    }
    out.push(ConfigCandidate {
        path: root.join("shepherd.toml"),
        tier,
    });
}

/// Validate and merge caller-supplied layers, highest priority first.
pub fn load<'a, I>(layers: I) -> Result<LoadedConfig>
where
    I: IntoIterator<Item = (&'a Path, &'a str)>,
{
    load_with_mode(layers, LoadMode::Strict)
}

/// Validate and merge layers for a layout-v5 migration only.
///
/// This remains one TOML parse and the normal [`ShepherdConfig`] schema. The
/// compatibility mode only removes retired values that it has first verified
/// against their historical types. All ordinary commands must use [`load`].
pub fn load_for_layout_v5_migration<'a, I>(layers: I) -> Result<LoadedConfig>
where
    I: IntoIterator<Item = (&'a Path, &'a str)>,
{
    load_with_mode(layers, LoadMode::LayoutV5Migration)
}

/// Validate and merge caller-supplied layers under one explicit policy.
///
/// Inputs arrive highest priority first, whereas `config` applies later
/// sources as overrides. We therefore validate in caller order, then add the
/// normalized sources in reverse. This keeps both Shepherd's provenance order
/// and the standard builder's merge semantics explicit.
pub fn load_with_mode<'a, I>(layers: I, mode: LoadMode) -> Result<LoadedConfig>
where
    I: IntoIterator<Item = (&'a Path, &'a str)>,
{
    let ordered: Vec<(&Path, &str)> = layers.into_iter().collect();
    let mut parsed = Vec::with_capacity(ordered.len());

    for (path, contents) in &ordered {
        parsed.push(parse_layer(path, contents, mode)?);
    }

    let mut builder = SourceConfig::builder();
    for value in parsed.iter().rev() {
        let source = toml::to_string(value).map_err(|error| {
            Error::config(alloc::format!(
                "{}: {error}",
                ordered
                    .first()
                    .map_or_else(|| Path::new("<defaults>"), |layer| layer.0)
                    .display()
            ))
        })?;
        builder = builder.add_source(File::from_str(&source, FileFormat::Toml));
    }
    let merged = builder.build().map_err(|error| {
        Error::config(alloc::format!(
            "{}: {error}",
            ordered
                .first()
                .map_or_else(|| Path::new("<defaults>"), |layer| layer.0)
                .display()
        ))
    })?;
    let config = deserialize_merged(
        ordered.first().map_or(Path::new("<defaults>"), |v| v.0),
        merged,
    )?;
    Ok(LoadedConfig {
        config,
        sources: ordered
            .into_iter()
            .map(|(path, _)| ConfigSource {
                path: path.to_path_buf(),
            })
            .collect(),
    })
}

/// Compatibility convenience returning only the resolved value.
pub fn layer<'a, I>(layers: I) -> Result<ShepherdConfig>
where
    I: IntoIterator<Item = (&'a Path, &'a str)>,
{
    load(layers).map(|loaded| loaded.config)
}

/// Validate a single candidate without touching the filesystem.
pub fn validate(path: &Path, contents: &str) -> Result {
    parse_layer(path, contents, LoadMode::Strict).map(|_| ())
}

fn parse_layer(path: &Path, contents: &str, mode: LoadMode) -> Result<toml::Value> {
    let mut value: toml::Value = toml::from_str(contents).map_err(|error| {
        Error::config(alloc::format!("{}: {}", path.display(), error.message()))
    })?;
    if mode == LoadMode::LayoutV5Migration {
        strip_retired_layout_v5(path, &mut value)?;
    }
    validate_gate_entries(path, &value)?;
    deserialize_toml(path, value.clone())?;
    Ok(value)
}

fn strip_retired_layout_v5(path: &Path, value: &mut toml::Value) -> Result {
    let Some(root) = value.as_table_mut() else {
        return Ok(());
    };

    if let Some(paths) = root.get_mut("paths").and_then(toml::Value::as_table_mut) {
        remove_legacy_string(path, paths, "paths", "plans")?;
        remove_legacy_string(path, paths, "paths", "reports")?;
    }

    if let Some(memory) = root.remove("memory") {
        validate_retired_memory(path, memory)?;
    }

    if let Some(context) = root.get_mut("context").and_then(toml::Value::as_table_mut) {
        remove_legacy_bool(path, context, "context", "enabled")?;
        for field in ["db_path", "lock_path", "project_id_path"] {
            remove_legacy_string(path, context, "context", field)?;
        }
        remove_legacy_string(path, context, "context", "announce_shctx_path")?;
    }
    Ok(())
}

fn validate_retired_memory(path: &Path, memory: toml::Value) -> Result {
    let Some(memory) = memory.as_table() else {
        return Err(config_error(path, "memory", "expected a table"));
    };
    for field in memory.keys() {
        if field != "project_memory" && field != "project_doctrines" {
            return Err(config_error(
                path,
                &alloc::format!("memory.{field}"),
                "unknown legacy key",
            ));
        }
    }
    for field in ["project_memory", "project_doctrines"] {
        match memory.get(field) {
            Some(toml::Value::String(_)) => {}
            Some(_) => {
                return Err(config_error(
                    path,
                    &alloc::format!("memory.{field}"),
                    "expected a string",
                ));
            }
            None => {
                return Err(config_error(
                    path,
                    &alloc::format!("memory.{field}"),
                    "required legacy key is missing",
                ));
            }
        }
    }
    Ok(())
}

fn remove_legacy_string(
    path: &Path,
    table: &mut toml::Table,
    section: &str,
    field: &str,
) -> Result {
    let Some(value) = table.remove(field) else {
        return Ok(());
    };
    if value.is_str() {
        Ok(())
    } else {
        Err(config_error(
            path,
            &alloc::format!("{section}.{field}"),
            "expected a string",
        ))
    }
}

fn remove_legacy_bool(path: &Path, table: &mut toml::Table, section: &str, field: &str) -> Result {
    let Some(value) = table.remove(field) else {
        return Ok(());
    };
    if value.is_bool() {
        Ok(())
    } else {
        Err(config_error(
            path,
            &alloc::format!("{section}.{field}"),
            "expected a boolean",
        ))
    }
}

fn config_error(path: &Path, key: &str, message: &str) -> Error {
    Error::config(alloc::format!("{}: {key}: {message}", path.display()))
}

fn validate_gate_entries(path: &Path, value: &toml::Value) -> Result {
    let Some(extra) = value.get("gates").and_then(|gates| gates.get("extra")) else {
        return Ok(());
    };

    if let Some(map) = extra.as_table() {
        for (name, command) in map {
            if !command.is_str() {
                return Err(Error::config(alloc::format!(
                    "{}: gates.extra.{name}: expected a string",
                    path.display()
                )));
            }
        }
        return Ok(());
    }

    let Some(entries) = extra.as_array() else {
        return Ok(());
    };

    for entry in entries {
        let Some(table) = entry.as_table() else {
            continue;
        };
        for field in ["name", "cmd"] {
            if !table.contains_key(field) {
                return Err(Error::config(alloc::format!(
                    "{}: gates.extra.{field}: required field is missing",
                    path.display()
                )));
            }
            if !table.get(field).is_some_and(toml::Value::is_str) {
                return Err(Error::config(alloc::format!(
                    "{}: gates.extra.{field}: expected a string",
                    path.display()
                )));
            }
        }
        for field in table.keys() {
            if field != "name" && field != "cmd" {
                return Err(Error::config(alloc::format!(
                    "{}: gates.extra.{field}: unknown key",
                    path.display()
                )));
            }
        }
    }
    Ok(())
}

fn deserialize_toml(path: &Path, value: toml::Value) -> Result<ShepherdConfig> {
    let config: ShepherdConfig = value.try_into().map_err(|error: toml::de::Error| {
        Error::config(alloc::format!("{}: {}", path.display(), diagnostic(&error)))
    })?;
    validate_config(path, config)
}

fn deserialize_merged(path: &Path, value: SourceConfig) -> Result<ShepherdConfig> {
    let config = value
        .try_deserialize()
        .map_err(|error| Error::config(alloc::format!("{}: {error}", path.display())))?;
    validate_config(path, config)
}

fn validate_config(path: &Path, config: ShepherdConfig) -> Result<ShepherdConfig> {
    config.validate().map_err(|error| {
        let message = match error {
            Error::Config(message) => message,
            other => other.to_string(),
        };
        Error::config(alloc::format!("{}: {message}", path.display()))
    })?;
    Ok(config)
}

fn diagnostic(error: &toml::de::Error) -> String {
    let rendered = error.to_string();
    let path = rendered.lines().find_map(|line| {
        line.strip_prefix("in `")
            .and_then(|line| line.strip_suffix('`'))
    });
    let message = error.message();
    let unknown = message
        .strip_prefix("unknown field `")
        .and_then(|rest| rest.split_once('`').map(|(field, _)| field));

    match (path, unknown) {
        (Some(parent), Some(field)) if !parent.is_empty() => {
            alloc::format!("{parent}.{field}: {message}")
        }
        (_, Some(field)) => alloc::format!("{field}: {message}"),
        (Some(path), None) if !path.is_empty() => alloc::format!("{path}: {message}"),
        _ => message.to_string(),
    }
}

/// Render the complete schema as deterministic compact JSON.
#[cfg(all(feature = "schema", feature = "json"))]
pub fn schema_json() -> Result<String> {
    serde_json::to_string(&schemars::schema_for!(ShepherdConfig))
        .map_err(|error| Error::Serialization(error.to_string()))
}
