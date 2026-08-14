#!/usr/bin/env node
// packages/harness-codex/hooks/scripts/shepherd_guard.mjs -- Codex hook entrypoint, wired by
// ../hooks.json under TWO events now (DF-75):
//
//   PostToolUse(spawn_agent|collaborationspawn_agent) -- tags the just-spawned agent with its
//     role (src/dispatch-record.mjs `recordSpawnDispatch`); never blocks, never prints.
//   PreToolUse(apply_patch|Bash) -- the write-boundary/git-custody guard: resolve role
//     locally, then relay to the shared guard engine, translating the verdict into Codex's
//     real `PreToolUse` hook-output shape (`src/guard.mjs`'s
//     `preToolUseDeny`/`interpretEngineResult` -- see that module's header for how the wire
//     format was verified, not assumed).
//
// T2-serve-wiring: the PreToolUse branch used to `spawnSync(LAUNCHER, ["guard", "eval"], ...)` --
// a fresh `bin/shepherd` process (and a fresh `content/predicates/*.toml` parse) on EVERY
// guarded apply_patch/Bash call, measured at 450-535ms/call. It now relays through
// `packages/harness-claude/src/guard-serve-client.mjs`'s `requestGuardVerdict()` (SHARED, not
// copied -- see that module's own header, and `guard-serve-engine.mjs`'s header for why it is
// not `packages/harness-pi`'s TypeScript `GuardClient` either), which talks to a persistent
// `bin/shepherd guard serve` engine over a Unix socket broker: warm requests measured
// sub-millisecond (see this step's CODER REPORT). `requestGuardVerdict()` always resolves to the
// same `{ok:true, engineResult} | {ok:false, detail}` envelope a `spawnSync` call's
// `{error,status}`/`JSON.parse(stdout)` used to produce, so the branch below is unchanged in
// shape, only in what feeds it.
//
// All decision logic lives in ../../src/guard.mjs + ../../src/dispatch-record.mjs so both stay
// unit-testable without a subprocess (../../test/guard.test.mjs); this script is the thin
// stdio + transport shell around them, mirroring `packages/harness-claude/hooks/guard-eval.mjs`'s
// own split.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { defaultSocketPath } from "../../../harness-claude/src/guard-serve-broker.mjs";
import { requestGuardVerdict } from "../../../harness-claude/src/guard-serve-client.mjs";
import { isSpawnTool, recordSpawnDispatch, resolveDataDir, resolveRole } from "../../src/dispatch-record.mjs";
import { buildGuardDecision, engineUnavailableVerdict, interpretEngineResult, missingRecordDeniedVerdict } from "../../src/guard.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
// hooks/scripts -> hooks -> harness-codex -> packages -> repo root (4 ups) -- `bin/shepherd`
// lives in the monorepo root, not under this package's own materialized tree; see
// src/guard.mjs's module header and packages/harness-claude/hooks/guard-eval.mjs for the same
// import.meta.url-relative pattern (never `$PLUGIN_ROOT`, which resolves to this package's own
// root on Codex, not the repo root).
const REPO_ROOT = join(HERE, "..", "..", "..", "..");
const LAUNCHER = join(REPO_ROOT, "bin", "shepherd");
const CONTENT_DIR = join(REPO_ROOT, "content");

function readStdin() {
  try {
    return readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function emit(verdict) {
  if (Object.keys(verdict).length > 0) console.log(JSON.stringify(verdict));
}

async function main() {
  const raw = readStdin();
  let payload;
  try {
    payload = JSON.parse(raw || "{}");
  } catch {
    return 0; // malformed hook input: nothing to decide, stay silent (never a false deny)
  }

  const dataDir = resolveDataDir();

  if (payload.hook_event_name === "PostToolUse" && isSpawnTool(payload.tool_name)) {
    recordSpawnDispatch({ toolInput: payload.tool_input, toolResponse: payload.tool_response, dataDir });
    return 0;
  }

  if (payload.hook_event_name !== "PreToolUse") return 0;

  const decision = buildGuardDecision(
    { toolName: payload.tool_name ?? "", toolInput: payload.tool_input ?? {}, agentId: payload.agent_id ?? null, dataDir },
    resolveRole
  );

  if (decision.kind === "allow") return 0;

  if (decision.kind === "missing-record") {
    emit(missingRecordDeniedVerdict(decision.agentId));
    return 0;
  }

  const result = await requestGuardVerdict({
    shepherdBin: LAUNCHER,
    contentDir: CONTENT_DIR,
    payload: decision.payload,
    socketPath: defaultSocketPath(CONTENT_DIR),
  });

  if (!result.ok) {
    emit(engineUnavailableVerdict(result.detail));
    return 0;
  }

  emit(interpretEngineResult(result.engineResult));
  return 0;
}

main().then((code) => {
  process.exitCode = code;
});
