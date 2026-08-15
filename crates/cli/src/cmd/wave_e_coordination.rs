//! Native coordination primitives owned by the canonical layout-v5 namespace.
//!
//! This Wave E slice ports the project lock contract. The lock is a
//! descriptor-safe file beside the canonical registry and its audit trail is
//! kept in `locks_history`; it does not call legacy Python, Bash, or Node.

use std::{
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

use clap::{Args, Subcommand};
use rusqlite::params;
use shepherd::registry::{OpenMode, Registry};
use uuid::Uuid;

use crate::{
    ContextInputs, ExecutionContext,
    interface::{CliError, CliGlobals},
};

const DEFAULT_MODE: &str = "context";
const MAX_LOCK_BYTES: u64 = 64 * 1024;

/// Canonical project coordination commands.
#[derive(
    Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Args, serde::Deserialize, serde::Serialize,
)]
#[command(disable_help_subcommand = true)]
pub struct WaveECoordinationCmd {
    #[command(subcommand)]
    action: Option<CoordinationAction>,
}

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    Subcommand,
    serde::Deserialize,
    serde::Serialize,
)]
enum CoordinationAction {
    Show {
        #[arg(long)]
        json: bool,
    },
    Acquire {
        #[arg(long, default_value = DEFAULT_MODE)]
        mode: String,
        #[arg(long)]
        session: Option<String>,
    },
    Release {
        #[arg(long, conflicts_with = "all")]
        force: bool,
        #[arg(long, conflicts_with = "force")]
        all: bool,
    },
    Reap,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
struct LockFile {
    holder_session_id: String,
    mode: String,
    acquired_at: i64,
    pid: u32,
    children: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize)]
struct LockJson {
    held: bool,
    holder_session_id: Option<String>,
    mode: Option<String>,
    acquired_at: Option<i64>,
    pid: Option<u32>,
    children: Option<Vec<String>>,
}

impl WaveECoordinationCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        match self
            .action
            .unwrap_or(CoordinationAction::Show { json: false })
        {
            CoordinationAction::Show { json } => show(globals, json),
            CoordinationAction::Acquire { mode, session } => acquire(globals, mode, session),
            CoordinationAction::Release { force, all } => release(globals, force || all),
            CoordinationAction::Reap => reap(globals),
        }
    }
}

fn context(globals: CliGlobals) -> Result<ExecutionContext, CliError> {
    let cwd = std::env::current_dir()
        .map_err(|error| CliError::message(format!("cannot resolve current directory: {error}")))?;
    let mut inputs = ContextInputs::from_environment(cwd)
        .map_err(|error| CliError::message(error.to_string()))?;
    inputs.explicit_config = globals.config;
    inputs.verbosity = globals.verbosity;
    ExecutionContext::discover(inputs).map_err(|error| CliError::message(error.to_string()))
}

fn open_registry(context: &ExecutionContext, write: bool) -> Result<Registry, CliError> {
    let mode = if write {
        OpenMode::ReadWrite
    } else {
        OpenMode::ReadOnly
    };
    Registry::open(&context.registry_path, mode).map_err(registry_error)
}

fn project_id(registry: &Registry) -> Result<String, CliError> {
    registry
        .query("SELECT id FROM projects ORDER BY id LIMIT 1", [], |row| {
            row.get(0)
        })
        .map_err(registry_error)?
        .into_iter()
        .next()
        .ok_or_else(|| CliError::message("no project registered — run 'shepherd init' first"))
}

