/*
    Appellation: interface <module>
    Created At: 2026.08.12:15:09:50
    Contrib: @FL03
*/
use crate::cmd::ShepherdCommand;

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
    #[clap(long, short = 'C', default_value_t = String::from(".shepherd/shepherd.toml"))]
    pub config: String,
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
}
