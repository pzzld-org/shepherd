use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use clap::Parser;
use shepherd_cli::migrate::{MigrateCmd, MigrationRequest, MigrationScope, execute, output_json};

fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after epoch")
        .as_nanos();
    let path = std::env::temp_dir().join(format!("shepherd-cli-layout-{label}-{nonce:x}"));
    fs::create_dir_all(&path).expect("create fixture");
    path
}

fn write(path: &Path, bytes: &[u8]) {
    fs::create_dir_all(path.parent().expect("fixture parent")).expect("create parent");
    fs::write(path, bytes).expect("write fixture");
}

fn run_state(run: &str) -> Vec<u8> {
    format!(
        r#"{{"run":"{run}","schema_version":1,"status":"planned"}}
"#
    )
    .into_bytes()
}

fn cleanup(path: &Path) {
    fs::remove_dir_all(path).expect("remove fixture");
}

fn initialize_git(root: &Path) {
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(root)
        .status()
        .expect("initialize fixture repository");
    assert!(status.success(), "git init failed");
}

#[test]
fn parser_defaults_to_project_dry_run_and_rejects_both_modes() {
    let command = MigrateCmd::try_parse_from(["migrate", "--layout", "v5"])
        .expect("minimal migration command parses");
    assert_eq!(command.scope, MigrationScope::Project);
    assert!(!command.confirm);
    assert!(!command.dry_run);
    assert!(MigrateCmd::try_parse_from(["migrate", "--confirm", "--dry-run"]).is_err());
}

#[test]
fn copied_live_shape_is_dry_run_only_until_explicit_confirmation() {
    let root = fixture("copied-live");
    let namespace = root.join(".shepherd");
    let runs = namespace.join("runs");
    write(&runs.join("v645/run.json"), &run_state("v645"));
    write(&namespace.join("docs/specs/old.md"), b"old spec");
    write(&namespace.join("dispatch/v645/old.json"), b"dispatch");
    write(&namespace.join("archive/.gitkeep"), b"");
    let before = fs::read_dir(&namespace)
        .expect("namespace listing")
        .map(|entry| entry.expect("entry").file_name())
        .collect::<Vec<_>>();

    let output = execute(&MigrationRequest::project(&namespace, &runs)).expect("dry run");
    assert!(output.execution.is_none());
    assert_eq!(
        before,
        fs::read_dir(&namespace)
            .expect("namespace still exists")
            .map(|entry| entry.expect("entry").file_name())
            .collect::<Vec<_>>()
    );
    let json = output_json(&output).expect("stable JSON");
    assert!(json.contains("shepherd-migrate-v5"));
    assert!(json.contains("runs/v645/dispatch/old.json"));

    let snapshot = root.join("evidence");
    let mut confirmed = MigrationRequest::project(&namespace, &runs);
    confirmed.confirm = true;
    confirmed.snapshot_dir = Some(snapshot.clone());
    let applied = execute(&confirmed).expect("confirmed fixture migration");
    assert!(applied.execution.is_some());
    assert!(snapshot.join("before").exists());
    assert!(snapshot.join("manifest.json").is_file());
    assert!(snapshot.join("rollback.sh").is_file());
    assert!(namespace.join("docs/old.md").is_file());
    assert!(namespace.join("runs/v645/dispatch/old.json").is_file());
    assert!(!namespace.join("docs/specs").exists());

    let second = execute(&MigrationRequest::project(&namespace, &runs)).expect("idempotent plan");
    assert!(second.manifest.entries.is_empty());
    cleanup(&root);
}

#[test]
fn dotted_dispatch_branch_id_maps_only_through_an_exact_validated_branch() {
    let root = fixture("unresolved-dispatch");
    let namespace = root.join(".shepherd");
    let runs = namespace.join("runs");
    write(
        &runs.join("v645/run.json"),
        br#"{"run":"v645","branch":"v6.4.5","schema_version":1,"status":"planned"}
"#,
    );
    write(&namespace.join("dispatch/v6.4.5/record.json"), b"record");
    let output = execute(&MigrationRequest::project(&namespace, &runs))
        .expect("the exact run.json branch is an explicit mapping proof");
    assert!(output.manifest.entries.iter().any(|entry| {
        entry.source.ends_with("dispatch/v6.4.5/record.json")
            && entry
                .destination
                .ends_with("runs/v645/dispatch/record.json")
    }));
    cleanup(&root);
}

