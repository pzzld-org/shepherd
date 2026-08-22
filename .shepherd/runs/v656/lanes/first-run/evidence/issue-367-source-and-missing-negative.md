# Historical pre-rebase reproduction

This file preserves the original `6837e109...` reproduction only. It is not
final-state evidence. Current base, implementation, projection, and gate results
are recorded in `status-and-diff.md`, `implementation-verification.md`, and
`issue-369-authored-spawn.md`.

HEAD: 6837e109ab618e3d22cb34c637de8ed7b7da7c69
COMMAND: nl -ba crates/core/tests/loader.rs | sed -n 532,632p
   532	fn layout_v5_migration_loader_accepts_only_the_typed_retired_subset() {
   533	    let path = Path::new("legacy-layout.toml");
   534	    let legacy = r#"
   535	[paths]
   536	plans = ".shepherd/docs/plans"
   537	reports = ".shepherd/docs/reports"
   538	runs = ".shepherd/executions"
   539	
   540	[memory]
   541	project_memory = ".shepherd/memory/project.md"
   542	project_doctrines = ".shepherd/memory/doctrines.md"
   543	
   544	[context]
   545	enabled = true
   546	db_path = ".shepherd/shepherd.db"
   547	lock_path = ".shepherd/shepherd.lock"
   548	project_id_path = ".shepherd/project.json"
   549	announce_shctx_path = "off"
   550	"#;
   551	
   552	    // CONTRACT CHANGE. Ordinary loading used to REJECT the retired subset, and
   553	    // that produced a deadlock in the field: a project whose shepherd.toml
   554	    // still carried a retired key could not run `doctor`, `migrate` or `init`
   555	    // -- every tool capable of repairing the config was blocked by the config.
   556	    // A key shepherd itself once wrote is not a typo, so the closed, typed
   557	    // registry is now consulted in every mode.
   558	    let strict =
   559	        loader::load([(path, legacy)]).expect("ordinary loading tolerates the retired subset");
   560	    assert_eq!(
   561	        strict.config.paths.runs,
   562	        PathBuf::from(".shepherd/executions")
   563	    );
   564	
   565	    // ...and typo protection is UNCHANGED, which is the half that matters. A
   566	    // key that was never part of the schema still fails, and still names the
   567	    // candidates.
   568	    let typo = loader::load([(path, "[paths]\nrunz = \".shepherd/executions\"\n")])
   569	        .expect_err("a key that was never in the schema must still fail");
   570	    assert!(typo.to_string().contains("legacy-layout.toml"), "{typo}");
   571	    assert!(typo.to_string().contains("unknown field"), "{typo}");
   572	
   573	    let loaded = loader::load_for_layout_v5_migration([(path, legacy)])
   574	        .expect("migration may load the closed retired subset");
   575	    assert_eq!(
   576	        loaded.config.paths.runs,
   577	        PathBuf::from(".shepherd/executions")
   578	    );
   579	    assert_eq!(loaded.config.context.announce_cli_path, Toggle::On);
   580	}
   581	
   582	#[test]
   583	fn layout_v5_migration_loader_rejects_malformed_or_unknown_legacy_keys() {
   584	    let cases = [
   585	        (
   586	            "bad-path-type.toml",
   587	            "[paths]\nplans = false\n",
   588	            "paths.plans",
   589	        ),
   590	        (
   591	            "bad-memory-type.toml",
   592	            "[memory]\nproject_memory = false\nproject_doctrines = \"doctrines\"\n",
   593	            "memory.project_memory",
   594	        ),
   595	        (
   596	            "unknown-memory.toml",
   597	            "[memory]\nproject_memory = \"memory\"\nproject_doctrines = \"doctrines\"\nextra = \"no\"\n",
   598	            "memory.extra",
   599	        ),
   600	        (
   601	            "missing-memory.toml",
   602	            "[memory]\nproject_memory = \"memory\"\n",
   603	            "memory.project_doctrines",
   604	        ),
   605	        (
   606	            "bad-context-type.toml",
   607	            "[context]\nenabled = \"yes\"\n",
   608	            "context.enabled",
   609	        ),
   610	        (
   611	            "bad-announcement-type.toml",
   612	            "[context]\nannounce_shctx_path = false\n",
   613	            "context.announce_shctx_path",
   614	        ),
   615	        (
   616	            "unknown-context.toml",
   617	            "[context]\ncache_path = \".shepherd/cache\"\n",
   618	            "context.cache_path",
   619	        ),
   620	    ];
   621	
   622	    for (file, text, key) in cases {
   623	        let error = loader::load_for_layout_v5_migration([(Path::new(file), text)])
   624	            .expect_err("only the documented legacy shape is accepted")
   625	            .to_string();
   626	        assert!(error.contains(file), "missing file in: {error}");
   627	        assert!(error.contains(key), "missing {key} in: {error}");
   628	    }
   629	}
   630	
   631	#[test]
   632	fn malformed_toml_names_the_candidate_without_echoing_other_inputs() {
COMMAND: grep -n reports crates/core/tests/loader.rs
537:reports = ".shepherd/docs/reports"
COMMAND: grep -n 'plans = false' crates/core/tests/loader.rs
525:    let malformed = loader::validate(Path::new("bad-retired.toml"), "[paths]\nplans = false\n")
587:            "[paths]\nplans = false\n",
EXIT_CODE: 0
