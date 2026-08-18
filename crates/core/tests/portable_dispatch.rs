use shepherd_core::{Harness, dispatch::*};
use std::collections::BTreeSet;

fn identity(
    harness: Harness,
    event: &str,
    agent_id: Option<&str>,
    agent_type: Option<&str>,
) -> RawIdentity {
    RawIdentity::new(
        harness,
        event,
        "session-1",
        agent_id,
        agent_type,
        Some("tool-call-1"),
        Some("model-1"),
        Some("provider-1"),
    )
}

fn binding() -> DispatchBinding {
    DispatchBinding::new(
        Some(RunId::new("v645").expect("run")),
        Some(Role::Coder),
        Some(LaneId::new("l1-engine").expect("lane")),
        None,
        vec!["crates/core/src/dispatch/**".into()],
        Some("model-1".into()),
        [
            "read",
            "search",
            "shell",
            "skill-load",
            "write",
            "subagent-provider",
        ],
        "native-probe",
        "1.0.0",
        Some("provider-1"),
        60_000,
    )
    .expect("binding")
}

#[test]
fn claude_codex_and_pi_fixtures_share_identity_facts_and_tool_ids_are_audit_only() {
    let fixtures = [
        (Harness::ClaudeCode, "coder", "agent-claude"),
        (Harness::Codex, "shepherd:coder", "agent-codex"),
        (Harness::Pi, "pi-subagents:worker", "agent-pi"),
    ];
    for (harness, agent_type, agent_id) in fixtures {
        let normalized = identity(harness, "PreToolUse", Some(agent_id), Some(agent_type))
            .normalize()
            .expect("fixture identity");
        assert_eq!(normalized.session_id().as_str(), "session-1");
        assert_eq!(normalized.agent_id().map(AgentId::as_str), Some(agent_id));
        assert_eq!(normalized.tool_call_id(), Some("tool-call-1"));
        let harness_name = match harness {
            Harness::ClaudeCode => "claude",
            Harness::Codex => "codex",
            Harness::Pi => "pi",
            Harness::PrimeAgent => "prime_agent",
            _ => "unknown",
        };
        assert_eq!(
            normalized.identity_key(),
            format!("{harness_name}\0session-1\0{agent_id}")
        );
    }

    let first = identity(
        Harness::ClaudeCode,
        "PreToolUse",
        Some("agent-1"),
        Some("coder"),
    )
    .normalize()
    .expect("first identity");
    let second = RawIdentity::new(
        Harness::ClaudeCode,
        "PreToolUse",
        "session-1",
        Some("agent-1"),
        Some("coder"),
        Some("different-tool"),
        None,
        None,
    )
    .normalize()
    .expect("second identity");
    assert_eq!(first.identity_key(), second.identity_key());
    assert_ne!(first.tool_call_id(), second.tool_call_id());
}

#[test]
fn identity_normalization_rejects_unsafe_or_partial_ids_and_infers_root_role() {
    for bad in ["../escape", ".", "", "a/b", "a\\b"] {
        let result = RawIdentity::new(
            Harness::Codex,
            "SubagentStart",
            bad,
            Some("agent-1"),
            Some("shepherd:coder"),
            None,
            None,
            None,
        )
        .normalize();
        assert!(result.is_err(), "unsafe session {bad:?} accepted");
    }
    assert!(
        RawIdentity::new(
            Harness::ClaudeCode,
            "SubagentStart",
            "session-1",
            Some("agent-1"),
            None,
            None,
            None,
            None,
        )
        .normalize()
        .is_err()
    );

    let root = RawIdentity::new(
        Harness::ClaudeCode,
        "SessionStart",
        "session-1",
        None,
        None,
        None,
        None,
        None,
    )
    .normalize()
    .expect("root identity");
    assert_eq!(root.role_carrier(), None);
    assert_eq!(root.root_role(), Role::Shepherd);

    let inferred = identity(
        Harness::ClaudeCode,
        "SubagentStart",
        Some("agent-1"),
        Some("coder"),
    )
    .normalize()
    .expect("inferred role");
    assert_eq!(inferred.role_carrier(), Some("shepherd:coder"));
    assert_eq!(inferred.semantic_role().expect("role"), Role::Coder);
}

