#!/usr/bin/env node
// packages/harness-claude/test/guard-serve-transport.test.mjs -- run directly:
//   node packages/harness-claude/test/guard-serve-transport.test.mjs
// T2-serve-wiring: the properties `src/guard-serve-engine.mjs` / `src/guard-serve-broker.mjs` /
// `src/guard-serve-client.mjs` must hold that a per-call `spawnSync` never had to account for,
// PLUS the perf claim this whole step exists to cash in:
//
//   1. fail CLOSED when the live engine dies mid-session -- the NEXT request denies, does not
//      hang, and does not silently allow (kills the real `guard serve` child between two
//      requests through the SAME broker).
//   2. a broker killed outright (not just its engine) leaves a stale socket file a later spawn
//      attempt must recover from, never get stuck on.
//   3. no orphan processes -- an idle broker closes itself (and unlinks its socket) without
//      anything external telling it to.
//   4. an engine that can never start (bad `bin/shepherd`) fails closed within a bounded time,
//      never a hang -- the exact failure mode a per-call spawn could not have (this step's own
//      module-header warning).
//   5. measured latency, cold (first request, pays the broker+engine spawn) vs warm (every
//      request after) -- printed as real numbers, not asserted against a brittle threshold
//      (perf numbers are environment-dependent; the CODER REPORT cites the printed figures).

import assert from "node:assert/strict";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { startGuardBroker } from "../src/guard-serve-broker.mjs";
import { requestGuardVerdict } from "../src/guard-serve-client.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const CONTENT_DIR = join(REPO_ROOT, "content");
const SHEPHERD_BIN = join(REPO_ROOT, "bin", "shepherd");

// Every sub-test below kills its OWN broker/engine by the PRECISE pid `startGuardBroker`/
// `requestGuardVerdict({idleTimeoutMs})` hand back -- never a process-table search
// (`pgrep -f "guard serve"`). `node --test` runs sibling test FILES concurrently, and this
// package's own `content/` root is shared by every one of them (by design -- see `src/
// guard-serve-broker.mjs`'s `defaultSocketPath()` header); a broad kill-by-pattern here would
// have a real chance of SIGKILLing a completely different, concurrently-running test's live
// engine instead of this test's own -- exactly the cross-test contamination this file exists to
// prove the transport does NOT produce for two genuinely different callers.

// -- 1. engine dies mid-session -> next request through the SAME still-live broker denies,
// does not hang, is not silently allowed -----------------------------------------------------
{
  const dir = mkdtempSync(join(tmpdir(), "hc-transport-kill-"));
  const socketPath = join(dir, "g.sock");
  const broker = await startGuardBroker({ shepherdBin: SHEPHERD_BIN, contentDir: CONTENT_DIR, socketPath, idleTimeoutMs: 60_000 });
  assert.ok(broker, "expected to win the bind race on a fresh socket");

  const payload = { harness: "claude", role: "coder", tool_name: "Bash", tool_input: { command: "git status" } };
  const before = await requestGuardVerdict({ shepherdBin: SHEPHERD_BIN, contentDir: CONTENT_DIR, payload, socketPath });
  assert.equal(before.ok, true, `pre-kill request must succeed against a live engine: ${before.detail}`);
  assert.equal(before.engineResult.decision, "allow");

  process.kill(broker.enginePid, "SIGKILL");
  await new Promise((resolve) => setTimeout(resolve, 250)); // let the child's `exit` event land

  const t0 = Date.now();
  const after = await requestGuardVerdict({ shepherdBin: SHEPHERD_BIN, contentDir: CONTENT_DIR, payload, socketPath });
  const elapsedMs = Date.now() - t0;
  assert.equal(after.ok, false, "a request after the engine died must fail closed, never a real verdict");
  // The raw transport `detail` here is deliberately NOT pre-wrapped with "guard engine
  // unavailable, failing closed: ..." -- that prefix belongs to the CALLER
  // (`engineUnavailableVerdict` in `src/guard.mjs`, exercised end to end by
  // `test/guard.test.mjs` and `packages/harness-codex/test/guard-serve-transport.test.mjs`'s own
  // real-relay case C); wrapping it here too would double it up in the final hook message.
  assert.match(after.detail, /guard serve exited/);
  assert.ok(elapsedMs < 2000, `must not hang -- resolved in ${elapsedMs}ms`);

  // The broker tears itself down promptly on engine death (module header, trigger 2) rather than
  // keep denying for the rest of the idle window -- confirm it actually did, not just that this
  // one request happened to deny.
  await broker.onClosed.then(() => {});
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(existsSync(socketPath), false, "the broker must unlink its own socket on teardown -- no orphaned socket file");

  rmSync(dir, { recursive: true, force: true });
  console.log(`ok: engine killed mid-session -> next request denies in ${elapsedMs}ms (not a hang, not an allow), broker self-tore-down`);
}

