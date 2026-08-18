/*
    Appellation: execution-context <module>
    Created At: 2026.08.14
    Contrib: @FL03
*/
//! Filesystem, environment, git, clock, identifier, and stdio discovery.
//!
//! The core receives only already-read configuration layers. This module is
//! the single host boundary that turns ambient machine state into one explicit
//! value shared by every command.

use std::{
    collections::BTreeSet,
    env,
    ffi::{OsStr, OsString},
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
    process::Command,
    str::FromStr,
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};

use shepherd::{
    Harness, ShepherdConfig,
    loader::{self, ConfigContext, ConfigSource},
};

/// Stable CLI output selection.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum OutputFormat {
    #[default]
    Text,
    Json,
}

/// Host facts supplied before context resolution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextInputs {
    pub start_dir: PathBuf,
    pub primary_fallback: Option<PathBuf>,
    pub shepherd_home: Option<PathBuf>,
    pub home_dir: Option<PathBuf>,
    pub active_harness: Option<Harness>,
    pub explicit_config: Option<PathBuf>,
    pub output_format: OutputFormat,
    pub verbosity: u8,
}

impl Default for ContextInputs {
    fn default() -> Self {
        Self {
            start_dir: PathBuf::from("."),
            primary_fallback: None,
            shepherd_home: None,
            home_dir: None,
            active_harness: None,
            explicit_config: None,
            output_format: OutputFormat::Text,
            verbosity: 0,
        }
    }
}

impl ContextInputs {
    /// Read supported host inputs without creating a directory.
    pub fn from_environment(start_dir: impl Into<PathBuf>) -> Result<Self, ContextError> {
        Self::from_environment_with(start_dir, &SystemEnvironment)
    }

    /// Read host inputs through an injectable environment boundary.
    pub fn from_environment_with(
        start_dir: impl Into<PathBuf>,
        environment: &dyn ContextEnvironment,
    ) -> Result<Self, ContextError> {
        let shepherd_home = environment_path(environment, "SHEPHERD_HOME");
        let home_dir = environment_path(environment, "HOME");
        let active_harness = resolve_environment_harness(environment)?;
        Ok(Self {
            start_dir: start_dir.into(),
            shepherd_home,
            home_dir,
            active_harness,
            ..Self::default()
        })
    }
}

/// Read-only environment operations required during host discovery.
pub trait ContextEnvironment {
    fn var_os(&self, key: &OsStr) -> Option<OsString>;
}

/// Production environment implementation. It never mutates process state.
#[derive(Clone, Copy, Debug, Default)]
pub struct SystemEnvironment;

impl ContextEnvironment for SystemEnvironment {
    fn var_os(&self, key: &OsStr) -> Option<OsString> {
        env::var_os(key)
    }
}

/// Injectable wall clock.
pub trait Clock: Send + Sync + core::fmt::Debug {
    fn now_unix_millis(&self) -> i64;
}

/// Injectable identifier sequence.
pub trait IdentifierSource: Send + core::fmt::Debug {
    fn next_id(&mut self) -> String;
}

/// Injectable command I/O boundary.
pub trait IoBoundary: Send + core::fmt::Debug {
    fn read_stdin(&mut self, buffer: &mut String) -> io::Result<usize>;
    fn write_stdout(&mut self, bytes: &[u8]) -> io::Result<()>;
    fn write_stderr(&mut self, bytes: &[u8]) -> io::Result<()>;
}

/// Nondeterministic runtime sources carried by [`ExecutionContext`].
#[derive(Debug)]
pub struct RuntimeBindings {
    clock: Box<dyn Clock>,
    identifiers: Box<dyn IdentifierSource>,
    io: Box<dyn IoBoundary>,
}

impl RuntimeBindings {
    pub fn new(
        clock: Box<dyn Clock>,
        identifiers: Box<dyn IdentifierSource>,
        io: Box<dyn IoBoundary>,
    ) -> Self {
        Self {
            clock,
            identifiers,
            io,
        }
    }

    pub fn system() -> Self {
        Self::new(
            Box::new(SystemClock),
            Box::new(SystemIdentifiers),
            Box::new(SystemIo),
        )
    }
}

