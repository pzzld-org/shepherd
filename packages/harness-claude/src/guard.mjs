// Claude hook translation only. Identity and policy are native Rust concerns.

export const GUARD_MATCHER = "Write|Edit|Bash|Agent|Workflow";

import { guardWithComponent } from "../../component-runtime/src/index.mjs";

export function preToolUseDeny(reason) {
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason,
    },
  };
}

export function buildGuardHooksEntry() {
  return {
    matcher: GUARD_MATCHER,
    hooks: [
      {
        type: "command",
        command: "node",
        args: ["${CLAUDE_PLUGIN_ROOT}/packages/harness-claude/hooks/guard-eval.mjs"],
      },
    ],
  };
}

export function buildGuardDecision(rawPayload, resolution) {
  if (
    resolution?.schema !== "shepherd.identity-resolution/1"
    || resolution.harness !== "claude"
    || typeof resolution.role !== "string"
  ) {
    return {
      kind: "identity-error",
      detail: "native identity resolver returned an invalid Claude resolution",
    };
  }
  const payload = rawPayload && typeof rawPayload === "object" ? rawPayload : {};
  return {
    kind: "request",
    payload: {
      harness: "claude",
      role: resolution.role,
      tool_name: payload.tool_name ?? "",
      tool_input: payload.tool_input ?? {},
      tool_use_id: payload.tool_use_id ?? null,
      dispatch: resolution,
    },
  };
}

export function evaluateGuardWithComponent(engine, rawPayload) {
  const payload = rawPayload && typeof rawPayload === "object" ? rawPayload : {};
  return guardWithComponent(engine, {
    tool_name: payload.tool_name ?? "",
    tool_input: payload.tool_input ?? {},
    role: payload.role ?? undefined,
  });
}

export function interpretEngineResult(engineResult) {
  if (engineResult?.decision === "allow") return {};
  if (engineResult?.decision === "deny") {
    const where = engineResult.predicate
      ? ` (${engineResult.predicate}/${engineResult.rule ?? "?"})`
      : "";
    const halt = engineResult.halt_code ? ` [${engineResult.halt_code}]` : "";
    return preToolUseDeny(`guard denied${where}${halt}: ${engineResult.reason ?? "no reason given"}`);
  }
  if (engineResult?.decision === "unresolved") {
    const missing = Array.isArray(engineResult.missing) && engineResult.missing.length > 0
      ? ` (missing: ${engineResult.missing.join(", ")})`
      : "";
    return preToolUseDeny(`guard could not reach a verdict, failing closed${missing}: ${engineResult.reason ?? "no reason given"}`);
  }
  return preToolUseDeny(`guard engine returned an unrecognized verdict: ${JSON.stringify(engineResult)}`);
}

export function engineUnavailableVerdict(detail) {
  return preToolUseDeny(`guard engine unavailable, failing closed: ${detail}`);
}

export function identityUnavailableVerdict(detail) {
  return preToolUseDeny(`native dispatch identity unavailable, failing closed: ${detail}`);
}
