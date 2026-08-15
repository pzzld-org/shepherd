/*
    Appellation: migrate <module>
    Contrib: @FL03
*/
//! Applies the registry's 21 schema files -- `0001_init.sql` (the baseline,
//! at the schema-dir TOP LEVEL) plus the 20 files under `migrations/`
//! (`0002`-`0021`) -- against a [`rusqlite::Connection`], reading and
//! writing `schema_versions`, never `PRAGMA user_version`.
//! `rusqlite_migration` tracks state in `user_version`, which is not the
//! shipped registry contract.
//!
//! All 21 files live under `migrate/sql/` and are embedded with `include_str!`.
//! This crate is the sole registry-schema authority: no skill, adapter, or
//! language-specific CLI carries a second copy. The closed sequence test pins
//! the count, ordering, filename/version agreement, and nonempty contents.
mod embedded;
mod runner;

pub use self::runner::apply_all;

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU64, Ordering};

    use rusqlite::Connection;

    use super::apply_all;
    use super::embedded;
    use super::runner::dump_sqlite_master;

    static NEXT_DB: AtomicU64 = AtomicU64::new(0);

    /// A fresh, file-backed database (never `:memory:` -- `0001_init.sql`
    /// sets `PRAGMA journal_mode = WAL`, and WAL behaves differently on an
    /// in-memory handle; `crates/registry/tests/default.rs`'s
    /// `a_file_database_survives_being_closed_and_reopened` establishes this
    /// file-backed-probe pattern already). WAL leaves `-wal`/`-shm`
    /// sidecars; all three are cleared before AND after so a previous
    /// failure cannot make a later run pass by reading stale state, and two
    /// tests and independent test processes never share a filename (`cargo
    /// test` and Shepherd's multi-agent development flow can run the same
    /// binary concurrently).
    fn fresh_db(name: &str) -> (Connection, std::path::PathBuf) {
        let path = loop {
            let ordinal = NEXT_DB.fetch_add(1, Ordering::Relaxed);
            let candidate =
                std::path::PathBuf::from(format!("shepherd-registry-migrate-{name}-{ordinal}.db"));
            match std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&candidate)
            {
                Ok(reservation) => {
                    drop(reservation);
                    break candidate;
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => panic!(
                    "reserve file-backed test database {}: {error}",
                    candidate.display()
                ),
            }
        };
        let conn = Connection::open(&path).expect("open a file-backed database");
        (conn, path)
    }

    fn cleanup(path: &std::path::Path) {
        for suffix in ["", "-wal", "-shm"] {
            let _ = std::fs::remove_file(format!("{}{suffix}", path.display()));
        }
    }

    #[test]
    fn fresh_databases_with_the_same_label_never_share_a_path() {
        let (first, first_path) = fresh_db("parallel-process-proof");
        let (second, second_path) = fresh_db("parallel-process-proof");
        drop(first);
        drop(second);
        cleanup(&first_path);
        cleanup(&second_path);

        assert_ne!(
            first_path, second_path,
            "independent test processes must never collide on a fixed database path"
        );
    }

    /// The frozen schema fingerprint this crate's runner must reproduce
    /// byte-for-byte. It is taken against a `full_schema` fixture (case.json:
    /// `db_fixture: "full_schema"`, `capture_sqlite_master: true`) -- see
    /// the lane plan's Deviations log for the full reasoning.
    fn frozen_sqlite_master() -> &'static str {
        include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../conformance/cases/guard-cli/status/ok/expected/sqlite_master.txt"
        ))
    }

    #[test]
    fn applies_twenty_one() {
        let (conn, path) = fresh_db("applies-twenty-one");
        let highest = apply_all(&conn).expect("a fresh database applies cleanly");
        assert_eq!(
            highest, 21,
            "0001_init.sql + 20 files under migrations/ = 21 applied versions"
        );

        let count: u32 = conn
            .query_row("SELECT COUNT(*) FROM schema_versions", [], |row| row.get(0))
            .expect("count schema_versions rows");
        assert_eq!(
            count, 21,
            "schema_versions must hold 21 rows, not 20 -- 0001_init.sql is not a \
             migrations/ file and is easy to silently skip"
        );

        drop(conn);
        cleanup(&path);
    }

    #[test]
    fn apply_all_is_idempotent() {
        let (conn, path) = fresh_db("idempotent");
        apply_all(&conn).expect("first apply");
        let second = apply_all(&conn)
            .expect("a fully-migrated database re-applies as a no-op, never an error");
        assert_eq!(second, 21);
        drop(conn);
        cleanup(&path);
    }

    /// The historical compatibility call shape applied ONLY
    /// `0001_init.sql` (W0-S2's preflight scaffold), and a later `apply_all`
    /// call must gap-fill the remaining 20 without erroring or re-applying
    /// version 1.
    #[test]
    fn gap_fills_after_init_only() {
        let (conn, path) = fresh_db("gap-fill-after-init");
        conn.execute_batch(embedded::INIT_SQL)
            .expect("apply only the baseline, simulating legacy initialization");
        let count: u32 = conn
            .query_row("SELECT COUNT(*) FROM schema_versions", [], |row| row.get(0))
            .expect("count schema_versions rows");
        assert_eq!(
            count, 1,
            "0001_init.sql self-inserts exactly its own version-1 row"
        );

        let highest = apply_all(&conn).expect("gap-fill the remaining 20 migrations");
        assert_eq!(highest, 21);
        let count: u32 = conn
            .query_row("SELECT COUNT(*) FROM schema_versions", [], |row| row.get(0))
            .expect("count schema_versions rows");
        assert_eq!(count, 21);

        drop(conn);
        cleanup(&path);
    }

    #[test]
    fn fts5_tokenizer_verbatim() {
        let (conn, path) = fresh_db("fts5-tokenizer");
        apply_all(&conn).expect("apply the full schema");

        for table in ["index_fts_artifacts", "index_fts_symbols"] {
            let sql: String = conn
                .query_row(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?1",
                    [table],
                    |row| row.get(0),
                )
                .unwrap_or_else(|e| panic!("{table} must exist after a full apply: {e}"));
            assert!(
                sql.contains("tokenize='unicode61 remove_diacritics 2'"),
                "{table} lost the contract tokenizer; sql was: {sql}"
            );
        }

        // The 6 FTS5 sync triggers exist by name (decision 4 / correction C6).
        for trigger in [
            "artifacts_ai",
            "artifacts_ad",
            "artifacts_au",
            "index_symbols_ai",
            "index_symbols_ad",
            "index_symbols_au",
        ] {
            let exists: bool = conn
                .query_row(
                    "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?1)",
                    [trigger],
                    |row| row.get(0),
                )
                .expect("query sqlite_master for the trigger");
            assert!(exists, "sync trigger {trigger} missing after a full apply");
        }

        drop(conn);
        cleanup(&path);
    }

    #[test]
    fn compile_options_include_fts5() {
        let (conn, path) = fresh_db("compile-options");
        apply_all(&conn).expect("apply the full schema");
        let options: Vec<String> = conn
            .prepare("PRAGMA compile_options")
            .expect("prepare compile_options")
            .query_map([], |row| row.get(0))
            .expect("query compile_options")
            .collect::<rusqlite::Result<_>>()
            .expect("collect compile_options");
        assert!(
            options.iter().any(|o| o == "ENABLE_FTS5"),
            "bundled SQLite lost ENABLE_FTS5; compile_options were {options:?}"
        );
        drop(conn);
        cleanup(&path);
    }

    /// The 8 guard-frozen tier-(a) objects (correction C10) exist by exact
    /// name after a full apply: `deliverables`, `focus`, `mem_entries`,
    /// `spawn_leads`, `sprint_metrics`, `teammates`, `worktrees` (7 tables)
    /// plus the view `v_teammates_live`.
    #[test]
    fn guard_frozen_objects_exist() {
        let (conn, path) = fresh_db("guard-frozen");
        apply_all(&conn).expect("apply the full schema");

        for table in [
            "deliverables",
            "focus",
            "mem_entries",
            "spawn_leads",
            "sprint_metrics",
            "teammates",
            "worktrees",
        ] {
            let exists: bool = conn
                .query_row(
                    "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name = ?1)",
                    [table],
                    |row| row.get(0),
                )
                .expect("query sqlite_master");
            assert!(
                exists,
                "guard-frozen object {table} missing after a full apply"
            );
        }
        let view_exists: bool = conn
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = 'v_teammates_live')",
                [],
                |row| row.get(0),
            )
            .expect("query sqlite_master for v_teammates_live");
        assert!(
            view_exists,
            "v_teammates_live view missing after a full apply"
        );

        drop(conn);
        cleanup(&path);
    }

    /// Post-migration object counts match the frozen corpus's RAW
    /// `sqlite_master` row counts exactly (not the addressable/named subset
    /// used elsewhere in this plan): 45 tables (35 base + 2 FTS5 virtual + 8
    /// FTS5 shadow), 14 views, 68 indexes (34 named + 34
    /// `sqlite_autoindex_*`), 7 triggers, 19 tables carrying at least one
    /// `json_valid` CHECK.
    #[test]
    fn object_counts_match_the_frozen_corpus() {
        let (conn, path) = fresh_db("object-counts");
        apply_all(&conn).expect("apply the full schema");

        let count = |kind: &str| -> u32 {
            conn.query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = ?1",
                [kind],
                |row| row.get(0),
            )
            .unwrap_or_else(|e| panic!("count sqlite_master rows of type {kind}: {e}"))
        };
        assert_eq!(count("table"), 45, "table row count");
        assert_eq!(count("view"), 14, "view row count");
        assert_eq!(count("index"), 68, "index row count (34 named + 34 auto)");
        assert_eq!(count("trigger"), 7, "trigger row count");

        let json_valid_tables: u32 = conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND sql LIKE '%json_valid(%'",
                [],
                |row| row.get(0),
            )
            .expect("count tables carrying a json_valid CHECK");
        assert_eq!(
            json_valid_tables, 19,
            "tables carrying >=1 json_valid CHECK"
        );

        drop(conn);
        cleanup(&path);
    }

    /// The order-normalized `sqlite_master` dump this runner produces must
    /// be byte-identical to the frozen schema fingerprint.
    #[test]
    fn sqlite_master_matches_the_frozen_schema_fingerprint() {
        let (conn, path) = fresh_db("sqlite-master-parity");
        apply_all(&conn).expect("apply the full schema");
        let actual = dump_sqlite_master(&conn).expect("dump sqlite_master");

        let expected = frozen_sqlite_master();

        if actual != expected {
            let first_diff = actual
                .lines()
                .zip(expected.lines())
                .enumerate()
                .find(|(_, (a, e))| a != e)
                .map(|(i, (a, e))| {
                    format!("first differing line {i}:\n  actual:   {a}\n  expected: {e}")
                })
                .unwrap_or_else(|| {
                    format!(
                        "line counts differ: actual={} expected={}",
                        actual.lines().count(),
                        expected.lines().count()
                    )
                });
            panic!("sqlite_master dump diverged from the frozen conformance fixture\n{first_diff}");
        }

        drop(conn);
        cleanup(&path);
    }

    /// Negative control: a genuinely broken schema (missing every migration)
    /// must NOT byte-match the frozen fixture -- proves the parity test
    /// above can actually fail, per `scripts/check-plugin.py --self-test`'s
    /// "a test that cannot fail is not a test" discipline (used throughout
    /// this plan, e.g. W2-S1 action 4).
    #[test]
    fn sqlite_master_dump_detects_a_missing_migration() {
        let (conn, path) = fresh_db("negative-control");
        conn.execute_batch(embedded::INIT_SQL)
            .expect("apply only the baseline");
        // Deliberately skip every migrations/*.sql -- the dump must differ.
        let actual = dump_sqlite_master(&conn).expect("dump sqlite_master");
        let expected = frozen_sqlite_master();
        assert_ne!(
            actual, expected,
            "a database missing 20 migrations must not match the full-schema fixture"
        );
        drop(conn);
        cleanup(&path);
    }

    /// Registry SQL has one source under this crate. Reintroducing a copy in a
    /// skill would make the shipped schema depend on which tree a maintainer
    /// happened to edit.
    #[test]
    fn registry_schema_has_no_second_skill_copy() {
        let repo_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let source_root = repo_root.join("skills/context/schema");
        let mut pending = vec![source_root];
        let mut files = Vec::new();
        while let Some(directory) = pending.pop() {
            let Ok(entries) = std::fs::read_dir(directory) else {
                continue;
            };
            for entry in entries {
                let path = entry.expect("read retired skill schema entry").path();
                if path.is_dir() {
                    pending.push(path);
                } else {
                    files.push(path);
                }
            }
        }
        assert!(
            files.is_empty(),
            "registry schema must live only in crates/registry/src/migrate/sql; found {files:?}"
        );
    }

    #[test]
    fn embedded_migration_sequence_is_closed_and_contiguous() {
        assert_eq!(embedded::MIGRATIONS.len(), 20);
        for (offset, migration) in embedded::MIGRATIONS.iter().enumerate() {
            let expected = u32::try_from(offset).expect("migration offset fits") + 2;
            assert_eq!(migration.version, expected);
            assert!(
                migration.filename.starts_with(&format!("{expected:04}_")),
                "migration {} has a filename that disagrees with its version",
                migration.filename
            );
            assert!(
                !migration.sql.trim().is_empty(),
                "migration {} must embed nonempty SQL",
                migration.filename
            );
        }
    }
}
