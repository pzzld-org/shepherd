/*
    Appellation: settings <module>
    Created At: 2026.08.12:14:58:31
    Contrib: @FL03
*/
//! Canonical, harness-neutral `shepherd.toml` schema.
//!
//! Every table is closed unless its value is explicitly a string-keyed map.
//! Individual files may be empty or partial; defaults are materialized only
//! after the loader merges caller-supplied layers.

use std::{
    collections::BTreeMap,
    path::{Component, Path, PathBuf},
};

use crate::{Error, Result};

macro_rules! config_struct {
    ($(#[$meta:meta])* $visibility:vis struct $name:ident { $($fields:tt)* }) => {
        $(#[$meta])*
        #[derive(Clone, Debug, Default, PartialEq)]
        #[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
        #[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
        #[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
        $visibility struct $name { $($fields)* }
    };
}

macro_rules! string_enum {
    ($name:ident, $default:ident, { $($variant:ident),+ $(,)? }) => {
        #[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
        #[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
        #[cfg_attr(feature = "serde", serde(rename_all = "kebab-case"))]
        #[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
        pub enum $name { $($variant),+ }

        impl Default for $name {
            fn default() -> Self { Self::$default }
        }
    };
}

string_enum!(HarnessLanguage, Rust, {
    Rust,
    Python,
    Typescript,
    Go,
    Mixed,
    Markdown,
});
string_enum!(Enforcement, Block, { Block, Warn, Off });
string_enum!(Toggle, On, { On, Off });
string_enum!(ReleaseDriver, GithubWorkflow, {
    Conductor,
    GithubWorkflow,
    Operator,
});
string_enum!(GradeFloorAction, Abort, { Abort, Pause, Continue });
string_enum!(InterSprintPause, Brief, { Brief, Signoff, None });
string_enum!(DupsHook, Warn, { Off, Warn, Block });

/// Automatic registry refresh triggers.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(rename_all = "kebab-case"))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub enum AutoRefresh {
    OnSprintOpen,
    OnEngineerDispatch,
    OnCloseFinalize,
    OnWaveGate,
}

config_struct! {
    /// Project identity and descriptive metadata.
    pub struct ProjectConfig {
        pub name: Option<String>,
        pub language: HarnessLanguage,
        pub description: String,
        pub harnesses: Vec<String>,
    }
}

/// Branch and artifact slug topology.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct BranchingConfig {
    pub patch_branch_pattern: String,
    pub sprint_branch_pattern: String,
    pub patch_slug_pattern: String,
    pub sprint_slug_pattern: String,
    pub sprints_per_patch: u32,
    pub main_branch: String,
    pub release_tag_pattern: String,
    pub allow_direct_main_commit: bool,
}

impl Default for BranchingConfig {
    fn default() -> Self {
        Self {
            patch_branch_pattern: "v{X}.{Y}.{Z}".into(),
            sprint_branch_pattern: "v{X}.{Y}.{Z}-dev.{N}".into(),
            patch_slug_pattern: "v{X}{Y}{Z}".into(),
            sprint_slug_pattern: "v{X}{Y}{Z}-dev{N}".into(),
            sprints_per_patch: 10,
            main_branch: "main".into(),
            release_tag_pattern: "v{X}.{Y}.{Z}".into(),
            allow_direct_main_commit: false,
        }
    }
}

/// One supplementary gate.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct GateExtraEntry {
    pub name: String,
    pub cmd: String,
}

/// The two supported `[gates.extra]` shapes.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(untagged))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub enum GatesExtra {
    List(Vec<GateExtraEntry>),
    Map(BTreeMap<String, String>),
}

impl Default for GatesExtra {
    fn default() -> Self {
        Self::List(Vec::new())
    }
}

/// Between-wave deterministic gates.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct GatesConfig {
    pub check: String,
    pub lint: String,
    pub format: String,
    pub extra: GatesExtra,
    pub target_clean_threshold_gb: u32,
    pub subtract_paths: Vec<String>,
}

impl Default for GatesConfig {
    fn default() -> Self {
        Self {
            check: String::new(),
            lint: String::new(),
            format: String::new(),
            extra: GatesExtra::default(),
            target_clean_threshold_gb: 20,
            subtract_paths: Vec::new(),
        }
    }
}

