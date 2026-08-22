/*
    Appellation: loader <test>
    Created At: 2026.08.14
    Contrib: @FL03
*/
//! The layout-v5 configuration contract.
#![cfg(all(feature = "config", feature = "std"))]

use std::path::{Path, PathBuf};

use shepherd_core::loader::{self, ConfigContext, ConfigTier};
use shepherd_core::settings::{GatesExtra, HarnessLanguage, ReleaseDriver, Toggle};
use shepherd_core::types::Harness;

fn context(harness: Option<Harness>) -> ConfigContext {
    ConfigContext {
        primary_root: PathBuf::from("/repo"),
        user_home: Some(PathBuf::from("/home/jo3/.shepherd")),
        harness,
    }
}

#[test]
fn canonical_candidates_with_harness_are_exactly_six() {
    let got: Vec<(PathBuf, ConfigTier)> = loader::candidates(&context(Some(Harness::ClaudeCode)))
        .into_iter()
        .map(|candidate| (candidate.path, candidate.tier))
        .collect();

    assert_eq!(
        got,
        vec![
            (
                PathBuf::from("/repo/.shepherd/shepherd.local.toml"),
                ConfigTier::Project,
            ),
            (
                PathBuf::from("/repo/.shepherd/shepherd.claude.toml"),
                ConfigTier::Project,
            ),
            (
                PathBuf::from("/repo/.shepherd/shepherd.toml"),
                ConfigTier::Project,
            ),
            (
                PathBuf::from("/home/jo3/.shepherd/shepherd.local.toml"),
                ConfigTier::User,
            ),
            (
                PathBuf::from("/home/jo3/.shepherd/shepherd.claude.toml"),
                ConfigTier::User,
            ),
            (
                PathBuf::from("/home/jo3/.shepherd/shepherd.toml"),
                ConfigTier::User,
            ),
        ]
    );
}

#[test]
fn canonical_candidates_without_harness_are_exactly_four() {
    let got: Vec<PathBuf> = loader::candidates(&context(None))
        .into_iter()
        .map(|candidate| candidate.path)
        .collect();

    assert_eq!(
        got,
        vec![
            PathBuf::from("/repo/.shepherd/shepherd.local.toml"),
            PathBuf::from("/repo/.shepherd/shepherd.toml"),
            PathBuf::from("/home/jo3/.shepherd/shepherd.local.toml"),
            PathBuf::from("/home/jo3/.shepherd/shepherd.toml"),
        ]
    );
}

#[test]
fn absent_user_home_removes_user_candidates_without_inventing_a_path() {
    let mut cx = context(Some(Harness::Pi));
    cx.user_home = None;

    let got: Vec<PathBuf> = loader::candidates(&cx)
        .into_iter()
        .map(|candidate| candidate.path)
        .collect();

    assert_eq!(
        got,
        vec![
            PathBuf::from("/repo/.shepherd/shepherd.local.toml"),
            PathBuf::from("/repo/.shepherd/shepherd.pi.toml"),
            PathBuf::from("/repo/.shepherd/shepherd.toml"),
        ]
    );
}

#[test]
fn project_namespace_used_as_user_home_does_not_duplicate_candidates() {
    let mut cx = context(Some(Harness::Pi));
    cx.user_home = Some(PathBuf::from("/repo/.shepherd"));

    let got: Vec<PathBuf> = loader::candidates(&cx)
        .into_iter()
        .map(|candidate| candidate.path)
        .collect();

    assert_eq!(
        got,
        vec![
            PathBuf::from("/repo/.shepherd/shepherd.local.toml"),
            PathBuf::from("/repo/.shepherd/shepherd.pi.toml"),
            PathBuf::from("/repo/.shepherd/shepherd.toml"),
        ]
    );
}

#[test]
fn legacy_claude_artifacts_and_xdg_paths_never_enter_the_chain() {
    let candidates = loader::candidates(&context(Some(Harness::Codex)));

    assert!(candidates.iter().all(|candidate| {
        let path = candidate.path.to_string_lossy();
        !path.contains("/.claude/") && !path.contains("/.artifacts/") && !path.contains("/.config/")
    }));
}

