//! Real-binary tests for native signal and teammate routes.

use std::{
    fs,
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
    time::{SystemTime, UNIX_EPOCH},
};

use shepherd_cli::shepherd::registry::{OpenMode, Registry};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-wave-g-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("root");
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("git");
    assert!(status.success());
    root
}

fn invoke(root: &PathBuf, args: &[&str]) -> std::process::Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("HOME", root.join("home"))
        .env("SHEPHERD_HOME", root.join("home/.shepherd"))
        .output()
        .expect("invoke")
}

fn initialized(label: &str) -> PathBuf {
    let root = fixture(label);
    let init = invoke(&root, &["init", "--confirm"]);
    assert!(init.status.success(), "stderr={:?}", init.stderr);
    let registry =
        Registry::open(root.join(".shepherd/shepherd.db"), OpenMode::ReadWrite).expect("registry");
    registry.execute("INSERT INTO projects (id, name, created_at, updated_at) VALUES ('project-g', 'wave g', 0, 0)", []).expect("project");
    root
}

#[test]
fn signal_send_poll_json_and_consume_are_scoped_and_bounded() {
    let root = initialized("signal");
    let mut child = Command::new(binary())
        .args([
            "signal",
            "send",
            "--to",
            "session-b",
            "--kind",
            "seed-ready",
        ])
        .current_dir(&root)
        .env("HOME", root.join("home"))
        .env("SHEPHERD_HOME", root.join("home/.shepherd"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn");
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all(
            br#"{"run":"v645"}
"#,
        )
        .expect("payload");
    let sent = child.wait_with_output().expect("send");
    assert!(sent.status.success(), "stderr={:?}", sent.stderr);
    assert_eq!(String::from_utf8_lossy(&sent.stdout).trim(), "1");
    let poll = invoke(
        &root,
        &[
            "signal",
            "poll",
            "--as",
            "session-b",
            "--kind",
            "seed-ready",
            "--json",
            "--consume",
        ],
    );
    assert!(poll.status.success(), "stderr={:?}", poll.stderr);
    let rows: serde_json::Value = serde_json::from_slice(&poll.stdout).expect("rows");
    assert_eq!(rows[0]["recipient"], "session-b");
    assert_eq!(rows[0]["payload"], "{\"run\":\"v645\"}\n");
    let empty = invoke(&root, &["signal", "poll", "--as", "session-b", "--json"]);
    assert_eq!(empty.stdout, b"[]\n");
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn signal_rejects_invalid_json_without_inserting_state() {
    let root = initialized("bad-signal");
    let mut child = Command::new(binary())
        .args(["signal", "send", "--to", "session-b", "--kind", "bad"])
        .current_dir(&root)
        .env("HOME", root.join("home"))
        .env("SHEPHERD_HOME", root.join("home/.shepherd"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn");
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all(b"not-json\n")
        .expect("payload");
    let output = child.wait_with_output().expect("send");
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("payload not valid JSON"));
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn signal_rejects_oversized_payload_before_registry_insert() {
    let root = initialized("large-signal");
    let mut child = Command::new(binary())
        .args(["signal", "send", "--to", "session-b", "--kind", "large"])
        .current_dir(&root)
        .env("HOME", root.join("home"))
        .env("SHEPHERD_HOME", root.join("home/.shepherd"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn");
    let payload = format!("{{\"data\":\"{}\"}}\n", "x".repeat(64 * 1024));
    child
        .stdin
        .take()
        .expect("stdin")
        .write_all(payload.as_bytes())
        .expect("payload");
    let output = child.wait_with_output().expect("send");
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("exceeds 65536 bytes"));
    let registry =
        Registry::open(root.join(".shepherd/shepherd.db"), OpenMode::ReadOnly).expect("registry");
    let count: i64 = registry
        .query(
            "SELECT count(*) FROM session_signals WHERE recipient = 'session-b'",
            [],
            |row| row.get(0),
        )
        .expect("count")
        .into_iter()
        .next()
        .expect("count row");
    assert_eq!(count, 0);
    fs::remove_dir_all(root).expect("cleanup");
}

#[cfg(unix)]
#[test]
fn signal_rejects_symlinked_registry_path() {
    use std::os::unix::fs::symlink;

    let root = initialized("signal-symlink");
    let db = root.join(".shepherd/shepherd.db");
    let real_db = root.join(".shepherd/shepherd.db.real");
    fs::rename(&db, &real_db).expect("move registry");
    symlink("shepherd.db.real", &db).expect("symlink registry");
    let output = invoke(&root, &["signal", "poll", "--as", "session-b"]);
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("symlink"));
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn concurrent_signal_sends_preserve_distinct_registry_rows() {
    let root = initialized("signal-race");
    let mut children = (0..2)
        .map(|index| {
            let mut child = Command::new(binary())
                .args(["signal", "send", "--to", "session-b", "--kind", "race"])
                .current_dir(&root)
                .env("HOME", root.join("home"))
                .env("SHEPHERD_HOME", root.join("home/.shepherd"))
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .expect("spawn");
            child
                .stdin
                .take()
                .expect("stdin")
                .write_all(format!("{{\"index\":{index}}}\n").as_bytes())
                .expect("payload");
            child
        })
        .collect::<Vec<_>>();
    let outputs = children
        .drain(..)
        .map(|child| child.wait_with_output().expect("send"))
        .collect::<Vec<_>>();
    assert!(outputs.iter().all(|output| output.status.success()));
    let ids = outputs
        .iter()
        .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_owned())
        .collect::<Vec<_>>();
    assert_ne!(ids[0], ids[1]);
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn teammate_state_status_and_liveness_share_typed_registry_state() {
    let root = initialized("teammate");
    let registry =
        Registry::open(root.join(".shepherd/shepherd.db"), OpenMode::ReadWrite).expect("registry");
    registry.execute("INSERT INTO teammates (id, project_id, team_name, teammate_name, agent_type, session_id, spawned_at, last_seen_at, status, declared_state) VALUES ('t1', 'project-g', 'team-a', 'lane-a', 'conductor', 'sess-a', ?1, ?1, 'active', NULL)", [0_i64]).expect("teammate");
    let status = invoke(&root, &["teammate", "status", "lane-a", "--json"]);
    assert!(status.status.success(), "stderr={:?}", status.stderr);
    let value: serde_json::Value = serde_json::from_slice(&status.stdout).expect("status json");
    assert_eq!(value["teammate_name"], "lane-a");
    let state = invoke(
        &root,
        &["teammate", "state", "lane-a", "--set", "in-progress"],
    );
    assert_eq!(state.stdout, b"in-progress\n");
    let live = invoke(
        &root,
        &["teammate", "liveness", "--json", "--stale-mins", "0"],
    );
    assert!(live.status.success(), "stderr={:?}", live.stderr);
    let rows: serde_json::Value = serde_json::from_slice(&live.stdout).expect("liveness json");
    assert_eq!(rows[0]["verdict"], "ok");
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn unsupported_host_routes_fail_closed_without_shell_authority() {
    let root = fixture("limitations");
    for args in [&["sync"][..], &["worktree", "list"][..]] {
        let output = invoke(&root, args);
        assert_eq!(output.status.code(), Some(1));
        assert!(String::from_utf8_lossy(&output.stderr).contains("unavailable"));
    }
    fs::remove_dir_all(root).expect("cleanup");
}
