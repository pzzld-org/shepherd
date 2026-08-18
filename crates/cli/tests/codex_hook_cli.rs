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
        "shepherd-codex-hook-{label}-{}-{nonce:x}",
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
    native_hook(root, input, "codex-hook")
}

fn claude_hook(root: &Path, input: serde_json::Value) -> Output {
    native_hook(root, input, "claude-hook")
}

fn native_hook(root: &Path, input: serde_json::Value, command: &str) -> Output {
    let mut child = Command::new(binary())
        .arg(command)
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn shepherd codex hook");
    child
        .stdin
        .take()
        .expect("hook stdin")
        .write_all(&serde_json::to_vec(&input).expect("encode hook input"))
        .expect("write hook input");
    child.wait_with_output().expect("wait for hook")
}

#[test]
fn session_start_binds_codex_root_and_safe_pretooluse_allows() {
    let root = repository("root-allow");
    let session = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SessionStart",
            "session_id": "codex-session-a",
            "provider_version": "0.147.0"
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
    let binding_path = root.join(".shepherd/runs/v645/dispatch/.root-session.codex-session-a.json");
    let binding: serde_json::Value = serde_json::from_slice(
        &fs::read(&binding_path).expect("Codex root-session binding is persisted"),
    )
    .expect("root-session binding is JSON");
    assert_eq!(binding["harness"], "codex");

    let safe = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "codex-session-a",
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
fn pretooluse_denies_an_unbound_codex_mutation() {
    let root = repository("deny");
    let denied = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "unbound-codex-session",
            "tool_use_id": "deny-tool-a",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** End Patch"}
        }),
    );
    assert!(
        denied.status.success(),
        "PreToolUse must emit a fail-closed Codex denial: stderr={}",
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
fn malformed_codex_input_is_a_fail_closed_host_response() {
    let root = repository("malformed");
    let mut malformed = Command::new(binary())
        .arg("codex-hook")
        .current_dir(&root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn malformed Codex hook");
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
    assert!(
        malformed["hookSpecificOutput"]["permissionDecisionReason"]
            .as_str()
            .is_some_and(|reason| reason.contains("Codex"))
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}

#[test]
fn codex_subagent_lifecycle_is_rejected_without_a_trusted_host_contract() {
    let root = repository("lifecycle");
    let session = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SessionStart",
            "session_id": "codex-session-lifecycle"
        }),
    );
    assert!(session.status.success());

    let started = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SubagentStart",
            "session_id": "codex-session-lifecycle",
            "agent_id": "codex-agent-lifecycle",
            "agent_type": "worker",
            "model": "gpt-5.5",
            "permission_mode": "default",
            "cwd": root,
            "transcript_path": null,
            "turn_id": "turn-lifecycle",
        }),
    );
    assert!(
        started.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&started.stderr)
    );
    let started_output: serde_json::Value =
        serde_json::from_slice(&started.stdout).expect("SubagentStart output is JSON");
    assert!(
        started_output["hookSpecificOutput"]["additionalContext"]
            .as_str()
            .is_some_and(|detail| detail.contains("no trusted lifecycle correlation")),
        "unexpected output: {}",
        started_output
    );
    assert!(
        !root
            .join(".shepherd/runs/v645/dispatch/codex-agent-lifecycle.json")
            .exists()
    );

    let stopped = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SubagentStop",
            "session_id": "codex-session-lifecycle",
            "agent_id": "codex-agent-lifecycle",
            "agent_type": "worker",
            "model": "gpt-5.5",
            "permission_mode": "default",
            "cwd": root,
            "transcript_path": null,
            "turn_id": "turn-lifecycle",
        }),
    );
    assert!(
        stopped.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&stopped.stderr)
    );
    let stopped: serde_json::Value =
        serde_json::from_slice(&stopped.stdout).expect("SubagentStop output is JSON");
    assert!(
        stopped["reason"]
            .as_str()
            .is_some_and(|reason| reason.contains("no trusted lifecycle correlation")),
        "unexpected output: {}",
        stopped
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}

#[test]
fn native_child_binding_requires_an_explicit_write_scope() {
    let root = repository("missing-scope");
    let started = claude_hook(
        &root,
        serde_json::json!({
            "hook_event_name": "SubagentStart",
            "session_id": "codex-session-missing-scope",
            "agent_id": "codex-agent-missing-scope",
            "agent_type": "worker",
            "shepherd_dispatch": {
                "run": "v645",
                "role": "coder",
                "lane": "l1-engine",
                "model": "gpt-5.5",
                "observed_capabilities": [
                    "read", "search", "shell", "write", "skill-load", "tool-discovery", "subagent-provider"
                ],
                "capability_source": "codex-hook-test",
                "harness_version": "test",
                "provider_version": "0.147.0",
                "lease_ms": 60000
            }
        }),
    );
    assert!(started.status.success());
    let output: serde_json::Value =
        serde_json::from_slice(&started.stdout).expect("missing-scope output is JSON");
    assert!(
        output["hookSpecificOutput"]["additionalContext"]
            .as_str()
            .is_some_and(|detail| detail.contains("write_scope is required")),
        "unexpected output: {}",
        output
    );
    assert!(
        !root
            .join(".shepherd/runs/v645/dispatch/codex-agent-missing-scope.json")
            .exists()
    );
    fs::remove_dir_all(root).expect("remove fixture directory");
}
