/*
    Appellation: guard <module>
    Created At: 2026.08.14:00:00:00
    Contrib: @FL03
*/
//! Harness-neutral guard-predicate evaluation.
//!
//! The evaluator consumes already-loaded predicate and role documents. It
//! does not inspect a process, choose a harness posture, or discover content
//! paths. [`GuardEngine::load_content`] is the optional `std` adapter for an
//! explicit caller-supplied path; the policy path remains allocation-only.

#[doc(inline)]
pub use self::{engine::GuardEngine, model::*, parser::*, tokenizer::extract_git_subcommands};

mod engine;
#[cfg(feature = "json")]
mod json;
mod model;
mod parser;
mod tokenizer;
