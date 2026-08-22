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

fn write_pi_targets(root: &Path) {
    let config_dir = root.join(".shepherd");
    fs::create_dir_all(&config_dir).expect("create native configuration directory");
    fs::write(
        config_dir.join("shepherd.pi.toml"),
        "[model_targets.pi]\ninherit-caller = \"inherit\"\nreasoning-high = \"openai-codex/gpt-5.6-sol:xhigh\"\nstandard = \"openai-codex/gpt-5.6-luna:max\"\neconomy = \"openai-codex/gpt-5.6-luna:max\"\n",
    )
    .expect("write Pi model targets");
}

fn command(root: &Path) -> Command {
    let mut command = Command::new(binary());
    command
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .env_remove("SHEPHERD_HARNESS")
        .env_remove("CLAUDECODE")
        .env_remove("CLAUDE_PLUGIN_ROOT")
        .env_remove("CODEX_HOME");
    command
}

fn run(root: &Path, args: &[&str]) -> Output {
    command(root).args(args).output().expect("run shepherd")
}

fn run_under_harness(root: &Path, harness: &str, args: &[&str]) -> Output {
    command(root)
        .env("SHEPHERD_HARNESS", harness)
        .args(args)
        .output()
        .expect("run shepherd under harness")
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
  "discovery": {"model": "economy", "source": "default"},
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
    ] {
        for role in ["planter", "engineer", "conductor"] {
            let output = run(&root, &["models", "resolve", role, "--harness", harness]);
            assert!(
                output.status.success(),
                "{harness}/{role}: {}",
                String::from_utf8_lossy(&output.stderr)
            );
            assert_eq!(output.stdout, expected, "{harness}/{role}");
        }
    }
    let missing = run(&root, &["models", "resolve", "engineer", "--harness", "pi"]);
    assert_eq!(missing.status.code(), Some(2));
    assert_eq!(
        String::from_utf8_lossy(&missing.stderr),
        "ERROR: Pi model target missing for portable hint `reasoning-high`. Set `model_targets.pi.reasoning-high = \"provider/model:thinking\"` in Shepherd configuration.\n"
    );
    assert!(missing.stdout.is_empty());

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_resolve_pi_uses_the_configured_concrete_target_map() {
    let root = repository("pi-target-map");
    let config_dir = root.join(".shepherd");
    fs::create_dir_all(&config_dir).expect("create native configuration directory");
    fs::write(
        config_dir.join("shepherd.pi.toml"),
        "[model_targets.pi]\ninherit-caller = \"inherit\"\nreasoning-high = \"openai-codex/gpt-5.6-sol:xhigh\"\nstandard = \"openai-codex/gpt-5.6-luna:max\"\neconomy = \"openai-codex/gpt-5.6-luna:max\"\n",
    )
    .expect("write Pi model targets");

    for (role, expected) in [
        ("planter", b"openai-codex/gpt-5.6-sol:xhigh\n".as_slice()),
        ("critic", b"openai-codex/gpt-5.6-luna:max\n".as_slice()),
        ("discovery", b"openai-codex/gpt-5.6-luna:max\n".as_slice()),
        ("engineer", b"openai-codex/gpt-5.6-sol:xhigh\n".as_slice()),
        ("conductor", b"openai-codex/gpt-5.6-sol:xhigh\n".as_slice()),
    ] {
        let output = run(&root, &["models", "resolve", role, "--harness", "pi"]);
        assert!(
            output.status.success(),
            "{role}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(output.stdout, expected, "{role}");
    }

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn requested_harnesses_load_project_model_overrides_for_resolve_and_show() {
    let root = repository("requested-harness-overrides");
    let config_dir = root.join(".shepherd");
    fs::create_dir_all(&config_dir).expect("create native configuration directory");
    fs::write(
        config_dir.join("shepherd.toml"),
        "[models]\nengineer = \"economy\"\n\n[model_targets.pi]\nreasoning-high = \"openai-codex/gpt-5.6-sol:xhigh\"\nstandard = \"openai-codex/gpt-5.6-luna:max\"\neconomy = \"openai-codex/gpt-5.6-luna:max\"\n",
    )
    .expect("write project model override");

    for (harness, expected) in [
        ("claude", "haiku"),
        ("codex", "economy"),
        ("pi", "openai-codex/gpt-5.6-luna:max"),
    ] {
        let resolved = run(
            &root,
            &["models", "resolve", "engineer", "--harness", harness],
        );
        assert!(
            resolved.status.success(),
            "{harness}: {}",
            String::from_utf8_lossy(&resolved.stderr)
        );
        assert_eq!(
            resolved.stdout,
            format!("{expected}\n").as_bytes(),
            "{harness}"
        );

        let shown = run(&root, &["models", "show", "--harness", harness, "--json"]);
        assert!(
            shown.status.success(),
            "{harness}: {}",
            String::from_utf8_lossy(&shown.stderr)
        );
        assert!(
            String::from_utf8_lossy(&shown.stdout).contains(&format!(
                "\"engineer\": {{\"model\": \"{expected}\", \"source\": \"config\"}}"
            )),
            "{harness}: {}",
            String::from_utf8_lossy(&shown.stdout)
        );
    }

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn explicit_harness_config_is_validated_under_the_requested_harness() {
    let root = repository("explicit-requested-harness");
    let config_dir = root.join(".shepherd");
    fs::create_dir_all(&config_dir).expect("create native configuration directory");
    fs::write(
        config_dir.join("shepherd.claude.toml"),
        "[models]\nengineer = \"standard\"\n",
    )
    .expect("write explicit Claude configuration");

    let resolved = run(
        &root,
        &[
            "--config",
            ".shepherd/shepherd.claude.toml",
            "models",
            "resolve",
            "engineer",
            "--harness",
            "claude",
            "--json",
        ],
    );

    assert!(
        resolved.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&resolved.stderr)
    );
    assert_eq!(
        resolved.stdout,
        b"{\n  \"role\": \"engineer\",\n  \"model\": \"sonnet\",\n  \"source\": \"config\",\n  \"harness\": \"claude\"\n}\n"
    );

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn no_target_preserves_the_environment_harness_for_config_selection() {
    let root = repository("environment-harness");
    let config_dir = root.join(".shepherd");
    fs::create_dir_all(&config_dir).expect("create native configuration directory");
    fs::write(
        config_dir.join("shepherd.claude.toml"),
        "[models]\nconductor = \"economy\"\n",
    )
    .expect("write environment-selected Claude configuration");

    let resolved = run_under_harness(
        &root,
        "claude",
        &["models", "resolve", "conductor", "--json"],
    );

    assert!(
        resolved.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&resolved.stderr)
    );
    assert_eq!(
        resolved.stdout,
        b"{\n  \"role\": \"conductor\",\n  \"model\": \"economy\",\n  \"source\": \"config\"\n}\n"
    );

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn context_free_missing_config_keeps_defaults_and_pi_fails_closed() {
    let root = tmp_dir("context-free-missing-config");
    for (harness, expected) in [
        ("claude", b"opus[1m]\n".as_slice()),
        ("codex", b"reasoning-high\n".as_slice()),
    ] {
        let resolved = run(
            &root,
            &["models", "resolve", "engineer", "--harness", harness],
        );
        assert!(
            resolved.status.success(),
            "{harness}: {}",
            String::from_utf8_lossy(&resolved.stderr)
        );
        assert_eq!(resolved.stdout, expected, "{harness}");
    }
    let pi = run(&root, &["models", "resolve", "engineer", "--harness", "pi"]);
    assert_eq!(pi.status.code(), Some(2));
    assert_eq!(
        pi.stderr,
        b"ERROR: Pi model target missing for portable hint `reasoning-high`. Set `model_targets.pi.reasoning-high = \"provider/model:thinking\"` in Shepherd configuration.\n"
    );

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn malformed_repository_never_falls_back_to_context_free_defaults() {
    let root = tmp_dir("malformed-repository");
    fs::create_dir(root.join(".git")).expect("create malformed repository marker");

    let resolved = run(
        &root,
        &["models", "resolve", "engineer", "--harness", "claude"],
    );

    assert!(!resolved.status.success());
    assert!(resolved.stdout.is_empty());
    assert!(
        String::from_utf8_lossy(&resolved.stderr)
            .contains("cannot resolve primary repository root"),
        "stderr={}",
        String::from_utf8_lossy(&resolved.stderr)
    );

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
        b"ERROR: unknown role: invalid (valid: root planter engineer conductor critic discovery coder auditor worker; alias: shepherd -> root)\n"
    );

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_resolve_shepherd_alias_matches_the_canonical_root_output_across_every_harness() {
    let root = repository("shepherd-alias");
    write_pi_targets(&root);

    // Compare live outputs rather than hardcoding a hint value: the value
    // that answers `resolve root` is config/profile-derived (see
    // `models_resolve_delegates_harness_translation_to_the_compiler_profiles`
    // above, which already covers what each harness spells root as), and
    // hardcoding it here would just be a second fitted assertion of the same
    // fact the `root` row already encodes.
    for harness in [None, Some("claude"), Some("codex"), Some("pi")] {
        let mut shepherd_args = vec!["models", "resolve", "shepherd"];
        let mut root_args = vec!["models", "resolve", "root"];
        if let Some(harness) = harness {
            shepherd_args.extend(["--harness", harness]);
            root_args.extend(["--harness", harness]);
        }

        let shepherd_out = run(&root, &shepherd_args);
        let root_out = run(&root, &root_args);

        assert!(
            shepherd_out.status.success(),
            "{harness:?}: stderr={}",
            String::from_utf8_lossy(&shepherd_out.stderr)
        );
        assert!(
            root_out.status.success(),
            "{harness:?}: stderr={}",
            String::from_utf8_lossy(&root_out.stderr)
        );
        assert_eq!(
            shepherd_out.stdout, root_out.stdout,
            "{harness:?}: `resolve shepherd` must print byte-identical stdout to `resolve root`"
        );
        assert!(shepherd_out.stderr.is_empty(), "{harness:?}");
        assert!(root_out.stderr.is_empty(), "{harness:?}");
    }

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_show_lists_exactly_the_canonical_roles_and_never_a_shepherd_row() {
    let root = repository("show-no-shepherd-row");
    write_pi_targets(&root);

    let plain = run(&root, &["models", "show"]);
    assert!(
        plain.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&plain.stderr)
    );
    let plain_text = String::from_utf8_lossy(&plain.stdout);
    // Table rows are the only lines with the renderer's two-space indent
    // (`"  {role:<10} {model:<10} (…)"`); the footer's `root is advisory...`
    // sentence starts flush left and must not be miscounted as a row.
    let plain_role_lines = plain_text
        .lines()
        .filter(|line| {
            line.strip_prefix("  ")
                .is_some_and(|rest| ROLES.iter().any(|role| rest.starts_with(role)))
        })
        .count();
    assert_eq!(plain_role_lines, ROLES.len(), "{plain_text}");
    // Row-shaped, not a bare substring check: the table title itself is
    // "shepherd model map (resolved)", which legitimately contains the word
    // without being a role row.
    assert!(
        !plain_text.lines().any(|line| line
            .strip_prefix("  ")
            .is_some_and(|rest| rest.starts_with("shepherd"))),
        "{plain_text}"
    );

    let markdown = run(&root, &["models", "show", "--md"]);
    assert!(
        markdown.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&markdown.stderr)
    );
    let markdown_text = String::from_utf8_lossy(&markdown.stdout);
    let markdown_role_rows = markdown_text
        .lines()
        .filter(|line| {
            line.starts_with('|')
                && ROLES
                    .iter()
                    .any(|role| line.contains(&format!("| {role} |")))
        })
        .count();
    assert_eq!(markdown_role_rows, ROLES.len(), "{markdown_text}");
    assert!(!markdown_text.contains("shepherd"), "{markdown_text}");

    let json = run(&root, &["models", "show", "--json"]);
    assert!(
        json.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&json.stderr)
    );
    let json_text = String::from_utf8_lossy(&json.stdout);
    let json_role_keys = json_text
        .lines()
        .filter(|line| {
            let trimmed = line.trim_start();
            ROLES
                .iter()
                .any(|role| trimmed.starts_with(&format!("\"{role}\":")))
        })
        .count();
    assert_eq!(json_role_keys, ROLES.len(), "{json_text}");
    assert!(!json_text.contains("\"shepherd\""), "{json_text}");

    for harness in ["claude", "codex", "pi"] {
        let harnessed = run(&root, &["models", "show", "--harness", harness, "--json"]);
        assert!(
            harnessed.status.success(),
            "{harness}: stderr={}",
            String::from_utf8_lossy(&harnessed.stderr)
        );
        let harnessed_text = String::from_utf8_lossy(&harnessed.stdout);
        let harnessed_role_keys = harnessed_text
            .lines()
            .filter(|line| {
                let trimmed = line.trim_start();
                ROLES
                    .iter()
                    .any(|role| trimmed.starts_with(&format!("\"{role}\":")))
            })
            .count();
        assert_eq!(
            harnessed_role_keys,
            ROLES.len(),
            "{harness}: {harnessed_text}"
        );
        assert!(
            !harnessed_text.contains("\"shepherd\""),
            "{harness}: {harnessed_text}"
        );
    }

    fs::remove_dir_all(root).expect("cleanup fixture");
}

#[test]
fn models_show_harness_translates_every_role_to_the_harness_native_spelling() {
    let root = repository("show-harness");
    write_pi_targets(&root);

    // Root, planter, engineer, and conductor are reasoning-high. The ordinary
    // bounded roles stay standard/economy for affordable fan-out. Each harness
    // translates the shared portable hints through compiler-owned policy.
    for (harness, reasoning_tier, standard_tier, economy_tier) in [
        ("claude", "opus[1m]", "sonnet", "haiku"),
        ("codex", "reasoning-high", "standard", "economy"),
        (
            "pi",
            "openai-codex/gpt-5.6-sol:xhigh",
            "openai-codex/gpt-5.6-luna:max",
            "openai-codex/gpt-5.6-luna:max",
        ),
    ] {
        let show = run(&root, &["models", "show", "--harness", harness, "--json"]);
        assert!(
            show.status.success(),
            "{harness}: stderr={}",
            String::from_utf8_lossy(&show.stderr)
        );
        let expected = format!(
            "{{\n  \"root\": {{\"model\": \"{reasoning_tier}\", \"source\": \"default\"}},\n  \"planter\": {{\"model\": \"{reasoning_tier}\", \"source\": \"default\"}},\n  \"engineer\": {{\"model\": \"{reasoning_tier}\", \"source\": \"default\"}},\n  \"conductor\": {{\"model\": \"{reasoning_tier}\", \"source\": \"default\"}},\n  \"critic\": {{\"model\": \"{standard_tier}\", \"source\": \"default\"}},\n  \"discovery\": {{\"model\": \"{economy_tier}\", \"source\": \"default\"}},\n  \"coder\": {{\"model\": \"{standard_tier}\", \"source\": \"default\"}},\n  \"auditor\": {{\"model\": \"{standard_tier}\", \"source\": \"default\"}},\n  \"worker\": {{\"model\": \"{standard_tier}\", \"source\": \"default\"}}\n}}\n"
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
        markdown_text.contains("| engineer | `opus[1m]` | default |"),
        "{markdown_text}"
    );
    assert!(
        markdown_text.contains("| coder | `sonnet` | default |"),
        "{markdown_text}"
    );
    assert!(
        markdown_text.contains("| discovery | `haiku` | default |"),
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
    body.push_str(
        "\n[model_targets.pi]\ninherit-caller = \"inherit\"\nreasoning-high = \"openai-codex/gpt-5.6-sol:xhigh\"\nstandard = \"openai-codex/gpt-5.6-luna:max\"\neconomy = \"openai-codex/gpt-5.6-luna:max\"\n",
    );
    fs::write(config_dir.join("shepherd.toml"), body).expect("write native configuration");

    for role in ROLES {
        for (harness, expected) in [
            ("claude", "haiku"),
            ("codex", "economy"),
            ("pi", "openai-codex/gpt-5.6-luna:max"),
        ] {
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
fn codex_agent_types_never_names_an_undispatchable_role() {
    // `[agent_types]` is the set of roles Codex may SPAWN, so it must contain
    // exactly the `dispatchable: true` roles. It used to key on
    // `model_hint == "inherit-caller"`, a proxy that was wrong in both
    // directions: `planter` is `dispatchable: false` and appeared here anyway
    // because its hint is `reasoning-high`, so Codex advertised the
    // operator-escalation role as spawnable; and any dispatchable role adopting
    // `inherit-caller` would have silently vanished from the table instead.
    //
    // Pinned against the LIVE authored content rather than a snapshot, so it
    // fails the moment an edit changes which roles are dispatchable.
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
    for undispatchable in ["shepherd", "planter"] {
        assert!(
            !agent_types
                .lines()
                .any(|line| line.trim_start().starts_with(&format!("{undispatchable} "))),
            "`{undispatchable}` is dispatchable: false and must never appear in the \
             codex [agent_types] table:\n{agent_types}"
        );
    }
    // The reasoning leads remain dispatchable and must stay in the table.
    for lead in ["engineer", "conductor"] {
        assert!(
            agent_types
                .lines()
                .any(|line| line.trim_start().starts_with(&format!("{lead} "))),
            "`{lead}` is dispatchable and must appear in the codex [agent_types] \
             table:\n{agent_types}"
        );
    }

    fs::remove_dir_all(out).expect("cleanup fixture");
}
