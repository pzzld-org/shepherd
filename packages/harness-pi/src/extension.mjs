// Pi host adapter. Identity, guard policy, and lifecycle planning are owned
// by the generated fl03:shepherd@6.5.6 component.

import {
  componentBinding,
  componentIdentityInput,
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
import { normalizeWithComponent } from "../../component-runtime/src/index.mjs";

const GUARDED_TOOL_NAMES = new Set(["write", "edit", "bash"]);

export default async function shepherdGuardExtension(pi, options = {}) {
  let component;
  let startupFailure = "";
  try {
    component = await loadComponent(options.componentModule);
  } catch (error) {
    startupFailure = String(error);
  }
  const nativeLauncher = nativeShepherdBin(options.shepherdBin);

  // FAIL CLOSED, DO NOT FAIL THE SESSION. A binding failure here used to
  // rethrow, which Pi surfaces as an extension error during bindExtensions and
  // which prevents the session from initializing AT ALL -- one unreadable
  // run.json in a project made Pi unusable in that directory.
  //
  // Shepherd's contract is that an unbound session may not MUTATE, not that the
  // host may not run. The other two harnesses already behave this way: the
  // Claude path returns additionalContext on SessionStart and reserves `deny`
  // for PreToolUse. The guard below already denies every write, edit and bash
  // call while `startupFailure` is set, so recording the failure preserves the
  // fail-closed property without taking the session down with it.
  pi.on("session_start", async (event, context) => {
    if (!component) {
      startupFailure = `Pi component unavailable: ${startupFailure}`;
      return;
    }
    let identity;
    let dispatch;
    try {
      identity = normalizeWithComponent(component, componentIdentityInput({
        harness: "pi",
        event: "SessionStart",
        sessionId: context.sessionManager.getSessionId(),
      }));
      dispatch = planToNativeDispatch(planWithComponent(component, identity));
    } catch (error) {
      // Identity normalization and lifecycle planning are as fatal to the
      // session as the dispatch itself if they escape. Same rule applies.
      startupFailure = `Pi SessionStart planning failed closed: ${String(error)}`;
      return;
    }
    if (dispatch === null) return;
    try {
      const result = invokeNativeDispatch({
        shepherdBin: nativeLauncher,
        operation: dispatch.operation,
        request: dispatch.request,
        cwd: context.cwd,
      });
      if (!result.ok) throw new Error(result.detail);
      validateNativeExchangeWithComponent(component, dispatch.operation, dispatch.request, result.value);
      if (result.value.harness !== "pi" || result.value.session_id !== identity.sessionId) {
        throw new Error("native root binding returned another Pi session");
      }
    } catch (error) {
      startupFailure = `Pi SessionStart binding failed closed (${event.reason}): ${String(error)}`;
      // Deliberately not rethrown. See the note above this handler.
    }
  });

  pi.on("session_shutdown", () => undefined);
  pi.on("tool_call", async (event, context) => {
    if (!GUARDED_TOOL_NAMES.has(event.toolName)) return undefined;
    if (!component) {
      return { block: true, reason: `guard component unavailable, failing closed: ${startupFailure}` };
    }
    let guardStep = "identity";
    try {
      const sessionId = context?.sessionManager?.getSessionId?.();
      if (typeof sessionId !== "string" || sessionId.length === 0) {
        throw new Error("Pi tool context omitted the native session_id");
      }
      const identity = normalizeWithComponent(component, componentIdentityInput({
        harness: "pi",
        event: "PreToolUse",
        sessionId,
        toolUseId: event.toolCallId,
      }));
      guardStep = "plan";
      const planned = planToNativeDispatch(planWithComponent(component, identity, componentBinding({
        writeScope: ["**"],
        toolName: nativeToolName(event.toolName),
        toolInput: nativeToolInput(event),
      })));
      if (!planned || planned.operation !== "resolve") {
        throw new Error("component did not plan Pi PreToolUse resolution");
      }
      const resolved = invokeNativeDispatch({
        shepherdBin: nativeLauncher,
        operation: planned.operation,
        request: planned.request,
        cwd: context?.cwd,
      });
      if (!resolved.ok) throw new Error(resolved.detail);
      guardStep = "response";
      validateNativeExchangeWithComponent(component, planned.operation, planned.request, resolved.value);
      if (resolved.value.harness !== "pi") {
        throw new Error("native identity resolution returned another harness");
      }
      if (resolved.value.session_id !== sessionId) {
        throw new Error("native identity resolution returned another session");
      }
      if (resolved.value.tool_use_id !== undefined && resolved.value.tool_use_id !== event.toolCallId) {
        throw new Error("native identity resolution returned another tool call");
      }
      if (typeof resolved.value.role !== "string" || resolved.value.role.length === 0) {
        throw new Error("native dispatch identity resolution did not provide a role");
      }
      const verdict = guardWithComponent(component, {
        tool_name: nativeToolName(event.toolName),
        tool_input: event.input,
        role: resolved.value.role,
        dispatch: resolved.value,
      });
      if (verdict.decision !== "allow") {
        return { block: true, reason: verdict.reason ?? "component denied the request" };
      }
    } catch (error) {
      return { block: true, reason: `Pi component rejected identity or guard request (${guardStep}): ${formatError(error)}` };
    }
    return undefined;
  });
}

function nativeToolName(toolName) {
  if (toolName === "write") return "Write";
  if (toolName === "edit") return "Edit";
  if (toolName === "bash") return "Bash";
  return toolName;
}

function nativeToolInput(event) {
  if (event.toolName === "bash") return { command: event.input?.command };
  if (event.toolName === "write" || event.toolName === "edit") {
    return { path: event.input?.path, operation: nativeToolName(event.toolName) };
  }
  return {};
}

function formatError(error) {
  if (error?.payload !== undefined) {
    try { return JSON.stringify(error.payload); } catch { /* fall through */ }
  }
  return String(error);
}
