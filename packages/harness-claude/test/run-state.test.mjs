#!/usr/bin/env node
// packages/harness-claude/test/run-state.test.mjs -- run directly:
//   node packages/harness-claude/test/run-state.test.mjs
// Proves `toCanonicalJson` byte-matches `crates/core/src/run/canonical.rs`'s documented
// encoder, and that `advanceStatus`/`advanceRunState` move the lifecycle forward without
// touching any field the schema does not name -- the two properties release-gate criterion
// C.4 (`test/advance-run.mjs`) depends on for "no migration step" to be true rather than
// asserted.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { advanceRunState, advanceStatus, loadRunState, RUN_STATUSES, storeRunState, toCanonicalJson } from "../src/run-state.mjs";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const REAL_RUN_JSON = join(REPO_ROOT, ".shepherd", "runs", "v645", "run.json");

// --- Golden byte round-trip against the REAL, Rust-written run.json this run itself lives
// under -- not a synthetic fixture, the actual canonical output of
// `RunState::to_canonical_json` on disk right now. ---
const originalBytes = readFileSync(REAL_RUN_JSON, "utf8");
assert.ok(originalBytes.endsWith("}\n"), "fixture assumption: run.json ends with `}\\n` (atomic_write's one trailing newline)");
const parsed = JSON.parse(originalBytes);
const reencoded = `${toCanonicalJson(parsed)}\n`;
assert.equal(reencoded, originalBytes, "toCanonicalJson does not byte-match the real, Rust-written .shepherd/runs/v645/run.json");

// --- Recursive sort, proven with a nested fixture out-of-order at every level (module docs'
// own claim: "recursively sorted keys, ... not just the top"). ---
assert.equal(
  toCanonicalJson({ z: 1, a: { z: 2, a: [{ z: 3, a: 4 }] } }),
  '{\n  "a": {\n    "a": [\n      {\n        "a": 4,\n        "z": 3\n      }\n    ],\n    "z": 2\n  },\n  "z": 1\n}'
);

// --- ASCII-only escaping: BMP above U+007F, and an astral codepoint as a surrogate pair --
// matching `write_json_string`'s two documented cases. ---
assert.equal(toCanonicalJson("café"), '"caf\\u00e9"');
assert.equal(toCanonicalJson("\u{1F600}"), '"\\ud83d\\ude00"'); // 😀

// --- Empty containers render inline, matching write_array/write_object's own early-return. ---
assert.equal(toCanonicalJson({ lanes: [], extra: {} }), '{\n  "extra": {},\n  "lanes": []\n}');

// --- Lifecycle advance. ---
assert.deepEqual([...RUN_STATUSES], ["planted", "planned", "executing", "closing", "closed"]);
assert.equal(advanceStatus("planted"), "planned");
assert.equal(advanceStatus("executing"), "closing");
assert.equal(advanceStatus("closed"), "closed", "advancing the terminal status must be idempotent, not throw or wrap around");
assert.throws(() => advanceStatus("bogus"), /cannot advance unrecognized run status/);

// --- advanceRunState only ever touches status + updated_at; every other field, including
// ones this module names nothing about (`lanes`, `extra`-shaped foreign keys), round-trips
// byte-for-byte -- the actual "no migration step" property. ---
const before = { run: "c4probe", status: "planted", branch: "", unknown_future_field: 42 };
const after = advanceRunState(before);
assert.equal(after.status, "planned");
assert.equal(after.run, before.run);
assert.equal(after.branch, before.branch);
assert.equal(after.unknown_future_field, 42, "advanceRunState must not drop a field it does not name (the #247 regression class)");
assert.ok(Number.isInteger(after.updated_at) && after.updated_at > 0, "advanceRunState must stamp updated_at with a real epoch-seconds value");
assert.notEqual(after, before, "advanceRunState must not mutate its input in place");

// --- load/store round trip through a real temp file. ---
const dir = mkdtempSync(join(tmpdir(), "harness-claude-run-state-"));
try {
  const path = join(dir, "run.json");
  storeRunState(path, after);
  const reloaded = loadRunState(path);
  assert.deepEqual(reloaded, after);
  assert.ok(readFileSync(path, "utf8").endsWith("}\n"), "storeRunState must end the file with exactly one trailing newline, matching atomic_write");
} finally {
  rmSync(dir, { recursive: true, force: true });
}

console.log("ok: toCanonicalJson byte-matches the real run.json on disk; advanceRunState advances status/updated_at only, dropping nothing");
