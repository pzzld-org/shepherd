mod support;

/*
    Appellation: run_store <integration tests>
    Created At: 2026.08.14
    Contrib: @FL03
*/

use std::fs::OpenOptions;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use shepherd_cli::{RunStore, RunStoreError, RunStoreResult};

fn fixture_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "shepherd-run-store-{label}-{}-{nonce:x}",
        std::process::id()
    ));
    std::fs::create_dir_all(&path).expect("create isolated run-store fixture");
    std::fs::canonicalize(path).expect("canonical isolated run-store fixture")
}

fn cleanup(path: &Path) {
    support::remove_dir_all(path)
}

fn state(run: &str) -> shepherd::RunState {
    serde_json::from_value(serde_json::json!({
        "run": run,
        "status": "executing",
        "future_top_level": {"owned_by": "another implementation"}
    }))
    .expect("fixture state parses")
}

fn wait_for_file(path: &Path) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !path.is_file() {
        assert!(
            Instant::now() < deadline,
            "timed out waiting for {}",
            path.display()
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn update_holds_one_lock_across_load_mutation_and_atomic_store() {
    let dir = fixture_dir("roundtrip");
    let path = dir.join("v645/run.json");
    let store = RunStore::new(&path);
    store.initialize(&state("v645")).expect("initialize run");

    store
        .update(|run| {
            run.updated_at = 42;
            run.extra
                .insert("new_writer_field".into(), serde_json::json!([1, 2, 3]));
            Ok(())
        })
        .expect("update run");

    let loaded = store.load().expect("load updated run");
    assert_eq!(loaded.updated_at, 42);
    assert_eq!(
        loaded.extra.get("future_top_level"),
        Some(&serde_json::json!({"owned_by": "another implementation"}))
    );
    assert_eq!(
        loaded.extra.get("new_writer_field"),
        Some(&serde_json::json!([1, 2, 3]))
    );
    assert_eq!(
        std::fs::read_to_string(&path).expect("read canonical bytes"),
        format!("{}\n", loaded.to_canonical_json())
    );
    assert_eq!(store.lock_path(), dir.join("v645/run.lock"));
    assert!(store.lock_path().is_file());

    cleanup(&dir);
}

#[test]
fn failed_mutation_and_panic_leave_the_previous_document_intact_and_release_the_lock() {
    let dir = fixture_dir("failed-mutation");
    let path = dir.join("v645/run.json");
    let store = RunStore::new(&path);
    store.initialize(&state("v645")).expect("initialize run");
    let before = std::fs::read(&path).expect("read baseline bytes");

    let failed: RunStoreResult<()> = store.update(|run| {
        run.status = "closed".into();
        Err(RunStoreError::mutation("refuse this transition"))
    });
    assert!(matches!(
        failed,
        Err(RunStoreError::Mutation(message)) if message == "refuse this transition"
    ));
    assert_eq!(std::fs::read(&path).expect("read after error"), before);

    let panicked = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _: RunStoreResult<()> = store.update(|_| panic!("simulated mutator panic"));
    }));
    assert!(panicked.is_err());
    assert_eq!(std::fs::read(&path).expect("read after panic"), before);

    store
        .update(|run| {
            run.updated_at = 9;
            Ok(())
        })
        .expect("lock is released during unwind");

    cleanup(&dir);
}

#[test]
fn invalid_or_foreign_state_is_never_published() {
    let dir = fixture_dir("validation");
    let path = dir.join("v645/run.json");
    let store = RunStore::new(&path);

    let mut mismatched = state("other-run");
    assert!(matches!(
        store.initialize(&mismatched),
        Err(RunStoreError::Validation(_))
    ));
    assert!(!path.exists());

    mismatched.run = "v645".into();
    store
        .initialize(&mismatched)
        .expect("valid state initializes");
    let before = std::fs::read(&path).expect("read baseline");

    let invalid = store.update(|run| {
        run.status = "made-up-state".into();
        run.lanes.push(
            serde_json::from_value(serde_json::json!({"id": "../escape"}))
                .expect("lane fixture parses"),
        );
        Ok(())
    });
    assert!(matches!(invalid, Err(RunStoreError::Validation(_))));
    assert_eq!(std::fs::read(&path).expect("invalid write refused"), before);

    let schema_ahead = store.update(|run| {
        run.schema_version += 1;
        Ok(())
    });
    assert!(matches!(schema_ahead, Err(RunStoreError::SchemaAhead(2))));
    assert_eq!(
        std::fs::read(&path).expect("foreign schema refused"),
        before
    );

    cleanup(&dir);
}

