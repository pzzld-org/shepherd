#!/usr/bin/env node
// packages/harness-claude/test/guard.test.mjs -- run directly:
//   node packages/harness-claude/test/guard.test.mjs
// plan.md W4-S4/S5/S6 [ACCEPTANCE]: "every guard predicate has an allow AND a deny case, in
// every adapter." `packages/scripts/predicate-coverage.mjs` (the cross-adapter enforcer of
// that line) is out of this step's file scope -- `packages/scripts/` belongs to no single
// adapter -- so this test is this adapter's own proof: `interpretEngineResult` (the one
// piece of decision logic this relay owns) is exercised on an allow verdict, a deny verdict,
// an unresolved verdict, and both classes of engine failure, without needing a live engine
// process -- PLUS the W10 auditor's HIGH finding's own regression suite (below): `hooks/guard-
// eval.mjs`'s prior version forwarded `{...JSON.parse(raw), harness:"claude"}` with no `role`
// key, ever, which -- wired live -- would have denied every Write/Edit/Bash/Agent/Workflow
// call from every role, including root's own git operations, project-wide.
//
// No test here hand-authors a dispatch record or injects a `role` field directly into
// guard-eval.mjs's own stdin -- that is precisely the shape `hooks/tests/
// test_coder_git_guard.sh`'s own header calls out as "proving the fixture, not the mechanism"
// (DF-19), the same lesson DF-77's own rebuild applied to that suite. Every role signal below
// goes through the REAL `hooks/scripts/agent_invocation_tagger.sh` writing a REAL dispatch
// record, read back by the REAL `hooks/scripts/_lib.sh` `current_role()` -- `src/dispatch-
// record.mjs` shells out to exactly that, never a second copy -- through the REAL `hooks/
// guard-eval.mjs` relay and the REAL, live `services/cli/shepherd_cli/` engine, end to end,
// each inside its own throwaway git repo (never the live shepherd monorepo's own dispatch
// state, which this very sprint is actively writing to).

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildGuardDecision,
  buildGuardHooksEntry,
  engineUnavailableVerdict,
  GUARD_MATCHER,
  interpretEngineResult,
  missingRecordDeniedVerdict,
  roleResolutionUnavailableVerdict,
} from "../src/guard.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const RELAY = join(HERE, "..", "hooks", "guard-eval.mjs");
const TAGGER = join(REPO_ROOT, "hooks", "scripts", "agent_invocation_tagger.sh");

// --- interpretEngineResult / engineUnavailableVerdict: pure coverage --------------------------

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
// failure detail surfaced rather than swallowed. This is requirement 4 of this file's own
// regression matrix ("engine unreachable -> deny, fail closed") -- deliberately unit-level:
// `hooks/guard-eval.mjs` only reaches this branch once role resolution has ALREADY produced a
// real request (see `buildGuardDecision` below), so breaking the real `bin/shepherd` launcher
// live would prove nothing this pure call does not already prove about the exact same code
// path `hooks/guard-eval.mjs` runs when `spawnSync(LAUNCHER, ...)` itself fails.
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

// --- missingRecordDeniedVerdict / roleResolutionUnavailableVerdict: pure coverage -------------

const missingVerdict = missingRecordDeniedVerdict("abc123");
assert.equal(missingVerdict.permissionDecision, "deny");
assert.match(missingVerdict.message, /abc123/);
assert.match(missingVerdict.message, /dispatch record/);

const resolutionFailedVerdict = roleResolutionUnavailableVerdict("bash unavailable");
assert.equal(resolutionFailedVerdict.permissionDecision, "deny");
assert.match(resolutionFailedVerdict.message, /bash unavailable/);

// --- buildGuardDecision: the pure three-way split, stubbed resolver (no subprocess) -----------
// Proves the DECISION shape independent of how role gets resolved -- the live integration
// section below proves the REAL resolver (src/dispatch-record.mjs) actually produces the
// inputs this expects.

assert.deepEqual(
  buildGuardDecision({ tool_use_id: "x", tool_name: "Bash", tool_input: { command: "git commit -m x" } }, () => ({ kind: "no-marker" })),
  { kind: "allow" }
);

assert.deepEqual(
  buildGuardDecision({ tool_use_id: "y", tool_name: "Bash", tool_input: { command: "git commit -m x" } }, () => ({
    kind: "missing-record",
    toolUseId: "y",
  })),
  { kind: "missing-record", toolUseId: "y" }
);

assert.deepEqual(
  buildGuardDecision({ tool_use_id: "z", tool_name: "Bash", tool_input: {} }, () => ({ kind: "resolution-failed", detail: "boom" })),
  { kind: "resolution-failed", detail: "boom" }
);

