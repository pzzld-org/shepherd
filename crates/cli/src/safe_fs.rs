//! Reparse-point-rejecting filesystem primitives for non-unix targets.
//!
//! WHY THIS EXISTS.
//!
//! Every mutating and reading path in this crate is paired: a `#[cfg(unix)]`
//! implementation built on `rustix`'s descriptor-anchored `openat`/`unlinkat`
//! family, and a non-unix twin. The twins used to be five families of
//! `Err("... unavailable on this platform")`, so the Windows binary this
//! repository builds, packages, signs, and publishes could not create
//! `.shepherd/`, could not bind a session, and could not store a run. Nothing
//! observed that, because the test suite had never run on Windows (#321).
//!
//! WHAT THIS GUARANTEES, STATED HONESTLY.
//!
//! The unix side is anchored: it walks a chain of directory descriptors, so a
//! component swapped after the check is still not the component the next
//! `openat` resolves against. Windows has no `openat` in `std`; the equivalent
//! needs `NtCreateFile` with a `RootDirectory` handle, which is ntdll FFI.
//!
//! So this module gives a weaker but real guarantee, and names it rather than
//! implying parity:
//!
//! * **The final component is never traversed.** Opens pass
//!   `FILE_FLAG_OPEN_REPARSE_POINT`, so if the leaf is (or becomes) a symlink
//!   or junction, the handle refers to the reparse point itself. An attacker
//!   who wins the race gets us reading link data, never their target file.
//! * **No ancestor may be a reparse point.** Each component is checked with
//!   `symlink_metadata`, which does not follow the entry it names.
//! * **Publication is no-clobber.** `create_new` is `CREATE_NEW`, which fails
//!   if anything exists at the name, and `hard_link` is `CreateHardLinkW`,
//!   which fails if the link name exists. Those are the same two refusals the
//!   unix side gets from `O_EXCL` and `linkat`.
//!
//! The residual gap is an ancestor swapped between its check and its use. That
//! is a narrower window than "the whole feature is disabled", it is written
//! down here rather than discovered later, and closing it is tracked work, not
//! a silent omission.

#![cfg(not(unix))]

use std::{
    fs::{self, File, OpenOptions},
    io::{self, Read, Write},
    path::{Component, Path},
};

/// `FILE_FLAG_OPEN_REPARSE_POINT`: open the link, never what it points at.
#[cfg(windows)]
const OPEN_REPARSE_POINT: u32 = 0x0020_0000;

/// The error a caller should surface for a path that is, or is under, a link.
pub(crate) fn symlink_refused(path: &Path) -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidInput,
        format!(
            "refusing to follow a symlink or junction at {}",
            path.display()
        ),
    )
}

/// Whether `path` names a link, without following it.
pub(crate) fn is_link(path: &Path) -> io::Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(metadata) => Ok(metadata.file_type().is_symlink()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

/// Refuse if any component of `path` that exists is a link.
///
/// Absent components are not a violation: a caller creating a tree walks a path
/// whose tail does not exist yet, and absence is reported by the operation that
/// needs it, not by this check.
pub(crate) fn reject_link_components(path: &Path) -> io::Result<()> {
    let mut walked = std::path::PathBuf::new();
    for component in path.components() {
        walked.push(component.as_os_str());
        // A prefix or root is not a stat-able entry and cannot be a link. On
        // Windows a bare `\\?\C:` answers `Incorrect function. (os error 1)`,
        // so probing one turns every path walk into a hard error.
        if matches!(component, Component::Prefix(_) | Component::RootDir)
            || walked.parent().is_none()
        {
            continue;
        }
        if is_link(&walked)? {
            return Err(symlink_refused(&walked));
        }
    }
    Ok(())
}

/// Open an existing regular file without traversing a link at any component.
pub(crate) fn open_regular_nofollow(path: &Path) -> io::Result<File> {
    reject_link_components(path)?;
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() {
        return Err(symlink_refused(path));
    }
    if !metadata.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("not a regular file: {}", path.display()),
        ));
    }
    open_leaf_nofollow(path)
}

#[cfg(windows)]
fn open_leaf_nofollow(path: &Path) -> io::Result<File> {
    use std::os::windows::fs::OpenOptionsExt;

    OpenOptions::new()
        .read(true)
        .custom_flags(OPEN_REPARSE_POINT)
        .open(path)
}

#[cfg(not(windows))]
fn open_leaf_nofollow(path: &Path) -> io::Result<File> {
    OpenOptions::new().read(true).open(path)
}

/// Read at most `limit` bytes from a regular file, refusing links.
///
/// Reads `limit + 1` so an over-limit file is detected rather than truncated
/// into a document that parses and is wrong.
pub(crate) fn read_regular_nofollow(path: &Path, limit: u64) -> io::Result<Vec<u8>> {
    let file = open_regular_nofollow(path)?;
    let mut bytes = Vec::new();
    file.take(limit.saturating_add(1)).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("file exceeds {limit}-byte limit: {}", path.display()),
        ));
    }
    Ok(bytes)
}

