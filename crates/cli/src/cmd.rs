/*
    Appellation: cmd <module>
    Created At: 2026.08.12:15:10:28
    Contrib: @FL03
*/
#[doc(inline)]
pub use self::prelude::*;

pub mod claude_hook;
pub mod compile;
pub mod dispatch;
pub mod guard;
pub mod wave_a_models;
pub mod wave_b1_mem;
pub mod wave_b1_status_handoff;
pub mod wave_b2_run;
pub mod wave_b2_seed;
pub mod wave_c_bootstrap;
pub mod wave_d_planning;
pub mod wave_e_coordination;
pub mod wave_f_knowledge;
pub mod wave_g_coordination;
pub mod wave_h_execution;

pub(crate) mod prelude {
    pub use super::ShepherdCommand;
    pub use super::claude_hook::ClaudeHookCmd;
    pub use super::compile::CompileCmd;
    pub use super::dispatch::DispatchCmd;
    pub use super::guard::GuardCmd;
    pub use super::wave_a_models::WaveAModelsCmd;
    pub use super::wave_b1_mem::WaveB1MemCmd;
    pub use super::wave_b1_status_handoff::{WaveB1HandoffCmd, WaveB1StatusCmd};
    pub use super::wave_b2_run::WaveB2RunCmd;
    pub use super::wave_b2_seed::WaveB2SeedCmd;
    pub use super::wave_c_bootstrap::{WaveCConfigCmd, WaveCDoctorCmd, WaveCHomeCmd, WaveCInitCmd};
    pub use super::wave_d_planning::{
        WaveDAuditCmd, WaveDCloseLaneCmd, WaveDDiscoveryCmd, WaveDGraphCmd, WaveDPlanCmd,
        WaveDRenderCmd, WaveDReportCmd,
    };
    pub use super::wave_e_coordination::WaveECoordinationCmd;
    pub use super::wave_f_knowledge::{
        WaveFDupsCmd, WaveFEvalCmd, WaveFExportCmd, WaveFInsightsCmd, WaveFQueryCmd, WaveFSearchCmd,
    };
    pub use super::wave_g_coordination::{
        WaveGSignalCmd, WaveGSyncCmd, WaveGTeammateCmd, WaveGWorktreeCmd,
    };
    pub use super::wave_h_execution::{
        WaveHDeliverableCmd, WaveHIssuesCmd, WaveHLintCmd, WaveHReadyCmd, WaveHSprintCmd,
    };
    pub use crate::migrate::MigrateCmd;
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
pub enum ShepherdCommand {
    /// Inspect the canonical audit artifacts for one run.
    Audit(WaveDAuditCmd),
    /// Compile canonical roles and skills for one harness.
    Compile(CompileCmd),
    /// Translate Claude Code hook envelopes through the canonical native engine.
    ClaudeHook(ClaudeHookCmd),
    /// Close one canonical run lane through the typed run ledger.
    CloseLane(WaveDCloseLaneCmd),
    /// Inspect or initialize the canonical typed project configuration.
    Config(WaveCConfigCmd),
    Dispatch(DispatchCmd),
    /// Inspect the canonical discovery artifacts for one run.
    Discovery(WaveDDiscoveryCmd),
    /// Diagnose the canonical project, registry, and layout-v5 namespace.
    Doctor(WaveCDoctorCmd),
    /// Record canonical deliverable lifecycle facts.
    Deliverable(WaveHDeliverableCmd),
    /// Inspect canonical duplicate declarations and registry shapes.
    Dups(WaveFDupsCmd),
    /// Inspect recorded evaluation results without invoking a second engine.
    Eval(WaveFEvalCmd),
    /// Export canonical typed registry views through stdout.
    Export(WaveFExportCmd),
    Guard(GuardCmd),
    /// Inspect canonical run topology without recreating retired graph state.
    Graph(WaveDGraphCmd),
    /// Inspect canonical handoff artifacts in the active project.
    Handoff(WaveB1HandoffCmd),
    /// Initialize the canonical layout-v5 project namespace.
    Init(WaveCInitCmd),
    /// Inspect immutable insights from the flat canonical docs root.
    Insights(WaveFInsightsCmd),
    /// Inspect the canonical issue ledger.
    Issues(WaveHIssuesCmd),
    /// Run deterministic native lint checks.
    Lint(WaveHLintCmd),
    /// Manage the canonical project coordination lock.
    Lock(WaveECoordinationCmd),
    /// Inspect or initialize the separately-owned Shepherd user home.
    Home(WaveCHomeCmd),
    /// Plan or apply the canonical layout-v5 namespace migration.
    Migrate(MigrateCmd),
    /// Manage canonical project memory in the typed registry.
    Mem(WaveB1MemCmd),
    /// Inspect or resolve the canonical model map.
    Models(WaveAModelsCmd),
    /// Inspect and verify one canonical run plan.
    Plan(WaveDPlanCmd),
    /// Run an allowlisted typed registry query.
    Query(WaveFQueryCmd),
    /// Render one canonical template without a legacy interpreter.
    Render(WaveDRenderCmd),
    /// Evaluate canonical sprint readiness.
    Ready(WaveHReadyCmd),
    /// Inspect canonical run reports.
    Report(WaveDReportCmd),
    /// Report canonical project and run status without mutating state.
    Status(WaveB1StatusCmd),
    /// Search canonical symbols and artifacts through the typed registry.
    Search(WaveFSearchCmd),
    /// Verify a seed deterministically before plan engineering begins.
    Seed(WaveB2SeedCmd),
    /// Exchange durable cross-session signals through the typed registry.
    Signal(WaveGSignalCmd),
    /// Manage the canonical sprint lifecycle.
    Sprint(WaveHSprintCmd),
    /// Run the native context refresh pipeline.
    Sync(WaveGSyncCmd),
    /// Inspect teammate liveness, status, and declared state.
    Teammate(WaveGTeammateCmd),
    /// Own the canonical run lifecycle and lane/wave ledger.
    Run(WaveB2RunCmd),
    /// Manage the native git worktree lifecycle.
    Worktree(WaveGWorktreeCmd),
    /// Reject removed legacy commands at the one canonical CLI boundary.
    #[command(external_subcommand)]
    Unsupported(Vec<String>),
}

impl ShepherdCommand {
    pub(crate) fn run(
        self,
        globals: crate::interface::CliGlobals,
    ) -> Result<(), crate::interface::CliError> {
        match self {
            Self::Audit(command) => command.run(globals),
            Self::Compile(command) => command.run(),
            Self::ClaudeHook(command) => command.run(globals),
            Self::CloseLane(command) => command.run(globals),
            Self::Config(command) => command.run(globals),
            Self::Dispatch(command) => command.run(globals),
            Self::Discovery(command) => command.run(globals),
            Self::Deliverable(command) => command.run(globals),
            Self::Doctor(command) => command.run(globals),
            Self::Dups(command) => command.run(globals),
            Self::Eval(command) => command.run(globals),
            Self::Export(command) => command.run(globals),
            Self::Guard(command) => command.run(),
            Self::Graph(command) => command.run(globals),
            Self::Handoff(command) => command.run(globals),
            Self::Init(command) => command.run(globals),
            Self::Insights(command) => command.run(globals),
            Self::Issues(command) => command.run(globals),
            Self::Lint(command) => command.run(globals),
            Self::Home(command) => command.run(globals),
            Self::Lock(command) => command.run(globals),
            Self::Migrate(command) => command.run(globals),
            Self::Mem(command) => command.run(globals),
            Self::Models(command) => command.run(globals),
            Self::Plan(command) => command.run(globals),
            Self::Query(command) => command.run(globals),
            Self::Render(command) => command.run(globals),
            Self::Ready(command) => command.run(globals),
            Self::Report(command) => command.run(globals),
            Self::Status(command) => command.run(globals),
            Self::Search(command) => command.run(globals),
            Self::Seed(command) => command.run(),
            Self::Signal(command) => command.run(globals),
            Self::Sprint(command) => command.run(globals),
            Self::Sync(command) => command.run(globals),
            Self::Teammate(command) => command.run(globals),
            Self::Run(command) => command.run(globals),
            Self::Worktree(command) => command.run(globals),
            Self::Unsupported(arguments) => {
                let command = arguments.first().map(String::as_str).unwrap_or("<empty>");
                Err(crate::interface::CliError::message(format!(
                    "command `{command}` is unavailable in the canonical Rust CLI; legacy Python, Bash, and Node command authorities are retired"
                )))
            }
        }
    }
}
