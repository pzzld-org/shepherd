//! WebAssembly component boundary for the pure Shepherd SDK.

use shepherd::{
    Decision, GuardEngine, GuardError, Harness, Verdict,
    compiler::{self, HarnessProfile as CoreHarnessProfile, Target as CoreTarget},
    dispatch::{
        self, AgentId, AgentType, CapabilityProbe, CapabilityReadiness, CapabilityReport,
        ContextBundle, ContextEntry, DispatchBinding, DispatchError, DispatchPlan, DispatchRecord,
        DispatchRequest, DispatchResponseFacts, DispatchState, NativeEvent,
        NativeLifecycleOperation, NativeLifecycleResponse, RawIdentity, ResumeContextResponse,
        Role, RootSessionBinding, RunId, SessionId,
    },
    guard::{parse_predicate_toml, parse_role_markdown},
};

pub const COMPONENT_CONTRACT_VERSION: &str = "fl03:shepherd@6.4.7";

pub mod bindings {
    wit_bindgen::generate!({
        path: "wit",
        world: "shepherd-core",
    });
}

use bindings::exports::fl03::shepherd::engine as wit;

fn dispatch_error_to_wit(error: DispatchError) -> wit::EngineError {
    let message = error.to_string();
    let code = match &error {
        DispatchError::InvalidIdentifier { .. } => "invalid-identifier",
        DispatchError::InvalidCapability(_) | DispatchError::CapabilityBlocked => "capability",
        DispatchError::InvalidEvent(_) => "invalid-event",
        DispatchError::InvalidResponse(_) => "invalid-response",
        DispatchError::AgentTypeRoleMismatch { .. } => "identity-mismatch",
        DispatchError::HarnessLimit { .. } => "harness-limit",
        DispatchError::InvalidRole(_) => "invalid-role",
        DispatchError::InvalidParent(_) => "invalid-parent",
        DispatchError::ReusedResumeIdentity => "resume-identity",
        _ => "dispatch",
    };
    wit::EngineError {
        code: code.into(),
        message,
    }
}

fn content_error_to_wit(error: compiler::content::ContentError) -> wit::EngineError {
    let code = match &error {
        compiler::content::ContentError::Io { .. } => "content-io",
        compiler::content::ContentError::InvalidFrontmatter { .. } => "content-frontmatter",
        compiler::content::ContentError::InvalidMetadata { .. } => "content-metadata",
        compiler::content::ContentError::InvalidSource { .. } => "content-source",
    };
    wit::EngineError {
        code: code.into(),
        message: error.to_string(),
    }
}

fn compile_error_to_wit(error: compiler::CompileError) -> wit::EngineError {
    let code = match error {
        compiler::CompileError::Invalid(_) => "compile-invalid",
        compiler::CompileError::Budget(_) => "compile-budget",
    };
    wit::EngineError {
        code: code.into(),
        message: error.to_string(),
    }
}

fn harness_from_wit(target: wit::Target) -> Harness {
    match target {
        wit::Target::Claude => Harness::ClaudeCode,
        wit::Target::Codex => Harness::Codex,
        wit::Target::Pi => Harness::Pi,
    }
}

fn target_from_harness(harness: Harness) -> wit::Target {
    match harness {
        Harness::ClaudeCode => wit::Target::Claude,
        Harness::Codex => wit::Target::Codex,
        _ => wit::Target::Pi,
    }
}

fn event_from_wit(event: wit::NativeEvent) -> Result<NativeEvent, DispatchError> {
    Ok(match event {
        wit::NativeEvent::SessionStart => NativeEvent::SessionStart,
        wit::NativeEvent::SubagentStart => NativeEvent::SubagentStart,
        wit::NativeEvent::SubagentResume => NativeEvent::SubagentResume,
        wit::NativeEvent::SubagentStop => NativeEvent::SubagentStop,
        wit::NativeEvent::PreToolUse => NativeEvent::PreToolUse,
        wit::NativeEvent::PostToolUse => NativeEvent::PostToolUse,
        wit::NativeEvent::OtherEvent(value) => NativeEvent::parse(value)?,
    })
}

