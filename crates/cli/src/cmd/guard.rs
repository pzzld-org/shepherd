use std::{
    collections::BTreeMap,
    io::{self, BufRead, Read, Write},
    path::PathBuf,
};

use shepherd::{
    GuardEngine, GuardError, GuardValue, Verdict,
    guard::{PredicateExample, parse_predicate_toml, parse_role_markdown},
};

use crate::interface::CliError;

const MALFORMED_JSON_MESSAGE: &str = "request must be one valid RFC 8259 JSON value";
const GUARD_PROTOCOL: &str = "shepherd/1";
const GUARD_OPERATION: &str = "guard.eval";
const MAX_GUARD_LINE_BYTES: usize = 1_048_576;
const REQUEST_TOO_LARGE_MESSAGE: &str = "guard protocol line exceeds 1048576-byte limit";
const EVAL_REQUEST_TOO_LARGE_MESSAGE: &str = "guard request exceeds 1048576-byte limit";
const INVALID_REQUEST_ID_MESSAGE: &str = "request envelope field `request_id` must be 1-128 ASCII letters, digits, `.`, `-`, `_`, or `:`";

const EMBEDDED_PREDICATE_SOURCES: &[(&str, &str)] = &[
    (
        "dedup-gate.toml",
        include_str!("../../../../content/predicates/dedup-gate.toml"),
    ),
    (
        "dispatch-scope.toml",
        include_str!("../../../../content/predicates/dispatch-scope.toml"),
    ),
    (
        "git-custody.toml",
        include_str!("../../../../content/predicates/git-custody.toml"),
    ),
    (
        "write-boundary.toml",
        include_str!("../../../../content/predicates/write-boundary.toml"),
    ),
];

const EMBEDDED_ROLE_SOURCES: &[(&str, &str)] = &[
    (
        "auditor.md",
        include_str!("../../../../content/roles/auditor.md"),
    ),
    (
        "coder.md",
        include_str!("../../../../content/roles/coder.md"),
    ),
    (
        "conductor.md",
        include_str!("../../../../content/roles/conductor.md"),
    ),
    (
        "critic.md",
        include_str!("../../../../content/roles/critic.md"),
    ),
    (
        "discovery.md",
        include_str!("../../../../content/roles/discovery.md"),
    ),
    (
        "engineer.md",
        include_str!("../../../../content/roles/engineer.md"),
    ),
    (
        "planter.md",
        include_str!("../../../../content/roles/planter.md"),
    ),
    (
        "shepherd.md",
        include_str!("../../../../content/roles/shepherd.md"),
    ),
    (
        "worker.md",
        include_str!("../../../../content/roles/worker.md"),
    ),
];

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
pub struct GuardCmd {
    #[command(subcommand)]
    action: GuardAction,
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
enum GuardAction {
    /// Evaluate one JSON request from stdin.
    Eval(ContentArgs),
    /// Serve line-delimited JSON requests until stdin closes.
    Serve(ContentArgs),
    /// Replay every predicate example.
    Test(ContentArgs),
    /// Explain one loaded predicate.
    Explain(ExplainArgs),
}

#[derive(
    Clone,
    Debug,
    Default,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Args,
    serde::Deserialize,
    serde::Serialize,
)]
struct ContentArgs {
    /// Override the content/ root.
    #[arg(long)]
    content_dir: Option<PathBuf>,
}

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
struct ExplainArgs {
    /// Predicate identifier, such as write-boundary.
    #[arg(value_name = "PREDICATE-ID")]
    predicate_id: String,
    /// Override the content/ root.
    #[arg(long)]
    content_dir: Option<PathBuf>,
}

impl GuardCmd {
    pub(crate) fn run(self) -> Result<(), CliError> {
        match self.action {
            GuardAction::Eval(args) => run_eval(args.content_dir),
            GuardAction::Serve(args) => run_serve(args.content_dir),
            GuardAction::Test(args) => run_test(args.content_dir),
            GuardAction::Explain(args) => run_explain(args),
        }
    }
}

pub(crate) fn load_engine(content_dir: Option<PathBuf>) -> Result<GuardEngine, CliError> {
    let override_dir = content_dir.or_else(|| {
        std::env::var_os("SHEPHERD_CONTENT_DIR")
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
    });
    match override_dir {
        Some(path) => GuardEngine::load_content(path).map_err(engine_error),
        None => load_embedded_engine(),
    }
}

