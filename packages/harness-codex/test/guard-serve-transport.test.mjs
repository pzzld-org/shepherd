#!/usr/bin/env node
// packages/harness-codex/test/guard-serve-transport.test.mjs -- run directly:
//   node packages/harness-codex/test/guard-serve-transport.test.mjs
// T2-serve-wiring. The low-level transport properties (kill mid-session -> fail closed, stale
// socket recovery, idle self-termination, an engine that never starts, cold-vs-warm latency) are
// already proven thoroughly against `packages/harness-claude/src/guard-serve-{engine,broker,
// client}.mjs` directly in `packages/harness-claude/test/guard-serve-transport.test.mjs` -- that
// module is SHARED, not owned separately by each package (see its own header), so re-deriving
// those same five properties from scratch here would be exactly the test-code duplication this
// sprint has been removing, not new coverage.
//
// What THIS file proves instead, end to end through Codex's own REAL, unstubbed
// `hooks/scripts/shepherd_guard.mjs` (never a stub of `buildGuardDecision`/`interpretEngineResult`
// -- this package's existing `test/guard.test.mjs` already covers those in isolation): Codex's
// specific wiring reaches the exact same fail-closed guarantee the shared transport provides --
// a real dispatched coder's `git commit` denies through a REAL live engine (case A), a second
// real hook invocation reuses the SAME warm broker (case B), and killing that broker's engine
// between two real hook invocations still denies, not hangs, not allows (case C) -- plus the
// real, unstubbed latency a genuine PreToolUse hook process pays, including Node's own
// subprocess-spawn overhead for the hook script itself (not just the transport call
// harness-claude's benchmark isolates).
//
// Deliberately does NOT pre-arm its own broker via `startGuardBroker` at `defaultSocketPath()`:
// that path is the shared production one (`packages/harness-claude/src/guard-serve-broker.mjs`'s
// `defaultSocketPath()` header -- Claude and Codex share ONE broker per `content/` root by
// design), so a broker may ALREADY be live there from a prior test run or a real session, and
// trying to "win the bind race" would make this file's pass/fail depend on run order -- observed
// live: an earlier version of this file asserted it always won that race and failed the moment
// `packages/harness-claude/test/guard.test.mjs` had already warmed the shared path first. Instead
// case A's own real relay call is what establishes (or reuses) the broker, exactly like a real
// session would, and the engine pid needed for case C is discovered PRECISELY afterward via
// `lsof -t <socketPath>` (the exact process bound to that exact socket file) then `pgrep -P
// <thatPid>` (its direct child, the actual `guard serve` engine) -- two narrow, targeted lookups,
// never a broad `pgrep -f "guard serve"` process-table pattern match (see
// `packages/harness-claude/test/guard-serve-transport.test.mjs`'s own header for why that would
// risk killing a completely different, concurrently-running test's engine).

import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { defaultSocketPath } from "../../harness-claude/src/guard-serve-broker.mjs";
import { writeDispatchRecord } from "../src/dispatch-record.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const CONTENT_DIR = join(REPO_ROOT, "content");
const RELAY = join(HERE, "..", "hooks", "scripts", "shepherd_guard.mjs");

function runRelay(dataDir, agentId, command) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({
      hook_event_name: "PreToolUse",
      tool_name: "Bash",
      tool_input: { command },
      agent_id: agentId,
    });
    const t0 = process.hrtime.bigint();
    const child = spawn(process.execPath, [RELAY], { env: { ...process.env, SHEPHERD_WORKDIR: dataDir } });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.once("error", reject);
    child.once("close", (code) => {
      const elapsedMs = Number(process.hrtime.bigint() - t0) / 1e6;
      if (code !== 0) {
        reject(new Error(`shepherd_guard.mjs exited ${code} (stderr: ${stderr})`));
        return;
      }
      resolve({ stdout, elapsedMs });
    });
    child.stdin.end(payload);
  });
}

