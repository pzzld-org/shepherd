//! Host-neutral adapter facts and native dispatch request planning.
//!
//! This module deliberately stops at typed values and bytes. It does not read
//! hook input, invoke a process, access a filesystem, or persist a record. A
//! host adapter only needs to extract a [`RawIdentity`], call a planner, and
//! hand the resulting bytes to its transport.

use alloc::{
    collections::BTreeSet,
    format,
    string::{String, ToString},
    vec,
    vec::Vec,
};

use crate::Harness;

use super::{
    AgentId, AgentType, CapabilityContract, CapabilityProbe, CapabilityReadiness, CapabilityReport,
    DispatchError, DispatchResult, LaneId, NativeIdentity, ProjectId, Role, RunId, SessionId,
    validate_write_scope_pattern,
};

pub const NATIVE_IDENTITY_SCHEMA: &str = "shepherd.native-identity/1";
pub const DISPATCH_REQUEST_SCHEMA: &str = "shepherd.dispatch-request/1";
pub const IDENTITY_RESOLUTION_SCHEMA: &str = "shepherd.identity-resolution/1";
pub const RESUME_CONTEXT_SCHEMA: &str = "shepherd.resume-context/1";
pub const CLAUDE_MAX_CONCURRENT_AGENTS: u32 = 16;
pub const CLAUDE_MAX_TOTAL_DISPATCHES_PER_RUN: u32 = 1_000;
pub const CODEX_MAX_DESCENDANTS: u32 = 3;

/// Event names exposed by the three supported native adapters.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeEvent {
    SessionStart,
    SubagentStart,
    SubagentResume,
    SubagentStop,
    PreToolUse,
    PostToolUse,
    Other(String),
}

impl NativeEvent {
    pub fn parse(value: impl Into<String>) -> DispatchResult<Self> {
        let value = value.into();
        if value.is_empty() || value.len() > 64 || value.chars().any(char::is_control) {
            return Err(DispatchError::InvalidEvent(value));
        }
        Ok(match value.as_str() {
            "SessionStart" => Self::SessionStart,
            "SubagentStart" => Self::SubagentStart,
            "SubagentResume" => Self::SubagentResume,
            "SubagentStop" => Self::SubagentStop,
            "PreToolUse" => Self::PreToolUse,
            "PostToolUse" => Self::PostToolUse,
            _ => Self::Other(value),
        })
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        match self {
            Self::SessionStart => "SessionStart",
            Self::SubagentStart => "SubagentStart",
            Self::SubagentResume => "SubagentResume",
            Self::SubagentStop => "SubagentStop",
            Self::PreToolUse => "PreToolUse",
            Self::PostToolUse => "PostToolUse",
            Self::Other(value) => value,
        }
    }
}

/// Raw, host-extracted identity fields. The constructor does not normalize
/// role carriers because the rule is harness-specific; [`Self::normalize`]
/// applies that rule once for every adapter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RawIdentity {
    pub harness: Harness,
    pub event: NativeEvent,
    pub session_id: String,
    pub agent_id: Option<String>,
    pub agent_type: Option<String>,
    pub tool_call_id: Option<String>,
    pub model: Option<String>,
    pub provider_version: Option<String>,
}

