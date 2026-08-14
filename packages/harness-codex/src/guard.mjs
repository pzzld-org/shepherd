// packages/harness-codex/src/guard.mjs -- Codex's guard-layer wiring. DF-75/CRITICAL: the
// PREVIOUS version of this module opened `decideForToolCall` with
// `if (!role) return { result: "allow" }`, where `role` came from a `SHEPHERD_ROLE`
// environment variable NOTHING sets for a Codex subprocess -- every branch fell through to
// allow, permanently. Two changes, in the binding order the wave auditor required:
//
// (1) ROLE RESOLUTION FIRST (src/dispatch-record.mjs) -- Codex's own analog of
//     hooks/scripts/agent_invocation_tagger.sh + `current_role()`. `resolveRole` distinguishes
//     three cases: no marker at all (root/operator session -> ALLOW, never touches the
//     engine), a marker with a resolved record (evaluate for real), and a marker with NO
//     record (a dispatched agent whose role cannot be determined -> DENY, loudly -- this is
//     the exact case that used to be a silent allow).
// (2) ONLY THEN collapse write-boundary/git-custody interpretation onto the shared engine
//     (`shepherd guard eval`, `services/cli/shepherd_cli/predicates.py`) -- this module is
//     now deliberately NOT a predicate interpreter (mirrors `packages/harness-claude/src/guard.mjs`'s
//     own module doc comment): it never reads `content/predicates/`, never encodes a
//     `subject`/`action`/`effect` rule. `hooks/scripts/shepherd_guard.mjs` is the thin stdio
//     shell that shells out to `bin/shepherd guard eval` and calls `interpretEngineResult`
//     below to translate the verdict -- `buildGuardDecision` stays pure (no subprocess, no
//     `spawnSync`) so it is directly unit-testable, matching why
//     `packages/harness-claude/src/guard.mjs`/`hooks/guard-eval.mjs` are also split in two.
//
// WIRE FORMAT -- verified, not copied from Claude's shape. The pre-existing
// `hooks/scripts/shepherd_guard.mjs` (now rewritten) claimed a flat
// `{"permissionDecision":"deny","message":"..."}` shape "confirmed identical" to Codex's own
// `codex-shepherd@1.0.2` bundle -- that claim does not hold up: reading that bundle's
// `hooks/protocol.py` `denial()` directly (not just this package's paraphrase of it) shows
// Codex's real `PreToolUse` hook output is a NESTED
// `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"|"allow",
// "permissionDecisionReason": "..."}}` shape -- confirmed a second, independent way by
// `strings /opt/homebrew/bin/codex` (the installed `codex-cli 0.147.0` binary), which embeds
// `PreToolUseHookSpecificOutputWire` with exactly those field names, and a third way by that
// bundle's own `tests/gate/test_governance.py` (`output["hookSpecificOutput"]["permissionDecision"]`).
// Emitting the OLD flat shape would have meant a correct `deny` verdict was silently ignored
// by Codex -- "it enforces nothing while looking healthy" one layer deeper than DF-75's own
// role-resolution defect. `preToolUseDeny` below is the one place this shape is built.

/**
 * @param {string} reason
 * @returns {{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: string}}}
 */
function preToolUseDeny(reason) {
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason,
    },
  };
}

/**
 * Pure translation from the engine's verdict JSON to Codex's real `PreToolUse` hook-output
 * shape. An `allow` verdict is `{}` (silence -- the executable relay prints nothing, matching
 * this codebase's `pass_silent` convention everywhere else). `deny` and any OTHER shape
 * (including `unresolved` -- DF-75's whole point: an unidentifiable dispatch must not
 * silently allow) fail CLOSED.
 *
 * @param {{decision?: string, predicate?: string, rule?: string, halt_code?: string, reason?: string}} engineResult
 * @returns {{}|ReturnType<typeof preToolUseDeny>}
 */
export function interpretEngineResult(engineResult) {
  if (engineResult?.decision === "allow") return {};
  if (engineResult?.decision === "deny") {
    const where = engineResult.predicate ? ` (${engineResult.predicate}/${engineResult.rule ?? "?"})` : "";
    const halt = engineResult.halt_code ? `[${engineResult.halt_code}] ` : "";
    return preToolUseDeny(`${halt}guard denied${where}: ${engineResult.reason ?? "no reason given"}`);
  }
  return preToolUseDeny(`guard engine returned an unrecognized verdict: ${JSON.stringify(engineResult)}`);
}

/**
 * The fail-closed verdict `hooks/scripts/shepherd_guard.mjs` emits when the `shepherd guard
 * eval` subprocess itself cannot be reached or exits non-zero -- an infra failure, never a
 * predicate decision. An unreachable engine must not be indistinguishable from "allowed."
 *
 * @param {string} detail
 */
export function engineUnavailableVerdict(detail) {
  return preToolUseDeny(`guard engine unavailable, failing closed: ${detail}`);
}

/**
 * DF-75's own regression case, given its own specific, loud message rather than the engine's
 * generic "missing role" reason (which does not name what is actually missing): a
 * `PreToolUse` call whose `agent_id` marker is present but for which no dispatch record was
 * ever written. Deliberately never invents a halt code (no `content/predicates/*.toml`
 * `[[example]]` attests one for this adapter-local, pre-engine case -- it mirrors
 * `packages/harness-pi/src/extension.ts`'s own unset-`SHEPHERD_ROLE` denial, which also
 * carries no halt code).
 *
 * @param {string} agentId
 */
export function missingRecordDeniedVerdict(agentId) {
  return preToolUseDeny(
    `role unresolved -- no dispatch record for agent \`${agentId}\`. This Codex subagent's ` +
      "spawn_agent/collaborationspawn_agent call was never tagged with a role, or its dispatch " +
      "record is missing. DF-75 requires failing closed rather than allowing an unidentified " +
      "dispatch to write."
  );
}

/**
 * The pure decision core behind `hooks/scripts/shepherd_guard.mjs`'s `PreToolUse` handling.
 * Resolves role locally (never touching the engine for the "no marker" case -- see module
 * header), then either short-circuits ALLOW/DENY or hands back the exact request the
 * executable relay forwards to `shepherd guard eval` (shape (b), a raw tool call --
 * `services/cli/shepherd_cli/predicates.py`'s `Engine._evaluate_tool_call` already maps
 * `apply_patch`/`Bash` onto `write-boundary`/`git-custody` and extracts git subcommands
 * itself; this module never re-implements that tokenizer).
 *
 * @param {{toolName: string, toolInput?: Record<string, unknown>, agentId?: string|null, dataDir: string}} call
 * @param {(agentId: string|null|undefined, dataDir: string) => {kind: string, role?: string, agentId?: string}} resolveRoleFn
 *   injected so this stays a pure function of its arguments -- `hooks/scripts/shepherd_guard.mjs`
 *   passes the real `resolveRole` from `src/dispatch-record.mjs`.
 * @returns {{kind: "allow"}|{kind: "missing-record", agentId: string}|{kind: "request", payload: object}}
 */
export function buildGuardDecision(call, resolveRoleFn) {
  const resolution = resolveRoleFn(call.agentId, call.dataDir);
  if (resolution.kind === "no-marker") return { kind: "allow" };
  if (resolution.kind === "missing-record") return { kind: "missing-record", agentId: resolution.agentId };
  return {
    kind: "request",
    payload: {
      harness: "codex",
      role: resolution.role,
      tool_name: call.toolName,
      tool_input: call.toolInput ?? {},
    },
  };
}
