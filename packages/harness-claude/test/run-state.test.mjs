import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
assert.equal(
  existsSync(join(here, "..", "src", "run-state.mjs")),
  false,
  "run-state mutation belongs to the canonical Rust CLI, never a harness adapter",
);

console.log("ok: Claude adapter-local run-state mutation is retired");
