/*
    Appellation: execution-context <test>
    Created At: 2026.08.14
    Contrib: @FL03
*/
//! Host discovery and nondeterminism injection at the CLI boundary.

use std::{
    collections::BTreeMap,
    ffi::{OsStr, OsString},
    fs, io,
    path::{Path, PathBuf},
    process::Command,
    sync::{Arc, Mutex},
};

use clap::Parser;
use shepherd_cli::{
    Clock, ContextEnvironment, ContextInputs, ExecutionContext, Harness, IdentifierSource,
    IoBoundary, OutputFormat, RuntimeBindings, ShepherdCli, SystemHost,
};

#[derive(Debug, Default)]
struct FixedEnvironment(BTreeMap<&'static str, OsString>);

impl FixedEnvironment {
    fn with(mut self, key: &'static str, value: impl Into<OsString>) -> Self {
        self.0.insert(key, value.into());
        self
    }
}

impl ContextEnvironment for FixedEnvironment {
    fn var_os(&self, key: &OsStr) -> Option<OsString> {
        self.0
            .iter()
            .find(|(candidate, _)| OsStr::new(candidate) == key)
            .map(|(_, value)| value.clone())
    }
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new(name: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let ordinal = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "shepherd-context-{}-{name}-{ordinal}",
            std::process::id()
        ));
        fs::create_dir_all(&root).expect("create isolated context fixture");
        Self { root }
    }

    fn path(&self, relative: &str) -> PathBuf {
        self.root.join(relative)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        if let Err(error) = fs::remove_dir_all(&self.root)
            && error.kind() != io::ErrorKind::NotFound
        {
            panic!("remove isolated context fixture: {error}");
        }
    }
}

