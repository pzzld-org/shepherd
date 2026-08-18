//! Focused deterministic tests for the native lock coordination slice.

use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
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
        "shepherd-wave-e-lock-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("fixture root");
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("git init");
    assert!(status.success());
    root
}

fn invoke(root: &Path, args: &[&str]) -> std::process::Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("HOME", root.join("home"))
        .env("SHEPHERD_HOME", root.join("home/.shepherd"))
        .output()
        .expect("invoke shepherd")
}

// The only caller is the `#[cfg(unix)]` reap test below: it puts a stub `kill`
// on PATH, which has no Windows equivalent.
#[cfg(unix)]
fn invoke_with_path(root: &Path, args: &[&str], path: &Path) -> std::process::Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("HOME", root.join("home"))
        .env("SHEPHERD_HOME", root.join("home/.shepherd"))
        .env("PATH", path)
        .output()
        .expect("invoke shepherd")
}

fn register_project(root: &Path) {
    let registry =
        Registry::open(root.join(".shepherd/shepherd.db"), OpenMode::ReadWrite).expect("registry");
    registry
        .execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('project-lock', 'lock fixture', 0, 0)",
            [],
        )
        .expect("project");
}

#[test]
fn lock_show_defaults_to_free_without_creating_state() {
    let root = fixture("show");
    let init = invoke(&root, &["init", "--confirm"]);
    assert!(init.status.success(), "stderr={:?}", init.stderr);
    let output = invoke(&root, &["lock"]);
    assert!(output.status.success(), "stderr={:?}", output.stderr);
    assert_eq!(output.stdout, b"lock: free\n");
    assert!(!root.join(".shepherd/shepherd.lock").exists());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn lock_acquire_is_atomic_and_second_holder_is_refused() {
    let root = fixture("acquire");
    let init = invoke(&root, &["init", "--confirm"]);
    assert!(init.status.success(), "stderr={:?}", init.stderr);
    register_project(&root);
    let first = invoke(
        &root,
        &[
            "lock",
            "acquire",
            "--mode",
            "parallel",
            "--session",
            "sess-a",
        ],
    );
    assert!(first.status.success(), "stderr={:?}", first.stderr);
    assert_eq!(first.stdout, b"lock: acquired (sess-a, parallel)\n");
    let second = invoke(&root, &["lock", "acquire", "--session", "sess-b"]);
    assert_eq!(second.status.code(), Some(1));
    assert_eq!(second.stderr, b"ERROR: lock already held\n");
    let show = invoke(&root, &["lock", "show", "--json"]);
    assert!(show.status.success(), "stderr={:?}", show.stderr);
    let payload: serde_json::Value = serde_json::from_slice(&show.stdout).expect("lock json");
    assert_eq!(payload["held"], true);
    assert_eq!(payload["holder_session_id"], "sess-a");
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn lock_release_updates_audit_and_refuses_symlink_paths() {
    let root = fixture("release");
    let init = invoke(&root, &["init", "--confirm"]);
    assert!(init.status.success(), "stderr={:?}", init.stderr);
    register_project(&root);
    let acquire = invoke(&root, &["lock", "acquire", "--session", "sess-release"]);
    assert!(acquire.status.success(), "stderr={:?}", acquire.stderr);
    let release = invoke(&root, &["lock", "release"]);
    assert!(release.status.success(), "stderr={:?}", release.stderr);
    assert_eq!(release.stdout, b"lock: released\n");
    let free = invoke(&root, &["lock", "show"]);
    assert_eq!(free.stdout, b"lock: free\n");

    #[cfg(unix)]
    {
        use std::os::unix::fs::symlink;
        let outside = root.join("outside.lock");
        fs::write(&outside, b"outside").expect("outside sentinel");
        symlink(&outside, root.join(".shepherd/shepherd.lock")).expect("lock symlink");
        let refused = invoke(&root, &["lock", "show"]);
        assert_eq!(refused.status.code(), Some(1));
        assert_eq!(fs::read(&outside).expect("sentinel remains"), b"outside");
    }
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn invalid_mode_is_rejected_before_any_lock_state_is_created() {
    let root = fixture("invalid-mode");
    let init = invoke(&root, &["init", "--confirm"]);
    assert!(init.status.success(), "stderr={:?}", init.stderr);
    register_project(&root);
    let output = invoke(
        &root,
        &["lock", "acquire", "--mode", "invalid", "--session", "bad"],
    );
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("invalid lock mode"));
    assert!(!root.join(".shepherd/shepherd.lock").exists());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn injected_history_failure_compensates_the_lock_file() {
    let root = fixture("insert-failure");
    let init = invoke(&root, &["init", "--confirm"]);
    assert!(init.status.success(), "stderr={:?}", init.stderr);
    register_project(&root);
    let registry =
        Registry::open(root.join(".shepherd/shepherd.db"), OpenMode::ReadWrite).expect("registry");
    registry.execute(
        "CREATE TRIGGER fail_lock_insert BEFORE INSERT ON locks_history BEGIN SELECT RAISE(ABORT, 'injected lock history failure'); END",
        [],
    ).expect("trigger");
    let output = invoke(
        &root,
        &[
            "lock",
            "acquire",
            "--mode",
            "context",
            "--session",
            "injected",
        ],
    );
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("injected lock history failure"));
    assert!(!root.join(".shepherd/shepherd.lock").exists());
    fs::remove_dir_all(root).expect("cleanup");
}

#[cfg(unix)]
#[test]
fn reap_uses_native_pid_probe_when_path_has_git_but_no_kill() {
    let root = fixture("native-pid");
    let init = invoke(&root, &["init", "--confirm"]);
    assert!(init.status.success(), "stderr={:?}", init.stderr);
    register_project(&root);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs();
    let lock = format!(
        r#"{{"holder_session_id":"live","mode":"context","acquired_at":{now},"pid":{},"children":[]}}"#,
        std::process::id()
    );
    fs::write(root.join(".shepherd/shepherd.lock"), lock).expect("lock fixture");
    let tool_bin = root.join("tool-bin");
    fs::create_dir_all(&tool_bin).expect("tool bin");
    let git = if PathBuf::from("/usr/bin/git").is_file() {
        "/usr/bin/git"
    } else {
        "/usr/local/bin/git"
    };
    std::os::unix::fs::symlink(git, tool_bin.join("git")).expect("git shim");
    let output = invoke_with_path(&root, &["lock", "reap"], &tool_bin);
    assert_eq!(output.status.code(), Some(1), "stderr={:?}", output.stderr);
    assert!(String::from_utf8_lossy(&output.stderr).contains("held by live pid"));
    assert!(root.join(".shepherd/shepherd.lock").exists());
    fs::remove_dir_all(root).expect("cleanup");
}
