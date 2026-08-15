//! Native read-only planning, graph, rendering, and report commands.
//!
//! Every artifact input is anchored below the canonical project namespace.

use std::path::{Component, Path, PathBuf};

use sha2::{Digest, Sha256};
use shepherd::{
    dispatch::{LaneId, RunId},
    registry::{OpenMode, Registry},
};

use crate::{
    ContextInputs, ExecutionContext, RunStore,
    interface::{CliError, CliGlobals},
};

const PLAN_USAGE: &str =
    "usage: shepherd plan <hash|validate|verify|topology|extract> --run <run> [--json]";
const GRAPH_USAGE: &str = "usage: shepherd graph <status|diagram|trace> --run <run> [--json]";
const REPORT_USAGE: &str =
    "usage: shepherd report <audit|close|discovery|escalation|teammates|help> [args]";
const MAX_ARTIFACT_BYTES: u64 = 1_048_576;

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
pub struct WaveDPlanCmd {
    #[command(subcommand)]
    action: Option<PlanAction>,
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
enum PlanAction {
    Hash(PlanRunCmd),
    Validate(PlanRunCmd),
    Verify(PlanRunCmd),
    Topology(PlanRunCmd),
    Extract(PlanRunCmd),
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
struct PlanRunCmd {
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
pub struct WaveDGraphCmd {
    #[command(subcommand)]
    action: Option<GraphAction>,
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
enum GraphAction {
    Status(GraphRunCmd),
    Diagram(GraphRunCmd),
    Trace(GraphRunCmd),
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
struct GraphRunCmd {
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
pub struct WaveDRenderCmd {
    template: String,
    #[arg(long = "var")]
    variables: Vec<String>,
    #[arg(long)]
    vars_json: Option<String>,
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
pub struct WaveDReportCmd {
    #[command(subcommand)]
    action: Option<ReportAction>,
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
enum ReportAction {
    Audit(ReportRunCmd),
    Close(ReportRunCmd),
    Discovery(ReportRunCmd),
    Escalation(ReportEscalationCmd),
    Teammates(ReportTeammatesCmd),
    Help,
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
struct ReportRunCmd {
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
struct ReportEscalationCmd {
    #[arg(long)]
    open_only: bool,
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
struct ReportTeammatesCmd {
    #[arg(long)]
    team: Option<String>,
    #[arg(long)]
    stale_mins: Option<u64>,
    #[arg(long)]
    json: bool,
}

#[derive(serde::Serialize)]
struct ReportEscalationOpen {
    id: i64,
    role: String,
    phase: String,
    question: String,
    raised_at: i64,
}

#[derive(serde::Serialize)]
struct ReportEscalation {
    id: i64,
    role: String,
    question: String,
    raised_at: i64,
    resolved_at: Option<i64>,
}

#[derive(serde::Serialize)]
struct ReportTeammate {
    teammate_name: String,
    agent_type: String,
    status: String,
    last_seen_at: i64,
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
pub struct WaveDAuditCmd {
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
pub struct WaveDDiscoveryCmd {
    #[arg(long)]
    run: String,
}

/// Close one registered lane through the canonical run-state ledger.
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
pub struct WaveDCloseLaneCmd {
    #[arg(long)]
    run: String,
    lane: String,
    /// Clean closures complete a lane; partial or failed closures preserve an
    /// explicit error state for the next resume owner.
    #[arg(long, default_value = "clean")]
    status: String,
}

impl WaveDPlanCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let Some(action) = self.action else {
            return Err(CliError::message_with_code(PLAN_USAGE, 2));
        };
        let mut context = context(globals)?;
        match action {
            PlanAction::Hash(command) => plan_hash(&mut context, command),
            PlanAction::Validate(command) | PlanAction::Verify(command) => {
                validate_plan(&mut context, command)
            }
            PlanAction::Topology(command) | PlanAction::Extract(command) => {
                topology(&mut context, command)
            }
        }
    }
}

impl WaveDGraphCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let Some(action) = self.action else {
            return Err(CliError::message_with_code(GRAPH_USAGE, 2));
        };
        let mut context = context(globals)?;
        match action {
            GraphAction::Status(command) => graph_status(&mut context, command),
            GraphAction::Diagram(command) => graph_diagram(&mut context, command),
            GraphAction::Trace(command) => graph_trace(&mut context, command),
        }
    }
}

impl WaveDRenderCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let template = template_path(&context, &self.template)?;
        let variables = render_variables(self.vars_json.as_deref(), &self.variables)?;
        let source = String::from_utf8(read_regular(&template)?)
            .map_err(|_| CliError::message_with_code("template is not UTF-8", 3))?;
        let text = shepherd::render::env::build()
            .template_from_str(&source)
            .and_then(|compiled| compiled.render(&variables))
            .map_err(|error| CliError::message_with_code(error.to_string(), 4))?;
        if self.json {
            let vars = serde_json::to_vec(&variables).map_err(|error| {
                CliError::message_with_code(format!("cannot encode template variables: {error}"), 4)
            })?;
            return write_json(
                &mut context,
                serde_json::json!({
                    "text": text,
                    "manifest": {
                        "template_sha256": hex_digest(source.as_bytes()),
                        "vars_sha256": hex_digest(&vars),
                        "output_sha256": hex_digest(text.as_bytes()),
                    },
                }),
            );
        }
        write_exact(&mut context, text.as_bytes())
    }
}

impl WaveDReportCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let Some(action) = self.action else {
            return write(&mut context, REPORT_USAGE);
        };
        match action {
            ReportAction::Audit(command) => report_audit(&mut context, &command.run),
            ReportAction::Close(command) => report_close(&mut context, &command.run),
            ReportAction::Discovery(command) => report_discovery(&mut context, &command.run),
            ReportAction::Escalation(command) => report_escalation(&mut context, command),
            ReportAction::Teammates(command) => report_teammates(&mut context, command),
            ReportAction::Help => write(&mut context, REPORT_USAGE),
        }
    }
}

impl WaveDAuditCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        report_audit(&mut context, &self.run)
    }
}

impl WaveDDiscoveryCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        report_discovery(&mut context, &self.run)
    }
}

impl WaveDCloseLaneCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        if !matches!(self.status.as_str(), "clean" | "partial" | "failed") {
            return Err(CliError::message_with_code(
                "--status must be clean, partial, or failed",
                2,
            ));
        }
        LaneId::new(&self.lane)
            .map_err(|error| CliError::message_with_code(error.to_string(), 2))?;
        let mut context = context(globals)?;
        let root = run_dir(&context, &self.run)?;
        let state_path = root.join("run.json");
        let next_state = if self.status == "clean" {
            "complete"
        } else {
            "error"
        };
        RunStore::new(state_path)
            .update(|state| {
                let lane = state
                    .lanes
                    .iter_mut()
                    .find(|lane| lane.id == self.lane)
                    .ok_or_else(|| {
                        crate::RunStoreError::mutation(format!(
                            "no such lane: {} in run {}",
                            self.lane, self.run
                        ))
                    })?;
                lane.state = next_state.into();
                Ok(())
            })
            .map_err(|error| CliError::message_with_code(error.to_string(), 5))?;
        write(
            &mut context,
            &format!(
                "lane {} closed in {} ({})",
                self.lane, self.run, self.status
            ),
        )
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

fn plan_hash(context: &mut ExecutionContext, command: PlanRunCmd) -> Result<(), CliError> {
    let path = plan_path(context, &command.run)?;
    let digest = hex_digest(&read_regular(&path)?);
    if command.json {
        return write_json(
            context,
            serde_json::json!({"run": command.run, "path": path, "sha256": digest}),
        );
    }
    write(context, &digest)
}

fn validate_plan(context: &mut ExecutionContext, command: PlanRunCmd) -> Result<(), CliError> {
    let path = plan_path(context, &command.run)?;
    let analysis = analyze_plan(&read_text(&path)?);
    let valid = analysis.errors.is_empty();
    if command.json {
        write_json(
            context,
            serde_json::json!({
                "run": command.run,
                "path": path,
                "headings": analysis.headings,
                "lanes": analysis.lanes,
                "errors": analysis.errors,
                "ok": valid,
            }),
        )?;
    } else if valid {
        write(
            context,
            &format!(
                "OK: {} heading(s), {} declared lane(s)",
                analysis.headings.len(),
                analysis.lanes.len()
            ),
        )?;
    } else {
        write(context, &analysis.errors.join("\n"))?;
    }
    if valid {
        Ok(())
    } else {
        Err(CliError::reported_with_code(6))
    }
}

fn topology(context: &mut ExecutionContext, command: PlanRunCmd) -> Result<(), CliError> {
    let path = plan_path(context, &command.run)?;
    let analysis = analyze_plan(&read_text(&path)?);
    let value = serde_json::json!({
        "schema": "shepherd.plan-topology/1",
        "run": command.run,
        "path": path,
        "headings": analysis.headings,
        "lanes": analysis.lanes,
        "errors": analysis.errors,
    });
    if command.json {
        write_json(context, value)
    } else {
        let headings = value["headings"].as_array().map_or(0, Vec::len);
        let lanes = value["lanes"].as_array().map_or(0, Vec::len);
        write(context, &format!("headings: {headings}\nlanes: {lanes}"))
    }
}

fn graph_status(context: &mut ExecutionContext, command: GraphRunCmd) -> Result<(), CliError> {
    let value = read_json(&graph_path(context, &command.run, "state.json")?)?;
    let nodes = value
        .get("nodes")
        .and_then(serde_json::Value::as_array)
        .map_or(0, Vec::len);
    let edges = value
        .get("edges")
        .and_then(serde_json::Value::as_array)
        .map_or(0, Vec::len);
    if command.json {
        write_json(
            context,
            serde_json::json!({"run": command.run, "nodes": nodes, "edges": edges, "state": value}),
        )
    } else {
        write(
            context,
            &format!("run: {}\nnodes: {nodes}\nedges: {edges}", command.run),
        )
    }
}

fn graph_diagram(context: &mut ExecutionContext, command: GraphRunCmd) -> Result<(), CliError> {
    let value = read_json(&graph_path(context, &command.run, "state.json")?)?;
    let nodes = value
        .get("nodes")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| CliError::message_with_code("graph state has no nodes array", 6))?;
    let edges = value
        .get("edges")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| CliError::message_with_code("graph state has no edges array", 6))?;
    let mut output = String::from("flowchart TD\n");
    for node in nodes {
        let id = node
            .get("id")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| CliError::message_with_code("graph node has no string id", 6))?;
        let label = node
            .get("label")
            .and_then(serde_json::Value::as_str)
            .unwrap_or(id);
        output.push_str(&format!(
            "  {}[\"{}\"]\n",
            mermaid_id(id)?,
            label.replace('"', "'")
        ));
    }
    for edge in edges {
        let from = edge
            .get("from")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| CliError::message_with_code("graph edge has no string from", 6))?;
        let to = edge
            .get("to")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| CliError::message_with_code("graph edge has no string to", 6))?;
        output.push_str(&format!(
            "  {} --> {}\n",
            mermaid_id(from)?,
            mermaid_id(to)?
        ));
    }
    if command.json {
        write_json(
            context,
            serde_json::json!({"run": command.run, "mermaid": output}),
        )
    } else {
        write_exact(context, output.as_bytes())
    }
}