#[test]
fn schema_ahead_state_is_readable_for_resume_but_never_overwritten() {
    let dir = fixture_dir("schema-ahead-read");
    let path = dir.join("v645/run.json");
    let mut future = state("v645");
    future.schema_version = 2;
    future.status = "paused-by-future-host".into();
    future.lanes.push(
        serde_json::from_value(serde_json::json!({
            "id": "l1-future",
            "state": "waiting-on-future-host",
            "future_lane_field": {"preserve": true}
        }))
        .expect("future lane parses through the tolerant state schema"),
    );
    future
        .store(&path)
        .expect("a future implementation publishes its state");
    let before = std::fs::read(&path).expect("read future bytes");

    let store = RunStore::new(&path);
    let loaded = store
        .load()
        .expect("schema-ahead state remains available to read-only resume and inspection");
    assert_eq!(loaded.schema_version, 2);
    assert_eq!(loaded.status, "paused-by-future-host");
    assert_eq!(loaded.lanes[0].state, "waiting-on-future-host");

    let mut called = false;
    let update: RunStoreResult<()> = store.update(|run| {
        called = true;
        run.updated_at += 1;
        Ok(())
    });
    assert!(matches!(update, Err(RunStoreError::SchemaAhead(2))));
    assert!(
        !called,
        "a schema-ahead document must be rejected before mutation"
    );
    assert_eq!(std::fs::read(&path).expect("read preserved bytes"), before);

    cleanup(&dir);
}

#[test]
fn raw_rewrite_holds_the_lock_and_refuses_to_publish_invalid_migrations() {
    let dir = fixture_dir("raw-rewrite");
    let path = dir.join("v645/run.json");
    let store = RunStore::new(&path);
    store.initialize(&state("v645")).expect("initialize run");
    let before = std::fs::read(&path).expect("read baseline");

    let invalid = store.rewrite_from_raw(|bytes| {
        assert_eq!(
            bytes,
            before.as_slice(),
            "transform receives current bytes under lock"
        );
        let mut state = state("v645");
        state.status = "not-a-status".into();
        Ok((state, ()))
    });
    assert!(matches!(invalid, Err(RunStoreError::Validation(_))));
    assert_eq!(
        std::fs::read(&path).expect("invalid migration preserves bytes"),
        before
    );

    let migrated = store
        .rewrite_from_raw(|bytes| {
            let mut migrated: shepherd::RunState = serde_json::from_slice(bytes)
                .expect("fixture document remains decodable during transform");
            migrated.status = "planned".into();
            Ok((migrated, "run_id -> run"))
        })
        .expect("valid migration writes atomically");
    assert_eq!(migrated, "run_id -> run");
    assert_eq!(
        store.load().expect("load migrated document").status,
        "planned"
    );

    cleanup(&dir);
}

#[test]
fn reading_or_updating_a_missing_run_never_scaffolds_an_orphan_directory() {
    let dir = fixture_dir("missing-run");
    let run_dir = dir.join("absent");
    let store = RunStore::new(run_dir.join("run.json"));

    assert!(store.load().is_err());
    let update: RunStoreResult<()> = store.update(|_| Ok(()));
    assert!(update.is_err());
    assert!(
        !run_dir.exists(),
        "a read path must not create {} or a stray run.lock",
        run_dir.display(),
    );

    cleanup(&dir);
}

#[test]
fn lock_contention_has_a_real_upper_bound_for_reads_and_writes() {
    let dir = fixture_dir("timeout");
    let path = dir.join("v645/run.json");
    let seed_store = RunStore::new(&path);
    seed_store
        .initialize(&state("v645"))
        .expect("initialize run");

    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .open(seed_store.lock_path())
        .expect("open sidecar lock");
    lock.lock().expect("hold competing lock");

    let store = RunStore::with_timeout(&path, Duration::from_millis(40));
    let started = Instant::now();
    assert!(matches!(
        store.load(),
        Err(RunStoreError::LockTimeout { .. })
    ));
    let read_elapsed = started.elapsed();
    assert!(read_elapsed >= Duration::from_millis(35));
    assert!(read_elapsed < Duration::from_millis(500));

    let started = Instant::now();
    let result: RunStoreResult<()> = store.update(|_| Ok(()));
    assert!(matches!(result, Err(RunStoreError::LockTimeout { .. })));
    let write_elapsed = started.elapsed();
    assert!(write_elapsed >= Duration::from_millis(35));
    assert!(write_elapsed < Duration::from_millis(500));

    lock.unlock().expect("release competing lock");
    cleanup(&dir);
}

