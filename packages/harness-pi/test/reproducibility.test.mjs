#!/usr/bin/env node
// packages/harness-pi/test/reproducibility.test.mjs -- run directly:
//   node test/reproducibility.test.mjs
// Proves materialize() is deterministic at the FILESYSTEM level, not just compile('pi')'s
// in-memory digest (already covered by packages/compiler/test/reproducibility.test.mjs):
// two independent materialize() calls into two independent temp directories produce
// byte-identical files on disk, every time.

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { compile } from "../../compiler/src/compile.mjs";
import { materialize } from "../src/materialize.mjs";

const dirA = mkdtempSync(join(tmpdir(), "harness-pi-repro-a-"));
const dirB = mkdtempSync(join(tmpdir(), "harness-pi-repro-b-"));

try {
  const treeA = compile("pi");
  const treeB = compile("pi");
  assert.equal(treeA.digest, treeB.digest, "compile('pi') digest drifted between two calls");

  const writtenA = materialize(treeA, dirA);
  const writtenB = materialize(treeB, dirB);
  assert.equal(writtenA.length, writtenB.length, "materialize() wrote a different file count across two calls");
  assert.ok(writtenA.length > 0, "materialize() wrote zero files");

  for (let i = 0; i < treeA.files.length; i += 1) {
    const relPath = treeA.files[i].path;
    const contentA = readFileSync(writtenA[i], "utf8");
    const contentB = readFileSync(writtenB[i], "utf8");
    assert.equal(contentA, contentB, `\`${relPath}\` differs on disk between two materialize() calls`);
    assert.equal(contentA, treeA.files[i].content, `\`${relPath}\` on disk does not match the EmittedTree's own content`);
  }

  console.log(`ok: materialize('pi') is byte-identical on disk across two calls -- ${writtenA.length} file(s)`);
} finally {
  rmSync(dirA, { recursive: true, force: true });
  rmSync(dirB, { recursive: true, force: true });
}
