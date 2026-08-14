#!/usr/bin/env node
// packages/harness-codex/test/reproducibility.test.mjs -- run directly:
//   node packages/harness-codex/test/reproducibility.test.mjs
// Proves buildCodexTree() is a PURE function of content/ + this adapter's own model-profile
// mapping: same inputs, byte-identical output, every call -- the exact property
// packages/compiler/test/reproducibility.test.mjs proves for compile() itself, extended here
// over this adapter's own post-compile augmentation (the dispatch brief requires this test
// "in this diff").

import assert from "node:assert/strict";
import { buildCodexTree } from "../src/materialize.mjs";

const first = buildCodexTree();
const second = buildCodexTree();

assert.equal(first.digest, second.digest, "buildCodexTree() digest drifted between two calls");
assert.deepEqual(
  JSON.parse(JSON.stringify(first)),
  JSON.parse(JSON.stringify(second)),
  "buildCodexTree() is not byte-identical across two calls"
);

console.log(`ok: buildCodexTree() is byte-identical across two calls -- ${first.files.length} file(s), digest ${first.digest}`);
