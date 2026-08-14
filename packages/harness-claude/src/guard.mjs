// packages/harness-claude/src/guard.mjs -- Claude's guard-layer wiring. Decision 1/2 (seed,
// restated in plan.md W4-S4/S5/S6): guard predicates (`content/predicates/*.toml`) are
// interpreted by exactly ONE evaluator on Claude and Codex -- the shared engine -- with
// Pi's TS interpreter as the sole SECOND one, kept in lockstep by a shared allow/deny case
// corpus rather than by two independent implementations. This module is therefore
// deliberately NOT a predicate interpreter: it never reads `content/predicates/`, never
// encodes a `subject`/`action`/`effect` rule, and never decides an allow/deny/unresolved
// verdict itself. It is the thin relay Claude's own hook contract requires -- forward the
// PreToolUse payload to the engine, translate its verdict back into Claude's hook-output
// shape -- exactly the boundary `[DO-NOT-DUPLICATE]`'s `rg -n "on\('tool_call'"` grep polices
// (that pattern is Pi's own guard API; it must never appear here, because interpretation
// never happens here).
//
// VERIFIED CONTRACT (DF-76): the engine exists and is LIVE -- `services/cli/shepherd_cli/`
// (`commands/guard.py` + `predicates.py`), served through `bin/shepherd guard eval`, the
// launcher `hooks/guard-eval.mjs` (below) actually invokes. It is Python, not Rust: Python
// 3.14 ships `tomllib` in the stdlib, so parsing `content/predicates/*.toml` there adds zero
// dependencies, and `services/cli/shepherd_cli/`'s own module docstring names itself "the
// reference implementation and the behavioral oracle" a later Rust port replays the
// `[[example]]` corpus against -- the same `crates/core/src/run.rs`/`models_run.py` pattern.
// `crates/cli` is NOT that engine: it remains a second, near-empty binary (`crates/cli/src/
// cmd.rs`'s only variant is `Init`) and was never the surface this relay shells out to, then
// or now. This replaces a prior "UNVERIFIED / PROPOSED CONTRACT" version of this comment
// written before the engine existed -- confirmed live (see `hooks/guard-eval.mjs`'s own
// header and `test/guard.test.mjs`'s integration case) rather than re-declared on faith:
//
//   stdin  (JSON): the live Claude PreToolUse hook payload verbatim (`tool_name`,
//                  `tool_input`, `tool_use_id`, `session_id`, ...), plus one adapter-added
//                  key `harness: "claude"`. NOTE: the engine does not read `harness` today
//                  (`Engine.evaluate` only branches on `predicate` vs `tool_name`) -- the key
//                  is forwarded as declared future-disambiguation headroom, not dead weight
//                  to strip, since Codex's own call site adds the same key for its harness.
//   exit 0 + stdout (JSON): exactly one of three decisions --
//                  `{"decision":"allow"}`,
//                  `{"decision":"deny","predicate":"<id>","rule":"<id>","halt_code":"<code>"?,"reason":"<text>"}`,
//                  or `{"decision":"unresolved","reason":"<text>","missing":["<field>",...]}`
//                  -- the verdict lives in the JSON body; a clean process exit means the
//                  engine successfully REACHED a verdict, all three decisions alike (never
//                  just allow/deny). `unresolved` is DF-75: the engine could not identify the
//                  acting role or otherwise lacked a fact it needed, and explicitly refuses
//                  to guess either an allow or a deny -- `interpretEngineResult` below is
//                  where THIS harness picks a posture for that state, loudly.
//   exit != 0:     an ENGINE failure (crash, malformed input, unreadable `content/`) --
//                  never a verdict, verified live: malformed stdin JSON exits 1 with an
//                  `ERROR: ...` line on stderr and nothing on stdout. The relay fails CLOSED
//                  on this (see `interpretEngineResult` below), matching this codebase's own
//                  "never a silent no-op" convention (`packages/compiler/bin/compile.mjs`'s
//                  postinstall self-heal chain note).