fn load_embedded_engine() -> Result<GuardEngine, CliError> {
    let predicates = EMBEDDED_PREDICATE_SOURCES
        .iter()
        .map(|(name, contents)| parse_predicate_toml(name, contents))
        .collect::<Result<Vec<_>, _>>()
        .map_err(engine_error)?;
    let roles = EMBEDDED_ROLE_SOURCES
        .iter()
        .map(|(name, contents)| parse_role_markdown(name, contents))
        .collect::<Result<Vec<_>, _>>()
        .map_err(engine_error)?;
    GuardEngine::new(predicates, roles).map_err(engine_error)
}

fn engine_error(error: GuardError) -> CliError {
    CliError::message(error.to_string())
}

fn run_eval(content_dir: Option<PathBuf>) -> Result<(), CliError> {
    let mut input = Vec::new();
    io::stdin()
        .take(u64::try_from(MAX_GUARD_LINE_BYTES + 1).expect("guard input limit fits in u64"))
        .read_to_end(&mut input)
        .map_err(|error| CliError::message(format!("cannot read stdin: {error}")))?;
    if input.len() > MAX_GUARD_LINE_BYTES {
        return Err(CliError::message(EVAL_REQUEST_TOO_LARGE_MESSAGE));
    }
    let input = std::str::from_utf8(&input).map_err(|_| {
        CliError::message(format!("malformed JSON on stdin: {MALFORMED_JSON_MESSAGE}"))
    })?;
    let engine = load_engine(content_dir)?;
    let verdict = engine.evaluate_json(input).map_err(|error| match error {
        GuardError::Json(_) => {
            CliError::message(format!("malformed JSON on stdin: {MALFORMED_JSON_MESSAGE}"))
        }
        other => engine_error(other),
    })?;
    write_stdout_line(&verdict.to_wire_json())
}

fn run_serve(content_dir: Option<PathBuf>) -> Result<(), CliError> {
    let engine = load_engine(content_dir)?;
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut input = stdin.lock();
    let mut output = stdout.lock();

    writeln!(
        output,
        "{{\"protocol\": \"{GUARD_PROTOCOL}\", \"ready\": true}}"
    )
    .and_then(|()| output.flush())
    .map_err(output_error)?;

    loop {
        let response = match read_guard_line(&mut input)
            .map_err(|error| CliError::message(format!("cannot read stdin: {error}")))?
        {
            None => break,
            Some(GuardLine::TooLarge) => {
                serve_error_response(None, "request_too_large", REQUEST_TOO_LARGE_MESSAGE)
            }
            Some(GuardLine::Bytes(line)) => match std::str::from_utf8(&line) {
                Ok(line) => match decode_serve_request(line) {
                    Ok(request) => match engine.evaluate(&GuardValue::from(request.payload)) {
                        Ok(verdict) => serve_success_response(&request.request_id, &verdict),
                        Err(_) => serve_error_response(
                            Some(&request.request_id),
                            "evaluation_error",
                            "guard evaluation failed",
                        ),
                    },
                    Err(error) => {
                        serve_error_response(error.request_id.as_deref(), error.code, error.message)
                    }
                },
                Err(_) => serve_error_response(None, "malformed_json", MALFORMED_JSON_MESSAGE),
            },
        };
        writeln!(output, "{response}")
            .and_then(|()| output.flush())
            .map_err(output_error)?;
    }
    Ok(())
}

enum GuardLine {
    Bytes(Vec<u8>),
    TooLarge,
}

fn read_guard_line(input: &mut impl BufRead) -> io::Result<Option<GuardLine>> {
    let mut line = Vec::new();
    let mut too_large = false;
    let mut saw_input = false;

    loop {
        let buffer = input.fill_buf()?;
        if buffer.is_empty() {
            return if saw_input {
                Ok(Some(if too_large {
                    GuardLine::TooLarge
                } else {
                    GuardLine::Bytes(line)
                }))
            } else {
                Ok(None)
            };
        }
        saw_input = true;

        let newline = buffer.iter().position(|byte| *byte == b'\n');
        let payload_len = newline.unwrap_or(buffer.len());
        if !too_large {
            let remaining = MAX_GUARD_LINE_BYTES.saturating_sub(line.len());
            if payload_len > remaining {
                too_large = true;
                line.clear();
            } else {
                line.extend_from_slice(&buffer[..payload_len]);
            }
        }

        input.consume(payload_len + usize::from(newline.is_some()));
        if newline.is_some() {
            return Ok(Some(if too_large {
                GuardLine::TooLarge
            } else {
                GuardLine::Bytes(line)
            }));
        }
    }
}

