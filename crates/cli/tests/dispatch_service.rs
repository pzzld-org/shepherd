mod support;

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use shepherd_cli::shepherd::{
    Harness, RunState,
    dispatch::{CapabilityReadiness, DispatchState, ProjectId, Role},
    registry::Registry,
};
use shepherd_cli::{
    BindRootDispatchRequest, DispatchService, DispatchStore, ResolveDispatchRequest,
    ResumeDispatchRequest, StartDispatchRequest, StopDispatchRequest,
};

fn fixture_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "shepherd-dispatch-service-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    std::fs::create_dir_all(&path).expect("fixture");
    std::fs::canonicalize(path).expect("canonical fixture")
}

#[test]
fn session_start_binding_is_durable_and_required_for_root_resolution() {
    let dir = fixture_dir("root-session");
    let service = service(&dir);

    let missing = service.resolve(
        ResolveDispatchRequest {
            schema: "shepherd.dispatch-request/1".into(),
            run: Some("v645".into()),
            harness: Harness::ClaudeCode,
            agent_id: None,
            agent_type: None,
            role_carrier: None,
            lane: None,
            session_id: "root-session-1".into(),
            tool_call_id: Some("audit-only-tool-id".into()),
            tool_name: None,
            tool_input: None,
        },
        1_000,
    );
    assert!(
        missing.is_err(),
        "root resolution must fail closed before SessionStart binds it"
    );

    let binding = service
        .bind_root(
            BindRootDispatchRequest {
                schema: "shepherd.dispatch-request/1".into(),
                run: Some("v645".into()),
                harness: Harness::ClaudeCode,
                session_id: "root-session-1".into(),
                role_carrier: "shepherd:shepherd".into(),
                mode: "execution".into(),
                lease_ms: 60_000,
            },
            1_000,
        )
        .expect("SessionStart publishes root binding");
    assert_eq!(binding.schema, "shepherd.root-session/1");
    assert_eq!(binding.bound_at, 1_000);
    assert_eq!(binding.expires_at, 61_000);

    let resolved = service
        .resolve(
            ResolveDispatchRequest {
                schema: "shepherd.dispatch-request/1".into(),
                run: None,
                harness: Harness::ClaudeCode,
                agent_id: None,
                agent_type: None,
                role_carrier: None,
                lane: None,
                session_id: "root-session-1".into(),
                tool_call_id: Some("different-audit-tool-id".into()),
                tool_name: None,
                tool_input: None,
            },
            2_000,
        )
        .expect("root identity resolves from durable binding");
    assert_eq!(resolved.role, Role::Shepherd);
    assert_eq!(resolved.mode.as_deref(), Some("execution"));
    assert_eq!(resolved.agent_id, None);

    let mismatch = service.resolve(
        ResolveDispatchRequest {
            schema: "shepherd.dispatch-request/1".into(),
            run: None,
            harness: Harness::Codex,
            agent_id: None,
            agent_type: None,
            role_carrier: None,
            lane: None,
            session_id: "root-session-1".into(),
            tool_call_id: None,
            tool_name: None,
            tool_input: None,
        },
        2_000,
    );
    assert!(mismatch.is_err(), "harness mismatch must fail closed");
    cleanup(&dir);
}

fn cleanup(path: &Path) {
    support::remove_dir_all(path)
}

fn service(dir: &Path) -> DispatchService {
    let runs = dir.join("primary/.shepherd/runs");
    let state: RunState = serde_json::from_value(serde_json::json!({
        "run": "v645",
        "status": "executing",
    }))
    .expect("run state");
    state.store(&runs.join("v645/run.json")).expect("store run");
    DispatchService::with_project_root(
        DispatchStore::new(runs),
        ProjectId::new("018f47ce-72d7-7f64-9eb1-2f651d521c2a").expect("project id"),
        dir.join("primary"),
    )
}

