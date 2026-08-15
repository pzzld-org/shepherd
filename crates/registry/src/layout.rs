//! The layout-v5 filesystem migration planner and executor.
//!
//! This module is the only Rust writer for the namespace migration. Planning is
//! read-only and deterministic. Execution is opt-in, snapshots every source
//! before mutation, refuses symlink boundaries and destination collisions, and
//! leaves rollback evidence behind after a failure.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write as _;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const MAX_FILES: usize = 100_000;
const MAX_BYTES: u64 = 100 * 1024 * 1024;
static SNAPSHOT_COUNTER: AtomicU64 = AtomicU64::new(0);
const RETIRED_ROOTS: &[&str] = &[
    "archive",
    "cache",
    "dispatch",
    "discoveries",
    "dispatcher-patches",
    "insights",
    "learnings",
    "logs",
    "memory",
    "pauses",
    "plans",
    "reports",
    "scripts",
    "snapshots",
    "styles",
    "tmp",
    "types",
];
const RUN_FILES: &[&str] = &[
    "seed.md",
    "mesh.md",
    "plan.md",
    "phase0.md",
    "close.md",
    "handoff.md",
    "dogfood.md",
];

/// The namespace being migrated. Project and user-home mutations are never
/// authorized by the same option.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum PlanScope {
    Project,
    UserHome,
}

/// The operator authorization required by [`LayoutPlan::execute`].
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Authorization {
    Project,
    UserHome,
}

/// A single deterministic manifest action.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum PlanAction {
    Move,
    Deduplicated,
    RemoveDirectory,
    RemoveFile,
    Rewrite,
}

/// One source-to-destination decision, including content provenance.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ManifestEntry {
    pub source: String,
    pub destination: String,
    pub classification: String,
    pub owner: String,
    pub provenance: String,
    pub byte_size: u64,
    pub sha256: String,
    pub action: PlanAction,
}

/// Stable JSON document emitted by a dry run.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct LayoutManifest {
    pub schema: String,
    pub scope: PlanScope,
    pub namespace: String,
    pub entries: Vec<ManifestEntry>,
}

/// Execution controls. The default is dry-run-safe: it has no authorization.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MigrationOptions {
    pub authorization: Option<Authorization>,
    pub confirm: bool,
    pub snapshot_dir: Option<PathBuf>,
    pub max_files: usize,
    pub max_bytes: u64,
}

impl Default for MigrationOptions {
    fn default() -> Self {
        Self {
            authorization: None,
            confirm: false,
            snapshot_dir: None,
            max_files: MAX_FILES,
            max_bytes: MAX_BYTES,
        }
    }
}

/// Evidence returned after a successful mutation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionReport {
    pub snapshot_dir: PathBuf,
    pub moved: usize,
    pub deduplicated: usize,
    pub removed_directories: usize,
    pub removed_files: usize,
    pub rewritten: usize,
}