fn event_to_wit(event: NativeEvent) -> wit::NativeEvent {
    match event {
        NativeEvent::SessionStart => wit::NativeEvent::SessionStart,
        NativeEvent::SubagentStart => wit::NativeEvent::SubagentStart,
        NativeEvent::SubagentResume => wit::NativeEvent::SubagentResume,
        NativeEvent::SubagentStop => wit::NativeEvent::SubagentStop,
        NativeEvent::PreToolUse => wit::NativeEvent::PreToolUse,
        NativeEvent::PostToolUse => wit::NativeEvent::PostToolUse,
        NativeEvent::Other(value) => wit::NativeEvent::OtherEvent(value),
    }
}

fn normalized_identity_to_wit(
    identity: shepherd::dispatch::NormalizedIdentity,
) -> wit::NormalizedIdentity {
    let identity_key = identity.identity_key();
    wit::NormalizedIdentity {
        harness: target_from_harness(identity.harness),
        event: event_to_wit(identity.event),
        session_id: identity.session_id.to_string(),
        agent_id: identity.agent_id.map(|value| value.to_string()),
        agent_type: identity.agent_type.map(|value| value.to_string()),
        role_carrier: identity.role_carrier,
        tool_use_id: identity.tool_call_id.map(|value| value.to_string()),
        model: identity.model,
        provider_version: identity.provider_version,
        identity_key,
    }
}

fn normalized_identity_from_wit(
    identity: wit::NormalizedIdentity,
) -> Result<shepherd::dispatch::NormalizedIdentity, DispatchError> {
    let session_id = SessionId::new(identity.session_id)?;
    let agent_id = identity.agent_id.map(AgentId::new).transpose()?;
    let agent_type = identity.agent_type.map(AgentType::new).transpose()?;
    let tool_call_id = identity.tool_use_id.map(SessionId::new).transpose()?;
    if agent_id.is_some() != agent_type.is_some() {
        return Err(DispatchError::InvalidRecord(
            "partial agent identity".into(),
        ));
    }
    let normalized = shepherd::dispatch::NormalizedIdentity {
        harness: harness_from_wit(identity.harness),
        event: event_from_wit(identity.event)?,
        session_id,
        agent_id,
        agent_type,
        role_carrier: identity.role_carrier,
        tool_call_id,
        model: identity.model,
        provider_version: identity.provider_version,
    };
    if normalized.identity_key() != identity.identity_key {
        return Err(DispatchError::InvalidRecord("identity key mismatch".into()));
    }
    Ok(normalized)
}

fn role_from_string(value: &str) -> Result<Role, DispatchError> {
    Role::from_carrier(value).or_else(|_| Role::from_name(value))
}

fn optional_run(value: Option<String>) -> Result<Option<RunId>, DispatchError> {
    value.map(RunId::new).transpose()
}

fn optional_lane(
    value: Option<String>,
) -> Result<Option<shepherd::dispatch::LaneId>, DispatchError> {
    value.map(shepherd::dispatch::LaneId::new).transpose()
}

fn tool_input_to_json(input: Option<wit::ToolInput>) -> Option<serde_json::Value> {
    input.map(|input| {
        let mut object = serde_json::Map::new();
        if let Some(value) = input.command {
            object.insert("command".into(), value.into());
        }
        if let Some(value) = input.target_role {
            object.insert("target_role".into(), value.into());
        }
        if let Some(value) = input.path {
            object.insert("path".into(), value.into());
        }
        if let Some(value) = input.operation {
            object.insert("operation".into(), value.into());
        }
        serde_json::Value::Object(object)
    })
}

fn tool_input_from_json(input: Option<serde_json::Value>) -> Option<wit::ToolInput> {
    let serde_json::Value::Object(object) = input? else {
        return None;
    };
    let string = |key: &str| {
        object
            .get(key)
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned)
    };
    Some(wit::ToolInput {
        command: string("command"),
        target_role: string("target_role"),
        path: string("path"),
        operation: string("operation"),
    })
}

