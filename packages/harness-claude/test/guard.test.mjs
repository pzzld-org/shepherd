#!/usr/bin/env node
// packages/harness-claude/test/guard.test.mjs -- run directly:
//   node packages/harness-claude/test/guard.test.mjs
// plan.md W4-S4/S5/S6 [ACCEPTANCE]: "every guard predicate has an allow AND a deny case, in
// every adapter." `packages/scripts/predicate-coverage.mjs` (the cross-adapter enforcer of
// that line) is out of this step's file scope -- `packages/scripts/` belongs to no single
// adapter -- so this test is this adapter's own proof: `interpretEngineResult` (the one
// piece of decision logic this relay owns) is exercised on an allow verdict, a deny verdict,
// and both classes of engine failure, without needing a live engine process.

import assert from "node:assert/strict";
import { buildGuardHooksEntry, engineUnavailableVerdict, GUARD_MATCHER, interpretEngineResult } from "../src/guard.mjs";

// Allow case: silence, never a `permissionDecision` key at all (Claude's own convention --
// see hooks/scripts/_lib.sh's `pass_silent`).
assert.deepEqual(interpretEngineResult({ decision: "allow" }), {});

// Deny case: cites the predicate/rule/reason, matching hooks/scripts/_lib.sh's `emit_deny`
// shape (`{"permissionDecision":"deny","message":"..."}`).
const deny = interpretEngineResult({
  decision: "deny",
  predicate: "dedup-gate",
  rule: "hit-requires-justification",
  reason: "symbol `normalize_id` already exists at crates/store/src/util.rs:42",
});
assert.equal(deny.permissionDecision, "deny");
assert.match(deny.message, /dedup-gate\/hit-requires-justification/);
assert.match(deny.message, /normalize_id/);

// Malformed/unrecognized engine output fails CLOSED, not open.
const malformed = interpretEngineResult({ nonsense: true });
assert.equal(malformed.permissionDecision, "deny");

// Engine-unreachable path (spawn failure, non-zero exit) also fails closed, with the
// failure detail surfaced rather than swallowed.
const unavailable = engineUnavailableVerdict("ENOENT: bin/shepherd not found");
assert.equal(unavailable.permissionDecision, "deny");
assert.match(unavailable.message, /ENOENT/);

// The hooks.json entry wires the relay script in under the write/dispatch matcher, never
// under Pi's `on('tool_call'` API shape (that pattern belongs to packages/harness-pi alone
// -- see this module's own [DO-NOT-DUPLICATE] doc comment).
const entry = buildGuardHooksEntry();
assert.equal(entry.matcher, GUARD_MATCHER);
assert.equal(entry.hooks[0].type, "command");
assert.match(entry.hooks[0].command, /guard-eval\.mjs$/);

console.log("ok: interpretEngineResult covers an allow case, a deny case, and both engine-failure modes -- all fail closed except the one true allow");
