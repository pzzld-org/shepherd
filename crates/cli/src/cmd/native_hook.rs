//! Host hook transport over the canonical Rust lifecycle and guard engine.
//!
//! The marketplace plugin calls the installed `shepherd` binary directly. This
//! boundary intentionally owns only host JSON envelopes and output shapes;
//! identity normalization, lifecycle planning, dispatch persistence, and guard
//! evaluation remain in the shared typed engine.

use std::{
    collections::BTreeSet,
    fs,
    io::{self, Read},
    path::Path,
};

use serde::Deserialize;
use shepherd::{
    GuardValue, Harness,
    dispatch::{
        AgentId, DispatchBinding, DispatchPlan, DispatchRequest, LaneId, RawIdentity, Role, RunId,
        plan_lifecycle,
    },
};

use crate::{
    ContextInputs, DispatchService, DispatchStore, ExecutionContext,
    cmd::{dispatch::read_project_id, guard::load_engine},
    interface::{CliError, CliGlobals},
};

const MAX_HOOK_BYTES: usize = 1_048_576;
const DEFAULT_LEASE_MS: u64 = 86_400_000;

#[derive(Clone, Copy)]
pub(super) enum HookHost {
    Claude,
    Codex,
}

impl HookHost {
    const fn capability_source(self) -> &'static str {
        match self {
            Self::Claude => "claude-native-hook",
            Self::Codex => "codex-native-hook",
        }
    }

    const fn harness(self) -> Harness {
        match self {
            Self::Claude => Harness::ClaudeCode,
            Self::Codex => Harness::Codex,
        }
    }

    const fn label(self) -> &'static str {
        match self {
            Self::Claude => "Claude",
            Self::Codex => "Codex",
        }
    }
}

#[derive(Debug, Deserialize)]
struct NativeHookInput {
    hook_event_name: String,
    session_id: String,
    #[serde(default)]
    agent_id: Option<String>,
    #[serde(default)]
    agent_type: Option<String>,
    #[serde(default)]
    tool_use_id: Option<String>,
    #[serde(default)]
    model: Option<String>,
    #[serde(default)]
    #[serde(alias = "claude_version")]
    provider_version: Option<String>,
    #[serde(default)]
    tool_name: Option<String>,
    #[serde(default)]
    tool_input: Option<serde_json::Value>,
    #[serde(default)]
    shepherd_dispatch: Option<ClaudeDispatchBinding>,
}

#[derive(Debug, Default, Deserialize)]
struct ClaudeDispatchBinding {
    #[serde(default)]
    run: Option<String>,
    #[serde(default)]
    role: Option<String>,
    #[serde(default)]
    lane: Option<String>,
    #[serde(default)]
    parent_agent_id: Option<String>,
    #[serde(default)]
    write_scope: Option<Vec<String>>,
    #[serde(default)]
    model: Option<String>,
    #[serde(default)]
    observed_capabilities: Option<BTreeSet<String>>,
    #[serde(default)]
    capability_source: Option<String>,
    #[serde(default)]
    harness_version: Option<String>,
    #[serde(default)]
    provider_version: Option<String>,
    #[serde(default)]
    lease_ms: Option<u64>,
    #[serde(default)]
    expected_revision: Option<u64>,
    #[serde(default)]
    result_artifact: Option<String>,
    #[serde(default)]
    source_agent_id: Option<String>,
    #[serde(default)]
    mode: Option<String>,
}

