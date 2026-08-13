/*
    Appellation: atomic <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! Atomic write: tempfile -> fsync -> rename -> fsync(dir).
//!
//! Reproduces `models_run.py:615-639`'s `atomic_write_json` step for step:
//!
//! | Python (`atomic_write_json`) | Here |
//! |---|---|
//! | `tempfile.mkstemp(dir=parent, ...)` | [`temp_path`], same directory as the target |
//! | `json.dump(...)` + `handle.write("\n")` | the caller-supplied `contents` (already the canonical text) + one trailing `\n` |
//! | `handle.flush()` + `os.fsync(handle.fileno())` | `File::flush` + `File::sync_all` |
//! | `os.replace(tmp_path, path)` | `std::fs::rename` |
//! | `os.fsync(dir_fd)` | opening `parent` as a [`std::fs::File`] and `sync_all` |
//! | `finally: os.unlink(tmp_path)` if it still exists | best-effort [`std::fs::remove_file`] on the same condition |
//!
//! `std::fs::File::open` on a directory, and fsyncing it, is POSIX behavior
//! that the Python reference itself relies on unconditionally (`os.open(parent,
//! os.O_RDONLY)` fails identically on platforms without it) — reproduced
//! here rather than made more lenient than the reference.
//!
//! No `std::process` anywhere in this module: `crates/core` may not depend on
//! it (decision 8, enforced by `boundaries.yml`'s process/argv grep), so the
//! temp filename's uniqueness comes from a wall-clock timestamp plus an
//! in-process atomic counter instead of a process id.
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use crate::error::{Error, Result};

static ATOMIC_WRITE_SEQ: AtomicU64 = AtomicU64::new(0);

/// A unique path in `target`'s own directory. Same directory matters: a
/// rename is only atomic within one filesystem, and a tempfile placed
/// elsewhere (e.g. `$TMPDIR`) can land on a different one.
fn temp_path(target: &Path) -> PathBuf {
    let seq = ATOMIC_WRITE_SEQ.fetch_add(1, Ordering::Relaxed);
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let stem = target
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("run-json");
    target.with_file_name(format!(".{stem}-{nanos:x}-{seq:x}.tmp"))
}

/// Write `contents` to `target` atomically, matching `atomic_write_json`'s
/// sequencing and bytes (a trailing `\n` after `contents`, which `contents`
/// itself should not already carry — [`crate::run::RunState::to_canonical_json`]
/// does not add one, for exactly this reason).
pub(crate) fn atomic_write(target: &Path, contents: &str) -> Result<()> {
    let parent = target
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .ok_or_else(|| {
            Error::unknown(format!(
                "{}: refusing to write -- no parent directory",
                target.display()
            ))
        })?;
    std::fs::create_dir_all(parent)
        .map_err(|error| Error::unknown(format!("create {}: {error}", parent.display())))?;

    let tmp = temp_path(target);
    let result = write_and_rename(&tmp, target, contents);
    if result.is_err() && tmp.exists() {
        // Best-effort cleanup, mirroring `atomic_write_json`'s `finally`
        // block. Its own failure is not reported: the ORIGINAL error is what
        // the caller needs to see, and a leftover `.tmp` file next to a
        // target that was never replaced is safe to leave for the next
        // writer to overwrite.
        let _ = std::fs::remove_file(&tmp);
    }
    result?;

    // fsync(dir): the write is not durable until the directory entry that
    // now points at `target` is flushed too, not just the file's own bytes.
    let dir = std::fs::File::open(parent)
        .map_err(|error| Error::unknown(format!("open {} for fsync: {error}", parent.display())))?;
    dir.sync_all()
        .map_err(|error| Error::unknown(format!("fsync {}: {error}", parent.display())))?;

    Ok(())
}

fn write_and_rename(tmp: &Path, target: &Path, contents: &str) -> Result<()> {
    use std::io::Write as _;

    let mut file = std::fs::File::create(tmp)
        .map_err(|error| Error::unknown(format!("create {}: {error}", tmp.display())))?;
    file.write_all(contents.as_bytes())
        .map_err(|error| Error::unknown(format!("write {}: {error}", tmp.display())))?;
    file.write_all(b"\n")
        .map_err(|error| Error::unknown(format!("write {}: {error}", tmp.display())))?;
    file.flush()
        .map_err(|error| Error::unknown(format!("flush {}: {error}", tmp.display())))?;
    file.sync_all()
        .map_err(|error| Error::unknown(format!("fsync {}: {error}", tmp.display())))?;
    drop(file);

    std::fs::rename(tmp, target).map_err(|error| {
        Error::unknown(format!(
            "rename {} -> {}: {error}",
            tmp.display(),
            target.display()
        ))
    })
}
