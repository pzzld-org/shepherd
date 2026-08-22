use shepherd_core::{
    Harness,
    dispatch::{
        AgentId, AgentType, CapabilityContract, CapabilityProbe, CapabilityReadiness, ContextEntry,
        ContextQuery, DispatchRecord, DispatchStart, DispatchState, IdentityError, LaneId,
        NativeIdentity, ProjectId, ROOT_SESSION_SCHEMA, Role, RootSessionBinding, RunId, SessionId,
        StopRequest, materialize_context, path_in_write_scope, resolve_native_identity,
    },
};
use std::collections::BTreeSet;

fn capabilities(values: &[&str]) -> BTreeSet<String> {
    values.iter().map(|value| (*value).to_owned()).collect()
}

#[test]
fn write_scope_matching_is_segment_aware_and_fail_closed() {
    let scopes = vec![
        "crates/core/src/dispatch/**".to_owned(),
        "docs/*/report.md".to_owned(),
        "*.md".to_owned(),
    ];
    assert!(path_in_write_scope("crates/core/src/dispatch/identity.rs", &scopes).unwrap());
    assert!(path_in_write_scope("docs/l1/report.md", &scopes).unwrap());
    assert!(!path_in_write_scope("crates/core/src/guard.rs", &scopes).unwrap());
    assert!(!path_in_write_scope("docs/l1/nested/report.md", &scopes).unwrap());
    assert!(path_in_write_scope("notes.md", &scopes).unwrap());
    assert!(!path_in_write_scope("notes.txt", &scopes).unwrap());
    assert!(!path_in_write_scope("docs/notes.md", &["*.md".into()]).unwrap());
    for unsafe_path in [
        "/tmp/escape.rs",
        "../escape.rs",
        "crates/core/src/dispatch/../../escape.rs",
        "crates/core/src/dispatch/*.rs",
    ] {
        assert!(
            path_in_write_scope(unsafe_path, &scopes).is_err(),
            "{unsafe_path}"
        );
    }
    for unsupported_scope in ["crates/**/src", "crates/co*re/**", "crates\\core\\**"] {
        assert!(
            path_in_write_scope("crates/core/src/lib.rs", &[unsupported_scope.into()]).is_err(),
            "{unsupported_scope}"
        );
    }
}

fn contract(required: &[&str], optional: &[&str], forbidden: &[&str]) -> CapabilityContract {
    CapabilityContract::new(required, optional, forbidden).expect("fixture contract is valid")
}

fn probe(observed: &[&str], at: i64) -> CapabilityProbe {
    CapabilityProbe::new(
        observed,
        "native-startup-probe",
        "1.2.3",
        Some("provider-4.5.6"),
        at,
    )
    .expect("fixture probe is valid")
}

fn start(agent: &str, harness: Harness, role: Role, lane: &str) -> DispatchStart {
    let capability_contract = role
        .dispatch_capability_contract()
        .expect("compiled role contract");
    let observed = capability_contract
        .required
        .union(&capability_contract.optional)
        .cloned()
        .collect::<BTreeSet<_>>();
    DispatchStart {
        project_id: ProjectId::new("018f47ce-72d7-7f64-9eb1-2f651d521c2a")
            .expect("fixture project id"),
        run: RunId::new("v645").expect("fixture run"),
        harness,
        agent_id: AgentId::new(agent).expect("fixture agent id"),
        agent_type: AgentType::new(role.carrier()).expect("fixture agent type"),
        role,
        lane: Some(LaneId::new(lane).expect("fixture lane")),
        parent_agent_id: None,
        session_id: SessionId::new("session-1").expect("fixture session"),
        write_scope: vec!["crates/core/src/dispatch/**".into()],
        model: Some("frontier".into()),
        capability_contract,
        capability_probe: CapabilityProbe::new(
            observed,
            "native-startup-probe",
            "1.2.3",
            Some("provider-4.5.6"),
            1_000,
        )
        .expect("fixture probe is valid"),
        started_at: 1_000,
        lease_expires_at: 11_000,
        resumes_agent_id: None,
    }
}

fn identity(record: &DispatchRecord, tool_call_id: &str, now: i64) -> NativeIdentity {
    NativeIdentity {
        harness: record.harness,
        project_id: record.project_id.clone(),
        run: record.run.clone(),
        lane: record.lane.clone(),
        session_id: record.session_id.clone(),
        agent_id: Some(record.agent_id.clone()),
        agent_type: Some(record.agent_type.clone()),
        role: Some(record.role),
        tool_call_id: Some(tool_call_id.into()),
        now,
        root_binding: None,
    }
}