pub(super) fn run_native_hook(host: HookHost, globals: CliGlobals) -> Result<(), CliError> {
    let input = match read_input(host) {
        Ok(input) => input,
        Err(error) => return emit_parse_error(error, host),
    };
    let pre_tool_use = input.hook_event_name == "PreToolUse";
    let hook_event_name = input.hook_event_name.clone();
    match run_hook(input, host, globals) {
        Ok(HookOutput::Silent) => Ok(()),
        Ok(HookOutput::Context { event, detail }) => emit_json(&context(&event, &detail), host),
        Ok(HookOutput::Deny { detail }) => emit_json(&deny(&hook_event_name, &detail), host),
        // A guard verdict reaches us as `Ok(HookOutput::Deny)`. Every error that
        // lands here is therefore an infrastructure fault in shepherd's own
        // bookkeeping -- an unresolved identity, a run that is not executing,
        // unreadable dispatch state -- and says nothing about whether the
        // requested call is safe. Denying on it strands the session: the repair
        // for broken run state is itself a tool call, and this matcher covers
        // every tool that could perform one. Surface the fault and allow.
        Err(error) if pre_tool_use => emit_json(
            &context(
                "PreToolUse",
                &format!(
                    "dispatch state unavailable, tool allowed: {}",
                    cli_error_detail(&error)
                ),
            ),
            host,
        ),
        Err(error) if hook_event_name == "SubagentStop" => emit_json(
            &block(&format!(
                "native lifecycle hook rejected: {}",
                cli_error_detail(&error)
            )),
            host,
        ),
        Err(error) => emit_json(
            &context(
                &hook_event_name,
                &format!(
                    "native lifecycle hook rejected: {}",
                    cli_error_detail(&error)
                ),
            ),
            host,
        ),
    }
}

enum HookOutput {
    Silent,
    Context { event: String, detail: String },
    Deny { detail: String },
}

fn read_input(host: HookHost) -> Result<NativeHookInput, CliError> {
    let mut bytes = Vec::new();
    io::stdin()
        .take(u64::try_from(MAX_HOOK_BYTES + 1).expect("hook input limit fits in u64"))
        .read_to_end(&mut bytes)
        .map_err(|error| {
            CliError::message(format!("cannot read {} hook input: {error}", host.label()))
        })?;
    if bytes.len() > MAX_HOOK_BYTES {
        return Err(CliError::message(format!(
            "{} hook input exceeds 1048576-byte limit",
            host.label()
        )));
    }
    serde_json::from_slice(&bytes).map_err(|_| {
        CliError::message(format!(
            "{} hook input must be one valid RFC 8259 JSON value",
            host.label()
        ))
    })
}

fn emit_parse_error(error: CliError, host: HookHost) -> Result<(), CliError> {
    let fallback = format!("invalid {} hook input", host.label());
    // The envelope did not parse, so the event it claimed is unknown; a
    // refusal is only meaningful pre-flight, which is what the host asked for.
    emit_json(
        &deny("PreToolUse", error.message_text().unwrap_or(&fallback)),
        host,
    )
}