fn output_error(error: io::Error) -> CliError {
    CliError::message(format!("cannot write stdout: {error}"))
}

struct ServeRequest {
    request_id: String,
    payload: serde_json::Value,
}

struct ServeProtocolError {
    request_id: Option<String>,
    code: &'static str,
    message: &'static str,
}

fn decode_serve_request(line: &str) -> Result<ServeRequest, ServeProtocolError> {
    let value: serde_json::Value = serde_json::from_str(line).map_err(|_| ServeProtocolError {
        request_id: None,
        code: "malformed_json",
        message: MALFORMED_JSON_MESSAGE,
    })?;
    let Some(object) = value.as_object() else {
        return Err(ServeProtocolError {
            request_id: None,
            code: "invalid_envelope",
            message: "request envelope must be a JSON object",
        });
    };
    let request_id = object
        .get("request_id")
        .and_then(serde_json::Value::as_str)
        .filter(|request_id| safe_request_id(request_id))
        .map(str::to_owned);

    match object.get("protocol").and_then(serde_json::Value::as_str) {
        Some(GUARD_PROTOCOL) => {}
        Some(_) => {
            return Err(ServeProtocolError {
                request_id,
                code: "unsupported_protocol",
                message: "request envelope field `protocol` must equal `shepherd/1`",
            });
        }
        None => {
            return Err(ServeProtocolError {
                request_id,
                code: "invalid_envelope",
                message: "request envelope field `protocol` must equal `shepherd/1`",
            });
        }
    }

    let Some(request_id) = request_id else {
        return Err(ServeProtocolError {
            request_id: None,
            code: "invalid_request_id",
            message: INVALID_REQUEST_ID_MESSAGE,
        });
    };

    match object.get("op").and_then(serde_json::Value::as_str) {
        Some(GUARD_OPERATION) => {}
        _ => {
            return Err(ServeProtocolError {
                request_id: Some(request_id),
                code: "unsupported_operation",
                message: "request envelope field `op` must equal `guard.eval`",
            });
        }
    }

    let Some(payload) = object.get("payload") else {
        return Err(ServeProtocolError {
            request_id: Some(request_id),
            code: "invalid_envelope",
            message: "request envelope must contain `payload`",
        });
    };

    if object
        .keys()
        .any(|key| !matches!(key.as_str(), "protocol" | "request_id" | "op" | "payload"))
    {
        return Err(ServeProtocolError {
            request_id: Some(request_id),
            code: "invalid_envelope",
            message: "request envelope contains unsupported fields",
        });
    }

    Ok(ServeRequest {
        request_id,
        payload: payload.clone(),
    })
}

fn safe_request_id(request_id: &str) -> bool {
    !request_id.is_empty()
        && request_id.len() <= 128
        && request_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_' | b':'))
}

fn serve_success_response(request_id: &str, verdict: &Verdict) -> String {
    let request_id = serde_json::to_string(request_id).expect("a string always serializes as JSON");
    format!(
        "{{\"protocol\": \"{GUARD_PROTOCOL}\", \"request_id\": {request_id}, \"ok\": true, \"result\": {}}}",
        verdict.to_wire_json()
    )
}

fn serve_error_response(request_id: Option<&str>, code: &str, message: &str) -> String {
    let request_id = request_id.map_or_else(
        || String::from("null"),
        |value| serde_json::to_string(value).expect("a string always serializes as JSON"),
    );
    let code = serde_json::to_string(code).expect("a string always serializes as JSON");
    let message = serde_json::to_string(message).expect("a string always serializes as JSON");
    format!(
        "{{\"protocol\": \"{GUARD_PROTOCOL}\", \"request_id\": {request_id}, \"ok\": false, \"error\": {{\"code\": {code}, \"message\": {message}}}}}"
    )
}

fn write_stdout_line(line: &str) -> Result<(), CliError> {
    let stdout = io::stdout();
    let mut output = stdout.lock();
    writeln!(output, "{line}")
        .and_then(|()| output.flush())
        .map_err(output_error)
}

