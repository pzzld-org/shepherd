//! Claude Code hook transport over the canonical Rust lifecycle and guard engine.
//!
//! The marketplace plugin calls the installed `shepherd` binary directly. This
//! boundary intentionally owns only Claude's JSON envelope and output shape;
//! identity normalization, lifecycle planning, dispatch persistence, and guard
//! evaluation remain in the shared typed engine.

use std::{
    collections::BTreeSet,
    io::{self, Read},
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
pub struct ClaudeHookCmd;

#[derive(Debug, Deserialize)]
struct ClaudeHookInput {
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
    claude_version: Option<String>,
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

impl ClaudeHookCmd {
    pub(crate) fn run(self, globals: CliGlobals) -> Result<(), CliError> {
        let input = match read_input() {
            Ok(input) => input,
            Err(error) => return emit_parse_error(error),
        };
        let pre_tool_use = input.hook_event_name == "PreToolUse";
        let hook_event_name = input.hook_event_name.clone();
        match run_hook(input, globals) {
            Ok(HookOutput::Silent) => Ok(()),
            Ok(HookOutput::Context { event, detail }) => emit_json(&context(&event, &detail)),
            Ok(HookOutput::Deny { detail }) => emit_json(&deny(&detail)),
            Err(error) if pre_tool_use => emit_json(&deny(cli_error_detail(&error))),
            Err(error) if hook_event_name == "SubagentStop" => emit_json(&block(&format!(
                "native lifecycle hook rejected: {}",
                cli_error_detail(&error)
            ))),
            Err(error) => emit_json(&context(
                &hook_event_name,
                &format!(
                    "native lifecycle hook rejected: {}",
                    cli_error_detail(&error)
                ),
            )),
        }
    }
}

enum HookOutput {
    Silent,
    Context { event: String, detail: String },
    Deny { detail: String },
}

fn read_input() -> Result<ClaudeHookInput, CliError> {
    let mut bytes = Vec::new();
    io::stdin()
        .take(u64::try_from(MAX_HOOK_BYTES + 1).expect("hook input limit fits in u64"))
        .read_to_end(&mut bytes)
        .map_err(|error| CliError::message(format!("cannot read Claude hook input: {error}")))?;
    if bytes.len() > MAX_HOOK_BYTES {
        return Err(CliError::message(
            "Claude hook input exceeds 1048576-byte limit",
        ));
    }
    serde_json::from_slice(&bytes)
        .map_err(|_| CliError::message("Claude hook input must be one valid RFC 8259 JSON value"))
}

fn emit_parse_error(error: CliError) -> Result<(), CliError> {
    emit_json(&deny(
        error.message_text().unwrap_or("invalid Claude hook input"),
    ))
}

fn run_hook(input: ClaudeHookInput, globals: CliGlobals) -> Result<HookOutput, CliError> {
    let identity = RawIdentity::new(
        Harness::ClaudeCode,
        &input.hook_event_name,
        input.session_id.clone(),
        input.agent_id.as_deref(),
        input.agent_type.as_deref(),
        input.tool_use_id.as_deref(),
        input.model.as_deref(),
        input.claude_version.as_deref(),
    )
    .normalize()
    .map_err(|error| CliError::message(error.to_string()))?;
    let binding = binding_for(&input, identity.event.as_str())?;
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
            let response = service.resolve(request, now).map_err(service_error)?;
            evaluate_pre_tool_use(&input, &response)
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

fn binding_for(input: &ClaudeHookInput, event: &str) -> Result<Option<DispatchBinding>, CliError> {
    let Some(raw) = input.shepherd_dispatch.as_ref() else {
        return Ok(None);
    };
    let role = raw
        .role
        .as_deref()
        .map(parse_role)
        .transpose()
        .map_err(|error| CliError::message(error.to_string()))?;
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
        raw.write_scope.clone().unwrap_or_else(|| vec!["**".into()]),
        raw.model.clone(),
        raw.observed_capabilities.clone().unwrap_or_default(),
        raw.capability_source
            .as_deref()
            .unwrap_or("claude-native-hook"),
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
        .unwrap_or("native Claude hook rejected the request")
}

fn evaluate_pre_tool_use(
    input: &ClaudeHookInput,
    resolution: &crate::DispatchResolution,
) -> Result<HookOutput, CliError> {
    let engine = load_engine(None)?;
    let request = serde_json::json!({
        "role": resolution.role.as_str(),
        "tool_name": input.tool_name.as_deref().unwrap_or_default(),
        "tool_input": input.tool_input.clone().unwrap_or(serde_json::Value::Object(Default::default())),
        "dispatch": resolution,
    });
    let verdict = engine
        .evaluate(&GuardValue::from(request))
        .map_err(|error| CliError::message(error.to_string()))?;
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

fn context(event: &str, detail: &str) -> serde_json::Value {
    serde_json::json!({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": format!("[shepherd] {detail}"),
        }
    })
}

fn deny(detail: &str) -> serde_json::Value {
    serde_json::json!({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
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

fn emit_json(value: &serde_json::Value) -> Result<(), CliError> {
    let value = serde_json::to_string(value)
        .map_err(|error| CliError::message(format!("cannot encode Claude hook output: {error}")))?;
    println!("{value}");
    Ok(())
}
