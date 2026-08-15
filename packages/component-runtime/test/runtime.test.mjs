import assert from "node:assert/strict";
import test from "node:test";
import {
  componentIdentityInput,
  eventVariant,
  guardWithComponent,
  loadComponent,
  renderNativeLifecycleContext,
  requireEngine,
  validateNativeExchangeWithComponent,
  validateNativeResponseWithComponent,
  validateResponseWithComponent,
} from "../src/index.mjs";

test("component runtime requires every typed Shepherd export", () => {
  assert.throws(() => requireEngine({}), { code: "component_invalid" });
  assert.throws(() => requireEngine({
    canonicalProfile() {}, compileCanonical() {}, normalizeIdentity() {}, planLifecycle() {},
    evaluateProvider() {}, validateResponse() {}, validateNativeResponse() {}, guardEvalCanonical() {},
  }), { code: "component_invalid" });
});

test("component runtime fails closed when the adjacent module is absent", async () => {
  await assert.rejects(loadComponent("/tmp/shepherd-component-does-not-exist.mjs"), { code: "component_unavailable" });
});

test("component runtime converts host events to typed WIT variants", () => {
  assert.deepEqual(eventVariant("SubagentStart"), { tag: "subagent-start" });
  assert.deepEqual(eventVariant("ProviderReady"), { tag: "other-event", val: "ProviderReady" });
  assert.deepEqual(componentIdentityInput({
    harness: "pi",
    event: "SubagentResume",
    sessionId: "session-a",
    agentId: "agent-a",
    agentType: "shepherd:engineer",
  }), {
    harness: "pi",
    event: { tag: "subagent-resume" },
    sessionId: "session-a",
    agentId: "agent-a",
    agentType: "shepherd:engineer",
    toolUseId: undefined,
    model: undefined,
    providerVersion: undefined,
  });
});

test("component runtime maps typed WIT guard variants without policy logic", () => {
  const engine = {
    canonicalProfile() {}, compileCanonical() {}, measure() {}, normalizeIdentity() {}, planLifecycle() {},
    evaluateProvider() {}, validateResponse() {}, validateNativeResponse() {}, validateNativeExchange() {},
    guardEvalCanonical() { return { tag: "allow" }; },
  };
  assert.deepEqual(guardWithComponent(engine, { tool_name: "Bash" }), { decision: "allow" });
});

test("component runtime validates native response facts through the typed export", () => {
  let received;
  const engine = {
    canonicalProfile() {}, compileCanonical() {}, measure() {}, normalizeIdentity() {}, planLifecycle() {},
    evaluateProvider() {}, guardEvalCanonical() { return { tag: "allow" }; },
    validateNativeResponse() {}, validateNativeExchange() {},
    validateResponse(value) { received = value; },
  };
  assert.equal(validateResponseWithComponent(engine, {
    schema: "shepherd.identity-resolution/1", write_scope: ["docs/**"], capabilities: { probed_at: 42 },
  }), true);
  assert.deepEqual(received, {
    schema: "shepherd.identity-resolution/1", writeScope: ["docs/**"], capabilities: { probedAt: 42n },
  });
});

