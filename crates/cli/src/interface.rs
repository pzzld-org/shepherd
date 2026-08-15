/*
    Appellation: interface <module>
    Created At: 2026.08.12:15:09:50
    Contrib: @FL03
*/
use crate::cmd::ShepherdCommand;

#[derive(Debug)]
pub struct CliError {
    message: Option<String>,
    exit_code: u8,
}

impl CliError {
    pub(crate) fn message(message: impl Into<String>) -> Self {
        Self {
            message: Some(message.into()),
            exit_code: 1,
        }
    }

    pub(crate) fn message_with_code(message: impl Into<String>, exit_code: u8) -> Self {
        debug_assert_ne!(exit_code, 0, "an error exit code must be nonzero");
        Self {
            message: Some(message.into()),
            exit_code: exit_code.max(1),
        }
    }

    pub(crate) const fn reported() -> Self {
        Self {
            message: None,
            exit_code: 1,
        }
    }

    pub(crate) const fn reported_with_code(exit_code: u8) -> Self {
        Self {
            message: None,
            exit_code: if exit_code == 0 { 1 } else { exit_code },
        }
    }

    pub fn message_text(&self) -> Option<&str> {
        self.message.as_deref()
    }

    pub fn exit_code(&self) -> u8 {
        self.exit_code
    }
}

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Parser,
    serde::Deserialize,
    serde::Serialize,
)]
#[clap(about, author, long_about = None, version)]
#[command(arg_required_else_help(true), allow_missing_positional(true))]
pub struct ShepherdCli {
    #[clap(subcommand)]
    pub(crate) command: Option<ShepherdCommand>,
    /// Select one canonical candidate explicitly. Absent means load the full
    /// canonical precedence chain.
    #[clap(long, short = 'C')]
    pub config: Option<String>,
    #[clap(action = clap::ArgAction::Count, long, short)]
    pub release: u8,
    #[arg(action = clap::ArgAction::Count, long, short)]
    pub update: u8,
    #[arg(action = clap::ArgAction::Count, long, short)]
    pub verbose: u8,
}

impl ShepherdCli {
    pub fn parse() -> Self {
        <Self as clap::Parser>::parse()
    }

    pub fn run(self) -> Result<(), CliError> {
        let globals = CliGlobals {
            config: self.config.map(Into::into),
            verbosity: self.verbose,
        };
        match self.command {
            Some(command) => command.run(globals),
            None => Ok(()),
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(crate) struct CliGlobals {
    pub(crate) config: Option<std::path::PathBuf>,
    pub(crate) verbosity: u8,
}
