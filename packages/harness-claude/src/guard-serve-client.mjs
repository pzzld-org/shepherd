// packages/harness-claude/src/guard-serve-client.mjs -- what a per-invocation hook script calls
// instead of `spawnSync(LAUNCHER, ["guard", "eval"], ...)` (T2-serve-wiring). SHARED between
// packages/harness-claude's `hooks/guard-eval.mjs` and packages/harness-codex's
// `hooks/scripts/shepherd_guard.mjs` -- see guard-serve-engine.mjs's header for why this lives
// here and is cross-imported rather than copied, and guard-serve-broker.mjs's header for why the
// persistent engine lives in a detached broker process rather than in this hook process itself.
//
// Contract: `requestGuardVerdict()` always resolves (never rejects, never hangs past its own
// bounded timeouts) to the SAME envelope `GuardServeEngine.evaluate()` produces --
// `{ok: true, engineResult}` or `{ok: false, detail}` -- regardless of whether the failure
// happened in the engine, the broker, or this connection. A caller's existing branch
// (`if (!result.ok) engineUnavailableVerdict(result.detail); else interpretEngineResult(result.engineResult)`)
// is therefore identical to the branch it already ran against `spawnSync`'s `{error, status}` /
// `JSON.parse(stdout)` shape -- only the transport underneath changed.

import { spawn } from "node:child_process";
import net from "node:net";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

/** Default path to the broker's executable entrypoint -- a peer of `hooks/guard-eval.mjs`. */
export const DEFAULT_BROKER_MAIN = join(HERE, "..", "hooks", "guard-broker-main.mjs");

const DEFAULT_CONNECT_TIMEOUT_MS = 1500;
const DEFAULT_SPAWN_WAIT_MS = 3000;
const SPAWN_POLL_INTERVAL_MS = 15;

/**
 * Connect-time error codes meaning "nothing usable is listening at this path" -- worth spawning
 * a fresh broker over. `ECONNREFUSED`/`ENOENT` are the two a broker's own clean absence or a
 * stale-but-properly-typed leftover socket produce; `ENOTSOCK` covers the (rarer, but observed in
 * this step's own tests) case of something other than a socket occupying the path -- a stale
 * broker's OWN `bindSocket()` recovery (`guard-serve-broker.mjs`) already unlinks unconditionally
 * on any failed probe-connect, regardless of code, so spawning here and letting THAT recovery run
 * is strictly safer than trying to special-case every possible filesystem state client-side. A
 * TIMEOUT or a malformed-response failure carries no `.code` at all and is deliberately excluded:
 * something DID answer (or a connection WAS established) in that case, and spawning a second,
 * competing broker would not fix either.
 */
const NO_LIVE_BROKER_CODES = new Set(["ECONNREFUSED", "ENOENT", "ENOTSOCK"]);

/**
 * One request/response round trip against an already-listening broker socket. Never rejects --
 * every failure (connect refused, timeout, malformed response, connection dropped before a full
 * line arrived) resolves to `{ok: false, detail}`.
 * @param {string} socketPath
 * @param {Record<string, unknown>} payload
 * @param {number} timeoutMs
 * @returns {Promise<{ok: true, engineResult: Record<string, unknown>} | {ok: false, detail: string, code?: string}>}
 */
function connectAndRequest(socketPath, payload, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      resolve(result);
    };
    const timer = setTimeout(() => finish({ ok: false, detail: `guard broker request timed out after ${timeoutMs}ms` }), timeoutMs).unref();

    const socket = net.createConnection(socketPath);
    let buffered = "";
    socket.once("connect", () => socket.write(`${JSON.stringify(payload)}\n`));
    socket.on("data", (chunk) => {
      buffered += chunk.toString("utf8");
      const newline = buffered.indexOf("\n");
      if (newline === -1) return;
      const line = buffered.slice(0, newline);
      try {
        finish(JSON.parse(line));
      } catch (err) {
        finish({ ok: false, detail: `guard broker response was not JSON: ${line} (${String(err)})` });
      }
    });
    socket.once("error", (err) => finish({ ok: false, detail: `guard broker connection error: ${err.code ?? err.message}`, code: err.code }));
    socket.once("close", () => finish({ ok: false, detail: "guard broker closed the connection before responding" }));
  });
}