fn show(globals: CliGlobals, json: bool) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let exists = lock_exists(&context.registry_lock_path)?;
    let lock = read_lock(&context.registry_lock_path)?;
    if !exists {
        return if json {
            stdout(
                &mut context,
                &serde_json::to_string_pretty(&LockJson {
                    held: false,
                    holder_session_id: None,
                    mode: None,
                    acquired_at: None,
                    pid: None,
                    children: None,
                })
                .map_err(|error| CliError::message(error.to_string()))?,
            )
        } else {
            stdout(&mut context, "lock: free")
        };
    }
    if json {
        let output = serde_json::to_string_pretty(&match lock {
            Some(lock) => LockJson {
                held: true,
                holder_session_id: Some(lock.holder_session_id),
                mode: Some(lock.mode),
                acquired_at: Some(lock.acquired_at),
                pid: Some(lock.pid),
                children: Some(lock.children),
            },
            None => LockJson {
                held: true,
                holder_session_id: None,
                mode: None,
                acquired_at: None,
                pid: None,
                children: None,
            },
        })
        .map_err(|error| CliError::message(format!("cannot render lock JSON: {error}")))?;
        return stdout(&mut context, &output);
    }
    match lock {
        Some(lock) => stdout(
            &mut context,
            &format!(
                "lock: held\n{}",
                serde_json::to_string_pretty(&lock)
                    .map_err(|error| CliError::message(error.to_string()))?
            ),
        ),
        None => stdout(&mut context, "lock: held"),
    }
}

fn acquire(globals: CliGlobals, mode: String, session: Option<String>) -> Result<(), CliError> {
    if !matches!(
        mode.as_str(),
        "autorun" | "parallel" | "start" | "plant" | "context" | "sprint" | "spawn"
    ) {
        return Err(CliError::message(format!(
            "invalid lock mode `{mode}`; expected autorun, parallel, start, plant, context, sprint, or spawn"
        )));
    }
    let mut context = context(globals)?;
    let registry = open_registry(&context, true)?;
    let project = project_id(&registry)?;
    let session = session
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| Uuid::now_v7().to_string());
    let acquired_at = now_seconds();
    let lock = LockFile {
        holder_session_id: session.clone(),
        mode: mode.clone(),
        acquired_at,
        pid: std::process::id(),
        children: Vec::new(),
    };
    let path = &context.registry_lock_path;
    let bytes = serde_json::to_vec(&lock)
        .map_err(|error| CliError::message(format!("cannot encode lock: {error}")))?;
    platform::create_lock(path, &bytes)?;
    if let Err(error) = registry.execute("INSERT INTO locks_history (project_id, session_id, mode, acquired_at) VALUES (?1, ?2, ?3, ?4)", params![project, session, mode, acquired_at]) {
        let _ = platform::remove_lock(path);
        return Err(registry_error(error));
    }
    stdout(&mut context, &format!("lock: acquired ({session}, {mode})"))
}

fn release(globals: CliGlobals, force: bool) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let registry = open_registry(&context, true)?;
    let project = project_id(&registry)?;
    let path = &context.registry_lock_path;
    if !lock_exists(path)? {
        return stdout(&mut context, "lock: free");
    }
    let lock = read_lock(path)?;
    remove_lock(path)?;
    let released_by = if force { "force" } else { "normal" };
    let session = lock.map_or_else(|| "null".to_owned(), |lock| lock.holder_session_id);
    registry.execute("UPDATE locks_history SET released_at = ?1, released_by = ?2 WHERE project_id = ?3 AND session_id = ?4 AND released_at IS NULL", params![now_seconds(), released_by, project, session]).map_err(registry_error)?;
    stdout(
        &mut context,
        if force {
            "lock: released (force)"
        } else {
            "lock: released"
        },
    )
}

fn reap(globals: CliGlobals) -> Result<(), CliError> {
    let mut context = context(globals)?;
    let registry = open_registry(&context, true)?;
    let project = project_id(&registry)?;
    let path = &context.registry_lock_path;
    if !lock_exists(path)? {
        return stdout(&mut context, "lock: free");
    }
    let Some(lock) = read_lock(path)? else {
        remove_lock(path)?;
        return stdout(&mut context, "lock: reaped (pid=null, age=0m)");
    };
    let now = now_seconds();
    let age_min = (now.saturating_sub(lock.acquired_at)) / 60;
    if process_is_alive(lock.pid) && age_min <= 60 {
        return Err(CliError::message(format!(
            "lock: held by live pid {} (age {age_min}m); not reaping",
            lock.pid
        )));
    }
    remove_lock(path)?;
    registry.execute("UPDATE locks_history SET released_at = ?1, released_by = 'reap' WHERE project_id = ?2 AND session_id = ?3 AND released_at IS NULL", params![now, project, lock.holder_session_id]).map_err(registry_error)?;
    stdout(
        &mut context,
        &format!("lock: reaped (pid={}, age={age_min}m)", lock.pid),
    )
}

