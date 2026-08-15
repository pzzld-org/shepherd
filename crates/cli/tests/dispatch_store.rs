use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use shepherd_cli::shepherd::{
    Harness, RunState,
    dispatch::{
        AgentId, AgentType, CapabilityProbe, DispatchRecord, DispatchStart, DispatchState, LaneId,
        NativeIdentity, ProjectId, ROOT_SESSION_SCHEMA, Role, RootSessionBinding, RunId, SessionId,
        StopRequest,
    },
};
use shepherd_cli::{DispatchStore, DispatchStoreError};

fn fixture_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "shepherd-dispatch-store-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    std::fs::create_dir_all(&path).expect("create fixture");
    std::fs::canonicalize(path).expect("canonical fixture")
}

fn cleanup(path: &Path) {
    std::fs::remove_dir_all(path).expect("remove fixture");
}

fn write_run(runs_root: &Path, run: &str, status: &str) {
    let state: RunState = serde_json::from_value(serde_json::json!({
        "run": run,
        "status": status,
    }))
    .expect("run fixture parses");
    state
        .store(&runs_root.join(run).join("run.json"))
        .expect("run fixture stores");
}

fn record(agent: &str, run: &str, role: Role, harness: Harness) -> DispatchRecord {
    let capability_contract = role
        .dispatch_capability_contract()
        .expect("compiled role contract");
    let observed = capability_contract
        .required
        .union(&capability_contract.optional)
        .cloned()
        .collect::<std::collections::BTreeSet<_>>();
    DispatchRecord::start(DispatchStart {
        project_id: ProjectId::new("018f47ce-72d7-7f64-9eb1-2f651d521c2a").expect("project id"),
        run: RunId::new(run).expect("run id"),
        harness,
        agent_id: AgentId::new(agent).expect("agent id"),
        agent_type: AgentType::new(role.carrier()).expect("agent type"),
        role,
        lane: Some(LaneId::new("l1-engine").expect("lane id")),
        parent_agent_id: None,
        session_id: SessionId::new("session-native-1").expect("session id"),
        write_scope: vec!["crates/core/src/dispatch/**".into()],
        model: Some("frontier".into()),
        capability_contract,
        capability_probe: CapabilityProbe::new(
            observed,
            "native-startup-probe",
            "1.2.3",
            None,
            1_000,
        )
        .expect("capability probe"),
        started_at: 1_000,
        lease_expires_at: 11_000,
        resumes_agent_id: None,
    })
    .expect("dispatch record")
}

fn identity(record: &DispatchRecord, now: i64) -> NativeIdentity {
    NativeIdentity {
        harness: record.harness,
        project_id: record.project_id.clone(),
        run: record.run.clone(),
        lane: record.lane.clone(),
        session_id: record.session_id.clone(),
        agent_id: Some(record.agent_id.clone()),
        agent_type: Some(record.agent_type.clone()),
        role: Some(record.role),
        tool_call_id: Some("fresh-per-tool-id".into()),
        now,
        root_binding: None,
    }
}

fn root_binding(run: &str, session: &str) -> RootSessionBinding {
    RootSessionBinding {
        schema: ROOT_SESSION_SCHEMA.into(),
        project_id: ProjectId::new("018f47ce-72d7-7f64-9eb1-2f651d521c2a").expect("project id"),
        run: RunId::new(run).expect("run id"),
        harness: Harness::ClaudeCode,
        session_id: SessionId::new(session).expect("session id"),
        role: Role::Shepherd,
        mode: "execution".into(),
        bound_at: 1_000,
        expires_at: 11_000,
    }
}

