// Pi host adapter. Identity, guard policy, and lifecycle planning are owned
// by the generated fl03:shepherd@6.5.6 component.

import { createHash } from "node:crypto";
import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
} from "node:fs";

import {
  compileCanonicalWithComponent,
  componentBinding,
  componentIdentityInput,
  guardWithComponent,
  loadComponent,
  normalizeWithComponent,
  planToNativeDispatch,
  planWithComponent,
  validateNativeExchangeWithComponent,
} from "../../component-runtime/src/index.mjs";
import {
  invokeNativeDispatch,
  nativeShepherdBin,
} from "../../component-runtime/src/native-transport.mjs";

const GUARDED_TOOL_NAMES = new Set(["write", "edit", "bash"]);
const MAX_PRECORRELATION_ATTEMPTS = 3;
const MAX_PRECORRELATION_CANDIDATES = 64;
const MAX_SESSION_HEADER_BYTES = 16_384;
const PROVIDER_REMEDIATION = "Pi subagent provider unavailable. Run `pi install npm:pi-subagents`, then restart Pi.";
const TERMINAL_STOPPED = /(?:^|\n)(?:(?:Error: )?ERROR: |Error: )?dispatch record is terminal: stopped(?:\n|$)/;

export default async function shepherdGuardExtension(pi, options = {}) {
  let component;
  let startupFailure = "";
  try {
    component = await loadComponent(options.componentModule);
  } catch (error) {
    startupFailure = String(error);
  }
  const nativeLauncher = nativeShepherdBin(options.shepherdBin);
  const environment = options.environment ?? process.env;
  const dispatchableRoles = component ? canonicalDispatchableRoles(component) : new Map();
  let childSession = false;
  let managedChild = null;
  let childEnvironmentFailure = "";
  if (environment.PI_SUBAGENT_CHILD === "1") {
    childSession = true;
    try {
      const carrier = childCarrier(environment);
      if (carrier !== null) {
        if (!component) throw new Error(startupFailure || "component unavailable");
        const role = dispatchableRoles.get(carrier);
        if (!role) throw new Error(`canonical profile rejected non-dispatchable child carrier ${carrier}`);
        managedChild = childBinding(environment, carrier, role);
      }
    } catch (error) {
      childEnvironmentFailure = `Pi child environment failed closed: ${formatError(error)}`;
    }
  } else if (environment.PI_SUBAGENT_CHILD !== undefined) {
    childSession = true;
    childEnvironmentFailure = "Pi child environment failed closed: PI_SUBAGENT_CHILD must equal 1";
  }

  const precorrelationCandidates = new Map();
  const terminalPending = new Map();
  const terminalComplete = new Set();
  let providerFailure = PROVIDER_REMEDIATION;
  let terminalFailure = "";
  let managedTerminalPending = false;
  const processHandlers = [];
  const eventUnsubscribers = [];

  const cleanupProcessHandlers = () => {
    for (const [signal, handler] of processHandlers.splice(0)) process.off(signal, handler);
  };

  const stopManagedChild = (context = undefined) => {
    if (!component || managedChild?.revision === undefined || startupFailure) return;
    cleanupProcessHandlers();
    managedTerminalPending = true;
    try {
      const identity = normalizeWithComponent(component, componentIdentityInput({
        harness: "pi",
        event: "SubagentStop",
        sessionId: managedChild.sessionId ?? context?.sessionManager?.getSessionId?.(),
        agentId: managedChild.agentId,
        agentType: managedChild.carrier,
      }));
      const dispatch = planToNativeDispatch(planWithComponent(component, identity, componentBinding({
        role: managedChild.role,
        writeScope: [".shepherd/runs/**"],
        expectedRevision: managedChild.revision,
      })));
      if (!dispatch || dispatch.operation !== "stop") throw new Error("component did not plan Pi child stop");
      const result = invokeNativeDispatch({
        shepherdBin: nativeLauncher,
        operation: dispatch.operation,
        request: dispatch.request,
        cwd: context?.cwd ?? managedChild.cwd,
      });
      if (!result.ok) {
        if (TERMINAL_STOPPED.test(result.detail)) {
          managedChild.revision = undefined;
          managedTerminalPending = false;
          terminalFailure = "";
          return;
        }
        throw new Error(result.detail);
      }
      validateNativeExchangeWithComponent(
        component,
        dispatch.operation,
        dispatch.request,
        nativeExchangeValue(result.value),
      );
      validateStoppedRecord(result.value, managedChild);
      managedChild.revision = undefined;
      managedTerminalPending = false;
      terminalFailure = "";
    } catch (error) {
      terminalFailure = `Pi child shutdown failed closed: ${formatError(error)}`;
      console.error(terminalFailure);
    }
  };

  const resolveObservedTerminal = (terminal, cwd) => {
    const identityInput = terminalIdentityInput(terminal, "PreToolUse");
    const identity = normalizeWithComponent(component, componentIdentityInput(identityInput));
    const resolution = planToNativeDispatch(planWithComponent(component, identity, componentBinding({
      role: terminal.role,
      writeScope: [".shepherd/runs/**"],
    })));
    if (!resolution || resolution.operation !== "resolve") {
      throw new Error("component did not plan Pi terminal identity resolution");
    }
    const resolved = invokeNativeDispatch({
      shepherdBin: nativeLauncher,
      operation: resolution.operation,
      request: resolution.request,
      cwd,
    });
    if (!resolved.ok) {
      if (TERMINAL_STOPPED.test(resolved.detail)) return null;
      throw new Error(resolved.detail);
    }
    validateNativeExchangeWithComponent(
      component,
      resolution.operation,
      resolution.request,
      nativeExchangeValue(resolved.value),
    );
    validateResolvedChild(resolved.value, terminal);
    return positiveSafeInteger(resolved.value.revision) ?? 1;
  };

  const stopObservedTerminal = ({ terminal, cwd, expectedRevision }) => {
    const identity = normalizeWithComponent(
      component,
      componentIdentityInput(terminalIdentityInput(terminal, "SubagentStop")),
    );
    const stop = planToNativeDispatch(planWithComponent(component, identity, componentBinding({
      role: terminal.role,
      writeScope: [".shepherd/runs/**"],
      expectedRevision,
    })));
    if (!stop || stop.operation !== "stop") throw new Error("component did not plan Pi observed child stop");
    const stopped = invokeNativeDispatch({
      shepherdBin: nativeLauncher,
      operation: stop.operation,
      request: stop.request,
      cwd,
    });
    if (!stopped.ok) {
      if (TERMINAL_STOPPED.test(stopped.detail)) return;
      throw new Error(stopped.detail);
    }
    validateNativeExchangeWithComponent(
      component,
      stop.operation,
      stop.request,
      nativeExchangeValue(stopped.value),
    );
    validateStoppedRecord(stopped.value, terminal);
  };

  const retryPendingTerminals = () => {
    for (const [key, pending] of terminalPending) {
      try {
        stopObservedTerminal(pending);
        terminalPending.delete(key);
        terminalComplete.add(key);
      } catch (error) {
        terminalFailure = `Pi observed child shutdown remains pending: ${formatError(error)}`;
      }
    }
    if (terminalPending.size === 0) terminalFailure = "";
  };

  const retryPrecorrelationCandidates = () => {
    for (const [key, candidate] of precorrelationCandidates) {
      if (terminalPending.has(candidate.terminal.agentId) || terminalComplete.has(candidate.terminal.agentId)) {
        precorrelationCandidates.delete(key);
        continue;
      }
      candidate.attempts += 1;
      try {
        const expectedRevision = resolveObservedTerminal(candidate.terminal, candidate.cwd);
        precorrelationCandidates.delete(key);
        if (expectedRevision === null) {
          terminalComplete.add(candidate.terminal.agentId);
          continue;
        }
        if (!terminalPending.has(candidate.terminal.agentId)) {
          terminalPending.set(candidate.terminal.agentId, {
            terminal: candidate.terminal,
            cwd: candidate.cwd,
            expectedRevision,
          });
        }
      } catch {
        if (candidate.attempts >= MAX_PRECORRELATION_ATTEMPTS) precorrelationCandidates.delete(key);
      }
    }
    retryPendingTerminals();
  };

  const observeTerminal = (candidate, cwd = process.cwd()) => {
    if (!component) return;
    try {
      const terminal = terminalChild(candidate, dispatchableRoles);
      if (terminalComplete.has(terminal.agentId) || terminalPending.has(terminal.agentId)) return;
      const key = terminalCandidateKey(terminal);
      if (precorrelationCandidates.has(key)) return;
      if (precorrelationCandidates.size >= MAX_PRECORRELATION_CANDIDATES) {
        precorrelationCandidates.delete(precorrelationCandidates.keys().next().value);
      }
      precorrelationCandidates.set(key, { terminal, cwd, attempts: 0 });
      retryPrecorrelationCandidates();
    } catch {
      // Provider terminal payloads are untrusted. Invalid and unrelated rows do
      // not gain mutation authority and do not poison valid pending work.
    }
  };

  // FAIL CLOSED, DO NOT FAIL THE SESSION. An unbound session may inspect but
  // may not mutate. Throwing here would prevent Pi from opening the session.
  pi.on("session_start", async (event, context) => {
    try {
      const tools = pi.getAllTools();
      if (!Array.isArray(tools)
        || !tools.every((tool) => tool !== null && typeof tool === "object" && typeof tool.name === "string" && tool.name.length > 0)
        || !tools.some((tool) => tool.name === "subagent")) {
        throw new TypeError("Pi getAllTools did not return a configured subagent tool");
      }
      providerFailure = "";
    } catch {
      providerFailure = PROVIDER_REMEDIATION;
      cleanupProcessHandlers();
      return;
    }
    if (!component) {
      startupFailure = `Pi component unavailable: ${startupFailure}`;
      cleanupProcessHandlers();
      return;
    }
    if (childSession && (childEnvironmentFailure || managedChild === null)) {
      startupFailure = childEnvironmentFailure || "non-Shepherd Pi child is not a Shepherd dispatch";
      cleanupProcessHandlers();
      return;
    }
    let identity;
    let dispatch;
    try {
      const child = managedChild !== null;
      identity = normalizeWithComponent(component, componentIdentityInput({
        harness: "pi",
        event: child ? "SubagentStart" : "SessionStart",
        sessionId: context.sessionManager.getSessionId(),
        agentId: child ? managedChild.agentId : undefined,
        agentType: child ? managedChild.carrier : undefined,
      }));
      dispatch = planToNativeDispatch(planWithComponent(
        component,
        identity,
        child ? componentBinding(managedChild.binding) : undefined,
      ));
    } catch (error) {
      startupFailure = `Pi SessionStart planning failed closed: ${formatError(error)}`;
      cleanupProcessHandlers();
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
      validateNativeExchangeWithComponent(
        component,
        dispatch.operation,
        dispatch.request,
        nativeExchangeValue(result.value),
      );
      if (result.value.harness !== "pi" || result.value.session_id !== identity.sessionId) {
        throw new Error("native binding returned another Pi session");
      }
      if (managedChild !== null) {
        if (result.value.agent_id !== managedChild.agentId
          || result.value.agent_type !== managedChild.carrier
          || result.value.role !== managedChild.role
          || result.value.state !== "active"
          || !positiveSafeInteger(result.value.revision)) {
          throw new Error("native child binding returned another Shepherd identity");
        }
        managedChild.revision = result.value.revision;
        managedChild.sessionId = identity.sessionId;
        managedChild.cwd = context.cwd;
        installProcessHandlers();
      }
    } catch (error) {
      cleanupProcessHandlers();
      startupFailure = `Pi SessionStart binding failed closed (${event.reason}): ${formatError(error)}`;
    }
  });

  const installProcessHandlers = () => {
    if (processHandlers.length > 0 || managedChild?.revision === undefined) return;
    const exit = () => {
      cleanupProcessHandlers();
      stopManagedChild();
    };
    processHandlers.push(["exit", exit]);
    process.once("exit", exit);
    for (const signal of ["SIGINT", "SIGTERM"]) {
      const terminate = () => {
        cleanupProcessHandlers();
        stopManagedChild();
        process.kill(process.pid, signal);
      };
      processHandlers.push([signal, terminate]);
      process.once(signal, terminate);
    }
  };

  pi.on("message_end", (event, context) => {
    const message = event.message;
    const hasToolCall = Array.isArray(message?.content)
      && message.content.some((item) => item?.type === "toolCall");
    if (message?.role === "assistant" && message.stopReason === "stop" && !hasToolCall) {
      stopManagedChild(context);
    }
  });
  pi.on("agent_settled", (_event, context) => {
    if (managedChild?.revision !== undefined) stopManagedChild(context);
    retryPrecorrelationCandidates();
  });
  pi.on("tool_result", (event, context) => {
    if (event?.toolName !== "subagent" || event.details?.background === true) return;
    const workflow = event.details?.workflow?.value;
    const entries = Array.isArray(workflow) ? workflow : workflow && typeof workflow === "object" ? [workflow] : [];
    if (entries.length > 0) {
      for (const entry of entries) {
        if (!Array.isArray(entry?.results)) continue;
        for (const result of entry.results) {
          observeTerminal({
            runId: entry?.runId,
            index: result?.index,
            agent: result?.agent,
            sessionFile: result?.sessionFile,
          }, context?.cwd);
        }
      }
      return;
    }
    if (!Array.isArray(event.details?.results)) return;
    for (const result of event.details.results) {
      if (result?.detached === true) continue;
      observeTerminal({
        runId: result?.runId ?? event.details?.runId,
        index: result?.index,
        agent: result?.agent,
        sessionFile: result?.sessionFile,
      }, context?.cwd);
    }
  });

  if (pi.events?.on) {
    eventUnsubscribers.push(pi.events.on("subagent:foreground-complete", (event) => {
      observeTerminal({
        runId: event?.runId,
        index: event?.taskIndex,
        agent: event?.agent,
        sessionFile: event?.sessionFile,
      }, event?.cwd);
    }));
    eventUnsubscribers.push(pi.events.on("subagent:async-complete", (event) => {
      if (!Array.isArray(event?.results)) return;
      for (const result of event.results) {
        observeTerminal({
          runId: result?.runId,
          index: result?.index,
          agent: result?.agent,
          sessionFile: result?.sessionFile ?? result?.sessionPath ?? result?.artifactPaths?.outputPath,
        }, event?.cwd);
      }
    }));
  }

  pi.on("session_shutdown", (_event, context) => {
    if (managedChild?.revision !== undefined) stopManagedChild(context);
    retryPrecorrelationCandidates();
    cleanupProcessHandlers();
    for (const unsubscribe of eventUnsubscribers.splice(0)) unsubscribe();
  });

  pi.on("tool_call", async (event, context) => {
    if (!GUARDED_TOOL_NAMES.has(event.toolName)) return undefined;
    if (providerFailure) return { block: true, reason: providerFailure };
    if (managedTerminalPending) stopManagedChild(context);
    retryPrecorrelationCandidates();
    if (managedTerminalPending || terminalPending.size > 0) {
      return { block: true, reason: terminalFailure || "Pi child terminal lifecycle remains pending" };
    }
    if (startupFailure) return { block: true, reason: startupFailure };
    if (childSession && managedChild === null) {
      return { block: true, reason: childEnvironmentFailure || "non-Shepherd Pi child is not a Shepherd dispatch" };
    }
    if (!component) {
      return { block: true, reason: `guard component unavailable, failing closed: ${startupFailure}` };
    }
    let guardStep = "identity";
    try {
      const sessionId = context?.sessionManager?.getSessionId?.();
      if (typeof sessionId !== "string" || sessionId.length === 0) {
        throw new Error("Pi tool context omitted the native session_id");
      }
      const toolCallId = piToolCallId(event.toolCallId);
      const identity = normalizeWithComponent(component, componentIdentityInput({
        harness: "pi",
        event: "PreToolUse",
        sessionId,
        agentId: managedChild?.agentId,
        agentType: managedChild?.carrier,
        toolUseId: toolCallId,
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
      validateNativeExchangeWithComponent(
        component,
        planned.operation,
        planned.request,
        nativeExchangeValue(resolved.value),
      );
      if (resolved.value.harness !== "pi") throw new Error("native identity resolution returned another harness");
      if (resolved.value.session_id !== sessionId) throw new Error("native identity resolution returned another session");
      if (resolved.value.tool_use_id !== undefined && resolved.value.tool_use_id !== toolCallId) {
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

function canonicalDispatchableRoles(component) {
  const roles = new Map();
  for (const role of compileCanonicalWithComponent(component, "pi").roles) {
    if (role.dispatchable) roles.set(`shepherd:${role.role}`, role);
  }
  return roles;
}

function terminalChild(candidate, dispatchableRoles) {
  const runId = requiredChildIdentifier(candidate?.runId, "terminal runId");
  const index = requiredEventIndex(candidate?.index, "terminal index");
  const carrier = requiredChildIdentifier(candidate?.agent, "terminal agent");
  const role = dispatchableRoles.get(carrier);
  if (!role) throw new TypeError("terminal agent is not a canonical dispatchable Shepherd carrier");
  return {
    runId,
    index,
    carrier,
    role: role.role,
    agentId: childAgentId(runId, index),
    sessionId: childSessionId(candidate?.sessionFile),
  };
}

function terminalIdentityInput(terminal, event) {
  return {
    harness: "pi",
    event,
    sessionId: terminal.sessionId,
    agentId: terminal.agentId,
    agentType: terminal.carrier,
  };
}

function terminalCandidateKey(terminal) {
  return `${terminal.agentId}\0${terminal.carrier}\0${terminal.role}\0${terminal.sessionId}`;
}

function childSessionId(sessionFile) {
  if (typeof sessionFile !== "string" || sessionFile.length === 0 || sessionFile.length > 4_096) {
    throw new TypeError("terminal sessionFile must be a bounded path");
  }
  const before = lstatSync(sessionFile);
  if (!before.isFile() || before.isSymbolicLink()) throw new TypeError("terminal sessionFile must be a regular non-symlink");
  const descriptor = openSync(
    sessionFile,
    constants.O_RDONLY | constants.O_NONBLOCK | (constants.O_NOFOLLOW ?? 0),
  );
  try {
    const after = fstatSync(descriptor);
    if (!after.isFile() || before.dev !== after.dev || before.ino !== after.ino) {
      throw new TypeError("terminal sessionFile changed during validation");
    }
    const buffer = Buffer.alloc(MAX_SESSION_HEADER_BYTES + 1);
    const bytes = readSync(descriptor, buffer, 0, buffer.length, 0);
    const newline = buffer.subarray(0, bytes).indexOf(0x0a);
    const lineBytes = newline === -1 ? bytes : newline;
    if (lineBytes === 0 || lineBytes > MAX_SESSION_HEADER_BYTES || (newline === -1 && bytes > MAX_SESSION_HEADER_BYTES)) {
      throw new TypeError("terminal session header exceeds its bound");
    }
    const header = JSON.parse(buffer.toString("utf8", 0, lineBytes));
    if (header === null || typeof header !== "object" || Array.isArray(header)
      || header.type !== "session" || Object.prototype.hasOwnProperty.call(header, "sessionId")) {
      throw new TypeError("terminal session header is not a Pi session record");
    }
    return requiredChildIdentifier(header.id, "terminal child session id");
  } finally {
    closeSync(descriptor);
  }
}

function childCarrier(environment) {
  const carrier = requiredChildIdentifier(environment.PI_SUBAGENT_CHILD_AGENT, "PI_SUBAGENT_CHILD_AGENT");
  if (!carrier.startsWith("shepherd:")) return null;
  return carrier;
}

function childBinding(environment, carrier, role) {
  const runId = requiredChildIdentifier(environment.PI_SUBAGENT_RUN_ID, "PI_SUBAGENT_RUN_ID");
  const childIndex = requiredChildIndex(environment.PI_SUBAGENT_CHILD_INDEX, "PI_SUBAGENT_CHILD_INDEX");
  const depth = environment.PI_SUBAGENT_PARENT_DEPTH === undefined || environment.PI_SUBAGENT_PARENT_DEPTH === ""
    ? 1
    : requiredChildIndex(environment.PI_SUBAGENT_PARENT_DEPTH, "PI_SUBAGENT_PARENT_DEPTH", 1);
  let parentAgentId;
  if (depth > 1) {
    const ancestry = childAncestry(environment.PI_SUBAGENT_PARENT_PATH, depth, runId, childIndex);
    const parent = ancestry.at(-2);
    parentAgentId = childAgentId(parent.runId, parent.stepIndex);
    if (parentAgentId === childAgentId(runId, childIndex)) throw new TypeError("PI_SUBAGENT_PARENT_PATH identifies the child as its own parent");
  }
  return {
    agentId: childAgentId(runId, childIndex),
    carrier,
    role: role.role,
    binding: {
      role: role.role,
      parentAgentId,
      writeScope: [".shepherd/runs/**"],
      observedCapabilities: [...new Set([...role.capabilities, "subagent-provider"])].sort(),
      capabilitySource: "pi-subagents-child-env",
      harnessVersion: "unknown",
    },
  };
}

function childAncestry(raw, depth, runId, childIndex) {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > 2_048) {
    throw new TypeError("PI_SUBAGENT_PARENT_PATH must be bounded JSON ancestry");
  }
  let ancestry;
  try {
    ancestry = JSON.parse(raw);
  } catch {
    throw new TypeError("PI_SUBAGENT_PARENT_PATH must be valid JSON ancestry");
  }
  if (!Array.isArray(ancestry) || ancestry.length !== depth || ancestry.length < 2 || ancestry.length > 4) {
    throw new TypeError("PI_SUBAGENT_PARENT_PATH is missing or truncated ancestry");
  }
  const validated = ancestry.map((entry, index) => {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      throw new TypeError(`PI_SUBAGENT_PARENT_PATH[${index}] must be an object`);
    }
    return {
      runId: requiredChildIdentifier(entry.runId, `PI_SUBAGENT_PARENT_PATH[${index}].runId`),
      stepIndex: requiredEventIndex(entry.stepIndex, `PI_SUBAGENT_PARENT_PATH[${index}].stepIndex`),
    };
  });
  const child = validated.at(-1);
  if (child.runId !== runId || child.stepIndex !== childIndex) {
    throw new TypeError("PI_SUBAGENT_PARENT_PATH final entry does not match the current child");
  }
  return validated;
}

function childAgentId(runId, childIndex) {
  return `pi-subagent-${createHash("sha256").update(`${runId}\0${childIndex}`).digest("hex")}`;
}

function requiredChildIdentifier(value, name) {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value)) {
    throw new TypeError(`${name} must be a bounded native identifier`);
  }
  return value;
}

function requiredChildIndex(value, name, minimum = 0) {
  if (typeof value !== "string" || !/^(0|[1-9][0-9]{0,8})$/.test(value)) {
    throw new TypeError(`${name} must be a bounded decimal index`);
  }
  const index = Number(value);
  if (index < minimum) throw new TypeError(`${name} must be at least ${minimum}`);
  return index;
}

function requiredEventIndex(value, name) {
  if (!Number.isSafeInteger(value) || value < 0 || value > 999_999_999) {
    throw new TypeError(`${name} must be a bounded non-negative integer`);
  }
  return value;
}

function positiveSafeInteger(value) {
  return Number.isSafeInteger(value) && value > 0 ? value : undefined;
}

function nativeExchangeValue(value) {
  const capabilities = value?.capabilities;
  if (capabilities === null || capabilities === undefined || capabilities.readiness !== undefined) return value;
  if (typeof capabilities !== "object" || Array.isArray(capabilities)) return value;
  const missingRequired = Array.isArray(capabilities.missing_required) ? capabilities.missing_required : [];
  const forbiddenExtra = Array.isArray(capabilities.forbidden_extra) ? capabilities.forbidden_extra : [];
  const missingOptional = Array.isArray(capabilities.missing_optional) ? capabilities.missing_optional : [];
  const readiness = missingRequired.length > 0 || forbiddenExtra.length > 0
    ? "blocked"
    : missingOptional.length > 0 ? "degraded" : "ready";
  return { ...value, capabilities: { ...capabilities, readiness } };
}

function validateResolvedChild(value, child) {
  if (value.harness !== "pi" || value.agent_id !== child.agentId
    || value.agent_type !== child.carrier || value.role !== child.role
    || value.session_id !== child.sessionId) {
    throw new Error("native terminal resolution returned another Shepherd identity");
  }
}

function validateStoppedRecord(value, child) {
  if (value.harness !== "pi" || value.agent_id !== child.agentId
    || value.agent_type !== child.carrier || value.role !== child.role
    || value.session_id !== child.sessionId || value.state !== "stopped"
    || !positiveSafeInteger(value.revision)) {
    throw new Error("native child stop returned another Shepherd identity");
  }
}

function piToolCallId(value) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError("Pi tool call omitted toolCallId");
  return `pi-tool-${createHash("sha256").update(value).digest("hex")}`;
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