fn binding_from_wit(input: wit::DispatchBinding) -> Result<DispatchBinding, DispatchError> {
    let role = input.role.as_deref().map(role_from_string).transpose()?;
    let mut binding = DispatchBinding::new(
        optional_run(input.run)?,
        role,
        optional_lane(input.lane)?,
        input.parent_agent_id.map(AgentId::new).transpose()?,
        input.write_scope,
        input.model,
        input.observed_capabilities,
        input.capability_source,
        input.harness_version,
        input.provider_version.as_deref(),
        input.lease_ms,
    )?;
    if input.expected_revision == 0 {
        return Err(DispatchError::InvalidRecord(
            "expected revision must be positive".into(),
        ));
    }
    binding.expected_revision = input.expected_revision;
    binding.result_artifact = input.result_artifact;
    binding.source_agent_id = input.source_agent_id.map(AgentId::new).transpose()?;
    if input.mode.is_empty() || input.mode.len() > 64 || input.mode.chars().any(char::is_control) {
        return Err(DispatchError::InvalidRecord("invalid root mode".into()));
    }
    binding.mode = input.mode;
    binding.tool_name = input.tool_name;
    binding.tool_input = tool_input_to_json(input.tool_input);
    Ok(binding)
}

fn capability_report_to_wit(report: CapabilityReport) -> wit::CapabilityReport {
    let readiness = match report.readiness() {
        CapabilityReadiness::Ready => wit::CapabilityReadiness::Ready,
        CapabilityReadiness::Degraded => wit::CapabilityReadiness::Degraded,
        CapabilityReadiness::Blocked => wit::CapabilityReadiness::Blocked,
    };
    wit::CapabilityReport {
        declared: report.declared.into_iter().collect(),
        observed: report.observed.into_iter().collect(),
        present: report.present.into_iter().collect(),
        missing: report.missing.into_iter().collect(),
        missing_required: report.missing_required.into_iter().collect(),
        missing_optional: report.missing_optional.into_iter().collect(),
        extra: report.extra.into_iter().collect(),
        forbidden_extra: report.forbidden_extra.into_iter().collect(),
        source: report.source,
        harness_version: report.harness_version,
        provider_version: report.provider_version,
        probed_at: report.probed_at,
        readiness,
    }
}

fn capability_report_from_wit(report: wit::CapabilityReport) -> CapabilityReport {
    CapabilityReport {
        declared: report.declared.into_iter().collect(),
        observed: report.observed.into_iter().collect(),
        present: report.present.into_iter().collect(),
        missing: report.missing.into_iter().collect(),
        missing_required: report.missing_required.into_iter().collect(),
        missing_optional: report.missing_optional.into_iter().collect(),
        extra: report.extra.into_iter().collect(),
        forbidden_extra: report.forbidden_extra.into_iter().collect(),
        source: report.source,
        harness_version: report.harness_version,
        provider_version: report.provider_version,
        probed_at: report.probed_at,
    }
}

fn dispatch_request_to_wit(request: DispatchRequest) -> wit::DispatchRequest {
    match request {
        DispatchRequest::BindRoot(value) => wit::DispatchRequest::BindRoot(wit::BindRootRequest {
            run: value.run.map(|value| value.to_string()),
            harness: target_from_harness(value.harness),
            session_id: value.session_id.to_string(),
            role_carrier: value.role_carrier,
            mode: value.mode,
            lease_ms: value.lease_ms,
        }),
        DispatchRequest::Start(value) => wit::DispatchRequest::Start(wit::StartRequest {
            run: value.run.map(|value| value.to_string()),
            harness: target_from_harness(value.harness),
            agent_id: value.agent_id.to_string(),
            agent_type: value.agent_type.to_string(),
            role_carrier: value.role_carrier,
            lane: value.lane.map(|value| value.to_string()),
            parent_agent_id: value.parent_agent_id.map(|value| value.to_string()),
            session_id: value.session_id.to_string(),
            write_scope: value.write_scope,
            model: value.model,
            observed_capabilities: value.observed_capabilities.into_iter().collect(),
            capability_source: value.capability_source,
            harness_version: value.harness_version,
            provider_version: value.provider_version,
            lease_ms: value.lease_ms,
        }),
        DispatchRequest::Resolve(value) => wit::DispatchRequest::Resolve(wit::ResolveRequest {
            run: value.run.map(|value| value.to_string()),
            harness: target_from_harness(value.harness),
            agent_id: value.agent_id.map(|value| value.to_string()),
            agent_type: value.agent_type.map(|value| value.to_string()),
            role_carrier: value.role_carrier,
            lane: value.lane.map(|value| value.to_string()),
            session_id: value.session_id.to_string(),
            tool_use_id: value.tool_call_id.map(|value| value.to_string()),
            tool_name: value.tool_name,
            tool_input: tool_input_from_json(value.tool_input),
        }),
        DispatchRequest::Stop(value) => wit::DispatchRequest::Stop(wit::StopRequest {
            run: value.run.map(|value| value.to_string()),
            harness: target_from_harness(value.harness),
            agent_id: value.agent_id.to_string(),
            agent_type: value.agent_type.to_string(),
            role_carrier: value.role_carrier,
            lane: value.lane.map(|value| value.to_string()),
            session_id: value.session_id.to_string(),
            expected_revision: value.expected_revision,
            result_artifact: value.result_artifact,
        }),
        DispatchRequest::Resume(value) => wit::DispatchRequest::Resume(wit::ResumeRequest {
            source_agent_id: value.source_agent_id.to_string(),
            next: match dispatch_request_to_wit(DispatchRequest::Start(value.next)) {
                wit::DispatchRequest::Start(next) => next,
                _ => unreachable!(),
            },
        }),
    }
}

