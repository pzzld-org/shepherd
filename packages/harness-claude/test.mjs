#!/usr/bin/env node
// packages/harness-claude/test.mjs -- runs every packages/harness-claude/test/*.test.mjs
// file (each also directly runnable on its own), mirroring
// packages/compiler/test.mjs's own runner exactly rather than reinventing one.
// `test/advance-run.mjs` is deliberately NOT `*.test.mjs` -- it is release-gate criterion
// C.4's standalone CLI script (plan.md W4-S4 Action 4), invoked by name with an argv, not
// auto-discovered here.

import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const TEST_DIR = join(HERE, "test");

const testFiles = readdirSync(TEST_DIR)
  .filter((f) => f.endsWith(".test.mjs"))
  .sort();

let failures = 0;
for (const file of testFiles) {
  try {
    await import(pathToFileURL(join(TEST_DIR, file)).href);
    console.log(`PASS ${file}`);
  } catch (err) {
    failures += 1;
    console.error(`FAIL ${file}`);
    console.error(err.stack ?? String(err));
  }
}

console.log(`\n${testFiles.length - failures}/${testFiles.length} test file(s) passed`);
process.exitCode = failures > 0 ? 1 : 0;