impl RawIdentity {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        harness: Harness,
        event: impl Into<String>,
        session_id: impl Into<String>,
        agent_id: Option<&str>,
        agent_type: Option<&str>,
        tool_call_id: Option<&str>,
        model: Option<&str>,
        provider_version: Option<&str>,
    ) -> Self {
        Self {
            harness,
            event: NativeEvent::parse(event).unwrap_or_else(|_| NativeEvent::Other(String::new())),
            session_id: session_id.into(),
            agent_id: agent_id.map(ToString::to_string),
            agent_type: agent_type.map(ToString::to_string),
            tool_call_id: tool_call_id.map(ToString::to_string),
            model: model.map(ToString::to_string),
            provider_version: provider_version.map(ToString::to_string),
        }
    }

    pub fn from_event(
        harness: Harness,
        event: impl Into<String>,
        session_id: impl Into<String>,
        agent_id: Option<String>,
        agent_type: Option<String>,
    ) -> DispatchResult<Self> {
        Ok(Self {
            harness,
            event: NativeEvent::parse(event)?,
            session_id: session_id.into(),
            agent_id,
            agent_type,
            tool_call_id: None,
            model: None,
            provider_version: None,
        })
    }

    pub fn normalize(self) -> DispatchResult<NormalizedIdentity> {
        if self.event.as_str().is_empty() {
            return Err(DispatchError::InvalidEvent(String::new()));
        }
        let session_id = SessionId::new(self.session_id)?;
        let agent_id = self.agent_id.map(AgentId::new).transpose()?;
        let agent_type = self.agent_type.map(AgentType::new).transpose()?;
        if agent_id.is_some() != agent_type.is_some() {
            return Err(DispatchError::InvalidRecord(
                "native identity requires both agent_id and agent_type".into(),
            ));
        }
        let role_carrier = infer_role_carrier(self.harness, agent_type.as_ref());
        let tool_call_id = self.tool_call_id.map(SessionId::new).transpose()?;
        if self.model.as_ref().is_some_and(|value| {
            value.is_empty() || value.len() > 256 || value.chars().any(char::is_control)
        }) {
            return Err(DispatchError::InvalidIdentifier {
                kind: "model",
                value: self.model.unwrap_or_default(),
            });
        }
        if self.provider_version.as_ref().is_some_and(|value| {
            value.is_empty() || value.len() > 128 || value.chars().any(char::is_control)
        }) {
            return Err(DispatchError::InvalidCapability(
                self.provider_version.unwrap_or_default(),
            ));
        }
        Ok(NormalizedIdentity {
            harness: self.harness,
            event: self.event,
            session_id,
            agent_id,
            agent_type,
            role_carrier,
            tool_call_id,
            model: self.model,
            provider_version: self.provider_version,
        })
    }
}

/// Validated identity facts shared by Claude, Codex, and Pi adapters.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NormalizedIdentity {
    pub harness: Harness,
    pub event: NativeEvent,
    pub session_id: SessionId,
    pub agent_id: Option<AgentId>,
    pub agent_type: Option<AgentType>,
    pub role_carrier: Option<String>,
    /// Correlates one hook pair for audit only. It is never part of identity_key.
    pub tool_call_id: Option<SessionId>,
    pub model: Option<String>,
    pub provider_version: Option<String>,
}

impl NormalizedIdentity {
    #[must_use]
    pub fn session_id(&self) -> &SessionId {
        &self.session_id
    }

    #[must_use]
    pub fn agent_id(&self) -> Option<&AgentId> {
        self.agent_id.as_ref()
    }

    #[must_use]
    pub fn tool_call_id(&self) -> Option<&str> {
        self.tool_call_id.as_ref().map(SessionId::as_str)
    }

    #[must_use]
    pub fn identity_key(&self) -> String {
        format!(
            "{}\0{}\0{}",
            harness_name(self.harness),
            self.session_id,
            self.agent_id.as_ref().map_or("<root>", AgentId::as_str)
        )
    }

    #[must_use]
    pub fn role_carrier(&self) -> Option<&str> {
        self.role_carrier.as_deref()
    }

    pub fn semantic_role(&self) -> DispatchResult<Role> {
        self.role_carrier
            .as_deref()
            .ok_or(DispatchError::MissingBinding)
            .and_then(Role::from_carrier)
    }

    #[must_use]
    pub fn root_role(&self) -> Role {
        Role::Shepherd
    }

    pub fn with_event(&self, event: NativeEvent) -> DispatchResult<Self> {
        let mut copy = self.clone();
        copy.event = event;
        Ok(copy)
    }

    pub fn to_native_identity(
        &self,
        project_id: ProjectId,
        run: RunId,
        lane: Option<LaneId>,
        now: i64,
        root_binding: Option<super::RootSessionBinding>,
    ) -> NativeIdentity {
        NativeIdentity {
            harness: self.harness,
            project_id,
            run,
            lane,
            session_id: self.session_id.clone(),
            agent_id: self.agent_id.clone(),
            agent_type: self.agent_type.clone(),
            role: self
                .role_carrier
                .as_deref()
                .and_then(|value| Role::from_carrier(value).ok()),
            tool_call_id: self.tool_call_id.as_ref().map(ToString::to_string),
            now,
            root_binding,
        }
    }
}