fn start_request_from_wit(
    input: wit::StartRequest,
) -> Result<dispatch::StartRequest, DispatchError> {
    Ok(dispatch::StartRequest {
        schema: dispatch::DISPATCH_REQUEST_SCHEMA.into(),
        run: optional_run(input.run)?,
        harness: harness_from_wit(input.harness),
        agent_id: AgentId::new(input.agent_id)?,
        agent_type: AgentType::new(input.agent_type)?,
        role_carrier: input.role_carrier,
        lane: optional_lane(input.lane)?,
        parent_agent_id: input.parent_agent_id.map(AgentId::new).transpose()?,
        session_id: SessionId::new(input.session_id)?,
        write_scope: input.write_scope,
        model: input.model,
        observed_capabilities: input.observed_capabilities.into_iter().collect(),
        capability_source: input.capability_source,
        harness_version: input.harness_version,
        provider_version: input.provider_version,
        lease_ms: input.lease_ms,
    })
}

fn dispatch_request_from_wit(
    input: wit::DispatchRequest,
) -> Result<DispatchRequest, DispatchError> {
    match input {
        wit::DispatchRequest::BindRoot(input) => {
            Ok(DispatchRequest::BindRoot(dispatch::BindRootRequest {
                schema: dispatch::DISPATCH_REQUEST_SCHEMA.into(),
                run: optional_run(input.run)?,
                harness: harness_from_wit(input.harness),
                session_id: SessionId::new(input.session_id)?,
                role_carrier: input.role_carrier,
                mode: input.mode,
                lease_ms: input.lease_ms,
            }))
        }
        wit::DispatchRequest::Start(input) => {
            start_request_from_wit(input).map(DispatchRequest::Start)
        }
        wit::DispatchRequest::Resolve(input) => {
            Ok(DispatchRequest::Resolve(dispatch::ResolveRequest {
                schema: dispatch::DISPATCH_REQUEST_SCHEMA.into(),
                run: optional_run(input.run)?,
                harness: harness_from_wit(input.harness),
                agent_id: input.agent_id.map(AgentId::new).transpose()?,
                agent_type: input.agent_type.map(AgentType::new).transpose()?,
                role_carrier: input.role_carrier,
                lane: optional_lane(input.lane)?,
                session_id: SessionId::new(input.session_id)?,
                tool_call_id: input.tool_use_id.map(SessionId::new).transpose()?,
                tool_name: input.tool_name,
                tool_input: tool_input_to_json(input.tool_input),
            }))
        }
        wit::DispatchRequest::Stop(input) => {
            Ok(DispatchRequest::Stop(dispatch::StopDispatchRequest {
                schema: dispatch::DISPATCH_REQUEST_SCHEMA.into(),
                run: optional_run(input.run)?,
                harness: harness_from_wit(input.harness),
                agent_id: AgentId::new(input.agent_id)?,
                agent_type: AgentType::new(input.agent_type)?,
                role_carrier: input.role_carrier,
                lane: optional_lane(input.lane)?,
                session_id: SessionId::new(input.session_id)?,
                expected_revision: input.expected_revision,
                result_artifact: input.result_artifact,
            }))
        }
        wit::DispatchRequest::Resume(input) => {
            Ok(DispatchRequest::Resume(dispatch::ResumeRequest {
                schema: dispatch::DISPATCH_REQUEST_SCHEMA.into(),
                source_agent_id: AgentId::new(input.source_agent_id)?,
                next: start_request_from_wit(input.next)?,
            }))
        }
    }
}