fn graph_trace(context: &mut ExecutionContext, command: GraphRunCmd) -> Result<(), CliError> {
    let bytes = read_regular(&graph_path(context, &command.run, "trace.jsonl")?)?;
    if command.json {
        let records = String::from_utf8(bytes)
            .map_err(|_| CliError::message_with_code("graph trace is not UTF-8", 6))?
            .lines()
            .filter(|line| !line.trim().is_empty())
            .map(serde_json::from_str::<serde_json::Value>)
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| {
                CliError::message_with_code(format!("invalid graph trace JSONL: {error}"), 6)
            })?;
        return write_json(
            context,
            serde_json::json!({"run": command.run, "records": records}),
        );
    }
    write_exact(context, &bytes)
}

fn report_audit(context: &mut ExecutionContext, run: &str) -> Result<(), CliError> {
    let files = markdown_files(&run_dir(context, run)?.join("audits"), "")?;
    render_report(context, run, "Audit", files)
}

fn report_discovery(context: &mut ExecutionContext, run: &str) -> Result<(), CliError> {
    let files = markdown_files(&run_dir(context, run)?.join("reports"), "discovery")?;
    render_report(context, run, "Discovery", files)
}

fn report_close(context: &mut ExecutionContext, run: &str) -> Result<(), CliError> {
    let root = run_dir(context, run)?;
    let audits = markdown_files(&root.join("audits"), "")?;
    let discovery = markdown_files(&root.join("reports"), "discovery")?;
    let mut output = format!(
        "# Close report: {run}\n\n## Audit artifacts\n\n{}\n\n## Discovery artifacts\n\n{}\n",
        audits.len(),
        discovery.len()
    );
    let close = root.join("close.md");
    if descriptor::regular_exists(&close)? {
        output.push_str("\n## Close artifact\n\n");
        output.push_str(&read_text(&close)?);
    }
    write_exact(context, output.as_bytes())
}

