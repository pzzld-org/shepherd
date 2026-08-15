//! Context-free native model-map command.
//!
//! The legacy `models` family is a pure inspection surface. Its default path
//! must therefore work in an isolated directory without creating a repository,
//! user home, database, or configuration file. An explicit canonical config
//! remains opt-in through the shared global `--config` switch.

use std::{
    collections::BTreeSet,
    fs,
    io::{self, Write},
};

use shepherd::{compiler::HarnessProfile, settings::ModelsConfig};

use crate::{
    ContextInputs, ExecutionContext,
    interface::{CliError, CliGlobals},
};

const ROLES: [&str; 9] = [
    "root",
    "planter",
    "engineer",
    "conductor",
    "critic",
    "discovery",
    "coder",
    "auditor",
    "worker",
];
const HARNESSES: [&str; 3] = ["claude", "codex", "pi"];
const USAGE: &str = "shepherd models <resolve|show> [args]\n\n  resolve <role>        Echo the portable model hint for one role.\n  resolve <role> --harness <claude|codex|pi>\n                        Resolve the hint through the compiler's canonical\n                        harness profile.\n                        Roles: root planter engineer conductor critic\n                               discovery coder auditor worker\n  show [--md|--json]    Print the full resolved 9-role hint table + source.\n\nThe [models] block in .shepherd/shepherd.toml is the one project map. Unset\nroles use portable defaults: root = inherit-caller; planter/engineer =\nreasoning-high; all other roles = standard. See docs/configuration.md §models.";
const TEXT_FOOTER: &str = "root is advisory (your live session model). Spawned roles resolve their\nportable hint through the Rust compiler's Claude, Codex, or Pi profile.\nSee docs/configuration.md §models.";
const MD_FOOTER: &str = "_root is advisory: it names the model your live session should run; a config key cannot rebind a running main-chat session._";

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
pub struct WaveAModelsCmd {
    /// Print the canonical models usage contract.
    #[arg(short = 'h', long = "help")]
    help: bool,
    #[command(subcommand)]
    action: Option<ModelsAction>,
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
enum ModelsAction {
    /// Print the canonical models usage contract.
    Help,
    /// Resolve one role's model slug.
    Resolve(ModelsResolveCmd),
    /// Render every resolved role.
    Show(ModelsShowCmd),
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
#[command(disable_help_flag = true)]
struct ModelsResolveCmd {
    /// Role to resolve. Kept optional so the legacy usage message remains stable.
    role: Option<String>,
    /// Translate an intent slug to one harness's native spelling.
    #[arg(long)]
    harness: Option<String>,
    /// Emit the one-role resolution as JSON.
    #[arg(long)]
    json: bool,
    /// Print the canonical models usage contract.
    #[arg(short = 'h', long = "help")]
    help: bool,
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
#[command(disable_help_flag = true)]
struct ModelsShowCmd {
    /// Render a markdown table.
    #[arg(long)]
    md: bool,
    /// Render the role map as JSON.
    #[arg(long)]
    json: bool,
    /// Print the canonical models usage contract.
    #[arg(short = 'h', long = "help")]
    help: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ModelRow {
    role: &'static str,
    model: String,
    source: ModelSource,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ModelSource {
    Config,
    Default,
}

impl ModelSource {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Config => "config",
            Self::Default => "default",
        }
    }
}

impl WaveAModelsCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        if self.help {
            return write_stdout(USAGE);
        }
        match self.action {
            Some(ModelsAction::Help) => write_stdout(USAGE),
            Some(ModelsAction::Resolve(command)) => command.run(globals),
            Some(ModelsAction::Show(command)) => command.run(globals),
            None => write_stdout(&render_text(&resolve_rows(&globals)?)),
        }
    }
}

impl ModelsResolveCmd {
    fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        if self.help {
            return write_stdout(USAGE);
        }
        let Some(role) = self.role.as_deref() else {
            return Err(CliError::message_with_code(
                "usage: shepherd models resolve <role>",
                2,
            ));
        };
        if !ROLES.contains(&role) {
            return Err(CliError::message_with_code(
                format!("unknown role: {role} (valid: {})", ROLES.join(" ")),
                2,
            ));
        }
        if let Some(harness) = self.harness.as_deref()
            && !HARNESSES.contains(&harness)
        {
            return Err(CliError::message_with_code(
                format!(
                    "unknown harness: {harness} (valid: {})",
                    HARNESSES.join(" ")
                ),
                2,
            ));
        }

