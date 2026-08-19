//! Native cross-session signals and teammate observability.
//!
//! This module owns only the durable typed-registry routes that have a stable
//! layout-v5 contract. Sync and worktree integration are reported as explicit
//! host limitations until their native refresh and git/worktree seams exist;
//! neither route shells out to a retired authority.

use std::{
    env,
    time::{SystemTime, UNIX_EPOCH},
};

use clap::{Args, Subcommand};
use rusqlite::params;
use shepherd::registry::{OpenMode, Registry};

use crate::{
    ContextInputs, ExecutionContext,
    interface::{CliError, CliGlobals},
};

const MAX_PAYLOAD_BYTES: usize = 64 * 1024;
const STATES: [&str; 5] = ["init", "in-progress", "error", "complete", "idle"];

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
pub struct WaveGSignalCmd {
    #[command(subcommand)]
    action: SignalAction,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
pub struct WaveGTeammateCmd {
    #[command(subcommand)]
    action: TeammateAction,
}
#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    Subcommand,
    serde::Deserialize,
    serde::Serialize,
)]
enum SignalAction {
    Send {
        #[arg(long)]
        to: String,
        #[arg(long)]
        kind: String,
    },
    Poll {
        #[arg(long = "as")]
        recipient: String,
        #[arg(long)]
        kind: Option<String>,
        #[arg(long)]
        consume: bool,
        #[arg(long)]
        json: bool,
    },
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
pub struct WaveGSyncCmd {
    #[arg(long)]
    scope: Option<String>,
    #[arg(long)]
    all: bool,
    #[arg(long, short)]
    verbose: bool,
}
#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    Subcommand,
    serde::Deserialize,
    serde::Serialize,
)]
enum TeammateAction {
    Liveness {
        #[arg(long, default_value_t = 5)]
        stale_mins: u64,
        #[arg(long)]
        all: bool,
        #[arg(long)]
        team: Option<String>,
        #[arg(long)]
        json: bool,
    },
    Status {
        name: String,
        #[arg(long)]
        json: bool,
    },
    State {
        name: String,
        #[arg(long = "set")]
        value: Option<String>,
    },
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
pub struct WaveGWorktreeCmd {
    #[arg(trailing_var_arg = true)]
    args: Vec<String>,
}

impl WaveGSignalCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        match self.action {
            SignalAction::Send { to, kind } => signal_send(globals, to, kind),
            SignalAction::Poll {
                recipient,
                kind,
                consume,
                json,
            } => signal_poll(globals, recipient, kind, consume, json),
        }
    }
}

impl WaveGTeammateCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        match self.action {
            TeammateAction::Liveness {
                stale_mins,
                all,
                team,
                json,
            } => teammate_liveness(globals, stale_mins, all, team, json),
            TeammateAction::Status { name, json } => teammate_status(globals, name, json),
            TeammateAction::State { name, value } => teammate_state(globals, name, value),
        }
    }
}

fn signal_send(globals: CliGlobals, recipient: String, kind: String) -> Result<(), CliError> {
    let mut context = context(globals)?;
    if recipient.is_empty() || kind.is_empty() {
        return Err(CliError::message("signal send requires --to and --kind"));
    }
    let payload = read_bounded_stdin(&mut context)?;
    if serde_json::from_str::<serde_json::Value>(&payload).is_err() {
        return Err(CliError::message("payload not valid JSON"));
    }
    let registry = open_registry(&context, true)?;
    let project = project_id(&registry)?;
    let sender = env::var("CLAUDE_TEAMMATE_NAME")
        .ok()
        .filter(|v| !v.is_empty())
        .or_else(|| env::var("SHEPHERD_SESSION_ID").ok())
        .unwrap_or_else(|| "root".into());
    registry.execute("INSERT INTO session_signals (project_id, sender, recipient, kind, payload, sent_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6)", params![project, sender, recipient, kind, payload, now_ms()]).map_err(registry_error)?;
    let id: i64 = registry
        .query("SELECT last_insert_rowid()", [], |row| row.get(0))
        .map_err(registry_error)?
        .into_iter()
        .next()
        .ok_or_else(|| CliError::message("signal insert did not return an id"))?;
    stdout(&mut context, &(id.to_string()))
}

