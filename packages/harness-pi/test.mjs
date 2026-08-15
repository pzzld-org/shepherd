#!/usr/bin/env node
// packages/harness-pi/test.mjs -- runs every packages/harness-pi/test/*.test.mjs file (each
// is also directly runnable on its own). Replaces the intentionally
// failing W0-S7 placeholder now that the adapter exists (W4-S6).

import { readdirSync } from "node:fs";
import { existsSync, mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const TEST_DIR = join(HERE, "test");

// Extension tests load the generated Rust component, never an injected policy
// object. Reuse an operator-provided staged module; otherwise transpile the
// checked-in wasm artifact into a disposable test directory.
if (!process.env.SHEPHERD_COMPONENT_MODULE) {
  const root = join(HERE, "..", "..");
  const artifact = process.env.SHEPHERD_COMPONENT_WASM ?? join(root, "target/wasm32-wasip2/release/shepherd_component.wasm");
  const jco = process.env.SHEPHERD_JCO_BIN ?? join(root, "node_modules/.bin/jco");
  if (!existsSync(artifact) || !existsSync(jco)) {
    throw new Error(`Pi extension tests require a staged component module or generated inputs: ${artifact}, ${jco}`);
  }
  const stage = mkdtempSync(join(tmpdir(), "shepherd-pi-component-"));
  const runtime = join(stage, "runtime");
  mkdirSync(runtime, { recursive: true });
  const result = spawnSync(jco, ["transpile", artifact, "--out-dir", runtime, "--name", "shepherd-component", "--quiet"], {
    cwd: root,
    encoding: "utf8",
  });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout || "jco component transpilation failed");
  symlinkSync(join(root, "node_modules"), join(stage, "node_modules"), "dir");
  process.env.SHEPHERD_COMPONENT_MODULE = join(runtime, "shepherd-component.js");
}

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
