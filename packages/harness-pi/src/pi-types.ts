// packages/harness-pi/src/pi-types.ts -- a minimal, hand-rolled subset of
// @earendil-works/pi-coding-agent's extension type surface -- ONLY the shapes
// src/extension.ts actually uses. Transcribed verbatim (field names, not paraphrased) from
// the real installed 0.84.1 package's own declarations at
// /opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/extensions/
// types.d.ts, confirmed on this box, not guessed or inferred from prose docs. No dependency
// on that package is added (packages/harness-pi/package.json has none) -- Pi loads
// extensions via jiti at runtime and supplies the REAL ExtensionAPI object; this file only
// types this package's OWN source against the same shapes so `tsc`-style tooling (and
// Node's own erasable-syntax check) can catch a mismatch before Pi ever loads the extension.

export interface ToolCallEventResult {
  /** Block tool execution. */
  block?: boolean;
  reason?: string;
  /** Early-terminate hint; applies only if every finalized result in the batch sets it. */
  terminate?: boolean;
}

interface ToolCallEventBase {
  type: "tool_call";
  toolCallId: string;
}

export interface BashToolCallEvent extends ToolCallEventBase {
  toolName: "bash";
  input: { command: string; timeout?: number };
}

export interface WriteToolCallEvent extends ToolCallEventBase {
  toolName: "write";
  input: { path: string; content: string };
}

export interface EditToolCallEvent extends ToolCallEventBase {
  toolName: "edit";
  input: { path: string; edits: { oldText: string; newText: string }[] };
}

export interface OtherToolCallEvent extends ToolCallEventBase {
  toolName: string;
  input: Record<string, unknown>;
}

export type ToolCallEvent = BashToolCallEvent | WriteToolCallEvent | EditToolCallEvent | OtherToolCallEvent;

/** The subset of ExtensionAPI this package's guard layer registers against. */
export interface ExtensionAPI {
  on(event: "tool_call", handler: (event: ToolCallEvent) => ToolCallEventResult | undefined): void;
}

/** Extension factory function type -- `(pi: ExtensionAPI) => void | Promise<void>`. */
export type ExtensionFactory = (pi: ExtensionAPI) => void | Promise<void>;
