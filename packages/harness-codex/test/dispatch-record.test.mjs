import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const retired = join(here, "..", "src", "dispatch-record.mjs");
assert.equal(existsSync(retired), false, "adapter-private dispatch record store must be retired");
const hook = readFileSync(join(here, "..", "hooks", "scripts", "shepherd_guard.mjs"), "utf8");
for (const forbidden of ["parseIntendedRole", "recordSpawnDispatch", "resolveDataDir", "writeDispatchRecord"]) {
  assert.equal(hook.includes(forbidden), false, `Codex hook must not contain ${forbidden}`);
}

console.log("ok: Codex adapter-private role parsing and record mutation are retired");
