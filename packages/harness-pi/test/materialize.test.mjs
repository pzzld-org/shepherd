#!/usr/bin/env node
// packages/harness-pi/test/materialize.test.mjs -- run directly:
//   node test/materialize.test.mjs

import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { compile } from "../../compiler/src/compile.mjs";
import { materialize, verifyMaterialized } from "../src/materialize.mjs";

const dir = mkdtempSync(join(tmpdir(), "harness-pi-materialize-"));
try {
  const tree = compile("pi");
  const written = materialize(tree, dir);
  assert.equal(written.length, tree.files.length, "materialize() must write exactly one file per EmittedFile");

  const okVerdict = verifyMaterialized(tree, dir);
  assert.deepEqual(okVerdict, { ok: true }, "a freshly materialized tree must verify clean");

  // Negative control: hand-corrupt one file, verifyMaterialized() must catch the drift.
  writeFileSync(join(dir, tree.files[0].path), "corrupted", "utf8");
  const driftVerdict = verifyMaterialized(tree, dir);
  assert.equal(driftVerdict.ok, false, "verifyMaterialized() must detect on-disk content drift");
  assert.match(driftVerdict.reason, /content drift/);

  // Negative control: delete one file entirely.
  writeFileSync(join(dir, tree.files[0].path), tree.files[0].content, "utf8"); // restore first
  rmSync(join(dir, tree.files[1].path));
  const missingVerdict = verifyMaterialized(tree, dir);
  assert.equal(missingVerdict.ok, false, "verifyMaterialized() must detect a missing file");
  assert.match(missingVerdict.reason, /missing/);

  console.log(`ok: materialize()/verifyMaterialized() round-trip and both negative controls (drift, missing) pass`);
} finally {
  rmSync(dir, { recursive: true, force: true });
}
