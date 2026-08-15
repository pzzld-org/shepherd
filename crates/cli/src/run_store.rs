/*
    Appellation: run_store <module>
    Created At: 2026.08.14
    Contrib: @FL03
*/
//! Serialized `run.json` read-modify-write ownership for every CLI command.

use std::collections::BTreeSet;
#[cfg(not(unix))]
use std::fs::OpenOptions;
use std::fs::{File, TryLockError};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use shepherd::RunState;

/// The result type returned by [`RunStore`].
pub type RunStoreResult<T = ()> = core::result::Result<T, RunStoreError>;

/// Failures at the run-state serialization boundary.
#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum RunStoreError {
    /// The engine could not decode or atomically encode `run.json`.
    #[error(transparent)]
    Engine(#[from] shepherd::Error),
    /// A filesystem operation outside the engine failed.
    #[error("{operation} {}: {source}", path.display())]
    Io {
        operation: &'static str,
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    /// The sidecar lock remained held beyond the configured deadline.
    #[error("timed out after {timeout:?} waiting for run lock {}", path.display())]
    LockTimeout { path: PathBuf, timeout: Duration },
    /// A caller attempted to initialize a run that already exists.
    #[error("run state already exists: {}", .0.display())]
    AlreadyExists(PathBuf),
    /// A run or lane violated the canonical writable-state contract.
    #[error("invalid run state: {0}")]
    Validation(String),
    /// A newer schema may be read by another implementation but never overwritten.
    #[error("run schema version {0} is newer than this binary supports")]
    SchemaAhead(u32),
    /// A caller-supplied mutation refused its own operation.
    #[error("{0}")]
    Mutation(String),
}

impl RunStoreError {
    /// Build a typed mutation refusal without collapsing it into an I/O failure.
    pub fn mutation(message: impl Into<String>) -> Self {
        Self::Mutation(message.into())
    }

    fn io(operation: &'static str, path: &Path, source: std::io::Error) -> Self {
        Self::Io {
            operation,
            path: path.to_path_buf(),
            source,
        }
    }
}

/// One run's canonical state file plus its persistent advisory lock file.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct RunStore {
    path: PathBuf,
    lock_path: PathBuf,
    timeout: Duration,
}

impl RunStore {
    /// Maximum lock wait for ordinary CLI operations.
    pub const DEFAULT_LOCK_TIMEOUT: Duration = Duration::from_secs(5);
    const LOCK_RETRY_INTERVAL: Duration = Duration::from_millis(10);
    const SCHEMA_VERSION: u32 = 1;

    /// Bind a store to one canonical `runs/<run>/run.json` path.
    pub fn new(path: impl AsRef<Path>) -> Self {
        Self::with_timeout(path, Self::DEFAULT_LOCK_TIMEOUT)
    }

    /// Bind a store with an explicit, testable lock deadline.
    pub fn with_timeout(path: impl AsRef<Path>, timeout: Duration) -> Self {
        let path = path.as_ref().to_path_buf();
        let lock_path = path.with_file_name("run.lock");
        Self {
            path,
            lock_path,
            timeout,
        }
    }

    /// The canonical `run.json` path.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// The persistent sidecar lock path.
    pub fn lock_path(&self) -> &Path {
        &self.lock_path
    }

    /// Create a new state document under an exclusive lock, refusing clobber.
    pub fn initialize(&self, state: &RunState) -> RunStoreResult<()> {
        #[cfg(unix)]
        return platform::initialize(self, state);
        #[cfg(not(unix))]
        {
            self.validate_writable(state)?;
            let _lock = self.acquire(LockMode::Exclusive, true)?;
            if self.path.exists() {
                return Err(RunStoreError::AlreadyExists(self.path.clone()));
            }
            state.store(&self.path)?;
            Ok(())
        }
    }

    /// Load one complete state document under a shared lock.
    pub fn load(&self) -> RunStoreResult<RunState> {
        #[cfg(unix)]
        return platform::load(self);
        #[cfg(not(unix))]
        {
            self.ensure_state_file()?;
            let _lock = self.acquire(LockMode::Shared, false)?;
            let state = RunState::load(&self.path)?;
            self.validate_readable(&state)?;
            Ok(state)
        }
    }

    /// Hold one exclusive lock across load, caller mutation, validation, and atomic store.
    pub fn update<T, F>(&self, mutate: F) -> RunStoreResult<T>
    where
        F: FnOnce(&mut RunState) -> RunStoreResult<T>,
    {
        #[cfg(unix)]
        return platform::update(self, mutate);
        #[cfg(not(unix))]
        {
            self.ensure_state_file()?;
            let _lock = self.acquire(LockMode::Exclusive, false)?;
            let mut state = RunState::load(&self.path)?;
            self.validate_writable(&state)?;
            let value = mutate(&mut state)?;
            self.validate_writable(&state)?;
            state.store(&self.path)?;
            Ok(value)
        }
    }