fn run_hook(
    input: NativeHookInput,
    host: HookHost,
    globals: CliGlobals,
) -> Result<HookOutput, CliError> {
    let identity = RawIdentity::new(
        host.harness(),
        &input.hook_event_name,
        input.session_id.clone(),
        input.agent_id.as_deref(),
        input.agent_type.as_deref(),
        input.tool_use_id.as_deref(),
        input.model.as_deref(),
        input.provider_version.as_deref(),
    )
    .normalize()
    .map_err(|error| CliError::message(error.to_string()))?;
    if matches!(host, HookHost::Codex)
        && matches!(
            input.hook_event_name.as_str(),
            "SubagentStart" | "SubagentStop"
        )
    {
        return Err(CliError::message(
            "Codex native hooks provide no trusted lifecycle correlation for subagents",
        ));
    }
    let binding = binding_for(&input, identity.event.as_str(), host)?;
    let plan = plan_lifecycle(&identity, binding.as_ref())
        .map_err(|error| CliError::message(error.to_string()))?;
    let DispatchPlan::Request(request) = plan else {
        return match plan {
            DispatchPlan::Ignored => Ok(HookOutput::Silent),
            DispatchPlan::Blocked(error) => Err(CliError::message(error.to_string())),
            DispatchPlan::Request(_) => unreachable!("request was matched above"),
        };
    };
    let context = execution_context(globals)?;
    let project_id = read_project_id(&context.project_id_path)?;
    let service = DispatchService::with_context(
        DispatchStore::new(&context.runs_root),
        project_id,
        &context.primary_root,
        &context.registry_path,
    );
    let now = context.now_unix_millis();
    match request {
        DispatchRequest::BindRoot(request) => {
            let request = decode_request(&request)?;
            let response = service.bind_root(request, now).map_err(service_error)?;
            Ok(HookOutput::Context {
                event: input.hook_event_name,
                detail: format!("bound root session to run {}", response.run),
            })
        }
        DispatchRequest::Start(request) => {
            let request = decode_request(&request)?;
            let response = service.start(request, now).map_err(service_error)?;
            Ok(HookOutput::Context {
                event: input.hook_event_name,
                detail: format!("started native dispatch {}", response.agent_id),
            })
        }
        DispatchRequest::Stop(request) => {
            let request = decode_request(&request)?;
            let response = service.stop(request, now).map_err(service_error)?;
            Ok(HookOutput::Context {
                event: input.hook_event_name,
                detail: format!("stopped native dispatch {}", response.agent_id),
            })
        }
        DispatchRequest::Resume(request) => {
            let request = decode_request(&request)?;
            let response = service.resume(request, now).map_err(service_error)?;
            Ok(HookOutput::Context {
                event: input.hook_event_name,
                detail: format!("resumed native dispatch {}", response.record.agent_id),
            })
        }
        DispatchRequest::Resolve(request) => {
            let request = decode_request(&request)?;
            match service.resolve(request, now) {
                // Both tool events resolve, but only the pre-flight one gates.
                // A `PostToolUse` verdict would be advice about a call that
                // already ran, emitted under a `PreToolUse` label -- so the
                // resolution is recorded and the guard is not consulted.
                Ok(_) if input.hook_event_name == "PostToolUse" => Ok(HookOutput::Silent),
                Ok(response) => evaluate_pre_tool_use(&input, &response),
                Err(error) if input.hook_event_name == "PostToolUse" => Ok(HookOutput::Context {
                    event: input.hook_event_name.clone(),
                    detail: format!("dispatch state unavailable after the tool ran: {error}"),
                }),
                Err(error) => Ok(unresolved_pre_tool_use(&input, &context, &error)),
            }
        }
    }
}

fn execution_context(globals: CliGlobals) -> Result<ExecutionContext, CliError> {
    let cwd = std::env::current_dir()
        .map_err(|error| CliError::message(format!("cannot resolve current directory: {error}")))?;
    let mut inputs = ContextInputs::from_environment(cwd)
        .map_err(|error| CliError::message(error.to_string()))?;
    inputs.explicit_config = globals.config;
    inputs.verbosity = globals.verbosity;
    ExecutionContext::discover(inputs).map_err(|error| CliError::message(error.to_string()))
}