/// Failures are explicit so callers can distinguish an unsafe input from a
/// collision or an operator authorization refusal.
#[derive(Debug, thiserror::Error)]
pub enum LayoutError {
    #[error("layout path does not exist: {0}")]
    Missing(PathBuf),
    #[error("unsafe layout path {path}: {reason}")]
    UnsafePath { path: PathBuf, reason: String },
    #[error("malformed run state {path}: {reason}")]
    MalformedRun { path: PathBuf, reason: String },
    #[error("layout destination collision at {destination}: {sources}")]
    Collision {
        destination: PathBuf,
        sources: String,
    },
    #[error("invalid layout input {0}")]
    InvalidInput(String),
    #[error("{0} authorization is required before mutation")]
    Authorization(&'static str),
    #[error("--confirm is required before layout mutation")]
    ConfirmationRequired,
    #[error("snapshot limit exceeded: {files} files, {bytes} bytes")]
    SnapshotLimit { files: usize, bytes: u64 },
    #[error("layout I/O at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("layout serialization: {0}")]
    Serialization(#[from] serde_json::Error),
}

type Result<T> = std::result::Result<T, LayoutError>;

/// A read-only migration plan. Constructing a plan never creates a directory
/// or changes a file.
#[derive(Clone, Debug)]
pub struct LayoutPlan {
    scope: PlanScope,
    namespace: PathBuf,
    manifest: LayoutManifest,
    rewrites: BTreeMap<PathBuf, Vec<u8>>,
}

impl LayoutPlan {
    /// Plan the project namespace. `runs` must be the configured canonical
    /// runs root and must remain below the namespace.
    pub fn project(namespace: impl AsRef<Path>, runs: impl AsRef<Path>) -> Result<Self> {
        Self::build(PlanScope::Project, namespace.as_ref(), runs.as_ref())
    }

    /// Plan the user-default namespace. User home has no run root. Direct
    /// canonical config candidates are preserved; obsolete profile, style,
    /// template, log, and plugin inputs are eligible for snapshot retirement.
    pub fn user_home(namespace: impl AsRef<Path>) -> Result<Self> {
        let namespace = namespace.as_ref();
        ensure_directory(namespace)?;
        let runs = namespace.join("__no-project-runs__");
        let mut plan = Self::build(PlanScope::UserHome, namespace, &runs)?;
        plan.manifest
            .entries
            .retain(|entry| entry.classification != "run");
        Ok(plan)
    }

    pub fn scope(&self) -> PlanScope {
        self.scope
    }

    pub fn namespace(&self) -> &Path {
        &self.namespace
    }

    pub fn manifest(&self) -> &LayoutManifest {
        &self.manifest
    }

    /// Compact, stable JSON with entries sorted by source and destination.
    pub fn manifest_json(&self) -> Result<String> {
        Ok(serde_json::to_string_pretty(&self.manifest)? + "\n")
    }

    /// Apply the plan after an explicit scope authorization and confirmation.
    pub fn execute(&self, options: &MigrationOptions) -> Result<ExecutionReport> {
        if !options.confirm {
            return Err(LayoutError::ConfirmationRequired);
        }
        let required = match self.scope {
            PlanScope::Project => Authorization::Project,
            PlanScope::UserHome => Authorization::UserHome,
        };
        if options.authorization != Some(required) {
            return Err(LayoutError::Authorization(match self.scope {
                PlanScope::Project => "project",
                PlanScope::UserHome => "user-home",
            }));
        }
        let requested_evidence_root = options
            .snapshot_dir
            .clone()
            .unwrap_or_else(default_snapshot_dir);
        let snapshot_dir = self.snapshot(&requested_evidence_root, options)?;
        let evidence_root = snapshot_dir
            .parent()
            .ok_or_else(|| LayoutError::InvalidInput("snapshot has no evidence root".into()))?;
        write_atomic(
            &evidence_root.join("manifest.json"),
            self.manifest_json()?.as_bytes(),
        )?;
        write_atomic(
            &evidence_root.join("rollback.sh"),
            rollback_commands(self).as_bytes(),
        )?;

        let mut report = ExecutionReport {
            snapshot_dir,
            moved: 0,
            deduplicated: 0,
            removed_directories: 0,
            removed_files: 0,
            rewritten: 0,
        };
        for entry in &self.manifest.entries {
            let source = Path::new(&entry.source);
            let destination = Path::new(&entry.destination);
            match entry.action {
                PlanAction::Move => {
                    move_verified(source, destination, &entry.sha256)?;
                    report.moved += 1;
                }
                PlanAction::Deduplicated => {
                    if destination.exists() && sha256_path(destination)? == entry.sha256 {
                        remove_file_nofollow(source)?;
                        report.deduplicated += 1;
                    }
                }
                PlanAction::Rewrite => {
                    let bytes = self.rewrites.get(source).ok_or_else(|| {
                        LayoutError::InvalidInput(format!(
                            "missing rewrite payload for {}",
                            source.display()
                        ))
                    })?;
                    write_atomic(destination, bytes)?;
                    report.rewritten += 1;
                }
                PlanAction::RemoveFile => {
                    remove_file_nofollow(source)?;
                    report.removed_files += 1;
                }
                PlanAction::RemoveDirectory => {
                    if source.exists() {
                        fs::remove_dir(source).map_err(|source_error| LayoutError::Io {
                            path: source.to_path_buf(),
                            source: source_error,
                        })?;
                        report.removed_directories += 1;
                    }
                }
            }
        }
        Ok(report)
    }

    fn build(scope: PlanScope, namespace: &Path, runs: &Path) -> Result<Self> {
        ensure_directory(namespace)?;
        if scope == PlanScope::Project {
            ensure_below(namespace, runs)?;
        }
        let validated_runs = if scope == PlanScope::Project && runs.exists() {
            validate_runs(runs)?
        } else {
            ValidatedRuns::default()
        };
        let mut candidates = Vec::new();
        walk(namespace, namespace, &mut candidates)?;
        let mut entries = Vec::new();
        let mut rewrites = BTreeMap::new();
        let mut destinations: BTreeMap<PathBuf, (String, String)> = BTreeMap::new();
        for candidate in candidates {
            if candidate.path == namespace {
                continue;
            }
            let relative =
                candidate
                    .path
                    .strip_prefix(namespace)
                    .map_err(|_| LayoutError::UnsafePath {
                        path: candidate.path.clone(),
                        reason: "path escaped namespace".into(),
                    })?;
            let components: Vec<_> = relative.components().collect();
            let Some(first) = components.first().and_then(|part| match part {
                Component::Normal(value) => value.to_str(),
                _ => None,
            }) else {
                continue;
            };
            if candidate.kind == EntryKind::File
                && candidate.path.file_name().and_then(|name| name.to_str()) == Some(".gitkeep")
                && fs::metadata(&candidate.path)
                    .map_err(|source| io(&candidate.path, source))?
                    .len()
                    == 0
            {
                entries.push(ManifestEntry {
                    source: candidate.path.display().to_string(),
                    destination: String::new(),
                    classification: "empty-placeholder".into(),
                    owner: owner(scope).into(),
                    provenance: "retired empty .gitkeep".into(),
                    byte_size: 0,
                    sha256: sha256_path(&candidate.path)?,
                    action: PlanAction::RemoveFile,
                });
                continue;
            }
            if candidate.kind == EntryKind::File
                && let Some((classification, provenance)) =
                    removable_legacy_file(scope, relative, &candidate.path)?
            {
                entries.push(ManifestEntry {
                    source: candidate.path.display().to_string(),
                    destination: String::new(),
                    classification,
                    owner: owner(scope).into(),
                    provenance,
                    byte_size: fs::metadata(&candidate.path)
                        .map_err(|source| io(&candidate.path, source))?
                        .len(),
                    sha256: sha256_path(&candidate.path)?,
                    action: PlanAction::RemoveFile,
                });
                continue;
            }
            if candidate.kind == EntryKind::File
                && components.len() == 1
                && is_canonical_config_candidate(first)
            {
                let original =
                    fs::read(&candidate.path).map_err(|source| io(&candidate.path, source))?;
                let rewritten = rewrite_config_for_layout_v5(&original);
                if rewritten != original {
                    let sha256 = sha256_bytes(&rewritten);
                    let byte_size = u64::try_from(rewritten.len()).unwrap_or(u64::MAX);
                    rewrites.insert(candidate.path.clone(), rewritten);
                    entries.push(ManifestEntry {
                        source: candidate.path.display().to_string(),
                        destination: candidate.path.display().to_string(),
                        classification: "project-config".into(),
                        owner: owner(scope).into(),
                        provenance: "removed retired layout-v5 configuration keys".into(),
                        byte_size,
                        sha256,
                        action: PlanAction::Rewrite,
                    });
                }
                continue;
            }
            if is_canonical(
                scope,
                &components,
                first,
                &candidate.path,
                runs,
                candidate.kind,
            ) {
                continue;
            }
            let Some((destination, classification, provenance)) = classify(
                scope,
                namespace,
                runs,
                &validated_runs,
                relative,
                candidate.kind,
            )?
            else {
                continue;
            };
            if candidate.kind == EntryKind::Directory {
                entries.push(ManifestEntry {
                    source: candidate.path.display().to_string(),
                    destination: destination.display().to_string(),
                    classification,
                    owner: owner(scope).into(),
                    provenance,
                    byte_size: 0,
                    sha256: String::new(),
                    action: PlanAction::RemoveDirectory,
                });
                continue;
            }
            let sha256 = sha256_path(&candidate.path)?;
            let byte_size = fs::metadata(&candidate.path)
                .map_err(|source| io(&candidate.path, source))?
                .len();
            let action = match destinations.get(&destination) {
                Some((_, previous_hash)) if previous_hash != &sha256 => {
                    return Err(LayoutError::Collision {
                        destination,
                        sources: format!("{} and {}", candidate.path.display(), previous_hash),
                    });
                }
                Some(_) => PlanAction::Deduplicated,
                None if destination.exists() => {
                    ensure_regular_file(&destination)?;
                    if sha256_path(&destination)? != sha256 {
                        return Err(LayoutError::Collision {
                            destination,
                            sources: candidate.path.display().to_string(),
                        });
                    }
                    PlanAction::Deduplicated
                }
                None => PlanAction::Move,
            };
            destinations.insert(
                destination.clone(),
                (candidate.path.display().to_string(), sha256.clone()),
            );
            entries.push(ManifestEntry {
                source: candidate.path.display().to_string(),
                destination: destination.display().to_string(),
                classification,
                owner: owner(scope).into(),
                provenance,
                byte_size,
                sha256,
                action,
            });
        }
        entries.sort_by(|a, b| {
            let action_order = |action: &PlanAction| {
                if matches!(
                    *action,
                    PlanAction::RemoveDirectory | PlanAction::RemoveFile
                ) {
                    1_usize
                } else {
                    0_usize
                }
            };
            action_order(&a.action)
                .cmp(&action_order(&b.action))
                .then_with(|| {
                    if matches!(
                        a.action,
                        PlanAction::RemoveDirectory | PlanAction::RemoveFile
                    ) && matches!(
                        b.action,
                        PlanAction::RemoveDirectory | PlanAction::RemoveFile
                    ) {
                        b.source
                            .matches(std::path::MAIN_SEPARATOR)
                            .count()
                            .cmp(&a.source.matches(std::path::MAIN_SEPARATOR).count())
                    } else {
                        std::cmp::Ordering::Equal
                    }
                })
                .then(a.source.cmp(&b.source))
                .then(a.destination.cmp(&b.destination))
        });
        Ok(Self {
            scope,
            namespace: namespace.to_path_buf(),
            manifest: LayoutManifest {
                schema: "layout-v5".into(),
                scope,
                namespace: namespace.display().to_string(),
                entries,
            },
            rewrites,
        })
    }

    fn snapshot(&self, requested_root: &Path, options: &MigrationOptions) -> Result<PathBuf> {
        let mut files = 0;
        let mut bytes: u64 = 0;
        for entry in &self.manifest.entries {
            if entry.action == PlanAction::RemoveDirectory {
                continue;
            }
            files += 1;
            let source = Path::new(&entry.source);
            bytes = bytes.saturating_add(
                fs::metadata(source)
                    .map_err(|source_error| io(source, source_error))?
                    .len(),
            );
            if files > options.max_files || bytes > options.max_bytes {
                return Err(LayoutError::SnapshotLimit { files, bytes });
            }
        }
        let evidence_root = create_snapshot_root(requested_root, &self.namespace)?;
        let before = evidence_root.join("before");
        fs::create_dir(&before).map_err(|source| io(&before, source))?;
        for entry in &self.manifest.entries {
            if entry.action == PlanAction::RemoveDirectory {
                continue;
            }
            let source = Path::new(&entry.source);
            let relative =
                source
                    .strip_prefix(&self.namespace)
                    .map_err(|_| LayoutError::UnsafePath {
                        path: source.to_path_buf(),
                        reason: "snapshot source escaped namespace".into(),
                    })?;
            let destination = before.join(relative);
            if let Some(parent) = destination.parent() {
                fs::create_dir_all(parent).map_err(|source_error| io(parent, source_error))?;
            }
            fs::copy(source, &destination)
                .map_err(|source_error| io(&destination, source_error))?;
        }
        Ok(before)
    }
}

fn create_snapshot_root(requested: &Path, namespace: &Path) -> Result<PathBuf> {
    let absolute = if requested.is_absolute() {
        requested.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|source| io(requested, source))?
            .join(requested)
    };
    let name = absolute.file_name().ok_or_else(|| {
        LayoutError::InvalidInput(format!(
            "snapshot directory has no final component: {}",
            requested.display()
        ))
    })?;
    let parent = absolute.parent().ok_or_else(|| {
        LayoutError::InvalidInput(format!(
            "snapshot directory has no parent: {}",
            requested.display()
        ))
    })?;
    let parent = fs::canonicalize(parent).map_err(|source| io(parent, source))?;
    let root = parent.join(name);
    let namespace = fs::canonicalize(namespace).map_err(|source| io(namespace, source))?;
    if root.starts_with(&namespace) {
        return Err(LayoutError::UnsafePath {
            path: root,
            reason: "snapshot directory must be outside the namespace being migrated".into(),
        });
    }
    fs::create_dir(&root).map_err(|source| LayoutError::UnsafePath {
        path: root.clone(),
        reason: format!("snapshot evidence root must be new and cannot be a symlink: {source}"),
    })?;
    Ok(root)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum EntryKind {
    File,
    Directory,
}

#[derive(Clone, Debug)]
struct Candidate {
    path: PathBuf,
    kind: EntryKind,
}

/// Run identities admitted by validated `run.json` documents. Legacy aliases
/// only resolve through this index: an exact run slug or an exact unique
/// branch. There is deliberately no normalized, substring, or dotted-id form.
#[derive(Clone, Debug, Default)]
struct ValidatedRuns {
    ids: BTreeSet<String>,
    branches: BTreeMap<String, BTreeSet<String>>,
}

impl ValidatedRuns {
    fn resolve(&self, reference: &str, source: &Path) -> Result<String> {
        if self.ids.contains(reference) {
            return Ok(reference.into());
        }
        match self.branches.get(reference) {
            Some(matches) if matches.len() == 1 => Ok(matches
                .first()
                .expect("one matching run is present")
                .clone()),
            Some(matches) => Err(LayoutError::InvalidInput(format!(
                "ambiguous legacy run reference `{reference}` from `{}` matches {}",
                source.display(),
                matches.iter().cloned().collect::<Vec<_>>().join(", "),
            ))),
            None => Err(LayoutError::InvalidInput(format!(
                "cannot map legacy run reference `{reference}` from `{}` to a canonical runs/<run>/run.json; only an exact run id or a unique exact branch is accepted",
                source.display(),
            ))),
        }
    }
}

fn classify(
    scope: PlanScope,
    namespace: &Path,
    runs: &Path,
    validated_runs: &ValidatedRuns,
    relative: &Path,
    kind: EntryKind,
) -> Result<Option<(PathBuf, String, String)>> {
    let parts: Vec<_> = relative.components().collect();
    let first = parts.first().and_then(|part| match part {
        Component::Normal(value) => value.to_str(),
        _ => None,
    });
    let Some(first) = first else { return Ok(None) };
    if scope == PlanScope::UserHome {
        if matches!(first, "styles" | "profiles" | "templates") && kind == EntryKind::Directory {
            return Ok(Some((
                PathBuf::new(),
                "retired-directory".into(),
                format!("retired user-home {first} root"),
            )));
        }
        if matches!(first, "logs" | "plugin-data") && kind == EntryKind::Directory {
            return Ok(Some((
                namespace.join(first),
                "retired-directory".into(),
                format!("obsolete user-home {first} root"),
            )));
        }
        return Err(LayoutError::InvalidInput(format!(
            "user-home path is not a supported input: {}",
            relative.display()
        )));
    }
    let name = relative
        .file_name()
        .and_then(|v| v.to_str())
        .unwrap_or_default();
    if relative == Path::new("CONVENTIONS.md") && kind == EntryKind::File {
        return Ok(Some((
            namespace.join("docs").join("CONVENTIONS.md"),
            "cross-run".into(),
            "flattened namespace convention reference".into(),
        )));
    }
    if first == "docs" || first == "ctx" {
        if kind == EntryKind::File && parts.len() > 2 {
            return Ok(Some((
                namespace.join(first).join(name),
                if first == "ctx" {
                    "knowledge"
                } else {
                    "cross-run"
                }
                .into(),
                format!("flattened {first} descendant"),
            )));
        }
        if kind == EntryKind::Directory && parts.len() > 1 {
            return Ok(Some((
                namespace.join(first),
                "retired-directory".into(),
                "flat namespace".into(),
            )));
        }
        return Ok(None);
    }
    if first == "plans" || first == "reports" {
        if kind == EntryKind::File {
            if let Some((run, artifact)) = run_artifact(name, runs) {
                return Ok(Some((
                    runs.join(run).join(artifact),
                    "run".into(),
                    format!("legacy {first} artifact mapped by validated run.json"),
                )));
            }
            return Ok(Some((
                namespace.join("docs").join(name),
                "cross-run-historical".into(),
                format!("legacy {first} without deterministic run mapping"),
            )));
        }
        return Ok(Some((
            namespace.join("docs"),
            "retired-directory".into(),
            format!("retired {first}"),
        )));
    }
    if matches!(first, "styles" | "profiles") && kind == EntryKind::Directory {
        return Ok(Some((
            PathBuf::new(),
            "retired-directory".into(),
            format!("retired project {first} root"),
        )));
    }
    if first == "cache"
        && parts.get(1).and_then(|part| part.as_os_str().to_str()) == Some("snapshots")
        && kind == EntryKind::File
    {
        let run = run_from_snapshot_json(namespace.join(relative).as_path(), validated_runs)?;
        let tail = parts[2..].iter().fold(PathBuf::new(), |mut path, part| {
            path.push(part.as_os_str());
            path
        });
        return Ok(Some((
            runs.join(&run).join("snapshots").join(tail),
            "run".into(),
            "snapshot JSON mapped by exact validated run or branch".into(),
        )));
    }
    if first == "logs" {
        if parts.get(1).and_then(|part| part.as_os_str().to_str()) == Some("hooks") {
            if kind == EntryKind::Directory {
                return Ok(Some((
                    namespace.join("docs"),
                    "retired-directory".into(),
                    "retired hook logs root".into(),
                )));
            }
            return Err(LayoutError::InvalidInput(format!(
                "nonempty hook log cannot be assigned to one run: {}",
                relative.display()
            )));
        }
        if kind == EntryKind::File && name.starts_with("events") && name.ends_with(".jsonl") {
            let run = run_from_event_jsonl(namespace.join(relative).as_path(), validated_runs)?;
            return Ok(Some((
                runs.join(&run).join("events").join(name),
                "run".into(),
                "event rows mapped by one exact validated run or branch".into(),
            )));
        }
        if kind == EntryKind::Directory {
            return Ok(Some((
                namespace.join("docs"),
                "retired-directory".into(),
                "retired event logs root".into(),
            )));
        }
    }
    if first == "dispatcher-patches" && kind == EntryKind::File && parts.len() == 2 {
        let run = run_from_dispatcher_patch(name, validated_runs, relative)?;
        return Ok(Some((
            runs.join(&run).join("reports").join(name),
            "run".into(),
            "dispatcher patch mapped by explicit run-prefix".into(),
        )));
    }
    if (first == "dispatch" || first == "snapshots" || first == "logs") && parts.len() >= 2 {
        let reference = parts[1].as_os_str().to_string_lossy();
        let run = validated_runs.resolve(&reference, relative)?;
        let tail = parts[2..].iter().fold(PathBuf::new(), |mut path, part| {
            path.push(part.as_os_str());
            path
        });
        let bucket = match first {
            "dispatch" => "dispatch",
            "snapshots" => "snapshots",
            _ => "events",
        };
        return Ok(Some((
            runs.join(&run).join(bucket).join(tail),
            "run".into(),
            if reference == run {
                "validated run.json mapping".into()
            } else {
                "validated run.json exact branch mapping".into()
            },
        )));
    }
    if first == "memory" {
        if parts.get(1).and_then(|part| part.as_os_str().to_str()) == Some("snapshots")
            && parts.len() >= 4
        {
            let run = parts[2].as_os_str().to_string_lossy();
            let run = validated_runs.resolve(&run, relative)?;
            let tail = parts[3..].iter().fold(PathBuf::new(), |mut path, part| {
                path.push(part.as_os_str());
                path
            });
            return Ok(Some((
                runs.join(&run).join("snapshots").join(tail),
                "run".into(),
                "validated run.json mapping".into(),
            )));
        }
        if kind == EntryKind::File {
            return Ok(Some((
                namespace.join("docs").join(name),
                "cross-run-historical".into(),
                "legacy memory knowledge".into(),
            )));
        }
    }
    if RETIRED_ROOTS.contains(&first) {
        if kind == EntryKind::File {
            return Ok(Some((
                namespace.join("docs").join(name),
                "cross-run-historical".into(),
                format!("retired {first} artifact"),
            )));
        }
        return Ok(Some((
            namespace.join(first),
            "retired-directory".into(),
            format!("retired {first}"),
        )));
    }
    Ok(None)
}

fn run_artifact<'a>(name: &'a str, runs: &Path) -> Option<(&'a str, &'static str)> {
    for suffix in [
        ".seed.md",
        ".plan.md",
        ".phase0.md",
        ".close.md",
        ".handoff.md",
    ] {
        if let Some(run) = name.strip_suffix(suffix)
            && run_state_exists(runs, run)
            && RUN_FILES.contains(&suffix.trim_start_matches('.'))
        {
            return Some((run, suffix.trim_start_matches('.')));
        }
    }
    None
}

fn is_canonical(
    scope: PlanScope,
    parts: &[Component<'_>],
    first: &str,
    path: &Path,
    runs: &Path,
    kind: EntryKind,
) -> bool {
    if scope == PlanScope::UserHome {
        return matches!(first, "shepherd.toml" | "shepherd.local.toml")
            || (matches!(
                first,
                "shepherd.claude.toml" | "shepherd.codex.toml" | "shepherd.pi.toml"
            ) && parts.len() == 1);
    }
    if matches!(
        first,
        "shepherd.toml" | "shepherd.local.toml" | "project.json" | "docs" | "ctx" | "templates"
    ) || first.starts_with("shepherd.") && first.ends_with(".toml")
    {
        if first == "docs" || first == "ctx" {
            return parts.len() == 2 && kind == EntryKind::File;
        }
        return true;
    }
    if path.starts_with(runs) {
        return true;
    }
    matches!(
        first,
        "shepherd.db"
            | "shepherd.db-wal"
            | "shepherd.db-shm"
            | "shepherd.db-journal"
            | "shepherd.lock"
    )
}

fn is_canonical_config_candidate(name: &str) -> bool {
    name == "shepherd.toml"
        || name == "shepherd.local.toml"
        || name.starts_with("shepherd.") && name.ends_with(".toml")
}

fn removable_legacy_file(
    scope: PlanScope,
    relative: &Path,
    path: &Path,
) -> Result<Option<(String, String)>> {
    let parts: Vec<_> = relative.components().collect();
    let first = parts.first().and_then(|part| match part {
        Component::Normal(value) => value.to_str(),
        _ => None,
    });
    if matches!(first, Some("profiles" | "styles"))
        || scope == PlanScope::UserHome && matches!(first, Some("templates"))
    {
        return Ok(Some((
            "retired-unread-authority".into(),
            format!(
                "snapshot-removed retired {} content with no native resolver",
                first.expect("matched legacy root")
            ),
        )));
    }
    if matches!(first, Some("logs"))
        && parts.get(1).and_then(|part| part.as_os_str().to_str()) == Some("hooks")
    {
        let bytes = fs::read(path).map_err(|source| io(path, source))?;
        if bytes.iter().all(u8::is_ascii_whitespace) {
            return Ok(Some((
                "empty-hook-log".into(),
                "retired empty hook log".into(),
            )));
        }
    }
    if scope == PlanScope::UserHome
        && relative == Path::new("plugin-data/cli/pyproject.toml.installed")
    {
        return Ok(Some((
            "obsolete-user-plugin-marker".into(),
            "obsolete user-home Python CLI marker".into(),
        )));
    }
    if scope == PlanScope::Project && matches!(first, Some("tmp")) {
        return Ok(Some((
            "retired-runtime-tmp".into(),
            "snapshot-removed retired runtime temporary artifact".into(),
        )));
    }
    if scope == PlanScope::Project && relative == Path::new(".gitignore") {
        return Ok(Some((
            "retired-project-ignore".into(),
            "retired namespace-local ignore rules covered by repository ignore".into(),
        )));
    }
    Ok(None)
}

fn run_from_snapshot_json(path: &Path, validated_runs: &ValidatedRuns) -> Result<String> {
    let bytes = fs::read(path).map_err(|source| io(path, source))?;
    let value: serde_json::Value = serde_json::from_slice(&bytes).map_err(|source| {
        LayoutError::InvalidInput(format!(
            "malformed snapshot JSON {}: {source}",
            path.display()
        ))
    })?;
    run_from_json_record(&value, validated_runs, path, "snapshot")
}

fn run_from_event_jsonl(path: &Path, validated_runs: &ValidatedRuns) -> Result<String> {
    let text = fs::read_to_string(path).map_err(|source| io(path, source))?;
    let mut run = None;
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let value: serde_json::Value = serde_json::from_str(line).map_err(|source| {
            LayoutError::InvalidInput(format!(
                "malformed event JSONL row {} in {}: {source}",
                index + 1,
                path.display()
            ))
        })?;
        let resolved = run_from_json_record(&value, validated_runs, path, "event")?;
        if let Some(previous) = &run
            && previous != &resolved
        {
            return Err(LayoutError::InvalidInput(format!(
                "mixed run identities in event log {}: `{previous}` and `{resolved}`",
                path.display()
            )));
        }
        run = Some(resolved);
    }
    run.ok_or_else(|| {
        LayoutError::InvalidInput(format!(
            "event log {} is empty; only empty hook logs are removable",
            path.display()
        ))
    })
}

fn run_from_json_record(
    value: &serde_json::Value,
    validated_runs: &ValidatedRuns,
    source: &Path,
    kind: &str,
) -> Result<String> {
    let object = value.as_object().ok_or_else(|| {
        LayoutError::InvalidInput(format!(
            "{kind} record in {} must be a JSON object",
            source.display()
        ))
    })?;
    let mut resolved = BTreeSet::new();
    let mut saw_reference = false;
    for field in ["run", "sprint", "branch"] {
        let Some(value) = object.get(field) else {
            continue;
        };
        let reference = value.as_str().ok_or_else(|| {
            LayoutError::InvalidInput(format!(
                "{kind} record field `{field}` in {} must be a string",
                source.display()
            ))
        })?;
        if reference.is_empty() {
            continue;
        }
        saw_reference = true;
        resolved.insert(validated_runs.resolve(reference, source)?);
    }
    if !saw_reference {
        return Err(LayoutError::InvalidInput(format!(
            "{kind} record in {} does not name a run, sprint, or branch",
            source.display()
        )));
    }
    if resolved.len() != 1 {
        return Err(LayoutError::InvalidInput(format!(
            "mixed run identities in {kind} record {}",
            source.display()
        )));
    }
    Ok(resolved
        .first()
        .expect("one resolved run is present")
        .clone())
}

fn run_from_dispatcher_patch(
    name: &str,
    validated_runs: &ValidatedRuns,
    source: &Path,
) -> Result<String> {
    let mut matches = validated_runs
        .ids
        .iter()
        .filter(|run| {
            name.strip_prefix(run.as_str())
                .is_some_and(|tail| tail.starts_with('-'))
        })
        .collect::<Vec<_>>();
    matches.sort_by_key(|run| std::cmp::Reverse(run.len()));
    match matches.as_slice() {
        [run] => Ok((*run).clone()),
        [first, second, ..] if first.len() == second.len() => {
            Err(LayoutError::InvalidInput(format!(
                "ambiguous dispatcher patch run-prefix in {}",
                source.display()
            )))
        }
        [run, ..] => Ok((*run).clone()),
        [] => Err(LayoutError::InvalidInput(format!(
            "dispatcher patch {} has no explicit canonical run-prefix",
            source.display()
        ))),
    }
}

fn validate_runs(runs: &Path) -> Result<ValidatedRuns> {
    let mut validated = ValidatedRuns::default();
    for entry in fs::read_dir(runs).map_err(|source| io(runs, source))? {
        let entry = entry.map_err(|source| io(runs, source))?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path).map_err(|source| io(&path, source))?;
        if metadata.file_type().is_symlink() {
            return Err(LayoutError::UnsafePath {
                path,
                reason: "symlink boundary".into(),
            });
        }
        if !metadata.is_dir() {
            continue;
        }
        let id = entry.file_name().to_string_lossy().to_string();
        validate_id(&id, "run")?;
        let state = path.join("run.json");
        let bytes = fs::read(&state).map_err(|source| LayoutError::MalformedRun {
            path: state.clone(),
            reason: source.to_string(),
        })?;
        let value: serde_json::Value =
            serde_json::from_slice(&bytes).map_err(|source| LayoutError::MalformedRun {
                path: state.clone(),
                reason: source.to_string(),
            })?;
        if value.get("run").and_then(serde_json::Value::as_str) != Some(&id) {
            return Err(LayoutError::MalformedRun {
                path: state,
                reason: format!("run identity does not match directory `{id}`"),
            });
        }
        if let Some(branch) = value.get("branch") {
            let branch = branch.as_str().ok_or_else(|| LayoutError::MalformedRun {
                path: state.clone(),
                reason: "branch must be a string".into(),
            })?;
            if !branch.is_empty() {
                validated
                    .branches
                    .entry(branch.into())
                    .or_default()
                    .insert(id.clone());
            }
        }
        validated.ids.insert(id);
    }
    Ok(validated)
}

