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
    collections::BTreeSet,
    string::{String, ToString},
    vec::Vec,
};
use std::path::{Path, PathBuf};

use config::{
    Config as SourceConfig, ConfigError, FileFormat, Format, Map, Source, Value, ValueKind,
};

use crate::{Error, Result, settings::ShepherdConfig, types::Harness};

/// A `config::ConfigError`-flavored result, used only by the structural
/// checks `parse_layer` performs before the typed schema ever sees a
/// layer. Kept distinct from [`Result`] (this crate's own typed error) so the
/// two error universes are never accidentally conflated.
type ConfigResult<T = ()> = core::result::Result<T, ConfigError>;

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
    /// Fully dotted keys (e.g. `"models.root"`) that some merged layer set
    /// explicitly, before defaults were applied. Collected from the same
    /// per-layer [`Format::parse`] each layer already goes through (see
    /// `parse_layer` and `collect_dotted_keys`), so this costs one walk
    /// of an already-parsed table, never an extra parse. This is the exact
    /// provenance a caller needs to distinguish "the merged value happens to
    /// equal the default" from "a layer actually set this key" -- a
    /// distinction comparing the merged value against
    /// [`crate::settings::ModelsConfig::default`] can never make.
    pub explicit_keys: BTreeSet<String>,
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
/// This remains one parse per layer and the normal [`ShepherdConfig`] schema.
/// The compatibility mode only removes retired values that it has first
/// verified against their historical types. All ordinary commands must use
/// [`load`].
pub fn load_for_layout_v5_migration<'a, I>(layers: I) -> Result<LoadedConfig>
where
    I: IntoIterator<Item = (&'a Path, &'a str)>,
{
    load_with_mode(layers, LoadMode::LayoutV5Migration)
}

