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
//
// ROLE RESOLUTION (closes the W10 auditor's HIGH finding, `.shepherd/runs/v645/reports/
// auditor-W10-central-verify.md`): the PRIOR version of `hooks/guard-eval.mjs` forwarded
// `{ ...JSON.parse(raw || "{}"), harness: "claude" }` -- no `role` key, ever, from any caller,
// because Claude's real `PreToolUse` payload never carries one. Wired into `hooks/hooks.json`
// as-is, that would have hit `_evaluate_write_tool`/`_evaluate_bash_tool`/
// `_evaluate_dispatch_tool`'s own `if role is None: return _unresolved(...)` for EVERY
// Write/Edit/Bash/Agent/Workflow call from EVERY role -- including root's own legitimate git
// operations -- and `interpretEngineResult` (below) turns `unresolved` into DENY. `src/
// dispatch-record.mjs`'s `resolveRole` closes this the same way
// `packages/harness-codex/src/dispatch-record.mjs`'s own `resolveRole` does (that module's
// header names it "the proven template"): a three-way split BEFORE the engine is ever
// consulted -- no marker (root, never dispatched) -> allow; marker + a resolved record ->
// forward `role` to the engine for a real decision; marker + no record -> WARN loudly and
// allow (see below -- this was DENY through v645's own first pass at this file, measured
// live against a real, dispatch-active sprint to deny 100% of calls, root's included; fixed
// here). Unlike Codex, this adapter does NOT build a new tagging mechanism -- it reuses the
// sibling DF-77 fix already on disk (`hooks/scripts/agent_invocation_tagger.sh` +
// `current_role()`, `hooks/scripts/_lib.sh`) by shelling out to it, so there is exactly one
// `tool_use_id` -> dispatch-record correlation in this codebase, not two. `buildGuardDecision`
// below is the pure decision core (injectable `resolveRoleFn`, matching
// `packages/harness-codex/src/guard.mjs`'s own split, so it is unit-testable without a
// subprocess); `hooks/guard-eval.mjs` is the thin stdio shell around it.
//
// MISSING-RECORD POSTURE, CORRECTED: the PRIOR version of this module denied a `missing-record`
// resolution outright (`missingRecordDeniedVerdict`, DENY), justified in text as "mirrored from
// `packages/harness-codex/src/dispatch-record.mjs`'s own three-way `resolveRole`" -- but that
// mirroring does not hold for the ACTION, only the SHAPE. Codex's `missing-record` denies
// safely because its correlation key, `agent_id`, is runtime-assigned once per spawned agent and
// never appears on root's own unspawned calls -- a `missing-record` there really does mean "a
// spawned agent went untagged," never "this might just be root." Claude's correlation key,
// `tool_use_id`, is minted fresh per tool call (DF-77 FIX 3, still open, `_lib.sh`'s own
// `current_role()` header) -- so `current_role()` returns the literal `"unknown"` for BOTH
// root's own direct call AND an untraceable dispatched call, with NO signal here that tells them
// apart. Denying on that ambiguity denies root. Measured live: a fresh `tool_use_id` against
// this repo's own `.shepherd/dispatch/v6.4.5/` (64 tagged records, non-empty since this
// sprint's first dispatch) resolves to `missing-record` for a PLAIN `git status`, every time --
// the directory-presence tiebreak (`hasMarker`) answers "has this sprint dispatched anything,
// ever," never "did THIS call come from a dispatch," so it is `true` for every call in every
// real sprint, forever, and cannot break the tie it was built to break.
//
// This repo already resolved the identical ambiguity once, correctly, for git writes:
// `hooks/scripts/coder_git_guard.sh`'s shipped DF-77 FIX 2 posture never denies an unresolved
// role, because root's own git writes are mechanically indistinguishable from an unidentified
// coder's -- it warns loudly (`additionalContext`, never `permissionDecision:"deny"`) so the gap
// stays auditable instead of either silently open or wrongly closed. Two guards reading the same
// unresolvable signal must not reach opposite verdicts -- `missing-record` now matches that
// posture: `missingRecordWarnedVerdict` (below) returns a WARN, not a DENY, and
// `hooks/guard-eval.mjs` lets the call through. This is not a narrower guarantee than Codex's --
// it is the honest one for a correlation key that, today, cannot tell root from an untraceable
// coder. It closes once DF-77 FIX 3 lands a real per-call correlation key; until then, a
// resolved, non-`"unknown"` role reaching the engine (the common, correctly-identified case) is
// unaffected -- only the genuinely unresolvable case changes.

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