/// Field-shape duplicate detector thresholds.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct DupsConfig {
    pub dups_threshold: f64,
    pub dups_block: f64,
    pub dups_name_weight: f64,
    pub dups_min_fields: u32,
    pub dups_hook: DupsHook,
    pub dups_registry: PathBuf,
}

impl Default for DupsConfig {
    fn default() -> Self {
        Self {
            dups_threshold: 0.7,
            dups_block: 0.85,
            dups_name_weight: 0.5,
            dups_min_fields: 2,
            dups_hook: DupsHook::Warn,
            dups_registry: "dups-registry.json".into(),
        }
    }
}

/// The only configurable layout-v5 project roots.
#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct PathsConfig {
    pub docs: PathBuf,
    pub ctx: PathBuf,
    pub runs: PathBuf,
}

impl Default for PathsConfig {
    fn default() -> Self {
        Self {
            docs: ".shepherd/docs".into(),
            ctx: ".shepherd/ctx".into(),
            runs: ".shepherd/runs".into(),
        }
    }
}

/// Fully resolved project paths. Resolution is lexical and performs no I/O.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedPaths {
    pub primary_root: PathBuf,
    pub namespace: PathBuf,
    pub docs: PathBuf,
    pub ctx: PathBuf,
    pub runs: PathBuf,
    pub dups_registry: PathBuf,
    pub registry: PathBuf,
    pub registry_lock: PathBuf,
    pub project_id: PathBuf,
}

/// Skill selection and open domain maps.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct SkillsConfig {
    pub mandatory: Vec<String>,
    pub by_domain: BTreeMap<String, Vec<String>>,
    pub detection: BTreeMap<String, Vec<String>>,
}

impl Default for SkillsConfig {
    fn default() -> Self {
        Self {
            mandatory: vec!["code-style".into()],
            by_domain: BTreeMap::new(),
            detection: BTreeMap::new(),
        }
    }
}

/// Issue-ledger awareness.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct LedgerConfig {
    pub phase_0_full_ledger: bool,
    pub classify_into: Vec<String>,
    pub non_issue_labels: Vec<String>,
    pub carry_forward_file: String,
    pub chronic_threshold_patches: u32,
}

impl Default for LedgerConfig {
    fn default() -> Self {
        Self {
            phase_0_full_ledger: true,
            classify_into: vec![
                "blocking-this-sprint".into(),
                "labeled-non-issue".into(),
                "tracking-future".into(),
                "drift-risk".into(),
            ],
            non_issue_labels: vec![
                "wontfix".into(),
                "tracking-future".into(),
                "design-question".into(),
                "rfc".into(),
            ],
            carry_forward_file: "{paths.docs}/v{X}.{Y}.{Z}-carry-forwards.md".into(),
            chronic_threshold_patches: 2,
        }
    }
}

/// Release pipeline selection.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct ReleaseConfig {
    pub driver: ReleaseDriver,
    pub release_notes_path: String,
    pub workflow_file: String,
    pub devlast_guard: Enforcement,
}

impl Default for ReleaseConfig {
    fn default() -> Self {
        Self {
            driver: ReleaseDriver::GithubWorkflow,
            release_notes_path: "{paths.docs}/v{X}.{Y}.{Z}-release-notes.md".into(),
            workflow_file: ".github/workflows/release.yml".into(),
            devlast_guard: Enforcement::Block,
        }
    }
}

config_struct! { pub struct TmuxConfig { pub pane_cleanup: Toggle, } }
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct ContextRefreshConfig {
    pub ttl_minutes: u32,
}

impl Default for ContextRefreshConfig {
    fn default() -> Self {
        Self { ttl_minutes: 30 }
    }
}

#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct ContextLockConfig {
    pub stale_after_minutes: u32,
}

impl Default for ContextLockConfig {
    fn default() -> Self {
        Self {
            stale_after_minutes: 120,
        }
    }
}
config_struct! {
    pub struct ContextNamingConfig {
        pub strict: bool,
        pub extra_patterns: Vec<String>,
        pub ignore_paths: Vec<String>,
    }
}

