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
        .expect("clock")
        .as_nanos();
    let root = std::env::temp_dir().join(format!("shepherd-seed-{label}-{nonce:x}"));
    fs::create_dir_all(&root).expect("fixture");
    root
}

fn write(root: &Path, name: &str, content: &str) -> PathBuf {
    let path = root.join(name);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("fixture parent");
    }
    fs::write(&path, content).expect("fixture file");
    path
}

fn run(root: &Path, args: &[&str]) -> Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("HOME", root.join("home"))
        .env("SHEPHERD_HOME", root.join("home/.shepherd"))
        .output()
        .expect("native seed command")
}

#[test]
fn usage_and_validation_have_stable_streams_and_exit_codes() {
    let root = fixture("usage");
    let bare = run(&root, &["seed"]);
    assert!(bare.status.success());
    assert!(String::from_utf8_lossy(&bare.stdout).starts_with("shepherd seed verify"));
    assert!(bare.stderr.is_empty());

    let help = run(&root, &["seed", "--help"]);
    assert_eq!(help.stdout, bare.stdout);
    assert!(help.status.success());

    let unknown = run(&root, &["seed", "bogus"]);
    assert_eq!(unknown.status.code(), Some(2));
    assert!(unknown.stdout.is_empty());
    assert!(String::from_utf8_lossy(&unknown.stderr).starts_with("unknown subcommand: bogus\n"));

    let missing = run(&root, &["seed", "verify"]);
    assert_eq!(missing.status.code(), Some(2));
    assert_eq!(missing.stderr, b"ERR: seed verify needs a <path>\n");

    let flag = run(&root, &["seed", "verify", "--bogus"]);
    assert_eq!(flag.status.code(), Some(2));
    assert_eq!(flag.stderr, b"unknown flag: --bogus\n");
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn universal_hard_checks_preserve_order_and_quiet_only_suppresses_output() {
    let root = fixture("hard");
    let body = format!(
        "kind: patch-seed\nTODO: resolve\nLane 4 is prescriptive\n{}\n",
        (0..205)
            .map(|index| format!("line {index}"))
            .collect::<Vec<_>>()
            .join("\n")
    );
    let path = write(&root, "broken.seed.md", &body);
    let shown = path.to_string_lossy();
    let loud = run(&root, &["seed", "verify", &shown]);
    assert_eq!(loud.status.code(), Some(1));
    let stdout = String::from_utf8_lossy(&loud.stdout);
    let footprint = stdout.find("HARD  footprint").expect("footprint");
    let todo = stdout.find("HARD  TODO:/FIXME:").expect("todo");
    let lane = stdout.find("HARD  prescriptive 'Lane N'").expect("lane");
    assert!(footprint < todo && todo < lane);
    assert!(stdout.ends_with("FAIL: 3 hard failure(s), 0 warning(s)\n"));
    assert!(loud.stderr.is_empty());

    let quiet = run(&root, &["seed", "verify", &shown, "--quiet"]);
    assert_eq!(quiet.status.code(), Some(1));
    assert!(quiet.stdout.is_empty());
    assert!(quiet.stderr.is_empty());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn file_scope_literals_new_markers_flow_lists_and_globs_are_deterministic() {
    let root = fixture("scope");
    let existing = write(&root, "src/exists.rs", "// fixture\n");
    let missing = root.join("src/missing.rs");
    let content = format!(
        "kind: sprint-seed\nmilestone: v1\nfile_scope:\n  exclusive: [{}, {}]\n  - {} (NEW - planned)\n  - {}\n---\n",
        existing.display(),
        missing.display(),
        root.join("src/new.rs").display(),
        root.join("src/*.rs").display(),
    );
    let seed = write(&root, "scope.seed.md", &content);
    let output = run(&root, &["seed", "verify", &seed.to_string_lossy()]);
    assert_eq!(output.status.code(), Some(1));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains(&format!(
        "file_scope path does not resolve and is not marked (NEW): {}",
        missing.display()
    )));
    assert_eq!(
        stdout.matches("file_scope path does not resolve").count(),
        1
    );
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn deliverable_and_canonical_warning_rules_match_the_frozen_policy() {
    let root = fixture("canonical");
    let seed = write(
        &root,
        "canonical.seed.md",
        "kind: sprint-seed\n### Medium delivery [MEDIUM]\n**Priority:** MEDIUM\nPhase 0 mesh\n| 1 | first |\n| 2 | second |\n",
    );
    let output = run(&root, &["seed", "verify", &seed.to_string_lossy()]);
    assert_eq!(output.status.code(), Some(1));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("1 deliverable block(s) carry a priority but no **GH:** anchor"));
    assert!(stdout.contains("Phase 0 mesh has 2 row(s) (< 8 recommended)"));
    assert!(stdout.contains("no deliverable ranked CRITICAL or HIGH"));
    assert!(stdout.contains("frontmatter missing 'milestone:'"));
    assert!(stdout.ends_with("FAIL: 1 hard failure(s), 3 warning(s)\n"));
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn clean_seed_and_trailing_blank_lines_are_stable() {
    let root = fixture("clean");
    let seed = write(
        &root,
        "clean.seed.md",
        "kind: patch-seed\nordinary prose\n\n\n",
    );
    let output = run(&root, &["seed", "verify", &seed.to_string_lossy()]);
    assert!(output.status.success());
    assert_eq!(output.stdout, b"OK: 0 hard failures, 0 warning(s)\n");
    assert!(output.stderr.is_empty());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn crlf_input_has_stable_verdict_bytes() {
    let root = fixture("crlf");
    let seed = write(
        &root,
        "crlf.seed.md",
        "kind: sprint-seed\r\nordinary prose\r\n",
    );
    let output = run(&root, &["seed", "verify", &seed.to_string_lossy()]);
    assert!(output.status.success());
    assert_eq!(output.stdout, b"OK: 0 hard failures, 0 warning(s)\n");
    assert!(output.stderr.is_empty());
    fs::remove_dir_all(root).expect("cleanup");
}

#[cfg(unix)]
#[test]
fn shell_style_globs_preserve_ranges_parent_components_and_dangling_links() {
    use std::os::unix::fs::symlink;

    let root = fixture("shell-globs");
    let parent = root.parent().expect("fixture parent");
    let sibling_name = format!(
        "{}-shared",
        root.file_name().expect("fixture name").to_string_lossy()
    );
    let sibling = parent.join(&sibling_name);
    fs::create_dir_all(&sibling).expect("sibling fixture");
    write(&sibling, "b.rs", "// bracket range fixture\n");
    fs::create_dir_all(root.join("links")).expect("links fixture");
    symlink(root.join("missing-target"), root.join("links/dangling.rs"))
        .expect("dangling symlink fixture");

    let seed = write(
        &root,
        "glob.seed.md",
        &format!(
            "kind: sprint-seed\nmilestone: v1\nfile_scope:\n  - ../{sibling_name}/[a-z].rs\n  - links/dangling.*\n---\n"
        ),
    );
    let output = run(&root, &["seed", "verify", &seed.to_string_lossy()]);
    assert_eq!(
        output.status.code(),
        Some(0),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(output.stdout, b"OK: 0 hard failures, 0 warning(s)\n");
    assert!(output.stderr.is_empty());
    fs::remove_dir_all(root).expect("cleanup root");
    fs::remove_dir_all(sibling).expect("cleanup sibling");
}

#[test]
fn seed_input_is_bounded_before_allocating_the_whole_file() {
    let root = fixture("size-bound");
    let seed = root.join("oversized.seed.md");
    fs::write(&seed, vec![b'x'; 1_048_577]).expect("oversized fixture");

    let output = run(&root, &["seed", "verify", &seed.to_string_lossy()]);
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8_lossy(&output.stderr),
        format!(
            "ERROR: seed input exceeds 1048576 bytes: {}\n",
            seed.display()
        )
    );
    fs::remove_dir_all(root).expect("cleanup");
}
