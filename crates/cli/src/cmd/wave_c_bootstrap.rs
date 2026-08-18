//! Native layout-v5 project and user-home bootstrap commands.
//!
//! Legacy bootstrap installed environments and wrote retired namespace roots.
//! The canonical CLI owns only typed layout-v5 roots.

use std::path::{Path, PathBuf};

use shepherd::{
    dispatch::ProjectId,
    registry::{OpenMode, Registry},
    settings::ShepherdConfig,
};

use crate::{
    ContextInputs, ExecutionContext,
    interface::{CliError, CliGlobals},
};

const PROJECT_DIRECTORIES: &[&str] = &["docs", "ctx", "runs"];
// The user tier owns only direct `shepherd*.toml` candidates. Project-owned
// templates live under `.shepherd/templates`; there is no user-template or
// filesystem-style-profile resolver in the native runtime.
const HOME_DIRECTORIES: &[&str] = &[];
const CONFIG_FILE: &str = "shepherd.toml";
// The two identity-bearing artifacts `init` owns, relative to `primary_root`.
const PROJECT_CONFIG_RELATIVE: &str = ".shepherd/shepherd.toml";
const PROJECT_IDENTITY_RELATIVE: &str = ".shepherd/project.json";
const MAX_PROJECT_IDENTITY_BYTES: usize = 65_536;

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Args,
    serde::Deserialize,
    serde::Serialize,
)]
pub struct WaveCInitCmd {
    /// Do not create the canonical project configuration document.
    #[arg(long)]
    pub no_config: bool,
    /// Do not run the read-only native health check after initialization.
    #[arg(long)]
    pub no_doctor: bool,
    /// Also initialize the separately-owned Shepherd user home.
    #[arg(long)]
    pub user: bool,
    /// Authorize filesystem mutation. Without it, init fails closed.
    #[arg(long)]
    pub confirm: bool,
}

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Args,
    serde::Deserialize,
    serde::Serialize,
)]
#[command(disable_help_subcommand = true)]
pub struct WaveCConfigCmd {
    #[command(subcommand)]
    action: Option<ConfigAction>,
}

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Subcommand,
    serde::Deserialize,
    serde::Serialize,
)]
enum ConfigAction {
    /// Print the canonical project configuration write path.
    Path,
    /// Print the fully resolved typed configuration.
    Show,
    /// Read one dotted key from the resolved typed configuration.
    Get { key: String },
    /// Create the canonical project configuration if it is absent.
    Init {
        /// Authorize the configuration write.
        #[arg(long)]
        confirm: bool,
    },
}

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Args,
    serde::Deserialize,
    serde::Serialize,
)]
#[command(disable_help_subcommand = true)]
pub struct WaveCHomeCmd {
    #[command(subcommand)]
    action: Option<HomeAction>,
}

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Subcommand,
    serde::Deserialize,
    serde::Serialize,
)]
enum HomeAction {
    /// Print the resolved user-home namespace path.
    Which,
    /// Describe the resolved user-home namespace without mutation.
    Show,
    /// Create the canonical user-home directories.
    Init {
        /// Authorize the user-home mutation.
        #[arg(long)]
        confirm: bool,
    },
}

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Args,
    serde::Deserialize,
    serde::Serialize,
)]
pub struct WaveCDoctorCmd {
    /// Emit one structured health report.
    #[arg(long)]
    json: bool,
}

impl WaveCInitCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        if !self.confirm {
            return Err(CliError::message_with_code(
                "init is mutating; re-run with --confirm",
                2,
            ));
        }
        let mut context = context(globals)?;
        initialize_project(&context, !self.no_config)?;
        if self.user {
            initialize_home(&context)?;
        }
        let report = health_report(&context);
        if !self.no_doctor && !report.ok {
            write(&mut context, report.render_text())?;
            return Err(CliError::reported_with_code(3));
        }
        let output = format!(
            "initialized layout-v5 namespace: {}\nregistry: {}",
            context.namespace.display(),
            context.registry_path.display()
        );
        write(&mut context, output)
    }
}
impl WaveCConfigCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        match self.action {
            Some(ConfigAction::Path) => {
                let output = config_path(&context).display().to_string();
                write(&mut context, output)
            }
            Some(ConfigAction::Show) => {
                let text = serde_json::to_string_pretty(&context.config).map_err(|error| {
                    CliError::message(format!("cannot encode typed config: {error}"))
                })?;
                write(&mut context, text)
            }
            Some(ConfigAction::Get { key }) => {
                let output = typed_config_value(&context.config, &key)?;
                write(&mut context, output)
            }
            Some(ConfigAction::Init { confirm }) => {
                if !confirm {
                    return Err(CliError::message_with_code(
                        "config init is mutating; re-run with --confirm",
                        2,
                    ));
                }
                initialize_project_config(&context)?;
                let output = format!("initialized config: {}", config_path(&context).display());
                write(&mut context, output)
            }
            None => write(&mut context, "shepherd config <path|show|get|init>".into()),
        }
    }
}
impl WaveCHomeCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let home = required_user_home(&context)?.to_path_buf();
        match self.action {
            Some(HomeAction::Which) => write(&mut context, home.display().to_string()),
            Some(HomeAction::Show) => write(&mut context, format!("home: {}", home.display())),
            Some(HomeAction::Init { confirm }) => {
                if !confirm {
                    return Err(CliError::message_with_code(
                        "home init is mutating; re-run with --confirm",
                        2,
                    ));
                }
                initialize_home(&context)?;
                write(
                    &mut context,
                    format!("initialized shepherd home: {}", home.display()),
                )
            }
            None => write(&mut context, "shepherd home <which|show|init>".into()),
        }
    }
}
impl WaveCDoctorCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let report = health_report(&context);
        if self.json {
            let text = serde_json::to_string_pretty(&report).map_err(|error| {
                CliError::message(format!("cannot encode doctor report: {error}"))
            })?;
            write(&mut context, text)?;
        } else {
            write(&mut context, report.render_text())?;
        }
        if report.ok {
            Ok(())
        } else {
            Err(CliError::reported_with_code(3))
        }
    }
}
fn context(globals: CliGlobals) -> Result<ExecutionContext, CliError> {
    let cwd = std::env::current_dir().map_err(|error| CliError::message(error.to_string()))?;
    let mut inputs = ContextInputs::from_environment(cwd)
        .map_err(|error| CliError::message(error.to_string()))?;
    inputs.explicit_config = globals.config;
    inputs.verbosity = globals.verbosity;
    ExecutionContext::discover(inputs).map_err(|error| CliError::message(error.to_string()))
}

