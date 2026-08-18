//! Native JSON boundary for dispatch lifecycle and identity operations.

use std::path::Path;

#[cfg(unix)]
use std::io::Read;

use serde::de::DeserializeOwned;
use shepherd::dispatch::ProjectId;

use crate::{
    ContextInputs, DispatchService, DispatchStore, ExecutionContext,
    interface::{CliError, CliGlobals},
};

const MAX_REQUEST_BYTES: usize = 1_048_576;
const MALFORMED_JSON_MESSAGE: &str = "request must be one valid RFC 8259 JSON value";

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Args,
    serde::Deserialize,
    serde::Serialize,
)]
pub struct DispatchCmd {
    #[command(subcommand)]
    action: DispatchAction,
}

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Subcommand,
    serde::Deserialize,
    serde::Serialize,
)]
enum DispatchAction {
    /// Bind the primary SessionStart identity to the active run.
    BindRoot,
    /// Publish a new native subagent dispatch record.
    Start,
    /// Resolve one native hook identity against its durable record.
    Resolve,
    /// Monotonically stop a native subagent and attach an artifact reference.
    Stop,
    /// Continue an existing dispatch with a fresh native identity.
    Resume,
}

impl DispatchCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let cwd = std::env::current_dir().map_err(|error| {
            CliError::message(format!("cannot resolve current directory: {error}"))
        })?;
        let mut inputs = ContextInputs::from_environment(cwd)
            .map_err(|error| CliError::message(error.to_string()))?;
        inputs.explicit_config = globals.config;
        inputs.verbosity = globals.verbosity;
        let mut context = ExecutionContext::discover(inputs)
            .map_err(|error| CliError::message(error.to_string()))?;
        let project_id = read_project_id(&context.project_id_path)?;
        let service = DispatchService::with_context(
            DispatchStore::new(&context.runs_root),
            project_id,
            &context.primary_root,
            &context.registry_path,
        );
        let now = context.now_unix_millis();

        match self.action {
            DispatchAction::BindRoot => {
                let response = service
                    .bind_root(read_request(&mut context)?, now)
                    .map_err(service_error)?;
                write_response(&mut context, &response)
            }
            DispatchAction::Start => {
                let response = service
                    .start(read_request(&mut context)?, now)
                    .map_err(service_error)?;
                write_response(&mut context, &response)
            }
            DispatchAction::Resolve => {
                let response = service
                    .resolve(read_request(&mut context)?, now)
                    .map_err(service_error)?;
                write_response(&mut context, &response)
            }
            DispatchAction::Stop => {
                let response = service
                    .stop(read_request(&mut context)?, now)
                    .map_err(service_error)?;
                write_response(&mut context, &response)
            }
            DispatchAction::Resume => {
                let response = service
                    .resume(read_request(&mut context)?, now)
                    .map_err(service_error)?;
                write_response(&mut context, &response)
            }
        }
    }
}

fn read_request<T: DeserializeOwned>(context: &mut ExecutionContext) -> Result<T, CliError> {
    let mut input = String::new();
    loop {
        let before = input.len();
        let read = context
            .read_stdin(&mut input)
            .map_err(|error| CliError::message(format!("cannot read stdin: {error}")))?;
        if input.len() > MAX_REQUEST_BYTES {
            return Err(CliError::message(format!(
                "dispatch request exceeds {MAX_REQUEST_BYTES}-byte limit"
            )));
        }
        if read == 0 {
            break;
        }
        if input.len() == before {
            return Err(CliError::message(
                "stdin boundary reported bytes without appending input",
            ));
        }
    }
    serde_json::from_str(&input).map_err(|_| CliError::message(MALFORMED_JSON_MESSAGE))
}

