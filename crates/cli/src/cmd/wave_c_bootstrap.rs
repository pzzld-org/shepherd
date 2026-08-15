//! Native layout-v5 project and user-home bootstrap commands.
//!
//! Legacy bootstrap installed environments and wrote retired namespace roots.
//! The canonical CLI owns only typed layout-v5 roots.

use std::path::{Path, PathBuf};

use shepherd::{
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

fn initialize_project(context: &ExecutionContext, write_config: bool) -> Result<(), CliError> {
    ensure_directory_tree(&context.primary_root, ".shepherd", PROJECT_DIRECTORIES)?;
    if write_config {
        initialize_project_config(context)?;
    }
    Registry::open_migrated(&context.registry_path)
        .map_err(|error| CliError::message(format!("cannot initialize typed registry: {error}")))?;
    Ok(())
}

fn initialize_project_config(context: &ExecutionContext) -> Result<(), CliError> {
    // An empty document is valid: the one typed schema loader materializes
    // every default, without a copied default table drifting from the schema.
    let contents = b"# Shepherd layout-v5 project configuration.\n# Defaults are supplied by the typed schema.\n";
    write_no_clobber(&context.primary_root, ".shepherd/shepherd.toml", contents)
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
    ensure_directory_tree(&parent, name, HOME_DIRECTORIES)
}

fn typed_config_value(config: &ShepherdConfig, key: &str) -> Result<String, CliError> {
    if key.is_empty() || key.split('.').any(|part| part.is_empty()) {
        return Err(CliError::message_with_code(
            "config key must be a dotted typed key",
            2,
        ));
    }
    let mut current = toml::Value::try_from(config)
        .map_err(|error| CliError::message(format!("cannot inspect typed config: {error}")))?;
    for part in key.split('.') {
        current = current.get(part).cloned().ok_or_else(|| {
            CliError::message_with_code(format!("unknown typed config key: {key}"), 2)
        })?;
    }
    match current {
        toml::Value::String(value) => Ok(value),
        value => serde_json::to_string(&value).map_err(|error| {
            CliError::message(format!("cannot encode typed config value: {error}"))
        }),
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
    findings: Vec<String>,
    ok: bool,
}

impl DoctorReport {
    fn render_text(&self) -> String {
        let mut output = format!(
            "primary: {}\nnamespace: {}\ndocs: {}\nctx: {}\nruns: {}\nregistry: {}\nstatus: {}",
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
        output
    }
}

fn health_report(context: &ExecutionContext) -> DoctorReport {
    let mut findings = Vec::new();
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
    let registry_schema = match Registry::open(&context.registry_path, OpenMode::ReadOnly) {
        Ok(registry) => match registry.schema_version() {
            Ok(version) => Some(version),
            Err(error) => {
                findings.push(format!("cannot read registry schema: {error}"));
                None
            }
        },
        Err(error) => {
            findings.push(format!("cannot open registry read-only: {error}"));
            None
        }
    };
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
        ok: findings.is_empty(),
        findings,
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
) -> Result<(), CliError> {
    let anchor_fd = descriptor::open_root(anchor)?;
    let directory = descriptor::open_directory(&anchor_fd, root_name, true)?;
    for child in children {
        let _ = descriptor::open_directory(&directory, child, true)?;
    }
    Ok(())
}

#[cfg(not(unix))]
fn ensure_directory_tree(_anchor: &Path, _root: &str, _children: &[&str]) -> Result<(), CliError> {
    Err(CliError::message(
        "descriptor-safe bootstrap mutation is unavailable on this platform",
    ))
}

#[cfg(unix)]
fn write_no_clobber(anchor: &Path, relative: &str, bytes: &[u8]) -> Result<(), CliError> {
    descriptor::write_no_clobber(anchor, relative, bytes)
}

#[cfg(not(unix))]
fn write_no_clobber(_anchor: &Path, _relative: &str, _bytes: &[u8]) -> Result<(), CliError> {
    Err(CliError::message(
        "descriptor-safe bootstrap mutation is unavailable on this platform",
    ))
}

#[cfg(unix)]
mod descriptor {
    use std::{
        fs::File,
        io::Write,
        os::fd::OwnedFd,
        path::{Component, Path},
        sync::atomic::{AtomicU64, Ordering},
    };

    use rustix::fs::{AtFlags, Mode, OFlags, linkat, mkdirat, open, openat, unlinkat};

    use crate::interface::CliError;

    static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

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

    pub(super) fn open_directory(
        parent: &OwnedFd,
        name: &str,
        create: bool,
    ) -> Result<OwnedFd, CliError> {
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW;
        match openat(parent, name, flags, Mode::empty()) {
            Ok(directory) => Ok(directory),
            Err(error) if create && error == rustix::io::Errno::NOENT => {
                match mkdirat(parent, name, Mode::from_raw_mode(0o755)) {
                    Ok(()) | Err(rustix::io::Errno::EXIST) => {}
                    Err(error) => {
                        return Err(CliError::message(format!(
                            "cannot create bootstrap directory `{name}`: {error}"
                        )));
                    }
                }
                openat(parent, name, flags, Mode::empty()).map_err(|error| {
                    CliError::message(format!(
                        "cannot open bootstrap directory `{name}` without following links: {error}"
                    ))
                })
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
    ) -> Result<(), CliError> {
        let (parent, name) = parent_and_name(anchor, relative)?;
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
        let result = (|| {
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
                return Ok(());
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
            .map_err(|error| CliError::message(format!("cannot sync bootstrap directory: {error}")))
        })();
        if result.is_err() {
            let _ = unlinkat(&parent, &temporary, AtFlags::empty());
        }
        result
    }

    fn parent_and_name(anchor: &Path, relative: &str) -> Result<(OwnedFd, String), CliError> {
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
            directory = open_directory(
                &directory,
                part.to_str()
                    .ok_or_else(|| CliError::message("bootstrap path is not UTF-8"))?,
                true,
            )?;
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
        for writer in writers {
            writer
                .join()
                .expect("writer thread must not panic")
                .expect("descriptor publication must succeed");
        }
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
}