fn observed(role: Role) -> BTreeSet<String> {
    let contract = role
        .dispatch_capability_contract()
        .expect("compiled role contract");
    contract
        .required
        .union(&contract.optional)
        .cloned()
        .collect()
}

fn start_request(
    harness: Harness,
    agent_id: &str,
    agent_type: &str,
    role: Role,
) -> StartDispatchRequest {
    StartDispatchRequest {
        schema: "shepherd.dispatch-request/1".into(),
        run: Some("v645".into()),
        harness,
        agent_id: agent_id.into(),
        agent_type: agent_type.into(),
        role_carrier: role.carrier(),
        lane: Some("l1-engine".into()),
        parent_agent_id: None,
        session_id: format!("session-{agent_id}"),
        write_scope: vec!["crates/core/src/dispatch/**".into()],
        model: Some("frontier".into()),
        observed_capabilities: observed(role),
        capability_source: "native-startup-probe".into(),
        harness_version: "1.2.3".into(),
        provider_version: Some("provider-4.5.6".into()),
        lease_ms: 60_000,
    }
}

#[test]
fn native_service_publishes_and_resolves_real_claude_codex_and_pi_identities() {
    let dir = fixture_dir("harnesses");
    let service = service(&dir);

    let claude = service
        .start(
            start_request(
                Harness::ClaudeCode,
                "claude-agent-1",
                "shepherd:coder",
                Role::Coder,
            ),
            1_000,
        )
        .expect("Claude start");
    let codex = service
        .start(
            start_request(Harness::Codex, "codex-agent-1", "worker", Role::Coder),
            1_000,
        )
        .expect("Codex start");
    let pi = service
        .start(
            start_request(
                Harness::Pi,
                "pi-agent-1",
                "pi-subagents:worker",
                Role::Worker,
            ),
            1_000,
        )
        .expect("Pi provider start");

    for record in [&claude, &codex, &pi] {
        assert_eq!(record.schema, "shepherd.dispatch/3");
        assert_eq!(record.state, DispatchState::Active);
        assert_eq!(record.capabilities.readiness(), CapabilityReadiness::Ready);
    }
    assert_eq!(
        codex.agent_type.as_str(),
        "worker",
        "Codex real native type is preserved"
    );

    let resolution = service
        .resolve(
            ResolveDispatchRequest {
                schema: "shepherd.dispatch-request/1".into(),
                run: None,
                harness: Harness::ClaudeCode,
                agent_id: Some("claude-agent-1".into()),
                agent_type: Some("shepherd:coder".into()),
                role_carrier: Some("shepherd:coder".into()),
                lane: None,
                session_id: "session-claude-agent-1".into(),
                tool_call_id: Some("tool-new-every-call".into()),
                tool_name: None,
                tool_input: None,
            },
            2_000,
        )
        .expect("Claude identity resolves");
    assert_eq!(resolution.role, Role::Coder);
    assert_eq!(resolution.agent_id.as_deref(), Some("claude-agent-1"));
    assert_eq!(resolution.project_id, claude.project_id);
    assert_eq!(resolution.run, claude.run);
    assert_eq!(resolution.harness, Harness::ClaudeCode);
    assert_eq!(resolution.agent_type.as_ref(), Some(&claude.agent_type));
    assert_eq!(resolution.lane, claude.lane);
    assert_eq!(resolution.session_id, claude.session_id);
    assert_eq!(resolution.write_scope, claude.write_scope);
    assert_eq!(resolution.capabilities.as_ref(), Some(&claude.capabilities));
    cleanup(&dir);
}

