import { spawnSync } from "node:child_process";

const OPERATIONS = new Set(["bind-root", "start", "resolve", "stop", "resume"]);

/**
 * Resolve the one native Shepherd CLI. Package adapters must not assume a
 * source checkout or publish their own launcher. Explicit embedding/test
 * overrides win, followed by the process override, then normal PATH lookup.
 */
export function nativeShepherdBin(override = undefined, environment = process.env) {
  if (typeof override === "string" && override.length > 0) return override;
  const configured = environment?.SHEPHERD_NATIVE_BIN;
  return typeof configured === "string" && configured.length > 0 ? configured : "shepherd";
}

/**
 * Host transport only. Dispatch planning and request shape come from the
 * component; this function merely sends the typed request to the native CLI.
 */
// The wire envelope the native CLI validates before it looks at anything else.
// Every request struct in crates/core/src/dispatch/portable.rs declares
// `pub schema: String` and is `#[serde(deny_unknown_fields)]`;
// crates/cli/src/dispatch_service.rs compares it against exactly this value.
// The WIT records deliberately omit it -- the component owns the semantic
// payload, the transport owns framing -- and nothing filled the gap, so EVERY
// request the component produced was rejected: bind-root, start, resolve, stop
// and resume alike.
export const DISPATCH_REQUEST_SCHEMA = "shepherd.dispatch-request/1";

// WIT and the native structs disagree on exactly one field name: WIT
// `tool-use-id` (camelToSnake renders it `tool_use_id`) against Rust
// `tool_call_id`. With deny_unknown_fields that made every resolve request
// rejected, so the Pi guard denied every write, edit and bash call.
//
// A repo-wide diff of the six shared records found this to be the ONLY naming
// divergence, so the map is exhaustive. Reconciled here rather than in the WIT
// because the WIT is a published contract and renaming a field breaks every
// embedder -- and applied HERE rather than in planToNativeDispatch because the
// component's validateNativeExchange consumes the unframed request to correlate
// responses.
const WIRE_FIELD_RENAMES = new Map([["tool_use_id", "tool_call_id"]]);

export function toWireRequest(request) {
  const wire = { schema: DISPATCH_REQUEST_SCHEMA };
  for (const [key, value] of Object.entries(request ?? {})) {
    wire[WIRE_FIELD_RENAMES.get(key) ?? key] = value;
  }
  return wire;
}

// The inverse. The CLI answers in ITS naming, and the component correlates the
// response against the request it planned -- in WIT naming. Translating only
// one direction leaves the correlation comparing `tool_call_id` against
// `tool_use_id`, which the component reports as "identity resolution identity
// does not match its request". Framing is a boundary, and a boundary has two
// sides.
const WIRE_FIELD_RESTORES = new Map(
  [...WIRE_FIELD_RENAMES].map(([witName, wireName]) => [wireName, witName]),
);

export function fromWireResponse(response) {
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    return response;
  }
  const restored = {};
  for (const [key, value] of Object.entries(response)) {
    restored[WIRE_FIELD_RESTORES.get(key) ?? key] = value;
  }
  return restored;
}

export function invokeNativeDispatch({
  shepherdBin,
  operation,
  request,
  cwd = process.cwd(),
  environment = process.env,
  spawn = spawnSync,
}) {
  const binary = nativeShepherdBin(shepherdBin, environment);
  if (!OPERATIONS.has(operation)) {
    return { ok: false, detail: "a supported native Shepherd dispatch operation is required" };
  }
  const result = spawn(binary, ["dispatch", operation], {
    cwd,
    encoding: "utf8",
    input: `${JSON.stringify(toWireRequest(request))}\n`,
    maxBuffer: 1_048_576,
  });
  if (result.error) return { ok: false, detail: String(result.error.message ?? result.error) };
  if (result.status !== 0) {
    return {
      ok: false,
      detail: String(result.stderr || `shepherd dispatch ${operation} exited ${result.status}`).trim(),
    };
  }
  try {
    return { ok: true, value: fromWireResponse(JSON.parse(String(result.stdout).trim())) };
  } catch (error) {
    return { ok: false, detail: `native dispatch returned malformed JSON: ${error.message}` };
  }
}
