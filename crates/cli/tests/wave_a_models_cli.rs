use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{SystemTime, UNIX_EPOCH},
};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn repository(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-wave-a-models-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("create fixture root");
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("initialize fixture repository");
    assert!(status.success());
    root
}

fn run(root: &Path, args: &[&str]) -> Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .output()
        .expect("run shepherd")
}

#[test]
fn models_resolve_and_show_use_portable_default_hints() {
    let root = repository("defaults");

    let resolve = run(&root, &["models", "resolve", "coder"]);
    assert!(
        resolve.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&resolve.stderr)
    );
    assert_eq!(resolve.stdout, b"standard\n");
    assert!(resolve.stderr.is_empty());

    let show = run(&root, &["models", "show", "--json"]);
    assert!(
        show.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&show.stderr)
    );
    assert_eq!(
        show.stdout,
        br#"{
  "root": {"model": "inherit-caller", "source": "default"},
  "planter": {"model": "reasoning-high", "source": "default"},
  "engineer": {"model": "reasoning-high", "source": "default"},
  "conductor": {"model": "standard", "source": "default"},
  "critic": {"model": "standard", "source": "default"},
  "discovery": {"model": "standard", "source": "default"},
  "coder": {"model": "standard", "source": "default"},
  "auditor": {"model": "standard", "source": "default"},
  "worker": {"model": "standard", "source": "default"}
}
"#
    );
    assert!(show.stderr.is_empty());

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_resolve_delegates_harness_translation_to_the_compiler_profiles() {
    let root = repository("harness-profiles");
    for (harness, expected) in [
        ("claude", b"opus[1m]\n".as_slice()),
        ("codex", b"reasoning-high\n".as_slice()),
        ("pi", b"opus\n".as_slice()),
    ] {
        let output = run(
            &root,
            &["models", "resolve", "engineer", "--harness", harness],
        );
        assert!(
            output.status.success(),
            "{harness}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(output.stdout, expected, "{harness}");
    }
    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_resolve_uses_an_explicit_canonical_config_and_tracks_its_source() {
    let root = repository("config");
    let config_dir = root.join(".shepherd");
    fs::create_dir_all(&config_dir).expect("create native configuration directory");
    fs::write(
        config_dir.join("shepherd.toml"),
        "[models]\ncoder = \"native-coder\"\n",
    )
    .expect("write native configuration");

    let resolve = run(
        &root,
        &[
            "--config",
            ".shepherd/shepherd.toml",
            "models",
            "resolve",
            "coder",
            "--json",
        ],
    );
    assert!(
        resolve.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&resolve.stderr)
    );
    assert_eq!(
        resolve.stdout,
        b"{\n  \"role\": \"coder\",\n  \"model\": \"native-coder\",\n  \"source\": \"config\"\n}\n"
    );
    assert!(resolve.stderr.is_empty());

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_negative_inputs_keep_the_oracle_messages_and_exit_code() {
    let root = repository("negative");

    let missing = run(&root, &["models", "resolve"]);
    assert_eq!(missing.status.code(), Some(2));
    assert!(missing.stdout.is_empty());
    assert_eq!(
        missing.stderr,
        b"ERROR: usage: shepherd models resolve <role>\n"
    );

    let unknown = run(&root, &["models", "resolve", "invalid"]);
    assert_eq!(unknown.status.code(), Some(2));
    assert!(unknown.stdout.is_empty());
    assert_eq!(
        unknown.stderr,
        b"ERROR: unknown role: invalid (valid: root planter engineer conductor critic discovery coder auditor worker)\n"
    );

    fs::remove_dir_all(root).expect("cleanup fixture");
}