fn git(cwd: &Path, args: &[&str]) {
    let output = Command::new("git")
        .current_dir(cwd)
        .args(args)
        .output()
        .expect("execute git fixture command");
    assert!(
        output.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

fn primary_repo(fixture: &Fixture) -> PathBuf {
    let primary = fixture.path("primary");
    fs::create_dir_all(primary.join(".shepherd")).expect("create primary namespace");
    git(&primary, &["init", "-q"]);
    git(&primary, &["config", "user.name", "Shepherd Tests"]);
    git(
        &primary,
        &["config", "user.email", "shepherd@example.invalid"],
    );
    fs::write(primary.join("README.md"), "fixture\n").expect("write fixture file");
    git(&primary, &["add", "README.md"]);
    git(&primary, &["commit", "-qm", "fixture"]);
    primary
}

#[derive(Debug)]
struct FixedClock(i64);

impl Clock for FixedClock {
    fn now_unix_millis(&self) -> i64 {
        self.0
    }
}

#[derive(Debug)]
struct FixedIds(Vec<String>);

impl IdentifierSource for FixedIds {
    fn next_id(&mut self) -> String {
        self.0.remove(0)
    }
}

#[derive(Debug)]
struct SharedIo {
    stdout: Arc<Mutex<Vec<u8>>>,
    stderr: Arc<Mutex<Vec<u8>>>,
}

impl IoBoundary for SharedIo {
    fn read_stdin(&mut self, _buffer: &mut String) -> io::Result<usize> {
        Ok(0)
    }

    fn write_stdout(&mut self, bytes: &[u8]) -> io::Result<()> {
        self.stdout
            .lock()
            .expect("stdout lock")
            .extend_from_slice(bytes);
        Ok(())
    }

    fn write_stderr(&mut self, bytes: &[u8]) -> io::Result<()> {
        self.stderr
            .lock()
            .expect("stderr lock")
            .extend_from_slice(bytes);
        Ok(())
    }
}

fn bindings(stdout: Arc<Mutex<Vec<u8>>>, stderr: Arc<Mutex<Vec<u8>>>) -> RuntimeBindings {
    RuntimeBindings::new(
        Box::new(FixedClock(1_725_000_000_123)),
        Box::new(FixedIds(vec!["id-1".into(), "id-2".into()])),
        Box::new(SharedIo { stdout, stderr }),
    )
}

#[test]
fn environment_inputs_validate_the_explicit_harness_and_preserve_home_inputs() {
    let environment = FixedEnvironment::default()
        .with("SHEPHERD_HOME", "/tmp/shepherd-user")
        .with("HOME", "/tmp/operator")
        .with("SHEPHERD_HARNESS", "pi")
        .with("CLAUDECODE", "1")
        .with("CODEX_HOME", "/tmp/codex");

    let inputs = ContextInputs::from_environment_with("/repo", &environment)
        .expect("the explicit supported harness wins");

    assert_eq!(inputs.start_dir, PathBuf::from("/repo"));
    assert_eq!(
        inputs.shepherd_home,
        Some(PathBuf::from("/tmp/shepherd-user"))
    );
    assert_eq!(inputs.home_dir, Some(PathBuf::from("/tmp/operator")));
    assert_eq!(inputs.active_harness, Some(Harness::Pi));
}

#[test]
fn environment_inputs_use_only_supported_host_markers_when_no_harness_is_explicit() {
    let claude = ContextInputs::from_environment_with(
        "/repo",
        &FixedEnvironment::default()
            .with("CLAUDE_PLUGIN_ROOT", "/plugin")
            .with("CODEX_HOME", "/tmp/codex"),
    )
    .expect("Claude marker resolves");
    let codex = ContextInputs::from_environment_with(
        "/repo",
        &FixedEnvironment::default().with("CODEX_HOME", "/tmp/codex"),
    )
    .expect("Codex marker resolves");
    let absent = ContextInputs::from_environment_with("/repo", &FixedEnvironment::default())
        .expect("missing markers are valid");

    assert_eq!(claude.active_harness, Some(Harness::ClaudeCode));
    assert_eq!(codex.active_harness, Some(Harness::Codex));
    assert_eq!(absent.active_harness, None);
}

#[test]
fn environment_harness_selects_only_its_canonical_override_candidate() {
    let fixture = Fixture::new("environment-harness-config");
    let primary = primary_repo(&fixture);
    fs::write(
        primary.join(".shepherd/shepherd.toml"),
        "[project]\nname = \"base\"\n",
    )
    .expect("write base config");
    fs::write(
        primary.join(".shepherd/shepherd.pi.toml"),
        "[project]\nname = \"pi\"\n",
    )
    .expect("write Pi config");
    fs::write(
        primary.join(".shepherd/shepherd.codex.toml"),
        "[project]\nname = \"codex\"\n",
    )
    .expect("write Codex config");
    let environment = FixedEnvironment::default().with("SHEPHERD_HARNESS", "pi");
    let inputs =
        ContextInputs::from_environment_with(&primary, &environment).expect("Pi harness resolves");

    let context = ExecutionContext::resolve_with(
        inputs,
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect("Pi context resolves");

    assert_eq!(context.active_harness, Some(Harness::Pi));
    assert_eq!(context.config.project.name.as_deref(), Some("pi"));
    assert!(
        context
            .config_sources
            .iter()
            .all(|source| !source.path.ends_with("shepherd.codex.toml"))
    );
}

#[test]
fn environment_inputs_reject_an_unknown_explicit_harness_without_echoing_it() {
    let error = ContextInputs::from_environment_with(
        "/repo",
        &FixedEnvironment::default().with("SHEPHERD_HARNESS", "secret-unknown-harness"),
    )
    .expect_err("an unknown explicit harness must not silently drop its config tier")
    .to_string();

    assert!(error.contains("SHEPHERD_HARNESS"), "{error}");
    assert!(!error.contains("secret-unknown-harness"), "{error}");
}

#[test]
fn environment_inputs_treat_empty_home_variables_as_absent() {
    let inputs = ContextInputs::from_environment_with(
        "/repo",
        &FixedEnvironment::default()
            .with("SHEPHERD_HOME", "")
            .with("HOME", ""),
    )
    .expect("empty optional home inputs are equivalent to absence");

    assert_eq!(inputs.shepherd_home, None);
    assert_eq!(inputs.home_dir, None);
}

#[test]
fn primary_checkout_loads_project_over_user_and_resolves_custom_runs() {
    let fixture = Fixture::new("primary");
    let primary = primary_repo(&fixture);
    let user = fixture.path("user");
    fs::create_dir_all(&user).expect("create user config root");
    fs::write(
        user.join("shepherd.local.toml"),
        "[project]\nname = \"user\"\n[spawn]\nmax_parallel = 9\n",
    )
    .expect("write user config");
    fs::write(
        primary.join(".shepherd/shepherd.toml"),
        "[project]\nname = \"primary\"\n[paths]\nruns = \".shepherd/executions\"\n",
    )
    .expect("write project config");

    let stdout = Arc::new(Mutex::new(Vec::new()));
    let stderr = Arc::new(Mutex::new(Vec::new()));
    let canonical_primary = primary.canonicalize().expect("canonical primary");
    let canonical_user = user.canonicalize().expect("canonical user home");
    let context = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary.join(".shepherd"),
            shepherd_home: Some(user.clone()),
            output_format: OutputFormat::Json,
            verbosity: 2,
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(stdout, stderr),
    )
    .expect("resolve primary context");

    assert_eq!(context.primary_root, canonical_primary);
    assert_eq!(context.user_home.as_deref(), Some(canonical_user.as_path()));
    assert_eq!(context.config.project.name.as_deref(), Some("primary"));
    assert_eq!(context.config.spawn.max_parallel, 9);
    assert_eq!(
        context.runs_root,
        canonical_primary.join(".shepherd/executions")
    );
    assert_eq!(
        context.registry_path,
        canonical_primary.join(".shepherd/shepherd.db")
    );
    assert_eq!(
        context.project_id_path,
        canonical_primary.join(".shepherd/project.json")
    );
    assert_eq!(
        context.dups_registry_path,
        canonical_primary.join(".shepherd/ctx/dups-registry.json")
    );
    assert_eq!(context.output_format, OutputFormat::Json);
    assert_eq!(context.verbosity, 2);
    assert_eq!(
        context
            .config_sources
            .iter()
            .map(|source| source.path.as_path())
            .collect::<Vec<_>>(),
        vec![
            canonical_primary.join(".shepherd/shepherd.toml"),
            canonical_user.join("shepherd.local.toml"),
        ]
    );
}

#[test]
fn linked_worktree_uses_primary_namespace_and_ignores_a_copied_local_namespace() {
    let fixture = Fixture::new("linked");
    let primary = primary_repo(&fixture);
    fs::write(
        primary.join(".shepherd/shepherd.toml"),
        "[project]\nname = \"primary-truth\"\n[paths]\nruns = \".shepherd/custom-runs\"\n",
    )
    .expect("write primary config");
    let linked = fixture.path("linked");
    git(
        &primary,
        &[
            "worktree",
            "add",
            "-qb",
            "linked-test",
            linked.to_str().expect("utf8 fixture path"),
        ],
    );
    fs::create_dir_all(linked.join(".shepherd/runs/copied"))
        .expect("create copied linked namespace");
    fs::write(
        linked.join(".shepherd/shepherd.local.toml"),
        "[project]\nname = \"copied-shadow\"\n",
    )
    .expect("write copied shadow config");
    fs::write(linked.join(".shepherd/runs/copied/run.json"), "{}\n")
        .expect("write copied shadow run");

    let context = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: linked.clone(),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect("resolve linked context");

    let canonical_primary = primary.canonicalize().expect("canonical primary");
    assert_eq!(context.primary_root, canonical_primary);
    assert_eq!(
        context.config.project.name.as_deref(),
        Some("primary-truth")
    );
    assert_eq!(
        context.runs_root,
        canonical_primary.join(".shepherd/custom-runs")
    );
    assert!(
        context
            .config_sources
            .iter()
            .all(|source| !source.path.starts_with(&linked)),
        "linked checkout config must not shadow primary provenance"
    );
}

#[test]
fn ambiguous_linked_worktree_requires_and_honors_an_explicit_primary_fallback() {
    let fixture = Fixture::new("linked-separate-git-dir");
    let primary = fixture.path("primary");
    let git_data = fixture.path("git-data");
    git(
        &fixture.root,
        &[
            "init",
            "-q",
            "--separate-git-dir",
            git_data.to_str().expect("utf8 git data path"),
            primary.to_str().expect("utf8 primary path"),
        ],
    );
    fs::create_dir_all(primary.join(".shepherd")).expect("create primary namespace");
    git(&primary, &["config", "user.name", "Shepherd Tests"]);
    git(
        &primary,
        &["config", "user.email", "shepherd@example.invalid"],
    );
    fs::write(primary.join("README.md"), "fixture\n").expect("write fixture file");
    git(&primary, &["add", "README.md"]);
    git(&primary, &["commit", "-qm", "fixture"]);
    fs::write(
        primary.join(".shepherd/shepherd.toml"),
        "[project]\nname = \"primary-truth\"\n",
    )
    .expect("write primary config");
    let linked = fixture.path("linked");
    git(
        &primary,
        &[
            "worktree",
            "add",
            "-qb",
            "separate-linked-test",
            linked.to_str().expect("utf8 linked path"),
        ],
    );
    fs::create_dir_all(linked.join(".shepherd")).expect("create linked namespace");
    fs::write(
        linked.join(".shepherd/shepherd.local.toml"),
        "[project]\nname = \"copied-shadow\"\n",
    )
    .expect("write copied linked config");

    let without_fallback = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: linked.clone(),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    );
    assert!(
        without_fallback.is_err(),
        "an ambiguous common directory must not turn the linked checkout into primary truth"
    );

    let context = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: linked,
            primary_fallback: Some(primary.clone()),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect("explicit primary fallback resolves ambiguous linked metadata");

    assert_eq!(
        context.primary_root,
        primary.canonicalize().expect("canonical primary")
    );
    assert_eq!(
        context.config.project.name.as_deref(),
        Some("primary-truth")
    );
}

#[test]
fn explicit_canonical_config_selects_one_file_without_adding_a_seventh_tier() {
    let fixture = Fixture::new("explicit");
    let primary = primary_repo(&fixture);
    fs::write(
        primary.join(".shepherd/shepherd.local.toml"),
        "[project]\nname = \"automatic-winner\"\n",
    )
    .expect("write local config");
    fs::write(
        primary.join(".shepherd/shepherd.toml"),
        "[project]\nname = \"explicit-base\"\n",
    )
    .expect("write base config");
    let canonical_primary = primary.canonicalize().expect("canonical primary");

    let context = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary.clone(),
            explicit_config: Some(canonical_primary.join(".shepherd/shepherd.toml")),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect("resolve explicit config");

    assert_eq!(
        context.config.project.name.as_deref(),
        Some("explicit-base")
    );
    assert_eq!(context.config_sources.len(), 1);
    assert_eq!(
        context.config_sources[0].path,
        canonical_primary.join(".shepherd/shepherd.toml")
    );
}

#[test]
fn arbitrary_explicit_config_is_rejected_instead_of_becoming_a_hidden_tier() {
    let fixture = Fixture::new("explicit-reject");
    let primary = primary_repo(&fixture);
    fs::write(primary.join("other.toml"), "[project]\nname = \"other\"\n")
        .expect("write noncanonical config");

    let error = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary,
            explicit_config: Some(PathBuf::from("other.toml")),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect_err("noncanonical explicit config must fail")
    .to_string();

    assert!(error.contains("canonical"), "{error}");
    assert!(
        !error.contains("other\""),
        "config contents must never be echoed: {error}"
    );
}

#[cfg(unix)]
#[test]
fn explicit_config_rejects_a_symlink_alias_outside_the_canonical_candidate_set() {
    use std::os::unix::fs::symlink;

    let fixture = Fixture::new("explicit-symlink-alias");
    let primary = primary_repo(&fixture);
    let canonical = primary.join(".shepherd/shepherd.toml");
    fs::write(&canonical, "[project]\nname = \"canonical\"\n").expect("write canonical config");
    let alias = primary.join("config-alias.toml");
    symlink(&canonical, &alias).expect("create config alias");

    let error = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary,
            explicit_config: Some(alias),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect_err("a symlink alias is not one of the canonical candidate paths")
    .to_string();

    assert!(error.contains("canonical shepherd candidate"), "{error}");
}

#[cfg(unix)]
#[test]
fn ordinary_resolution_rejects_a_canonical_candidate_that_is_a_symlink() {
    use std::os::unix::fs::symlink;

    let fixture = Fixture::new("candidate-symlink");
    let primary = primary_repo(&fixture);
    let external = fixture.path("external.toml");
    fs::write(&external, "[project]\nname = \"must-not-load\"\n").expect("write external config");
    let candidate = primary.join(".shepherd/shepherd.toml");
    symlink(&external, &candidate).expect("create symlinked candidate");

    let error = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary,
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect_err("ordinary resolution must not follow a symlinked candidate")
    .to_string();

    assert!(error.contains("not canonical"), "{error}");
    assert!(!error.contains("must-not-load"), "{error}");
}

#[test]
fn custom_context_root_rehomes_the_duplicate_registry_filename() {
    let fixture = Fixture::new("custom-context-root");
    let primary = primary_repo(&fixture);
    fs::write(
        primary.join(".shepherd/shepherd.toml"),
        "[paths]\nctx = \".shepherd/knowledge\"\n[dups]\ndups_registry = \"curated.json\"\n",
    )
    .expect("write custom context config");

    let context = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary.clone(),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect("custom context paths resolve");

    let canonical_primary = primary.canonicalize().expect("canonical primary");
    assert_eq!(
        context.dups_registry_path,
        canonical_primary.join(".shepherd/knowledge/curated.json")
    );
}

#[cfg(unix)]
#[test]
fn resolved_project_paths_reject_symlinked_roots_and_knowledge_files() {
    use std::os::unix::fs::symlink;

    for (relative, expected_key, target_is_directory) in [
        (".shepherd/ctx", "paths.ctx", true),
        (".shepherd/runs", "paths.runs", true),
        (
            ".shepherd/ctx/dups-registry.json",
            "dups.dups_registry",
            false,
        ),
    ] {
        let fixture = Fixture::new(expected_key);
        let primary = primary_repo(&fixture);
        fs::create_dir_all(primary.join(".shepherd/ctx")).expect("create context root");
        let link = primary.join(relative);
        if link.exists() {
            if link.is_dir() {
                fs::remove_dir(&link).expect("remove empty canonical directory");
            } else {
                fs::remove_file(&link).expect("remove canonical file");
            }
        }
        let external = fixture.path("external");
        if target_is_directory {
            fs::create_dir_all(&external).expect("create external directory");
        } else {
            fs::write(&external, "{}\n").expect("create external knowledge file");
        }
        symlink(&external, &link).expect("create escaping symlink");

        let error = ExecutionContext::resolve_with(
            ContextInputs {
                start_dir: primary,
                ..ContextInputs::default()
            },
            &SystemHost,
            bindings(
                Arc::new(Mutex::new(Vec::new())),
                Arc::new(Mutex::new(Vec::new())),
            ),
        )
        .expect_err("resolved project paths must not follow symlinks")
        .to_string();

        assert!(error.contains(expected_key), "{error}");
        assert!(!error.contains("external"), "{error}");
    }
}

#[cfg(unix)]
#[test]
fn resolved_project_paths_reject_dangling_symlinks_and_file_ancestors() {
    use std::os::unix::fs::symlink;

    let fixture = Fixture::new("dangling-paths");
    let primary = primary_repo(&fixture);
    let dangling_ctx = primary.join(".shepherd/ctx");
    symlink("missing-context", &dangling_ctx).expect("create dangling context symlink");

    let error = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary.clone(),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect_err("dangling context symlink must fail closed")
    .to_string();
    assert!(error.contains("paths.ctx"), "{error}");

    fs::remove_file(&dangling_ctx).expect("remove dangling context symlink");
    fs::write(&dangling_ctx, "not-a-directory\n").expect("create file ancestor");
    let error = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary.clone(),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect_err("a project root cannot be a regular file")
    .to_string();
    assert!(error.contains("paths.ctx"), "{error}");

    let nested_config = primary.join(".shepherd/shepherd.toml");
    fs::write(&nested_config, "[paths]\ndocs = \".shepherd/ctx/docs\"\n")
        .expect("write nested path config");
    let error = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary,
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect_err("a file ancestor cannot be a project root")
    .to_string();
    assert!(error.contains("paths.docs"), "{error}");
}

#[test]
fn explicit_primary_fallback_and_missing_user_home_are_read_only() {
    let fixture = Fixture::new("fallback");
    let primary = fixture.path("not-a-git-repo");
    fs::create_dir_all(primary.join(".shepherd")).expect("create fallback namespace");

    let context = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary.clone(),
            primary_fallback: Some(primary.clone()),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(Mutex::new(Vec::new())),
        ),
    )
    .expect("fallback resolves");

    assert_eq!(context.user_home, None);
    assert!(context.config_sources.is_empty());
    assert!(!fixture.path("not-a-git-repo/.shepherd/docs").exists());
    assert!(!fixture.path("not-a-git-repo/.shepherd/runs").exists());
}

