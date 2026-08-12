/*
    Appellation: shepherd-cli <library>
    Created At: 2026.08.12:14:55:18
    Contrib: @FL03
*/

// modules (public)
pub mod cli;
pub mod settings;

// re-exports
#[doc(inline)]
pub use self::{cli::ShepherdCli, settings::Settings};
// prelude
#[doc(hidden)]
pub mod prelude {
    pub use crate::cli::prelude::*;
    pub use crate::settings::Settings;
}