/// Validate and merge caller-supplied layers under one explicit policy.
///
/// Inputs arrive highest priority first, whereas `config` applies later
/// sources as overrides. We therefore register the normalized sources in
/// reverse, which keeps both Shepherd's provenance order and the standard
/// builder's merge semantics explicit.
///
/// Each layer is parsed exactly once by `parse_layer`, which also carries
/// the layer's own structural checks (the layout-v5 migration strip and the
/// open-map shape checks) and hands back the already-typed
/// `Map<String, Value>`. That same table is walked once more, locally, via
/// `collect_dotted_keys` to fold its explicit keys into
/// [`LoadedConfig::explicit_keys`] before the table is handed to a thin
/// `LayerSource` wrapper for the merge -- no second parse anywhere in this
/// path. Only after every layer has been merged does the full
/// [`ShepherdConfig`] get decoded and cross-field validated -- once, against
/// the merged result, never per layer. A layer that is legal only in
/// combination with another layer (see
/// [`crate::loader`] module docs and the `loader.rs` test suite) therefore
/// loads correctly instead of being rejected before the merge ever happens.
pub fn load_with_mode<'a, I>(layers: I, mode: LoadMode) -> Result<LoadedConfig>
where
    I: IntoIterator<Item = (&'a Path, &'a str)>,
{
    let ordered: Vec<(&Path, &str)> = layers.into_iter().collect();
    let default_path = ordered
        .first()
        .map_or_else(|| Path::new("<defaults>"), |layer| layer.0);

    let mut explicit_keys: BTreeSet<String> = BTreeSet::new();
    let mut builder = SourceConfig::builder();
    for (path, contents) in ordered.iter().rev() {
        let table =
            parse_layer(path, contents, mode).map_err(|error| Error::config(error.to_string()))?;
        collect_dotted_keys(&table, "", &mut explicit_keys);
        builder = builder.add_source(LayerSource::new(table));
    }
    let merged = builder
        .build()
        .map_err(|error| Error::config(error.to_string()))?;
    let config = deserialize_merged(default_path, merged)?;
    Ok(LoadedConfig {
        config,
        sources: ordered
            .into_iter()
            .map(|(path, _)| ConfigSource {
                path: path.to_path_buf(),
            })
            .collect(),
        explicit_keys,
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
///
/// This is a single-layer call into [`load_with_mode`]: with exactly one
/// layer contributing, the merge is a no-op and the full decode plus
/// cross-field validation run against that one candidate, which is precisely
/// the single-candidate contract this function promises.
pub fn validate(path: &Path, contents: &str) -> Result {
    load_with_mode([(path, contents)], LoadMode::Strict).map(|_| ())
}

/// Parse one already-read layer exactly once via the public [`Format`] trait
/// (`FileFormat::Toml.parse`), which stamps every resulting value's origin
/// with `path` as it parses (so a post-merge type error can still name the
/// file that contributed the offending value) -- unlike [`config::File`],
/// which only ever parses from a stored path or hardcodes `uri: None` for
/// [`config::File::from_str`], this never loses the layer's identity. It
/// also applies the layout-v5 migration strip when
/// [`LoadMode::LayoutV5Migration`] is active, and runs the per-layer
/// structural checks that cannot wait for the merge (dynamic map and
/// gate-entry shapes; these are local to one key's value and can never
/// become valid only in combination with another layer, unlike the
/// cross-field checks in [`crate::settings::ShepherdConfig::validate`]).
///
/// The returned table is the single source both `LayerSource` (the merge)
/// and `collect_dotted_keys` (the explicit-key provenance walk in
/// [`load_with_mode`]) read from -- neither ever reparses `contents`.
fn parse_layer(path: &Path, contents: &str, mode: LoadMode) -> ConfigResult<Map<String, Value>> {
    let origin = path.display().to_string();
    let mut table: Map<String, Value> = FileFormat::Toml
        .parse(Some(&origin), contents)
        .map_err(|error| sanitize_parse_error(&origin, error.as_ref()))?;

    // The retired-key registry is consulted in EVERY mode, not only during
    // migration.
    //
    // A key shepherd itself once wrote is not a typo, and refusing to load a
    // config because it still carries one is a deadlock: `shepherd.codex.toml`
    // in a real project retained the retired `spawn.max_concurrent_children`,
    // which made the config unloadable, which aborted `doctor`, `migrate` AND
    // `init` alike -- so every tool capable of repairing it was blocked by the
    // thing it repairs. Deprecation has to be possible without stranding the
    // documents already in the field.
    //
    // Typo protection is untouched, because the registry is a CLOSED, TYPED
    // set: each entry is verified against its historical type before it is
    // dropped, and any key that was never part of the schema still reaches the
    // strict decode and still produces the did-you-mean list.
    strip_retired_layout_v5(path, &mut table)?;
    let _ = mode;
    validate_gate_entries(path, &table)?;
    validate_open_bool_map(path, &table, "mcp")?;
    validate_open_bool_map(path, &table, "cli")?;

    Ok(table)
}

/// Fold every leaf key of an already-parsed layer table into `out` as a
/// fully dotted path (`"models.root"`, never bare `"root"`). Only a
/// [`Value`] that is itself a table recurses; a table with zero entries
/// therefore contributes nothing, which is correct -- an empty `[section]`
/// header configures no key.
fn collect_dotted_keys(table: &Map<String, Value>, prefix: &str, out: &mut BTreeSet<String>) {
    for (key, value) in table {
        let dotted = if prefix.is_empty() {
            key.clone()
        } else {
            alloc::format!("{prefix}.{key}")
        };
        match &value.kind {
            ValueKind::Table(nested) => collect_dotted_keys(nested, &dotted, out),
            _ => {
                out.insert(dotted);
            }
        }
    }
}

/// A `config::Source` over one already-parsed, already-validated layer
/// table. Parsing and the per-layer structural checks happen once, in
/// `parse_layer`, before a layer ever becomes a `LayerSource`; `collect`
/// here is therefore an infallible clone, never a second parse.
#[derive(Clone, Debug)]
struct LayerSource {
    table: Map<String, Value>,
}

impl LayerSource {
    fn new(table: Map<String, Value>) -> Self {
        Self { table }
    }
}

impl Source for LayerSource {
    fn clone_into_box(&self) -> Box<dyn Source + Send + Sync> {
        Box::new(self.clone())
    }

    fn collect(&self) -> ConfigResult<Map<String, Value>> {
        Ok(self.table.clone())
    }
}

fn as_table(value: &Value) -> Option<&Map<String, Value>> {
    match &value.kind {
        ValueKind::Table(table) => Some(table),
        _ => None,
    }
}

fn as_table_mut(value: &mut Value) -> Option<&mut Map<String, Value>> {
    match &mut value.kind {
        ValueKind::Table(table) => Some(table),
        _ => None,
    }
}

/// Rewrite a raw TOML parse failure into one message: the layer's own path
/// plus a sanitized, single-line description of the cause.
///
/// [`Format::parse`] returns a bare, type-erased `dyn Error` straight from
/// `toml`'s own parser, never `config`'s `ConfigError::FileParse` (that
/// variant is only ever produced by [`config::File`]). Its `Display` renders
/// a multi-line snippet of the offending source -- `"TOML parse error at
/// line 1, column 9"` followed by a `|`-gutter quote of the bad line -- so
/// only the first line, the parser's own positional summary, is ever safe to
/// surface. Anything past the first `\n` may echo another candidate's raw
/// source text, which must never leak into an error message.
fn sanitize_parse_error(
    origin: &str,
    error: &(dyn std::error::Error + Send + Sync),
) -> ConfigError {
    let rendered = error.to_string();
    let sanitized = rendered.lines().next().unwrap_or(&rendered).trim();
    ConfigError::Message(alloc::format!("{origin}: {sanitized}"))
}

fn config_error(path: &Path, key: &str, message: &str) -> ConfigError {
    ConfigError::Message(alloc::format!("{}: {key}: {message}", path.display()))
}

/// Remove and type-check the closed, typed set of layout-v5 retired keys.
///
/// Every removed key is verified against its historical type before it is
/// dropped, so a malformed legacy value still fails loudly instead of being
/// silently discarded.
fn strip_retired_layout_v5(path: &Path, root: &mut Map<String, Value>) -> ConfigResult {
    if let Some(paths) = root.get_mut("paths").and_then(as_table_mut) {
        remove_legacy_string(path, paths, "paths", "plans")?;
        remove_legacy_string(path, paths, "paths", "reports")?;
    }

    if let Some(memory) = root.remove("memory") {
        validate_retired_memory(path, &memory)?;
    }

    // Retired with the spawn-concurrency rework: the value was an integer cap
    // on concurrent children. Projects configured before its removal still
    // carry it, and it is what proved the deadlock described in `parse_layer`.
    if let Some(spawn) = root.get_mut("spawn").and_then(as_table_mut) {
        remove_legacy_integer(path, spawn, "spawn", "max_concurrent_children")?;
    }

    if let Some(context) = root.get_mut("context").and_then(as_table_mut) {
        remove_legacy_bool(path, context, "context", "enabled")?;
        for field in ["db_path", "lock_path", "project_id_path"] {
            remove_legacy_string(path, context, "context", field)?;
        }
        remove_legacy_string(path, context, "context", "announce_shctx_path")?;
    }
    Ok(())
}

/// Remove a retired integer key, verifying its historical type first so a
/// malformed legacy value still fails loudly instead of being discarded.
fn remove_legacy_integer(
    path: &Path,
    table: &mut Map<String, Value>,
    section: &str,
    field: &str,
) -> ConfigResult {
    let Some(value) = table.remove(field) else {
        return Ok(());
    };
    match value.kind {
        ValueKind::I64(_) | ValueKind::I128(_) | ValueKind::U64(_) | ValueKind::U128(_) => Ok(()),
        _ => Err(config_error(
            path,
            &alloc::format!("{section}.{field}"),
            "expected an integer",
        )),
    }
}

fn validate_retired_memory(path: &Path, memory: &Value) -> ConfigResult {
    let Some(memory) = as_table(memory) else {
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
        match memory.get(field).map(|value| &value.kind) {
            Some(ValueKind::String(_)) => {}
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
    table: &mut Map<String, Value>,
    section: &str,
    field: &str,
) -> ConfigResult {
    let Some(value) = table.remove(field) else {
        return Ok(());
    };
    if matches!(value.kind, ValueKind::String(_)) {
        Ok(())
    } else {
        Err(config_error(
            path,
            &alloc::format!("{section}.{field}"),
            "expected a string",
        ))
    }
}

fn remove_legacy_bool(
    path: &Path,
    table: &mut Map<String, Value>,
    section: &str,
    field: &str,
) -> ConfigResult {
    let Some(value) = table.remove(field) else {
        return Ok(());
    };
    if matches!(value.kind, ValueKind::Boolean(_)) {
        Ok(())
    } else {
        Err(config_error(
            path,
            &alloc::format!("{section}.{field}"),
            "expected a boolean",
        ))
    }
}

/// Validate the two supported `[gates.extra]` shapes before the typed schema
/// ever sees them: a string-keyed map of commands, or a list of
/// `{ name, cmd }` entries. This inspects `ValueKind` directly rather than
/// deserializing, so it is immune to `config::Value`'s loose scalar
/// coercions (see [`validate_open_bool_map`]).
fn validate_gate_entries(path: &Path, root: &Map<String, Value>) -> ConfigResult {
    let Some(extra) = root
        .get("gates")
        .and_then(as_table)
        .and_then(|gates| gates.get("extra"))
    else {
        return Ok(());
    };

    if let ValueKind::Table(map) = &extra.kind {
        for (name, command) in map {
            if !matches!(command.kind, ValueKind::String(_)) {
                return Err(config_error(
                    path,
                    &alloc::format!("gates.extra.{name}"),
                    "expected a string",
                ));
            }
        }
        return Ok(());
    }

    let ValueKind::Array(entries) = &extra.kind else {
        return Ok(());
    };

    for entry in entries {
        let ValueKind::Table(table) = &entry.kind else {
            continue;
        };
        for field in ["name", "cmd"] {
            let Some(value) = table.get(field) else {
                return Err(config_error(
                    path,
                    &alloc::format!("gates.extra.{field}"),
                    "required field is missing",
                ));
            };
            if !matches!(value.kind, ValueKind::String(_)) {
                return Err(config_error(
                    path,
                    &alloc::format!("gates.extra.{field}"),
                    "expected a string",
                ));
            }
        }
        for field in table.keys() {
            if field != "name" && field != "cmd" {
                return Err(config_error(
                    path,
                    &alloc::format!("gates.extra.{field}"),
                    "unknown key",
                ));
            }
        }
    }
    Ok(())
}

/// Reject a non-boolean value in an open, string-keyed boolean map (`[mcp]`,
/// `[cli]`) before the typed schema ever sees it.
///
/// `config::Value`'s scalar deserializer deliberately coerces strings like
/// `"yes"`/`"on"` and non-zero integers into `true` (the same leniency that
/// makes environment-variable sources usable), which the strict TOML-only
/// decode this loader replaces never did. These two fields are the only
/// dynamically-keyed booleans in the schema, so the fix is a direct
/// `ValueKind` check here rather than a coercion the whole crate must live
/// with.
fn validate_open_bool_map(path: &Path, root: &Map<String, Value>, section: &str) -> ConfigResult {
    let Some(entries) = root.get(section).and_then(as_table) else {
        return Ok(());
    };
    for (name, value) in entries {
        if !matches!(value.kind, ValueKind::Boolean(_)) {
            return Err(config_error(
                path,
                &alloc::format!("{section}.{name}"),
                "expected a boolean",
            ));
        }
    }
    Ok(())
}

fn deserialize_merged(path: &Path, value: SourceConfig) -> Result<ShepherdConfig> {
    let config = value
        .try_deserialize::<ShepherdConfig>()
        .map_err(|error| deserialize_error(path, &error))?;
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

/// Build a path- and dotted-key-qualified message from a `config::ConfigError`
/// raised while decoding the merged (or single-candidate) configuration.
///
/// `config::Value`'s origin is only ever populated on `ConfigError::Type`
/// (scalar type mismatches; see [`LayerSource::collect`] for how origin gets
/// there in the first place). A `deny_unknown_fields` rejection never carries
/// an origin -- it is raised while matching a field *identifier*, one level
/// below where any value (and its origin) exists -- so this always falls
/// back to the externally known candidate path in that case.
fn deserialize_error(path: &Path, error: &ConfigError) -> Error {
    let (key, origin, message) = describe_config_error(error);
    let origin = origin.unwrap_or_else(|| path.display().to_string());
    match key {
        Some(key) => Error::config(alloc::format!("{origin}: {key}: {message}")),
        None => Error::config(alloc::format!("{origin}: {message}")),
    }
}

/// Walk a `config::ConfigError`, extracting the fully-qualified dotted key
/// (if any), the most specific known origin, and a message that never
/// echoes another candidate's content.
///
/// `config`'s own `prepend_key` only ever wraps a foreign error into `At`
/// once per accumulation (each further `prepend_key` call just extends the
/// existing `key` string with a `.segment`), so this never needs to unwrap
/// more than the one `At` layer `config` itself produces; the recursion below
/// is simply the general, defensive shape of that fact.
fn describe_config_error(error: &ConfigError) -> (Option<String>, Option<String>, String) {
    match error {
        ConfigError::Type {
            origin,
            unexpected,
            expected,
            key,
        } => (
            key.clone(),
            origin.clone(),
            alloc::format!("invalid type: {unexpected}, expected {expected}"),
        ),
        ConfigError::At { error, origin, key } => {
            let (inner_key, inner_origin, message) = describe_config_error(error);
            let combined_key = match (key.as_deref(), inner_key) {
                (Some(outer), Some(inner)) => Some(alloc::format!("{outer}.{inner}")),
                (Some(outer), None) => Some(outer.to_string()),
                (None, inner) => inner,
            };
            (combined_key, origin.clone().or(inner_origin), message)
        }
        ConfigError::Message(message) => {
            // `deny_unknown_fields` raises exactly this shape (see
            // `serde_core::de::Error::unknown_field`'s default
            // implementation); extracting the field name here is what lets
            // an unknown nested field still resolve to a full dotted key
            // once its enclosing `At` wrapper is unwound above.
            let field = message
                .strip_prefix("unknown field `")
                .and_then(|rest| rest.split_once('`'))
                .map(|(field, _)| field.to_string());
            (field, None, message.clone())
        }
        ConfigError::NotFound(key) => (
            Some(key.clone()),
            None,
            "missing configuration field".to_string(),
        ),
        other => (None, None, other.to_string()),
    }
}

/// Render the complete schema as deterministic compact JSON.
#[cfg(all(feature = "schema", feature = "json"))]
pub fn schema_json() -> Result<String> {
    serde_json::to_string(&schemars::schema_for!(ShepherdConfig))
        .map_err(|error| Error::Serialization(error.to_string()))
}