// -- 2. a broker process killed outright leaves a stale socket file; the NEXT spawn attempt
// recovers instead of getting stuck ------------------------------------------------------------
{
  const dir = mkdtempSync(join(tmpdir(), "hc-transport-stale-"));
  const socketPath = join(dir, "g.sock");
  // Simulate the file a killed-outright broker leaves behind: a Unix socket file with nothing
  // listening on it (never cleanly unlinked, unlike this test's own `broker.close()` elsewhere).
  writeFileSync(socketPath, "");

  const t0 = Date.now();
  const result = await requestGuardVerdict({
    shepherdBin: SHEPHERD_BIN,
    contentDir: CONTENT_DIR,
    payload: { harness: "claude", role: "coder", tool_name: "Bash", tool_input: { command: "git status" } },
    socketPath,
    idleTimeoutMs: 500, // self-cleans up shortly after this test, never lingers
  });
  const elapsedMs = Date.now() - t0;
  assert.equal(result.ok, true, `must recover from a stale socket file, not get stuck denying forever: ${result.detail}`);
  assert.equal(result.engineResult.decision, "allow");
  assert.ok(elapsedMs < 5000, `stale-socket recovery must stay well under a PreToolUse hook timeout budget -- took ${elapsedMs}ms`);

  await new Promise((resolve) => setTimeout(resolve, 700)); // let the spawned broker's own idle timeout close it before this dir is removed
  rmSync(dir, { recursive: true, force: true });
  console.log(`ok: stale socket file recovered from in ${elapsedMs}ms, never stuck`);
}

// -- 3. no orphan processes: an idle broker closes itself and unlinks its own socket -----------
{
  const dir = mkdtempSync(join(tmpdir(), "hc-transport-idle-"));
  const socketPath = join(dir, "g.sock");
  const broker = await startGuardBroker({ shepherdBin: SHEPHERD_BIN, contentDir: CONTENT_DIR, socketPath, idleTimeoutMs: 250 });
  assert.ok(broker);
  const t0 = Date.now();
  await broker.onClosed;
  const elapsedMs = Date.now() - t0;
  assert.ok(elapsedMs >= 250 && elapsedMs < 2000, `idle shutdown should fire close to the configured timeout, got ${elapsedMs}ms`);
  assert.equal(existsSync(socketPath), false, "idle shutdown must unlink its own socket file");
  rmSync(dir, { recursive: true, force: true });
  console.log(`ok: an idle broker (250ms timeout) self-terminated after ${elapsedMs}ms and unlinked its socket -- no orphan process`);
}

// -- 4. an engine that can never start fails closed within a bounded time, never a hang --------
{
  const fixtureRoot = mkdtempSync(join(tmpdir(), "hc-transport-nospawn-"));
  const fakeShepherdBin = join(fixtureRoot, "bin-shepherd");
  writeFileSync(fakeShepherdBin, '#!/usr/bin/env bash\necho "simulated: engine unavailable" >&2\nexit 1\n', { mode: 0o755 });
  const socketPath = join(fixtureRoot, "g.sock");

  const t0 = Date.now();
  const result = await requestGuardVerdict({
    shepherdBin: fakeShepherdBin,
    contentDir: CONTENT_DIR,
    payload: { harness: "claude", role: "coder", tool_name: "Bash", tool_input: { command: "git status" } },
    socketPath,
    spawnWaitMs: 1000,
  });
  const elapsedMs = Date.now() - t0;
  assert.equal(result.ok, false, "an engine that can never start must fail closed, never a silent allow");
  assert.match(result.detail, /guard broker did not become ready/);
  assert.ok(elapsedMs < 3000, `must not hang past its own spawnWaitMs budget -- took ${elapsedMs}ms`);
  assert.equal(existsSync(socketPath), false, "a broker whose engine never started must never bind the socket");

  rmSync(fixtureRoot, { recursive: true, force: true });
  console.log(`ok: an engine that never starts fails closed in ${elapsedMs}ms (bounded by spawnWaitMs), never a hang`);
}

// -- 5. latency: cold (first request, pays the broker+engine spawn) vs warm (every request
// after) -- printed, not threshold-asserted (see module header) -------------------------------
{
  const dir = mkdtempSync(join(tmpdir(), "hc-transport-latency-"));
  const socketPath = join(dir, "g.sock");
  const payload = { harness: "claude", role: "coder", tool_name: "Bash", tool_input: { command: "git status" } };

  const coldStart = process.hrtime.bigint();
  const cold = await requestGuardVerdict({ shepherdBin: SHEPHERD_BIN, contentDir: CONTENT_DIR, payload, socketPath, idleTimeoutMs: 2000 });
  const coldMs = Number(process.hrtime.bigint() - coldStart) / 1e6;
  assert.equal(cold.ok, true, `cold request must succeed: ${cold.detail}`);

  const warmTimes = [];
  for (let i = 0; i < 20; i += 1) {
    const t0 = process.hrtime.bigint();
    const warm = await requestGuardVerdict({ shepherdBin: SHEPHERD_BIN, contentDir: CONTENT_DIR, payload, socketPath });
    warmTimes.push(Number(process.hrtime.bigint() - t0) / 1e6);
    assert.equal(warm.ok, true, `warm request ${i} must succeed: ${warm.detail}`);
  }
  const warmAvg = warmTimes.reduce((a, b) => a + b, 0) / warmTimes.length;
  const warmMin = Math.min(...warmTimes);
  const warmMax = Math.max(...warmTimes);

  assert.ok(warmAvg < coldMs, "a warm request must be faster than the cold (spawn-paying) request");

  await new Promise((resolve) => setTimeout(resolve, 2200)); // let this broker's own 2s idle timeout close it before this dir is removed
  rmSync(dir, { recursive: true, force: true });

  console.log(
    `LATENCY cold (first call, spawns broker+engine): ${coldMs.toFixed(2)}ms | ` +
      `warm (next 20 calls via the persistent broker): avg=${warmAvg.toFixed(3)}ms min=${warmMin.toFixed(3)}ms max=${warmMax.toFixed(3)}ms`
  );
}

console.log("ok: guard-serve transport fails closed on engine death and on an engine that never starts, recovers from a stale socket, self-terminates when idle, and is measurably faster warm than cold");
