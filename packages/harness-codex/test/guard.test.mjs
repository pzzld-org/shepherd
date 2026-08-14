#!/usr/bin/env node
// packages/harness-codex/test/guard.test.mjs -- run directly:
//   node packages/harness-codex/test/guard.test.mjs
// DF-75's own conformance suite. Exercises src/guard.mjs's pure decision core PLUS one real,
// unstubbed `bin/shepherd guard eval` invocation -- per the dispatch brief: "A unit test with
// a stubbed engine does not establish that codex-shepherd enforces anything." No test here
// ever sets SHEPHERD_ROLE to manufacture a role the runtime would not provide -- that is the
// exact defect DF-75 fixes; every role signal below goes through the real resolution path
// (src/dispatch-record.mjs's `writeDispatchRecord`/`resolveRole`) against a real, disposable
// dispatch-record file.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveRole, writeDispatchRecord } from "../src/dispatch-record.mjs";
import { buildGuardDecision, engineUnavailableVerdict, interpretEngineResult, missingRecordDeniedVerdict } from "../src/guard.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const LAUNCHER = join(HERE, "..", "..", "..", "bin", "shepherd");

const dataDir = mkdtempSync(join(tmpdir(), "harness-codex-guard-test-"));

// 1. marker absent -> allow (the root/operator session keeps working; no engine call at all,
//    the whole reason blanket fail-closed would deadlock and this design does not) ----------
const noMarker = buildGuardDecision(
  { toolName: "Bash", toolInput: { command: "git commit -m x" }, agentId: null, dataDir },
  resolveRole
);
assert.deepEqual(noMarker, { kind: "allow" });

// 2. marker present + record found + implementer role attempting a git write -> DENY with
//    halt code CODER-GIT-WRITE. Role comes from a REAL dispatch record (never a manufactured
//    SHEPHERD_ROLE), and the verdict comes from a REAL `bin/shepherd guard eval` subprocess --
//    a stubbed engine could not prove this fires at all. -------------------------------------
writeDispatchRecord(dataDir, "agent-coder-1", "coder");
const coderGitWrite = buildGuardDecision(
  { toolName: "Bash", toolInput: { command: "git commit -m x" }, agentId: "agent-coder-1", dataDir },
  resolveRole
);
assert.equal(coderGitWrite.kind, "request");
assert.deepEqual(coderGitWrite.payload, {
  harness: "codex",
  role: "coder",
  tool_name: "Bash",
  tool_input: { command: "git commit -m x" },
});

const engineRun = spawnSync(LAUNCHER, ["guard", "eval"], { input: JSON.stringify(coderGitWrite.payload), encoding: "utf8" });
assert.equal(engineRun.status, 0, engineRun.stderr);
const engineVerdict = JSON.parse(engineRun.stdout);
assert.equal(engineVerdict.decision, "deny");
assert.equal(engineVerdict.halt_code, "CODER-GIT-WRITE");

const hookOutput = interpretEngineResult(engineVerdict);
assert.equal(hookOutput.hookSpecificOutput.hookEventName, "PreToolUse");
assert.equal(hookOutput.hookSpecificOutput.permissionDecision, "deny");
assert.match(hookOutput.hookSpecificOutput.permissionDecisionReason, /CODER-GIT-WRITE/);

// 3. marker present + record MISSING -> DENY. This is the DF-75 regression test: previously
//    an unresolvable role fell through to `if (!role) return { result: "allow" }` -- a silent
//    allow. No dispatch record was ever written for this agent id. -----------------------------
const missingRecord = buildGuardDecision(
  { toolName: "apply_patch", toolInput: {}, agentId: "agent-never-tagged", dataDir },
  resolveRole
);
assert.deepEqual(missingRecord, { kind: "missing-record", agentId: "agent-never-tagged" });
const missingRecordVerdict = missingRecordDeniedVerdict(missingRecord.agentId);
assert.equal(missingRecordVerdict.hookSpecificOutput.permissionDecision, "deny");
assert.match(missingRecordVerdict.hookSpecificOutput.permissionDecisionReason, /agent-never-tagged/);
assert.match(missingRecordVerdict.hookSpecificOutput.permissionDecisionReason, /no dispatch record/);

// 4. engine exits non-zero (or is otherwise unreachable) -> DENY, fail closed --------------
const unavailable = engineUnavailableVerdict("ENOENT: bin/shepherd not found");
assert.equal(unavailable.hookSpecificOutput.permissionDecision, "deny");
assert.match(unavailable.hookSpecificOutput.permissionDecisionReason, /ENOENT/);

// A malformed/unrecognized engine verdict also fails CLOSED, never open.
const malformed = interpretEngineResult({ nonsense: true });
assert.equal(malformed.hookSpecificOutput.permissionDecision, "deny");

// A real, unstubbed engine allow still reaches an empty (silent) verdict.
const allowRun = spawnSync(LAUNCHER, ["guard", "eval"], {
  input: JSON.stringify({ harness: "codex", role: "coder", tool_name: "Bash", tool_input: { command: "git status" } }),
  encoding: "utf8",
});
assert.equal(allowRun.status, 0, allowRun.stderr);
assert.deepEqual(interpretEngineResult(JSON.parse(allowRun.stdout)), {});

rmSync(dataDir, { recursive: true, force: true });

console.log(
  "ok: buildGuardDecision resolves role via a REAL dispatch record (no SHEPHERD_ROLE manufacturing), " +
    "denies a real CODER-GIT-WRITE through the real `bin/shepherd guard eval` engine, denies an " +
    "untagged dispatch loudly (DF-75), and fails closed on an unreachable/malformed engine"
);