fn report_escalation(
    context: &mut ExecutionContext,
    command: ReportEscalationCmd,
) -> Result<(), CliError> {
    let registry = Registry::open(&context.registry_path, OpenMode::ReadOnly).map_err(|error| {
        CliError::message_with_code(format!("cannot open canonical registry: {error}"), 5)
    })?;
    let project = report_project_id(&registry)?;
    let rows = if command.open_only {
        registry.query(
            "SELECT id, role, COALESCE(phase, ''), question, raised_at, NULL FROM escalations WHERE project_id = ?1 AND resolved_at IS NULL ORDER BY raised_at ASC",
            rusqlite::params![project],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, String>(3)?, row.get::<_, i64>(4)?, row.get::<_, Option<i64>>(5)?)),
        )
    } else {
        registry.query(
            "SELECT id, role, '', question, raised_at, resolved_at FROM escalations WHERE project_id = ?1 ORDER BY raised_at DESC",
            rusqlite::params![project],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, String>(3)?, row.get::<_, i64>(4)?, row.get::<_, Option<i64>>(5)?)),
        )
    }.map_err(|error| CliError::message_with_code(format!("cannot query escalations: {error}"), 5))?;
    if command.json {
        if command.open_only {
            let values = rows
                .into_iter()
                .map(
                    |(id, role, phase, question, raised_at, _)| ReportEscalationOpen {
                        id,
                        role,
                        phase,
                        question,
                        raised_at,
                    },
                )
                .collect::<Vec<_>>();
            return write_serialized(context, &values);
        }
        let values = rows
            .into_iter()
            .map(
                |(id, role, _, question, raised_at, resolved_at)| ReportEscalation {
                    id,
                    role,
                    question,
                    raised_at,
                    resolved_at,
                },
            )
            .collect::<Vec<_>>();
        return write_serialized(context, &values);
    }
    let mut output = String::from("# Escalations\n");
    for (id, role, phase, question, raised_at, resolved_at) in rows {
        if command.open_only {
            let phase = if phase.is_empty() { "?" } else { &phase };
            output.push_str(&format!(
                "\n- **#{id} [{role}/{phase}]** {question} (raised: {raised_at})"
            ));
        } else {
            let status = if resolved_at.is_some() {
                "RESOLVED"
            } else {
                "OPEN"
            };
            output.push_str(&format!("\n- **#{id} [{role}/{status}]** {question}"));
        }
    }
    write(context, &output)
}

