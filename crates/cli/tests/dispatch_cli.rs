use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn fixture_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "shepherd-dispatch-cli-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    std::fs::create_dir_all(&path).expect("fixture");
    path
}

fn repository(label: &str) -> PathBuf {
    let root = fixture_dir(label);
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("git init");
    assert!(status.success());
    std::fs::create_dir_all(root.join(".shepherd/runs/v645")).expect("namespace");
    std::fs::write(
        root.join(".shepherd/project.json"),
        br#"{"id":"018f47ce-72d7-7f64-9eb1-2f651d521c2a","scaffolded_at":1000}"#,
    )
    .expect("project identity");
    std::fs::write(
        root.join(".shepherd/runs/v645/run.json"),
        br#"{"run":"v645","status":"executing"}"#,
    )
    .expect("run state");
    root
}

fn run(root: &Path, args: &[&str], input: &serde_json::Value) -> Output {
    let mut child = Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn shepherd");
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all(&serde_json::to_vec(input).expect("request bytes"))
        .expect("write request");
    child.wait_with_output().expect("wait shepherd")
}

fn start_request() -> serde_json::Value {
    serde_json::json!({
        "schema": "shepherd.dispatch-request/1",
        "run": "v645",
        "harness": "claude",
        "agent_id": "claude-native-1",
        "agent_type": "shepherd:coder",
        "role_carrier": "shepherd:coder",
        "lane": "l1-engine",
        "parent_agent_id": null,
        "session_id": "session-1",
        "write_scope": ["crates/core/src/dispatch/**"],
        "model": "claude-sonnet-5",
        "observed_capabilities": [
            "read", "search", "shell", "skill-load", "write", "tool-discovery",
            "subagent-provider"
        ],
        "capability_source": "claude-installed-agent-probe",
        "harness_version": "2.1.218",
        "provider_version": null,
        "lease_ms": 60000
    })
}

#[test]
fn binary_start_resolve_and_stop_use_the_primary_active_run() {
    let root = repository("lifecycle");
    let start = run(&root, &["dispatch", "start"], &start_request());
    assert!(
        start.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&start.stderr)
    );
    let record: serde_json::Value = serde_json::from_slice(&start.stdout).expect("start response");
    assert_eq!(record["schema"], "shepherd.dispatch/3");
    assert_eq!(record["agent_id"], "claude-native-1");
    assert!(
        root.join(".shepherd/runs/v645/dispatch/claude-native-1.json")
            .is_file()
    );

    let resolve = run(
        &root,
        &["dispatch", "resolve"],
        &serde_json::json!({
            "schema": "shepherd.dispatch-request/1",
            "run": "v645",
            "harness": "claude",
            "agent_id": "claude-native-1",
            "agent_type": "shepherd:coder",
            "role_carrier": "shepherd:coder",
            "lane": "l1-engine",
            "session_id": "session-1",
            "tool_call_id": "fresh-tool-id"
        }),
    );
    assert!(
        resolve.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&resolve.stderr)
    );
    let resolution: serde_json::Value =
        serde_json::from_slice(&resolve.stdout).expect("resolve response");
    assert_eq!(resolution["agent_id"], "claude-native-1");
    assert_eq!(resolution["role"], "coder");

    let stop = run(
        &root,
        &["dispatch", "stop"],
        &serde_json::json!({
            "schema": "shepherd.dispatch-request/1",
            "run": "v645",
            "harness": "claude",
            "agent_id": "claude-native-1",
            "agent_type": "shepherd:coder",
            "role_carrier": "shepherd:coder",
            "lane": "l1-engine",
            "session_id": "session-1",
            "expected_revision": 1,
            "result_artifact": "lanes/l1-engine/reports/claude-native-1.md"
        }),
    );
    assert!(
        stop.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&stop.stderr)
    );
    let stopped: serde_json::Value = serde_json::from_slice(&stop.stdout).expect("stop response");
    assert_eq!(stopped["state"], "stopped");
    assert_eq!(stopped["revision"], 2);
    std::fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn malformed_requests_and_ambiguous_runs_fail_without_publishing() {
    let root = repository("fail-closed");
    std::fs::create_dir_all(root.join(".shepherd/runs/v646")).expect("second run");
    std::fs::write(
        root.join(".shepherd/runs/v646/run.json"),
        br#"{"run":"v646","status":"executing"}"#,
    )
    .expect("second run state");

    let ambiguous = run(&root, &["dispatch", "start"], &start_request());
    assert_eq!(ambiguous.status.code(), Some(1));
    assert!(ambiguous.stdout.is_empty());
    assert!(
        String::from_utf8_lossy(&ambiguous.stderr).contains("multiple executing shepherd runs")
    );
    assert!(
        !root
            .join(".shepherd/runs/v645/dispatch/claude-native-1.json")
            .exists()
    );

    let malformed = Command::new(binary())
        .args(["dispatch", "start"])
        .current_dir(&root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .and_then(|mut child| {
            child.stdin.take().expect("stdin").write_all(b"{broken")?;
            child.wait_with_output()
        })
        .expect("malformed request run");
    assert_eq!(malformed.status.code(), Some(1));
    assert!(malformed.stdout.is_empty());
    assert!(String::from_utf8_lossy(&malformed.stderr).contains("valid RFC 8259 JSON"));
    std::fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn linked_worktree_uses_only_the_primary_project_and_active_run_store() {
    let root = repository("linked-primary");
    let linked = root.with_file_name(format!(
        "{}-linked",
        root.file_name().expect("fixture name").to_string_lossy()
    ));
    let commit = Command::new("git")
        .args([
            "-c",
            "user.name=Shepherd Test",
            "-c",
            "user.email=shepherd-test@example.invalid",
            "commit",
            "--allow-empty",
            "--quiet",
            "-m",
            "fixture",
        ])
        .current_dir(&root)
        .status()
        .expect("fixture commit");
    assert!(commit.success());
    let add = Command::new("git")
        .args(["worktree", "add", "--detach", "--quiet"])
        .arg(&linked)
        .arg("HEAD")
        .current_dir(&root)
        .status()
        .expect("linked worktree");
    assert!(add.success());

    std::fs::create_dir_all(linked.join(".shepherd/runs/v646")).expect("linked shadow");
    std::fs::write(
        linked.join(".shepherd/project.json"),
        br#"{"id":"018f47ce-72d7-7f64-8eb1-2f651d521c2a"}"#,
    )
    .expect("shadow project");
    std::fs::write(
        linked.join(".shepherd/runs/v646/run.json"),
        br#"{"run":"v646","status":"executing"}"#,
    )
    .expect("shadow run");

    let start = run(&linked, &["dispatch", "start"], &start_request());
    assert!(
        start.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&start.stderr)
    );
    let record: serde_json::Value = serde_json::from_slice(&start.stdout).expect("record");
    assert_eq!(record["project_id"], "018f47ce-72d7-7f64-9eb1-2f651d521c2a");
    assert_eq!(record["run"], "v645");
    assert!(
        root.join(".shepherd/runs/v645/dispatch/claude-native-1.json")
            .is_file()
    );
    assert!(!linked.join(".shepherd/runs/v646/dispatch").exists());

    std::fs::remove_dir_all(&linked).expect("cleanup linked");
    std::fs::remove_dir_all(&root).expect("cleanup primary");
}