fn config_path(context: &ExecutionContext) -> PathBuf {
    context.namespace.join(CONFIG_FILE)
}

fn required_user_home(context: &ExecutionContext) -> Result<&Path, CliError> {
    context.user_home.as_deref().ok_or_else(|| {
        CliError::message_with_code(
            "cannot resolve shepherd user home; set SHEPHERD_HOME or HOME",
            2,
        )
    })
}

/// One filesystem artifact this invocation of `init` created, in creation
/// order. Rollback only ever unwinds artifacts recorded here: an artifact
/// that already existed before this call is never pushed, and so can never
/// be deleted by a failed run.
enum ScaffoldArtifact {
    Directory(String),
    File(String),
    /// The typed registry (`shepherd.db`, plus its `-wal`/`-shm` siblings).
    Registry,
}

struct Scaffold {
    primary_root: PathBuf,
    created: Vec<ScaffoldArtifact>,
}

impl Scaffold {
    fn new(primary_root: &Path) -> Self {
        Self {
            primary_root: primary_root.to_path_buf(),
            created: Vec::new(),
        }
    }

    fn record_directory(&mut self, relative: String) {
        self.created.push(ScaffoldArtifact::Directory(relative));
    }

    fn record_file(&mut self, relative: String) {
        self.created.push(ScaffoldArtifact::File(relative));
    }

    fn record_registry(&mut self) {
        self.created.push(ScaffoldArtifact::Registry);
    }

    /// Best-effort unwind of exactly what this invocation created, in
    /// reverse creation order. Never touches an artifact this invocation
    /// did not itself create; a pre-existing user artifact is never in
    /// `created` in the first place.
    fn rollback(&self) {
        for artifact in self.created.iter().rev() {
            match artifact {
                ScaffoldArtifact::File(relative) => {
                    let _ = remove_file_no_follow(&self.primary_root, relative);
                }
                ScaffoldArtifact::Registry => {
                    let _ = remove_file_no_follow(&self.primary_root, ".shepherd/shepherd.db");
                    let _ = remove_file_no_follow(&self.primary_root, ".shepherd/shepherd.db-wal");
                    let _ = remove_file_no_follow(&self.primary_root, ".shepherd/shepherd.db-shm");
                }
                ScaffoldArtifact::Directory(relative) => {
                    let _ = remove_directory_no_follow(&self.primary_root, relative);
                }
            }
        }
    }
}

fn initialize_project(context: &ExecutionContext, write_config: bool) -> Result<(), CliError> {
    let mut scaffold = Scaffold::new(&context.primary_root);
    match scaffold_project(context, write_config, &mut scaffold) {
        Ok(()) => Ok(()),
        Err(error) => {
            scaffold.rollback();
            Err(error)
        }
    }
}

/// Create only what is missing, register identity, and never clobber or
/// silently resolve a conflict. On success every artifact `init` needs to
/// dispatch — the directory tree, `shepherd.toml`, `shepherd.db`,
/// `project.json`, and the matching `projects` row — exists and agrees.
fn scaffold_project(
    context: &ExecutionContext,
    write_config: bool,
    scaffold: &mut Scaffold,
) -> Result<(), CliError> {
    for relative in ensure_directory_tree(&context.primary_root, ".shepherd", PROJECT_DIRECTORIES)?
    {
        scaffold.record_directory(relative);
    }
    if write_config && initialize_project_config(context)? {
        scaffold.record_file(PROJECT_CONFIG_RELATIVE.to_owned());
    }
    // `Registry::open_migrated` gives no signal of its own for "did this call
    // create the file". `crates/registry/src/**` is out of this lane's scope,
    // so this pre-check is the only source of that fact; the registry crate
    // still performs its own symlink-safe open underneath it.
    let registry_existed = context.registry_path.is_file();
    let registry = Registry::open_migrated(&context.registry_path)
        .map_err(|error| CliError::message(format!("cannot initialize typed registry: {error}")))?;
    if !registry_existed {
        scaffold.record_registry();
    }
    let project_id = resolve_project_identity(context, scaffold)?;
    register_project(&registry, &project_id)
}

fn initialize_project_config(context: &ExecutionContext) -> Result<bool, CliError> {
    // An empty document is valid: the one typed schema loader materializes
    // every default, without a copied default table drifting from the schema.
    let contents = b"# Shepherd layout-v5 project configuration.\n# Defaults are supplied by the typed schema.\n";
    write_no_clobber(&context.primary_root, PROJECT_CONFIG_RELATIVE, contents)
}