#[test]
fn native_resolution_derives_write_scope_with_nofollow_containment() {
    let dir = fixture_dir("write-scope");
    let service = service(&dir);
    let primary = dir.join("primary");
    std::fs::create_dir_all(primary.join("crates/core/src/dispatch")).expect("scope directory");
    std::fs::write(
        primary.join("crates/core/src/dispatch/identity.rs"),
        "// fixture\n",
    )
    .expect("scope file");
    service
        .start(
            start_request(
                Harness::ClaudeCode,
                "claude-scope-1",
                "shepherd:coder",
                Role::Coder,
            ),
            1_000,
        )
        .expect("start");

    let resolve = |path: &str| {
        service.resolve(
            ResolveDispatchRequest {
                schema: "shepherd.dispatch-request/1".into(),
                run: None,
                harness: Harness::ClaudeCode,
                agent_id: Some("claude-scope-1".into()),
                agent_type: Some("shepherd:coder".into()),
                role_carrier: Some("shepherd:coder".into()),
                lane: None,
                session_id: "session-claude-scope-1".into(),
                tool_call_id: None,
                tool_name: Some("Write".into()),
                tool_input: Some(serde_json::json!({"file_path": path})),
            },
            2_000,
        )
    };

    let allowed = resolve("crates/core/src/dispatch/identity.rs").expect("allowed fact");
    assert_eq!(
        allowed.write_paths,
        ["crates/core/src/dispatch/identity.rs"]
    );
    assert_eq!(allowed.path_in_write_scope, Some(true));

    let new_file = resolve(
        &primary
            .join("crates/core/src/dispatch/new.rs")
            .display()
            .to_string(),
    )
    .expect("missing final file is safely contained");
    assert_eq!(new_file.write_paths, ["crates/core/src/dispatch/new.rs"]);
    assert_eq!(new_file.path_in_write_scope, Some(true));

    let outside =
        resolve("crates/core/src/guard.rs").expect("out-of-scope is a derived false fact");
    assert_eq!(outside.path_in_write_scope, Some(false));

    let patch = service
        .resolve(
            ResolveDispatchRequest {
                schema: "shepherd.dispatch-request/1".into(),
                run: None,
                harness: Harness::ClaudeCode,
                agent_id: Some("claude-scope-1".into()),
                agent_type: Some("shepherd:coder".into()),
                role_carrier: Some("shepherd:coder".into()),
                lane: None,
                session_id: "session-claude-scope-1".into(),
                tool_call_id: None,
                tool_name: Some("apply_patch".into()),
                tool_input: Some(serde_json::json!({
                    "patch": "*** Begin Patch\n*** Update File: crates/core/src/dispatch/identity.rs\n*** Add File: crates/core/src/dispatch/new.rs\n*** End Patch"
                })),
            },
            2_000,
        )
        .expect("Rust parses canonical patch headers");
    assert_eq!(
        patch.write_paths,
        [
            "crates/core/src/dispatch/identity.rs",
            "crates/core/src/dispatch/new.rs",
        ]
    );
    assert_eq!(patch.path_in_write_scope, Some(true));

    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(
            "identity.rs",
            primary.join("crates/core/src/dispatch/link.rs"),
        )
        .expect("symlink fixture");
        assert!(resolve("crates/core/src/dispatch/link.rs").is_err());
        std::fs::create_dir_all(primary.join("outside")).expect("outside directory");
        std::os::unix::fs::symlink(
            primary.join("outside"),
            primary.join("crates/core/src/dispatch/linked-directory"),
        )
        .expect("directory symlink fixture");
        assert!(resolve("crates/core/src/dispatch/linked-directory/escape.rs").is_err());
    }
    cleanup(&dir);
}

#[test]
fn pi_provider_absence_publishes_a_capability_block_before_work() {
    let dir = fixture_dir("pi-absent");
    let service = service(&dir);
    let mut request = start_request(
        Harness::Pi,
        "pi-agent-blocked",
        "pi-subagents:worker",
        Role::Worker,
    );
    request.observed_capabilities.remove("subagent-provider");
    request.provider_version = None;

    let blocked = service
        .start(request, 1_000)
        .expect("blocked record is auditable");
    assert_eq!(blocked.state, DispatchState::CapabilityBlocked);
    assert!(
        blocked
            .capabilities
            .missing_required
            .contains("subagent-provider")
    );
    assert!(
        service
            .resolve_for_mutation("pi-agent-blocked", 2_000)
            .is_err()
    );
    cleanup(&dir);
}

