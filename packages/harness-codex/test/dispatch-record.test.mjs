#!/usr/bin/env node
// packages/harness-codex/test/dispatch-record.test.mjs -- run directly:
//   node packages/harness-codex/test/dispatch-record.test.mjs
// Unit coverage for src/dispatch-record.mjs's pure/fs helpers: role parsing (both signals --
// `task_name`'s `shepherd_<role>_<node>` shape and a `# @<role>` message header), agent-id
// extraction from a spawn tool_response, and the write/read/resolve record round-trip.

import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  extractAgentId,
  isSpawnTool,
  parseIntendedRole,
  readDispatchRecord,
  recordSpawnDispatch,
  resolveRole,
  writeDispatchRecord,
} from "../src/dispatch-record.mjs";

// isSpawnTool ---------------------------------------------------------------------------------
assert.equal(isSpawnTool("spawn_agent"), true);
assert.equal(isSpawnTool("collaborationspawn_agent"), true);
assert.equal(isSpawnTool("Bash"), false);

// parseIntendedRole: task_name's `shepherd_<role>_<node>` wins over a message header ----------
assert.equal(parseIntendedRole({ task_name: "shepherd_coder_b1codex", message: "# @auditor\nignored" }), "coder");
assert.equal(parseIntendedRole({ task_name: "shepherd_discovery_scan_a" }), "discovery");
// falls back to a `# @<role>` message header when task_name doesn't carry the shape
assert.equal(parseIntendedRole({ message: "# @conductor -- Lane Executor\n\nbody text" }), "conductor");
assert.equal(parseIntendedRole({ prompt: "# @critic\n\nbody text" }), "critic");
// unresolvable either way -> "unknown", never omitted (a record still gets written for it)
assert.equal(parseIntendedRole({ task_name: "not-a-shepherd-task" }), "unknown");
assert.equal(parseIntendedRole(undefined), "unknown");

// extractAgentId: JSON string, plain object, and both field-name fallbacks --------------------
assert.equal(extractAgentId('{"agent_id":"abc123","task_name":"shepherd_coder_b1"}'), "abc123");
assert.equal(extractAgentId({ id: "xyz789" }), "xyz789");
assert.equal(extractAgentId("not json"), null);
assert.equal(extractAgentId({}), null);
assert.equal(extractAgentId(null), null);

// write/read/resolve round-trip, against a real disposable dataDir ---------------------------
const dataDir = mkdtempSync(join(tmpdir(), "harness-codex-dispatch-record-test-"));

writeDispatchRecord(dataDir, "agent-1", "auditor");
const record = readDispatchRecord(dataDir, "agent-1");
assert.equal(record.agent_id, "agent-1");
assert.equal(record.agent_role, "auditor");
assert.equal(typeof record.recorded_at, "number");

assert.equal(readDispatchRecord(dataDir, "agent-never-written"), null);

assert.deepEqual(resolveRole(null, dataDir), { kind: "no-marker" });
assert.deepEqual(resolveRole("", dataDir), { kind: "no-marker" });
assert.deepEqual(resolveRole("agent-1", dataDir), { kind: "resolved", role: "auditor", agentId: "agent-1" });
assert.deepEqual(resolveRole("agent-ghost", dataDir), { kind: "missing-record", agentId: "agent-ghost" });

// recordSpawnDispatch: PostToolUse(spawn_agent) shape -- tool_input + tool_response together --
const written = recordSpawnDispatch({
  toolInput: { task_name: "shepherd_worker_w1", message: "ignored" },
  toolResponse: '{"agent_id":"agent-2","task_name":"shepherd_worker_w1"}',
  dataDir,
});
assert.equal(written.agent_role, "worker");
assert.deepEqual(resolveRole("agent-2", dataDir), { kind: "resolved", role: "worker", agentId: "agent-2" });

// no agent id in the response -> no-op, nothing written, nothing to key on
assert.equal(recordSpawnDispatch({ toolInput: { task_name: "shepherd_worker_w2" }, toolResponse: "{}", dataDir }), null);

rmSync(dataDir, { recursive: true, force: true });

console.log("ok: dispatch-record.mjs resolves role from task_name/message, extracts agent ids, and round-trips real records on disk");