/// Publish a fresh project identity, or heal by reading back whatever
/// already answers that name. Never overwrites, and never silently prefers
/// a freshly generated id over one that was already on disk.
fn resolve_project_identity(
    context: &ExecutionContext,
    scaffold: &mut Scaffold,
) -> Result<ProjectId, CliError> {
    let candidate_id = ProjectId::new(uuid::Uuid::now_v7().to_string())
        .expect("a freshly minted uuid v7 is always a valid project id");
    let document = serde_json::json!({
        "id": candidate_id.as_str(),
        "scaffolded_at": now_seconds(),
    });
    let bytes = serde_json::to_vec(&document)
        .map_err(|error| CliError::message(format!("cannot encode project identity: {error}")))?;
    let published = write_no_clobber(&context.primary_root, PROJECT_IDENTITY_RELATIVE, &bytes)?;
    if published {
        scaffold.record_file(PROJECT_IDENTITY_RELATIVE.to_owned());
        return Ok(candidate_id);
    }
    // Something already answers `project.json`. Read it back rather than
    // discarding or replacing it — this is the one healing path the product
    // has, and it never mutates what it finds.
    match descriptor::read_relative_nofollow(
        &context.primary_root,
        PROJECT_IDENTITY_RELATIVE,
        MAX_PROJECT_IDENTITY_BYTES,
    )? {
        descriptor::Lookup::Regular(existing) => parse_project_identity(&existing),
        descriptor::Lookup::Missing => Err(CliError::message(format!(
            "project identity vanished during initialization: {PROJECT_IDENTITY_RELATIVE}"
        ))),
        descriptor::Lookup::NotRegular => Err(CliError::message(format!(
            "project identity is not a regular file: {PROJECT_IDENTITY_RELATIVE}"
        ))),
    }
}

fn parse_project_identity(bytes: &[u8]) -> Result<ProjectId, CliError> {
    let document: serde_json::Value = serde_json::from_slice(bytes).map_err(|error| {
        CliError::message(format!("invalid project identity document: {error}"))
    })?;
    let id = document
        .as_object()
        .and_then(|object| object.get("id"))
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| {
            CliError::message("invalid project identity document: field `id` must be a string")
        })?;
    ProjectId::new(id).map_err(|error| CliError::message(error.to_string()))
}

/// Register `project_id` in the `projects` table, or verify it already is.
/// A namespace whose file and row disagree is rejected loudly: it is never
/// resolved by preferring the file or the row.
fn register_project(registry: &Registry, project_id: &ProjectId) -> Result<(), CliError> {
    let existing: Vec<String> = registry
        .query("SELECT id FROM projects", [], |row| row.get(0))
        .map_err(|error| CliError::message(format!("cannot read registered projects: {error}")))?;
    if existing.iter().any(|id| id.as_str() != project_id.as_str()) {
        return Err(CliError::message(format!(
            "project identity {project_id} disagrees with registered project id(s) {}",
            existing.join(", ")
        )));
    }
    if !existing.iter().any(|id| id.as_str() == project_id.as_str()) {
        registry
            .execute(
                "INSERT INTO projects (id, created_at, updated_at) VALUES (?1, ?2, ?2) \
                 ON CONFLICT(id) DO NOTHING",
                rusqlite::params![project_id.as_str(), now_seconds()],
            )
            .map_err(|error| CliError::message(format!("cannot register project: {error}")))?;
    }
    Ok(())
}

fn now_seconds() -> i64 {
    i64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    )
    .unwrap_or(i64::MAX)
}

fn initialize_home(context: &ExecutionContext) -> Result<(), CliError> {
    let home = required_user_home(context)?;
    let parent = home
        .parent()
        .ok_or_else(|| CliError::message("shepherd user home has no parent"))?;
    let parent = std::fs::canonicalize(parent).map_err(|error| {
        CliError::message(format!(
            "cannot resolve shepherd user-home parent {}: {error}",
            parent.display()
        ))
    })?;
    let name = home
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| CliError::message("shepherd user home has no UTF-8 final component"))?;
    ensure_directory_tree(&parent, name, HOME_DIRECTORIES)?;
    Ok(())
}

fn typed_config_value(config: &ShepherdConfig, key: &str) -> Result<String, CliError> {
    if key.is_empty() || key.split('.').any(|part| part.is_empty()) {
        return Err(CliError::message_with_code(
            "config key must be a dotted typed key",
            2,
        ));
    }
    // Configuration reads go through `config`; `dep:toml` is a one-way
    // dependency and this call site must never adopt it back.
    let source = config::Config::try_from(config)
        .map_err(|error| CliError::message(format!("cannot inspect typed config: {error}")))?;
    match source.get_string(key) {
        Ok(value) => Ok(value),
        Err(config::ConfigError::NotFound(_)) => Err(CliError::message_with_code(
            format!("unknown typed config key: {key}"),
            2,
        )),
        Err(_not_a_string) => {
            let value: serde_json::Value = source.get(key).map_err(|error| {
                CliError::message(format!("cannot read typed config key `{key}`: {error}"))
            })?;
            serde_json::to_string(&value).map_err(|error| {
                CliError::message(format!("cannot encode typed config value: {error}"))
            })
        }
    }
}

