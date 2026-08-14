// packages/harness-claude/src/dispatch-record.mjs -- Claude's role-resolution half of the
// guard relay, closing the W10 auditor's HIGH finding against `src/guard.mjs`'s own header:
// "payload = { ...JSON.parse(raw || "{}"), harness: "claude" };  // no `role` key, ever" --
// which, if wired into `hooks/hooks.json`, would hit the engine's missing-role `unresolved`
// path for EVERY Write/Edit/Bash/Agent/Workflow call from EVERY role, including root's own
// legitimate git operations, and deny project-wide.
//
// UNLIKE `packages/harness-codex/src/dispatch-record.mjs` (this file's own namesake and the
// dispatch brief's named "proven template" for the three-way split), this module does NOT
// build a NEW role-tagging mechanism. A sibling step already shipped Claude's own analog of
// `agent_invocation_tagger.sh` + `current_role()` (`hooks/scripts/agent_invocation_tagger.sh`,
// `hooks/scripts/_lib.sh`, DF-77) before this step ran. Re-deriving that lookup here in JS --
// a second copy of the `tool_use_id` -> `<ns>/dispatch/<sprint>/<tool_use_id>.json`
// correlation -- is exactly the drift risk this wave exists to close ("A second copy of the
// lookup rules WILL drift from the first" -- this step's own brief). So `resolveHookRole`
// below SHELLS OUT to the real `hooks/scripts/_lib.sh`, sourcing it and calling its own
// exported `current_sprint()` / `current_role()` / `resolve_namespace()` verbatim, in ONE bash
// subprocess per guarded call -- mirroring `hooks/scripts/coder_git_guard.sh`'s own
// `SPRINT=$(current_sprint); ROLE=$(current_role "$TOOL_USE_ID" "$SPRINT")` call site, just
// invoked from Node instead of a second bash script.
//
// FIELD RESOLVED FROM: `agent_invocation_tagger.sh`'s PRIMARY signal is
// `tool_input.subagent_type` on a `PreToolUse(Agent|Task)` call (the dispatch-law-mandated
// field `dispatch_guard.sh` already requires present) -- written into a dispatch record's own
// `agent_role` field. `current_role()`, this module's one real dependency, reads that field
// back for a LATER call.
//
// CORRELATION KEY: `tool_use_id` -- the id a dispatching `Agent()`/`Task()` call's own
// `tool_use_id` is recorded under, looked up again by a LATER tool call's OWN `tool_use_id`.
// `_lib.sh`'s own `current_role()` header documents the correlation gap still open (DF-77 FIX
// 3): a `tool_use_id` is minted fresh per tool call, so a coder's later `Bash` call
// structurally never shares the id its own dispatching `Agent()` call was tagged under --
// `current_role()` therefore returns the literal string `"unknown"` for BOTH root's own
// untracked action AND an untraceable dispatched call, by design, today (confirmed against
// that file's own header and `hooks/tests/test_coder_git_guard.sh`'s "untagged" case, which
// asserts exactly that ambiguity resolves to NOT-denied).
//
// `resolveRole` below breaks that tie with ONE extra, narrow signal `current_role()` does not
// itself consult: whether ANY flock dispatch has been tagged in this sprint's dispatch
// directory AT ALL (`hasActiveDispatch` inside `RESOLVE_SCRIPT`, a plain directory-non-empty
// check over the exact directory `agent_invocation_tagger.sh` already writes to -- not a
// second `tool_use_id` correlation of its own; it answers a different, narrower question --
// "has this sprint seen ANY dispatch activity" -- not "who made this specific call", so it
// cannot drift out of step with the real lookup the way a second id-keyed search could). An
// empty/missing dispatch dir means nothing has ever been dispatched in this sprint --
// `current_role()`'s `"unknown"` is presumed to be root's own untracked action, matching
// `coder_git_guard.sh`'s own shipped DF-77 FIX 2 posture: never deny an unresolved role when
// nothing else in the sprint is even correlatable. A non-empty dispatch dir means at least one
// real `Agent()`/`Task()` dispatch WAS tagged somewhere in this sprint, so a marker genuinely
// exists -- but none of the tagged records correlate to THIS call's own `tool_use_id`: the
// DF-75 "marker present, no record" shape, SHAPED like
// `packages/harness-codex/src/dispatch-record.mjs`'s own three-way `resolveRole` (`agentId`
// falsy -> `no-marker`; `agentId` + record -> `resolved`; `agentId` + no record ->
// `missing-record`) -- ported here as the same three outcomes, just keyed on `tool_use_id`
// correlation-into-`current_role()` plus this one directory-presence tiebreak instead of
// Codex's own runtime-assigned `agent_id`. Claude's `PreToolUse` payload carries no verified
// per-caller identity field to use instead -- `_lib.sh`'s own `current_role()` header: "whether
// PreToolUse ALSO carries [agent_id] for a tool call issued from inside an already-running
// subagent could NOT be confirmed here" -- using it anyway would be inventing a second,
// unverified correlation mechanism, exactly what this step's brief forbids ("do not invent a
// second mechanism").
//
// WHERE THE SHAPES DIVERGE: `missing-record` is SHAPED like Codex's own outcome of the same
// name, but is deliberately NOT handled the same way downstream (`src/guard.mjs`'s
// `missingRecordWarnedVerdict`, a WARN, not Codex's `missingRecordDeniedVerdict`, a DENY) --
// see that module's own "MISSING-RECORD POSTURE, CORRECTED" header for the full argument.
// One paragraph of it belongs here too, because this is the module a future reader will reach
// for first when asking "why does hasMarker exist at all": Codex's `agent_id` is assigned ONCE,
// by the Codex runtime, at spawn time, and carried on every later call FROM that spawned agent
// -- so an `agent_id` present with no matching record really does mean "a spawned agent went
// untagged," and an `agent_id` absent really does mean "no spawn is in flight" (root).
// `tool_use_id` has no such property: Claude mints a fresh one per tool call, so the id a
// dispatching `Agent()` call itself carried can never be the id a LATER call from inside that
// dispatch carries (DF-77 FIX 3, open). `hasMarker` therefore cannot answer "did THIS call come
// from a dispatch" the way Codex's `agent_id` presence can -- it can only answer "has ANYTHING
// been dispatched this sprint," which is true for the entire remainder of every real sprint
// from its first dispatch onward. Treating that as grounds to deny is denying root.