fn read_bounded_stdin(context: &mut ExecutionContext) -> Result<String, CliError> {
    let mut payload = String::new();
    loop {
        let before = payload.len();
        context
            .read_stdin(&mut payload)
            .map_err(|error| CliError::message(format!("cannot read signal payload: {error}")))?;
        if payload.len() > MAX_PAYLOAD_BYTES {
            return Err(CliError::message(format!(
                "signal payload exceeds {MAX_PAYLOAD_BYTES} bytes"
            )));
        }
        if payload.len() == before {
            break;
        }
    }
    Ok(payload)
}

fn signal_poll(
    globals: CliGlobals,
    recipient: String,
    kind: Option<String>,
    consume: bool,
    json: bool,
) -> Result<(), CliError> {
    let mut context = context(globals)?;
    if recipient.is_empty() {
        return Err(CliError::message("signal poll requires --as"));
    }
    let registry = open_registry(&context, consume)?;
    let project = project_id(&registry)?;
    let mut sql = String::from(
        "SELECT id, project_id, sender, recipient, kind, payload, sent_at, consumed_at FROM session_signals WHERE project_id = ?1 AND recipient = ?2 AND consumed_at IS NULL",
    );
    if kind.is_some() {
        sql.push_str(" AND kind = ?3");
    }
    sql.push_str(" ORDER BY sent_at, id");
    let rows: Vec<SignalRow> = match kind {
        Some(ref kind) => registry.query(&sql, params![project, recipient, kind], decode_signal),
        None => registry.query(&sql, params![project, recipient], decode_signal),
    }
    .map_err(registry_error)?;
    if consume && !rows.is_empty() {
        for row in &rows {
            registry.execute("UPDATE session_signals SET consumed_at = ?1 WHERE id = ?2 AND consumed_at IS NULL", params![now_ms(), row.id]).map_err(registry_error)?;
        }
    }
    if json {
        stdout(
            &mut context,
            &serde_json::to_string_pretty(&rows)
                .map_err(|error| CliError::message(error.to_string()))?,
        )
    } else {
        stdout(
            &mut context,
            &rows
                .iter()
                .map(|row| format!("{} {} {}", row.id, row.kind, row.payload))
                .collect::<Vec<_>>()
                .join("\n"),
        )
    }
}

#[derive(Clone, Debug, serde::Serialize)]
struct SignalRow {
    id: i64,
    project_id: String,
    sender: String,
    recipient: String,
    kind: String,
    payload: String,
    sent_at: i64,
    consumed_at: Option<i64>,
}
fn decode_signal(row: &rusqlite::Row<'_>) -> rusqlite::Result<SignalRow> {
    Ok(SignalRow {
        id: row.get(0)?,
        project_id: row.get(1)?,
        sender: row.get(2)?,
        recipient: row.get(3)?,
        kind: row.get(4)?,
        payload: row.get(5)?,
        sent_at: row.get(6)?,
        consumed_at: row.get(7)?,
    })
}

