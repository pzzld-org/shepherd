use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use shepherd_registry::layout::{
    Authorization, LayoutPlan, MigrationOptions, PlanAction, PlanScope,
};

fn fixture(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after epoch")
        .as_nanos();
    let path = std::env::temp_dir().join(format!("shepherd-layout-v5-{label}-{nonce:x}"));
    fs::create_dir_all(&path).expect("create fixture");
    path
}

fn write(path: &Path, bytes: &[u8]) {
    fs::create_dir_all(path.parent().expect("fixture parent")).expect("create parent");
    fs::write(path, bytes).expect("write fixture");
}

fn run_json(run: &str) -> Vec<u8> {
    format!(
        r#"{{"run":"{run}","schema_version":1,"status":"planned"}}
"#
    )
    .into_bytes()
}

fn run_json_with_branch(run: &str, branch: &str) -> Vec<u8> {
    format!(
        r#"{{"run":"{run}","branch":"{branch}","schema_version":1,"status":"planned"}}
"#
    )
    .into_bytes()
}

fn cleanup(path: &Path) {
    fs::remove_dir_all(path).expect("remove fixture");
}

#[test]
fn plans_flat_docs_and_run_artifacts_deterministically() {
    let root = fixture("flat");
    let namespace = root.join(".shepherd");
    write(&namespace.join("runs/v645/run.json"), &run_json("v645"));
    write(
        &namespace.join("docs/specs/2026-08-14-layout.md"),
        b"design",
    );
    write(&namespace.join("docs/specs/.gitkeep"), b"");
    write(&namespace.join("plans/v645.seed.md"), b"seed");
    write(&namespace.join("dispatch/v645/old.json"), b"dispatch");
    write(&namespace.join("CONVENTIONS.md"), b"old namespace mirror");
    write(&namespace.join(".gitignore"), b"logs/\n");

    let plan = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect("fixture is a valid project migration");
    assert_eq!(plan.scope(), PlanScope::Project);
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.destination.ends_with("docs/2026-08-14-layout.md") && entry.action == PlanAction::Move
    }));
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.destination.ends_with("runs/v645/seed.md") && entry.action == PlanAction::Move
    }));
    assert!(plan.manifest().entries.iter().all(|entry| {
        !entry.destination.contains("docs/specs/")
            && !entry.destination.contains("plans/")
            && !entry.destination.contains("dispatch/v645/")
    }));
    assert!(
        plan.manifest()
            .entries
            .iter()
            .any(|entry| entry.action == PlanAction::RemoveFile)
    );
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.source.ends_with("CONVENTIONS.md")
            && entry.destination.ends_with("docs/CONVENTIONS.md")
    }));
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.source.ends_with(".shepherd/.gitignore")
            && entry.action == PlanAction::RemoveFile
            && entry.provenance.contains("repository ignore")
    }));
    let first_manifest = plan.manifest_json().expect("serialize manifest");
    assert_eq!(first_manifest, plan.manifest_json().unwrap());
    cleanup(&root);
}

#[test]
fn snapshot_removes_retired_runtime_tmp_files_instead_of_polluting_flat_docs() {
    let root = fixture("retired-runtime-tmp");
    let namespace = root.join(".shepherd");
    write(
        &namespace.join("tmp/gates-ran-session.jsonl"),
        br#"{"gate":"fast","status":"ok"}
"#,
    );
    write(
        &namespace.join("tmp/coordinate-guard-session.count"),
        b"2\n",
    );

    let plan = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect("retired runtime temp files have one safe migration");
    let retired = plan
        .manifest()
        .entries
        .iter()
        .filter(|entry| entry.source.contains("/.shepherd/tmp/"))
        .collect::<Vec<_>>();
    assert_eq!(retired.len(), 2, "both runtime temp files are planned");
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.source.ends_with("/.shepherd/tmp") && entry.action == PlanAction::RemoveDirectory
    }));
    let retired_files = retired
        .iter()
        .filter(|entry| entry.action == PlanAction::RemoveFile)
        .collect::<Vec<_>>();
    assert_eq!(retired_files.len(), 2);
    assert!(retired_files.iter().all(|entry| {
        entry.destination.is_empty()
            && entry.classification == "retired-runtime-tmp"
            && entry.provenance.contains("snapshot")
    }));
    assert!(
        retired
            .iter()
            .all(|entry| !entry.destination.contains("/docs/"))
    );

    let evidence = root.join("evidence");
    plan.execute(&MigrationOptions {
        authorization: Some(Authorization::Project),
        confirm: true,
        snapshot_dir: Some(evidence.clone()),
        ..MigrationOptions::default()
    })
    .expect("snapshot-backed temporary runtime cleanup succeeds");
    assert!(!namespace.join("tmp").exists());
    assert!(!namespace.join("docs/gates-ran-session.jsonl").exists());
    assert!(
        evidence
            .join("before/tmp/gates-ran-session.jsonl")
            .is_file()
    );
    assert!(
        evidence
            .join("before/tmp/coordinate-guard-session.count")
            .is_file()
    );
    cleanup(&root);
}

