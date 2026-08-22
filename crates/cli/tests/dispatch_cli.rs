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

fn repository_missing_identity(label: &str) -> PathBuf {
    let root = fixture_dir(label);
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("git init");
    assert!(status.success());
    std::fs::create_dir_all(root.join(".shepherd/runs/v645")).expect("namespace");
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
    assert_eq!(record["lane"], "l1-engine");
    assert_eq!(
        record["write_scope"],
        serde_json::json!(["crates/core/src/dispatch/**"])
    );
    assert!(
        !(record["lane"].is_null() && record["write_scope"] == serde_json::json!(["**"])),
        "a named dispatch must not receive the root fallback facts: {record}"
    );
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
    assert_eq!(resolution["lane"], "l1-engine");
    assert_eq!(
        resolution["write_scope"],
        serde_json::json!(["crates/core/src/dispatch/**"])
    );
    assert!(
        !(resolution["lane"].is_null() && resolution["write_scope"] == serde_json::json!(["**"])),
        "native resolution must not use the root fallback facts: {resolution}"
    );

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
fn root_resolution_does_not_use_universal_fallback_scope() {
    let root = repository("root-least-authority");
    let session = run(
        &root,
        &["claude-hook"],
        &serde_json::json!({
            "hook_event_name": "SessionStart",
            "session_id": "root-session"
        }),
    );
    assert!(
        session.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&session.stderr)
    );

    let resolve = run(
        &root,
        &["dispatch", "resolve"],
        &serde_json::json!({
            "schema": "shepherd.dispatch-request/1",
            "run": "v645",
            "harness": "claude",
            "agent_id": null,
            "agent_type": null,
            "role_carrier": null,
            "lane": null,
            "session_id": "root-session",
            "tool_call_id": "root-tool-id"
        }),
    );
    assert!(
        resolve.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&resolve.stderr)
    );
    let resolution: serde_json::Value =
        serde_json::from_slice(&resolve.stdout).expect("root resolution response");
    assert_eq!(resolution["role"], "shepherd");
    assert!(resolution["lane"].is_null());
    assert_eq!(
        resolution["write_scope"],
        serde_json::json!(["*.md"]),
        "root resolution must use the root-level markdown scope: {resolution}"
    );
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

#[test]
fn dispatch_reports_missing_identity_as_unscaffolded_not_a_symlink_refusal() {
    // GE1: a plain ENOENT on `.shepherd/project.json` (zero symlinks anywhere
    // in this fixture) must be classified as "not scaffolded", never as a
    // refused symlink follow. See w0-gate.md section 8 for the reproduction
    // this test pins.
    let root = repository_missing_identity("missing-identity");
    assert!(!root.join(".shepherd/project.json").exists());

    let start = run(&root, &["dispatch", "start"], &start_request());
    assert!(!start.status.success());
    assert!(start.stdout.is_empty());
    let stderr = String::from_utf8_lossy(&start.stderr);
    assert!(stderr.contains("project not scaffolded"), "stderr={stderr}");
    // End to end companion to the unit assertion in `cmd/dispatch.rs`: the
    // printed remediation has to be runnable verbatim. `init` refuses without
    // `--confirm`, so the flagless form this assertion used to accept sent the
    // operator to an exit-2 dead end on the one path that exists to unblock a
    // cold project.
    assert!(
        stderr.contains("run `shepherd init --confirm`"),
        "stderr={stderr}"
    );
    assert!(
        !stderr.contains("without following symlinks"),
        "stderr={stderr}"
    );
    std::fs::remove_dir_all(root).expect("cleanup");
}

