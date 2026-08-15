// Codex hook translation only. Identity and policy are native Rust concerns.

import { guardWithComponent } from "../../component-runtime/src/index.mjs";

function deny(reason) {
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason,
    },
  };
}

export function buildGuardDecision(rawPayload, resolution) {
  if (
    resolution?.schema !== "shepherd.identity-resolution/1"
    || resolution.harness !== "codex"
    || typeof resolution.role !== "string"
    || resolution.role.length === 0
  ) {
    return {
      kind: "identity-error",
      detail: "native identity resolver returned an invalid Codex resolution",
    };
  }
  const payload = rawPayload && typeof rawPayload === "object" ? rawPayload : {};
  return {
    kind: "request",
    payload: {
      harness: "codex",
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
    const halt = engineResult.halt_code ? `[${engineResult.halt_code}] ` : "";
    return deny(`${halt}guard denied${where}: ${engineResult.reason ?? "no reason given"}`);
  }
  if (engineResult?.decision === "unresolved") {
    return deny(`guard could not reach a verdict, failing closed: ${engineResult.reason ?? "no reason given"}`);
  }
  return deny(`guard engine returned an unrecognized verdict: ${JSON.stringify(engineResult)}`);
}

export function engineUnavailableVerdict(detail) {
  return deny(`guard engine unavailable, failing closed: ${detail}`);
}

export function identityUnavailableVerdict(detail) {
  return deny(`native dispatch identity unavailable, failing closed: ${detail}`);
}
