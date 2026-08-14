#!/usr/bin/env node
// packages/harness-codex/test/guard.test.mjs -- run directly:
//   node packages/harness-codex/test/guard.test.mjs
// Exercises src/guard.mjs's pure decision core directly (no subprocess/stdin needed --
// hooks/scripts/shepherd_guard.mjs is a thin stdio shell around it).

import assert from "node:assert/strict";
import { decideForToolCall, extractGitSubcommands } from "../src/guard.mjs";

// write-boundary via apply_patch -----------------------------------------------------------
assert.equal(decideForToolCall({ toolName: "apply_patch", role: "coder" }).result, "allow");
assert.equal(decideForToolCall({ toolName: "apply_patch", role: "critic" }).result, "deny");
assert.equal(decideForToolCall({ toolName: "apply_patch", role: "critic" }).predicateId, "write-boundary");

// unknown/absent role fails open ------------------------------------------------------------
assert.equal(decideForToolCall({ toolName: "apply_patch", role: "" }).result, "allow");
assert.equal(decideForToolCall({ toolName: "apply_patch", role: "not-a-real-role" }).result, "allow");

// git-custody via Bash ----------------------------------------------------------------------
assert.equal(
  decideForToolCall({ toolName: "Bash", role: "coder", toolInput: { command: "git status" } }).result,
  "allow"
);
const commitDeny = decideForToolCall({ toolName: "Bash", role: "coder", toolInput: { command: "git commit -m x" } });
assert.equal(commitDeny.result, "deny");
assert.equal(commitDeny.predicateId, "git-custody");
assert.deepEqual(commitDeny.firedRuleIds, ["implementer-never-writes-git"]);

// non-git Bash and non-guarded tools pass through --------------------------------------------
assert.equal(decideForToolCall({ toolName: "Bash", role: "coder", toolInput: { command: "ls -la" } }).result, "allow");
assert.equal(decideForToolCall({ toolName: "Read", role: "critic" }).result, "allow");

// extractGitSubcommands ----------------------------------------------------------------------
assert.deepEqual(extractGitSubcommands("git status && git log"), ["status", "log"]);
assert.deepEqual(extractGitSubcommands("git -C x commit -m y"), ["commit"]);
assert.deepEqual(extractGitSubcommands("ls -la"), []);

console.log("ok: decideForToolCall enforces write-boundary + git-custody, fails open for unresolvable role/tool signals");
