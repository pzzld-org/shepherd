//! Codex host hook transport over the shared native guard engine.
//!
//! The regular marketplace carrier registers SessionStart and PreToolUse only;
//! Codex subagent lifecycle events remain unavailable until the host exposes a
//! trusted spawn-to-child correlation contract.

use crate::{
    cmd::native_hook::{HookHost, run_native_hook},
    interface::{CliError, CliGlobals},
};

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
pub struct CodexHookCmd;

impl CodexHookCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        run_native_hook(HookHost::Codex, globals)
    }
}
