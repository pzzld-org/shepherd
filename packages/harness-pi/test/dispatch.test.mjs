import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  resumeSubagent,
  spawnSubagent,
  stopSubagent,
} from "../src/dispatch.mjs";

const fixtureDir = mkdtempSync(join(tmpdir(), "shepherd-pi-dispatch-"));
const dispatcher = join(fixtureDir, "shepherd-native.mjs");
const dispatchLog = join(fixtureDir, "operations.log");
writeFileSync(dispatcher, `#!/usr/bin/env node
import { appendFileSync } from "node:fs";
let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const operation = process.argv[3];
  appendFileSync(${JSON.stringify(dispatchLog)}, operation + "\\n");
  const request = JSON.parse(input);
  const requestedAgentId = request.agent_id ?? request.next?.agent_id ?? "pi-agent-1";
  const agentId = process.env.SHEPHERD_PI_TEST_AGENT ?? requestedAgentId;
  const agentType = request.agent_type ?? request.next?.agent_type ?? "pi-subagents:worker";
  const harness = request.harness ?? request.next?.harness ?? "pi";
  const sessionId = request.session_id ?? request.next?.session_id ?? "pi-session-1";
  const base = {
    schema: "shepherd.dispatch/3", revision: operation === "stop" ? 2 : 1,
    harness, session_id: sessionId, agent_id: agentId, agent_type: agentType,
    capabilities: { probed_at: 1 },
    started_at: 1, lease_expires_at: 60001,
    stopped_at: operation === "stop" ? 2 : null,
    resumes_agent_id: operation === "resume"
      ? (process.env.SHEPHERD_PI_TEST_SOURCE ?? request.source_agent_id)
      : null,
  };
  if (process.env.SHEPHERD_PI_TEST_STOP_FAIL === "1" && operation === "stop") {
    process.stderr.write("simulated native stop failure");
    process.exit(1);
  }
  if (process.env.SHEPHERD_PI_TEST_BAD === "1") {
    process.stdout.write(JSON.stringify({ ...base, state: "capability_blocked" }));
    return;
  }
  if (operation === "resume") {
    process.stdout.write(JSON.stringify({
      schema: "shepherd.resume-context/1",
      record: { ...base, state: "active" },
      context: { entries: [], words: 0, tokens: 0 },
    }));
    return;
  }
  process.stdout.write(JSON.stringify({ ...base, state: operation === "stop" ? "stopped" : "active" }));
});
`);
chmodSync(dispatcher, 0o755);

const request = {
  schema: "shepherd.spawn-request/1",
  role_carrier: "shepherd:worker",
  lane: "l1-engine",
  write_scope: ["docs/**"],
  task: "Write the bounded report",
};
const componentEngine = {
  canonicalProfile() {}, compileCanonical() {}, measure() {}, guardEvalCanonical() { return { tag: "allow" }; },
  evaluateProvider() {}, validateResponse() {}, validateNativeResponse() {},
  validateNativeExchange(request, response) {
    assert.equal(request.tag, response.tag, "exchange response must match the planned operation");
    const expected = request.tag === "resume" ? request.val.next : request.val;
    const record = response.tag === "resume" ? response.val.dispatchRecord : response.val;
    if (request.tag === "start" || request.tag === "stop" || request.tag === "resume") {
      if (record.agentId !== expected.agentId || record.agentType !== expected.agentType
        || record.harness !== expected.harness || record.sessionId !== expected.sessionId) {
        throw new TypeError("exchange response did not match the planned native identity");
      }
    }
    if (request.tag === "resume" && record.resumesAgentId !== request.val.sourceAgentId) {
      throw new TypeError("exchange response did not match the planned resume source");
    }
  },
  normalizeIdentity(input) {
    return {
      ...input,
      identityKey: `pi\0${input.sessionId}\0${input.agentId}`,
      roleCarrier: input.agentType,
      providerVersion: input.providerVersion,
    };
  },
  planLifecycle(identity, binding) {
    const val = {
      run: binding?.run,
      harness: "pi",
      agentId: identity.agentId,
      agentType: identity.agentType,
      roleCarrier: binding?.role ?? identity.roleCarrier,
      lane: binding?.lane,
      sessionId: identity.sessionId,
      writeScope: binding?.writeScope ?? [],
      model: identity.model,
      observedCapabilities: binding?.observedCapabilities ?? [],
      capabilitySource: binding?.capabilitySource ?? "test",
      harnessVersion: binding?.harnessVersion ?? "1.0",
      providerVersion: identity.providerVersion,
      leaseMs: binding?.leaseMs ?? 60_000,
      expectedRevision: binding?.expectedRevision ?? 1,
      resultArtifact: binding?.resultArtifact,
      sourceAgentId: binding?.sourceAgentId,
      next: undefined,
    };
    const event = identity.event.tag;
    if (event === "subagent-resume") return { tag: "request", val: { tag: "resume", val: { sourceAgentId: binding.sourceAgentId ?? identity.agentId, next: val } } };
    if (event === "subagent-stop") return { tag: "request", val: { tag: "stop", val } };
    return { tag: "request", val: { tag: "start", val } };
  },
};
assert.deepEqual(
  await spawnSubagent(null, request, {
    sessionId: "pi-session-1",
    providerVersion: "unavailable",
  }),
  {
    kind: "capability_blocked",
    missing_required: ["subagent-provider"],
  },
  "base Pi never falls back to a shell pseudo-flock",
);