    /// Rewrite a legacy document while holding the same exclusive run lock as
    /// ordinary mutations.
    ///
    /// The transformer receives the exact current bytes because a migration
    /// may need to repair a shape that [`RunState`] cannot decode yet. Its
    /// returned state is still validated and published through the canonical
    /// atomic writer, so this escape hatch does not weaken the writable-state
    /// contract.
    pub fn rewrite_from_raw<T, F>(&self, transform: F) -> RunStoreResult<T>
    where
        F: FnOnce(&[u8]) -> RunStoreResult<(RunState, T)>,
    {
        #[cfg(unix)]
        return platform::rewrite_from_raw(self, transform);
        #[cfg(not(unix))]
        {
            self.ensure_state_file()?;
            let _lock = self.acquire(LockMode::Exclusive, false)?;
            let bytes = std::fs::read(&self.path)
                .map_err(|source| RunStoreError::io("read state", &self.path, source))?;
            let (state, value) = transform(&bytes)?;
            self.validate_writable(&state)?;
            state.store(&self.path)?;
            Ok(value)
        }
    }

    #[cfg(not(unix))]
    fn ensure_state_file(&self) -> RunStoreResult<()> {
        match std::fs::metadata(&self.path) {
            Ok(metadata) if metadata.is_file() => Ok(()),
            Ok(_) => Err(RunStoreError::io(
                "open state",
                &self.path,
                std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "run state path is not a regular file",
                ),
            )),
            Err(source) => Err(RunStoreError::io("open state", &self.path, source)),
        }
    }

    #[cfg(not(unix))]
    fn acquire(&self, mode: LockMode, create_parent: bool) -> RunStoreResult<RunLock> {
        let parent = self.lock_path.parent().ok_or_else(|| {
            RunStoreError::Validation(format!(
                "lock path has no parent: {}",
                self.lock_path.display()
            ))
        })?;
        if create_parent {
            std::fs::create_dir_all(parent)
                .map_err(|source| RunStoreError::io("create directory", parent, source))?;
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&self.lock_path)
            .map_err(|source| RunStoreError::io("open lock", &self.lock_path, source))?;

        let started = Instant::now();
        loop {
            let attempt = match mode {
                LockMode::Exclusive => file.try_lock(),
                LockMode::Shared => file.try_lock_shared(),
            };
            match attempt {
                Ok(()) => return Ok(RunLock { file }),
                Err(TryLockError::WouldBlock) if started.elapsed() < self.timeout => {
                    let remaining = self.timeout.saturating_sub(started.elapsed());
                    std::thread::sleep(Self::LOCK_RETRY_INTERVAL.min(remaining));
                }
                Err(TryLockError::WouldBlock) => {
                    return Err(RunStoreError::LockTimeout {
                        path: self.lock_path.clone(),
                        timeout: self.timeout,
                    });
                }
                Err(TryLockError::Error(source)) => {
                    return Err(RunStoreError::io("acquire lock", &self.lock_path, source));
                }
            }
        }
    }

    fn validate_readable(&self, state: &RunState) -> RunStoreResult<()> {
        self.validate_identity(state)?;
        if state.schema_version <= Self::SCHEMA_VERSION {
            self.validate_current_vocabulary(state)?;
        }
        Ok(())
    }

    fn validate_writable(&self, state: &RunState) -> RunStoreResult<()> {
        self.validate_identity(state)?;
        if state.schema_version > Self::SCHEMA_VERSION {
            return Err(RunStoreError::SchemaAhead(state.schema_version));
        }
        self.validate_current_vocabulary(state)
    }

    fn validate_identity(&self, state: &RunState) -> RunStoreResult<()> {
        let file_name = self.path.file_name().and_then(|name| name.to_str());
        if file_name != Some("run.json") {
            return Err(RunStoreError::Validation(format!(
                "state path must end in run.json: {}",
                self.path.display()
            )));
        }
        let expected_run = self
            .path
            .parent()
            .and_then(Path::file_name)
            .and_then(|name| name.to_str())
            .ok_or_else(|| {
                RunStoreError::Validation(format!(
                    "state path has no UTF-8 run directory: {}",
                    self.path.display()
                ))
            })?;
        validate_id("run", expected_run)?;
        if state.run != expected_run {
            return Err(RunStoreError::Validation(format!(
                "document run `{}` does not match directory `{expected_run}`",
                state.run
            )));
        }
        if state.schema_version == 0 {
            return Err(RunStoreError::Validation(
                "schema_version must be at least 1".into(),
            ));
        }

        let mut lane_ids = BTreeSet::new();
        for lane in &state.lanes {
            validate_id("lane", &lane.id)?;
            if !lane_ids.insert(&lane.id) {
                return Err(RunStoreError::Validation(format!(
                    "duplicate lane id `{}`",
                    lane.id
                )));
            }
        }
        Ok(())
    }

    fn validate_current_vocabulary(&self, state: &RunState) -> RunStoreResult<()> {
        if !matches!(
            state.status.as_str(),
            "planted" | "planned" | "executing" | "closing" | "closed"
        ) {
            return Err(RunStoreError::Validation(format!(
                "unknown run status `{}`",
                state.status
            )));
        }
        for lane in &state.lanes {
            if !matches!(
                lane.state.as_str(),
                "pending" | "in-progress" | "complete" | "error"
            ) {
                return Err(RunStoreError::Validation(format!(
                    "unknown state `{}` for lane `{}`",
                    lane.state, lane.id
                )));
            }
        }
        Ok(())
    }
}

