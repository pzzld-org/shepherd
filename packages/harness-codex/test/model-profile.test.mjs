#!/usr/bin/env node
// packages/harness-codex/test/model-profile.test.mjs -- run directly:
//   node packages/harness-codex/test/model-profile.test.mjs

import assert from "node:assert/strict";
import { allProfiles, resolveProfile, ROOT_MODEL_HINT } from "../src/model-profile.mjs";

assert.equal(ROOT_MODEL_HINT, "inherit-caller");

assert.deepEqual(resolveProfile("standard"), { name: "standard", reasoningEffort: "medium" });
assert.deepEqual(resolveProfile("reasoning-high"), { name: "reasoning-high", reasoningEffort: "high" });

// No Claude-specific token (`opus`, `sonnet`, `[1m]`) ever leaks into a profile name or its
// reasoning_effort -- the exact hazard the dispatch brief names ("opus[1m] maps to opus; the
// [1m] suffix... must not leak into a Codex profile").
for (const profile of allProfiles()) {
  assert.doesNotMatch(profile.name, /opus|sonnet|haiku|fable|\[1m\]/i);
  assert.doesNotMatch(profile.reasoningEffort, /opus|sonnet|haiku|fable|\[1m\]/i);
}

assert.throws(() => resolveProfile("inherit-caller"), /root-only/);
assert.throws(() => resolveProfile("nonsense"), /no Codex profile mapping/);

console.log(`ok: model-profile resolves every non-root model_hint to a Claude-syntax-free profile name (${allProfiles().length} profile(s))`);