#[test]
fn closed_role_registry_has_exactly_nine_stable_carriers() {
    let carriers: Vec<String> = Role::ALL.into_iter().map(Role::carrier).collect();
    assert_eq!(
        carriers,
        [
            "shepherd:auditor",
            "shepherd:coder",
            "shepherd:conductor",
            "shepherd:critic",
            "shepherd:discovery",
            "shepherd:engineer",
            "shepherd:planter",
            "shepherd:shepherd",
            "shepherd:worker",
        ]
    );
    assert!(Role::from_carrier("shepherd:architect").is_err());
    assert!(Role::from_carrier("coder").is_err());
}

#[test]
fn all_nine_roles_expose_exact_compiled_capability_contracts() {
    let expected = [
        (
            Role::Auditor,
            &[
                "code-intelligence",
                "read",
                "report-write",
                "search",
                "shell",
                "skill-load",
            ][..],
            &["tool-discovery"][..],
        ),
        (
            Role::Coder,
            &["read", "search", "shell", "skill-load", "write"][..],
            &["tool-discovery"][..],
        ),
        (
            Role::Conductor,
            &[
                "dispatch",
                "message-peer",
                "read",
                "search",
                "shell",
                "skill-load",
                "task-tracking",
            ][..],
            &["schedule-wakeup", "tool-discovery", "web-research"][..],
        ),
        (
            Role::Critic,
            &["read", "search", "shell", "skill-load"][..],
            &[][..],
        ),
        (
            Role::Discovery,
            &["read", "report-write", "search", "shell", "skill-load"][..],
            &["tool-discovery", "web-research"][..],
        ),
        (
            Role::Engineer,
            &[
                "dispatch",
                "message-peer",
                "read",
                "search",
                "shell",
                "skill-load",
                "write",
            ][..],
            &["tool-discovery"][..],
        ),
        (
            Role::Planter,
            &[
                "ask-operator",
                "dispatch",
                "read",
                "search",
                "shell",
                "skill-load",
                "task-tracking",
                "write",
            ][..],
            &["tool-discovery", "web-research"][..],
        ),
        (
            Role::Shepherd,
            &[
                "dispatch",
                "message-peer",
                "read",
                "search",
                "shell",
                "skill-load",
                "task-tracking",
                "write",
            ][..],
            &["tool-discovery", "web-research"][..],
        ),
        (
            Role::Worker,
            &["read", "search", "shell", "skill-load", "write"][..],
            &["tool-discovery"][..],
        ),
    ];

    for (role, required, optional) in expected {
        let contract = role
            .capability_contract()
            .expect("compiled contract is valid");
        assert_eq!(contract.required, capabilities(required), "{role}");
        assert_eq!(contract.optional, capabilities(optional), "{role}");
        assert!(contract.forbidden.contains("admin"), "{role}");
        assert!(contract.forbidden.contains("sudo"), "{role}");
        if matches!(role, Role::Auditor | Role::Critic | Role::Discovery) {
            assert!(contract.forbidden.contains("write"), "{role}");
        }
        let dispatch = role
            .dispatch_capability_contract()
            .expect("dispatch contract");
        assert!(dispatch.required.contains("subagent-provider"), "{role}");
    }
}

#[test]
fn capability_diff_separates_present_missing_extra_and_forbidden_extra() {
    let report = contract(&["read", "write"], &["web"], &["admin", "sudo"])
        .evaluate(probe(&["read", "web", "admin", "telemetry"], 50));

    assert_eq!(report.declared, capabilities(&["read", "web", "write"]));
    assert_eq!(
        report.observed,
        capabilities(&["admin", "read", "telemetry", "web"])
    );
    assert_eq!(report.present, capabilities(&["read", "web"]));
    assert_eq!(report.missing, capabilities(&["write"]));
    assert_eq!(report.missing_required, capabilities(&["write"]));
    assert!(report.missing_optional.is_empty());
    assert_eq!(report.extra, capabilities(&["admin", "telemetry"]));
    assert_eq!(report.forbidden_extra, capabilities(&["admin"]));
    assert_eq!(report.readiness(), CapabilityReadiness::Blocked);
    assert_eq!(report.source, "native-startup-probe");
    assert_eq!(report.provider_version.as_deref(), Some("provider-4.5.6"));
}

