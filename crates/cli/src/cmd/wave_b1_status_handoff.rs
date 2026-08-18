//! Status plus canonical run-scoped handoff creation and inspection.

use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};

use chrono::{DateTime, Utc};
use rusqlite::params;
use shepherd::{
    RunState,
    dispatch::RunId,
    registry::{OpenMode, Registry},
};
use uuid::Uuid;

use crate::{
    ContextInputs, ExecutionContext,
    interface::{CliError, CliGlobals},
};

const HANDOFF_FILE: &str = "handoff.md";

const TABLES: [&str; 13] = [
    "projects",
    "sessions",
    "profiles_defs",
    "mem_entries",
    "index_symbols",
    "index_concepts",
    "index_issues",
    "index_prs",
    "index_releases",
    "index_milestones",
    "logs_events",
    "artifacts",
    "locks_history",
];
const STALENESS: [&str; 5] = [
    "index_symbols",
    "index_issues",
    "index_prs",
    "index_releases",
    "index_milestones",
];

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
pub struct WaveB1StatusCmd;

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
pub struct WaveB1HandoffCmd {
    #[command(subcommand)]
    action: Option<HandoffAction>,
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
enum HandoffAction {
    /// Create the active run's canonical `handoff.md`.
    Create {
        /// Select one existing run explicitly.
        #[arg(long)]
        run: Option<String>,
        /// Select the existing run whose recorded branch matches exactly.
        #[arg(long)]
        branch: Option<String>,
        /// Compatibility spelling. It must resolve to the selected run's
        /// canonical `handoff.md`; arbitrary output paths are rejected.
        #[arg(long)]
        out: Option<PathBuf>,
        /// Atomically replace an existing handoff instead of refusing it.
        #[arg(long)]
        replace: bool,
    },
    List,
    Show {
        pattern: Option<String>,
    },
}

impl WaveB1StatusCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        if !context.registry_path.is_file() {
            return Err(CliError::message(format!(
                "no DB at {} — run 'shepherd init'",
                context.registry_path.display()
            )));
        }
        let registry =
            Registry::open(&context.registry_path, OpenMode::ReadOnly).map_err(registry_error)?;
        let version: i64 = registry
            .query_one("SELECT MAX(version) FROM schema_versions", [], |row| {
                row.get(0)
            })
            .map_err(registry_error)?;
        let mut lines = vec![
            format!("Schema version: {version}"),
            String::new(),
            "Tables (rows):".into(),
        ];
        for table in TABLES {
            let count: i64 = registry
                .query_one(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                    row.get(0)
                })
                .map_err(registry_error)?;
            lines.push(format!("  {table:<20} {count}"));
        }
        lines.extend([String::new(), "Refresh staleness:".into()]);
        let now = now_seconds();
        for table in STALENESS {
            let last: i64 = registry
                .query_one(
                    &format!("SELECT COALESCE(MAX(refreshed_at), 0) FROM {table}"),
                    [],
                    |row| row.get(0),
                )
                .map_err(registry_error)?;
            let age = if last == 0 {
                "never".into()
            } else {
                format!("{} min ago", (now - last) / 60)
            };
            lines.push(format!("  {table:<20} {age}"));
        }
        lines.push(String::new());
        if context.registry_lock_path.is_file() {
            lines.push("Lock: held".into());
            let raw = fs::read_to_string(&context.registry_lock_path).map_err(|error| {
                CliError::message(format!(
                    "cannot read lock {}: {error}",
                    context.registry_lock_path.display()
                ))
            })?;
            let pretty = serde_json::from_str::<serde_json::Value>(&raw)
                .ok()
                .and_then(|value| serde_json::to_string_pretty(&value).ok())
                .unwrap_or(raw);
            lines.push(pretty);
        } else {
            lines.push("Lock: free".into());
        }
        write(&mut context, &lines.join("\n"))
    }
}

impl WaveB1HandoffCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let Some(action) = self.action else {
            return write(&mut context, usage());
        };
        match action {
            HandoffAction::Create {
                run,
                branch,
                out,
                replace,
            } => create_handoff(
                &mut context,
                run.as_deref(),
                branch.as_deref(),
                out,
                replace,
            ),
            HandoffAction::List => {
                let files = handoffs(&context)?;
                if files.is_empty() {
                    let root = canonical_handoff_root(&context).display().to_string();
                    return write(&mut context, &format!("(no handoffs at {root})"));
                }
                let output = files
                    .into_iter()
                    .map(|path| handoff_label(&context, &path))
                    .collect::<Vec<_>>()
                    .join("\n");
                write(&mut context, &output)
            }
            HandoffAction::Show { pattern } => {
                let mut files = handoffs(&context)?;
                if files.is_empty() {
                    let root = canonical_handoff_root(&context).display().to_string();
                    return write(&mut context, &format!("(no handoffs at {root})"));
                }
                if let Some(pattern) = pattern.as_deref() {
                    files.retain(|path| path.to_string_lossy().contains(pattern));
                }
                let Some(path) = files.into_iter().next() else {
                    return write_error_stdout(
                        &mut context,
                        &format!("(no handoff matching '{}')", pattern.unwrap_or_default()),
                    );
                };
                let content = read_regular_handoff(&context, &path)?;
                write_exact(&mut context, content.as_bytes())
            }
        }
    }
}

