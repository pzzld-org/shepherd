#!/usr/bin/env node
// packages/harness-codex/hooks/scripts/shepherd_guard.mjs -- Codex PreToolUse guard
// entrypoint, wired by ../hooks.json. Reads one JSON hook payload from stdin and writes one
// JSON decision to stdout, matching the SAME `{"permissionDecision":"deny","message":"..."}`
// / silent-exit-0-on-allow contract Claude's own `hooks/scripts/_lib.sh` (`emit_deny`/
// `pass_silent`) and the installed `codex-shepherd@1.0.2` bundle's `shepherd_hook.py` both
// already use (confirmed identical wire format by reading that bundle's own `main()`) -- this
// script is the thin stdio shell; all decision logic lives in ../../src/guard.mjs so it can
// be unit-tested without a subprocess (../../test/guard.test.mjs).
//
// SHEPHERD_ROLE is read from the environment as the interim role signal -- see
// src/guard.mjs's module header for exactly why, and what closes this gap later.

import { decideForToolCall } from "../../src/guard.mjs";

// halt_code per (predicateId, fired rule id), transcribed from content/predicates/*.toml's
// own `[[example]]` blocks -- the only two predicates this adapter's guard actually fires.
const HALT_CODES = Object.freeze({
  "write-boundary:role-write-eligibility": "SCOPE OVERFLOW",
  "write-boundary:path-in-declared-scope": "SCOPE OVERFLOW",
  "git-custody:implementer-never-writes-git": "CODER-GIT-WRITE",
  "git-custody:lane-lead-owns-its-own-branch-only": "TEAMMATE-GIT-WRITE",
  "git-custody:cross-lane-integration-is-root-exclusive": "TEAMMATE-GIT-WRITE",
});

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", () => resolve(data));
  });
}

async function main() {
  const raw = await readStdin();
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return 0; // malformed hook input fails open, same as hooks/scripts/_lib.sh's json_field
  }

  const decision = decideForToolCall({
    toolName: payload.tool_name ?? "",
    toolInput: payload.tool_input ?? {},
    role: process.env.SHEPHERD_ROLE ?? "",
  });

  if (decision.result === "deny") {
    const firedRuleIds = decision.firedRuleIds ?? [];
    const haltCode = firedRuleIds.map((id) => HALT_CODES[`${decision.predicateId}:${id}`]).find(Boolean) ?? "SCOPE OVERFLOW";
    process.stdout.write(
      JSON.stringify({
        permissionDecision: "deny",
        message: `[shepherd] ${haltCode} -- predicate \`${decision.predicateId}\` denied (fired: ${firedRuleIds.join(", ")}).`,
      })
    );
  }
  return 0;
}

main().then((code) => (process.exitCode = code));
