import {
  accessSync,
  constants,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const COMPONENT_CONTRACT_VERSION = "fl03:shepherd@6.5.0";
export const COMPONENT_MODULE_ENV = "SHEPHERD_COMPONENT_MODULE";
export const DEFAULT_COMPONENT_MODULE = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "runtime",
  "shepherd-component.js",
);

/**
 * Loads a jco-generated ESM module from an operator-selected path. The module
 * and its adjacent core Wasm are distribution artifacts, never repository
 * inputs. No registry lookup, npm invocation, or source-code fallback exists.
 */
export async function loadComponent(modulePath = process.env[COMPONENT_MODULE_ENV] ?? DEFAULT_COMPONENT_MODULE) {
  if (typeof modulePath !== "string" || modulePath.length === 0) {
    throw new ComponentRuntimeError(
      "component_unavailable",
      `${COMPONENT_MODULE_ENV} must point to the generated Shepherd component module or the packaged adjacent runtime must exist`,
    );
  }
  try {
    accessSync(modulePath, constants.R_OK);
  } catch (error) {
    throw new ComponentRuntimeError("component_unavailable", `component module is unreadable: ${error.message}`);
  }
  const loaded = await import(pathToFileURL(modulePath).href);
  const engine = loaded.engine ?? loaded.default?.engine;
  return requireEngine(engine);
}

export function requireEngine(engine) {
  if (engine === null || typeof engine !== "object") {
    throw new ComponentRuntimeError("component_invalid", "generated module did not export engine");
  }
  for (const method of [
    "canonicalProfile",
    "compileCanonical",
    "measure",
    "guardEvalCanonical",
    "normalizeIdentity",
    "planLifecycle",
    "evaluateProvider",
    "validateResponse",
    "validateNativeResponse",
    "validateNativeExchange",
  ]) {
    if (typeof engine[method] !== "function") {
      throw new ComponentRuntimeError("component_invalid", `generated component is missing engine.${method}()`);
    }
  }
  return engine;
}

export function componentIdentityInput({ harness, event, sessionId, agentId, agentType, toolUseId, model, providerVersion }) {
  return {
    harness,
    event: eventVariant(event),
    sessionId: required(sessionId, "sessionId"),
    agentId: agentId ?? undefined,
    agentType: agentType ?? undefined,
    toolUseId: toolUseId ?? undefined,
    model: model ?? undefined,
    providerVersion: providerVersion ?? undefined,
  };
}

export function eventVariant(event) {
  const known = new Set([
    "SessionStart",
    "SubagentStart",
    "SubagentResume",
    "SubagentStop",
    "PreToolUse",
    "PostToolUse",
  ]);
  if (known.has(event)) return { tag: event.replace(/[A-Z]/g, (value, index) => index ? `-${value.toLowerCase()}` : value.toLowerCase()) };
  return { tag: "other-event", val: required(event, "event") };
}

export function normalizeWithComponent(engine, input) {
  return requireEngine(engine).normalizeIdentity(input);
}

export function planWithComponent(engine, identity, binding = undefined) {
  return requireEngine(engine).planLifecycle(identity, binding);
}

export function planToNativeDispatch(plan) {
  if (plan?.tag === "ignored") return null;
  if (plan?.tag === "blocked") {
    throw new ComponentRuntimeError("dispatch_blocked", plan.val?.message ?? "component blocked dispatch");
  }
  if (plan?.tag !== "request" || !plan.val?.tag) {
    throw new ComponentRuntimeError("component_invalid", "component returned an invalid dispatch plan");
  }
  return {
    operation: plan.val.tag,
    request: camelToSnake(plan.val.val),
  };
}

export function componentBinding(binding = {}) {
  return {
    run: binding.run ?? undefined,
    role: binding.role ?? binding.role_carrier ?? undefined,
    lane: binding.lane ?? undefined,
    parentAgentId: binding.parentAgentId ?? binding.parent_agent_id ?? undefined,
    writeScope: binding.writeScope ?? binding.write_scope ?? [],
    model: binding.model ?? undefined,
    observedCapabilities: binding.observedCapabilities ?? binding.observed_capabilities ?? [],
    capabilitySource: binding.capabilitySource ?? binding.capability_source ?? "native-adapter",
    harnessVersion: binding.harnessVersion ?? binding.harness_version ?? "unknown",
    providerVersion: binding.providerVersion ?? binding.provider_version ?? undefined,
    leaseMs: binding.leaseMs ?? binding.lease_ms ?? 86_400_000,
    expectedRevision: binding.expectedRevision ?? binding.expected_revision ?? 1,
    resultArtifact: binding.resultArtifact ?? binding.result_artifact ?? undefined,
    sourceAgentId: binding.sourceAgentId ?? binding.source_agent_id ?? undefined,
    mode: binding.mode ?? "execution",
    toolName: binding.toolName ?? binding.tool_name ?? undefined,
    toolInput: binding.toolInput ?? binding.tool_input ?? undefined,
  };
}

