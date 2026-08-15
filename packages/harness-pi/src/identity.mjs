import {
  componentIdentityInput,
  normalizeWithComponent,
} from "../../component-runtime/src/index.mjs";

// Host-only provider envelope extraction. Validation and lifecycle policy are
// owned by the typed component contract.
export function piComponentIdentityInput(event, runtime) {
  if (event === null || typeof event !== "object" || Array.isArray(event)) {
    throw new TypeError("provider lifecycle event must be an object");
  }
  if (runtime === null || typeof runtime !== "object" || Array.isArray(runtime)) {
    throw new TypeError("provider runtime must be an object");
  }
  const lifecycleEvents = {
    started: "SubagentStart",
    resumed: "SubagentResume",
    stopped: "SubagentStop",
  };
  return componentIdentityInput({
    harness: "pi",
    event: lifecycleEvents[event.lifecycle] ?? event.lifecycle,
    sessionId: runtime.sessionId,
    agentId: event.agentId,
    agentType: event.agentType,
    toolUseId: event.toolUseId,
    model: event.model,
    providerVersion: runtime.providerVersion,
  });
}

export function normalizePiWithComponent(event, runtime, engine) {
  return normalizeWithComponent(engine, piComponentIdentityInput(event, runtime));
}

export function piToolIdentityInput(event, resolution, sessionId) {
  return componentIdentityInput({
    harness: "pi",
    event: "PreToolUse",
    sessionId,
    agentId: resolution?.agent_id,
    agentType: resolution?.agent_type,
    toolUseId: event?.toolCallId,
    model: resolution?.model,
    providerVersion: resolution?.provider_version,
  });
}