#[test]
fn optional_gap_degrades_but_required_provider_gap_blocks() {
    let degraded = contract(&["read"], &["web"], &[]).evaluate(probe(&["read"], 10));
    assert_eq!(degraded.missing_optional, capabilities(&["web"]));
    assert_eq!(degraded.readiness(), CapabilityReadiness::Degraded);

    let provider_absent = contract(&["subagent-provider"], &[], &[]).evaluate(probe(&[], 10));
    assert_eq!(
        provider_absent.missing_required,
        capabilities(&["subagent-provider"])
    );
    assert_eq!(provider_absent.readiness(), CapabilityReadiness::Blocked);
}

#[test]
fn start_builds_dispatch_v3_and_blocks_before_work_on_capability_failure() {
    let active = DispatchRecord::start(start(
        "claude-agent-1",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    ))
    .expect("valid start");
    assert_eq!(active.schema, "shepherd.dispatch/3");
    assert_eq!(active.revision, 1);
    assert_eq!(active.state, DispatchState::Active);
    assert_eq!(active.agent_id.as_str(), "claude-agent-1");
    assert_eq!(active.role, Role::Coder);

    let mut explicitly_non_writable = start(
        "claude-critic-read-only",
        Harness::ClaudeCode,
        Role::Critic,
        "l1-review",
    );
    explicitly_non_writable.write_scope.clear();
    let explicitly_non_writable = DispatchRecord::start(explicitly_non_writable)
        .expect("an empty scope explicitly carries no write authority");
    assert!(explicitly_non_writable.write_scope.is_empty());

    let mut blocked_start = start("pi-agent-1", Harness::Pi, Role::Coder, "l1-engine");
    blocked_start
        .capability_probe
        .observed
        .remove("subagent-provider");
    let blocked = DispatchRecord::start(blocked_start).expect("blocked dispatch is auditable");
    assert_eq!(blocked.state, DispatchState::CapabilityBlocked);
    assert_eq!(
        blocked.capabilities.missing_required,
        capabilities(&["subagent-provider"])
    );

    let mut mismatched_claude = start(
        "claude-mismatched-carrier",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    );
    mismatched_claude.agent_type = AgentType::new("shepherd:auditor").expect("safe carrier");
    assert!(DispatchRecord::start(mismatched_claude).is_err());
}

#[test]
fn native_identity_uses_agent_fields_and_never_tool_call_correlation() {
    let record = DispatchRecord::start(start(
        "claude-agent-1",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    ))
    .expect("valid start");

    let first = resolve_native_identity(Some(&record), &identity(&record, "tool-1", 2_000))
        .expect("first tool resolves");
    let second = resolve_native_identity(Some(&record), &identity(&record, "tool-2", 2_001))
        .expect("fresh tool id from same agent resolves");
    assert_eq!(first, second);

    let other = DispatchRecord::start(start(
        "claude-agent-2",
        Harness::ClaudeCode,
        Role::Auditor,
        "l1-engine",
    ))
    .expect("valid second start");
    let error = resolve_native_identity(Some(&record), &identity(&other, "tool-1", 2_000))
        .expect_err("same tool id from another agent cannot cross-resolve");
    assert!(matches!(error, IdentityError::AgentIdMismatch { .. }));
}

#[test]
fn codex_native_worker_type_preserves_separate_semantic_role() {
    let mut input = start("codex-coder-1", Harness::Codex, Role::Coder, "l1-engine");
    input.agent_type = AgentType::new("worker").expect("Codex native type");
    let record = DispatchRecord::start(input).expect("native type is not a semantic role claim");
    let mut native = identity(&record, "turn-tool-1", 2_000);
    native.role = None;

    let resolution = resolve_native_identity(Some(&record), &native)
        .expect("Codex resolves native agent id and type against durable semantic role");
    assert_eq!(
        resolution,
        shepherd_core::dispatch::IdentityResolution::Agent {
            agent_id: record.agent_id.clone(),
            role: Role::Coder,
        }
    );
}

