//! Primary-run dispatch persistence with descriptor-relative path confinement.

use std::path::{Path, PathBuf};
use std::time::Duration;

use std::time::Instant;

#[cfg(unix)]
use std::{
    fs::File,
    io::{Read, Write},
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};

use shepherd::dispatch::{
    AgentId, DispatchError, DispatchRecord, DispatchStart, IdentityError, IdentityResolution,
    NativeIdentity, RootSessionBinding, RunId, SessionId, StopRequest, resolve_native_identity,
};

use shepherd::RunState;

pub type DispatchStoreResult<T> = core::result::Result<T, DispatchStoreError>;

#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum DispatchStoreError {
    #[error("dispatch filesystem operation `{operation}` failed for {}: {source}", path.display())]
    Io {
        operation: &'static str,
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("unsafe dispatch path: {}", path.display())]
    UnsafePath { path: PathBuf },
    #[error("invalid run document {}: {reason}", path.display())]
    InvalidRunDocument { path: PathBuf, reason: String },
    #[error("no executing shepherd run exists")]
    NoActiveRun,
    #[error("multiple executing shepherd runs are ambiguous: {runs:?}")]
    AmbiguousActiveRuns { runs: Vec<RunId> },
    #[error("dispatch record already exists: {}", path.display())]
    AlreadyExists { path: PathBuf },
    #[error("dispatch record is {size} bytes; maximum is {max} bytes")]
    RecordTooLarge { size: usize, max: usize },
    #[error("dispatch record for `{agent_id}` is unknown in run `{run}`: {reason}")]
    UnknownRecord {
        run: RunId,
        agent_id: AgentId,
        reason: String,
    },
    #[error("event names run `{supplied}`, but primary active run is `{active}`")]
    WrongActiveRun { supplied: RunId, active: RunId },
    #[error("timed out after {timeout:?} waiting for dispatch lock {}", path.display())]
    LockTimeout { path: PathBuf, timeout: Duration },
    #[error(transparent)]
    Domain(#[from] DispatchError),
    #[error(transparent)]
    Identity(#[from] IdentityError),
}

impl DispatchStoreError {
    fn io(operation: &'static str, path: PathBuf, source: impl Into<std::io::Error>) -> Self {
        Self::Io {
            operation,
            path,
            source: source.into(),
        }
    }
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct DispatchStore {
    runs_root: PathBuf,
    timeout: Duration,
}

impl DispatchStore {
    pub const DEFAULT_LOCK_TIMEOUT: Duration = Duration::from_secs(5);

    pub fn new(primary_runs_root: impl AsRef<Path>) -> Self {
        Self::with_timeout(primary_runs_root, Self::DEFAULT_LOCK_TIMEOUT)
    }

    pub fn with_timeout(primary_runs_root: impl AsRef<Path>, timeout: Duration) -> Self {
        Self {
            runs_root: primary_runs_root.as_ref().to_path_buf(),
            timeout,
        }
    }

    #[must_use]
    pub fn runs_root(&self) -> &Path {
        &self.runs_root
    }

    pub fn resolve_active_run(&self) -> DispatchStoreResult<RunId> {
        resolve_active_run(self)
    }

    pub fn publish_active(&self, record: &DispatchRecord) -> DispatchStoreResult<()> {
        record.validate_loaded()?;
        let active = self.resolve_active_run()?;
        if record.run != active {
            return Err(DispatchStoreError::WrongActiveRun {
                supplied: record.run.clone(),
                active,
            });
        }
        platform::publish(self, record)
    }

    pub fn publish_root_binding(&self, binding: &RootSessionBinding) -> DispatchStoreResult<()> {
        binding.validate()?;
        let active = self.resolve_active_run()?;
        if binding.run != active {
            return Err(DispatchStoreError::WrongActiveRun {
                supplied: binding.run.clone(),
                active,
            });
        }
        platform::publish_root_binding(self, binding)
    }

    pub fn load_active_root_binding(
        &self,
        session_id: &SessionId,
    ) -> DispatchStoreResult<RootSessionBinding> {
        let active = self.resolve_active_run()?;
        platform::load_root_binding(self, &active, session_id)
    }

    pub fn load_active(&self, agent_id: &AgentId) -> DispatchStoreResult<DispatchRecord> {
        let active = self.resolve_active_run()?;
        platform::load(self, &active, agent_id)
    }

    pub fn resolve_active_identity(
        &self,
        native: &NativeIdentity,
    ) -> DispatchStoreResult<IdentityResolution> {
        self.resolve_active_identity_with_record(native)
            .map(|(resolution, _)| resolution)
    }

    pub(crate) fn resolve_active_identity_with_record(
        &self,
        native: &NativeIdentity,
    ) -> DispatchStoreResult<(IdentityResolution, Option<DispatchRecord>)> {
        let active = self.resolve_active_run()?;
        if native.run != active {
            return Err(DispatchStoreError::WrongActiveRun {
                supplied: native.run.clone(),
                active,
            });
        }
        let record = match &native.agent_id {
            Some(agent_id) => Some(platform::load(self, &active, agent_id)?),
            None => None,
        };
        let resolution = resolve_native_identity(record.as_ref(), native)?;
        Ok((resolution, record))
    }

    pub fn stop_active(&self, request: StopRequest) -> DispatchStoreResult<DispatchRecord> {
        let active = self.resolve_active_run()?;
        platform::stop(self, &active, request)
    }

    pub fn stop_active_verified(
        &self,
        native: &NativeIdentity,
        request: StopRequest,
    ) -> DispatchStoreResult<DispatchRecord> {
        let active = self.resolve_active_run()?;
        if native.run != active {
            return Err(DispatchStoreError::WrongActiveRun {
                supplied: native.run.clone(),
                active,
            });
        }
        platform::stop_verified(self, &native.run, native, request)
    }

    pub fn resume_active(
        &self,
        source_agent_id: &AgentId,
        input: DispatchStart,
    ) -> DispatchStoreResult<DispatchRecord> {
        let active = self.resolve_active_run()?;
        if input.run != active {
            return Err(DispatchStoreError::WrongActiveRun {
                supplied: input.run,
                active,
            });
        }
        platform::resume(self, &active, source_agent_id, input)
    }

    fn record_path(&self, run: &RunId, agent_id: &AgentId) -> PathBuf {
        self.runs_root
            .join(run.as_str())
            .join("dispatch")
            .join(format!("{}.json", agent_id.as_str()))
    }

    fn root_binding_path(&self, run: &RunId, session_id: &SessionId) -> PathBuf {
        self.runs_root
            .join(run.as_str())
            .join("dispatch")
            .join(root_binding_name(session_id))
    }
}

fn root_binding_name(session_id: &SessionId) -> String {
    format!(".root-session.{}.json", session_id.as_str())
}

/// Resolve the single `status == "executing"` run beneath the runs root.
///
/// Enumeration is deliberately tolerant of what it finds. `.shepherd/runs/`
/// accumulates directories that are not runs -- a legacy namespace holding
/// only `plan.md`, an empty tree, a scratch tree carrying `dispatch/` and no
/// `run.json` -- and that set is unbounded, so repairing one only reveals the
/// next. A namespace whose `run.json` is *absent* is therefore passed over
/// exactly as a name that does not parse as a `RunId` already is.
///
/// Absence is the only tolerated failure. A corrupt document still raises
/// `InvalidRunDocument` and a linked or non-regular one still raises
/// `UnsafePath`: swallowing those would trade a loud abort for a silent
/// `NoActiveRun` and delete the diagnosis, which is the same deadlock with
/// less to go on (#330).
///
/// Everything above the anchoring is platform-free and lives here once. The
/// `platform` twins contribute only `open_runs_root` and `read_run_document`.
fn resolve_active_run(store: &DispatchStore) -> DispatchStoreResult<RunId> {
    let root = platform::open_runs_root(store)?;
    let mut names = Vec::new();
    let entries = std::fs::read_dir(&store.runs_root).map_err(|source| {
        DispatchStoreError::io("read runs directory", store.runs_root.clone(), source)
    })?;
    for entry in entries {
        let entry = entry.map_err(|source| {
            DispatchStoreError::io("read runs directory", store.runs_root.clone(), source)
        })?;
        let name = entry.file_name();
        let name = name
            .to_str()
            .ok_or_else(|| DispatchStoreError::UnsafePath {
                path: store.runs_root.join("<non-utf8>"),
            })?;
        if name == "." || name == ".." {
            continue;
        }
        if let Ok(run) = RunId::new(name) {
            names.push(run);
        }
    }
    names.sort();
    names.dedup();

    let mut active = Vec::new();
    for run in names {
        let state = match platform::read_run_document(store, &root, &run) {
            Ok(state) => state,
            Err(error) if is_not_found(&error) => continue,
            Err(error) => return Err(error),
        };
        if state.status == "executing" {
            active.push(run);
        }
    }
    match active.len() {
        0 => Err(DispatchStoreError::NoActiveRun),
        1 => Ok(active.remove(0)),
        _ => Err(DispatchStoreError::AmbiguousActiveRuns { runs: active }),
    }
}

/// Whether `error` is the filesystem reporting that a name does not exist.
///
/// `unsafe_path_or_io` sends `ELOOP` and `ENOTDIR` to `UnsafePath`, so what
/// reaches `Io { NotFound }` really is "no such entry" and nothing else.
fn is_not_found(error: &DispatchStoreError) -> bool {
    matches!(
        error,
        DispatchStoreError::Io { source, .. }
            if source.kind() == std::io::ErrorKind::NotFound
    )
}

#[cfg(unix)]
mod platform {
    use std::fs::TryLockError;
    use std::os::fd::OwnedFd;

    use rustix::fs::{
        self, AtFlags, FileType, Mode, OFlags, linkat, mkdirat, open, openat, renameat, unlinkat,
    };

    use super::*;

    const MAX_RECORD_BYTES: u64 = 1_048_576;
    const LOCK_RETRY_INTERVAL: Duration = Duration::from_millis(10);
    const MAX_TEMP_ATTEMPTS: u32 = 100;
    static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

    pub(super) fn publish(
        store: &DispatchStore,
        record: &DispatchRecord,
    ) -> DispatchStoreResult<()> {
        let root = open_runs_root(store)?;
        let run_fd = open_run_dir(store, &root, &record.run)?;
        let dispatch_fd = open_dispatch_dir(store, &run_fd, &record.run, true)?;
        let _lock = acquire_lock(store, &dispatch_fd, &record.run)?;
        let name = record_name(&record.agent_id);
        let bytes = encode_record(record)?;
        publish_no_clobber(store, &dispatch_fd, &record.run, &name, &bytes)?;
        let loaded = read_record(store, &dispatch_fd, &record.run, &record.agent_id)?;
        if loaded != *record {
            return Err(unknown_record(
                &record.run,
                &record.agent_id,
                "published bytes did not round-trip",
            ));
        }
        Ok(())
    }

    pub(super) fn publish_root_binding(
        store: &DispatchStore,
        binding: &RootSessionBinding,
    ) -> DispatchStoreResult<()> {
        let root = open_runs_root(store)?;
        let run_fd = open_run_dir(store, &root, &binding.run)?;
        let dispatch_fd = open_dispatch_dir(store, &run_fd, &binding.run, true)?;
        let _lock = acquire_lock(store, &dispatch_fd, &binding.run)?;
        let name = root_binding_name(&binding.session_id);
        let bytes = encode_document(binding)?;
        publish_no_clobber(store, &dispatch_fd, &binding.run, &name, &bytes)
    }

    pub(super) fn load_root_binding(
        store: &DispatchStore,
        run: &RunId,
        session_id: &SessionId,
    ) -> DispatchStoreResult<RootSessionBinding> {
        let root = open_runs_root(store)?;
        let run_fd = open_run_dir(store, &root, run)?;
        let dispatch_fd = open_dispatch_dir(store, &run_fd, run, false)?;
        let _lock = acquire_lock(store, &dispatch_fd, run)?;
        let name = root_binding_name(session_id);
        let path = store.root_binding_path(run, session_id);
        let file = open_regular_at(&dispatch_fd, &name, &path)?;
        let bytes = read_bounded(file, MAX_RECORD_BYTES)
            .map_err(|source| DispatchStoreError::io("read root binding", path.clone(), source))?;
        let binding: RootSessionBinding = serde_json::from_slice(&bytes).map_err(|error| {
            DispatchStoreError::Domain(DispatchError::InvalidRecord(error.to_string()))
        })?;
        binding.validate()?;
        if &binding.run != run || &binding.session_id != session_id {
            return Err(DispatchStoreError::Domain(DispatchError::InvalidRecord(
                "root binding identity does not match its canonical path".into(),
            )));
        }
        Ok(binding)
    }

    pub(super) fn load(
        store: &DispatchStore,
        run: &RunId,
        agent_id: &AgentId,
    ) -> DispatchStoreResult<DispatchRecord> {
        let root = open_runs_root(store)?;
        let run_fd = open_run_dir(store, &root, run)?;
        let dispatch_fd = open_dispatch_dir(store, &run_fd, run, false).map_err(|error| {
            if is_not_found(&error) {
                unknown_record(run, agent_id, "dispatch directory is absent")
            } else {
                error
            }
        })?;
        let _lock = acquire_lock(store, &dispatch_fd, run)?;
        read_record(store, &dispatch_fd, run, agent_id)
    }

    pub(super) fn stop(
        store: &DispatchStore,
        run: &RunId,
        request: StopRequest,
    ) -> DispatchStoreResult<DispatchRecord> {
        let root = open_runs_root(store)?;
        let run_fd = open_run_dir(store, &root, run)?;
        let dispatch_fd = open_dispatch_dir(store, &run_fd, run, false)?;
        let _lock = acquire_lock(store, &dispatch_fd, run)?;
        let mut record = read_record(store, &dispatch_fd, run, &request.agent_id)?;
        record.stop(request)?;
        record.validate_loaded()?;
        replace_record(store, &dispatch_fd, run, &record)?;
        Ok(record)
    }

    pub(super) fn stop_verified(
        store: &DispatchStore,
        run: &RunId,
        native: &NativeIdentity,
        request: StopRequest,
    ) -> DispatchStoreResult<DispatchRecord> {
        let root = open_runs_root(store)?;
        let run_fd = open_run_dir(store, &root, run)?;
        let dispatch_fd = open_dispatch_dir(store, &run_fd, run, false)?;
        let _lock = acquire_lock(store, &dispatch_fd, run)?;
        let mut record = read_record(store, &dispatch_fd, run, &request.agent_id)?;
        resolve_native_identity(Some(&record), native)?;
        record.stop(request)?;
        record.validate_loaded()?;
        replace_record(store, &dispatch_fd, run, &record)?;
        Ok(record)
    }

    pub(super) fn resume(
        store: &DispatchStore,
        run: &RunId,
        source_agent_id: &AgentId,
        input: DispatchStart,
    ) -> DispatchStoreResult<DispatchRecord> {
        let root = open_runs_root(store)?;
        let run_fd = open_run_dir(store, &root, run)?;
        let dispatch_fd = open_dispatch_dir(store, &run_fd, run, false)?;
        let _lock = acquire_lock(store, &dispatch_fd, run)?;
        let source = read_record(store, &dispatch_fd, run, source_agent_id)?;
        let resumed = source.resume(input)?;
        let name = record_name(&resumed.agent_id);
        let bytes = encode_record(&resumed)?;
        publish_no_clobber(store, &dispatch_fd, run, &name, &bytes)?;
        Ok(resumed)
    }

    /// Walk `/` down to the runs root one `O_NOFOLLOW` descriptor at a time.
    ///
    /// Also the anchor the shared resolver holds across enumeration, which is
    /// why an unsafe runs root is `UnsafePath` before a single entry is read.
    pub(super) fn open_runs_root(store: &DispatchStore) -> DispatchStoreResult<OwnedFd> {
        reject_parent_components(&store.runs_root)?;
        let mut descriptor = open(
            "/",
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|source| unsafe_path_or_io("open filesystem root", PathBuf::from("/"), source))?;
        let mut traversed = PathBuf::from("/");
        for component in store.runs_root.components() {
            let std::path::Component::Normal(name) = component else {
                continue;
            };
            traversed.push(name);
            descriptor = openat(
                &descriptor,
                name,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::empty(),
            )
            .map_err(|source| {
                unsafe_path_or_io("open runs root component", traversed.clone(), source)
            })?;
        }
        Ok(descriptor)
    }

    fn open_run_dir(
        store: &DispatchStore,
        root: &OwnedFd,
        run: &RunId,
    ) -> DispatchStoreResult<OwnedFd> {
        let path = store.runs_root.join(run.as_str());
        openat(
            root,
            run.as_str(),
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|source| unsafe_path_or_io("open run directory", path, source))
    }

    fn open_dispatch_dir(
        store: &DispatchStore,
        run_fd: &OwnedFd,
        run: &RunId,
        create: bool,
    ) -> DispatchStoreResult<OwnedFd> {
        let path = store.runs_root.join(run.as_str()).join("dispatch");
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW;
        match openat(run_fd, "dispatch", flags, Mode::empty()) {
            Ok(fd) => Ok(fd),
            Err(source) if create && source == rustix::io::Errno::NOENT => {
                match mkdirat(run_fd, "dispatch", Mode::RWXU) {
                    Ok(()) | Err(rustix::io::Errno::EXIST) => {}
                    Err(source) => {
                        return Err(DispatchStoreError::io(
                            "create dispatch directory",
                            path,
                            source,
                        ));
                    }
                }
                openat(run_fd, "dispatch", flags, Mode::empty())
                    .map_err(|source| unsafe_path_or_io("open dispatch directory", path, source))
            }
            Err(source) => Err(unsafe_path_or_io("open dispatch directory", path, source)),
        }
    }

    /// Read `<runs_root>/<run>/run.json` through the runs-root descriptor.
    ///
    /// Opening the run directory is part of the read, not a separate step the
    /// caller sequences: a run whose directory vanished between enumeration
    /// and here is *absent*, which is the one failure the shared resolver
    /// skips. A linked run directory is `ELOOP` and a non-directory is
    /// `ENOTDIR`; `unsafe_path_or_io` renders both as `UnsafePath`, so an
    /// escape attempt can never be mistaken for absence.
    pub(super) fn read_run_document(
        store: &DispatchStore,
        root: &OwnedFd,
        run: &RunId,
    ) -> DispatchStoreResult<RunState> {
        let run_fd = open_run_dir(store, root, run)?;
        let path = store.runs_root.join(run.as_str()).join("run.json");
        let file = open_regular_at(&run_fd, "run.json", &path)?;
        let bytes = read_bounded(file, MAX_RECORD_BYTES)
            .map_err(|source| DispatchStoreError::io("read run document", path.clone(), source))?;
        let state: RunState = serde_json::from_slice(&bytes).map_err(|error| {
            DispatchStoreError::InvalidRunDocument {
                path: path.clone(),
                reason: error.to_string(),
            }
        })?;
        if state.run != run.as_str()
            || state.schema_version != 1
            || !matches!(
                state.status.as_str(),
                "planted" | "planned" | "executing" | "closing" | "closed"
            )
        {
            return Err(DispatchStoreError::InvalidRunDocument {
                path,
                reason: "run identity, schema, or status is invalid".into(),
            });
        }
        Ok(state)
    }

    fn read_record(
        store: &DispatchStore,
        dispatch_fd: &OwnedFd,
        run: &RunId,
        agent_id: &AgentId,
    ) -> DispatchStoreResult<DispatchRecord> {
        let name = record_name(agent_id);
        let path = store.record_path(run, agent_id);
        let file = match open_regular_at(dispatch_fd, &name, &path) {
            Ok(file) => file,
            Err(DispatchStoreError::Io { source, .. })
                if source.kind() == std::io::ErrorKind::NotFound =>
            {
                return Err(unknown_record(run, agent_id, "record is absent"));
            }
            Err(error) => return Err(error),
        };
        let bytes = read_bounded(file, MAX_RECORD_BYTES)
            .map_err(|error| unknown_record(run, agent_id, error.to_string()))?;
        let record: DispatchRecord = serde_json::from_slice(&bytes)
            .map_err(|error| unknown_record(run, agent_id, error.to_string()))?;
        record
            .validate_loaded()
            .map_err(|error| unknown_record(run, agent_id, error.to_string()))?;
        if &record.agent_id != agent_id || &record.run != run {
            return Err(unknown_record(
                run,
                agent_id,
                "record identity does not match its canonical path",
            ));
        }
        Ok(record)
    }

    fn open_regular_at(parent: &OwnedFd, name: &str, path: &Path) -> DispatchStoreResult<File> {
        let fd = openat(
            parent,
            name,
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|source| unsafe_path_or_io("open regular file", path.to_path_buf(), source))?;
        let stat = fs::fstat(&fd).map_err(|source| {
            DispatchStoreError::io("inspect regular file", path.to_path_buf(), source)
        })?;
        if !FileType::from_raw_mode(stat.st_mode).is_file() {
            return Err(DispatchStoreError::UnsafePath {
                path: path.to_path_buf(),
            });
        }
        Ok(File::from(fd))
    }

    fn acquire_lock(
        store: &DispatchStore,
        dispatch_fd: &OwnedFd,
        run: &RunId,
    ) -> DispatchStoreResult<DispatchLock> {
        let path = store.runs_root.join(run.as_str()).join("dispatch.lock");
        let fd = openat(
            dispatch_fd,
            ".dispatch.lock",
            OFlags::RDWR | OFlags::CREATE | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|source| unsafe_path_or_io("open dispatch lock", path.clone(), source))?;
        let file = File::from(fd);
        let started = Instant::now();
        loop {
            match file.try_lock() {
                Ok(()) => return Ok(DispatchLock(file)),
                Err(TryLockError::WouldBlock) if started.elapsed() < store.timeout => {
                    let remaining = store.timeout.saturating_sub(started.elapsed());
                    std::thread::sleep(LOCK_RETRY_INTERVAL.min(remaining));
                }
                Err(TryLockError::WouldBlock) => {
                    return Err(DispatchStoreError::LockTimeout {
                        path,
                        timeout: store.timeout,
                    });
                }
                Err(TryLockError::Error(source)) => {
                    return Err(DispatchStoreError::io(
                        "acquire dispatch lock",
                        path,
                        source,
                    ));
                }
            }
        }
    }

    fn publish_no_clobber(
        store: &DispatchStore,
        dispatch_fd: &OwnedFd,
        run: &RunId,
        target: &str,
        bytes: &[u8],
    ) -> DispatchStoreResult<()> {
        let (temp_name, mut temp) = create_temp(store, dispatch_fd, run, target)?;
        let result = (|| {
            temp.write_all(bytes).map_err(|source| {
                DispatchStoreError::io(
                    "write dispatch temp",
                    store.runs_root.join(run.as_str()).join(&temp_name),
                    source,
                )
            })?;
            temp.sync_all().map_err(|source| {
                DispatchStoreError::io(
                    "fsync dispatch temp",
                    store.runs_root.join(run.as_str()).join(&temp_name),
                    source,
                )
            })?;
            linkat(
                dispatch_fd,
                &temp_name,
                dispatch_fd,
                target,
                AtFlags::empty(),
            )
            .map_err(|source| {
                if source == rustix::io::Errno::EXIST {
                    DispatchStoreError::AlreadyExists {
                        path: store
                            .runs_root
                            .join(run.as_str())
                            .join("dispatch")
                            .join(target),
                    }
                } else {
                    DispatchStoreError::io(
                        "publish dispatch record",
                        store
                            .runs_root
                            .join(run.as_str())
                            .join("dispatch")
                            .join(target),
                        source,
                    )
                }
            })?;
            unlinkat(dispatch_fd, &temp_name, AtFlags::empty()).map_err(|source| {
                DispatchStoreError::io(
                    "unlink dispatch temp",
                    store
                        .runs_root
                        .join(run.as_str())
                        .join("dispatch")
                        .join(&temp_name),
                    source,
                )
            })?;
            fs::fsync(dispatch_fd).map_err(|source| {
                DispatchStoreError::io(
                    "fsync dispatch directory",
                    store.runs_root.join(run.as_str()).join("dispatch"),
                    source,
                )
            })
        })();
        if result.is_err() {
            let _ = unlinkat(dispatch_fd, &temp_name, AtFlags::empty());
        }
        result
    }

    fn replace_record(
        store: &DispatchStore,
        dispatch_fd: &OwnedFd,
        run: &RunId,
        record: &DispatchRecord,
    ) -> DispatchStoreResult<()> {
        let target = record_name(&record.agent_id);
        let bytes = encode_record(record)?;
        let (temp_name, mut temp) = create_temp(store, dispatch_fd, run, &target)?;
        let result = (|| {
            temp.write_all(&bytes).map_err(|source| {
                DispatchStoreError::io(
                    "write dispatch temp",
                    store.runs_root.join(run.as_str()).join(&temp_name),
                    source,
                )
            })?;
            temp.sync_all().map_err(|source| {
                DispatchStoreError::io(
                    "fsync dispatch temp",
                    store.runs_root.join(run.as_str()).join(&temp_name),
                    source,
                )
            })?;
            let target_path = store.record_path(run, &record.agent_id);
            let stat =
                fs::statat(dispatch_fd, &target, AtFlags::SYMLINK_NOFOLLOW).map_err(|source| {
                    unsafe_path_or_io("inspect dispatch record", target_path.clone(), source)
                })?;
            if !FileType::from_raw_mode(stat.st_mode).is_file() {
                return Err(DispatchStoreError::UnsafePath { path: target_path });
            }
            renameat(dispatch_fd, &temp_name, dispatch_fd, &target).map_err(|source| {
                DispatchStoreError::io(
                    "replace dispatch record",
                    store.record_path(run, &record.agent_id),
                    source,
                )
            })?;
            fs::fsync(dispatch_fd).map_err(|source| {
                DispatchStoreError::io(
                    "fsync dispatch directory",
                    store.runs_root.join(run.as_str()).join("dispatch"),
                    source,
                )
            })
        })();
        if result.is_err() {
            let _ = unlinkat(dispatch_fd, &temp_name, AtFlags::empty());
        }
        result
    }

    fn create_temp(
        store: &DispatchStore,
        dispatch_fd: &OwnedFd,
        run: &RunId,
        target: &str,
    ) -> DispatchStoreResult<(String, File)> {
        for _ in 0..MAX_TEMP_ATTEMPTS {
            let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
            let nanos = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|duration| duration.as_nanos())
                .unwrap_or(0);
            let name = format!(".{target}.{nanos:x}.{sequence:x}.tmp");
            match openat(
                dispatch_fd,
                &name,
                OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::RUSR | Mode::WUSR,
            ) {
                Ok(fd) => return Ok((name, File::from(fd))),
                Err(rustix::io::Errno::EXIST) => continue,
                Err(source) => {
                    return Err(DispatchStoreError::io(
                        "create dispatch temp",
                        store
                            .runs_root
                            .join(run.as_str())
                            .join("dispatch")
                            .join(name),
                        source,
                    ));
                }
            }
        }
        Err(DispatchStoreError::io(
            "create dispatch temp",
            store.runs_root.join(run.as_str()).join("dispatch"),
            std::io::Error::new(
                std::io::ErrorKind::AlreadyExists,
                "temporary name collision budget exhausted",
            ),
        ))
    }

    fn encode_record(record: &DispatchRecord) -> DispatchStoreResult<Vec<u8>> {
        encode_document(record)
    }

    fn encode_document(document: &impl serde::Serialize) -> DispatchStoreResult<Vec<u8>> {
        let mut bytes = serde_json::to_vec(document).map_err(|error| {
            DispatchStoreError::Domain(DispatchError::InvalidRecord(error.to_string()))
        })?;
        bytes.push(b'\n');
        let max = usize::try_from(MAX_RECORD_BYTES).expect("record limit fits usize");
        if bytes.len() > max {
            return Err(DispatchStoreError::RecordTooLarge {
                size: bytes.len(),
                max,
            });
        }
        Ok(bytes)
    }

    fn read_bounded(file: File, limit: u64) -> std::io::Result<Vec<u8>> {
        let mut bytes = Vec::new();
        file.take(limit + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 > limit {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "document exceeds size limit",
            ));
        }
        Ok(bytes)
    }

    fn record_name(agent_id: &AgentId) -> String {
        format!("{}.json", agent_id.as_str())
    }

    fn unknown_record(
        run: &RunId,
        agent_id: &AgentId,
        reason: impl Into<String>,
    ) -> DispatchStoreError {
        DispatchStoreError::UnknownRecord {
            run: run.clone(),
            agent_id: agent_id.clone(),
            reason: reason.into(),
        }
    }

    fn reject_parent_components(path: &Path) -> DispatchStoreResult<()> {
        if !path.is_absolute()
            || path.components().any(|component| {
                matches!(
                    component,
                    std::path::Component::ParentDir | std::path::Component::CurDir
                )
            })
        {
            return Err(DispatchStoreError::UnsafePath {
                path: path.to_path_buf(),
            });
        }
        Ok(())
    }

    fn unsafe_path_or_io(
        operation: &'static str,
        path: PathBuf,
        source: rustix::io::Errno,
    ) -> DispatchStoreError {
        if matches!(source, rustix::io::Errno::LOOP | rustix::io::Errno::NOTDIR) {
            DispatchStoreError::UnsafePath { path }
        } else {
            DispatchStoreError::io(operation, path, source)
        }
    }

    struct DispatchLock(File);

    impl Drop for DispatchLock {
        fn drop(&mut self) {
            let _ = self.0.unlock();
        }
    }
}