#[derive(serde::Serialize)]
struct DoctorReport {
    primary_root: PathBuf,
    namespace: PathBuf,
    docs: PathBuf,
    ctx: PathBuf,
    runs: PathBuf,
    registry: PathBuf,
    config_sources: Vec<PathBuf>,
    registry_schema: Option<u32>,
    /// Where `shepherd` resolves on `PATH`, the way a shell would. `None`
    /// means nothing answers the name at all.
    resolved_shepherd_path: Option<PathBuf>,
    /// Whether that resolved file is the native compiled binary, as
    /// opposed to a launcher or wrapper script. `None` only when no
    /// `resolved_shepherd_path` was found to classify.
    resolved_shepherd_native: Option<bool>,
    /// Seconds by which the resolved binary's mtime trails the mtime of
    /// the binary currently running this check. Negative means stale.
    /// `None` when no comparison could be made (nothing resolved, or the
    /// running binary's own path or mtime is unavailable).
    resolved_shepherd_skew_seconds: Option<i64>,
    findings: Vec<String>,
    /// Real, operator-visible facts about the *environment* — principally
    /// the resolved `shepherd` — that must never flip `ok`/exit 3. A
    /// checkout with nothing installed on `PATH` at all is a legitimate
    /// developer workflow, not a broken namespace.
    warnings: Vec<String>,
    ok: bool,
}

impl DoctorReport {
    fn render_text(&self) -> String {
        let resolved_shepherd = match &self.resolved_shepherd_path {
            Some(path) => {
                let native = match self.resolved_shepherd_native {
                    Some(true) => "native",
                    Some(false) => "not native",
                    None => "format unknown",
                };
                let skew = match self.resolved_shepherd_skew_seconds {
                    Some(skew) if skew < 0 => format!(", {} s stale", -skew),
                    _ => String::new(),
                };
                format!("{} ({native}{skew})", path.display())
            }
            None => "not found on PATH".to_owned(),
        };
        let mut output = format!(
            "primary: {}\nnamespace: {}\ndocs: {}\nctx: {}\nruns: {}\nregistry: {}\n\
             resolved shepherd: {resolved_shepherd}\nstatus: {}",
            self.primary_root.display(),
            self.namespace.display(),
            self.docs.display(),
            self.ctx.display(),
            self.runs.display(),
            self.registry.display(),
            if self.ok { "ok" } else { "failed" }
        );
        for finding in &self.findings {
            output.push_str("\nissue: ");
            output.push_str(finding);
        }
        for warning in &self.warnings {
            output.push_str("\nwarning: ");
            output.push_str(warning);
        }
        output
    }
}

fn health_report(context: &ExecutionContext) -> DoctorReport {
    let mut findings = Vec::new();
    let mut warnings = Vec::new();
    for (label, path) in [
        ("namespace", &context.namespace),
        ("docs", &context.docs_root),
        ("ctx", &context.ctx_root),
        ("runs", &context.runs_root),
    ] {
        if !path.is_dir() {
            findings.push(format!("{label} directory is absent: {}", path.display()));
        }
    }
    let mut registry_handle = None;
    let mut registry_schema = None;
    match Registry::open(&context.registry_path, OpenMode::ReadOnly) {
        Ok(registry) => {
            match registry.schema_version() {
                Ok(version) => registry_schema = Some(version),
                Err(error) => findings.push(format!("cannot read registry schema: {error}")),
            }
            registry_handle = Some(registry);
        }
        Err(error) => findings.push(format!("cannot open registry read-only: {error}")),
    }

    let identity = read_project_identity_for_doctor(&context.primary_root, &mut findings);

    let project_rows = registry_handle.as_ref().and_then(|registry| {
        match registry.query::<String, _, _>("SELECT id FROM projects", [], |row| row.get(0)) {
            Ok(rows) => Some(rows),
            Err(error) => {
                findings.push(format!("cannot read registered projects: {error}"));
                None
            }
        }
    });

    match (&identity, &project_rows) {
        (Some(identity), Some(rows)) if rows.is_empty() => {
            findings.push(format!(
                "no `projects` row is registered for project identity {identity}"
            ));
        }
        (Some(identity), Some(rows))
            if !rows.iter().any(|row| row.as_str() == identity.as_str()) =>
        {
            findings.push(format!(
                "project identity {identity} disagrees with registered project id(s) {}",
                rows.join(", ")
            ));
        }
        _ => {}
    }

    let resolved_shepherd = inspect_resolved_shepherd(&mut warnings);

    DoctorReport {
        primary_root: context.primary_root.clone(),
        namespace: context.namespace.clone(),
        docs: context.docs_root.clone(),
        ctx: context.ctx_root.clone(),
        runs: context.runs_root.clone(),
        registry: context.registry_path.clone(),
        config_sources: context
            .config_sources
            .iter()
            .map(|source| source.path.clone())
            .collect(),
        registry_schema,
        resolved_shepherd_path: resolved_shepherd.path,
        resolved_shepherd_native: resolved_shepherd.native,
        resolved_shepherd_skew_seconds: resolved_shepherd.skew_seconds,
        ok: findings.is_empty(),
        findings,
        warnings,
    }
}

/// Doctor's own identity check. Read-only: a missing, malformed, or
/// disagreeing identity becomes a finding, never a repair.
fn read_project_identity_for_doctor(
    primary_root: &Path,
    findings: &mut Vec<String>,
) -> Option<ProjectId> {
    match descriptor::read_relative_nofollow(
        primary_root,
        PROJECT_IDENTITY_RELATIVE,
        MAX_PROJECT_IDENTITY_BYTES,
    ) {
        Ok(descriptor::Lookup::Missing) => {
            findings.push(format!(
                "project identity is absent: run `shepherd init --confirm` ({PROJECT_IDENTITY_RELATIVE})"
            ));
            None
        }
        Ok(descriptor::Lookup::NotRegular) => {
            findings.push(format!(
                "project identity is not a regular file: {PROJECT_IDENTITY_RELATIVE}"
            ));
            None
        }
        Ok(descriptor::Lookup::Regular(bytes)) => match parse_project_identity(&bytes) {
            Ok(id) => Some(id),
            Err(error) => {
                findings.push(format!(
                    "project identity is invalid: {}",
                    error.message_text().unwrap_or("unknown error")
                ));
                None
            }
        },
        Err(error) => {
            findings.push(format!(
                "cannot inspect project identity: {}",
                error.message_text().unwrap_or("unknown error")
            ));
            None
        }
    }
}

