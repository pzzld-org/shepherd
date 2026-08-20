use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Output, Stdio},
    time::{SystemTime, UNIX_EPOCH},
};

use shepherd_cli::{RunStore, RunStoreError};

fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-harness-regression-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("create fixture root");
    root
}

fn initialize_git(root: &Path) {
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(root)
        .status()
        .expect("initialize fixture repository");
    assert!(status.success(), "git init failed");
}

fn invoke(root: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args(args)
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .output()
        .expect("run shepherd binary")
}

fn hook(root: &Path, input: serde_json::Value) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args(["claude-hook"])
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn native Claude hook");
    child
        .stdin
        .take()
        .expect("hook stdin")
        .write_all(&serde_json::to_vec(&input).expect("encode hook payload"))
        .expect("write hook payload");
    child.wait_with_output().expect("wait for native hook")
}

#[test]
fn legacy_map_shaped_run_loads_and_normalizes_on_first_write() {
    let root = fixture("legacy-map");
    let path = root.join("legacy/run.json");
    fs::create_dir_all(path.parent().expect("run parent")).expect("create run parent");
    fs::write(
        &path,
        br#"{
  "run_id": "legacy",
  "status": "executing",
  "lanes": {
    "V01-STATIC-CONTRACT": {
      "status": "passed",
      "dependencies": [],
      "report": "reports/static-contract.md"
    }
  },
  "audits": {
    "A01": {"status": "passed", "report": "audits/a01.md"}
  }
}
"#,
    )
    .expect("write legacy run state");

    let store = RunStore::new(&path);
    let loaded = store.load().expect("legacy map shape must remain readable");
    assert_eq!(loaded.run, "legacy");
    assert_eq!(loaded.lanes.len(), 1);
    assert_eq!(loaded.lanes[0].id, "V01-STATIC-CONTRACT");
    assert_eq!(loaded.lanes[0].state, "complete");
    assert_eq!(
        loaded.lanes[0].extra.get("report"),
        Some(&serde_json::json!("reports/static-contract.md"))
    );
    assert_eq!(
        loaded.extra.get("audits"),
        Some(&serde_json::json!({
            "A01": {"status": "passed", "report": "audits/a01.md"}
        }))
    );

    store
        .update(|state| {
            state.branch = "v0.3.9-dev.1".into();
            Ok(())
        })
        .expect("first legitimate mutation canonicalizes the legacy document");

    let canonical: serde_json::Value =
        serde_json::from_slice(&fs::read(&path).expect("read canonical state"))
            .expect("canonical state is JSON");
    assert_eq!(canonical["run"], "legacy");
    assert!(canonical.get("run_id").is_none());
    assert!(canonical["lanes"].is_array());
    assert_eq!(canonical["lanes"][0]["id"], "V01-STATIC-CONTRACT");
    assert_eq!(canonical["lanes"][0]["state"], "complete");
    assert_eq!(canonical["audits"]["A01"]["status"], "passed");

    fs::remove_dir_all(root).expect("remove fixture");
}

#[test]
fn legacy_lane_key_conflict_is_rejected_instead_of_silently_relabelled() {
    let root = fixture("legacy-conflict");
    let path = root.join("legacy/run.json");
    fs::create_dir_all(path.parent().expect("run parent")).expect("create run parent");
    fs::write(
        &path,
        br#"{"run_id":"legacy","status":"executing","lanes":{"l1":{"id":"l2"}}}
"#,
    )
    .expect("write conflicting legacy state");

    let error = RunStore::new(&path)
        .load()
        .expect_err("map key and embedded id conflict must fail closed");
    assert!(
        matches!(error, RunStoreError::Validation(_)),
        "unexpected error: {error}"
    );
    let detail = error.to_string();
    assert!(detail.contains("l1") && detail.contains("l2"), "{detail}");

    fs::remove_dir_all(root).expect("remove fixture");
}

#[test]
fn run_set_accepts_branch_and_base_and_advertises_them_in_help() {
    let root = fixture("run-set-ref");
    initialize_git(&root);

    let init = invoke(&root, &["run", "init", "v039-dev2"]);
    assert_eq!(
        init.status.code(),
        Some(0),
        "stderr={}",
        String::from_utf8_lossy(&init.stderr)
    );

    let set = invoke(
        &root,
        &[
            "run",
            "set",
            "v039-dev2",
            "--branch",
            "dev/v0.3.9-dev.2",
            "--base",
            "e00017f79424e0ad95479556c362190b82c956ff",
        ],
    );
    assert_eq!(
        set.status.code(),
        Some(0),
        "stderr={}",
        String::from_utf8_lossy(&set.stderr)
    );

    let state: serde_json::Value = serde_json::from_slice(
        &fs::read(root.join(".shepherd/runs/v039-dev2/run.json")).expect("read run state"),
    )
    .expect("run state is JSON");
    assert_eq!(state["branch"], "dev/v0.3.9-dev.2");
    assert_eq!(state["base"], "e00017f79424e0ad95479556c362190b82c956ff");

    let help = invoke(&root, &["run", "set", "--help"]);
    assert_eq!(help.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&help.stdout);
    assert!(stdout.contains("--branch"), "{stdout}");
    assert!(stdout.contains("--base"), "{stdout}");

    fs::remove_dir_all(root).expect("remove fixture");
}

#[test]
fn malformed_historical_run_cannot_wedge_pretooluse_repair_tools() {
    let root = fixture("hook-repair");
    initialize_git(&root);
    fs::create_dir_all(root.join(".shepherd/runs/broken/dispatch")).expect("create run namespace");
    fs::write(
        root.join(".shepherd/project.json"),
        br#"{"id":"018f47ce-72d7-7f64-9eb1-2f651d521c2a","scaffolded_at":1000}"#,
    )
    .expect("write project identity");
    fs::write(
        root.join(".shepherd/runs/broken/run.json"),
        br#"{"run":"broken","status":"executing","lanes":{"l1":"not-an-object"}}"#,
    )
    .expect("write malformed historical state");

    let output = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "repair-session",
            "tool_use_id": "repair-write",
            "tool_name": "Write",
            "tool_input": {
                "file_path": ".shepherd/runs/broken/run.json",
                "content": "{}"
            }
        }),
    );
    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    let response: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("hook warning is JSON");
    let hook_output = &response["hookSpecificOutput"];
    assert_eq!(hook_output["hookEventName"], "PreToolUse");
    assert!(
        hook_output.get("permissionDecision").is_none()
            || hook_output["permissionDecision"].is_null(),
        "infrastructure damage must warn and allow: {response}"
    );
    let detail = hook_output["additionalContext"]
        .as_str()
        .expect("fail-open response carries repair context");
    assert!(detail.contains("tool allowed"), "{detail}");

    fs::remove_dir_all(root).expect("remove fixture");
}
