const REQUIRED_METHODS = Object.freeze(["capabilities", "spawn", "resume", "stop"]);

export function bindSubagentProvider(candidate) {
  if (candidate === undefined || candidate === null) return null;
  for (const method of REQUIRED_METHODS) {
    if (typeof candidate[method] !== "function") {
      throw new TypeError(`SubagentProvider.${method}() is required`);
    }
  }
  return candidate;
}

export function probeSubagentProvider(provider, runtime) {
  return admitSubagentProvider(provider, {
    harnessVersion: runtime?.harnessVersion,
    probedAt: runtime?.probedAt,
  }).report;
}

/**
 * Admits a provider to a lifecycle operation only after its capability
 * envelope is known to be ready. The probe is intentionally fail-closed: a
 * malformed envelope or probe exception returns null and no lifecycle method
 * is eligible to run.
 */
export function readySubagentProvider(provider, runtime = {}) {
  try {
    return admitSubagentProvider(provider, {
      harnessVersion: runtime.harnessVersion ?? runtime.harness_version ?? "unknown",
      probedAt: runtime.probedAt ?? runtime.probed_at ?? 0,
    }).binding;
  } catch {
    return null;
  }
}

function admitSubagentProvider(provider, runtime) {
  const harnessVersion = requireBounded(runtime?.harnessVersion, "harnessVersion", 128);
  const probedAt = runtime?.probedAt;
  if (!Number.isSafeInteger(probedAt) || probedAt < 0) {
    throw new TypeError("probedAt must be a non-negative safe integer");
  }
  const base = {
    observed: [],
    source: "pi-startup-provider-probe",
    harness_version: harnessVersion,
    provider_version: null,
    probed_at: probedAt,
  };
  let bound;
  try {
    bound = bindSubagentProvider(provider);
  } catch {
    return { report: blocked(base), binding: null };
  }
  if (bound === null) {
    return { report: blocked(base), binding: null };
  }
  try {
    const capabilities = bound.capabilities();
    if (capabilities === null || typeof capabilities !== "object" || Array.isArray(capabilities)) {
      return { report: blocked(base), binding: null };
    }
    if (capabilities.primitive !== "subagent-provider") {
      return { report: blocked(base), binding: null };
    }
    const providerVersion = requireBounded(capabilities.version, "provider version", 128);
    const limits = capabilities.limits;
    if (limits === null || typeof limits !== "object" || Array.isArray(limits)) {
      return { report: blocked(base), binding: null };
    }
    if (capabilities.readiness !== undefined && capabilities.readiness !== "ready") {
      return { report: blocked(base), binding: null };
    }
    if (capabilities.ready !== undefined && capabilities.ready !== true) {
      return { report: blocked(base), binding: null };
    }
    const snapshot = freezeSnapshot({ ...capabilities, limits: { ...limits } });
    const report = {
      ...base,
      observed: ["subagent-provider"],
      provider_version: providerVersion,
      readiness: "ready",
      missing_required: [],
      limits: { ...limits },
    };
    const binding = Object.freeze({
      capabilities: () => snapshot,
      spawn: bound.spawn.bind(bound),
      resume: bound.resume.bind(bound),
      stop: bound.stop.bind(bound),
    });
    return { report, binding };
  } catch {
    // Capability discovery is an admission probe. A provider that cannot
    // describe itself is unavailable, not an exception that may reach the
    // lifecycle method and create an untracked child.
    return { report: blocked(base), binding: null };
  }
}

function freezeSnapshot(value) {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) freezeSnapshot(child);
    Object.freeze(value);
  }
  return value;
}

function blocked(base) {
  return {
    ...base,
    readiness: "capability_blocked",
    missing_required: ["subagent-provider"],
  };
}

function requireBounded(value, field, max) {
  if (typeof value !== "string" || value.length === 0 || value.length > max) {
    throw new TypeError(`${field} must be a non-empty bounded string`);
  }
  return value;
}