fn run_state_exists(runs: &Path, id: &str) -> bool {
    runs.join(id).join("run.json").is_file()
}

fn validate_id(value: &str, kind: &str) -> Result<()> {
    let bytes = value.as_bytes();
    if !(1..=64).contains(&bytes.len())
        || !bytes[0].is_ascii_lowercase() && !bytes[0].is_ascii_digit()
        || !bytes
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-')
    {
        return Err(LayoutError::InvalidInput(format!(
            "unsafe {kind} id `{value}`"
        )));
    }
    Ok(())
}

fn walk(root: &Path, path: &Path, out: &mut Vec<Candidate>) -> Result<()> {
    let metadata = fs::symlink_metadata(path).map_err(|source| io(path, source))?;
    if metadata.file_type().is_symlink() {
        return Err(LayoutError::UnsafePath {
            path: path.to_path_buf(),
            reason: "symbolic-link boundary".into(),
        });
    }
    if metadata.is_dir() {
        if path != root {
            out.push(Candidate {
                path: path.to_path_buf(),
                kind: EntryKind::Directory,
            });
        }
        let mut children = fs::read_dir(path)
            .map_err(|source| io(path, source))?
            .collect::<std::io::Result<Vec<_>>>()
            .map_err(|source| io(path, source))?;
        children.sort_by_key(|entry| entry.file_name());
        for child in children {
            walk(root, &child.path(), out)?;
        }
    } else if metadata.is_file() {
        out.push(Candidate {
            path: path.to_path_buf(),
            kind: EntryKind::File,
        });
    }
    Ok(())
}