        let row = resolve_rows(&globals)?
            .into_iter()
            .find(|row| row.role == role)
            .expect("validated role exists in the fixed role map");
        let model = match self.harness.as_deref() {
            Some(harness) => translate_for_harness(&row.model, harness)?,
            None => row.model.clone(),
        };
        if self.json {
            let mut lines = vec![
                "{".to_owned(),
                format!("  \"role\": {},", json_string(row.role)),
                format!("  \"model\": {},", json_string(&model)),
                format!("  \"source\": {}", json_string(row.source.as_str())),
            ];
            if let Some(harness) = self.harness {
                let last = lines.pop().expect("JSON source line exists");
                lines.push(format!("{last},"));
                lines.push(format!("  \"harness\": {}", json_string(&harness)));
            }
            lines.push("}".to_owned());
            write_stdout(&lines.join("\n"))
        } else {
            write_stdout(&model)
        }
    }
}

impl ModelsShowCmd {
    fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        if self.help {
            return write_stdout(USAGE);
        }
        let rows = resolve_rows(&globals)?;
        if self.json {
            write_stdout(&render_json(&rows))
        } else if self.md {
            write_stdout(&render_markdown(&rows))
        } else {
            write_stdout(&render_text(&rows))
        }
    }
}

fn resolve_rows(globals: &CliGlobals) -> Result<Vec<ModelRow>, CliError> {
    // Default inspection remains side-effect-free and does not require a git
    // checkout. `--config` opts into the canonical discovery boundary.
    let (models, configured_roles) = match &globals.config {
        None => (ModelsConfig::default(), BTreeSet::new()),
        Some(_) => explicit_models(globals)?,
    };
    Ok(ROLES
        .into_iter()
        .map(|role| ModelRow {
            role,
            model: model_for(&models, role).to_owned(),
            source: if configured_roles.contains(role) {
                ModelSource::Config
            } else {
                ModelSource::Default
            },
        })
        .collect())
}

fn explicit_models(
    globals: &CliGlobals,
) -> Result<(ModelsConfig, BTreeSet<&'static str>), CliError> {
    let cwd = std::env::current_dir()
        .map_err(|error| CliError::message(format!("cannot resolve current directory: {error}")))?;
    let mut inputs = ContextInputs::from_environment(cwd)
        .map_err(|error| CliError::message(error.to_string()))?;
    inputs.explicit_config = globals.config.clone();
    inputs.verbosity = globals.verbosity;
    let context =
        ExecutionContext::discover(inputs).map_err(|error| CliError::message(error.to_string()))?;
    let config_path = context
        .config_sources
        .first()
        .map(|source| source.path.as_path())
        .ok_or_else(|| {
            CliError::message("explicit models configuration did not contribute a source")
        })?;
    let contents = fs::read_to_string(config_path).map_err(|error| {
        CliError::message(format!(
            "cannot read explicit models configuration {}: {error}",
            config_path.display()
        ))
    })?;
    let document: toml::Value = toml::from_str(&contents).map_err(|error| {
        CliError::message(format!(
            "cannot parse explicit models configuration {}: {error}",
            config_path.display()
        ))
    })?;
    let configured_roles = document
        .get("models")
        .and_then(toml::Value::as_table)
        .map(|models| {
            ROLES
                .into_iter()
                .filter(|role| models.contains_key(*role))
                .collect()
        })
        .unwrap_or_default();
    Ok((context.config.models, configured_roles))
}

