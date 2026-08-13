/*
    Appellation: migrate <module>
    Contrib: @FL03
*/
//! Applies the registry's 21 schema files -- `0001_init.sql` (the baseline,
//! at the schema-dir TOP LEVEL) plus the 20 files under `migrations/`
//! (`0002`-`0021`) -- against a [`rusqlite::Connection`], reading and
//! writing `schema_versions`, never `PRAGMA user_version` (decision 6:
//! `rusqlite_migration` tracks state in `user_version`, which neither the
//! existing bash (`cmd_migrate.sh`) nor Python
//! (`shepherd_cli.commands.migrate`) runner would ever see).
//!
//! All 21 files are vendored verbatim under `migrate/sql/` at build time
//! (`include_str!`) rather than read from `skills/context/schema/` at
//! runtime, for two reasons: a published `rlib` cannot `include_str!`
//! outside its own package root (`cargo package` only bundles files under
//! the crate directory), and a self-contained crate should not need the
//! monorepo layout on disk to build. [`tests::vendored_copies_match_source`]
//! is the standing drift check -- it fails the day `skills/context/schema/**`
//! changes without the vendored copy being updated to match, so "verbatim"
//! stays true after this landed, not just at the moment it was written.
mod embedded;
mod runner;

pub use self::runner::apply_all;

#[cfg(test)]
mod tests {
    use rusqlite::Connection;

    use super::apply_all;
    use super::embedded;
    use super::runner::dump_sqlite_master;

    /// A fresh, file-backed database (never `:memory:` -- `0001_init.sql`
    /// sets `PRAGMA journal_mode = WAL`, and WAL behaves differently on an
    /// in-memory handle; `crates/registry/tests/default.rs`'s
    /// `a_file_database_survives_being_closed_and_reopened` establishes this
    /// file-backed-probe pattern already). WAL leaves `-wal`/`-shm`
    /// sidecars; all three are cleared before AND after so a previous
    /// failure cannot make a later run pass by reading stale state, and two
    /// tests never share a filename (`cargo test` runs unit tests in
    /// parallel by default).
    fn fresh_db(name: &str) -> (Connection, std::path::PathBuf) {
        let path = std::path::PathBuf::from(format!("shepherd-registry-migrate-{name}.db"));
        cleanup(&path);
        let conn = Connection::open(&path).expect("open a file-backed database");
        (conn, path)
    }

    fn cleanup(path: &std::path::Path) {
        for suffix in ["", "-wal", "-shm"] {
            let _ = std::fs::remove_file(format!("{}{suffix}", path.display()));
        }
    }

    /// The frozen Python capture this crate's runner must reproduce
    /// byte-for-byte. `conformance/cases/schema/**` does not exist in this
    /// tree; the ONE `sqlite_master` capture in the whole corpus is this
    /// one, taken against a `full_schema` fixture (case.json:
    /// `db_fixture: "full_schema"`, `capture_sqlite_master: true`) -- see
    /// the lane plan's Deviations log for the full reasoning.
    fn frozen_sqlite_master_path() -> std::path::PathBuf {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../conformance/cases/guard-cli/status/ok/expected/sqlite_master.txt")
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

    /// The realistic production call shape: `shctx init` applies ONLY
    /// `0001_init.sql` (W0-S2's preflight scaffold), and a later `apply_all`
    /// call must gap-fill the remaining 20 without erroring or re-applying
    /// version 1.
    #[test]
    fn gap_fills_after_init_only() {
        let (conn, path) = fresh_db("gap-fill-after-init");
        conn.execute_batch(embedded::INIT_SQL)
            .expect("apply only the baseline, simulating `shctx init`");
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
    /// be byte-identical to the frozen Python capture.
    #[test]
    fn sqlite_master_matches_the_frozen_python_capture() {
        let (conn, path) = fresh_db("sqlite-master-parity");
        apply_all(&conn).expect("apply the full schema");
        let actual = dump_sqlite_master(&conn).expect("dump sqlite_master");

        let expected_path = frozen_sqlite_master_path();
        let expected = std::fs::read_to_string(&expected_path)
            .unwrap_or_else(|e| panic!("read frozen fixture {}: {e}", expected_path.display()));

        if actual != expected {
            let first_diff = actual
                .lines()
                .zip(expected.lines())
                .enumerate()
                .find(|(_, (a, e))| a != e)
                .map(|(i, (a, e))| {
                    format!("first differing line {i}:\n  rust:   {a}\n  python: {e}")
                })
                .unwrap_or_else(|| {
                    format!(
                        "line counts differ: rust={} python={}",
                        actual.lines().count(),
                        expected.lines().count()
                    )
                });
            panic!(
                "sqlite_master dump diverged from the frozen Python capture at {}\n{first_diff}",
                expected_path.display()
            );
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
        let expected =
            std::fs::read_to_string(frozen_sqlite_master_path()).expect("read frozen fixture");
        assert_ne!(
            actual, expected,
            "a database missing 20 migrations must not match the full-schema fixture"
        );
        drop(conn);
        cleanup(&path);
    }

    /// Standing drift check: the vendored copies under `migrate/sql/` must
    /// stay byte-identical to their source of truth at
    /// `skills/context/schema/**`. That tree is `must_not_touch`/read-only
    /// for this crate -- the SQL is the contract, ported verbatim, never
    /// edited -- so this test is the only thing that would catch a future
    /// edit to the source drifting away from the vendored copy this crate
    /// actually compiles against.
    #[test]
    fn vendored_copies_match_source() {
        let repo_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let source_root = repo_root.join("skills/context/schema");

        let mut pairs: Vec<(std::path::PathBuf, &str)> =
            vec![(source_root.join("0001_init.sql"), embedded::INIT_SQL)];
        for migration in embedded::MIGRATIONS {
            pairs.push((
                source_root.join("migrations").join(migration.filename),
                migration.sql,
            ));
        }

        assert_eq!(
            pairs.len(),
            21,
            "21 vendored files expected (0001_init.sql + 20 under migrations/)"
        );

        for (source_path, vendored_sql) in pairs {
            let source_sql = std::fs::read_to_string(&source_path)
                .unwrap_or_else(|e| panic!("read source-of-truth {}: {e}", source_path.display()));
            assert_eq!(
                vendored_sql,
                source_sql,
                "vendored copy drifted from {} -- re-copy it verbatim, never edit either side by hand",
                source_path.display()
            );
        }
    }
}