#[cfg(not(unix))]
mod platform {
    //! The non-unix twin of the descriptor-anchored dispatch ledger.
    //!
    //! Every ledger operation performs the SAME sequence as the unix module --
    //! validate the runs root, resolve the run directory, resolve the dispatch
    //! directory, take the exclusive dispatch lock, then operate -- and returns
    //! the SAME error variants, because callers and the hook fixtures branch on
    //! them. `AlreadyExists` in particular is the fact that stops a second
    //! `SessionStart` from silently overwriting a live root binding.
    //!
    //! The anchoring differs, and only the anchoring: paths with per-component
    //! link rejection instead of a chain of directory descriptors. See
    //! `crate::safe_fs` for exactly what that does and does not guarantee.
    //!
    //! Active-run resolution is deliberately NOT twinned. Enumerating the runs
    //! root, filtering names, sorting, and choosing among the candidates is
    //! platform-free, so it lives once in `super::resolve_active_run` and this
    //! module contributes only the anchoring residue that resolver calls:
    //! `open_runs_root` and `read_run_document`. A twin of the choosing logic
    //! is a twin that drifts, because only one of the two is ever compiled
    //! here.

    use std::fs::{File, TryLockError};

    use super::*;
    use crate::safe_fs;

    const MAX_RECORD_BYTES: u64 = 1_048_576;
    const LOCK_RETRY_INTERVAL: Duration = Duration::from_millis(10);

