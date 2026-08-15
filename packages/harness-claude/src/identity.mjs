import {
  componentIdentityInput,
  normalizeWithComponent,
} from "../../component-runtime/src/index.mjs";

// Host-only extraction. Validation, role normalization, and identity keys are
// owned by the typed component contract.
export function claudeComponentIdentityInput(payload) {
  const input = payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
  return componentIdentityInput({
    harness: "claude",
    event: input.hook_event_name,
    sessionId: input.session_id,
    agentId: input.agent_id,
    agentType: input.agent_type,
    toolUseId: input.tool_use_id,
    model: input.model,
    providerVersion: input.provider_version,
  });
}

export function normalizeClaudeWithComponent(payload, engine) {
  return normalizeWithComponent(engine, claudeComponentIdentityInput(payload));
}
