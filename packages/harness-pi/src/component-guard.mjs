import { guardWithComponent } from "../../component-runtime/src/index.mjs";

export function evaluatePiGuardWithComponent(engine, payload) {
  const input = payload && typeof payload === "object" ? payload : {};
  return guardWithComponent(engine, {
    tool_name: input.tool_name ?? "",
    tool_input: input.tool_input ?? {},
    role: input.role ?? undefined,
  });
}