    /// The anchor the shared resolver holds across enumeration.
    ///
    /// The unix twin hands back a directory descriptor that every later
    /// `openat` resolves against. There is no descriptor here -- anchoring is
    /// per-component and re-checked at each open -- so this carries no data
    /// and exists only as proof that the runs root was validated before a
    /// single entry was enumerated. Only [`open_runs_root`] can mint one.
    pub(super) struct RunsRoot;

    /// Validate the runs root and mint the resolver's anchor.
    pub(super) fn open_runs_root(store: &DispatchStore) -> DispatchStoreResult<RunsRoot> {
        reject_parent_components(&store.runs_root)?;
        Ok(RunsRoot)
    }

    pub(super) fn publish(
        store: &DispatchStore,
        record: &DispatchRecord,
    ) -> DispatchStoreResult<()> {
        let dispatch = dispatch_dir(store, &record.run, true)?;
        let _lock = acquire_lock(store, &record.run)?;
        let bytes = encode_record(record)?;
        publish_no_clobber(&dispatch.join(record_name(&record.agent_id)), &bytes)?;
        // Round-trip before reporting success. A record that cannot be read
        // back is a record the next hook invocation refuses, and finding that
        // out here names the writer instead of the reader.
        let loaded = read_record(store, &record.run, &record.agent_id)?;
        if loaded != *record {
            return Err(unknown_record(
                &record.run,
                &record.agent_id,
                "published bytes did not round-trip",
            ));
        }
        Ok(())
    }