#[test]
fn active_run_resolution_is_exact_and_rejects_multiple_executing_runs() {
    let dir = fixture_dir("active");
    let runs = dir.join("primary/.shepherd/runs");
    write_run(&runs, "v645", "executing");
    write_run(&runs, "v646", "executing");
    let store = DispatchStore::new(&runs);

    assert!(matches!(
        store.resolve_active_run(),
        Err(DispatchStoreError::AmbiguousActiveRuns { ref runs })
            if runs == &[RunId::new("v645").unwrap(), RunId::new("v646").unwrap()]
    ));

    write_run(&runs, "v646", "closed");
    assert_eq!(
        store.resolve_active_run().expect("one active run"),
        RunId::new("v645").expect("run id")
    );
    cleanup(&dir);
}

#[test]
fn malformed_nested_and_non_object_run_documents_never_activate() {
    let dir = fixture_dir("malformed-run");
    let runs = dir.join("primary/.shepherd/runs");
    let run_dir = runs.join("v645");
    std::fs::create_dir_all(&run_dir).expect("run dir");
    let store = DispatchStore::new(&runs);

    std::fs::write(run_dir.join("run.json"), b"{\"run\":\"v645\"").expect("write malformed run");
    assert!(matches!(
        store.resolve_active_run(),
        Err(DispatchStoreError::InvalidRunDocument { .. })
    ));

    std::fs::write(
        run_dir.join("run.json"),
        br#"{"run":"v645","status":"closed","nested":{"status":"executing"}}"#,
    )
    .expect("write nested status");
    assert!(matches!(
        store.resolve_active_run(),
        Err(DispatchStoreError::NoActiveRun)
    ));

    std::fs::write(run_dir.join("run.json"), b"[]").expect("write non-object run");
    assert!(matches!(
        store.resolve_active_run(),
        Err(DispatchStoreError::InvalidRunDocument { .. })
    ));
    cleanup(&dir);
}

#[test]
fn publication_is_no_clobber_and_stop_is_expected_revision_atomic() {
    let dir = fixture_dir("lifecycle");
    let runs = dir.join("primary/.shepherd/runs");
    write_run(&runs, "v645", "executing");
    let store = DispatchStore::new(&runs);
    let initial = record("claude-agent-1", "v645", Role::Coder, Harness::ClaudeCode);

    store
        .publish_active(&initial)
        .expect("first publication succeeds");
    let path = runs.join("v645/dispatch/claude-agent-1.json");
    let before = std::fs::read(&path).expect("read first record");
    assert!(matches!(
        store.publish_active(&initial),
        Err(DispatchStoreError::AlreadyExists { .. })
    ));
    assert_eq!(std::fs::read(&path).expect("read after no-clobber"), before);

    assert!(matches!(
        store.stop_active(StopRequest {
            agent_id: initial.agent_id.clone(),
            expected_revision: 9,
            stopped_at: 2_000,
            result_artifact: Some("lanes/l1-engine/reports/claude-agent-1.md".into()),
        }),
        Err(DispatchStoreError::Domain(_))
    ));
    assert_eq!(
        std::fs::read(&path).expect("read after stale update"),
        before
    );

    let stopped = store
        .stop_active(StopRequest {
            agent_id: initial.agent_id.clone(),
            expected_revision: 1,
            stopped_at: 2_000,
            result_artifact: Some("lanes/l1-engine/reports/claude-agent-1.md".into()),
        })
        .expect("stop succeeds");
    assert_eq!(stopped.state, DispatchState::Stopped);
    assert_eq!(stopped.revision, 2);
    assert_eq!(store.load_active(&initial.agent_id).unwrap(), stopped);
    cleanup(&dir);
}

#[test]
fn root_session_binding_is_durable_no_clobber_and_primary_run_scoped() {
    let dir = fixture_dir("root-binding");
    let runs = dir.join("primary/.shepherd/runs");
    write_run(&runs, "v645", "executing");
    let store = DispatchStore::new(&runs);
    let binding = root_binding("v645", "session-root-1");

    store
        .publish_root_binding(&binding)
        .expect("first root binding publication succeeds");
    assert_eq!(
        store
            .load_active_root_binding(&binding.session_id)
            .expect("load durable root binding"),
        binding,
    );
    assert!(matches!(
        store.publish_root_binding(&binding),
        Err(DispatchStoreError::AlreadyExists { .. })
    ));

    let wrong_run = root_binding("v646", "session-root-2");
    assert!(matches!(
        store.publish_root_binding(&wrong_run),
        Err(DispatchStoreError::WrongActiveRun { .. })
    ));
    cleanup(&dir);
}

