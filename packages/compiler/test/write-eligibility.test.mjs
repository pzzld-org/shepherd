#!/usr/bin/env node
// packages/compiler/test/write-eligibility.test.mjs -- run directly:
//   node packages/compiler/test/write-eligibility.test.mjs
// (also picked up by `npm test` via ../test.mjs.) Named explicitly in plan.md W4-S3's
// [ACCEPTANCE]. Proves the defect content/roles/*.md's `write_eligible` field exists to
// prevent: a read-only role compiling to Codex's write-capable `worker` primitive
// (content/RECONCILIATION.md §`write_eligible` -- "Hazard 1").

import assert from "node:assert/strict";
import { compile } from "../src/compile.mjs";
import { loadRoles } from "../src/content.mjs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const CONTENT_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "content");

const roles = loadRoles(CONTENT_DIR);
const codexTree = compile("codex");
const config = codexTree.files.find((f) => f.path === "shepherd.codex.toml");
assert.ok(config, "compile('codex') must emit shepherd.codex.toml");

const agentTypes = new Map();
for (const line of config.content.split("\n")) {
  const m = line.match(/^(\S+) = "(worker|explorer)"$/);
  if (m) agentTypes.set(m[1], m[2]);
}

// Positive case: every write_eligible role present in the table compiles to `worker`.
// Negative case: every non-write_eligible role present in the table compiles to `explorer`,
// NEVER `worker` -- the exact defect this test exists to catch.
for (const role of roles) {
  const compiled = agentTypes.get(role.role);
  if (!agentTypes.has(role.role)) continue; // root (model_hint: inherit-caller) is excluded
  const expected = role.writeEligible ? "worker" : "explorer";
  assert.equal(
    compiled,
    expected,
    `role \`${role.role}\` has write_eligible=${role.writeEligible} but compiled to \`${compiled}\`, expected \`${expected}\``
  );
}

// Concrete allow/deny pair, named explicitly (a predicate with only a loop assertion can
// pass vacuously if the loop body is ever weakened -- pin two real cases directly).
assert.equal(agentTypes.get("auditor"), "explorer", "auditor (write_eligible: false) must compile to explorer");
assert.equal(agentTypes.get("coder"), "worker", "coder (write_eligible: true) must compile to worker");

// Root is never a candidate at all (content/RECONCILIATION.md row 4).
assert.ok(!agentTypes.has("shepherd"), "root (shepherd) must never appear in the compiled agent-type table");

console.log(`ok: ${agentTypes.size} role(s) in the Codex agent-type table, write_eligible enforced for every one`);
