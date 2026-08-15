import assert from "node:assert/strict";

import {
  buildGuardDecision,
  engineUnavailableVerdict,
  evaluateGuardWithComponent,
  identityUnavailableVerdict,
  interpretEngineResult,
} from "../src/guard.mjs";

const resolution = {
  schema: "shepherd.identity-resolution/1",
  project_id: "018f47ce-72d7-7f64-9eb1-2f651d521c2a",
  run: "v645",
  harness: "codex",
  agent_id: "019f-agent",
  agent_type: "worker",
  role: "coder",
  lane: "l1-engine",
  session_id: "019f-session",
  write_scope: ["crates/core/**"],
  capabilities: { declared: [], observed: [] },
};
assert.deepEqual(
  buildGuardDecision(
    { tool_name: "Bash", tool_input: { command: "git commit -m x" }, tool_use_id: "call-2" },
    resolution,
  ),
  {
    kind: "request",
    payload: {
      harness: "codex",
      role: "coder",
      tool_name: "Bash",
      tool_input: { command: "git commit -m x" },
      tool_use_id: "call-2",
      dispatch: resolution,
    },
  },
);
for (const invalidResolution of [
  { ...resolution, schema: "wrong" },
  { ...resolution, harness: "claude" },
  { ...resolution, role: "" },
]) {
  assert.equal(buildGuardDecision({}, invalidResolution).kind, "identity-error");
}
const engine = {
  canonicalProfile() {},
  compileCanonical() {},
  measure() {},
  guardEvalCanonical(request) {
    assert.equal(JSON.parse(request).role, "coder");
    return { tag: "allow" };
  },
  normalizeIdentity() {},
  planLifecycle() {},
  evaluateProvider() {},
  validateResponse() {},
  validateNativeResponse() {},
  validateNativeExchange() {},
};
assert.deepEqual(evaluateGuardWithComponent(engine, { role: "coder" }), { decision: "allow" });
assert.deepEqual(interpretEngineResult({ decision: "allow" }), {});
assert.equal(
  interpretEngineResult({ decision: "deny", halt_code: "CODER-GIT-WRITE", reason: "blocked" })
    .hookSpecificOutput.permissionDecision,
  "deny",
);
assert.equal(
  interpretEngineResult({ decision: "unresolved", reason: "missing" })
    .hookSpecificOutput.permissionDecision,
  "deny",
);
assert.equal(engineUnavailableVerdict("offline").hookSpecificOutput.permissionDecision, "deny");
assert.equal(identityUnavailableVerdict("missing").hookSpecificOutput.permissionDecision, "deny");

console.log("ok: Codex guard adapter forwards native resolution and translates verdicts only");
