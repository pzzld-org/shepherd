#!/usr/bin/env node
// packages/harness-pi/bin/materialize.mjs -- CLI over materialize(). Usage:
//   node packages/harness-pi/bin/materialize.mjs --out=<dir> [--check] [--list]
//
// Mirrors packages/compiler/bin/compile.mjs's shape. `--out` is REQUIRED and has no
// default -- this adapter never guesses at a real `~/.pi/agent/` or project `.pi/` install
// path; the caller (an install script, an operator) decides where Pi's tree actually lands.
// --check materializes twice into the SAME --out and asserts the second pass produced
// byte-identical files (the on-disk analogue of compile()'s own --check).
// --list prints every path compile('pi') would emit, one per line, and writes nothing.

import { parseArgs } from "node:util";
import { compile } from "../../compiler/src/compile.mjs";
import { materialize, verifyMaterialized } from "../src/materialize.mjs";

function usage() {
  return "usage: materialize.mjs --out=<dir> [--check] [--list]";
}

function main(argv) {
  let values;
  try {
    ({ values } = parseArgs({
      args: argv,
      options: {
        out: { type: "string" },
        check: { type: "boolean", default: false },
        list: { type: "boolean", default: false },
      },
    }));
  } catch (err) {
    console.error(`error: ${err.message}\n${usage()}`);
    return 2;
  }

  if (values.list) {
    for (const file of compile("pi").files) console.log(file.path);
    return 0;
  }

  if (!values.out) {
    console.error(`error: --out is required\n${usage()}`);
    return 2;
  }

  try {
    const tree = compile("pi");
    const written = materialize(tree, values.out);
    if (values.check) {
      const verdict = verifyMaterialized(compile("pi"), values.out);
      if (!verdict.ok) {
        console.error(`FAIL: ${verdict.reason}`);
        return 1;
      }
    }
    console.log(`ok: materialized ${written.length} file(s) to \`${values.out}\``);
    return 0;
  } catch (err) {
    console.error(`error: ${err.message}`);
    return 1;
  }
}

process.exitCode = main(process.argv.slice(2));
