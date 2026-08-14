#!/usr/bin/env node
// packages/harness-claude/hooks/guard-eval.mjs -- the executable PreToolUse relay
// `src/guard.mjs`'s `buildGuardHooksEntry()` wires in. Reads Claude's PreToolUse hook JSON
// from stdin, forwards it verbatim (plus `harness: "claude"`) to the shared guard engine via
// `bin/shepherd guard eval` -- LIVE, confirmed by running this exact file end to end against
// the real `services/cli/shepherd_cli/` engine (see `src/guard.mjs`'s module doc comment for
// the full contract, and `test/guard.test.mjs`'s integration case for the reproducible
// invocation) -- and prints Claude's own hook-output JSON. `LAUNCHER` below resolves to the
// repo-root `bin/shepherd` bash wrapper, never `crates/cli`; that wrapper's own header calls
// itself "the single canonical entrypoint for the shepherd CLI." All decision logic lives in
// `src/guard.mjs` (`interpretEngineResult` / `engineUnavailableVerdict`) so it stays unit
// testable without spawning a process -- this file is intentionally the thinnest possible
// wrapper around that logic plus stdin/stdout/`spawnSync` plumbing.

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { engineUnavailableVerdict, interpretEngineResult } from "../src/guard.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const LAUNCHER = join(REPO_ROOT, "bin", "shepherd");

function readStdin() {
  try {
    return readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function main() {
  const raw = readStdin();
  let payload;
  try {
    payload = { ...JSON.parse(raw || "{}"), harness: "claude" };
  } catch (error) {
    console.log(JSON.stringify(engineUnavailableVerdict(`malformed PreToolUse input: ${error.message}`)));
    return 0;
  }

  const result = spawnSync(LAUNCHER, ["guard", "eval"], {
    input: JSON.stringify(payload),
    encoding: "utf8",
  });

  if (result.error || result.status !== 0) {
    const detail = result.error ? result.error.message : `exit ${result.status}: ${result.stderr?.trim()}`;
    console.log(JSON.stringify(engineUnavailableVerdict(detail)));
    return 0;
  }

  let engineResult;
  try {
    engineResult = JSON.parse(result.stdout);
  } catch (error) {
    console.log(JSON.stringify(engineUnavailableVerdict(`unparseable engine output: ${error.message}`)));
    return 0;
  }

  const verdict = interpretEngineResult(engineResult);
  if (Object.keys(verdict).length > 0) console.log(JSON.stringify(verdict));
  return 0;
}

process.exitCode = main();
