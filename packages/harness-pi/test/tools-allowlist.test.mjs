#!/usr/bin/env node
// packages/harness-pi/test/tools-allowlist.test.mjs -- run directly:
//   node test/tools-allowlist.test.mjs
// Proves the trap this step's brief names first: "`--tools` is a REPLACING allowlist, not
// additive... Emit the full desired set per role, explicitly." Every resolved tool name is
// also checked against PI_BUILTIN_TOOLS -- the real installed binary's own registry -- so no
// invented tool name can silently pass.

import assert from "node:assert/strict";
import { PI_BUILTIN_TOOLS, PI_UNSUPPORTED_CAPABILITIES, resolvePiTools } from "../src/tools.mjs";
import { loadRoleFacts } from "../src/roles.mjs";

assert.throws(() => resolvePiTools(["not-a-real-capability"]), /unknown capability/);

// coder: read/search/shell/write/skill-load/tool-discovery -> the full replacing set, no
// subtraction, no invented tool name.
{
  const { tools, unsupported } = resolvePiTools(["read", "search", "shell", "write", "skill-load", "tool-discovery"]);
  assert.deepEqual(tools, ["read", "grep", "find", "bash", "write", "edit"], "coder's full --tools set must be exact and order-stable");
  assert.deepEqual(unsupported, ["skill-load", "tool-discovery"], "coder's two Pi-unsupported capabilities must be reported, not silently dropped");
  for (const tool of tools) assert.ok(PI_BUILTIN_TOOLS.includes(tool), `\`${tool}\` is not one of Pi's real builtin tools`);
}

// A capability that maps to zero tools (report-write's sibling, `write`) must still be
// deduped against a role holding BOTH `write` and `report-write`.
{
  const { tools } = resolvePiTools(["write", "report-write"]);
  assert.deepEqual(tools, ["write", "edit"], "`write` and `report-write` share the `write` tool -- must dedupe, not double-list");
}

// Cross-check against the live content/roles/*.md corpus: every role resolves without
// throwing, and every returned tool is a real Pi builtin -- never an invented name.
const CONTENT_DIR = new URL("../../../content", import.meta.url).pathname;
const roleFacts = loadRoleFacts(CONTENT_DIR);
for (const [role, fact] of roleFacts) {
  const { tools, unsupported } = resolvePiTools(fact.capabilities);
  for (const tool of tools) assert.ok(PI_BUILTIN_TOOLS.includes(tool), `role \`${role}\` resolved to unknown tool \`${tool}\``);
  for (const capability of unsupported) assert.ok(PI_UNSUPPORTED_CAPABILITIES.includes(capability), `role \`${role}\`'s gap \`${capability}\` is not a declared Pi gap`);
}

// conductor's dispatch/message-peer/task-tracking/web-research/schedule-wakeup have no Pi
// tool -- named gaps, not silently dropped.
{
  const { unsupported } = resolvePiTools(roleFacts.get("conductor").capabilities);
  for (const cap of ["dispatch", "message-peer", "task-tracking", "web-research", "schedule-wakeup"]) {
    assert.ok(unsupported.includes(cap), `conductor's \`${cap}\` gap must be reported`);
  }
}

console.log(`ok: --tools allowlist resolution verified for all ${roleFacts.size} content/roles/*.md role(s), zero invented tool names`);