// `role` is ALWAYS taken from the resolver, never trusted from the raw payload -- a caller
// that stuffed its own `role` in gets overwritten. This is the exact defect the W10 finding
// closes: the relay must never forward an UNRESOLVED (or spoofed) role to the engine.
const stubbedRequest = buildGuardDecision(
  { tool_use_id: "w", tool_name: "Bash", tool_input: { command: "git commit -m x" }, role: "should-be-overwritten" },
  () => ({ kind: "resolved", role: "coder" })
);
assert.equal(stubbedRequest.kind, "request");
assert.deepEqual(stubbedRequest.payload, {
  tool_use_id: "w",
  tool_name: "Bash",
  tool_input: { command: "git commit -m x" },
  role: "coder",
  harness: "claude",
});

// --- INTEGRATION: real dispatch records, real relay, real engine, no mocks --------------------
//
// One throwaway git repo, shared across the three cases below (mirrors `hooks/tests/
// test_coder_git_guard.sh`'s own shared-repo pattern) so case 3 can genuinely observe case 2's
// tagged dispatch record still sitting in the sprint's dispatch dir.

function sh(cmd, args, opts = {}) {
  const result = spawnSync(cmd, args, { encoding: "utf8", ...opts });
  if (result.status !== 0) {
    throw new Error(`${cmd} ${args.join(" ")} exited ${result.status}: ${result.stderr}`);
  }
  return result;
}

function initRepo() {
  const dir = mkdtempSync(join(tmpdir(), "harness-claude-guard-test-"));
  sh("git", ["init", "-q", "."], { cwd: dir });
  sh("git", ["config", "user.email", "t@t"], { cwd: dir });
  sh("git", ["config", "user.name", "t"], { cwd: dir });
  mkdirSync(join(dir, ".claude"), { recursive: true });
  writeFileSync(join(dir, ".claude", "shepherd.toml"), "");
  sh("git", ["add", ".claude/shepherd.toml"], { cwd: dir });
  sh("git", ["-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"], { cwd: dir });
  return dir;
}

// Runs the REAL agent_invocation_tagger.sh with a REALISTIC, dispatch-law-compliant
// PreToolUse(Agent) payload -- `tool_input.subagent_type` is the only role signal it reads,
// per DF-77 FIX 1 -- so the dispatch record consumed below is genuinely produced by the fix
// under test, never hand-authored.
function tagDispatch(dir, toolUseId, subagentType) {
  const payload = JSON.stringify({
    session_id: "s",
    tool_name: "Agent",
    tool_use_id: toolUseId,
    tool_input: { subagent_type: subagentType, model: "claude-sonnet-5", prompt: "do the work" },
  });
  sh("bash", [TAGGER], { cwd: dir, input: payload });
}

// Spawns the REAL hooks/guard-eval.mjs exactly as hooks.json would (a child node process
// reading JSON off stdin), `cwd`-scoped to the throwaway repo so role resolution (and the
// live engine invocation it may trigger) never touches this actual monorepo's own live
// dispatch state -- this very sprint is concurrently writing real dispatch records for real
// sibling coders, which would otherwise make this test's outcome depend on wave timing.
// `CLAUDE_PLUGIN_ROOT` is set to the REAL repo root so the engine (`bin/shepherd guard eval`,
// spawned by the relay with `cwd` still the throwaway repo) resolves the real `content/
// predicates/*.toml` corpus instead of walking up from the throwaway repo and finding none --
// exactly the env var a live Claude Code plugin install always sets (`buildGuardHooksEntry()`
// itself wires the relay in via `${CLAUDE_PLUGIN_ROOT}`), not a test-only shortcut.
function runRelay(dir, toolUseId, command) {
  const payload = JSON.stringify({
    session_id: "s",
    hook_event_name: "PreToolUse",
    tool_name: "Bash",
    tool_input: { command },
    tool_use_id: toolUseId,
  });
  const result = spawnSync(process.execPath, [RELAY], {
    cwd: dir,
    input: payload,
    encoding: "utf8",
    env: { ...process.env, CLAUDE_PLUGIN_ROOT: REPO_ROOT },
  });
  assert.equal(result.status, 0, `guard-eval.mjs exited ${result.status} (stderr: ${result.stderr})`);
  return result.stdout;
}

const repo = initRepo();
let rootStdout;
let coderStdout;
let untraceableStdout;

