// packages/harness-codex/src/guard.mjs -- the pure decision core behind
// hooks/scripts/shepherd_guard.mjs. Separated from stdio so it is directly unit-testable
// (test/guard.test.mjs) without spawning a subprocess, mirroring why
// packages/compiler/src/compile.mjs and packages/compiler/bin/compile.mjs are two files.
//
// NAMED GAP (read before extending this module): Claude's `current_role()`
// (hooks/scripts/_lib.sh) resolves the acting role from a dispatch record
// `agent_invocation_tagger.sh` writes on every `Agent()` call. Codex has no analogous
// tagger for `spawn_agent`/`collaborationspawn_agent` -- building one is `spawn_agent`
// interception work, squarely W4-S1's "auto-wire the launcher" concern (or a dedicated
// follow-up), not this adapter's file scope. `decideForToolCall` therefore trusts a
// `SHEPHERD_ROLE` environment variable as the interim role signal; an unset/unknown role
// fails OPEN (returns `allow`), matching every existing Claude-side guard's own posture for
// a dispatch it cannot identify (`hooks/scripts/coder_git_guard.sh`: "Non-coder turns fail
// open"). The same applies to `path_in_dispatch_write_scope`: this adapter has no Codex-side
// reader of the CURRENT dispatch's declared file scope, so it is left `undefined` --
// `EFFECT_HANDLERS.deny_if_false` (predicates.mjs) then denies a `write_eligible: false`
// role's write by default (fail-closed, the safe direction) and allows a `write_eligible:
// true` role's write (fail-open, since per-path scope enforcement is not yet wired). Both
// gaps close together once a Codex-side dispatch-record writer exists.

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadRoles } from "../../compiler/src/content.mjs";
import { buildEnv, evaluate, loadPredicates } from "./predicates.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_CONTENT_DIR = join(HERE, "..", "..", "..", "content");

/** content/predicates/dispatch-scope.toml + git-custody.toml's own `role` tiering, as
 * evidenced by their examples (`shepherd` -> root, `conductor` -> lane-lead, the five
 * implementer roles -> implementer). `engineer`/`planter` never appear as a `role` in any
 * example across the four predicate files, so they are deliberately left unmapped rather
 * than guessed -- `decideForToolCall` fails open for them, same as an unknown role. */
const ROLE_TIER = Object.freeze({
  shepherd: "root",
  conductor: "lane-lead",
  coder: "implementer",
  worker: "implementer",
  discovery: "implementer",
  auditor: "implementer",
  critic: "implementer",
});

// git subcommands git-custody.toml's `vcs.integrate` action governs; everything else a git
// invocation reaches is `vcs.write` (mirrors hooks/scripts/coder_git_guard.sh's own verb
// split, narrowed to the two this predicate's rules actually distinguish).
const INTEGRATE_VERBS = Object.freeze(new Set(["merge", "rebase", "cherry-pick"]));

// Read-only git subcommands never reach git-custody at all -- hooks/scripts/coder_git_guard.sh's
// own READONLY_GIT_VERBS allowlist, ported directly (that script is the enforced Claude-side
// behavior this predicate already governs; a `git status` is not a `vcs.write`/`vcs.integrate`
// attempt under either harness).
const READONLY_GIT_VERBS = Object.freeze(
  new Set(
    "status diff log show rev-parse ls-files ls-tree cat-file blame show-ref rev-list merge-base describe shortlog for-each-ref name-rev diff-tree diff-index grep var whatchanged count-objects show-branch cherry version help".split(
      " "
    )
  )
);

// git global options that consume a SEPARATE following token (coder_git_guard.sh's own
// `takes_arg` set) -- without this, `git -C x commit` would misparse `x` as the subcommand.
const GIT_OPTS_TAKING_ARG = new Set(["-C", "-c", "--git-dir", "--work-tree", "--namespace"]);

/**
 * @param {string} command a Bash tool_input.command string.
 * @returns {string[]} every top-level `git <subcommand>` found, lowercased. A single-pass,
 *   non-recursive port of coder_git_guard.sh's tokenizer (that script's own Layer 2 raw scan
 *   is the documented fallback for exactly this simpler shape) -- sufficient to classify
 *   `vcs.write` vs `vcs.integrate`, not a full shell-injection audit.
 */
export function extractGitSubcommands(command) {
  const tokens = command.split(/\s+/).filter(Boolean);
  const verbs = [];
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].replace(/^.*\//, "") !== "git") continue;
    let j = i + 1;
    while (j < tokens.length) {
      const opt = tokens[j];
      if (GIT_OPTS_TAKING_ARG.has(opt)) {
        j += 2;
        continue;
      }
      if (opt.startsWith("-")) {
        j += 1;
        continue;
      }
      verbs.push(opt.toLowerCase().replace(/[;&|].*$/, ""));
      break;
    }
    i = j;
  }
  return verbs.filter(Boolean);
}

/**
 * @param {{toolName: string, toolInput?: Record<string, unknown>, role?: string, contentDir?: string}} call
 * @returns {{result: "allow"|"deny", predicateId?: string, firedRuleIds?: string[]}}
 */
export function decideForToolCall(call) {
  const role = call.role;
  if (!role) return { result: "allow" }; // no role signal -- fail open, see module header

  const contentDir = call.contentDir ?? DEFAULT_CONTENT_DIR;
  const predicates = loadPredicates(contentDir);
  const roles = loadRoles(contentDir);
  const roleRecord = roles.find((r) => r.role === role);
  if (!roleRecord) return { result: "allow" }; // unrecognized role id -- fail open

  const env = buildEnv(roles.map((r) => r.role));

  if (call.toolName === "apply_patch") {
    const decision = evaluate(
      "write-boundary",
      "fs.write",
      { write_eligible: roleRecord.writeEligible, path_in_dispatch_write_scope: undefined },
      predicates,
      env
    );
    return { predicateId: "write-boundary", ...decision };
  }

  if (call.toolName === "Bash") {
    const verbs = extractGitSubcommands(String(call.toolInput?.command ?? ""));
    const writeVerbs = verbs.filter((v) => !READONLY_GIT_VERBS.has(v));
    if (writeVerbs.length === 0) return { result: "allow" };
    const roleTier = ROLE_TIER[role];
    if (!roleTier) return { result: "allow" }; // unclassified tier -- fail open, see module header
    const action = writeVerbs.some((v) => INTEGRATE_VERBS.has(v)) ? "vcs.integrate" : "vcs.write";
    const decision = evaluate("git-custody", action, { role_tier: roleTier, is_own_lane_branch: undefined }, predicates, env);
    return { predicateId: "git-custody", ...decision };
  }

  return { result: "allow" };
}