    pub(super) fn publish_root_binding(
        store: &DispatchStore,
        binding: &RootSessionBinding,
    ) -> DispatchStoreResult<()> {
        let dispatch = dispatch_dir(store, &binding.run, true)?;
        let _lock = acquire_lock(store, &binding.run)?;
        let bytes = encode_document(binding)?;
        publish_no_clobber(
            &dispatch.join(root_binding_name(&binding.session_id)),
            &bytes,
        )
    }

    pub(super) fn load_root_binding(
        store: &DispatchStore,
        run: &RunId,
        session_id: &SessionId,
    ) -> DispatchStoreResult<RootSessionBinding> {
        dispatch_dir(store, run, false)?;
        let _lock = acquire_lock(store, run)?;
        let path = store.root_binding_path(run, session_id);
        let bytes = read_document(&path, "read root binding")?;
        let binding: RootSessionBinding = serde_json::from_slice(&bytes).map_err(|error| {
            DispatchStoreError::Domain(DispatchError::InvalidRecord(error.to_string()))
        })?;
        binding.validate()?;
        if &binding.run != run || &binding.session_id != session_id {
            return Err(DispatchStoreError::Domain(DispatchError::InvalidRecord(
                "root binding identity does not match its canonical path".into(),
            )));
        }
        Ok(binding)
    }