try {
  // 1. ROOT'S OWN GIT OPERATION -- no dispatch record anywhere in this sprint at all yet. This
  //    is the ONE case that would have taken the project down under the pre-fix relay (every
  //    role-less request hit the engine's missing-role `unresolved` path and got denied,
  //    unconditionally) -- assert it FIRST.
  rootStdout = runRelay(repo, "root-git-1", "git commit -am 'root working directly'");
  assert.equal(rootStdout.trim(), "", `root's own git write must NOT be denied, got: ${rootStdout}`);

  // 2. a tagged coder's `git commit` IS denied, through the real relay against the live
  //    `bin/shepherd guard eval` engine -- role comes from a REAL dispatch record, the verdict
  //    from a REAL engine subprocess; a stubbed engine could not prove either fires at all.
  tagDispatch(repo, "coder1", "shepherd:coder");
  coderStdout = runRelay(repo, "coder1", "git commit -am 'should be denied'");
  let coderVerdict;
  try {
    coderVerdict = JSON.parse(coderStdout);
  } catch (error) {
    throw new Error(`guard-eval.mjs printed non-JSON stdout: ${coderStdout} (${error.message})`);
  }
  assert.equal(coderVerdict.permissionDecision, "deny", `expected a real engine deny, got: ${coderStdout}`);
  assert.match(coderVerdict.message, /git-custody/);
  assert.match(coderVerdict.message, /CODER-GIT-WRITE/);

  // 3. a dispatched call with a marker but no record is denied loudly (the DF-75 shape): the
  //    sprint's dispatch dir now holds coder1's tagged record from case 2 (a marker genuinely
  //    exists), but THIS call's own tool_use_id was never tagged -- current_role() cannot
  //    correlate it (the acknowledged DF-77 FIX 3 gap). Unlike case 1, there IS dispatch
  //    activity in this sprint, so the ambiguity resolves to DENY, loudly, through
  //    `missingRecordDeniedVerdict`, never a silent allow and never the engine (no engine
  //    subprocess is spawned for this case at all -- the deny is entirely local).
  untraceableStdout = runRelay(repo, "never-tagged-1", "git commit -am 'untraceable'");
  let untraceableVerdict;
  try {
    untraceableVerdict = JSON.parse(untraceableStdout);
  } catch (error) {
    throw new Error(`guard-eval.mjs printed non-JSON stdout: ${untraceableStdout} (${error.message})`);
  }
  assert.equal(untraceableVerdict.permissionDecision, "deny");
  assert.match(untraceableVerdict.message, /never-tagged-1/);
  assert.match(untraceableVerdict.message, /dispatch record/);

  // 4. REGRESSION: a genuinely-tagged `conductor` dispatch (a real dispatch record whose
  //    `agent_role` happens to be the literal string `"conductor"`) must still reach the
  //    engine, never fall into the `no-marker` allow bucket. `current_role()` prints that same
  //    literal string for TWO different situations -- an empty `tool_use_id` (root, no tool
  //    call in flight) AND a real, correctly-tagged conductor dispatch -- `resolveRole` tells
  //    them apart by checking `toolUseId` itself, not the resolved string (see its own doc
  //    comment). Proven with `git rebase` specifically (not `git commit`) because it is the
  //    ONE command whose outcome actually DIFFERS between the two behaviors: a bare `vcs.write`
  //    bypasses `git-custody.toml`'s branch-scope rule with no context to fire it either way
  //    (case 1 and this case would look identical), but `vcs.integrate` (rebase/merge/
  //    cherry-pick/worktree) is `deny_unless_root` -- a lane-lead is NOT root, so the real
  //    engine denies it. `no-marker` would have silently allowed it instead.
  tagDispatch(repo, "conductor1", "shepherd:conductor");
  const conductorStdout = runRelay(repo, "conductor1", "git rebase main");
  let conductorVerdict;
  try {
    conductorVerdict = JSON.parse(conductorStdout);
  } catch (error) {
    throw new Error(`guard-eval.mjs printed non-JSON stdout: ${conductorStdout} (${error.message})`);
  }
  assert.equal(
    conductorVerdict.permissionDecision,
    "deny",
    `a real conductor dispatch's rebase must reach the engine and be denied (cross-lane-integration-is-root-exclusive), got: ${conductorStdout}`
  );
  assert.match(conductorVerdict.message, /git-custody/);
} finally {
  rmSync(repo, { recursive: true, force: true });
}

console.log(`VERDICT root-allow (case 1) stdout: ${JSON.stringify(rootStdout.trim())}`);
console.log(`VERDICT coder-deny (case 2) stdout: ${coderStdout.trim()}`);
console.log(`VERDICT untraceable-deny (case 3) stdout: ${untraceableStdout.trim()}`);

console.log(
  "ok: interpretEngineResult/engineUnavailableVerdict/missingRecordDeniedVerdict/roleResolutionUnavailableVerdict cover " +
    "allow, deny, unresolved, and every failure mode; buildGuardDecision's three-way split is proven both against a " +
    "stubbed resolver AND, end to end through the real hooks/guard-eval.mjs relay, against real dispatch records and " +
    "the real live engine -- root's own untraceable git write is NOT denied, a tagged coder's IS (real engine, " +
    "CODER-GIT-WRITE), and an untraceable call inside an otherwise-active sprint is denied loudly without ever " +
    "reaching the engine"
);
