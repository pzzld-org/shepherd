// packages/harness-claude/src/guard-serve-broker.mjs -- the out-of-process daemon a per-invocation
// hook script cannot itself be (T2-serve-wiring). SHARED between packages/harness-claude and
// packages/harness-codex; see guard-serve-engine.mjs's own header for why this lives here and is
// cross-imported rather than copied.
//
// WHY A BROKER, NOT A DIRECT PORT OF PI'S GuardClient: a Claude/Codex `PreToolUse` hook is
// `hooks.json`'s `command`, spawned FRESH by the host CLI for every matching tool call and exited
// once it prints its verdict -- confirmed by this package's own `hooks/guard-eval.mjs` and
// `packages/harness-codex/hooks/scripts/shepherd_guard.mjs`, both single-shot `main()` functions
// with no loop, no persistent listener, nothing surviving past `process.exitCode = ...`. Pi's
// `GuardClient` (packages/harness-pi/src/guard-client.ts) can hold one `guard serve` child for an
// entire session because `src/extension.ts` itself IS a single long-lived host-embedded process
// for that whole session -- there is no equivalent "one process per session" primitive on the
// Claude/Codex hook side to hang a `GuardClient` off of. A hook process cannot hold a server
// across invocations; what it CAN do is talk, over a fast IPC channel, to something else that
// does -- so the persistent `guard serve` engine moves OUT of the hook process entirely, into
// this broker: a small Unix-domain-socket server, spawned DETACHED by the first hook invocation
// that needs it (`guard-serve-client.mjs`), that owns exactly one `GuardServeEngine` and answers
// one request per accepted connection. Every later hook invocation in the same window just
// connects, writes one line, reads one line, and exits -- paying a socket round-trip (measured,
// see this step's CODER REPORT) instead of a fresh `bin/shepherd` process spawn.
//
// LIFECYCLE ("no orphan processes: the server exits when its client does", restated for a
// topology where there is no single client process to tie to): this broker outlives any one
// hook invocation by design -- that IS the optimization. What it must never do is outlive the
// work that needs it. Two independent triggers close it down, both defined here, neither left to
// an external supervisor this file scope has no access to:
//   (1) IDLE TIMEOUT (`idleTimeoutMs`, default `DEFAULT_IDLE_TIMEOUT_MS`) -- no accepted
//       connection for that long means no hook has asked for a verdict in that long, the closest
//       observable analog "all clients gone" has in a topology built entirely from short-lived,
//       anonymous, stateless callers.
//   (2) ENGINE DEATH -- the instant `GuardServeEngine.deathReason` is set (the `guard serve`
//       child crashed or exited), this broker finishes any IN-FLIGHT connections (each still gets
//       its own fail-closed `{ok:false}` envelope -- see `guard-serve-engine.mjs`), then tears
//       itself down immediately rather than waiting out the idle window: continuing to accept
//       connections against a permanently-dead engine would either deny for up to
//       `idleTimeoutMs` after a transient crash (worse recovery than the per-call spawn this
//       replaces) or, worse, be mistaken for still being useful. Tearing down promptly means the
//       VERY NEXT hook invocation's connect attempt gets ECONNREFUSED/ENOENT and falls through to
//       `guard-serve-client.mjs`'s spawn-a-fresh-broker path -- self-healing without ever masking
//       the fact that the specific request colliding with the crash was denied, not silently
//       retried into an allow.

import { createHash } from "node:crypto";
import { existsSync, unlinkSync } from "node:fs";
import net from "node:net";
import { GuardServeEngine } from "./guard-serve-engine.mjs";

/** 10 minutes -- long enough to stay warm across a realistic gap between tool calls in one
 * interactive session, short enough that a broker nobody is using does not linger indefinitely. */
export const DEFAULT_IDLE_TIMEOUT_MS = 10 * 60 * 1000;

/**
 * Deterministic default socket path for a given `content/` root -- same `contentDir` (the normal
 * case: one repo checkout) always resolves to the same path, so `packages/harness-claude` and
 * `packages/harness-codex` share ONE broker/engine for the same repo without any coordination
 * beyond both computing this function the same way. `/tmp` directly (never `os.tmpdir()`): a Unix
 * domain socket path is capped at 104 bytes on macOS / 108 on Linux, and this repo's own hook
 * scripts (`hooks/guard-eval.mjs`, `hooks/scripts/shepherd_guard.mjs`) already assume a
 * POSIX/macOS+Linux-only host -- `os.tmpdir()`'s macOS per-user path (`/var/folders/...`) is long
 * enough to risk that limit; `/tmp` is short and always POSIX-guaranteed.
 * @param {string} contentDir
 * @returns {string}
 */
