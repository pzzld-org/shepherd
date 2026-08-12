/*
    Appellation: mod <module>
    Created At: 2026.08.12:15:10:01
    Contrib: @FL03
*/

#[doc(inline)]
pub use self::prelude::*;

mod cmd;
mod interface;

pub(crate) mod prelude {
    pub use super::cmd::prelude::*;
    pub use super::interface::*;
}
