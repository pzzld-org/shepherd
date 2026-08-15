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
    input: `${JSON.stringify(request)}\n`,
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
    return { ok: true, value: JSON.parse(String(result.stdout).trim()) };
  } catch (error) {
    return { ok: false, detail: `native dispatch returned malformed JSON: ${error.message}` };
  }
}