fn binding_for(
    input: &NativeHookInput,
    event: &str,
    host: HookHost,
) -> Result<Option<DispatchBinding>, CliError> {
    let Some(raw) = input.shepherd_dispatch.as_ref() else {
        // A host tool envelope carries no `shepherd_dispatch` block -- only a
        // dispatched subagent gets one -- but it does name the tool being
        // requested. `plan_lifecycle` substitutes a default root binding here,
        // and that default carries no tool name, so the resolver derived no
        // write paths and the guard refused every Write and Edit from a root
        // session for lack of them. Forward what the host actually sent.
        if matches!(event, "PreToolUse" | "PostToolUse") {
            let mut binding = DispatchBinding::root(Role::Shepherd, "execution", DEFAULT_LEASE_MS)
                .map_err(|error| CliError::message(error.to_string()))?;
            binding.tool_name = input.tool_name.clone();
            binding.tool_input = input.tool_input.clone();
            return Ok(Some(binding));
        }
        return Ok(None);
    };
    let role = raw
        .role
        .as_deref()
        .map(parse_role)
        .transpose()
        .map_err(|error| CliError::message(error.to_string()))?;
    let write_scope = if event == "SubagentStart" {
        raw.write_scope.clone().ok_or_else(|| {
            CliError::message("write_scope is required for a SubagentStart binding")
        })?
    } else {
        raw.write_scope.clone().unwrap_or_else(|| vec!["**".into()])
    };
    let mut binding = DispatchBinding::new(
        raw.run
            .as_deref()
            .map(RunId::new)
            .transpose()
            .map_err(|error| CliError::message(error.to_string()))?,
        role,
        raw.lane
            .as_deref()
            .map(LaneId::new)
            .transpose()
            .map_err(|error| CliError::message(error.to_string()))?,
        raw.parent_agent_id
            .as_deref()
            .map(AgentId::new)
            .transpose()
            .map_err(|error| CliError::message(error.to_string()))?,
        write_scope,
        raw.model.clone(),
        raw.observed_capabilities.clone().unwrap_or_default(),
        raw.capability_source
            .as_deref()
            .unwrap_or(host.capability_source()),
        raw.harness_version.as_deref().unwrap_or("unknown"),
        raw.provider_version.as_deref(),
        raw.lease_ms.unwrap_or(DEFAULT_LEASE_MS),
    )
    .map_err(|error| CliError::message(error.to_string()))?;
    binding.expected_revision = raw.expected_revision.unwrap_or(1);
    binding.result_artifact = raw.result_artifact.clone();
    binding.source_agent_id = raw
        .source_agent_id
        .as_deref()
        .map(AgentId::new)
        .transpose()
        .map_err(|error| CliError::message(error.to_string()))?;
    binding.mode = raw.mode.clone().unwrap_or_else(|| "execution".into());
    if matches!(event, "PreToolUse" | "PostToolUse") {
        binding.tool_name = input.tool_name.clone();
        binding.tool_input = input.tool_input.clone();
    }
    Ok(Some(binding))
}

fn parse_role(value: &str) -> shepherd::dispatch::DispatchResult<Role> {
    if value.starts_with("shepherd:") {
        Role::from_carrier(value)
    } else {
        Role::from_name(value)
    }
}

fn decode_request<T: serde::de::DeserializeOwned>(
    value: &impl serde::Serialize,
) -> Result<T, CliError> {
    serde_json::to_value(value)
        .and_then(serde_json::from_value)
        .map_err(|error| {
            CliError::message(format!("cannot decode planned native dispatch: {error}"))
        })
}

fn service_error(error: crate::DispatchServiceError) -> CliError {
    CliError::message(error.to_string())
}

fn cli_error_detail(error: &CliError) -> &str {
    error
        .message_text()
        .unwrap_or("native hook rejected the request")
}

fn evaluate_pre_tool_use(
    input: &NativeHookInput,
    resolution: &crate::DispatchResolution,
) -> Result<HookOutput, CliError> {
    // Guard integrity is the one fault class that stays fail-closed: an engine
    // that will not load or evaluate cannot vouch for the call. The self-repair
    // exemption in `guard_unavailable` is what keeps that from bricking a
    // session whose only route back to a working ruleset is a tool call.
    let engine = match load_engine(None) {
        Ok(engine) => engine,
        Err(error) => return Ok(guard_unavailable(input, cli_error_detail(&error))),
    };
    let request = serde_json::json!({
        "role": resolution.role.as_str(),
        "tool_name": input.tool_name.as_deref().unwrap_or_default(),
        "tool_input": input.tool_input.clone().unwrap_or(serde_json::Value::Object(Default::default())),
        "dispatch": resolution,
    });
    let verdict = match engine.evaluate(&GuardValue::from(request)) {
        Ok(verdict) => verdict,
        Err(error) => return Ok(guard_unavailable(input, &error.to_string())),
    };
    if verdict.decision.as_str() == "allow" {
        Ok(HookOutput::Silent)
    } else {
        Ok(HookOutput::Deny {
            detail: verdict
                .reason
                .unwrap_or_else(|| "Shepherd denied this tool request".into()),
        })
    }
}