fn write_response<T: serde::Serialize>(
    context: &mut ExecutionContext,
    response: &T,
) -> Result<(), CliError> {
    let mut bytes = serde_json::to_vec(response)
        .map_err(|error| CliError::message(format!("cannot encode stdout: {error}")))?;
    bytes.push(b'\n');
    context
        .write_stdout(&bytes)
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

fn service_error(error: crate::DispatchServiceError) -> CliError {
    CliError::message(error.to_string())
}

/// Distinguishes which artifact a `NOFOLLOW`-guarded read names, so the
/// remediation text can differ by subject: `shepherd init` mints exactly
/// one artifact, `.shepherd/project.json`, and nothing else. Pointing an
/// ordinary missing file back at `init` is as wrong as pointing a missing
/// identity file anywhere else.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ReadSubject {
    /// `.shepherd/project.json`, the one artifact `shepherd init` creates.
    ProjectIdentity,
    /// Any other regular file read through the same descriptor-safe path.
    File,
}

impl ReadSubject {
    /// Only the descriptor-safe classifier renders this, and that classifier is
    /// unix-only. The type itself is not: both the unix and non-unix readers
    /// take a `ReadSubject`, so it cannot be gated without splitting every
    /// caller.
    // `not(test)` matters: `read_subject_labels_only_project_identity` calls this
    // on every platform, so in a non-unix LIB TEST build the item is live and
    // the expectation would be unfulfilled -- which `-D warnings` rejects just
    // as hard as the dead code it was written to tolerate.
    #[cfg_attr(
        all(not(unix), not(test)),
        expect(dead_code, reason = "only the unix classifier renders a label")
    )]
    fn open_label(self) -> &'static str {
        match self {
            Self::ProjectIdentity => "project identity ",
            Self::File => "",
        }
    }

    /// The message a caller anywhere in the crate should surface for a
    /// `NOFOLLOW`-guarded read whose target is simply absent.
    pub(crate) fn not_found_message(self, path: &Path) -> String {
        match self {
            Self::ProjectIdentity => format!(
                "project not scaffolded — run `shepherd init`: {}",
                path.display()
            ),
            Self::File => format!("no such file: {}", path.display()),
        }
    }

    /// The message a caller anywhere in the crate should surface for a
    /// `NOFOLLOW`-guarded read whose target exists but is not a regular file.
    pub(crate) fn not_a_regular_file_message(self, path: &Path) -> String {
        match self {
            Self::ProjectIdentity => {
                format!("project identity is not a regular file: {}", path.display())
            }
            Self::File => format!("not a regular file: {}", path.display()),
        }
    }
}

/// Classifies a `NOFOLLOW`-guarded `open` failure by its real errno rather
/// than assuming every failure is a refused symlink. `ENOENT` (plain
/// absence) and `ELOOP`/refused-`NOFOLLOW` (an actual symlink) are
/// different failures with different remediations, and conflating them
/// sends operators chasing a security incident that a `find -type l`
/// already rules out.
#[cfg(unix)]
pub(crate) fn classify_nofollow_open_error(
    subject: ReadSubject,
    path: &Path,
    error: rustix::io::Errno,
) -> CliError {
    use rustix::io::Errno;

    match error {
        Errno::NOENT => CliError::message(subject.not_found_message(path)),
        Errno::ISDIR => CliError::message(subject.not_a_regular_file_message(path)),
        Errno::LOOP => CliError::message(format!(
            "cannot open {}{} without following symlinks: {error}",
            subject.open_label(),
            path.display()
        )),
        other => CliError::message(format!(
            "cannot open {}{}: {other}",
            subject.open_label(),
            path.display()
        )),
    }
}

pub(crate) fn read_project_id(path: &Path) -> Result<ProjectId, CliError> {
    let bytes = read_regular_nofollow(path, MAX_REQUEST_BYTES)?;
    let document: serde_json::Value = serde_json::from_slice(&bytes).map_err(|error| {
        CliError::message(format!(
            "invalid project identity document {}: {error}",
            path.display()
        ))
    })?;
    let id = document
        .as_object()
        .and_then(|object| object.get("id"))
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| {
            CliError::message(format!(
                "invalid project identity document {}: field `id` must be a string",
                path.display()
            ))
        })?;
    ProjectId::new(id).map_err(|error| CliError::message(error.to_string()))
}