#[test]
fn empty_document_materializes_the_canonical_defaults() {
    let config = loader::layer([(Path::new("empty.toml"), "")]).expect("empty config is valid");

    assert_eq!(config.project.language, HarnessLanguage::Rust);
    assert_eq!(config.paths.docs, PathBuf::from(".shepherd/docs"));
    assert_eq!(config.paths.ctx, PathBuf::from(".shepherd/ctx"));
    assert_eq!(config.paths.runs, PathBuf::from(".shepherd/runs"));
    assert_eq!(
        config.dups.dups_registry,
        PathBuf::from("dups-registry.json")
    );
    // Root, planter, and both reasoning leads hold the reasoning tier. Fresh
    // lead dispatch must never inherit an ambient model with unknown effort.
    // All nine remain overridable through `[models]`.
    assert_eq!(config.models.root, "reasoning-high");
    assert_eq!(config.models.planter, "reasoning-high");
    assert_eq!(config.models.engineer, "reasoning-high");
    assert_eq!(config.models.conductor, "reasoning-high");
    assert_eq!(config.models.critic, "standard");
    // the widest fan-out role: width beats depth for bounded research
    assert_eq!(config.models.discovery, "economy");
    assert_eq!(config.models.coder, "standard");
    assert_eq!(config.models.auditor, "standard");
    assert_eq!(config.models.worker, "standard");
    assert_eq!(config.model_targets.pi.inherit_caller, "");
    assert_eq!(config.model_targets.pi.reasoning_high, "");
    assert_eq!(config.model_targets.pi.standard, "");
    assert_eq!(config.model_targets.pi.economy, "");
    assert_eq!(config.release.driver, ReleaseDriver::GithubWorkflow);
    assert_eq!(config.context.refresh.ttl_minutes, 30);
    assert_eq!(config.context.lock.stale_after_minutes, 120);
    assert_eq!(config.prune.logs_days, 60);
    assert_eq!(config.prune.dispatch_days, 30);
    assert_eq!(config.prune.snapshots_keep, 20);
    assert_eq!(config.prune.findings_sprints, 6);
}

#[test]
fn pi_model_targets_are_closed_and_loaded_by_the_canonical_schema() {
    let config = loader::layer([(
        Path::new("pi-model-targets.toml"),
        "[model_targets.pi]\ninherit-caller = \"inherit\"\nreasoning-high = \"openai-codex/gpt-5.6-sol:xhigh\"\nstandard = \"openai-codex/gpt-5.6-luna:max\"\neconomy = \"openai-codex/gpt-5.6-luna:max\"\n",
    )])
    .expect("closed Pi model target map loads through the canonical schema");

    assert_eq!(config.model_targets.pi.inherit_caller, "inherit");
    assert_eq!(
        config.model_targets.pi.reasoning_high,
        "openai-codex/gpt-5.6-sol:xhigh"
    );
    assert_eq!(
        config.model_targets.pi.standard,
        "openai-codex/gpt-5.6-luna:max"
    );
    assert_eq!(
        config.model_targets.pi.economy,
        "openai-codex/gpt-5.6-luna:max"
    );

    let error = loader::validate(
        Path::new("unknown-pi-model-target.toml"),
        "[model_targets.pi]\nstandard = \"openai-codex/gpt-5.6-luna:max\"\ncustom = \"provider/model:max\"\n",
    )
    .expect_err("portable target map must reject unknown hints");
    assert!(error.to_string().contains("custom"));

    for invalid in [
        "[model_targets.pi]\nstandard = \"openai-codex/gpt-5.6-luna\"\n",
        "[model_targets.pi]\nstandard = \"openai-codex/gpt-5.6-luna:ultra\"\n",
        "[model_targets.pi]\ninherit-caller = \"openai-codex/gpt-5.6-sol:xhigh\"\n",
    ] {
        let error = loader::validate(Path::new("invalid-pi-model-target.toml"), invalid)
            .expect_err("Pi targets require a concrete model plus supported effort");
        assert!(
            error.to_string().contains("model_targets.pi"),
            "unexpected validation error: {error}"
        );
    }
}

