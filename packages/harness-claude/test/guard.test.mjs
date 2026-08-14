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
//
// DISPATCH-DIR POPULATION, DELIBERATE (the regression this file now gates): every prior
// version of this file's integration section ran its FIRST, root-proving case
// (`initRepo()`, fresh, zero dispatch records) against an EMPTY dispatch directory --
// `hasMarker` false, `no-marker` allow. Every REAL sprint, from its first dispatch onward, has
// a NON-EMPTY dispatch directory (this repo's own `.shepherd/dispatch/v6.4.5/` holds 64
// records as of this fix) -- `hasMarker` true, `missing-record`, a DIFFERENT code path the
// empty-sandbox case never exercised. That gap is exactly how the relay measured 100% deny on
// a live repo while this file stayed green: the test manufactured the precondition (empty
// dispatch dir) the runtime never supplies. Below, every case that exercises role resolution
// runs against a dispatch directory SEEDED with several unrelated dispatch records FIRST
// (`seedUnrelatedDispatchActivity`) -- the real state of a real sprint -- and the one
// remaining empty-directory case is kept, but demoted to an explicitly labeled EDGE CASE that
// proves nothing about root's safety on its own.

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
  missingRecordWarnedVerdict,
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

// --- missingRecordWarnedVerdict / roleResolutionUnavailableVerdict: pure coverage -------------
// WARN, not deny (see src/guard.mjs's "MISSING-RECORD POSTURE, CORRECTED"): no
// `permissionDecision` key at all, so the call is not blocked -- only `additionalContext`,
// matching hooks/scripts/_lib.sh's `emit_context` shape.

const missingVerdict = missingRecordWarnedVerdict("abc123");
assert.equal(missingVerdict.permissionDecision, undefined);
assert.match(missingVerdict.additionalContext, /abc123/);
assert.match(missingVerdict.additionalContext, /NOT denied/);
assert.match(missingVerdict.additionalContext, /coder_git_guard\.sh/);

const resolutionFailedVerdict = roleResolutionUnavailableVerdict("bash unavailable");
assert.equal(resolutionFailedVerdict.permissionDecision, "deny");
assert.match(resolutionFailedVerdict.message, /bash unavailable/);

// --- buildGuardDecision: the pure three-way split, stubbed resolver (no subprocess) -----------
// Proves the DECISION shape (which `kind` a given resolution maps to) independent of how role
// actually gets resolved -- a TRANSLATION-shape test, legitimately stubbed: no claim here about
// whether the REAL resolver ever produces "no-marker" over "missing-record" for a given
// sandbox state, only "IF it produces X, buildGuardDecision maps it to Y." That claim -- what
// the real resolver actually returns against a real sandbox -- is exactly what a stub cannot
// prove and exactly what hid the empty-dispatch-dir defect this file's own header names; it is
// proven only by the live integration section below, against the REAL resolver, the REAL
// tagger, and a dispatch directory shaped like a real sprint's.

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
// One throwaway git repo, shared across every case below except the explicitly-labeled
// EMPTY-DIR EDGE CASE at the end (which needs its own, genuinely-never-dispatched repo --
// sharing would defeat the point of that case). `seedUnrelatedDispatchActivity` runs FIRST,
// before any assertion, so every role-resolution case below runs against a NON-EMPTY dispatch
// dir -- the shape of a real sprint, per this file's own header.

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
// per DF-77 FIX 1 -- so every dispatch record below is genuinely produced by the fix under
// test, never hand-authored.
function tagDispatch(dir, toolUseId, subagentType) {
  const payload = JSON.stringify({
    session_id: "s",
    tool_name: "Agent",
    tool_use_id: toolUseId,
    tool_input: { subagent_type: subagentType, model: "claude-sonnet-5", prompt: "do the work" },
  });
  sh("bash", [TAGGER], { cwd: dir, input: payload });
}