/// Context behavior. Layout paths are fixed by layout-v5 and are not knobs.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct ContextConfig {
    pub auto_refresh: Vec<AutoRefresh>,
    pub announce_cli_path: Toggle,
    pub announce_core_doctrine: Toggle,
    pub announce_adaptation: Toggle,
    pub refresh: ContextRefreshConfig,
    pub lock: ContextLockConfig,
    pub naming: ContextNamingConfig,
}

impl Default for ContextConfig {
    fn default() -> Self {
        Self {
            auto_refresh: vec![AutoRefresh::OnSprintOpen],
            announce_cli_path: Toggle::On,
            announce_core_doctrine: Toggle::On,
            announce_adaptation: Toggle::On,
            refresh: ContextRefreshConfig { ttl_minutes: 30 },
            lock: ContextLockConfig {
                stale_after_minutes: 120,
            },
            naming: ContextNamingConfig::default(),
        }
    }
}

/// Dispatch-hook integration.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct HooksConfig {
    pub on_every_dispatch: Vec<String>,
    pub on_conductor_only: Vec<String>,
    pub on_engineer_only: Vec<String>,
    pub on_planter_only: Vec<String>,
    pub quiet_warnings: bool,
    pub flag_handrolled_fanout: bool,
    pub workflow_model_guard: Enforcement,
    pub teammate_heartbeat: Toggle,
}

impl Default for HooksConfig {
    fn default() -> Self {
        Self {
            on_every_dispatch: vec!["code-style".into()],
            on_conductor_only: Vec::new(),
            on_engineer_only: vec!["workflow".into()],
            on_planter_only: Vec::new(),
            quiet_warnings: false,
            flag_handrolled_fanout: true,
            workflow_model_guard: Enforcement::Block,
            teammate_heartbeat: Toggle::On,
        }
    }
}

/// Teammate-spawn coordination.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct SpawnConfig {
    pub coordinate_drive_guard: Enforcement,
    pub wave_ack_timeout_sec: u32,
    pub cross_dep_timeout_sec: u32,
    pub max_parallel: u32,
    pub dashboard_cadence: String,
    pub staged_timeout_minutes: u32,
    pub lead_effort: String,
    pub stale_sweep_minutes: u32,
}

impl Default for SpawnConfig {
    fn default() -> Self {
        Self {
            coordinate_drive_guard: Enforcement::Block,
            wave_ack_timeout_sec: 60,
            cross_dep_timeout_sec: 300,
            max_parallel: 4,
            dashboard_cadence: "3m".into(),
            staged_timeout_minutes: 90,
            lead_effort: "ultracode".into(),
            stale_sweep_minutes: 60,
        }
    }
}

/// Unattended walk behavior.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct AutorunConfig {
    pub min_grade: String,
    pub on_grade_floor: GradeFloorAction,
    pub inter_sprint_pause: InterSprintPause,
}

impl Default for AutorunConfig {
    fn default() -> Self {
        Self {
            min_grade: "B".into(),
            on_grade_floor: GradeFloorAction::Abort,
            inter_sprint_pause: InterSprintPause::Brief,
        }
    }
}

/// Compaction snapshot behavior.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct CompactionConfig {
    pub precompact_snapshot: Toggle,
    pub snapshot_retention: u32,
}

impl Default for CompactionConfig {
    fn default() -> Self {
        Self {
            precompact_snapshot: Toggle::On,
            snapshot_retention: 5,
        }
    }
}

/// Focus-loop rehydration behavior.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct FocusConfig {
    pub rehydrate: Toggle,
    pub heartbeat_actions: u32,
    pub heartbeat_interval: String,
    pub loop_max_default: u32,
}

impl Default for FocusConfig {
    fn default() -> Self {
        Self {
            rehydrate: Toggle::On,
            heartbeat_actions: 20,
            heartbeat_interval: String::new(),
            loop_max_default: 8,
        }
    }
}

/// Close-phase behavior.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct CloseConfig {
    pub autonomous_sentinel: Toggle,
}

impl Default for CloseConfig {
    fn default() -> Self {
        Self {
            autonomous_sentinel: Toggle::Off,
        }
    }
}