#[test]
fn shipped_example_configs_are_valid_layout_v5_documents() {
    let examples = [
        (
            Path::new("examples/minimal/shepherd.toml"),
            include_str!("../../../examples/minimal/shepherd.toml"),
        ),
        (
            Path::new("examples/rust-service/shepherd.toml"),
            include_str!("../../../examples/rust-service/shepherd.toml"),
        ),
    ];

    for (path, text) in examples {
        loader::validate(path, text)
            .unwrap_or_else(|error| panic!("{} must satisfy layout v5: {error}", path.display()));
    }
}

#[test]
fn partial_nested_tables_retain_sibling_defaults() {
    let config = loader::layer([(
        Path::new("partial.toml"),
        "[context.refresh]\n[prune]\nlogs_days = 7\n",
    )])
    .expect("partial nested tables are valid");

    assert_eq!(config.context.refresh.ttl_minutes, 30);
    assert_eq!(config.prune.logs_days, 7);
    assert_eq!(config.prune.dispatch_days, 30);
    assert_eq!(config.prune.snapshots_keep, 20);
    assert_eq!(config.prune.findings_sprints, 6);
}

#[test]
fn canonical_context_cli_announcement_has_no_shctx_alias() {
    let canonical = loader::layer([(
        Path::new("canonical-context.toml"),
        "[context]\nannounce_cli_path = \"off\"\n",
    )])
    .expect("the one native CLI has a canonical announcement key");
    assert_eq!(canonical.context.announce_cli_path, Toggle::Off);

    // The retired spelling is now TOLERATED in every mode and dropped, rather
    // than rejected. Rejecting it stranded any project configured before the
    // second CLI was retired, including from `doctor` and `migrate`. What must
    // NOT happen is the retired key influencing the canonical one, so that is
    // what is asserted: it loads, and the canonical value keeps its default.
    let legacy = "[context]\nannounce_shctx_path = \"off\"\n";
    let strict = loader::load([(Path::new("legacy-context.toml"), legacy)])
        .expect("ordinary loading tolerates the retired second-CLI spelling");
    assert_eq!(strict.config.context.announce_cli_path, Toggle::On);

    let migrated =
        loader::load_for_layout_v5_migration([(Path::new("legacy-context.toml"), legacy)])
            .expect("layout migration accepts and removes the typed retired spelling");
    assert_eq!(migrated.config.context.announce_cli_path, Toggle::On);
}

#[test]
fn partial_layers_merge_and_the_highest_priority_value_wins() {
    let project = Path::new("/repo/.shepherd/shepherd.local.toml");
    let user = Path::new("/home/jo3/.shepherd/shepherd.toml");

    let loaded = loader::load([
        (
            project,
            "[spawn]\nmax_parallel = 2\n[project]\ndescription = \"winner\"\n",
        ),
        (
            user,
            "[spawn]\nmax_parallel = 8\n[project]\nname = \"from-user\"\n",
        ),
    ])
    .expect("valid layers merge");

    assert_eq!(loaded.config.spawn.max_parallel, 2);
    assert_eq!(loaded.config.project.name.as_deref(), Some("from-user"));
    assert_eq!(loaded.config.project.description, "winner");
    assert_eq!(
        loaded
            .sources
            .iter()
            .map(|source| source.path.as_path())
            .collect::<Vec<_>>(),
        vec![project, user]
    );
}

#[test]
fn explicit_keys_records_a_role_set_to_its_own_default_value() {
    // `models.conductor`'s portable default is `reasoning-high` (see
    // `ModelsConfig::default`). A layer that explicitly sets it to that same
    // value must still be recorded as explicit -- the merged value alone can
    // never distinguish "a layer set this" from "nothing set this and the
    // default happened to apply", which is exactly what a
    // merged-value-vs-default comparison gets wrong.
    let loaded = loader::load([(
        Path::new("/repo/.shepherd/shepherd.toml"),
        "[models]\nconductor = \"reasoning-high\"\n",
    )])
    .expect("valid layer loads");

    assert_eq!(loaded.config.models.conductor, "reasoning-high");
    assert!(
        loaded.explicit_keys.contains("models.conductor"),
        "{:?}",
        loaded.explicit_keys
    );
    assert!(
        !loaded.explicit_keys.contains("models.root"),
        "an unset role must not be recorded as explicit: {:?}",
        loaded.explicit_keys
    );
}