/// Filesystem and git operations required during resolution.
pub trait ContextHost {
    fn canonicalize(&self, path: &Path) -> io::Result<PathBuf>;
    fn git_rev_parse(&self, cwd: &Path, argument: &str) -> io::Result<PathBuf>;
    fn read_optional(&self, path: &Path) -> io::Result<Option<String>>;

    /// Inspect a path without following its final symlink component.
    ///
    /// The default is the production implementation. Test hosts can keep
    /// implementing only the older discovery methods while still receiving
    /// the fail-closed symlink check.
    fn symlink_metadata(&self, path: &Path) -> io::Result<fs::Metadata> {
        fs::symlink_metadata(path)
    }
}

/// Production host implementation. It never writes.
#[derive(Clone, Copy, Debug, Default)]
pub struct SystemHost;

impl ContextHost for SystemHost {
    fn canonicalize(&self, path: &Path) -> io::Result<PathBuf> {
        fs::canonicalize(path)
    }

    fn git_rev_parse(&self, cwd: &Path, argument: &str) -> io::Result<PathBuf> {
        let output = Command::new("git")
            .current_dir(cwd)
            .args(["rev-parse", "--path-format=absolute", argument])
            .output()?;
        if !output.status.success() {
            return Err(io::Error::other(
                "git rev-parse did not resolve a repository",
            ));
        }
        let value = String::from_utf8(output.stdout)
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "git returned non-UTF-8"))?;
        let value = value.trim();
        if value.is_empty() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "git returned an empty path",
            ));
        }
        Ok(PathBuf::from(value))
    }

    fn read_optional(&self, path: &Path) -> io::Result<Option<String>> {
        match fs::read_to_string(path) {
            Ok(contents) => Ok(Some(contents)),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error),
        }
    }
}

