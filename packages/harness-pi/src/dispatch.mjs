//! Provider-only Pi lifecycle adapter. The component owns identity and
//! dispatch policy; this module owns provider invocation and host publication.

import {
  componentBinding,
  planToNativeDispatch,
  planWithComponent,
  validateNativeExchangeWithComponent,
} from "../../component-runtime/src/index.mjs";
import {
  invokeNativeDispatch,
  nativeShepherdBin,
} from "../../component-runtime/src/native-transport.mjs";
import { normalizePiWithComponent } from "./identity.mjs";
import { readySubagentProvider } from "./subagent-provider.mjs";

export async function spawnSubagent(provider, request, runtime) {
  const bound = readySubagentProvider(provider, runtime);
  if (bound === null) return capabilityBlocked("subagent-provider");
  if (!runtime?.componentEngine) return capabilityBlocked("component-runtime");
  const engine = runtime.componentEngine;
  let nativeEvent;
  let spawned = false;
  try {
    nativeEvent = await bound.spawn(request);
    spawned = true;
    const lifecycle = lifecycleResult("started", bound, nativeEvent, runtime, engine);
    const dispatch = planToNativeDispatch(lifecycle.plan);
    if (!dispatch || dispatch.operation !== "start") throw new Error("component did not plan a start request");
    const published = publishNative(dispatch, runtime);
    validateNativeExchangeWithComponent(engine, dispatch.operation, dispatch.request, published);
    validatePublishedIdentity(published, lifecycle.identity, dispatch.operation);
    return { kind: "started", identity: lifecycle.identity, native_event: nativeEvent, plan: lifecycle.plan, request: dispatch.request, dispatch: published };
  } catch (publishError) {
    if (!spawned) throw publishError;
    return await failAndStopChild(bound, childAgentId(nativeEvent), publishError, "native dispatch publication failed and the Pi child could not be stopped");
  }
}

export async function resumeSubagent(provider, agentId, runtime) {
  return publishLifecycle("resumed", provider, agentId, runtime);
}

export async function stopSubagent(provider, agentId, runtime) {
  return publishLifecycle("stopped", provider, agentId, runtime);
}

async function publishLifecycle(kind, provider, agentId, runtime) {
  const bound = readySubagentProvider(provider, runtime);
  if (bound === null) return capabilityBlocked("subagent-provider");
  if (!runtime?.componentEngine) return capabilityBlocked("component-runtime");
  let nativeEvent;
  try {
    nativeEvent = kind === "resumed"
      ? await bound.resume(agentId)
      : kind === "stopped"
        ? stopIdentity(agentId, runtime)
        : await bound.stop(agentId);
    const lifecycle = lifecycleResult(kind, bound, nativeEvent, { ...runtime, sourceAgentId: agentId }, runtime.componentEngine);
    const dispatch = planToNativeDispatch(lifecycle.plan);
    if (!dispatch) throw new Error(`component ignored ${kind} lifecycle`);
    const published = publishNative(dispatch, runtime);
    validateNativeExchangeWithComponent(runtime.componentEngine, dispatch.operation, dispatch.request, published);
    validatePublishedIdentity(published, lifecycle.identity, dispatch.operation);
    const providerEvent = kind === "stopped" ? await bound.stop(agentId) : nativeEvent;
    return { kind, identity: lifecycle.identity, native_event: providerEvent, plan: lifecycle.plan, request: dispatch.request, dispatch: published };
  } catch (lifecycleError) {
    if (kind !== "resumed") throw lifecycleError;
    return await failAndStopChild(bound, childAgentId(nativeEvent), lifecycleError, "native resume publication failed and the resumed Pi child could not be stopped");
  }
}

export async function planPiLifecycleWithComponent(provider, event, runtime, engine, binding = undefined) {
  const bound = readySubagentProvider(provider, runtime);
  if (bound === null) return capabilityBlocked("subagent-provider");
  const nativeEvent = event.lifecycle === "started"
    ? await bound.spawn(event)
    : event.lifecycle === "resumed"
      ? await bound.resume(event.agentId)
      : await bound.stop(event.agentId);
  const identity = normalizePiWithComponent(nativeEvent, {
    sessionId: runtime?.sessionId,
    providerVersion: bound.capabilities()?.version,
  }, engine);
  const plan = planWithComponent(engine, identity, binding === undefined ? undefined : componentBinding(binding));
  return { identity, plan, native_event: nativeEvent };
}

function lifecycleResult(kind, provider, nativeEvent, runtime, engine) {
  const capabilities = provider.capabilities();
  const identity = normalizePiWithComponent(nativeEvent, {
    sessionId: runtime?.sessionId,
    providerVersion: capabilities?.version,
  }, engine);
  const binding = componentBinding({
    run: runtime.run,
    role: runtime.role_carrier ?? runtime.roleCarrier ?? identity.roleCarrier,
    lane: runtime.lane,
    parentAgentId: runtime.parent_agent_id ?? runtime.parentAgentId,
    writeScope: runtime.write_scope ?? runtime.writeScope,
    model: runtime.model ?? identity.model,
    observedCapabilities: runtime.observed_capabilities ?? runtime.observedCapabilities,
    capabilitySource: runtime.capability_source ?? runtime.capabilitySource ?? "pi-startup-provider-probe",
    harnessVersion: runtime.harnessVersion,
    providerVersion: identity.providerVersion,
    leaseMs: runtime.leaseMs,
    expectedRevision: runtime.expectedRevision,
    resultArtifact: nativeEvent.resultArtifact ?? runtime.resultArtifact,
    sourceAgentId: kind === "resumed" ? runtime.sourceAgentId ?? identity.agentId : undefined,
  });
  const plan = planWithComponent(engine, identity, binding);
  return { kind, identity, plan };
}

function stopIdentity(agentId, runtime) {
  const agentType = runtime.agent_type ?? runtime.agentType;
  if (typeof agentType !== "string" || agentType.length === 0) {
    throw new TypeError("Pi stop requires the provider agent_type before native durable stop");
  }
  return {
    lifecycle: "stopped",
    agentId,
    agentType,
    model: runtime.model,
    resultArtifact: runtime.result_artifact ?? runtime.resultArtifact,
  };
}

function publishNative(dispatch, runtime) {
  const result = invokeNativeDispatch({
    shepherdBin: nativeShepherdBin(runtime.shepherdBin),
    operation: dispatch.operation,
    request: dispatch.request,
    cwd: runtime.cwd ?? process.cwd(),
  });
  if (!result.ok) throw new Error(result.detail);
  return result.value;
}

function validatePublishedIdentity(value, identity, operation) {
  const record = operation === "resume" ? value?.record : value;
  if (record?.agent_id !== identity.agentId
    || record.agent_type !== identity.agentType
    || record.harness !== identity.harness
    || record.session_id !== identity.sessionId
    || (operation === "start" && record.state === "capability_blocked")) {
    throw new TypeError("native dispatch publisher returned a mismatched or blocked record");
  }
}

function childAgentId(nativeEvent) {
  const agentId = nativeEvent?.agentId ?? nativeEvent?.agent_id;
  return typeof agentId === "string" && agentId.length > 0 ? agentId : null;
}

async function failAndStopChild(provider, agentId, primaryError, message) {
  if (agentId === null) throw primaryError;
  try {
    await provider.stop(agentId);
  } catch (stopError) {
    throw new AggregateError([primaryError, stopError], message);
  }
  throw primaryError;
}

function capabilityBlocked(name) {
  return { kind: "capability_blocked", missing_required: [name] };
}