#[test]
fn explicit_keys_union_every_merged_layer_regardless_of_priority() {
    let project = Path::new("/repo/.shepherd/shepherd.toml");
    let user = Path::new("/home/jo3/.shepherd/shepherd.toml");

    let loaded = loader::load([
        (project, "[models]\ncoder = \"native-coder\"\n"),
        (user, "[models]\nworker = \"native-worker\"\n"),
    ])
    .expect("valid layers merge");

    assert_eq!(loaded.config.models.coder, "native-coder");
    assert_eq!(loaded.config.models.worker, "native-worker");
    assert!(loaded.explicit_keys.contains("models.coder"));
    assert!(loaded.explicit_keys.contains("models.worker"));
    assert!(!loaded.explicit_keys.contains("models.root"));
}

#[test]
fn a_layer_illegal_alone_but_legal_after_merge_still_loads() {
    // `paths.ctx` and `paths.docs` must not overlap (settings.rs's
    // cross-field check). The user layer only sets `paths.ctx`, which is
    // illegal in isolation because it collides with `paths.docs`'s default
    // (".shepherd/docs"). The higher-priority project layer moves
    // `paths.docs` out of the way, so the *merged* result is legal even
    // though the user layer alone never would be. Per-layer decoding used to
    // reject the user layer before the merge ever happened; the loader must
    // now decode and validate only once, against the merged configuration.
    let project = Path::new("/repo/.shepherd/shepherd.toml");
    let user = Path::new("/home/jo3/.shepherd/shepherd.toml");

    let loaded = loader::load([
        (project, "[paths]\ndocs = \".shepherd/documentation\"\n"),
        (user, "[paths]\nctx = \".shepherd/docs\"\n"),
    ])
    .expect("a layer illegal alone but legal after merge must still load");

    assert_eq!(
        loaded.config.paths.docs,
        PathBuf::from(".shepherd/documentation")
    );
    assert_eq!(loaded.config.paths.ctx, PathBuf::from(".shepherd/docs"));
}

#[test]
fn open_maps_gate_shapes_and_all_nine_role_models_round_trip() {
    let text = r#"
[mcp]
future_server = true
[cli]
future_binary = false
[skills.by_domain]
quantum = ["quantum-skill"]
[skills.detection]
quantum = ["**/*.q"]
[gates.extra]
schema = "cargo test"
[models]
root = "r"
planter = "p"
engineer = "e"
conductor = "c"
critic = "k"
discovery = "d"
coder = "o"
auditor = "a"
worker = "w"
"#;

    let config = loader::layer([(Path::new("maps.toml"), text)]).expect("maps are valid");

    assert_eq!(config.mcp.get("future_server"), Some(&true));
    assert_eq!(config.cli.get("future_binary"), Some(&false));
    assert_eq!(config.skills.by_domain["quantum"], ["quantum-skill"]);
    assert_eq!(config.skills.detection["quantum"], ["**/*.q"]);
    assert!(
        matches!(config.gates.extra, GatesExtra::Map(ref map) if map["schema"] == "cargo test")
    );
    assert_eq!(
        [
            config.models.root.as_str(),
            config.models.planter.as_str(),
            config.models.engineer.as_str(),
            config.models.conductor.as_str(),
            config.models.critic.as_str(),
            config.models.discovery.as_str(),
            config.models.coder.as_str(),
            config.models.auditor.as_str(),
            config.models.worker.as_str(),
        ],
        ["r", "p", "e", "c", "k", "d", "o", "a", "w"]
    );
}