    pub(super) fn load(
        store: &DispatchStore,
        run: &RunId,
        agent_id: &AgentId,
    ) -> DispatchStoreResult<DispatchRecord> {
        dispatch_dir(store, run, false).map_err(|error| {
            if is_not_found(&error) {
                unknown_record(run, agent_id, "dispatch directory is absent")
            } else {
                error
            }
        })?;
        let _lock = acquire_lock(store, run)?;
        read_record(store, run, agent_id)
    }

    pub(super) fn stop(
        store: &DispatchStore,
        run: &RunId,
        request: StopRequest,
    ) -> DispatchStoreResult<DispatchRecord> {
        dispatch_dir(store, run, false)?;
        let _lock = acquire_lock(store, run)?;
        let mut record = read_record(store, run, &request.agent_id)?;
        record.stop(request)?;
        record.validate_loaded()?;
        replace_record(store, run, &record)?;
        Ok(record)
    }

    pub(super) fn stop_verified(
        store: &DispatchStore,
        run: &RunId,
        native: &NativeIdentity,
        request: StopRequest,
    ) -> DispatchStoreResult<DispatchRecord> {
        dispatch_dir(store, run, false)?;
        let _lock = acquire_lock(store, run)?;
        let mut record = read_record(store, run, &request.agent_id)?;
        resolve_native_identity(Some(&record), native)?;
        record.stop(request)?;
        record.validate_loaded()?;
        replace_record(store, run, &record)?;
        Ok(record)
    }