fn ensure_directory(path: &Path) -> Result<()> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => Err(LayoutError::UnsafePath {
            path: path.to_path_buf(),
            reason: "symbolic-link namespace".into(),
        }),
        Ok(metadata) if metadata.is_dir() => Ok(()),
        Ok(_) => Err(LayoutError::UnsafePath {
            path: path.to_path_buf(),
            reason: "namespace is not a directory".into(),
        }),
        Err(source) if source.kind() == std::io::ErrorKind::NotFound => {
            Err(LayoutError::Missing(path.to_path_buf()))
        }
        Err(source) => Err(io(path, source)),
    }
}

fn ensure_below(root: &Path, path: &Path) -> Result<()> {
    if !path.starts_with(root) || path == root {
        return Err(LayoutError::UnsafePath {
            path: path.to_path_buf(),
            reason: "configured runs root must be a child of namespace".into(),
        });
    }
    Ok(())
}

fn ensure_regular_file(path: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(path).map_err(|source| io(path, source))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(LayoutError::UnsafePath {
            path: path.to_path_buf(),
            reason: "destination is not a regular file".into(),
        });
    }
    Ok(())
}

fn remove_file_nofollow(path: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(path).map_err(|source| io(path, source))?;
    if metadata.file_type().is_symlink() {
        return Err(LayoutError::UnsafePath {
            path: path.to_path_buf(),
            reason: "refusing to remove symlink".into(),
        });
    }
    fs::remove_file(path).map_err(|source| io(path, source))
}