#[test]
fn resume_claude_to_codex_to_pi_assigns_new_ids_and_preserves_binding() {
    let dir = fixture_dir("resume");
    let service = service(&dir);
    let primary = dir.join("primary");
    std::fs::create_dir_all(primary.join(".shepherd/runs/v645/lanes/l1-engine/reports"))
        .expect("lane artifacts");
    std::fs::create_dir_all(primary.join(".shepherd/runs/v645/snapshots")).expect("snapshots");
    std::fs::write(
        primary.join(".shepherd/runs/v645/lanes/l1-engine/plan.md"),
        "# Lane plan\n\nImplement the native dispatch boundary.\n",
    )
    .expect("lane plan");
    std::fs::write(
        primary.join(".shepherd/runs/v645/snapshots/precompact-session-2000.json"),
        "{\"checkpoint\":\"accepted\",\"at\":2000}\n",
    )
    .expect("checkpoint");
    let registry =
        Registry::open_migrated(primary.join(".shepherd/shepherd.db")).expect("registry");
    registry
        .execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?1, ?2, 1, 1)",
            ("018f47ce-72d7-7f64-9eb1-2f651d521c2a", "resume fixture"),
        )
        .expect("project");
    registry
        .execute(
            "INSERT INTO mem_entries (id, project_id, kind, title, body, tags, pinned, created_at, updated_at) VALUES (?1, ?2, 'decision', ?3, ?4, ?5, 1, 2, 2)",
            (
                "memory-1",
                "018f47ce-72d7-7f64-9eb1-2f651d521c2a",
                "Native identity",
                "Never infer an agent identity from a tool-use id.",
                "[\"run:v645\",\"lane:l1-engine\"]",
            ),
        )
        .expect("memory");
    drop(registry);
    let claude = service
        .start(
            start_request(
                Harness::ClaudeCode,
                "claude-a",
                "shepherd:coder",
                Role::Coder,
            ),
            1_000,
        )
        .expect("Claude starts");
    service
        .stop(
            StopDispatchRequest {
                schema: "shepherd.dispatch-request/1".into(),
                run: None,
                harness: Harness::ClaudeCode,
                agent_id: "claude-a".into(),
                agent_type: "shepherd:coder".into(),
                role_carrier: Some("shepherd:coder".into()),
                lane: None,
                session_id: "session-claude-a".into(),
                expected_revision: 1,
                result_artifact: Some("lanes/l1-engine/reports/claude-a.md".into()),
            },
            2_000,
        )
        .expect("Claude stops");
    std::fs::write(
        primary.join(".shepherd/runs/v645/lanes/l1-engine/reports/claude-a.md"),
        "Claude result evidence.\n",
    )
    .expect("Claude result");

    let codex_resume = service
        .resume(
            ResumeDispatchRequest {
                schema: "shepherd.dispatch-request/1".into(),
                source_agent_id: "claude-a".into(),
                next: start_request(Harness::Codex, "codex-b", "worker", Role::Coder),
            },
            3_000,
        )
        .expect("Codex resumes");
    let codex = codex_resume.record;
    assert!(
        service
            .stop(
                StopDispatchRequest {
                    schema: "shepherd.dispatch-request/1".into(),
                    run: None,
                    harness: Harness::Codex,
                    agent_id: "codex-b".into(),
                    agent_type: "explorer".into(),
                    role_carrier: None,
                    lane: None,
                    session_id: "session-codex-b".into(),
                    expected_revision: 1,
                    result_artifact: None,
                },
                3_500,
            )
            .is_err(),
        "SubagentStop must verify the full native identity before mutation",
    );
    assert_eq!(
        service
            .store()
            .load_active(&codex.agent_id)
            .expect("mismatch leaves record readable")
            .state,
        DispatchState::Active,
    );
    service
        .stop(
            StopDispatchRequest {
                schema: "shepherd.dispatch-request/1".into(),
                run: None,
                harness: Harness::Codex,
                agent_id: "codex-b".into(),
                agent_type: "worker".into(),
                role_carrier: None,
                lane: None,
                session_id: "session-codex-b".into(),
                expected_revision: 1,
                result_artifact: Some("lanes/l1-engine/reports/codex-b.md".into()),
            },
            4_000,
        )
        .expect("Codex stops");
    std::fs::write(
        primary.join(".shepherd/runs/v645/lanes/l1-engine/reports/codex-b.md"),
        "Codex result evidence.\n",
    )
    .expect("Codex result");
    let pi_resume = service
        .resume(
            ResumeDispatchRequest {
                schema: "shepherd.dispatch-request/1".into(),
                source_agent_id: "codex-b".into(),
                next: start_request(Harness::Pi, "pi-c", "pi-subagents:worker", Role::Coder),
            },
            5_000,
        )
        .expect("Pi resumes");
    let pi = pi_resume.record;

    assert_eq!(codex.resumes_agent_id.as_ref(), Some(&claude.agent_id));
    assert_eq!(pi.resumes_agent_id.as_ref(), Some(&codex.agent_id));
    assert_eq!(pi.run, claude.run);
    assert_eq!(pi.lane, claude.lane);
    assert_eq!(pi.write_scope, claude.write_scope);
    assert!(pi_resume.context.words > 0);
    assert!(pi_resume.context.tokens <= 32_768);
    let provenance = pi_resume
        .context
        .entries
        .iter()
        .map(|entry| entry.provenance.as_str())
        .collect::<Vec<_>>();
    assert!(provenance.contains(&"run.json"));
    assert!(provenance.contains(&"lanes/l1-engine/plan.md"));
    assert!(
        provenance
            .iter()
            .any(|value| value.starts_with("snapshots/precompact-"))
    );
    assert!(provenance.contains(&"lanes/l1-engine/reports/claude-a.md"));
    assert!(provenance.contains(&"lanes/l1-engine/reports/codex-b.md"));
    assert!(
        provenance
            .iter()
            .any(|value| value.starts_with("registry:memory-1:"))
    );
    cleanup(&dir);
}