#[test]
fn refuses_non_identical_flat_doc_collision_and_collapses_identical_duplicate() {
    let root = fixture("collision");
    let namespace = root.join(".shepherd");
    write(&namespace.join("docs/a/2026-08-14-note.md"), b"one");
    write(&namespace.join("docs/b/2026-08-14-note.md"), b"two");
    let error = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect_err("different bytes must block a collision");
    assert!(error.to_string().contains("collision"));

    fs::remove_dir_all(namespace.join("docs/b")).expect("remove conflicting branch");
    write(&namespace.join("docs/b/2026-08-14-note.md"), b"one");
    let plan = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect("identical duplicate is safe");
    assert!(
        plan.manifest()
            .entries
            .iter()
            .any(|entry| entry.action == PlanAction::Deduplicated)
    );
    cleanup(&root);
}

#[test]
fn malformed_run_state_and_symlink_escape_are_rejected() {
    let root = fixture("unsafe");
    let namespace = root.join(".shepherd");
    write(&namespace.join("runs/broken/run.json"), b"not json");
    let malformed = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect_err("malformed run state must block migration");
    assert!(malformed.to_string().contains("run.json"));

    fs::remove_dir_all(namespace.join("runs/broken")).expect("remove malformed run");
    write(&namespace.join("docs/real.md"), b"safe");
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(root.join("outside"), namespace.join("docs/link"))
            .expect("create symlink fixture");
        let error = LayoutPlan::project(&namespace, namespace.join("runs"))
            .expect_err("symlink boundary must be rejected");
        assert!(error.to_string().contains("symbolic") || error.to_string().contains("symlink"));
    }
    cleanup(&root);
}

#[test]
fn project_and_user_home_authorization_are_separate() {
    let root = fixture("authorization");
    let namespace = root.join(".shepherd");
    write(&namespace.join("docs/old/2026-08-14-note.md"), b"note");
    let plan = LayoutPlan::project(&namespace, namespace.join("runs")).expect("valid project");
    assert!(plan.execute(&MigrationOptions::default()).is_err());
    assert!(
        plan.execute(&MigrationOptions {
            authorization: Some(Authorization::Project),
            confirm: true,
            ..MigrationOptions::default()
        })
        .is_ok()
    );
    let home = root.join("home/.shepherd");
    write(&home.join("styles/rust.md"), b"user");
    let user_plan = LayoutPlan::user_home(&home).expect("valid user home");
    assert_eq!(user_plan.scope(), PlanScope::UserHome);
    let style = user_plan
        .manifest()
        .entries
        .iter()
        .find(|entry| entry.source.ends_with("styles/rust.md"))
        .expect("legacy style must be explicitly retired");
    assert_eq!(style.action, PlanAction::RemoveFile);
    assert!(style.destination.is_empty());
    assert!(
        user_plan
            .manifest()
            .entries
            .iter()
            .all(|entry| !entry.destination.contains("profiles")),
        "migration must never recreate an unread profile root"
    );
    assert!(user_plan.execute(&MigrationOptions::default()).is_err());
    let evidence = root.join("user-evidence");
    let user_result = user_plan.execute(&MigrationOptions {
        authorization: Some(Authorization::UserHome),
        confirm: true,
        snapshot_dir: Some(evidence.clone()),
        ..MigrationOptions::default()
    });
    assert!(
        user_result.is_ok(),
        "user migration failed: {user_result:?}"
    );
    assert!(!home.join("styles/rust.md").exists());
    assert_eq!(
        fs::read(evidence.join("before/styles/rust.md")).expect("snapshot retired style"),
        b"user"
    );
    cleanup(&root);
}