fn context(globals: CliGlobals) -> Result<ExecutionContext, CliError> {
    let cwd = std::env::current_dir()
        .map_err(|error| CliError::message(format!("cannot resolve current directory: {error}")))?;
    let mut inputs = ContextInputs::from_environment(cwd)
        .map_err(|error| CliError::message(error.to_string()))?;
    inputs.explicit_config = globals.config;
    inputs.verbosity = globals.verbosity;
    ExecutionContext::discover(inputs).map_err(|error| CliError::message(error.to_string()))
}

#[derive(Debug)]
struct RunSelection {
    id: RunId,
    state: RunState,
}

#[derive(Debug)]
struct HandoffCandidate {
    path: PathBuf,
    modified_nanos: u128,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
struct HandoffMetrics {
    artifacts: i64,
    memory: i64,
    locks: i64,
    open_issues: i64,
    drift_risk: i64,
}

fn create_handoff(
    context: &mut ExecutionContext,
    requested_run: Option<&str>,
    requested_branch: Option<&str>,
    requested_out: Option<PathBuf>,
    replace: bool,
) -> Result<(), CliError> {
    let selection = select_run(context, requested_run, requested_branch)?;
    if selection.state.status == "closed" {
        return Err(CliError::message(format!(
            "run `{}` is closed and cannot receive a new handoff",
            selection.id
        )));
    }
    if selection.state.branch.is_empty() {
        return Err(CliError::message(format!(
            "run `{}` has no recorded branch",
            selection.id
        )));
    }

    let target = context
        .runs_root
        .join(selection.id.as_str())
        .join(HANDOFF_FILE);
    let shown = if let Some(out) = requested_out {
        let resolved = normalize_output_path(&context.primary_root, &out)?;
        if resolved != target {
            return Err(CliError::message(format!(
                "--out must name the selected run's canonical handoff path {}",
                target.display()
            )));
        }
        out
    } else {
        target
            .strip_prefix(&context.primary_root)
            .map(Path::to_path_buf)
            .unwrap_or_else(|_| target.clone())
    };

    let content = render_handoff(context, &selection.state.branch)?;
    platform::publish_handoff(context, &selection, content.as_bytes(), replace)?;
    write(context, &crate::interface::canonical_display(&shown))
}

fn select_run(
    context: &ExecutionContext,
    requested_run: Option<&str>,
    requested_branch: Option<&str>,
) -> Result<RunSelection, CliError> {
    let states = platform::run_states(context)?;
    if let Some(raw_run) = requested_run {
        let run = RunId::new(raw_run)
            .map_err(|error| CliError::message(format!("invalid run `{raw_run}`: {error}")))?;
        let Some((_, state)) = states.into_iter().find(|(candidate, _)| candidate == &run) else {
            return Err(CliError::message(format!(
                "run `{}` does not exist under {}",
                run,
                context.runs_root.display()
            )));
        };
        if let Some(branch) = requested_branch.filter(|value| !value.is_empty())
            && state.branch != branch
        {
            return Err(CliError::message(format!(
                "run `{run}` records branch `{}` rather than `{branch}`",
                state.branch
            )));
        }
        return Ok(RunSelection { id: run, state });
    }

    let branch = requested_branch
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| current_branch(&context.primary_root));
    let mut matching = states
        .into_iter()
        .filter(|(_, state)| state.branch == branch)
        .collect::<Vec<_>>();
    match matching.len() {
        0 => Err(CliError::message(format!(
            "no existing run records branch `{branch}` under {}",
            context.runs_root.display()
        ))),
        1 => {
            let (id, state) = matching.remove(0);
            Ok(RunSelection { id, state })
        }
        _ => Err(CliError::message(format!(
            "multiple runs record branch `{branch}`: {}",
            matching
                .iter()
                .map(|(run, _)| run.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        ))),
    }
}

fn normalize_output_path(root: &Path, path: &Path) -> Result<PathBuf, CliError> {
    let joined = if path.is_absolute() {
        path.to_path_buf()
    } else {
        root.join(path)
    };
    let mut normalized = PathBuf::new();
    for component in joined.components() {
        match component {
            std::path::Component::Prefix(prefix) => normalized.push(prefix.as_os_str()),
            std::path::Component::RootDir => normalized.push(Path::new("/")),
            std::path::Component::CurDir => {}
            std::path::Component::Normal(part) => normalized.push(part),
            std::path::Component::ParentDir => {
                return Err(CliError::message(
                    "--out must be normalized and cannot contain `..`",
                ));
            }
        }
    }
    Ok(normalized)
}

fn render_handoff(context: &ExecutionContext, branch: &str) -> Result<String, CliError> {
    let date = DateTime::<Utc>::from_timestamp_millis(context.now_unix_millis())
        .ok_or_else(|| CliError::message("system clock is outside the supported date range"))?
        .format("%Y-%m-%d")
        .to_string();
    let metrics = handoff_metrics(context);
    let values = serde_json::json!({
        "ARTIFACTS_COUNT": metrics.artifacts.to_string(),
        "BRANCH": branch,
        "CARRY_FORWARDS": "[FILL IN]",
        "COMMITS": commits_for(&context.primary_root, branch),
        "DATE": date,
        "DRIFT_RISK_COUNT": metrics.drift_risk.to_string(),
        "FILES_OF_INTEREST": "[FILL IN]",
        "LOCK_COUNT": metrics.locks.to_string(),
        "MEM_COUNT": metrics.memory.to_string(),
        "NEXT_FOCUS": "[FILL IN]",
        "NORTH_STAR": "[FILL IN]",
        "OPEN_ISSUES_COUNT": metrics.open_issues.to_string(),
        "SESSION": Uuid::now_v7().to_string(),
    });
    let environment = shepherd::render::env::build();
    environment
        .template_from_str(shepherd::compiler::content::embedded_handoff_template())
        .map_err(|error| CliError::message(format!("cannot compile handoff template: {error}")))?
        .render(values)
        .map_err(|error| CliError::message(format!("cannot render handoff template: {error}")))
}

fn current_branch(root: &Path) -> String {
    command_output(root, &["rev-parse", "--abbrev-ref", "HEAD"])
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "unknown".into())
}