/// `true` if `path` is an existing regular file that is not a link.
pub(crate) fn regular_exists(path: &Path) -> io::Result<bool> {
    if reject_link_components(path).is_err() {
        return Ok(false);
    }
    match fs::symlink_metadata(path) {
        Ok(metadata) => Ok(metadata.is_file() && !metadata.file_type().is_symlink()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

/// `true` if `path` is an existing directory that is not a link or junction.
pub(crate) fn directory_exists(path: &Path) -> io::Result<bool> {
    if reject_link_components(path).is_err() {
        return Ok(false);
    }
    match fs::symlink_metadata(path) {
        Ok(metadata) => Ok(metadata.is_dir() && !metadata.file_type().is_symlink()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

/// Names of the regular, non-link children of `root`, sorted byte-wise.
///
/// Sorted so callers render a stable order on every platform; `read_dir`
/// order is filesystem-defined and differs between NTFS and ext4.
pub(crate) fn regular_children(root: &Path) -> io::Result<Vec<String>> {
    reject_link_components(root)?;
    let mut names = Vec::new();
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            continue;
        }
        if let Some(name) = entry.file_name().to_str() {
            names.push(name.to_owned());
        }
    }
    names.sort_unstable();
    Ok(names)
}

/// Names of the directory, non-link children of `root`, sorted byte-wise.
pub(crate) fn directory_children(root: &Path) -> io::Result<Vec<String>> {
    reject_link_components(root)?;
    let mut names = Vec::new();
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        if !entry.file_type()?.is_dir() {
            continue;
        }
        if let Some(name) = entry.file_name().to_str() {
            names.push(name.to_owned());
        }
    }
    names.sort_unstable();
    Ok(names)
}

/// Create `path` with `bytes`, refusing to replace anything already there.
///
/// Returns whether THIS call published it. `false` means a racing writer won,
/// which is the fact atomic rollback needs so it only removes what it made.
///
/// Content is written and flushed to a sibling temporary first, then published
/// by `hard_link`, so the destination name never exists holding a partial
/// document. That is the same two-step the unix side performs with `O_EXCL`
/// plus `linkat`.
pub(crate) fn write_no_clobber(path: &Path, bytes: &[u8]) -> io::Result<bool> {
    reject_link_components(path)?;
    let parent = path.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("path has no parent directory: {}", path.display()),
        )
    })?;
    let name = path.file_name().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("path has no file name: {}", path.display()),
        )
    })?;
    if is_link(path)? {
        return Err(symlink_refused(path));
    }
    let temporary = parent.join(format!(
        ".{}.shepherd.tmp.{}",
        name.to_string_lossy(),
        std::process::id()
    ));
    let _ = fs::remove_file(&temporary);
    let publish = (|| -> io::Result<bool> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        match fs::hard_link(&temporary, path) {
            Ok(()) => Ok(true),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => Ok(false),
            Err(error) => Err(error),
        }
    })();
    let _ = fs::remove_file(&temporary);
    publish
}

/// Replace `path` with `bytes` atomically, refusing links.
///
/// Unlike [`write_no_clobber`], an existing destination is expected and
/// replaced. `fs::rename` on Windows replaces an existing file atomically
/// within a volume, and the temporary is a sibling so the volume always
/// matches.
pub(crate) fn replace_atomic(path: &Path, bytes: &[u8]) -> io::Result<()> {
    reject_link_components(path)?;
    if is_link(path)? {
        return Err(symlink_refused(path));
    }
    let parent = path.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("path has no parent directory: {}", path.display()),
        )
    })?;
    let name = path.file_name().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("path has no file name: {}", path.display()),
        )
    })?;
    fs::create_dir_all(parent)?;
    let temporary = parent.join(format!(
        ".{}.shepherd.swap.{}",
        name.to_string_lossy(),
        std::process::id()
    ));
    let _ = fs::remove_file(&temporary);
    let result = (|| -> io::Result<()> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

/// Create `name` under `parent` if absent. Returns whether THIS call made it.
pub(crate) fn ensure_directory(parent: &Path, name: &str) -> io::Result<bool> {
    let target = parent.join(name);
    if is_link(&target)? {
        return Err(symlink_refused(&target));
    }
    match fs::create_dir(&target) {
        Ok(()) => Ok(true),
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            if fs::symlink_metadata(&target)?.is_dir() {
                Ok(false)
            } else {
                Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("not a directory: {}", target.display()),
                ))
            }
        }
        Err(error) => Err(error),
    }
}

/// Remove a regular file without following a link at any component. An absent
/// file is success: the caller asked for it to be gone, and it is.
pub(crate) fn remove_file_nofollow(path: &Path) -> io::Result<()> {
    reject_link_components(path)?;
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}

