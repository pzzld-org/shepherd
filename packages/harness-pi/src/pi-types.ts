// Minimal subset of the installed Pi 0.84.1 extension surface used by
// src/extension.mjs. Field names follow Pi's declarations and pi-subagents
// 0.53.0 public event payloads. This package adds no runtime Pi dependency.

export interface ToolCallEventResult {
  block?: boolean;
  reason?: string;
  terminate?: boolean;
}

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

export interface ExtensionContext {
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

export interface SubagentToolResultChild {
  runId?: string;
  index: number;
  agent: string;
  detached?: boolean;
  sessionFile?: string;
}

export interface SubagentWorkflowResult {
  runId?: string;
  results?: SubagentToolResultChild[];
}

export interface SubagentToolResultEvent {
  type: "tool_result";
  toolName: "subagent";
  toolCallId: string;
  input: Record<string, unknown>;
  content: unknown[];
  isError: boolean;
  details?: {
    runId?: string;
    background?: boolean;
    results: SubagentToolResultChild[];
    workflow?: { value?: SubagentWorkflowResult | SubagentWorkflowResult[] };
  };
}

export interface MessageEndEvent {
  type: "message_end";
  message: {
    role: string;
    stopReason?: string;
    content?: { type?: string }[];
  };
}

export interface ForegroundCompleteEvent {
  runId?: string;
  taskIndex?: number;
  agent?: string;
  sessionFile?: string;
  cwd?: string;
  sessionId?: string;
}

export interface AsyncCompleteResult {
  runId?: string;
  index?: number;
  agent?: string;
  sessionFile?: string;
  sessionPath?: string;
  artifactPaths?: { outputPath?: string };
}

export interface AsyncCompleteEvent {
  runId?: string;
  results?: AsyncCompleteResult[];
  cwd?: string;
  sessionId?: string;
}

export type ToolCallHandler = (
  event: ToolCallEvent,
  context: ExtensionContext,
) => ToolCallEventResult | undefined | Promise<ToolCallEventResult | undefined>;

export interface EventBus {
  emit(channel: string, data: unknown): void;
  on(channel: "subagent:foreground-complete", handler: (event: ForegroundCompleteEvent) => void): () => void;
  on(channel: "subagent:async-complete", handler: (event: AsyncCompleteEvent) => void): () => void;
}

export interface ConfiguredTool {
  name: string;
  description: string;
  parameters: unknown;
  promptGuidelines?: string[];
  sourceInfo: {
    path: string;
    source: string;
    scope: "user" | "project" | "temporary";
    origin: "package" | "top-level";
  };
}

export interface ExtensionAPI {
  events: EventBus;
  getAllTools(): ConfiguredTool[];
  on(
    event: "session_start",
    handler: (event: SessionStartEvent, context: ExtensionContext) => void | Promise<void>,
  ): void;
  on(event: "tool_call", handler: ToolCallHandler): void;
  on(
    event: "tool_result",
    handler: (event: SubagentToolResultEvent, context: ExtensionContext) => void | Promise<void>,
  ): void;
  on(event: "message_end", handler: (event: MessageEndEvent, context: ExtensionContext) => void | Promise<void>): void;
  on(event: "agent_settled", handler: (event: unknown, context: ExtensionContext) => void | Promise<void>): void;
  on(
    event: "session_shutdown",
    handler: (event: SessionShutdownEvent, context: ExtensionContext) => void | Promise<void>,
  ): void;
}

export type ExtensionFactory = (pi: ExtensionAPI) => void | Promise<void>;