fn commits_for(root: &Path, branch: &str) -> String {
    let valid_ref = Command::new("git")
        .current_dir(root)
        .args(["rev-parse", "--verify", "--quiet", branch])
        .output()
        .is_ok_and(|output| output.status.success());
    let mut arguments = vec!["log", "--oneline", "-n", "10"];
    if valid_ref {
        arguments.push(branch);
    }
    command_output(root, &arguments)
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "(no commits)".into())
}

fn command_output(root: &Path, arguments: &[&str]) -> Option<String> {
    let output = Command::new("git")
        .current_dir(root)
        .args(arguments)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    String::from_utf8(output.stdout)
        .ok()
        .map(|value| value.trim_end_matches('\n').to_owned())
}

fn handoff_metrics(context: &ExecutionContext) -> HandoffMetrics {
    let Some(project_id) = project_id(context) else {
        return HandoffMetrics::default();
    };
    let Ok(registry) = Registry::open(&context.registry_path, OpenMode::ReadOnly) else {
        return HandoffMetrics::default();
    };
    HandoffMetrics {
        artifacts: metric(&registry, "artifacts", &project_id),
        memory: metric(&registry, "mem_entries", &project_id),
        locks: metric(&registry, "locks_history", &project_id),
        open_issues: metric(&registry, "v_open_issues", &project_id),
        drift_risk: metric(&registry, "v_drift_risk", &project_id),
    }
}

fn project_id(context: &ExecutionContext) -> Option<String> {
    let bytes = platform::read_project_identity(context).ok()?;
    serde_json::from_slice::<serde_json::Value>(&bytes)
        .ok()?
        .as_object()?
        .get("id")?
        .as_str()
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
}

fn metric(registry: &Registry, source: &str, project_id: &str) -> i64 {
    registry
        .query_one(
            &format!("SELECT COUNT(*) FROM {source} WHERE project_id = ?1"),
            params![project_id],
            |row| row.get(0),
        )
        .unwrap_or(0)
}

fn handoffs(context: &ExecutionContext) -> Result<Vec<PathBuf>, CliError> {
    let mut candidates = platform::handoffs(context)?;
    candidates.sort_by(|left, right| {
        right
            .modified_nanos
            .cmp(&left.modified_nanos)
            .then_with(|| {
                handoff_label(context, &left.path).cmp(&handoff_label(context, &right.path))
            })
    });
    Ok(candidates
        .into_iter()
        .map(|candidate| candidate.path)
        .collect())
}

fn canonical_handoff_root(context: &ExecutionContext) -> &Path {
    &context.runs_root
}

fn handoff_label(context: &ExecutionContext, path: &Path) -> String {
    if let Ok(relative) = path.strip_prefix(&context.runs_root) {
        return crate::interface::canonical_display(relative);
    }
    path.file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.to_string_lossy().into_owned())
}

fn read_regular_handoff(context: &ExecutionContext, path: &Path) -> Result<String, CliError> {
    let bytes = platform::read_handoff(context, path)?;
    String::from_utf8(bytes)
        .map_err(|_| CliError::message(format!("handoff is not valid UTF-8: {}", path.display())))
}

#[cfg(unix)]
mod platform {
    use std::{
        fs::File,
        io::{Read, Write},
        os::fd::OwnedFd,
        sync::atomic::{AtomicU64, Ordering},
        time::UNIX_EPOCH,
    };

    use rustix::fs::{
        self, AtFlags, Dir, FileType, Mode, OFlags, linkat, open, openat, renameat, unlinkat,
    };

    use super::*;

