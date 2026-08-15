//! Native layout-v5 migration command boundary.
//!
//! The command is deliberately a standalone module while the command enum is
//! being coordinated by the root lane. It accepts already-resolved namespace
//! paths from `ExecutionContext`; it does not discover a repository, inspect
//! the environment, or touch the live project by itself.

use std::{
    fs,
    path::{Path, PathBuf},
};

use clap::{Parser, ValueEnum};
use serde::Serialize;

use shepherd::{
    loader,
    registry::layout::{
        Authorization, ExecutionReport, LayoutError, LayoutManifest, LayoutPlan, MigrationOptions,
    },
};

use crate::{
    ContextInputs, ExecutionContext,
    interface::{CliError, CliGlobals},
};

/// The only filesystem layout currently accepted by the native migrator.
pub const LAYOUT_VERSION: &str = "v5";

/// CLI scope. Project and user-home authorization are intentionally distinct.
#[derive(
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    serde::Deserialize,
    serde::Serialize,
    ValueEnum,
)]
pub enum MigrationScope {
    Project,
    UserHome,
}

/// Parser-owned arguments. Root supplies the resolved paths through
/// [`MigrationRequest`] after constructing its normal execution context.
#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Parser, serde::Deserialize, serde::Serialize,
)]
#[command(name = "migrate", about = "plan or apply a layout-v5 migration")]
pub struct MigrateCmd {
    /// The filesystem layout schema to migrate to.
    #[arg(long, default_value = LAYOUT_VERSION)]
    pub layout: String,
    /// The namespace tier to migrate. User-home is never implied by project.
    #[arg(long, value_enum, default_value_t = MigrationScope::Project)]
    pub scope: MigrationScope,
    /// Print the manifest and do not mutate. This is the default.
    #[arg(long, conflicts_with = "confirm")]
    pub dry_run: bool,
    /// Authorize the selected scope for mutation.
    #[arg(long, conflicts_with = "dry_run")]
    pub confirm: bool,
    /// Evidence directory. The planner writes `before/`, `manifest.json`, and
    /// `rollback.sh` below this path only after confirmation.
    #[arg(long, value_name = "PATH")]
    pub snapshot_dir: Option<PathBuf>,
}

impl MigrateCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let cwd = std::env::current_dir().map_err(|error| {
            CliError::message(format!("cannot resolve current directory: {error}"))
        })?;
        let mut inputs = ContextInputs::from_environment(cwd)
            .map_err(|error| CliError::message(error.to_string()))?;
        inputs.explicit_config = globals.config;
        inputs.verbosity = globals.verbosity;
        let mut context = ExecutionContext::discover_for_layout_v5_migration(inputs)
            .map_err(|error| CliError::message(error.to_string()))?;

        let mut request = match self.scope {
            MigrationScope::Project => {
                MigrationRequest::project(&context.namespace, &context.runs_root)
            }
            MigrationScope::UserHome => {
                let namespace = context.user_home.as_ref().ok_or_else(|| {
                    CliError::message(
                        "cannot resolve shepherd user home; set SHEPHERD_HOME or HOME",
                    )
                })?;
                MigrationRequest::user_home(namespace)
            }
        };
        request.layout = self.layout;
        request.confirm = self.confirm && !self.dry_run;
        request.snapshot_dir = self.snapshot_dir;
        validate_retired_config_candidates(&request.namespace)?;
        let output = execute(&request).map_err(|error| CliError::message(error.to_string()))?;
        let bytes = output_json(&output)
            .map_err(|error| CliError::message(error.to_string()))?
            .into_bytes();
        context
            .write_stdout(&bytes)
            .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
    }
}

/// The planner rewrites every direct canonical `shepherd*.toml` file, not
/// only the active harness's selected layer. Validate all of them through the
/// core migration mode before the planner receives authority to mutate.
fn validate_retired_config_candidates(namespace: &Path) -> Result<(), CliError> {
    let entries = match fs::read_dir(namespace) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => {
            return Err(CliError::message(format!(
                "cannot inspect migration configuration candidates {}: {error}",
                namespace.display()
            )));
        }
    };
    for entry in entries {
        let entry = entry.map_err(|error| {
            CliError::message(format!(
                "cannot inspect migration configuration candidates {}: {error}",
                namespace.display()
            ))
        })?;
        let file_type = entry.file_type().map_err(|error| {
            CliError::message(format!(
                "cannot inspect migration configuration candidate {}: {error}",
                entry.path().display()
            ))
        })?;
        let path = entry.path();
        if !file_type.is_file()
            || !path
                .file_name()
                .and_then(|name| name.to_str())
                .is_some_and(is_canonical_config_candidate)
        {
            continue;
        }
        let contents = fs::read_to_string(&path).map_err(|error| {
            CliError::message(format!(
                "cannot read migration configuration candidate {}: {error}",
                path.display()
            ))
        })?;
        loader::load_for_layout_v5_migration([(path.as_path(), contents.as_str())])
            .map_err(|error| CliError::message(error.to_string()))?;
    }
    Ok(())
}

fn is_canonical_config_candidate(name: &str) -> bool {
    name == "shepherd.toml"
        || name == "shepherd.local.toml"
        || name.starts_with("shepherd.") && name.ends_with(".toml")
}

