#!/usr/bin/env node
// packages/harness-claude/test/model.test.mjs -- run directly:
//   node packages/harness-claude/test/model.test.mjs
// Pins `resolveModel`'s three known cases against the values the CURRENTLY COMMITTED
// `agents/*.md` actually carries -- not just against `src/model.mjs`'s own table, which
// would only prove the module agrees with itself. `assumptions[]` in this step's report
// names this comparison as verified, not guessed; this test is the receipt.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveModel } from "../src/model.mjs";
import { loadRoles } from "../../compiler/src/content.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const CONTENT_DIR = join(REPO_ROOT, "content");
const AGENTS_DIR = join(REPO_ROOT, "agents");

assert.equal(resolveModel("standard"), "sonnet");
assert.equal(resolveModel("reasoning-high"), "opus[1m]");
assert.equal(resolveModel("inherit-caller"), "inherit");
assert.throws(() => resolveModel("nonexistent-hint"), /unknown model_hint/);

const roles = loadRoles(CONTENT_DIR);
assert.ok(roles.length > 0, "expected at least one content/roles/*.md role");

let checked = 0;
for (const role of roles) {
  const agentPath = join(AGENTS_DIR, `${role.role}.md`);
  if (!readdirSync(AGENTS_DIR).includes(`${role.role}.md`)) continue;
  const handText = readFileSync(agentPath, "utf8");
  const handModel = handText.match(/^model:\s*(\S+)/m)?.[1];
  assert.ok(handModel, `agents/${role.role}.md carries no model: line`);
  assert.equal(
    resolveModel(role.modelHint),
    handModel,
    `role \`${role.role}\`: resolveModel(${JSON.stringify(role.modelHint)}) = ${resolveModel(role.modelHint)}, but agents/${role.role}.md says model: ${handModel}`
  );
  checked += 1;
}
assert.equal(checked, roles.length, "expected every content/ role to have a matching agents/*.md file to check against");

console.log(`ok: resolveModel matches agents/*.md's hand-maintained model: for all ${checked} role(s)`);