    pub(super) fn resume(
        store: &DispatchStore,
        run: &RunId,
        source_agent_id: &AgentId,
        input: DispatchStart,
    ) -> DispatchStoreResult<DispatchRecord> {
        let dispatch = dispatch_dir(store, run, false)?;
        let _lock = acquire_lock(store, run)?;
        let source = read_record(store, run, source_agent_id)?;
        let resumed = source.resume(input)?;
        let bytes = encode_record(&resumed)?;
        publish_no_clobber(&dispatch.join(record_name(&resumed.agent_id)), &bytes)?;
        Ok(resumed)
    }

    /// Resolve `<runs_root>/<run>/dispatch`, creating it only when asked.
    ///
    /// `create` is false on every read path, so a caller expecting an existing
    /// ledger gets `NotFound` instead of quietly manufacturing an empty
    /// directory that then reports "record is absent".
    fn dispatch_dir(
        store: &DispatchStore,
        run: &RunId,
        create: bool,
    ) -> DispatchStoreResult<PathBuf> {
        reject_parent_components(&store.runs_root)?;
        let dispatch = store.runs_root.join(run.as_str()).join("dispatch");
        if create {
            std::fs::create_dir_all(&dispatch).map_err(|source| {
                DispatchStoreError::io("create dispatch directory", dispatch.clone(), source)
            })?;
        }
        safe_fs::reject_link_components(&dispatch).map_err(|_| DispatchStoreError::UnsafePath {
            path: dispatch.clone(),
        })?;
        if !create {
            let metadata = std::fs::symlink_metadata(&dispatch).map_err(|source| {
                DispatchStoreError::io("open dispatch directory", dispatch.clone(), source)
            })?;
            if !metadata.is_dir() {
                return Err(DispatchStoreError::UnsafePath { path: dispatch });
            }
        }
        Ok(dispatch)
    }

