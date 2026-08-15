/*
    Appellation: registry <integration tests>
    Created At: 2026.08.14
    Contrib: @FL03
*/

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use shepherd_registry::{Error, OpenMode, Registry, Result};

static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

fn fixture_dir(label: &str) -> PathBuf {
    loop {
        let ordinal = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
        let path = PathBuf::from(format!("shepherd-registry-api-{label}-{ordinal}"));
        match std::fs::create_dir(&path) {
            Ok(()) => return path,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => panic!(
                "create isolated registry fixture {}: {error}",
                path.display()
            ),
        }
    }
}

fn cleanup(path: &Path) {
    std::fs::remove_dir_all(path).expect("remove isolated registry fixture");
}

fn insert_project(registry: &Registry, id: &str, name: &str) -> Result<usize> {
    registry.execute(
        "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?1, ?2, ?3, ?4)",
        (id, name, 1_i64, 1_i64),
    )
}

#[test]
fn migrated_open_builds_the_full_schema_with_runtime_pragmas() {
    let dir = fixture_dir("migrated-open");
    let path = dir.join("shepherd.db");

    let registry = Registry::open_migrated(&path).expect("open and migrate registry");
    assert_eq!(registry.path(), path);
    assert_eq!(registry.mode(), OpenMode::ReadWriteCreate);
    assert_eq!(registry.schema_version().expect("read schema version"), 21);

    let journal: String = registry
        .query_one("PRAGMA journal_mode", (), |row| row.get(0))
        .expect("read journal mode");
    // SQLite's WASI VFS has no shared-memory locking for WAL, so the
    // requested mode correctly falls back to the file-backed `delete` mode.
    // Native hosts must retain WAL; the WASI lane separately proves that the
    // resulting database survives close/reopen and executes every migration.
    let expected_journal = if cfg!(target_os = "wasi") {
        "delete"
    } else {
        "wal"
    };
    assert_eq!(journal.to_ascii_lowercase(), expected_journal);

    let foreign_keys: i64 = registry
        .query_one("PRAGMA foreign_keys", (), |row| row.get(0))
        .expect("read foreign-key mode");
    assert_eq!(foreign_keys, 1);

    let busy_timeout: i64 = registry
        .query_one("PRAGMA busy_timeout", (), |row| row.get(0))
        .expect("read busy timeout");
    assert_eq!(
        busy_timeout,
        i64::try_from(Registry::DEFAULT_BUSY_TIMEOUT.as_millis()).expect("timeout fits in i64")
    );

    drop(registry);
    cleanup(&dir);
}

#[test]
fn parameterized_execute_and_typed_queries_preserve_hostile_text() {
    #[derive(Debug, Eq, PartialEq)]
    struct Project {
        id: String,
        name: String,
    }

    let dir = fixture_dir("parameterized-query");
    let path = dir.join("shepherd.db");
    let registry = Registry::open_migrated(&path).expect("open registry");
    let hostile = "Joe's project'); DROP TABLE projects;--";

    insert_project(&registry, "project-1", hostile).expect("bound insert succeeds");
    let rows = registry
        .query(
            "SELECT id, name FROM projects WHERE name = ?1 ORDER BY id",
            [hostile],
            |row| {
                Ok(Project {
                    id: row.get(0)?,
                    name: row.get(1)?,
                })
            },
        )
        .expect("typed query succeeds");
    assert_eq!(
        rows,
        [Project {
            id: "project-1".into(),
            name: hostile.into(),
        }]
    );

    let projects_table: i64 = registry
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects')",
            (),
            |row| row.get(0),
        )
        .expect("query catalog");
    assert_eq!(projects_table, 1);

    drop(registry);
    cleanup(&dir);
}