#[cfg(unix)]
#[test]
fn dispatch_refuses_a_symlinked_project_identity() {
    // GE2: an ACTUAL symlink in place of `.shepherd/project.json`, end to
    // end through the CLI. Measured, not assumed: `context.rs`'s
    // `validate_resolved_project_paths` already walks `project_id_path` and
    // refuses any symlink there (`ContextError::NonCanonicalProjectPath`)
    // during `ExecutionContext::discover`, before `dispatch.rs::read_project_id`
    // ever runs. So this exact CLI scenario surfaces that earlier guard's
    // wording ("resolved project path is not canonical"), not dispatch.rs's
    // own NOFOLLOW refusal — dispatch.rs's NOFOLLOW-on-a-symlink branch for
    // the project identity subject is unreachable through the CLI for this
    // reason and is pinned directly instead, in
    // `read_project_id_refuses_a_symlinked_identity_with_the_security_wording`
    // (crates/cli/src/cmd/dispatch.rs). What this test still proves, for
    // real and end to end: a symlinked identity is refused, and refused
    // with a security-shaped message, never with the "not scaffolded"
    // remediation a plain absence gets.
    use std::os::unix::fs::symlink;

    let root = repository("symlinked-identity");
    let target = root.join(".shepherd/identity-target.json");
    std::fs::write(
        &target,
        br#"{"id":"018f47ce-72d7-7f64-9eb1-2f651d521c2a","scaffolded_at":1000}"#,
    )
    .expect("identity target");
    std::fs::remove_file(root.join(".shepherd/project.json")).expect("remove regular identity");
    symlink(&target, root.join(".shepherd/project.json")).expect("symlink identity");

    let start = run(&root, &["dispatch", "start"], &start_request());
    assert!(!start.status.success());
    assert!(start.stdout.is_empty());
    let stderr = String::from_utf8_lossy(&start.stderr);
    assert!(stderr.contains("not canonical"), "stderr={stderr}");
    assert!(
        !stderr.contains("project not scaffolded"),
        "stderr={stderr}"
    );
    std::fs::remove_dir_all(root).expect("cleanup");
}

#[cfg(unix)]
#[test]
fn dispatch_refuses_a_directory_in_place_of_project_identity() {
    // GE3: `.shepherd/project.json` present as a directory must classify as
    // "not a regular file", distinct from both the symlink refusal and the
    // not-scaffolded remediation.
    let root = repository("directory-identity");
    std::fs::remove_file(root.join(".shepherd/project.json")).expect("remove regular identity");
    std::fs::create_dir(root.join(".shepherd/project.json")).expect("directory identity");

    let start = run(&root, &["dispatch", "start"], &start_request());
    assert!(!start.status.success());
    assert!(start.stdout.is_empty());
    let stderr = String::from_utf8_lossy(&start.stderr);
    assert!(stderr.contains("not a regular file"), "stderr={stderr}");
    std::fs::remove_dir_all(root).expect("cleanup");
}

#[cfg(unix)]
#[test]
fn dispatch_directory_identity_gets_the_identity_specific_not_a_regular_file_wording() {
    // GG1 (review follow-up, wave 2 of the identity lane): pins the
    // SUBJECT-VARYING wording that `ReadSubject::not_a_regular_file_message`
    // exists to produce. `dispatch_refuses_a_directory_in_place_of_project_identity`
    // above only checks the shared substring "not a regular file"; this test
    // checks the identity subject's exact prefix, from a REAL on-disk
    // directory (the kernel produces the post-fstat is_file() failure, not a
    // hand-built error), so a regression that collapses both subjects back
    // onto one shared string is caught here even though the shared substring
    // would still match.
    let root = repository("directory-identity-wording");
    std::fs::remove_file(root.join(".shepherd/project.json")).expect("remove regular identity");
    std::fs::create_dir(root.join(".shepherd/project.json")).expect("directory identity");

    let start = run(&root, &["dispatch", "start"], &start_request());
    assert!(!start.status.success());
    assert!(start.stdout.is_empty());
    let stderr = String::from_utf8_lossy(&start.stderr);
    assert!(
        stderr.contains("project identity is not a regular file:"),
        "stderr={stderr}"
    );
    std::fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn dispatch_start_rejects_universal_scope_with_or_without_a_lane() {
    for lane in [Some("l1-engine"), None] {
        let root = repository(if lane.is_some() {
            "universal-named"
        } else {
            "universal-lane-less"
        });
        let mut request = start_request();
        request["write_scope"] = serde_json::json!(["**"]);
        request["lane"] = lane
            .map(serde_json::Value::from)
            .unwrap_or(serde_json::Value::Null);
        let output = run(&root, &["dispatch", "start"], &request);
        assert!(!output.status.success(), "lane={lane:?}");
        assert!(
            String::from_utf8_lossy(&output.stderr)
                .contains("dispatch must provide a bounded write_scope"),
            "lane={lane:?}, stderr={}",
            String::from_utf8_lossy(&output.stderr)
        );
        std::fs::remove_dir_all(root).expect("cleanup");
    }
}