fn report_teammates(
    context: &mut ExecutionContext,
    command: ReportTeammatesCmd,
) -> Result<(), CliError> {
    // `--stale-mins` was parsed but ignored by the legacy command. Keep that
    // surface stable while intentionally leaving liveness policy to `teammate`.
    let _ = command.stale_mins;
    let registry = Registry::open(&context.registry_path, OpenMode::ReadOnly).map_err(|error| {
        CliError::message_with_code(format!("cannot open canonical registry: {error}"), 5)
    })?;
    let project = report_project_id(&registry)?;
    let rows = registry.query(
        "SELECT teammate_name, agent_type, status, last_seen_at FROM teammates WHERE project_id = ?1 AND (?2 IS NULL OR team_name = ?2) ORDER BY spawned_at DESC",
        rusqlite::params![project, command.team],
        |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, i64>(3)?)),
    ).map_err(|error| CliError::message_with_code(format!("cannot query teammates: {error}"), 5))?;
    if command.json {
        let values = rows
            .into_iter()
            .map(
                |(teammate_name, agent_type, status, last_seen_at)| ReportTeammate {
                    teammate_name,
                    agent_type,
                    status,
                    last_seen_at,
                },
            )
            .collect::<Vec<_>>();
        return write_serialized(context, &values);
    }
    let mut output = String::from("# Teammates\n");
    for (name, agent_type, status, last_seen_at) in rows {
        output.push_str(&format!(
            "\n- **{name}** ({agent_type}) — status: {status} — last seen: {last_seen_at}"
        ));
    }
    write(context, &output)
}

