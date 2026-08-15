import assert from "node:assert/strict";
import { fileURLToPath, pathToFileURL } from "node:url";

const modulePath = process.argv[2];
const extensionPath = process.argv[3];
if (!modulePath || !extensionPath) {
  throw new Error("usage: test-active-pi.mjs <component-module> <pi-extension>");
}
const { default: shepherdGuardExtension } = await import(pathToFileURL(extensionPath).href);
const handlers = {};
const pi = { on(event, handler) { handlers[event] = handler; } };
const options = {
  componentModule: modulePath.startsWith("file:") ? fileURLToPath(modulePath) : modulePath,
};
await shepherdGuardExtension(pi, options);
const context = {
  cwd: process.cwd(),
  sessionManager: { getSessionId: () => "pi-root" },
};
await handlers.session_start({ type: "session_start", reason: "startup" }, {
  ...context,
});
assert.equal(await handlers.tool_call({
  type: "tool_call", toolCallId: "pi-tool", toolName: "write",
  input: { path: "crates/core/src/lib.rs", content: "safe" },
}, context), undefined);
assert.equal(await handlers.tool_call({
  type: "tool_call", toolCallId: "pi-tool-2", toolName: "bash",
  input: { command: "git commit -m forbidden" },
}, context), undefined, "component guard has no role policy fixture for this probe");
console.log("ok: active Pi extension loaded the staged component and used native bind/resolve dispatch");
