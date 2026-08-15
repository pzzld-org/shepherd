import assert from "node:assert/strict";
import test from "node:test";
import { validateNativeExchangeWithComponent } from "../../component-runtime/src/index.mjs";
import { claudeComponentIdentityInput, normalizeClaudeWithComponent } from "../src/identity.mjs";
import { assertClaudeLifecycleSucceeded, planClaudeLifecycleWithComponent } from "../src/lifecycle.mjs";
import { evaluateGuardWithComponent } from "../src/guard.mjs";

const payload = {
  hook_event_name: "SubagentStart",
  session_id: "session-a",
  agent_id: "agent-a",
  agent_type: "engineer",
  tool_use_id: "tool-a",
  model: "model-a",
};

function fakeComponent() {
  const calls = [];
  return {
    calls,
    normalizeIdentity(input) { calls.push(["identity", input]); return { ...input, identityKey: "claude\0session-a\0agent-a", roleCarrier: "shepherd:engineer" }; },
    planLifecycle(identity, binding) {
      calls.push(["plan", identity, binding]);
      return { tag: "request", val: { tag: identity.event.tag === "subagent-resume" ? "resume" : "start", val: {} } };
    },
    guardEvalCanonical() { return { tag: "allow" }; },
    canonicalProfile() {}, compileCanonical() {}, measure() {}, evaluateProvider() {}, validateResponse() {}, validateNativeResponse() {}, validateNativeExchange() {},
  };
}

test("Claude adapter translates host identity and lifecycle into typed component calls", () => {
  const component = fakeComponent();
  assert.deepEqual(claudeComponentIdentityInput(payload), {
    harness: "claude",
    event: { tag: "subagent-start" },
    sessionId: "session-a",
    agentId: "agent-a",
    agentType: "engineer",
    toolUseId: "tool-a",
    model: "model-a",
    providerVersion: undefined,
  });
  const normalized = normalizeClaudeWithComponent(payload, component);
  assert.equal(normalized.identityKey, "claude\0session-a\0agent-a");
  const result = planClaudeLifecycleWithComponent(payload, component, {
    run: "v645", role_carrier: "shepherd:engineer", lane: "l1", write_scope: ["crates/**"],
    observed_capabilities: ["read"], capability_source: "test", harness_version: "1.0", lease_ms: 1000,
  });
  assert.equal(result.plan.tag, "request");
  assert.equal(component.calls.at(-1)[0], "plan");
  assert.equal(component.calls.at(-1)[2].role, "shepherd:engineer");
});

test("Claude explicit source identity upgrades its real SubagentStart hook into typed resume", () => {
  const component = fakeComponent();
  const result = planClaudeLifecycleWithComponent(payload, component, {
    role: "engineer", source_agent_id: "agent-old", write_scope: ["crates/**"],
    observed_capabilities: ["read"], capability_source: "test", harness_version: "1.0", lease_ms: 1000,
  });
  assert.equal(result.identity.event.tag, "subagent-resume");
  assert.equal(result.plan.val.tag, "resume");
});

test("Claude guard translation delegates the verdict to the typed component", () => {
  assert.deepEqual(evaluateGuardWithComponent(fakeComponent(), { tool_name: "Bash", tool_input: { command: "true" } }), { decision: "allow" });
});

test("Claude adapter rejects a structurally valid native response for another session", () => {
  const component = fakeComponent();
  component.validateNativeExchange = (request, response) => {
    if (request.val.sessionId !== response.val.sessionId) throw new Error("native lifecycle exchange session mismatch");
  };
  assert.throws(
    () => validateNativeExchangeWithComponent(component, "resolve", {
      session_id: "session-a", agent_id: "agent-a", harness: "claude",
    }, {
      schema: "shepherd.identity-resolution/1", session_id: "session-b", agent_id: "agent-a", harness: "claude",
    }),
    /session mismatch/,
  );
});

test("Claude adapter fails closed when native start is capability_blocked", () => {
  assert.throws(
    () => assertClaudeLifecycleSucceeded("start", {
      state: "capability_blocked",
      capabilities: { missing_required: ["dispatch"] },
    }),
    /capability_blocked.*dispatch/,
  );
});
