#!/usr/bin/env node
import assert from "node:assert/strict";
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import { resumeSubagent, spawnSubagent, stopSubagent } from "../harness-pi/src/dispatch.mjs";

const modulePath = process.argv[2];
const packageRoot = resolve(process.argv[3] ?? join(dirname(fileURLToPath(import.meta.url)), ".."));
if (!modulePath) throw new Error("usage: test-active-adapters.mjs <component-module> [package-root]");
const packageDirectories = {
  claude: ["harness-claude", "claude-shepherd"],
  codex: ["harness-codex", "codex-shepherd"],
  pi: ["harness-pi", "pi-shepherd"],
  runtime: ["component-runtime", "component-runtime"],
};
function packageDirectory([workspaceDirectory, publishedDirectory]) {
  for (const directory of [workspaceDirectory, publishedDirectory]) {
    if (existsSync(join(packageRoot, directory, "package.json"))) return directory;
  }
  throw new Error(`package root is missing ${workspaceDirectory} or ${publishedDirectory}: ${packageRoot}`);
}
const packages = Object.fromEntries(
  Object.entries(packageDirectories).map(([name, directories]) => [name, packageDirectory(directories)]),
);
const temp = mkdtempSync(join(tmpdir(), "shepherd-active-adapters-"));
const dispatcher = join(temp, "native-dispatch.mjs");
const loadedComponent = await import(pathToFileURL(modulePath).href);
const componentEngine = loadedComponent.engine ?? loadedComponent.default?.engine;
if (!componentEngine) throw new Error("staged component did not export engine");
const observedCapabilities = [
  "read", "search", "shell", "write", "skill-load", "dispatch", "message-peer", "subagent-provider",
];
const engineerCapabilities = camelToSnake(componentEngine.evaluateProvider("engineer", {
  observed: observedCapabilities,
  source: "active-probe",
  harnessVersion: "1.0",
  providerVersion: "pi-subagents/2.3.0",
}));
const genericEngineerCapabilities = camelToSnake(componentEngine.evaluateProvider("engineer", {
  observed: observedCapabilities,
  source: "active-probe",
  harnessVersion: "1.0",
  providerVersion: undefined,
}));
writeFileSync(dispatcher, `#!/usr/bin/env node
let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const request = JSON.parse(input);
  const operation = process.argv[3];
  const projectId = "0192f6e8-7b2c-7abc-8def-0123456789ab";
  const run = process.env.SHEPHERD_TEST_NATIVE_RUN ?? request.run ?? request.next?.run ?? "v645";
  if (operation === "bind-root") {
    process.stdout.write(JSON.stringify({
      schema: process.env.SHEPHERD_TEST_LIFECYCLE_SCHEMA ?? "shepherd.root-session/1",
      project_id: projectId, run, harness: request.harness,
      session_id: process.env.SHEPHERD_TEST_NATIVE_SESSION ?? request.session_id,
      role: request.role_carrier, mode: request.mode, bound_at: 1,
      expires_at: 1 + request.lease_ms,
    }));
    return;
  }
  if (operation === "resolve") {
    const role = process.env.SHEPHERD_TEST_NATIVE_ROLE ?? "engineer";
    const schema = process.env.SHEPHERD_TEST_NATIVE_SCHEMA ?? "shepherd.identity-resolution/1";
    const harness = process.env.SHEPHERD_TEST_NATIVE_HARNESS ?? request.harness;
    const root = role === "shepherd" || role === "planter";
    process.stdout.write(JSON.stringify({
      schema, project_id: projectId, run, harness,
      agent_id: root ? null : (request.agent_id ?? "agent-a"),
      agent_type: root ? null : (request.agent_type ?? "engineer"),
      role, lane: root ? null : "l1",
      session_id: process.env.SHEPHERD_TEST_NATIVE_SESSION ?? request.session_id,
      write_scope: root ? ["**"] : ["crates/**"], capabilities: ${JSON.stringify(engineerCapabilities)},
      write_paths: ["crates/core/src/lib.rs"], path_in_write_scope: true,
      tool_call_id: process.env.SHEPHERD_TEST_NATIVE_TOOL ?? request.tool_call_id ?? "tool-a", mode: "execution",
    }));
    return;
  }
  const next = operation === "resume" ? request.next : request;
  const role = process.env.SHEPHERD_TEST_LIFECYCLE_ROLE
    ?? (next.role_carrier ?? "shepherd:engineer").replace(/^shepherd:/, "");
  const state = operation === "stop" ? "stopped" : (process.env.SHEPHERD_TEST_LIFECYCLE_STATE ?? "active");
  const record = {
    schema: process.env.SHEPHERD_TEST_LIFECYCLE_SCHEMA ?? "shepherd.dispatch/3",
    revision: operation === "stop" ? 2 : 1,
    project_id: projectId, run, harness: next.harness,
    agent_id: process.env.SHEPHERD_TEST_LIFECYCLE_AGENT ?? next.agent_id,
    agent_type: next.agent_type, role,
    lane: next.lane ?? null, parent_agent_id: next.parent_agent_id ?? null,
    session_id: process.env.SHEPHERD_TEST_NATIVE_SESSION ?? next.session_id,
    write_scope: next.write_scope ?? ["crates/**"], model: next.model ?? null,
    capabilities: next.harness === "pi" ? ${JSON.stringify(engineerCapabilities)} : ${JSON.stringify(genericEngineerCapabilities)}, state,
    started_at: 1, lease_expires_at: 1 + (next.lease_ms ?? 60000),
    stopped_at: operation === "stop" ? 2 : null,
    result_artifact: next.result_artifact ?? null,
    resumes_agent_id: operation === "resume"
      ? (process.env.SHEPHERD_TEST_RESUME_SOURCE ?? request.source_agent_id)
      : null,
  };
  if (operation === "resume") {
    process.stdout.write(JSON.stringify({
      schema: process.env.SHEPHERD_TEST_RESUME_SCHEMA ?? "shepherd.resume-context/1",
      record,
      context: {
        entries: [{
          id: "context-a", project_id: projectId, run, lane: record.lane,
          provenance: "checkpoint", freshness: 1, words: 3, tokens: 4,
          priority: 1, content: "bounded shared context",
        }],
        words: 3, tokens: 4,
      },
    }));
    return;
  }
  process.stdout.write(JSON.stringify(record));
});
`);
chmodSync(dispatcher, 0o755);
const env = { ...process.env, SHEPHERD_COMPONENT_MODULE: modulePath, SHEPHERD_NATIVE_BIN: dispatcher };

