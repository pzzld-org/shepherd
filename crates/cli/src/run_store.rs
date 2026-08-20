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
            let bytes = std::fs::read(&self.path)
                .map_err(|source| RunStoreError::io("read state", &self.path, source))?;
            let state = decode_compatible(&bytes, &self.path)?;
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
            let bytes = std::fs::read(&self.path)
                .map_err(|source| RunStoreError::io("read state", &self.path, source))?;
            let mut state = decode_compatible(&bytes, &self.path)?;
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
            validate_lane_id(&lane.id)?;
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

fn decode_compatible(bytes: &[u8], path: &Path) -> RunStoreResult<RunState> {
    let mut document: serde_json::Value = serde_json::from_slice(bytes)
        .map_err(|error| RunStoreError::Validation(format!("{}: {error}", path.display())))?;
    normalize_legacy_run_document(&mut document, path)?;
    serde_json::from_value(document)
        .map_err(|error| RunStoreError::Validation(format!("{}: {error}", path.display())))
}

/// Normalize the pre-v1 map-shaped run document without discarding unknown
/// top-level or lane fields. Canonical bytes are written only after a caller
/// performs a legitimate locked mutation.
fn normalize_legacy_run_document(
    document: &mut serde_json::Value,
    path: &Path,
) -> RunStoreResult<()> {
    let object = document.as_object_mut().ok_or_else(|| {
        RunStoreError::Validation(format!(
            "{}: run document must be a JSON object",
            path.display()
        ))
    })?;

    let canonical_run = object.get("run").cloned();
    let legacy_run = object.remove("run_id");
    match (canonical_run, legacy_run) {
        (None, Some(value)) => {
            object.insert("run".into(), value);
        }
        (Some(canonical), Some(legacy)) if canonical != legacy => {
            return Err(RunStoreError::Validation(format!(
                "{}: conflicting `run` and legacy `run_id` values",
                path.display()
            )));
        }
        _ => {}
    }

    let Some(lanes) = object.get_mut("lanes") else {
        return Ok(());
    };
    if !lanes.is_object() {
        return Ok(());
    }
    let serde_json::Value::Object(legacy_lanes) = std::mem::take(lanes) else {
        unreachable!("object shape checked above")
    };
    let mut rows: Vec<_> = legacy_lanes.into_iter().collect();
    rows.sort_by(|left, right| left.0.cmp(&right.0));
    let mut normalized = Vec::with_capacity(rows.len());

    for (lane_key, mut value) in rows {
        let lane = value.as_object_mut().ok_or_else(|| {
            RunStoreError::Validation(format!(
                "{}: legacy lane `{lane_key}` must be a JSON object",
                path.display()
            ))
        })?;
        match lane.get("id") {
            None => {
                lane.insert("id".into(), serde_json::Value::String(lane_key.clone()));
            }
            Some(serde_json::Value::String(id)) if id == &lane_key => {}
            Some(serde_json::Value::String(id)) => {
                return Err(RunStoreError::Validation(format!(
                    "{}: legacy lane key `{lane_key}` conflicts with embedded id `{id}`",
                    path.display()
                )));
            }
            Some(_) => {
                return Err(RunStoreError::Validation(format!(
                    "{}: legacy lane `{lane_key}` has a non-string id",
                    path.display()
                )));
            }
        }

        if let Some(status_value) = lane.remove("status") {
            let status = status_value.as_str().ok_or_else(|| {
                RunStoreError::Validation(format!(
                    "{}: legacy lane `{lane_key}` has a non-string status",
                    path.display()
                ))
            })?;
            let mapped = legacy_lane_state(status);
            match lane.get("state") {
                None => {
                    lane.insert("state".into(), serde_json::Value::String(mapped.into()));
                }
                Some(serde_json::Value::String(state)) if state == mapped => {}
                Some(serde_json::Value::String(state)) => {
                    return Err(RunStoreError::Validation(format!(
                        "{}: legacy lane `{lane_key}` status `{status}` conflicts with state `{state}`",
                        path.display()
                    )));
                }
                Some(_) => {
                    return Err(RunStoreError::Validation(format!(
                        "{}: legacy lane `{lane_key}` has a non-string state",
                        path.display()
                    )));
                }
            }
        }
        normalized.push(value);
    }
    *lanes = serde_json::Value::Array(normalized);
    Ok(())
}