    /// Read `<runs_root>/<run>/run.json`.
    ///
    /// The anchor carries nothing, so it is named `_root`: every open below
    /// re-walks and re-checks its own components (`crate::safe_fs`), which is
    /// exactly the guarantee the module header refuses to overstate. An absent
    /// document surfaces as `Io { NotFound }` and a linked or non-regular one
    /// as `UnsafePath`, so the shared resolver can tell "not a run" apart from
    /// "unreadable".
    pub(super) fn read_run_document(
        store: &DispatchStore,
        _root: &RunsRoot,
        run: &RunId,
    ) -> DispatchStoreResult<RunState> {
        let path = store.runs_root.join(run.as_str()).join("run.json");
        let bytes = read_document(&path, "read run document")?;
        let state: RunState = serde_json::from_slice(&bytes).map_err(|error| {
            DispatchStoreError::InvalidRunDocument {
                path: path.clone(),
                reason: error.to_string(),
            }
        })?;
        if state.run != run.as_str()
            || state.schema_version != 1
            || !matches!(
                state.status.as_str(),
                "planted" | "planned" | "executing" | "closing" | "closed"
            )
        {
            return Err(DispatchStoreError::InvalidRunDocument {
                path,
                reason: "run identity, schema, or status is invalid".into(),
            });
        }
        Ok(state)
    }