#[test]
fn read_only_mode_reads_but_rejects_mutation_and_migration() {
    let dir = fixture_dir("read-only");
    let path = dir.join("shepherd.db");
    {
        let registry = Registry::open_migrated(&path).expect("seed registry");
        insert_project(&registry, "project-1", "read me").expect("seed project");
    }

    let registry = Registry::open(&path, OpenMode::ReadOnly).expect("open read-only registry");
    let name: String = registry
        .query_one(
            "SELECT name FROM projects WHERE id = ?1",
            ["project-1"],
            |row| row.get(0),
        )
        .expect("read-only query succeeds");
    assert_eq!(name, "read me");

    assert!(matches!(
        registry.execute("DELETE FROM projects", ()),
        Err(Error::ReadOnly)
    ));
    assert!(matches!(registry.apply_migrations(), Err(Error::ReadOnly)));

    let disguised_mutation = registry.query("DELETE FROM projects RETURNING id", (), |row| {
        row.get::<_, String>(0)
    });
    assert!(
        matches!(disguised_mutation, Err(Error::Sqlite(_))),
        "SQLite query_only must backstop a mutation passed through the query surface"
    );
    let still_present: i64 = registry
        .query_one("SELECT COUNT(*) FROM projects", (), |row| row.get(0))
        .expect("failed mutation leaves registry intact");
    assert_eq!(still_present, 1);

    drop(registry);
    cleanup(&dir);
}

#[test]
fn read_write_existing_never_creates_a_missing_database() {
    let dir = fixture_dir("existing-only");
    let path = dir.join("missing.db");

    let error = Registry::open(&path, OpenMode::ReadWrite)
        .expect_err("read-write-existing must reject a missing database");
    assert!(matches!(error, Error::Sqlite(_)));
    assert!(!path.exists());

    cleanup(&dir);
}

#[test]
fn migration_refuses_a_schema_newer_than_the_binary() {
    let dir = fixture_dir("schema-ahead");
    let path = dir.join("shepherd.db");
    let registry = Registry::open_migrated(&path).expect("seed current registry");
    registry
        .execute(
            "INSERT INTO schema_versions (version, applied_at, checksum) VALUES (?1, ?2, ?3)",
            (999_i64, 1_i64, "future-schema"),
        )
        .expect("model a future implementation's migration");

    let error = registry
        .apply_migrations()
        .expect_err("an older binary must not migrate or accept a future schema");
    assert!(matches!(
        error,
        Error::SchemaAhead {
            found: 999,
            supported: 21
        }
    ));
    assert_eq!(
        registry
            .schema_version()
            .expect("future version remains readable"),
        999
    );

    drop(registry);
    cleanup(&dir);
}

#[cfg(unix)]
#[test]
fn registry_open_refuses_a_symlink_database_target() {
    use std::os::unix::fs::symlink;

    let dir = fixture_dir("nofollow");
    let real_path = dir.join("real.db");
    drop(Registry::open_migrated(&real_path).expect("seed real registry"));
    let link_path = dir.join("linked.db");
    symlink(&real_path, &link_path).expect("create final-component symlink");

    let error = Registry::open(&link_path, OpenMode::ReadWrite)
        .expect_err("the registry boundary must not follow a database symlink");
    assert!(matches!(error, Error::UnsafePath(_)));

    cleanup(&dir);
}

#[test]
fn transaction_commits_on_success_and_rolls_back_on_error() {
    let dir = fixture_dir("transactions");
    let path = dir.join("shepherd.db");
    let mut registry = Registry::open_migrated(&path).expect("open registry");

    registry
        .transaction(|tx| {
            tx.execute(
                "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?1, ?2, 1, 1)",
                ("committed", "committed"),
            )?;
            Ok(())
        })
        .expect("commit successful transaction");

    let rolled_back: Result<()> = registry.transaction(|tx| {
        tx.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?1, ?2, 1, 1)",
            ("rolled-back", "rolled-back"),
        )?;
        Err(Error::unknown("force rollback"))
    });
    assert!(matches!(rolled_back, Err(Error::Unknown(message)) if message == "force rollback"));

    let ids = registry
        .query("SELECT id FROM projects ORDER BY id", (), |row| {
            row.get::<_, String>(0)
        })
        .expect("query projects");
    assert_eq!(ids, ["committed"]);

    drop(registry);
    cleanup(&dir);
}

#[test]
fn read_only_registry_rejects_transactions_before_calling_the_body() {
    let dir = fixture_dir("read-only-transaction");
    let path = dir.join("shepherd.db");
    drop(Registry::open_migrated(&path).expect("seed registry"));

    let mut registry = Registry::open(&path, OpenMode::ReadOnly).expect("open read-only");
    let mut called = false;
    let result: Result<()> = registry.transaction(|_| {
        called = true;
        Ok(())
    });
    assert!(matches!(result, Err(Error::ReadOnly)));
    assert!(!called, "read-only transaction body must never execute");

    drop(registry);
    cleanup(&dir);
}