/// Remove a directory without following a link at any component.
pub(crate) fn remove_directory_nofollow(path: &Path) -> io::Result<()> {
    reject_link_components(path)?;
    match fs::remove_dir(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}

#[cfg(test)]
mod tests {
    //! These run only on non-unix targets, which is the point: they are the
    //! first tests this repository has ever had for the half of the CLI that
    //! ships in the Windows binary.

    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn fixture(label: &str) -> std::path::PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock is after epoch")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "shepherd-safe-fs-{label}-{}-{nonce:x}",
            std::process::id()
        ));
        fs::create_dir_all(&root).expect("create fixture");
        root
    }

    #[test]
    fn no_clobber_publishes_once_and_reports_the_loser() {
        let root = fixture("no-clobber");
        let target = root.join("record.json");

        assert!(write_no_clobber(&target, b"first").expect("first publish"));
        assert!(!write_no_clobber(&target, b"second").expect("second publish"));
        assert_eq!(fs::read(&target).expect("read back"), b"first");

        // The temporary must not survive either outcome, or the next publish
        // inherits a stale sibling and the directory accumulates garbage.
        let leftovers: Vec<_> = fs::read_dir(&root)
            .expect("list")
            .filter_map(Result::ok)
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .filter(|name| name.contains("shepherd.tmp"))
            .collect();
        assert!(leftovers.is_empty(), "left temporaries: {leftovers:?}");
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn replace_atomic_overwrites_where_no_clobber_refuses() {
        let root = fixture("replace");
        let target = root.join("run.json");
        assert!(write_no_clobber(&target, b"before").expect("publish"));
        replace_atomic(&target, b"after").expect("replace");
        assert_eq!(fs::read(&target).expect("read back"), b"after");
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn read_refuses_an_over_limit_file_instead_of_truncating() {
        let root = fixture("limit");
        let target = root.join("big.json");
        fs::write(&target, vec![b'x'; 64]).expect("write");

        assert_eq!(
            read_regular_nofollow(&target, 64)
                .expect("at the limit")
                .len(),
            64
        );
        let error = read_regular_nofollow(&target, 63).expect_err("over the limit");
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn absence_and_wrong_type_are_distinguishable() {
        let root = fixture("kinds");
        let absent = read_regular_nofollow(&root.join("nope.json"), 16).expect_err("absent");
        assert_eq!(absent.kind(), io::ErrorKind::NotFound);

        let directory = root.join("a-directory");
        fs::create_dir(&directory).expect("mkdir");
        let wrong = read_regular_nofollow(&directory, 16).expect_err("not a regular file");
        assert_eq!(wrong.kind(), io::ErrorKind::InvalidInput);

        assert!(!regular_exists(&directory).expect("probe"));
        assert!(directory_exists(&directory).expect("probe"));
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn ensure_directory_reports_only_what_it_created() {
        let root = fixture("ensure");
        assert!(ensure_directory(&root, "runs").expect("first"));
        assert!(!ensure_directory(&root, "runs").expect("second"));

        // A name already taken by a FILE is a hard error, not a silent success:
        // the caller is about to write children into it.
        fs::write(root.join("occupied"), b"x").expect("write");
        let error = ensure_directory(&root, "occupied").expect_err("occupied by a file");
        assert_eq!(error.kind(), io::ErrorKind::InvalidInput);
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn children_are_sorted_and_split_by_kind() {
        let root = fixture("children");
        for name in ["c.json", "a.json", "b.json"] {
            fs::write(root.join(name), b"{}").expect("write");
        }
        fs::create_dir(root.join("nested")).expect("mkdir");

        assert_eq!(
            regular_children(&root).expect("files"),
            vec!["a.json", "b.json", "c.json"]
        );
        assert_eq!(directory_children(&root).expect("dirs"), vec!["nested"]);
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn removal_is_idempotent() {
        let root = fixture("remove");
        let file = root.join("gone.json");
        fs::write(&file, b"x").expect("write");
        remove_file_nofollow(&file).expect("remove");
        remove_file_nofollow(&file).expect("removing an absent file is success");

        let directory = root.join("gone-dir");
        fs::create_dir(&directory).expect("mkdir");
        remove_directory_nofollow(&directory).expect("remove");
        remove_directory_nofollow(&directory).expect("removing an absent directory is success");
        fs::remove_dir_all(root).expect("cleanup");
    }

    /// The security property, exercised against a real link rather than a
    /// hand-built error. Windows needs Developer Mode or elevation to create a
    /// symlink, so the test SKIPS when it cannot make one -- and says so, so a
    /// skip is never mistaken for a pass.
    #[test]
    fn a_link_is_refused_rather_than_followed() {
        let root = fixture("links");
        let secret = root.join("secret.json");
        fs::write(&secret, b"{\"secret\":true}").expect("write");
        let link = root.join("link.json");

        #[cfg(windows)]
        let created = std::os::windows::fs::symlink_file(&secret, &link).is_ok();
        #[cfg(not(windows))]
        let created = false;

        if !created {
            eprintln!("skipped: this environment cannot create a symlink");
            fs::remove_dir_all(root).expect("cleanup");
            return;
        }

        let error = read_regular_nofollow(&link, 64).expect_err("must refuse a link");
        assert_eq!(error.kind(), io::ErrorKind::InvalidInput);
        assert!(is_link(&link).expect("probe"));
        assert!(!regular_exists(&link).expect("probe"));

        // And an ancestor link is refused too, not just the leaf.
        let through = link.join("child.json");
        assert!(reject_link_components(&through).is_err());
        fs::remove_dir_all(root).expect("cleanup");
    }
}
