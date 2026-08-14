#!/usr/bin/env node
// packages/harness-pi/test/team-primitive-absent.test.mjs -- run directly:
//   node test/team-primitive-absent.test.mjs
// Operationalizes this step's [NON-GOALS]: "Do not add a Pi team primitive by depending on
// the unvetted third-party `@tintinweb/pi-subagents`; declare the capability absent
// instead." A negative control: this fails loudly the day someone adds that dependency to
// "fix" Pi's missing team primitive, or removes the documented gap without replacing it.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { resolvePiTools } from "../src/tools.mjs";

const PACKAGE_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const packageJson = JSON.parse(readFileSync(join(PACKAGE_ROOT, "package.json"), "utf8"));
const readme = readFileSync(join(PACKAGE_ROOT, "README.md"), "utf8");

const allDeclaredDeps = {
  ...(packageJson.dependencies ?? {}),
  ...(packageJson.devDependencies ?? {}),
  ...(packageJson.optionalDependencies ?? {}),
};
assert.ok(!("@tintinweb/pi-subagents" in allDeclaredDeps), "package.json must not depend on the unvetted third-party pi-subagents extension");

assert.match(readme, /pi-subagents/, "README must name the third-party extension it deliberately does not depend on");
assert.match(readme, /no native team/i, "README must state the team/subagent primitive gap explicitly, not silently");

// `dispatch` has no Pi tool -- the guard/tools layer's own declaration of the same gap.
const { unsupported } = resolvePiTools(["dispatch"]);
assert.deepEqual(unsupported, ["dispatch"], "the `dispatch` capability must be a declared Pi gap, never silently mapped to a tool");

console.log("ok: no pi-subagents dependency, the team-primitive gap is named in README and in src/tools.mjs");