    const MAX_HANDOFF_BYTES: u64 = 1_048_576;
    const MAX_TEMP_ATTEMPTS: u32 = 100;
    static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

    pub(super) fn run_states(
        context: &ExecutionContext,
    ) -> Result<Vec<(RunId, RunState)>, CliError> {
        let root = open_absolute_directory(&context.runs_root, "open runs directory")?;
        let mut states = Vec::new();
        for name in directory_names(&root, &context.runs_root)? {
            let Ok(run) = RunId::new(&name) else {
                continue;
            };
            let run_fd = open_run_directory(context, &root, &run)?;
            let state = read_run_state(context, &run_fd, &run)?;
            states.push((run, state));
        }
        states.sort_by(|left, right| left.0.cmp(&right.0));
        Ok(states)
    }

    pub(super) fn handoffs(context: &ExecutionContext) -> Result<Vec<HandoffCandidate>, CliError> {
        let mut candidates = Vec::new();
        if path_exists_nofollow(&context.runs_root)? {
            let runs = open_absolute_directory(&context.runs_root, "open runs directory")?;
            for name in directory_names(&runs, &context.runs_root)? {
                let Ok(run) = RunId::new(&name) else {
                    continue;
                };
                let run_fd = open_run_directory(context, &runs, &run)?;
                let path = context.runs_root.join(run.as_str()).join(HANDOFF_FILE);
                if let Some(file) = open_regular_optional(&run_fd, HANDOFF_FILE, &path)? {
                    candidates.push(candidate(path, &file)?);
                }
            }
        }

        if path_exists_nofollow(&context.docs_root)? {
            let docs = open_absolute_directory(&context.docs_root, "open docs directory")?;
            collect_handoffs(
                &docs,
                &context.docs_root,
                |name| name.ends_with("handoff.md"),
                &mut candidates,
            )?;

            let legacy_root = context.docs_root.join("handoffs");
            match openat(
                &docs,
                "handoffs",
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::empty(),
            ) {
                Ok(legacy) => collect_handoffs(
                    &legacy,
                    &legacy_root,
                    |name| name.ends_with(".md"),
                    &mut candidates,
                )?,
                Err(rustix::io::Errno::NOENT) => {}
                Err(error) => {
                    return Err(path_error(
                        "open legacy handoff directory",
                        &legacy_root,
                        error,
                    ));
                }
            }
        }
        Ok(candidates)
    }

    pub(super) fn read_handoff(
        context: &ExecutionContext,
        path: &Path,
    ) -> Result<Vec<u8>, CliError> {
        if let Ok(relative) = path.strip_prefix(&context.runs_root) {
            let parts = normal_parts(relative)?;
            if parts.len() != 2 || parts[1] != HANDOFF_FILE {
                return Err(CliError::message(format!(
                    "noncanonical run handoff path: {}",
                    path.display()
                )));
            }
            let run = RunId::new(&parts[0]).map_err(|error| {
                CliError::message(format!(
                    "invalid run handoff path {}: {error}",
                    path.display()
                ))
            })?;
            let root = open_absolute_directory(&context.runs_root, "open runs directory")?;
            let run_fd = open_run_directory(context, &root, &run)?;
            let file = open_regular(&run_fd, HANDOFF_FILE, path)?;
            return read_bounded(file, path);
        }

        if let Ok(relative) = path.strip_prefix(&context.docs_root) {
            let parts = normal_parts(relative)?;
            let valid = match parts.as_slice() {
                [name] => name.ends_with("handoff.md"),
                [directory, name] => directory == "handoffs" && name.ends_with(".md"),
                _ => false,
            };
            if !valid {
                return Err(CliError::message(format!(
                    "noncanonical legacy handoff path: {}",
                    path.display()
                )));
            }
            return read_relative_file(&context.docs_root, &parts, path);
        }

        Err(CliError::message(format!(
            "handoff path is outside canonical and legacy roots: {}",
            path.display()
        )))
    }

    pub(super) fn read_project_identity(context: &ExecutionContext) -> Result<Vec<u8>, CliError> {
        let relative = context
            .project_id_path
            .strip_prefix(&context.namespace)
            .map_err(|_| {
                CliError::message(format!(
                    "project identity path escapes namespace: {}",
                    context.project_id_path.display()
                ))
            })?;
        let parts = normal_parts(relative)?;
        read_relative_file(&context.namespace, &parts, &context.project_id_path)
    }