fn report_project_id(registry: &Registry) -> Result<String, CliError> {
    registry
        .query("SELECT id FROM projects ORDER BY id LIMIT 1", [], |row| {
            row.get::<_, String>(0)
        })
        .map_err(|error| {
            CliError::message_with_code(format!("cannot query project identity: {error}"), 5)
        })?
        .into_iter()
        .next()
        .ok_or_else(|| {
            CliError::message_with_code("no project registered in the canonical registry", 5)
        })
}

fn render_report(
    context: &mut ExecutionContext,
    run: &str,
    kind: &str,
    files: Vec<PathBuf>,
) -> Result<(), CliError> {
    if files.is_empty() {
        return write(
            context,
            &format!("# {kind} report: {run}\n\n(no {kind} artifacts)"),
        );
    }
    let mut output = format!("# {kind} report: {run}\n");
    for path in files {
        output.push_str("\n---\n\n");
        output.push_str(&read_text(&path)?);
        if !output.ends_with('\n') {
            output.push('\n');
        }
    }
    write_exact(context, output.as_bytes())
}

fn plan_path(context: &ExecutionContext, run: &str) -> Result<PathBuf, CliError> {
    let root = run_dir(context, run)?;
    RunStore::new(root.join("run.json"))
        .load()
        .map_err(|error| {
            CliError::message_with_code(format!("cannot load requested run: {error}"), 5)
        })?;
    let plan = root.join("plan.md");
    if !descriptor::regular_exists(&plan)? {
        return Err(CliError::message_with_code(
            format!("no canonical plan at {}", plan.display()),
            5,
        ));
    }
    Ok(plan)
}

fn graph_path(context: &ExecutionContext, run: &str, leaf: &str) -> Result<PathBuf, CliError> {
    let path = run_dir(context, run)?.join("graph").join(leaf);
    if !descriptor::regular_exists(&path)? {
        return Err(CliError::message_with_code(
            format!("no graph artifact at {}", path.display()),
            5,
        ));
    }
    Ok(path)
}

fn run_dir(context: &ExecutionContext, run: &str) -> Result<PathBuf, CliError> {
    RunId::new(run).map_err(|error| CliError::message_with_code(error.to_string(), 2))?;
    let path = context.runs_root.join(run);
    if !descriptor::directory_exists(&path)? {
        return Err(CliError::message_with_code(
            format!("no canonical run directory at {}", path.display()),
            5,
        ));
    }
    RunStore::new(path.join("run.json"))
        .load()
        .map_err(|error| {
            CliError::message_with_code(format!("cannot load requested run: {error}"), 5)
        })?;
    Ok(path)
}

fn template_path(context: &ExecutionContext, requested: &str) -> Result<PathBuf, CliError> {
    let relative = safe_relative_path(requested)?;
    let root = context.namespace.join("templates");
    let direct = root.join(&relative);
    let with_extension = if direct.extension().is_none() {
        direct.with_extension("j2")
    } else {
        direct.clone()
    };
    if descriptor::regular_exists(&direct)? {
        return Ok(direct);
    }
    if descriptor::regular_exists(&with_extension)? {
        return Ok(with_extension);
    }
    Err(CliError::message_with_code(
        format!("template not found: {requested}"),
        3,
    ))
}