#[test]
fn user_logs_and_plugin_data_are_rejected_as_project_state() {
    for legacy in ["logs/events.jsonl", "plugin-data/records.json"] {
        let root = fixture("user-invalid");
        let namespace = root.join(".shepherd");
        write(&namespace.join(legacy), b"state");
        let error = execute(&MigrationRequest::user_home(&namespace))
            .expect_err("user home must reject project state");
        assert!(
            error
                .to_string()
                .contains(legacy.split('/').next().unwrap())
        );
        cleanup(&root);
    }
}

#[test]
fn public_cli_dry_run_uses_the_resolved_project_namespace_without_mutation() {
    let root = fixture("public-cli");
    initialize_git(&root);
    let namespace = root.join(".shepherd");
    let runs = namespace.join("runs");
    write(&runs.join("v645/run.json"), &run_state("v645"));
    write(&namespace.join("docs/specs/old.md"), b"old spec");
    let isolated_home = root.join("home");
    fs::create_dir_all(&isolated_home).expect("create isolated home");

    let output = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args([
            "migrate",
            "--layout",
            "v5",
            "--scope",
            "project",
            "--dry-run",
        ])
        .current_dir(&root)
        .env("HOME", &isolated_home)
        .env_remove("SHEPHERD_HOME")
        .env_remove("SHEPHERD_HARNESS")
        .output()
        .expect("run canonical CLI");

    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    let json: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("CLI writes one JSON result");
    assert_eq!(json["schema"], "shepherd-migrate-v5");
    assert_eq!(json["scope"], "project");
    assert!(json["execution"].is_null());
    assert!(namespace.join("docs/specs/old.md").is_file());
    assert!(!namespace.join("docs/old.md").exists());

    cleanup(&root);
}

#[test]
fn public_cli_can_plan_the_legacy_config_that_layout_v5_must_rewrite() {
    let root = fixture("legacy-config-bootstrap");
    initialize_git(&root);
    let namespace = root.join(".shepherd");
    let runs = namespace.join("runs");
    write(&runs.join("v645/run.json"), &run_state("v645"));
    write(&namespace.join("docs/plans/legacy.md"), b"legacy plan");
    write(
        &namespace.join("shepherd.toml"),
        b"[paths]\nplans = \".shepherd/docs/plans\"\nreports = \".shepherd/docs/reports\"\n",
    );
    let isolated_home = root.join("home");
    fs::create_dir_all(&isolated_home).expect("create isolated home");

    let output = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args([
            "migrate",
            "--layout",
            "v5",
            "--scope",
            "project",
            "--dry-run",
        ])
        .current_dir(&root)
        .env("HOME", &isolated_home)
        .env_remove("SHEPHERD_HOME")
        .env_remove("SHEPHERD_HARNESS")
        .output()
        .expect("run canonical CLI against legacy config");

    assert!(
        output.status.success(),
        "migration must be able to read the config it retires: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let json: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("migration plan JSON");
    assert!(
        json["manifest"]["entries"]
            .as_array()
            .expect("manifest entries")
            .iter()
            .any(|entry| entry.to_string().contains("shepherd.toml")),
        "manifest must include the legacy config rewrite"
    );
    assert_eq!(
        fs::read(namespace.join("shepherd.toml")).expect("legacy config preserved"),
        b"[paths]\nplans = \".shepherd/docs/plans\"\nreports = \".shepherd/docs/reports\"\n"
    );

    cleanup(&root);
}

#[test]
fn public_cli_rejects_invalid_retired_fields_in_an_inactive_harness_config() {
    let root = fixture("inactive-harness-invalid");
    initialize_git(&root);
    let namespace = root.join(".shepherd");
    let runs = namespace.join("runs");
    write(&runs.join("v645/run.json"), &run_state("v645"));
    write(
        &namespace.join("shepherd.toml"),
        b"[paths]\nplans = \".shepherd/docs/plans\"\n",
    );
    write(
        &namespace.join("shepherd.pi.toml"),
        b"[paths]\nreports = false\n",
    );
    let isolated_home = root.join("home");
    fs::create_dir_all(&isolated_home).expect("create isolated home");

    let output = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args([
            "migrate",
            "--layout",
            "v5",
            "--scope",
            "project",
            "--dry-run",
        ])
        .current_dir(&root)
        .env("HOME", &isolated_home)
        .env_remove("SHEPHERD_HOME")
        .env_remove("SHEPHERD_HARNESS")
        .output()
        .expect("run canonical CLI against inactive harness config");

    assert!(!output.status.success(), "invalid retired value must block");
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("shepherd.pi.toml"), "{stderr}");
    assert!(stderr.contains("paths.reports"), "{stderr}");
    assert_eq!(
        fs::read(namespace.join("shepherd.pi.toml")).expect("invalid config remains unchanged"),
        b"[paths]\nreports = false\n"
    );

    cleanup(&root);
}