#[test]
fn oversized_publication_fails_before_exposing_a_record() {
    let dir = fixture_dir("oversized-publication");
    let runs = dir.join("primary/.shepherd/runs");
    write_run(&runs, "v645", "executing");
    let store = DispatchStore::new(&runs);
    let mut oversized = record(
        "claude-agent-oversized",
        "v645",
        Role::Coder,
        Harness::ClaudeCode,
    );
    let contract = oversized
        .role
        .dispatch_capability_contract()
        .expect("compiled contract");
    let mut observed = contract
        .required
        .union(&contract.optional)
        .cloned()
        .collect::<std::collections::BTreeSet<_>>();
    for index in 0..12_000 {
        observed.insert(format!("extra-{index:05}-{}", "x".repeat(90)));
    }
    oversized.capabilities = contract.evaluate(
        CapabilityProbe::new(observed, "native-startup-probe", "1.2.3", None, 1_000)
            .expect("large probe remains structurally valid"),
    );
    oversized.validate_loaded().expect("large record is valid");

    assert!(store.publish_active(&oversized).is_err());
    assert!(
        !runs
            .join("v645/dispatch/claude-agent-oversized.json")
            .exists(),
        "failed publication must not leave a visible record",
    );
    cleanup(&dir);
}

#[test]
fn malformed_records_and_arbitrary_roles_resolve_typed_unknown() {
    let dir = fixture_dir("malformed-record");
    let runs = dir.join("primary/.shepherd/runs");
    write_run(&runs, "v645", "executing");
    let dispatch = runs.join("v645/dispatch");
    std::fs::create_dir_all(&dispatch).expect("dispatch dir");
    let store = DispatchStore::new(&runs);
    let agent = AgentId::new("claude-agent-invalid").expect("agent id");

    std::fs::write(dispatch.join("claude-agent-invalid.json"), b"{broken")
        .expect("write malformed record");
    assert!(matches!(
        store.load_active(&agent),
        Err(DispatchStoreError::UnknownRecord { .. })
    ));

    let mut value = serde_json::to_value(record(
        "claude-agent-invalid",
        "v645",
        Role::Coder,
        Harness::ClaudeCode,
    ))
    .expect("record value");
    value["role"] = serde_json::json!("arbitrary-admin");
    std::fs::write(
        dispatch.join("claude-agent-invalid.json"),
        serde_json::to_vec(&value).expect("record bytes"),
    )
    .expect("write forged role");
    assert!(matches!(
        store.load_active(&agent),
        Err(DispatchStoreError::UnknownRecord { .. })
    ));
    cleanup(&dir);
}

#[test]
fn native_resolution_is_fail_closed_for_missing_wrong_run_wrong_lane_and_stale_records() {
    let dir = fixture_dir("resolve");
    let runs = dir.join("primary/.shepherd/runs");
    write_run(&runs, "v645", "executing");
    let store = DispatchStore::new(&runs);
    let record = record("codex-agent-1", "v645", Role::Worker, Harness::Codex);
    let native = identity(&record, 2_000);

    assert!(matches!(
        store.resolve_active_identity(&native),
        Err(DispatchStoreError::UnknownRecord { .. })
    ));
    store.publish_active(&record).expect("publish record");

    let mut wrong_run = native.clone();
    wrong_run.run = RunId::new("v646").expect("run id");
    assert!(matches!(
        store.resolve_active_identity(&wrong_run),
        Err(DispatchStoreError::WrongActiveRun { .. })
    ));

    let mut wrong_lane = native.clone();
    wrong_lane.lane = Some(LaneId::new("l9-other").expect("lane id"));
    assert!(matches!(
        store.resolve_active_identity(&wrong_lane),
        Err(DispatchStoreError::Identity(_))
    ));

    let mut stale = native;
    stale.now = 11_000;
    assert!(matches!(
        store.resolve_active_identity(&stale),
        Err(DispatchStoreError::Identity(_))
    ));
    cleanup(&dir);
}