fn safe_relative_path(value: &str) -> Result<PathBuf, CliError> {
    let path = Path::new(value);
    if value.is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(CliError::message_with_code(
            "template path must be a non-empty safe relative path",
            2,
        ));
    }
    Ok(path.to_path_buf())
}

fn render_variables(
    vars_json: Option<&str>,
    pairs: &[String],
) -> Result<serde_json::Value, CliError> {
    let mut value = match vars_json {
        Some(raw) => serde_json::from_str(raw).map_err(|error| {
            CliError::message_with_code(format!("--vars-json must be valid JSON: {error}"), 2)
        })?,
        None => serde_json::Value::Object(serde_json::Map::new()),
    };
    let object = value.as_object_mut().ok_or_else(|| {
        CliError::message_with_code("--vars-json must decode to a JSON object", 2)
    })?;
    for pair in pairs {
        let (key, text) = pair.split_once('=').ok_or_else(|| {
            CliError::message_with_code(format!("--var expects key=value, got: {pair:?}"), 2)
        })?;
        if key.is_empty() {
            return Err(CliError::message_with_code(
                "--var key must be non-empty",
                2,
            ));
        }
        object.insert(key.to_owned(), serde_json::Value::String(text.to_owned()));
    }
    Ok(value)
}

fn read_regular(path: &Path) -> Result<Vec<u8>, CliError> {
    descriptor::read_regular(path, MAX_ARTIFACT_BYTES)
}

fn read_text(path: &Path) -> Result<String, CliError> {
    String::from_utf8(read_regular(path)?)
        .map_err(|_| CliError::message_with_code("artifact is not UTF-8", 6))
}

fn read_json(path: &Path) -> Result<serde_json::Value, CliError> {
    serde_json::from_slice(&read_regular(path)?)
        .map_err(|error| CliError::message_with_code(format!("invalid JSON: {error}"), 6))
}

fn markdown_files(root: &Path, needle: &str) -> Result<Vec<PathBuf>, CliError> {
    let mut files = descriptor::regular_children(root)?
        .into_iter()
        .filter(|name| name.ends_with(".md") && name.contains(needle))
        .map(|name| root.join(name))
        .collect::<Vec<_>>();
    files.sort();
    Ok(files)
}

fn hex_digest(bytes: &[u8]) -> String {
    use core::fmt::Write;

    Sha256::digest(bytes)
        .iter()
        .fold(String::new(), |mut output, byte| {
            write!(&mut output, "{byte:02x}").expect("writing a String cannot fail");
            output
        })
}

fn mermaid_id(value: &str) -> Result<String, CliError> {
    if value.is_empty()
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
    {
        return Err(CliError::message_with_code(
            format!("graph identifier is not Mermaid-safe: {value:?}"),
            6,
        ));
    }
    Ok(value.to_owned())
}

#[derive(Debug)]
struct PlanAnalysis {
    headings: Vec<String>,
    lanes: Vec<String>,
    errors: Vec<String>,
}

fn analyze_plan(text: &str) -> PlanAnalysis {
    let headings = text
        .lines()
        .filter_map(|line| line.strip_prefix('#').map(str::trim))
        .filter(|heading| !heading.is_empty())
        .map(ToOwned::to_owned)
        .collect::<Vec<_>>();
    let mut lanes = text.lines().filter_map(declared_lane).collect::<Vec<_>>();
    lanes.sort();
    lanes.dedup();
    let mut errors = Vec::new();
    if headings.is_empty() {
        errors.push("ERROR: plan has no Markdown heading".into());
    }
    if text.contains('\0') {
        errors.push("ERROR: plan contains NUL bytes".into());
    }
    PlanAnalysis {
        headings,
        lanes,
        errors,
    }
}

fn declared_lane(line: &str) -> Option<String> {
    let marker = line.trim().strip_prefix("lane:")?.trim();
    RunId::new(marker).ok().map(|id| id.as_str().to_owned())
}

fn write(context: &mut ExecutionContext, output: &str) -> Result<(), CliError> {
    write_exact(context, format!("{output}\n").as_bytes())
}