fn legacy_lane_state(status: &str) -> &str {
    match status {
        "passed" | "pass" | "completed" | "done" => "complete",
        "failed" | "failure" | "fail" => "error",
        "running" | "active" | "executing" | "in_progress" => "in-progress",
        "blocked" | "queued" | "not_started" => "pending",
        other => other,
    }
}

/// Legacy orchestration lane ids used upper-case phase labels. They remain
/// path-safe, while new lane creation continues to use the stricter canonical
/// lower-case validator in the command surface.
fn validate_lane_id(value: &str) -> RunStoreResult<()> {
    let bytes = value.as_bytes();
    let valid = (1..=64).contains(&bytes.len()) && bytes[0].is_ascii_alphanumeric();
    let valid = valid
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || *byte == b'-');
    if valid {
        Ok(())
    } else {
        Err(RunStoreError::Validation(format!(
            "unsafe lane id `{value}`"
        )))
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
                Err(error) => return Err(errno_path(store, "open state directory", seen, error)),
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
        decode_compatible(&read_regular(store, parent, "run.json")?, &store.path)
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
        errno_path(store, op, store.path.clone(), error)
    }

    /// Render one `rustix` errno as a [`RunStoreError`].
    ///
    /// `ENOENT` here always means the same thing: the run this [`RunStore`]
    /// is bound to does not exist (issue #331). It does not matter which of
    /// the fourteen call sites first noticed -- a missing run directory, a
    /// missing lock file, a missing `run.json` all fail the same ENOENT way
    /// once the run itself is gone -- so every `ENOENT` collapses to one
    /// operator-facing sentence naming the run and the command that lists
    /// the runs that DO exist, instead of a raw errno. The run id is read
    /// from `store.path`'s own parent directory name rather than from
    /// `path`, because `path` is wherever the directory walk happened to
    /// fail -- which can be an ancestor of the run directory (for example a
    /// missing `runs/` itself) and would otherwise name the wrong thing as
    /// "the run".
    ///
    /// `wave_b2_run.rs`'s own `load`/`update` helpers already special-case
    /// `RunStoreError::Io { source, .. }` on `source.kind() ==
    /// ErrorKind::NotFound` to build their own "no such run" message, so
    /// this keeps constructing the same `Io` variant with the same
    /// `ErrorKind::NotFound` -- only the message text changes here, never
    /// the shape that caller matches on.
    ///
    /// Every other errno -- `EACCES`, `EIO`, a path that exists but is not a
    /// regular file, and so on -- is a real filesystem fault, not a missing
    /// run, and pointing the operator at `shepherd run list` there would be
    /// actively misleading. Those keep the original operation/path/OS-error
    /// rendering, unchanged.
    fn errno_path(
        store: &RunStore,
        op: &'static str,
        path: PathBuf,
        error: rustix::io::Errno,
    ) -> RunStoreError {
        if error == rustix::io::Errno::NOENT {
            let run = store
                .path
                .parent()
                .and_then(Path::file_name)
                .and_then(|name| name.to_str())
                .unwrap_or("<unknown>");
            return RunStoreError::io(
                "run lookup",
                &path,
                std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    format!("no such run `{run}` — list existing runs with `shepherd run list`"),
                ),
            );
        }
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

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::fs;

    /// A private, per-test temp directory that already exists and is fully
    /// canonicalized (no symlink components anywhere in it -- on macOS
    /// `std::env::temp_dir()` lives under `/var`, which is itself a symlink
    /// to `/private/var`, and this module's `NOFOLLOW`-guarded traversal
    /// correctly rejects a symlinked ancestor as a real fault rather than
    /// treating it as ENOENT). Only `root` itself is created; a `dummy`
    /// child directory joined onto the returned path stays genuinely
    /// missing, giving a clean ENOENT one level below a symlink-free root.
    fn scratch_dir(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "shepherd-run-store-test-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after epoch")
                .as_nanos()
        ));
        fs::create_dir_all(&root).expect("create fixture root");
        fs::canonicalize(root).expect("canonicalize fixture root")
    }

    /// #331 regression: a run that was never created must fail to load with
    /// an operator-facing "no such run" diagnostic naming the run and
    /// `shepherd run list`, never a bare `os error N`.
    #[test]
    fn missing_run_reports_no_such_run_without_a_bare_errno() {
        let root = scratch_dir("missing-run");
        // `root` exists and is canonical; `root/dummy` is deliberately never
        // created, so the run directory itself is ENOENT -- the exact
        // `shepherd ready --run dummy` repro.
        let store = RunStore::new(root.join("dummy").join("run.json"));
        let error = store
            .load()
            .expect_err("a run directory that was never created must fail to load");
        let message = error.to_string();
        assert!(
            !message.contains("os error"),
            "message must not leak a bare errno: {message}"
        );
        assert!(
            message.contains("shepherd run list"),
            "message must point at the discovery command: {message}"
        );
        assert!(
            message.contains("dummy"),
            "message must name the missing run: {message}"
        );
        match error {
            RunStoreError::Io { source, .. } => {
                assert_eq!(
                    source.kind(),
                    std::io::ErrorKind::NotFound,
                    "wave_b2_run.rs's own no-such-run handling matches on this exact kind"
                );
            }
            other => panic!("expected RunStoreError::Io, got {other:?}"),
        }
        fs::remove_dir_all(&root).expect("remove fixture");
    }

    /// The same #331 diagnostic must apply when the run's own directory
    /// exists but `run.json` inside it does not (a distinct call site from
    /// the one above: this ENOENT surfaces from `read_regular`'s "open
    /// state" `openat`, not from `parent`'s "open state directory" walk).
    /// Confirms the fix lives in the shared helper, not in one call site.
    #[test]
    fn run_json_missing_inside_an_existing_run_directory_is_still_no_such_run() {
        let root = scratch_dir("missing-run-json");
        // The run directory itself exists; only `run.json` is absent.
        fs::create_dir_all(root.join("dummy")).expect("create run directory");
        let store = RunStore::new(root.join("dummy").join("run.json"));
        let error = store
            .load()
            .expect_err("an existing run directory with no run.json must fail to load");
        let message = error.to_string();
        assert!(
            !message.contains("os error"),
            "message must not leak a bare errno: {message}"
        );
        assert!(
            message.contains("shepherd run list"),
            "message must point at the discovery command: {message}"
        );
        fs::remove_dir_all(&root).expect("remove fixture");
    }

    /// A real filesystem fault -- here, the run's own directory slot is
    /// occupied by a plain file, so opening it as a directory fails with
    /// `ENOTDIR`, not `ENOENT` -- must not be relabeled "no such run". That
    /// would send an operator chasing `shepherd run list` for a problem
    /// `run list` cannot show or fix.
    #[test]
    fn real_fault_is_not_relabeled_no_such_run() {
        let root = scratch_dir("real-fault");
        // "dummy" exists, but as a file, not a directory.
        fs::write(root.join("dummy"), b"not a directory").expect("create blocking file");
        let store = RunStore::new(root.join("dummy").join("run.json"));
        let error = store
            .load()
            .expect_err("a run slot occupied by a file must fail to load");
        let message = error.to_string();
        assert!(
            !message.contains("shepherd run list"),
            "a real fault must not be told apart as a missing run: {message}"
        );
        fs::remove_dir_all(&root).expect("remove fixture");
    }
}