/** The exact pid bound to `socketPath` -- `null` if nothing is listening there. */
function brokerPidOn(socketPath) {
  const result = spawnSync("lsof", ["-t", socketPath], { encoding: "utf8" });
  const pid = result.stdout.trim().split("\n")[0];
  return pid ? Number(pid) : null;
}

/** The engine's pid -- the ONE direct child of the broker process found above. */
function enginePidChildOf(brokerPid) {
  const result = spawnSync("pgrep", ["-P", String(brokerPid)], { encoding: "utf8" });
  const pid = result.stdout.trim().split("\n")[0];
  return pid ? Number(pid) : null;
}

const dataDir = mkdtempSync(join(tmpdir(), "hcx-transport-"));
writeDispatchRecord(dataDir, "agent-coder-1", "coder");
const socketPath = defaultSocketPath(CONTENT_DIR);

try {
  // -- A. a real dispatched coder's `git commit`, end to end: real dispatch record, real relay
  // subprocess, a real engine (spawned fresh here, or reused if the shared path was already
  // warm -- either is correct). Verbatim stdout captured for the CODER REPORT. -------------------
  const first = await runRelay(dataDir, "agent-coder-1", "git commit -m 'should be denied'");
  const firstVerdict = JSON.parse(first.stdout);
  assert.equal(firstVerdict.hookSpecificOutput.hookEventName, "PreToolUse");
  assert.equal(firstVerdict.hookSpecificOutput.permissionDecision, "deny");
  assert.match(firstVerdict.hookSpecificOutput.permissionDecisionReason, /CODER-GIT-WRITE/);
  console.log(`VERDICT codex real-relay coder-deny (case A) stdout: ${first.stdout.trim()}`);

  // -- B. a second real hook invocation reuses the SAME warm broker -- allow this time (`git
  // status` carries no git-custody write verb). ----------------------------------------------
  const second = await runRelay(dataDir, "agent-coder-1", "git status");
  assert.equal(second.stdout.trim(), "", `an allow must print nothing, got: ${second.stdout}`);

  console.log(
    `LATENCY real hook process (Node spawn + transport), first call (establishes or reuses the shared broker): ` +
      `${first.elapsedMs.toFixed(2)}ms | second call (warm broker reused): ${second.elapsedMs.toFixed(2)}ms`
  );

  // -- C. kill the engine precisely (never a process-table pattern match -- see module header),
  // then a THIRD real hook invocation must deny, not hang, not allow. ---------------------------
  const brokerPid = brokerPidOn(socketPath);
  assert.ok(brokerPid, `expected a broker listening on ${socketPath} after case A/B`);
  const enginePid = enginePidChildOf(brokerPid);
  assert.ok(enginePid, `expected broker pid ${brokerPid} to have exactly one guard-serve child`);
  process.kill(enginePid, "SIGKILL");
  await new Promise((resolve) => setTimeout(resolve, 250)); // let the child's `exit` event land

  const t0 = Date.now();
  const third = await runRelay(dataDir, "agent-coder-1", "git status");
  const killedElapsedMs = Date.now() - t0;
  const thirdVerdict = JSON.parse(third.stdout);
  assert.equal(thirdVerdict.hookSpecificOutput.permissionDecision, "deny", `an engine killed mid-session must deny the next real hook call, got: ${third.stdout}`);
  assert.match(thirdVerdict.hookSpecificOutput.permissionDecisionReason, /guard engine unavailable, failing closed/);
  assert.ok(killedElapsedMs < 5000, `must not hang -- resolved in ${killedElapsedMs}ms`);
  console.log(`VERDICT codex real-relay engine-killed-mid-session (case C) stdout: ${third.stdout.trim()} (${killedElapsedMs}ms, not a hang)`);
} finally {
  rmSync(dataDir, { recursive: true, force: true });
}

console.log(
  "ok: Codex's real hooks/scripts/shepherd_guard.mjs relay denies a real CODER-GIT-WRITE end to end through the shared " +
    "broker/client transport (established or reused, then warm-reused), and still denies -- not hangs, not allows -- " +
    "after the engine is killed mid-session, through the real nested hookSpecificOutput wire shape"
);
