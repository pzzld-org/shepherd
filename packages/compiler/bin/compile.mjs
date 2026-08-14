#!/usr/bin/env node
// packages/compiler/bin/compile.mjs -- CLI over compile(target). Usage:
//   node packages/compiler/bin/compile.mjs --target=<claude|codex|pi> [--check] [--list]
//
// --check  compiles TWICE and asserts the two EmittedTrees are byte-identical -- the
//          reproducibility contract this step's acceptance line calls "idempotent, diffs
//          clean". Never writes to disk, matching packages/compiler/'s file-scope boundary.
// --list   prints every emitted file's path, one per line, and nothing else.
// (none)   prints the EmittedTree as JSON to stdout -- the machine-readable form
//          packages/harness-{claude,codex,pi} (W4-S4/S5/S6) read to materialize the real
//          tree; this CLI is a pure reader of content/, never a writer of it.

import { parseArgs } from "node:util";
import { compile, TARGETS } from "../src/compile.mjs";

function usage() {
  return `usage: compile.mjs --target=<${TARGETS.join("|")}> [--check] [--list]`;
}

function parseCliArgs(argv) {
  return parseArgs({
    args: argv,
    options: {
      target: { type: "string" },
      check: { type: "boolean", default: false },
      list: { type: "boolean", default: false },
    },
  });
}

function runCheck(target) {
  const first = compile(target);
  const second = compile(target);
  if (first.digest !== second.digest) {
    console.error(`FAIL: compile('${target}') is not idempotent -- digest ${first.digest} vs ${second.digest}`);
    return 1;
  }
  console.log(`ok: compile('${target}') is idempotent -- ${first.files.length} file(s), digest ${first.digest}`);
  return 0;
}

function runList(target) {
  for (const file of compile(target).files) console.log(file.path);
  return 0;
}

function runPrint(target) {
  console.log(JSON.stringify(compile(target), null, 2));
  return 0;
}

function main(argv) {
  let values;
  try {
    ({ values } = parseCliArgs(argv));
  } catch (err) {
    console.error(`error: ${err.message}\n${usage()}`);
    return 2;
  }

  if (!values.target || !TARGETS.includes(values.target)) {
    console.error(`error: --target is required and must be one of ${TARGETS.join(", ")}\n${usage()}`);
    return 2;
  }

  try {
    if (values.check) return runCheck(values.target);
    if (values.list) return runList(values.target);
    return runPrint(values.target);
  } catch (err) {
    console.error(`error: ${err.message}`);
    return 1;
  }
}

process.exitCode = main(process.argv.slice(2));
