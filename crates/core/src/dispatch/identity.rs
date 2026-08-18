//! Native identity validation independent of per-tool call identifiers.

#[cfg(feature = "alloc")]
use alloc::string::{String, ToString};

use crate::Harness;

use super::{
    AgentId, AgentType, CapabilityReadiness, DispatchRecord, DispatchState, LaneId, ProjectId,
    Role, RunId, SessionId,
};

pub const ROOT_SESSION_SCHEMA: &str = "shepherd.root-session/1";

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootSessionBinding {
    pub schema: String,
    pub project_id: ProjectId,
    pub run: RunId,
    pub harness: Harness,
    pub session_id: SessionId,
    pub role: Role,
    pub mode: String,
    pub bound_at: i64,
    pub expires_at: i64,
}

impl RootSessionBinding {
    /// Validate the persisted, host-independent shape of a root-session binding.
    pub fn validate(&self) -> core::result::Result<(), IdentityError> {
        if self.schema != ROOT_SESSION_SCHEMA {
            return Err(IdentityError::InvalidRootBinding(self.schema.clone()));
        }
        if !matches!(self.role, Role::Shepherd | Role::Planter) {
            return Err(IdentityError::InvalidRootBinding(self.role.to_string()));
        }
        let mode = self.mode.as_bytes();
        if self.bound_at < 0
            || self.expires_at <= self.bound_at
            || !(1..=64).contains(&mode.len())
            || !mode[0].is_ascii_lowercase()
            || !mode.iter().all(|byte| {
                byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(*byte, b'-' | b'_')
            })
        {
            return Err(IdentityError::InvalidRootBinding(
                "binding time range or mode is invalid".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeIdentity {
    pub harness: Harness,
    pub project_id: ProjectId,
    pub run: RunId,
    pub lane: Option<LaneId>,
    pub session_id: SessionId,
    pub agent_id: Option<AgentId>,
    pub agent_type: Option<AgentType>,
    pub role: Option<Role>,
    /// Audit-only correlation for one Pre/Post tool pair. Identity resolution
    /// deliberately never reads this field.
    pub tool_call_id: Option<String>,
    pub now: i64,
    pub root_binding: Option<RootSessionBinding>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IdentityResolution {
    Root { role: Role, mode: String },
    Agent { agent_id: AgentId, role: Role },
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
#[non_exhaustive]
pub enum IdentityError {
    #[error("native identity fields are incomplete")]
    IncompleteNativeIdentity,
    #[error("no explicit root session binding exists")]
    MissingRootBinding,
    #[error("dispatch record missing for native agent `{agent_id}`")]
    MissingRecord { agent_id: AgentId },
    #[error("dispatch agent id mismatch: native `{native}`, record `{record}`")]
    AgentIdMismatch { native: AgentId, record: AgentId },
    #[error("dispatch agent type mismatch: native `{native}`, record `{record}`")]
    AgentTypeMismatch {
        native: AgentType,
        record: AgentType,
    },
    #[error("dispatch role mismatch: native `{native}`, record `{record}`")]
    RoleMismatch { native: Role, record: Role },
    #[error("dispatch harness mismatch")]
    HarnessMismatch,
    #[error("dispatch project mismatch")]
    ProjectMismatch,
    #[error("wrong active run: native `{native}`, record `{record}`")]
    WrongRun { native: RunId, record: RunId },
    #[error("wrong lane: native `{native:?}`, record `{record:?}`")]
    WrongLane {
        native: Option<LaneId>,
        record: Option<LaneId>,
    },
    #[error("dispatch session mismatch")]
    SessionMismatch,
    #[error("dispatch record is stale since {expired_at}")]
    Stale { expired_at: i64 },
    #[error("dispatch record is terminal: {state}")]
    Terminal { state: DispatchState },
    #[error("dispatch capability contract blocks work")]
    CapabilityBlocked,
    #[error("root session binding is invalid: {0}")]
    InvalidRootBinding(String),
}

pub fn resolve_native_identity(
    record: Option<&DispatchRecord>,
    native: &NativeIdentity,
) -> core::result::Result<IdentityResolution, IdentityError> {
    let Some(agent_id) = &native.agent_id else {
        if native.agent_type.is_some() || native.role.is_some() {
            return Err(IdentityError::IncompleteNativeIdentity);
        }
        return resolve_root(native);
    };
    let record = record.ok_or_else(|| IdentityError::MissingRecord {
        agent_id: agent_id.clone(),
    })?;
    if agent_id != &record.agent_id {
        return Err(IdentityError::AgentIdMismatch {
            native: agent_id.clone(),
            record: record.agent_id.clone(),
        });
    }
    // A host declares agent_type when the agent starts and resends only
    // agent_id on each tool call afterwards. The record is the authority for
    // the type, so an absent one is read from there rather than treated as an
    // incomplete identity. A type that IS supplied still has to agree.
    if let Some(agent_type) = &native.agent_type
        && agent_type != &record.agent_type
    {
        return Err(IdentityError::AgentTypeMismatch {
            native: agent_type.clone(),
            record: record.agent_type.clone(),
        });
    }
    if let Some(role) = native.role
        && role != record.role
    {
        return Err(IdentityError::RoleMismatch {
            native: role,
            record: record.role,
        });
    }
    if native.harness != record.harness {
        return Err(IdentityError::HarnessMismatch);
    }
    if native.project_id != record.project_id {
        return Err(IdentityError::ProjectMismatch);
    }
    if native.run != record.run {
        return Err(IdentityError::WrongRun {
            native: native.run.clone(),
            record: record.run.clone(),
        });
    }
    if native.lane.is_some() && native.lane != record.lane {
        return Err(IdentityError::WrongLane {
            native: native.lane.clone(),
            record: record.lane.clone(),
        });
    }
    if native.session_id != record.session_id {
        return Err(IdentityError::SessionMismatch);
    }
    if record.state != DispatchState::Active {
        return Err(IdentityError::Terminal {
            state: record.state,
        });
    }
    if native.now >= record.lease_expires_at {
        return Err(IdentityError::Stale {
            expired_at: record.lease_expires_at,
        });
    }
    if record.capabilities.readiness() == CapabilityReadiness::Blocked {
        return Err(IdentityError::CapabilityBlocked);
    }
    Ok(IdentityResolution::Agent {
        agent_id: agent_id.clone(),
        role: record.role,
    })
}

fn resolve_root(
    native: &NativeIdentity,
) -> core::result::Result<IdentityResolution, IdentityError> {
    let binding = native
        .root_binding
        .as_ref()
        .ok_or(IdentityError::MissingRootBinding)?;
    binding.validate()?;
    if binding.bound_at > native.now {
        return Err(IdentityError::InvalidRootBinding(
            "binding begins in the future".into(),
        ));
    }
    if binding.harness != native.harness {
        return Err(IdentityError::HarnessMismatch);
    }
    if binding.project_id != native.project_id {
        return Err(IdentityError::ProjectMismatch);
    }
    if binding.run != native.run {
        return Err(IdentityError::WrongRun {
            native: native.run.clone(),
            record: binding.run.clone(),
        });
    }
    if binding.session_id != native.session_id {
        return Err(IdentityError::SessionMismatch);
    }
    if native.now >= binding.expires_at {
        return Err(IdentityError::Stale {
            expired_at: binding.expires_at,
        });
    }
    Ok(IdentityResolution::Root {
        role: binding.role,
        mode: binding.mode.clone(),
    })
}