#[test]
fn confirmed_cli_rewrite_is_idempotent_and_readable_by_the_strict_loader() {
    let root = fixture("legacy-config-confirm");
    initialize_git(&root);
    let namespace = root.join(".shepherd");
    let runs = namespace.join("runs");
    write(&runs.join("v645/run.json"), &run_state("v645"));
    let legacy = b"# retain this comment\n[paths]\nplans = \".shepherd/docs/plans\"\nreports = \".shepherd/docs/reports\"\nruns = \".shepherd/runs\"\n\n[memory]\nproject_memory = \".shepherd/memory/project.md\"\nproject_doctrines = \".shepherd/memory/doctrines.md\"\n\n[context]\nenabled = true\ndb_path = \".shepherd/shepherd.db\"\nlock_path = \".shepherd/shepherd.lock\"\nproject_id_path = \".shepherd/project.json\"\n\n[models]\nworker = \"fable\"\n";
    for candidate in [
        "shepherd.toml",
        "shepherd.local.toml",
        "shepherd.claude.toml",
        "shepherd.codex.toml",
        "shepherd.pi.toml",
    ] {
        write(&namespace.join(candidate), legacy);
    }
    let isolated_home = root.join("home");
    fs::create_dir_all(&isolated_home).expect("create isolated home");
    let snapshot = root.join("evidence");

    let confirm = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args([
            "migrate",
            "--layout",
            "v5",
            "--scope",
            "project",
            "--confirm",
            "--snapshot-dir",
            snapshot.to_str().expect("fixture path is UTF-8"),
        ])
        .current_dir(&root)
        .env("HOME", &isolated_home)
        .env_remove("SHEPHERD_HOME")
        .env_remove("SHEPHERD_HARNESS")
        .output()
        .expect("run confirmed canonical CLI");
    assert!(
        confirm.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&confirm.stderr)
    );
    assert!(snapshot.join("before").is_dir());

    for candidate in [
        "shepherd.toml",
        "shepherd.local.toml",
        "shepherd.claude.toml",
        "shepherd.codex.toml",
        "shepherd.pi.toml",
    ] {
        let rewritten = fs::read_to_string(namespace.join(candidate)).expect("rewritten config");
        assert!(rewritten.contains("# retain this comment"));
        for retired in [
            "plans =",
            "reports =",
            "[memory]",
            "project_memory",
            "project_doctrines",
            "enabled =",
            "db_path",
            "lock_path",
            "project_id_path",
        ] {
            assert!(
                !rewritten.contains(retired),
                "{candidate} retains {retired}"
            );
        }
    }

    let strict = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args([
            "--config",
            ".shepherd/shepherd.toml",
            "models",
            "resolve",
            "worker",
        ])
        .current_dir(&root)
        .env("HOME", &isolated_home)
        .env_remove("SHEPHERD_HOME")
        .env_remove("SHEPHERD_HARNESS")
        .output()
        .expect("run ordinary strict command after rewrite");
    assert!(
        strict.status.success(),
        "strict loader rejected rewritten config: {}",
        String::from_utf8_lossy(&strict.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&strict.stdout), "fable\n");

    let replan = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args([
            "migrate",
            "--layout",
            "v5",
            "--scope",
            "project",
            "--dry-run",
        ])
        .current_dir(&root)
        .env("HOME", &isolated_home)
        .env_remove("SHEPHERD_HOME")
        .env_remove("SHEPHERD_HARNESS")
        .output()
        .expect("replan through canonical CLI");
    assert!(
        replan.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&replan.stderr)
    );
    let replan_json: serde_json::Value =
        serde_json::from_slice(&replan.stdout).expect("replan JSON");
    assert!(
        replan_json["manifest"]["entries"]
            .as_array()
            .expect("entries array")
            .is_empty(),
        "rewrite must be idempotent: {replan_json}"
    );

    cleanup(&root);
}