import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
// src -> harness-claude -> packages -> repo root (3 ups) -- the same import.meta.url-relative
// pattern `hooks/guard-eval.mjs` already uses to find `bin/shepherd`. `hooks/scripts/_lib.sh`
// lives at the identical repo-root offset: both ship as part of the one shepherd plugin
// install `${CLAUDE_PLUGIN_ROOT}` resolves to, never separately materialized per target
// project (`src/materialize.mjs` only ever writes `content/`-compiled artifacts, never this
// package's own `hooks/`/`src/` sources).
const REPO_ROOT = join(HERE, "..", "..", "..");
const LIB_SH = join(REPO_ROOT, "hooks", "scripts", "_lib.sh");

// One bash subprocess, sourcing the REAL `hooks/scripts/_lib.sh` and calling its OWN exported
// `current_sprint()` / `current_role()` / `resolve_namespace()` -- zero re-derived lookup
// logic. `bash -c SCRIPT $0 $1` binds `$0` to `LIB_SH`, `$1` to the tool_use_id -- the same
// two-argument shape `coder_git_guard.sh`'s own `current_role "$TOOL_USE_ID" "$SPRINT"` call
// site uses. `HAS_MARKER`'s loop (not `ls`, which would print a literal glob and mis-parse
// on a truly empty dir) is the ONE new fact this module adds: does
// `<namespace>/dispatch/<sprint>/` hold any `*.json` record at all.
const RESOLVE_SCRIPT = `
source "$0" 2>/dev/null || exit 3
SPRINT="$(current_sprint)"
ROLE="$(current_role "$1" "$SPRINT")"
NS="$(resolve_namespace)"
DISPATCH_DIR="$NS/dispatch/$SPRINT"
HAS_MARKER=false
if [ -d "$DISPATCH_DIR" ]; then
  for f in "$DISPATCH_DIR"/*.json; do
    [ -e "$f" ] && { HAS_MARKER=true; break; }
  done
fi
emit_json_obj role "$ROLE" has_marker "$HAS_MARKER"
`;