    pub(super) fn publish_handoff(
        context: &ExecutionContext,
        selection: &RunSelection,
        bytes: &[u8],
        replace: bool,
    ) -> Result<(), CliError> {
        if bytes.len() as u64 > MAX_HANDOFF_BYTES {
            return Err(CliError::message(format!(
                "handoff is {} bytes; maximum is {MAX_HANDOFF_BYTES}",
                bytes.len()
            )));
        }
        let root = open_absolute_directory(&context.runs_root, "open runs directory")?;
        let run_fd = open_run_directory(context, &root, &selection.id)?;
        let current = read_run_state(context, &run_fd, &selection.id)?;
        if current.branch != selection.state.branch
            || current.status != selection.state.status
            || current.schema_version != selection.state.schema_version
        {
            return Err(CliError::message(format!(
                "run `{}` changed while the handoff was being rendered",
                selection.id
            )));
        }

        let target = context
            .runs_root
            .join(selection.id.as_str())
            .join(HANDOFF_FILE);
        let (temporary, mut file) = create_temp(&run_fd, &target)?;
        let result = (|| {
            file.write_all(bytes).map_err(|error| {
                CliError::message(format!("cannot write handoff temporary file: {error}"))
            })?;
            file.sync_all().map_err(|error| {
                CliError::message(format!("cannot fsync handoff temporary file: {error}"))
            })?;

            if replace {
                match fs::statat(&run_fd, HANDOFF_FILE, AtFlags::SYMLINK_NOFOLLOW) {
                    Ok(stat) if FileType::from_raw_mode(stat.st_mode).is_file() => {}
                    Ok(_) => {
                        return Err(CliError::message(format!(
                            "refusing to replace non-regular handoff {}",
                            target.display()
                        )));
                    }
                    Err(rustix::io::Errno::NOENT) => {}
                    Err(error) => {
                        return Err(path_error("inspect handoff target", &target, error));
                    }
                }
                renameat(&run_fd, &temporary, &run_fd, HANDOFF_FILE)
                    .map_err(|error| path_error("replace handoff", &target, error))?;
            } else {
                linkat(&run_fd, &temporary, &run_fd, HANDOFF_FILE, AtFlags::empty()).map_err(
                    |error| {
                        if error == rustix::io::Errno::EXIST {
                            CliError::message(format!(
                                "handoff already exists: {}; pass --replace to replace it",
                                target.display()
                            ))
                        } else {
                            path_error("publish handoff", &target, error)
                        }
                    },
                )?;
                unlinkat(&run_fd, &temporary, AtFlags::empty())
                    .map_err(|error| path_error("remove handoff temporary", &target, error))?;
            }
            fs::fsync(&run_fd)
                .map_err(|error| path_error("fsync run directory", &target, error))?;
            let published = read_bounded(open_regular(&run_fd, HANDOFF_FILE, &target)?, &target)?;
            if published != bytes {
                return Err(CliError::message(format!(
                    "published handoff did not round-trip: {}",
                    target.display()
                )));
            }
            Ok(())
        })();
        if result.is_err() {
            let _ = unlinkat(&run_fd, &temporary, AtFlags::empty());
        }
        result
    }

    fn collect_handoffs(
        directory: &OwnedFd,
        root: &Path,
        include: impl Fn(&str) -> bool,
        candidates: &mut Vec<HandoffCandidate>,
    ) -> Result<(), CliError> {
        for name in directory_names(directory, root)? {
            if !include(&name) {
                continue;
            }
            let path = root.join(&name);
            if let Some(file) = open_regular_optional(directory, &name, &path)? {
                candidates.push(candidate(path, &file)?);
            }
        }
        Ok(())
    }

