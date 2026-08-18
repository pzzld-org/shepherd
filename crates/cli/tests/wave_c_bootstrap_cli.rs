mod support;

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

fn invoke_with_path(root: &Path, args: &[&str], path: &str) -> Output {
    Command::new(binary())
        .args(args)
        .current_dir(root)
        .env("SHEPHERD_HOME", root.join("isolated-home"))
        .env("PATH", path)
        .output()
        .expect("run shepherd binary with an overridden PATH")
}

/// The inherited `PATH`, minus any directory that already answers
/// `shepherd`. Doctor itself shells out to `git` to resolve the primary
/// root, so a test that wants "nothing resolves `shepherd`" cannot simply
/// hand it an empty `PATH` — that would break `git` resolution too, and
/// the failure would be `context()` erroring out, not the fact under test.
/// Filtering, rather than emptying, keeps every other tool on `PATH`
/// reachable regardless of whether this machine happens to have a real
/// `shepherd` installed somewhere.
fn path_without_any_shepherd() -> String {
    let real = std::env::var_os("PATH").unwrap_or_default();
    let filtered: Vec<PathBuf> = std::env::split_paths(&real)
        .filter(|dir| !dir.join("shepherd").exists() && !dir.join("shepherd.exe").exists())
        .collect();
    std::env::join_paths(filtered)
        .expect("join filtered PATH")
        .to_string_lossy()
        .into_owned()
}

fn text(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes).into_owned()
}

fn cleanup(root: &Path) {
    support::remove_dir_all(root);
}

fn registry_path(root: &Path) -> PathBuf {
    root.join(".shepherd/shepherd.db")
}

fn identity_path(root: &Path) -> PathBuf {
    root.join(".shepherd/project.json")
}

fn project_identity_id(path: &Path) -> String {
    let bytes = std::fs::read(path).expect("read project identity");
    let value: serde_json::Value =
        serde_json::from_slice(&bytes).expect("project identity must be valid JSON");
    value["id"]
        .as_str()
        .expect("project identity id must be a string")
        .to_owned()
}

