/*
    Appellation: runner <module>
    Contrib: @FL03
*/
//! The migration runner: reads and writes `schema_versions`, never `PRAGMA
//! user_version` (decision 6 -- both existing bash (`cmd_migrate.sh`) and
//! Python (`shepherd_cli.commands.migrate`) runners already read
//! `schema_versions`, and `rusqlite_migration` tracks state in
//! `user_version` instead, which neither of them would ever see).

use std::collections::HashSet;
use std::fmt::Write as _;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{Connection, params};
use sha2::{Digest, Sha256};

use super::embedded::{INIT_SQL, MIGRATIONS};
use crate::error::{Error, Result};

/// sqlite error substrings meaning "a sibling process already applied this
/// DDL" rather than a real failure -- mirrors
/// `services/cli/shepherd_cli/commands/migrate.py`'s
/// `_TOLERATED_ERROR_MARKERS` exactly, so a concurrent `shctx init` +
/// `apply_all` race degrades the same way the Python runner's does, instead
/// of surfacing as a hard failure.
const TOLERATED_ERROR_MARKERS: [&str; 2] = ["duplicate column", "already exists"];

/// Applies every pending schema migration against `conn` and returns the
/// highest applied `schema_versions.version`.
///
/// Bootstraps a brand-new, empty database from nothing: if `schema_versions`
/// does not exist yet, `0001_init.sql` (the baseline -- see the crate's own
/// top-level doc comment on why it is NOT under `migrations/`) is applied
/// first; it creates `schema_versions` itself and self-inserts its own
/// version-1 row, so this function never inserts that row a second time.
/// Every migration under `migrations/` (`0002`..`0021`) is then applied in
/// filename order, SKIPPING any version already present in
/// `schema_versions` -- a gap-fill, not a `> MAX(version)` check, so a
/// genuine gap a middle migration left behind (e.g. a database a sibling
/// process partially migrated) is caught too. On a fully fresh database this
/// returns `21`; called again on an already-fully-migrated database it is a
/// no-op that still returns `21`.
///
/// Known limitation, out of scope to guard against: this function detects
/// "already bootstrapped" solely from `schema_versions` existing. Every real
/// caller reaches that state only via a full `0001_init.sql` apply (it wraps
/// its own `CREATE TABLE`s in one `BEGIN`/`COMMIT`), so the two are
/// equivalent in practice; a database hand-edited to have `schema_versions`
/// without the rest of the baseline schema is not a supported input, and
/// migration `0002` (which references `projects`) will fail loudly rather
/// than silently miscount.
///
/// # Errors
///
/// Returns [`Error::Migration`] naming the exact file and underlying SQLite
/// message on the FIRST hard failure -- anything other than the two
/// tolerated markers above -- and stops there without attempting the
/// remaining migrations, mirroring `cmd_migrate.sh`'s `set -e` abort.
pub fn apply_all(conn: &Connection) -> Result<u32> {
    if !schema_versions_exists(conn)? {
        conn.execute_batch(INIT_SQL)
            .map_err(|source| Error::Migration {
                version: 1,
                message: format!("0001_init.sql: {source}"),
            })?;
    }

    let mut known = known_versions(conn)?;

    for migration in MIGRATIONS {
        if known.contains(&migration.version) {
            continue;
        }

        if let Err(source) = conn.execute_batch(migration.sql) {
            let message = source.to_string();
            let tolerated = TOLERATED_ERROR_MARKERS
                .iter()
                .any(|marker| message.to_ascii_lowercase().contains(marker));
            if !tolerated {
                return Err(Error::Migration {
                    version: i64::from(migration.version),
                    message: format!("{}: {message}", migration.filename),
                });
            }
        }

        record_version(
            conn,
            migration.version,
            checksum_hex(migration.sql.as_bytes()),
        )?;
        known.insert(migration.version);
    }

    read_current_version(conn)
}

/// `SELECT COALESCE(MAX(version), 0) FROM schema_versions` -- the highest
/// applied version, or 0 on an empty (or absent) table.
fn read_current_version(conn: &Connection) -> Result<u32> {
    let max: i64 = conn.query_row(
        "SELECT COALESCE(MAX(version), 0) FROM schema_versions",
        [],
        |row| row.get(0),
    )?;
    u32::try_from(max)
        .map_err(|_| Error::unknown(format!("schema_versions.version out of range: {max}")))
}