/// The three facts `doctor` owes the operator about whatever answers
/// `shepherd` on `PATH` — the exact binary a hook or another shell session
/// would actually run. A version string alone proved unable to answer any
/// of them: a stale install and its own fix reported the identical
/// `shepherd-cli` version throughout an entire incident.
#[derive(Default)]
struct ResolvedShepherd {
    path: Option<PathBuf>,
    native: Option<bool>,
    skew_seconds: Option<i64>,
}

/// Inspect whatever answers `shepherd` on `PATH`. Read-only, and never
/// fatal: an operator running from a bare checkout with nothing installed
/// still gets a report, not a crash. Findings land in `warnings`, never in
/// `findings` — this reports on the *environment*, not on the namespace
/// `doctor` was asked to check, and it must never flip `init`'s or
/// `doctor`'s exit code for a developer who has simply never installed the
/// CLI system-wide.
fn inspect_resolved_shepherd(warnings: &mut Vec<String>) -> ResolvedShepherd {
    let Some(resolved) = resolve_shepherd_on_path() else {
        warnings.push(
            "shepherd is not present on PATH; hooks and any other process that invokes the \
             bare `shepherd` name will fail to find one until it is installed (for example: \
             `cargo install --path crates/cli --locked --force`)"
                .to_owned(),
        );
        return ResolvedShepherd::default();
    };

    let format = classify_binary_format(&resolved);
    if format != BinaryFormat::Native {
        warnings.push(format!(
            "the `shepherd` resolved from PATH at {} is {}; anything invoking the bare name \
             runs whatever that file does, not the native binary",
            resolved.display(),
            format.describe(),
        ));
    }

    let skew_seconds = compare_binary_freshness(&resolved, warnings);

    ResolvedShepherd {
        path: Some(resolved),
        native: Some(format == BinaryFormat::Native),
        skew_seconds,
    }
}

/// Resolve `shepherd` on `PATH` the way a shell would: first directory,
/// first match, in `PATH` order.
fn resolve_shepherd_on_path() -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    let names: &[&str] = if cfg!(windows) {
        &["shepherd.exe", "shepherd"]
    } else {
        &["shepherd"]
    };
    for directory in std::env::split_paths(&path) {
        for name in names {
            let candidate = directory.join(name);
            if is_executable_file(&candidate) {
                return Some(candidate);
            }
        }
    }
    None
}

fn is_executable_file(path: &Path) -> bool {
    let Ok(metadata) = std::fs::metadata(path) else {
        return false;
    };
    if !metadata.is_file() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        metadata.permissions().mode() & 0o111 != 0
    }
    #[cfg(not(unix))]
    {
        true
    }
}

/// What kind of file answers `shepherd` on `PATH`. Distinguishing this
/// from a version string is the entire point: a launcher script and the
/// native binary it wraps can both report the same `shepherd-cli` version.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum BinaryFormat {
    Native,
    Script,
    Unknown,
}

impl BinaryFormat {
    fn describe(self) -> &'static str {
        match self {
            BinaryFormat::Native => "a native compiled binary",
            BinaryFormat::Script => "a shell script or launcher, not the native binary",
            BinaryFormat::Unknown => "an unrecognized executable format",
        }
    }
}

/// Sniff the first bytes of `path` for a shebang or a known native
/// executable magic number (ELF, Mach-O, or Windows PE). Never trusts a
/// version string: a launcher and its target can both claim the same one.
fn classify_binary_format(path: &Path) -> BinaryFormat {
    use std::io::Read;
    let Ok(mut file) = std::fs::File::open(path) else {
        return BinaryFormat::Unknown;
    };
    let mut header = [0u8; 4];
    let read = file.read(&mut header).unwrap_or(0);
    if read >= 2 && &header[..2] == b"#!" {
        return BinaryFormat::Script;
    }
    if read < 4 {
        return BinaryFormat::Unknown;
    }
    const ELF_MAGIC: [u8; 4] = [0x7f, b'E', b'L', b'F'];
    const MACHO_MAGICS: [[u8; 4]; 6] = [
        [0xfe, 0xed, 0xfa, 0xce], // Mach-O 32-bit
        [0xfe, 0xed, 0xfa, 0xcf], // Mach-O 64-bit
        [0xce, 0xfa, 0xed, 0xfe], // Mach-O 32-bit, byte-swapped
        [0xcf, 0xfa, 0xed, 0xfe], // Mach-O 64-bit, byte-swapped
        [0xca, 0xfe, 0xba, 0xbe], // universal (fat), big-endian
        [0xbe, 0xba, 0xfe, 0xca], // universal (fat), little-endian
    ];
    const PE_MAGIC: [u8; 2] = *b"MZ";
    if header == ELF_MAGIC || MACHO_MAGICS.contains(&header) || header[..2] == PE_MAGIC {
        return BinaryFormat::Native;
    }
    BinaryFormat::Unknown
}