const calls = [];
const provider = {
  capabilities() {
    return { primitive: "subagent-provider", version: "pi-subagents/2.3.0", limits: {} };
  },
  async spawn(value) {
    calls.push(["spawn", value]);
    return { agentId: "pi-agent-1", agentType: "pi-subagents:worker", lifecycle: "started" };
  },
  async resume(agentId) {
    calls.push(["resume", agentId]);
    return { agentId: "pi-agent-2", agentType: "pi-subagents:worker", lifecycle: "resumed" };
  },
  async stop(agentId) {
    calls.push(["stop", agentId]);
    return { agentId, agentType: "pi-subagents:worker", lifecycle: "stopped" };
  },
};
assert.deepEqual(
  await spawnSubagent(provider, request, {
    sessionId: "pi-session-1",
    harnessVersion: "0.84.1",
    observedCapabilities: [],
  }),
  {
    kind: "capability_blocked",
    missing_required: ["component-runtime"],
  },
  "Pi never spawns an agent without the Component runtime",
);
assert.equal(calls.length, 0);

const runtime = {
  componentEngine,
  shepherdBin: dispatcher,
  cwd: process.cwd(),
  sessionId: "pi-session-1",
  harnessVersion: "0.84.1",
  leaseMs: 60_000,
  role_carrier: "shepherd:worker",
  agent_type: "pi-subagents:worker",
  lane: "l1-engine",
  write_scope: ["docs/**"],
  run: "v645",
  observedCapabilities: [
    "read", "search", "shell", "skill-load", "write", "tool-discovery",
    "subagent-provider",
  ],
};
let stableCapabilityCalls = 0;
const stableStops = [];
const stableProvider = {
  capabilities() {
    stableCapabilityCalls += 1;
    if (stableCapabilityCalls > 1) throw new Error("provider capability probe must be cached");
    return { primitive: "subagent-provider", version: "pi-subagents/2.3.0", limits: {} };
  },
  async spawn() {
    return { agentId: "stable-agent", agentType: "pi-subagents:worker", lifecycle: "started" };
  },
  async resume(agentId) {
    return { agentId: "stable-resumed-agent", agentType: "pi-subagents:worker", lifecycle: "resumed", sourceAgentId: agentId };
  },
  async stop(agentId) {
    stableStops.push(agentId);
    return { agentId, agentType: "pi-subagents:worker", lifecycle: "stopped" };
  },
};
const stableStarted = await spawnSubagent(stableProvider, request, runtime);
assert.equal(stableStarted.identity.agentId, "stable-agent");
assert.equal(stableCapabilityCalls, 1, "lifecycle construction must use the admitted capability snapshot");
assert.deepEqual(stableStops, [], "a later provider capability failure cannot leak or compensate a successful child");

const constructionStops = [];
const constructionEngine = {
  ...componentEngine,
  normalizeIdentity() {
    throw new Error("lifecycle construction failed");
  },
};
const constructionProvider = {
  capabilities: () => ({ primitive: "subagent-provider", version: "1.0", limits: {} }),
  spawn: async () => ({ agentId: "construction-agent", agentType: "pi-subagents:worker", lifecycle: "started" }),
  resume: async () => ({ agentId: "construction-resumed", agentType: "pi-subagents:worker", lifecycle: "resumed" }),
  stop: async (agentId) => { constructionStops.push(agentId); },
};
await assert.rejects(
  spawnSubagent(constructionProvider, request, { ...runtime, componentEngine: constructionEngine }),
  /lifecycle construction failed/,
);
assert.deepEqual(constructionStops, ["construction-agent"], "lifecycle construction failures must stop the spawned child");

const blockedCalls = [];
const blockedProviders = [
  { capabilities: () => null },
  { capabilities: () => ({ primitive: "subagent-provider", version: "1.0", limits: {}, readiness: "degraded" }) },
  { capabilities: () => ({ primitive: "subagent-provider", version: "1.0", limits: {}, ready: false }) },
  {
    capabilities: () => ({ primitive: "subagent-provider", version: "1.0", limits: {}, readiness: "blocked" }),
    spawn: async () => { blockedCalls.push("spawn"); throw new Error("must not spawn"); },
    resume: async () => { blockedCalls.push("resume"); throw new Error("must not resume"); },
    stop: async () => { blockedCalls.push("stop"); throw new Error("must not stop"); },
  },
];
for (const blockedProvider of blockedProviders) {
  assert.deepEqual(await spawnSubagent(blockedProvider, request, runtime), {
    kind: "capability_blocked",
    missing_required: ["subagent-provider"],
  });
  assert.deepEqual(await resumeSubagent(blockedProvider, "pi-agent-1", runtime), {
    kind: "capability_blocked",
    missing_required: ["subagent-provider"],
  });
  assert.deepEqual(await stopSubagent(blockedProvider, "pi-agent-1", runtime), {
    kind: "capability_blocked",
    missing_required: ["subagent-provider"],
  });
}
assert.deepEqual(blockedCalls, [], "unready providers must be blocked before any lifecycle method runs");