/// Context resolution failure.
#[derive(Debug, thiserror::Error)]
pub enum ContextError {
    #[error("SHEPHERD_HARNESS must name a supported harness")]
    InvalidHarness,
    #[error("cannot resolve primary repository root: {0}")]
    Primary(String),
    #[error("cannot read configuration candidate {path}: {source}")]
    ReadConfig {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("configuration candidate is not canonical: {0}")]
    NonCanonicalCandidate(PathBuf),
    #[error("explicit configuration path is not a canonical shepherd candidate: {0}")]
    NonCanonicalConfig(PathBuf),
    #[error("explicit configuration candidate does not exist: {0}")]
    MissingExplicitConfig(PathBuf),
    #[error("cannot resolve explicit configuration candidate {path}: {source}")]
    ResolveExplicitConfig {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("cannot resolve shepherd user home {path}: {source}")]
    ResolveUserHome {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("shepherd user home must not overlap the project namespace")]
    UserHomeOverlap,
    #[error("{key}: resolved project path is not canonical: {path}")]
    NonCanonicalProjectPath { key: &'static str, path: PathBuf },
    #[error("cannot resolve {key} project path {path}: {source}")]
    ResolveProjectPath {
        key: &'static str,
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error(transparent)]
    Config(#[from] shepherd::Error),
}

fn resolve_environment_harness(
    environment: &dyn ContextEnvironment,
) -> Result<Option<Harness>, ContextError> {
    if let Some(raw) = environment.var_os(OsStr::new("SHEPHERD_HARNESS"))
        && !raw.is_empty()
    {
        let value = raw.to_str().ok_or(ContextError::InvalidHarness)?.trim();
        if !value.is_empty() {
            return Harness::from_str(value)
                .map(Some)
                .map_err(|_| ContextError::InvalidHarness);
        }
    }
    if environment_value_is_present(environment, "CLAUDECODE")
        || environment_value_is_present(environment, "CLAUDE_PLUGIN_ROOT")
    {
        return Ok(Some(Harness::ClaudeCode));
    }
    if environment_value_is_present(environment, "CODEX_HOME") {
        return Ok(Some(Harness::Codex));
    }
    Ok(None)
}

fn environment_value_is_present(environment: &dyn ContextEnvironment, key: &str) -> bool {
    environment
        .var_os(OsStr::new(key))
        .is_some_and(|value| !value.is_empty())
}

fn environment_path(environment: &dyn ContextEnvironment, key: &str) -> Option<PathBuf> {
    environment
        .var_os(OsStr::new(key))
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
}

/// All resolved machine facts required by CLI commands.
pub struct ExecutionContext {
    pub primary_root: PathBuf,
    pub namespace: PathBuf,
    pub docs_root: PathBuf,
    pub ctx_root: PathBuf,
    pub runs_root: PathBuf,
    pub registry_path: PathBuf,
    pub registry_lock_path: PathBuf,
    pub project_id_path: PathBuf,
    pub dups_registry_path: PathBuf,
    pub user_home: Option<PathBuf>,
    pub active_harness: Option<Harness>,
    pub explicit_config: Option<PathBuf>,
    pub config: ShepherdConfig,
    pub config_sources: Vec<ConfigSource>,
    /// Dotted keys (e.g. `"models.root"`) some merged config layer set
    /// explicitly. Carried straight from
    /// [`shepherd_core::loader::LoadedConfig::explicit_keys`] so a caller can
    /// tell "a layer set this key" from "the merged value happens to equal
    /// the default" without re-reading or re-parsing any configuration file.
    pub explicit_keys: BTreeSet<String>,
    pub output_format: OutputFormat,
    pub verbosity: u8,
    runtime: RuntimeBindings,
}

impl core::fmt::Debug for ExecutionContext {
    fn fmt(&self, formatter: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        formatter
            .debug_struct("ExecutionContext")
            .field("primary_root", &self.primary_root)
            .field("namespace", &self.namespace)
            .field("user_home", &self.user_home)
            .field("active_harness", &self.active_harness)
            .field("explicit_config", &self.explicit_config)
            .field("config_sources", &self.config_sources)
            .field("explicit_keys", &self.explicit_keys)
            .field("output_format", &self.output_format)
            .field("verbosity", &self.verbosity)
            .finish_non_exhaustive()
    }
}

impl ExecutionContext {
    /// Resolve using production host and runtime boundaries.
    pub fn discover(inputs: ContextInputs) -> Result<Self, ContextError> {
        Self::resolve_with(inputs, &SystemHost, RuntimeBindings::system())
    }

    /// Resolve only for a layout-v5 migration.
    ///
    /// The migration has to read the retired fields it will remove. Every
    /// regular command remains on [`Self::discover`] and therefore rejects
    /// them through the ordinary strict loader.
    pub fn discover_for_layout_v5_migration(inputs: ContextInputs) -> Result<Self, ContextError> {
        Self::resolve_with_loader(inputs, &SystemHost, RuntimeBindings::system(), true)
    }

    /// Resolve with every nondeterministic operation injected.
    pub fn resolve_with(
        inputs: ContextInputs,
        host: &dyn ContextHost,
        runtime: RuntimeBindings,
    ) -> Result<Self, ContextError> {
        Self::resolve_with_loader(inputs, host, runtime, false)
    }

    fn resolve_with_loader(
        inputs: ContextInputs,
        host: &dyn ContextHost,
        runtime: RuntimeBindings,
        layout_v5_migration: bool,
    ) -> Result<Self, ContextError> {
        let primary_root = resolve_primary(&inputs, host)?;
        let user_home = resolve_user_home(&inputs, &primary_root, host)?;
        let config_context = ConfigContext {
            primary_root: primary_root.clone(),
            user_home: user_home.clone(),
            harness: inputs.active_harness,
        };
        let candidates = loader::candidates(&config_context);
        let explicit_requested = inputs.explicit_config.as_ref().map(|path| {
            if path.is_absolute() {
                path.clone()
            } else {
                primary_root.join(path)
            }
        });

        let explicit_config = if let Some(explicit) = explicit_requested {
            if !candidates
                .iter()
                .any(|candidate| candidate.path == explicit)
            {
                return Err(ContextError::NonCanonicalConfig(explicit));
            }
            let resolved = match host.canonicalize(&explicit) {
                Ok(resolved) => resolved,
                Err(error) if error.kind() == io::ErrorKind::NotFound => {
                    return Err(ContextError::MissingExplicitConfig(explicit));
                }
                Err(source) => {
                    return Err(ContextError::ResolveExplicitConfig {
                        path: explicit,
                        source,
                    });
                }
            };
            if resolved != explicit {
                return Err(ContextError::NonCanonicalCandidate(explicit));
            }
            Some(resolved)
        } else {
            None
        };

        let selected: Vec<PathBuf> = if let Some(explicit) = &explicit_config {
            vec![explicit.clone()]
        } else {
            candidates
                .into_iter()
                .map(|candidate| candidate.path)
                .collect()
        };

        let mut contents = Vec::new();
        for path in selected {
            let canonical = match host.canonicalize(&path) {
                Ok(canonical) if canonical == path => Some(canonical),
                Ok(_) => return Err(ContextError::NonCanonicalCandidate(path)),
                Err(error) if error.kind() == io::ErrorKind::NotFound => None,
                Err(source) => {
                    return Err(ContextError::ReadConfig {
                        path: path.clone(),
                        source,
                    });
                }
            };
            let Some(canonical) = canonical else {
                if explicit_config.is_some() {
                    return Err(ContextError::MissingExplicitConfig(path));
                }
                continue;
            };
            match host
                .read_optional(&canonical)
                .map_err(|source| ContextError::ReadConfig {
                    path: canonical.clone(),
                    source,
                })? {
                Some(contents_value) => contents.push((canonical, contents_value)),
                None if explicit_config.is_some() => {
                    return Err(ContextError::MissingExplicitConfig(canonical));
                }
                None => {}
            }
        }

        let layers = contents
            .iter()
            .map(|(path, contents)| (path.as_path(), contents.as_str()));
        let loaded = if layout_v5_migration {
            loader::load_for_layout_v5_migration(layers)?
        } else {
            loader::load(layers)?
        };
        let paths = loaded.config.resolve_paths(&primary_root)?;
        validate_resolved_project_paths(host, &paths)?;

        Ok(Self {
            primary_root,
            namespace: paths.namespace,
            docs_root: paths.docs,
            ctx_root: paths.ctx,
            runs_root: paths.runs,
            registry_path: paths.registry,
            registry_lock_path: paths.registry_lock,
            project_id_path: paths.project_id,
            dups_registry_path: paths.dups_registry,
            user_home,
            active_harness: inputs.active_harness,
            explicit_config,
            config: loaded.config,
            config_sources: loaded.sources,
            explicit_keys: loaded.explicit_keys,
            output_format: inputs.output_format,
            verbosity: inputs.verbosity,
            runtime,
        })
    }

    pub fn now_unix_millis(&self) -> i64 {
        self.runtime.clock.now_unix_millis()
    }

    pub fn next_id(&mut self) -> String {
        self.runtime.identifiers.next_id()
    }

    pub fn read_stdin(&mut self, buffer: &mut String) -> io::Result<usize> {
        self.runtime.io.read_stdin(buffer)
    }

    pub fn write_stdout(&mut self, bytes: &[u8]) -> io::Result<()> {
        self.runtime.io.write_stdout(bytes)
    }

    pub fn write_stderr(&mut self, bytes: &[u8]) -> io::Result<()> {
        self.runtime.io.write_stderr(bytes)
    }
}

fn validate_resolved_project_paths(
    host: &dyn ContextHost,
    paths: &shepherd::settings::ResolvedPaths,
) -> Result<(), ContextError> {
    for (key, path) in [
        ("namespace", paths.namespace.as_path()),
        ("paths.docs", paths.docs.as_path()),
        ("paths.ctx", paths.ctx.as_path()),
        ("paths.runs", paths.runs.as_path()),
        ("registry", paths.registry.as_path()),
        ("registry_lock", paths.registry_lock.as_path()),
        ("project_id", paths.project_id.as_path()),
        ("dups.dups_registry", paths.dups_registry.as_path()),
    ] {
        let file_allowed = matches!(
            key,
            "registry" | "registry_lock" | "project_id" | "dups.dups_registry"
        );
        validate_resolved_project_path(host, &paths.namespace, key, path, file_allowed)?;
    }
    Ok(())
}

fn validate_resolved_project_path(
    host: &dyn ContextHost,
    namespace: &Path,
    key: &'static str,
    path: &Path,
    file_allowed: bool,
) -> Result<(), ContextError> {
    if !path.starts_with(namespace) {
        return Err(ContextError::NonCanonicalProjectPath {
            key,
            path: path.to_path_buf(),
        });
    }

    let mut current = path;
    loop {
        match host.symlink_metadata(current) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err(ContextError::NonCanonicalProjectPath {
                    key,
                    path: path.to_path_buf(),
                });
            }
            Ok(metadata) if (!file_allowed || current != path) && !metadata.is_dir() => {
                return Err(ContextError::NonCanonicalProjectPath {
                    key,
                    path: path.to_path_buf(),
                });
            }
            Ok(_) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(source) => {
                return Err(ContextError::ResolveProjectPath {
                    key,
                    path: path.to_path_buf(),
                    source,
                });
            }
        }
        match host.canonicalize(current) {
            Ok(canonical) if canonical == current => return Ok(()),
            Ok(_) => {
                return Err(ContextError::NonCanonicalProjectPath {
                    key,
                    path: path.to_path_buf(),
                });
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                if current == namespace {
                    return Ok(());
                }
                current =
                    current
                        .parent()
                        .ok_or_else(|| ContextError::NonCanonicalProjectPath {
                            key,
                            path: path.to_path_buf(),
                        })?;
            }
            Err(source) => {
                return Err(ContextError::ResolveProjectPath {
                    key,
                    path: path.to_path_buf(),
                    source,
                });
            }
        }
    }
}