function runHook(script, payload, hookEnv = env) {
  const result = spawnSync(process.execPath, [script], {
    cwd: process.cwd(), env: hookEnv, encoding: "utf8", input: `${JSON.stringify(payload)}\n`,
  });
  assert.equal(result.status, 0, `${script}: ${result.stderr}`);
  return result.stdout.trim() ? JSON.parse(result.stdout) : null;
}

function camelToSnake(value) {
  if (Array.isArray(value)) return value.map(camelToSnake);
  if (typeof value === "bigint") {
    const number = Number(value);
    if (!Number.isSafeInteger(number)) throw new Error("component emitted an unsafe test integer");
    return number;
  }
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [
    key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`),
    camelToSnake(item),
  ]));
}

const claudeGuardScript = join(packageRoot, packages.claude, "hooks/guard-eval.mjs");
const claudeLifecycleScript = join(packageRoot, packages.claude, "hooks/dispatch-lifecycle.mjs");
const codexHookScript = join(packageRoot, packages.codex, "hooks/scripts/shepherd_guard.mjs");
const piExtension = join(packageRoot, packages.pi, "src/extension.mjs");

const claudeGuard = runHook(claudeGuardScript, {
  hook_event_name: "PreToolUse", session_id: "session-a", tool_use_id: "tool-a",
  tool_name: "Bash", tool_input: { command: "printf safe" },
});
assert.equal(claudeGuard, null);
const wrongClaudeSession = runHook(claudeGuardScript, {
  hook_event_name: "PreToolUse", session_id: "session-a", tool_use_id: "tool-a",
  tool_name: "Bash", tool_input: { command: "printf safe" },
}, { ...env, SHEPHERD_TEST_NATIVE_SESSION: "session-b" });
assert.equal(
  wrongClaudeSession?.hookSpecificOutput?.permissionDecision,
  "deny",
  "Claude must reject a valid-schema resolution for another session",
);
const wrongClaudeTool = runHook(claudeGuardScript, {
  hook_event_name: "PreToolUse", session_id: "session-a", tool_use_id: "tool-a",
  tool_name: "Bash", tool_input: { command: "printf safe" },
}, { ...env, SHEPHERD_TEST_NATIVE_TOOL: "tool-b" });
assert.equal(
  wrongClaudeTool?.hookSpecificOutput?.permissionDecision,
  "deny",
  "Claude must reject a valid-schema resolution for another tool call",
);
const rootEnv = { ...env, SHEPHERD_TEST_NATIVE_ROLE: "shepherd" };
const rootWrite = runHook(claudeGuardScript, {
  hook_event_name: "PreToolUse", session_id: "root-session", tool_use_id: "root-write",
  tool_name: "Write", tool_input: { file_path: "crates/core/src/lib.rs", content: "root write" },
}, rootEnv);
assert.equal(rootWrite, null, "root Write must use the authoritative resolved native role");
const rootEdit = runHook(claudeGuardScript, {
  hook_event_name: "PreToolUse", session_id: "root-session", tool_use_id: "root-edit",
  tool_name: "Edit", tool_input: { file_path: "crates/core/src/lib.rs", old_string: "before", new_string: "after" },
}, rootEnv);
assert.equal(rootEdit, null, "root Edit must use the authoritative resolved native role");
const rootGitWrite = runHook(claudeGuardScript, {
  hook_event_name: "PreToolUse", session_id: "root-session", tool_use_id: "root-git-write",
  tool_name: "Bash", tool_input: { command: "git commit -m root-write" },
}, rootEnv);
assert.equal(rootGitWrite, null, "root Bash mutation must use the authoritative resolved native role");
const invalidRoleEnv = { ...env, SHEPHERD_TEST_NATIVE_ROLE: "" };
const invalidNativeRole = runHook(claudeGuardScript, {
  hook_event_name: "PreToolUse", session_id: "root-session", tool_use_id: "invalid-native-role",
  tool_name: "Bash", tool_input: { command: "git commit -m must-not-run" },
}, invalidRoleEnv);
assert.deepEqual(invalidNativeRole, {
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: invalidNativeRole?.hookSpecificOutput?.permissionDecisionReason,
  },
}, "an invalid resolved native role must fail closed");
const claudeLifecycle = runHook(claudeLifecycleScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-a", agent_type: "engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: ["read", "search", "shell", "write", "skill-load", "dispatch", "message-peer", "subagent-provider"],
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000,
  },
});
assert.equal(claudeLifecycle, null);
const wrongClaudeAgent = runHook(claudeLifecycleScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-a", agent_type: "engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: observedCapabilities,
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000,
  },
}, { ...env, SHEPHERD_TEST_LIFECYCLE_AGENT: "agent-b" });
assert.match(
  wrongClaudeAgent?.hookSpecificOutput?.additionalContext ?? "",
  /component rejected lifecycle/,
  "Claude must reject a valid-schema start response for another agent",
);
const blockedClaudeStart = runHook(claudeLifecycleScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-a", agent_type: "engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: observedCapabilities,
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000,
  },
}, { ...env, SHEPHERD_TEST_LIFECYCLE_STATE: "capability_blocked" });
assert.match(
  blockedClaudeStart?.hookSpecificOutput?.additionalContext ?? "",
  /capability_blocked/,
  "Claude must fail closed when the durable start is capability-blocked",
);
const malformedClaudeLifecycle = runHook(claudeLifecycleScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-a", agent_type: "engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: observedCapabilities,
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000,
  },
}, { ...env, SHEPHERD_TEST_LIFECYCLE_SCHEMA: "host-invented" });
assert.match(
  malformedClaudeLifecycle?.hookSpecificOutput?.additionalContext ?? "",
  /component rejected lifecycle/,
  "Claude lifecycle must reject a successful process response with the wrong typed schema",
);
const claudeResume = runHook(claudeLifecycleScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-b", agent_type: "engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: observedCapabilities,
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000, source_agent_id: "agent-a",
  },
});
assert.equal(
  claudeResume?.hookSpecificOutput?.additionalContext,
  "[shepherd resume context: 1 entry, 3 words, 4 tokens]\n\n[checkpoint]\nbounded shared context",
  "Claude resume must inject the validated bounded native context",
);
const wrongClaudeResumeSource = runHook(claudeLifecycleScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-b", agent_type: "engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: observedCapabilities,
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000, source_agent_id: "agent-a",
  },
}, { ...env, SHEPHERD_TEST_RESUME_SOURCE: "agent-z" });
assert.match(
  wrongClaudeResumeSource?.hookSpecificOutput?.additionalContext ?? "",
  /component rejected lifecycle/,
  "Claude must reject a valid-schema resume response for another source agent",
);
const codexGuard = runHook(codexHookScript, {
  hook_event_name: "PreToolUse", session_id: "session-a", tool_use_id: "tool-a",
  tool_name: "Bash", tool_input: { command: "printf safe" },
});
assert.equal(codexGuard, null);
const codexRootWrite = runHook(codexHookScript, {
  hook_event_name: "PreToolUse", session_id: "root-session", tool_use_id: "codex-root-write",
  tool_name: "Write", tool_input: { file_path: "crates/core/src/lib.rs", content: "root write" },
}, rootEnv);
assert.equal(codexRootWrite, null, "Codex root Write must use the authoritative resolved native role");
const malformedCodexEnv = { ...env, SHEPHERD_TEST_NATIVE_SCHEMA: "wrong" };
const malformedCodexResolution = runHook(codexHookScript, {
  hook_event_name: "PreToolUse", session_id: "session-a", tool_use_id: "codex-malformed-resolution",
  tool_name: "Bash", tool_input: { command: "printf safe" },
}, malformedCodexEnv);
assert.equal(
  malformedCodexResolution?.hookSpecificOutput?.permissionDecision,
  "deny",
  "Codex must fail closed on a malformed native resolution even for a role-free safe command",
);
const codexLifecycle = runHook(codexHookScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-a", agent_type: "shepherd:engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: ["read", "search", "shell", "write", "skill-load", "dispatch", "message-peer", "subagent-provider"],
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000,
  },
});
assert.equal(codexLifecycle, null);
const wrongCodexRun = runHook(codexHookScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-a", agent_type: "shepherd:engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: observedCapabilities,
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000,
  },
}, { ...env, SHEPHERD_TEST_NATIVE_RUN: "v999" });
assert.match(
  wrongCodexRun?.hookSpecificOutput?.additionalContext ?? "",
  /component rejected lifecycle/,
  "Codex must reject a valid-schema start response for another run",
);
const wrongCodexRole = runHook(codexHookScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-a", agent_type: "shepherd:engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: observedCapabilities,
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000,
  },
}, { ...env, SHEPHERD_TEST_LIFECYCLE_ROLE: "critic" });
assert.match(
  wrongCodexRole?.hookSpecificOutput?.additionalContext ?? "",
  /component rejected lifecycle/,
  "Codex must reject a valid-schema start response for another role",
);
const malformedCodexStop = runHook(codexHookScript, {
  hook_event_name: "SubagentStop", session_id: "session-a", agent_id: "agent-a", agent_type: "shepherd:engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: observedCapabilities,
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000, expected_revision: 1,
  },
}, { ...env, SHEPHERD_TEST_LIFECYCLE_SCHEMA: "host-invented" });
assert.match(
  malformedCodexStop?.hookSpecificOutput?.additionalContext ?? "",
  /component rejected lifecycle/,
  "Codex lifecycle must reject a successful process response with the wrong typed schema",
);
const codexResume = runHook(codexHookScript, {
  hook_event_name: "SubagentStart", session_id: "session-a", agent_id: "agent-b", agent_type: "shepherd:engineer",
  shepherd_dispatch: {
    run: "v645", role: "engineer", lane: "l1", write_scope: ["crates/**"], observed_capabilities: observedCapabilities,
    capability_source: "active-probe", harness_version: "1.0", lease_ms: 60000, source_agent_id: "agent-a",
  },
});
assert.equal(
  codexResume?.hookSpecificOutput?.additionalContext,
  "[shepherd resume context: 1 entry, 3 words, 4 tokens]\n\n[checkpoint]\nbounded shared context",
  "Codex resume must inject the validated bounded native context",
);

const pathBin = join(temp, "path-bin");
mkdirSync(pathBin);
copyFileSync(dispatcher, join(pathBin, "shepherd"));
chmodSync(join(pathBin, "shepherd"), 0o755);
const pathEnv = { ...env, PATH: `${pathBin}:${env.PATH ?? ""}` };
delete pathEnv.SHEPHERD_NATIVE_BIN;
const pathResolved = runHook(claudeGuardScript, {
  hook_event_name: "PreToolUse", session_id: "session-a", tool_use_id: "tool-path",
  tool_name: "Bash", tool_input: { command: "printf safe" },
}, pathEnv);
assert.equal(pathResolved, null, "installed adapter must resolve the one shepherd CLI from PATH");
const codexPathResolved = runHook(codexHookScript, {
  hook_event_name: "PreToolUse", session_id: "session-a", tool_use_id: "tool-path",
  tool_name: "Bash", tool_input: { command: "printf safe" },
}, pathEnv);
assert.equal(codexPathResolved, null, "installed Codex adapter must resolve the one shepherd CLI from PATH");
const missingEnv = { ...env, SHEPHERD_COMPONENT_MODULE: join(temp, "missing-component.mjs") };
const missingClaude = spawnSync(process.execPath, [claudeGuardScript], {
  cwd: process.cwd(), env: missingEnv, encoding: "utf8", input: JSON.stringify({
    hook_event_name: "PreToolUse", session_id: "session-a", tool_name: "Bash", tool_input: { command: "true" },
  }),
});
assert.equal(missingClaude.status, 0);
assert.equal(JSON.parse(missingClaude.stdout).hookSpecificOutput.permissionDecision, "deny");
const missingCodex = spawnSync(process.execPath, [codexHookScript], {
  cwd: process.cwd(), env: missingEnv, encoding: "utf8", input: JSON.stringify({
    hook_event_name: "PreToolUse", session_id: "session-a", tool_name: "Bash", tool_input: { command: "true" },
  }),
});
assert.equal(missingCodex.status, 0);
assert.equal(JSON.parse(missingCodex.stdout).hookSpecificOutput.permissionDecision, "deny");

const piProbeScript = fileURLToPath(new URL("./test-active-pi.mjs", import.meta.url));
const piProbe = spawnSync(process.execPath, [piProbeScript, pathToFileURL(modulePath).href, piExtension], {
  cwd: process.cwd(), env, encoding: "utf8",
});
assert.equal(piProbe.status, 0, piProbe.stderr || piProbe.stdout);
const piNativeProbe = spawnSync(
  process.execPath,
  [piProbeScript, pathToFileURL(modulePath).href, piExtension, "native"],
  { cwd: process.cwd(), env: pathEnv, encoding: "utf8" },
);
assert.equal(piNativeProbe.status, 0, piNativeProbe.stderr || piNativeProbe.stdout);
const piProvider = {
  capabilities: () => ({ primitive: "subagent-provider", version: "pi-subagents/2.3.0", limits: { maxConcurrent: 4 } }),
  spawn: async () => ({ lifecycle: "started", agentId: "agent-a", agentType: "shepherd:engineer", model: "model-a" }),
  resume: async (agentId) => ({ lifecycle: "resumed", agentId: "agent-b", agentType: "shepherd:engineer", model: "model-a", sourceAgentId: agentId }),
  stop: async (agentId) => ({ lifecycle: "stopped", agentId, agentType: "shepherd:engineer", model: "model-a" }),
};
const piRuntime = {
  componentEngine,
  shepherdBin: dispatcher,
  cwd: process.cwd(),
  sessionId: "session-a",
  harnessVersion: "1.0",
  leaseMs: 60_000,
  expectedRevision: 1,
  role_carrier: "shepherd:engineer",
  agent_type: "shepherd:engineer",
  lane: "l1",
  write_scope: ["crates/**"],
  run: "v645",
  observedCapabilities,
  capability_source: "active-probe",
};
const piStarted = await spawnSubagent(piProvider, { task: "active Pi start probe" }, piRuntime);
assert.equal(piStarted.kind, "started");
assert.equal(piStarted.dispatch.agent_id, "agent-a");
const piResumed = await resumeSubagent(piProvider, "agent-a", piRuntime);
assert.equal(piResumed.kind, "resumed");
assert.equal(piResumed.request.source_agent_id, "agent-a");
assert.equal(piResumed.request.next.agent_id, "agent-b");
assert.equal(piResumed.dispatch.record.agent_id, "agent-b");
const piStopped = await stopSubagent(piProvider, "agent-a", piRuntime);
assert.equal(piStopped.kind, "stopped");
assert.equal(piStopped.dispatch.state, "stopped");
console.log("ok: generated Component correlated Pi start, resume, and durable stop exchanges");
console.log("ok: active Claude, Codex, and Pi paths loaded the staged component and exercised hooks");