fn teammate_liveness(
    globals: CliGlobals,
    stale_mins: u64,
    all: bool,
    team: Option<String>,
    json: bool,
) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let registry = open_registry(&context, false)?;
    let project = project_id(&registry)?;
    let now = now_ms();
    let rows = if all { registry.query("SELECT teammate_name, agent_type, status, declared_state, last_seen_at FROM teammates WHERE status NOT IN ('crashed','retired') ORDER BY last_seen_at ASC", [], decode_live) } else if let Some(team) = team { registry.query("SELECT teammate_name, agent_type, status, declared_state, last_seen_at FROM teammates WHERE project_id = ?1 AND team_name = ?2 AND status NOT IN ('crashed','retired') ORDER BY last_seen_at ASC", params![project, team], decode_live) } else { registry.query("SELECT teammate_name, agent_type, status, declared_state, last_seen_at FROM teammates WHERE project_id = ?1 AND status NOT IN ('crashed','retired') ORDER BY last_seen_at ASC", params![project], decode_live) }.map_err(registry_error)?;
    let views: Vec<_> = rows
        .into_iter()
        .map(|row| live_view(row, now, stale_mins))
        .collect();
    if json {
        stdout(
            &mut context,
            &serde_json::to_string_pretty(&views)
                .map_err(|error| CliError::message(error.to_string()))?,
        )
    } else {
        stdout(&mut context, &render_live(&views))
    }
}
#[derive(Clone, Debug)]
struct LiveRow {
    name: String,
    agent_type: String,
    status: String,
    declared: Option<String>,
    seen: i64,
}
fn decode_live(row: &rusqlite::Row<'_>) -> rusqlite::Result<LiveRow> {
    Ok(LiveRow {
        name: row.get(0)?,
        agent_type: row.get(1)?,
        status: row.get(2)?,
        declared: row.get(3)?,
        seen: row.get(4)?,
    })
}
#[derive(Clone, Debug, serde::Serialize)]
struct LiveView {
    teammate_name: String,
    agent_type: String,
    status: String,
    declared_state: Option<String>,
    sec_since_seen: i64,
    verdict: String,
}
fn live_view(row: LiveRow, now: i64, stale_mins: u64) -> LiveView {
    let age = (now - row.seen).max(0);
    let verdict = match row.declared.as_deref() {
        Some("in-progress") => "ok",
        Some("error") => "error",
        Some("complete") => "complete",
        Some("idle") => "idle",
        _ if age > (stale_mins as i64) * 60_000
            && matches!(row.status.as_str(), "booting" | "active") =>
        {
            "presumed-crashed"
        }
        _ => "ok",
    };
    LiveView {
        teammate_name: row.name,
        agent_type: row.agent_type,
        status: row.status,
        declared_state: row.declared,
        sec_since_seen: age / 1000,
        verdict: verdict.into(),
    }
}
fn render_live(rows: &[LiveView]) -> String {
    let cols = [
        "teammate_name",
        "agent_type",
        "status",
        "declared",
        "sec_since_seen",
        "verdict",
    ];
    let vals: Vec<Vec<String>> = rows
        .iter()
        .map(|r| {
            vec![
                r.teammate_name.clone(),
                r.agent_type.clone(),
                r.status.clone(),
                r.declared_state.clone().unwrap_or_else(|| "-".into()),
                r.sec_since_seen.to_string(),
                r.verdict.clone(),
            ]
        })
        .collect();
    let widths: Vec<usize> = cols
        .iter()
        .enumerate()
        .map(|(i, c)| {
            vals.iter()
                .map(|v| v[i].len())
                .max()
                .unwrap_or(0)
                .max(c.len())
        })
        .collect();
    let line = |v: Vec<String>| {
        v.into_iter()
            .enumerate()
            .map(|(i, s)| format!("{s:<width$}", width = widths[i]))
            .collect::<Vec<_>>()
            .join("  ")
    };
    let mut out = line(cols.iter().map(|v| (*v).into()).collect());
    for row in vals {
        out.push('\n');
        out.push_str(line(row).trim_end());
    }
    out
}

fn teammate_status(globals: CliGlobals, name: String, json: bool) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let registry = open_registry(&context, false)?;
    let row = registry
        .query(
            "SELECT id, project_id, team_name, teammate_name, agent_type, session_id, tmux_pane_id, spawned_at, last_seen_at, status, metadata, declared_state FROM teammates WHERE teammate_name = ?1 ORDER BY spawned_at DESC LIMIT 1",
            params![name],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, String>(4)?,
                    r.get::<_, Option<String>>(5)?,
                    r.get::<_, Option<String>>(6)?,
                    r.get::<_, i64>(7)?,
                    r.get::<_, i64>(8)?,
                    r.get::<_, String>(9)?,
                    r.get::<_, Option<String>>(10)?,
                    r.get::<_, Option<String>>(11)?,
                ))
            },
        )
        .map_err(registry_error)?
        .into_iter()
        .next()
        .ok_or_else(|| CliError::message(format!("no teammate named {name}")))?;
    let value = serde_json::json!({
        "id": row.0,
        "project_id": row.1,
        "team_name": row.2,
        "teammate_name": row.3,
        "agent_type": row.4,
        "session_id": row.5,
        "tmux_pane_id": row.6,
        "spawned_at": row.7,
        "last_seen_at": row.8,
        "status": row.9,
        "metadata": row.10,
        "declared_state": row.11,
    });
    if json {
        stdout(
            &mut context,
            &serde_json::to_string_pretty(&value)
                .map_err(|error| CliError::message(error.to_string()))?,
        )
    } else {
        let fields = [
            "id",
            "project_id",
            "team_name",
            "teammate_name",
            "agent_type",
            "session_id",
            "tmux_pane_id",
            "spawned_at",
            "last_seen_at",
            "status",
            "metadata",
            "declared_state",
        ];
        let lines = fields
            .iter()
            .map(|key| format!("{key}: {}", display_value(value.get(key))))
            .collect::<Vec<_>>()
            .join("\n");
        stdout(&mut context, &lines)
    }
}