fn dispatch_plan_to_wit(plan: DispatchPlan) -> wit::DispatchPlan {
    match plan {
        DispatchPlan::Request(request) => {
            wit::DispatchPlan::Request(dispatch_request_to_wit(request))
        }
        DispatchPlan::Ignored => wit::DispatchPlan::Ignored,
        DispatchPlan::Blocked(error) => wit::DispatchPlan::Blocked(dispatch_error_to_wit(error)),
    }
}

fn response_from_wit(input: wit::ResponseFacts) -> Result<DispatchResponseFacts, DispatchError> {
    Ok(DispatchResponseFacts {
        schema: input.schema,
        project_id: shepherd::dispatch::ProjectId::new(input.project_id)?,
        run: RunId::new(input.run)?,
        harness: harness_from_wit(input.harness),
        agent_id: input.agent_id,
        agent_type: input.agent_type.map(AgentType::new).transpose()?,
        role: role_from_string(&input.role)?,
        lane: optional_lane(input.lane)?,
        session_id: SessionId::new(input.session_id)?,
        write_scope: input.write_scope,
        capabilities: input.capabilities.map(capability_report_from_wit),
        tool_call_id: input.tool_use_id,
        mode: input.mode,
        write_paths: input.write_paths,
        path_in_write_scope: input.path_in_write_scope,
    })
}

fn dispatch_state_from_wit(state: wit::DispatchState) -> DispatchState {
    match state {
        wit::DispatchState::Active => DispatchState::Active,
        wit::DispatchState::CapabilityBlocked => DispatchState::CapabilityBlocked,
        wit::DispatchState::Stopped => DispatchState::Stopped,
    }
}

fn root_binding_from_wit(
    input: wit::RootSessionBinding,
) -> Result<RootSessionBinding, DispatchError> {
    Ok(RootSessionBinding {
        schema: input.schema,
        project_id: shepherd::dispatch::ProjectId::new(input.project_id)?,
        run: RunId::new(input.run)?,
        harness: harness_from_wit(input.harness),
        session_id: SessionId::new(input.session_id)?,
        role: role_from_string(&input.role)?,
        mode: input.mode,
        bound_at: input.bound_at,
        expires_at: input.expires_at,
    })
}

fn dispatch_record_from_wit(input: wit::DispatchRecord) -> Result<DispatchRecord, DispatchError> {
    Ok(DispatchRecord {
        schema: input.schema,
        revision: input.revision,
        project_id: shepherd::dispatch::ProjectId::new(input.project_id)?,
        run: RunId::new(input.run)?,
        harness: harness_from_wit(input.harness),
        agent_id: AgentId::new(input.agent_id)?,
        agent_type: AgentType::new(input.agent_type)?,
        role: role_from_string(&input.role)?,
        lane: optional_lane(input.lane)?,
        parent_agent_id: input.parent_agent_id.map(AgentId::new).transpose()?,
        session_id: SessionId::new(input.session_id)?,
        write_scope: input.write_scope,
        model: input.model,
        capabilities: capability_report_from_wit(input.capabilities),
        state: dispatch_state_from_wit(input.state),
        started_at: input.started_at,
        lease_expires_at: input.lease_expires_at,
        stopped_at: input.stopped_at,
        result_artifact: input.result_artifact,
        resumes_agent_id: input.resumes_agent_id.map(AgentId::new).transpose()?,
    })
}

fn usize_from_wit(value: u64, field: &'static str) -> Result<usize, DispatchError> {
    usize::try_from(value).map_err(|_| {
        DispatchError::InvalidResponse(format!("{field} exceeds the component target usize"))
    })
}