#[test]
fn two_os_processes_cannot_lose_each_others_lane_update() {
    let dir = fixture_dir("process-race");
    let path = dir.join("v645/run.json");
    RunStore::new(&path)
        .initialize(&state("v645"))
        .expect("initialize run");

    let go = dir.join("go");
    let ready_a = dir.join("ready-a");
    let ready_b = dir.join("ready-b");
    let spawn = |lane: &str, ready: &Path| {
        Command::new(std::env::current_exe().expect("current test binary"))
            .args(["--ignored", "--exact", "run_store_process_helper"])
            .env("RUN_STORE_HELPER_MODE", "update")
            .env("RUN_STORE_PATH", &path)
            .env("RUN_STORE_LANE", lane)
            .env("RUN_STORE_READY", ready)
            .env("RUN_STORE_GO", &go)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn update helper")
    };

    let child_a = spawn("l1-alpha", &ready_a);
    let child_b = spawn("l2-beta", &ready_b);
    wait_for_file(&ready_a);
    wait_for_file(&ready_b);
    std::fs::write(&go, b"go\n").expect("release process barrier");

    for child in [child_a, child_b] {
        let output = child.wait_with_output().expect("wait for update helper");
        assert!(
            output.status.success(),
            "helper failed: stdout={} stderr={}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }

    let loaded = RunStore::new(&path).load().expect("load final state");
    let lane_ids: Vec<_> = loaded.lanes.iter().map(|lane| lane.id.as_str()).collect();
    assert_eq!(lane_ids.len(), 2, "both updates survive: {lane_ids:?}");
    assert!(lane_ids.contains(&"l1-alpha"));
    assert!(lane_ids.contains(&"l2-beta"));
    assert_eq!(loaded.updated_at, 2);

    cleanup(&dir);
}

#[test]
fn an_aborted_process_releases_its_os_lock() {
    let dir = fixture_dir("crash-release");
    let path = dir.join("v645/run.json");
    let store = RunStore::new(&path);
    store.initialize(&state("v645")).expect("initialize run");
    let ready = dir.join("crash-ready");

    let output = Command::new(std::env::current_exe().expect("current test binary"))
        .args(["--ignored", "--exact", "run_store_process_helper"])
        .env("RUN_STORE_HELPER_MODE", "crash")
        .env("RUN_STORE_PATH", &path)
        .env("RUN_STORE_READY", &ready)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .expect("run crashing lock holder");
    assert!(
        !output.status.success(),
        "helper must abort, not exit cleanly"
    );
    assert!(ready.is_file(), "helper acquired the lock before aborting");

    store
        .update(|run| {
            run.updated_at = 7;
            Ok(())
        })
        .expect("OS releases the crashed process lock");

    cleanup(&dir);
}

#[test]
#[ignore = "subprocess-only helper"]
fn run_store_process_helper() {
    let mode = std::env::var("RUN_STORE_HELPER_MODE").expect("helper mode");
    let path = PathBuf::from(std::env::var_os("RUN_STORE_PATH").expect("run path"));
    let ready = PathBuf::from(std::env::var_os("RUN_STORE_READY").expect("ready path"));

    if mode == "crash" {
        let lock_path = path.with_file_name("run.lock");
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(lock_path)
            .expect("open crash lock");
        lock.lock().expect("acquire crash lock");
        std::fs::write(ready, b"locked\n").expect("publish crash readiness");
        std::process::abort();
    }

    assert_eq!(mode, "update");
    let lane = std::env::var("RUN_STORE_LANE").expect("lane id");
    let go = PathBuf::from(std::env::var_os("RUN_STORE_GO").expect("barrier path"));
    std::fs::write(&ready, b"ready\n").expect("publish update readiness");
    wait_for_file(&go);

    RunStore::with_timeout(path, Duration::from_secs(3))
        .update(|run| {
            std::thread::sleep(Duration::from_millis(150));
            run.lanes.push(
                serde_json::from_value(serde_json::json!({"id": lane}))
                    .expect("lane helper state parses"),
            );
            run.updated_at += 1;
            Ok(())
        })
        .expect("helper update succeeds");
}
