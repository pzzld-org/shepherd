//! Native project-memory commands over the canonical typed registry.

use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::params;
use shepherd::registry::{OpenMode, Registry};
use uuid::Uuid;

use crate::{
    ContextInputs, ExecutionContext,
    interface::{CliError, CliGlobals},
};

const USAGE: &str = "usage: shepherd mem <add|list|search|show|pin|unpin|rm>";
const LIST_COLUMNS: [&str; 5] = ["id", "kind", "title", "pinned", "created_at"];
const SEARCH_COLUMNS: [&str; 4] = ["id", "kind", "title", "pinned"];
const SHOW_COLUMNS: [&str; 8] = [
    "id",
    "kind",
    "title",
    "body",
    "tags",
    "pinned",
    "created_at",
    "updated_at",
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
#[command(disable_help_flag = true, disable_help_subcommand = true)]
pub struct WaveB1MemCmd {
    #[command(subcommand)]
    action: Option<MemAction>,
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
enum MemAction {
    Add(MemAddCmd),
    List(MemListCmd),
    Search(MemSearchCmd),
    Show(MemShowCmd),
    Pin(MemIdCmd),
    Unpin(MemIdCmd),
    Rm(MemIdCmd),
    Delete(MemIdCmd),
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
struct MemAddCmd {
    #[arg(long, default_value = "")]
    title: String,
    #[arg(long, default_value = "note")]
    kind: String,
    #[arg(long, default_value = "")]
    body: String,
    #[arg(long, default_value = "[]")]
    tags: String,
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
struct MemListCmd {
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
struct MemSearchCmd {
    #[arg(long, default_value = "")]
    q: String,
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
struct MemShowCmd {
    id: Option<String>,
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
struct MemIdCmd {
    id: Option<String>,
}

#[derive(Debug)]
struct MemRow {
    id: String,
    kind: String,
    title: String,
    body: String,
    tags: String,
    pinned: i64,
    created_at: i64,
    updated_at: i64,
}

impl WaveB1MemCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let Some(action) = self.action else {
            return Err(CliError::message(USAGE));
        };
        match action {
            MemAction::Add(command) => command.run(globals),
            MemAction::List(command) => command.run(globals),
            MemAction::Search(command) => command.run(globals),
            MemAction::Show(command) => command.run(globals),
            MemAction::Pin(command) => command.set_pinned(globals, 1, "pin"),
            MemAction::Unpin(command) => command.set_pinned(globals, 0, "unpin"),
            MemAction::Rm(command) | MemAction::Delete(command) => command.remove(globals),
        }
    }
}

impl MemAddCmd {
    fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let registry = Registry::open_migrated(&context.registry_path).map_err(registry_error)?;
        let project_id = project_id(&registry)?;
        if self.title.is_empty() {
            return Err(CliError::message("--title required"));
        }
        let id = Uuid::now_v7().to_string();
        let now = now_seconds();
        registry
            .execute(
                "INSERT INTO mem_entries (id, project_id, kind, title, body, tags, pinned, created_at, updated_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 0, ?7, ?7)",
                params![id, project_id, self.kind, self.title, self.body, self.tags, now],
            )
            .map_err(registry_error)?;
        write_stdout(&mut context, &id)
    }
}

impl MemListCmd {
    fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let registry = open_read_registry(&context)?;
        let project_id = project_id(&registry)?;
        let rows = query_mem_rows(
            &registry,
            "SELECT id, kind, title, body, tags, pinned, created_at, updated_at FROM mem_entries WHERE project_id = ?1 ORDER BY pinned DESC, created_at DESC",
            params![project_id],
        )?;
        if self.json {
            return write_stdout(&mut context, &render_list_json(&rows));
        }
        let values = rows
            .iter()
            .map(|row| {
                vec![
                    row.id.clone(),
                    row.kind.clone(),
                    row.title.clone(),
                    row.pinned.to_string(),
                    row.created_at.to_string(),
                ]
            })
            .collect::<Vec<_>>();
        write_if_nonempty(&mut context, &render_table(&LIST_COLUMNS, &values))
    }
}

impl MemSearchCmd {
    fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let registry = open_read_registry(&context)?;
        let project_id = project_id(&registry)?;
        if self.q.is_empty() {
            return Err(CliError::message("--q=<text> required for mem search"));
        }
        let pattern = format!("%{}%", self.q);
        let rows = query_mem_rows(
            &registry,
            "SELECT id, kind, title, body, tags, pinned, created_at, updated_at FROM mem_entries WHERE project_id = ?1 AND (title LIKE ?2 OR body LIKE ?2) ORDER BY pinned DESC, created_at DESC",
            params![project_id, pattern],
        )?;
        if self.json {
            return write_stdout(&mut context, &render_search_json(&rows));
        }
        let values = rows
            .iter()
            .map(|row| {
                vec![
                    row.id.clone(),
                    row.kind.clone(),
                    row.title.clone(),
                    row.pinned.to_string(),
                ]
            })
            .collect::<Vec<_>>();
        write_if_nonempty(&mut context, &render_table(&SEARCH_COLUMNS, &values))
    }
}

impl MemShowCmd {
    fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let registry = open_read_registry(&context)?;
        let project_id = project_id(&registry)?;
        let Some(id) = self.id else {
            return Err(CliError::message("usage: shepherd mem show <id>"));
        };
        let mut rows = query_mem_rows(
            &registry,
            "SELECT id, kind, title, body, tags, pinned, created_at, updated_at FROM mem_entries WHERE project_id = ?1 AND id = ?2",
            params![project_id, id],
        )?;
        let row = rows.pop();
        if self.json {
            return write_stdout(
                &mut context,
                &row.map_or_else(|| "null".to_owned(), |row| render_show_json(&row)),
            );
        }
        let values = row.map(|row| {
            vec![vec![
                row.id,
                row.kind,
                row.title,
                row.body,
                row.tags,
                row.pinned.to_string(),
                row.created_at.to_string(),
                row.updated_at.to_string(),
            ]]
        });
        write_if_nonempty(
            &mut context,
            &values.map_or_else(String::new, |rows| render_table(&SHOW_COLUMNS, &rows)),
        )
    }
}

impl MemIdCmd {
    fn set_pinned(self, globals: CliGlobals, value: i64, command: &str) -> Result<(), CliError> {
        let context = context(globals)?;
        let registry =
            Registry::open(&context.registry_path, OpenMode::ReadWrite).map_err(registry_error)?;
        let project_id = project_id(&registry)?;
        let Some(id) = self.id else {
            return Err(CliError::message(format!(
                "usage: shepherd mem {command} <id>"
            )));
        };
        registry
            .execute(
                "UPDATE mem_entries SET pinned = ?1, updated_at = ?2 WHERE id = ?3 AND project_id = ?4",
                params![value, now_seconds(), id, project_id],
            )
            .map_err(registry_error)?;
        Ok(())
    }

    fn remove(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let registry =
            Registry::open(&context.registry_path, OpenMode::ReadWrite).map_err(registry_error)?;
        let project_id = project_id(&registry)?;
        let Some(id) = self.id else {
            return Err(CliError::message("usage: shepherd mem rm <id>"));
        };
        registry
            .execute(
                "DELETE FROM mem_entries WHERE project_id = ?1 AND id = ?2",
                params![project_id, id],
            )
            .map_err(registry_error)?;
        write_stdout(&mut context, &format!("shepherd mem rm: removed {id}"))
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

fn open_read_registry(context: &ExecutionContext) -> Result<Registry, CliError> {
    Registry::open(&context.registry_path, OpenMode::ReadOnly).map_err(registry_error)
}

fn project_id(registry: &Registry) -> Result<String, CliError> {
    registry
        .query("SELECT id FROM projects LIMIT 1", [], |row| row.get(0))
        .map_err(registry_error)?
        .into_iter()
        .next()
        .ok_or_else(|| CliError::message("no project registered — run 'shepherd init' first"))
}

fn query_mem_rows<P: rusqlite::Params>(
    registry: &Registry,
    sql: &str,
    params: P,
) -> Result<Vec<MemRow>, CliError> {
    registry
        .query(sql, params, |row| {
            Ok(MemRow {
                id: row.get(0)?,
                kind: row.get(1)?,
                title: row.get(2)?,
                body: row.get(3)?,
                tags: row.get(4)?,
                pinned: row.get(5)?,
                created_at: row.get(6)?,
                updated_at: row.get(7)?,
            })
        })
        .map_err(registry_error)
}

fn render_list_json(rows: &[MemRow]) -> String {
    let items = rows
        .iter()
        .map(|row| {
            format!(
                "  {{\n    \"id\": {},\n    \"kind\": {},\n    \"title\": {},\n    \"pinned\": {},\n    \"created_at\": {}\n  }}",
                json(&row.id), json(&row.kind), json(&row.title), row.pinned, row.created_at
            )
        })
        .collect::<Vec<_>>();
    format!("[\n{}\n]", items.join(",\n"))
}

fn render_search_json(rows: &[MemRow]) -> String {
    let items = rows
        .iter()
        .map(|row| {
            format!(
                "  {{\n    \"id\": {},\n    \"kind\": {},\n    \"title\": {},\n    \"pinned\": {}\n  }}",
                json(&row.id), json(&row.kind), json(&row.title), row.pinned
            )
        })
        .collect::<Vec<_>>();
    format!("[\n{}\n]", items.join(",\n"))
}

fn render_show_json(row: &MemRow) -> String {
    format!(
        "{{\n  \"id\": {},\n  \"kind\": {},\n  \"title\": {},\n  \"body\": {},\n  \"tags\": {},\n  \"pinned\": {},\n  \"created_at\": {},\n  \"updated_at\": {}\n}}",
        json(&row.id),
        json(&row.kind),
        json(&row.title),
        json(&row.body),
        json(&row.tags),
        row.pinned,
        row.created_at,
        row.updated_at
    )
}

fn render_table(columns: &[&str], rows: &[Vec<String>]) -> String {
    if rows.is_empty() {
        return String::new();
    }
    let mut widths = columns
        .iter()
        .map(|column| column.len())
        .collect::<Vec<_>>();
    for row in rows {
        for (index, cell) in row.iter().enumerate() {
            widths[index] = widths[index].max(cell.len());
        }
    }
    let line = |cells: &[String]| {
        cells
            .iter()
            .enumerate()
            .map(|(index, cell)| format!("{cell:<width$}", width = widths[index]))
            .collect::<Vec<_>>()
            .join("  ")
    };
    let header = columns
        .iter()
        .map(|value| value.to_string())
        .collect::<Vec<_>>();
    let separator = widths
        .iter()
        .map(|width| "-".repeat(*width))
        .collect::<Vec<_>>();
    let mut output = vec![line(&header), line(&separator)];
    output.extend(rows.iter().map(|row| line(row)));
    output.join("\n")
}

fn json(value: &str) -> String {
    serde_json::to_string(value).expect("serializing a string cannot fail")
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

fn write_if_nonempty(context: &mut ExecutionContext, output: &str) -> Result<(), CliError> {
    if output.is_empty() {
        Ok(())
    } else {
        write_stdout(context, output)
    }
}

fn write_stdout(context: &mut ExecutionContext, output: &str) -> Result<(), CliError> {
    let mut bytes = output.as_bytes().to_vec();
    bytes.push(b'\n');
    context
        .write_stdout(&bytes)
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

fn registry_error(error: shepherd::registry::Error) -> CliError {
    CliError::message(error.to_string())
}