/// The skew signal: whether the file `PATH` resolves is OLDER than the
/// binary currently executing this very check. Two binaries reporting the
/// identical `--version` string proved unable to be told apart this way —
/// the second occurrence of that exact incident, in one session, is the
/// reason this check exists — but their mtimes can.
///
/// Deliberately NOT compared against the diagnosed namespace's own git
/// history: `primary_root` names the *project being checked*, which is not
/// necessarily this tool's own source checkout, so its HEAD commit date is
/// not a trustworthy proxy for when `shepherd` itself was last built. The
/// binary currently running this very check is: it is that source tree's
/// most recent compile, by construction.
fn compare_binary_freshness(resolved: &Path, warnings: &mut Vec<String>) -> Option<i64> {
    let current_exe = std::env::current_exe().ok()?;
    if same_binary(resolved, &current_exe) {
        return Some(0);
    }
    let resolved_mtime = binary_mtime_seconds(resolved)?;
    let current_mtime = binary_mtime_seconds(&current_exe)?;
    let skew = resolved_mtime - current_mtime;
    if skew < 0 {
        warnings.push(format!(
            "the `shepherd` resolved from PATH at {} is {} second(s) older than the binary \
             currently running this check; PATH may be resolving a stale install. Reinstall \
             with `cargo install --path crates/cli --locked --force`",
            resolved.display(),
            -skew,
        ));
    }
    Some(skew)
}

fn binary_mtime_seconds(path: &Path) -> Option<i64> {
    let metadata = std::fs::metadata(path).ok()?;
    let modified = metadata.modified().ok()?;
    let duration = modified.duration_since(std::time::UNIX_EPOCH).ok()?;
    i64::try_from(duration.as_secs()).ok()
}

/// Whether `a` and `b` are the same underlying file, so a binary invoked
/// directly is never compared against itself and flagged as its own skew.
fn same_binary(a: &Path, b: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        match (std::fs::metadata(a), std::fs::metadata(b)) {
            (Ok(left), Ok(right)) => left.dev() == right.dev() && left.ino() == right.ino(),
            _ => false,
        }
    }
    #[cfg(not(unix))]
    {
        match (std::fs::canonicalize(a), std::fs::canonicalize(b)) {
            (Ok(left), Ok(right)) => left == right,
            _ => false,
        }
    }
}

