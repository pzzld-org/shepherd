mod support;

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::time::{SystemTime, UNIX_EPOCH};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-wave-b2-run-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    std::fs::create_dir_all(&root).expect("create fixture root");
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("initialize fixture git repository");
    assert!(status.success(), "git init must succeed");
    root
}

fn invoke(root: &Path, args: &[&str]) -> Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .output()
        .expect("run shepherd binary")
}

fn primary(root: &Path) -> PathBuf {
    std::fs::canonicalize(root).expect("canonical fixture root")
}

fn text(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes).into_owned()
}

fn cleanup(root: &Path) {
    support::remove_dir_all(root)
}

#[test]
fn init_scaffolds_the_layout_v5_run_at_the_primary_root_and_refuses_a_second_init() {
    let root = fixture("init");
    let first = invoke(
        &root,
        &[
            "run",
            "init",
            "v900-dev0",
            "--kind",
            "sprint",
            "--branch",
            "v9.0.0-dev.0",
            "--base",
            "main",
        ],
    );
    assert_eq!(
        first.status.code(),
        Some(0),
        "stderr={}",
        text(&first.stderr)
    );
    assert_eq!(
        text(&first.stdout),
        format!(
            "{}\n",
            primary(&root)
                .join(".shepherd/runs/v900-dev0/run.json")
                .display()
        )
    );
    let directory = "lanes";
    assert!(
        root.join(".shepherd/runs/v900-dev0")
            .join(directory)
            .is_dir(),
        "{directory} is part of the canonical layout-v5 run shape"
    );

    let second = invoke(&root, &["run", "init", "v900-dev0"]);
    assert_eq!(second.status.code(), Some(5));
    assert_eq!(
        text(&second.stderr),
        "ERROR: run already exists: v900-dev0\n"
    );
    cleanup(&root);
}

#[test]
fn invalid_ids_missing_runs_and_schema_ahead_documents_have_stable_exit_codes_without_writes() {
    let root = fixture("fail-closed");
    let invalid = invoke(&root, &["run", "init", "../escape"]);
    assert_eq!(invalid.status.code(), Some(2));
    assert!(!root.join(".shepherd/runs").exists());

    let absent = invoke(&root, &["run", "show", "v900-dev0"]);
    assert_eq!(absent.status.code(), Some(5));
    assert_eq!(
        text(&absent.stderr),
        format!(
            "ERROR: no such run: v900-dev0 (expected {})\n",
            primary(&root)
                .join(".shepherd/runs/v900-dev0/run.json")
                .display()
        )
    );

    let run = root.join(".shepherd/runs/v900-dev0");
    std::fs::create_dir_all(&run).expect("create run fixture");
    let future =
        b"{\"schema_version\":2,\"run\":\"v900-dev0\",\"status\":\"paused-by-future-host\"}\n";
    std::fs::write(run.join("run.json"), future).expect("write future document");
    let claim = invoke(&root, &["run", "claim", "v900-dev0"]);
    assert_eq!(claim.status.code(), Some(2));
    assert_eq!(
        std::fs::read(run.join("run.json")).expect("read unchanged future document"),
        future
    );
    cleanup(&root);
}

#[test]
fn lifecycle_lane_wave_layout_and_read_only_routes_cover_the_native_surface() {
    let root = fixture("surface");
    let init = invoke(&root, &["run", "init", "v901-dev0"]);
    assert_eq!(init.status.code(), Some(0), "stderr={}", text(&init.stderr));

    for args in [
        &[
            "run",
            "set",
            "v901-dev0",
            "--status",
            "executing",
            "--seed",
            "runs/v901-dev0/seed.md",
            "--plan",
            "runs/v901-dev0/plan.md",
        ][..],
        &[
            "run",
            "lane",
            "add",
            "v901-dev0",
            "l1-engine",
            "--branch",
            "lane/l1",
        ][..],
        &[
            "run",
            "lane",
            "set",
            "v901-dev0",
            "l1-engine",
            "--state",
            "in-progress",
        ][..],
        &[
            "run",
            "wave",
            "accept",
            "v901-dev0",
            "l1-engine",
            "--commit",
            "abc123",
        ][..],
    ] {
        let result = invoke(&root, args);
        assert_eq!(
            result.status.code(),
            Some(0),
            "args={args:?} stderr={}",
            text(&result.stderr)
        );
    }
    let pending = invoke(&root, &["run", "wave", "pending", "v901-dev0"]);
    assert_eq!(pending.status.code(), Some(6));
    assert_eq!(text(&pending.stdout), "l1-engine\tabc123\n");
    let merged = invoke(&root, &["run", "wave", "merged", "v901-dev0", "l1-engine"]);
    assert_eq!(
        merged.status.code(),
        Some(0),
        "stderr={}",
        text(&merged.stderr)
    );
    let clear = invoke(&root, &["run", "wave", "pending", "v901-dev0", "--json"]);
    assert_eq!(clear.status.code(), Some(0));
    assert!(text(&clear.stdout).contains("\"ok\":true"));

    std::fs::write(
        root.join(".shepherd/runs/v901-dev0/lanes/l1-engine/plan.md"),
        "### W1-L1-S1: native command\n",
    )
    .expect("lane plan");
    std::fs::write(
        root.join(".shepherd/runs/v901-dev0/auditor-verdicts.txt"),
        "L1 w1-s1 PASS completed\n",
    )
    .expect("ledger");
    let verified = invoke(&root, &["run", "wave", "verify", "v901-dev0"]);
    assert_eq!(
        verified.status.code(),
        Some(0),
        "stderr={}",
        text(&verified.stderr)
    );
    assert_eq!(
        text(&verified.stdout),
        "W1-L1-S1\tPASS\tL1 w1-s1 PASS completed\n"
    );

    let show = invoke(&root, &["run", "show", "v901-dev0", "--json"]);
    assert_eq!(show.status.code(), Some(0));
    assert!(text(&show.stdout).contains("\"l1-engine\""));
    let listed = invoke(&root, &["run", "list", "--json"]);
    assert_eq!(text(&listed.stdout), "[\"v901-dev0\"]\n");
    let ledger = invoke(&root, &["run", "ledger", "path", "v901-dev0"]);
    assert_eq!(ledger.status.code(), Some(0));
    assert!(text(&ledger.stdout).ends_with(".shepherd/runs/v901-dev0/auditor-verdicts.txt\n"));
    let checked = invoke(&root, &["run", "ledger", "check", "v901-dev0", "--json"]);
    assert_eq!(
        checked.status.code(),
        Some(0),
        "stderr={}",
        text(&checked.stderr)
    );
    let layout = invoke(&root, &["run", "layout", "v901-dev0", "--json"]);
    assert_eq!(layout.status.code(), Some(0));
    assert!(text(&layout.stdout).contains("\"ok\": true"));
    cleanup(&root);
}

