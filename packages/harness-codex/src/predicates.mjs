// packages/harness-codex/src/predicates.mjs -- interprets content/predicates/*.toml, the
// declarative guard-predicate spec plan.md's W4-S4/S5/S6 block says a "Rust engine" and Pi's
// TS layer both read (decision 2: shared data, ONE interpreter's worth of logic per harness).
//
// NAMED GAP, not a silently-degraded emission: crates/** carries no guard/predicate CLI verb
// yet (verified -- crates/cli/src/cmd.rs has exactly one subcommand, `init`; there is no
// `shepherd guard`/`shepherd predicate` to shell out to), and crates/** is outside this
// coder's file scope regardless. Codex's real native hook system (confirmed live:
// `~/.codex/config.toml`'s `hooks=stable,true`, and the installed `codex-shepherd@1.0.2`
// bundle's own `hooks/hooks.json` -- same PreToolUse/matcher/`{permissionDecision}` JSON
// contract Claude's `hooks/scripts/_lib.sh` already uses) needs SOMETHING to call today, so
// this module is a Codex-local interim interpreter of the SAME `content/predicates/*.toml`
// source Pi's W4-S6 will also read -- the SPEC is not duplicated (decision 2's actual
// requirement), only its evaluation is temporarily local instead of routed through the
// not-yet-built Rust engine. Once that engine exists, `evaluate()`'s call sites in
// `hooks/scripts/shepherd_guard.mjs` become a thin subprocess wrapper with this same shape.
//
// FINDING against content/predicates/write-boundary.toml (see `EFFECT_HANDLERS.deny_if_false`
// below): its rule 1 reads "denied outright" for `write_eligible: false`, but the file's own
// `discovery-writes-its-one-declared-output-path` example pairs `write_eligible: false` with
// `path_in_dispatch_write_scope: true` and asserts `result = "allow"` -- a literal outright
// reading fails that example. Resolved by reading `path_in_dispatch_write_scope` as the
// decisive signal (RECONCILIATION.md §`write_eligible`'s own words: a false `write_eligible`
// plus a narrow in-scope grant is "one fact, not a contradiction"), verified against all five
// of that file's worked examples in test/predicates.test.mjs -- flagging for content/'s own
// authors (W0-S8) since a generic reader should not have to special-case one rule's wording.

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parsePredicateToml } from "./toml-lite.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_CONTENT_DIR = join(HERE, "..", "..", "..", "content");

// The two role ids content/predicates/dispatch-scope.toml's own rule description names
// verbatim: "the plan-author (engineer) or gating (critic) roles." Not derivable from
// content/roles/*.md's fields (no `role_function:` key exists) -- test/predicates.test.mjs
// asserts both ids stay present in the loaded flock as a drift tripwire.
const PLAN_OR_GATE_ROLES = Object.freeze(new Set(["engineer", "critic"]));

const EFFECT_HANDLERS = Object.freeze({
  deny_if_false: (ctx) => ctx.write_eligible === false && ctx.path_in_dispatch_write_scope !== true,
  deny_if_path_outside_scope: (ctx) => ctx.path_in_dispatch_write_scope === false,
  allow_if_no_hit: () => false, // documentary: no-hit is the default-allow, not a deny trigger
  deny_if_hit_without_justification: (ctx) => ctx.dedup_hit === true && ctx.justification_present !== true,
  deny_if_target_outside_flock: (ctx, env) =>
    typeof ctx.target_role === "string" && !env.flockRoles.has(ctx.target_role),
  deny_if_dispatcher_is_lane_lead_and_target_is_plan_or_gate_role: (ctx, env) =>
    ctx.dispatcher_tier === "lane-lead" && env.planOrGateRoles.has(ctx.target_role),
  deny_if_dispatcher_is_implementer: (ctx) => ctx.dispatcher_tier === "implementer",
  deny_if_role_is_implementer: (ctx) => ctx.role_tier === "implementer",
  deny_if_branch_outside_own_lane: (ctx) => ctx.is_own_lane_branch === false,
  deny_unless_root: (ctx) => ctx.role_tier !== "root",
});

/**
 * @param {string} [contentDir] absolute path to `content/`; defaults to the real tree.
 * @returns {Map<string, import("./toml-lite.mjs").TomlDoc>} keyed by `predicate.id`.
 */
export function loadPredicates(contentDir = DEFAULT_CONTENT_DIR) {
  const dir = join(contentDir, "predicates");
  const byId = new Map();
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".toml")).sort()) {
    const doc = parsePredicateToml(readFileSync(join(dir, file), "utf8"));
    if (!doc.predicate.id) {
      throw new Error(`${file}: missing [predicate].id`);
    }
    byId.set(doc.predicate.id, doc);
  }
  return byId;
}

/**
 * @param {string[]} flockRoleIds every dispatchable `content/roles/*.md` `role:` id.
 * @returns {{flockRoles: Set<string>, planOrGateRoles: Set<string>}}
 */
export function buildEnv(flockRoleIds) {
  return { flockRoles: new Set(flockRoleIds), planOrGateRoles: PLAN_OR_GATE_ROLES };
}

/**
 * @param {string} predicateId e.g. `"write-boundary"`.
 * @param {string} action the rule-scoping action, e.g. `"fs.write"`, `"dispatch"`,
 *   `"vcs.write"`, `"vcs.integrate"` -- only rules whose own `action` matches are evaluated
 *   (content/predicates/git-custody.toml scopes 2 of its 3 rules to `vcs.write` and the third
 *   to `vcs.integrate`; evaluating all 3 unconditionally would double-apply a `vcs.write`-only
 *   rule to a `vcs.integrate` request).
 * @param {Record<string, unknown>} context flattened example/dispatch fields.
 * @param {Map<string, import("./toml-lite.mjs").TomlDoc>} predicates from `loadPredicates()`.
 * @param {{flockRoles: Set<string>, planOrGateRoles: Set<string>}} env from `buildEnv()`.
 * @returns {{result: "allow"|"deny", firedRuleIds: string[]}}
 */
export function evaluate(predicateId, action, context, predicates, env) {
  const doc = predicates.get(predicateId);
  if (!doc) throw new Error(`predicates.mjs: no such predicate \`${predicateId}\``);

  const applicable = doc.rule.filter((rule) => rule.action === action);
  if (applicable.length === 0) {
    throw new Error(`predicates.mjs: predicate \`${predicateId}\` has no rule scoped to action \`${action}\``);
  }

  const fired = applicable.filter((rule) => {
    const handler = EFFECT_HANDLERS[rule.effect];
    if (!handler) {
      throw new Error(`predicates.mjs: no handler for effect \`${rule.effect}\` (predicate \`${predicateId}\`, rule \`${rule.id}\`)`);
    }
    return handler(context, env);
  });

  return fired.length === 0
    ? { result: "allow", firedRuleIds: [] }
    : { result: "deny", firedRuleIds: fired.map((rule) => rule.id) };
}
