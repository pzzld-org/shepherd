import assert from "node:assert/strict";

import {
  GUARD_MATCHER,
  buildGuardDecision,
  buildGuardHooksEntry,
  engineUnavailableVerdict,
  identityUnavailableVerdict,
  interpretEngineResult,
} from "../src/guard.mjs";

const resolution = {
  schema: "shepherd.identity-resolution/1",
  project_id: "018f47ce-72d7-7f64-9eb1-2f651d521c2a",
  run: "v645",
  harness: "claude",
  agent_id: "agent-claude-1",
  agent_type: "shepherd:coder",
  role: "coder",
  lane: "l1-engine",
  session_id: "session-1",
  write_scope: ["crates/core/**"],
  capabilities: { declared: [], observed: [] },
};
assert.deepEqual(
  buildGuardDecision(
    { tool_name: "Bash", tool_input: { command: "git status" }, tool_use_id: "fresh-tool" },
    resolution,
  ),
  {
    kind: "request",
    payload: {
      harness: "claude",
      role: "coder",
      tool_name: "Bash",
      tool_input: { command: "git status" },
      tool_use_id: "fresh-tool",
      dispatch: resolution,
    },
  },
);
assert.deepEqual(interpretEngineResult({ decision: "allow" }), {});
for (const [name, decision] of [
  ["policy denial", interpretEngineResult({ decision: "deny", reason: "blocked" })],
  ["unresolved guard", interpretEngineResult({ decision: "unresolved", reason: "missing" })],
  ["engine failure", engineUnavailableVerdict("offline")],
  ["identity failure", identityUnavailableVerdict("missing record")],
]) {
  assert.deepEqual(decision, {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: decision.hookSpecificOutput?.permissionDecisionReason,
    },
  }, `${name} must use Claude's documented nested PreToolUse denial envelope`);
  assert.equal(typeof decision.hookSpecificOutput.permissionDecisionReason, "string");
  assert.notEqual(decision.hookSpecificOutput.permissionDecisionReason, "");
}
assert.equal(buildGuardHooksEntry().matcher, GUARD_MATCHER);
assert.deepEqual(buildGuardHooksEntry().hooks[0], {
  type: "command",
  command: "node",
  args: ["${CLAUDE_PLUGIN_ROOT}/packages/harness-claude/hooks/guard-eval.mjs"],
});

console.log("ok: Claude guard adapter forwards native resolution and translates verdicts only");
