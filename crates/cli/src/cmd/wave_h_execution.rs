//! Native execution-planning commands over the canonical registry and run ledger.
//!
//! This module deliberately replaces the retired Python commands' process
//! pipelines with small, typed operations. A command either reads the typed
//! registry/run ledger or changes it under its existing lock; it never invokes
//! a sibling CLI, a shell, git, or a network client.

use rusqlite::params;
use shepherd::{
    dispatch::{LaneId, RunId},
    registry::{OpenMode, Registry},
};

use crate::{
    ContextInputs, ExecutionContext, RunStore, RunStoreError,
    interface::{CliError, CliGlobals},
};

const SPRINT_USAGE: &str = "usage: shepherd sprint <help|open|wave|close> --run <run> [lane]";
const DELIVERABLE_USAGE: &str = "usage: shepherd deliverable <promise|complete|stalled> [args]";
const ISSUES_USAGE: &str =
    "usage: shepherd issues <list|classify> [--state open|closed|all] [--json]";

/// Validate the canonical registry and one run ledger before work begins.
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
pub struct WaveHReadyCmd {
    #[arg(long)]
    run: String,
    #[arg(long)]
    json: bool,
}

/// Lint one canonical run ledger. Flat project docs are cross-run material,
/// not input to an unsafe ambient directory walk.
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
pub struct WaveHLintCmd {
    #[arg(long)]
    run: String,
    #[arg(long)]
    json: bool,
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
pub struct WaveHSprintCmd {
    #[command(subcommand)]
    action: Option<SprintAction>,
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
enum SprintAction {
    Help,
    Open(SprintRunCmd),
    Wave(SprintWaveCmd),
    Close(SprintRunCmd),
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
struct SprintRunCmd {
    #[arg(long)]
    run: String,
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
struct SprintWaveCmd {
    #[arg(long)]
    run: String,
    /// The registered lane representing this execution wave.
    lane: String,
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
pub struct WaveHDeliverableCmd {
    #[command(subcommand)]
    action: Option<DeliverableAction>,
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
enum DeliverableAction {
    Promise(DeliverablePromiseCmd),
    Complete(DeliverableCompleteCmd),
    Stalled(DeliverableStalledCmd),
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
struct DeliverablePromiseCmd {
    #[arg(long)]
    kind: String,
    #[arg(long)]
    target: String,
    #[arg(long, default_value = "unknown")]
    role: String,
    #[arg(long, default_value = "unknown")]
    session: String,
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
struct DeliverableCompleteCmd {
    id: i64,
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
struct DeliverableStalledCmd {
    #[arg(long, default_value_t = 10)]
    since_mins: u64,
    #[arg(long)]
    json: bool,
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
pub struct WaveHIssuesCmd {
    #[command(subcommand)]
    action: Option<IssuesAction>,
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
enum IssuesAction {
    List(IssueListCmd),
    Classify(IssueClassifyCmd),
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
struct IssueListCmd {
    #[arg(long, default_value = "open")]
    state: String,
    #[arg(long, default_value_t = 100)]
    limit: u32,
    #[arg(long)]
    json: bool,
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
struct IssueClassifyCmd {
    #[arg(long)]
    sprint: Option<String>,
    #[arg(long, default_value_t = 30)]
    drift_days: i64,
    #[arg(long)]
    unclassified_only: bool,
    #[arg(long)]
    json: bool,
}

#[derive(Debug, serde::Serialize)]
struct IssueRow {
    number: i64,
    title: String,
    state: String,
    labels: Vec<String>,
    milestone: Option<String>,
    url: String,
    updated_at: i64,
}

#[derive(Debug, serde::Serialize)]
struct DeliverableRow {
    id: i64,
    agent_role: String,
    kind: String,
    target_ref: String,
    promised_at: i64,
}

impl WaveHReadyCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let state = load_run(&context, &self.run)?;
        let registry =
            Registry::open(&context.registry_path, OpenMode::ReadOnly).map_err(registry_error)?;
        let version = registry.schema_version().map_err(registry_error)?;
        let value = serde_json::json!({"ready": true, "run": state.run, "status": state.status, "lanes": state.lanes.len(), "registry_schema_version": version});
        if self.json {
            write_json(&mut context, value)
        } else {
            write(
                &mut context,
                &format!(
                    "ready: {} ({} lane(s), registry schema v{version})",
                    state.run,
                    state.lanes.len()
                ),
            )
        }
    }
}

impl WaveHLintCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let state = load_run(&context, &self.run)?;
        let mut findings = Vec::new();
        if !matches!(
            state.status.as_str(),
            "planted" | "planned" | "executing" | "closing" | "closed"
        ) {
            findings.push(format!(
                "run {} has invalid lifecycle status {:?}",
                state.run, state.status
            ));
        }
        for lane in &state.lanes {
            if LaneId::new(&lane.id).is_err() {
                findings.push(format!("lane {} has an invalid identifier", lane.id));
            }
            if !matches!(
                lane.state.as_str(),
                "pending" | "in-progress" | "complete" | "error"
            ) {
                findings.push(format!(
                    "lane {} has invalid state {:?}",
                    lane.id, lane.state
                ));
            }
        }
        let ok = findings.is_empty();
        if self.json {
            write_json(
                &mut context,
                serde_json::json!({"run": state.run, "ok": ok, "findings": findings}),
            )?;
        } else if ok {
            write(&mut context, &format!("lint: ok ({})", state.run))?;
        } else {
            write(
                &mut context,
                &format!(
                    "{}\nlint: FAIL ({} violation(s))",
                    findings.join("\n"),
                    findings.len()
                ),
            )?;
        }
        if ok {
            Ok(())
        } else {
            Err(CliError::reported_with_code(6))
        }
    }
}

impl WaveHSprintCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        match self.action {
            None | Some(SprintAction::Help) => write(&mut context, SPRINT_USAGE),
            Some(SprintAction::Open(command)) => sprint_open(&mut context, &command.run),
            Some(SprintAction::Wave(command)) => {
                sprint_wave(&mut context, &command.run, &command.lane)
            }
            Some(SprintAction::Close(command)) => sprint_close(&mut context, &command.run),
        }
    }
}

impl WaveHDeliverableCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        match self.action {
            None => write(&mut context, DELIVERABLE_USAGE),
            Some(DeliverableAction::Promise(command)) => deliverable_promise(&mut context, command),
            Some(DeliverableAction::Complete(command)) => {
                deliverable_complete(&mut context, command.id)
            }
            Some(DeliverableAction::Stalled(command)) => deliverable_stalled(&mut context, command),
        }
    }
}

impl WaveHIssuesCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        match self.action {
            None => write(&mut context, ISSUES_USAGE),
            Some(IssuesAction::List(command)) => issues_list(&mut context, command),
            Some(IssuesAction::Classify(command)) => issues_classify(&mut context, command),
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

fn run_path(context: &ExecutionContext, run: &str) -> Result<std::path::PathBuf, CliError> {
    RunId::new(run).map_err(|error| CliError::message_with_code(error.to_string(), 2))?;
    Ok(context.runs_root.join(run).join("run.json"))
}

fn load_run(context: &ExecutionContext, run: &str) -> Result<shepherd::RunState, CliError> {
    RunStore::new(run_path(context, run)?)
        .load()
        .map_err(run_error)
}
fn run_error(error: RunStoreError) -> CliError {
    CliError::message_with_code(error.to_string(), 5)
}
fn registry_error(error: shepherd::registry::Error) -> CliError {
    CliError::message_with_code(error.to_string(), 5)
}

fn write(context: &mut ExecutionContext, text: &str) -> Result<(), CliError> {
    let mut bytes = text.as_bytes().to_vec();
    bytes.push(b'\n');
    context
        .write_stdout(&bytes)
        .map_err(|error| CliError::message(error.to_string()))
}
fn write_json(context: &mut ExecutionContext, value: serde_json::Value) -> Result<(), CliError> {
    let text = serde_json::to_string_pretty(&value)
        .map_err(|error| CliError::message(error.to_string()))?;
    write(context, &text)
}

fn sprint_open(context: &mut ExecutionContext, run: &str) -> Result<(), CliError> {
    let now = context.now_unix_millis() / 1_000;
    RunStore::new(run_path(context, run)?)
        .update(|state| {
            if !matches!(state.status.as_str(), "planted" | "planned") {
                return Err(RunStoreError::mutation(format!(
                    "run {run} cannot open from status {}",
                    state.status
                )));
            }
            state.status = "executing".into();
            state.updated_at = now;
            Ok(())
        })
        .map_err(run_error)?;
    write(context, &format!("sprint opened: {run}"))
}

fn sprint_wave(context: &mut ExecutionContext, run: &str, lane_id: &str) -> Result<(), CliError> {
    LaneId::new(lane_id).map_err(|error| CliError::message_with_code(error.to_string(), 2))?;
    let now = context.now_unix_millis() / 1_000;
    RunStore::new(run_path(context, run)?)
        .update(|state| {
            if state.status != "executing" {
                return Err(RunStoreError::mutation(format!(
                    "run {run} is not executing"
                )));
            }
            let lane = state
                .lanes
                .iter_mut()
                .find(|lane| lane.id == lane_id)
                .ok_or_else(|| {
                    RunStoreError::mutation(format!("no such lane: {lane_id} in run {run}"))
                })?;
            if lane.state != "pending" {
                return Err(RunStoreError::mutation(format!(
                    "lane {lane_id} cannot begin from state {}",
                    lane.state
                )));
            }
            lane.state = "in-progress".into();
            lane.updated_at = now;
            state.updated_at = now;
            Ok(())
        })
        .map_err(run_error)?;
    write(context, &format!("wave started: {run}/{lane_id}"))
}

fn sprint_close(context: &mut ExecutionContext, run: &str) -> Result<(), CliError> {
    let now = context.now_unix_millis() / 1_000;
    RunStore::new(run_path(context, run)?)
        .update(|state| {
            if !matches!(state.status.as_str(), "executing" | "closing") {
                return Err(RunStoreError::mutation(format!(
                    "run {run} cannot close from status {}",
                    state.status
                )));
            }
            if let Some(lane) = state.lanes.iter().find(|lane| lane.state != "complete") {
                return Err(RunStoreError::mutation(format!(
                    "lane {} is {}; every lane must be complete before sprint close",
                    lane.id, lane.state
                )));
            }
            state.status = "closed".into();
            state.updated_at = now;
            Ok(())
        })
        .map_err(run_error)?;
    write(context, &format!("sprint closed: {run}"))
}

fn project_id(registry: &Registry) -> Result<String, CliError> {
    registry
        .query("SELECT id FROM projects ORDER BY id LIMIT 1", [], |row| {
            row.get::<_, String>(0)
        })
        .map_err(registry_error)
        .and_then(|values| {
            values.into_iter().next().ok_or_else(|| {
                CliError::message_with_code(
                    "no project registered in the canonical registry; initialize project identity before promising deliverables",
                    5,
                )
            })
        })
}

fn deliverable_promise(
    context: &mut ExecutionContext,
    command: DeliverablePromiseCmd,
) -> Result<(), CliError> {
    if command.kind.trim().is_empty() || command.target.trim().is_empty() {
        return Err(CliError::message_with_code(
            "--kind and --target must be non-empty",
            2,
        ));
    }
    let registry =
        Registry::open(&context.registry_path, OpenMode::ReadWrite).map_err(registry_error)?;
    let project_id = project_id(&registry)?;
    registry.execute("INSERT INTO deliverables (project_id, agent_session, agent_role, kind, target_ref, promised_at, status) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'pending')", params![project_id, command.session, command.role, command.kind, command.target, context.now_unix_millis()]).map_err(registry_error)?;
    let id = registry
        .query_one("SELECT last_insert_rowid()", [], |row| row.get::<_, i64>(0))
        .map_err(registry_error)?;
    write(context, &id.to_string())
}

fn deliverable_complete(context: &mut ExecutionContext, id: i64) -> Result<(), CliError> {
    if id < 1 {
        return Err(CliError::message_with_code(
            "id must be a positive integer",
            2,
        ));
    }
    let registry =
        Registry::open(&context.registry_path, OpenMode::ReadWrite).map_err(registry_error)?;
    let changed = registry.execute("UPDATE deliverables SET status = 'delivered', delivered_at = ?1 WHERE id = ?2 AND status = 'pending'", params![context.now_unix_millis(), id]).map_err(registry_error)?;
    if changed != 1 {
        return Err(CliError::message_with_code(
            format!("pending deliverable {id} was not found"),
            5,
        ));
    }
    write(context, &format!("deliverable completed: {id}"))
}

fn deliverable_stalled(
    context: &mut ExecutionContext,
    command: DeliverableStalledCmd,
) -> Result<(), CliError> {
    let age = i64::try_from(command.since_mins)
        .map_err(|_| CliError::message_with_code("--since-mins is too large", 2))?;
    let cutoff = context
        .now_unix_millis()
        .checked_sub(age.saturating_mul(60_000))
        .ok_or_else(|| CliError::message_with_code("--since-mins is too large", 2))?;
    let registry =
        Registry::open(&context.registry_path, OpenMode::ReadOnly).map_err(registry_error)?;
    let rows = registry.query("SELECT id, agent_role, kind, target_ref, promised_at FROM deliverables WHERE status = 'pending' AND promised_at < ?1 ORDER BY promised_at", params![cutoff], |row| Ok(DeliverableRow { id: row.get(0)?, agent_role: row.get(1)?, kind: row.get(2)?, target_ref: row.get(3)?, promised_at: row.get(4)? })).map_err(registry_error)?;
    if command.json {
        return write_json(
            context,
            serde_json::to_value(rows).map_err(|error| CliError::message(error.to_string()))?,
        );
    }
    if rows.is_empty() {
        return write(context, "no stalled deliverables");
    }
    write(
        context,
        &rows
            .iter()
            .map(|row| {
                format!(
                    "{}  {}  {}  {}  {}",
                    row.id, row.agent_role, row.kind, row.target_ref, row.promised_at
                )
            })
            .collect::<Vec<_>>()
            .join("\n"),
    )
}

fn issues_list(context: &mut ExecutionContext, command: IssueListCmd) -> Result<(), CliError> {
    if !matches!(command.state.as_str(), "open" | "closed" | "all") {
        return Err(CliError::message_with_code(
            "--state must be open, closed, or all",
            2,
        ));
    }
    let registry =
        Registry::open(&context.registry_path, OpenMode::ReadOnly).map_err(registry_error)?;
    let project = project_id(&registry)?;
    let rows = registry.query("SELECT number, title, state, labels, milestone, url, updated_at FROM index_issues WHERE project_id = ?1 AND (?2 = 'all' OR state = ?2) ORDER BY number LIMIT ?3", params![project, command.state, i64::from(command.limit)], decode_issue).map_err(registry_error)?;
    render_issues(context, rows, command.json)
}

fn issues_classify(
    context: &mut ExecutionContext,
    command: IssueClassifyCmd,
) -> Result<(), CliError> {
    let registry =
        Registry::open(&context.registry_path, OpenMode::ReadOnly).map_err(registry_error)?;
    let project = project_id(&registry)?;
    let rows = registry.query("SELECT number, title, state, labels, milestone, url, updated_at FROM index_issues WHERE project_id = ?1 AND state = 'open' ORDER BY number", params![project], decode_issue).map_err(registry_error)?;
    if command.drift_days < 0 {
        return Err(CliError::message_with_code(
            "--drift-days must be non-negative",
            2,
        ));
    }
    let threshold = context
        .now_unix_millis()
        .saturating_div(1_000)
        .saturating_sub(command.drift_days.saturating_mul(86_400));
    let classified = rows
        .into_iter()
        .map(|row| {
            let bucket = issue_bucket(&row, command.sprint.as_deref(), threshold);
            serde_json::json!({"bucket": bucket, "issue": row})
        })
        .filter(|value| !command.unclassified_only || value["bucket"] == "unclassified")
        .collect::<Vec<_>>();
    if command.json {
        return write_json(context, serde_json::Value::Array(classified));
    }
    let text = classified
        .iter()
        .map(|value| {
            format!(
                "{}: #{} {}",
                value["bucket"].as_str().unwrap_or("unclassified"),
                value["issue"]["number"],
                value["issue"]["title"].as_str().unwrap_or_default()
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    write(
        context,
        if text.is_empty() {
            "no matching issues"
        } else {
            &text
        },
    )
}

fn decode_issue(row: &rusqlite::Row<'_>) -> rusqlite::Result<IssueRow> {
    let labels_text: String = row.get(3)?;
    let labels = serde_json::from_str::<Vec<String>>(&labels_text).unwrap_or_else(|_| {
        labels_text
            .split(',')
            .map(|value| value.trim().trim_matches(['[', ']', '"']).to_owned())
            .filter(|value| !value.is_empty())
            .collect()
    });
    Ok(IssueRow {
        number: row.get(0)?,
        title: row.get(1)?,
        state: row.get(2)?,
        labels,
        milestone: row.get(4)?,
        url: row.get(5)?,
        updated_at: row.get(6)?,
    })
}

fn issue_bucket(row: &IssueRow, sprint: Option<&str>, drift_threshold: i64) -> &'static str {
    let has = |wanted: &[&str]| {
        row.labels.iter().any(|label| {
            wanted
                .iter()
                .any(|needle| label.eq_ignore_ascii_case(needle))
        })
    };
    if has(&["deferred", "wontfix", "invalid", "duplicate", "question"]) {
        "labeled-non-issue"
    } else if sprint.is_some_and(|value| row.milestone.as_deref() == Some(value))
        || has(&["blocking", "critical"])
    {
        "blocking-this-sprint"
    } else if has(&["tracking", "epic", "enhancement"]) {
        "tracking-future"
    } else if has(&["critical", "high", "bug"])
        && sprint.is_none_or(|value| row.milestone.as_deref() != Some(value))
        && row.updated_at >= drift_threshold
    {
        "drift-risk"
    } else {
        "unclassified"
    }
}

fn render_issues(
    context: &mut ExecutionContext,
    rows: Vec<IssueRow>,
    json: bool,
) -> Result<(), CliError> {
    if json {
        return write_json(
            context,
            serde_json::to_value(rows).map_err(|error| CliError::message(error.to_string()))?,
        );
    }
    let text = rows
        .iter()
        .map(|row| format!("#{} [{}] {}", row.number, row.state, row.title))
        .collect::<Vec<_>>()
        .join("\n");
    write(context, if text.is_empty() { "no issues" } else { &text })
}

#[cfg(test)]
mod tests {
    use super::{IssueRow, issue_bucket};
    // Used only by the `#[cfg(unix)]` regression test below: the
    // missing-run message text it asserts on is produced by run_store.rs's
    // `mod platform`, which is `#[cfg(unix)]`-only.
    #[cfg(unix)]
    use super::{RunStore, run_error};

    /// #331 regression: `run_error` must keep mapping every `RunStoreError`
    /// to exit 5 (this is what `shepherd ready --run dummy` and every other
    /// run-gated command relies on), even now that the missing-run message
    /// text has changed -- and that new text must never leak a bare
    /// `os error N` while still pointing at `shepherd run list`. Both
    /// halves are asserted together: absence of `os error` alone would also
    /// pass a binary that had simply stopped erroring.
    #[cfg(unix)]
    #[test]
    fn run_error_keeps_exit_5_and_names_the_run_list_command() {
        let root = std::env::temp_dir().join(format!(
            "shepherd-run-error-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after epoch")
                .as_nanos()
        ));
        // `root` is created and canonicalized so the fixture path itself has
        // no symlink component to trip the store's NOFOLLOW-guarded
        // traversal (on macOS the system temp dir lives under `/var`, which
        // is a symlink to `/private/var`; leaving it unresolved would make
        // the very first path component fail as a real fault instead of the
        // `root/dummy` ENOENT this test means to exercise). `root/dummy`
        // itself is never created, matching the exact `shepherd ready --run
        // dummy` repro from issue #331.
        std::fs::create_dir_all(&root).expect("create fixture root");
        let root = std::fs::canonicalize(&root).expect("canonicalize fixture root");
        let store = RunStore::new(root.join("dummy").join("run.json"));
        let store_error = store
            .load()
            .expect_err("a never-created run must fail to load");
        let cli_error = run_error(store_error);
        assert_eq!(
            cli_error.exit_code(),
            5,
            "run-gated commands must keep exiting 5"
        );
        let message = cli_error
            .message_text()
            .expect("run_error always carries a message");
        assert!(
            !message.contains("os error"),
            "message must not leak a bare errno: {message}"
        );
        assert!(
            message.contains("shepherd run list"),
            "message must point at the discovery command: {message}"
        );
        std::fs::remove_dir_all(&root).expect("remove fixture");
    }

    #[test]
    fn classifier_follows_the_declared_precedence() {
        let row = IssueRow {
            number: 7,
            title: "x".into(),
            state: "open".into(),
            labels: vec!["enhancement".into(), "critical".into()],
            milestone: None,
            url: String::new(),
            updated_at: 0,
        };
        assert_eq!(issue_bucket(&row, None, 0), "blocking-this-sprint");
    }
    #[test]
    fn classifier_keeps_unlabeled_work_for_judgment() {
        let row = IssueRow {
            number: 8,
            title: "x".into(),
            state: "open".into(),
            labels: Vec::new(),
            milestone: None,
            url: String::new(),
            updated_at: 0,
        };
        assert_eq!(issue_bucket(&row, None, 0), "unclassified");
    }

    #[test]
    fn classifier_reserves_recent_high_severity_unplanned_work_for_drift() {
        let row = IssueRow {
            number: 9,
            title: "x".into(),
            state: "open".into(),
            labels: vec!["bug".into()],
            milestone: None,
            url: String::new(),
            updated_at: 100,
        };
        assert_eq!(issue_bucket(&row, Some("v900"), 100), "drift-risk");
    }
}