/// An order-normalized `sqlite_master` dump -- the registry parity surface.
///
/// One `type\tname\ttbl_name\tsql\n` line per catalog entry, `ORDER BY
/// type, name` (never physical/rowid order, which SQLite does not
/// guarantee stable across writes). Mirrors
/// `conformance/lib/harness.py`'s `dump_sqlite_master` byte-for-byte,
/// including its escaping: a multi-line `CREATE TABLE`'s own `sql` text
/// carries real newlines, replaced here with the two-character literal
/// `\n` so the dump stays one physical line per catalog entry. No name
/// filter -- SQLite's own bookkeeping rows (`sqlite_sequence`,
/// `sqlite_autoindex_*`) are part of the real fingerprint; a port that
/// models a column differently (e.g. drops `AUTOINCREMENT`, or names a
/// `UNIQUE` index explicitly) changes exactly these rows, which is
/// precisely the drift this dump exists to catch.
///
/// `pub(crate)`, not `pub`: the step's declared interface is `apply_all`
/// alone. Consumed today only by this module's own `#[cfg(test)]` parity
/// tests, hence the `allow(dead_code)` on non-test builds rather than a
/// wider public API surface the step never asked for -- see the lane
/// plan's Deviations log for the rejected alternative (making this fully
/// `pub`, which was reverted).
#[cfg_attr(not(test), allow(dead_code))]
pub(crate) fn dump_sqlite_master(conn: &Connection) -> Result<String> {
    let mut stmt =
        conn.prepare("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name")?;
    let rows = stmt.query_map([], |row| {
        let kind: String = row.get(0)?;
        let name: String = row.get(1)?;
        let tbl_name: String = row.get(2)?;
        let sql: Option<String> = row.get(3)?;
        Ok((kind, name, tbl_name, sql))
    })?;

    let mut out = String::new();
    for row in rows {
        let (kind, name, tbl_name, sql) = row?;
        let sql = sql.unwrap_or_default().replace('\n', "\\n");
        writeln!(out, "{kind}\t{name}\t{tbl_name}\t{sql}")
            .expect("writing to a String cannot fail");
    }
    Ok(out)
}

fn schema_versions_exists(conn: &Connection) -> Result<bool> {
    let exists: bool = conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_versions')",
        [],
        |row| row.get(0),
    )?;
    Ok(exists)
}

fn known_versions(conn: &Connection) -> Result<HashSet<u32>> {
    if !schema_versions_exists(conn)? {
        return Ok(HashSet::new());
    }
    let mut stmt = conn.prepare("SELECT version FROM schema_versions")?;
    let rows = stmt.query_map([], |row| row.get::<_, i64>(0))?;
    let mut set = HashSet::new();
    for row in rows {
        let version = row?;
        set.insert(
            u32::try_from(version).map_err(|_| {
                Error::unknown(format!("negative schema_versions.version: {version}"))
            })?,
        );
    }
    Ok(set)
}

fn record_version(conn: &Connection, version: u32, checksum: String) -> Result<()> {
    let applied_at = i64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0),
    )
    .unwrap_or(i64::MAX);
    conn.execute(
        "INSERT OR IGNORE INTO schema_versions (version, applied_at, checksum) VALUES (?1, ?2, ?3)",
        params![i64::from(version), applied_at, checksum],
    )?;
    Ok(())
}

/// A lowercase hex sha256 digest of `bytes`, matching
/// `services/cli/shepherd_cli/commands/migrate.py`'s
/// `hashlib.sha256(sql_text.encode("utf-8")).hexdigest()`. Not asserted
/// against `sqlite_master` (row DATA never appears there, only DDL text),
/// but the Python ORM mirror (`models.py`: `checksum =
/// fields.CharField(max_length=64)`) pins the column to a real sha256 hex
/// digest's length, so this computes a real one rather than a cheaper
/// non-cryptographic stand-in.
fn checksum_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut out = String::with_capacity(digest.len() * 2);
    for byte in digest.as_slice() {
        write!(out, "{byte:02x}").expect("writing to a String cannot fail");
    }
    out
}