// Several REAL, tagged dispatch records for roles unrelated to whatever `tool_use_id` a later
// case under test uses -- the exact shape of a real sprint's dispatch dir by the time a
// coder's first tool call fires: SOME dispatch activity recorded, none of it correlating to a
// call that was never itself tagged (this repo's own `.shepherd/dispatch/v6.4.5/` holds 64
// such records right now).
function seedUnrelatedDispatchActivity(dir) {
  tagDispatch(dir, "seed-auditor-1", "shepherd:auditor");
  tagDispatch(dir, "seed-discovery-1", "shepherd:discovery");
  tagDispatch(dir, "seed-worker-1", "shepherd:worker");
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
// itself wires the relay in via `${CLAUDE_PLUGIN_ROOT}`), not a test-only shortcut. Takes the
// real `PreToolUse` tool name/input pair rather than assuming Bash -- the regression gate below
// proves the fix on a plain read, a plain `Write`, AND a git write.
function runRelay(dir, toolUseId, toolName, toolInput) {
  const payload = JSON.stringify({
    session_id: "s",
    hook_event_name: "PreToolUse",
    tool_name: toolName,
    tool_input: toolInput,
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

function parseVerdict(stdout, label) {
  if (stdout.trim() === "") return {};
  try {
    return JSON.parse(stdout);
  } catch (error) {
    throw new Error(`guard-eval.mjs (${label}) printed non-JSON stdout: ${stdout} (${error.message})`);
  }
}

const repo = initRepo();
let gateStdout;

try {
  seedUnrelatedDispatchActivity(repo);

  // --- PRIMARY REGRESSION GATE ---------------------------------------------------------------
  // A fresh `tool_use_id` matching NONE of the seeded records above, in a sandbox whose
  // dispatch dir is genuinely non-empty (3 unrelated records just written) -- this step's
  // brief's own opening measurement, replayed as a test: `hasMarker` true, `current_role()`
  // resolves `"unknown"`, and the PRIOR relay denied both a plain `git status` and a plain
  // `Write` unconditionally. Neither may be denied now -- this is the regression gate for the
  // entire finding.
  gateStdout = runRelay(repo, "regression-gate-bash", "Bash", { command: "git status" });
  const gateBashVerdict = parseVerdict(gateStdout, "regression-gate-bash");
  assert.equal(gateBashVerdict.permissionDecision, undefined, `plain 'git status' must NOT be denied, got: ${gateStdout}`);
  assert.match(gateBashVerdict.additionalContext ?? "", /NOT denied/);
  assert.match(gateBashVerdict.additionalContext ?? "", /regression-gate-bash/);

  const gateWriteStdout = runRelay(repo, "regression-gate-write", "Write", { file_path: "/tmp/regression-gate-target" });
  const gateWriteVerdict = parseVerdict(gateWriteStdout, "regression-gate-write");
  assert.equal(gateWriteVerdict.permissionDecision, undefined, `plain 'Write' must NOT be denied, got: ${gateWriteStdout}`);
  assert.match(gateWriteVerdict.additionalContext ?? "", /NOT denied/);

  // A fresh, untraceable call attempting an actual git WRITE (not just a read) also only
  // warns, never denies -- the behavior this fix deliberately changed from the PRIOR deny (see
  // src/guard.mjs's "MISSING-RECORD POSTURE, CORRECTED"): the correlation gap (DF-77 FIX 3)
  // means this ambiguity cannot be told apart from root's own git write, so it gets the same
  // posture `hooks/scripts/coder_git_guard.sh` already ships for the identical ambiguity.
  const gateGitWriteStdout = runRelay(repo, "regression-gate-git-write", "Bash", { command: "git commit -am 'untraceable'" });
  const gateGitWriteVerdict = parseVerdict(gateGitWriteStdout, "regression-gate-git-write");
  assert.equal(gateGitWriteVerdict.permissionDecision, undefined, `an untraceable git WRITE must NOT be denied (warn only), got: ${gateGitWriteStdout}`);
  assert.match(gateGitWriteVerdict.additionalContext ?? "", /coder_git_guard\.sh/);

  // --- a genuinely-tagged coder's git write IS still denied -------------------------------
  // Role resolution succeeds (a REAL dispatch record correlates), so the real engine is
  // consulted and denies it -- proves the fix did NOT weaken enforcement for the case DF-75
  // actually resolves; only the genuinely-unresolvable case above changed.
  tagDispatch(repo, "coder1", "shepherd:coder");
  const coderStdout = runRelay(repo, "coder1", "Bash", { command: "git commit -am 'should be denied'" });
  const coderVerdict = parseVerdict(coderStdout, "coder1");
  assert.equal(coderVerdict.permissionDecision, "deny", `expected a real engine deny, got: ${coderStdout}`);
  assert.match(coderVerdict.message, /git-custody/);
  assert.match(coderVerdict.message, /CODER-GIT-WRITE/);

  // --- REGRESSION: a resolved, non-"unknown" role still reaches the engine ----------------
  // A genuinely-tagged `conductor` dispatch (a real dispatch record whose `agent_role` happens
  // to be the literal string `"conductor"`) must still reach the engine, never fall into the
  // `no-marker`/`missing-record` allow-with-warn bucket. `current_role()` prints that same
  // literal string for TWO different situations -- an empty `tool_use_id` (root, no tool call
  // in flight) AND a real, correctly-tagged conductor dispatch -- `resolveRole` tells them
  // apart by checking `toolUseId` itself, not the resolved string (see its own doc comment).
  // Proven with `git rebase` specifically (not `git commit`) because it is the ONE command
  // whose outcome actually DIFFERS between the two behaviors: a bare `vcs.write` bypasses
  // `git-custody.toml`'s branch-scope rule with no context to fire it either way, but
  // `vcs.integrate` (rebase/merge/cherry-pick/worktree) is `deny_unless_root` -- a lane-lead is
  // NOT root, so the real engine denies it. Either allow-with-warn bucket would have let it
  // through instead.
  tagDispatch(repo, "conductor1", "shepherd:conductor");
  const conductorStdout = runRelay(repo, "conductor1", "Bash", { command: "git rebase main" });
  const conductorVerdict = parseVerdict(conductorStdout, "conductor1");
  assert.equal(
    conductorVerdict.permissionDecision,
    "deny",
    `a real conductor dispatch's rebase must reach the engine and be denied (cross-lane-integration-is-root-exclusive), got: ${conductorStdout}`
  );
  assert.match(conductorVerdict.message, /git-custody/);
} finally {
  rmSync(repo, { recursive: true, force: true });
}

// --- EDGE CASE, explicitly labeled: a genuinely EMPTY dispatch dir --------------------------
// Kept because the `no-marker` branch of the three-way split is real and worth covering, but
// this is NOT the proof that root is safe in a real sprint -- see this file's own header for
// why an empty-dispatch-dir sandbox is the wrong precondition to establish that. A fresh repo
// with ZERO dispatch records ever written allows SILENTLY (no warning at all -- unlike every
// populated-dir case above, which warns loudly).
const emptyDirRepo = initRepo();
try {
  const emptyDirStdout = runRelay(emptyDirRepo, "edge-case-empty-dir", "Bash", { command: "git status" });
  assert.equal(
    emptyDirStdout.trim(),
    "",
    `an empty dispatch dir must allow silently (edge case only, not this fix's proof), got: ${emptyDirStdout}`
  );
} finally {
  rmSync(emptyDirRepo, { recursive: true, force: true });
}

console.log(`VERDICT regression-gate (git status, populated dispatch dir) stdout: ${gateStdout.trim()}`);

console.log(
  "ok: interpretEngineResult/engineUnavailableVerdict/missingRecordWarnedVerdict/roleResolutionUnavailableVerdict cover " +
    "allow, deny, unresolved, and every failure mode; buildGuardDecision's three-way split is proven both against a " +
    "stubbed resolver AND, end to end through the real hooks/guard-eval.mjs relay against a POPULATED dispatch dir " +
    "shaped like a real sprint -- a fresh, untraceable tool_use_id's plain 'git status', plain 'Write', and even a " +
    "git WRITE all warn and let the call through (never deny), a genuinely-tagged coder's git write IS still denied " +
    "by the real engine, and a genuinely-tagged conductor's rebase still reaches the engine rather than falling " +
    "into the allow-with-warn bucket; the empty-dispatch-dir case is kept only as an explicitly labeled edge case"
);