#[test]
fn list_gate_shape_requires_name_and_command() {
    let valid = "[gates]\nextra = [{ name = \"schema\", cmd = \"cargo test\" }]\n";
    let invalid = "[gates]\nextra = [{ name = \"schema\" }]\n";

    assert!(loader::validate(Path::new("valid.toml"), valid).is_ok());
    let error = loader::validate(Path::new("invalid.toml"), invalid)
        .expect_err("missing command must fail")
        .to_string();
    assert!(error.contains("invalid.toml"), "{error}");
    assert!(error.contains("gates.extra"), "{error}");
    assert!(error.contains("cmd"), "{error}");

    let unknown = loader::validate(
        Path::new("unknown.toml"),
        "[gates]\nextra = [{ name = \"schema\", cmd = \"cargo test\", typo = true }]\n",
    )
    .expect_err("unknown gate field must fail")
    .to_string();
    assert!(unknown.contains("gates.extra.typo"), "{unknown}");
}

#[test]
fn open_map_value_errors_name_the_dynamic_dotted_key() {
    let cases = [
        ("[mcp]\nfuture = \"yes\"\n", "mcp.future"),
        ("[cli]\nfuture = 1\n", "cli.future"),
        (
            "[skills.by_domain]\nfuture = \"skill\"\n",
            "skills.by_domain.future",
        ),
        ("[gates.extra]\nfuture = true\n", "gates.extra.future"),
    ];

    for (text, dotted) in cases {
        let error = loader::validate(Path::new("dynamic.toml"), text)
            .expect_err("wrong dynamic value type must fail")
            .to_string();
        assert!(error.contains(dotted), "missing {dotted} in: {error}");
    }
}

#[test]
fn every_validation_failure_names_the_file_and_dotted_key() {
    let cases = [
        ("unknown-root.toml", "[bogus]\nx = true\n", "bogus"),
        (
            "unknown-key.toml",
            "[project]\nnaem = \"x\"\n",
            "project.naem",
        ),
        (
            "bad-enum.toml",
            "[release]\ndriver = \"git\"\n",
            "release.driver",
        ),
        (
            "bad-type.toml",
            "[spawn]\nmax_parallel = \"six\"\n",
            "spawn.max_parallel",
        ),
        (
            "bad-range.toml",
            "[dups]\ndups_threshold = 1.1\n",
            "dups.dups_threshold",
        ),
    ];

    for (file, text, dotted) in cases {
        let error = loader::validate(Path::new(file), text)
            .expect_err("invalid configuration must fail")
            .to_string();
        assert!(error.contains(file), "missing file in: {error}");
        assert!(error.contains(dotted), "missing {dotted} in: {error}");
    }

    // The RETIRED subset is deliberately not in the list above. These are keys
    // shepherd itself once wrote, so refusing to load a document that still
    // carries one strands every project configured before their removal -- and
    // blocks `doctor`, `migrate` and `init`, the tools that would fix it. They
    // are recognized, type-checked, and dropped.
    //
    // This is a CLOSED set, which is what keeps the distinction meaningful: a
    // key that was never in the schema is still a hard error above.
    for (file, text) in [
        ("deprecated.toml", "[paths]\nplans = \".shepherd/plans\"\n"),
        (
            // Both keys: the retired `[memory]` table is validated as a WHOLE
            // before it is dropped, so a half-written one is still an error.
            // That is the discipline that keeps tolerance from becoming
            // silent discard, and it caught this fixture.
            "retired-memory.toml",
            "[memory]\nproject_memory = \"x\"\nproject_doctrines = \"y\"\n",
        ),
        (
            "retired-context-path.toml",
            "[context]\ndb_path = \".shepherd/other.db\"\n",
        ),
    ] {
        loader::validate(Path::new(file), text)
            .unwrap_or_else(|error| panic!("retired key in {file} must be tolerated: {error}"));
    }

    // ...and a retired key carrying the WRONG historical type still fails, so
    // tolerance never becomes silent discard.
    let malformed = loader::validate(Path::new("bad-retired.toml"), "[paths]\nplans = false\n")
        .expect_err("a retired key with the wrong type must still fail")
        .to_string();
    assert!(malformed.contains("paths.plans"), "{malformed}");
}