export function guardWithComponent(engine, request) {
  const result = requireEngine(engine).guardEvalCanonical(JSON.stringify(request));
  return result.tag === "allow"
    ? { decision: "allow" }
    : result.tag === "deny"
      ? {
          decision: "deny",
          predicate: result.val.predicate,
          rule: result.val.rule,
          halt_code: result.val.haltCode,
          reason: result.val.reason,
        }
      : { decision: "unresolved", missing: result.val.missing, reason: result.val.reason };
}

export function validateResponseWithComponent(engine, response) {
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    throw new ComponentRuntimeError("invalid_response", "native dispatch response must be an object");
  }
  const facts = snakeToCamel(response);
  if (facts.capabilities !== null && facts.capabilities !== undefined) {
    facts.capabilities = capabilityReportToWit(facts.capabilities, "capabilities");
  }
  requireEngine(engine).validateResponse(facts);
  return true;
}

const NATIVE_LIFECYCLE_OPERATIONS = new Set(["bind-root", "start", "resolve", "stop", "resume"]);

/**
 * Lowers one native CLI lifecycle response into the exact jco/WIT variant and
 * asks the Rust Component to validate schema, operation, state, identity, and
 * resume-context invariants. Native JSON uses numbers; WIT s64/u64 fields use
 * BigInt, so this boundary performs the only representation conversion.
 */
export function validateNativeResponseWithComponent(engine, operation, response) {
  requireEngine(engine).validateNativeResponse(operation, nativeResponseVariant(operation, response));
  return true;
}

/**
 * Validates both halves of a native dispatch exchange in Rust. The response
 * may be structurally valid yet belong to another agent, session, run, or tool
 * call; this is the authoritative correlation boundary for every adapter.
 */
export function validateNativeExchangeWithComponent(engine, operation, request, response) {
  const requestVariant = nativeRequestVariant(operation, request);
  const responseVariant = nativeResponseVariant(operation, response);
  requireEngine(engine).validateNativeExchange(requestVariant, responseVariant);
  return true;
}

/**
 * Renders only host-facing lifecycle context. Validation remains Rust-owned;
 * adapters call validateNativeExchangeWithComponent before this translator.
 */
export function renderNativeLifecycleContext(operation, response) {
  if (operation === "start" && response?.state === "capability_blocked") {
    const missing = response?.capabilities?.missing_required;
    const detail = Array.isArray(missing) && missing.length > 0 ? missing.join(", ") : "unknown";
    return `[shepherd] native start is capability_blocked; missing required capabilities: ${detail}`;
  }
  if (operation !== "resume") return "";
  const entries = response?.context?.entries;
  if (!Array.isArray(entries) || entries.length === 0) return "";
  const words = response.context.words;
  const tokens = response.context.tokens;
  const label = entries.length === 1 ? "entry" : "entries";
  const sections = entries.map((entry, index) => {
    if (typeof entry?.provenance !== "string" || typeof entry?.content !== "string") {
      throw new ComponentRuntimeError("invalid_response", `resume context entry ${index} is malformed`);
    }
    return `[${entry.provenance}]\n${entry.content}`;
  });
  return `[shepherd resume context: ${entries.length} ${label}, ${words} words, ${tokens} tokens]\n\n${sections.join("\n\n")}`;
}

export function compileCanonicalWithComponent(engine, target) {
  return requireEngine(engine).compileCanonical(target);
}

function required(value, field) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${field} must be non-empty`);
  return value;
}

function camelToSnake(value) {
  if (Array.isArray(value)) return value.map(camelToSnake);
  if (typeof value === "bigint") {
    const number = Number(value);
    if (!Number.isSafeInteger(number)) throw new ComponentRuntimeError("component_invalid", "component returned an unsafe integer");
    return number;
  }
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [
    key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`),
    camelToSnake(item),
  ]));
}

function snakeToCamel(value) {
  if (Array.isArray(value)) return value.map(snakeToCamel);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [
    key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase()),
    snakeToCamel(item),
  ]));
}

function rootBindingToWit(response) {
  const value = snakeToCamel(response);
  value.boundAt = integerToBigInt(value.boundAt, "bound_at");
  value.expiresAt = integerToBigInt(value.expiresAt, "expires_at");
  return value;
}