#[test]
fn identity_mismatch_missing_stale_terminal_wrong_run_and_wrong_lane_are_typed() {
    let mut record = DispatchRecord::start(start(
        "codex-agent-1",
        Harness::Codex,
        Role::Worker,
        "l2-cli",
    ))
    .expect("valid start");

    assert!(matches!(
        resolve_native_identity(None, &identity(&record, "tool-a", 2_000)),
        Err(IdentityError::MissingRecord { .. })
    ));

    let mut wrong_type = identity(&record, "tool-b", 2_000);
    wrong_type.agent_type = Some(AgentType::new("explorer").expect("fixture type"));
    assert!(matches!(
        resolve_native_identity(Some(&record), &wrong_type),
        Err(IdentityError::AgentTypeMismatch { .. })
    ));

    let mut wrong_role = identity(&record, "tool-c", 2_000);
    wrong_role.role = Some(Role::Auditor);
    assert!(matches!(
        resolve_native_identity(Some(&record), &wrong_role),
        Err(IdentityError::RoleMismatch { .. })
    ));

    let mut wrong_run = identity(&record, "tool-d", 2_000);
    wrong_run.run = RunId::new("v646").expect("fixture run");
    assert!(matches!(
        resolve_native_identity(Some(&record), &wrong_run),
        Err(IdentityError::WrongRun { .. })
    ));

    let mut wrong_lane = identity(&record, "tool-e", 2_000);
    wrong_lane.lane = Some(LaneId::new("l9-other").expect("fixture lane"));
    assert!(matches!(
        resolve_native_identity(Some(&record), &wrong_lane),
        Err(IdentityError::WrongLane { .. })
    ));

    assert!(matches!(
        resolve_native_identity(Some(&record), &identity(&record, "tool-f", 11_000)),
        Err(IdentityError::Stale { .. })
    ));

    record
        .stop(StopRequest {
            agent_id: record.agent_id.clone(),
            expected_revision: 1,
            stopped_at: 5_000,
            result_artifact: Some("lanes/l2-cli/reports/codex-agent-1.md".into()),
        })
        .expect("active record stops once");
    assert!(matches!(
        resolve_native_identity(Some(&record), &identity(&record, "tool-g", 5_001)),
        Err(IdentityError::Terminal { .. })
    ));
}

#[test]
fn root_identity_requires_a_current_explicit_session_binding() {
    let record = DispatchRecord::start(start(
        "claude-root-fixture",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    ))
    .expect("fixture record");
    let mut native = identity(&record, "root-tool", 2_000);
    native.agent_id = None;
    native.agent_type = None;
    native.role = None;
    native.lane = None;
    assert!(matches!(
        resolve_native_identity(None, &native),
        Err(IdentityError::MissingRootBinding)
    ));

    native.root_binding = Some(RootSessionBinding {
        schema: ROOT_SESSION_SCHEMA.into(),
        project_id: native.project_id.clone(),
        run: native.run.clone(),
        harness: native.harness,
        session_id: native.session_id.clone(),
        role: Role::Shepherd,
        mode: "execution".into(),
        bound_at: 1_000,
        expires_at: 3_000,
    });
    assert!(resolve_native_identity(None, &native).is_ok());

    native.root_binding.as_mut().expect("binding").bound_at = 2_001;
    assert!(matches!(
        resolve_native_identity(None, &native),
        Err(IdentityError::InvalidRootBinding(_))
    ));
    let binding = native.root_binding.as_mut().expect("binding");
    binding.bound_at = 1_000;
    binding.expires_at = 1_000;
    assert!(matches!(
        resolve_native_identity(None, &native),
        Err(IdentityError::InvalidRootBinding(_))
    ));
    let binding = native.root_binding.as_mut().expect("binding");
    binding.expires_at = 3_000;
    binding.mode.clear();
    assert!(matches!(
        resolve_native_identity(None, &native),
        Err(IdentityError::InvalidRootBinding(_))
    ));

    let binding = native.root_binding.as_mut().expect("binding");
    binding.mode = "execution".into();
    native.now = 3_000;
    assert!(matches!(
        resolve_native_identity(None, &native),
        Err(IdentityError::Stale { .. })
    ));
}