fn read_lock(path: &Path) -> Result<Option<LockFile>, CliError> {
    platform::read_lock(path)
}

fn lock_exists(path: &Path) -> Result<bool, CliError> {
    platform::exists(path)
}

fn remove_lock(path: &Path) -> Result<(), CliError> {
    platform::remove_lock(path)
}

fn process_is_alive(pid: u32) -> bool {
    if pid == std::process::id() {
        return true;
    }
    #[cfg(unix)]
    {
        rustix::process::Pid::from_raw(pid as i32)
            .is_some_and(|pid| rustix::process::test_kill_process(pid).is_ok())
    }
    #[cfg(not(unix))]
    {
        false
    }
}

fn stdout(context: &mut ExecutionContext, output: &str) -> Result<(), CliError> {
    let mut bytes = output.as_bytes().to_vec();
    bytes.push(b'\n');
    context
        .write_stdout(&bytes)
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

fn registry_error(error: shepherd::registry::Error) -> CliError {
    CliError::message(error.to_string())
}

fn now_seconds() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
        .try_into()
        .unwrap_or(i64::MAX)
}

#[cfg(unix)]
mod platform {
    use std::{
        fs::File,
        io::{Read, Write},
        os::fd::OwnedFd,
        path::{Component, Path},
    };

    use rustix::fs::{self, AtFlags, FileType, Mode, OFlags, open, openat, unlinkat};

    use super::{CliError, LockFile, MAX_LOCK_BYTES};

    fn parent(path: &Path) -> Result<OwnedFd, CliError> {
        if !path.is_absolute() {
            return Err(CliError::message(format!(
                "lock path must be absolute: {}",
                path.display()
            )));
        }
        let mut fd = open(
            "/",
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| CliError::message(format!("open lock root: {error}")))?;
        let parent = path
            .parent()
            .ok_or_else(|| CliError::message("lock path has no parent"))?;
        for component in parent.components() {
            let Component::Normal(name) = component else {
                continue;
            };
            fd = openat(
                &fd,
                name,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::empty(),
            )
            .map_err(|error| CliError::message(format!("open lock directory: {error}")))?;
        }
        Ok(fd)
    }

    pub(super) fn create_lock(path: &Path, bytes: &[u8]) -> Result<(), CliError> {
        let parent = parent(path)?;
        let name = path
            .file_name()
            .ok_or_else(|| CliError::message("lock path has no file name"))?;
        let fd = openat(
            &parent,
            name,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|error| {
            if error == rustix::io::Errno::EXIST {
                CliError::message("lock already held")
            } else {
                CliError::message(format!("create lock {}: {error}", path.display()))
            }
        })?;
        let mut file = File::from(fd);
        if let Err(error) = file.write_all(bytes).and_then(|_| file.sync_all()) {
            let _ = unlinkat(&parent, name, AtFlags::empty());
            return Err(CliError::message(format!(
                "write lock {}: {error}",
                path.display()
            )));
        }
        fs::fsync(&parent)
            .map_err(|error| CliError::message(format!("sync lock directory: {error}")))
    }