function nativeRequestVariant(operation, request) {
  requireLifecycleOperation(operation);
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new ComponentRuntimeError("invalid_response", "native lifecycle request must be an object");
  }
  const value = operation === "bind-root"
    ? bindRootRequestToWit(request)
    : operation === "start"
      ? startRequestToWit(request)
      : operation === "resolve"
        ? snakeToCamel(request)
        : operation === "stop"
          ? stopRequestToWit(request)
          : resumeRequestToWit(request);
  return { tag: operation, val: value };
}

function nativeResponseVariant(operation, response) {
  requireLifecycleOperation(operation);
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    throw new ComponentRuntimeError("invalid_response", "native lifecycle response must be an object");
  }
  const value = operation === "bind-root"
    ? rootBindingToWit(response)
    : operation === "start" || operation === "stop"
      ? dispatchRecordToWit(response)
      : operation === "resolve"
        ? responseFactsToWit(response)
        : resumeResponseToWit(response);
  return { tag: operation, val: value };
}

function bindRootRequestToWit(request) {
  const value = snakeToCamel(request);
  value.leaseMs = integerToBigInt(value.leaseMs, "lease_ms");
  return value;
}

function startRequestToWit(request) {
  const value = snakeToCamel(request);
  value.leaseMs = integerToBigInt(value.leaseMs, "lease_ms");
  return value;
}

function stopRequestToWit(request) {
  const value = snakeToCamel(request);
  value.expectedRevision = integerToBigInt(value.expectedRevision, "expected_revision");
  return value;
}

function resumeRequestToWit(request) {
  if (request.next === null || typeof request.next !== "object" || Array.isArray(request.next)) {
    throw new ComponentRuntimeError("invalid_response", "native resume request must contain next");
  }
  return {
    sourceAgentId: request.source_agent_id ?? request.sourceAgentId,
    next: startRequestToWit(request.next),
  };
}

function responseFactsToWit(response) {
  const value = snakeToCamel(response);
  if (value.capabilities !== null && value.capabilities !== undefined) {
    value.capabilities = capabilityReportToWit(value.capabilities, "capabilities");
  }
  return value;
}

function requireLifecycleOperation(operation) {
  if (!NATIVE_LIFECYCLE_OPERATIONS.has(operation)) {
    throw new ComponentRuntimeError("invalid_response", `unknown native lifecycle operation: ${String(operation)}`);
  }
}

function dispatchRecordToWit(response) {
  const value = snakeToCamel(response);
  value.revision = integerToBigInt(value.revision, "revision");
  value.startedAt = integerToBigInt(value.startedAt, "started_at");
  value.leaseExpiresAt = integerToBigInt(value.leaseExpiresAt, "lease_expires_at");
  value.stoppedAt = optionalIntegerToBigInt(value.stoppedAt, "stopped_at");
  value.capabilities = capabilityReportToWit(value.capabilities, "capabilities");
  return value;
}

function capabilityReportToWit(report, field) {
  if (report === null || typeof report !== "object" || Array.isArray(report)) {
    throw new ComponentRuntimeError("invalid_response", `${field} must be an object`);
  }
  const value = snakeToCamel(report);
  value.probedAt = integerToBigInt(value.probedAt, `${field}.probed_at`);
  return value;
}

function resumeResponseToWit(response) {
  if (response.record === null || typeof response.record !== "object" || Array.isArray(response.record)) {
    throw new ComponentRuntimeError("invalid_response", "native resume response must contain record");
  }
  if (response.context === null || typeof response.context !== "object" || Array.isArray(response.context)) {
    throw new ComponentRuntimeError("invalid_response", "native resume response must contain context");
  }
  const context = snakeToCamel(response.context);
  if (!Array.isArray(context.entries)) {
    throw new ComponentRuntimeError("invalid_response", "native resume context entries must be an array");
  }
  context.entries = context.entries.map((entry, index) => {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      throw new ComponentRuntimeError("invalid_response", `native resume context entry ${index} must be an object`);
    }
    const value = snakeToCamel(entry);
    value.freshness = integerToBigInt(value.freshness, `context.entries[${index}].freshness`);
    value.words = integerToBigInt(value.words, `context.entries[${index}].words`);
    value.tokens = integerToBigInt(value.tokens, `context.entries[${index}].tokens`);
    return value;
  });
  context.words = integerToBigInt(context.words, "context.words");
  context.tokens = integerToBigInt(context.tokens, "context.tokens");
  return {
    schema: response.schema,
    dispatchRecord: dispatchRecordToWit(response.record),
    context,
  };
}

function integerToBigInt(value, field) {
  if (typeof value === "bigint") return value;
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new ComponentRuntimeError("invalid_response", `${field} must be a safe JSON integer`);
  }
  return BigInt(value);
}

function optionalIntegerToBigInt(value, field) {
  return value === null || value === undefined ? undefined : integerToBigInt(value, field);
}

export class ComponentRuntimeError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ComponentRuntimeError";
    this.code = code;
  }
}
