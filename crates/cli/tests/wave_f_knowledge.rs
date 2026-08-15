//! Black-box gates for the native top-level knowledge leaves.

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
    let root = std::env::temp_dir().join(format!(
        "shepherd-wave-f-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("fixture");
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("git init");
    assert!(status.success());
    root
}

fn invoke(root: &Path, args: &[&str]) -> Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .output()
        .expect("invoke shepherd")
}

fn init(root: &Path) {
    let output = invoke(root, &["init", "--confirm"]);
    assert!(output.status.success(), "stderr={:?}", output.stderr);
}

fn cleanup(root: PathBuf) {
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn query_allowlist_and_schema_absence_fail_closed() {
    let root = fixture("query");
    let absent = invoke(&root, &["query", "open-issues", "--json"]);
    assert_eq!(absent.status.code(), Some(1));
    assert!(absent.stdout.is_empty());

    init(&root);
    let unknown = invoke(&root, &["query", "arbitrary-sql", "--json"]);
    assert_eq!(unknown.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&unknown.stderr).contains("unsupported canned query"));
    cleanup(root);
}

#[test]
fn query_existing_but_unmigrated_database_fails_closed() {
    let root = fixture("schema-absence");
    init(&root);
    fs::remove_file(root.join(".shepherd/shepherd.db")).expect("remove fixture database");
    fs::write(root.join(".shepherd/shepherd.db"), b"").expect("empty database");
    let output = invoke(&root, &["query", "open-issues", "--json"]);
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("no such table") || stderr.contains("schema"));
    cleanup(root);
}

#[test]
fn search_scope_and_limit_are_rejected_before_query() {
    let root = fixture("search-validation");
    init(&root);
    for args in [
        ["search", "term", "--scope", "unknown"],
        ["search", "term", "--limit", "0"],
        ["search", "term", "--limit", "1001"],
    ] {
        let output = invoke(&root, &args);
        assert_eq!(output.status.code(), Some(1));
        assert!(output.stdout.is_empty());
        assert!(
            String::from_utf8_lossy(&output.stderr).contains("unsupported search scope")
                || String::from_utf8_lossy(&output.stderr).contains("search limit")
        );
    }
    cleanup(root);
}

#[cfg(unix)]
#[test]
fn dups_check_rejects_symlinks_and_oversized_files() {
    use std::os::unix::fs::symlink;

    let root = fixture("safe-files");
    init(&root);
    let outside = root.join("outside.rs");
    fs::write(&outside, b"pub struct Outside;").expect("outside");
    symlink(&outside, root.join("link.rs")).expect("symlink");
    let refused = invoke(&root, &["dups", "check", "link.rs", "--json"]);
    assert_eq!(refused.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&refused.stderr).contains("without following symlinks"));

    let oversized = root.join("oversized.rs");
    fs::write(&oversized, vec![b'x'; 1_048_577]).expect("oversized");
    let bounded = invoke(&root, &["dups", "check", "oversized.rs", "--json"]);
    assert_eq!(bounded.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&bounded.stderr).contains("1048576-byte limit"));
    cleanup(root);
}

#[test]
fn knowledge_leaves_do_not_fallback_to_an_interpreter() {
    let root = fixture("native");
    init(&root);
    let output = invoke(&root, &["eval", "run", "--kind", "reflection"]);
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("eval run is unavailable"));
    assert!(!stderr.contains("python"));
    assert!(!stderr.contains("node"));
    assert!(!stderr.contains("bash"));
    cleanup(root);
}
