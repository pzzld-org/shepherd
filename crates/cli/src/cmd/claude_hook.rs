//! Claude Code command boundary for the shared native hook transport.

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
pub struct ClaudeHookCmd;

impl ClaudeHookCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        run_native_hook(HookHost::Claude, globals)
    }
}
