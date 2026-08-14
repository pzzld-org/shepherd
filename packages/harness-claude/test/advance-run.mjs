#!/usr/bin/env node
// packages/harness-claude/test/advance-run.mjs -- the JS half of release-gate criterion C.4
// (plan.md W4-S4 Action 4). Invoked directly by name, not picked up by `test.mjs`'s
// `*.test.mjs` auto-discovery (it takes an argv, not assertions):
//
//   ./target/release/shepherd run init c4probe &&
//     node packages/harness-claude/test/advance-run.mjs c4probe &&
//     ./target/release/shepherd run show c4probe | grep -q '"status"'
//
// Loads `.shepherd/runs/<run>/run.json` (the Rust binary's own write, per `run init`),
// advances its `status` one lifecycle step via `src/run-state.mjs`'s `advanceRunState`, and
// stores it back through the same module's byte-exact canonical encoder -- proving the Rust
// binary can subsequently `run show` a file THIS adapter wrote, with no migration step, per
// `crates/core/src/run.rs`'s own documented schema.

import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { advanceRunState, loadRunState, storeRunState } from "../src/run-state.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");

function main(argv) {
  const run = argv[2];
  if (!run) {
    console.error("usage: advance-run.mjs <run-id>");
    return 2;
  }
  const path = join(REPO_ROOT, ".shepherd", "runs", run, "run.json");
  const before = loadRunState(path);
  const after = advanceRunState(before);
  storeRunState(path, after);
  console.log(`ok: ${run} status ${before.status ?? "(unset)"} -> ${after.status}`);
  return 0;
}

process.exitCode = main(process.argv);