#[test]
fn retires_unread_profile_and_user_template_roots_without_new_destinations() {
    for (scope, label) in [
        (PlanScope::Project, "project-retired-profile"),
        (PlanScope::UserHome, "user-retired-profile"),
    ] {
        let root = fixture(label);
        let namespace = root.join(".shepherd");
        write(&namespace.join("profiles/rust/style.md"), b"profile");
        if scope == PlanScope::UserHome {
            write(&namespace.join("templates/legacy.md"), b"template");
        }
        let plan = match scope {
            PlanScope::Project => LayoutPlan::project(&namespace, namespace.join("runs")),
            PlanScope::UserHome => LayoutPlan::user_home(&namespace),
        }
        .expect("retired roots must produce a migration plan");

        let files: Vec<_> = plan
            .manifest()
            .entries
            .iter()
            .filter(|entry| entry.action == PlanAction::RemoveFile)
            .collect();
        assert!(
            files
                .iter()
                .any(|entry| entry.source.ends_with("profiles/rust/style.md")),
            "profile bytes must be snapshot-retired"
        );
        if scope == PlanScope::UserHome {
            assert!(
                files
                    .iter()
                    .any(|entry| entry.source.ends_with("templates/legacy.md")),
                "unresolved user-template bytes must be snapshot-retired"
            );
        }
        assert!(
            plan.manifest().entries.iter().all(|entry| {
                !(entry.destination.contains("/profiles")
                    || scope == PlanScope::UserHome && entry.destination.contains("/templates"))
            }),
            "retired roots must not acquire a new destination"
        );
        cleanup(&root);
    }
}

#[test]
fn rejects_snapshot_limits_before_creating_snapshot_or_mutating_namespace() {
    let root = fixture("snapshot-limit");
    let namespace = root.join(".shepherd");
    write(&namespace.join("docs/nested/large.md"), b"four");
    let plan = LayoutPlan::project(&namespace, namespace.join("runs")).expect("valid plan");
    let evidence = root.join("evidence");
    let error = plan
        .execute(&MigrationOptions {
            authorization: Some(Authorization::Project),
            confirm: true,
            snapshot_dir: Some(evidence.clone()),
            max_bytes: 3,
            ..MigrationOptions::default()
        })
        .expect_err("source bytes exceed the configured snapshot cap");
    assert!(error.to_string().contains("snapshot limit"));
    assert!(!evidence.join("before").exists());
    assert!(namespace.join("docs/nested/large.md").is_file());
    assert!(!namespace.join("docs/large.md").exists());
    cleanup(&root);
}

#[cfg(unix)]
#[test]
fn rejects_symlinked_or_preexisting_snapshot_roots_before_namespace_mutation() {
    use std::os::unix::fs::symlink;

    for mode in ["symlink", "preexisting"] {
        let root = fixture(mode);
        let namespace = root.join(".shepherd");
        write(&namespace.join("docs/nested/note.md"), b"preserve me");
        let plan = LayoutPlan::project(&namespace, namespace.join("runs")).expect("valid plan");
        let evidence = root.join("evidence");
        let outside = root.join("outside");
        fs::create_dir_all(&outside).expect("create outside directory");
        if mode == "symlink" {
            symlink(&outside, &evidence).expect("create snapshot-root symlink");
        } else {
            fs::create_dir(&evidence).expect("create preexisting evidence root");
            write(&evidence.join("operator-owned.txt"), b"do not overwrite");
        }

        let error = plan
            .execute(&MigrationOptions {
                authorization: Some(Authorization::Project),
                confirm: true,
                snapshot_dir: Some(evidence.clone()),
                ..MigrationOptions::default()
            })
            .expect_err("snapshot evidence must be new and cannot be redirected");
        assert!(error.to_string().contains("snapshot"));
        assert!(namespace.join("docs/nested/note.md").is_file());
        assert!(!namespace.join("docs/note.md").exists());
        assert!(!outside.join("before").exists());
        if mode == "preexisting" {
            assert_eq!(
                fs::read(evidence.join("operator-owned.txt")).expect("read operator evidence"),
                b"do not overwrite"
            );
        }
        cleanup(&root);
    }
}

#[test]
fn rewrites_retired_config_paths_atomically_and_is_idempotent() {
    let root = fixture("config");
    let namespace = root.join(".shepherd");
    write(
        &namespace.join("shepherd.toml"),
        b"[paths]\ndocs = \".shepherd/docs\"\nplans = \".shepherd/plans\"\nreports = \".shepherd/reports\"\nruns = \".shepherd/runs\"\n",
    );
    let plan = LayoutPlan::project(&namespace, namespace.join("runs")).expect("valid config");
    assert!(
        plan.manifest()
            .entries
            .iter()
            .any(|entry| entry.action == PlanAction::Rewrite)
    );
    let snapshot = root.join("evidence");
    plan.execute(&MigrationOptions {
        authorization: Some(Authorization::Project),
        confirm: true,
        snapshot_dir: Some(snapshot),
        ..MigrationOptions::default()
    })
    .expect("config rewrite succeeds");
    let rollback = fs::read_to_string(root.join("evidence/rollback.sh"))
        .expect("rollback script is written with the snapshot");
    assert!(rollback.contains("$before"));
    assert!(rollback.contains("cp -p --"));
    assert!(rollback.contains("shepherd.toml"));
    let config = fs::read_to_string(namespace.join("shepherd.toml")).expect("rewritten config");
    assert!(!config.contains("plans =") && !config.contains("reports ="));
    let second = LayoutPlan::project(&namespace, namespace.join("runs")).expect("replan");
    assert!(second.manifest().entries.is_empty());
    cleanup(&root);
}

