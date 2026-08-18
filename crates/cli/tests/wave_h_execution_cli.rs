use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{SystemTime, UNIX_EPOCH},
};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-wave-h-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("create fixture");
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("initialize fixture git repository");
    assert!(status.success());
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

fn text(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes).into_owned()
}

fn setup_run(root: &Path) {
    let init = invoke(root, &["init", "--confirm"]);
    assert!(init.status.success(), "init stderr={}", text(&init.stderr));
    let run = invoke(root, &["run", "init", "v900"]);
    assert!(
        run.status.success(),
        "run init stderr={}",
        text(&run.stderr)
    );
}

fn registry_path(root: &Path) -> PathBuf {
    root.join(".shepherd/shepherd.db")
}

/// Read the project id `init` actually minted, from the identity document it
/// wrote. Fixtures key their hand-inserted rows to this id instead of an
/// invented one, so they never compete with the row `init` itself registers.
fn project_id(root: &Path) -> String {
    let raw = fs::read_to_string(root.join(".shepherd/project.json")).expect("project.json");
    let document: serde_json::Value =
        serde_json::from_str(&raw).expect("project.json is valid JSON");
    document["id"]
        .as_str()
        .expect("project identity id must be a string")
        .to_owned()
}

#[test]
fn sprint_transitions_are_locked_and_close_requires_every_lane() {
    let root = fixture("sprint");
    setup_run(&root);
    let add = invoke(
        &root,
        &[
            "run",
            "lane",
            "add",
            "v900",
            "l1-engine",
            "--branch",
            "lane/l1",
        ],
    );
    assert!(add.status.success(), "stderr={}", text(&add.stderr));

    let ready = invoke(&root, &["ready", "--run", "v900", "--json"]);
    assert!(ready.status.success(), "stderr={}", text(&ready.stderr));
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&ready.stdout).expect("ready json")["ready"],
        true
    );
    let lint = invoke(&root, &["lint", "--run", "v900"]);
    assert_eq!(text(&lint.stdout), "lint: ok (v900)\n");

    let open = invoke(&root, &["sprint", "open", "--run", "v900"]);
    assert_eq!(open.status.code(), Some(0), "stderr={}", text(&open.stderr));
    let wave = invoke(&root, &["sprint", "wave", "--run", "v900", "l1-engine"]);
    assert_eq!(wave.status.code(), Some(0), "stderr={}", text(&wave.stderr));
    let premature = invoke(&root, &["sprint", "close", "--run", "v900"]);
    assert_eq!(premature.status.code(), Some(5));
    assert!(text(&premature.stderr).contains("every lane must be complete"));

    let closed_lane = invoke(
        &root,
        &[
            "close-lane",
            "--run",
            "v900",
            "l1-engine",
            "--status",
            "clean",
        ],
    );
    assert!(closed_lane.status.success());
    let close = invoke(&root, &["sprint", "close", "--run", "v900"]);
    assert_eq!(
        close.status.code(),
        Some(0),
        "stderr={}",
        text(&close.stderr)
    );
    assert!(text(&invoke(&root, &["run", "show", "v900"]).stdout).contains("status: closed"));
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn deliverables_and_issue_cache_use_the_typed_registry() {
    let root = fixture("registry");
    setup_run(&root);
    let project = project_id(&root);
    let promise = invoke(
        &root,
        &[
            "deliverable",
            "promise",
            "--kind",
            "test",
            "--target",
            "crates/cli/tests/wave_h_execution_cli.rs",
            "--role",
            "test-agent",
            "--session",
            "session-1",
        ],
    );
    assert!(promise.status.success(), "stderr={}", text(&promise.stderr));
    let id = text(&promise.stdout)
        .trim()
        .parse::<i64>()
        .expect("promise id");
    let stalled = invoke(
        &root,
        &["deliverable", "stalled", "--since-mins", "0", "--json"],
    );
    assert!(stalled.status.success());
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&stalled.stdout).expect("stalled json")[0]["id"],
        id
    );
    let complete = invoke(&root, &["deliverable", "complete", &id.to_string()]);
    assert!(
        complete.status.success(),
        "stderr={}",
        text(&complete.stderr)
    );
    assert_eq!(
        text(&invoke(&root, &["deliverable", "stalled", "--since-mins", "0"]).stdout),
        "no stalled deliverables\n"
    );

    let database = registry_path(&root);
    let connection = rusqlite::Connection::open(database).expect("open fixture registry");
    connection.execute(
        "INSERT INTO index_issues (id, project_id, source, number, title, state, labels, milestone, assignees, body, url, created_at, updated_at, refreshed_at) VALUES ('i7', ?1, 'test', 7, 'Critical regression', 'open', '[\"critical\"]', NULL, '[]', '', 'https://example.test/7', 1, 1, 1)",
        rusqlite::params![project],
    ).expect("insert issue");
    let issues = invoke(&root, &["issues", "classify", "--json"]);
    assert!(issues.status.success(), "stderr={}", text(&issues.stderr));
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&issues.stdout).expect("issues json")[0]["bucket"],
        "blocking-this-sprint"
    );
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn report_escalation_and_teammates_have_registry_backed_output() {
    let root = fixture("report");
    setup_run(&root);
    let project = project_id(&root);
    let database = registry_path(&root);
    let connection = rusqlite::Connection::open(database).expect("open fixture registry");
    connection.execute(
        "INSERT INTO escalations (project_id, role, phase, question, blocking, context_refs, raised_at) VALUES (?1, 'reviewer', 'verify', 'Is the output safe?', 1, '[]', 42)",
        rusqlite::params![project],
    ).expect("insert escalation");
    connection.execute(
        "INSERT INTO teammates (id, project_id, team_name, teammate_name, agent_type, session_id, tmux_pane_id, spawned_at, last_seen_at, status, metadata) VALUES ('t1', ?1, 'core', 'luna', 'worker', 's1', '', 1, 2, 'active', '{}')",
        rusqlite::params![project],
    ).expect("insert teammate");
    let escalation = invoke(&root, &["report", "escalation", "--open-only"]);
    assert!(
        escalation.status.success(),
        "stderr={}",
        text(&escalation.stderr)
    );
    assert!(
        text(&escalation.stdout).contains(
            "# Escalations\n\n- **#1 [reviewer/verify]** Is the output safe? (raised: 42)"
        )
    );
    let teammates = invoke(&root, &["report", "teammates", "--team", "core", "--json"]);
    assert!(
        teammates.status.success(),
        "stderr={}",
        text(&teammates.stderr)
    );
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&teammates.stdout).expect("teammates json")[0]
            ["teammate_name"],
        "luna"
    );
    fs::remove_dir_all(root).expect("cleanup");
}