#[test]
fn lifecycle_planning_selects_native_operations_and_blocks_missing_bindings() {
    let root = identity(Harness::ClaudeCode, "SessionStart", None, None)
        .normalize()
        .expect("root");
    let root_plan = plan_lifecycle(&root, None).expect("root plan");
    assert_eq!(root_plan.operation(), DispatchOperation::BindRoot);
    assert_eq!(root_plan.request().expect("request").to_json_bytes().expect("json"), br#"{"schema":"shepherd.dispatch-request/1","run":null,"harness":"claude","session_id":"session-1","role_carrier":"shepherd:shepherd","mode":"execution","lease_ms":86400000}"#);

    let child = identity(
        Harness::Codex,
        "SubagentStart",
        Some("agent-1"),
        Some("shepherd:coder"),
    )
    .normalize()
    .expect("child");
    let blocked = plan_lifecycle(&child, None).expect("blocked plan");
    assert_eq!(
        blocked,
        DispatchPlan::Blocked(DispatchError::MissingBinding)
    );
    let start = plan_lifecycle(&child, Some(&binding())).expect("start plan");
    assert_eq!(start.operation(), DispatchOperation::Start);

    let resolve = child.with_event(NativeEvent::PreToolUse).expect("event");
    let resolve = plan_lifecycle(&resolve, Some(&binding())).expect("resolve");
    assert_eq!(resolve.operation(), DispatchOperation::Resolve);

    let stop = child.with_event(NativeEvent::SubagentStop).expect("event");
    let stop = plan_lifecycle(&stop, Some(&binding())).expect("stop");
    assert_eq!(stop.operation(), DispatchOperation::Stop);

    let mut resume_binding = binding();
    resume_binding.source_agent_id = Some(AgentId::new("source-agent").expect("source"));
    let resumed = child
        .with_event(NativeEvent::SubagentResume)
        .expect("event");
    let resumed = plan_lifecycle(&resumed, Some(&resume_binding)).expect("resume");
    assert_eq!(resumed.operation(), DispatchOperation::Resume);
    assert_eq!(resumed.operation().as_str(), "resume");
}

#[test]
fn requests_are_canonical_snake_case_and_validate_parent_capability_and_resume_facts() {
    let child = identity(
        Harness::ClaudeCode,
        "SubagentStart",
        Some("agent-1"),
        Some("shepherd:coder"),
    )
    .normalize()
    .expect("child");
    let mut facts = binding();
    let request = build_start_request(&child, &facts).expect("start request");
    let bytes = request.to_json_bytes().expect("request JSON");
    let text = String::from_utf8(bytes).expect("utf8");
    assert!(text.contains("\"agent_id\":\"agent-1\""));
    assert!(text.contains("\"parent_agent_id\":null"));
    assert!(!text.contains("agentId"));

    facts.parent_agent_id = Some(AgentId::new("agent-1").expect("parent"));
    assert!(build_start_request(&child, &facts).is_err());

    facts.parent_agent_id = None;
    facts.observed_capabilities = BTreeSet::from(["read".into()]);
    assert!(matches!(
        validate_provider_binding(Role::Coder, &facts),
        Err(DispatchError::CapabilityBlocked)
    ));

    let source = AgentId::new("source-agent").expect("source");
    let resume = build_resume_request(source, request).expect("resume");
    assert_eq!(resume.operation(), DispatchOperation::Resume);
    assert_eq!(resume.to_json_bytes().expect("resume JSON")[0], b'{');
}

#[test]
fn harness_limits_include_claude_total_dispatch_ceiling_and_response_validation_is_fail_closed() {
    let limits = Harness::ClaudeCode.limits();
    assert_eq!(limits.max_concurrent_agents, Some(16));
    assert_eq!(limits.max_total_dispatches_per_run, Some(1_000));
    assert!(limits.validate_budget(1_000, 16).is_ok());
    assert!(limits.validate_budget(1_001, 1).is_err());

    let response = DispatchResponseFacts {
        schema: IDENTITY_RESOLUTION_SCHEMA.into(),
        project_id: ProjectId::new("018f47ce-72d7-7f64-9eb1-2f651d521c2a").expect("project"),
        run: RunId::new("v645").expect("run"),
        harness: Harness::ClaudeCode,
        agent_id: None,
        agent_type: None,
        role: Role::Shepherd,
        lane: None,
        session_id: SessionId::new("session-1").expect("session"),
        write_scope: vec!["**".into()],
        capabilities: None,
        tool_call_id: Some("audit-only".into()),
        mode: Some("execution".into()),
        write_paths: Vec::new(),
        path_in_write_scope: None,
    };
    response.validate().expect("valid root response");
    let mut malformed = response;
    malformed.schema = "wrong".into();
    assert!(malformed.validate().is_err());
}

fn lifecycle_record(agent: &str, observed: BTreeSet<String>) -> DispatchRecord {
    let role = Role::Coder;
    let contract = role
        .dispatch_capability_contract()
        .expect("fixture capability contract");
    DispatchRecord::start(DispatchStart {
        project_id: ProjectId::new("018f47ce-72d7-7f64-9eb1-2f651d521c2a")
            .expect("fixture project"),
        run: RunId::new("v645").expect("fixture run"),
        harness: Harness::Codex,
        agent_id: AgentId::new(agent).expect("fixture agent"),
        agent_type: AgentType::new("shepherd:coder").expect("fixture agent type"),
        role,
        lane: Some(LaneId::new("l1-engine").expect("fixture lane")),
        parent_agent_id: None,
        session_id: SessionId::new("session-1").expect("fixture session"),
        write_scope: vec!["crates/core/src/dispatch/**".into()],
        model: Some("model-1".into()),
        capability_contract: contract,
        capability_probe: CapabilityProbe::new(
            observed,
            "native-probe",
            "1.0.0",
            Some("provider-1"),
            1,
        )
        .expect("fixture probe"),
        started_at: 1,
        lease_expires_at: 10_001,
        resumes_agent_id: None,
    })
    .expect("fixture record")
}

#[test]
fn native_lifecycle_response_validation_enforces_operation_schema_state_and_context_counters() {
    let root = RootSessionBinding {
        schema: ROOT_SESSION_SCHEMA.into(),
        project_id: ProjectId::new("018f47ce-72d7-7f64-9eb1-2f651d521c2a")
            .expect("fixture project"),
        run: RunId::new("v645").expect("fixture run"),
        harness: Harness::Codex,
        session_id: SessionId::new("session-1").expect("fixture session"),
        role: Role::Shepherd,
        mode: "execution".into(),
        bound_at: 1,
        expires_at: 10_001,
    };
    NativeLifecycleResponse::BindRoot(root.clone())
        .validate_for(NativeLifecycleOperation::BindRoot)
        .expect("valid root binding");
    let mut invalid_root = root;
    invalid_root.schema = "wrong".into();
    assert!(
        NativeLifecycleResponse::BindRoot(invalid_root)
            .validate_for(NativeLifecycleOperation::BindRoot)
            .is_err()
    );

    let contract = Role::Coder
        .dispatch_capability_contract()
        .expect("fixture contract");
    let active = lifecycle_record(
        "agent-active",
        contract
            .required
            .union(&contract.optional)
            .cloned()
            .collect(),
    );
    NativeLifecycleResponse::Start(active.clone())
        .validate_for(NativeLifecycleOperation::Start)
        .expect("active start response");

    let capability_blocked = lifecycle_record("agent-blocked", BTreeSet::new());
    assert_eq!(capability_blocked.state, DispatchState::CapabilityBlocked);
    NativeLifecycleResponse::Start(capability_blocked)
        .validate_for(NativeLifecycleOperation::Start)
        .expect("blocked start remains a valid typed outcome");

    assert!(
        NativeLifecycleResponse::Stop(active.clone())
            .validate_for(NativeLifecycleOperation::Stop)
            .is_err()
    );
    let mut stopped = active.clone();
    stopped
        .stop(StopRequest {
            agent_id: active.agent_id.clone(),
            expected_revision: 1,
            stopped_at: 2,
            result_artifact: None,
        })
        .expect("stop fixture");
    NativeLifecycleResponse::Stop(stopped)
        .validate_for(NativeLifecycleOperation::Stop)
        .expect("stopped response");

    let entry = ContextEntry::new(
        "context-a",
        active.project_id.clone(),
        active.run.clone(),
        active.lane.clone(),
        "checkpoint",
        1,
        3,
        4,
        1,
        "bounded context",
    )
    .expect("context entry");
    let invalid_resume = ResumeContextResponse {
        schema: RESUME_CONTEXT_SCHEMA.into(),
        record: active.clone(),
        context: ContextBundle {
            entries: vec![entry.clone()],
            words: 2,
            tokens: 4,
        },
    };
    assert!(
        NativeLifecycleResponse::Resume(invalid_resume)
            .validate_for(NativeLifecycleOperation::Resume)
            .is_err()
    );
    let mut wrong_lane_entry = entry.clone();
    wrong_lane_entry.lane = Some(LaneId::new("l2-other").expect("other lane"));
    assert!(
        NativeLifecycleResponse::Resume(ResumeContextResponse {
            schema: RESUME_CONTEXT_SCHEMA.into(),
            record: active.clone(),
            context: ContextBundle {
                entries: vec![wrong_lane_entry],
                words: 3,
                tokens: 4,
            },
        })
        .validate_for(NativeLifecycleOperation::Resume)
        .is_err()
    );
    let oversized_entries = vec![entry.clone(); MAX_RESUME_CONTEXT_ENTRIES + 1];
    assert!(
        NativeLifecycleResponse::Resume(ResumeContextResponse {
            schema: RESUME_CONTEXT_SCHEMA.into(),
            record: active.clone(),
            context: ContextBundle {
                words: oversized_entries.len() * 3,
                tokens: oversized_entries.len() * 4,
                entries: oversized_entries,
            },
        })
        .validate_for(NativeLifecycleOperation::Resume)
        .is_err()
    );
    let valid_resume = ResumeContextResponse {
        schema: RESUME_CONTEXT_SCHEMA.into(),
        record: active,
        context: ContextBundle {
            entries: vec![entry],
            words: 3,
            tokens: 4,
        },
    };
    NativeLifecycleResponse::Resume(valid_resume)
        .validate_for(NativeLifecycleOperation::Resume)
        .expect("valid resume response");
}

/// A host resends `agent_id` on every subagent tool call but not `agent_type`,
/// which it only declares when the agent starts. Requiring the pair on tool
/// events made every dispatched agent's tool use unresolvable, so the guard
/// never ran for a subagent at all.
#[test]
fn tool_events_resolve_a_subagent_from_agent_id_alone() {
    for event in ["PreToolUse", "PostToolUse"] {
        let normalized = identity(Harness::ClaudeCode, event, Some("agent-1"), None)
            .normalize()
            .unwrap_or_else(|error| panic!("{event} with agent_id alone must normalize: {error}"));
        assert_eq!(
            normalized.agent_id.as_ref().map(AgentId::as_str),
            Some("agent-1")
        );
        assert!(normalized.agent_type.is_none());

        // An agent_type with no agent_id stays invalid: there is no record to key.
        assert!(
            identity(Harness::ClaudeCode, event, None, Some("shepherd:coder"))
                .normalize()
                .is_err(),
            "{event} accepted an agent_type with no agent_id"
        );
    }

    // Lifecycle events still require the pair -- they CREATE the record, so
    // they must declare which role is starting.
    for event in ["SubagentStart", "SubagentStop"] {
        assert!(
            identity(Harness::ClaudeCode, event, Some("agent-1"), None)
                .normalize()
                .is_err(),
            "{event} must still require agent_type"
        );
    }
}
