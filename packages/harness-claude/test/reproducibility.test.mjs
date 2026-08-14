#!/usr/bin/env node
// packages/harness-claude/test/reproducibility.test.mjs -- run directly:
//   node packages/harness-claude/test/reproducibility.test.mjs
// This step's dispatch brief, verbatim: "Emission must be REPRODUCIBLE -- running it twice
// produces byte-identical output. Ship the test that proves it, in this diff." Mirrors
// packages/compiler/test/reproducibility.test.mjs's own proof, one level up the pipeline:
// `compile('claude')` is already proven pure there; this proves `finalizeClaudeTree` stays
// pure on top of it (model resolution is a deterministic table lookup, so it must).

import assert from "node:assert/strict";
import { compile } from "../../compiler/src/compile.mjs";
import { finalizeClaudeTree } from "../src/finalize.mjs";

const first = finalizeClaudeTree(compile("claude"));
const second = finalizeClaudeTree(compile("claude"));

assert.equal(first.digest, second.digest, "finalizeClaudeTree(compile('claude')) digest drifted between two calls");
assert.deepEqual(first.files, second.files, "finalizeClaudeTree(compile('claude')) file list drifted between two calls despite matching digest");
assert.deepEqual(
  JSON.parse(JSON.stringify(first)),
  JSON.parse(JSON.stringify(second)),
  "finalizeClaudeTree(compile('claude')) is not byte-identical across two calls"
);

// Every role file must actually carry a resolved `model:` line, never a leftover
// `model_hint:` -- the one thing this stage exists to guarantee.
for (const file of first.files.filter((f) => f.kind === "role")) {
  assert.match(file.content, /^model: \S+$/m, `${file.path}: missing resolved \`model:\` line`);
  assert.doesNotMatch(file.content, /^model_hint:/m, `${file.path}: leaked unresolved \`model_hint:\` line`);
}

console.log(`ok: finalizeClaudeTree(compile('claude')) is byte-identical across two calls -- ${first.files.length} file(s), digest ${first.digest}`);
