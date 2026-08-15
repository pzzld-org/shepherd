//! Versioned dispatch record creation, stop, and cross-harness resume.

#[cfg(feature = "alloc")]
use alloc::{
    format,
    string::{String, ToString},
    vec::Vec,
};

use crate::Harness;

use super::{
    AgentId, AgentType, CapabilityContract, CapabilityProbe, CapabilityReadiness, CapabilityReport,
    DispatchError, DispatchResult, LaneId, ProjectId, Role, RunId, SessionId,
    validate_write_scope_pattern,
};

pub const DISPATCH_SCHEMA: &str = "shepherd.dispatch/3";

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum DispatchState {
    Active,
    CapabilityBlocked,
    Stopped,
}

impl DispatchState {
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::CapabilityBlocked | Self::Stopped)
    }
}

impl core::fmt::Display for DispatchState {
    fn fmt(&self, formatter: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        formatter.write_str(match self {
            Self::Active => "active",
            Self::CapabilityBlocked => "capability_blocked",
            Self::Stopped => "stopped",
        })
    }
}

impl serde::Serialize for DispatchState {
    fn serialize<S>(&self, serializer: S) -> core::result::Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(match self {
            Self::Active => "active",
            Self::CapabilityBlocked => "capability_blocked",
            Self::Stopped => "stopped",
        })
    }
}

