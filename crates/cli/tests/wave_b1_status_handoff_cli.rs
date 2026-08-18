use std::{
    fs::{self, File, FileTimes},
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use shepherd_cli::shepherd::registry::Registry;

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}
fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let root = std::env::temp_dir().join(format!("shepherd-wave-b1-status-{label}-{nonce:x}"));
    fs::create_dir_all(root.join(".shepherd")).expect("namespace");
    assert!(
        Command::new("git")
            .args(["init", "--quiet"])
            .current_dir(&root)
            .status()
            .expect("git")
            .success()
    );
    Registry::open_migrated(root.join(".shepherd/shepherd.db"))
        .expect("registry")
        .execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?1, ?2, ?3, ?4)",
            ["project", "fixture", "0", "0"],
        )
        .expect("project");
    root
}
fn run(root: &Path, args: &[&str]) -> Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("HOME", root.join("home"))
        .env("SHEPHERD_HOME", root.join("home/.shepherd"))
        .output()
        .expect("run")
}

fn write_run(root: &Path, run: &str, branch: &str, status: &str) {
    let directory = root.join(".shepherd/runs").join(run);
    fs::create_dir_all(&directory).expect("run directory");
    fs::write(
        directory.join("run.json"),
        format!(
            "{{\"schema_version\":1,\"run\":\"{run}\",\"status\":\"{status}\",\"branch\":\"{branch}\"}}\n"
        ),
    )
    .expect("run state");
}

fn write_project_id(root: &Path, project_id: &str) {
    fs::write(
        root.join(".shepherd/project.json"),
        format!("{{\"id\":\"{project_id}\"}}\n"),
    )
    .expect("project identity");
}

fn set_same_modified(paths: &[&Path]) {
    let timestamp = UNIX_EPOCH + Duration::from_secs(1_700_000_000);
    let times = FileTimes::new().set_modified(timestamp);
    for path in paths {
        File::options()
            .write(true)
            .open(path)
            .expect("open fixture for timestamp")
            .set_times(times)
            .expect("set fixture timestamp");
    }
}