/** Detached-spawns the broker and never lets the caller's own process wait on it. `idleTimeoutMs`
 * is forwarded as `--idle-timeout-ms` only when the caller overrides it -- omitted, the broker
 * keeps `guard-serve-broker.mjs`'s own `DEFAULT_IDLE_TIMEOUT_MS`. Tests use this to bound how
 * long a spawned broker lingers rather than guessing its pid via a process-table search
 * (`GuardServeEngine`/`startGuardBroker` already expose `pid`/`enginePid` for the in-process
 * case; a detached spawn's own pid is intentionally not surfaced back to the caller here -- the
 * whole point of `detached: true` + `unref()` is that this process never tracks it). */
function spawnBroker({ brokerMainPath, shepherdBin, contentDir, socketPath, idleTimeoutMs }) {
  const args = [brokerMainPath, "--socket", socketPath, "--shepherd-bin", shepherdBin, "--content-dir", contentDir];
  if (idleTimeoutMs !== undefined) args.push("--idle-timeout-ms", String(idleTimeoutMs));
  const child = spawn(process.execPath, args, { detached: true, stdio: "ignore" });
  child.unref();
}

/**
 * Polls `socketPath` with real zero-payload connect probes (not just file-existence) up to
 * `deadlineMs` total -- a Unix domain socket file can exist slightly before `listen()` has
 * actually started accepting connections, and file-existence alone would let that narrow window
 * produce a spurious ECONNREFUSED on the caller's real request right after "readiness."
 * @param {string} socketPath
 * @param {number} deadlineMs
 * @returns {Promise<boolean>}
 */
async function waitForBrokerReady(socketPath, deadlineMs) {
  const start = Date.now();
  while (Date.now() - start < deadlineMs) {
    const ready = await new Promise((resolve) => {
      const probe = net.createConnection(socketPath);
      probe.once("connect", () => {
        probe.destroy();
        resolve(true);
      });
      probe.once("error", () => resolve(false));
    });
    if (ready) return true;
    await new Promise((resolve) => setTimeout(resolve, SPAWN_POLL_INTERVAL_MS));
  }
  return false;
}

/**
 * Requests one guard verdict via the persistent `shepherd guard serve` broker, spawning it (once)
 * if it is not already running. Fails CLOSED on every transport problem: no broker reachable
 * within `spawnWaitMs` of spawning one, a connection refused a second time, a malformed response,
 * or a request that outlives `connectTimeoutMs` all resolve to `{ok: false, detail}` -- never a
 * hang, never treated as an allow.
 * @param {{
 *   shepherdBin: string,
 *   contentDir: string,
 *   payload: Record<string, unknown>,
 *   socketPath: string,
 *   brokerMainPath?: string,
 *   connectTimeoutMs?: number,
 *   spawnWaitMs?: number,
 *   idleTimeoutMs?: number,
 * }} options `idleTimeoutMs` is forwarded to a newly-spawned broker only (an already-running one
 *   keeps whatever idle timeout it started with); tests use a short value so a spawned broker
 *   never outlives the test run.
 * @returns {Promise<{ok: true, engineResult: Record<string, unknown>} | {ok: false, detail: string}>}
 */
export async function requestGuardVerdict({
  shepherdBin,
  contentDir,
  payload,
  socketPath,
  brokerMainPath = DEFAULT_BROKER_MAIN,
  connectTimeoutMs = DEFAULT_CONNECT_TIMEOUT_MS,
  spawnWaitMs = DEFAULT_SPAWN_WAIT_MS,
  idleTimeoutMs,
}) {
  const first = await connectAndRequest(socketPath, payload, connectTimeoutMs);
  if (first.ok || !NO_LIVE_BROKER_CODES.has(first.code)) {
    // Either it worked, or it failed in a way spawning a fresh broker cannot fix (a malformed
    // response or a timeout means something ALREADY listening is broken/slow, not absent).
    const { code, ...rest } = first;
    return rest;
  }

  spawnBroker({ brokerMainPath, shepherdBin, contentDir, socketPath, idleTimeoutMs });
  const ready = await waitForBrokerReady(socketPath, spawnWaitMs);
  if (!ready) {
    return { ok: false, detail: `guard broker did not become ready within ${spawnWaitMs}ms after spawn (never accepted a connection at ${socketPath})` };
  }

  const second = await connectAndRequest(socketPath, payload, connectTimeoutMs);
  const { code, ...rest } = second;
  return rest;
}
