#!/usr/bin/env node
// packages/harness-pi/test/model-pin.test.mjs -- run directly:
//   node test/model-pin.test.mjs
// Pins this step's brief trap #3 verbatim: "Model pinning is a subprocess `--model` flag
// carrying the BARE model id. `opus[1m]` becomes `opus`."

import assert from "node:assert/strict";
import { resolvePiModelFlag, toBareModelId } from "../src/models.mjs";
import { loadRoleFacts } from "../src/roles.mjs";

assert.equal(toBareModelId("opus[1m]"), "opus", "opus[1m] must become the bare id `opus`");
assert.equal(toBareModelId("sonnet"), "sonnet", "a slug with no annotation must pass through unchanged");

assert.equal(resolvePiModelFlag("standard"), "sonnet");
assert.equal(resolvePiModelFlag("reasoning-high"), "opus", "reasoning-high must resolve to the bare id, not opus[1m]");
assert.equal(resolvePiModelFlag("inherit-caller"), undefined, "inherit-caller (root) is never spawned as its own subprocess");
assert.throws(() => resolvePiModelFlag("nonexistent-hint"), /unknown model_hint/);

// Cross-check against the live content/roles/*.md corpus, not a hand-picked pair: every
// role's declared model_hint must resolve without throwing.
const CONTENT_DIR = new URL("../../../content", import.meta.url).pathname;
const roleFacts = loadRoleFacts(CONTENT_DIR);
for (const [role, fact] of roleFacts) {
  assert.doesNotThrow(() => resolvePiModelFlag(fact.modelHint), `role \`${role}\`'s model_hint \`${fact.modelHint}\` must resolve`);
}
assert.equal(resolvePiModelFlag(roleFacts.get("shepherd").modelHint), undefined, "shepherd (root) must resolve to no --model flag");
assert.equal(resolvePiModelFlag(roleFacts.get("engineer").modelHint), "opus", "engineer (reasoning-high) must resolve to the bare `opus` id");
assert.equal(resolvePiModelFlag(roleFacts.get("coder").modelHint), "sonnet", "coder (standard) must resolve to `sonnet`");

console.log(`ok: model_hint -> Pi --model resolution verified for all ${roleFacts.size} content/roles/*.md role(s)`);
