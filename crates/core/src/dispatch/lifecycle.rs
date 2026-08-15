//! Typed native lifecycle response validation.
//!
//! The CLI owns persistence and each harness owns transport. This module owns
//! the response contract between them so an adapter cannot mistake one native
//! operation's JSON shape for another operation's authority.

use alloc::{
    format,
    string::{String, ToString},
};

use super::{
    AgentId, BindRootRequest, ContextBundle, DISPATCH_REQUEST_SCHEMA, DispatchError,
    DispatchRecord, DispatchRequest, DispatchResponseFacts, DispatchResult, DispatchState,
    RESUME_CONTEXT_SCHEMA, Role, RootSessionBinding, StartRequest, StopDispatchRequest,
};

/// The native operation that produced a response.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeLifecycleOperation {
    BindRoot,
    Start,
    Resolve,
    Stop,
    Resume,
}

/// A native response shape accepted by the host-neutral lifecycle boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeLifecycleResponse {
    BindRoot(RootSessionBinding),
    Start(DispatchRecord),
    Resolve(DispatchResponseFacts),
    Stop(DispatchRecord),
    Resume(ResumeContextResponse),
}

/// A successful resume includes the new active dispatch and its bounded
/// context bundle. The schema makes this envelope distinguishable from a bare
/// start record in every native transport.
#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResumeContextResponse {
    pub schema: String,
    pub record: DispatchRecord,
    pub context: ContextBundle,
}

impl NativeLifecycleResponse {
    /// Validate that a native lifecycle result has the exact type and terminal
    /// state required by the operation that requested it.
    pub fn validate_for(&self, operation: NativeLifecycleOperation) -> DispatchResult<()> {
        match (operation, self) {
            (NativeLifecycleOperation::BindRoot, Self::BindRoot(binding)) => binding
                .validate()
                .map_err(|error| DispatchError::InvalidResponse(error.to_string())),
            (NativeLifecycleOperation::Start, Self::Start(record)) => {
                record.validate_loaded()?;
                if matches!(
                    record.state,
                    DispatchState::Active | DispatchState::CapabilityBlocked
                ) {
                    Ok(())
                } else {
                    Err(DispatchError::InvalidResponse(
                        "start response must be active or capability_blocked".into(),
                    ))
                }
            }
            (NativeLifecycleOperation::Resolve, Self::Resolve(response)) => response.validate(),
            (NativeLifecycleOperation::Stop, Self::Stop(record)) => {
                record.validate_loaded()?;
                if record.state == DispatchState::Stopped {
                    Ok(())
                } else {
                    Err(DispatchError::InvalidResponse(
                        "stop response must be stopped".into(),
                    ))
                }
            }
            (NativeLifecycleOperation::Resume, Self::Resume(response)) => response.validate(),
            (operation, response) => Err(DispatchError::InvalidResponse(format!(
                "native {operation:?} response has incompatible {} shape",
                response.operation_name()
            ))),
        }
    }
}

/// Validate a complete native request/response exchange. In addition to the
/// response shape and terminal state, this establishes that the response is
/// the one produced for the exact typed request the adapter sent.
pub fn validate_native_exchange(
    request: &DispatchRequest,
    response: &NativeLifecycleResponse,
) -> DispatchResult<()> {
    match (request, response) {
        (DispatchRequest::BindRoot(request), NativeLifecycleResponse::BindRoot(response)) => {
            response
                .validate()
                .map_err(|error| DispatchError::InvalidResponse(error.to_string()))?;
            validate_bind_root_exchange(request, response)
        }
        (DispatchRequest::Start(request), NativeLifecycleResponse::Start(response)) => {
            response.validate_loaded()?;
            if !matches!(
                response.state,
                DispatchState::Active | DispatchState::CapabilityBlocked
            ) {
                return invalid_exchange("start response must be active or capability_blocked");
            }
            validate_start_exchange(request, response, None)
        }
        (DispatchRequest::Resolve(request), NativeLifecycleResponse::Resolve(response)) => {
            response.validate()?;
            validate_resolve_exchange(request, response)
        }
        (DispatchRequest::Stop(request), NativeLifecycleResponse::Stop(response)) => {
            response.validate_loaded()?;
            if response.state != DispatchState::Stopped {
                return invalid_exchange("stop response must be stopped");
            }
            validate_stop_exchange(request, response)
        }
        (DispatchRequest::Resume(request), NativeLifecycleResponse::Resume(response)) => {
            response.validate()?;
            if response.record.resumes_agent_id.as_ref() != Some(&request.source_agent_id) {
                return invalid_exchange("resume response has the wrong source agent");
            }
            validate_start_exchange(
                &request.next,
                &response.record,
                Some(&request.source_agent_id),
            )
        }
        (request, response) => invalid_exchange(format!(
            "request operation `{}` has incompatible {} response",
            request.operation().as_str(),
            response.operation_name()
        )),
    }
}

impl NativeLifecycleResponse {
    const fn operation_name(&self) -> &'static str {
        match self {
            Self::BindRoot(_) => "bind-root",
            Self::Start(_) => "start",
            Self::Resolve(_) => "resolve",
            Self::Stop(_) => "stop",
            Self::Resume(_) => "resume",
        }
    }
}

fn validate_bind_root_exchange(
    request: &BindRootRequest,
    response: &RootSessionBinding,
) -> DispatchResult<()> {
    validate_request_schema(&request.schema)?;
    let role = Role::from_carrier(&request.role_carrier)?;
    if request.run.as_ref().is_some_and(|run| run != &response.run)
        || request.harness != response.harness
        || request.session_id != response.session_id
        || role != response.role
        || request.mode != response.mode
    {
        return invalid_exchange("root binding does not match its request");
    }
    validate_lease_duration(response.expires_at - response.bound_at, request.lease_ms)
}