#[test]
fn shepherd_user_home_cannot_overlap_the_project_namespace() {
    for relative in [".shepherd", ".shepherd/user-defaults"] {
        let fixture = Fixture::new("overlapping-user-home");
        let primary = primary_repo(&fixture);
        let user_home = primary.join(relative);
        fs::create_dir_all(&user_home).expect("create overlapping user home");

        let error = ExecutionContext::resolve_with(
            ContextInputs {
                start_dir: primary,
                shepherd_home: Some(user_home),
                ..ContextInputs::default()
            },
            &SystemHost,
            bindings(
                Arc::new(Mutex::new(Vec::new())),
                Arc::new(Mutex::new(Vec::new())),
            ),
        )
        .expect_err("project and user namespaces must have separate ownership")
        .to_string();

        assert!(error.contains("must not overlap"), "{error}");
    }
}

#[test]
fn clock_identifiers_and_stdio_are_injected_and_observable() {
    let fixture = Fixture::new("bindings");
    let primary = fixture.path("repo");
    fs::create_dir_all(primary.join(".shepherd")).expect("create fallback namespace");
    let stdout = Arc::new(Mutex::new(Vec::new()));
    let stderr = Arc::new(Mutex::new(Vec::new()));

    let mut context = ExecutionContext::resolve_with(
        ContextInputs {
            start_dir: primary.clone(),
            primary_fallback: Some(primary),
            ..ContextInputs::default()
        },
        &SystemHost,
        bindings(Arc::clone(&stdout), Arc::clone(&stderr)),
    )
    .expect("context resolves");

    assert_eq!(context.now_unix_millis(), 1_725_000_000_123);
    assert_eq!(context.next_id(), "id-1");
    assert_eq!(context.next_id(), "id-2");
    context.write_stdout(b"out").expect("write stdout");
    context.write_stderr(b"err").expect("write stderr");
    assert_eq!(&*stdout.lock().expect("stdout lock"), b"out");
    assert_eq!(&*stderr.lock().expect("stderr lock"), b"err");
}

#[test]
fn help_and_version_do_not_construct_context_or_create_user_home() {
    let fixture = Fixture::new("help");
    let user_home = fixture.path("absent-user-home");
    let binary = env!("CARGO_BIN_EXE_shepherd");

    for argument in ["--help", "--version"] {
        let output = Command::new(binary)
            .arg(argument)
            .current_dir(&fixture.root)
            .env("SHEPHERD_HOME", &user_home)
            .output()
            .expect("run real shepherd informational entrypoint");
        assert!(
            output.status.success(),
            "{argument} failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    assert!(!user_home.exists());
    assert!(!fixture.path(".shepherd").exists());
}

#[test]
fn cli_distinguishes_automatic_precedence_from_an_explicit_config() {
    let automatic = ShepherdCli::try_parse_from(["shepherd", "--verbose"])
        .expect("verbosity makes an otherwise commandless parse explicit");
    let explicit =
        ShepherdCli::try_parse_from(["shepherd", "--config", ".shepherd/shepherd.local.toml"])
            .expect("explicit config parses");

    assert_eq!(automatic.config, None);
    assert_eq!(
        explicit.config.as_deref(),
        Some(".shepherd/shepherd.local.toml")
    );
}