fn count_project_rows(database: &Path) -> i64 {
    let connection = rusqlite::Connection::open(database).expect("open registry");
    connection
        .query_row("SELECT COUNT(*) FROM projects", [], |row| row.get(0))
        .expect("count projects rows")
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

    // The complete artifact set: project identity, and its matching row.
    // GI1 — a namespace that lacks either of these cannot dispatch, and the
    // gate this replaces never looked at either one.
    let identity = identity_path(&root);
    let identity_metadata =
        std::fs::symlink_metadata(&identity).expect("project identity must exist");
    assert!(
        identity_metadata.is_file(),
        "project identity must be a regular file"
    );
    let id = project_identity_id(&identity);
    let parsed = uuid::Uuid::parse_str(&id).expect("project identity id must be a valid uuid");
    assert_eq!(
        parsed.get_version_num(),
        7,
        "project identity id must be a uuid v7"
    );

    let database = registry_path(&root);
    let connection = rusqlite::Connection::open(&database).expect("open registry");
    let rows: Vec<String> = connection
        .prepare("SELECT id FROM projects")
        .expect("prepare projects query")
        .query_map([], |row| row.get(0))
        .expect("query projects")
        .collect::<Result<Vec<_>, _>>()
        .expect("collect project rows");
    assert_eq!(
        rows,
        vec![id],
        "the projects table must hold exactly one row matching the identity file"
    );

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

// GI2 — doctor is honest: a namespace whose identity vanished after a
// healthy `init` must fail loudly, not report `status: ok`.
#[test]
fn doctor_fails_loudly_on_a_namespace_missing_project_identity() {
    let root = fixture("doctor-missing-identity");
    let initialized = invoke(&root, &["init", "--confirm"]);
    assert_eq!(
        initialized.status.code(),
        Some(0),
        "stderr={}",
        text(&initialized.stderr)
    );

    std::fs::remove_file(identity_path(&root)).expect("remove project identity");

    let sick = invoke(&root, &["doctor"]);
    assert_eq!(sick.status.code(), Some(3));
    let stdout = text(&sick.stdout);
    assert!(
        !stdout.contains("status: ok"),
        "doctor must not report ok on a namespace missing identity: {stdout}"
    );
    assert!(
        stdout.contains("project identity is absent"),
        "doctor must name the missing identity: {stdout}"
    );

    let sick_json = invoke(&root, &["doctor", "--json"]);
    assert_eq!(sick_json.status.code(), Some(3));
    let report: serde_json::Value = serde_json::from_slice(&sick_json.stdout).expect("doctor JSON");
    assert_eq!(report["ok"], false);
    cleanup(&root);
}

// GI3 — scaffolding is atomic: a conflicting `project.json` (here, a
// directory sitting where the identity file must go) must leave nothing
// this invocation created behind, and must never touch what was already
// there.
#[test]
fn init_rolls_back_everything_it_created_when_identity_cannot_be_written() {
    let root = fixture("atomic-rollback");
    let namespace = root.join(".shepherd");
    std::fs::create_dir_all(namespace.join("project.json"))
        .expect("pre-create a conflicting project.json directory");

    let result = invoke(&root, &["init", "--confirm"]);
    assert_ne!(
        result.status.code(),
        Some(0),
        "stdout={}",
        text(&result.stdout)
    );

    for directory in ["docs", "ctx", "runs"] {
        assert!(
            !namespace.join(directory).exists(),
            "{directory} must be rolled back after a failed init"
        );
    }
    assert!(
        !namespace.join("shepherd.toml").exists(),
        "shepherd.toml must be rolled back after a failed init"
    );
    assert!(
        !namespace.join("shepherd.db").exists(),
        "shepherd.db must be rolled back after a failed init"
    );
    assert!(
        namespace.join("project.json").is_dir(),
        "the pre-existing project.json directory must survive untouched"
    );
    cleanup(&root);
}

// GI4 — a repeated `init --confirm` is idempotent, and a namespace that
// already has `shepherd.toml` and `shepherd.db` but lost its identity heals
// to exactly one row, rather than duplicating it.
#[test]
fn init_is_idempotent_and_heals_a_namespace_missing_only_identity() {
    let root = fixture("idempotent-heal");
    let database = registry_path(&root);
    let identity = identity_path(&root);

    let first = invoke(&root, &["init", "--confirm"]);
    assert_eq!(
        first.status.code(),
        Some(0),
        "stderr={}",
        text(&first.stderr)
    );
    let first_id = project_identity_id(&identity);
    assert_eq!(count_project_rows(&database), 1);

    let repeated = invoke(&root, &["init", "--confirm"]);
    assert_eq!(
        repeated.status.code(),
        Some(0),
        "stderr={}",
        text(&repeated.stderr)
    );
    assert_eq!(
        project_identity_id(&identity),
        first_id,
        "a repeated init must not mint a new identity"
    );
    assert_eq!(
        count_project_rows(&database),
        1,
        "a repeated init must not duplicate the projects row"
    );

    // Simulate the operator's partially-scaffolded state: `shepherd.toml`
    // and `shepherd.db` present, identity absent, no registered row.
    std::fs::remove_file(&identity).expect("remove project identity");
    rusqlite::Connection::open(&database)
        .expect("open registry")
        .execute("DELETE FROM projects", [])
        .expect("clear projects row");

    let healed = invoke(&root, &["init", "--confirm"]);
    assert_eq!(
        healed.status.code(),
        Some(0),
        "stderr={}",
        text(&healed.stderr)
    );
    assert!(identity.is_file(), "heal must recreate project identity");
    assert_eq!(
        count_project_rows(&database),
        1,
        "heal must register exactly one project row"
    );
    cleanup(&root);
}

// GD1 — doctor reports install integrity. A binary that is a real, native,
// byte-for-byte copy of `shepherd` but deliberately back-dated years into
// the past must be reported as stale when it is what `PATH` resolves,
// because a version-only check cannot tell it apart from the binary
// running this very check: both report the identical `shepherd-cli`
// version throughout the incident this gate exists to catch.
#[test]
fn doctor_reports_a_stale_shepherd_resolved_from_path() {
    let root = fixture("stale-path");
    let initialized = invoke(&root, &["init", "--confirm"]);
    assert_eq!(
        initialized.status.code(),
        Some(0),
        "stderr={}",
        text(&initialized.stderr)
    );

    let scratch = root.join("scratch-path");
    std::fs::create_dir_all(&scratch).expect("create scratch PATH directory");
    let stale = scratch.join("shepherd");
    std::fs::copy(binary(), &stale).expect("copy the native binary into the scratch PATH entry");
    let ancient = SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(1_000_000_000);
    std::fs::OpenOptions::new()
        .write(true)
        .open(&stale)
        .expect("open the stale copy to back-date it")
        .set_modified(ancient)
        .expect("back-date the stale binary's mtime");

    let path = format!(
        "{}:{}",
        scratch.display(),
        std::env::var("PATH").unwrap_or_default()
    );

    let json = invoke_with_path(&root, &["doctor", "--json"], &path);
    assert_eq!(json.status.code(), Some(0), "stderr={}", text(&json.stderr));
    let report: serde_json::Value = serde_json::from_slice(&json.stdout).expect("doctor JSON");
    assert_eq!(
        report["ok"], true,
        "a stale PATH binary is an environment finding, never a namespace defect: {report}"
    );
    assert_eq!(
        report["resolved_shepherd_path"].as_str().map(PathBuf::from),
        Some(stale.clone()),
        "doctor must resolve PATH in order and find the scratch entry first: {report}"
    );
    assert_eq!(
        report["resolved_shepherd_native"], true,
        "a byte-for-byte copy of the native binary must classify as native: {report}"
    );
    let skew = report["resolved_shepherd_skew_seconds"]
        .as_i64()
        .unwrap_or_else(|| {
            panic!("doctor must report a numeric skew for a resolvable stale binary: {report}")
        });
    assert!(
        skew < 0,
        "a binary back-dated to 2001 must read as stale relative to the freshly built test binary: {report}"
    );

    let text_report = invoke_with_path(&root, &["doctor"], &path);
    assert_eq!(
        text_report.status.code(),
        Some(0),
        "stderr={}",
        text(&text_report.stderr)
    );
    let rendered = text(&text_report.stdout);
    assert!(
        rendered.contains("stale") || rendered.contains("older"),
        "doctor's text report must name the skew: {rendered}"
    );

    cleanup(&root);
}

// GD1 companion — a checkout with nothing on `PATH` at all is a real,
// common developer workflow (`cargo run` / `cargo test` only). Doctor must
// still produce a sensible report, not a crash, and must not fail a
// healthy namespace purely because nothing is installed system-wide.
#[test]
fn doctor_reports_a_sensible_result_when_nothing_answers_shepherd_on_path() {
    let root = fixture("no-path-binary");
    let initialized = invoke(&root, &["init", "--confirm"]);
    assert_eq!(
        initialized.status.code(),
        Some(0),
        "stderr={}",
        text(&initialized.stderr)
    );

    let path = path_without_any_shepherd();

    let json = invoke_with_path(&root, &["doctor", "--json"], &path);
    assert_eq!(json.status.code(), Some(0), "stderr={}", text(&json.stderr));
    let report: serde_json::Value = serde_json::from_slice(&json.stdout).expect("doctor JSON");
    assert_eq!(
        report["ok"], true,
        "no PATH binary at all must not fail a healthy namespace: {report}"
    );
    assert!(
        report["resolved_shepherd_path"].is_null(),
        "nothing on PATH must resolve to nothing: {report}"
    );
    assert!(
        report["warnings"]
            .as_array()
            .expect("warnings must be an array")
            .iter()
            .any(|warning| warning.as_str().is_some_and(|text| text.contains("PATH"))),
        "doctor must still say something about the missing PATH binary: {report}"
    );
    cleanup(&root);
}

/// Recursively collects every `*.rs` file under `dir`. Dependency-free by
/// design (`std::fs` only) — used solely by the sole-inserter invariant
/// test below.
fn collect_rs_files(dir: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    for entry in
        std::fs::read_dir(dir).unwrap_or_else(|error| panic!("read_dir {}: {error}", dir.display()))
    {
        let entry = entry.expect("directory entry");
        let path = entry.path();
        if entry.file_type().expect("entry file type").is_dir() {
            files.extend(collect_rs_files(&path));
        } else if path.extension().is_some_and(|extension| extension == "rs") {
            files.push(path);
        }
    }
    files
}

// Five commands resolve "the current project" by taking the single row out
// of `projects` (`SELECT id FROM projects ORDER BY id LIMIT 1`) rather than
// resolving by identity. That is only safe because exactly one production
// call site ever inserts a row: `wave_c_bootstrap.rs`'s register path. The
// moment a second inserter exists anywhere under `crates/*/src/`, a
// namespace can hold two rows and all five call sites start picking a
// project alphabetically instead of by identity — a failure mode that has
// already been misdiagnosed once this sprint, when a test fixture hand-
// inserted a competing row. This test makes the "exactly one inserter"
// invariant load-bearing instead of implicit.
#[test]
fn wave_c_bootstrap_remains_the_sole_production_inserter_of_projects() {
    let workspace_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("canonicalize workspace root from CARGO_MANIFEST_DIR");
    let crates_dir = workspace_root.join("crates");

    let mut sources = Vec::new();
    for entry in std::fs::read_dir(&crates_dir).expect("read crates/ directory") {
        let entry = entry.expect("crates/ directory entry");
        if !entry.file_type().expect("crate entry file type").is_dir() {
            continue;
        }
        let src_dir = entry.path().join("src");
        if src_dir.is_dir() {
            sources.extend(collect_rs_files(&src_dir));
        }
    }

    let mut offenders: Vec<String> = sources
        .into_iter()
        .filter(|path| {
            std::fs::read_to_string(path)
                .map(|contents| {
                    contents
                        .to_ascii_uppercase()
                        .contains("INSERT INTO PROJECTS")
                })
                .unwrap_or(false)
        })
        .map(|path| {
            path.strip_prefix(&workspace_root)
                .unwrap_or(path.as_path())
                .to_string_lossy()
                .replace('\\', "/")
        })
        .collect();
    offenders.sort();

    assert_eq!(
        offenders,
        vec!["crates/cli/src/cmd/wave_c_bootstrap.rs".to_string()],
        "found {} production `INSERT INTO projects` writer(s): {offenders:?}. Five commands \
         resolve \"the current project\" with `SELECT id FROM projects ORDER BY id LIMIT 1` \
         (crates/cli/src/cmd/wave_h_execution.rs:563, crates/cli/src/cmd/wave_d_planning.rs:785, \
         crates/cli/src/cmd/wave_e_coordination.rs:121, crates/cli/src/cmd/wave_g_coordination.rs:541, \
         crates/cli/src/cmd/wave_f_knowledge.rs:409), so a second inserter makes all five pick a \
         project alphabetically instead of by identity. The correct fix is a shared resolver \
         keyed to `.shepherd/project.json`, not another `INSERT INTO projects` call site.",
        offenders.len(),
    );
}