/// Latent-output evaluation behavior.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct EvalConfig {
    pub eval_judge_model: String,
    pub eval_on_close: Toggle,
}

impl Default for EvalConfig {
    fn default() -> Self {
        Self {
            eval_judge_model: String::new(),
            eval_on_close: Toggle::Off,
        }
    }
}

/// Model selection for all nine roles.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct ModelsConfig {
    pub root: String,
    pub planter: String,
    pub engineer: String,
    pub conductor: String,
    pub critic: String,
    pub discovery: String,
    pub coder: String,
    pub auditor: String,
    pub worker: String,
}

impl Default for ModelsConfig {
    fn default() -> Self {
        Self {
            // root and planter hold the reasoning tier: the sprint's expensive
            // thinking is its seeding and its top-level orchestration, and that
            // is where a fable-class model earns its cost.
            root: "reasoning-high".into(),
            planter: "reasoning-high".into(),
            // The team leads INHERIT the caller instead of pinning a tier. A
            // sprint spawned at the reasoning tier gets leads at that tier; a
            // sprint spawned cheaply gets cheap leads. Pinning them meant every
            // lane lead cost the top tier regardless of what the run was worth.
            // Override either in `[models]` in `.shepherd/shepherd.toml`.
            engineer: "inherit-caller".into(),
            conductor: "inherit-caller".into(),
            critic: "standard".into(),
            discovery: "standard".into(),
            coder: "standard".into(),
            auditor: "standard".into(),
            worker: "standard".into(),
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct PruneConfig {
    pub logs_days: u32,
    pub dispatch_days: u32,
    pub snapshots_keep: u32,
    pub findings_sprints: u32,
}

impl Default for PruneConfig {
    fn default() -> Self {
        Self {
            logs_days: 60,
            dispatch_days: 30,
            snapshots_keep: 20,
            findings_sprints: 6,
        }
    }
}
config_struct! { pub struct SeedConfig { pub seed_gate: Enforcement, } }

/// Entry-command preflight.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct PreflightConfig {
    pub auto_invoke: String,
}

impl Default for PreflightConfig {
    fn default() -> Self {
        Self {
            auto_invoke: "doctor".into(),
        }
    }
}

/// Intro-wave defaults.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct StageGraphIntroWaveConfig {
    pub enabled: bool,
    pub default_discoveries: Vec<String>,
    pub default_intro_auditors: Vec<String>,
    pub disable_for_tshirt: Vec<String>,
    pub parallel_max: u32,
}

impl Default for StageGraphIntroWaveConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            default_discoveries: Vec::new(),
            default_intro_auditors: Vec::new(),
            disable_for_tshirt: Vec::new(),
            parallel_max: 5,
        }
    }
}

/// Stage-graph defaults.
#[derive(Clone, Debug, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct StageGraphConfig {
    pub default_wave_count: u32,
    pub hotfix_max_iterations: u32,
    pub walk_trace_enabled: bool,
    pub intro_wave: StageGraphIntroWaveConfig,
}

impl Default for StageGraphConfig {
    fn default() -> Self {
        Self {
            default_wave_count: 2,
            hotfix_max_iterations: 3,
            walk_trace_enabled: true,
            intro_wave: StageGraphIntroWaveConfig::default(),
        }
    }
}

/// The complete ordinary-runtime `shepherd.toml` document.
#[derive(Clone, Debug, Default, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(default, deny_unknown_fields))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct ShepherdConfig {
    pub project: ProjectConfig,
    pub branching: BranchingConfig,
    pub paths: PathsConfig,
    pub gates: GatesConfig,
    pub dups: DupsConfig,
    pub skills: SkillsConfig,
    pub mcp: BTreeMap<String, bool>,
    pub cli: BTreeMap<String, bool>,
    pub ledger: LedgerConfig,
    pub release: ReleaseConfig,
    pub tmux: TmuxConfig,
    pub context: ContextConfig,
    pub hooks: HooksConfig,
    pub spawn: SpawnConfig,
    pub autorun: AutorunConfig,
    pub compaction: CompactionConfig,
    pub focus: FocusConfig,
    pub close: CloseConfig,
    pub eval: EvalConfig,
    pub models: ModelsConfig,
    pub prune: PruneConfig,
    pub seed: SeedConfig,
    pub preflight: PreflightConfig,
    pub stage_graph: StageGraphConfig,
}

