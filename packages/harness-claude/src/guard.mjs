// packages/harness-claude/src/guard.mjs -- Claude's guard-layer wiring. Decision 1/2 (seed,
// restated in plan.md W4-S4/S5/S6): guard predicates (`content/predicates/*.toml`) are
// interpreted by exactly ONE evaluator on Claude and Codex -- the shared Rust engine --
// with Pi's TS interpreter as the sole SECOND one, kept in lockstep by a shared
// allow/deny case corpus rather than by two independent implementations. This module is
// therefore deliberately NOT a predicate interpreter: it never reads `content/predicates/`,
// never encodes a `subject`/`action`/`effect` rule, and never decides an allow/deny verdict
// itself. It is the thin relay Claude's own hook contract requires -- forward the
// PreToolUse payload to the engine, translate its verdict back into Claude's hook-output
// shape -- exactly the boundary `[DO-NOT-DUPLICATE]`'s `rg -n "on\('tool_call'"` grep polices
// (that pattern is Pi's own guard API; it must never appear here, because interpretation
// never happens here).
//
// UNVERIFIED / PROPOSED CONTRACT: `crates/cli` does not expose a `guard eval` subcommand as
// of this adapter's base commit (confirmed by reading `crates/cli/src/cmd.rs`: the only
// variant is `Init`) -- the "shared Rust engine" plan.md's Action 2 names has no CLI surface
// yet. `crates/**` is outside this step's file scope, so this module cannot build that
// engine; it declares the exact contract the engine needs to satisfy instead (never guesses
// at one that already exists), matching the "declare, don't invent" pattern
// `packages/harness-codex`'s own README uses for its 3-descendant cap:
//
//   stdin  (JSON): the live Claude PreToolUse hook payload verbatim (`tool_name`,
//                  `tool_input`, `tool_use_id`, `session_id`, ...), plus one adapter-added
//                  key `harness: "claude"` so the shared engine can disambiguate hook-shape
//                  differences from Codex's own call site without a second contract.
//   exit 0 + stdout (JSON): `{"decision":"allow"}` or
//                  `{"decision":"deny","predicate":"<id>","rule":"<id>","reason":"<text>"}`
//                  -- the verdict lives in the JSON body; a clean process exit means the
//                  engine successfully evaluated the call, allow or deny alike.
//   exit != 0:     an ENGINE failure (crash, malformed input) -- never a verdict. The relay
//                  fails CLOSED on this (see `interpretEngineResult` below), matching this
//                  codebase's own "never a silent no-op" convention
//                  (`packages/compiler/bin/compile.mjs`'s postinstall self-heal chain note).

/**
 * The PreToolUse matcher this adapter's guard relay binds to. Deliberately every tool the
 * four live `content/predicates/*.toml` files' `action` values actually name, rather than
 * "*" -- a predicate evaluation on every `Read`/`Grep` call the engine will always allow is
 * pure overhead this relay does not need to pay. Read directly off those four files'
 * `action = "..."` lines, not guessed:
 *   - `fs.write` (dedup-gate, write-boundary)     -> Write, Edit
 *   - `vcs.write` / `vcs.integrate` (git-custody)  -> Bash (git commit/push run through it;
 *     see the live `hooks/scripts/coder_git_guard.sh` / `teammate_git_guard.sh`, both
 *     matcher-bound to `Bash` today)
 *   - `dispatch` (dispatch-scope)                  -> Agent, Workflow
 */
export const GUARD_MATCHER = "Write|Edit|Bash|Agent|Workflow";

/**
 * @returns {object} the `hooks.json` `PreToolUse` array entry wiring this adapter's guard
 *   relay in. Consumed by whatever future step materializes `packages/harness-claude/`'s
 *   output onto the live `hooks/hooks.json` (out of this step's file scope -- see the
 *   module doc comment on why that step is not this one).
 */
export function buildGuardHooksEntry() {
  return {
    matcher: GUARD_MATCHER,
    hooks: [
      {
        type: "command",
        command: "node ${CLAUDE_PLUGIN_ROOT}/packages/harness-claude/hooks/guard-eval.mjs",
      },
    ],
  };
}

/**
 * Pure translation from the engine's verdict JSON to Claude's own PreToolUse hook-output
 * shape (`{"permissionDecision":"deny","message":"..."}` to block; an allow is silence --
 * verified against this repo's own live guard scripts, e.g. `hooks/scripts/_lib.sh`'s
 * `emit_deny` / `pass_silent`). Split out from the executable relay
 * (`hooks/guard-eval.mjs`) specifically so both the allow and the deny path are unit
 * testable without a live engine process -- `test/guard.test.mjs` exercises both, matching
 * plan.md's own acceptance requirement that "every guard predicate has an allow AND a deny
 * case."
 *
 * @param {{decision: "allow"|"deny", predicate?: string, rule?: string, reason?: string}} engineResult
 * @returns {{permissionDecision?: "deny", message?: string}} an empty object means "allow,
 *   stay silent."
 */
export function interpretEngineResult(engineResult) {
  if (engineResult?.decision === "allow") return {};
  if (engineResult?.decision === "deny") {
    const where = engineResult.predicate ? ` (${engineResult.predicate}/${engineResult.rule ?? "?"})` : "";
    return {
      permissionDecision: "deny",
      message: `guard denied${where}: ${engineResult.reason ?? "no reason given"}`,
    };
  }
  // Neither a recognized verdict nor an engine-failure exit -- treat as a malformed
  // response the same way an engine crash is treated: fail closed, never silently allow.
  return {
    permissionDecision: "deny",
    message: `guard engine returned an unrecognized verdict: ${JSON.stringify(engineResult)}`,
  };
}

/**
 * The fail-closed verdict `hooks/guard-eval.mjs` emits when the engine process itself
 * cannot be reached or exits non-zero -- an infra failure, not a predicate decision. Never a
 * silent no-op: an unreachable engine must not be indistinguishable from "allowed."
 *
 * @param {string} detail
 */
export function engineUnavailableVerdict(detail) {
  return {
    permissionDecision: "deny",
    message: `guard engine unavailable, failing closed: ${detail}`,
  };
}