/// Decide what an unresolved `PreToolUse` means before refusing it.
///
/// Resolution fails for two unrelated reasons, and they deserve opposite
/// answers. Either shepherd's own run bookkeeping is unusable -- in which case
/// the failure says nothing about this tool call, and denying would strand the
/// session, since every repair is itself a tool call -- or the run is healthy
/// and this session is simply not bound to it, which is a genuine refusal.
fn unresolved_pre_tool_use(
    input: &NativeHookInput,
    context: &ExecutionContext,
    error: &crate::DispatchServiceError,
) -> HookOutput {
    if is_self_repair_call(input) {
        return HookOutput::Context {
            event: "PreToolUse".into(),
            detail: format!("dispatch unresolved ({error}); allowed shepherd self-repair"),
        };
    }
    if run_namespace_is_usable(&context.runs_root) {
        return HookOutput::Deny {
            detail: error.to_string(),
        };
    }
    HookOutput::Context {
        event: "PreToolUse".into(),
        detail: format!(
            "no usable run namespace ({error}); tool allowed. \
Repair with `shepherd run layout <run> --repair` \
then `shepherd run set <run> --status executing`."
        ),
    }
}

/// Whether any run is executing with the dispatch directory it needs.
///
/// This is the minimum state shepherd requires to attribute a tool call to a
/// role. Below it, no refusal it issues would be meaningful.
fn run_namespace_is_usable(runs_root: &Path) -> bool {
    let Ok(entries) = fs::read_dir(runs_root) else {
        return false;
    };
    entries.filter_map(Result::ok).any(|entry| {
        let run = entry.path();
        run.join("dispatch").is_dir()
            && fs::read(run.join("run.json"))
                .ok()
                .and_then(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes).ok())
                .is_some_and(|document| document["status"] == "executing")
    })
}

/// Fail closed when the guard engine cannot reach a verdict, except for a bare
/// `shepherd` invocation.
///
/// Without the exemption a damaged ruleset is unrecoverable from inside the
/// session that has to recover it: every repair path is a tool call, and every
/// tool call is denied.
fn guard_unavailable(input: &NativeHookInput, detail: &str) -> HookOutput {
    if is_self_repair_call(input) {
        return HookOutput::Context {
            event: "PreToolUse".into(),
            detail: format!("guard engine unavailable ({detail}); allowed shepherd self-repair"),
        };
    }
    HookOutput::Deny {
        detail: format!("guard engine unavailable: {detail}"),
    }
}

/// True for a `Bash` call that runs `shepherd` and nothing else.
///
/// Shell metacharacters disqualify the call rather than being parsed. This is a
/// deliberately narrow escape hatch, so anything that could chain a second
/// command past it is refused outright.
fn is_self_repair_call(input: &NativeHookInput) -> bool {
    if input.tool_name.as_deref() != Some("Bash") {
        return false;
    }
    let Some(command) = input
        .tool_input
        .as_ref()
        .and_then(|value| value.get("command"))
        .and_then(serde_json::Value::as_str)
    else {
        return false;
    };
    if command.contains([';', '|', '&', '`', '>', '<', '\n', '\r']) || command.contains("$(") {
        return false;
    }
    input_is_shepherd(command.trim_start())
}

fn input_is_shepherd(command: &str) -> bool {
    command
        .strip_prefix("shepherd")
        .is_some_and(|rest| rest.is_empty() || rest.starts_with(char::is_whitespace))
}

fn context(event: &str, detail: &str) -> serde_json::Value {
    serde_json::json!({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": format!("[shepherd] {detail}"),
        }
    })
}

fn deny(event: &str, detail: &str) -> serde_json::Value {
    serde_json::json!({
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": format!("[shepherd] {detail}"),
        }
    })
}

fn block(detail: &str) -> serde_json::Value {
    serde_json::json!({
        "decision": "block",
        "reason": format!("[shepherd] {detail}"),
    })
}

fn emit_json(value: &serde_json::Value, host: HookHost) -> Result<(), CliError> {
    let value = serde_json::to_string(value).map_err(|error| {
        CliError::message(format!(
            "cannot encode {} hook output: {error}",
            host.label()
        ))
    })?;
    println!("{value}");
    Ok(())
}