#[test]
fn layout_v5_migration_loader_accepts_only_the_typed_retired_subset() {
    let path = Path::new("legacy-layout.toml");
    let legacy = r#"
[paths]
plans = ".shepherd/docs/plans"
reports = ".shepherd/docs/reports"
runs = ".shepherd/executions"

[memory]
project_memory = ".shepherd/memory/project.md"
project_doctrines = ".shepherd/memory/doctrines.md"

[context]
enabled = true
db_path = ".shepherd/shepherd.db"
lock_path = ".shepherd/shepherd.lock"
project_id_path = ".shepherd/project.json"
announce_shctx_path = "off"
"#;

    // CONTRACT CHANGE. Ordinary loading used to REJECT the retired subset, and
    // that produced a deadlock in the field: a project whose shepherd.toml
    // still carried a retired key could not run `doctor`, `migrate` or `init`
    // -- every tool capable of repairing the config was blocked by the config.
    // A key shepherd itself once wrote is not a typo, so the closed, typed
    // registry is now consulted in every mode.
    let strict =
        loader::load([(path, legacy)]).expect("ordinary loading tolerates the retired subset");
    assert_eq!(
        strict.config.paths.runs,
        PathBuf::from(".shepherd/executions")
    );

    // ...and typo protection is UNCHANGED, which is the half that matters. A
    // key that was never part of the schema still fails, and still names the
    // candidates.
    let typo = loader::load([(path, "[paths]\nrunz = \".shepherd/executions\"\n")])
        .expect_err("a key that was never in the schema must still fail");
    assert!(typo.to_string().contains("legacy-layout.toml"), "{typo}");
    assert!(typo.to_string().contains("unknown field"), "{typo}");

    let loaded = loader::load_for_layout_v5_migration([(path, legacy)])
        .expect("migration may load the closed retired subset");
    assert_eq!(
        loaded.config.paths.runs,
        PathBuf::from(".shepherd/executions")
    );
    assert_eq!(loaded.config.context.announce_cli_path, Toggle::On);
}

#[test]
fn layout_v5_migration_loader_rejects_malformed_or_unknown_legacy_keys() {
    let cases = [
        (
            "bad-path-type.toml",
            "[paths]\nplans = false\n",
            "paths.plans",
        ),
        (
            "bad-memory-type.toml",
            "[memory]\nproject_memory = false\nproject_doctrines = \"doctrines\"\n",
            "memory.project_memory",
        ),
        (
            "unknown-memory.toml",
            "[memory]\nproject_memory = \"memory\"\nproject_doctrines = \"doctrines\"\nextra = \"no\"\n",
            "memory.extra",
        ),
        (
            "missing-memory.toml",
            "[memory]\nproject_memory = \"memory\"\n",
            "memory.project_doctrines",
        ),
        (
            "bad-context-type.toml",
            "[context]\nenabled = \"yes\"\n",
            "context.enabled",
        ),
        (
            "bad-announcement-type.toml",
            "[context]\nannounce_shctx_path = false\n",
            "context.announce_shctx_path",
        ),
        (
            "unknown-context.toml",
            "[context]\ncache_path = \".shepherd/cache\"\n",
            "context.cache_path",
        ),
    ];

    for (file, text, key) in cases {
        let error = loader::load_for_layout_v5_migration([(Path::new(file), text)])
            .expect_err("only the documented legacy shape is accepted")
            .to_string();
        assert!(error.contains(file), "missing file in: {error}");
        assert!(error.contains(key), "missing {key} in: {error}");
    }
}

#[test]
fn malformed_toml_names_the_candidate_without_echoing_other_inputs() {
    let error = loader::validate(
        Path::new("/repo/.shepherd/shepherd.local.toml"),
        "[project\nname = \"never-echo-this\"",
    )
    .expect_err("malformed TOML must fail")
    .to_string();

    assert!(error.contains("shepherd.local.toml"), "{error}");
    assert!(!error.contains("never-echo-this"), "{error}");
}