fn run_test(content_dir: Option<PathBuf>) -> Result<(), CliError> {
    let engine = load_engine(content_dir)?;
    let mut passed = 0usize;
    let mut total = 0usize;
    let mut failures = Vec::new();

    for (predicate_id, predicate) in engine.predicates() {
        for example in &predicate.examples {
            total += 1;
            let verdict = evaluate_example(&engine, predicate_id, example)?;
            let expected_halt = example.halt_code.as_deref();
            let matches = verdict.decision.as_str() == example.result
                && expected_halt.is_none_or(|halt| verdict.halt_code.as_deref() == Some(halt));
            if matches {
                passed += 1;
            } else {
                failures.push(format!(
                    "FAIL {predicate_id}/{}: expected result={} halt_code={}, got decision={} halt_code={}",
                    example.name,
                    quoted_value_repr(&example.result),
                    optional_value_repr(expected_halt),
                    quoted_value_repr(verdict.decision.as_str()),
                    optional_value_repr(verdict.halt_code.as_deref()),
                ));
            }
        }
    }

    for failure in failures {
        eprintln!("{failure}");
    }
    println!("{passed}/{total} examples passed");
    if total == 0 {
        eprintln!(
            "ERROR: zero content/predicates/*.toml examples loaded -- refusing to report a green suite"
        );
        return Err(CliError::reported());
    }
    if passed != total {
        return Err(CliError::reported());
    }
    Ok(())
}

fn evaluate_example(
    engine: &GuardEngine,
    predicate_id: &str,
    example: &PredicateExample,
) -> Result<Verdict, CliError> {
    let request = GuardValue::Object(BTreeMap::from([
        ("predicate".into(), GuardValue::from(predicate_id)),
        ("role".into(), example.role.clone()),
        ("action".into(), GuardValue::from(example.action.clone())),
        (
            "context".into(),
            GuardValue::Object(example.flattened_context()),
        ),
    ]));
    engine.evaluate(&request).map_err(engine_error)
}

fn quoted_value_repr(value: &str) -> String {
    format!("'{}'", value.replace('\\', "\\\\").replace('\'', "\\'"))
}

fn optional_value_repr(value: Option<&str>) -> String {
    value.map_or_else(|| String::from("None"), quoted_value_repr)
}

fn run_explain(args: ExplainArgs) -> Result<(), CliError> {
    let engine = load_engine(args.content_dir)?;
    let Some(predicate) = engine.predicate(&args.predicate_id) else {
        let known = engine
            .predicates()
            .map(|(id, _)| id)
            .collect::<Vec<_>>()
            .join(", ");
        let known = if known.is_empty() {
            String::from("(none loaded)")
        } else {
            known
        };
        return Err(CliError::message(format!(
            "no such predicate `{}` -- known: {known}",
            args.predicate_id
        )));
    };

    println!(
        "{} (v{}) -- {}\n\nRules:",
        predicate.id, predicate.version, predicate.description
    );
    for rule in &predicate.rules {
        println!(
            "  [{}] action={} effect={}\n    {}",
            rule.id, rule.action, rule.effect, rule.description
        );
    }
    println!("\nExamples:");
    for example in &predicate.examples {
        let halt = example
            .halt_code
            .as_deref()
            .filter(|value| !value.is_empty())
            .map_or_else(String::new, |value| format!(" halt_code={value}"));
        println!(
            "  [{}] {} -> {}{halt}",
            example.kind, example.name, example.result
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{fs, path::Path};

    use super::{EMBEDDED_PREDICATE_SOURCES, EMBEDDED_ROLE_SOURCES};

    #[test]
    fn embedded_guard_inventory_exactly_matches_the_canonical_source_tree() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../content");
        assert_eq!(
            source_names(&root.join("predicates"), "toml"),
            embedded_names(EMBEDDED_PREDICATE_SOURCES),
            "additions and removals must update the standalone binary's embedded predicate inventory"
        );
        assert_eq!(
            source_names(&root.join("roles"), "md"),
            embedded_names(EMBEDDED_ROLE_SOURCES),
            "additions and removals must update the standalone binary's embedded role inventory"
        );
    }

    fn source_names(directory: &Path, extension: &str) -> Vec<String> {
        let mut names = fs::read_dir(directory)
            .expect("read canonical content directory")
            .map(|entry| entry.expect("read canonical content entry").path())
            .filter(|path| path.extension().and_then(|value| value.to_str()) == Some(extension))
            .map(|path| {
                path.file_name()
                    .and_then(|value| value.to_str())
                    .expect("canonical content filename is UTF-8")
                    .to_owned()
            })
            .collect::<Vec<_>>();
        names.sort();
        names
    }

    fn embedded_names(sources: &[(&str, &str)]) -> Vec<String> {
        let mut names = sources
            .iter()
            .map(|(name, _)| (*name).to_owned())
            .collect::<Vec<_>>();
        names.sort();
        names
    }
}
