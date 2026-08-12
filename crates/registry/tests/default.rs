/*
    Appellation: default <test>
    Created At: 2026.08.12:16:20:00
    Contrib: @FL03
*/
//! The SQLite capability contract, asserted as a gate test.
//!
//! Locked decision 4 says `rusqlite` ships with `features = ["bundled"]` and
//! nothing else, on the strength of a one-off probe. A probe that ran once
//! proves nothing about the next dependency bump, so the probe lives here and
//! runs on every commit. If a future `rusqlite` release drops FTS5 or changes
//! the tokenizer, this fails rather than the schema silently degrading.

/// FTS5 must be compiled in. The registry's search tables are external-content
/// FTS5 tables; without this the migrations do not apply at all.
#[test]
fn sqlite_ships_with_fts5() {
    let conn = rusqlite::Connection::open_in_memory().expect("open in-memory database");
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
}

/// The tokenizer is part of the contract, not an implementation detail: search
/// rows indexed with a different one do not match the same queries.
#[test]
fn fts5_accepts_the_contract_tokenizer() {
    let conn = rusqlite::Connection::open_in_memory().expect("open in-memory database");
    conn.execute_batch(
        "CREATE VIRTUAL TABLE probe USING fts5(
             body,
             tokenize = 'unicode61 remove_diacritics 2'
         );
         INSERT INTO probe(body) VALUES ('resumé');",
    )
    .expect("create an fts5 table with the contract tokenizer");

    let hits: i64 = conn
        .query_row(
            "SELECT count(*) FROM probe WHERE probe MATCH 'resume'",
            [],
            |row| row.get(0),
        )
        .expect("query the fts5 index");

    assert_eq!(
        hits, 1,
        "remove_diacritics 2 must fold 'resumé' to 'resume'"
    );
}

/// `json_valid()` backs CHECK constraints across the schema. Assert the
/// behavior, never `PRAGMA compile_options` for `ENABLE_JSON1`: that flag is
/// absent on 3.53.2 and the function still works, because JSON went core in
/// SQLite 3.38.
#[test]
fn json_valid_enforces_check_constraints() {
    let conn = rusqlite::Connection::open_in_memory().expect("open in-memory database");
    conn.execute_batch(
        "CREATE TABLE probe (
             payload TEXT NOT NULL CHECK (json_valid(payload))
         );",
    )
    .expect("create a table with a json_valid CHECK");

    conn.execute("INSERT INTO probe(payload) VALUES ('{\"ok\":true}')", [])
        .expect("well-formed json must be accepted");

    let rejected = conn.execute("INSERT INTO probe(payload) VALUES ('not json')", []);
    assert!(
        rejected.is_err(),
        "the json_valid CHECK must reject malformed payloads"
    );
}

/// The registry is a **file** at `.shepherd/shepherd.db`, not an in-memory
/// handle: 32 bash guard scripts open that exact path with the `sqlite3`
/// binary. So a build that can only manage `:memory:` does not solve the guard
/// problem, it solves a different one.
///
/// This is the check that distinguishes the two WebAssembly targets. On
/// `wasm32-unknown-unknown`, `sqlite-wasm-rs` offers an in-memory VFS and, in
/// browsers, OPFS — and Node has no OPFS, so this test cannot pass there. On
/// `wasm32-wasip1` the WASI VFS reaches a real preopened directory and it can.
///
/// The path is relative on purpose. `std::env::temp_dir()` **panics** on
/// `wasm32-wasip1` -- WASI has no ambient temp directory, only what the host
/// preopens -- so an absolute temp path turns this into a test that cannot run
/// on the one target it exists to characterise. A relative path lands in the
/// preopened directory, which `.cargo/config.toml` grants via `wasmtime --dir=.`.
#[test]
fn a_file_database_survives_being_closed_and_reopened() {
    let path = std::path::PathBuf::from("shepherd-registry-file-vfs-probe.db");
    // WAL leaves sidecars; clear all three so a previous failure cannot make
    // this pass by reading a stale database.
    let cleanup = || {
        for suffix in ["", "-wal", "-shm"] {
            let _ = std::fs::remove_file(format!("{}{suffix}", path.display()));
        }
    };
    cleanup();

    {
        let conn = rusqlite::Connection::open(&path).expect("create a file-backed database");
        conn.execute_batch(
            "PRAGMA journal_mode = WAL;
             CREATE TABLE probe (id INTEGER PRIMARY KEY, note TEXT NOT NULL);
             INSERT INTO probe(note) VALUES ('written before close');",
        )
        .expect("write to a file-backed database");
    }

    let conn = rusqlite::Connection::open(&path).expect("reopen the same file");
    let note: String = conn
        .query_row("SELECT note FROM probe WHERE id = 1", [], |row| row.get(0))
        .expect("read back a row written by a previous connection");

    assert_eq!(note, "written before close");
    drop(conn);
    cleanup();
}