fn context_entry_from_wit(input: wit::ContextEntry) -> Result<ContextEntry, DispatchError> {
    Ok(ContextEntry {
        id: AgentId::new(input.id)?,
        project_id: shepherd::dispatch::ProjectId::new(input.project_id)?,
        run: RunId::new(input.run)?,
        lane: optional_lane(input.lane)?,
        provenance: input.provenance,
        freshness: input.freshness,
        words: usize_from_wit(input.words, "context entry words")?,
        tokens: usize_from_wit(input.tokens, "context entry tokens")?,
        priority: input.priority,
        content: input.content,
    })
}

fn context_bundle_from_wit(input: wit::ContextBundle) -> Result<ContextBundle, DispatchError> {
    Ok(ContextBundle {
        entries: input
            .entries
            .into_iter()
            .map(context_entry_from_wit)
            .collect::<Result<Vec<_>, _>>()?,
        words: usize_from_wit(input.words, "context bundle words")?,
        tokens: usize_from_wit(input.tokens, "context bundle tokens")?,
    })
}

fn lifecycle_operation_from_wit(
    operation: wit::NativeLifecycleOperation,
) -> NativeLifecycleOperation {
    match operation {
        wit::NativeLifecycleOperation::BindRoot => NativeLifecycleOperation::BindRoot,
        wit::NativeLifecycleOperation::Start => NativeLifecycleOperation::Start,
        wit::NativeLifecycleOperation::Resolve => NativeLifecycleOperation::Resolve,
        wit::NativeLifecycleOperation::Stop => NativeLifecycleOperation::Stop,
        wit::NativeLifecycleOperation::Resume => NativeLifecycleOperation::Resume,
    }
}

fn lifecycle_response_from_wit(
    response: wit::NativeLifecycleResponse,
) -> Result<NativeLifecycleResponse, DispatchError> {
    match response {
        wit::NativeLifecycleResponse::BindRoot(binding) => {
            root_binding_from_wit(binding).map(NativeLifecycleResponse::BindRoot)
        }
        wit::NativeLifecycleResponse::Start(record) => {
            dispatch_record_from_wit(record).map(NativeLifecycleResponse::Start)
        }
        wit::NativeLifecycleResponse::Resolve(response) => {
            response_from_wit(response).map(NativeLifecycleResponse::Resolve)
        }
        wit::NativeLifecycleResponse::Stop(record) => {
            dispatch_record_from_wit(record).map(NativeLifecycleResponse::Stop)
        }
        wit::NativeLifecycleResponse::Resume(response) => {
            let record = dispatch_record_from_wit(response.dispatch_record)?;
            let context = context_bundle_from_wit(response.context)?;
            Ok(NativeLifecycleResponse::Resume(ResumeContextResponse {
                schema: response.schema,
                record,
                context,
            }))
        }
    }
}

#[doc(hidden)]
pub struct Component;

impl wit::Guest for Component {
    fn canonical_profile(target: wit::Target) -> wit::HarnessProfile {
        profile_to_wit(canonical_profile(target))
    }

    fn compile_canonical(target: wit::Target) -> Result<wit::EmittedTree, wit::EngineError> {
        let input = compiler::content::embedded_compile_input().map_err(content_error_to_wit)?;
        let profile = canonical_profile(target);
        let tree = compiler::compile(&input, &profile).map_err(compile_error_to_wit)?;
        Ok(tree_to_wit(tree))
    }

    fn measure(text: String) -> wit::Measurement {
        measurement_to_wit(compiler::measure_text(&text))
    }

    fn guard_eval_canonical(request_json: String) -> Result<wit::GuardVerdict, wit::EngineError> {
        evaluate_canonical_guard(&request_json)
    }

    fn normalize_identity(
        input: wit::IdentityInput,
    ) -> Result<wit::NormalizedIdentity, wit::EngineError> {
        let raw = RawIdentity {
            harness: harness_from_wit(input.harness),
            event: event_from_wit(input.event).map_err(dispatch_error_to_wit)?,
            session_id: input.session_id,
            agent_id: input.agent_id,
            agent_type: input.agent_type,
            tool_call_id: input.tool_use_id,
            model: input.model,
            provider_version: input.provider_version,
        };
        raw.normalize()
            .map(normalized_identity_to_wit)
            .map_err(dispatch_error_to_wit)
    }