    fn read_record(
        store: &DispatchStore,
        run: &RunId,
        agent_id: &AgentId,
    ) -> DispatchStoreResult<DispatchRecord> {
        let path = store.record_path(run, agent_id);
        let bytes = match read_document(&path, "read dispatch record") {
            Ok(bytes) => bytes,
            Err(error) if is_not_found(&error) => {
                return Err(unknown_record(run, agent_id, "record is absent"));
            }
            Err(error @ DispatchStoreError::UnsafePath { .. }) => return Err(error),
            Err(error) => return Err(unknown_record(run, agent_id, error.to_string())),
        };
        let record: DispatchRecord = serde_json::from_slice(&bytes)
            .map_err(|error| unknown_record(run, agent_id, error.to_string()))?;
        record
            .validate_loaded()
            .map_err(|error| unknown_record(run, agent_id, error.to_string()))?;
        if &record.agent_id != agent_id || &record.run != run {
            return Err(unknown_record(
                run,
                agent_id,
                "record identity does not match its canonical path",
            ));
        }
        Ok(record)
    }

    fn read_document(path: &Path, operation: &'static str) -> DispatchStoreResult<Vec<u8>> {
        safe_fs::read_regular_nofollow(path, MAX_RECORD_BYTES).map_err(|source| {
            if source.kind() == std::io::ErrorKind::InvalidInput {
                DispatchStoreError::UnsafePath {
                    path: path.to_path_buf(),
                }
            } else {
                DispatchStoreError::io(operation, path.to_path_buf(), source)
            }
        })
    }

    /// The advisory lock is `std::fs::File::try_lock`: `LockFileEx` on Windows,
    /// `flock` on unix. The unix twin makes the same call, so the
    /// mutual-exclusion contract is genuinely shared, not approximated.
    fn acquire_lock(store: &DispatchStore, run: &RunId) -> DispatchStoreResult<DispatchLock> {
        let path = store.runs_root.join(run.as_str()).join("dispatch.lock");
        let lock_path = store
            .runs_root
            .join(run.as_str())
            .join("dispatch")
            .join(".dispatch.lock");
        if safe_fs::is_link(&lock_path).unwrap_or(true) {
            return Err(DispatchStoreError::UnsafePath { path: lock_path });
        }
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|source| DispatchStoreError::io("open dispatch lock", path.clone(), source))?;
        let started = Instant::now();
        loop {
            match file.try_lock() {
                Ok(()) => return Ok(DispatchLock(file)),
                Err(TryLockError::WouldBlock) if started.elapsed() < store.timeout => {
                    let remaining = store.timeout.saturating_sub(started.elapsed());
                    std::thread::sleep(LOCK_RETRY_INTERVAL.min(remaining));
                }
                Err(TryLockError::WouldBlock) => {
                    return Err(DispatchStoreError::LockTimeout {
                        path,
                        timeout: store.timeout,
                    });
                }
                Err(TryLockError::Error(source)) => {
                    return Err(DispatchStoreError::io(
                        "acquire dispatch lock",
                        path,
                        source,
                    ));
                }
            }
        }
    }

    /// Refusing to replace is the point: a second publication for a live
    /// binding must be reported, never silently overwritten.
    fn publish_no_clobber(path: &Path, bytes: &[u8]) -> DispatchStoreResult<()> {
        match safe_fs::write_no_clobber(path, bytes) {
            Ok(true) => Ok(()),
            Ok(false) => Err(DispatchStoreError::AlreadyExists {
                path: path.to_path_buf(),
            }),
            Err(source) if source.kind() == std::io::ErrorKind::InvalidInput => {
                Err(DispatchStoreError::UnsafePath {
                    path: path.to_path_buf(),
                })
            }
            Err(source) => Err(DispatchStoreError::io(
                "publish dispatch record",
                path.to_path_buf(),
                source,
            )),
        }
    }

    fn replace_record(
        store: &DispatchStore,
        run: &RunId,
        record: &DispatchRecord,
    ) -> DispatchStoreResult<()> {
        let path = store.record_path(run, &record.agent_id);
        let bytes = encode_record(record)?;
        safe_fs::replace_atomic(&path, &bytes).map_err(|source| {
            DispatchStoreError::io("replace dispatch record", path.clone(), source)
        })
    }

    fn encode_record(record: &DispatchRecord) -> DispatchStoreResult<Vec<u8>> {
        encode_document(record)
    }

    fn encode_document(document: &impl serde::Serialize) -> DispatchStoreResult<Vec<u8>> {
        let mut bytes = serde_json::to_vec(document).map_err(|error| {
            DispatchStoreError::Domain(DispatchError::InvalidRecord(error.to_string()))
        })?;
        bytes.push(b'\n');
        let max = usize::try_from(MAX_RECORD_BYTES).expect("record limit fits usize");
        if bytes.len() > max {
            return Err(DispatchStoreError::RecordTooLarge {
                size: bytes.len(),
                max,
            });
        }
        Ok(bytes)
    }

    fn record_name(agent_id: &AgentId) -> String {
        format!("{}.json", agent_id.as_str())
    }

    fn unknown_record(
        run: &RunId,
        agent_id: &AgentId,
        reason: impl Into<String>,
    ) -> DispatchStoreError {
        DispatchStoreError::UnknownRecord {
            run: run.clone(),
            agent_id: agent_id.clone(),
            reason: reason.into(),
        }
    }

    fn reject_parent_components(path: &Path) -> DispatchStoreResult<()> {
        if !path.is_absolute()
            || path.components().any(|component| {
                matches!(
                    component,
                    std::path::Component::ParentDir | std::path::Component::CurDir
                )
            })
        {
            return Err(DispatchStoreError::UnsafePath {
                path: path.to_path_buf(),
            });
        }
        Ok(())
    }

    struct DispatchLock(File);

    impl Drop for DispatchLock {
        fn drop(&mut self) {
            let _ = self.0.unlock();
        }
    }
}
