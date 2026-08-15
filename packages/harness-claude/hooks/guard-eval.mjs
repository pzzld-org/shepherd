#!/usr/bin/env node

import { readFileSync } from "node:fs";
import {
  componentBinding,
  guardWithComponent,
  loadComponent,
  planToNativeDispatch,
  planWithComponent,
  validateNativeExchangeWithComponent,
} from "../../component-runtime/src/index.mjs";
import {
  invokeNativeDispatch,
  nativeShepherdBin,
} from "../../component-runtime/src/native-transport.mjs";
import { normalizeClaudeWithComponent } from "../src/identity.mjs";
import { preToolUseDeny } from "../src/guard.mjs";

const nativeLauncher = nativeShepherdBin();

function failClosed(detail) {
  return preToolUseDeny(`Shepherd component unavailable or rejected the request: ${detail}`);
}

async function main() {
  let payload;
  try {
    payload = JSON.parse(readFileSync(0, "utf8") || "{}");
    const engine = await loadComponent();
    const identity = normalizeClaudeWithComponent(payload, engine);
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
    if (typeof resolved.value.role !== "string" || resolved.value.role.length === 0) {
      throw new Error("native dispatch identity resolution did not provide a role");
    }
    const verdict = guardWithComponent(engine, {
      tool_name: payload.tool_name ?? "",
      tool_input: payload.tool_input ?? {},
      role: resolved.value.role,
      dispatch: resolved.value,
    });
    if (verdict.decision === "allow") return;
    console.log(JSON.stringify(preToolUseDeny(verdict.reason ?? "Shepherd component denied the request")));
  } catch (error) {
    console.log(JSON.stringify(failClosed(error?.message ?? error)));
  }
}

main();