#[cfg(unix)]
#[test]
fn symlinked_run_state_is_refused_without_following_the_link() {
    let root = fixture("symlink");
    let outside = fixture("outside");
    std::fs::create_dir_all(root.join(".shepherd/runs/v902-dev0")).expect("run directory");
    std::fs::write(outside.join("state.json"), b"{\"run\":\"v902-dev0\"}\n")
        .expect("outside state");
    std::os::unix::fs::symlink(
        outside.join("state.json"),
        root.join(".shepherd/runs/v902-dev0/run.json"),
    )
    .expect("symlink state");
    let show = invoke(&root, &["run", "show", "v902-dev0"]);
    assert_ne!(show.status.code(), Some(0));
    assert!(text(&show.stderr).contains("symlink"));
    assert_eq!(
        std::fs::read(outside.join("state.json")).expect("outside unchanged"),
        b"{\"run\":\"v902-dev0\"}\n"
    );
    cleanup(&outside);
    cleanup(&root);
}

#[test]
fn rename_canonicalize_and_migrate_preserve_the_run_lifecycle_contract() {
    let root = fixture("migration");
    let init = invoke(&root, &["run", "init", "v903-dev0"]);
    assert_eq!(init.status.code(), Some(0));
    let renamed = invoke(&root, &["run", "rename", "v903-dev0", "v904-dev0-codex-01"]);
    assert_eq!(
        renamed.status.code(),
        Some(0),
        "stderr={}",
        text(&renamed.stderr)
    );
    let canonicalized = invoke(&root, &["run", "canonicalize", "v904-dev0-codex-01"]);
    assert_eq!(
        canonicalized.status.code(),
        Some(0),
        "stderr={}",
        text(&canonicalized.stderr)
    );
    assert!(root.join(".shepherd/runs/v904-dev0/run.json").is_file());

    let legacy = root.join(".shepherd/runs/v905-dev0");
    std::fs::create_dir_all(&legacy).expect("legacy directory");
    std::fs::write(
        legacy.join("run.json"),
        b"{\"run_id\":\"v905-dev0\",\"lanes\":{\"l1-engine\":{\"state\":\"pending\"}},\"updated_at\":\"42\"}\n",
    )
    .expect("legacy run document");
    let migrated = invoke(&root, &["run", "migrate", "v905-dev0"]);
    assert_eq!(
        migrated.status.code(),
        Some(0),
        "stderr={}",
        text(&migrated.stderr)
    );
    let state: serde_json::Value =
        serde_json::from_slice(&std::fs::read(legacy.join("run.json")).expect("migrated state"))
            .expect("canonical JSON");
    assert_eq!(state["run"], "v905-dev0");
    assert_eq!(state["lanes"][0]["id"], "l1-engine");
    cleanup(&root);
}

#[test]
fn linked_worktree_reads_and_mutates_only_the_primary_runs_root() {
    let root = fixture("linked-primary");
    let init = invoke(&root, &["run", "init", "v906-dev0"]);
    assert_eq!(init.status.code(), Some(0));
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
        .expect("commit fixture");
    assert!(commit.success());
    let linked = root.with_file_name(format!(
        "{}-linked",
        root.file_name().expect("fixture name").to_string_lossy()
    ));
    let add = Command::new("git")
        .args(["worktree", "add", "--detach", "--quiet"])
        .arg(&linked)
        .arg("HEAD")
        .current_dir(&root)
        .status()
        .expect("add linked worktree");
    assert!(add.success());
    std::fs::create_dir_all(linked.join(".shepherd/runs/v999-dev0")).expect("linked shadow");
    std::fs::write(
        linked.join(".shepherd/runs/v999-dev0/run.json"),
        b"{\"run\":\"v999-dev0\"}\n",
    )
    .expect("linked shadow state");
    let shown = invoke(&linked, &["run", "show", "v906-dev0"]);
    assert_eq!(
        shown.status.code(),
        Some(0),
        "stderr={}",
        text(&shown.stderr)
    );
    let shadow = invoke(&linked, &["run", "show", "v999-dev0"]);
    assert_eq!(shadow.status.code(), Some(5));
    let update = invoke(
        &linked,
        &["run", "set", "v906-dev0", "--status", "executing"],
    );
    assert_eq!(
        update.status.code(),
        Some(0),
        "stderr={}",
        text(&update.stderr)
    );
    assert!(
        std::fs::read_to_string(root.join(".shepherd/runs/v906-dev0/run.json"))
            .expect("primary state")
            .contains("\"executing\"")
    );
    std::fs::remove_dir_all(&linked).expect("remove linked fixture");
    cleanup(&root);
}
