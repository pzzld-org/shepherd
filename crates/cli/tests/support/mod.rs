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
/// genuine leak: if the tree is still locked after a second of trying, that is
/// no longer a scheduling artifact and the panic reports it.
pub(crate) fn remove_dir_all(path: &Path) {
    const ATTEMPTS: u32 = 20;
    const BACKOFF: Duration = Duration::from_millis(50);

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
    panic!(
        "cannot remove fixture {} after {ATTEMPTS} attempts: {}",
        path.display(),
        last.expect("a failure was recorded")
    );
}