fn write(context: &mut ExecutionContext, text: String) -> Result<(), CliError> {
    context
        .write_stdout(format!("{text}\n").as_bytes())
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

#[cfg(unix)]
fn ensure_directory_tree(
    anchor: &Path,
    root_name: &str,
    children: &[&str],
) -> Result<Vec<String>, CliError> {
    let mut created = Vec::new();
    let anchor_fd = descriptor::open_root(anchor)?;
    let (directory, root_created) = descriptor::open_directory(&anchor_fd, root_name, true)?;
    if root_created {
        created.push(root_name.to_owned());
    }
    for child in children {
        let (_, child_created) = descriptor::open_directory(&directory, child, true)?;
        if child_created {
            created.push(format!("{root_name}/{child}"));
        }
    }
    Ok(created)
}

#[cfg(not(unix))]
fn ensure_directory_tree(
    _anchor: &Path,
    _root: &str,
    _children: &[&str],
) -> Result<Vec<String>, CliError> {
    Err(CliError::message(
        "descriptor-safe bootstrap mutation is unavailable on this platform",
    ))
}

#[cfg(unix)]
fn write_no_clobber(anchor: &Path, relative: &str, bytes: &[u8]) -> Result<bool, CliError> {
    descriptor::write_no_clobber(anchor, relative, bytes)
}

#[cfg(not(unix))]
fn write_no_clobber(_anchor: &Path, _relative: &str, _bytes: &[u8]) -> Result<bool, CliError> {
    Err(CliError::message(
        "descriptor-safe bootstrap mutation is unavailable on this platform",
    ))
}

#[cfg(unix)]
fn remove_file_no_follow(anchor: &Path, relative: &str) -> Result<(), CliError> {
    descriptor::remove_file_no_follow(anchor, relative)
}

#[cfg(not(unix))]
fn remove_file_no_follow(_anchor: &Path, _relative: &str) -> Result<(), CliError> {
    Err(CliError::message(
        "descriptor-safe bootstrap mutation is unavailable on this platform",
    ))
}

#[cfg(unix)]
fn remove_directory_no_follow(anchor: &Path, relative: &str) -> Result<(), CliError> {
    descriptor::remove_directory_no_follow(anchor, relative)
}

#[cfg(not(unix))]
fn remove_directory_no_follow(_anchor: &Path, _relative: &str) -> Result<(), CliError> {
    Err(CliError::message(
        "descriptor-safe bootstrap mutation is unavailable on this platform",
    ))
}

#[cfg(unix)]
mod descriptor {
    use std::{
        fs::File,
        io::{Read, Write},
        os::fd::OwnedFd,
        path::{Component, Path},
        sync::atomic::{AtomicU64, Ordering},
    };

    use rustix::fs::{AtFlags, FileType, Mode, OFlags, linkat, mkdirat, open, openat, unlinkat};

    use crate::interface::CliError;

    static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

    /// The outcome of a descriptor-safe, non-creating, non-following lookup.
    pub(super) enum Lookup {
        Missing,
        NotRegular,
        Regular(Vec<u8>),
    }

    pub(super) fn open_root(path: &Path) -> Result<OwnedFd, CliError> {
        let mut descriptor = open(
            "/",
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| CliError::message(format!("cannot open filesystem root: {error}")))?;
        for component in path.components() {
            let Component::Normal(part) = component else {
                continue;
            };
            descriptor = openat(
                &descriptor,
                part,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::empty(),
            )
            .map_err(|error| {
                CliError::message(format!(
                    "cannot open bootstrap path {} without following links: {error}",
                    path.display()
                ))
            })?;
        }
        Ok(descriptor)
    }

    /// Open (and, if `create`, make) a child directory. The returned `bool`
    /// is whether THIS call created it: `false` means it already existed,
    /// which is exactly the fact atomic rollback needs to own only what it
    /// made.
    pub(super) fn open_directory(
        parent: &OwnedFd,
        name: &str,
        create: bool,
    ) -> Result<(OwnedFd, bool), CliError> {
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW;
        match openat(parent, name, flags, Mode::empty()) {
            Ok(directory) => Ok((directory, false)),
            Err(error) if create && error == rustix::io::Errno::NOENT => {
                let created = match mkdirat(parent, name, Mode::from_raw_mode(0o755)) {
                    Ok(()) => true,
                    Err(rustix::io::Errno::EXIST) => false,
                    Err(error) => {
                        return Err(CliError::message(format!(
                            "cannot create bootstrap directory `{name}`: {error}"
                        )));
                    }
                };
                let directory = openat(parent, name, flags, Mode::empty()).map_err(|error| {
                    CliError::message(format!(
                        "cannot open bootstrap directory `{name}` without following links: {error}"
                    ))
                })?;
                Ok((directory, created))
            }
            Err(error) => Err(CliError::message(format!(
                "cannot open bootstrap directory `{name}` without following links: {error}"
            ))),
        }
    }

    pub(super) fn write_no_clobber(
        anchor: &Path,
        relative: &str,
        bytes: &[u8],
    ) -> Result<bool, CliError> {
        let (parent, name) = parent_and_name(anchor, relative, true)?;
        let nonce = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
        let temporary = format!(".{name}.shepherd.tmp.{}.{nonce}", std::process::id());
        let descriptor = openat(
            &parent,
            &temporary,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::from_raw_mode(0o644),
        )
        .map_err(|error| {
            CliError::message(format!("cannot create `{relative}` atomically: {error}"))
        })?;
        let mut file = File::from(descriptor);
        let result = (|| -> Result<bool, CliError> {
            file.write_all(bytes).map_err(|error| {
                CliError::message(format!("cannot write `{relative}`: {error}"))
            })?;
            file.sync_all()
                .map_err(|error| CliError::message(format!("cannot sync `{relative}`: {error}")))?;
            let published = match linkat(&parent, &temporary, &parent, &name, AtFlags::empty()) {
                Ok(()) => true,
                Err(error) if error == rustix::io::Errno::EXIST => false,
                Err(error) => {
                    return Err(CliError::message(format!(
                        "cannot publish `{relative}` without replacing an existing file: {error}"
                    )));
                }
            };
            unlinkat(&parent, &temporary, AtFlags::empty()).map_err(|error| {
                CliError::message(format!(
                    "cannot remove `{relative}` temporary file: {error}"
                ))
            })?;
            if !published {
                return Ok(false);
            }
            File::from(
                openat(
                    &parent,
                    ".",
                    OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                    Mode::empty(),
                )
                .map_err(|error| {
                    CliError::message(format!("cannot reopen bootstrap directory: {error}"))
                })?,
            )
            .sync_all()
            .map_err(|error| {
                CliError::message(format!("cannot sync bootstrap directory: {error}"))
            })?;
            Ok(true)
        })();
        if result.is_err() {
            let _ = unlinkat(&parent, &temporary, AtFlags::empty());
        }
        result
    }

    /// Descriptor-safe, non-creating, non-following lookup used by both
    /// `doctor` (read-only) and `init`'s heal path. A missing intermediate
    /// directory or a missing final component is reported as [`Lookup::Missing`],
    /// never created.
    pub(super) fn read_relative_nofollow(
        anchor: &Path,
        relative: &str,
        limit: usize,
    ) -> Result<Lookup, CliError> {
        let (parent, name) = match parent_and_name(anchor, relative, false) {
            Ok(located) => located,
            Err(_) => return Ok(Lookup::Missing),
        };
        let descriptor = match openat(
            &parent,
            &name,
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        ) {
            Ok(descriptor) => descriptor,
            Err(rustix::io::Errno::NOENT) => return Ok(Lookup::Missing),
            Err(rustix::io::Errno::ISDIR) => return Ok(Lookup::NotRegular),
            Err(error) => {
                return Err(CliError::message(format!(
                    "cannot open `{relative}`: {error}"
                )));
            }
        };
        let stat = rustix::fs::fstat(&descriptor)
            .map_err(|error| CliError::message(format!("cannot inspect `{relative}`: {error}")))?;
        if !FileType::from_raw_mode(stat.st_mode).is_file() {
            return Ok(Lookup::NotRegular);
        }
        let file = File::from(descriptor);
        let mut bytes = Vec::new();
        file.take(u64::try_from(limit + 1).expect("identity limit fits in u64"))
            .read_to_end(&mut bytes)
            .map_err(|error| CliError::message(format!("cannot read `{relative}`: {error}")))?;
        if bytes.len() > limit {
            return Err(CliError::message(format!(
                "`{relative}` exceeds {limit}-byte limit"
            )));
        }
        Ok(Lookup::Regular(bytes))
    }

    pub(super) fn remove_file_no_follow(anchor: &Path, relative: &str) -> Result<(), CliError> {
        let (parent, name) = parent_and_name(anchor, relative, false)?;
        match unlinkat(&parent, &name, AtFlags::empty()) {
            Ok(()) | Err(rustix::io::Errno::NOENT) => Ok(()),
            Err(error) => Err(CliError::message(format!(
                "cannot remove `{relative}`: {error}"
            ))),
        }
    }

    pub(super) fn remove_directory_no_follow(
        anchor: &Path,
        relative: &str,
    ) -> Result<(), CliError> {
        let (parent, name) = parent_and_name(anchor, relative, false)?;
        match unlinkat(&parent, &name, AtFlags::REMOVEDIR) {
            Ok(()) | Err(rustix::io::Errno::NOENT) => Ok(()),
            Err(error) => Err(CliError::message(format!(
                "cannot remove directory `{relative}`: {error}"
            ))),
        }
    }

    fn parent_and_name(
        anchor: &Path,
        relative: &str,
        create: bool,
    ) -> Result<(OwnedFd, String), CliError> {
        let relative = Path::new(relative);
        if relative.is_absolute()
            || relative
                .components()
                .any(|part| !matches!(part, Component::Normal(_)))
        {
            return Err(CliError::message(
                "bootstrap file path is not a safe relative path",
            ));
        }
        let mut parts = relative.components();
        let name = parts
            .next_back()
            .and_then(|part| match part {
                Component::Normal(name) => name.to_str(),
                _ => None,
            })
            .ok_or_else(|| CliError::message("bootstrap file path has no valid name"))?
            .to_owned();
        let mut directory = open_root(anchor)?;
        for part in parts {
            let Component::Normal(part) = part else {
                unreachable!("validated component")
            };
            let (next, _) = open_directory(
                &directory,
                part.to_str()
                    .ok_or_else(|| CliError::message("bootstrap path is not UTF-8"))?,
                create,
            )?;
            directory = next;
        }
        Ok((directory, name))
    }
}

#[cfg(all(test, unix))]
mod tests {
    use std::{
        fs,
        sync::{Arc, Barrier},
        thread,
        time::{SystemTime, UNIX_EPOCH},
    };

    use super::descriptor;

    #[test]
    fn no_clobber_publication_keeps_one_racing_writer_and_leaves_no_temp() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock is after epoch")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "shepherd-wave-c-bootstrap-race-{}-{nonce:x}",
            std::process::id()
        ));
        fs::create_dir_all(root.join(".shepherd")).expect("create fixture namespace");
        let root = fs::canonicalize(root).expect("canonicalize fixture root");
        let barrier = Arc::new(Barrier::new(3));
        let mut writers = Vec::new();
        for bytes in [b"first\n".as_slice(), b"second\n".as_slice()] {
            let root = root.clone();
            let barrier = Arc::clone(&barrier);
            writers.push(thread::spawn(move || {
                barrier.wait();
                descriptor::write_no_clobber(&root, ".shepherd/shepherd.toml", bytes)
            }));
        }
        barrier.wait();
        let mut published_count = 0;
        for writer in writers {
            if writer
                .join()
                .expect("writer thread must not panic")
                .expect("descriptor publication must succeed")
            {
                published_count += 1;
            }
        }
        assert_eq!(
            published_count, 1,
            "exactly one racing writer must observe publication"
        );
        let published = fs::read(root.join(".shepherd/shepherd.toml")).expect("read publication");
        assert!(matches!(published.as_slice(), b"first\n" | b"second\n"));
        assert!(
            fs::read_dir(root.join(".shepherd"))
                .expect("read namespace")
                .all(|entry| !entry
                    .expect("directory entry")
                    .file_name()
                    .to_string_lossy()
                    .contains(".shepherd.tmp.")),
            "atomic no-clobber publication must clean temporary files"
        );
        fs::remove_dir_all(root).expect("remove fixture");
    }

    #[test]
    fn classify_binary_format_tells_a_shebang_launcher_from_the_native_test_binary() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock is after epoch")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "shepherd-wave-c-bootstrap-classify-{}-{nonce:x}",
            std::process::id()
        ));
        fs::create_dir_all(&root).expect("create fixture directory");

        let script = root.join("launcher");
        fs::write(&script, b"#!/bin/sh\nexec shepherd \"$@\"\n").expect("write launcher script");
        assert_eq!(
            super::classify_binary_format(&script),
            super::BinaryFormat::Script,
            "a shebang file must never be classified as the native binary"
        );

        let empty = root.join("empty");
        fs::write(&empty, b"").expect("write empty file");
        assert_eq!(
            super::classify_binary_format(&empty),
            super::BinaryFormat::Unknown
        );

        // The test harness's own executable is a real, native, compiled
        // binary (a Mach-O/ELF executable), so it is a faithful stand-in
        // for `shepherd` itself without depending on `CARGO_BIN_EXE_shepherd`,
        // which is only available to integration tests under `tests/`.
        let native = std::env::current_exe().expect("resolve the running test binary");
        assert_eq!(
            super::classify_binary_format(&native),
            super::BinaryFormat::Native,
            "the running test binary must be classified as native"
        );

        fs::remove_dir_all(root).expect("remove fixture");
    }

    #[test]
    fn same_binary_matches_a_hard_link_and_rejects_distinct_files() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock is after epoch")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "shepherd-wave-c-bootstrap-same-binary-{}-{nonce:x}",
            std::process::id()
        ));
        fs::create_dir_all(&root).expect("create fixture directory");

        let original = root.join("original");
        fs::write(&original, b"identical content\n").expect("write original file");
        let linked = root.join("linked");
        fs::hard_link(&original, &linked).expect("hard link the original file");
        assert!(
            super::same_binary(&original, &linked),
            "a hard link must resolve to the same underlying file"
        );

        let distinct = root.join("distinct");
        fs::write(&distinct, b"identical content\n").expect("write a byte-identical copy");
        assert!(
            !super::same_binary(&original, &distinct),
            "byte-identical content must not be mistaken for the same file"
        );

        fs::remove_dir_all(root).expect("remove fixture");
    }
}
