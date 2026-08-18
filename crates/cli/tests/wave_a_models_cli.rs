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

/// A bare temporary directory, no git repository -- for commands (like
/// `compile --content-dir`) that never touch project discovery.
fn tmp_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-wave-a-models-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    fs::create_dir_all(&root).expect("create temp root");
    root
}

const ROLES: [&str; 9] = [
    "root",
    "planter",
    "engineer",
    "conductor",
    "critic",
    "discovery",
    "coder",
    "auditor",
    "worker",
];

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
  "root": {"model": "reasoning-high", "source": "default"},
  "planter": {"model": "reasoning-high", "source": "default"},
  "engineer": {"model": "reasoning-high", "source": "default"},
  "conductor": {"model": "reasoning-high", "source": "default"},
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

#[test]
fn models_show_harness_translates_every_role_to_the_harness_native_spelling() {
    let root = repository("show-harness");

    // root/planter/engineer/conductor are the opus tier; coder/auditor/
    // worker/critic and discovery are the sonnet tier. Each harness spells
    // both tiers differently, and root's tier still translates through the
    // ordinary hint table even though its compiled carrier is advisory.
    for (harness, opus_tier, sonnet_tier) in [
        ("claude", "opus[1m]", "sonnet"),
        ("codex", "reasoning-high", "standard"),
        ("pi", "opus", "sonnet"),
    ] {
        let show = run(&root, &["models", "show", "--harness", harness, "--json"]);
        assert!(
            show.status.success(),
            "{harness}: stderr={}",
            String::from_utf8_lossy(&show.stderr)
        );
        let expected = format!(
            "{{\n  \"root\": {{\"model\": \"{opus_tier}\", \"source\": \"default\"}},\n  \"planter\": {{\"model\": \"{opus_tier}\", \"source\": \"default\"}},\n  \"engineer\": {{\"model\": \"{opus_tier}\", \"source\": \"default\"}},\n  \"conductor\": {{\"model\": \"{opus_tier}\", \"source\": \"default\"}},\n  \"critic\": {{\"model\": \"{sonnet_tier}\", \"source\": \"default\"}},\n  \"discovery\": {{\"model\": \"{sonnet_tier}\", \"source\": \"default\"}},\n  \"coder\": {{\"model\": \"{sonnet_tier}\", \"source\": \"default\"}},\n  \"auditor\": {{\"model\": \"{sonnet_tier}\", \"source\": \"default\"}},\n  \"worker\": {{\"model\": \"{sonnet_tier}\", \"source\": \"default\"}}\n}}\n"
        );
        assert_eq!(String::from_utf8_lossy(&show.stdout), expected, "{harness}");
        assert!(show.stderr.is_empty(), "{harness}");
    }

    // The exact invocation shape the operator names: `--harness` composes
    // with `--md` and reuses the same renderer, byte-identical in shape to
    // the unharnessed table.
    let markdown = run(&root, &["models", "show", "--harness", "claude", "--md"]);
    assert!(
        markdown.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&markdown.stderr)
    );
    let markdown_text = String::from_utf8_lossy(&markdown.stdout);
    assert!(
        markdown_text.starts_with("| role | model | source |\n|---|---|---|\n"),
        "{markdown_text}"
    );
    assert!(
        markdown_text.contains("| root | `opus[1m]` | default |"),
        "{markdown_text}"
    );
    assert!(
        markdown_text.contains("| conductor | `opus[1m]` | default |"),
        "{markdown_text}"
    );
    assert!(
        markdown_text.contains("| coder | `sonnet` | default |"),
        "{markdown_text}"
    );
    assert!(
        markdown_text.contains("| discovery | `sonnet` | default |"),
        "{markdown_text}"
    );

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_show_harness_rejects_an_unknown_harness_with_the_resolve_message_shape() {
    let root = repository("show-harness-negative");

    // Before this change, `--harness` was not a recognized flag on `show` at
    // all: `error: unexpected argument '--harness' found`. Now it is
    // recognized and validated exactly like `resolve --harness`.
    let bad = run(&root, &["models", "show", "--harness", "bogus"]);
    assert_eq!(bad.status.code(), Some(2));
    assert!(bad.stdout.is_empty());
    assert_eq!(
        bad.stderr,
        b"ERROR: unknown harness: bogus (valid: claude codex pi)\n"
    );

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_show_explicit_default_value_still_reports_source_config() {
    let root = repository("explicit-default-value");
    let config_dir = root.join(".shepherd");
    fs::create_dir_all(&config_dir).expect("create native configuration directory");
    // `coder`'s portable default is exactly `"standard"`. Setting it
    // explicitly to that same value must still report `source: config`.
    // Deriving provenance by comparing the merged value against
    // `ModelsConfig::default()` cannot see this -- the value is identical
    // either way -- and would wrongly render `source: default`. This is the
    // test that distinguishes the exact key-provenance design from the
    // banned default-value-comparison approximation.
    fs::write(
        config_dir.join("shepherd.toml"),
        "[models]\ncoder = \"standard\"\n",
    )
    .expect("write native configuration");

    let show = run(
        &root,
        &[
            "--config",
            ".shepherd/shepherd.toml",
            "models",
            "show",
            "--json",
        ],
    );
    assert!(
        show.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&show.stderr)
    );
    let stdout = String::from_utf8_lossy(&show.stdout);
    assert!(
        stdout.contains("\"coder\": {\"model\": \"standard\", \"source\": \"config\"}"),
        "an explicitly configured role must report source: config even when its \
         value equals the default: {stdout}"
    );
    assert!(
        stdout.contains("\"root\": {\"model\": \"reasoning-high\", \"source\": \"default\"}"),
        "an unconfigured role must still report source: default: {stdout}"
    );

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_resolve_all_nine_roles_and_three_harnesses_accept_the_economy_opt_down() {
    let root = repository("economy-opt-down");
    let config_dir = root.join(".shepherd");
    fs::create_dir_all(&config_dir).expect("create native configuration directory");
    let mut body = String::from("[models]\n");
    for role in ROLES {
        body.push_str(&format!("{role} = \"economy\"\n"));
    }
    fs::write(config_dir.join("shepherd.toml"), body).expect("write native configuration");

    for role in ROLES {
        for (harness, expected) in [("claude", "haiku"), ("codex", "economy"), ("pi", "haiku")] {
            let resolve = run(
                &root,
                &[
                    "--config",
                    ".shepherd/shepherd.toml",
                    "models",
                    "resolve",
                    role,
                    "--harness",
                    harness,
                ],
            );
            assert!(
                resolve.status.success(),
                "{role}/{harness}: stderr={}",
                String::from_utf8_lossy(&resolve.stderr)
            );
            assert_eq!(
                resolve.stdout,
                format!("{expected}\n").into_bytes(),
                "{role}/{harness}"
            );
        }
    }

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn codex_agent_types_never_names_root() {
    // `content/roles/shepherd.md` (root's carrier) is `dispatchable: false`
    // and keeps `model_hint: inherit-caller` even though root's portable
    // hint elsewhere is now the opus tier (see `ModelsConfig::root`).
    // `compiler.rs` uses exactly that hint to exclude root from the codex
    // `[agent_types]` table -- this pins that exclusion against the live
    // authored content, not a snapshot, so it fails the moment a future edit
    // removes the guard.
    let content_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("crates/cli has two ancestors up to the repository root")
        .join("content");
    assert!(
        content_dir.join("roles/shepherd.md").is_file(),
        "resolved content dir does not look like the repository's content/: {}",
        content_dir.display()
    );

    let out = tmp_dir("codex-root-exclusion-pin");
    let status = Command::new(binary())
        .arg("compile")
        .args(["--target", "codex"])
        .arg("--content-dir")
        .arg(&content_dir)
        .arg("--out")
        .arg(&out)
        .status()
        .expect("run shepherd compile");
    assert!(status.success());

    let manifest =
        fs::read_to_string(out.join("shepherd.codex.toml")).expect("read generated codex carrier");
    let agent_types = manifest
        .split("[agent_types]\n")
        .nth(1)
        .and_then(|rest| rest.split("\n[models]").next())
        .expect("[agent_types] section exists in the generated codex carrier");
    assert!(
        !agent_types
            .lines()
            .any(|line| line.trim_start().starts_with("shepherd ")),
        "root (role id `shepherd`) must never appear in the codex [agent_types] table:\n{agent_types}"
    );

    fs::remove_dir_all(out).expect("cleanup fixture");
}
