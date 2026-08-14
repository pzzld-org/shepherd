#!/usr/bin/env node
// packages/harness-pi/test/extension-guard.test.mjs -- run directly:
//   node --experimental-strip-types test/extension-guard.test.mjs
// End-to-end test for src/extension.ts's default export (C1-pi-collapse): a mock ExtensionAPI
// drives real `tool_call` events through `shepherdGuardExtension` against a LIVE `bin/shepherd
// guard serve` child process -- the whole wire, not just the detectors (test/extension-detectors
// .test.mjs) or the corpus-vs-engine agreement (test/guard-predicates.test.mjs) in isolation.
// Proves the fail-closed contract survived the collapse from a synchronous local interpreter
// (deleted src/guard.ts) to an async relay: an unset role still denies every write/edit/bash,
// a coder still cannot `git commit`, an out-of-scope write is still denied, and the guard-serve
// child still gets closed (not orphaned) on `session_shutdown`.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import shepherdGuardExtension from "../src/extension.ts";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const CONTENT_DIR = join(REPO_ROOT, "content");

/** A minimal mock of pi-types.ts's ExtensionAPI: captures the ONE handler registered per event. */
function makeMockPi() {
  const handlers = {};
  return {
    on(event, handler) {
      assert.ok(!(event in handlers), `mock pi received a second on("${event}", ...) registration -- extension.ts must register exactly one handler per event`);
      handlers[event] = handler;
    },
    handlers,
  };
}

// -- 0. `bin/shepherd guard serve` never comes up (a broken venv, a provisioning failure):
// the extension must fail closed on every write/edit/bash for the rest of the session,
// never let a spawn failure silently degrade into "every capability is allowed." A
// self-contained fixture (a fake `<root>/bin/shepherd` that exits 1 immediately, and just
// enough `content/roles/coder.md` for `loadRoleFacts` to succeed) drives this without
// touching the real repo's bin/shepherd.
{
  const fixtureRoot = mkdtempSync(join(tmpdir(), "harness-pi-guard-spawn-fail-"));
  try {
    mkdirSync(join(fixtureRoot, "content", "roles"), { recursive: true });
    mkdirSync(join(fixtureRoot, "bin"), { recursive: true });
    writeFileSync(
      join(fixtureRoot, "content", "roles", "coder.md"),
      "---\nrole: coder\nwrite_eligible: true\ndispatchable: true\ncapabilities: [read, write]\n---\nfixture role\n"
    );
    const fakeShepherdBin = join(fixtureRoot, "bin", "shepherd");
    writeFileSync(fakeShepherdBin, '#!/usr/bin/env bash\necho "simulated: engine unavailable" >&2\nexit 1\n', { mode: 0o755 });

    const brokenPi = makeMockPi();
    await shepherdGuardExtension(brokenPi, join(fixtureRoot, "content"));
    process.env.SHEPHERD_ROLE = "coder";
    process.env.SHEPHERD_SCOPE = "anything";
    const result = await brokenPi.handlers.tool_call({
      type: "tool_call",
      toolCallId: "0",
      toolName: "write",
      input: { path: "anything/x.mjs", content: "" },
    });
    assert.equal(result?.block, true, "a guard-serve process that never starts must fail closed, never silently allow every write");
    delete process.env.SHEPHERD_ROLE;
    delete process.env.SHEPHERD_SCOPE;
  } finally {
    rmSync(fixtureRoot, { recursive: true, force: true });
  }
}

const pi = makeMockPi();
process.env.SHEPHERD_ROLE = "";
delete process.env.SHEPHERD_ROLE;
await shepherdGuardExtension(pi, CONTENT_DIR);

assert.equal(typeof pi.handlers.tool_call, "function", "shepherdGuardExtension must register a tool_call handler");
assert.equal(typeof pi.handlers.session_shutdown, "function", "shepherdGuardExtension must register a session_shutdown handler to close the guard-serve child");

const toolCall = pi.handlers.tool_call;