fn display_value(value: Option<&serde_json::Value>) -> String {
    match value {
        None | Some(serde_json::Value::Null) => String::new(),
        Some(serde_json::Value::String(value)) => value.clone(),
        Some(value) => value.to_string(),
    }
}

fn teammate_state(
    globals: CliGlobals,
    name: String,
    value: Option<String>,
) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let registry = open_registry(&context, value.is_some())?;
    if let Some(value) = value {
        if !STATES.contains(&value.as_str()) {
            return Err(CliError::message(format!(
                "invalid teammate state `{value}`"
            )));
        }
        registry
            .execute(
                "UPDATE teammates SET declared_state = ?1 WHERE teammate_name = ?2",
                params![value, name],
            )
            .map_err(registry_error)?;
    }
    let current: Option<String> = registry.query("SELECT declared_state FROM teammates WHERE teammate_name = ?1 ORDER BY spawned_at DESC LIMIT 1", params![name], |r| r.get(0)).map_err(registry_error)?.into_iter().next().flatten();
    stdout(&mut context, &current.unwrap_or_default())
}

impl WaveGSyncCmd {
    pub(crate) fn run(self, _globals: CliGlobals) -> Result<(), CliError> {
        let scope = if self.all {
            "all"
        } else {
            self.scope.as_deref().unwrap_or("all")
        };
        Err(CliError::message(format!(
            "sync unavailable: native refresh/lint/status stages are not yet wired (scope={scope}, verbose={})",
            self.verbose
        )))
    }
}
impl WaveGWorktreeCmd {
    pub(crate) fn run(self, _globals: CliGlobals) -> Result<(), CliError> {
        Err(CliError::message(format!(
            "worktree unavailable: native git worktree host seam is not enabled; arguments={:?}",
            self.args
        )))
    }
}

fn context(globals: CliGlobals) -> Result<ExecutionContext, CliError> {
    let cwd = env::current_dir().map_err(|e| CliError::message(e.to_string()))?;
    let mut inputs =
        ContextInputs::from_environment(cwd).map_err(|e| CliError::message(e.to_string()))?;
    inputs.explicit_config = globals.config;
    inputs.verbosity = globals.verbosity;
    ExecutionContext::discover(inputs).map_err(|e| CliError::message(e.to_string()))
}
fn open_registry(context: &ExecutionContext, write: bool) -> Result<Registry, CliError> {
    Registry::open(
        &context.registry_path,
        if write {
            OpenMode::ReadWrite
        } else {
            OpenMode::ReadOnly
        },
    )
    .map_err(registry_error)
}
fn project_id(registry: &Registry) -> Result<String, CliError> {
    registry
        .query("SELECT id FROM projects ORDER BY id LIMIT 1", [], |row| {
            row.get(0)
        })
        .map_err(registry_error)?
        .into_iter()
        .next()
        .ok_or_else(|| {
            CliError::message("no project registered — run 'shepherd init --confirm' first")
        })
}
fn stdout(context: &mut ExecutionContext, value: &str) -> Result<(), CliError> {
    let mut bytes = value.as_bytes().to_vec();
    bytes.push(b'\n');
    context
        .write_stdout(&bytes)
        .map_err(|e| CliError::message(e.to_string()))
}
fn registry_error(error: shepherd::registry::Error) -> CliError {
    CliError::message(error.to_string())
}
fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(i64::MAX)
}
