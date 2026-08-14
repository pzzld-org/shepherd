// packages/harness-pi/src/guard.ts -- the pure predicate interpreter: evaluates one
// content/predicates/*.toml rule set against a concrete (role, action, context) tuple. This
// is Pi's second real interpreter of the shared guard-predicate spec (decision 1,
// discovery-d1-harness.md), kept in lockstep with the spec by replaying every
// content/predicates/*.toml `[[example]]` directly (test/guard-predicates.test.mjs), never a
// hand-copied fixture list. Four sub-evaluators, one per predicate id -- verified against
// every allow/deny example in the corpus, not just the happy path.
//
// dedup-gate is implemented and tested here but deliberately NOT wired into
// src/extension.ts's pi.on('tool_call', ...) handler -- see that file's header for why
// (the tool_call event carries no resolved symbol name or registry hit).

import { PLAN_OR_GATE_TARGET_ROLES, ROLE_TIER } from "./roles.mjs";

export type PredicateId = "dedup-gate" | "dispatch-scope" | "git-custody" | "write-boundary";

export interface GuardCheck {
  predicateId: PredicateId;
  role: string;
  action: string;
  context: Record<string, unknown>;
}

export interface GuardVerdict {
  allow: boolean;
  haltCode?: string;
  reason: string;
}

export interface RoleFact {
  writeEligible: boolean;
  capabilities: string[];
}

export function evaluate(check: GuardCheck, roleFacts: Map<string, RoleFact>): GuardVerdict {
  switch (check.predicateId) {
    case "dedup-gate":
      return evalDedupGate(check.context);
    case "dispatch-scope":
      return evalDispatchScope(check.role, check.action, check.context);
    case "git-custody":
      return evalGitCustody(check.role, check.action, check.context);
    case "write-boundary":
      return evalWriteBoundary(check.role, check.context, roleFacts);
    default:
      return { allow: false, reason: `unknown predicate \`${check.predicateId}\`` };
  }
}

// content/predicates/dedup-gate.toml
function evalDedupGate(context: Record<string, unknown>): GuardVerdict {
  const hit = Boolean(context.dedup_hit);
  if (!hit) return { allow: true, reason: "no dedup hit in the registry corpus" };
  if (context.justification_present) {
    return { allow: true, reason: "dedup hit, but a JUSTIFY-NEW block is present" };
  }
  return { allow: false, haltCode: "DEDUP-HIT", reason: "dedup hit with no justification" };
}

// content/predicates/dispatch-scope.toml
function evalDispatchScope(role: string, _action: string, context: Record<string, unknown>): GuardVerdict {
  const targetRole = String(context.target_role ?? "");
  if (!(targetRole in ROLE_TIER)) {
    return { allow: false, haltCode: "DISPATCH-OFF-FLOCK", reason: "target role outside the closed nine-role flock" };
  }
  const dispatcherTier = String(context.dispatcher_tier ?? ROLE_TIER[role as keyof typeof ROLE_TIER] ?? "");
  if (dispatcherTier === "implementer") {
    return { allow: false, reason: "implementer roles never dispatch" };
  }
  if (dispatcherTier === "lane-lead" && PLAN_OR_GATE_TARGET_ROLES.has(targetRole)) {
    return { allow: false, haltCode: "WRONG-TIER-DISPATCH", reason: "lane-lead may not dispatch plan-authorship/gating roles" };
  }
  return { allow: true, reason: "dispatch within the closed flock and this dispatcher's tier reach" };
}

// content/predicates/git-custody.toml
function evalGitCustody(role: string, action: string, context: Record<string, unknown>): GuardVerdict {
  const tier = String(context.role_tier ?? ROLE_TIER[role as keyof typeof ROLE_TIER] ?? "");
  if (action === "vcs.write") {
    if (tier === "implementer") {
      return { allow: false, haltCode: "CODER-GIT-WRITE", reason: "implementer roles never perform a version-control write" };
    }
    if (context.is_own_lane_branch === false) {
      return { allow: false, haltCode: "TEAMMATE-GIT-WRITE", reason: "lane-lead wrote outside its own lane branch" };
    }
    return { allow: true, reason: "lane-lead writing its own lane branch" };
  }
  if (action === "vcs.integrate") {
    if (tier !== "root") {
      return { allow: false, haltCode: "TEAMMATE-GIT-WRITE", reason: "cross-lane integration is root-exclusive" };
    }
    return { allow: true, reason: "root performing cross-lane integration" };
  }
  return { allow: false, reason: `unrecognized git-custody action \`${action}\`` };
}

// content/predicates/write-boundary.toml
function evalWriteBoundary(role: string, context: Record<string, unknown>, roleFacts: Map<string, RoleFact>): GuardVerdict {
  if (context.path_in_dispatch_write_scope === true) {
    return { allow: true, reason: "target path within this dispatch's declared write_scope" };
  }
  const writeEligible = context.write_eligible === true;
  if (writeEligible) {
    return { allow: false, haltCode: "SCOPE OVERFLOW", reason: "write_eligible role wrote outside its declared file scope" };
  }
  // A write_eligible=false role MAY still hold the narrow `report-write` capability
  // (RECONCILIATION.md §write_eligible -- "one fact, not a contradiction"); only that
  // sub-case gets the specific report-path halt code, matching the corpus exactly.
  const capabilities = roleFacts.get(role)?.capabilities ?? [];
  if (capabilities.includes("report-write")) {
    return { allow: false, haltCode: "DISCOVERY-WRITE-PATH", reason: "report-write role missed its one declared output path" };
  }
  return { allow: false, reason: "role holds no write capability at all" };
}
