import assert from "node:assert/strict";
import test from "node:test";
import { normalizePiWithComponent } from "../src/identity.mjs";
import { planPiLifecycleWithComponent } from "../src/dispatch.mjs";
import { evaluatePiGuardWithComponent } from "../src/component-guard.mjs";

function provider() {
  return {
    capabilities: () => ({ primitive: "subagent-provider", version: "1.0", limits: { max: 3 } }),
    spawn: async () => ({ lifecycle: "started", agentId: "agent-a", agentType: "shepherd:engineer", model: "model-a" }),
    resume: async () => ({ lifecycle: "resumed", agentId: "agent-b", agentType: "shepherd:engineer", model: "model-a" }),
    stop: async () => ({ lifecycle: "stopped", agentId: "agent-a", agentType: "shepherd:engineer" }),
  };
}

function fakeComponent() {
  const calls = [];
  return {
    calls,
    normalizeIdentity(input) { calls.push(["identity", input]); return { ...input, identityKey: "pi\0session-a\0agent-a", roleCarrier: "shepherd:engineer" }; },
    planLifecycle(identity, binding) { calls.push(["plan", identity, binding]); return { tag: "request", val: { tag: "start", val: {} } }; },
    guardEvalCanonical() { return { tag: "allow" }; },
    canonicalProfile() {}, compileCanonical() {}, measure() {}, evaluateProvider() {}, validateResponse() {}, validateNativeResponse() {}, validateNativeExchange() {},
  };
}

test("Pi provider lifecycle publishes only through typed component planning", async () => {
  const component = fakeComponent();
  const result = await planPiLifecycleWithComponent(provider(), { lifecycle: "started" }, { sessionId: "session-a" }, component, {
    role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: ["read"], capability_source: "pi-extension", harness_version: "1.0", lease_ms: 1000,
  });
  assert.equal(result.identity.event.tag, "subagent-start");
  assert.equal(result.plan.val.tag, "start");
  assert.equal(component.calls.at(-1)[0], "plan");
});

test("Pi guard translation delegates the verdict to the typed component", () => {
  assert.deepEqual(evaluatePiGuardWithComponent(fakeComponent(), { tool_name: "Bash" }), { decision: "allow" });
});
