//! Pure, deterministic compilation of canonical Shepherd content.
#![cfg_attr(not(feature = "std"), no_std)]

#[cfg(feature = "alloc")]
extern crate alloc;

mod budget;
mod compiler;
#[cfg(feature = "std")]
pub mod content;
mod model;

pub use self::{budget::*, compiler::compile, model::*};
