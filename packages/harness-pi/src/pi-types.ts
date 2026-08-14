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
//
// C1-pi-collapse CORRECTION: an earlier revision of this file narrowed `on("tool_call", ...)`
// to a strictly synchronous `(event) => ToolCallEventResult | undefined` handler, and
// src/guard.ts's header cited that narrowing as the reason a `guard serve` relay was
// impossible ("extension.ts calls this file's evaluate() SYNCHRONOUSLY... there is no
// subprocess boundary to absorb a slow call"). That was a bad transcription, not a real
// constraint. The actual installed 0.84.1 `types.d.ts` (same file, same version, re-checked
// for this step) declares:
//   `export type ExtensionHandler<E, R> = (event: E, ctx: ExtensionContext) =>
//    Promise<R | void> | R | void;`
//   `on(event: "tool_call", handler: ExtensionHandler<ToolCallEvent, ToolCallEventResult>): void;`
// -- async IS supported. `dist/core/extensions/runner.js`'s `emitToolCall` (`await
// handler(event, ctx)`) and `dist/core/agent-session.js`'s `_installAgentToolHooks`
// (`this.agent.beforeToolCall = async (...) => { ... await runner.emitToolCall(...) ... }`)
// both genuinely await it before the tool executes -- not fire-and-forget. The bundled
// `docs/extensions.md` documents this as the first-class pattern
// (`pi.on("tool_call", async (event, ctx) => {...})`) and states the concurrency bound this
// package's guard relay depends on: "In the default parallel tool execution mode, sibling
// tool calls from the same assistant message are preflighted sequentially, then executed
// concurrently" -- so one in-flight request at a time against one long-lived `guard serve`
// child process (src/guard-client.ts) is always correct here, never a race.

export interface ToolCallEventResult {
  /** Block tool execution. */
  block?: boolean;
  reason?: string;
  /** Early-terminate hint; applies only if every finalized result in the batch sets it. */
  terminate?: boolean;
}

/** Verbatim shape of the real `SessionShutdownEvent` -- used only to close the guard-serve child. */
export interface SessionShutdownEvent {
  type: "session_shutdown";
  reason: "quit" | "reload" | "new" | "resume" | "fork";
  targetSessionFile?: string;
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
  event: ToolCallEvent
) => ToolCallEventResult | undefined | Promise<ToolCallEventResult | undefined>;

/** The subset of ExtensionAPI this package's guard layer registers against. */
export interface ExtensionAPI {
  on(event: "tool_call", handler: ToolCallHandler): void;
  /** Registered once, to close the `guard serve` child cleanly instead of orphaning it. */
  on(event: "session_shutdown", handler: (event: SessionShutdownEvent) => void | Promise<void>): void;
}

/** Extension factory function type -- `(pi: ExtensionAPI) => void | Promise<void>`. */
export type ExtensionFactory = (pi: ExtensionAPI) => void | Promise<void>;