fn model_for<'a>(models: &'a ModelsConfig, role: &str) -> &'a str {
    match role {
        "root" => &models.root,
        "planter" => &models.planter,
        "engineer" => &models.engineer,
        "conductor" => &models.conductor,
        "critic" => &models.critic,
        "discovery" => &models.discovery,
        "coder" => &models.coder,
        "auditor" => &models.auditor,
        "worker" => &models.worker,
        _ => unreachable!("callers validate against the fixed role map"),
    }
}

fn translate_for_harness(model_hint: &str, harness: &str) -> Result<String, CliError> {
    let profile = HarnessProfile::canonical()
        .into_iter()
        .find(|profile| profile.target.as_str() == harness)
        .expect("callers validate against the fixed harness map");
    let resolution = profile.model_by_hint.get(model_hint).ok_or_else(|| {
        CliError::message_with_code(
            format!("unknown model hint `{model_hint}` for {harness}"),
            2,
        )
    })?;
    Ok(resolution
        .model
        .as_ref()
        .or(resolution.profile.as_ref())
        .cloned()
        .unwrap_or_else(|| model_hint.to_owned()))
}

fn render_text(rows: &[ModelRow]) -> String {
    let mut lines = vec!["shepherd model map (resolved)".to_owned()];
    lines.extend(rows.iter().map(|row| {
        format!(
            "  {:<10} {:<10} ({})",
            row.role,
            row.model,
            row.source.as_str()
        )
    }));
    lines.push(String::new());
    lines.push(TEXT_FOOTER.to_owned());
    lines.join("\n")
}

fn render_markdown(rows: &[ModelRow]) -> String {
    let mut lines = vec![
        "| role | model | source |".to_owned(),
        "|---|---|---|".to_owned(),
    ];
    lines.extend(rows.iter().map(|row| {
        format!(
            "| {} | `{}` | {} |",
            row.role,
            row.model,
            row.source.as_str()
        )
    }));
    lines.push(String::new());
    lines.push(MD_FOOTER.to_owned());
    lines.join("\n")
}

fn render_json(rows: &[ModelRow]) -> String {
    let entries = rows.iter().map(|row| {
        format!(
            "  \"{}\": {{\"model\": {}, \"source\": {}}}",
            row.role,
            json_string(&row.model),
            json_string(row.source.as_str())
        )
    });
    format!("{{\n{}\n}}", entries.collect::<Vec<_>>().join(",\n"))
}

fn json_string(value: &str) -> String {
    serde_json::to_string(value).expect("serializing a string cannot fail")
}

fn write_stdout(text: &str) -> Result<(), CliError> {
    let mut stdout = io::stdout().lock();
    stdout
        .write_all(text.as_bytes())
        .and_then(|()| stdout.write_all(b"\n"))
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

#[cfg(test)]
mod tests {
    use super::{
        ModelRow, ModelSource, render_json, render_markdown, render_text, translate_for_harness,
    };

    fn defaults() -> Vec<ModelRow> {
        vec![
            ModelRow {
                role: "root",
                model: "inherit-caller".into(),
                source: ModelSource::Default,
            },
            ModelRow {
                role: "coder",
                model: "standard".into(),
                source: ModelSource::Default,
            },
        ]
    }

    #[test]
    fn renderers_preserve_the_legacy_row_order_and_shape() {
        let rows = defaults();
        assert_eq!(
            render_json(&rows),
            "{\n  \"root\": {\"model\": \"inherit-caller\", \"source\": \"default\"},\n  \"coder\": {\"model\": \"standard\", \"source\": \"default\"}\n}"
        );
        assert!(render_text(&rows).starts_with("shepherd model map (resolved)\n"));
        assert!(render_markdown(&rows).starts_with("| role | model | source |\n"));
    }

    #[test]
    fn harness_translation_fails_closed_for_unknown_claude_models() {
        assert_eq!(
            translate_for_harness("reasoning-high", "claude").expect("known hint"),
            "opus[1m]"
        );
        assert_eq!(
            translate_for_harness("reasoning-high", "codex").expect("known hint"),
            "reasoning-high"
        );
        assert_eq!(
            translate_for_harness("reasoning-high", "pi").expect("known hint"),
            "opus"
        );
        assert!(translate_for_harness("custom", "claude").is_err());
    }
}
