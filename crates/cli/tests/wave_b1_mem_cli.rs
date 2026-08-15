use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{SystemTime, UNIX_EPOCH},
};

use shepherd_cli::shepherd::registry::Registry;

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-wave-b1-mem-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    let namespace = root.join(".shepherd");
    fs::create_dir_all(&namespace).expect("create namespace");
    let initialized = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("initialize fixture repository");
    assert!(initialized.success());
    let registry =
        Registry::open_migrated(namespace.join("shepherd.db")).expect("create migrated registry");
    registry
        .execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?1, ?2, ?3, ?4)",
            ["proj-mem", "fixture", "0", "0"],
        )
        .expect("insert project");
    root
}

fn run(root: &Path, args: &[&str]) -> Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("HOME", root.join("isolated-home"))
        .env("SHEPHERD_HOME", root.join("isolated-home/.shepherd"))
        .output()
        .expect("run shepherd")
}

#[test]
fn mem_add_list_pin_unpin_show_and_delete_use_the_native_registry() {
    let root = fixture("lifecycle");
    let add = run(
        &root,
        &[
            "mem",
            "add",
            "--title",
            "native memory",
            "--kind",
            "note",
            "--body",
            "body",
            "--tags",
            "[\"native\"]",
        ],
    );
    assert!(
        add.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&add.stderr)
    );
    let id = String::from_utf8(add.stdout)
        .expect("UTF-8 id")
        .trim()
        .to_owned();
    assert!(!id.is_empty());

    let list = run(&root, &["mem", "list", "--json"]);
    assert!(list.status.success());
    assert!(String::from_utf8_lossy(&list.stdout).contains("native memory"));

    for action in ["pin", "unpin"] {
        let output = run(&root, &["mem", action, &id]);
        assert!(
            output.status.success(),
            "action={action} stderr={}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(output.stdout.is_empty());
    }

    let show = run(&root, &["mem", "show", &id, "--json"]);
    assert!(show.status.success());
    assert!(String::from_utf8_lossy(&show.stdout).contains("[\\\"native\\\"]"));

    let delete = run(&root, &["mem", "delete", &id]);
    assert!(delete.status.success());
    assert_eq!(
        delete.stdout,
        format!("shepherd mem rm: removed {id}\n").as_bytes()
    );

    let absent = run(&root, &["mem", "show", &id, "--json"]);
    assert!(absent.status.success());
    assert_eq!(absent.stdout, b"null\n");

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn mem_negative_usage_is_stable_and_nonzero() {
    let root = fixture("negative");
    let search = run(&root, &["mem", "search"]);
    assert_eq!(search.status.code(), Some(1));
    assert!(search.stdout.is_empty());
    assert_eq!(
        search.stderr,
        b"ERROR: --q=<text> required for mem search\n"
    );

    let show = run(&root, &["mem", "show"]);
    assert_eq!(show.status.code(), Some(1));
    assert!(show.stdout.is_empty());
    assert_eq!(show.stderr, b"ERROR: usage: shepherd mem show <id>\n");

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn mem_in_a_linked_worktree_uses_the_primary_registry_and_explicit_config() {
    let root = fixture("linked-worktree");
    fs::write(
        root.join(".shepherd/shepherd.toml"),
        "[paths]\ndocs = \".shepherd/notes\"\nctx = \".shepherd/context\"\nruns = \".shepherd/runs\"\n",
    )
    .expect("write canonical configuration");
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
    let linked_status = Command::new("git")
        .args(["worktree", "add", "--detach", "--quiet"])
        .arg(&linked)
        .arg("HEAD")
        .current_dir(&root)
        .status()
        .expect("create linked worktree");
    assert!(linked_status.success());

    let add = run(
        &linked,
        &[
            "--config",
            ".shepherd/shepherd.toml",
            "mem",
            "add",
            "--title",
            "primary-owned",
        ],
    );
    assert!(
        add.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&add.stderr)
    );
    let id = String::from_utf8(add.stdout)
        .expect("UTF-8 id")
        .trim()
        .to_owned();

    let show = run(&root, &["mem", "show", &id, "--json"]);
    assert!(show.status.success());
    assert!(String::from_utf8_lossy(&show.stdout).contains("primary-owned"));
    assert!(!linked.join(".shepherd/shepherd.db").exists());

    fs::remove_dir_all(linked).expect("cleanup linked fixture");
    fs::remove_dir_all(root).expect("cleanup primary fixture");
}
