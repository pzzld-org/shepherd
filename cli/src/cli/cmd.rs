/*
    Appellation: cmd <module>
    Created At: 2026.08.12:15:10:28
    Contrib: @FL03
*/
#[doc(inline)]
pub use self::prelude::*;

pub mod init;

pub(crate) mod prelude {
    pub use super::ShepherdCommand;
    pub use super::init::InitCmd;
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
    Init(InitCmd)
}