#[test]
fn rewrites_every_canonical_config_candidate_for_project_and_user_home() {
    let legacy = b"# retained header\n[paths]\nplans=\".shepherd/docs/plans\"\nreports = \".shepherd/docs/reports\"\nruns = \".shepherd/runs\"\n\n[memory]\nproject_memory = \".shepherd/memory/project.md\"\nproject_doctrines = \".shepherd/memory/doctrines.md\"\n\n[context]\nenabled = true\ndb_path = \".shepherd/shepherd.db\"\nlock_path = \".shepherd/shepherd.lock\"\nproject_id_path = \".shepherd/project.json\"\nannounce_shctx_path = \"off\"\n\n[project]\nname = \"preserved\"\n";
    let candidates = [
        "shepherd.toml",
        "shepherd.local.toml",
        "shepherd.claude.toml",
        "shepherd.codex.toml",
        "shepherd.pi.toml",
    ];

    for (scope, label) in [
        (PlanScope::Project, "project"),
        (PlanScope::UserHome, "user"),
    ] {
        let root = fixture(label);
        let namespace = root.join(".shepherd");
        for candidate in candidates {
            write(&namespace.join(candidate), legacy);
        }

        let plan = match scope {
            PlanScope::Project => LayoutPlan::project(&namespace, namespace.join("runs")),
            PlanScope::UserHome => LayoutPlan::user_home(&namespace),
        }
        .expect("legacy candidates must plan");
        assert_eq!(
            plan.manifest()
                .entries
                .iter()
                .filter(|entry| entry.action == PlanAction::Rewrite)
                .count(),
            candidates.len()
        );
        let authorization = match scope {
            PlanScope::Project => Authorization::Project,
            PlanScope::UserHome => Authorization::UserHome,
        };
        plan.execute(&MigrationOptions {
            authorization: Some(authorization),
            confirm: true,
            snapshot_dir: Some(root.join("evidence")),
            ..MigrationOptions::default()
        })
        .expect("confirmed rewrite succeeds");

        for candidate in candidates {
            let rewritten =
                fs::read_to_string(namespace.join(candidate)).expect("rewritten config");
            assert!(rewritten.contains("# retained header"));
            assert!(rewritten.contains("[project]\nname = \"preserved\""));
            for retired in [
                "plans=",
                "reports =",
                "[memory]",
                "project_memory",
                "project_doctrines",
                "enabled =",
                "db_path",
                "lock_path",
                "project_id_path",
                "announce_shctx_path",
            ] {
                assert!(
                    !rewritten.contains(retired),
                    "{candidate} retains {retired}"
                );
            }
        }

        let second = match scope {
            PlanScope::Project => LayoutPlan::project(&namespace, namespace.join("runs")),
            PlanScope::UserHome => LayoutPlan::user_home(&namespace),
        }
        .expect("rewritten candidates remain plannable");
        assert!(second.manifest().entries.is_empty());
        cleanup(&root);
    }
}

#[test]
fn maps_a_dotted_legacy_dispatch_branch_to_its_unique_validated_run() {
    let root = fixture("dotted-dispatch");
    let namespace = root.join(".shepherd");
    write(
        &namespace.join("runs/v645/run.json"),
        &run_json_with_branch("v645", "v6.4.5"),
    );
    write(
        &namespace.join("dispatch/v6.4.5/record.json"),
        b"dispatch record",
    );

    let plan = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect("a unique validated branch mapping is deterministic");
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.source.ends_with("dispatch/v6.4.5/record.json")
            && entry
                .destination
                .ends_with("runs/v645/dispatch/record.json")
            && entry.classification == "run"
            && entry.provenance.contains("branch")
    }));
    cleanup(&root);
}