    fn plan_lifecycle(
        identity: wit::NormalizedIdentity,
        binding: Option<wit::DispatchBinding>,
    ) -> Result<wit::DispatchPlan, wit::EngineError> {
        let identity = normalized_identity_from_wit(identity).map_err(dispatch_error_to_wit)?;
        let binding = binding
            .map(binding_from_wit)
            .transpose()
            .map_err(dispatch_error_to_wit)?;
        dispatch::plan_lifecycle(&identity, binding.as_ref())
            .map(dispatch_plan_to_wit)
            .map_err(dispatch_error_to_wit)
    }

    fn validate_response(response: wit::ResponseFacts) -> Result<(), wit::EngineError> {
        response_from_wit(response)
            .and_then(|response| response.validate())
            .map_err(dispatch_error_to_wit)
    }

    fn validate_native_response(
        operation: wit::NativeLifecycleOperation,
        response: wit::NativeLifecycleResponse,
    ) -> Result<(), wit::EngineError> {
        lifecycle_response_from_wit(response)
            .and_then(|response| response.validate_for(lifecycle_operation_from_wit(operation)))
            .map_err(dispatch_error_to_wit)
    }

    fn validate_native_exchange(
        request: wit::DispatchRequest,
        response: wit::NativeLifecycleResponse,
    ) -> Result<(), wit::EngineError> {
        let request = dispatch_request_from_wit(request).map_err(dispatch_error_to_wit)?;
        let response = lifecycle_response_from_wit(response).map_err(dispatch_error_to_wit)?;
        dispatch::validate_native_exchange(&request, &response).map_err(dispatch_error_to_wit)
    }

    fn evaluate_provider(
        role: String,
        probe: wit::CapabilityProbe,
    ) -> Result<wit::CapabilityReport, wit::EngineError> {
        let role = role_from_string(&role).map_err(dispatch_error_to_wit)?;
        let probe = CapabilityProbe::new(
            probe.observed,
            probe.source,
            probe.harness_version,
            probe.provider_version.as_deref(),
            0,
        )
        .map_err(dispatch_error_to_wit)?;
        role.dispatch_capability_contract()
            .map(|contract| contract.evaluate(probe))
            .map(capability_report_to_wit)
            .map_err(dispatch_error_to_wit)
    }
}

#[cfg(target_arch = "wasm32")]
#[allow(unsafe_code)]
mod component_exports {
    // `wit-bindgen` owns the component ABI shims. The handwritten
    // implementation remains safe Rust; this narrow exception covers
    // generated export-name, pointer-lifting, and lowering code.
    use super::{Component, bindings};

    bindings::export!(Component with_types_in bindings);
}

fn canonical_profile(target: wit::Target) -> CoreHarnessProfile {
    match target {
        wit::Target::Claude => CoreHarnessProfile::claude(),
        wit::Target::Codex => CoreHarnessProfile::codex(),
        wit::Target::Pi => CoreHarnessProfile::pi(),
    }
}

fn profile_to_wit(profile: CoreHarnessProfile) -> wit::HarnessProfile {
    wit::HarnessProfile {
        target: target_to_wit(profile.target),
        max_concurrent_children: u32::try_from(profile.max_concurrent_children).unwrap_or(u32::MAX),
        tools_by_capability: profile
            .tools_by_capability
            .into_iter()
            .map(|(capability, tools)| wit::CapabilityTools { capability, tools })
            .collect(),
        unsupported_capabilities: profile.unsupported_capabilities.into_iter().collect(),
        model_by_hint: profile
            .model_by_hint
            .into_iter()
            .map(|(hint, resolution)| wit::ModelResolution {
                hint,
                model: resolution.model,
                profile: resolution.profile,
                reasoning_effort: resolution.reasoning_effort,
            })
            .collect(),
    }
}

