//! Shared fixture teardown for the CLI integration tests.
//!
//! Not every item is used by every test binary, and each `tests/*.rs` is its
//! own crate, so an unused helper here is expected rather than a defect.
#![allow(dead_code)]

use std::{fs, io, path::Path, thread, time::Duration};

/// Remove a fixture tree, tolerating Windows' delayed handle release.
///
/// On Windows a directory cannot be removed while any file inside it still has
/// an open handle, and a handle closed by an exiting child process is not
/// always released by the time the parent's next syscall runs. Six tests failed
/// their teardown -- not their assertions -- with
/// `The process cannot access the file because it is being used by another
/// process. (os error 32)`.
///
/// Retrying is the fix, and bounding the retry is what keeps it from hiding a
/// genuine leak: if the tree is still locked after ten seconds of trying, that is
/// no longer a scheduling artifact and the panic reports it.
pub(crate) fn remove_dir_all(path: &Path) {
    const ATTEMPTS: u32 = 100;
    const BACKOFF: Duration = Duration::from_millis(100);

    let mut last = None;
    for attempt in 0..ATTEMPTS {
        match fs::remove_dir_all(path) {
            Ok(()) => return,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return,
            Err(error) => {
                last = Some(error);
                if attempt + 1 < ATTEMPTS {
                    thread::sleep(BACKOFF);
                }
            }
        }
    }
    // Naming the survivors is the difference between "Windows was slow" and a
    // real handle leak. Without it the next investigation starts from scratch.
    let mut survivors = Vec::new();
    collect(path, path, &mut survivors);
    survivors.sort();
    panic!(
        "cannot remove fixture {} after {ATTEMPTS} attempts: {}\nstill present: {survivors:?}",
        path.display(),
        last.expect("a failure was recorded")
    );
}

/// List every file still present under `root`, relative to it.
///
/// The top-level listing said `[".shepherd"]`, which names a directory and not
/// the handle holding it open. The whole point of the diagnostic is to name the
/// FILE, so the walk goes all the way down.
fn collect(root: &Path, current: &Path, found: &mut Vec<String>) {
    let Ok(entries) = fs::read_dir(current) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect(root, &path, found);
        } else if let Ok(relative) = path.strip_prefix(root) {
            found.push(relative.to_string_lossy().replace('\\', "/"));
        }
    }
}