// -- 1. SHEPHERD_ROLE unset: fail closed on write/edit/bash, allow everything else through.
{
  delete process.env.SHEPHERD_ROLE;
  const write = await toolCall({ type: "tool_call", toolCallId: "1", toolName: "write", input: { path: "x.md", content: "" } });
  assert.equal(write?.block, true, "an unidentified session must be denied a write");

  const read = await toolCall({ type: "tool_call", toolCallId: "2", toolName: "read", input: { path: "x.md" } });
  assert.equal(read, undefined, "a non-guarded tool (read) is never blocked even with no role");
}

// -- 2. coder writing inside its declared scope: allowed (relayed through the live engine).
{
  process.env.SHEPHERD_ROLE = "coder";
  process.env.SHEPHERD_SCOPE = "packages/harness-pi";
  const result = await toolCall({
    type: "tool_call",
    toolCallId: "3",
    toolName: "write",
    input: { path: "packages/harness-pi/src/x.mjs", content: "" },
  });
  assert.equal(result, undefined, `an in-scope write must be allowed, got ${JSON.stringify(result)}`);
}

// -- 3. coder writing outside its declared scope: denied, with the real engine's reason.
{
  const result = await toolCall({
    type: "tool_call",
    toolCallId: "4",
    toolName: "write",
    input: { path: "crates/core/src/x.rs", content: "" },
  });
  assert.equal(result?.block, true, "an out-of-scope write must be denied");
  assert.ok(result.reason.length > 0, "a denial must carry a non-empty reason");
}

// -- 4. coder attempting `git commit`: denied -- CODER-GIT-WRITE is an implementer-tier
// invariant this collapse must not have loosened (content/predicates/git-custody.toml).
{
  const result = await toolCall({ type: "tool_call", toolCallId: "5", toolName: "bash", input: { command: "git commit -m x" } });
  assert.equal(result?.block, true, "a coder must never be allowed a git commit");
}

// -- 5. the compound-command git obfuscation case: `cd worktree && git push origin
// <other-branch>` must still be caught after the collapse (an auditor falsified this case
// this sprint; test/extension-detectors.test.mjs proves the DETECTOR side, this proves the
// detector's output still reaches a real deny through the new relay).
{
  process.env.SHEPHERD_ROLE = "conductor";
  process.env.SHEPHERD_LANE_BRANCH = "agent-v645-l5-harness";
  const result = await toolCall({
    type: "tool_call",
    toolCallId: "6",
    toolName: "bash",
    input: { command: "cd worktree && git push origin other-lane-branch" },
  });
  assert.equal(result?.block, true, "an obfuscated cross-lane git push must still be denied end-to-end");
}

// -- 6. a plain, non-guarded bash command is never blocked.
{
  const result = await toolCall({ type: "tool_call", toolCallId: "7", toolName: "bash", input: { command: "npm test" } });
  assert.equal(result, undefined, "a bash command with no git/pi invocation must never be blocked");
}

delete process.env.SHEPHERD_ROLE;
delete process.env.SHEPHERD_SCOPE;
delete process.env.SHEPHERD_LANE_BRANCH;

// -- 7. session_shutdown closes the guard-serve child cleanly -- no orphan process. A second
// tool_call after shutdown must still fail closed (the child is gone), never silently allow.
await pi.handlers.session_shutdown({ type: "session_shutdown", reason: "quit" });
process.env.SHEPHERD_ROLE = "coder";
process.env.SHEPHERD_SCOPE = "packages/harness-pi";
// Give the child's `exit` event a tick to fire before the next relay attempt.
await new Promise((resolve) => setTimeout(resolve, 200));
const afterShutdown = await toolCall({
  type: "tool_call",
  toolCallId: "8",
  toolName: "write",
  input: { path: "packages/harness-pi/src/x.mjs", content: "" },
});
assert.equal(afterShutdown?.block, true, "a guard-serve child closed by session_shutdown must fail closed on any further call, never silently allow");
delete process.env.SHEPHERD_ROLE;
delete process.env.SHEPHERD_SCOPE;

console.log("ok: shepherdGuardExtension() verified end-to-end against a live guard-serve relay (fail-closed role, in/out-of-scope write, git-custody, compound-command push, clean shutdown)");
