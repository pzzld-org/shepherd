import {
  componentBinding,
  planWithComponent,
} from "../../component-runtime/src/index.mjs";
import { normalizeClaudeWithComponent } from "./identity.mjs";

// Lifecycle policy is component-owned. This module only joins Claude's
// envelope to the typed component records.
export function planClaudeLifecycleWithComponent(payload, engine, binding = undefined) {
  const identity = normalizeClaudeWithComponent(resumePayload(payload, binding), engine);
  const plan = planWithComponent(
    engine,
    identity,
    binding === undefined ? undefined : componentBinding(binding),
  );
  return { identity, plan };
}

export function assertClaudeLifecycleSucceeded(operation, response) {
  if (operation === "start" && response?.state === "capability_blocked") {
    const missing = Array.isArray(response.capabilities?.missing_required)
      ? response.capabilities.missing_required.join(", ")
      : "unknown";
    throw new Error(`native start is capability_blocked; missing required capabilities: ${missing}`);
  }
  return response;
}

function resumePayload(payload, binding) {
  const sourceAgentId = binding?.sourceAgentId ?? binding?.source_agent_id;
  return payload?.hook_event_name === "SubagentStart" && typeof sourceAgentId === "string" && sourceAgentId.length > 0
    ? { ...payload, hook_event_name: "SubagentResume" }
    : payload;
}
