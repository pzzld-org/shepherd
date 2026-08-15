/*
    Appellation: registry <module>
    Created At: 2026.08.14
    Contrib: @FL03
*/
//! Typed ownership boundary around one Shepherd SQLite registry.

use std::path::{Path, PathBuf};
use std::time::Duration;

use rusqlite::{Connection, OpenFlags, Params, Row, Transaction};

use crate::error::{Error, Result};

/// The filesystem and mutation posture used when opening a registry.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum OpenMode {
    /// Open an existing database and reject every mutation before execution.
    ReadOnly,
    /// Open an existing database for reads and writes, never creating it.
    ReadWrite,
    /// Open a database for reads and writes, creating it when absent.
    ReadWriteCreate,
}

impl OpenMode {
    const fn flags(self) -> OpenFlags {
        let access = match self {
            Self::ReadOnly => OpenFlags::SQLITE_OPEN_READ_ONLY,
            Self::ReadWrite => OpenFlags::SQLITE_OPEN_READ_WRITE,
            Self::ReadWriteCreate => {
                OpenFlags::SQLITE_OPEN_READ_WRITE.union(OpenFlags::SQLITE_OPEN_CREATE)
            }
        };
        access.union(OpenFlags::SQLITE_OPEN_NOFOLLOW)
    }

    const fn can_write(self) -> bool {
        !matches!(self, Self::ReadOnly)
    }
}

/// An opened Shepherd registry with an explicit read/write posture.
#[derive(Debug)]
pub struct Registry {
    connection: Connection,
    mode: OpenMode,
    path: PathBuf,
}

impl Registry {
    /// SQLite lock contention is bounded, never an unbounded hook or CLI hang.
    pub const DEFAULT_BUSY_TIMEOUT: Duration = Duration::from_secs(5);

    /// Open `path` with the requested creation and mutation posture.
    pub fn open(path: impl AsRef<Path>, mode: OpenMode) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        let open_path = safe_open_path(&path)?;
        let connection = Connection::open_with_flags(&open_path, mode.flags())?;
        connection.busy_timeout(Self::DEFAULT_BUSY_TIMEOUT)?;
        connection.execute_batch("PRAGMA foreign_keys = ON;")?;
        if !mode.can_write() {
            connection.execute_batch("PRAGMA query_only = ON;")?;
        }
        Ok(Self {
            connection,
            mode,
            path,
        })
    }

    /// Open a writable registry, create it when absent, and apply every schema migration.
    pub fn open_migrated(path: impl AsRef<Path>) -> Result<Self> {
        let registry = Self::open(path, OpenMode::ReadWriteCreate)?;
        registry.apply_migrations()?;
        Ok(registry)
    }

    /// The exact path passed to [`Self::open`].
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// The immutable open posture for this handle.
    pub const fn mode(&self) -> OpenMode {
        self.mode
    }

    /// Apply every embedded migration and return the resulting schema version.
    pub fn apply_migrations(&self) -> Result<u32> {
        self.require_write()?;
        crate::migrate::apply_all(&self.connection)
    }

    /// Return the greatest recorded schema version.
    pub fn schema_version(&self) -> Result<u32> {
        let version: i64 = self.connection.query_row(
            "SELECT COALESCE(MAX(version), 0) FROM schema_versions",
            [],
            |row| row.get(0),
        )?;
        u32::try_from(version)
            .map_err(|_| Error::unknown(format!("schema_versions.version out of range: {version}")))
    }

    /// Execute one parameterized mutating statement.
    pub fn execute<P>(&self, sql: &str, params: P) -> Result<usize>
    where
        P: Params,
    {
        self.require_write()?;
        Ok(self.connection.execute(sql, params)?)
    }

    /// Decode every row returned by a parameterized query.
    pub fn query<T, P, F>(&self, sql: &str, params: P, mut decode: F) -> Result<Vec<T>>
    where
        P: Params,
        F: FnMut(&Row<'_>) -> rusqlite::Result<T>,
    {
        let mut statement = self.connection.prepare(sql)?;
        let rows = statement.query_map(params, |row| decode(row))?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Decode exactly one row returned by a parameterized query.
    pub fn query_one<T, P, F>(&self, sql: &str, params: P, decode: F) -> Result<T>
    where
        P: Params,
        F: FnOnce(&Row<'_>) -> rusqlite::Result<T>,
    {
        Ok(self.connection.query_row(sql, params, decode)?)
    }

    /// Run `body` inside one explicit transaction.
    pub fn transaction<T, F>(&mut self, body: F) -> Result<T>
    where
        F: FnOnce(&RegistryTransaction<'_>) -> Result<T>,
    {
        self.require_write()?;
        let transaction = self.connection.transaction()?;
        let result = {
            let wrapped = RegistryTransaction {
                transaction: &transaction,
            };
            body(&wrapped)
        };

        match result {
            Ok(value) => {
                transaction.commit()?;
                Ok(value)
            }
            Err(cause) => match transaction.rollback() {
                Ok(()) => Err(cause),
                Err(rollback) => Err(Error::TransactionRollback {
                    cause: cause.to_string(),
                    rollback: rollback.to_string(),
                }),
            },
        }
    }

    fn require_write(&self) -> Result<()> {
        if self.mode.can_write() {
            Ok(())
        } else {
            Err(Error::ReadOnly)
        }
    }
}

fn safe_open_path(path: &Path) -> Result<PathBuf> {
    let file_name = path.file_name().ok_or_else(|| {
        Error::UnsafePath(format!(
            "registry path has no file name: {}",
            path.display()
        ))
    })?;
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let parent = std::fs::canonicalize(parent).map_err(|source| {
        Error::UnsafePath(format!(
            "cannot resolve registry parent {}: {source}",
            parent.display()
        ))
    })?;
    let resolved = parent.join(file_name);
    match std::fs::symlink_metadata(&resolved) {
        Ok(metadata) if metadata.file_type().is_symlink() => Err(Error::UnsafePath(format!(
            "symbolic-link database target {}",
            path.display()
        ))),
        Ok(_) => Ok(resolved),
        Err(source) if source.kind() == std::io::ErrorKind::NotFound => Ok(resolved),
        Err(source) => Err(Error::UnsafePath(format!(
            "cannot inspect registry target {}: {source}",
            path.display()
        ))),
    }
}

/// The bounded query and mutation surface available inside a transaction.
#[derive(Debug)]
pub struct RegistryTransaction<'connection> {
    transaction: &'connection Transaction<'connection>,
}

impl RegistryTransaction<'_> {
    /// Execute one parameterized statement in this transaction.
    pub fn execute<P>(&self, sql: &str, params: P) -> Result<usize>
    where
        P: Params,
    {
        Ok(self.transaction.execute(sql, params)?)
    }

    /// Decode every row returned by a parameterized query in this transaction.
    pub fn query<T, P, F>(&self, sql: &str, params: P, mut decode: F) -> Result<Vec<T>>
    where
        P: Params,
        F: FnMut(&Row<'_>) -> rusqlite::Result<T>,
    {
        let mut statement = self.transaction.prepare(sql)?;
        let rows = statement.query_map(params, |row| decode(row))?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Decode exactly one row returned by a parameterized query in this transaction.
    pub fn query_one<T, P, F>(&self, sql: &str, params: P, decode: F) -> Result<T>
    where
        P: Params,
        F: FnOnce(&Row<'_>) -> rusqlite::Result<T>,
    {
        Ok(self.transaction.query_row(sql, params, decode)?)
    }
}
