use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::time::{SystemTime, UNIX_EPOCH};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "shepherd-wave-c-bootstrap-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    std::fs::create_dir_all(&root).expect("create fixture root");
    let status = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&root)
        .status()
        .expect("initialize fixture git repository");
    assert!(status.success(), "git init must succeed");
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

fn cleanup(root: &Path) {
    std::fs::remove_dir_all(root).expect("remove fixture");
}

#[test]
fn init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots() {
    let root = fixture("init");

    let refused = invoke(&root, &["init"]);
    assert_eq!(refused.status.code(), Some(2));
    assert_eq!(
        text(&refused.stderr),
        "ERROR: init is mutating; re-run with --confirm\n"
    );
    assert!(!root.join(".shepherd").exists());

    let initialized = invoke(&root, &["init", "--confirm"]);
    assert_eq!(
        initialized.status.code(),
        Some(0),
        "stderr={}",
        text(&initialized.stderr)
    );
    assert!(
        text(&initialized.stdout).starts_with("initialized layout-v5 namespace: "),
        "stdout={}",
        text(&initialized.stdout)
    );
    for directory in ["docs", "ctx", "runs"] {
        assert!(
            root.join(".shepherd").join(directory).is_dir(),
            "{directory} must be part of the approved layout-v5 project shape"
        );
    }
    assert!(root.join(".shepherd/shepherd.toml").is_file());
    assert!(root.join(".shepherd/shepherd.db").is_file());
    for retired in ["graph", "reports", "audits", "plans", "dispatch"] {
        assert!(
            !root.join(".shepherd").join(retired).exists(),
            "init must not recreate retired root {retired}"
        );
    }

    let repeated = invoke(&root, &["init", "--confirm"]);
    assert_eq!(
        repeated.status.code(),
        Some(0),
        "stderr={}",
        text(&repeated.stderr)
    );
    cleanup(&root);
}

#[test]
fn config_reads_typed_defaults_and_requires_confirmation_to_create_its_document() {
    let root = fixture("config");
    let expected = std::fs::canonicalize(&root)
        .expect("canonical root")
        .join(".shepherd/shepherd.toml");

    let path = invoke(&root, &["config", "path"]);
    assert_eq!(path.status.code(), Some(0), "stderr={}", text(&path.stderr));
    assert_eq!(text(&path.stdout), format!("{}\n", expected.display()));
    assert!(!root.join(".shepherd").exists(), "path is read-only");

    let value = invoke(&root, &["config", "get", "paths.runs"]);
    assert_eq!(
        value.status.code(),
        Some(0),
        "stderr={}",
        text(&value.stderr)
    );
    assert_eq!(text(&value.stdout), ".shepherd/runs\n");
    assert!(!root.join(".shepherd").exists(), "get is read-only");

    let refused = invoke(&root, &["config", "init"]);
    assert_eq!(refused.status.code(), Some(2));
    assert_eq!(
        text(&refused.stderr),
        "ERROR: config init is mutating; re-run with --confirm\n"
    );
    assert!(!root.join(".shepherd").exists());

    let initialized = invoke(&root, &["config", "init", "--confirm"]);
    assert_eq!(
        initialized.status.code(),
        Some(0),
        "stderr={}",
        text(&initialized.stderr)
    );
    assert!(root.join(".shepherd/shepherd.toml").is_file());
    let show = invoke(&root, &["config", "show"]);
    assert_eq!(show.status.code(), Some(0), "stderr={}", text(&show.stderr));
    assert!(text(&show.stdout).contains("\"paths\""));
    cleanup(&root);
}