fn move_verified(source: &Path, destination: &Path, expected: &str) -> Result<()> {
    if destination.exists() {
        ensure_regular_file(destination)?;
        return Err(LayoutError::Collision {
            destination: destination.to_path_buf(),
            sources: source.display().to_string(),
        });
    }
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent).map_err(|source_error| io(parent, source_error))?;
    }
    match fs::rename(source, destination) {
        Ok(()) => {}
        Err(rename_error) if rename_error.raw_os_error() == Some(18) => {
            let temporary = destination.with_file_name(format!(
                ".{}.layout-v5.tmp",
                destination
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
            ));
            let mut input = File::open(source).map_err(|source_error| io(source, source_error))?;
            let mut output = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)
                .map_err(|source_error| io(&temporary, source_error))?;
            std::io::copy(&mut input, &mut output)
                .map_err(|source_error| io(&temporary, source_error))?;
            output
                .sync_all()
                .map_err(|source_error| io(&temporary, source_error))?;
            fs::rename(&temporary, destination)
                .map_err(|source_error| io(destination, source_error))?;
            remove_file_nofollow(source)?;
        }
        Err(source_error) => return Err(io(source, source_error)),
    }
    if sha256_path(destination)? != expected {
        return Err(LayoutError::InvalidInput(format!(
            "checksum verification failed after moving {}",
            source.display()
        )));
    }
    Ok(())
}

