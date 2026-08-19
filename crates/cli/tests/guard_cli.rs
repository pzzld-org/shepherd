use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Output, Stdio},
    time::{SystemTime, UNIX_EPOCH},
};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_shepherd")
}

fn content_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../content")
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after epoch")
        .as_nanos();
    let path = std::env::temp_dir().join(format!("shepherd-cli-{label}-{nonce:x}"));
    fs::create_dir_all(&path).expect("create fixture directory");
    path
}

fn run(args: &[&str], stdin: &str) -> Output {
    run_bytes(args, stdin.as_bytes())
}

fn run_bytes(args: &[&str], stdin: &[u8]) -> Output {
    let mut child = Command::new(binary())
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn shepherd");
    child
        .stdin
        .take()
        .expect("stdin is piped")
        .write_all(stdin)
        .expect("write request");
    child.wait_with_output().expect("wait for shepherd")
}

fn isolated_binary(label: &str) -> (PathBuf, PathBuf) {
    let fixture = unique_temp_dir(label);
    let copied = fixture.join("shepherd");
    fs::copy(binary(), &copied).expect("copy standalone shepherd binary");
    (fixture, copied)
}

/// Parses a `guard test` summary line of the exact form `N/M examples
/// passed` and asserts every loaded example passed (`N == M`) and the
/// corpus was not empty (`N > 0`).
///
/// This parses instead of pinning a corpus-size literal on purpose:
/// `guard.rs:424-430` already fails closed and refuses to report a green
/// suite when `total == 0`, and `guard_test_fails_closed_on_an_empty_corpus`
/// (below) pins that exact `0/0` refusal. A literal count here would
/// re-break every time `content/predicates/*.toml` gains an example -- do
/// not "simplify" this back into a hardcoded string.
fn assert_all_examples_passed(stdout: &[u8]) {
    let text = std::str::from_utf8(stdout).expect("guard test stdout is UTF-8");
    let line = text.trim_end_matches('\n');
    let counts = line.strip_suffix(" examples passed").unwrap_or_else(|| {
        panic!("guard test stdout does not match `N/M examples passed`: {text:?}")
    });
    let (passed, total) = counts.split_once('/').unwrap_or_else(|| {
        panic!("guard test stdout does not match `N/M examples passed`: {text:?}")
    });
    let passed: u64 = passed
        .parse()
        .unwrap_or_else(|_| panic!("passed count is not a number: {text:?}"));
    let total: u64 = total
        .parse()
        .unwrap_or_else(|_| panic!("total count is not a number: {text:?}"));
    assert_eq!(passed, total, "not every example passed: {text:?}");
    assert!(total > 0, "guard example corpus is empty: {text:?}");
}

