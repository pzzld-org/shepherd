#!/usr/bin/env node
// packages/compiler/test/reproducibility.test.mjs -- run directly:
//   node packages/compiler/test/reproducibility.test.mjs
// Proves compile() is a PURE function of content/: same input, same bytes out, every call
// (the exact property plan.md's [USER-STYLE] states and this step's dispatch brief
// mandates -- "compile twice, assert byte-identical output").

import assert from "node:assert/strict";
import { compile, TARGETS } from "../src/compile.mjs";

for (const target of TARGETS) {
  const first = compile(target);
  const second = compile(target);

  assert.equal(first.digest, second.digest, `compile('${target}') digest drifted between two calls`);
  assert.deepEqual(
    first.files,
    second.files,
    `compile('${target}') file list drifted between two calls despite matching digest`
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(first)),
    JSON.parse(JSON.stringify(second)),
    `compile('${target}') is not byte-identical across two calls`
  );

  console.log(`ok: compile('${target}') is byte-identical across two calls -- ${first.files.length} file(s)`);
}