fn tree_to_wit(tree: compiler::EmittedTree) -> wit::EmittedTree {
    wit::EmittedTree {
        target: target_to_wit(tree.target),
        roles: tree
            .roles
            .into_iter()
            .map(|role| wit::EmittedRole {
                role: role.role,
                carrier_path: role.carrier_path,
                description: role.description,
                model: role.model,
                profile: role.profile,
                reasoning_effort: role.reasoning_effort,
                tools: role.tools,
                unsupported_capabilities: role.unsupported_capabilities,
                capabilities: role.capabilities,
                write_eligible: role.write_eligible,
                dispatchable: role.dispatchable,
                write_scope: role.write_scope,
            })
            .collect(),
        files: tree
            .files
            .into_iter()
            .map(|file| wit::EmittedFile {
                path: file.path,
                kind: match file.kind {
                    compiler::EmittedKind::Role => wit::EmittedKind::Role,
                    compiler::EmittedKind::Skill => wit::EmittedKind::Skill,
                    compiler::EmittedKind::Config => wit::EmittedKind::Config,
                },
                content: file.content,
                source_path: file.source_path,
                source_sha256: file.source_sha256,
                content_sha256: file.content_sha256,
                measurement: measurement_to_wit(file.measurement),
            })
            .collect(),
        digest: tree.digest,
        tokenizer_version: tree.tokenizer_version.into(),
    }
}

fn evaluate_canonical_guard(request_json: &str) -> Result<wit::GuardVerdict, wit::EngineError> {
    let engine = canonical_guard_engine()?;
    let verdict = engine
        .evaluate_json(request_json)
        .map_err(engine_error_to_wit)?;
    Ok(verdict_to_wit(verdict))
}

fn canonical_guard_engine() -> Result<GuardEngine, wit::EngineError> {
    let (predicate_sources, role_sources) = compiler::content::embedded_guard_sources();
    let predicates = predicate_sources
        .iter()
        .map(|(name, content)| parse_predicate_toml(name, content).map_err(engine_error_to_wit))
        .collect::<Result<Vec<_>, _>>()?;
    let roles = role_sources
        .iter()
        .map(|(name, content)| parse_role_markdown(name, content).map_err(engine_error_to_wit))
        .collect::<Result<Vec<_>, _>>()?;
    GuardEngine::new(predicates, roles).map_err(engine_error_to_wit)
}

fn engine_error_to_wit(error: GuardError) -> wit::EngineError {
    let message = error.to_string();
    let code = match &error {
        GuardError::Input(_) => "input",
        GuardError::Predicate(_) => "predicate",
        GuardError::Role(_) => "role",
        GuardError::Io(_) => "io",
        GuardError::Json(_) => "json",
        _ => "engine",
    };
    wit::EngineError {
        code: code.into(),
        message,
    }
}

fn verdict_to_wit(verdict: Verdict) -> wit::GuardVerdict {
    match verdict.decision {
        Decision::Allow => wit::GuardVerdict::Allow,
        Decision::Deny => wit::GuardVerdict::Deny(wit::GuardDeny {
            predicate: verdict.predicate.unwrap_or_default(),
            rule: verdict.rule.unwrap_or_default(),
            halt_code: verdict.halt_code,
            reason: verdict.reason.unwrap_or_default(),
        }),
        Decision::Unresolved => wit::GuardVerdict::Unresolved(wit::GuardUnresolved {
            reason: verdict.reason.unwrap_or_default(),
            missing: verdict.missing,
        }),
    }
}

fn measurement_to_wit(measurement: compiler::Measurement) -> wit::Measurement {
    wit::Measurement {
        lines: u64::try_from(measurement.lines).unwrap_or(u64::MAX),
        words: u64::try_from(measurement.words).unwrap_or(u64::MAX),
        utf8_bytes: u64::try_from(measurement.utf8_bytes).unwrap_or(u64::MAX),
        prompt_tokens: u64::try_from(measurement.prompt_tokens).unwrap_or(u64::MAX),
    }
}

fn target_to_wit(target: CoreTarget) -> wit::Target {
    match target {
        CoreTarget::Claude => wit::Target::Claude,
        CoreTarget::Codex => wit::Target::Codex,
        CoreTarget::Pi => wit::Target::Pi,
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::*;

    #[test]
    fn capability_report_wit_conversion_preserves_persisted_probe_time() {
        let contract = Role::Coder
            .dispatch_capability_contract()
            .expect("fixture capability contract");
        let observed = contract
            .required
            .union(&contract.optional)
            .cloned()
            .collect::<BTreeSet<_>>();
        let report = contract.evaluate(
            CapabilityProbe::new(observed, "native-probe", "1.0", Some("provider-1"), 42)
                .expect("fixture probe"),
        );

        let converted = capability_report_from_wit(capability_report_to_wit(report.clone()));
        assert_eq!(converted.probed_at, 42);
        assert_eq!(converted, report);
    }
}