fn harness_name(harness: Harness) -> &'static str {
    match harness {
        Harness::ClaudeCode => "claude",
        Harness::Codex => "codex",
        Harness::Pi => "pi",
        Harness::PrimeAgent => "prime_agent",
    }
}

fn infer_role_carrier(harness: Harness, agent_type: Option<&AgentType>) -> Option<String> {
    let value = agent_type?.as_str();
    if value.starts_with("shepherd:") {
        return Some(value.to_string());
    }
    if harness == Harness::ClaudeCode && !value.contains(':') && Role::from_name(value).is_ok() {
        return Some(format!("shepherd:{value}"));
    }
    None
}

/// Binding facts supplied by a dispatcher or provider. No host object is
/// stored here, so the same value can cross a wasm boundary unchanged.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchBinding {
    pub run: Option<RunId>,
    pub role: Option<Role>,
    pub lane: Option<LaneId>,
    pub parent_agent_id: Option<AgentId>,
    pub write_scope: Vec<String>,
    pub model: Option<String>,
    pub observed_capabilities: BTreeSet<String>,
    pub capability_source: String,
    pub harness_version: String,
    pub provider_version: Option<String>,
    pub lease_ms: u64,
    pub expected_revision: u64,
    pub result_artifact: Option<String>,
    pub source_agent_id: Option<AgentId>,
    pub mode: String,
    pub tool_name: Option<String>,
    pub tool_input: Option<serde_json::Value>,
}

impl DispatchBinding {
    #[allow(clippy::too_many_arguments)]
    pub fn new<I, S>(
        run: Option<RunId>,
        role: Option<Role>,
        lane: Option<LaneId>,
        parent_agent_id: Option<AgentId>,
        write_scope: Vec<String>,
        model: Option<String>,
        observed_capabilities: I,
        capability_source: impl Into<String>,
        harness_version: impl Into<String>,
        provider_version: Option<&str>,
        lease_ms: u64,
    ) -> DispatchResult<Self>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let observed_capabilities = observed_capabilities
            .into_iter()
            .map(|value| value.as_ref().to_string())
            .collect();
        let value = Self {
            run,
            role,
            lane,
            parent_agent_id,
            write_scope,
            model,
            observed_capabilities,
            capability_source: capability_source.into(),
            harness_version: harness_version.into(),
            provider_version: provider_version.map(ToString::to_string),
            lease_ms,
            expected_revision: 1,
            result_artifact: None,
            source_agent_id: None,
            mode: "execution".into(),
            tool_name: None,
            tool_input: None,
        };
        value.validate_common()?;
        Ok(value)
    }

    pub fn root(role: Role, mode: impl Into<String>, lease_ms: u64) -> DispatchResult<Self> {
        Self::new(
            None,
            Some(role),
            None,
            None,
            vec!["**".into()],
            None,
            ["read"],
            "native-root-binding",
            "unknown",
            None,
            lease_ms,
        )
        .map(|mut value| {
            value.mode = mode.into();
            value
        })
    }

    fn validate_common(&self) -> DispatchResult<()> {
        if self.write_scope.is_empty() {
            return Err(DispatchError::InvalidWriteScope(String::new()));
        }
        for scope in &self.write_scope {
            validate_write_scope_pattern(scope)?;
        }
        if self.lease_ms == 0 || self.lease_ms > 86_400_000 {
            return Err(DispatchError::InvalidTime(
                "lease_ms must be positive and bounded".into(),
            ));
        }
        if self.expected_revision == 0 {
            return Err(DispatchError::InvalidRecord(
                "expected revision must be positive".into(),
            ));
        }
        if self.mode.is_empty() || self.mode.len() > 64 || self.mode.chars().any(char::is_control) {
            return Err(DispatchError::InvalidRecord("invalid root mode".into()));
        }
        Ok(())
    }
}

/// Exact operation names accepted by the native CLI dispatch service.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DispatchOperation {
    BindRoot,
    Start,
    Resolve,
    Stop,
    Resume,
    Ignored,
}