    fn candidate(path: PathBuf, file: &File) -> Result<HandoffCandidate, CliError> {
        let modified = file
            .metadata()
            .and_then(|metadata| metadata.modified())
            .map_err(|error| {
                CliError::message(format!(
                    "cannot inspect handoff {}: {error}",
                    path.display()
                ))
            })?;
        let modified_nanos = modified
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0);
        Ok(HandoffCandidate {
            path,
            modified_nanos,
        })
    }

    fn directory_names(directory: &OwnedFd, path: &Path) -> Result<Vec<String>, CliError> {
        let entries = Dir::read_from(directory).map_err(|error| {
            CliError::message(format!("cannot read directory {}: {error}", path.display()))
        })?;
        let mut names = Vec::new();
        for entry in entries {
            let entry = entry.map_err(|error| {
                CliError::message(format!("cannot read directory {}: {error}", path.display()))
            })?;
            let Ok(name) = entry.file_name().to_str() else {
                continue;
            };
            if name != "." && name != ".." {
                names.push(name.to_owned());
            }
        }
        names.sort();
        Ok(names)
    }

    fn open_absolute_directory(path: &Path, operation: &str) -> Result<OwnedFd, CliError> {
        if !path.is_absolute()
            || path.components().any(|component| {
                matches!(
                    component,
                    std::path::Component::ParentDir | std::path::Component::CurDir
                )
            })
        {
            return Err(CliError::message(format!(
                "unsafe directory path: {}",
                path.display()
            )));
        }
        let mut directory = open(
            "/",
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| path_error(operation, Path::new("/"), error))?;
        let mut traversed = PathBuf::from("/");
        for component in path.components() {
            let std::path::Component::Normal(name) = component else {
                continue;
            };
            traversed.push(name);
            directory = openat(
                &directory,
                name,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::empty(),
            )
            .map_err(|error| path_error(operation, &traversed, error))?;
        }
        Ok(directory)
    }

    fn open_run_directory(
        context: &ExecutionContext,
        runs: &OwnedFd,
        run: &RunId,
    ) -> Result<OwnedFd, CliError> {
        let path = context.runs_root.join(run.as_str());
        openat(
            runs,
            run.as_str(),
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| path_error("open run directory", &path, error))
    }

    fn read_run_state(
        context: &ExecutionContext,
        run_fd: &OwnedFd,
        run: &RunId,
    ) -> Result<RunState, CliError> {
        let path = context.runs_root.join(run.as_str()).join("run.json");
        let bytes = read_bounded(open_regular(run_fd, "run.json", &path)?, &path)?;
        let state: RunState = serde_json::from_slice(&bytes).map_err(|error| {
            CliError::message(format!("invalid run document {}: {error}", path.display()))
        })?;
        if state.schema_version != 1
            || state.run != run.as_str()
            || !matches!(
                state.status.as_str(),
                "planted" | "planned" | "executing" | "closing" | "closed"
            )
        {
            return Err(CliError::message(format!(
                "invalid run identity, schema, or status in {}",
                path.display()
            )));
        }
        Ok(state)
    }

    fn open_regular(directory: &OwnedFd, name: &str, path: &Path) -> Result<File, CliError> {
        open_regular_optional(directory, name, path)?.ok_or_else(|| {
            CliError::message(format!(
                "required regular file is absent: {}",
                path.display()
            ))
        })
    }

    fn open_regular_optional(
        directory: &OwnedFd,
        name: &str,
        path: &Path,
    ) -> Result<Option<File>, CliError> {
        let descriptor = match openat(
            directory,
            name,
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        ) {
            Ok(descriptor) => descriptor,
            Err(rustix::io::Errno::NOENT) => return Ok(None),
            Err(error) => return Err(path_error("open regular file", path, error)),
        };
        let stat = fs::fstat(&descriptor)
            .map_err(|error| path_error("inspect regular file", path, error))?;
        if !FileType::from_raw_mode(stat.st_mode).is_file() {
            return Err(CliError::message(format!(
                "refusing non-regular file: {}",
                path.display()
            )));
        }
        Ok(Some(File::from(descriptor)))
    }

    fn read_relative_file(root: &Path, parts: &[String], path: &Path) -> Result<Vec<u8>, CliError> {
        let Some((file_name, parents)) = parts.split_last() else {
            return Err(CliError::message(format!(
                "file path has no relative components: {}",
                path.display()
            )));
        };
        let mut directory = open_absolute_directory(root, "open artifact root")?;
        let mut traversed = root.to_path_buf();
        for parent in parents {
            traversed.push(parent);
            directory = openat(
                &directory,
                parent,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::empty(),
            )
            .map_err(|error| path_error("open artifact directory", &traversed, error))?;
        }
        read_bounded(open_regular(&directory, file_name, path)?, path)
    }

    fn read_bounded(file: File, path: &Path) -> Result<Vec<u8>, CliError> {
        let mut bytes = Vec::new();
        file.take(MAX_HANDOFF_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|error| {
                CliError::message(format!("cannot read {}: {error}", path.display()))
            })?;
        if bytes.len() as u64 > MAX_HANDOFF_BYTES {
            return Err(CliError::message(format!(
                "file exceeds {MAX_HANDOFF_BYTES} bytes: {}",
                path.display()
            )));
        }
        Ok(bytes)
    }

    fn create_temp(directory: &OwnedFd, target: &Path) -> Result<(String, File), CliError> {
        for _ in 0..MAX_TEMP_ATTEMPTS {
            let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
            let name = format!(".{HANDOFF_FILE}.{}.{sequence:x}.tmp", std::process::id());
            match openat(
                directory,
                &name,
                OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::RUSR | Mode::WUSR,
            ) {
                Ok(descriptor) => return Ok((name, File::from(descriptor))),
                Err(rustix::io::Errno::EXIST) => continue,
                Err(error) => return Err(path_error("create handoff temporary", target, error)),
            }
        }
        Err(CliError::message(format!(
            "temporary name collision budget exhausted for {}",
            target.display()
        )))
    }

    fn normal_parts(path: &Path) -> Result<Vec<String>, CliError> {
        path.components()
            .map(|component| match component {
                std::path::Component::Normal(value) => value
                    .to_str()
                    .map(str::to_owned)
                    .ok_or_else(|| CliError::message("artifact path must be UTF-8")),
                _ => Err(CliError::message(format!(
                    "artifact path is not normalized: {}",
                    path.display()
                ))),
            })
            .collect()
    }

    fn path_exists_nofollow(path: &Path) -> Result<bool, CliError> {
        match std::fs::symlink_metadata(path) {
            Ok(metadata) if metadata.file_type().is_symlink() => Err(CliError::message(format!(
                "symbolic-link artifact root is forbidden: {}",
                path.display()
            ))),
            Ok(metadata) if metadata.is_dir() => Ok(true),
            Ok(_) => Err(CliError::message(format!(
                "artifact root is not a directory: {}",
                path.display()
            ))),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(CliError::message(format!(
                "cannot inspect artifact root {}: {error}",
                path.display()
            ))),
        }
    }

    fn path_error(operation: &str, path: &Path, error: rustix::io::Errno) -> CliError {
        CliError::message(format!("{operation} {}: {error}", path.display()))
    }
}