fn sha256_path(path: &Path) -> Result<String> {
    let mut file = File::open(path).map_err(|source| io(path, source))?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 8192];
    loop {
        let count = file.read(&mut buffer).map_err(|source| io(path, source))?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format_digest(digest.finalize()))
}

fn sha256_bytes(bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(bytes);
    format_digest(digest.finalize())
}

fn format_digest(bytes: impl IntoIterator<Item = u8>) -> String {
    let mut output = String::with_capacity(64);
    for byte in bytes {
        write!(output, "{byte:02x}").expect("String write");
    }
    output
}

fn rewrite_config_for_layout_v5(original: &[u8]) -> Vec<u8> {
    let Ok(text) = std::str::from_utf8(original) else {
        return original.to_vec();
    };
    let mut output = String::with_capacity(text.len());
    let mut in_paths = false;
    let mut in_context = false;
    let mut skip_memory = false;
    for line in text.lines() {
        let trimmed = line.trim_start();
        if trimmed.starts_with('[') {
            in_paths = trimmed == "[paths]";
            in_context = trimmed == "[context]";
            skip_memory = trimmed == "[memory]";
        }
        if skip_memory {
            continue;
        }
        if in_paths && (is_assignment_to(trimmed, "plans") || is_assignment_to(trimmed, "reports"))
        {
            continue;
        }
        if in_context
            && (is_assignment_to(trimmed, "enabled")
                || is_assignment_to(trimmed, "db_path")
                || is_assignment_to(trimmed, "lock_path")
                || is_assignment_to(trimmed, "project_id_path")
                || is_assignment_to(trimmed, "announce_shctx_path"))
        {
            continue;
        }
        output.push_str(line);
        output.push('\n');
    }
    if !text.ends_with('\n') && !output.is_empty() {
        output.pop();
    }
    output.into_bytes()
}

