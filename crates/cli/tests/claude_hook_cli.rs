use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Output, Stdio},
    time::{SystemTime, UNIX_EPOCH},
};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn fixture_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-claude-hook-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("create fixture directory");
    root
}

fn repository(label: &str) -> PathBuf {
    let root = fixture_dir(label);
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("initialize fixture repository");
    assert!(status.success());
    fs::create_dir_all(root.join(".shepherd/runs/v645/dispatch")).expect("create run namespace");
    fs::write(
        root.join(".shepherd/project.json"),
        br#"{"id":"018f47ce-72d7-7f64-9eb1-2f651d521c2a","scaffolded_at":1000}"#,
    )
    .expect("write project identity");
    fs::write(
        root.join(".shepherd/runs/v645/run.json"),
        br#"{"run":"v645","status":"executing"}"#,
    )
    .expect("write active run");
    root
}

fn hook(root: &Path, input: serde_json::Value) -> Output {
    let mut child = Command::new(binary())
        .args(["claude-hook"])
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn shepherd claude hook");
    child
        .stdin
        .take()
        .expect("hook stdin")
        .write_all(&serde_json::to_vec(&input).expect("encode hook input"))
        .expect("write hook input");
    child.wait_with_output().expect("wait for hook")
}

#[test]
fn session_start_binds_root_and_safe_pretooluse_allows() {
    let root = repository("root-allow");
    let session = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SessionStart",
            "session_id": "claude-session-a"
        }),
    );
    assert!(
        session.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&session.stderr)
    );
    let output: serde_json::Value =
        serde_json::from_slice(&session.stdout).expect("SessionStart hook output is JSON");
    assert_eq!(
        output["hookSpecificOutput"]["hookEventName"],
        "SessionStart"
    );
    assert!(
        root.join(".shepherd/runs/v645/dispatch/.root-session.claude-session-a.json")
            .is_file()
    );

    let safe = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "claude-session-a",
            "tool_use_id": "safe-tool-a",
            "tool_name": "Bash",
            "tool_input": {"command": "printf safe"}
        }),
    );
    assert!(
        safe.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&safe.stderr)
    );
    assert!(safe.stdout.is_empty(), "safe tool use must emit no denial");
    fs::remove_dir_all(root).expect("remove fixture directory");
}

#[test]
fn pretooluse_denies_unresolved_or_unbound_requests() {
    let root = repository("deny");
    // The run is healthy, so an unattributed session is a real refusal rather
    // than a symptom of shepherd's own bookkeeping being broken.
    let denied = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "unbound-session",
            "tool_use_id": "deny-tool-a",
            "tool_name": "Write",
            "tool_input": {"file_path": "README.md", "content": "nope"}
        }),
    );
    assert!(
        denied.status.success(),
        "PreToolUse must emit a fail-closed Claude denial instead of crashing: stderr={}",
        String::from_utf8_lossy(&denied.stderr)
    );
    let output: serde_json::Value =
        serde_json::from_slice(&denied.stdout).expect("denial output is JSON");
    assert_eq!(output["hookSpecificOutput"]["hookEventName"], "PreToolUse");
    assert_eq!(output["hookSpecificOutput"]["permissionDecision"], "deny");
    assert!(
        output["hookSpecificOutput"]["permissionDecisionReason"]
            .as_str()
            .is_some_and(|reason| !reason.is_empty())
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}

