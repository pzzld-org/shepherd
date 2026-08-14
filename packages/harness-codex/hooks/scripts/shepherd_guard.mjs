#!/usr/bin/env node
// packages/harness-codex/hooks/scripts/shepherd_guard.mjs -- Codex hook entrypoint, wired by
// ../hooks.json under TWO events now (DF-75):
//
//   PostToolUse(spawn_agent|collaborationspawn_agent) -- tags the just-spawned agent with its
//     role (src/dispatch-record.mjs `recordSpawnDispatch`); never blocks, never prints.
//   PreToolUse(apply_patch|Bash) -- the write-boundary/git-custody guard: resolve role
//     locally, then shell out to `bin/shepherd guard eval` for anything that needs the
//     engine, translating the verdict into Codex's real `PreToolUse` hook-output shape
//     (`src/guard.mjs`'s `preToolUseDeny`/`interpretEngineResult` -- see that module's header
//     for how the wire format was verified, not assumed).
//
// All decision logic lives in ../../src/guard.mjs + ../../src/dispatch-record.mjs so both stay
// unit-testable without a subprocess (../../test/guard.test.mjs); this script is the thin
// stdio + `spawnSync` shell around them, mirroring `packages/harness-claude/hooks/guard-eval.mjs`'s
// own split.

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
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

function main() {
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

  const result = spawnSync(LAUNCHER, ["guard", "eval"], { input: JSON.stringify(decision.payload), encoding: "utf8" });
  if (result.error || result.status !== 0) {
    const detail = result.error ? result.error.message : `exit ${result.status}: ${result.stderr?.trim()}`;
    emit(engineUnavailableVerdict(detail));
    return 0;
  }

  let engineResult;
  try {
    engineResult = JSON.parse(result.stdout);
  } catch (error) {
    emit(engineUnavailableVerdict(`unparseable engine output: ${error.message}`));
    return 0;
  }

  emit(interpretEngineResult(engineResult));
  return 0;
}

process.exitCode = main();