    pub(super) fn read_lock(path: &Path) -> Result<Option<LockFile>, CliError> {
        let parent = parent(path)?;
        let name = path
            .file_name()
            .ok_or_else(|| CliError::message("lock path has no file name"))?;
        let fd = match openat(
            &parent,
            name,
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        ) {
            Ok(fd) => fd,
            Err(rustix::io::Errno::NOENT) => return Ok(None),
            Err(error) => {
                return Err(CliError::message(format!(
                    "open lock {}: {error}",
                    path.display()
                )));
            }
        };
        let stat = fs::fstat(&fd).map_err(|error| {
            CliError::message(format!("inspect lock {}: {error}", path.display()))
        })?;
        if !FileType::from_raw_mode(stat.st_mode).is_file() {
            return Err(CliError::message(format!(
                "lock is not a regular file: {}",
                path.display()
            )));
        }
        let mut file = File::from(fd).take(MAX_LOCK_BYTES + 1);
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)
            .map_err(|error| CliError::message(format!("read lock {}: {error}", path.display())))?;
        if bytes.len() as u64 > MAX_LOCK_BYTES {
            return Err(CliError::message(
                "lock file exceeds the canonical size limit",
            ));
        }
        Ok(serde_json::from_slice(&bytes).ok())
    }

    pub(super) fn exists(path: &Path) -> Result<bool, CliError> {
        let parent = parent(path)?;
        let name = path
            .file_name()
            .ok_or_else(|| CliError::message("lock path has no file name"))?;
        match fs::statat(&parent, name, AtFlags::SYMLINK_NOFOLLOW) {
            Ok(stat) if FileType::from_raw_mode(stat.st_mode).is_file() => Ok(true),
            Ok(stat) if FileType::from_raw_mode(stat.st_mode).is_symlink() => Err(
                CliError::message(format!("refusing symlink lock {}", path.display())),
            ),
            Ok(_) => Err(CliError::message(format!(
                "lock is not a regular file: {}",
                path.display()
            ))),
            Err(rustix::io::Errno::NOENT) => Ok(false),
            Err(error) => Err(CliError::message(format!(
                "inspect lock {}: {error}",
                path.display()
            ))),
        }
    }

    pub(super) fn remove_lock(path: &Path) -> Result<(), CliError> {
        let parent = parent(path)?;
        let name = path
            .file_name()
            .ok_or_else(|| CliError::message("lock path has no file name"))?;
        match fs::statat(&parent, name, AtFlags::SYMLINK_NOFOLLOW) {
            Ok(stat) if FileType::from_raw_mode(stat.st_mode).is_file() => {}
            Ok(stat) if FileType::from_raw_mode(stat.st_mode).is_symlink() => {
                return Err(CliError::message(format!(
                    "refusing symlink lock {}",
                    path.display()
                )));
            }
            Ok(_) => {
                return Err(CliError::message(format!(
                    "lock is not a regular file: {}",
                    path.display()
                )));
            }
            Err(rustix::io::Errno::NOENT) => return Ok(()),
            Err(error) => {
                return Err(CliError::message(format!(
                    "inspect lock {}: {error}",
                    path.display()
                )));
            }
        }
        unlinkat(&parent, name, AtFlags::empty()).map_err(|error| {
            CliError::message(format!("remove lock {}: {error}", path.display()))
        })?;
        fs::fsync(&parent)
            .map_err(|error| CliError::message(format!("sync lock directory: {error}")))
    }
}

#[cfg(not(unix))]
mod platform {
    use std::{
        fs::{self, File, OpenOptions},
        io::{Read, Write},
        path::Path,
    };

    use super::{CliError, LockFile, MAX_LOCK_BYTES};

    pub(super) fn create_lock(path: &Path, bytes: &[u8]) -> Result<(), CliError> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|error| CliError::message(error.to_string()))?;
        file.write_all(bytes)
            .and_then(|_| file.sync_all())
            .map_err(|error| CliError::message(error.to_string()))
    }

    pub(super) fn read_lock(path: &Path) -> Result<Option<LockFile>, CliError> {
        let mut file = match File::open(path) {
            Ok(file) => file.take(MAX_LOCK_BYTES + 1),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(CliError::message(error.to_string())),
        };
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)
            .map_err(|error| CliError::message(error.to_string()))?;
        Ok(serde_json::from_slice(&bytes).ok())
    }

    pub(super) fn exists(path: &Path) -> Result<bool, CliError> {
        Ok(path.is_file())
    }

    pub(super) fn remove_lock(path: &Path) -> Result<(), CliError> {
        fs::remove_file(path).map_err(|error| CliError::message(error.to_string()))
    }
}