#[test]
fn home_and_doctor_are_read_only_until_explicitly_confirmed() {
    let root = fixture("home-doctor");
    let home = root.join("isolated-home");

    let which = invoke(&root, &["home", "which"]);
    assert_eq!(
        which.status.code(),
        Some(0),
        "stderr={}",
        text(&which.stderr)
    );
    assert_eq!(text(&which.stdout), format!("{}\n", home.display()));
    assert!(!home.exists(), "home which must not create the path");

    let show = invoke(&root, &["home", "show"]);
    assert_eq!(show.status.code(), Some(0), "stderr={}", text(&show.stderr));
    assert_eq!(text(&show.stdout), format!("home: {}\n", home.display()));
    assert!(!home.exists(), "home show must not create the path");

    let refused = invoke(&root, &["home", "init"]);
    assert_eq!(refused.status.code(), Some(2));
    assert_eq!(
        text(&refused.stderr),
        "ERROR: home init is mutating; re-run with --confirm\n"
    );
    assert!(!home.exists());

    let sick = invoke(&root, &["doctor", "--json"]);
    assert_eq!(sick.status.code(), Some(3));
    let report: serde_json::Value = serde_json::from_slice(&sick.stdout).expect("doctor JSON");
    assert_eq!(report["ok"], false);
    assert!(
        !root.join(".shepherd").exists(),
        "doctor must not bootstrap"
    );

    let initialized = invoke(&root, &["home", "init", "--confirm"]);
    assert_eq!(
        initialized.status.code(),
        Some(0),
        "stderr={}",
        text(&initialized.stderr)
    );
    assert!(home.is_dir());
    assert!(
        !home.join("profiles").exists(),
        "unused profile authority must not be recreated"
    );
    assert!(
        !home.join("templates").exists(),
        "user templates have no native resolver and must not be recreated"
    );

    let project = invoke(&root, &["init", "--confirm"]);
    assert_eq!(
        project.status.code(),
        Some(0),
        "stderr={}",
        text(&project.stderr)
    );
    let healthy = invoke(&root, &["doctor", "--json"]);
    assert_eq!(
        healthy.status.code(),
        Some(0),
        "stderr={}",
        text(&healthy.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&healthy.stdout).expect("doctor JSON");
    assert_eq!(report["ok"], true);
    assert!(report["registry_schema"].as_u64().is_some());
    cleanup(&root);
}

#[test]
fn init_user_option_bootstraps_only_the_separately_resolved_user_home() {
    let root = fixture("init-user");
    let home = root.join("isolated-home");
    let initialized = invoke(&root, &["init", "--confirm", "--user"]);
    assert_eq!(
        initialized.status.code(),
        Some(0),
        "stderr={}",
        text(&initialized.stderr)
    );
    assert!(home.is_dir());
    assert!(!home.join("profiles").exists());
    assert!(!home.join("templates").exists());
    assert!(
        !home.join("runs").exists(),
        "project roots never leak into user home"
    );
    cleanup(&root);
}

#[cfg(unix)]
#[test]
fn init_refuses_a_symlink_namespace_without_touching_its_target() {
    use std::os::unix::fs::symlink;

    let root = fixture("symlink");
    let outside = root.join("outside");
    std::fs::create_dir_all(&outside).expect("create outside target");
    symlink(&outside, root.join(".shepherd")).expect("create namespace symlink");

    let result = invoke(&root, &["init", "--confirm"]);
    assert_ne!(result.status.code(), Some(0));
    assert!(!outside.join("docs").exists());
    assert!(!outside.join("shepherd.toml").exists());
    assert!(!outside.join("shepherd.db").exists());
    cleanup(&root);
}

#[cfg(unix)]
#[test]
fn init_refuses_an_existing_config_symlink_instead_of_reporting_success() {
    use std::os::unix::fs::symlink;

    let root = fixture("config-symlink");
    let namespace = root.join(".shepherd");
    std::fs::create_dir_all(&namespace).expect("create real namespace");
    let outside = root.join("outside-shepherd.toml");
    let original = b"# external config must remain untouched\n";
    std::fs::write(&outside, original).expect("write external config");
    symlink(&outside, namespace.join("shepherd.toml")).expect("create config symlink");

    let result = invoke(&root, &["init", "--confirm"]);
    assert_ne!(result.status.code(), Some(0));
    assert!(text(&result.stderr).contains("symbolic") || text(&result.stderr).contains("link"));
    assert_eq!(
        std::fs::read(&outside).expect("read external config"),
        original
    );
    assert!(!namespace.join("shepherd.db").exists());
    cleanup(&root);
}

#[test]
fn top_level_migrate_stays_an_explicit_dry_run_until_confirmation() {
    let root = fixture("migrate");
    let namespace = root.join(".shepherd");
    std::fs::create_dir_all(namespace.join("runs/v645")).expect("create canonical run root");
    std::fs::create_dir_all(namespace.join("docs/specs")).expect("create legacy docs root");
    std::fs::write(
        namespace.join("runs/v645/run.json"),
        b"{\"run\":\"v645\",\"schema_version\":1,\"status\":\"planned\"}\n",
    )
    .expect("write run document");
    std::fs::write(namespace.join("docs/specs/legacy.md"), b"legacy\n")
        .expect("write legacy document");

    let result = invoke(&root, &["migrate", "--dry-run"]);
    assert_eq!(
        result.status.code(),
        Some(0),
        "stderr={}",
        text(&result.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&result.stdout).expect("migrate JSON");
    assert_eq!(report["schema"], "shepherd-migrate-v5");
    assert!(report["execution"].is_null());
    assert!(namespace.join("docs/specs/legacy.md").is_file());
    assert!(!namespace.join("docs/legacy.md").exists());
    cleanup(&root);
}
