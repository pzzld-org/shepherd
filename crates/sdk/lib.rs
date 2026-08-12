/*
    Appellation: axiom <library>
    Created At: 2026.03.17:20:17:26
    Contrib: @FL03
*/
//! Welcome to `shepherd-sdk`
#![deny(deprecated)]
#![cfg_attr(not(feature = "std"), no_std)]
#![cfg_attr(all(feature = "nightly", feature = "alloc"), feature(allocator_api))]
// external crates
#[cfg(feature = "alloc")]
extern crate alloc;
// modules

// re-exports
#[doc(inline)]
pub use shepherd_core::*;
// prelude
#[doc(hidden)]
pub mod prelude {
    pub use shepherd_core::prelude::*;

}
