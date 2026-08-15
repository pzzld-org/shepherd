#!/usr/bin/env node
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { normalizeClaudeWithComponent } from "../harness-claude/src/identity.mjs";
import { planClaudeLifecycleWithComponent } from "../harness-claude/src/lifecycle.mjs";
import { evaluateGuardWithComponent as evaluateClaudeGuard } from "../harness-claude/src/guard.mjs";
import { normalizeCodexWithComponent } from "../harness-codex/src/identity.mjs";
import { planCodexLifecycleWithComponent } from "../harness-codex/src/lifecycle.mjs";
import { evaluateGuardWithComponent as evaluateCodexGuard } from "../harness-codex/src/guard.mjs";
import { planPiLifecycleWithComponent } from "../harness-pi/src/dispatch.mjs";
import { evaluatePiGuardWithComponent } from "../harness-pi/src/component-guard.mjs";

const modulePath = process.argv[2];
if (!modulePath) throw new Error("usage: test-adapters-component.mjs <transpiled-component.js>");
const loaded = await import(pathToFileURL(modulePath).href);
const engine = loaded.engine;
if (!engine) throw new Error("generated component module did not export engine");

const capabilities = ["read", "search", "shell", "write", "skill-load", "dispatch", "message-peer", "subagent-provider"];
const binding = {
  run: "v645", role: "engineer", lane: "l1", parent_agent_id: "parent-a", write_scope: ["crates/**"],
  model: "model-a", observed_capabilities: capabilities, capability_source: "native-extension",
  harness_version: "1.0", provider_version: "1.0", lease_ms: 60_000, expected_revision: 1, mode: "execution",
};
const claude = { hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-a", agent_type: "engineer", model: "model-a", tool_use_id: "tool-1" };
const codex = { hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-a", agent_type: "shepherd:engineer", model: "model-a", tool_use_id: "tool-1" };
const claudeIdentity = normalizeClaudeWithComponent(claude, engine);
const codexIdentity = normalizeCodexWithComponent(codex, engine);
assert.equal(claudeIdentity.identityKey, "claude\0session-a\0agent-a");
assert.equal(codexIdentity.identityKey, "codex\0session-a\0agent-a");
assert.equal(planClaudeLifecycleWithComponent(claude, engine, binding).plan.val.tag, "start");
assert.equal(planCodexLifecycleWithComponent(codex, engine, binding).plan.val.tag, "start");
assert.equal(evaluateClaudeGuard(engine, { tool_name: "Bash", tool_input: { command: "printf safe" } }).decision, "allow");
assert.equal(evaluateCodexGuard(engine, { tool_name: "Bash", tool_input: { command: "printf safe" } }).decision, "allow");

const provider = {
  capabilities: () => ({ primitive: "subagent-provider", version: "1.0", limits: { max: 3 } }),
  spawn: async () => ({ lifecycle: "started", agentId: "agent-a", agentType: "shepherd:engineer", model: "model-a" }),
  resume: async () => ({ lifecycle: "resumed", agentId: "agent-b", agentType: "shepherd:engineer", model: "model-a" }),
  stop: async () => ({ lifecycle: "stopped", agentId: "agent-a", agentType: "shepherd:engineer" }),
};
const pi = await planPiLifecycleWithComponent(provider, { lifecycle: "started" }, { sessionId: "session-a" }, engine, binding);
assert.equal(pi.identity.harness, "pi");
assert.equal(pi.plan.val.tag, "start");
assert.equal(evaluatePiGuardWithComponent(engine, { tool_name: "Bash", tool_input: { command: "printf safe" } }).decision, "allow");
console.log("ok: generated Shepherd component served Claude, Codex, and Pi adapter identity, lifecycle, provider, and guard probes");