fn resolve_primary(
    inputs: &ContextInputs,
    host: &dyn ContextHost,
) -> Result<PathBuf, ContextError> {
    let git = (|| {
        let top = host.git_rev_parse(&inputs.start_dir, "--show-toplevel")?;
        let common = host.git_rev_parse(&inputs.start_dir, "--git-common-dir")?;
        let common = host.canonicalize(&common)?;
        let git_dir = host.git_rev_parse(&inputs.start_dir, "--git-dir")?;
        let git_dir = host.canonicalize(&git_dir)?;
        let primary = if git_dir == common {
            top
        } else if common.file_name().is_some_and(|name| name == ".git") {
            common.parent().map(Path::to_path_buf).unwrap_or(top)
        } else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "linked worktree common directory cannot identify the primary checkout; provide an explicit primary fallback",
            ));
        };
        host.canonicalize(&primary)
    })();

    match (git, &inputs.primary_fallback) {
        (Ok(primary), _) => Ok(primary),
        (Err(_), Some(fallback)) => host
            .canonicalize(fallback)
            .map_err(|error| ContextError::Primary(error.to_string())),
        (Err(error), None) => Err(ContextError::Primary(error.to_string())),
    }
}

fn resolve_user_home(
    inputs: &ContextInputs,
    primary_root: &Path,
    host: &dyn ContextHost,
) -> Result<Option<PathBuf>, ContextError> {
    let raw = inputs
        .shepherd_home
        .clone()
        .or_else(|| inputs.home_dir.as_ref().map(|home| home.join(".shepherd")));
    let Some(raw) = raw else {
        return Ok(None);
    };
    let path = if raw.is_absolute() {
        raw
    } else {
        primary_root.join(raw)
    };
    let resolved = match host.canonicalize(&path) {
        Ok(canonical) => canonical,
        Err(error) if error.kind() == io::ErrorKind::NotFound => path,
        Err(source) => return Err(ContextError::ResolveUserHome { path, source }),
    };
    let namespace = primary_root.join(".shepherd");
    if resolved.starts_with(&namespace) || namespace.starts_with(&resolved) {
        return Err(ContextError::UserHomeOverlap);
    }
    Ok(Some(resolved))
}

#[derive(Debug)]
struct SystemClock;

impl Clock for SystemClock {
    fn now_unix_millis(&self) -> i64 {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        i64::try_from(millis).unwrap_or(i64::MAX)
    }
}

#[derive(Debug)]
struct SystemIdentifiers;

impl IdentifierSource for SystemIdentifiers {
    fn next_id(&mut self) -> String {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let ordinal = NEXT.fetch_add(1, Ordering::Relaxed);
        format!("{}-{ordinal}", std::process::id())
    }
}

#[derive(Debug)]
struct SystemIo;

impl IoBoundary for SystemIo {
    fn read_stdin(&mut self, buffer: &mut String) -> io::Result<usize> {
        io::stdin().read_line(buffer)
    }

    fn write_stdout(&mut self, bytes: &[u8]) -> io::Result<()> {
        let mut stdout = io::stdout().lock();
        stdout.write_all(bytes)?;
        stdout.flush()
    }

    fn write_stderr(&mut self, bytes: &[u8]) -> io::Result<()> {
        let mut stderr = io::stderr().lock();
        stderr.write_all(bytes)?;
        stderr.flush()
    }
}
