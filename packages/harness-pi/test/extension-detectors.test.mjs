import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "..", "src", "extension.mjs"), "utf8");
for (const forbidden of [
  "parseGitInvocation",
  "ROLE_TIER",
  "SHEPHERD_ROLE",
  "SHEPHERD_SCOPE",
  "path_in_dispatch_write_scope",
  "predicateId",
]) {
  assert.equal(source.includes(forbidden), false, `Pi adapter must not contain ${forbidden}`);
}

console.log("ok: Pi extension contains transport mapping only, with no predicate or role policy");