#[test]
fn malformed_input_and_unbound_subagent_events_have_safe_host_outputs() {
    let root = repository("malformed-and-blocked");
    let mut malformed = Command::new(binary())
        .args(["claude-hook"])
        .current_dir(&root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn malformed hook");
    malformed
        .stdin
        .take()
        .expect("malformed stdin")
        .write_all(b"{")
        .expect("write malformed input");
    let malformed = malformed.wait_with_output().expect("wait malformed hook");
    assert!(malformed.status.success());
    let malformed: serde_json::Value =
        serde_json::from_slice(&malformed.stdout).expect("malformed input denial is JSON");
    assert_eq!(
        malformed["hookSpecificOutput"]["permissionDecision"],
        "deny"
    );

    // An in-flock SubagentStart is now recorded rather than rejected, so the
    // unresolvable case is an agent type outside the closed flock -- which is
    // what this assertion was really about.
    let blocked = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SubagentStart",
            "session_id": "claude-session-blocked",
            "agent_id": "claude-agent-blocked",
            "agent_type": "general-purpose"
        }),
    );
    assert!(blocked.status.success());
    let blocked: serde_json::Value =
        serde_json::from_slice(&blocked.stdout).expect("blocked lifecycle context is JSON");
    assert_eq!(
        blocked["hookSpecificOutput"]["hookEventName"],
        "SubagentStart"
    );
    assert!(
        blocked["hookSpecificOutput"]["additionalContext"]
            .as_str()
            .is_some_and(|detail| detail.contains("rejected"))
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}

#[test]
fn subagent_stop_blocks_when_dispatch_cannot_be_resolved() {
    let root = repository("stop-unresolved");
    let stopped = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SubagentStop",
            "session_id": "claude-session-unresolved",
            "agent_id": "claude-agent-unresolved",
            "agent_type": "coder"
        }),
    );
    assert!(
        stopped.status.success(),
        "SubagentStop must return Claude's blocking decision instead of crashing: stderr={}",
        String::from_utf8_lossy(&stopped.stderr)
    );
    let output: serde_json::Value =
        serde_json::from_slice(&stopped.stdout).expect("blocked stop output is JSON");
    assert_eq!(output["decision"], "block");
    assert!(
        output["reason"]
            .as_str()
            .is_some_and(|reason| reason.contains("rejected")),
        "blocking stop output must explain why the lifecycle transition was rejected: {output}"
    );
    assert!(output.get("hookSpecificOutput").is_none());
    fs::remove_dir_all(root).expect("remove fixture directory");
}

#[test]
fn lifecycle_start_and_stop_follow_the_native_dispatch_ledger() {
    let root = repository("lifecycle");
    let session = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SessionStart",
            "session_id": "claude-session-lifecycle"
        }),
    );
    assert!(session.status.success());

    let binding = serde_json::json!({
        "run": "v645",
        "role": "coder",
        "lane": "l1-engine",
        "write_scope": ["crates/core/src/dispatch/**"],
        "model": "claude-sonnet-5",
        "observed_capabilities": [
            "read", "search", "shell", "write", "skill-load", "tool-discovery", "subagent-provider"
        ],
        "capability_source": "claude-hook-test",
        "harness_version": "test",
        "lease_ms": 60000
    });
    let started = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SubagentStart",
            "session_id": "claude-session-lifecycle",
            "agent_id": "claude-agent-lifecycle",
            "agent_type": "coder",
            "shepherd_dispatch": binding
        }),
    );
    assert!(
        started.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&started.stderr)
    );
    assert!(
        root.join(".shepherd/runs/v645/dispatch/claude-agent-lifecycle.json")
            .is_file()
    );

    let stopped = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SubagentStop",
            "session_id": "claude-session-lifecycle",
            "agent_id": "claude-agent-lifecycle",
            "agent_type": "coder",
            "shepherd_dispatch": {
                "run": "v645",
                "lane": "l1-engine",
                "expected_revision": 1,
                "result_artifact": "lanes/l1-engine/reports/claude-agent-lifecycle.md"
            }
        }),
    );
    assert!(
        stopped.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&stopped.stderr)
    );
    let record: serde_json::Value = serde_json::from_slice(
        &fs::read(root.join(".shepherd/runs/v645/dispatch/claude-agent-lifecycle.json"))
            .expect("read stopped dispatch record"),
    )
    .expect("decode stopped dispatch record");
    assert_eq!(record["state"], "stopped");
    fs::remove_dir_all(root).expect("remove fixture directory");
}