/// Paths resolved by the CLI host. Keeping this input explicit makes tests
/// fixture-only and prevents this module from accidentally selecting a linked
/// worktree or a user home on its own.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MigrationRequest {
    pub namespace: PathBuf,
    pub runs: Option<PathBuf>,
    pub scope: MigrationScope,
    pub layout: String,
    pub confirm: bool,
    pub snapshot_dir: Option<PathBuf>,
}

impl MigrationRequest {
    pub fn project(namespace: impl Into<PathBuf>, runs: impl Into<PathBuf>) -> Self {
        Self {
            namespace: namespace.into(),
            runs: Some(runs.into()),
            scope: MigrationScope::Project,
            layout: LAYOUT_VERSION.into(),
            confirm: false,
            snapshot_dir: None,
        }
    }

    pub fn user_home(namespace: impl Into<PathBuf>) -> Self {
        Self {
            namespace: namespace.into(),
            runs: None,
            scope: MigrationScope::UserHome,
            layout: LAYOUT_VERSION.into(),
            confirm: false,
            snapshot_dir: None,
        }
    }
}

/// Stable JSON result. `execution` is absent from dry-run semantics and is
/// populated only after a confirmed mutation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MigrationOutput {
    pub schema: &'static str,
    pub scope: MigrationScopeOutput,
    pub manifest: LayoutManifest,
    pub execution: Option<ExecutionOutput>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum MigrationScopeOutput {
    Project,
    UserHome,
}

impl From<MigrationScope> for MigrationScopeOutput {
    fn from(scope: MigrationScope) -> Self {
        match scope {
            MigrationScope::Project => Self::Project,
            MigrationScope::UserHome => Self::UserHome,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ExecutionOutput {
    pub snapshot_dir: String,
    pub moved: usize,
    pub deduplicated: usize,
    pub removed_directories: usize,
    pub removed_files: usize,
    pub rewritten: usize,
}

impl From<ExecutionReport> for ExecutionOutput {
    fn from(report: ExecutionReport) -> Self {
        Self {
            snapshot_dir: report.snapshot_dir.display().to_string(),
            moved: report.moved,
            deduplicated: report.deduplicated,
            removed_directories: report.removed_directories,
            removed_files: report.removed_files,
            rewritten: report.rewritten,
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum MigrationCommandError {
    #[error("unsupported layout `{0}`; expected {LAYOUT_VERSION}")]
    UnsupportedLayout(String),
    #[error("project migration requires a resolved configured runs root")]
    MissingRuns,
    #[error(transparent)]
    Layout(#[from] LayoutError),
    #[error("serialize migration result: {0}")]
    Serialization(#[from] serde_json::Error),
}

/// Plan or execute one migration request. The absence of `confirm` is a dry
/// run regardless of the command's `dry_run` parser flag.
pub fn execute(request: &MigrationRequest) -> Result<MigrationOutput, MigrationCommandError> {
    if request.layout != LAYOUT_VERSION {
        return Err(MigrationCommandError::UnsupportedLayout(
            request.layout.clone(),
        ));
    }
    let plan = match request.scope {
        MigrationScope::Project => LayoutPlan::project(
            &request.namespace,
            request
                .runs
                .as_deref()
                .ok_or(MigrationCommandError::MissingRuns)?,
        )?,
        MigrationScope::UserHome => LayoutPlan::user_home(&request.namespace)?,
    };
    let execution = if request.confirm {
        let authorization = match request.scope {
            MigrationScope::Project => Authorization::Project,
            MigrationScope::UserHome => Authorization::UserHome,
        };
        Some(
            plan.execute(&MigrationOptions {
                authorization: Some(authorization),
                confirm: true,
                snapshot_dir: request.snapshot_dir.clone(),
                ..MigrationOptions::default()
            })?
            .into(),
        )
    } else {
        None
    };
    Ok(MigrationOutput {
        schema: "shepherd-migrate-v5",
        scope: request.scope.into(),
        manifest: plan.manifest().clone(),
        execution,
    })
}

/// Serialize one result without path-dependent pretty-printing differences.
pub fn output_json(output: &MigrationOutput) -> Result<String, MigrationCommandError> {
    Ok(serde_json::to_string_pretty(output)? + "\n")
}

/// Convert parser arguments into a host-resolved request. Root should supply
/// `namespace`, `runs`, and `user_home_namespace` from `ExecutionContext`.
pub fn request_from_command(
    command: &MigrateCmd,
    project_namespace: impl AsRef<Path>,
    configured_runs: Option<impl AsRef<Path>>,
    user_home_namespace: impl AsRef<Path>,
) -> MigrationRequest {
    let mut request = match command.scope {
        MigrationScope::Project => MigrationRequest::project(
            project_namespace.as_ref().to_path_buf(),
            configured_runs
                .map(|path| path.as_ref().to_path_buf())
                .unwrap_or_else(|| project_namespace.as_ref().join("runs")),
        ),
        MigrationScope::UserHome => MigrationRequest::user_home(user_home_namespace.as_ref()),
    };
    request.layout = command.layout.clone();
    request.confirm = command.confirm && !command.dry_run;
    request.snapshot_dir = command.snapshot_dir.clone();
    request
}
