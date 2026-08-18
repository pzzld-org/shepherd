import assert from "node:assert/strict";

import { bindSubagentProvider, probeSubagentProvider } from "../src/subagent-provider.mjs";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const contract = JSON.parse(readFileSync(join(fileURLToPath(new URL("..", import.meta.url)), "shepherd.pi.json"), "utf8"));
assert.equal(contract.contract, "fl03:shepherd@6.4.8");
assert.equal(contract.provider.failClosedWhenAbsent, true);
assert.deepEqual(contract.provider.requiredMethods, ["capabilities", "spawn", "resume", "stop"]);
assert.deepEqual(contract.component.requiredExports, [
  "canonicalProfile",
  "compileCanonical",
  "measure",
  "guardEvalCanonical",
  "normalizeIdentity",
  "planLifecycle",
  "evaluateProvider",
  "validateResponse",
  "validateNativeResponse",
  "validateNativeExchange",
], "Pi declares the complete shared component engine surface");

assert.deepEqual(probeSubagentProvider(undefined, { harnessVersion: "0.84.1", probedAt: 1000 }), {
  observed: [],
  source: "pi-startup-provider-probe",
  harness_version: "0.84.1",
  provider_version: null,
  probed_at: 1000,
  readiness: "capability_blocked",
  missing_required: ["subagent-provider"],
});
assert.equal(bindSubagentProvider(undefined), null, "base Pi has no synthetic shell fallback");

for (const capabilities of [
  null,
  { primitive: "other-provider", version: "1.0", limits: {} },
  { primitive: "subagent-provider", version: "", limits: {} },
  { primitive: "subagent-provider", version: "1.0", limits: null },
  { primitive: "subagent-provider", version: "1.0", limits: {}, readiness: "degraded" },
  { primitive: "subagent-provider", version: "1.0", limits: {}, ready: false },
]) {
  const malformed = {
    capabilities: () => capabilities,
    spawn() { throw new Error("must not spawn"); },
    resume() { throw new Error("must not resume"); },
    stop() { throw new Error("must not stop"); },
  };
  assert.equal(
    probeSubagentProvider(malformed, { harnessVersion: "0.84.1", probedAt: 1000 }).readiness,
    "capability_blocked",
    "malformed or explicitly unready provider capabilities fail closed",
  );
}

const calls = [];
const provider = {
  capabilities() {
    return { primitive: "subagent-provider", version: "pi-subagents/2.3.0", limits: { maxConcurrent: 4 } };
  },
  async spawn(request) {
    calls.push(["spawn", request]);
    return { agentId: "pi-agent-1", agentType: "pi-subagents:worker", lifecycle: "started" };
  },
  async resume(agentId) {
    calls.push(["resume", agentId]);
    return { agentId, lifecycle: "resumed" };
  },
  async stop(agentId) {
    calls.push(["stop", agentId]);
    return { agentId, lifecycle: "stopped", resultArtifact: "lanes/l1/reports/pi-agent-1.md" };
  },
};
const bound = bindSubagentProvider(provider);
assert.equal(bound, provider);
assert.deepEqual(probeSubagentProvider(bound, { harnessVersion: "0.84.1", probedAt: 1000 }), {
  observed: ["subagent-provider"],
  source: "pi-startup-provider-probe",
  harness_version: "0.84.1",
  provider_version: "pi-subagents/2.3.0",
  probed_at: 1000,
  readiness: "ready",
  missing_required: [],
  limits: { maxConcurrent: 4 },
});

const request = {
  schema: "shepherd.spawn-request/1",
  role_carrier: "shepherd:worker",
  lane: "l1-engine",
  write_scope: ["docs/**"],
  task: "Write the bounded report",
};
assert.deepEqual(await bound.spawn(request), {
  agentId: "pi-agent-1",
  agentType: "pi-subagents:worker",
  lifecycle: "started",
});
assert.deepEqual(await bound.resume("pi-agent-1"), { agentId: "pi-agent-1", lifecycle: "resumed" });
assert.deepEqual(await bound.stop("pi-agent-1"), {
  agentId: "pi-agent-1",
  lifecycle: "stopped",
  resultArtifact: "lanes/l1/reports/pi-agent-1.md",
});
assert.deepEqual(calls[0], ["spawn", request], "provider gets explicit role, lane, and scope");

for (const incomplete of [{}, { capabilities() {} }, { capabilities() {}, spawn() {}, resume() {} }]) {
  assert.throws(() => bindSubagentProvider(incomplete), /SubagentProvider/);
}

console.log("ok: Pi requires an explicit SubagentProvider and reports absence as a capability block");
