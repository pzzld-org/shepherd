import assert from "node:assert/strict";
import test from "node:test";
import { validateNativeExchangeWithComponent } from "../../component-runtime/src/index.mjs";
import { codexComponentIdentityInput, normalizeCodexWithComponent } from "../src/identity.mjs";
import { assertCodexLifecycleSucceeded, planCodexLifecycleWithComponent } from "../src/lifecycle.mjs";
import { evaluateGuardWithComponent } from "../src/guard.mjs";

const payload = {
  hook_event_name: "SubagentStart",
  session_id: "session-a",
  agent_id: "agent-a",
  agent_type: "shepherd:engineer",
  tool_use_id: "tool-a",
};

function fakeComponent() {
  const calls = [];
  return {
    calls,
    normalizeIdentity(input) { calls.push(["identity", input]); return { ...input, identityKey: "codex\0session-a\0agent-a", roleCarrier: "shepherd:engineer" }; },
    planLifecycle(identity, binding) {
      calls.push(["plan", identity, binding]);
      return { tag: "request", val: { tag: identity.event.tag === "subagent-resume" ? "resume" : "start", val: {} } };
    },
    guardEvalCanonical() { return { tag: "allow" }; },
    canonicalProfile() {}, compileCanonical() {}, measure() {}, evaluateProvider() {}, validateResponse() {}, validateNativeResponse() {}, validateNativeExchange() {},
  };
}

test("Codex adapter translates current hook fields and delegates lifecycle policy", () => {
  const component = fakeComponent();
  assert.equal(codexComponentIdentityInput(payload).event.tag, "subagent-start");
  assert.equal(normalizeCodexWithComponent(payload, component).harness, "codex");
  const result = planCodexLifecycleWithComponent(payload, component, { role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: ["read"], capability_source: "test", harness_version: "1.0", lease_ms: 1000 });
  assert.equal(result.plan.val.tag, "start");
  assert.equal(component.calls.at(-1)[0], "plan");
});

test("Codex explicit source identity upgrades its real SubagentStart hook into typed resume", () => {
  const component = fakeComponent();
  const result = planCodexLifecycleWithComponent(payload, component, {
    role: "engineer", source_agent_id: "agent-old", write_scope: ["crates/**"],
    observed_capabilities: ["read"], capability_source: "test", harness_version: "1.0", lease_ms: 1000,
  });
  assert.equal(result.identity.event.tag, "subagent-resume");
  assert.equal(result.plan.val.tag, "resume");
});

test("Codex guard translation delegates the verdict to the typed component", () => {
  assert.deepEqual(evaluateGuardWithComponent(fakeComponent(), { tool_name: "Bash" }), { decision: "allow" });
});

test("Codex adapter rejects a structurally valid native response for another agent", () => {
  const component = fakeComponent();
  component.validateNativeExchange = (request, response) => {
    if (request.val.agentId !== response.val.agentId) throw new Error("native lifecycle exchange agent mismatch");
  };
  assert.throws(
    () => validateNativeExchangeWithComponent(component, "resolve", {
      session_id: "session-a", agent_id: "agent-a", harness: "codex",
    }, {
      schema: "shepherd.identity-resolution/1", session_id: "session-a", agent_id: "agent-b", harness: "codex",
    }),
    /agent mismatch/,
  );
});

test("Codex adapter fails closed when native start is capability_blocked", () => {
  assert.throws(
    () => assertCodexLifecycleSucceeded("start", {
      state: "capability_blocked",
      capabilities: { missing_required: ["write", "dispatch"] },
    }),
    /capability_blocked.*write, dispatch/,
  );
});