#[test]
fn all_nine_role_profiles_have_exact_capability_diffs_on_each_harness() {
    let dir = fixture_dir("all-role-profiles");
    let service = service(&dir);
    for harness in [Harness::ClaudeCode, Harness::Codex, Harness::Pi] {
        for role in Role::ALL {
            let native_type = match harness {
                Harness::ClaudeCode => role.carrier(),
                Harness::Codex
                    if matches!(role, Role::Auditor | Role::Critic | Role::Discovery) =>
                {
                    "explorer".into()
                }
                Harness::Codex => "worker".into(),
                Harness::Pi => format!("pi-subagents:{}", role.as_str()),
                _ => unreachable!("closed harness set"),
            };
            let agent_id = format!("{}-{}", harness, role.as_str());
            let record = service
                .start(start_request(harness, &agent_id, &native_type, role), 1_000)
                .expect("role profile boots");
            assert_eq!(record.capabilities.readiness(), CapabilityReadiness::Ready);
            assert!(record.capabilities.missing.is_empty(), "{harness}/{role}");
            assert!(
                record.capabilities.forbidden_extra.is_empty(),
                "{harness}/{role}"
            );
            let contract = role.dispatch_capability_contract().expect("role contract");
            assert_eq!(
                record.capabilities.declared,
                contract
                    .required
                    .union(&contract.optional)
                    .cloned()
                    .collect::<BTreeSet<_>>(),
                "{harness}/{role}",
            );
        }
    }
    cleanup(&dir);
}