/// A run shepherd cannot attribute against must not disable the tools that
/// repair it.
///
/// This is the v6.4.6 dogfooding deadlock: the `Write|Edit|Bash|Agent|Workflow`
/// matcher covers the entire repair surface, so one unusable run namespace made
/// the session structurally incapable of fixing its own run state.
#[test]
fn broken_run_namespace_allows_tools_instead_of_stranding_the_session() {
    let root = repository("broken-namespace");
    // Exactly the v646 state: a run that exists but is not executing.
    fs::write(
        root.join(".shepherd/runs/v645/run.json"),
        br#"{"run":"v645","status":"planted"}"#,
    )
    .expect("write non-executing run");

    let blocked = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "stranded-session",
            "tool_use_id": "repair-tool-a",
            "tool_name": "Write",
            "tool_input": {"file_path": ".shepherd/runs/v645/run.json", "content": "{}"}
        }),
    );
    assert!(blocked.status.success());
    let output: serde_json::Value =
        serde_json::from_slice(&blocked.stdout).expect("hook output is JSON");
    assert_ne!(
        output["hookSpecificOutput"]["permissionDecision"], "deny",
        "a broken run namespace must not deny the tools that repair it: {output}"
    );
    assert!(
        output["hookSpecificOutput"]["additionalContext"]
            .as_str()
            .is_some_and(|detail| detail.contains("no usable run namespace")),
        "the fault must be surfaced, not swallowed: {output}"
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}

/// `shepherd` invoking itself is always permitted, so a session can never be
/// denied the one command that repairs the state doing the denying.
#[test]
fn shepherd_self_repair_is_always_permitted() {
    let root = repository("self-repair");
    let repair = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "unbound-session",
            "tool_use_id": "repair-tool-b",
            "tool_name": "Bash",
            "tool_input": {"command": "shepherd run set v645 --status executing"}
        }),
    );
    assert!(repair.status.success());
    let output: serde_json::Value =
        serde_json::from_slice(&repair.stdout).expect("hook output is JSON");
    assert_ne!(
        output["hookSpecificOutput"]["permissionDecision"], "deny",
        "shepherd self-repair must never be denied: {output}"
    );

    // The exemption is narrow: chaining past it is refused, so it cannot be
    // used to smuggle an unrelated command through an unbound session.
    let chained = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "unbound-session",
            "tool_use_id": "repair-tool-c",
            "tool_name": "Bash",
            "tool_input": {"command": "shepherd --version; rm -rf /tmp/shepherd-escape"}
        }),
    );
    assert!(chained.status.success());
    let chained: serde_json::Value =
        serde_json::from_slice(&chained.stdout).expect("hook output is JSON");
    assert_eq!(
        chained["hookSpecificOutput"]["permissionDecision"], "deny",
        "a chained command must not ride the self-repair exemption: {chained}"
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}

/// A host tool envelope carries no `shepherd_dispatch` block, so the tool name
/// never reached the resolver, no write paths were derived, and the guard
/// refused every `Write` and `Edit` a root session attempted for lack of them.
#[test]
fn root_session_may_write_inside_the_repository_but_not_outside_it() {
    let root = repository("root-write");
    let session = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SessionStart",
            "session_id": "claude-session-write"
        }),
    );
    assert!(session.status.success());

    let inside = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "claude-session-write",
            "tool_use_id": "write-inside",
            "tool_name": "Write",
            // Relative: the fixture root resolves through a /var -> /private/var
            // symlink on macOS, which is a temp-dir artifact, not a scope escape.
            "tool_input": {"file_path": "notes.md", "content": "ok"}
        }),
    );
    assert!(
        inside.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&inside.stderr)
    );
    assert!(
        inside.stdout.is_empty(),
        "a root session must be able to write inside its own repository: {}",
        String::from_utf8_lossy(&inside.stdout)
    );

    // Deriving the path is what makes the scope check meaningful, so the
    // escape must still be refused rather than passing for want of a path.
    let outside = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "claude-session-write",
            "tool_use_id": "write-outside",
            "tool_name": "Write",
            "tool_input": {"file_path": "/etc/passwd", "content": "no"}
        }),
    );
    assert!(outside.status.success());
    let outside: serde_json::Value =
        serde_json::from_slice(&outside.stdout).expect("hook output is JSON");
    assert_eq!(
        outside["hookSpecificOutput"]["permissionDecision"], "deny",
        "a write outside the primary repository must stay refused: {outside}"
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}