#[test]
fn canonical_paths_resolve_under_the_primary_namespace() {
    let config = loader::layer([(
        Path::new("paths.toml"),
        "[paths]\ndocs = \".shepherd/flat-docs\"\nctx = \".shepherd/context\"\nruns = \".shepherd/executions\"\n",
    )])
    .expect("paths are valid");

    let paths = config
        .resolve_paths(Path::new("/primary"))
        .expect("paths remain in namespace");

    assert_eq!(paths.namespace, PathBuf::from("/primary/.shepherd"));
    assert_eq!(paths.docs, PathBuf::from("/primary/.shepherd/flat-docs"));
    assert_eq!(paths.ctx, PathBuf::from("/primary/.shepherd/context"));
    assert_eq!(paths.runs, PathBuf::from("/primary/.shepherd/executions"));
    assert_eq!(
        paths.dups_registry,
        PathBuf::from("/primary/.shepherd/context/dups-registry.json")
    );
    assert_eq!(
        paths.registry,
        PathBuf::from("/primary/.shepherd/shepherd.db")
    );
    assert_eq!(
        paths.project_id,
        PathBuf::from("/primary/.shepherd/project.json")
    );
}

#[test]
fn duplicate_registry_is_a_safe_filename_resolved_below_the_configured_context_root() {
    let valid = loader::layer([(
        Path::new("dups.toml"),
        "[paths]\nctx = \".shepherd/knowledge\"\n[dups]\ndups_registry = \"curated.json\"\n",
    )])
    .expect("a curated registry below the configured context root is valid");
    assert_eq!(
        Path::new(&valid.dups.dups_registry),
        Path::new("curated.json")
    );

    for value in [
        "/tmp/dups-registry.json",
        ".shepherd/dups-registry.json",
        "../dups-registry.json",
        "nested/dups-registry.json",
        "nested\\dups-registry.json",
        "bad\tregistry.json",
        ".",
    ] {
        let text = format!("[dups]\ndups_registry = {value:?}\n");
        let error = loader::validate(Path::new("dups-invalid.toml"), &text)
            .expect_err("the curated registry cannot leave paths.ctx")
            .to_string();
        assert!(error.contains("dups.dups_registry"), "{error}");
    }
}

#[test]
fn absolute_and_namespace_escape_paths_are_rejected_at_the_named_key() {
    for (value, key) in [
        ("/tmp/docs", "paths.docs"),
        (".shepherd/../outside", "paths.docs"),
        ("docs", "paths.docs"),
        // `context.db_path` was a case here and is gone: it is a RETIRED key,
        // stripped before the schema sees it, so escape-validating it asserts
        // nothing about live behaviour. Escape rejection is still covered by
        // the three `paths.docs` cases above, which are keys that exist.
        ("runs", "paths.runs"),
    ] {
        let section = "paths";
        let field = key.split('.').nth(1).expect("test key has a field");
        let text = format!("[{section}]\n{field} = {value:?}\n");
        let error = loader::validate(Path::new("escape.toml"), &text)
            .expect_err("escaping path must fail")
            .to_string();
        assert!(error.contains(key), "missing {key} in: {error}");
    }
}

#[test]
fn canonical_layout_roots_cannot_alias_each_other() {
    let error = loader::validate(
        Path::new("aliases.toml"),
        "[paths]\ndocs = \".shepherd/shared\"\nctx = \".shepherd/shared\"\n",
    )
    .expect_err("two artifact classes cannot share one root")
    .to_string();

    assert!(error.contains("paths.ctx"), "{error}");
    assert!(error.contains("paths.docs"), "{error}");

    let nested = loader::validate(
        Path::new("nested.toml"),
        "[paths]\nruns = \".shepherd/docs/runs\"\n",
    )
    .expect_err("artifact roots cannot nest inside each other")
    .to_string();
    assert!(nested.contains("paths.runs"), "{nested}");
    assert!(nested.contains("paths.docs"), "{nested}");
}

#[cfg(all(feature = "schema", feature = "json"))]
#[test]
fn config_schema_json_is_deterministic_and_non_empty() {
    let first = loader::schema_json().expect("schema renders");
    let second = loader::schema_json().expect("schema renders twice");

    assert_eq!(first, second);
    assert!(
        first.len() > 1_000,
        "full schema must not collapse: {}",
        first.len()
    );
    assert!(first.contains("stage_graph"));
    assert!(first.contains("additionalProperties"));
}
