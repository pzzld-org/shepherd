#!/usr/bin/env node

import { readFileSync } from "node:fs";

import {
  componentBinding,
  guardWithComponent,
  loadComponent,
  planToNativeDispatch,
  planWithComponent,
  renderNativeLifecycleContext,
  validateNativeExchangeWithComponent,
} from "../../../component-runtime/src/index.mjs";
import {
  invokeNativeDispatch,
  nativeShepherdBin,
} from "../../../component-runtime/src/native-transport.mjs";
import { normalizeCodexWithComponent } from "../../src/identity.mjs";
import { buildGuardDecision } from "../../src/guard.mjs";
import {
  assertCodexLifecycleSucceeded,
  planCodexLifecycleWithComponent,
} from "../../src/lifecycle.mjs";

const nativeLauncher = nativeShepherdBin();

function emit(value) {
  if (value && Object.keys(value).length > 0) console.log(JSON.stringify(value));
}

function deny(reason) {
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason,
    },
  };
}

function lifecycleContext(event, detail) {
  return {
    hookSpecificOutput: {
      hookEventName: event,
      additionalContext: `[shepherd] ${detail}`,
    },
  };
}

function nativeLifecycleContext(event, additionalContext) {
  return {
    hookSpecificOutput: {
      hookEventName: event,
      additionalContext,
    },
  };
}

async function main() {
  let payload;
  try {
    payload = JSON.parse(readFileSync(0, "utf8") || "{}");
  } catch (error) {
    emit(deny(`invalid hook input: ${error.message}`));
    return;
  }

  let engine;
  try {
    engine = await loadComponent();
  } catch (error) {
    emit(deny(`component unavailable, failing closed: ${error.message}`));
    return;
  }

  const event = payload.hook_event_name;
  if (["SessionStart", "SubagentStart", "SubagentResume", "SubagentStop"].includes(event)) {
    try {
      const { plan } = planCodexLifecycleWithComponent(payload, engine, payload.shepherd_dispatch);
      const dispatch = planToNativeDispatch(plan);
      if (dispatch === null) return;
      const result = invokeNativeDispatch({
        shepherdBin: nativeLauncher,
        operation: dispatch.operation,
        request: dispatch.request,
      });
      if (!result.ok) {
        emit(lifecycleContext(event, result.detail));
        return;
      }
      validateNativeExchangeWithComponent(engine, dispatch.operation, dispatch.request, result.value);
      assertCodexLifecycleSucceeded(dispatch.operation, result.value);
      const additionalContext = renderNativeLifecycleContext(dispatch.operation, result.value);
      if (additionalContext) emit(nativeLifecycleContext(event, additionalContext));
    } catch (error) {
      emit(lifecycleContext(event, `component rejected lifecycle: ${error.message ?? error}`));
    }
    return;
  }
  if (event !== "PreToolUse") return;

  try {
    const identity = normalizeCodexWithComponent(payload, engine);
    const planned = planToNativeDispatch(planWithComponent(
      engine,
      identity,
      payload.shepherd_dispatch === undefined ? undefined : componentBinding(payload.shepherd_dispatch),
    ));
    if (!planned || planned.operation !== "resolve") throw new Error("component did not plan PreToolUse resolution");
    const resolved = invokeNativeDispatch({
      shepherdBin: nativeLauncher,
      operation: planned.operation,
      request: planned.request,
    });
    if (!resolved.ok) throw new Error(resolved.detail);
    validateNativeExchangeWithComponent(engine, "resolve", planned.request, resolved.value);
    const decision = buildGuardDecision(payload, resolved.value);
    if (decision.kind !== "request") {
      throw new Error(decision.detail);
    }
    const verdict = guardWithComponent(engine, {
      tool_name: decision.payload.tool_name,
      tool_input: decision.payload.tool_input,
      role: decision.payload.role,
      dispatch: decision.payload.dispatch,
    });
    if (verdict.decision === "allow") return;
    emit(deny(verdict.reason ?? "component denied the request"));
  } catch (error) {
    emit(deny(`component rejected identity or guard request: ${error.message ?? error}`));
  }
}

main();