export function defaultSocketPath(contentDir) {
  const digest = createHash("sha256").update(contentDir).digest("hex").slice(0, 16);
  return `/tmp/shepherd-guard-${digest}.sock`;
}

/**
 * Reads exactly one newline-delimited JSON request off a connected socket, evaluates it against
 * `engine`, writes exactly one JSON response line back, then ends the connection -- one request
 * per connection, so the connection itself is the correlation id and no per-request tracking is
 * needed. A connection that never sends a complete line (client died mid-write) is simply ended
 * with no response; `guard-serve-client.mjs`'s own timeout is what keeps that from ever hanging a
 * caller.
 * @param {import("node:net").Socket} socket
 * @param {GuardServeEngine} engine
 */
function handleConnection(socket, engine) {
  let buffered = "";
  socket.on("data", (chunk) => {
    buffered += chunk.toString("utf8");
    const newline = buffered.indexOf("\n");
    if (newline === -1) return;
    const line = buffered.slice(0, newline);
    socket.removeAllListeners("data");
    let payload;
    try {
      payload = JSON.parse(line);
    } catch (err) {
      socket.end(`${JSON.stringify({ ok: false, detail: `guard broker received a non-JSON request line: ${line} (${String(err)})` })}\n`);
      return;
    }
    engine.evaluate(payload).then(
      (result) => socket.end(`${JSON.stringify(result)}\n`),
      (err) => socket.end(`${JSON.stringify({ ok: false, detail: `guard broker evaluation threw: ${String(err)}` })}\n`)
    );
  });
  socket.on("error", () => socket.destroy());
}

/**
 * Binds `socketPath`, recovering from a stale socket file left by a broker that was killed
 * (rather than exiting cleanly): probe-connects first; ECONNREFUSED/ENOENT means nothing is
 * listening, so any leftover file is unlinked before binding. A genuine race against another
 * process binding the SAME path at the SAME moment resolves to `null` (this attempt lost, the
 * caller should treat that as "a broker now owns this socket, nothing more to spawn").
 * @param {string} socketPath
 * @returns {Promise<import("node:net").Server | null>}
 */
async function bindSocket(socketPath) {
  if (existsSync(socketPath)) {
    const alive = await new Promise((resolve) => {
      const probe = net.createConnection(socketPath);
      probe.once("connect", () => {
        probe.destroy();
        resolve(true);
      });
      probe.once("error", () => resolve(false));
    });
    if (alive) return null; // another broker is already live on this path
    try {
      unlinkSync(socketPath);
    } catch {
      // Another process may have unlinked/rebound it between our probe and here; listen() below
      // is the authoritative check either way.
    }
  }
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", (err) => {
      if (err.code === "EADDRINUSE") resolve(null);
      else reject(err);
    });
    server.listen(socketPath, () => resolve(server));
  });
}

/**
 * Spawns one `GuardServeEngine`, binds `socketPath`, and starts answering one guard verdict per
 * connection until idle-timeout or engine death closes it down (see module header).
 * @param {{shepherdBin: string, contentDir: string, socketPath: string, idleTimeoutMs?: number}} options
 * @returns {Promise<{socketPath: string, enginePid: number, close: () => void, onClosed: Promise<void>} | null>} null
 *   means another broker already owns `socketPath` -- this instance spawned no engine and bound
 *   nothing; the caller should simply connect to the existing one.
 */
export async function startGuardBroker({ shepherdBin, contentDir, socketPath, idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS }) {
  const engine = await GuardServeEngine.spawn(shepherdBin, contentDir);
  const server = await bindSocket(socketPath);
  if (server === null) {
    engine.close();
    return null;
  }

  let idleTimer;
  let activeConnections = 0;
  let closed = false;
  let resolveClosed;
  const onClosed = new Promise((resolve) => {
    resolveClosed = resolve;
  });

  const shutdown = () => {
    if (closed) return;
    closed = true;
    clearTimeout(idleTimer);
    server.close();
    try {
      unlinkSync(socketPath);
    } catch {
      // already gone -- fine, that is the goal.
    }
    engine.close();
    resolveClosed();
  };

  const armIdleTimer = () => {
    clearTimeout(idleTimer);
    if (activeConnections === 0) idleTimer = setTimeout(shutdown, idleTimeoutMs).unref();
  };

  server.on("connection", (socket) => {
    activeConnections += 1;
    clearTimeout(idleTimer);
    handleConnection(socket, engine);
    socket.once("close", () => {
      activeConnections -= 1;
      // An engine that died while this connection was in flight already got its one fail-closed
      // reply from handleConnection -- shut down now rather than keep serving from a dead engine
      // for the rest of the idle window.
      if (engine.deathReason) shutdown();
      else armIdleTimer();
    });
  });

  armIdleTimer();
  return { socketPath, enginePid: engine.pid, close: shutdown, onClosed };
}
