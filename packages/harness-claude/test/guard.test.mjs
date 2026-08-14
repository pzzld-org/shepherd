#!/usr/bin/env node
// packages/harness-claude/test/guard.test.mjs -- run directly:
//   node packages/harness-claude/test/guard.test.mjs
// plan.md W4-S4/S5/S6 [ACCEPTANCE]: "every guard predicate has an allow AND a deny case, in
// every adapter." `packages/scripts/predicate-coverage.mjs` (the cross-adapter enforcer of
// that line) is out of this step's file scope -- `packages/scripts/` belongs to no single
// adapter -- so this test is this adapter's own proof: `interpretEngineResult` (the one
// piece of decision logic this relay owns) is exercised on an allow verdict, a deny verdict,
// an unresolved verdict, and both classes of engine failure, without needing a live engine
// process -- PLUS one integration case (below) that spawns the real relay against the real,
// now-live `services/cli/shepherd_cli/` engine end to end (DF-76). Skipping that integration
// case because the engine "might not be installed" is exactly how `src/guard.mjs` stayed
// written against an unrunnable contract for a whole wave -- an absent/broken engine here is
// a FAILURE of this test, never a silent skip.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildGuardHooksEntry, engineUnavailableVerdict, GUARD_MATCHER, interpretEngineResult } from "../src/guard.mjs";

// Allow case: silence, never a `permissionDecision` key at all (Claude's own convention --
// see hooks/scripts/_lib.sh's `pass_silent`).
assert.deepEqual(interpretEngineResult({ decision: "allow" }), {});

// Deny case: cites the predicate/rule/halt_code/reason, matching hooks/scripts/_lib.sh's
// `emit_deny` shape (`{"permissionDecision":"deny","message":"..."}`) plus the halt code the
// engine's own `[[example]].halt_code` corpus attests -- surfaced now, not dropped.
const deny = interpretEngineResult({
  decision: "deny",
  predicate: "git-custody",
  rule: "implementer-never-writes-git",
  halt_code: "CODER-GIT-WRITE",
  reason: "A role dispatched to implement one file-disjoint scope never performs any version-control write",
});
assert.equal(deny.permissionDecision, "deny");
assert.match(deny.message, /git-custody\/implementer-never-writes-git/);
assert.match(deny.message, /CODER-GIT-WRITE/);
assert.match(deny.message, /never performs any version-control write/);

// Unresolved case (DF-75): the engine could not identify the acting role (or another
// required fact) and explicitly refuses to guess allow OR deny. This harness's posture is
// still DENY (never a silent no-op), but the message must name it as an unresolved verdict,
// distinctly from the generic "malformed" bucket below -- an operator reading the deny
// should be able to tell "the engine couldn't decide" apart from "something is broken."
const unresolved = interpretEngineResult({
  decision: "unresolved",
  reason: "missing `role` -- cannot identify the acting role",
  missing: ["role"],
});
assert.equal(unresolved.permissionDecision, "deny");
assert.match(unresolved.message, /could not reach a verdict/);
assert.match(unresolved.message, /missing: role/);
assert.doesNotMatch(unresolved.message, /unrecognized verdict/);

// Malformed/unrecognized engine output (neither allow, deny, nor unresolved) fails CLOSED
// too, but through the genuinely-generic path -- distinct from the `unresolved` case above.
const malformed = interpretEngineResult({ nonsense: true });
assert.equal(malformed.permissionDecision, "deny");
assert.match(malformed.message, /unrecognized verdict/);

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

// --- INTEGRATION: the real relay, the real engine, no mocks -----------------------------
//
// Spawns `hooks/guard-eval.mjs` exactly as `hooks.json` would (a child node process reading
// a JSON payload off stdin), which itself shells out to the real `bin/shepherd guard eval`
// (`services/cli/shepherd_cli/`, DF-76) -- proving the invocation path, the argv, and the
// response-JSON shape this whole adapter was written against are all real, not declared.
// The command (`git commit`) and role (`coder`) are chosen to land on a genuine engine-level
// predicate deny (`git-custody`/`implementer-never-writes-git`, halt_code `CODER-GIT-WRITE`)
// rather than the adapter's own `unresolved`-triggered fallback deny -- a fallback would
// also print `{"permissionDecision":"deny"}` but would NOT prove the engine actually
// evaluated a rule, which is the entire point of this test (see this file's own header: an
// absent/broken engine must FAIL this test).
{
  const here = dirname(fileURLToPath(import.meta.url));
  const relay = join(here, "..", "hooks", "guard-eval.mjs");
  const payload = JSON.stringify({
    session_id: "guard-integration-test",
    hook_event_name: "PreToolUse",
    tool_name: "Bash",
    tool_input: { command: "git commit -am 'should be denied'" },
    tool_use_id: "guard-integration-test-1",
    role: "coder",
  });
  const result = spawnSync(process.execPath, [relay], { input: payload, encoding: "utf8" });
  assert.equal(result.status, 0, `guard-eval.mjs exited ${result.status} (stderr: ${result.stderr})`);
  let output;
  try {
    output = JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(`guard-eval.mjs printed non-JSON stdout: ${result.stdout} (${error.message})`);
  }
  assert.equal(output.permissionDecision, "deny", `expected a real engine deny, got: ${JSON.stringify(output)}`);
  assert.match(output.message, /git-custody/);
  assert.match(output.message, /CODER-GIT-WRITE/);

  // And the allow leg of the same live round trip: a read-only git command never denies.
  const allowPayload = JSON.stringify({
    session_id: "guard-integration-test",
    hook_event_name: "PreToolUse",
    tool_name: "Bash",
    tool_input: { command: "git status" },
    tool_use_id: "guard-integration-test-2",
    role: "coder",
  });
  const allowResult = spawnSync(process.execPath, [relay], { input: allowPayload, encoding: "utf8" });
  assert.equal(allowResult.status, 0, `guard-eval.mjs exited ${allowResult.status} (stderr: ${allowResult.stderr})`);
  assert.equal(allowResult.stdout.trim(), "", `expected silence (allow), got: ${allowResult.stdout}`);
}

console.log(
  "ok: interpretEngineResult covers allow/deny/unresolved and both engine-failure modes -- all fail closed except the one true allow -- PLUS a live integration round trip through the real engine (allow and deny)",
);