/**
 * The PreToolUse matcher this adapter's guard relay binds to. Deliberately every tool the
 * four live `content/predicates/*.toml` files' `action` values actually name, rather than
 * "*" -- a predicate evaluation on every `Read`/`Grep` call the engine will always allow is
 * pure overhead this relay does not need to pay.
 *
 * CONFIRMED against the live engine's shape-(b) raw-tool-call table
 * (`services/cli/shepherd_cli/predicates.py`'s `_WRITE_TOOL_NAMES` / `_DISPATCH_TOOL_NAMES`
 * / `Engine._evaluate_tool_call`), not just read off the TOML `action = "..."` lines -- every
 * entry below is a tool name that engine actually recognizes and maps to a
 * (predicate, action) pair, verified live (see `test/guard.test.mjs`'s integration case):
 *   - `write-boundary` (`fs.write`)                -> Write, Edit (`_evaluate_write_tool`;
 *     `apply_patch` is also in the engine's `_WRITE_TOOL_NAMES` set but is Codex's tool name,
 *     never Claude's, so it is correctly absent from this matcher)
 *   - `git-custody` (`vcs.write` / `vcs.integrate`) -> Bash (`_evaluate_bash_tool`, via the
 *     ported `extract_git_subcommands` tokenizer; a command with no git write verb in it
 *     allows outright, no predicate lookup needed -- matches the live
 *     `hooks/scripts/coder_git_guard.sh` / `teammate_git_guard.sh`, both matcher-bound to
 *     `Bash` today)
 *   - `dispatch-scope` (`dispatch`)                 -> Agent, Workflow (`_evaluate_dispatch_tool`)
 *
 * `dedup-gate` has NO entry here on purpose: the engine's shape-(b) mapping never resolves a
 * bare Write/Edit tool call to `dedup-gate` (only `write-boundary` -- `dedup-gate` is reachable
 * only via the normalized shape-(a) request, which this relay never constructs). The live
 * `hooks/scripts/dedup_write_guard.sh` / `dups_write_guard.sh` are the only enforcement of
 * that predicate against Claude today; this relay does not (yet) duplicate or replace them.
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
 * Handles all THREE engine decisions explicitly (allow / deny / unresolved), not two --
 * `unresolved` used to fall through to the generic "malformed" branch below, which reads as
 * an engine bug even though `unresolved` is one of the engine's three legitimate verdicts
 * (DF-75: it cannot identify the acting role, or is otherwise missing a fact it needs, and
 * refuses to guess). This harness's posture for `unresolved` is DENY -- consistent with this
 * whole module's "never a silent no-op" convention -- but the message names it as an
 * unresolved verdict distinctly from a truly malformed/garbage response, so an operator
 * reading the deny message can tell "the engine could not decide" apart from "the engine (or
 * this relay) is broken."
 *
 * @param {{decision: "allow"|"deny"|"unresolved", predicate?: string, rule?: string,
 *   halt_code?: string, reason?: string, missing?: string[]}} engineResult
 * @returns {{permissionDecision?: "deny", message?: string}} an empty object means "allow,
 *   stay silent."
 */
export function interpretEngineResult(engineResult) {
  if (engineResult?.decision === "allow") return {};
  if (engineResult?.decision === "deny") {
    const where = engineResult.predicate ? ` (${engineResult.predicate}/${engineResult.rule ?? "?"})` : "";
    const halt = engineResult.halt_code ? ` [${engineResult.halt_code}]` : "";
    return {
      permissionDecision: "deny",
      message: `guard denied${where}${halt}: ${engineResult.reason ?? "no reason given"}`,
    };
  }
  if (engineResult?.decision === "unresolved") {
    const missing = Array.isArray(engineResult.missing) && engineResult.missing.length > 0 ? ` (missing: ${engineResult.missing.join(", ")})` : "";
    return {
      permissionDecision: "deny",
      message: `guard could not reach a verdict, failing closed${missing}: ${engineResult.reason ?? "no reason given"}`,
    };
  }
  // Neither a recognized verdict (allow/deny/unresolved) nor an engine-failure exit -- a
  // truly malformed response, treated the same way an engine crash is treated: fail closed,
  // never silently allow.
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
