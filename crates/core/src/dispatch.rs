/*
    Appellation: dispatch <module>
    Created At: 2026.08.14
    Contrib: @FL03
*/
//! Harness-neutral identity, capability, lifecycle, resume, and context rules.
//!
//! Adapters supply already-normalized native facts. This module never parses a
//! harness event, touches a filesystem, selects a run, or decides a guard
//! predicate. It makes malformed identity and lifecycle states unrepresentable
//! before a native adapter persists or forwards them.

#[doc(inline)]
pub use self::{
    capability::*, context::*, identifier::*, identity::*, lifecycle::*, portable::*, record::*,
    role::*, scope::*,
};

mod capability;
mod context;
mod identifier;
mod identity;
mod lifecycle;
mod portable;
mod record;
mod role;
mod scope;

#[cfg(feature = "alloc")]
use alloc::string::String;

/// A malformed dispatch-domain value or illegal lifecycle transition.
#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
#[non_exhaustive]
pub enum DispatchError {
    #[error("unsafe {kind} `{value}`")]
    InvalidIdentifier { kind: &'static str, value: String },
    #[error("invalid capability `{0}`")]
    InvalidCapability(String),
    #[error("capability `{capability}` appears in both {left} and {right}")]
    CapabilityOverlap {
        capability: String,
        left: &'static str,
        right: &'static str,
    },
    #[error("invalid dispatch role carrier `{0}`")]
    InvalidRole(String),
    #[error("agent type `{agent_type}` disagrees with role `{role}`")]
    AgentTypeRoleMismatch { agent_type: String, role: Role },
    #[error("invalid dispatch time: {0}")]
    InvalidTime(String),
    #[error("invalid write scope `{0}`")]
    InvalidWriteScope(String),
    #[error("invalid result artifact reference `{0}`")]
    InvalidArtifact(String),
    #[error("dispatch record revision mismatch: expected {expected}, found {found}")]
    RevisionMismatch { expected: u64, found: u64 },
    #[error("dispatch agent mismatch: expected `{expected}`, found `{found}`")]
    AgentMismatch { expected: String, found: String },
    #[error("illegal dispatch transition from {from} to {to}")]
    InvalidTransition {
        from: DispatchState,
        to: DispatchState,
    },
    #[error("resume must assign a new native agent id")]
    ReusedResumeIdentity,
    #[error("resume changed immutable {field}: expected `{expected}`, found `{found}`")]
    ResumeMismatch {
        field: &'static str,
        expected: String,
        found: String,
    },
    #[error("invalid context entry: {0}")]
    InvalidContext(String),
    #[error("invalid dispatch record: {0}")]
    InvalidRecord(String),
    #[error("missing dispatch binding")]
    MissingBinding,
    #[error("invalid native lifecycle event `{0}`")]
    InvalidEvent(String),
    #[error("invalid native dispatch response: {0}")]
    InvalidResponse(String),
    #[error("dispatch capability contract blocks work")]
    CapabilityBlocked,
    #[error("invalid parent-child dispatch relation: {0}")]
    InvalidParent(String),
    #[error("{harness} dispatch {kind} limit exceeded: {observed} > {limit}")]
    HarnessLimit {
        harness: crate::Harness,
        kind: &'static str,
        limit: u32,
        observed: u32,
    },
}

/// Dispatch-domain result.
pub type DispatchResult<T> = core::result::Result<T, DispatchError>;