impl ShepherdConfig {
    /// Validate cross-field ranges and layout-v5 path containment.
    pub fn validate(&self) -> Result {
        for (key, value) in [
            ("dups.dups_threshold", self.dups.dups_threshold),
            ("dups.dups_block", self.dups.dups_block),
            ("dups.dups_name_weight", self.dups.dups_name_weight),
        ] {
            if !value.is_finite() || !(0.0..=1.0).contains(&value) {
                return Err(Error::config(format_args!(
                    "{key}: expected a finite value in 0..=1"
                )));
            }
        }

        let docs = normalize_namespace_path("paths.docs", &self.paths.docs)?;
        let ctx = normalize_namespace_path("paths.ctx", &self.paths.ctx)?;
        let runs = normalize_namespace_path("paths.runs", &self.paths.runs)?;
        validate_knowledge_filename("dups.dups_registry", &self.dups.dups_registry)?;
        for (key, value, other_key, other_value) in [
            ("paths.ctx", &ctx, "paths.docs", &docs),
            ("paths.runs", &runs, "paths.docs", &docs),
            ("paths.runs", &runs, "paths.ctx", &ctx),
        ] {
            if value.starts_with(other_value) || other_value.starts_with(value) {
                return Err(Error::config(format_args!(
                    "{key}: must not overlap {other_key}"
                )));
            }
        }
        Ok(())
    }

    /// Resolve the configured roots against an already-resolved primary root.
    pub fn resolve_paths(&self, primary_root: &Path) -> Result<ResolvedPaths> {
        self.validate()?;
        let namespace = primary_root.join(".shepherd");
        let docs = normalize_namespace_path("paths.docs", &self.paths.docs)?;
        let ctx = normalize_namespace_path("paths.ctx", &self.paths.ctx)?;
        let runs = normalize_namespace_path("paths.runs", &self.paths.runs)?;
        Ok(ResolvedPaths {
            primary_root: primary_root.to_path_buf(),
            namespace: namespace.clone(),
            docs: primary_root.join(&docs),
            ctx: primary_root.join(&ctx),
            runs: primary_root.join(&runs),
            dups_registry: primary_root.join(&ctx).join(&self.dups.dups_registry),
            registry: namespace.join("shepherd.db"),
            registry_lock: namespace.join("shepherd.lock"),
            project_id: namespace.join("project.json"),
        })
    }
}

fn normalize_namespace_path(key: &str, path: &Path) -> Result<PathBuf> {
    let mut components = path.components();
    if !matches!(components.next(), Some(Component::Normal(first)) if first == ".shepherd") {
        return Err(Error::config(format_args!(
            "{key}: path must be relative and rooted in .shepherd"
        )));
    }

    let mut has_child = false;
    let mut normalized = PathBuf::from(".shepherd");
    for component in components {
        match component {
            Component::Normal(value) => {
                has_child = true;
                normalized.push(value);
            }
            Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                return Err(Error::config(format_args!(
                    "{key}: path must not escape .shepherd"
                )));
            }
        }
    }
    if !has_child {
        return Err(Error::config(format_args!(
            "{key}: path must name a child of .shepherd"
        )));
    }
    Ok(normalized)
}

fn validate_knowledge_filename(key: &str, path: &Path) -> Result {
    let value = path.to_str().ok_or_else(|| {
        Error::config(format_args!(
            "{key}: filename must be valid UTF-8 without separators"
        ))
    })?;
    let mut components = path.components();
    let is_one_normal_component =
        matches!(components.next(), Some(Component::Normal(_))) && components.next().is_none();
    if value.is_empty()
        || value.contains('/')
        || value.contains('\\')
        || value.chars().any(char::is_control)
        || !is_one_normal_component
    {
        return Err(Error::config(format_args!(
            "{key}: filename must be relative, contain no separators, and contain no control characters"
        )));
    }
    Ok(())
}
