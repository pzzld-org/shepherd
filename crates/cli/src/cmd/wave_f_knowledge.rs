//! Native v6.4.5 knowledge commands.
//!
//! The retired Python leaves accepted arbitrary SQL, arbitrary paths, and
//! delegated evaluation to another interpreter. This module keeps the useful
//! read-only knowledge surface while making the authority typed and bounded.

use std::{
    collections::BTreeMap,
    fs,
    io::Read,
    path::{Path, PathBuf},
};

use clap::{Args, Subcommand};
use rusqlite::{params, types::ValueRef};
use serde_json::Value;
use shepherd::registry::{OpenMode, Registry};

use crate::{
    ContextInputs, ExecutionContext,
    cmd::dispatch::ReadSubject,
    interface::{CliError, CliGlobals},
};
// The classifier maps a `rustix::io::Errno`, so it exists only where the
// descriptor-safe read does. `ReadSubject` is unconditional because both the
// unix and non-unix readers take one.
#[cfg(unix)]
use crate::cmd::dispatch::classify_nofollow_open_error;

const MAX_KNOWLEDGE_BYTES: u64 = 1_048_576;
const MAX_SEARCH_TEXT: usize = 4_096;
const DEFAULT_SEARCH_LIMIT: i64 = 20;

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
#[command(disable_help_subcommand = true)]
pub struct WaveFDupsCmd {
    #[command(subcommand)]
    action: Option<DupsAction>,
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
enum DupsAction {
    Scan(OutputArgs),
    Check(DupsCheckCmd),
    Registry(DupsRegistryCmd),
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct OutputArgs {
    #[arg(long)]
    json: bool,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct DupsCheckCmd {
    path: Option<PathBuf>,
    #[arg(long)]
    json: bool,
    #[arg(long)]
    stdin: bool,
    #[arg(long = "as", requires = "stdin")]
    as_path: Option<PathBuf>,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct DupsRegistryCmd {
    #[arg(long)]
    json: bool,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
pub struct WaveFQueryCmd {
    name: String,
    #[arg(long)]
    json: bool,
    #[arg(long)]
    md: bool,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
pub struct WaveFSearchCmd {
    text: String,
    #[arg(long, default_value = "all")]
    scope: String,
    #[arg(long, default_value_t = DEFAULT_SEARCH_LIMIT)]
    limit: i64,
    #[arg(long)]
    json: bool,
    #[arg(long)]
    md: bool,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
#[command(disable_help_subcommand = true)]
pub struct WaveFInsightsCmd {
    #[command(subcommand)]
    action: Option<InsightsAction>,
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
enum InsightsAction {
    List(InsightListCmd),
    Show(InsightShowCmd),
    Export(InsightExportCmd),
    Clear(InsightClearCmd),
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct InsightListCmd {
    #[arg(long)]
    sprint: Option<String>,
    #[arg(long)]
    kind: Option<String>,
    #[arg(long)]
    actioned: bool,
    #[arg(long)]
    unactioned: bool,
    #[arg(long)]
    json: bool,
    #[arg(long)]
    md: bool,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct InsightShowCmd {
    id: String,
    #[arg(long)]
    json: bool,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct InsightExportCmd {
    #[arg(long)]
    sprint: Option<String>,
    #[arg(long)]
    md: bool,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct InsightClearCmd {
    #[arg(long, default_value_t = 60)]
    older_than_days: i64,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
#[command(disable_help_subcommand = true)]
pub struct WaveFExportCmd {
    kind: Option<String>,
    #[arg(long)]
    all: bool,
    #[arg(long)]
    out: Option<PathBuf>,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
#[command(disable_help_subcommand = true)]
pub struct WaveFEvalCmd {
    #[command(subcommand)]
    action: Option<EvalAction>,
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
enum EvalAction {
    Run(EvalRunCmd),
    Report(EvalReportCmd),
    List(EvalListCmd),
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct EvalRunCmd {
    #[arg(long)]
    kind: Option<String>,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct EvalReportCmd {
    #[arg(long)]
    kind: Option<String>,
    #[arg(long)]
    sprint: Option<String>,
    #[arg(long)]
    json: bool,
    #[arg(long)]
    md: bool,
}

#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
struct EvalListCmd {
    #[arg(long)]
    kind: Option<String>,
    #[arg(long, default_value_t = 20)]
    limit: i64,
    #[arg(long)]
    json: bool,
    #[arg(long)]
    md: bool,
}

impl WaveFDupsCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        match self.action {
            Some(DupsAction::Scan(options)) => dups_scan(globals, options.json),
            Some(DupsAction::Check(command)) => dups_check(globals, command),
            Some(DupsAction::Registry(command)) => dups_registry(globals, command.json),
            None => Err(CliError::message("usage: dups <scan|check|registry>")),
        }
    }
}

impl WaveFQueryCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let _ = self.md;
        let (columns, sql) = query_spec(&self.name)?;
        let mut context = context(globals)?;
        let registry = open_registry(&context)?;
        let project = project_id(&context, &registry)?;
        let rows = registry
            .query(sql, params![project], |row| row_values(row, columns.len()))
            .map_err(registry_error)?;
        let output = if self.json {
            render_json_rows(columns, &rows)
        } else {
            render_table(columns, &rows)
        };
        stdout(&mut context, &output)
    }
}

impl WaveFSearchCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let _ = self.md;
        let mut context = context(globals)?;
        if self.text.is_empty() || self.text.len() > MAX_SEARCH_TEXT {
            return Err(CliError::message(format!(
                "search text must contain 1..{MAX_SEARCH_TEXT} bytes"
            )));
        }
        if self.limit <= 0 || self.limit > 1_000 {
            return Err(CliError::message("search limit must be between 1 and 1000"));
        }
        if !matches!(self.scope.as_str(), "symbols" | "artifacts" | "all") {
            return Err(CliError::message(format!(
                "unsupported search scope: {}",
                self.scope
            )));
        }
        let registry = open_registry(&context)?;
        let project = project_id(&context, &registry)?;
        let mut rows = Vec::new();
        if self.scope == "symbols" || self.scope == "all" {
            rows.extend(search_symbols(&registry, &project, &self.text, self.limit)?);
        }
        if self.scope == "artifacts" || self.scope == "all" {
            rows.extend(search_artifacts(
                &registry, &project, &self.text, self.limit,
            )?);
        }
        let output = if self.json {
            render_json_rows(&["kind", "name", "location", "summary"], &rows)
        } else {
            render_table(&["kind", "name", "location", "summary"], &rows)
        };
        stdout(&mut context, &output)
    }
}

impl WaveFInsightsCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        match self.action {
            Some(InsightsAction::List(command)) => insights_list(globals, command),
            Some(InsightsAction::Show(command)) => insights_show(globals, command),
            Some(InsightsAction::Export(command)) => insights_export(globals, command),
            Some(InsightsAction::Clear(command)) => insights_clear(command),
            None => Err(CliError::message(
                "usage: insights <list|show|export|clear>",
            )),
        }
    }
}

impl WaveFExportCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        if self.out.is_some() {
            return Err(CliError::message(
                "export --out is unavailable: native v6.4.5 emits through the injected output boundary; no arbitrary filesystem writes",
            ));
        }
        let mut context = context(globals)?;
        let registry = open_registry(&context)?;
        let project = project_id(&context, &registry)?;
        let kinds = if self.all {
            vec![
                "canonical-types",
                "open-issues",
                "open-prs",
                "recent-releases",
                "drift-risk",
                "mem",
            ]
        } else if let Some(kind) = self.kind.as_deref() {
            vec![kind]
        } else {
            return Err(CliError::message("usage: export <kind> or --all"));
        };
        let mut sections = Vec::new();
        for kind in kinds {
            let (columns, sql) = query_spec(kind)?;
            let rows = registry
                .query(sql, params![project], |row| row_values(row, columns.len()))
                .map_err(registry_error)?;
            sections.push(format!("## {kind}\n\n{}", render_table(columns, &rows)));
        }
        stdout(&mut context, &sections.join("\n\n"))
    }
}

impl WaveFEvalCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        match self.action {
            Some(EvalAction::Run(command)) => {
                let _ = command.kind;
                Err(CliError::message(
                    "eval run is unavailable: native v6.4.5 does not invoke a legacy interpreter or remote judge; record a provider-produced verdict through the component/runtime boundary",
                ))
            }
            Some(EvalAction::Report(command)) => eval_report(globals, command),
            Some(EvalAction::List(command)) => eval_list(globals, command),
            None => Err(CliError::message("usage: eval <run|report|list>")),
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

fn open_registry(context: &ExecutionContext) -> Result<Registry, CliError> {
    Registry::open(&context.registry_path, OpenMode::ReadOnly).map_err(registry_error)
}

fn project_id(context: &ExecutionContext, registry: &Registry) -> Result<String, CliError> {
    if let Some(id) = registry
        .query("SELECT id FROM projects ORDER BY id LIMIT 1", [], |row| {
            row.get(0)
        })
        .map_err(registry_error)?
        .into_iter()
        .next()
    {
        return Ok(id);
    }
    let bytes = read_regular_nofollow(
        ReadSubject::ProjectIdentity,
        &context.project_id_path,
        MAX_KNOWLEDGE_BYTES,
    )?;
    let identity: Value = serde_json::from_slice(&bytes)
        .map_err(|error| CliError::message(format!("invalid project identity: {error}")))?;
    identity
        .get("id")
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty())
        .map(ToOwned::to_owned)
        .ok_or_else(|| CliError::message("project identity is missing a string id"))
}

fn query_spec(name: &str) -> Result<(&'static [&'static str], &'static str), CliError> {
    match name {
        "canonical-types" => Ok((
            &[
                "package",
                "kind",
                "name",
                "signature",
                "doc_summary",
                "file_path",
                "line",
                "concept",
                "aliases_to_avoid",
            ],
            "SELECT package, kind, name, signature, doc_summary, file_path, line, concept, aliases_to_avoid FROM v_canonical_types WHERE project_id = ?1 ORDER BY package, name",
        )),
        "open-issues" => Ok((
            &[
                "number",
                "title",
                "state",
                "labels",
                "milestone",
                "assignees",
                "url",
                "updated_at",
            ],
            "SELECT number, title, state, labels, milestone, assignees, url, updated_at FROM v_open_issues WHERE project_id = ?1 ORDER BY updated_at DESC",
        )),
        "open-prs" => Ok((
            &[
                "number",
                "title",
                "state",
                "base_branch",
                "head_branch",
                "labels",
                "url",
                "updated_at",
            ],
            "SELECT number, title, state, base_branch, head_branch, labels, url, updated_at FROM index_prs WHERE project_id = ?1 AND state = 'open' ORDER BY updated_at DESC",
        )),
        "recent-releases" => Ok((
            &["tag", "name", "prerelease", "draft", "url", "published_at"],
            "SELECT tag, name, prerelease, draft, url, published_at FROM index_releases WHERE project_id = ?1 ORDER BY published_at DESC LIMIT 20",
        )),
        "drift-risk" => Ok((
            &["number", "title", "milestone", "labels"],
            "SELECT number, title, milestone, labels FROM v_drift_risk WHERE project_id = ?1 ORDER BY number",
        )),
        "mem" => Ok((
            &[
                "id",
                "kind",
                "title",
                "body",
                "tags",
                "pinned",
                "created_at",
                "updated_at",
            ],
            "SELECT id, kind, title, body, tags, pinned, created_at, updated_at FROM mem_entries WHERE project_id = ?1 ORDER BY pinned DESC, created_at DESC",
        )),
        other => Err(CliError::message(format!(
            "unsupported canned query: {other}"
        ))),
    }
}

fn row_values(row: &rusqlite::Row<'_>, count: usize) -> rusqlite::Result<Vec<Value>> {
    (0..count)
        .map(|index| value_ref(row.get_ref(index)?))
        .collect()
}

fn value_ref(value: ValueRef<'_>) -> rusqlite::Result<Value> {
    Ok(match value {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(value) => Value::from(value),
        ValueRef::Real(value) => Value::from(value),
        ValueRef::Text(value) => Value::String(String::from_utf8_lossy(value).into_owned()),
        ValueRef::Blob(value) => Value::String(format!("0x{}", hex_bytes(value))),
    })
}

fn hex_bytes(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn search_symbols(
    registry: &Registry,
    project: &str,
    text: &str,
    limit: i64,
) -> Result<Vec<Vec<Value>>, CliError> {
    registry.query("SELECT s.name, COALESCE(s.file_path, ''), COALESCE(s.doc_summary, ''), COALESCE(s.signature, '') FROM index_fts_symbols JOIN index_symbols s ON s.rowid = index_fts_symbols.rowid WHERE s.project_id = ?1 AND index_fts_symbols MATCH ?2 ORDER BY bm25(index_fts_symbols) LIMIT ?3", params![project, text, limit], |row| {
        let values = row_values(row, 4)?;
        Ok(vec![Value::String("symbol".into()), values[0].clone(), values[1].clone(), values[2].clone()])
    }).map_err(registry_error)
}

fn search_artifacts(
    registry: &Registry,
    project: &str,
    text: &str,
    limit: i64,
) -> Result<Vec<Vec<Value>>, CliError> {
    registry.query("SELECT COALESCE(a.path, ''), COALESCE(a.title, ''), COALESCE(a.sprint_branch, ''), snippet(index_fts_artifacts, 2, '[', ']', '…', 16) FROM index_fts_artifacts JOIN artifacts a ON a.rowid = index_fts_artifacts.rowid WHERE a.project_id = ?1 AND index_fts_artifacts MATCH ?2 ORDER BY bm25(index_fts_artifacts) LIMIT ?3", params![project, text, limit], |row| {
        let values = row_values(row, 4)?;
        Ok(vec![Value::String("artifact".into()), values[0].clone(), values[1].clone(), values[3].clone()])
    }).map_err(registry_error)
}

fn dups_registry(globals: CliGlobals, json: bool) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let bytes = match read_regular_nofollow(
        ReadSubject::File,
        &context.dups_registry_path,
        MAX_KNOWLEDGE_BYTES,
    ) {
        Ok(bytes) => bytes,
        Err(error)
            if context.dups_registry_path == context.primary_root.join("dups-registry.json") =>
        {
            return Err(error);
        }
        Err(_) => Vec::new(),
    };
    if json {
        stdout(
            &mut context,
            if bytes.is_empty() {
                "{}".into()
            } else {
                String::from_utf8_lossy(&bytes).into_owned()
            }
            .as_str(),
        )
    } else {
        let path = context.dups_registry_path.display().to_string();
        stdout(&mut context, &format!("dups registry: {path}"))
    }
}

fn dups_check(globals: CliGlobals, command: DupsCheckCmd) -> Result<(), CliError> {
    if command.stdin {
        return Err(CliError::message(
            "dups check --stdin is unavailable: stdin-to-file identity is not descriptor-safe; provide a canonical regular path",
        ));
    }
    let _ = command.as_path;
    let path = command
        .path
        .ok_or_else(|| CliError::message("usage: dups check <file>"))?;
    let bytes = read_regular_nofollow(ReadSubject::File, &path, MAX_KNOWLEDGE_BYTES)?;
    let mut names = BTreeMap::<String, usize>::new();
    for line in String::from_utf8_lossy(&bytes).lines() {
        let mut words = line.split_whitespace();
        if matches!(words.next(), Some("pub"))
            && let Some(kind) = words.next()
            && matches!(kind, "struct" | "enum" | "type")
            && let Some(name) = words.next()
        {
            *names
                .entry(
                    name.trim_matches(|ch: char| !ch.is_ascii_alphanumeric() && ch != '_')
                        .to_owned(),
                )
                .or_default() += 1;
        }
    }
    let duplicates: Vec<Value> = names
        .into_iter()
        .filter(|(_, count)| *count > 1)
        .map(|(name, count)| serde_json::json!({"name": name, "count": count}))
        .collect();
    let value =
        serde_json::json!({"path": path, "duplicates": duplicates, "authority": "native-v6.4.5"});
    let mut context = context(globals)?;
    if command.json {
        let output = serde_json::to_string_pretty(&value)
            .map_err(|error| CliError::message(error.to_string()))?;
        stdout(&mut context, &output)
    } else {
        stdout(
            &mut context,
            &format!(
                "duplicate declarations: {}",
                value["duplicates"].as_array().map_or(0, Vec::len)
            ),
        )
    }
}

fn dups_scan(globals: CliGlobals, json: bool) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let registry = open_registry(&context)?;
    let project = project_id(&context, &registry)?;
    let rows = registry.query("SELECT shape_hash, COUNT(*) FROM index_struct_shapes WHERE project_id = ?1 GROUP BY shape_hash HAVING COUNT(*) > 1 ORDER BY shape_hash", params![project], |row| Ok(vec![Value::String(row.get::<_, String>(0)?), Value::from(row.get::<_, i64>(1)?)] )).map_err(registry_error)?;
    if json {
        stdout(
            &mut context,
            &render_json_rows(&["shape_hash", "count"], &rows),
        )
    } else {
        stdout(&mut context, &render_table(&["shape_hash", "count"], &rows))
    }
}

fn insights_root(context: &ExecutionContext) -> PathBuf {
    context.docs_root.clone()
}

fn insight_files(context: &ExecutionContext) -> Result<Vec<PathBuf>, CliError> {
    let entries = match fs::read_dir(insights_root(context)) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => {
            return Err(CliError::message(format!(
                "cannot list canonical docs: {error}"
            )));
        }
    };
    let mut paths = Vec::new();
    for entry in entries {
        let path = entry
            .map_err(|error| CliError::message(format!("cannot inspect canonical docs: {error}")))?
            .path();
        if path
            .extension()
            .is_some_and(|extension| extension == "json")
            && path
                .file_name()
                .is_some_and(|name| name.to_string_lossy().starts_with("insight-"))
        {
            paths.push(path);
        }
    }
    paths.sort();
    Ok(paths)
}

fn load_insights(context: &ExecutionContext) -> Result<Vec<Value>, CliError> {
    insight_files(context)?
        .into_iter()
        .map(|path| {
            let bytes = read_regular_nofollow(ReadSubject::File, &path, MAX_KNOWLEDGE_BYTES)?;
            serde_json::from_slice(&bytes).map_err(|error| {
                CliError::message(format!("invalid insight {}: {error}", path.display()))
            })
        })
        .collect()
}

fn insights_list(globals: CliGlobals, command: InsightListCmd) -> Result<(), CliError> {
    if command.actioned && command.unactioned {
        return Err(CliError::message(
            "--actioned and --unactioned are mutually exclusive",
        ));
    }
    let mut context = context(globals)?;
    let mut records = load_insights(&context)?;
    records.retain(|record| {
        command
            .sprint
            .as_deref()
            .is_none_or(|value| record.get("sprint").and_then(Value::as_str) == Some(value))
    });
    records.retain(|record| {
        command
            .kind
            .as_deref()
            .is_none_or(|value| record.get("kind").and_then(Value::as_str) == Some(value))
    });
    if command.actioned {
        records.retain(|record| record.get("actioned").and_then(Value::as_bool) == Some(true));
    }
    if command.unactioned {
        records.retain(|record| record.get("actioned").and_then(Value::as_bool) != Some(true));
    }
    if command.json {
        stdout(&mut context, &render_json_values(&records))
    } else if command.md {
        stdout(&mut context, &render_insights_markdown(&records))
    } else {
        stdout(&mut context, &format!("insights: {}", records.len()))
    }
}

fn insights_show(globals: CliGlobals, command: InsightShowCmd) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let record = load_insights(&context)?
        .into_iter()
        .find(|record| record.get("id").and_then(Value::as_str) == Some(command.id.as_str()))
        .ok_or_else(|| CliError::message(format!("insight {} not found", command.id)))?;
    if command.json {
        let output = serde_json::to_string_pretty(&record)
            .map_err(|error| CliError::message(error.to_string()))?;
        stdout(&mut context, &output)
    } else {
        stdout(&mut context, &record.to_string())
    }
}

fn insights_export(globals: CliGlobals, command: InsightExportCmd) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let mut records = load_insights(&context)?;
    records.retain(|record| {
        command
            .sprint
            .as_deref()
            .is_none_or(|value| record.get("sprint").and_then(Value::as_str) == Some(value))
    });
    if command.md {
        stdout(&mut context, &render_insights_markdown(&records))
    } else {
        stdout(&mut context, &render_json_values(&records))
    }
}

fn insights_clear(command: InsightClearCmd) -> Result<(), CliError> {
    if command.older_than_days < 0 {
        return Err(CliError::message("--older-than-days must not be negative"));
    }
    Err(CliError::message(
        "insights clear is unavailable: canonical docs are immutable run evidence; use an explicit run artifact cleanup operation",
    ))
}

fn eval_report(globals: CliGlobals, command: EvalReportCmd) -> Result<(), CliError> {
    let _ = command.sprint;
    let _ = command.md;
    let mut context = context(globals)?;
    let registry = open_registry(&context)?;
    let project = project_id(&context, &registry)?;
    let mut sql = "SELECT kind, subject_ref, score, threshold, passed, model, rationale, created_at FROM v_eval_latest WHERE project_id = ?1".to_owned();
    if command.kind.is_some() {
        sql.push_str(" AND kind = ?2");
    }
    sql.push_str(" ORDER BY created_at DESC");
    let rows = if let Some(kind) = command.kind {
        registry.query(&sql, params![project, kind], |row| row_values(row, 8))
    } else {
        registry.query(&sql, params![project], |row| row_values(row, 8))
    }
    .map_err(registry_error)?;
    if command.json {
        stdout(
            &mut context,
            &render_json_rows(
                &[
                    "kind",
                    "subject_ref",
                    "score",
                    "threshold",
                    "passed",
                    "model",
                    "rationale",
                    "created_at",
                ],
                &rows,
            ),
        )
    } else {
        stdout(
            &mut context,
            &render_table(
                &[
                    "kind",
                    "subject_ref",
                    "score",
                    "threshold",
                    "passed",
                    "model",
                    "rationale",
                    "created_at",
                ],
                &rows,
            ),
        )
    }
}

fn eval_list(globals: CliGlobals, command: EvalListCmd) -> Result<(), CliError> {
    let _ = command.md;
    if command.limit <= 0 || command.limit > 1_000 {
        return Err(CliError::message("eval limit must be between 1 and 1000"));
    }
    let mut context = context(globals)?;
    let registry = open_registry(&context)?;
    let project = project_id(&context, &registry)?;
    let rows = if let Some(kind) = command.kind { registry.query("SELECT kind, subject_ref, score, threshold, passed, model, rationale, created_at FROM eval_runs WHERE project_id = ?1 AND kind = ?2 ORDER BY created_at DESC LIMIT ?3", params![project, kind, command.limit], |row| row_values(row, 8)) } else { registry.query("SELECT kind, subject_ref, score, threshold, passed, model, rationale, created_at FROM eval_runs WHERE project_id = ?1 ORDER BY created_at DESC LIMIT ?2", params![project, command.limit], |row| row_values(row, 8)) }.map_err(registry_error)?;
    if command.json {
        stdout(
            &mut context,
            &render_json_rows(
                &[
                    "kind",
                    "subject_ref",
                    "score",
                    "threshold",
                    "passed",
                    "model",
                    "rationale",
                    "created_at",
                ],
                &rows,
            ),
        )
    } else {
        stdout(
            &mut context,
            &render_table(
                &[
                    "kind",
                    "subject_ref",
                    "score",
                    "threshold",
                    "passed",
                    "model",
                    "rationale",
                    "created_at",
                ],
                &rows,
            ),
        )
    }
}

fn render_json_values(values: &[Value]) -> String {
    serde_json::to_string_pretty(values).unwrap_or_else(|_| "[]".into())
}
fn render_json_rows(columns: &[&str], rows: &[Vec<Value>]) -> String {
    let objects = rows
        .iter()
        .map(|row| {
            columns
                .iter()
                .zip(row.iter())
                .map(|(column, value)| ((*column).to_owned(), value.clone()))
                .collect::<serde_json::Map<_, _>>()
        })
        .map(Value::Object)
        .collect::<Vec<_>>();
    serde_json::to_string_pretty(&objects).unwrap_or_else(|_| "[]".into())
}

fn render_table(columns: &[&str], rows: &[Vec<Value>]) -> String {
    if rows.is_empty() {
        return String::new();
    }
    let cells: Vec<Vec<String>> = rows
        .iter()
        .map(|row| row.iter().map(value_text).collect())
        .collect();
    let widths: Vec<usize> = (0..columns.len())
        .map(|index| {
            std::iter::once(columns[index].len())
                .chain(
                    cells
                        .iter()
                        .map(|row| row.get(index).map_or(0, String::len)),
                )
                .max()
                .unwrap_or(0)
        })
        .collect();
    let line = |row: &[String]| {
        row.iter()
            .enumerate()
            .map(|(index, cell)| format!("{cell:<width$}", width = widths[index]))
            .collect::<Vec<_>>()
            .join("  ")
    };
    let header = columns
        .iter()
        .map(|column| (*column).to_owned())
        .collect::<Vec<_>>();
    let separator = widths
        .iter()
        .map(|width| "-".repeat(*width))
        .collect::<Vec<_>>();
    std::iter::once(line(&header))
        .chain(std::iter::once(line(&separator)))
        .chain(cells.iter().map(|row| line(row)))
        .collect::<Vec<_>>()
        .join("\n")
}

fn value_text(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(value) => value.clone(),
        other => other.to_string(),
    }
}
fn render_insights_markdown(records: &[Value]) -> String {
    if records.is_empty() {
        return "(no insights)".into();
    }
    records
        .iter()
        .map(|record| {
            format!(
                "- **{}** {}",
                record
                    .get("kind")
                    .and_then(Value::as_str)
                    .unwrap_or("insight"),
                record.get("title").and_then(Value::as_str).unwrap_or("")
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn stdout(context: &mut ExecutionContext, output: &str) -> Result<(), CliError> {
    let mut bytes = output.as_bytes().to_vec();
    if !bytes.ends_with(b"\n") {
        bytes.push(b'\n');
    }
    context
        .write_stdout(&bytes)
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}
fn registry_error(error: shepherd::registry::Error) -> CliError {
    CliError::message(error.to_string())
}
#[cfg(unix)]
fn read_regular_nofollow(
    subject: ReadSubject,
    path: &Path,
    limit: u64,
) -> Result<Vec<u8>, CliError> {
    use rustix::fs::{FileType, Mode, OFlags, fstat, open};
    use std::fs::File;
    let descriptor = open(
        path,
        OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
        Mode::empty(),
    )
    .map_err(|error| classify_nofollow_open_error(subject, path, error))?;
    let stat = fstat(&descriptor).map_err(|error| {
        CliError::message(format!("cannot inspect {}: {error}", path.display()))
    })?;
    if !FileType::from_raw_mode(stat.st_mode).is_file() {
        return Err(CliError::message(subject.not_a_regular_file_message(path)));
    }
    let mut bytes = Vec::new();
    File::from(descriptor)
        .take(limit.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|error| CliError::message(format!("cannot read {}: {error}", path.display())))?;
    if bytes.len() as u64 > limit {
        return Err(CliError::message(format!(
            "file exceeds {limit}-byte limit: {}",
            path.display()
        )));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_regular_nofollow(
    subject: ReadSubject,
    path: &Path,
    limit: u64,
) -> Result<Vec<u8>, CliError> {
    let metadata = fs::symlink_metadata(path).map_err(|error| {
        if error.kind() == std::io::ErrorKind::NotFound {
            CliError::message(subject.not_found_message(path))
        } else {
            CliError::message(format!("cannot inspect {}: {error}", path.display()))
        }
    })?;
    if !metadata.is_file() {
        return Err(CliError::message(subject.not_a_regular_file_message(path)));
    }
    let mut bytes = Vec::new();
    fs::File::open(path)
        .map_err(|error| CliError::message(error.to_string()))?
        .take(limit.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|error| CliError::message(error.to_string()))?;
    if bytes.len() as u64 > limit {
        return Err(CliError::message(format!(
            "file exceeds {limit}-byte limit: {}",
            path.display()
        )));
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::{
        ReadSubject, hex_bytes, query_spec, read_regular_nofollow, render_insights_markdown,
        render_table,
    };
    #[test]
    fn query_names_are_an_allowlist() {
        assert!(query_spec("canonical-types").is_ok());
        assert!(query_spec("drop-table").is_err());
    }
    #[test]
    fn rendering_is_deterministic_and_bounded() {
        assert_eq!(render_table(&["a"], &[]), "");
        assert_eq!(hex_bytes(&[0, 15, 255]), "000fff");
        assert_eq!(render_insights_markdown(&[]), "(no insights)");
    }

    #[cfg(unix)]
    #[test]
    fn bounded_reads_reject_symlinks() {
        use std::{
            fs,
            os::unix::fs::symlink,
            time::{SystemTime, UNIX_EPOCH},
        };
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!("shepherd-wave-f-{suffix}"));
        fs::create_dir(&root).expect("temporary test directory");
        let target = root.join("target");
        let link = root.join("link");
        fs::write(&target, b"bounded").expect("target");
        symlink(&target, &link).expect("symlink");
        assert!(read_regular_nofollow(ReadSubject::File, &target, 7).is_ok());
        assert!(read_regular_nofollow(ReadSubject::File, &target, 6).is_err());
        assert!(read_regular_nofollow(ReadSubject::File, &link, 7).is_err());
        fs::remove_dir_all(root).expect("cleanup");
    }
}