#[test]
fn refuses_ambiguous_dotted_legacy_dispatch_branch_mapping() {
    let root = fixture("ambiguous-dotted-dispatch");
    let namespace = root.join(".shepherd");
    write(
        &namespace.join("runs/v645/run.json"),
        &run_json_with_branch("v645", "v6.4.5"),
    );
    write(
        &namespace.join("runs/v645-alt/run.json"),
        &run_json_with_branch("v645-alt", "v6.4.5"),
    );
    write(&namespace.join("dispatch/v6.4.5/record.json"), b"record");

    let error = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect_err("a branch shared by two run states cannot be guessed");
    assert!(error.to_string().contains("ambiguous"));
    assert!(error.to_string().contains("v6.4.5"));
    cleanup(&root);
}

#[test]
fn maps_v645_cache_snapshots_and_single_branch_event_logs_to_one_run() {
    let root = fixture("cache-and-events");
    let namespace = root.join(".shepherd");
    write(
        &namespace.join("runs/v645/run.json"),
        &run_json_with_branch("v645", "v6.4.5"),
    );
    write(
        &namespace.join("cache/snapshots/precompact.json"),
        br#"{"sprint":"v6.4.5","run":""}"#,
    );
    write(
        &namespace.join("logs/events.jsonl"),
        b"{\"sprint\":\"v6.4.5\",\"event_type\":\"cache_usage\"}\n\n{\"branch\":\"v6.4.5\"}\n",
    );

    let plan = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect("all nonempty records name the same validated branch");
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.source.ends_with("cache/snapshots/precompact.json")
            && entry
                .destination
                .ends_with("runs/v645/snapshots/precompact.json")
    }));
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.source.ends_with("logs/events.jsonl")
            && entry.destination.ends_with("runs/v645/events/events.jsonl")
    }));
    cleanup(&root);
}

#[test]
fn refuses_mixed_or_malformed_event_logs_and_removes_empty_hook_logs() {
    let root = fixture("event-validation");
    let namespace = root.join(".shepherd");
    write(
        &namespace.join("runs/v645/run.json"),
        &run_json_with_branch("v645", "v6.4.5"),
    );
    write(
        &namespace.join("runs/v646/run.json"),
        &run_json_with_branch("v646", "v6.4.6"),
    );
    write(
        &namespace.join("logs/events.jsonl"),
        b"{\"sprint\":\"v6.4.5\"}\n{\"sprint\":\"v6.4.6\"}\n",
    );
    let mixed = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect_err("mixed logs cannot be moved into one run");
    assert!(mixed.to_string().contains("mixed"));

    fs::remove_file(namespace.join("logs/events.jsonl")).expect("remove mixed fixture");
    write(&namespace.join("logs/hooks/empty.jsonl"), b"\n\t\n");
    let plan = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect("empty hook logs are disposable legacy diagnostics");
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.source.ends_with("logs/hooks/empty.jsonl")
            && entry.action == PlanAction::RemoveFile
            && entry.provenance.contains("empty hook")
    }));
    cleanup(&root);
}

#[test]
fn maps_dispatcher_patch_to_its_run_report() {
    let root = fixture("dispatcher-patch");
    let namespace = root.join(".shepherd");
    write(&namespace.join("runs/v645/run.json"), &run_json("v645"));
    write(
        &namespace.join("dispatcher-patches/v645-pc-1.md"),
        b"# v645 patch\n",
    );

    let plan = LayoutPlan::project(&namespace, namespace.join("runs"))
        .expect("prefix run identity is explicit in a dispatcher patch filename");
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.source.ends_with("dispatcher-patches/v645-pc-1.md")
            && entry
                .destination
                .ends_with("runs/v645/reports/v645-pc-1.md")
            && entry.provenance.contains("dispatcher patch")
    }));
    cleanup(&root);
}

#[test]
fn user_home_removes_obsolete_plugin_markers_and_empty_hook_logs() {
    let root = fixture("user-home-retired");
    let namespace = root.join(".shepherd");
    write(
        &namespace.join("plugin-data/cli/pyproject.toml.installed"),
        b"legacy marker",
    );
    write(&namespace.join("logs/hooks/old.jsonl"), b"");

    let plan = LayoutPlan::user_home(&namespace).expect("obsolete user roots are removable");
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry
            .source
            .ends_with("plugin-data/cli/pyproject.toml.installed")
            && entry.action == PlanAction::RemoveFile
            && entry.provenance.contains("obsolete")
    }));
    assert!(plan.manifest().entries.iter().any(|entry| {
        entry.source.ends_with("logs/hooks/old.jsonl") && entry.action == PlanAction::RemoveFile
    }));
    cleanup(&root);
}
