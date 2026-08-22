import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import shepherdGuardExtension from "../src/extension.mjs";

const fixtureDir = mkdtempSync(join(tmpdir(), "shepherd-pi-extension-"));
const dispatcher = join(fixtureDir, "shepherd-native.mjs");
const dispatchLog = join(fixtureDir, "operations.log");
const toolCallLog = join(fixtureDir, "tool-calls.log");
// The stub below must speak the protocol of the REAL native CLI, which names
// the correlation field tool_call_id on both sides of the exchange (see
// crates/core/src/dispatch/portable.rs). It previously read and echoed
// tool_use_id -- the component's name -- so it emulated a binary that has never
// existed, and the genuine divergence between the two namings was unobservable
// through this test. A stub that speaks a protocol nothing implements validates
// a fiction.
writeFileSync(dispatcher, `#!/usr/bin/env node
import { appendFileSync } from "node:fs";
let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const operation = process.argv[3];
  appendFileSync(${JSON.stringify(dispatchLog)}, operation + "\\n");
  const request = JSON.parse(input);
  if (operation === "resolve") {
    appendFileSync(${JSON.stringify(toolCallLog)}, request.tool_call_id + "\\n");
    const malformed = process.env.SHEPHERD_PI_TEST_MALFORMED === "1";
    const path = request.tool_input?.path ?? "docs/report.md";
    process.stdout.write(JSON.stringify({
      schema: malformed ? "host-invented" : "shepherd.identity-resolution/1",
      project_id: "0192f6e8-7b2c-7abc-8def-0123456789ab",
      run: "v645",
      harness: "pi",
      agent_id: null,
      agent_type: null,
      role: "shepherd",
      lane: null,
      session_id: process.env.SHEPHERD_PI_TEST_RESOLVE_SESSION ?? request.session_id,
      write_scope: ["**"],
      capabilities: null,
      tool_call_id: process.env.SHEPHERD_PI_TEST_RESOLVE_TOOL ?? request.tool_call_id,
      mode: "execution",
      write_paths: [path],
      path_in_write_scope: true,
    }));
    return;
  }
  process.stdout.write(JSON.stringify({
    schema: "shepherd.root-session/1",
    project_id: "0192f6e8-7b2c-7abc-8def-0123456789ab",
    run: "v645",
    harness: "pi",
    session_id: request.session_id,
    role: request.role_carrier,
    mode: request.mode,
    bound_at: 1,
    expires_at: 86400001,
  }));
});
`);
chmodSync(dispatcher, 0o755);
process.env.SHEPHERD_NATIVE_BIN = dispatcher;

const handlers = {};
const pi = {
  getAllTools() { return [{ name: "subagent" }]; },
  on(event, handler) { handlers[event] = handler; },
};
const context = {
  cwd: process.cwd(),
  sessionManager: { getSessionId: () => "pi-root-session-1" },
};
await shepherdGuardExtension(pi, {
  componentModule: process.env.SHEPHERD_COMPONENT_MODULE,
  // These legacy-looking values are intentionally hostile. Production must
  // ignore them: native bind/resolve are the only authority paths.
  bindRootIdentity: async () => { throw new Error("host-invented bind authority was used"); },
  resolveIdentity: async () => { throw new Error("host-invented resolve authority was used"); },
});

await handlers.session_start({ type: "session_start", reason: "startup" }, context);
assert.equal(await handlers.tool_call({
  type: "tool_call", toolCallId: "pi-tool-1", toolName: "write",
  input: { path: "docs/report.md", content: "x" },
}, context), undefined);

assert.equal(await handlers.tool_call({
  type: "tool_call",
  toolCallId: "call_IGcYvykwDDwEpcB5873Eb2Sk|fc_0c4060b9c5de4864016a88e81ff8ec87d08b5ecd3295c62698",
  toolName: "write",
  input: { path: "docs/report.md", content: "x" },
}, context), undefined, "Pi/OpenAI compound tool-call IDs must reach native guard policy");

assert.equal(await handlers.tool_call({
  type: "tool_call", toolCallId: "x".repeat(1024), toolName: "write",
  input: { path: "docs/report.md", content: "x" },
}, context), undefined, "oversized opaque tool-call IDs must be bounded before native validation");

assert.equal(await handlers.tool_call({
  type: "tool_call", toolCallId: "call-control\nid", toolName: "write",
  input: { path: "docs/report.md", content: "x" },
}, context), undefined, "control characters must not reach native identifiers");

process.env.SHEPHERD_PI_TEST_MALFORMED = "1";
assert.equal((await handlers.tool_call({
  type: "tool_call", toolCallId: "pi-tool-malformed", toolName: "write",
  input: { path: "docs/report.md", content: "x" },
}, context)).block, true, "malformed native resolution must fail closed before guard evaluation");
delete process.env.SHEPHERD_PI_TEST_MALFORMED;

process.env.SHEPHERD_PI_TEST_RESOLVE_SESSION = "another-pi-session";
const wrongSession = await handlers.tool_call({
  type: "tool_call", toolCallId: "pi-tool-wrong-session", toolName: "write",
  input: { path: "docs/report.md", content: "x" },
}, context);
assert.equal(wrongSession.block, true, "a valid native resolve for another session must fail exchange correlation");
delete process.env.SHEPHERD_PI_TEST_RESOLVE_SESSION;

process.env.SHEPHERD_PI_TEST_RESOLVE_TOOL = "another-pi-tool";
const wrongTool = await handlers.tool_call({
  type: "tool_call", toolCallId: "pi-tool-wrong-tool", toolName: "write",
  input: { path: "docs/report.md", content: "x" },
}, context);
assert.equal(wrongTool.block, true, "a valid native resolve for another tool call must fail exchange correlation");
delete process.env.SHEPHERD_PI_TEST_RESOLVE_TOOL;

const missingToolCallId = await handlers.tool_call({
  type: "tool_call", toolName: "write", input: { path: "x", content: "x" },
}, context);
assert.equal(missingToolCallId.block, true, "a missing provider tool-call ID must fail closed");

const nonStringToolCallId = await handlers.tool_call({
  type: "tool_call", toolCallId: 42, toolName: "write", input: { path: "x", content: "x" },
}, context);
assert.equal(nonStringToolCallId.block, true, "a non-string provider tool-call ID must fail closed");

const missingContext = await handlers.tool_call({
  type: "tool_call", toolCallId: "pi-tool-no-context", toolName: "edit", input: { path: "x", edits: [] },
});
assert.equal(missingContext.block, true);
assert.deepEqual(readFileSync(dispatchLog, "utf8").trim().split("\n"), [
  "bind-root", "resolve", "resolve", "resolve", "resolve", "resolve", "resolve", "resolve",
]);
const nativeToolCallIds = readFileSync(toolCallLog, "utf8").trim().split("\n");
assert.equal(nativeToolCallIds.length, 7);
assert.equal(new Set(nativeToolCallIds).size, 7, "distinct provider calls need distinct native correlation tokens");
assert.ok(nativeToolCallIds.every((id) => /^pi-tool-[0-9a-f]{64}$/.test(id)),
  "raw, oversized, and control-character provider IDs must never reach native dispatch");
console.log("ok: Pi guard uses native bind/resolve, correlates exact exchanges, and fails closed");