/**
 * DF-75's own regression case, given its own specific, loud message rather than a silent pass:
 * a `PreToolUse` call whose sprint has SOME tagged dispatch record (a marker genuinely exists --
 * see `src/dispatch-record.mjs`'s module header for what "marker" means on Claude's own wire
 * shape), yet none of those records correlate to THIS call's own `tool_use_id`. NOT a deny --
 * see this module's header ("MISSING-RECORD POSTURE, CORRECTED") for why `tool_use_id`'s open
 * correlation gap (DF-77 FIX 3) makes root's own call and an untraceable dispatched call
 * genuinely indistinguishable here, and why `hooks/scripts/coder_git_guard.sh`'s shipped DF-77
 * FIX 2 posture -- warn loudly, never deny, on the identical ambiguity -- is the one this
 * verdict now matches. `additionalContext`, not `permissionDecision`, so the call proceeds
 * (Claude's own convention -- see `hooks/scripts/_lib.sh`'s `emit_context`). Deliberately never
 * invents a halt code: this is a warning, not an enforcement action.
 *
 * @param {string} toolUseId
 */
export function missingRecordWarnedVerdict(toolUseId) {
  return {
    additionalContext:
      `[shepherd] guard could not confirm the acting role for tool_use_id \`${toolUseId}\` -- ` +
      "this sprint has tagged dispatch records, but none matches this call. NOT denied: " +
      "the correlation key (tool_use_id, DF-77 FIX 3) is still open, so a resolved role of " +
      `"unknown" here is indistinguishable from root's own untracked action -- denying would ` +
      "block root's legitimate work alongside an unidentified dispatch (matches " +
      "hooks/scripts/coder_git_guard.sh's own DF-77 FIX 2 posture for the identical ambiguity). " +
      "If this call actually came from a dispatched agent, its role was NOT enforced by this " +
      "relay -- see agents/coder.md + skills/shepherd/references/flock.md §@coder.",
  };
}

/**
 * The fail-closed verdict `hooks/guard-eval.mjs` emits when role resolution ITSELF is
 * unavailable -- `hooks/scripts/_lib.sh` could not be sourced, or produced no parseable
 * output (`src/dispatch-record.mjs`'s `resolveRole` returning `{kind: "resolution-failed"}`).
 * A DIFFERENT failure than `engineUnavailableVerdict` (the shared predicate engine is
 * unreachable) -- this one never even reaches the engine, because the one fact every engine
 * request needs (`role`) could not be produced at all. Never a silent no-op either.
 *
 * @param {string} detail
 */
export function roleResolutionUnavailableVerdict(detail) {
  return {
    permissionDecision: "deny",
    message: `guard role resolution unavailable, failing closed: ${detail}`,
  };
}

/**
 * The pure decision core behind `hooks/guard-eval.mjs`'s `PreToolUse` handling. Resolves role
 * LOCALLY first (never touching the engine for the no-marker/missing-record cases -- see this
 * module's header), then either short-circuits allow/warn (`missing-record` is a WARN-and-let-
 * through, not a deny -- see the module header's "MISSING-RECORD POSTURE, CORRECTED") or hands
 * back the exact request the executable relay forwards to `shepherd guard eval` -- `payload`
 * preserves the raw hook payload verbatim (this adapter's own long-standing "forward the whole
 * thing, plus `harness`" convention -- see the module header on `stdin (JSON)`) with `role`
 * added/overwritten from the resolution, never trusted from the caller.
 *
 * @param {Record<string, unknown>} rawPayload the parsed `PreToolUse` hook JSON.
 * @param {(toolUseId: string, cwd?: string) => {kind: string, role?: string, toolUseId?: string, detail?: string}} resolveRoleFn
 *   injected so this stays a pure function of its arguments -- `hooks/guard-eval.mjs` passes
 *   the real `resolveRole` from `src/dispatch-record.mjs`.
 * @returns {{kind: "allow"}
 *   |{kind: "missing-record", toolUseId: string}
 *   |{kind: "resolution-failed", detail: string}
 *   |{kind: "request", payload: object}}
 */
export function buildGuardDecision(rawPayload, resolveRoleFn) {
  const payload = rawPayload && typeof rawPayload === "object" ? rawPayload : {};
  const toolUseId = typeof payload.tool_use_id === "string" ? payload.tool_use_id : "";
  const resolution = resolveRoleFn(toolUseId);
  if (resolution.kind === "no-marker") return { kind: "allow" };
  if (resolution.kind === "resolution-failed") return { kind: "resolution-failed", detail: resolution.detail };
  if (resolution.kind === "missing-record") return { kind: "missing-record", toolUseId };
  return { kind: "request", payload: { ...payload, harness: "claude", role: resolution.role } };
}
