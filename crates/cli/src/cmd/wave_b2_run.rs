//! Native `shepherd run` lifecycle commands.
//!
//! The only writable namespace is `ExecutionContext::runs_root`, which is
//! resolved against the primary checkout.  Every state mutation goes through
//! `RunStore`, preserving its advisory lock and atomic canonical writer.

use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};

use shepherd::{RunState, run::LaneState};

use crate::{
    ContextInputs, ExecutionContext, RunStore, RunStoreError,
    interface::{CliError, CliGlobals},
};

// Layout-v5 makes lane plans the only directory-shaped canonical run
// artifact. Reports/audits are disposable views and dispatch/graph are
// operational state; none is scaffolded as a durable run contract.
const RUN_SUBDIRS: [&str; 1] = ["lanes"];
const TRACKED_FILES: [&str; 6] = [
    "seed.md",
    "mesh.md",
    "plan.md",
    "phase0.md",
    "close.md",
    "handoff.md",
];
const RUN_STATUSES: [&str; 5] = ["planted", "planned", "executing", "closing", "closed"];
const LANE_STATES: [&str; 4] = ["pending", "in-progress", "complete", "error"];
const LEDGER_FILE: &str = "auditor-verdicts.txt";

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
pub struct WaveB2RunCmd {
    #[command(subcommand)]
    action: Option<RunAction>,
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
enum RunAction {
    Init {
        run: Option<String>,
        #[arg(long, default_value = "sprint")]
        kind: String,
        #[arg(long, default_value = "")]
        branch: String,
        #[arg(long, default_value = "")]
        base: String,
        #[arg(long, default_value = "")]
        version: String,
        #[arg(long)]
        force: bool,
    },
    Rename {
        old: String,
        new: String,
    },
    Canonicalize {
        run: Option<String>,
        #[arg(long = "all")]
        all_runs: bool,
        #[arg(long)]
        dry_run: bool,
    },
    Show {
        run: String,
        #[arg(long)]
        json: bool,
    },
    List {
        #[arg(long)]
        json: bool,
    },
    Claim {
        run: String,
        #[arg(long)]
        json: bool,
    },
    Migrate {
        run: Option<String>,
        #[arg(long = "all")]
        all_runs: bool,
    },
    Set {
        run: String,
        #[arg(long, default_value = "")]
        status: String,
        #[arg(long, default_value = "")]
        seed: String,
        #[arg(long, default_value = "")]
        plan: String,
    },
    Lane {
        #[command(subcommand)]
        action: LaneAction,
    },
    Wave {
        #[command(subcommand)]
        action: WaveAction,
    },
    Ledger {
        #[command(subcommand)]
        action: LedgerAction,
    },
    Layout {
        run: String,
        #[arg(long)]
        repair: bool,
        #[arg(long)]
        json: bool,
    },
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
enum LaneAction {
    Add {
        run: String,
        lane: String,
        #[arg(long, default_value = "")]
        plan: String,
        #[arg(long, default_value = "")]
        worktree: String,
        #[arg(long, default_value = "")]
        branch: String,
    },
    Set {
        run: String,
        lane: String,
        #[arg(long)]
        state: String,
    },
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
enum WaveAction {
    Accept {
        run: String,
        lane: String,
        #[arg(long)]
        commit: String,
    },
    Merged {
        run: String,
        lane: String,
    },
    Pending {
        run: String,
        #[arg(long)]
        json: bool,
    },
    Verify {
        run: String,
        #[arg(long)]
        wave: Option<u32>,
        #[arg(long)]
        json: bool,
    },
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
enum LedgerAction {
    Path {
        run: Option<String>,
        #[arg(long)]
        check: bool,
    },
    Check {
        run: Option<String>,
        #[arg(long)]
        json: bool,
    },
}

impl WaveB2RunCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let mut context = context(globals)?;
        let Some(action) = self.action else {
            return output(&mut context, run_usage());
        };
        match action {
            RunAction::Init {
                run,
                kind,
                branch,
                base,
                version,
                force,
            } => init(&mut context, run, &kind, &branch, &base, &version, force),
            RunAction::Rename { old, new } => rename(&mut context, &old, &new, true),
            RunAction::Canonicalize {
                run,
                all_runs,
                dry_run,
            } => canonicalize(&mut context, run, all_runs, dry_run),
            RunAction::Show { run, json } => show(&mut context, &run, json),
            RunAction::List { json } => list(&mut context, json),
            RunAction::Claim { run, json } => claim(&mut context, &run, json),
            RunAction::Migrate { run, all_runs } => migrate(&mut context, run, all_runs),
            RunAction::Set {
                run,
                status,
                seed,
                plan,
            } => set(&mut context, &run, &status, &seed, &plan),
            RunAction::Lane { action } => lane(&mut context, action),
            RunAction::Wave { action } => wave(&mut context, action),
            RunAction::Ledger { action } => ledger(&mut context, action),
            RunAction::Layout { run, repair, json } => layout(&mut context, &run, repair, json),
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

fn init(
    context: &mut ExecutionContext,
    requested: Option<String>,
    kind: &str,
    branch: &str,
    base: &str,
    version: &str,
    force: bool,
) -> Result<(), CliError> {
    if !matches!(kind, "sprint" | "patch-arc") {
        return usage("invalid --kind: sprint | patch-arc");
    }
    let run = match requested {
        Some(run) => run,
        None => derive_id(if version.is_empty() { branch } else { version }, kind)?,
    };
    validate_id("run", &run)?;
    if !is_canonical(&run) && !force {
        return usage(format!(
            "non-canonical run id: {run:?} -- pass --force to override"
        ));
    }
    if !is_canonical(&run) && force {
        error_output(
            context,
            &format!("WARNING: {run:?} is a non-canonical run id, forced by --force."),
        )?;
    }
    let path = state_path(context, &run)?;
    if path.exists() {
        return missing_or_conflict(format!("run already exists: {run}"));
    }
    scaffold(context, &run)?;
    let mut state = RunState {
        schema_version: 1,
        run: run.clone(),
        kind: kind.into(),
        branch: branch.into(),
        base: base.into(),
        seed: String::new(),
        plan: String::new(),
        status: "planted".into(),
        lanes: Vec::new(),
        updated_at: now_seconds(context),
        extra: Default::default(),
    };
    state.updated_at = now_seconds(context);
    RunStore::new(&path)
        .initialize(&state)
        .map_err(store_error)?;
    output(context, &path.display().to_string())
}

fn show(context: &mut ExecutionContext, run: &str, json: bool) -> Result<(), CliError> {
    let state = load(context, run)?;
    if json {
        return output(context, &state.to_canonical_json());
    }
    let mut lines = vec![
        format!("run: {}", state.run),
        format!("kind: {}", state.kind),
        format!("status: {}", state.status),
        format!("branch: {}", empty_dash(&state.branch)),
        format!("base: {}", empty_dash(&state.base)),
        format!("seed: {}", empty_dash(&state.seed)),
        format!("plan: {}", empty_dash(&state.plan)),
        format!("lanes: {}", state.lanes.len()),
    ];
    for lane in state.lanes {
        lines.push(format!(
            "  {}: {}{}",
            lane.id,
            lane.state,
            if lane.accepted_commit.is_some() && !lane.merged {
                " PENDING-MERGE"
            } else {
                ""
            }
        ));
    }
    output(context, &lines.join("\n"))
}

fn list(context: &mut ExecutionContext, json: bool) -> Result<(), CliError> {
    let mut runs = run_names(context, true)?;
    runs.sort();
    if json {
        return output(
            context,
            &serde_json::to_string(&runs).map_err(|error| CliError::message(error.to_string()))?,
        );
    }
    output(context, &runs.join("\n"))
}

fn claim(context: &mut ExecutionContext, run: &str, json: bool) -> Result<(), CliError> {
    let state = load(context, run)?;
    if state.schema_version > 1 {
        return usage(format!(
            "run {run} is schema_version {}, newer than this CLI supports claiming (max 1)",
            state.schema_version
        ));
    }
    let path = state_path(context, run)?;
    if json {
        return output(context, &serde_json::to_string_pretty(&serde_json::json!({"run": state.run, "schema_version": state.schema_version, "status": state.status, "lane_count": state.lanes.len(), "path": path})).map_err(|error| CliError::message(error.to_string()))?);
    }
    output(
        context,
        &format!(
            "claimed {} (schema {}, status {}, {} lane(s)): {}",
            state.run,
            state.schema_version,
            state.status,
            state.lanes.len(),
            path.display()
        ),
    )
}

fn set(
    context: &mut ExecutionContext,
    run: &str,
    status: &str,
    seed: &str,
    plan: &str,
) -> Result<(), CliError> {
    if status.is_empty() && seed.is_empty() && plan.is_empty() {
        return usage("nothing to set (pass --status, --seed, and/or --plan)");
    }
    if !status.is_empty() && !RUN_STATUSES.contains(&status) {
        return usage(format!(
            "invalid --status: {status} (valid: {})",
            RUN_STATUSES.join(", ")
        ));
    }
    update(context, run, |state| {
        if !status.is_empty() {
            state.status = status.into();
        }
        if !seed.is_empty() {
            state.seed = seed.into();
        }
        if !plan.is_empty() {
            state.plan = plan.into();
        }
        Ok(())
    })?;
    output(context, &format!("updated {run}"))
}

fn lane(context: &mut ExecutionContext, action: LaneAction) -> Result<(), CliError> {
    match action {
        LaneAction::Add {
            run,
            lane,
            plan,
            worktree,
            branch,
        } => {
            validate_id("lane", &lane)?;
            let run_dir = run_dir(context, &run)?;
            update(context, &run, |state| {
                if state.lanes.iter().any(|entry| entry.id == lane) {
                    return Err(RunStoreError::mutation(format!(
                        "lane already registered: {lane}"
                    )));
                }
                state.lanes.push(LaneState {
                    id: lane.clone(),
                    plan: if plan.is_empty() {
                        format!("lanes/{lane}/plan.md")
                    } else {
                        plan
                    },
                    worktree,
                    branch,
                    state: "pending".into(),
                    accepted_commit: None,
                    merged: false,
                    updated_at: 0,
                    extra: Default::default(),
                });
                Ok(())
            })?;
            create_dir_safe(&run_dir.join("lanes").join(&lane))?;
            output(context, &format!("lane {lane} registered in {run}"))
        }
        LaneAction::Set { run, lane, state } => {
            if !LANE_STATES.contains(&state.as_str()) {
                return usage(format!(
                    "invalid --state: {state} (valid: {})",
                    LANE_STATES.join(", ")
                ));
            }
            update(context, &run, |document| {
                let Some(entry) = document.lanes.iter_mut().find(|entry| entry.id == lane) else {
                    return Err(RunStoreError::mutation(format!(
                        "no such lane: {lane} in run {run}"
                    )));
                };
                entry.state = state.clone();
                Ok(())
            })?;
            output(context, &format!("lane {lane} -> {state}"))
        }
    }
}

fn wave(context: &mut ExecutionContext, action: WaveAction) -> Result<(), CliError> {
    match action {
        WaveAction::Accept { run, lane, commit } => {
            if commit.is_empty() {
                return usage("--commit must be non-empty");
            }
            update(context, &run, |state| {
                let Some(entry) = state.lanes.iter_mut().find(|entry| entry.id == lane) else {
                    return Err(RunStoreError::mutation(format!(
                        "no such lane: {lane} in run {run}"
                    )));
                };
                entry.accepted_commit = Some(commit.clone());
                entry.merged = false;
                Ok(())
            })?;
            output(context, &format!("accepted {lane} @ {commit}"))
        }
        WaveAction::Merged { run, lane } => {
            let commit = update(context, &run, |state| {
                let Some(entry) = state.lanes.iter_mut().find(|entry| entry.id == lane) else {
                    return Err(RunStoreError::mutation(format!(
                        "no such lane: {lane} in run {run}"
                    )));
                };
                let Some(commit) = entry.accepted_commit.clone() else {
                    return Err(RunStoreError::mutation(format!(
                        "lane {lane} has no accepted commit to mark merged"
                    )));
                };
                entry.merged = true;
                Ok(commit)
            })?;
            output(context, &format!("merged {lane} @ {commit}"))
        }
        WaveAction::Pending { run, json } => pending(context, &run, json),
        WaveAction::Verify { run, wave, json } => verify(context, &run, wave, json),
    }
}

fn pending(context: &mut ExecutionContext, run: &str, json: bool) -> Result<(), CliError> {
    let state = load(context, run)?;
    let pending: Vec<_> = state
        .lanes
        .iter()
        .filter(|lane| lane.accepted_commit.is_some() && !lane.merged)
        .collect();
    let plan = fs::read_to_string(run_dir(context, run)?.join("plan.md")).unwrap_or_default();
    let declared = declared_lanes(&plan);
    let missing: Vec<_> = declared
        .into_iter()
        .filter(|lane| {
            !state
                .lanes
                .iter()
                .any(|entry| entry.id.eq_ignore_ascii_case(lane))
        })
        .collect();
    if json {
        output(context, &serde_json::to_string(&serde_json::json!({"pending": pending.iter().map(|lane| serde_json::json!({"lane": lane.id, "commit": lane.accepted_commit})).collect::<Vec<_>>(), "missing_lanes": missing, "ok": pending.is_empty() && missing.is_empty()})).map_err(|error| CliError::message(error.to_string()))?)?;
    } else {
        let rows = pending
            .iter()
            .map(|lane| {
                format!(
                    "{}\t{}",
                    lane.id,
                    lane.accepted_commit.as_deref().unwrap_or_default()
                )
            })
            .chain(
                missing
                    .iter()
                    .map(|lane| format!("{lane}\tMISSING-DECLARED-LANE")),
            )
            .collect::<Vec<_>>()
            .join("\n");
        if !rows.is_empty() {
            output(context, &rows)?;
        }
    }
    if pending.is_empty() && missing.is_empty() {
        Ok(())
    } else {
        Err(CliError::message_with_code(
            "wave pending: accepted work remains or declared lanes are missing",
            6,
        ))
    }
}

fn layout(
    context: &mut ExecutionContext,
    run: &str,
    repair: bool,
    json: bool,
) -> Result<(), CliError> {
    let path = state_path(context, run)?;
    if !path.is_file() {
        return no_such_run(context, run);
    }
    let base = run_dir(context, run)?;
    let mut missing = RUN_SUBDIRS
        .iter()
        .filter(|name| !base.join(name).is_dir())
        .copied()
        .collect::<Vec<_>>();
    let mut created = Vec::new();
    if repair {
        for name in &missing {
            create_dir_safe(&base.join(name))?;
            created.push(*name);
        }
        missing.retain(|name| !base.join(name).is_dir());
    }
    if json {
        output(context, &serde_json::to_string_pretty(&serde_json::json!({"run":run,"run_dir":base,"subdirs":RUN_SUBDIRS,"missing":missing,"created":created,"tracked_files_present":TRACKED_FILES.iter().filter(|name| base.join(name).is_file()).collect::<Vec<_>>(),"ok":missing.is_empty()})).map_err(|error| CliError::message(error.to_string()))?)?;
    } else {
        let mut lines = RUN_SUBDIRS
            .iter()
            .map(|name| {
                format!(
                    "{:<12}{}",
                    format!("{name}/"),
                    if missing.contains(name) {
                        "missing"
                    } else if created.contains(name) {
                        "created"
                    } else {
                        "ok"
                    }
                )
            })
            .collect::<Vec<_>>();
        lines.push(format!(
            "tracked artifacts: {}",
            TRACKED_FILES
                .iter()
                .filter(|name| base.join(name).is_file())
                .copied()
                .collect::<Vec<_>>()
                .join(", ")
        ));
        output(context, &lines.join("\n"))?;
    }
    if missing.is_empty() {
        Ok(())
    } else {
        Err(CliError::message_with_code(
            format!(
                "layout incomplete ({}) — re-run with --repair",
                missing.join(", ")
            ),
            6,
        ))
    }
}

fn rename(
    context: &mut ExecutionContext,
    old: &str,
    new: &str,
    announce: bool,
) -> Result<(), CliError> {
    validate_id("run", old)?;
    validate_id("run", new)?;
    if old == new {
        return usage("old and new run ids are identical");
    }
    let old_dir = run_dir(context, old)?;
    let new_dir = run_dir(context, new)?;
    if !old_dir.is_dir() {
        return Err(CliError::message_with_code(
            format!(
                "no such run directory: {old} (expected {})",
                old_dir.display()
            ),
            5,
        ));
    }
    if new_dir.exists() {
        return Err(CliError::message_with_code(
            format!("destination already exists: {new}"),
            5,
        ));
    }
    reject_symlink_path(&old_dir)?;
    reject_symlink_path(&new_dir)?;
    let registered = old_dir.join("run.json").is_file();
    fs::rename(&old_dir, &new_dir)
        .map_err(|error| CliError::message(format!("rename {old} -> {new}: {error}")))?;
    if registered {
        let path = state_path(context, new)?;
        RunStore::new(&path)
            .rewrite_from_raw(|bytes| {
                let mut state: RunState = serde_json::from_slice(bytes).map_err(|error| {
                    RunStoreError::mutation(format!(
                        "run.json for {old} could not be read: {error}"
                    ))
                })?;
                if state.run != old {
                    return Err(RunStoreError::mutation(format!(
                        "document run `{}` does not match renamed directory `{old}`",
                        state.run
                    )));
                }
                state.run = new.into();
                let old_prefix = format!("runs/{old}/");
                let new_prefix = format!("runs/{new}/");
                if state.seed.starts_with(&old_prefix) {
                    state.seed = format!("{new_prefix}{}", &state.seed[old_prefix.len()..]);
                }
                if state.plan.starts_with(&old_prefix) {
                    state.plan = format!("{new_prefix}{}", &state.plan[old_prefix.len()..]);
                }
                state.updated_at = now_seconds(context);
                Ok((state, ()))
            })
            .map_err(store_error)?;
    }
    if announce {
        output(
            context,
            &format!("renamed {old} -> {new}: {}", new_dir.display()),
        )
    } else {
        Ok(())
    }
}

fn canonicalize(
    context: &mut ExecutionContext,
    run: Option<String>,
    all_runs: bool,
    dry_run: bool,
) -> Result<(), CliError> {
    if context.config.branching.sprint_slug_pattern != "v{X}{Y}{Z}-dev{N}"
        || context.config.branching.patch_slug_pattern != "v{X}{Y}{Z}"
    {
        return usage(
            "run canonicalize supports only the default slug patterns; configured patterns require a native pattern parser before this route can be promoted",
        );
    }
    if run.is_some() == all_runs {
        return usage("pass exactly one of <run> or --all");
    }
    let targets = match run {
        Some(value) => vec![value],
        None => run_names(context, false)?,
    };
    if targets.is_empty() {
        return output(context, "no runs to canonicalize");
    }
    let mut lines = Vec::new();
    for target in targets {
        let source = run_dir(context, &target)?;
        if !source.is_dir() {
            return Err(CliError::message_with_code(
                format!(
                    "no such run directory: {target} (expected {})",
                    source.display()
                ),
                5,
            ));
        }
        if is_canonical(&target) {
            lines.push(format!("{target}: already canonical"));
            continue;
        }
        let Some(candidate) = canonical_suggestion(&target) else {
            lines.push(format!("{target}: no recognizable canonical form -- fix manually with: shepherd run rename {target} <new-id>"));
            continue;
        };
        if run_dir(context, &candidate)?.exists() {
            lines.push(format!("{target}: canonical form {candidate:?} already exists -- refusing to overwrite, fix manually"));
            continue;
        }
        if dry_run {
            lines.push(format!(
                "{target} -> {candidate} (dry run, no changes made)"
            ));
            continue;
        }
        rename(context, &target, &candidate, false)?;
        lines.push(format!(
            "{target} -> {candidate}: {}",
            run_dir(context, &candidate)?.display()
        ));
    }
    if !lines.is_empty() {
        output(context, &lines.join("\n"))
    } else {
        Ok(())
    }
}

fn migrate(
    context: &mut ExecutionContext,
    run: Option<String>,
    all_runs: bool,
) -> Result<(), CliError> {
    if run.is_some() == all_runs {
        return usage("pass exactly one of <run> or --all");
    }
    let targets = match run {
        Some(value) => vec![value],
        None => run_names(context, true)?,
    };
    if targets.is_empty() {
        return output(context, "no runs to migrate");
    }
    let mut lines = Vec::new();
    for run in targets {
        let path = state_path(context, &run)?;
        let applied = RunStore::new(&path)
            .rewrite_from_raw(|bytes| {
                let raw: serde_json::Value = serde_json::from_slice(bytes).map_err(|error| {
                    RunStoreError::mutation(format!(
                        "run.json for {run} could not be read: {error}"
                    ))
                })?;
                let (mut document, applied) = normalize_document(raw).map_err(|error| {
                    RunStoreError::mutation(error.message_text().unwrap_or("run migration failed"))
                })?;
                if document.run != run {
                    return Err(RunStoreError::mutation(format!(
                        "run.json for {run} has mismatched run identity `{}`",
                        document.run
                    )));
                }
                document.updated_at = now_seconds(context);
                Ok((document, applied))
            })
            .map_err(store_error)?;
        let migration_note = if applied.is_empty() {
            "no changes".to_owned()
        } else {
            applied.join(", ")
        };
        lines.push(format!(
            "migrated {run} ({migration_note}): {}",
            path.display()
        ));
    }
    output(context, &lines.join("\n"))
}

fn ledger(context: &mut ExecutionContext, action: LedgerAction) -> Result<(), CliError> {
    match action {
        LedgerAction::Path { run, check } => {
            let run = resolve_active(context, run)?;
            let path = run_dir(context, &run)?.join(LEDGER_FILE);
            output(context, &path.display().to_string())?;
            if check && local_ledger_exists(context, &run)? {
                return Err(CliError::message_with_code(
                    format!(
                        "divergent local ledger copy for {run}; use {}",
                        path.display()
                    ),
                    3,
                ));
            }
            Ok(())
        }
        LedgerAction::Check { run, json } => {
            ledger_check(context, resolve_active(context, run)?, json)
        }
    }
}

fn ledger_check(context: &mut ExecutionContext, run: String, json: bool) -> Result<(), CliError> {
    let primary = run_dir(context, &run)?.join(LEDGER_FILE);
    let primary_text = fs::read_to_string(&primary).map_err(|_| {
        CliError::message_with_code(
            format!("no ledger for run {run} (expected {})", primary.display()),
            5,
        )
    })?;
    let mut divergences = Vec::new();
    let git_output = Command::new("git")
        .args(["worktree", "list", "--porcelain"])
        .current_dir(&context.primary_root)
        .output();
    match git_output {
        Ok(output) if output.status.success() => {
            let worktree_text = String::from_utf8_lossy(&output.stdout);
            let worktrees = worktree_text
                .lines()
                .filter_map(|line| line.strip_prefix("worktree "))
                .map(str::to_owned)
                .collect::<Vec<_>>();
            for worktree in worktrees.into_iter().skip(1) {
                let candidate = Path::new(&worktree)
                    .join(context.namespace.file_name().unwrap_or_default())
                    .join("runs")
                    .join(&run)
                    .join(LEDGER_FILE);
                if let Ok(text) = fs::read_to_string(candidate) {
                    for row in normalized_rows(&text) {
                        if !normalized_rows(&primary_text).contains(&row) {
                            divergences.push(serde_json::json!({"worktree":worktree,"row":row}));
                        }
                    }
                }
            }
        }
        _ => {}
    }
    if json {
        output(context, &serde_json::to_string(&serde_json::json!({"run":run,"divergences":divergences,"ok":divergences.is_empty()})).map_err(|error| CliError::message(error.to_string()))?)?;
    } else if !divergences.is_empty() {
        output(
            context,
            &divergences
                .iter()
                .map(|value| {
                    format!(
                        "{}\t{}",
                        value["worktree"].as_str().unwrap_or_default(),
                        value["row"].as_str().unwrap_or_default()
                    )
                })
                .collect::<Vec<_>>()
                .join("\n"),
        )?;
    }
    if divergences.is_empty() {
        Ok(())
    } else {
        Err(CliError::message_with_code("worktree ledger divergence", 7))
    }
}

fn verify(
    context: &mut ExecutionContext,
    run: &str,
    wave: Option<u32>,
    json: bool,
) -> Result<(), CliError> {
    let base = run_dir(context, run)?;
    if !base.join("lanes").is_dir() {
        return Err(CliError::message_with_code(
            format!(
                "no lane plans for run {run} (expected {})",
                base.join("lanes").display()
            ),
            5,
        ));
    }
    let mut steps = Vec::new();
    for lane in fs::read_dir(base.join("lanes"))
        .map_err(|_| CliError::message_with_code(format!("no lane plans for run {run}"), 5))?
    {
        let lane = lane.map_err(|error| CliError::message(error.to_string()))?;
        let text = fs::read_to_string(lane.path().join("plan.md")).unwrap_or_default();
        steps.extend(parse_plan_steps(&text));
    }
    if let Some(wave) = wave {
        steps.retain(|step| step.wave == wave);
    }
    let ledger = fs::read_to_string(base.join(LEDGER_FILE)).unwrap_or_default();
    let rows = parse_ledger(&ledger);
    let malformed = ledger
        .lines()
        .enumerate()
        .filter(|(_, line)| {
            !line.trim().is_empty()
                && !line.trim().starts_with('#')
                && parse_ledger_line(line).is_none()
        })
        .map(|(line_no, line)| format!("MALFORMED-ROW\tline {}: {}", line_no + 1, line))
        .collect::<Vec<_>>();
    let mut findings = malformed;
    let mut rendered = Vec::new();
    for step in &steps {
        let winner = rows.iter().rev().find(|row| {
            row.lane == step.lane
                && row.wave == step.wave
                && (row.step.is_none() || row.step == Some(step.step))
        });
        rendered.push(format!(
            "{}\t{}\t{}",
            step.id(),
            winner.map_or("-", |row| row.verdict.as_str()),
            winner.map_or("-", |row| row.raw.as_str())
        ));
        match winner {
            None => findings.push(format!("NO-VERDICT\t{} has no ledger verdict", step.id())),
            Some(row) if row.verdict != "PASS" => findings.push(format!(
                "UNRESOLVED-VERDICT\t{} resolves to {}",
                step.id(),
                row.verdict
            )),
            _ => {}
        }
    }
    for row in &rows {
        if !steps.iter().any(|step| {
            step.lane == row.lane
                && step.wave == row.wave
                && (row.step.is_none() || row.step == Some(step.step))
        }) {
            findings.push(format!("ORPHAN-VERDICT\t{}", row.raw));
        }
    }
    if json {
        output(context, &serde_json::to_string(&serde_json::json!({"run":run,"wave":wave,"steps":rendered,"findings":findings,"ok":findings.is_empty()})).map_err(|error| CliError::message(error.to_string()))?)?;
    } else {
        if !rendered.is_empty() {
            output(context, &rendered.join("\n"))?;
        }
        if !findings.is_empty() {
            output(context, &format!("\nFINDINGS:\n{}", findings.join("\n")))?;
        }
    }
    if findings.is_empty() {
        Ok(())
    } else {
        Err(CliError::message_with_code("wave verification findings", 6))
    }
}

fn load(context: &ExecutionContext, run: &str) -> Result<RunState, CliError> {
    let path = state_path(context, run)?;
    reject_symlink_path(&path)?;
    RunStore::new(&path).load().map_err(|error| match error {
        RunStoreError::Io { source, .. } if source.kind() == std::io::ErrorKind::NotFound => {
            no_such_run_error(context, run)
        }
        other => store_error(other),
    })
}

fn update<T>(
    context: &ExecutionContext,
    run: &str,
    mutation: impl FnOnce(&mut RunState) -> Result<T, RunStoreError>,
) -> Result<T, CliError> {
    let path = state_path(context, run)?;
    reject_symlink_path(&path)?;
    RunStore::new(&path)
        .update(|state| {
            let value = mutation(state)?;
            state.updated_at = now_seconds(context);
            Ok(value)
        })
        .map_err(|error| match error {
            RunStoreError::Io { source, .. } if source.kind() == std::io::ErrorKind::NotFound => {
                no_such_run_error(context, run)
            }
            RunStoreError::Mutation(message) if message.starts_with("no such lane:") => {
                CliError::message_with_code(message, 5)
            }
            RunStoreError::Mutation(message) => CliError::message_with_code(message, 2),
            other => store_error(other),
        })
}

fn state_path(context: &ExecutionContext, run: &str) -> Result<PathBuf, CliError> {
    validate_id("run", run)?;
    Ok(context.runs_root.join(run).join("run.json"))
}

fn run_dir(context: &ExecutionContext, run: &str) -> Result<PathBuf, CliError> {
    validate_id("run", run)?;
    Ok(context.runs_root.join(run))
}

fn scaffold(context: &ExecutionContext, run: &str) -> Result<(), CliError> {
    let base = run_dir(context, run)?;
    create_dir_safe(&base)?;
    for name in RUN_SUBDIRS {
        create_dir_safe(&base.join(name))?;
    }
    Ok(())
}

fn create_dir_safe(path: &Path) -> Result<(), CliError> {
    if let Some(parent) = path.parent() {
        reject_symlink_path(parent)?;
    }
    fs::create_dir_all(path).map_err(|error| {
        CliError::message(format!("create directory {}: {error}", path.display()))
    })?;
    reject_symlink_path(path)
}

fn reject_symlink_path(path: &Path) -> Result<(), CliError> {
    let mut cursor = PathBuf::new();
    for component in path.components() {
        cursor.push(component.as_os_str());
        match fs::symlink_metadata(&cursor) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err(CliError::message(format!(
                    "refusing symlinked run path: {}",
                    cursor.display()
                )));
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => break,
            Err(error) => {
                return Err(CliError::message(format!(
                    "inspect {}: {error}",
                    cursor.display()
                )));
            }
        }
    }
    Ok(())
}

fn run_names(context: &ExecutionContext, registered_only: bool) -> Result<Vec<String>, CliError> {
    match fs::read_dir(&context.runs_root) {
        Ok(entries) => entries
            .map(|entry| entry.map_err(|error| CliError::message(error.to_string())))
            .filter_map(|entry| match entry {
                Ok(entry) if entry.file_type().map(|kind| kind.is_dir()).unwrap_or(false) => {
                    entry.file_name().into_string().ok().map(Ok)
                }
                Ok(_) => None,
                Err(error) => Some(Err(error)),
            })
            .filter(|name| {
                name.as_ref().is_ok_and(|name| {
                    !registered_only || context.runs_root.join(name).join("run.json").is_file()
                })
            })
            .collect(),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Vec::new()),
        Err(error) => Err(CliError::message(format!(
            "read runs directory {}: {error}",
            context.runs_root.display()
        ))),
    }
}

fn resolve_active(context: &ExecutionContext, run: Option<String>) -> Result<String, CliError> {
    if let Some(run) = run {
        return Ok(run);
    }
    let mut candidates = Vec::new();
    for run in run_names(context, true)? {
        let path = state_path(context, &run)?;
        let modified = fs::metadata(&path)
            .and_then(|metadata| metadata.modified())
            .ok();
        if load(context, &run).is_ok_and(|state| state.status == "executing") {
            candidates.push((modified, run));
        }
    }
    candidates.sort_by_key(|candidate| std::cmp::Reverse(candidate.0));
    candidates.into_iter().next().map(|(_, run)| run).ok_or_else(|| CliError::message_with_code("no <run> given and no active run found (a runs/*/run.json with status: \"executing\") -- pass <run> explicitly", 2))
}

fn local_ledger_exists(context: &ExecutionContext, run: &str) -> Result<bool, CliError> {
    let output = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .current_dir(std::env::current_dir().map_err(|error| CliError::message(error.to_string()))?)
        .output()
        .map_err(|error| CliError::message(format!("git worktree lookup: {error}")))?;
    if !output.status.success() {
        return Ok(false);
    }
    let current = PathBuf::from(String::from_utf8_lossy(&output.stdout).trim());
    if current == context.primary_root {
        return Ok(false);
    }
    let namespace = context
        .namespace
        .file_name()
        .ok_or_else(|| CliError::message("configured namespace has no basename"))?;
    Ok(current
        .join(namespace)
        .join("runs")
        .join(run)
        .join(LEDGER_FILE)
        .is_file())
}

fn normalize_document(raw: serde_json::Value) -> Result<(RunState, Vec<String>), CliError> {
    let mut object = raw
        .as_object()
        .cloned()
        .ok_or_else(|| usage_error("run.json root must be an object"))?;
    let mut applied = Vec::new();
    if let (true, Some(run)) = (!object.contains_key("run"), object.remove("run_id")) {
        object.insert("run".into(), run);
        applied.push("run_id -> run".into());
    }
    if let Some(lanes) = object
        .get("lanes")
        .cloned()
        .and_then(|lanes| lanes.as_object().cloned())
    {
        let mut entries = lanes
            .iter()
            .map(|(id, value)| {
                let mut value = value.as_object().cloned().unwrap_or_default();
                value.insert("id".into(), serde_json::Value::String(id.clone()));
                serde_json::Value::Object(value)
            })
            .collect::<Vec<_>>();
        entries.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
        object.insert("lanes".into(), serde_json::Value::Array(entries));
        applied.push("lanes dict -> list".into());
    }
    match object.get("updated_at").cloned() {
        Some(value) if !value.is_i64() && !value.is_u64() => {
            object.insert(
                "updated_at".into(),
                serde_json::Value::from(coerce_epoch(&value)),
            );
            applied.push("updated_at -> epoch".into());
        }
        _ => {}
    }
    serde_json::from_value(serde_json::Value::Object(object))
        .map(|state| (state, applied))
        .map_err(|error| usage_error(format!("run.json schema validation failed: {error}")))
}

fn coerce_epoch(value: &serde_json::Value) -> i64 {
    value
        .as_i64()
        .or_else(|| value.as_u64().and_then(|value| i64::try_from(value).ok()))
        .or_else(|| {
            value
                .as_f64()
                .and_then(|value| value.trunc().to_string().parse::<i64>().ok())
        })
        .or_else(|| value.as_str().and_then(|value| value.parse::<i64>().ok()))
        .unwrap_or(0)
}

fn declared_lanes(plan: &str) -> Vec<String> {
    let mut lines = plan.lines();
    for line in lines.by_ref() {
        if line
            .trim_start_matches('#')
            .trim()
            .eq_ignore_ascii_case("lane projection")
        {
            break;
        }
    }
    let mut result = Vec::new();
    let mut header = false;
    let mut separator = false;
    for line in lines {
        let trimmed = line.trim();
        if trimmed.starts_with('#') {
            break;
        }
        if !trimmed.starts_with('|') {
            if header {
                break;
            }
            continue;
        }
        let cells = trimmed
            .trim_matches('|')
            .split('|')
            .map(str::trim)
            .collect::<Vec<_>>();
        if !header {
            header = true;
            if cells.first().is_none_or(|cell| {
                !cell
                    .trim_matches(['`', '*', ' '])
                    .eq_ignore_ascii_case("lane_id")
            }) {
                break;
            }
            continue;
        }
        if !separator {
            separator = true;
            if cells
                .iter()
                .all(|cell| cell.trim_matches([':', '-']).is_empty())
            {
                continue;
            }
        }
        if let Some(id) = cells
            .first()
            .map(|cell| cell.trim_matches(['`', '*', ' ']).to_ascii_lowercase())
            .filter(|id| !id.is_empty())
        {
            result.push(id);
        }
    }
    result
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Step {
    wave: u32,
    lane: u32,
    step: u32,
}
impl Step {
    fn id(&self) -> String {
        format!("W{}-L{}-S{}", self.wave, self.lane, self.step)
    }
}
#[derive(Clone, Debug)]
struct LedgerRow {
    lane: u32,
    wave: u32,
    step: Option<u32>,
    verdict: String,
    raw: String,
}

fn parse_plan_steps(text: &str) -> Vec<Step> {
    text.split_whitespace()
        .filter_map(|token| {
            let token = token.trim_matches(|character: char| {
                !character.is_ascii_alphanumeric() && character != '-'
            });
            let parts = token.split('-').collect::<Vec<_>>();
            if parts.len() != 3 {
                return None;
            }
            Some(Step {
                wave: parts[0].strip_prefix(['W', 'w'])?.parse().ok()?,
                lane: parts[1].strip_prefix(['L', 'l'])?.parse().ok()?,
                step: parts[2].strip_prefix(['S', 's'])?.parse().ok()?,
            })
        })
        .collect()
}

fn parse_ledger(text: &str) -> Vec<LedgerRow> {
    text.lines().filter_map(parse_ledger_line).collect()
}
fn parse_ledger_line(line: &str) -> Option<LedgerRow> {
    let fields = line.split_whitespace().collect::<Vec<_>>();
    if fields.len() < 3 || line.trim_start().starts_with('#') {
        return None;
    }
    let lane = fields[0].strip_prefix(['L', 'l'])?.parse().ok()?;
    let scope = fields[1].strip_prefix(['W', 'w'])?;
    let (wave, step) = match scope.split_once(['-', '–']) {
        Some((wave, step)) => (
            wave.parse().ok()?,
            step.strip_prefix(['s', 'S'])?
                .trim_end_matches(|character: char| !character.is_ascii_digit())
                .parse()
                .ok(),
        ),
        None => (scope.parse().ok()?, None),
    };
    let verdict = fields[2].to_ascii_uppercase();
    if !matches!(verdict.as_str(), "PASS" | "REDO" | "FAIL") {
        return None;
    }
    Some(LedgerRow {
        lane,
        wave,
        step,
        verdict,
        raw: line.into(),
    })
}

fn normalized_rows(text: &str) -> Vec<String> {
    text.lines()
        .map(str::trim_end)
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .map(str::to_owned)
        .collect()
}
fn now_seconds(context: &ExecutionContext) -> i64 {
    context.now_unix_millis() / 1_000
}
fn empty_dash(value: &str) -> &str {
    if value.is_empty() { "-" } else { value }
}
fn validate_id(kind: &str, value: &str) -> Result<(), CliError> {
    let bytes = value.as_bytes();
    if (1..=64).contains(&bytes.len())
        && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit())
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'-')
    {
        Ok(())
    } else {
        usage(format!("unsafe {kind} id `{value}`"))
    }
}
fn is_canonical(value: &str) -> bool {
    canonical_suggestion(value).is_some_and(|candidate| candidate == value)
}
fn canonical_suggestion(value: &str) -> Option<String> {
    let rest = value.strip_prefix('v')?;
    if let Some((version, dev_tail)) = rest.split_once("-dev") {
        let dev = dev_tail
            .bytes()
            .take_while(u8::is_ascii_digit)
            .map(char::from)
            .collect::<String>();
        if !version.is_empty()
            && !dev.is_empty()
            && version.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Some(format!("v{version}-dev{dev}"));
        }
        return None;
    }
    if !rest.is_empty() && rest.bytes().all(|byte| byte.is_ascii_digit()) {
        return Some(format!("v{rest}"));
    }
    None
}
fn derive_id(value: &str, kind: &str) -> Result<String, CliError> {
    let version = value
        .strip_prefix('v')
        .ok_or_else(|| usage_error(format!("cannot derive a run id from {value:?}")))?;
    let (numbers, dev) = version.split_once("-dev.").unwrap_or((version, ""));
    let parts = numbers.split('.').collect::<Vec<_>>();
    if parts.len() != 3
        || parts
            .iter()
            .any(|part| part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()))
        || (kind == "sprint" && (dev.is_empty() || !dev.bytes().all(|byte| byte.is_ascii_digit())))
    {
        return Err(usage_error(format!(
            "cannot derive a run id from {value:?} (expected v{{X}}.{{Y}}.{{Z}} or v{{X}}.{{Y}}.{{Z}}-dev.{{N}})"
        )));
    }
    Ok(if kind == "sprint" {
        format!("v{}{}{}-dev{dev}", parts[0], parts[1], parts[2])
    } else {
        format!("v{}{}{}", parts[0], parts[1], parts[2])
    })
}
fn output(context: &mut ExecutionContext, value: &str) -> Result<(), CliError> {
    context
        .write_stdout(format!("{value}\n").as_bytes())
        .map_err(|error| CliError::message(format!("write stdout: {error}")))
}
fn error_output(context: &mut ExecutionContext, value: &str) -> Result<(), CliError> {
    context
        .write_stderr(format!("{value}\n").as_bytes())
        .map_err(|error| CliError::message(format!("write stderr: {error}")))
}
fn usage(message: impl Into<String>) -> Result<(), CliError> {
    Err(usage_error(message))
}
fn usage_error(message: impl Into<String>) -> CliError {
    CliError::message_with_code(message, 2)
}
fn missing_or_conflict(message: impl Into<String>) -> Result<(), CliError> {
    Err(CliError::message_with_code(message, 5))
}
fn no_such_run(context: &ExecutionContext, run: &str) -> Result<(), CliError> {
    Err(no_such_run_error(context, run))
}
fn no_such_run_error(context: &ExecutionContext, run: &str) -> CliError {
    CliError::message_with_code(
        format!(
            "no such run: {run} (expected {})",
            context.runs_root.join(run).join("run.json").display()
        ),
        5,
    )
}
fn store_error(error: RunStoreError) -> CliError {
    match error {
        RunStoreError::AlreadyExists(path) => CliError::message_with_code(
            format!(
                "run already exists: {}",
                path.parent()
                    .and_then(Path::file_name)
                    .and_then(|name| name.to_str())
                    .unwrap_or("<unknown>")
            ),
            5,
        ),
        RunStoreError::SchemaAhead(version) => CliError::message_with_code(
            format!("run schema version {version} is newer than this binary supports"),
            2,
        ),
        RunStoreError::Validation(message) | RunStoreError::Mutation(message) => {
            CliError::message_with_code(message, 2)
        }
        other => CliError::message(other.to_string()),
    }
}
fn run_usage() -> &'static str {
    "shepherd run <init|rename|canonicalize|show|list|claim|set|migrate|lane|layout|ledger|wave>"
}
