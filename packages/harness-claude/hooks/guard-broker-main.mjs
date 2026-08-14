#!/usr/bin/env node
// packages/harness-claude/hooks/guard-broker-main.mjs -- the executable a hook process detached-
// spawns (`src/guard-serve-client.mjs`'s `spawnBroker()`) so a persistent `guard serve` engine can
// outlive the short-lived hook invocation that started it (T2-serve-wiring). SHARED between
// packages/harness-claude and packages/harness-codex -- `packages/harness-codex/hooks/scripts/
// shepherd_guard.mjs` spawns THIS SAME file (cross-package, same convention `src/materialize.mjs`
// already uses importing `../../compiler/`), never a second copy.
//
// Deliberately the thinnest possible wrapper, mirroring `guard-eval.mjs`'s own "all decision
// logic lives in src/, this file is stdio/argv plumbing" split: parses argv, calls
// `src/guard-serve-broker.mjs`'s `startGuardBroker()`, and simply awaits `onClosed` -- the broker
// module owns every lifecycle decision (idle timeout, engine-death teardown). This process's own
// job ends the moment `onClosed` resolves; nothing here decides WHEN that happens.

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { startGuardBroker } from "../src/guard-serve-broker.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const DEFAULT_LAUNCHER = join(REPO_ROOT, "bin", "shepherd");
const DEFAULT_CONTENT_DIR = join(REPO_ROOT, "content");

/** @param {string[]} argv @returns {Record<string, string>} */
function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const flag = argv[i];
    if (!flag?.startsWith("--")) continue;
    args[flag.slice(2)] = argv[i + 1];
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const socketPath = args.socket;
  if (!socketPath) {
    process.stderr.write("guard-broker-main.mjs: --socket <path> is required\n");
    process.exitCode = 1;
    return;
  }
  const shepherdBin = args["shepherd-bin"] ?? DEFAULT_LAUNCHER;
  const contentDir = args["content-dir"] ?? DEFAULT_CONTENT_DIR;
  const idleTimeoutMs = args["idle-timeout-ms"] ? Number(args["idle-timeout-ms"]) : undefined;

  let broker;
  try {
    broker = await startGuardBroker({
      shepherdBin,
      contentDir,
      socketPath,
      ...(idleTimeoutMs === undefined ? {} : { idleTimeoutMs }),
    });
  } catch (err) {
    // The engine itself never came up (bad `bin/shepherd`, unreadable content/) -- exit without
    // ever binding a socket. Every waiting client's own `waitForBrokerReady` times out and fails
    // closed; nothing here needs to signal that beyond exiting.
    process.stderr.write(`guard-broker-main.mjs: ${err.message ?? err}\n`);
    process.exitCode = 1;
    return;
  }
  if (broker === null) {
    // Lost the race to bind `socketPath` -- another broker already owns it. Exit clean; that
    // broker answers every client instead.
    return;
  }
  await broker.onClosed;
}

await main();
