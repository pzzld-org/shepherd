#!/usr/bin/env node
// packages/harness-codex/bin/apply.mjs -- CLI over src/materialize.mjs. Usage:
//   node packages/harness-codex/bin/apply.mjs [--dir=<targetDir>] [--check]
//
// (none)  materializes `compile('codex')` (model-profile-augmented) onto `--dir`, default
//         this package's own root -- the real, committed `shepherd.codex.toml` +
//         `skills/**` the plan's [ACCEPTANCE] greps against.
// --check builds the tree TWICE and asserts byte-identical digests without writing anything
//         (mirrors packages/compiler/bin/compile.mjs's own `--check`) -- the reproducibility
//         proof this step's dispatch brief requires in the diff.

import { parseArgs } from "node:util";
import { buildCodexTree, DEFAULT_TARGET_DIR, materialize } from "../src/materialize.mjs";

function runCheck() {
  const first = buildCodexTree();
  const second = buildCodexTree();
  if (first.digest !== second.digest) {
    console.error(`FAIL: buildCodexTree() is not idempotent -- digest ${first.digest} vs ${second.digest}`);
    return 1;
  }
  console.log(`ok: buildCodexTree() is idempotent -- ${first.files.length} file(s), digest ${first.digest}`);
  return 0;
}

function runApply(targetDir) {
  const tree = materialize(targetDir);
  for (const file of tree.files) console.log(`wrote ${file.path}`);
  console.log(`ok: materialized ${tree.files.length} file(s) to ${targetDir} -- digest ${tree.digest}`);
  return 0;
}

function main(argv) {
  let values;
  try {
    ({ values } = parseArgs({
      args: argv,
      options: { dir: { type: "string" }, check: { type: "boolean", default: false } },
    }));
  } catch (err) {
    console.error(`error: ${err.message}\nusage: apply.mjs [--dir=<targetDir>] [--check]`);
    return 2;
  }

  try {
    if (values.check) return runCheck();
    return runApply(values.dir ?? DEFAULT_TARGET_DIR);
  } catch (err) {
    console.error(`error: ${err.message}`);
    return 1;
  }
}

process.exitCode = main(process.argv.slice(2));