/// `PostToolUse` resolves like `PreToolUse` but must not be gated by it: a
/// verdict about a call that already ran is advice, and it was being emitted
/// under a hardcoded `PreToolUse` label.
#[test]
fn post_tool_use_records_without_running_the_pre_flight_guard() {
    let root = repository("post-tool-use");
    let session = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SessionStart",
            "session_id": "claude-session-post"
        }),
    );
    assert!(session.status.success());

    // The same shape that PreToolUse refuses outside the repository.
    let after = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PostToolUse",
            "session_id": "claude-session-post",
            "tool_use_id": "post-tool-a",
            "tool_name": "Write",
            "tool_input": {"file_path": "/etc/passwd", "content": "no"}
        }),
    );
    assert!(
        after.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&after.stderr)
    );
    let text = String::from_utf8_lossy(&after.stdout);
    assert!(
        !text.contains("\"permissionDecision\""),
        "PostToolUse must not emit a permission decision: {text}"
    );
    assert!(
        !text.contains("PreToolUse"),
        "PostToolUse must never label its output PreToolUse: {text}"
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}

/// The dispatch ledger stayed empty on every harness: `SubagentStart` blocked
/// on a missing binding because a host envelope carries no `shepherd_dispatch`
/// block and has no way to add one. With no record, no tool call could be
/// attributed to a role, so not one role-scoped guard rule could ever fire.
#[test]
fn dispatched_agents_are_recorded_and_their_role_rules_enforce() {
    let root = repository("subagent-ledger");
    assert!(
        hook(
            &root,
            serde_json::json!({"hook_event_name": "SessionStart", "session_id": "s1"})
        )
        .status
        .success()
    );

    for (agent, agent_type) in [
        ("cond-1", "shepherd:conductor"),
        ("code-1", "shepherd:coder"),
    ] {
        let started = hook(
            &root,
            serde_json::json!({
                "hook_event_name": "SubagentStart",
                "session_id": "s1",
                "agent_id": agent,
                "agent_type": agent_type,
                "model": "test-model"
            }),
        );
        assert!(started.status.success());
        assert!(
            root.join(format!(".shepherd/runs/v645/dispatch/{agent}.json"))
                .is_file(),
            "{agent_type} must be recorded in the dispatch ledger"
        );
    }

    // Tool calls carry agent_id only; the record supplies the type.
    let decision = |agent: &str, tool: &str, input: serde_json::Value| -> String {
        let out = hook(
            &root,
            serde_json::json!({
                "hook_event_name": "PreToolUse",
                "session_id": "s1",
                "agent_id": agent,
                "tool_use_id": format!("{agent}-{tool}"),
                "tool_name": tool,
                "tool_input": input
            }),
        );
        assert!(out.status.success());
        String::from_utf8_lossy(&out.stdout).into_owned()
    };

    assert!(
        decision(
            "cond-1",
            "Bash",
            serde_json::json!({"command": "printf hi"})
        )
        .is_empty(),
        "a recorded conductor may run a safe shell command"
    );
    assert!(
        decision(
            "cond-1",
            "Agent",
            serde_json::json!({"subagent_type": "shepherd:coder"})
        )
        .is_empty(),
        "a conductor may dispatch an implementer"
    );
    assert!(
        decision(
            "cond-1",
            "Agent",
            serde_json::json!({"subagent_type": "shepherd:engineer"})
        )
        .contains("deny"),
        "a conductor must not dispatch the plan-author role"
    );
    assert!(
        decision(
            "code-1",
            "Agent",
            serde_json::json!({"subagent_type": "shepherd:worker"})
        )
        .contains("deny"),
        "an implementer must not dispatch at all"
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}