#[test]
fn status_and_handoff_reads_use_context_paths_without_mutating() {
    let root = fixture("read-only");
    let status = run(&root, &["status"]);
    assert!(
        status.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&status.stderr)
    );
    assert!(String::from_utf8_lossy(&status.stdout).contains("Schema version: 21\n"));
    let handoffs = root.join(".shepherd/docs/handoffs");
    fs::create_dir_all(&handoffs).expect("handoffs");
    fs::write(
        handoffs.join("2026-01-01-main-close-handoff.md"),
        "handoff content\n",
    )
    .expect("handoff");
    let list = run(&root, &["handoff", "list"]);
    assert!(list.status.success());
    assert_eq!(list.stdout, b"2026-01-01-main-close-handoff.md\n");
    let show = run(&root, &["handoff", "show", "main"]);
    assert!(show.status.success());
    assert_eq!(show.stdout, b"handoff content\n");
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn status_no_db_is_a_stable_read_only_failure() {
    let root = fixture("no-db");
    fs::remove_file(root.join(".shepherd/shepherd.db")).expect("remove fixture db");
    let output = run(&root, &["status"]);
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert!(String::from_utf8_lossy(&output.stderr).contains("ERROR: no DB at "));
    assert!(String::from_utf8_lossy(&output.stderr).contains("run 'shepherd init'"));
    assert!(!String::from_utf8_lossy(&output.stderr).contains("shctx"));
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn create_writes_only_the_selected_runs_canonical_handoff_with_registry_metrics() {
    let root = fixture("create");
    write_project_id(&root, "project");
    write_run(&root, "v645", "v6.4.5", "closing");
    let registry =
        Registry::open_migrated(root.join(".shepherd/shepherd.db")).expect("open fixture registry");
    registry
        .execute(
            "INSERT INTO artifacts (id, project_id, kind, path, hash, created_at, updated_at) VALUES ('artifact', 'project', 'report', 'runs/v645/report.md', 'hash', 0, 0)",
            [],
        )
        .expect("artifact");
    registry
        .execute(
            "INSERT INTO mem_entries (id, project_id, kind, title, body, tags, pinned, created_at, updated_at) VALUES ('memory', 'project', 'note', 'note', 'body', '[]', 0, 0, 0)",
            [],
        )
        .expect("memory");
    // Release the fixture's connection before the CLI opens the same database.
    // Holding it across the subprocess leaves this test contending with itself
    // for the SQLite write lock, which is why it was the only flaky test in
    // this file under the full parallel gate.
    drop(registry);

    let output = run(&root, &["handoff", "create", "--run=v645"]);
    assert!(
        output.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(output.stdout, b".shepherd/runs/v645/handoff.md\n");
    assert!(output.stderr.is_empty());
    let target = root.join(".shepherd/runs/v645/handoff.md");
    let content = fs::read_to_string(&target).expect("canonical handoff");
    assert!(content.contains("# Sprint handoff — v6.4.5\n"));
    assert!(content.contains("| Artifacts (created/modified) | 1 |"));
    assert!(content.contains("| Memory entries written | 1 |"));
    assert!(content.contains("| Lock acquisitions | 0 |"));
    assert!(!root.join(".shepherd/docs/handoffs").exists());

    let list = run(&root, &["handoff", "list"]);
    assert_eq!(list.stdout, b"v645/handoff.md\n");
    let show = run(&root, &["handoff", "show", "v645"]);
    assert_eq!(show.stdout, content.as_bytes());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn create_refuses_noncanonical_outputs_and_unknown_or_ambiguous_runs() {
    let root = fixture("create-paths");
    write_run(&root, "v645", "v6.4.5", "closing");
    write_run(&root, "v645-copy", "v6.4.5", "closing");

    let outside = run(
        &root,
        &["handoff", "create", "--run=v645", "--out=outside.md"],
    );
    assert_eq!(outside.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&outside.stderr).contains("canonical handoff path"));
    assert!(!root.join("outside.md").exists());

    let unknown = run(&root, &["handoff", "create", "--run=missing"]);
    assert_eq!(unknown.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&unknown.stderr).contains("run `missing` does not exist"));

    let ambiguous = run(&root, &["handoff", "create", "--branch=v6.4.5"]);
    assert_eq!(ambiguous.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&ambiguous.stderr).contains("multiple runs record branch"));
    assert!(!root.join(".shepherd/docs/handoffs").exists());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn create_refuses_clobber_and_replaces_atomically_only_when_explicit() {
    let root = fixture("create-replace");
    write_run(&root, "v645", "v6.4.5", "closing");
    let target = root.join(".shepherd/runs/v645/handoff.md");
    fs::write(&target, "operator-authored\n").expect("existing handoff");

    let refused = run(&root, &["handoff", "create", "--run=v645"]);
    assert_eq!(refused.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&refused.stderr).contains("already exists"));
    assert_eq!(
        fs::read_to_string(&target).expect("preserved"),
        "operator-authored\n"
    );

    let replaced = run(&root, &["handoff", "create", "--run=v645", "--replace"]);
    assert!(replaced.status.success());
    let content = fs::read_to_string(&target).expect("replaced handoff");
    assert!(content.starts_with("# Sprint handoff — v6.4.5"));
    assert!(
        !content.contains("Mirrored as the bundled Jinja template"),
        "the native template must not advertise a retired language-specific copy"
    );
    assert!(!content.contains("operator-authored"));
    assert_eq!(
        fs::read_dir(target.parent().expect("run directory"))
            .expect("run entries")
            .filter_map(Result::ok)
            .filter(|entry| entry.file_name().to_string_lossy().ends_with(".tmp"))
            .count(),
        0,
        "atomic publication must not leak a temporary file"
    );
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn list_and_show_merge_canonical_flat_and_legacy_reads_with_stable_ties() {
    let root = fixture("list-merged");
    write_run(&root, "a-run", "a", "closing");
    write_run(&root, "z-run", "z", "closing");
    let a = root.join(".shepherd/runs/a-run/handoff.md");
    let z = root.join(".shepherd/runs/z-run/handoff.md");
    fs::write(&a, "a run\n").expect("a handoff");
    fs::write(&z, "z run\n").expect("z handoff");
    fs::create_dir_all(root.join(".shepherd/docs/handoffs")).expect("legacy root");
    let legacy = root.join(".shepherd/docs/handoffs/2025-main-handoff.md");
    fs::write(&legacy, "legacy\n").expect("legacy handoff");
    let flat = root.join(".shepherd/docs/project-handoff.md");
    fs::write(&flat, "flat").expect("flat handoff");
    set_same_modified(&[&a, &z, &legacy, &flat]);

    let list = run(&root, &["handoff", "list"]);
    assert!(list.status.success());
    assert_eq!(
        list.stdout,
        b"2025-main-handoff.md\na-run/handoff.md\nproject-handoff.md\nz-run/handoff.md\n"
    );
    let show = run(&root, &["handoff", "show"]);
    assert_eq!(show.stdout, b"legacy\n");
    let legacy_show = run(&root, &["handoff", "show", "2025-main"]);
    assert_eq!(legacy_show.stdout, b"legacy\n");
    let flat_show = run(&root, &["handoff", "show", "project-handoff"]);
    assert_eq!(flat_show.stdout, b"flat");
    fs::remove_dir_all(root).expect("cleanup");
}

#[cfg(unix)]
#[test]
fn create_and_show_reject_symbolic_link_run_and_handoff_targets() {
    use std::os::unix::fs::symlink;

    let root = fixture("symlink");
    let external = root.join("external");
    fs::create_dir_all(&external).expect("external");
    fs::write(
        external.join("run.json"),
        "{\"schema_version\":1,\"run\":\"escape\",\"status\":\"closing\",\"branch\":\"escape\"}\n",
    )
    .expect("external state");
    fs::create_dir_all(root.join(".shepherd/runs")).expect("runs");
    symlink(&external, root.join(".shepherd/runs/escape")).expect("run symlink");
    let escaped = run(&root, &["handoff", "create", "--run=escape"]);
    assert_eq!(escaped.status.code(), Some(1));
    assert!(!external.join("handoff.md").exists());

    write_run(&root, "v645", "v6.4.5", "closing");
    let outside = root.join("outside-handoff.md");
    fs::write(&outside, "outside\n").expect("outside target");
    symlink(&outside, root.join(".shepherd/runs/v645/handoff.md")).expect("handoff symlink");
    let shown = run(&root, &["handoff", "show", "v645"]);
    assert_eq!(shown.status.code(), Some(1));
    assert!(!String::from_utf8_lossy(&shown.stdout).contains("outside"));
    fs::remove_dir_all(root).expect("cleanup");
}