#[test]
fn stop_is_monotonic_revision_checked_and_stores_only_artifact_reference() {
    let mut record = DispatchRecord::start(start(
        "claude-agent-stop",
        Harness::ClaudeCode,
        Role::Auditor,
        "l3-audit",
    ))
    .expect("valid start");
    record
        .stop(StopRequest {
            agent_id: record.agent_id.clone(),
            expected_revision: 1,
            stopped_at: 2_000,
            result_artifact: Some("reports/auditor-claude-agent-stop.md".into()),
        })
        .expect("first stop succeeds");
    assert_eq!(record.state, DispatchState::Stopped);
    assert_eq!(record.revision, 2);
    assert_eq!(
        record.result_artifact.as_deref(),
        Some("reports/auditor-claude-agent-stop.md")
    );
    assert!(
        record
            .stop(StopRequest {
                agent_id: record.agent_id.clone(),
                expected_revision: 2,
                stopped_at: 3_000,
                result_artifact: None,
            })
            .is_err()
    );
    assert!(
        serde_json::to_string(&record)
            .expect("record serializes")
            .find("transcript")
            .is_none()
    );
}

#[test]
fn resume_lineage_assigns_new_native_ids_across_harnesses() {
    let mut claude = DispatchRecord::start(start(
        "claude-a",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    ))
    .expect("Claude starts");
    claude
        .stop(StopRequest {
            agent_id: claude.agent_id.clone(),
            expected_revision: 1,
            stopped_at: 2_000,
            result_artifact: Some("lanes/l1-engine/reports/claude-a.md".into()),
        })
        .expect("Claude stops");

    let mut codex_start = start("codex-b", Harness::Codex, Role::Coder, "l1-engine");
    codex_start.resumes_agent_id = Some(claude.agent_id.clone());
    let mut codex = claude.resume(codex_start).expect("Codex resumes Claude");
    codex
        .stop(StopRequest {
            agent_id: codex.agent_id.clone(),
            expected_revision: 1,
            stopped_at: 4_000,
            result_artifact: Some("lanes/l1-engine/reports/codex-b.md".into()),
        })
        .expect("Codex stops");

    let mut pi_start = start("pi-c", Harness::Pi, Role::Coder, "l1-engine");
    pi_start.resumes_agent_id = Some(codex.agent_id.clone());
    let pi = codex.resume(pi_start).expect("Pi resumes Codex");

    assert_eq!(codex.resumes_agent_id.as_ref(), Some(&claude.agent_id));
    assert_eq!(pi.resumes_agent_id.as_ref(), Some(&codex.agent_id));
    assert_ne!(claude.agent_id, codex.agent_id);
    assert_ne!(codex.agent_id, pi.agent_id);
    assert_eq!(pi.run, claude.run);
    assert_eq!(pi.lane, claude.lane);
    assert_eq!(pi.write_scope, claude.write_scope);
}

#[test]
fn unsafe_identifiers_and_artifact_parent_escapes_are_rejected() {
    assert!(AgentId::new("../agent").is_err());
    assert!(AgentId::new("agent/child").is_err());
    assert!(AgentId::new(".").is_err());
    assert!(AgentId::new("a".repeat(129)).is_err());
    assert!(ProjectId::new("not-a-project-uuid").is_err());
    assert!(RunId::new("../v645").is_err());
    assert!(LaneId::new("L1-UPPER").is_err());

    let mut absolute_scope = start(
        "claude-absolute-scope",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    );
    absolute_scope.write_scope = vec!["/tmp/outside/**".into()];
    assert!(DispatchRecord::start(absolute_scope).is_err());

    let mut dotted_scope = start(
        "claude-dotted-scope",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    );
    dotted_scope.write_scope = vec!["crates/./core/**".into()];
    assert!(DispatchRecord::start(dotted_scope).is_err());

    let mut control_scope = start(
        "claude-control-scope",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    );
    control_scope.write_scope = vec!["crates/core/**\nforged".into()];
    assert!(DispatchRecord::start(control_scope).is_err());

    let mut invalid_model = start(
        "claude-control-model",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    );
    invalid_model.model = Some("model\nforged".into());
    assert!(DispatchRecord::start(invalid_model).is_err());

    assert!(
        CapabilityProbe::new(["read"], "native-startup-probe", "1.2.3", Some(""), 1_000,).is_err()
    );

    let mut record = DispatchRecord::start(start(
        "claude-artifact",
        Harness::ClaudeCode,
        Role::Auditor,
        "l3-audit",
    ))
    .expect("valid start");
    assert!(
        record
            .stop(StopRequest {
                agent_id: record.agent_id.clone(),
                expected_revision: 1,
                stopped_at: 2_000,
                result_artifact: Some("../transcript.jsonl".into()),
            })
            .is_err()
    );
}

