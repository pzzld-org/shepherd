#!/usr/bin/env node
// packages/harness-codex/test.mjs -- runs every packages/harness-codex/test/*.test.mjs file
// (each is also directly runnable on its own -- see the usage comment at the top of each).
// Replaces the intentionally failing W0-S7 placeholder now that the adapter exists (W4-S5).

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