impl<'de> serde::Deserialize<'de> for DispatchState {
    fn deserialize<D>(deserializer: D) -> core::result::Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        match String::deserialize(deserializer)?.as_str() {
            "active" => Ok(Self::Active),
            "capability_blocked" => Ok(Self::CapabilityBlocked),
            "stopped" => Ok(Self::Stopped),
            value => Err(serde::de::Error::unknown_variant(
                value,
                &["active", "capability_blocked", "stopped"],
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchStart {
    pub project_id: ProjectId,
    pub run: RunId,
    pub harness: Harness,
    pub agent_id: AgentId,
    pub agent_type: AgentType,
    pub role: Role,
    pub lane: Option<LaneId>,
    pub parent_agent_id: Option<AgentId>,
    pub session_id: SessionId,
    pub write_scope: Vec<String>,
    pub model: Option<String>,
    pub capability_contract: CapabilityContract,
    pub capability_probe: CapabilityProbe,
    pub started_at: i64,
    pub lease_expires_at: i64,
    pub resumes_agent_id: Option<AgentId>,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchRecord {
    pub schema: String,
    pub revision: u64,
    pub project_id: ProjectId,
    pub run: RunId,
    pub harness: Harness,
    pub agent_id: AgentId,
    pub agent_type: AgentType,
    pub role: Role,
    pub lane: Option<LaneId>,
    pub parent_agent_id: Option<AgentId>,
    pub session_id: SessionId,
    pub write_scope: Vec<String>,
    pub model: Option<String>,
    pub capabilities: CapabilityReport,
    pub state: DispatchState,
    pub started_at: i64,
    pub lease_expires_at: i64,
    pub stopped_at: Option<i64>,
    pub result_artifact: Option<String>,
    pub resumes_agent_id: Option<AgentId>,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct StopRequest {
    pub agent_id: AgentId,
    pub expected_revision: u64,
    pub stopped_at: i64,
    pub result_artifact: Option<String>,
}

impl DispatchRecord {
    pub fn start(input: DispatchStart) -> DispatchResult<Self> {
        validate_start(&input)?;
        let compiled_contract = input.role.dispatch_capability_contract()?;
        if input.capability_contract != compiled_contract {
            return Err(DispatchError::InvalidRecord(
                "capability contract does not match the compiled role profile".into(),
            ));
        }
        let capabilities = input.capability_contract.evaluate(input.capability_probe);
        let blocked = capabilities.readiness() == CapabilityReadiness::Blocked;
        let record = Self {
            schema: DISPATCH_SCHEMA.into(),
            revision: 1,
            project_id: input.project_id,
            run: input.run,
            harness: input.harness,
            agent_id: input.agent_id,
            agent_type: input.agent_type,
            role: input.role,
            lane: input.lane,
            parent_agent_id: input.parent_agent_id,
            session_id: input.session_id,
            write_scope: input.write_scope,
            model: input.model,
            capabilities,
            state: if blocked {
                DispatchState::CapabilityBlocked
            } else {
                DispatchState::Active
            },
            started_at: input.started_at,
            lease_expires_at: input.lease_expires_at,
            stopped_at: blocked.then_some(input.started_at),
            result_artifact: None,
            resumes_agent_id: input.resumes_agent_id,
        };
        record.validate_loaded()?;
        Ok(record)
    }

    pub fn validate_loaded(&self) -> DispatchResult<()> {
        if self.schema != DISPATCH_SCHEMA {
            return Err(DispatchError::InvalidRecord(format!(
                "unsupported schema `{}`",
                self.schema
            )));
        }
        if self.revision == 0 {
            return Err(DispatchError::InvalidRecord(
                "revision must be positive".into(),
            ));
        }
        self.capabilities.validate()?;
        let expected_capabilities =
            self.role
                .dispatch_capability_contract()?
                .evaluate(CapabilityProbe {
                    observed: self.capabilities.observed.clone(),
                    source: self.capabilities.source.clone(),
                    harness_version: self.capabilities.harness_version.clone(),
                    provider_version: self.capabilities.provider_version.clone(),
                    probed_at: self.capabilities.probed_at,
                });
        if self.capabilities != expected_capabilities {
            return Err(DispatchError::InvalidRecord(
                "capability diff does not match the compiled role profile".into(),
            ));
        }
        let start = DispatchStart {
            project_id: self.project_id.clone(),
            run: self.run.clone(),
            harness: self.harness,
            agent_id: self.agent_id.clone(),
            agent_type: self.agent_type.clone(),
            role: self.role,
            lane: self.lane.clone(),
            parent_agent_id: self.parent_agent_id.clone(),
            session_id: self.session_id.clone(),
            write_scope: self.write_scope.clone(),
            model: self.model.clone(),
            capability_contract: CapabilityContract::default(),
            capability_probe: CapabilityProbe {
                observed: self.capabilities.observed.clone(),
                source: self.capabilities.source.clone(),
                harness_version: self.capabilities.harness_version.clone(),
                provider_version: self.capabilities.provider_version.clone(),
                probed_at: self.capabilities.probed_at,
            },
            started_at: self.started_at,
            lease_expires_at: self.lease_expires_at,
            resumes_agent_id: self.resumes_agent_id.clone(),
        };
        validate_start(&start)?;
        start.capability_probe.validate()?;
        match self.state {
            DispatchState::Active
                if self.revision == 1
                    && self.stopped_at.is_none()
                    && self.result_artifact.is_none()
                    && self.capabilities.readiness() != CapabilityReadiness::Blocked => {}
            DispatchState::CapabilityBlocked
                if self.revision == 1
                    && self.stopped_at == Some(self.started_at)
                    && self.result_artifact.is_none()
                    && self.capabilities.readiness() == CapabilityReadiness::Blocked => {}
            DispatchState::Stopped
                if self.revision >= 2
                    && self.stopped_at.is_some_and(|at| at >= self.started_at) =>
            {
                if let Some(reference) = &self.result_artifact {
                    validate_artifact(reference)?;
                }
            }
            _ => {
                return Err(DispatchError::InvalidRecord(
                    "state, revision, timestamps, and capability readiness disagree".into(),
                ));
            }
        }
        Ok(())
    }

    pub fn stop(&mut self, request: StopRequest) -> DispatchResult<()> {
        if request.expected_revision != self.revision {
            return Err(DispatchError::RevisionMismatch {
                expected: request.expected_revision,
                found: self.revision,
            });
        }
        if request.agent_id != self.agent_id {
            return Err(DispatchError::AgentMismatch {
                expected: self.agent_id.to_string(),
                found: request.agent_id.to_string(),
            });
        }
        if self.state != DispatchState::Active {
            return Err(DispatchError::InvalidTransition {
                from: self.state,
                to: DispatchState::Stopped,
            });
        }
        if request.stopped_at < self.started_at {
            return Err(DispatchError::InvalidTime(
                "stop time precedes start time".into(),
            ));
        }
        if let Some(reference) = &request.result_artifact {
            validate_artifact(reference)?;
        }
        self.state = DispatchState::Stopped;
        self.stopped_at = Some(request.stopped_at);
        self.result_artifact = request.result_artifact;
        self.revision += 1;
        Ok(())
    }

    pub fn resume(&self, input: DispatchStart) -> DispatchResult<Self> {
        if !self.state.is_terminal() {
            return Err(DispatchError::InvalidTransition {
                from: self.state,
                to: DispatchState::Active,
            });
        }
        if input.agent_id == self.agent_id {
            return Err(DispatchError::ReusedResumeIdentity);
        }
        if input.resumes_agent_id.as_ref() != Some(&self.agent_id) {
            return Err(DispatchError::ResumeMismatch {
                field: "resumes_agent_id",
                expected: self.agent_id.to_string(),
                found: input
                    .resumes_agent_id
                    .as_ref()
                    .map(ToString::to_string)
                    .unwrap_or_default(),
            });
        }
        require_resume_match("project_id", &self.project_id, &input.project_id)?;
        require_resume_match("run", &self.run, &input.run)?;
        require_resume_match("role", &self.role, &input.role)?;
        require_resume_match("lane", &self.lane, &input.lane)?;
        if self.write_scope != input.write_scope {
            return Err(DispatchError::ResumeMismatch {
                field: "write_scope",
                expected: format!("{:?}", self.write_scope),
                found: format!("{:?}", input.write_scope),
            });
        }
        Self::start(input)
    }
}

fn validate_start(input: &DispatchStart) -> DispatchResult<()> {
    input.capability_contract.validate()?;
    input.capability_probe.validate()?;
    if input.harness == Harness::ClaudeCode
        && input.agent_type.as_str() != input.role.as_str()
        && input.agent_type.as_str() != input.role.carrier()
    {
        return Err(DispatchError::AgentTypeRoleMismatch {
            agent_type: input.agent_type.to_string(),
            role: input.role,
        });
    }
    if input.started_at < 0 || input.lease_expires_at <= input.started_at {
        return Err(DispatchError::InvalidTime(
            "lease must expire after a non-negative start".into(),
        ));
    }
    if input.resumes_agent_id.as_ref() == Some(&input.agent_id) {
        return Err(DispatchError::ReusedResumeIdentity);
    }
    if input.write_scope.is_empty() {
        return Err(DispatchError::InvalidWriteScope(String::new()));
    }
    for scope in &input.write_scope {
        validate_write_scope_pattern(scope)?;
    }
    if input.model.as_ref().is_some_and(|model| {
        model.is_empty() || model.len() > 256 || model.chars().any(char::is_control)
    }) {
        return Err(DispatchError::InvalidIdentifier {
            kind: "model",
            value: input.model.clone().unwrap_or_default(),
        });
    }
    Ok(())
}

fn validate_artifact(reference: &str) -> DispatchResult<()> {
    let valid = !reference.is_empty()
        && reference.len() <= 512
        && !reference.starts_with('/')
        && !reference.contains('\\')
        && !reference.contains('\0')
        && !reference.chars().any(char::is_control)
        && reference
            .split('/')
            .all(|part| !part.is_empty() && part != "." && part != "..");
    if valid {
        Ok(())
    } else {
        Err(DispatchError::InvalidArtifact(reference.into()))
    }
}

fn require_resume_match<T>(field: &'static str, expected: &T, found: &T) -> DispatchResult<()>
where
    T: Eq + core::fmt::Debug,
{
    if expected == found {
        Ok(())
    } else {
        Err(DispatchError::ResumeMismatch {
            field,
            expected: format!("{expected:?}"),
            found: format!("{found:?}"),
        })
    }
}