fn validate_start_exchange(
    request: &StartRequest,
    response: &DispatchRecord,
    resumes_agent_id: Option<&AgentId>,
) -> DispatchResult<()> {
    validate_request_schema(&request.schema)?;
    let role = Role::from_carrier(&request.role_carrier)?;
    if request.run.as_ref().is_some_and(|run| run != &response.run)
        || request.harness != response.harness
        || request.agent_id != response.agent_id
        || request.agent_type != response.agent_type
        || role != response.role
        || request.lane != response.lane
        || request.parent_agent_id != response.parent_agent_id
        || request.session_id != response.session_id
        || request.write_scope != response.write_scope
        || request.model != response.model
        || request.observed_capabilities != response.capabilities.observed
        || request.capability_source != response.capabilities.source
        || request.harness_version != response.capabilities.harness_version
        || request.provider_version != response.capabilities.provider_version
        || resumes_agent_id != response.resumes_agent_id.as_ref()
    {
        return invalid_exchange("start record does not match its request");
    }
    let duration = response
        .lease_expires_at
        .checked_sub(response.started_at)
        .ok_or_else(|| DispatchError::InvalidResponse("start lease underflows".into()))?;
    validate_lease_duration(duration, request.lease_ms)
}

fn validate_resolve_exchange(
    request: &super::ResolveRequest,
    response: &DispatchResponseFacts,
) -> DispatchResult<()> {
    validate_request_schema(&request.schema)?;
    if request.run.as_ref().is_some_and(|run| run != &response.run)
        || request.harness != response.harness
        || request.session_id != response.session_id
        || request
            .lane
            .as_ref()
            .is_some_and(|lane| response.lane.as_ref() != Some(lane))
    {
        return invalid_exchange("identity resolution does not match its request");
    }
    if request
        .agent_id
        .as_ref()
        .is_some_and(|agent_id| response.agent_id.as_deref() != Some(agent_id.as_str()))
        || request
            .agent_type
            .as_ref()
            .is_some_and(|agent_type| response.agent_type.as_ref() != Some(agent_type))
        || request.tool_call_id.as_ref().is_some_and(|tool_call_id| {
            response.tool_call_id.as_deref() != Some(tool_call_id.as_str())
        })
    {
        return invalid_exchange("identity resolution identity does not match its request");
    }
    if let Some(role_carrier) = &request.role_carrier
        && Role::from_carrier(role_carrier)? != response.role
    {
        return invalid_exchange("identity resolution role does not match its request");
    }
    Ok(())
}

fn validate_stop_exchange(
    request: &StopDispatchRequest,
    response: &DispatchRecord,
) -> DispatchResult<()> {
    validate_request_schema(&request.schema)?;
    let expected_revision = request
        .expected_revision
        .checked_add(1)
        .ok_or_else(|| DispatchError::InvalidResponse("stop revision overflows".into()))?;
    if request.run.as_ref().is_some_and(|run| run != &response.run)
        || request.harness != response.harness
        || request.agent_id != response.agent_id
        || request.agent_type != response.agent_type
        || request.lane != response.lane
        || request.session_id != response.session_id
        || response.revision != expected_revision
        || request.result_artifact != response.result_artifact
    {
        return invalid_exchange("stopped record does not match its request");
    }
    if let Some(role_carrier) = &request.role_carrier
        && Role::from_carrier(role_carrier)? != response.role
    {
        return invalid_exchange("stopped record role does not match its request");
    }
    Ok(())
}

fn validate_request_schema(schema: &str) -> DispatchResult<()> {
    if schema == DISPATCH_REQUEST_SCHEMA {
        Ok(())
    } else {
        invalid_exchange("request schema is unsupported")
    }
}

fn validate_lease_duration(duration: i64, lease_ms: u64) -> DispatchResult<()> {
    let lease_ms = i64::try_from(lease_ms).map_err(|_| {
        DispatchError::InvalidResponse("lease exceeds signed timestamp range".into())
    })?;
    if duration == lease_ms {
        Ok(())
    } else {
        invalid_exchange("response lease duration does not match its request")
    }
}

fn invalid_exchange(reason: impl Into<String>) -> DispatchResult<()> {
    Err(DispatchError::InvalidResponse(reason.into()))
}

impl ResumeContextResponse {
    /// Validate the complete resume result before an adapter consumes context.
    pub fn validate(&self) -> DispatchResult<()> {
        if self.schema != RESUME_CONTEXT_SCHEMA {
            return Err(DispatchError::InvalidResponse(self.schema.clone()));
        }
        self.record.validate_loaded()?;
        if self.record.state != DispatchState::Active {
            return Err(DispatchError::InvalidResponse(
                "resume response must contain an active record".into(),
            ));
        }
        self.context.validate_for_resume(
            &self.record.project_id,
            &self.record.run,
            self.record.lane.as_ref(),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mismatched_operation_and_response_is_rejected() {
        let response = NativeLifecycleResponse::BindRoot(RootSessionBinding {
            schema: "shepherd.root-session/1".into(),
            project_id: super::super::ProjectId::new("018f47ce-72d7-7f64-9eb1-2f651d521c2a")
                .expect("fixture project"),
            run: super::super::RunId::new("v645").expect("fixture run"),
            harness: crate::Harness::Codex,
            session_id: super::super::SessionId::new("session-a").expect("fixture session"),
            role: super::super::Role::Shepherd,
            mode: "execution".into(),
            bound_at: 1,
            expires_at: 2,
        });
        assert!(
            response
                .validate_for(NativeLifecycleOperation::Start)
                .is_err()
        );
    }
}
