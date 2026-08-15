/*
    Appellation: atomic <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! Atomic write: tempfile -> fsync -> rename -> fsync(dir).
//!
//! The publication sequence is fixed: create a same-directory candidate with
//! `O_CREAT|O_EXCL`, write the canonical bytes plus one newline, flush and
//! fsync the file, rename it over the target, then fsync the parent directory.
//! Directory fsync is a POSIX durability boundary and fails explicitly on a
//! host that cannot provide it.
//!
//! No `std::process` anywhere in this module: `crates/core` may not depend on
//! it (decision 8, enforced by `boundaries.yml`'s process/argv grep), so the
//! temp filename's uniqueness comes from a wall-clock timestamp plus an
//! in-process atomic counter instead of a process id. That means two
//! *different OS processes* can independently compute the same
//! `(nanos, counter)` candidate and both call [`temp_path`] for the same
//! `target` at (effectively) the same nanosecond — the in-process counter
//! only rules out a same-process collision. [`create_temp_file_exclusive`]
//! is what turns that possible collision into a retry instead of silent
//! corruption: it opens each candidate with `O_CREAT|O_EXCL`
//! (`create_new(true)`), so a colliding candidate fails atomically with
//! `ErrorKind::AlreadyExists` rather than truncating whatever the other
//! writer already has open there.
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use crate::error::{Error, Result};

static ATOMIC_WRITE_SEQ: AtomicU64 = AtomicU64::new(0);

/// Attempts before [`create_temp_file_exclusive`] gives up. Each attempt is
/// an independently generated `(nanos, counter)` candidate; a collision on
/// every one of a hundred of them would mean something structurally wrong
/// (a stuck clock, an exhausted counter) rather than an ordinary two-process
/// race, which is expected to resolve within one or two retries.
const MAX_TEMP_NAME_ATTEMPTS: u32 = 100;

/// A candidate path in `target`'s own directory. Same directory matters: a
/// rename is only atomic within one filesystem, and a tempfile placed
/// elsewhere (e.g. `$TMPDIR`) can land on a different one.
///
/// This is a *candidate*, not a guaranteed-unique name — see the module doc
/// comment. [`create_temp_file_exclusive`] is what actually enforces
/// uniqueness, by retrying with a fresh candidate on collision.
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

/// Exclusively create a tempfile from a sequence of candidate paths. Each candidate is
/// opened with `O_CREAT|O_EXCL` (`create_new(true)`), which atomically fails
/// with `ErrorKind::AlreadyExists` if the path already exists instead of
/// truncating whatever is there. On that specific error, a fresh candidate
/// is pulled from `next_candidate` and retried, bounded by
/// [`MAX_TEMP_NAME_ATTEMPTS`].
///
/// Parameterized over the candidate generator (rather than calling
/// [`temp_path`] directly) so a test can force a collision deterministically
/// — seed the first candidate with a path a fixture already created, then
/// hand back a genuinely free one — without depending on a real two-process
/// race or wall-clock timing.
///
/// Returns the path that was exclusively created and the open handle
/// positioned at its start, ready for writing.
///
/// # Errors
///
/// Returns [`Error::Unknown`] if a candidate fails to open for a reason
/// other than `AlreadyExists`, or if every one of
/// [`MAX_TEMP_NAME_ATTEMPTS`] candidates collided.
fn create_temp_file_exclusive(
    mut next_candidate: impl FnMut() -> PathBuf,
) -> Result<(PathBuf, std::fs::File)> {
    let mut attempts = 0u32;
    loop {
        let candidate = next_candidate();
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(file) => return Ok((candidate, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                attempts += 1;
                if attempts >= MAX_TEMP_NAME_ATTEMPTS {
                    return Err(Error::unknown(format!(
                        "{}: giving up after {MAX_TEMP_NAME_ATTEMPTS} tempfile-name collisions",
                        candidate.display()
                    )));
                }
            }
            Err(error) => {
                return Err(Error::unknown(format!(
                    "create {}: {error}",
                    candidate.display()
                )));
            }
        }
    }
}

/// Write `contents` to `target` atomically with the pinned run-store
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

    write_and_rename(target, contents, || temp_path(target))?;

    // fsync(dir): the write is not durable until the directory entry that
    // now points at `target` is flushed too, not just the file's own bytes.
    let dir = std::fs::File::open(parent)
        .map_err(|error| Error::unknown(format!("open {} for fsync: {error}", parent.display())))?;
    dir.sync_all()
        .map_err(|error| Error::unknown(format!("fsync {}: {error}", parent.display())))?;

    Ok(())
}

/// Exclusively create a tempfile near `target` (via `next_candidate` and
/// [`create_temp_file_exclusive`]), write `contents` + a trailing `\n` to
/// it, fsync it, then rename it onto `target`.
///
/// Split out from [`atomic_write`] so the collision-retry path is
/// unit-testable directly: a test supplies `next_candidate` and inspects
/// `target` afterward, without needing `atomic_write`'s directory-creation
/// or closing directory-fsync steps. `pub(super)` (rather than private) is
/// exactly that seam: visible to `run::tests::atomic_io`, invisible outside
/// the `run` module.
///
/// Cleanup on failure only ever targets the ONE tempfile this call itself
/// exclusively created (`tmp`, below) — never a path merely returned by
/// `next_candidate`, since a collision there means that path belongs to
/// another writer.
pub(super) fn write_and_rename(
    target: &Path,
    contents: &str,
    next_candidate: impl FnMut() -> PathBuf,
) -> Result<()> {
    use std::io::Write as _;

    let (tmp, mut file) = create_temp_file_exclusive(next_candidate)?;

    let write_result = (|| -> Result<()> {
        file.write_all(contents.as_bytes())
            .map_err(|error| Error::unknown(format!("write {}: {error}", tmp.display())))?;
        file.write_all(b"\n")
            .map_err(|error| Error::unknown(format!("write {}: {error}", tmp.display())))?;
        file.flush()
            .map_err(|error| Error::unknown(format!("flush {}: {error}", tmp.display())))?;
        file.sync_all()
            .map_err(|error| Error::unknown(format!("fsync {}: {error}", tmp.display())))
    })();
    drop(file);

    if let Err(error) = write_result {
        // Best-effort cleanup, mirroring `atomic_write_json`'s `finally`
        // block. Its own failure is not reported: the ORIGINAL error is what
        // the caller needs to see, and a leftover `.tmp` file next to a
        // target that was never replaced is safe to leave for the next
        // writer to overwrite.
        let _ = std::fs::remove_file(&tmp);
        return Err(error);
    }

    std::fs::rename(&tmp, target).map_err(|error| {
        let rename_error = Error::unknown(format!(
            "rename {} -> {}: {error}",
            tmp.display(),
            target.display()
        ));
        let _ = std::fs::remove_file(&tmp);
        rename_error
    })
}
