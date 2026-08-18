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
        "shepherd-compile-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("fixture");
    root
}

fn run(cwd: &Path, args: &[&str]) -> Output {
    Command::new(binary())
        .args(args)
        .current_dir(cwd)
        .output()
        .expect("run shepherd")
}

fn copy_tree(source: &Path, destination: &Path) {
    fs::create_dir_all(destination).expect("copy destination");
    for entry in fs::read_dir(source).expect("copy source") {
        let entry = entry.expect("copy entry");
        let target = destination.join(entry.file_name());
        if entry.file_type().expect("copy type").is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), target).expect("copy file");
        }
    }
}

#[test]
fn standalone_binary_compiles_embedded_content_without_a_checkout() {
    let root = fixture("embedded");
    let copied = root.join("shepherd");
    fs::copy(binary(), &copied).expect("copy binary");
    let output = Command::new(&copied)
        .args(["compile", "--target", "claude"])
        .current_dir(&root)
        .output()
        .expect("run copied binary");
    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    let manifest: serde_json::Value = serde_json::from_slice(&output.stdout).expect("manifest");
    assert_eq!(manifest["schema"], "shepherd.compiled-tree/2");
    assert_eq!(manifest["target"], "claude");
    assert_eq!(manifest["files"].as_array().expect("files").len(), 18);
    assert_eq!(manifest["roles"].as_array().expect("roles").len(), 9);
    let coder = manifest["roles"]
        .as_array()
        .expect("roles")
        .iter()
        .find(|role| role["role"] == "coder")
        .expect("coder role contract");
    assert_eq!(coder["carrier_path"], "agents/coder.md");
    assert_eq!(coder["model"], "sonnet");
    assert!(coder["profile"].is_null());
    assert!(
        coder["tools"]
            .as_array()
            .expect("tools")
            .iter()
            .any(|tool| tool == "Write")
    );
    assert!(output.stderr.is_empty());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn materialize_is_reproducible_and_check_is_read_only() {
    let root = fixture("materialize");
    let output_root = root.join("codex");
    let output = run(
        &root,
        &[
            "compile",
            "--target",
            "codex",
            "--out",
            output_root.to_str().expect("output path"),
        ],
    );
    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stdout.is_empty());
    assert!(output_root.join(".shepherd-generated.json").is_file());
    assert!(output_root.join("shepherd.codex.toml").is_file());

    let check = run(
        &root,
        &[
            "compile",
            "--target",
            "codex",
            "--out",
            output_root.to_str().expect("output path"),
            "--check",
        ],
    );
    assert!(
        check.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&check.stderr)
    );
    assert!(check.stdout.is_empty());
    assert!(check.stderr.is_empty());

    let generated = output_root.join("skills/thinking/SKILL.md");
    let original = fs::read(&generated).expect("generated skill");
    fs::write(&generated, b"hand edited\n").expect("drift");
    let drift = run(
        &root,
        &[
            "compile",
            "--target",
            "codex",
            "--out",
            output_root.to_str().expect("output path"),
            "--check",
        ],
    );
    assert_eq!(drift.status.code(), Some(1));
    assert!(drift.stdout.is_empty());
    assert!(String::from_utf8_lossy(&drift.stderr).contains("generated file drift"));
    assert_eq!(
        fs::read(&generated).expect("preserved drift"),
        b"hand edited\n"
    );

    let overwrite = run(
        &root,
        &[
            "compile",
            "--target",
            "codex",
            "--out",
            output_root.to_str().expect("output path"),
        ],
    );
    assert_eq!(overwrite.status.code(), Some(1));
    assert_eq!(
        fs::read(&generated).expect("still preserved"),
        b"hand edited\n"
    );

    fs::write(&generated, original).expect("restore generated file");
    let replay = run(
        &root,
        &[
            "compile",
            "--target",
            "codex",
            "--out",
            output_root.to_str().expect("output path"),
        ],
    );
    assert!(replay.status.success());
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn materialize_refuses_unowned_targets_and_symlink_roots() {
    let root = fixture("ownership");
    let output_root = root.join("unowned");
    fs::create_dir_all(&output_root).expect("unowned root");
    fs::write(output_root.join("shepherd.codex.toml"), b"user file\n").expect("user file");
    let unowned = run(
        &root,
        &[
            "compile",
            "--target",
            "codex",
            "--out",
            output_root.to_str().expect("output path"),
        ],
    );
    assert_eq!(unowned.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&unowned.stderr).contains("not owned"));
    assert_eq!(
        fs::read(output_root.join("shepherd.codex.toml")).expect("user file"),
        b"user file\n"
    );

    #[cfg(unix)]
    {
        let real = root.join("real");
        fs::create_dir_all(&real).expect("real root");
        let linked = root.join("linked");
        std::os::unix::fs::symlink(&real, &linked).expect("symlink root");
        let linked_output = run(
            &root,
            &[
                "compile",
                "--target",
                "codex",
                "--out",
                linked.to_str().expect("linked path"),
            ],
        );
        assert_eq!(linked_output.status.code(), Some(1));
        assert!(real.read_dir().expect("real directory").next().is_none());
    }
    fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn stale_generated_files_are_removed_only_with_intact_prior_provenance() {
    let root = fixture("stale");
    let authored = root.join("content");
    copy_tree(
        &PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../content"),
        &authored,
    );
    let output_root = root.join("claude");
    let common = [
        "compile",
        "--target",
        "claude",
        "--out",
        output_root.to_str().expect("output path"),
        "--content-dir",
        authored.to_str().expect("content path"),
    ];
    let initial = run(&root, &common);
    assert!(
        initial.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&initial.stderr)
    );
    let stale = output_root.join("skills/adaptation/SKILL.md");
    assert!(stale.is_file());
    fs::remove_dir_all(authored.join("skills/adaptation")).expect("remove authored skill");
    fs::write(&stale, b"operator change\n").expect("drift stale file");

    let refused = run(&root, &common);
    assert_eq!(refused.status.code(), Some(1));
    assert_eq!(
        fs::read(&stale).expect("preserved stale drift"),
        b"operator change\n"
    );

    let original = embedded_skill("adaptation");
    fs::write(&stale, original).expect("restore generated stale file");
    let updated = run(&root, &common);
    assert!(
        updated.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&updated.stderr)
    );
    assert!(!stale.exists());
    assert!(!output_root.join("skills/adaptation").exists());
    let manifest: serde_json::Value = serde_json::from_slice(
        &fs::read(output_root.join(".shepherd-generated.json")).expect("manifest"),
    )
    .expect("manifest JSON");
    assert_eq!(manifest["files"].as_array().expect("files").len(), 17);
    fs::remove_dir_all(root).expect("cleanup");
}

fn embedded_skill(name: &str) -> Vec<u8> {
    let root = fixture("expected-skill");
    let output = root.join("claude");
    let result = run(
        &root,
        &[
            "compile",
            "--target",
            "claude",
            "--out",
            output.to_str().expect("output path"),
        ],
    );
    assert!(result.status.success());
    let bytes = fs::read(output.join(format!("skills/{name}/SKILL.md"))).expect("embedded skill");
    fs::remove_dir_all(root).expect("cleanup expected skill");
    bytes
}

#[test]
fn removed_legacy_commands_never_fall_through_to_another_cli() {
    let root = fixture("retired-command");
    let output = run(&root, &["style", "show"]);
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8(output.stderr).expect("UTF-8 stderr"),
        "ERROR: command `style` is unavailable in the canonical Rust CLI; legacy Python, Bash, and Node command authorities are retired\n"
    );
    fs::remove_dir_all(root).expect("cleanup");
}