test("component runtime lowers every native lifecycle response into the typed jco ABI", () => {
  const received = [];
  const engine = {
    canonicalProfile() {}, compileCanonical() {}, measure() {}, normalizeIdentity() {}, planLifecycle() {},
    evaluateProvider() {}, validateResponse() {}, guardEvalCanonical() { return { tag: "allow" }; },
    validateNativeExchange() {},
    validateNativeResponse(operation, response) { received.push({ operation, response }); },
  };
  validateNativeResponseWithComponent(engine, "bind-root", {
    schema: "shepherd.root-session/1", project_id: "project-a", run: "v645", harness: "claude",
    session_id: "session-a", role: "shepherd", mode: "execution", bound_at: 1, expires_at: 60_001,
  });
  validateNativeResponseWithComponent(engine, "stop", {
    schema: "shepherd.dispatch/3", revision: 2, project_id: "project-a", run: "v645", harness: "pi",
    agent_id: "agent-a", agent_type: "pi-subagents:worker", role: "worker", lane: "l1",
    parent_agent_id: null, session_id: "session-a", write_scope: ["docs/**"], model: null,
    capabilities: { probed_at: 17 }, state: "stopped", started_at: 1, lease_expires_at: 60_001,
    stopped_at: 2, result_artifact: null, resumes_agent_id: null,
  });
  validateNativeResponseWithComponent(engine, "resume", {
    schema: "shepherd.resume-context/1",
    record: {
      schema: "shepherd.dispatch/3", revision: 1, project_id: "project-a", run: "v645", harness: "pi",
      agent_id: "agent-b", agent_type: "pi-subagents:worker", role: "worker", lane: "l1",
      parent_agent_id: null, session_id: "session-a", write_scope: ["docs/**"], model: null,
      capabilities: { probed_at: 17 }, state: "active", started_at: 3, lease_expires_at: 60_003,
      stopped_at: null, result_artifact: null, resumes_agent_id: "agent-a",
    },
    context: {
      entries: [{
        id: "context-a", project_id: "project-a", run: "v645", lane: "l1", provenance: "agent-a",
        freshness: 2, words: 3, tokens: 4, priority: 5, content: "bounded shared context",
      }],
      words: 3,
      tokens: 4,
    },
  });

  assert.deepEqual(received[0], {
    operation: "bind-root",
    response: {
      tag: "bind-root",
      val: {
        schema: "shepherd.root-session/1", projectId: "project-a", run: "v645", harness: "claude",
        sessionId: "session-a", role: "shepherd", mode: "execution", boundAt: 1n, expiresAt: 60_001n,
      },
    },
  });
  assert.equal(received[1].response.tag, "stop");
  assert.equal(received[1].response.val.revision, 2n);
  assert.equal(received[1].response.val.capabilities.probedAt, 17n);
  assert.equal(received[1].response.val.stoppedAt, 2n);
  assert.equal(received[2].response.tag, "resume");
  assert.equal(received[2].response.val.dispatchRecord.revision, 1n);
  assert.equal(received[2].response.val.context.entries[0].freshness, 2n);
  assert.equal(received[2].response.val.context.words, 3n);
  assert.equal(received[2].response.val.context.tokens, 4n);
  assert.equal(received[2].response.val.record, undefined);
});

test("component runtime rejects unknown lifecycle operations before component evaluation", () => {
  const engine = {
    canonicalProfile() {}, compileCanonical() {}, measure() {}, normalizeIdentity() {}, planLifecycle() {},
    evaluateProvider() {}, validateResponse() {}, validateNativeResponse() {}, validateNativeExchange() {},
    guardEvalCanonical() { return { tag: "allow" }; },
  };
  assert.throws(
    () => validateNativeResponseWithComponent(engine, "invented", {}),
    { code: "invalid_response" },
  );
});

test("component runtime restores typed native request variants for Rust-owned exchange correlation", () => {
  let received;
  const engine = {
    canonicalProfile() {}, compileCanonical() {}, measure() {}, normalizeIdentity() {}, planLifecycle() {},
    evaluateProvider() {}, validateResponse() {}, validateNativeResponse() {},
    validateNativeExchange(request, response) { received = { request, response }; },
    guardEvalCanonical() { return { tag: "allow" }; },
  };
  validateNativeExchangeWithComponent(engine, "start", {
    run: "v645", harness: "codex", agent_id: "agent-a", agent_type: "shepherd:engineer",
    role_carrier: "shepherd:engineer", lane: "l1", parent_agent_id: null,
    session_id: "session-a", write_scope: ["crates/**"], model: null,
    observed_capabilities: ["read"], capability_source: "test", harness_version: "1.0",
    provider_version: null, lease_ms: 60_000,
  }, {
    schema: "shepherd.dispatch/3", revision: 1, project_id: "project-a", run: "v645", harness: "codex",
    agent_id: "agent-a", agent_type: "shepherd:engineer", role: "engineer", lane: "l1",
    parent_agent_id: null, session_id: "session-a", write_scope: ["crates/**"], model: null,
    capabilities: { probed_at: 17 }, state: "active", started_at: 1, lease_expires_at: 60_001,
    stopped_at: null, result_artifact: null, resumes_agent_id: null,
  });
  assert.equal(received.request.tag, "start");
  assert.equal(received.request.val.leaseMs, 60_000n);
  assert.equal(received.response.tag, "start");
  assert.equal(received.response.val.revision, 1n);
  assert.equal(received.response.val.capabilities.probedAt, 17n);
});

test("component runtime renders bounded resume and capability-blocked context without policy", () => {
  assert.equal(renderNativeLifecycleContext("resume", {
    context: {
      entries: [{ provenance: "checkpoint", content: "bounded shared context" }],
      words: 3,
      tokens: 4,
    },
  }), "[shepherd resume context: 1 entry, 3 words, 4 tokens]\n\n[checkpoint]\nbounded shared context");
  assert.equal(renderNativeLifecycleContext("start", {
    state: "capability_blocked",
    capabilities: { missing_required: ["write", "dispatch"] },
  }), "[shepherd] native start is capability_blocked; missing required capabilities: write, dispatch");
  assert.equal(renderNativeLifecycleContext("stop", { state: "stopped" }), "");
});