#[cfg(not(unix))]
mod platform {
    //! The non-unix twin of the descriptor-anchored run-artifact reader.
    //!
    //! Same verdicts, same messages, same ordering as the unix module: run
    //! states sorted by run id, handoff candidates carrying their modification
    //! time so `list` renders newest first, and the same refusal for a
    //! noncanonical path. Only the anchoring differs -- see `crate::safe_fs`.

    use std::path::PathBuf;

    use super::*;
    use crate::safe_fs;

    const MAX_HANDOFF_BYTES: u64 = 1_048_576;

    pub(super) fn run_states(
        context: &ExecutionContext,
    ) -> Result<Vec<(RunId, RunState)>, CliError> {
        let mut states = Vec::new();
        for name in directory_names(&context.runs_root)? {
            let Ok(run) = RunId::new(&name) else {
                continue;
            };
            states.push((run.clone(), read_run_state(context, &run)?));
        }
        states.sort_by(|left, right| left.0.cmp(&right.0));
        Ok(states)
    }

    pub(super) fn handoffs(context: &ExecutionContext) -> Result<Vec<HandoffCandidate>, CliError> {
        let mut candidates = Vec::new();
        for name in directory_names(&context.runs_root)? {
            let Ok(run) = RunId::new(&name) else {
                continue;
            };
            let path = context.runs_root.join(run.as_str()).join(HANDOFF_FILE);
            if safe_fs::regular_exists(&path).map_err(|error| read_error(&path, error))? {
                candidates.push(candidate(path)?);
            }
        }

        collect_handoffs(
            &context.docs_root,
            |name| name.ends_with("handoff.md"),
            &mut candidates,
        )?;
        // The legacy directory is read-only and optional: a project that never
        // had one is not an error, it just has no legacy documents.
        collect_handoffs(
            &context.docs_root.join("handoffs"),
            |name| name.ends_with(".md"),
            &mut candidates,
        )?;
        Ok(candidates)
    }

    pub(super) fn read_handoff(
        context: &ExecutionContext,
        path: &Path,
    ) -> Result<Vec<u8>, CliError> {
        if let Ok(relative) = path.strip_prefix(&context.runs_root) {
            let parts = normal_parts(relative)?;
            if parts.len() != 2 || parts[1] != HANDOFF_FILE {
                return Err(CliError::message(format!(
                    "noncanonical run handoff path: {}",
                    path.display()
                )));
            }
            RunId::new(&parts[0]).map_err(|error| {
                CliError::message(format!(
                    "invalid run handoff path {}: {error}",
                    path.display()
                ))
            })?;
            return read_bounded(path);
        }

        if let Ok(relative) = path.strip_prefix(&context.docs_root) {
            let parts = normal_parts(relative)?;
            let valid = match parts.as_slice() {
                [name] => name.ends_with("handoff.md"),
                [directory, name] => directory == "handoffs" && name.ends_with(".md"),
                _ => false,
            };
            if !valid {
                return Err(CliError::message(format!(
                    "noncanonical legacy handoff path: {}",
                    path.display()
                )));
            }
            return read_bounded(path);
        }

        Err(CliError::message(format!(
            "handoff path is outside canonical and legacy roots: {}",
            path.display()
        )))
    }

    pub(super) fn read_project_identity(context: &ExecutionContext) -> Result<Vec<u8>, CliError> {
        let relative = context
            .project_id_path
            .strip_prefix(&context.namespace)
            .map_err(|_| {
                CliError::message(format!(
                    "project identity path escapes namespace: {}",
                    context.project_id_path.display()
                ))
            })?;
        normal_parts(relative)?;
        read_bounded(&context.project_id_path)
    }

