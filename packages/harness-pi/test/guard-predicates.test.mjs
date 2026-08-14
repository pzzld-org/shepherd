#!/usr/bin/env node
// packages/harness-pi/test/guard-predicates.test.mjs -- run directly:
//   node --experimental-strip-types test/guard-predicates.test.mjs
// Replays every content/predicates/*.toml `[[example]]` (the shared allow/deny case corpus,
// decision 1) through src/guard.ts's evaluate(). This is the "kept in lockstep... not by
// discipline" proof: a change to content/predicates/*.toml is caught here on the next run,
// never a hand-copied fixture silently drifting from the source of truth.

import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPredicates } from "../src/predicates.mjs";
import { loadRoleFacts } from "../src/roles.mjs";
import { evaluate } from "../src/guard.ts";

const CONTENT_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "content");
const CANONICAL_EXAMPLE_KEYS = new Set(["name", "kind", "role", "action", "context", "result", "halt_code", "note"]);

const roleFacts = new Map(
  Array.from(loadRoleFacts(CONTENT_DIR)).map(([role, fact]) => [role, { writeEligible: fact.writeEligible, capabilities: fact.capabilities }])
);

let checked = 0;
let allowCount = 0;
let denyCount = 0;

for (const spec of loadPredicates(CONTENT_DIR)) {
  assert.ok(spec.examples.length > 0, `${spec.id}: predicate corpus carries zero examples`);
  for (const example of spec.examples) {
    // Extra top-level fields (target_role, target_branch, path, symbol, ...) merge into
    // context -- guard.ts reads them uniformly, the fixture doesn't need a bespoke shape.
    const extras = Object.fromEntries(Object.entries(example).filter(([k]) => !CANONICAL_EXAMPLE_KEYS.has(k)));
    const context = { ...example.context, ...extras };

    const verdict = evaluate({ predicateId: spec.id, role: example.role, action: example.action, context }, roleFacts);
    const expectedAllow = example.result === "allow";

    assert.equal(verdict.allow, expectedAllow, `${spec.id}/${example.name}: expected ${example.result}, got ${verdict.allow ? "allow" : "deny"} (${verdict.reason})`);
    if (example.halt_code) {
      assert.equal(verdict.haltCode, example.halt_code, `${spec.id}/${example.name}: expected halt_code \`${example.halt_code}\`, got \`${verdict.haltCode}\``);
    }

    checked += 1;
    if (example.kind === "allow") allowCount += 1;
    else denyCount += 1;
  }

  // Every predicate's corpus carries at least one allow AND one deny case (the property
  // `packages/scripts/predicate-coverage.mjs --require-allow-and-deny` checks across all
  // three adapters -- this asserts it independently for this adapter's own interpreter).
  const kinds = new Set(spec.examples.map((e) => e.kind));
  assert.ok(kinds.has("allow"), `${spec.id}: corpus has no allow case`);
  assert.ok(kinds.has("deny"), `${spec.id}: corpus has no deny case`);
}

assert.ok(allowCount > 0 && denyCount > 0, "the full corpus across all predicates must carry both allow and deny cases");
console.log(`ok: ${checked} guard-predicate example(s) across every content/predicates/*.toml file matched (${allowCount} allow, ${denyCount} deny)`);