#[cfg(unix)]
fn read_regular_nofollow(path: &Path, limit: usize) -> Result<Vec<u8>, CliError> {
    use std::fs::File;

    use rustix::fs::{FileType, Mode, OFlags, open};

    let descriptor = open(
        path,
        OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
        Mode::empty(),
    )
    .map_err(|error| classify_nofollow_open_error(ReadSubject::ProjectIdentity, path, error))?;
    let stat = rustix::fs::fstat(&descriptor).map_err(|error| {
        CliError::message(format!(
            "cannot inspect project identity {}: {error}",
            path.display()
        ))
    })?;
    if !FileType::from_raw_mode(stat.st_mode).is_file() {
        return Err(CliError::message(
            ReadSubject::ProjectIdentity.not_a_regular_file_message(path),
        ));
    }
    let file = File::from(descriptor);
    let mut bytes = Vec::new();
    file.take(u64::try_from(limit + 1).expect("identity limit fits in u64"))
        .read_to_end(&mut bytes)
        .map_err(|error| {
            CliError::message(format!(
                "cannot read project identity {}: {error}",
                path.display()
            ))
        })?;
    if bytes.len() > limit {
        return Err(CliError::message(format!(
            "project identity exceeds {limit}-byte limit: {}",
            path.display()
        )));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_regular_nofollow(path: &Path, _limit: usize) -> Result<Vec<u8>, CliError> {
    Err(CliError::message(format!(
        "race-safe project identity reads are unavailable on this platform: {}",
        path.display()
    )))
}

#[cfg(test)]
mod tests {
    use std::{
        fs, io,
        path::PathBuf,
        sync::{Arc, Mutex},
    };

    use crate::{
        Clock, ContextInputs, ExecutionContext, IdentifierSource, IoBoundary, RuntimeBindings,
        SystemHost,
    };

    use super::{ReadSubject, read_request, write_response};
    // Both callers are `#[cfg(unix)]`: they build a real symlink and let the
    // kernel produce a real ELOOP, which Windows cannot do.
    #[cfg(unix)]
    use super::read_project_id;

    #[derive(Debug)]
    struct FixedClock;

    impl Clock for FixedClock {
        fn now_unix_millis(&self) -> i64 {
            1_000
        }
    }

    #[derive(Debug)]
    struct FixedIds;

    impl IdentifierSource for FixedIds {
        fn next_id(&mut self) -> String {
            "fixed-id".into()
        }
    }

    #[derive(Debug)]
    struct FixedIo {
        input: String,
        consumed: bool,
        stdout: Arc<Mutex<Vec<u8>>>,
    }

    impl IoBoundary for FixedIo {
        fn read_stdin(&mut self, buffer: &mut String) -> io::Result<usize> {
            if self.consumed {
                return Ok(0);
            }
            buffer.push_str(&self.input);
            self.consumed = true;
            Ok(self.input.len())
        }

        fn write_stdout(&mut self, bytes: &[u8]) -> io::Result<()> {
            self.stdout
                .lock()
                .expect("stdout lock")
                .extend_from_slice(bytes);
            Ok(())
        }

        fn write_stderr(&mut self, _bytes: &[u8]) -> io::Result<()> {
            Ok(())
        }
    }

    fn context(input: &str) -> (ExecutionContext, Arc<Mutex<Vec<u8>>>, PathBuf) {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "shepherd-dispatch-io-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).expect("create fixture");
        let stdout = Arc::new(Mutex::new(Vec::new()));
        let runtime = RuntimeBindings::new(
            Box::new(FixedClock),
            Box::new(FixedIds),
            Box::new(FixedIo {
                input: input.into(),
                consumed: false,
                stdout: Arc::clone(&stdout),
            }),
        );
        let context = ExecutionContext::resolve_with(
            ContextInputs {
                start_dir: root.clone(),
                primary_fallback: Some(root.clone()),
                ..ContextInputs::default()
            },
            &SystemHost,
            runtime,
        )
        .expect("resolve context");
        (context, stdout, root)
    }

    // GE2 (unit level): `.shepherd/project.json` sits behind
    // `context::validate_resolved_project_paths`, which already refuses any
    // symlink at that exact leaf path before `ExecutionContext::discover`
    // ever returns (see `crates/cli/src/context.rs::validate_resolved_project_path`).
    // That means dispatch.rs's own `NOFOLLOW` refusal for the project
    // identity subject cannot be exercised end to end through the CLI: the
    // earlier, unrelated guard always wins the race. It CAN be exercised
    // directly, since `read_project_id` and its NOFOLLOW open never go
    // through `ExecutionContext` at all — they take a bare path. This test
    // constructs a real symlink and lets the kernel produce a real `ELOOP`,
    // satisfying the "no hand-built errno" rule while proving the exact
    // code this lane changed.
    #[cfg(unix)]
    #[test]
    fn read_project_id_refuses_a_symlinked_identity_with_the_security_wording() {
        use std::{
            os::unix::fs::symlink,
            time::{SystemTime, UNIX_EPOCH},
        };

        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("shepherd-dispatch-identity-symlink-{suffix}"));
        fs::create_dir_all(&root).expect("fixture");
        let target = root.join("identity-target.json");
        fs::write(&target, br#"{"id":"018f47ce-72d7-7f64-9eb1-2f651d521c2a"}"#)
            .expect("identity target");
        let link = root.join("project.json");
        symlink(&target, &link).expect("symlink identity");

        let error = read_project_id(&link).expect_err("symlinked identity must be refused");
        let message = error.message_text().expect("error carries a message");
        assert!(
            message.contains("without following symlinks"),
            "message={message}"
        );
        assert!(message.contains("project identity"), "message={message}");
        assert!(!message.contains("not scaffolded"), "message={message}");
        fs::remove_dir_all(root).expect("cleanup");
    }

    // GE1 (unit level companion): the same function on a plainly absent path
    // must not repeat the symlink wording, and must name the real
    // remediation. Reproduced end to end in `tests/dispatch_cli.rs`; this
    // pins the same behaviour directly against `read_project_id`.
    #[cfg(unix)]
    #[test]
    fn read_project_id_reports_absence_as_not_scaffolded() {
        let root = std::env::temp_dir().join(format!(
            "shepherd-dispatch-identity-absent-{}",
            std::process::id()
        ));
        fs::create_dir_all(&root).expect("fixture");
        let absent = root.join("project.json");

        let error = read_project_id(&absent).expect_err("absent identity must be refused");
        let message = error.message_text().expect("error carries a message");
        assert!(
            message.contains("project not scaffolded"),
            "message={message}"
        );
        assert!(
            !message.contains("without following symlinks"),
            "message={message}"
        );
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn read_subject_labels_only_project_identity() {
        assert_eq!(
            ReadSubject::ProjectIdentity.open_label(),
            "project identity "
        );
        assert_eq!(ReadSubject::File.open_label(), "");
    }

    #[test]
    fn dispatch_json_uses_the_execution_context_io_boundary() {
        let (mut context, stdout, root) = context("{\n  \"value\": 7\n}\n");
        let request: serde_json::Value = read_request(&mut context).expect("read request");
        assert_eq!(request, serde_json::json!({"value": 7}));
        write_response(&mut context, &serde_json::json!({"ok": true})).expect("write response");
        assert_eq!(&*stdout.lock().expect("stdout lock"), b"{\"ok\":true}\n");
        fs::remove_dir_all(root).expect("remove fixture");
    }

    #[test]
    fn dispatch_json_rejects_trailing_values_after_reading_to_eof() {
        let (mut context, _stdout, root) = context("{}\n{\"second\":true}\n");
        let error = read_request::<serde_json::Value>(&mut context).expect_err("trailing value");
        assert_eq!(error.message_text(), Some(super::MALFORMED_JSON_MESSAGE));
        fs::remove_dir_all(root).expect("remove fixture");
    }

    #[test]
    fn dispatch_json_applies_the_limit_to_the_total_input() {
        let oversized = format!("\"{}\"", "x".repeat(super::MAX_REQUEST_BYTES));
        let (mut context, _stdout, root) = context(&oversized);
        let error = read_request::<serde_json::Value>(&mut context).expect_err("oversized input");
        assert!(
            error
                .message_text()
                .is_some_and(|message| message.contains("exceeds"))
        );
        fs::remove_dir_all(root).expect("remove fixture");
    }
}