const spawned = await spawnSubagent(provider, request, runtime);
assert.equal(spawned.kind, "started");
assert.equal(spawned.identity.agentId, "pi-agent-1");
assert.deepEqual(calls[0], ["spawn", request]);
assert.equal(spawned.dispatch.schema, "shepherd.dispatch/3");
const resumed = await resumeSubagent(provider, "pi-agent-1", runtime);
assert.equal(resumed.identity.event.tag, "subagent-resume");
assert.equal(resumed.request.source_agent_id, "pi-agent-1");
assert.equal(resumed.request.next.agent_id, "pi-agent-2", "resume publishes the provider's new identity, never the source identity");
assert.equal(resumed.dispatch.schema, "shepherd.resume-context/1");
const stopped = await stopSubagent(provider, "pi-agent-1", runtime);
assert.equal(stopped.identity.event.tag, "subagent-stop");
assert.equal(stopped.request.agent_id, "pi-agent-1");
assert.equal(stopped.dispatch.schema, "shepherd.dispatch/3");
assert.equal(stopped.dispatch.state, "stopped", "native stop is terminal, not active");
assert.deepEqual(calls.at(-1), ["stop", "pi-agent-1"], "provider termination follows native durable stop");

const stopCallsBeforeNativeFailure = calls.filter(([operation]) => operation === "stop").length;
process.env.SHEPHERD_PI_TEST_STOP_FAIL = "1";
await assert.rejects(
  stopSubagent(provider, "pi-agent-1", runtime),
  /simulated native stop failure/,
);
delete process.env.SHEPHERD_PI_TEST_STOP_FAIL;
assert.equal(
  calls.filter(([operation]) => operation === "stop").length,
  stopCallsBeforeNativeFailure,
  "native stop failure must not terminate the provider child",
);

process.env.SHEPHERD_PI_TEST_BAD = "1";
await assert.rejects(
  spawnSubagent(provider, request, {
    ...runtime,
    shepherdBin: dispatcher,
  }),
  /mismatched or blocked/,
);
delete process.env.SHEPHERD_PI_TEST_BAD;
assert.deepEqual(calls.at(-1), ["stop", "pi-agent-1"], "failed publication stops the native child");

process.env.SHEPHERD_PI_TEST_AGENT = "another-pi-agent";
await assert.rejects(
  spawnSubagent(provider, request, runtime),
  /exchange response did not match the planned native identity/,
  "a structurally valid start for another agent must fail native exchange correlation",
);
delete process.env.SHEPHERD_PI_TEST_AGENT;

process.env.SHEPHERD_PI_TEST_SOURCE = "another-source-agent";
await assert.rejects(
  resumeSubagent(provider, "pi-agent-1", runtime),
  /exchange response did not match the planned resume source/,
  "a resume response for another source must fail native exchange correlation",
);
delete process.env.SHEPHERD_PI_TEST_SOURCE;
assert.deepEqual(calls.at(-1), ["stop", "pi-agent-2"], "resume publication failure must stop the newly resumed child, not its source");

const resumeCleanupFailures = [];
const failingResumeCleanupProvider = {
  capabilities: () => ({ primitive: "subagent-provider", version: "1.0", limits: {} }),
  spawn: async () => ({ agentId: "unused", agentType: "pi-subagents:worker", lifecycle: "started" }),
  resume: async () => ({ agentId: "resume-cleanup-agent", agentType: "pi-subagents:worker", lifecycle: "resumed" }),
  stop: async (agentId) => {
    resumeCleanupFailures.push(agentId);
    throw new Error("resume cleanup failed");
  },
};
process.env.SHEPHERD_PI_TEST_SOURCE = "another-source-agent";
await assert.rejects(
  resumeSubagent(failingResumeCleanupProvider, "pi-agent-1", runtime),
  (error) => error instanceof AggregateError
    && error.errors.some((entry) => /planned resume source/.test(String(entry)))
    && error.errors.some((entry) => /resume cleanup failed/.test(String(entry))),
  "resume cleanup failures must retain both the publication and cleanup errors",
);
delete process.env.SHEPHERD_PI_TEST_SOURCE;
assert.deepEqual(resumeCleanupFailures, ["resume-cleanup-agent"]);

assert.deepEqual(
  readFileSync(dispatchLog, "utf8").trim().split("\n"),
  ["start", "start", "resume", "stop", "stop", "start", "start", "resume", "resume"],
  "every Pi lifecycle publication must execute the native Shepherd transport",
);

console.log("ok: Pi dispatch is provider-backed only; provider absence is capability-blocked");