fn write_exact(context: &mut ExecutionContext, bytes: &[u8]) -> Result<(), CliError> {
    context
        .write_stdout(bytes)
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

fn write_json(context: &mut ExecutionContext, value: serde_json::Value) -> Result<(), CliError> {
    let output = serde_json::to_string_pretty(&value)
        .map_err(|error| CliError::message(format!("cannot encode JSON: {error}")))?;
    write(context, &output)
}

fn write_serialized<T: serde::Serialize>(
    context: &mut ExecutionContext,
    value: &T,
) -> Result<(), CliError> {
    let output = serde_json::to_string_pretty(value)
        .map_err(|error| CliError::message(format!("cannot encode JSON: {error}")))?;
    write(context, &output)
}

#[cfg(unix)]
mod descriptor {
    use std::{
        fs::File,
        io::Read,
        os::fd::OwnedFd,
        path::{Component, Path},
    };

    use rustix::fs::{self, AtFlags, Dir, FileType, Mode, OFlags, open, openat};

    use super::{CliError, MAX_ARTIFACT_BYTES};

    fn directory_flags() -> OFlags {
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW
    }

    fn open_absolute_directory(path: &Path) -> Result<OwnedFd, rustix::io::Errno> {
        if !path.is_absolute() {
            return Err(rustix::io::Errno::INVAL);
        }
        let mut directory = open("/", directory_flags(), Mode::empty())?;
        for component in path.components() {
            let Component::Normal(name) = component else {
                continue;
            };
            directory = openat(&directory, name, directory_flags(), Mode::empty())?;
        }
        Ok(directory)
    }

    fn parent_and_name(path: &Path) -> Result<(OwnedFd, &std::ffi::OsStr), rustix::io::Errno> {
        let parent = path.parent().ok_or(rustix::io::Errno::INVAL)?;
        let name = path.file_name().ok_or(rustix::io::Errno::INVAL)?;
        Ok((open_absolute_directory(parent)?, name))
    }

    fn open_regular(path: &Path) -> Result<Option<File>, CliError> {
        let (parent, name) = match parent_and_name(path) {
            Ok(parts) => parts,
            Err(rustix::io::Errno::NOENT) => {
                return Ok(None);
            }
            Err(error) => {
                return Err(CliError::message_with_code(
                    format!(
                        "cannot open canonical parent for {} without following links: {error}",
                        path.display()
                    ),
                    2,
                ));
            }
        };
        let fd = match openat(
            &parent,
            name,
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        ) {
            Ok(fd) => fd,
            Err(rustix::io::Errno::NOENT) => return Ok(None),
            Err(error) => {
                return Err(CliError::message_with_code(
                    format!(
                        "cannot open canonical artifact {} without following links: {error}",
                        path.display()
                    ),
                    2,
                ));
            }
        };
        let stat = fs::fstat(&fd).map_err(|error| {
            CliError::message(format!(
                "cannot inspect canonical artifact {}: {error}",
                path.display()
            ))
        })?;
        if !FileType::from_raw_mode(stat.st_mode).is_file() {
            return Err(CliError::message_with_code(
                format!("artifact is not a regular file: {}", path.display()),
                2,
            ));
        }
        Ok(Some(File::from(fd)))
    }

    pub(super) fn read_regular(path: &Path, limit: u64) -> Result<Vec<u8>, CliError> {
        let Some(file) = open_regular(path)? else {
            return Err(CliError::message_with_code(
                format!("artifact is missing: {}", path.display()),
                5,
            ));
        };
        let mut bytes = Vec::new();
        file.take(limit + 1)
            .read_to_end(&mut bytes)
            .map_err(|error| {
                CliError::message(format!("cannot read {}: {error}", path.display()))
            })?;
        if bytes.len() as u64 > limit {
            return Err(CliError::message_with_code(
                format!("artifact exceeds {MAX_ARTIFACT_BYTES} byte limit"),
                6,
            ));
        }
        Ok(bytes)
    }

    pub(super) fn regular_exists(path: &Path) -> Result<bool, CliError> {
        Ok(open_regular(path)?.is_some())
    }

    pub(super) fn directory_exists(path: &Path) -> Result<bool, CliError> {
        match open_absolute_directory(path) {
            Ok(_) => Ok(true),
            Err(rustix::io::Errno::NOENT) => Ok(false),
            Err(error) => Err(CliError::message_with_code(
                format!(
                    "cannot open canonical directory {} without following links: {error}",
                    path.display()
                ),
                2,
            )),
        }
    }

    pub(super) fn regular_children(root: &Path) -> Result<Vec<String>, CliError> {
        let directory = match open_absolute_directory(root) {
            Ok(directory) => directory,
            Err(rustix::io::Errno::NOENT) => return Ok(Vec::new()),
            Err(error) => {
                return Err(CliError::message_with_code(
                    format!(
                        "cannot open canonical directory {} without following links: {error}",
                        root.display()
                    ),
                    2,
                ));
            }
        };
        let entries = Dir::read_from(&directory).map_err(|error| {
            CliError::message(format!("cannot enumerate {}: {error}", root.display()))
        })?;
        let mut names = Vec::new();
        for entry in entries {
            let entry = entry.map_err(|error| {
                CliError::message(format!("cannot enumerate {}: {error}", root.display()))
            })?;
            let name = entry.file_name();
            if name.to_bytes() == b"." || name.to_bytes() == b".." {
                continue;
            }
            let Some(name) = name.to_str().ok() else {
                continue;
            };
            let stat =
                fs::statat(&directory, name, AtFlags::SYMLINK_NOFOLLOW).map_err(|error| {
                    CliError::message(format!(
                        "cannot inspect {}: {error}",
                        root.join(name).display()
                    ))
                })?;
            if FileType::from_raw_mode(stat.st_mode).is_symlink() {
                return Err(CliError::message_with_code(
                    format!(
                        "refusing symlinked planning artifact: {}",
                        root.join(name).display()
                    ),
                    2,
                ));
            }
            if FileType::from_raw_mode(stat.st_mode).is_file() {
                names.push(name.to_owned());
            }
        }
        Ok(names)
    }
}

#[cfg(not(unix))]
mod descriptor {
    use std::path::Path;

    use super::CliError;

    fn unsupported() -> CliError {
        CliError::message(
            "descriptor-safe planning artifact access is unavailable on this platform",
        )
    }

    pub(super) fn read_regular(_path: &Path, _limit: u64) -> Result<Vec<u8>, CliError> {
        Err(unsupported())
    }

    pub(super) fn regular_exists(_path: &Path) -> Result<bool, CliError> {
        Err(unsupported())
    }

    pub(super) fn directory_exists(_path: &Path) -> Result<bool, CliError> {
        Err(unsupported())
    }

    pub(super) fn regular_children(_root: &Path) -> Result<Vec<String>, CliError> {
        Err(unsupported())
    }
}

#[cfg(test)]
mod tests {
    use super::{
        analyze_plan, declared_lane, hex_digest, mermaid_id, render_variables, safe_relative_path,
    };

    #[test]
    fn plan_analysis_is_sorted_and_rejects_headingless_documents() {
        let analysis = analyze_plan("# Sprint\nlane: l2\nlane: l1\nlane: l2\n");
        assert_eq!(analysis.headings, ["Sprint"]);
        assert_eq!(analysis.lanes, ["l1", "l2"]);
        assert!(analysis.errors.is_empty());

        let missing = analyze_plan("lane: l1\n");
        assert_eq!(missing.errors, ["ERROR: plan has no Markdown heading"]);
    }

    #[test]
    fn paths_and_graph_identifiers_fail_closed() {
        assert!(safe_relative_path("nested/template.j2").is_ok());
        assert!(safe_relative_path("../escape.j2").is_err());
        assert!(safe_relative_path("/absolute.j2").is_err());
        assert_eq!(mermaid_id("node_1").expect("safe id"), "node_1");
        assert!(mermaid_id("bad-id").is_err());
        assert_eq!(declared_lane(" lane: l1 "), Some("l1".into()));
    }

    #[test]
    fn variables_override_and_hash_is_deterministic() {
        let value = render_variables(
            Some(r#"{"answer":42,"name":"base"}"#),
            &["name=explicit".into()],
        )
        .expect("valid render variables");
        assert_eq!(value["answer"], 42);
        assert_eq!(value["name"], "explicit");
        assert_eq!(
            hex_digest(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}