#[test]
fn confirmed_user_home_rewrite_is_idempotent_and_readable_by_the_strict_loader() {
    let root = fixture("legacy-user-config-confirm");
    initialize_git(&root);
    let user_home = root.join("user-home/.shepherd");
    let legacy = b"# retain user comment\n[paths]\nplans = \".shepherd/docs/plans\"\nreports = \".shepherd/docs/reports\"\nruns = \".shepherd/runs\"\n\n[memory]\nproject_memory = \".shepherd/memory/project.md\"\nproject_doctrines = \".shepherd/memory/doctrines.md\"\n\n[context]\nenabled = true\ndb_path = \".shepherd/shepherd.db\"\nlock_path = \".shepherd/shepherd.lock\"\nproject_id_path = \".shepherd/project.json\"\n\n[models]\nworker = \"fable\"\n";
    for candidate in [
        "shepherd.toml",
        "shepherd.local.toml",
        "shepherd.claude.toml",
        "shepherd.codex.toml",
        "shepherd.pi.toml",
    ] {
        write(&user_home.join(candidate), legacy);
    }
    let snapshot = root.join("user-evidence");

    let confirm = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args([
            "migrate",
            "--layout",
            "v5",
            "--scope",
            "user-home",
            "--confirm",
            "--snapshot-dir",
            snapshot.to_str().expect("fixture path is UTF-8"),
        ])
        .current_dir(&root)
        .env("HOME", root.join("user-home"))
        .env("SHEPHERD_HOME", &user_home)
        .env_remove("SHEPHERD_HARNESS")
        .output()
        .expect("run confirmed user-home migration");
    assert!(
        confirm.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&confirm.stderr)
    );
    assert!(snapshot.join("before").is_dir());

    for candidate in [
        "shepherd.toml",
        "shepherd.local.toml",
        "shepherd.claude.toml",
        "shepherd.codex.toml",
        "shepherd.pi.toml",
    ] {
        let rewritten = fs::read_to_string(user_home.join(candidate)).expect("rewritten config");
        assert!(rewritten.contains("# retain user comment"));
        for retired in [
            "plans =",
            "reports =",
            "[memory]",
            "project_memory",
            "project_doctrines",
            "enabled =",
            "db_path",
            "lock_path",
            "project_id_path",
        ] {
            assert!(
                !rewritten.contains(retired),
                "{candidate} retains {retired}"
            );
        }
    }

    let canonical_user_config =
        fs::canonicalize(user_home.join("shepherd.toml")).expect("canonical user config");
    let strict = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args([
            "--config",
            canonical_user_config
                .to_str()
                .expect("fixture path is UTF-8"),
            "models",
            "resolve",
            "worker",
        ])
        .current_dir(&root)
        .env("HOME", root.join("user-home"))
        .env("SHEPHERD_HOME", &user_home)
        .env_remove("SHEPHERD_HARNESS")
        .output()
        .expect("run strict command against rewritten user config");
    assert!(
        strict.status.success(),
        "strict loader rejected rewritten user config: {}",
        String::from_utf8_lossy(&strict.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&strict.stdout), "fable\n");

    let replan = Command::new(env!("CARGO_BIN_EXE_shepherd"))
        .args([
            "migrate",
            "--layout",
            "v5",
            "--scope",
            "user-home",
            "--dry-run",
        ])
        .current_dir(&root)
        .env("HOME", root.join("user-home"))
        .env("SHEPHERD_HOME", &user_home)
        .env_remove("SHEPHERD_HARNESS")
        .output()
        .expect("replan user home through canonical CLI");
    assert!(
        replan.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&replan.stderr)
    );
    let replan_json: serde_json::Value =
        serde_json::from_slice(&replan.stdout).expect("replan JSON");
    assert!(
        replan_json["manifest"]["entries"]
            .as_array()
            .expect("entries array")
            .is_empty(),
        "rewrite must be idempotent: {replan_json}"
    );

    cleanup(&root);
}