    pub(super) fn publish_handoff(
        context: &ExecutionContext,
        selection: &RunSelection,
        bytes: &[u8],
        replace: bool,
    ) -> Result<(), CliError> {
        if bytes.len() as u64 > MAX_HANDOFF_BYTES {
            return Err(CliError::message(format!(
                "handoff is {} bytes; maximum is {MAX_HANDOFF_BYTES}",
                bytes.len()
            )));
        }
        // Re-read the run under the same rules the renderer used. A run that
        // moved while the handoff was being written would publish a document
        // describing a state that no longer exists.
        let current = read_run_state(context, &selection.id)?;
        if current.branch != selection.state.branch
            || current.status != selection.state.status
            || current.schema_version != selection.state.schema_version
        {
            return Err(CliError::message(format!(
                "run `{}` changed while the handoff was being rendered",
                selection.id
            )));
        }

        let target = context
            .runs_root
            .join(selection.id.as_str())
            .join(HANDOFF_FILE);
        if replace {
            match std::fs::symlink_metadata(&target) {
                Ok(metadata) if metadata.is_file() && !metadata.file_type().is_symlink() => {}
                Ok(_) => {
                    return Err(CliError::message(format!(
                        "refusing to replace non-regular handoff {}",
                        target.display()
                    )));
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => {
                    return Err(CliError::message(format!(
                        "cannot inspect handoff target {}: {error}",
                        target.display()
                    )));
                }
            }
            safe_fs::replace_atomic(&target, bytes).map_err(|error| {
                CliError::message(format!(
                    "cannot replace handoff {}: {error}",
                    target.display()
                ))
            })
        } else {
            match safe_fs::write_no_clobber(&target, bytes) {
                Ok(true) => Ok(()),
                Ok(false) => Err(CliError::message(format!(
                    "handoff already exists: {}",
                    target.display()
                ))),
                Err(error) => Err(CliError::message(format!(
                    "cannot publish handoff {}: {error}",
                    target.display()
                ))),
            }
        }
    }

    /// An absent directory contributes nothing rather than failing: `list` on a
    /// project with no legacy documents must render the canonical ones, not an
    /// error.
    fn collect_handoffs(
        root: &Path,
        accept: impl Fn(&str) -> bool,
        candidates: &mut Vec<HandoffCandidate>,
    ) -> Result<(), CliError> {
        let names = match safe_fs::regular_children(root) {
            Ok(names) => names,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(error) => return Err(read_error(root, error)),
        };
        for name in names {
            if accept(&name) {
                candidates.push(candidate(root.join(name))?);
            }
        }
        Ok(())
    }

    fn candidate(path: PathBuf) -> Result<HandoffCandidate, CliError> {
        let modified = std::fs::symlink_metadata(&path)
            .and_then(|metadata| metadata.modified())
            .map_err(|error| {
                CliError::message(format!(
                    "cannot inspect handoff {}: {error}",
                    path.display()
                ))
            })?;
        let modified_nanos = modified
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0);
        Ok(HandoffCandidate {
            path,
            modified_nanos,
        })
    }

    /// Directory children of the runs root, sorted. An absent root is an empty
    /// list: a project that has never run has no runs, which is not a failure.
    fn directory_names(root: &Path) -> Result<Vec<String>, CliError> {
        match safe_fs::directory_children(root) {
            Ok(names) => Ok(names),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Vec::new()),
            Err(error) => Err(read_error(root, error)),
        }
    }

    fn read_run_state(context: &ExecutionContext, run: &RunId) -> Result<RunState, CliError> {
        let path = context.runs_root.join(run.as_str()).join("run.json");
        let bytes = read_bounded(&path)?;
        let state: RunState = serde_json::from_slice(&bytes).map_err(|error| {
            CliError::message(format!("invalid run document {}: {error}", path.display()))
        })?;
        if state.schema_version != 1
            || state.run != run.as_str()
            || !matches!(
                state.status.as_str(),
                "planted" | "planned" | "executing" | "closing" | "closed"
            )
        {
            return Err(CliError::message(format!(
                "invalid run identity, schema, or status in {}",
                path.display()
            )));
        }
        Ok(state)
    }

    fn read_bounded(path: &Path) -> Result<Vec<u8>, CliError> {
        safe_fs::read_regular_nofollow(path, MAX_HANDOFF_BYTES)
            .map_err(|error| read_error(path, error))
    }

    fn read_error(path: &Path, error: std::io::Error) -> CliError {
        CliError::message(format!("cannot read {}: {error}", path.display()))
    }

    fn normal_parts(path: &Path) -> Result<Vec<String>, CliError> {
        let mut parts = Vec::new();
        for component in path.components() {
            match component {
                std::path::Component::Normal(part) => parts.push(
                    part.to_str()
                        .ok_or_else(|| {
                            CliError::message(format!("path is not UTF-8: {}", path.display()))
                        })?
                        .to_owned(),
                ),
                _ => {
                    return Err(CliError::message(format!(
                        "path is not normalized: {}",
                        path.display()
                    )));
                }
            }
        }
        Ok(parts)
    }
}

fn usage() -> &'static str {
    "shepherd handoff <create|list|show> [args]\n\n  create [--run=<id>] [--branch=<name>] [--out=<canonical-path>] [--replace]\n      Render one existing run's canonical runs/<run>/handoff.md.\n\n  list\n      List canonical run handoffs newest first, plus legacy documents read-only.\n\n  show [<run|branch|date>]\n      Print the newest matching handoff (no argument = newest)."
}
fn now_seconds() -> i64 {
    i64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    )
    .unwrap_or(i64::MAX)
}
fn write(context: &mut ExecutionContext, output: &str) -> Result<(), CliError> {
    let mut bytes = output.as_bytes().to_vec();
    bytes.push(b'\n');
    context
        .write_stdout(&bytes)
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

fn write_exact(context: &mut ExecutionContext, bytes: &[u8]) -> Result<(), CliError> {
    context
        .write_stdout(bytes)
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

fn write_error_stdout(context: &mut ExecutionContext, output: &str) -> Result<(), CliError> {
    write(context, output)?;
    Err(CliError::reported())
}
fn registry_error(error: shepherd::registry::Error) -> CliError {
    CliError::message(error.to_string())
}
