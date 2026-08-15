#!/usr/bin/env node

import { readFileSync } from "node:fs";

import {
  loadComponent,
  planToNativeDispatch,
  renderNativeLifecycleContext,
  validateNativeExchangeWithComponent,
} from "../../component-runtime/src/index.mjs";
import {
  invokeNativeDispatch,
  nativeShepherdBin,
} from "../../component-runtime/src/native-transport.mjs";
import {
  assertClaudeLifecycleSucceeded,
  planClaudeLifecycleWithComponent,
} from "../src/lifecycle.mjs";

const shepherdBin = nativeShepherdBin();

function context(event, detail) {
  return {
    hookSpecificOutput: {
      hookEventName: event,
      additionalContext: `[shepherd] ${detail}`,
    },
  };
}

function nativeContext(event, additionalContext) {
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
    console.log(JSON.stringify(context("SubagentStart", `invalid lifecycle input: ${error.message}`)));
    return;
  }
  try {
    const engine = await loadComponent();
    const { plan } = planClaudeLifecycleWithComponent(payload, engine, payload.shepherd_dispatch);
    const dispatch = planToNativeDispatch(plan);
    if (dispatch === null) return;
    const result = invokeNativeDispatch({
      shepherdBin,
      operation: dispatch.operation,
      request: dispatch.request,
    });
    if (!result.ok) {
      console.log(JSON.stringify(context(payload.hook_event_name, result.detail)));
      return;
    }
    validateNativeExchangeWithComponent(engine, dispatch.operation, dispatch.request, result.value);
    assertClaudeLifecycleSucceeded(dispatch.operation, result.value);
    const additionalContext = renderNativeLifecycleContext(dispatch.operation, result.value);
    if (additionalContext) {
      console.log(JSON.stringify(nativeContext(payload.hook_event_name, additionalContext)));
    }
  } catch (error) {
    console.log(JSON.stringify(context(
      payload.hook_event_name ?? "SubagentStart",
      `component rejected lifecycle: ${error.message ?? error}`,
    )));
  }
}

main();