#[cfg(unix)]
#[test]
fn symlinked_roots_runs_dispatch_dirs_and_records_are_rejected_without_escape() {
    use std::os::unix::fs::symlink;

    let dir = fixture_dir("symlinks");
    let outside = dir.join("outside");
    std::fs::create_dir_all(&outside).expect("outside dir");

    let linked_runs = dir.join("linked-runs");
    symlink(&outside, &linked_runs).expect("runs symlink");
    assert!(matches!(
        DispatchStore::new(&linked_runs).resolve_active_run(),
        Err(DispatchStoreError::UnsafePath { .. })
    ));

    let redirected_namespace = dir.join("redirected-namespace");
    std::fs::create_dir_all(redirected_namespace.join("runs")).expect("outside namespace runs");
    let primary = dir.join("ancestor-primary");
    std::fs::create_dir_all(&primary).expect("primary root");
    symlink(&redirected_namespace, primary.join(".shepherd")).expect("namespace ancestor symlink");
    assert!(matches!(
        DispatchStore::new(primary.join(".shepherd/runs")).resolve_active_run(),
        Err(DispatchStoreError::UnsafePath { .. })
    ));

    let runs = dir.join("primary/.shepherd/runs");
    std::fs::create_dir_all(&runs).expect("runs root");
    symlink(&outside, runs.join("v645")).expect("run symlink");
    assert!(matches!(
        DispatchStore::new(&runs).resolve_active_run(),
        Err(DispatchStoreError::UnsafePath { .. })
    ));
    std::fs::remove_file(runs.join("v645")).expect("remove run symlink");

    write_run(&runs, "v645", "executing");
    symlink(&outside, runs.join("v645/dispatch")).expect("dispatch symlink");
    let store = DispatchStore::new(&runs);
    let dispatch_record = record("claude-symlink", "v645", Role::Coder, Harness::ClaudeCode);
    assert!(matches!(
        store.publish_active(&dispatch_record),
        Err(DispatchStoreError::UnsafePath { .. })
    ));
    assert!(!outside.join("claude-symlink.json").exists());

    std::fs::remove_file(runs.join("v645/dispatch")).expect("remove dispatch symlink");
    std::fs::create_dir(runs.join("v645/dispatch")).expect("dispatch dir");
    let outside_record = outside.join("outside.json");
    std::fs::write(&outside_record, b"forged").expect("outside record");
    symlink(
        &outside_record,
        runs.join("v645/dispatch/claude-symlink.json"),
    )
    .expect("record symlink");
    assert!(matches!(
        store.load_active(&dispatch_record.agent_id),
        Err(DispatchStoreError::UnsafePath { .. })
    ));
    cleanup(&dir);
}

#[test]
fn primary_store_ignores_a_linked_shadow_record() {
    let dir = fixture_dir("primary-only");
    let primary_runs = dir.join("primary/.shepherd/runs");
    let linked_runs = dir.join("linked/.shepherd/runs");
    write_run(&primary_runs, "v645", "executing");
    write_run(&linked_runs, "v645", "executing");
    let primary = DispatchStore::new(&primary_runs);
    let linked = DispatchStore::new(&linked_runs);
    let primary_record = record("shared-agent", "v645", Role::Coder, Harness::ClaudeCode);
    let linked_record = record("shared-agent", "v645", Role::Auditor, Harness::ClaudeCode);
    primary
        .publish_active(&primary_record)
        .expect("primary record");
    linked
        .publish_active(&linked_record)
        .expect("linked shadow");

    assert_eq!(
        primary
            .load_active(&primary_record.agent_id)
            .expect("load primary"),
        primary_record
    );
    cleanup(&dir);
}