#[test]
fn loaded_records_reject_schema_drift_inconsistent_capability_diffs_and_states() {
    let record = DispatchRecord::start(start(
        "claude-loaded",
        Harness::ClaudeCode,
        Role::Coder,
        "l1-engine",
    ))
    .expect("valid start");
    record.validate_loaded().expect("fresh record validates");

    let mut wrong_schema = record.clone();
    wrong_schema.schema = "shepherd.dispatch/99".into();
    assert!(wrong_schema.validate_loaded().is_err());

    let mut inconsistent_diff = record.clone();
    inconsistent_diff.capabilities.present.clear();
    assert!(inconsistent_diff.validate_loaded().is_err());

    let mut relabeled_required_gap = record.clone();
    let required = relabeled_required_gap
        .capabilities
        .declared
        .iter()
        .next()
        .expect("compiled role declares capabilities")
        .clone();
    relabeled_required_gap
        .capabilities
        .observed
        .remove(&required);
    relabeled_required_gap
        .capabilities
        .present
        .remove(&required);
    relabeled_required_gap
        .capabilities
        .missing
        .insert(required.clone());
    relabeled_required_gap
        .capabilities
        .missing_optional
        .insert(required);
    relabeled_required_gap.state = DispatchState::Active;
    assert!(
        relabeled_required_gap.validate_loaded().is_err(),
        "a durable record cannot downgrade a compiled required capability to optional"
    );

    let mut omitted_forbidden = record.clone();
    omitted_forbidden
        .capabilities
        .observed
        .insert("admin".into());
    omitted_forbidden.capabilities.extra.insert("admin".into());
    assert!(
        omitted_forbidden.validate_loaded().is_err(),
        "a durable record cannot omit a compiled forbidden extra"
    );

    let mut invalid_provider_version = record.clone();
    invalid_provider_version.capabilities.provider_version = Some(String::new());
    assert!(invalid_provider_version.validate_loaded().is_err());

    let mut mismatched_claude_carrier = record.clone();
    mismatched_claude_carrier.agent_type =
        AgentType::new("shepherd:auditor").expect("safe carrier");
    assert!(mismatched_claude_carrier.validate_loaded().is_err());

    let mut forged_terminal = record.clone();
    forged_terminal.state = DispatchState::Stopped;
    assert!(forged_terminal.validate_loaded().is_err());

    let malformed_role = serde_json::to_value(&record)
        .expect("record serializes")
        .as_object()
        .cloned()
        .map(|mut value| {
            value.insert("role".into(), serde_json::json!("arbitrary-admin"));
            serde_json::Value::Object(value)
        })
        .expect("record is an object");
    assert!(serde_json::from_value::<DispatchRecord>(malformed_role).is_err());
}

#[test]
fn context_materialization_is_scoped_ranked_and_budget_bounded() {
    let project = ProjectId::new("018f47ce-72d7-7f64-9eb1-2f651d521c2a").expect("fixture project");
    let run = RunId::new("v645").expect("fixture run");
    let lane = LaneId::new("l1-engine").expect("fixture lane");
    let entries = vec![
        ContextEntry::new(
            "lane-new",
            project.clone(),
            run.clone(),
            Some(lane.clone()),
            "checkpoint",
            300,
            10,
            15,
            100,
            "new lane context",
        )
        .expect("fixture entry"),
        ContextEntry::new(
            "shared-high",
            project.clone(),
            run.clone(),
            None,
            "memory",
            250,
            8,
            10,
            90,
            "shared context",
        )
        .expect("fixture entry"),
        ContextEntry::new(
            "wrong-lane",
            project.clone(),
            run.clone(),
            Some(LaneId::new("l2-cli").expect("fixture lane")),
            "memory",
            400,
            1,
            1,
            999,
            "must be filtered",
        )
        .expect("fixture entry"),
        ContextEntry::new(
            "too-old",
            project.clone(),
            run.clone(),
            None,
            "memory",
            10,
            1,
            1,
            500,
            "stale",
        )
        .expect("fixture entry"),
    ];
    let bundle = materialize_context(
        &entries,
        &ContextQuery {
            project_id: project,
            run,
            lane: Some(lane),
            min_freshness: 100,
            max_entries: 2,
            max_words: 20,
            max_tokens: 30,
        },
    );
    let ids: Vec<&str> = bundle
        .entries
        .iter()
        .map(|entry| entry.id.as_str())
        .collect();
    assert_eq!(ids, ["lane-new", "shared-high"]);
    assert_eq!(bundle.words, 18);
    assert_eq!(bundle.tokens, 25);
}