/**
 * Shell out to the real `hooks/scripts/_lib.sh` for exactly the two facts the DF-75 three-way
 * split needs: the resolved role (`current_role()`, untouched) and whether this sprint's
 * dispatch dir carries any tagged record at all (this module's own narrow tiebreak -- see the
 * module header for why that is not a second correlation key).
 *
 * @param {string} toolUseId the CURRENT tool call's own `tool_use_id` (`PreToolUse` payload).
 * @param {string} [cwd] working directory to resolve the target repo/sprint from; defaults to
 *   `process.cwd()` -- the same cwd Claude Code's own hook subprocess runs the guard relay in,
 *   so a linked-worktree dispatch resolves the same namespace `current_role()` itself would.
 * @returns {{role: string, hasMarker: boolean}|null} `null` only when `_lib.sh` itself could
 *   not be sourced or produced no parseable output -- an INFRA failure, never a normal
 *   resolution outcome (`current_role()`'s own contract guarantees it always resolves to SOME
 *   string otherwise: `"conductor"`, `"unknown"`, or a real role).
 */
export function resolveHookRole(toolUseId, cwd = process.cwd()) {
  const result = spawnSync("bash", ["-c", RESOLVE_SCRIPT, LIB_SH, toolUseId ?? ""], { cwd, encoding: "utf8" });
  if (result.error || result.status !== 0 || !result.stdout) return null;
  try {
    const parsed = JSON.parse(result.stdout.trim());
    if (typeof parsed.role !== "string" || !parsed.role) return null;
    return { role: parsed.role, hasMarker: parsed.has_marker === "true" };
  } catch {
    return null;
  }
}

/**
 * The three-way DF-75 split for Claude's own wire shape
 * (`packages/harness-codex/src/dispatch-record.mjs`'s `resolveRole` is the proven template
 * this mirrors -- same three-way SHAPE, same `kind` names; the ACTION each `kind` drives
 * downstream is adapter-specific and deliberately diverges for `missing-record` -- see this
 * module's header, "WHERE THE SHAPES DIVERGE"): an EMPTY `toolUseId` (no tool call in flight --
 * genuinely root, `_lib.sh`'s own documented "conductor" case) always allows without consulting
 * the marker tiebreak; a resolved, non-`"unknown"` role hands back to the engine for real;
 * `"unknown"` defers to `hasMarker` (see module header for why) purely to shape the WARNING
 * this now produces -- never to choose allow vs deny, which no longer differs between the two.
 *
 * Deliberately checks `toolUseId` itself for the "no tool call in flight" case, NOT the
 * string `current_role()` returned: `current_role()` prints the literal `"conductor"` in TWO
 * different situations -- an empty `tool_use_id` (unconditionally, `_lib.sh`'s own first
 * branch), AND a REAL, correctly-tagged dispatch record whose `agent_role` happens to be
 * `"conductor"` (a lane-lead was genuinely dispatched and tagged). Those two cases must NOT
 * collapse here: the first is root, skip the engine entirely; the second is a real dispatch
 * whose git-custody rights are branch-scoped (`content/predicates/git-custody.toml`'s
 * `lane-lead-owns-its-own-branch-only`) and MUST still reach the engine, or a conductor's
 * cross-lane write would silently bypass the very predicate that governs it.
 *
 * @param {string} toolUseId
 * @param {string} [cwd]
 * @returns {{kind: "no-marker"}
 *   |{kind: "resolved", role: string}
 *   |{kind: "missing-record", toolUseId: string}
 *   |{kind: "resolution-failed", detail: string}}
 */
export function resolveRole(toolUseId, cwd = process.cwd()) {
  if (!toolUseId) return { kind: "no-marker" };
  const resolved = resolveHookRole(toolUseId, cwd);
  if (resolved === null) {
    return {
      kind: "resolution-failed",
      detail: "hooks/scripts/_lib.sh could not be sourced (or produced no parseable output) -- role could not be resolved at all",
    };
  }
  const { role, hasMarker } = resolved;
  if (role !== "unknown") return { kind: "resolved", role };
  return hasMarker ? { kind: "missing-record", toolUseId } : { kind: "no-marker" };
}
