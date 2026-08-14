#!/usr/bin/env node
// packages/harness-pi/test/dispatch.test.mjs -- run directly:
//   node test/dispatch.test.mjs

import assert from "node:assert/strict";
import { buildRoleInvocation } from "../src/dispatch.mjs";
import { loadRoleFacts } from "../src/roles.mjs";

const CONTENT_DIR = new URL("../../../content", import.meta.url).pathname;
const roleFacts = loadRoleFacts(CONTENT_DIR);

// coder: standard model_hint -> sonnet. Its `skill-load`/`tool-discovery` capabilities have
// no Pi tool (src/tools.mjs's declared gap set) -- surfaced, not silently dropped.
{
  const { argv, env, unsupportedCapabilities } = buildRoleInvocation(roleFacts.get("coder"), {
    promptPath: "/tmp/prompts/coder.md",
    writeScope: "packages/harness-pi",
  });
  assert.deepEqual(argv, ["pi", "--print", "--append-system-prompt", "/tmp/prompts/coder.md", "--tools", "read,grep,find,bash,write,edit", "--model", "sonnet"]);
  assert.deepEqual(env, { SHEPHERD_ROLE: "coder", SHEPHERD_SCOPE: "packages/harness-pi" });
  assert.deepEqual(unsupportedCapabilities, ["skill-load", "tool-discovery"]);
}

// engineer: reasoning-high -> bare `opus`, not `opus[1m]`.
{
  const { argv } = buildRoleInvocation(roleFacts.get("engineer"), { promptPath: "/tmp/prompts/engineer.md" });
  assert.ok(argv.includes("--model"), "engineer must carry a --model flag");
  assert.equal(argv[argv.indexOf("--model") + 1], "opus", "engineer's --model value must be the bare id, never opus[1m]");
}

// shepherd (root, inherit-caller, dispatchable: false) must never be spawned as a subprocess.
assert.throws(
  () => buildRoleInvocation(roleFacts.get("shepherd"), { promptPath: "/tmp/prompts/shepherd.md" }),
  /dispatchable: false/,
  "shepherd (root) must refuse to build a subprocess invocation"
);

// promptPath is mandatory.
assert.throws(() => buildRoleInvocation(roleFacts.get("coder"), {}), /promptPath is required/);

// conductor: no --model flag omission bug, and its Pi-unsupported capabilities surface.
{
  const { unsupportedCapabilities } = buildRoleInvocation(roleFacts.get("conductor"), { promptPath: "/tmp/prompts/conductor.md" });
  assert.ok(unsupportedCapabilities.includes("dispatch"), "conductor's `dispatch` gap must surface from buildRoleInvocation");
}

console.log("ok: buildRoleInvocation() verified for coder, engineer, shepherd (refusal), conductor");
