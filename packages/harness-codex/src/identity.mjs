import {
  componentIdentityInput,
  normalizeWithComponent,
} from "../../component-runtime/src/index.mjs";

// Host-only extraction. Validation, role normalization, and identity keys are
// owned by the typed component contract.
export function codexComponentIdentityInput(payload) {
  const input = payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
  return componentIdentityInput({
    harness: "codex",
    event: input.hook_event_name,
    sessionId: input.session_id,
    agentId: input.agent_id,
    agentType: input.agent_type,
    toolUseId: input.tool_use_id,
    model: input.model,
    providerVersion: input.provider_version,
  });
}

export function normalizeCodexWithComponent(payload, engine) {
  return normalizeWithComponent(engine, codexComponentIdentityInput(payload));
}