#[test]
fn guard_eval_emits_one_clean_versioned_wire_verdict() {
    let content = content_dir();
    let output = run(
        &[
            "guard",
            "eval",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        r#"{"role":"coder","tool_name":"Bash","tool_input":{"command":"git status"}}"#,
    );

    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(output.stdout, b"{\"decision\": \"allow\"}\n");
    assert!(output.stderr.is_empty());
}

#[test]
fn guard_eval_non_string_role_preserves_the_oracle_unresolved_verdict() {
    let content = content_dir();
    let output = run(
        &[
            "guard",
            "eval",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        r#"{"role":42,"tool_name":"Write"}"#,
    );

    assert!(output.status.success());
    assert_eq!(
        output.stdout,
        b"{\"decision\": \"unresolved\", \"reason\": \"unknown role `42`\", \"missing\": [\"role_facts\"]}\n"
    );
    assert!(output.stderr.is_empty());
}

#[test]
fn guard_eval_safe_bash_does_not_require_a_role() {
    let content = content_dir();
    let output = run(
        &[
            "guard",
            "eval",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        r#"{"tool_name":"Bash","tool_input":{"command":"printf safe"}}"#,
    );

    assert!(output.status.success());
    assert_eq!(output.stdout, b"{\"decision\": \"allow\"}\n");
    assert!(output.stderr.is_empty());
}

#[test]
fn guard_eval_rejects_every_malformed_or_nonstandard_json_with_one_stable_error() {
    let content = content_dir();
    for input in [
        "",
        " \t\r\n",
        "not-json\n",
        "{",
        r#"{"role":}"#,
        r#"{"role":"coder",}"#,
        r#"{"role":"unterminated}"#,
        r#"{"role":"\uZZZZ"}"#,
        "00",
        "{} {}",
        "NaN",
        "Infinity",
        "-Infinity",
        r#"{"value":1e999}"#,
    ] {
        let output = run(
            &[
                "guard",
                "eval",
                "--content-dir",
                content.to_str().expect("UTF-8 content path"),
            ],
            input,
        );

        assert_eq!(output.status.code(), Some(1), "input={input:?}");
        assert!(output.stdout.is_empty(), "input={input:?}");
        assert_eq!(
            String::from_utf8(output.stderr).expect("UTF-8 stderr"),
            "ERROR: malformed JSON on stdin: request must be one valid RFC 8259 JSON value\n",
            "input={input:?}"
        );
    }
}

#[test]
fn guard_eval_bounds_stdin_and_accepts_the_exact_limit() {
    const MAX_GUARD_INPUT_BYTES: usize = 1_048_576;

    let content = content_dir();
    let prefix = concat!(
        "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"printf safe\"},",
        "\"padding\":\"",
    );
    let suffix = "\"}";
    let at_limit = format!(
        "{prefix}{}{suffix}",
        "x".repeat(MAX_GUARD_INPUT_BYTES - prefix.len() - suffix.len())
    );
    assert_eq!(at_limit.len(), MAX_GUARD_INPUT_BYTES);
    let accepted = run(
        &[
            "guard",
            "eval",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        &at_limit,
    );
    assert!(accepted.status.success());
    assert_eq!(accepted.stdout, b"{\"decision\": \"allow\"}\n");

    let oversized = run(
        &[
            "guard",
            "eval",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        &"x".repeat(MAX_GUARD_INPUT_BYTES + 1),
    );
    assert_eq!(oversized.status.code(), Some(1));
    assert!(oversized.stdout.is_empty());
    assert_eq!(
        oversized.stderr,
        b"ERROR: guard request exceeds 1048576-byte limit\n"
    );
}

#[test]
fn guard_eval_invalid_utf8_is_one_stable_engine_error() {
    let content = content_dir();
    let output = run_bytes(
        &[
            "guard",
            "eval",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        &[0xff],
    );
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert_eq!(
        output.stderr,
        b"ERROR: malformed JSON on stdin: request must be one valid RFC 8259 JSON value\n"
    );
}

#[test]
fn guard_serve_survives_a_bad_line_and_preserves_response_order() {
    let content = content_dir();
    let output = run(
        &[
            "guard",
            "serve",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        concat!(
            "not-json\n",
            "{\"protocol\":\"shepherd/1\",\"request_id\":\"rust-test-1\",",
            "\"op\":\"guard.eval\",\"payload\":{\"role\":\"coder\",",
            "\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git status\"}}}\n",
        ),
    );

    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let lines: Vec<_> = String::from_utf8(output.stdout)
        .expect("UTF-8 stdout")
        .lines()
        .map(String::from)
        .collect();
    assert_eq!(lines[0], r#"{"protocol": "shepherd/1", "ready": true}"#);
    assert_eq!(
        lines[1],
        r#"{"protocol": "shepherd/1", "request_id": null, "ok": false, "error": {"code": "malformed_json", "message": "request must be one valid RFC 8259 JSON value"}}"#
    );
    assert_eq!(
        lines[2],
        r#"{"protocol": "shepherd/1", "request_id": "rust-test-1", "ok": true, "result": {"decision": "allow"}}"#
    );
}

#[test]
fn guard_serve_rejects_unversioned_and_malformed_envelopes_without_losing_correlation() {
    let content = content_dir();
    let output = run(
        &[
            "guard",
            "serve",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        concat!(
            "{\"role\":\"coder\",\"tool_name\":\"Bash\"}\n",
            "{\"protocol\":\"shepherd/0\",\"request_id\":\"bad-version\",",
            "\"op\":\"guard.eval\",\"payload\":{}}\n",
            "{\"protocol\":\"shepherd/1\",\"request_id\":\"ok-2\",",
            "\"op\":\"guard.eval\",\"payload\":{\"role\":\"coder\",\"tool_name\":\"Bash\",",
            "\"tool_input\":{\"command\":\"printf safe\"}}}\n",
        ),
    );

    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let lines: Vec<_> = String::from_utf8(output.stdout)
        .expect("UTF-8 stdout")
        .lines()
        .map(String::from)
        .collect();
    assert_eq!(lines.len(), 4);
    assert_eq!(
        lines[1],
        r#"{"protocol": "shepherd/1", "request_id": null, "ok": false, "error": {"code": "invalid_envelope", "message": "request envelope field `protocol` must equal `shepherd/1`"}}"#
    );
    assert_eq!(
        lines[2],
        r#"{"protocol": "shepherd/1", "request_id": "bad-version", "ok": false, "error": {"code": "unsupported_protocol", "message": "request envelope field `protocol` must equal `shepherd/1`"}}"#
    );
    assert_eq!(
        lines[3],
        r#"{"protocol": "shepherd/1", "request_id": "ok-2", "ok": true, "result": {"decision": "allow"}}"#
    );
}

#[test]
fn guard_serve_rejects_unsafe_request_ids_and_unknown_operations() {
    let content = content_dir();
    let output = run(
        &[
            "guard",
            "serve",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        concat!(
            "{\"protocol\":\"shepherd/1\",\"request_id\":\"unsafe id\",",
            "\"op\":\"guard.eval\",\"payload\":{}}\n",
            "{\"protocol\":\"shepherd/1\",\"request_id\":\"op-1\",",
            "\"op\":\"guard.write\",\"payload\":{}}\n",
        ),
    );

    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    let lines: Vec<_> = String::from_utf8(output.stdout)
        .expect("UTF-8 stdout")
        .lines()
        .map(String::from)
        .collect();
    assert_eq!(
        lines[1],
        r#"{"protocol": "shepherd/1", "request_id": null, "ok": false, "error": {"code": "invalid_request_id", "message": "request envelope field `request_id` must be 1-128 ASCII letters, digits, `.`, `-`, `_`, or `:`"}}"#
    );
    assert_eq!(
        lines[2],
        r#"{"protocol": "shepherd/1", "request_id": "op-1", "ok": false, "error": {"code": "unsupported_operation", "message": "request envelope field `op` must equal `guard.eval`"}}"#
    );
}

#[test]
fn guard_serve_bounds_each_line_and_recovers_at_the_next_frame() {
    const MAX_GUARD_LINE_BYTES: usize = 1_048_576;

    let content = content_dir();
    let prefix = concat!(
        "{\"protocol\":\"shepherd/1\",\"request_id\":\"at-limit-1\",",
        "\"op\":\"guard.eval\",\"payload\":{\"tool_name\":\"Bash\",",
        "\"tool_input\":{\"command\":\"printf safe\"},\"padding\":\"",
    );
    let suffix = "\"}}";
    let mut input = String::from(prefix);
    input.push_str(&"x".repeat(MAX_GUARD_LINE_BYTES - prefix.len() - suffix.len()));
    input.push_str(suffix);
    assert_eq!(input.len(), MAX_GUARD_LINE_BYTES);
    input.push('\n');
    input.push_str(&"x".repeat(MAX_GUARD_LINE_BYTES + 1));
    input.push('\n');
    input.push_str(concat!(
        "{\"protocol\":\"shepherd/1\",\"request_id\":\"after-large-1\",",
        "\"op\":\"guard.eval\",\"payload\":{\"tool_name\":\"Bash\",",
        "\"tool_input\":{\"command\":\"printf safe\"}}}\n",
    ));
    let output = run(
        &[
            "guard",
            "serve",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        &input,
    );

    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let lines: Vec<_> = String::from_utf8(output.stdout)
        .expect("UTF-8 stdout")
        .lines()
        .map(String::from)
        .collect();
    assert_eq!(lines.len(), 4);
    assert_eq!(
        lines[1],
        r#"{"protocol": "shepherd/1", "request_id": "at-limit-1", "ok": true, "result": {"decision": "allow"}}"#
    );
    assert_eq!(
        lines[2],
        r#"{"protocol": "shepherd/1", "request_id": null, "ok": false, "error": {"code": "request_too_large", "message": "guard protocol line exceeds 1048576-byte limit"}}"#
    );
    assert_eq!(
        lines[3],
        r#"{"protocol": "shepherd/1", "request_id": "after-large-1", "ok": true, "result": {"decision": "allow"}}"#
    );
}

#[test]
fn guard_serve_contains_invalid_utf8_to_one_frame() {
    let content = content_dir();
    let mut input = vec![0xff, b'\n'];
    input.extend_from_slice(
        concat!(
            "{\"protocol\":\"shepherd/1\",\"request_id\":\"after-utf8-1\",",
            "\"op\":\"guard.eval\",\"payload\":{\"tool_name\":\"Bash\",",
            "\"tool_input\":{\"command\":\"printf safe\"}}}\n",
        )
        .as_bytes(),
    );
    let output = run_bytes(
        &[
            "guard",
            "serve",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        &input,
    );

    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    let lines: Vec<_> = String::from_utf8(output.stdout)
        .expect("UTF-8 stdout")
        .lines()
        .map(String::from)
        .collect();
    assert_eq!(lines.len(), 3);
    assert_eq!(
        lines[1],
        r#"{"protocol": "shepherd/1", "request_id": null, "ok": false, "error": {"code": "malformed_json", "message": "request must be one valid RFC 8259 JSON value"}}"#
    );
    assert_eq!(
        lines[2],
        r#"{"protocol": "shepherd/1", "request_id": "after-utf8-1", "ok": true, "result": {"decision": "allow"}}"#
    );
}

#[test]
fn installed_binary_uses_complete_embedded_guard_content_without_repo_or_plugin_files() {
    let (fixture, copied) = isolated_binary("embedded-content");
    let output = Command::new(&copied)
        .args(["guard", "test"])
        .current_dir(&fixture)
        .env_remove("SHEPHERD_CONTENT_DIR")
        .env("CLAUDE_PLUGIN_ROOT", fixture.join("poisoned-plugin-root"))
        .output()
        .expect("run isolated shepherd binary");

    assert!(
        output.status.success(),
        "status={:?} stderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stderr)
    );
    assert_all_examples_passed(&output.stdout);
    assert!(output.stderr.is_empty());
    assert_eq!(
        fs::read_dir(&fixture)
            .expect("isolated install directory remains readable")
            .count(),
        1,
        "the standalone command must not create or discover content beside itself"
    );
    fs::remove_dir_all(fixture).expect("remove fixture");
}

#[test]
fn guard_eval_reports_a_closed_stdout_without_panicking() {
    let content = content_dir();
    let mut child = Command::new(binary())
        .args([
            "guard",
            "eval",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn shepherd");
    drop(child.stdout.take().expect("stdout is piped"));
    child
        .stdin
        .take()
        .expect("stdin is piped")
        .write_all(br#"{"role":"coder","tool_name":"Bash","tool_input":{"command":"git status"}}"#)
        .expect("write request");
    let output = child.wait_with_output().expect("wait for shepherd");

    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8(output.stderr).expect("UTF-8 stderr");
    assert!(
        stderr.starts_with("ERROR: cannot write stdout:"),
        "{stderr}"
    );
    assert!(!stderr.contains("panicked at"), "{stderr}");
}

#[test]
fn guard_test_fails_closed_on_an_empty_corpus() {
    let fixture = unique_temp_dir("empty-corpus");
    fs::create_dir_all(fixture.join("predicates")).expect("create empty predicates");
    fs::create_dir_all(fixture.join("roles")).expect("create empty roles");

    let output = run(
        &[
            "guard",
            "test",
            "--content-dir",
            fixture.to_str().expect("UTF-8 fixture path"),
        ],
        "",
    );

    assert_eq!(output.status.code(), Some(1));
    assert_eq!(output.stdout, b"0/0 examples passed\n");
    assert_eq!(
        String::from_utf8(output.stderr).expect("UTF-8 stderr"),
        "ERROR: zero content/predicates/*.toml examples loaded -- refusing to report a green suite\n"
    );
    fs::remove_dir_all(fixture).expect("remove fixture");
}

#[test]
fn guard_test_replays_the_complete_live_corpus() {
    let content = content_dir();
    let output = run(
        &[
            "guard",
            "test",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        "",
    );

    assert!(
        output.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_all_examples_passed(&output.stdout);
    assert!(output.stderr.is_empty());
}

#[test]
fn guard_explain_reports_unknown_predicate_without_mutation() {
    let content = content_dir();
    let output = run(
        &[
            "guard",
            "explain",
            "missing",
            "--content-dir",
            content.to_str().expect("UTF-8 content path"),
        ],
        "",
    );

    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8(output.stderr).expect("UTF-8 stderr"),
        "ERROR: no such predicate `missing` -- known: dedup-gate, dispatch-scope, git-custody, write-boundary\n"
    );
}

#[test]
fn guard_help_is_clean_and_side_effect_free() {
    let fixture = unique_temp_dir("help");
    let output = Command::new(binary())
        .args(["guard", "--help"])
        .current_dir(&fixture)
        .output()
        .expect("run guard help");

    assert!(
        output.status.success(),
        "status={:?} stderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let stdout = String::from_utf8(output.stdout).expect("UTF-8 help");
    for command in ["eval", "serve", "test", "explain"] {
        assert!(stdout.contains(command), "missing {command} in {stdout}");
    }
    assert_eq!(
        fs::read_dir(&fixture)
            .expect("fixture remains readable")
            .count(),
        0,
        "help must not create config, cache, or registry state"
    );
    fs::remove_dir_all(fixture).expect("remove fixture");
}
