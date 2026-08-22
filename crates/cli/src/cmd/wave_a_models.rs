//! Read-only native model-map command.
//!
//! The `models` family is a read-only inspection surface. In a project it loads
//! canonical model configuration for the requested or environment harness. In
//! an isolated directory with no explicit config it remains context-free and
//! materializes typed defaults without creating any filesystem state.

use std::{
    collections::BTreeSet,
    fs,
    io::{self, Write},
    path::Path,
};

use shepherd::{
    Harness,
    compiler::HarnessProfile,
    settings::{ModelsConfig, PiModelTargetsConfig},
};

use crate::{
    ContextError, ContextInputs, ExecutionContext,
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
// `root` is the canonical spelling on THIS surface only: it is the literal
// `[models]` TOML key operators write (`ModelsConfig::root`,
// `crates/core/src/settings.rs:546`), and `docs/configuration.md`'s default
// table is cross-checked against that field name by
// `scripts/check-workspace.sh`'s `rule_model_defaults_match_the_docs`. Every
// other surface in this plugin -- `content/roles/shepherd.md`,
// `skills/shepherd/SKILL.md`, `agents/shepherd.md`, the `shepherd:shepherd`
// subagent type, and `role_tier` in `crates/core/src/guard/engine.rs` --
// spells the same role `shepherd`. Renaming the models role to match would
// ripple into `crates/core` and `docs/`, both outside this file's scope, so
// `shepherd` is a documented INPUT alias that resolves to `root`, never a
// tenth entry in `ROLES` and never a second canonical spelling.
const ROLE_ALIASES: [(&str, &str); 1] = [("shepherd", "root")];
const USAGE: &str = "shepherd models <resolve|show> [args]\n\n  resolve <role>        Echo the portable model hint for one role.\n  resolve <role> --harness <claude|codex|pi>\n                        Resolve the hint to a harness-native target. Pi uses\n                        the closed model_targets.pi config map.\n                        Roles: root planter engineer conductor critic\n                               discovery coder auditor worker\n                        Alias: shepherd -> root (the [models] root config key\n                               is canonical here; content/, the guard engine,\n                               and the agent cards spell this same role\n                               shepherd).\n  show [--md|--json]    Print the full resolved 9-role hint table + source.\n  show --harness <claude|codex|pi> [--md|--json]\n                        Render every role's harness-native model spelling\n                        instead of the portable hint.\n\nThe [models] block in .shepherd/shepherd.toml is the one project map. Unset\nroles use portable defaults: root/planter/engineer/conductor =\nreasoning-high; discovery = economy; all others = standard. See\ndocs/configuration.md §models.";
const TEXT_FOOTER: &str = "root is advisory (your live session model). Spawned roles resolve their\nportable hint through compiler-owned harness policy plus configured concrete targets.\nSee docs/configuration.md §models.";
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
    /// Translate every row's model to one harness's native spelling.
    #[arg(long)]
    harness: Option<String>,
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
            None => {
                let (rows, _) = resolve_rows(&globals, None)?;
                write_stdout(&render_text(&rows))
            }
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
        // Normalize an alias input (e.g. `shepherd`) to its canonical `ROLES`
        // spelling BEFORE the membership check and the row lookup below, so
        // both see only canonical role strings.
        let role = canonical_role(role);
        if !ROLES.contains(&role) {
            return Err(CliError::message_with_code(unknown_role_message(role), 2));
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

        let requested_harness = self.harness.as_deref().map(harness_from_name);
        let (rows, pi_targets) = resolve_rows(&globals, requested_harness)?;
        let row = rows
            .into_iter()
            .find(|row| row.role == role)
            .expect("validated role exists in the fixed role map");
        let model = match self.harness.as_deref() {
            Some(harness) => translate_for_harness(&row.model, harness, &pi_targets)?,
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

        let requested_harness = self.harness.as_deref().map(harness_from_name);
        let (mut rows, pi_targets) = resolve_rows(&globals, requested_harness)?;
        if let Some(harness) = self.harness.as_deref() {
            for row in &mut rows {
                row.model = translate_for_harness(&row.model, harness, &pi_targets)?;
            }
        }
        if self.json {
            write_stdout(&render_json(&rows))
        } else if self.md {
            write_stdout(&render_markdown(&rows))
        } else {
            write_stdout(&render_text(&rows))
        }
    }
}

fn resolve_rows(
    globals: &CliGlobals,
    requested_harness: Option<Harness>,
) -> Result<(Vec<ModelRow>, PiModelTargetsConfig), CliError> {
    let cwd = std::env::current_dir()
        .map_err(|error| CliError::message(format!("cannot resolve current directory: {error}")))?;
    let outside_repository = !has_repository_marker(&cwd)?;
    let mut inputs = ContextInputs::from_environment(cwd)
        .map_err(|error| CliError::message(error.to_string()))?;
    inputs.explicit_config = globals.config.clone();
    if let Some(harness) = requested_harness {
        inputs.active_harness = Some(harness);
    }
    inputs.verbosity = globals.verbosity;
    let context = match ExecutionContext::discover(inputs) {
        Ok(context) => Some(context),
        Err(ContextError::Primary(_)) if globals.config.is_none() && outside_repository => None,
        Err(error) => return Err(CliError::message(error.to_string())),
    };
    let (models, configured_roles, pi_targets) = if let Some(context) = context {
        // The loader already walked every merged layer's parsed table once to
        // build `explicit_keys` (see `shepherd_core::loader::LoadedConfig`); a
        // role is "configured" exactly when its dotted `models.<role>` key was
        // present in some layer, never by comparing the merged value against
        // `ModelsConfig::default()`.
        let configured_roles = ROLES
            .into_iter()
            .filter(|role| context.explicit_keys.contains(&format!("models.{role}")))
            .collect();
        (
            context.config.models,
            configured_roles,
            context.config.model_targets.pi,
        )
    } else {
        (
            ModelsConfig::default(),
            BTreeSet::new(),
            PiModelTargetsConfig::default(),
        )
    };
    let rows = ROLES
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
        .collect();
    Ok((rows, pi_targets))
}

fn has_repository_marker(start: &Path) -> Result<bool, CliError> {
    for ancestor in start.ancestors() {
        match fs::symlink_metadata(ancestor.join(".git")) {
            Ok(_) => return Ok(true),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => {
                return Err(CliError::message(format!(
                    "cannot inspect repository marker below {}: {error}",
                    ancestor.display()
                )));
            }
        }
    }
    Ok(false)
}

fn harness_from_name(harness: &str) -> Harness {
    match harness {
        "claude" => Harness::ClaudeCode,
        "codex" => Harness::Codex,
        "pi" => Harness::Pi,
        _ => unreachable!("callers validate against the fixed harness map"),
    }
}

/// Map an input role spelling to its canonical `ROLES` spelling through
/// `ROLE_ALIASES`. A role with no alias entry passes through unchanged.
/// Aliases are input-only: the return value is always either the input
/// itself or a member of `ROLES`, never a synthesized third spelling.
fn canonical_role(role: &str) -> &str {
    ROLE_ALIASES
        .iter()
        .find(|(alias, _)| *alias == role)
        .map_or(role, |(_, canonical)| *canonical)
}

/// Build the `unknown role` error message from `ROLES` and `ROLE_ALIASES`
/// rather than a hand-typed literal, so the valid-role list and the alias
/// hint cannot drift out of sync with the const arrays that define them.
fn unknown_role_message(role: &str) -> String {
    let aliases = ROLE_ALIASES
        .iter()
        .map(|(alias, canonical)| format!("{alias} -> {canonical}"))
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "unknown role: {role} (valid: {}; alias: {aliases})",
        ROLES.join(" ")
    )
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

fn translate_for_harness(
    model_hint: &str,
    harness: &str,
    pi_targets: &PiModelTargetsConfig,
) -> Result<String, CliError> {
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
    if harness == "pi" {
        if model_hint == "inherit-caller" {
            return Ok("inherit".into());
        }
        return pi_targets
            .get(model_hint)
            .map(ToOwned::to_owned)
            .ok_or_else(|| {
                CliError::message_with_code(
                    format!(
                        "Pi model target missing for portable hint `{model_hint}`. Set \
                         `model_targets.pi.{model_hint} = \"provider/model:thinking\"` in Shepherd configuration."
                    ),
                    2,
                )
            });
    }
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
    use shepherd::settings::PiModelTargetsConfig;

    use super::{
        ModelRow, ModelSource, ROLE_ALIASES, ROLES, USAGE, canonical_role, render_json,
        render_markdown, render_text, translate_for_harness, unknown_role_message,
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
        let pi_targets = PiModelTargetsConfig {
            inherit_caller: "inherit".into(),
            reasoning_high: "openai-codex/gpt-5.6-sol:xhigh".into(),
            standard: "openai-codex/gpt-5.6-luna:max".into(),
            economy: "openai-codex/gpt-5.6-luna:max".into(),
        };
        assert_eq!(
            translate_for_harness("reasoning-high", "claude", &pi_targets).expect("known hint"),
            "opus[1m]"
        );
        assert_eq!(
            translate_for_harness("reasoning-high", "codex", &pi_targets).expect("known hint"),
            "reasoning-high"
        );
        assert_eq!(
            translate_for_harness("reasoning-high", "pi", &pi_targets).expect("known hint"),
            "openai-codex/gpt-5.6-sol:xhigh"
        );
        assert_eq!(
            translate_for_harness("inherit-caller", "pi", &PiModelTargetsConfig::default())
                .expect("Pi inheritance is concrete"),
            "inherit"
        );
        assert!(translate_for_harness("standard", "pi", &PiModelTargetsConfig::default()).is_err());
        assert!(translate_for_harness("custom", "claude", &pi_targets).is_err());
    }

    /// Anti-drift tripwire: `ROLES` and the USAGE text are two of the three
    /// hand-maintained copies of the role vocabulary this step exists to stop
    /// from drifting apart (the third is the pinned CLI-test assertion in
    /// `tests/wave_a_models_cli.rs`). This iterates `ROLES` and
    /// `ROLE_ALIASES` rather than checking today's nine literal names, so it
    /// fails the moment a role or alias is added to either const without also
    /// reaching the usage text.
    #[test]
    fn usage_names_every_role_and_every_alias_pair() {
        for role in ROLES {
            assert!(
                USAGE.contains(role),
                "a role was added to ROLES without reaching USAGE: `{role}` is \
                 missing from:\n{USAGE}"
            );
        }
        for (alias, canonical) in ROLE_ALIASES {
            let direction = format!("{alias} -> {canonical}");
            assert!(
                USAGE.contains(&direction),
                "an alias was added to ROLE_ALIASES without reaching USAGE: \
                 `{direction}` is missing from:\n{USAGE}"
            );
        }
    }

    #[test]
    fn canonical_role_maps_the_documented_alias_and_passes_through_everything_else() {
        assert_eq!(canonical_role("shepherd"), "root");
        assert_eq!(canonical_role("root"), "root");
        assert_eq!(canonical_role("coder"), "coder");
        assert_eq!(canonical_role("nonsense"), "nonsense");
    }

    #[test]
    fn unknown_role_message_names_the_alias_direction_and_every_valid_role() {
        let message = unknown_role_message("nonsense");
        assert_eq!(
            message,
            "unknown role: nonsense (valid: root planter engineer conductor \
             critic discovery coder auditor worker; alias: shepherd -> root)"
        );
        for role in ROLES {
            assert!(message.contains(role), "missing role `{role}`: {message}");
        }
    }
}