impl DispatchOperation {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::BindRoot => "bind-root",
            Self::Start => "start",
            Self::Resolve => "resolve",
            Self::Stop => "stop",
            Self::Resume => "resume",
            Self::Ignored => "ignored",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct BindRootRequest {
    pub schema: String,
    pub run: Option<RunId>,
    pub harness: Harness,
    pub session_id: SessionId,
    pub role_carrier: String,
    pub mode: String,
    pub lease_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct StartRequest {
    pub schema: String,
    pub run: Option<RunId>,
    pub harness: Harness,
    pub agent_id: AgentId,
    pub agent_type: AgentType,
    pub role_carrier: String,
    pub lane: Option<LaneId>,
    pub parent_agent_id: Option<AgentId>,
    pub session_id: SessionId,
    pub write_scope: Vec<String>,
    pub model: Option<String>,
    pub observed_capabilities: BTreeSet<String>,
    pub capability_source: String,
    pub harness_version: String,
    pub provider_version: Option<String>,
    pub lease_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResolveRequest {
    pub schema: String,
    pub run: Option<RunId>,
    pub harness: Harness,
    pub agent_id: Option<AgentId>,
    pub agent_type: Option<AgentType>,
    pub role_carrier: Option<String>,
    pub lane: Option<LaneId>,
    pub session_id: SessionId,
    pub tool_call_id: Option<SessionId>,
    pub tool_name: Option<String>,
    pub tool_input: Option<serde_json::Value>,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct StopDispatchRequest {
    pub schema: String,
    pub run: Option<RunId>,
    pub harness: Harness,
    pub agent_id: AgentId,
    pub agent_type: AgentType,
    pub role_carrier: Option<String>,
    pub lane: Option<LaneId>,
    pub session_id: SessionId,
    pub expected_revision: u64,
    pub result_artifact: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResumeRequest {
    pub schema: String,
    pub source_agent_id: AgentId,
    pub next: StartRequest,
}

/// Names matching the native CLI DTO vocabulary. The aliases keep adapters
/// from inventing a second wire model while retaining the shorter core names.
pub type StartDispatchRequest = StartRequest;
pub type ResolveDispatchRequest = ResolveRequest;
pub type ResumeDispatchRequest = ResumeRequest;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DispatchRequest {
    BindRoot(BindRootRequest),
    Start(StartRequest),
    Resolve(ResolveRequest),
    Stop(StopDispatchRequest),
    Resume(ResumeRequest),
}

impl DispatchRequest {
    #[must_use]
    pub const fn operation(&self) -> DispatchOperation {
        match self {
            Self::BindRoot(_) => DispatchOperation::BindRoot,
            Self::Start(_) => DispatchOperation::Start,
            Self::Resolve(_) => DispatchOperation::Resolve,
            Self::Stop(_) => DispatchOperation::Stop,
            Self::Resume(_) => DispatchOperation::Resume,
        }
    }

    pub fn to_json_bytes(&self) -> DispatchResult<Vec<u8>> {
        let result = match self {
            Self::BindRoot(value) => serde_json::to_vec(value),
            Self::Start(value) => serde_json::to_vec(value),
            Self::Resolve(value) => serde_json::to_vec(value),
            Self::Stop(value) => serde_json::to_vec(value),
            Self::Resume(value) => serde_json::to_vec(value),
        };
        result.map_err(|error| DispatchError::InvalidRecord(error.to_string()))
    }
}

pub fn build_bind_root_request(
    identity: &NormalizedIdentity,
    binding: &DispatchBinding,
) -> DispatchResult<DispatchRequest> {
    if identity.agent_id.is_some()
        || identity.agent_type.is_some()
        || identity.event != NativeEvent::SessionStart
    {
        return Err(DispatchError::InvalidRecord(
            "root identity required for bind-root".into(),
        ));
    }
    let role = binding.role.unwrap_or(Role::Shepherd);
    if !matches!(role, Role::Shepherd | Role::Planter) {
        return Err(DispatchError::InvalidRole(role.to_string()));
    }
    Ok(DispatchRequest::BindRoot(BindRootRequest {
        schema: DISPATCH_REQUEST_SCHEMA.into(),
        run: binding.run.clone(),
        harness: identity.harness,
        session_id: identity.session_id.clone(),
        role_carrier: role.carrier(),
        mode: binding.mode.clone(),
        lease_ms: binding.lease_ms,
    }))
}

pub fn build_start_request(
    identity: &NormalizedIdentity,
    binding: &DispatchBinding,
) -> DispatchResult<DispatchRequest> {
    if identity.agent_id.is_none()
        || identity.agent_type.is_none()
        || identity.event != NativeEvent::SubagentStart
    {
        return Err(DispatchError::InvalidRecord(
            "subagent start identity required".into(),
        ));
    }
    let agent_id = identity
        .agent_id
        .clone()
        .ok_or(DispatchError::MissingBinding)?;
    let agent_type = identity
        .agent_type
        .clone()
        .ok_or(DispatchError::MissingBinding)?;
    validate_parent_child(binding.parent_agent_id.as_ref(), &agent_id)?;
    let role = binding
        .role
        .or_else(|| identity.semantic_role().ok())
        .ok_or(DispatchError::MissingBinding)?;
    if identity.harness == Harness::ClaudeCode
        && agent_type.as_str() != role.as_str()
        && agent_type.as_str() != role.carrier()
    {
        return Err(DispatchError::AgentTypeRoleMismatch {
            agent_type: agent_type.to_string(),
            role,
        });
    }
    let report = validate_provider_binding(role, binding)?;
    if report.readiness() == CapabilityReadiness::Blocked {
        return Err(DispatchError::CapabilityBlocked);
    }
    Ok(DispatchRequest::Start(StartRequest {
        schema: DISPATCH_REQUEST_SCHEMA.into(),
        run: binding.run.clone(),
        harness: identity.harness,
        agent_id,
        agent_type,
        role_carrier: role.carrier(),
        lane: binding.lane.clone(),
        parent_agent_id: binding.parent_agent_id.clone(),
        session_id: identity.session_id.clone(),
        write_scope: binding.write_scope.clone(),
        model: binding.model.clone().or_else(|| identity.model.clone()),
        observed_capabilities: binding.observed_capabilities.clone(),
        capability_source: binding.capability_source.clone(),
        harness_version: binding.harness_version.clone(),
        provider_version: binding
            .provider_version
            .clone()
            .or_else(|| identity.provider_version.clone()),
        lease_ms: binding.lease_ms,
    }))
}

pub fn build_resolve_request(
    identity: &NormalizedIdentity,
    binding: &DispatchBinding,
) -> DispatchResult<DispatchRequest> {
    Ok(DispatchRequest::Resolve(ResolveRequest {
        schema: DISPATCH_REQUEST_SCHEMA.into(),
        run: binding.run.clone(),
        harness: identity.harness,
        agent_id: identity.agent_id.clone(),
        agent_type: identity.agent_type.clone(),
        role_carrier: identity.role_carrier.clone(),
        lane: binding.lane.clone(),
        session_id: identity.session_id.clone(),
        tool_call_id: identity.tool_call_id.clone(),
        tool_name: binding.tool_name.clone(),
        tool_input: binding.tool_input.clone(),
    }))
}

pub fn build_stop_request(
    identity: &NormalizedIdentity,
    binding: &DispatchBinding,
) -> DispatchResult<DispatchRequest> {
    if identity.agent_id.is_none()
        || identity.agent_type.is_none()
        || identity.event != NativeEvent::SubagentStop
    {
        return Err(DispatchError::InvalidRecord(
            "subagent stop identity required".into(),
        ));
    }
    Ok(DispatchRequest::Stop(StopDispatchRequest {
        schema: DISPATCH_REQUEST_SCHEMA.into(),
        run: binding.run.clone(),
        harness: identity.harness,
        agent_id: identity
            .agent_id
            .clone()
            .ok_or(DispatchError::MissingBinding)?,
        agent_type: identity
            .agent_type
            .clone()
            .ok_or(DispatchError::MissingBinding)?,
        role_carrier: identity.role_carrier.clone(),
        lane: binding.lane.clone(),
        session_id: identity.session_id.clone(),
        expected_revision: binding.expected_revision,
        result_artifact: binding.result_artifact.clone(),
    }))
}

pub fn build_resume_request(
    source_agent_id: AgentId,
    next: DispatchRequest,
) -> DispatchResult<DispatchRequest> {
    let DispatchRequest::Start(next) = next else {
        return Err(DispatchError::InvalidTransition {
            from: super::DispatchState::Stopped,
            to: super::DispatchState::Active,
        });
    };
    if next.agent_id == source_agent_id {
        return Err(DispatchError::ReusedResumeIdentity);
    }
    Ok(DispatchRequest::Resume(ResumeRequest {
        schema: DISPATCH_REQUEST_SCHEMA.into(),
        source_agent_id,
        next,
    }))
}

pub fn validate_parent_child(parent: Option<&AgentId>, child: &AgentId) -> DispatchResult<()> {
    if parent == Some(child) {
        Err(DispatchError::InvalidParent(child.to_string()))
    } else {
        Ok(())
    }
}

pub fn validate_provider_binding(
    role: Role,
    binding: &DispatchBinding,
) -> DispatchResult<CapabilityReport> {
    let contract: CapabilityContract = role.dispatch_capability_contract()?;
    let probe = CapabilityProbe::new(
        binding.observed_capabilities.clone(),
        binding.capability_source.clone(),
        binding.harness_version.clone(),
        binding.provider_version.as_deref(),
        0,
    )?;
    let report = contract.evaluate(probe);
    if report.readiness() == CapabilityReadiness::Blocked {
        Err(DispatchError::CapabilityBlocked)
    } else {
        Ok(report)
    }
}

// Request DTOs are intentionally owned in this plan so an adapter can hand
// the plan across a transport boundary without a second lifetime or arena.
#[allow(clippy::large_enum_variant)]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DispatchPlan {
    Request(DispatchRequest),
    Ignored,
    Blocked(DispatchError),
}

impl DispatchPlan {
    #[must_use]
    pub const fn operation(&self) -> DispatchOperation {
        match self {
            Self::Request(request) => request.operation(),
            Self::Ignored => DispatchOperation::Ignored,
            Self::Blocked(_) => DispatchOperation::Ignored,
        }
    }

    #[must_use]
    pub fn request(&self) -> Option<&DispatchRequest> {
        match self {
            Self::Request(request) => Some(request),
            Self::Ignored | Self::Blocked(_) => None,
        }
    }
}

pub fn plan_lifecycle(
    identity: &NormalizedIdentity,
    binding: Option<&DispatchBinding>,
) -> DispatchResult<DispatchPlan> {
    let result = match &identity.event {
        NativeEvent::SessionStart => {
            let default = DispatchBinding::root(Role::Shepherd, "execution", 86_400_000)?;
            DispatchPlan::Request(build_bind_root_request(
                identity,
                binding.unwrap_or(&default),
            )?)
        }
        NativeEvent::SubagentStart => {
            let Some(binding) = binding else {
                return Ok(DispatchPlan::Blocked(DispatchError::MissingBinding));
            };
            DispatchPlan::Request(build_start_request(identity, binding)?)
        }
        NativeEvent::SubagentStop => {
            let Some(binding) = binding else {
                return Ok(DispatchPlan::Blocked(DispatchError::MissingBinding));
            };
            DispatchPlan::Request(build_stop_request(identity, binding)?)
        }
        NativeEvent::PreToolUse | NativeEvent::PostToolUse => {
            let default = DispatchBinding::root(Role::Shepherd, "execution", 86_400_000)?;
            DispatchPlan::Request(build_resolve_request(
                identity,
                binding.unwrap_or(&default),
            )?)
        }
        NativeEvent::SubagentResume => {
            let Some(binding) = binding else {
                return Ok(DispatchPlan::Blocked(DispatchError::MissingBinding));
            };
            let Some(source_agent_id) = binding.source_agent_id.clone() else {
                return Ok(DispatchPlan::Blocked(DispatchError::MissingBinding));
            };
            let next_identity = identity.with_event(NativeEvent::SubagentStart)?;
            let next = build_start_request(&next_identity, binding)?;
            DispatchPlan::Request(build_resume_request(source_agent_id, next)?)
        }
        NativeEvent::Other(_) => DispatchPlan::Ignored,
    };
    Ok(result)
}

/// Native identity-resolution facts. This is intentionally a facts envelope,
/// not a policy verdict; adapters translate it into their host verdict shape.
#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchResponseFacts {
    pub schema: String,
    pub project_id: ProjectId,
    pub run: RunId,
    pub harness: Harness,
    pub agent_id: Option<String>,
    pub agent_type: Option<AgentType>,
    pub role: Role,
    pub lane: Option<LaneId>,
    pub session_id: SessionId,
    pub write_scope: Vec<String>,
    pub capabilities: Option<CapabilityReport>,
    pub tool_call_id: Option<String>,
    pub mode: Option<String>,
    pub write_paths: Vec<String>,
    pub path_in_write_scope: Option<bool>,
}

impl DispatchResponseFacts {
    pub fn validate(&self) -> DispatchResult<()> {
        if self.schema != IDENTITY_RESOLUTION_SCHEMA {
            return Err(DispatchError::InvalidResponse(self.schema.clone()));
        }
        let agent_id = self.agent_id.as_deref().map(AgentId::new).transpose()?;
        if agent_id.is_none() != self.agent_type.is_none() {
            return Err(DispatchError::InvalidResponse(
                "partial agent identity".into(),
            ));
        }
        if agent_id.is_none() && !matches!(self.role, Role::Shepherd | Role::Planter) {
            return Err(DispatchError::InvalidResponse("invalid root role".into()));
        }
        if self.harness == Harness::ClaudeCode
            && let Some(agent_type) = &self.agent_type
            && agent_type.as_str() != self.role.as_str()
            && agent_type.as_str() != self.role.carrier()
        {
            return Err(DispatchError::AgentTypeRoleMismatch {
                agent_type: agent_type.to_string(),
                role: self.role,
            });
        }
        for scope in &self.write_scope {
            validate_write_scope_pattern(scope)?;
        }
        for path in &self.write_paths {
            let derived = super::path_in_write_scope(path, &self.write_scope)?;
            if self.path_in_write_scope != Some(derived) {
                return Err(DispatchError::InvalidResponse(
                    "write-scope fact disagrees with write paths".into(),
                ));
            }
        }
        if let Some(report) = &self.capabilities {
            report.validate()?;
        }
        if let Some(mode) = &self.mode
            && (mode.is_empty() || mode.len() > 64 || mode.chars().any(char::is_control))
        {
            return Err(DispatchError::InvalidResponse("invalid mode".into()));
        }
        if let Some(tool_call_id) = &self.tool_call_id {
            SessionId::new(tool_call_id.clone())?;
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HarnessLimits {
    pub harness: Harness,
    pub max_concurrent_agents: Option<u32>,
    pub max_total_dispatches_per_run: Option<u32>,
}

impl HarnessLimits {
    pub fn validate_budget(
        self,
        total_dispatches: u32,
        concurrent_agents: u32,
    ) -> DispatchResult<()> {
        if self
            .max_total_dispatches_per_run
            .is_some_and(|limit| total_dispatches > limit)
        {
            return Err(DispatchError::HarnessLimit {
                harness: self.harness,
                kind: "total dispatch",
                limit: self.max_total_dispatches_per_run.unwrap_or_default(),
                observed: total_dispatches,
            });
        }
        if self
            .max_concurrent_agents
            .is_some_and(|limit| concurrent_agents > limit)
        {
            return Err(DispatchError::HarnessLimit {
                harness: self.harness,
                kind: "concurrent agent",
                limit: self.max_concurrent_agents.unwrap_or_default(),
                observed: concurrent_agents,
            });
        }
        Ok(())
    }
}

impl Harness {
    #[must_use]
    pub const fn limits(self) -> HarnessLimits {
        match self {
            Self::ClaudeCode => HarnessLimits {
                harness: self,
                max_concurrent_agents: Some(CLAUDE_MAX_CONCURRENT_AGENTS),
                max_total_dispatches_per_run: Some(CLAUDE_MAX_TOTAL_DISPATCHES_PER_RUN),
            },
            Self::Codex => HarnessLimits {
                harness: self,
                max_concurrent_agents: Some(CODEX_MAX_DESCENDANTS),
                max_total_dispatches_per_run: None,
            },
            Self::Pi | Self::PrimeAgent => HarnessLimits {
                harness: self,
                max_concurrent_agents: None,
                max_total_dispatches_per_run: None,
            },
        }
    }
}