fn is_assignment_to(line: &str, field: &str) -> bool {
    line.split_once('=')
        .is_some_and(|(key, _)| key.trim() == field)
}

fn write_atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|source| io(parent, source))?;
    }
    let temporary = path.with_file_name(format!(
        ".{}.tmp",
        path.file_name().unwrap_or_default().to_string_lossy()
    ));
    let mut file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(&temporary)
        .map_err(|source| io(&temporary, source))?;
    file.write_all(bytes)
        .map_err(|source| io(&temporary, source))?;
    file.sync_all().map_err(|source| io(&temporary, source))?;
    fs::rename(&temporary, path).map_err(|source| io(path, source))
}

fn rollback_commands(plan: &LayoutPlan) -> String {
    let mut output = String::from(
        "#!/bin/sh\nset -eu\n\n# Restores every source from the adjacent before/ snapshot.\nevidence_root=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\nbefore=\"$evidence_root/before\"\ntest -d \"$before\"\n\n",
    );
    for entry in &plan.manifest.entries {
        if entry.action != PlanAction::Move || entry.source == entry.destination {
            continue;
        }
        let _ = writeln!(output, "rm -f -- {}", shell_quote(&entry.destination));
    }
    output.push('\n');
    for entry in &plan.manifest.entries {
        if entry.action != PlanAction::RemoveDirectory {
            continue;
        }
        let _ = writeln!(output, "mkdir -p -- {}", shell_quote(&entry.source));
    }
    output.push('\n');
    for entry in &plan.manifest.entries {
        if entry.action == PlanAction::RemoveDirectory {
            continue;
        }
        let source = Path::new(&entry.source);
        let relative = source
            .strip_prefix(&plan.namespace)
            .expect("manifest sources are under the planned namespace");
        let _ = writeln!(
            output,
            "mkdir -p -- {}\ncp -p -- \"$before\"/{} {}",
            shell_quote(
                &source
                    .parent()
                    .expect("namespace descendants have a parent")
                    .display()
                    .to_string(),
            ),
            shell_quote(&relative.display().to_string()),
            shell_quote(&entry.source)
        );
    }
    output
}

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn owner(scope: PlanScope) -> &'static str {
    match scope {
        PlanScope::Project => "project",
        PlanScope::UserHome => "user-home",
    }
}

fn default_snapshot_dir() -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0);
    let nonce = SNAPSHOT_COUNTER.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!("shepherd-layout-v5-{stamp:x}-{nonce}"))
}

fn io(path: &Path, source: std::io::Error) -> LayoutError {
    LayoutError::Io {
        path: path.to_path_buf(),
        source,
    }
}