fn validate_id(kind: &str, value: &str) -> RunStoreResult<()> {
    let bytes = value.as_bytes();
    let valid = (1..=64).contains(&bytes.len())
        && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit());
    let valid = valid
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'-');
    if valid {
        Ok(())
    } else {
        Err(RunStoreError::Validation(format!(
            "unsafe {kind} id `{value}`"
        )))
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[cfg(not(unix))]
enum LockMode {
    Exclusive,
    Shared,
}

#[derive(Debug)]
struct RunLock {
    file: File,
}

#[cfg(unix)]
mod platform {
    use std::io::{Read, Write};
    use std::os::fd::OwnedFd;
    use std::sync::atomic::{AtomicU64, Ordering};

    use rustix::fs::{self, AtFlags, FileType, Mode, OFlags, open, openat, renameat, unlinkat};

    use super::*;

    static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

    pub(super) fn initialize(store: &RunStore, state: &RunState) -> RunStoreResult<()> {
        store.validate_writable(state)?;
        let parent = parent(store, true)?;
        let _lock = lock(store, &parent)?;
        if fs::statat(&parent, "run.json", AtFlags::SYMLINK_NOFOLLOW).is_ok() {
            return Err(RunStoreError::AlreadyExists(store.path.clone()));
        }
        write_state(store, &parent, state, false)
    }

    pub(super) fn load(store: &RunStore) -> RunStoreResult<RunState> {
        let parent = parent(store, false)?;
        let _lock = lock(store, &parent)?;
        let state = decode(store, &parent)?;
        store.validate_readable(&state)?;
        Ok(state)
    }

    pub(super) fn update<T, F>(store: &RunStore, mutate: F) -> RunStoreResult<T>
    where
        F: FnOnce(&mut RunState) -> RunStoreResult<T>,
    {
        let parent = parent(store, false)?;
        let _lock = lock(store, &parent)?;
        let mut state = decode(store, &parent)?;
        store.validate_writable(&state)?;
        let value = mutate(&mut state)?;
        store.validate_writable(&state)?;
        write_state(store, &parent, &state, true)?;
        Ok(value)
    }

    pub(super) fn rewrite_from_raw<T, F>(store: &RunStore, transform: F) -> RunStoreResult<T>
    where
        F: FnOnce(&[u8]) -> RunStoreResult<(RunState, T)>,
    {
        let parent = parent(store, false)?;
        let _lock = lock(store, &parent)?;
        let bytes = read_regular(store, &parent, "run.json")?;
        let (state, value) = transform(&bytes)?;
        store.validate_writable(&state)?;
        write_state(store, &parent, &state, true)?;
        Ok(value)
    }

    fn parent(store: &RunStore, create: bool) -> RunStoreResult<OwnedFd> {
        let parent = store
            .path
            .parent()
            .ok_or_else(|| RunStoreError::Validation("state path has no parent".into()))?;
        if !parent.is_absolute()
            || parent.components().any(|part| {
                matches!(
                    part,
                    std::path::Component::ParentDir | std::path::Component::CurDir
                )
            })
        {
            return Err(RunStoreError::Validation(format!(
                "unsafe state parent: {}",
                parent.display()
            )));
        }
        let mut fd = open(
            "/",
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| errno(store, "open filesystem root", error))?;
        let mut seen = PathBuf::from("/");
        for part in parent.components() {
            let std::path::Component::Normal(name) = part else {
                continue;
            };
            seen.push(name);
            fd = match openat(
                &fd,
                name,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::empty(),
            ) {
                Ok(fd) => fd,
                Err(rustix::io::Errno::NOENT) if create => {
                    rustix::fs::mkdirat(&fd, name, Mode::RWXU)
                        .map_err(|error| errno(store, "create state directory", error))?;
                    openat(
                        &fd,
                        name,
                        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                        Mode::empty(),
                    )
                    .map_err(|error| errno(store, "open state directory", error))?
                }
                Err(error) => return Err(errno_path("open state directory", seen, error)),
            };
        }
        Ok(fd)
    }

    fn lock(store: &RunStore, parent: &OwnedFd) -> RunStoreResult<RunLock> {
        let fd = openat(
            parent,
            "run.lock",
            OFlags::RDWR | OFlags::CREATE | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|error| errno(store, "open lock", error))?;
        let file = File::from(fd);
        let started = Instant::now();
        loop {
            match file.try_lock() {
                Ok(()) => return Ok(RunLock { file }),
                Err(TryLockError::WouldBlock) if started.elapsed() < store.timeout => {
                    std::thread::sleep(
                        RunStore::LOCK_RETRY_INTERVAL
                            .min(store.timeout.saturating_sub(started.elapsed())),
                    )
                }
                Err(TryLockError::WouldBlock) => {
                    return Err(RunStoreError::LockTimeout {
                        path: store.lock_path.clone(),
                        timeout: store.timeout,
                    });
                }
                Err(TryLockError::Error(error)) => {
                    return Err(RunStoreError::io("acquire lock", &store.lock_path, error));
                }
            }
        }
    }

    fn decode(store: &RunStore, parent: &OwnedFd) -> RunStoreResult<RunState> {
        serde_json::from_slice(&read_regular(store, parent, "run.json")?).map_err(|error| {
            RunStoreError::Validation(format!("{}: {error}", store.path.display()))
        })
    }
    fn read_regular(store: &RunStore, parent: &OwnedFd, name: &str) -> RunStoreResult<Vec<u8>> {
        let fd = openat(
            parent,
            name,
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| errno(store, "open state", error))?;
        let stat = fs::fstat(&fd).map_err(|error| errno(store, "inspect state", error))?;
        if !FileType::from_raw_mode(stat.st_mode).is_file() {
            return Err(RunStoreError::Validation(format!(
                "state is not a regular file: {}",
                store.path.display()
            )));
        }
        let mut bytes = Vec::new();
        File::from(fd)
            .read_to_end(&mut bytes)
            .map_err(|error| RunStoreError::io("read state", &store.path, error))?;
        Ok(bytes)
    }
    fn write_state(
        store: &RunStore,
        parent: &OwnedFd,
        state: &RunState,
        replace: bool,
    ) -> RunStoreResult<()> {
        let name = format!(
            ".run.json-{:x}.tmp",
            TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        );
        let fd = openat(
            parent,
            &name,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|error| errno(store, "create state temp", error))?;
        let mut file = File::from(fd);
        let result = (|| {
            file.write_all(state.to_canonical_json().as_bytes())
                .and_then(|_| file.write_all(b"\n"))
                .map_err(|error| RunStoreError::io("write state", &store.path, error))?;
            file.sync_all()
                .map_err(|error| RunStoreError::io("fsync state", &store.path, error))?;
            if !replace {
                rustix::fs::linkat(parent, &name, parent, "run.json", AtFlags::empty())
                    .map_err(|error| errno(store, "publish state", error))?;
                unlinkat(parent, &name, AtFlags::empty())
                    .map_err(|error| errno(store, "unlink state temp", error))?;
            } else {
                let stat = fs::statat(parent, "run.json", AtFlags::SYMLINK_NOFOLLOW)
                    .map_err(|error| errno(store, "inspect state", error))?;
                if !FileType::from_raw_mode(stat.st_mode).is_file() {
                    return Err(RunStoreError::Validation(format!(
                        "state is not a regular file: {}",
                        store.path.display()
                    )));
                }
                renameat(parent, &name, parent, "run.json")
                    .map_err(|error| errno(store, "replace state", error))?;
            }
            fs::fsync(parent).map_err(|error| errno(store, "fsync state directory", error))
        })();
        if result.is_err() {
            let _ = unlinkat(parent, &name, AtFlags::empty());
        }
        result
    }
    fn errno(store: &RunStore, op: &'static str, error: rustix::io::Errno) -> RunStoreError {
        errno_path(op, store.path.clone(), error)
    }
    fn errno_path(op: &'static str, path: PathBuf, error: rustix::io::Errno) -> RunStoreError {
        RunStoreError::io(
            op,
            &path,
            std::io::Error::from_raw_os_error(error.raw_os_error()),
        )
    }
}

impl Drop for RunLock {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}
