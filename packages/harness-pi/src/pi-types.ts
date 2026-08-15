// packages/harness-pi/src/pi-types.ts -- a minimal, hand-rolled subset of
// @earendil-works/pi-coding-agent's extension type surface -- ONLY the shapes
// src/extension.mjs actually uses. Transcribed verbatim (field names, not paraphrased) from
// the real installed 0.84.1 package's own declarations at
// /opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/extensions/
// types.d.ts, confirmed on this box, not guessed or inferred from prose docs. No dependency
// on that package is added (packages/harness-pi/package.json has none) -- Pi loads
// extensions via jiti at runtime and supplies the REAL ExtensionAPI object; this file only
// types this package's OWN source against the same shapes so `tsc`-style tooling (and
// Node's own erasable-syntax check) can catch a mismatch before Pi ever loads the extension.
//
// The async handler shape is intentional. Pi awaits this callback before a tool executes,
// allowing the component-backed guard evaluation to finish before the host proceeds. The
// installed 0.84.1 declarations use the same promise-capable handler contract:
//   `export type ExtensionHandler<E, R> = (event: E, ctx: ExtensionContext) =>
//    Promise<R | void> | R | void;`
//   `on(event: "tool_call", handler: ExtensionHandler<ToolCallEvent, ToolCallEventResult>): void;`
// -- async IS supported. `dist/core/extensions/runner.js`'s `emitToolCall` (`await
// handler(event, ctx)`) and `dist/core/agent-session.js`'s `_installAgentToolHooks`
// (`this.agent.beforeToolCall = async (...) => { ... await runner.emitToolCall(...) ... }`)
// both genuinely await it before the tool executes -- not fire-and-forget. The bundled
// `docs/extensions.md` documents this as the first-class pattern
// (`pi.on("tool_call", async (event, ctx) => {...})`) and states the concurrency bound this
// package's component callback depends on: "In the default parallel tool execution mode,
// sibling tool calls from the same assistant message are preflighted sequentially, then
// executed concurrently" -- so the extension can perform one bounded evaluation at a time.

export interface ToolCallEventResult {
  /** Block tool execution. */
  block?: boolean;
  reason?: string;
  /** Early-terminate hint; applies only if every finalized result in the batch sets it. */
  terminate?: boolean;
}

/** Verbatim shape of the real `SessionShutdownEvent`. */
export interface SessionShutdownEvent {
  type: "session_shutdown";
  reason: "quit" | "reload" | "new" | "resume" | "fork";
  targetSessionFile?: string;
}

export interface SessionStartEvent {
  type: "session_start";
  reason: "startup" | "reload" | "new" | "resume" | "fork";
  previousSessionFile?: string;
}

export interface SessionStartContext {
  cwd: string;
  sessionManager: { getSessionId(): string };
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

/** The subset of `ExtensionHandler<ToolCallEvent, ToolCallEventResult>` this package needs -- async included. */
export type ToolCallHandler = (
  event: ToolCallEvent,
  context: SessionStartContext
) => ToolCallEventResult | undefined | Promise<ToolCallEventResult | undefined>;

/** The subset of ExtensionAPI this package's guard layer registers against. */
export interface ExtensionAPI {
  on(
    event: "session_start",
    handler: (event: SessionStartEvent, context: SessionStartContext) => void | Promise<void>
  ): void;
  on(event: "tool_call", handler: ToolCallHandler): void;
  /** Registered once for session cleanup and future host resources. */
  on(event: "session_shutdown", handler: (event: SessionShutdownEvent) => void | Promise<void>): void;
}

/** Extension factory function type -- `(pi: ExtensionAPI) => void | Promise<void>`. */
export type ExtensionFactory = (pi: ExtensionAPI) => void | Promise<void>;
