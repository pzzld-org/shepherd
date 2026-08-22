# Historical pre-rebase reproduction

This file preserves the original `6837e109...` reproduction only. It is not
final-state evidence. Current base, implementation, projection, and gate results
are recorded in `status-and-diff.md`, `implementation-verification.md`, and
`issue-369-authored-spawn.md`.

HEAD: 6837e109ab618e3d22cb34c637de8ed7b7da7c69
COMMAND: nl -ba crates/cli/tests/migrate_layout.rs | sed -n 243,280p
   243	    let runs = namespace.join("runs");
   244	    write(&runs.join("v645/run.json"), &run_state("v645"));
   245	    write(
   246	        &namespace.join("shepherd.toml"),
   247	        b"[paths]\nplans = \".shepherd/docs/plans\"\n",
   248	    );
   249	    write(
   250	        &namespace.join("shepherd.pi.toml"),
   251	        b"[paths]\nreports = false\n",
   252	    );
   253	    let isolated_home = root.join("home");
   254	    fs::create_dir_all(&isolated_home).expect("create isolated home");
   255	
   256	    let output = Command::new(env!("CARGO_BIN_EXE_shepherd"))
   257	        .args([
   258	            "migrate",
   259	            "--layout",
   260	            "v5",
   261	            "--scope",
   262	            "project",
   263	            "--dry-run",
   264	        ])
   265	        .current_dir(&root)
   266	        .env("HOME", &isolated_home)
   267	        .env_remove("SHEPHERD_HOME")
   268	        .env_remove("SHEPHERD_HARNESS")
   269	        .output()
   270	        .expect("run canonical CLI against inactive harness config");
   271	
   272	    assert!(!output.status.success(), "invalid retired value must block");
   273	    let stderr = String::from_utf8_lossy(&output.stderr);
   274	    assert!(stderr.contains("shepherd.pi.toml"), "{stderr}");
   275	    assert!(stderr.contains("paths.reports"), "{stderr}");
   276	    assert_eq!(
   277	        fs::read(namespace.join("shepherd.pi.toml")).expect("invalid config remains unchanged"),
   278	        b"[paths]\nreports = false\n"
   279	    );
   280	
COMMAND: grep -n 'reports = false' crates/core/tests/loader.rs crates/cli/tests/migrate_layout.rs
crates/cli/tests/migrate_layout.rs:251:        b"[paths]\nreports = false\n",
crates/cli/tests/migrate_layout.rs:278:        b"[paths]\nreports = false\n"
EXIT_CODE: 0
