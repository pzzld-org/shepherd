#!/usr/bin/env node
// packages/harness-claude/hooks/guard-eval.mjs -- the executable PreToolUse relay
// `src/guard.mjs`'s `buildGuardHooksEntry()` wires in. Reads Claude's PreToolUse hook JSON
// from stdin, resolves `role` LOCALLY (`src/dispatch-record.mjs`'s `resolveRole`, closing the
// W10 auditor's HIGH finding -- see `src/guard.mjs`'s own "ROLE RESOLUTION" header for the
// full three-way contract), then either short-circuits allow/deny or forwards the resolved
// request to the shared guard engine and prints Claude's own hook-output JSON.
//
// T2-serve-wiring: this used to `spawnSync(LAUNCHER, ["guard", "eval"], ...)` -- a fresh
// `bin/shepherd` process (and a fresh `content/predicates/*.toml` parse) on EVERY guarded
// Write/Edit/Bash/Agent/Workflow call, measured at 450-535ms/call. It now relays through
// `src/guard-serve-client.mjs`'s `requestGuardVerdict()`, which talks to a persistent
// `bin/shepherd guard serve` engine over a Unix socket broker (`src/guard-serve-broker.mjs`) --
// warm requests measured sub-millisecond (see this step's CODER REPORT). `requestGuardVerdict()`
// always resolves to the same `{ok:true, engineResult} | {ok:false, detail}` envelope a
// `spawnSync` call's `{error,status}`/`JSON.parse(stdout)` used to produce, so the two branches
// below are unchanged in shape, only in what feeds them. All decision logic still lives in
// `src/guard.mjs` (`buildGuardDecision` / `interpretEngineResult` / `engineUnavailableVerdict` /
// `missingRecordDeniedVerdict` / `roleResolutionUnavailableVerdict`) so it stays unit testable
// without spawning a process -- this file is intentionally the thinnest possible wrapper around
// that logic plus stdin/stdout/transport plumbing.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveRole } from "../src/dispatch-record.mjs";
import {
  buildGuardDecision,
  engineUnavailableVerdict,
  interpretEngineResult,
  missingRecordDeniedVerdict,
  roleResolutionUnavailableVerdict,
} from "../src/guard.mjs";
import { defaultSocketPath } from "../src/guard-serve-broker.mjs";
import { requestGuardVerdict } from "../src/guard-serve-client.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const LAUNCHER = join(REPO_ROOT, "bin", "shepherd");
const CONTENT_DIR = join(REPO_ROOT, "content");

function readStdin() {
  try {
    return readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

async function main() {
  const raw = readStdin();
  let input;
  try {
    input = JSON.parse(raw || "{}");
  } catch (error) {
    console.log(JSON.stringify(engineUnavailableVerdict(`malformed PreToolUse input: ${error.message}`)));
    return 0;
  }

  const decision = buildGuardDecision(input, resolveRole);
  if (decision.kind === "allow") return 0;
  if (decision.kind === "missing-record") {
    console.log(JSON.stringify(missingRecordDeniedVerdict(decision.toolUseId)));
    return 0;
  }
  if (decision.kind === "resolution-failed") {
    console.log(JSON.stringify(roleResolutionUnavailableVerdict(decision.detail)));
    return 0;
  }

  const result = await requestGuardVerdict({
    shepherdBin: LAUNCHER,
    contentDir: CONTENT_DIR,
    payload: decision.payload,
    socketPath: defaultSocketPath(CONTENT_DIR),
  });

  if (!result.ok) {
    console.log(JSON.stringify(engineUnavailableVerdict(result.detail)));
    return 0;
  }

  const verdict = interpretEngineResult(result.engineResult);
  if (Object.keys(verdict).length > 0) console.log(JSON.stringify(verdict));
  return 0;
}

main().then((code) => {
  process.exitCode = code;
});
