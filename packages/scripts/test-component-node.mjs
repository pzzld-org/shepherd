#!/usr/bin/env node
// Execute the temporary jco-generated module. The module path is deliberately
// an argument so generated JS, core Wasm, and declarations never enter git.

import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) throw new Error("usage: test-component-node.mjs <transpiled-component.js>");

const { engine } = await import(pathToFileURL(modulePath).href);
const canonicalByTarget = new Map();
for (const target of ["claude", "codex", "pi"]) {
  const profile = engine.canonicalProfile(target);
  assert.equal(profile.target, target);
  assert.ok(profile.maxConcurrentChildren > 0);

  const canonical = engine.compileCanonical(target);
  assert.equal(canonical.target, target);
  assert.equal(canonical.roles.length, 9);
  assert.ok(canonical.files.length > 0);
  assert.ok(canonical.files.every((file) => file.sourceSha256.length === 64));
  const expected = {
    claude: ["87c6b27c3449505fba7b872eae3b32a4e24891319d233549d0ebabde2cf1cb8e", 16],
    codex: ["a17bfc70e2a70ae266d254d4073402e23cbbea0017114da17f33c5b919822784", 7],
    pi: ["b0b3f7deb52aa78fafdd56ccf4ba18ac49d644428f4269b260c876b8f6898e76", 15],
  }[target];
  assert.equal(canonical.digest, expected[0]);
  assert.equal(canonical.files.length, expected[1]);
  canonicalByTarget.set(target, canonical);
}
const canonical = canonicalByTarget.get("codex");
assert.ok(canonical.files.some((file) => file.path === "shepherd.codex.toml"));

const requestJson = '{"tool_name":"Bash","tool_input":{"command":"printf safe"}}';
const canonicalAllow = engine.guardEvalCanonical(requestJson);
assert.equal(canonicalAllow.tag, "allow");
const canonicalDeny = engine.guardEvalCanonical(
  '{"tool_name":"Agent","role":"conductor","tool_input":{"target_role":"engineer"}}',
);
assert.equal(canonicalDeny.tag, "deny");
assert.equal(canonicalDeny.val.predicate, "dispatch-scope");
assert.equal(canonicalDeny.val.rule, "plan-authorship-and-gating-are-root-tier-exclusive");
assert.equal(canonicalDeny.val.haltCode, "WRONG-TIER-DISPATCH");
assert.ok(canonicalDeny.val.reason.length > 0);

const capabilities = [
  "read",
  "search",
  "shell",
  "write",
  "skill-load",
  "dispatch",
  "message-peer",
  "subagent-provider",
];
for (const harness of ["claude", "codex", "pi"]) {
  const agentType = harness === "claude" ? "engineer" : "shepherd:engineer";
  const normalized = engine.normalizeIdentity({
    harness,
    event: { tag: "subagent-start" },
    sessionId: "session-a",
    agentId: "agent-a",
    agentType,
    toolUseId: "tool-1",
    model: "model-a",
    providerVersion: "provider-1",
  });
  assert.equal(normalized.harness, harness);
  assert.equal(normalized.roleCarrier, "shepherd:engineer");
  assert.equal(normalized.identityKey, `${harness}\u0000session-a\u0000agent-a`);

  const binding = {
    run: "v645",
    role: "engineer",
    lane: "l1",
    parentAgentId: "parent-a",
    writeScope: ["crates/**"],
    model: "model-a",
    observedCapabilities: capabilities,
    capabilitySource: "native-extension",
    harnessVersion: "1.0",
    providerVersion: "1.0",
    leaseMs: 60000,
    expectedRevision: 1,
    resultArtifact: undefined,
    sourceAgentId: undefined,
    mode: "execution",
    toolName: undefined,
    toolInput: undefined,
  };
  const startPlan = engine.planLifecycle(normalized, binding);
  assert.equal(startPlan.tag, "request");
  assert.equal(startPlan.val.tag, "start");

  const resolveIdentity = engine.normalizeIdentity({
    harness,
    event: { tag: "pre-tool-use" },
    sessionId: "session-a",
    agentId: "agent-a",
    agentType,
    toolUseId: "tool-2",
    model: undefined,
    providerVersion: undefined,
  });
  const resolvePlan = engine.planLifecycle(resolveIdentity, binding);
  assert.equal(resolvePlan.tag, "request");
  assert.equal(resolvePlan.val.tag, "resolve");
  assert.equal(resolvePlan.val.val.toolUseId, "tool-2");
}

const absentProvider = engine.evaluateProvider("engineer", {
  observed: [],
  source: "pi-extension",
  harnessVersion: "1.0",
  providerVersion: undefined,
});
assert.equal(absentProvider.readiness, "blocked");
assert.ok(absentProvider.missingRequired.includes("subagent-provider"));

engine.validateResponse({
  schema: "shepherd.identity-resolution/1",
  projectId: "0192f6e8-7b2c-7abc-8def-0123456789ab",
  run: "v645",
  harness: "pi",
  agentId: "agent-a",
  agentType: "shepherd:engineer",
  role: "engineer",
  lane: "l1",
  sessionId: "session-a",
  capabilities: undefined,
  toolUseId: "tool-1",
  mode: "execution",
  writeScope: ["crates/**"],
  writePaths: ["crates/core/src/lib.rs"],
  pathInWriteScope: true,
});
try {
  engine.guardEvalCanonical("{");
  assert.fail("malformed JSON must throw the typed engine error");
} catch (error) {
  const typedError = error?.payload ?? error?.val ?? error;
  assert.equal(typedError.code, "json");
  assert.match(typedError.message, /malformed JSON/);
}

console.log("ok: Node called canonical, typed identity, lifecycle, provider, response, and guard exports through jco");
