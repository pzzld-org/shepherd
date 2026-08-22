import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import test from "node:test";
import { tmpdir } from "node:os";
import { join } from "node:path";

import shepherdGuardExtension from "../src/extension.mjs";

const fixtureDir = mkdtempSync(join(tmpdir(), "shepherd-pi-child-lifecycle-"));
const dispatcher = join(fixtureDir, "shepherd-native.mjs");
const requestLog = join(fixtureDir, "requests.log");
const stateFile = join(fixtureDir, "state.json");
writeFileSync(stateFile, "{}\n");
writeFileSync(dispatcher, `#!/usr/bin/env node
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const operation = process.argv[3];
  const request = JSON.parse(input);
  appendFileSync(${JSON.stringify(requestLog)}, JSON.stringify({ operation, request }) + "\\n");
  const statePath = ${JSON.stringify(stateFile)};
  const state = JSON.parse(readFileSync(statePath, "utf8"));
  const save = () => writeFileSync(statePath, JSON.stringify(state));
  if (operation === "bind-root") {
    process.stdout.write(JSON.stringify({
      schema: "shepherd.root-session/1", project_id: "0192f6e8-7b2c-7abc-8def-0123456789ab",
      run: "v656", harness: "pi", session_id: request.session_id,
      role: request.role_carrier, mode: request.mode, bound_at: 1, expires_at: 86400001,
    }));
    return;
  }
  if (operation === "start") {
    if (request.session_id.includes("publish-fail")) {
      process.stderr.write("simulated child publication failure");
      process.exitCode = 1;
      return;
    }
    const mismatch = request.session_id.includes("mismatch");
    state[request.agent_id] = {
      run: request.run ?? "v656", carrier: request.agent_type,
      role: request.role_carrier.slice("shepherd:".length), session: request.session_id,
      revision: 1, state: "active", failStops: request.session_id.includes("stop-fail") ? 3 : 0,
    };
    save();
    process.stdout.write(JSON.stringify(record(request, state[request.agent_id], mismatch ? "pi-subagent-mismatched" : request.agent_id)));
    return;
  }
  const stored = state[request.agent_id];
  if (!stored) return fail("missing active dispatch record");
  if (stored.carrier !== request.agent_type || stored.session !== request.session_id
      || (request.role_carrier && stored.carrier !== request.role_carrier)) {
    return fail("native dispatch identity mismatch");
  }
  if (stored.state !== "active") return fail("ERROR: dispatch record is terminal: stopped");
  if (operation === "resolve") {
    process.stdout.write(JSON.stringify({
      schema: "shepherd.identity-resolution/1", project_id: "0192f6e8-7b2c-7abc-8def-0123456789ab",
      run: stored.run, harness: "pi", agent_id: request.agent_id, agent_type: stored.carrier,
      role: stored.role, lane: null, session_id: stored.session, write_scope: [".shepherd/runs/**"],
      capabilities: capabilities(stored.role), tool_call_id: request.tool_call_id ?? null, mode: null,
      write_paths: request.tool_name === "Write" ? [request.tool_input.path] : [],
      path_in_write_scope: request.tool_name === "Write" ? true : null,
    }));
    return;
  }
  if (operation === "stop") {
    if (stored.failStops > 0) {
      stored.failStops -= 1;
      save();
      return fail("simulated stop failure");
    }
    if (request.expected_revision !== stored.revision) return fail("revision conflict");
    stored.state = "stopped";
    stored.revision += 1;
    save();
    process.stdout.write(JSON.stringify(record(request, stored, request.agent_id)));
    return;
  }
  fail("unsupported operation");
});
function capabilities(role = "engineer") {
  const byRole = {
    auditor: ["code-intelligence", "read", "report-write", "search", "shell", "skill-load", "subagent-provider", "tool-discovery"],
    conductor: ["dispatch", "message-peer", "read", "schedule-wakeup", "search", "shell", "skill-load", "subagent-provider", "task-tracking", "tool-discovery", "web-research"],
    critic: ["read", "search", "shell", "skill-load", "subagent-provider"],
    discovery: ["read", "report-write", "search", "shell", "skill-load", "subagent-provider", "tool-discovery", "web-research"],
    engineer: ["dispatch", "message-peer", "read", "search", "shell", "skill-load", "subagent-provider", "tool-discovery", "write"],
    worker: ["read", "search", "shell", "skill-load", "subagent-provider", "tool-discovery", "write"],
  };
  const observed = byRole[role] ?? byRole.engineer;
  return { declared: observed, observed, present: observed, missing: [], missing_required: [], missing_optional: [], extra: [], forbidden_extra: [], source: "pi-child-environment", harness_version: "unknown", provider_version: null, probed_at: 0 };
}
function record(request, stored, agentId) {
  return {
    schema: "shepherd.dispatch/3", revision: stored.revision,
    project_id: "0192f6e8-7b2c-7abc-8def-0123456789ab", run: stored.run,
    harness: "pi", session_id: stored.session, agent_id: agentId,
    agent_type: stored.carrier, role: stored.role, lane: null, parent_agent_id: request.parent_agent_id ?? null,
    write_scope: [".shepherd/runs/**"], model: null, capabilities: capabilities(stored.role), state: stored.state,
    started_at: 1, lease_expires_at: 86400001, stopped_at: stored.state === "stopped" ? 2 : null,
    result_artifact: null, resumes_agent_id: null,
  };
}
function fail(message) { process.stderr.write(message); process.exitCode = 1; }
`);
chmodSync(dispatcher, 0o755);

function childEnvironment(overrides = {}) {
  return {
    PI_SUBAGENT_CHILD: "1",
    PI_SUBAGENT_RUN_ID: "child-run",
    PI_SUBAGENT_CHILD_AGENT: "shepherd:engineer",
    PI_SUBAGENT_CHILD_INDEX: "2",
    ...overrides,
  };
}

async function register(environment = {}, allTools = [{ name: "subagent" }], options = {}) {
  const handlers = {};
  const eventHandlers = {};
  const pi = {
    getActiveTools() { return ["read", "write", "edit", "bash"]; },
    getAllTools() {
      if (allTools instanceof Error) throw allTools;
      return allTools;
    },
    on(event, handler) { handlers[event] = handler; },
    events: {
      on(event, handler) {
        eventHandlers[event] = handler;
        return () => { delete eventHandlers[event]; };
      },
    },
  };
  await shepherdGuardExtension(pi, {
    componentModule: process.env.SHEPHERD_COMPONENT_MODULE,
    shepherdBin: dispatcher,
    environment,
    ...options,
  });
  return { handlers, eventHandlers };
}

function context(sessionId = "pi-parent-session") {
  return { cwd: process.cwd(), sessionManager: { getSessionId: () => sessionId } };
}

function requests() {
  try {
    return readFileSync(requestLog, "utf8").trim().split("\n").filter(Boolean).map(JSON.parse);
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
}

function state() {
  return JSON.parse(readFileSync(stateFile, "utf8"));
}

function agentId(runId, index) {
  return `pi-subagent-${createHash("sha256").update(`${runId}\0${index}`).digest("hex")}`;
}

function sessionFile(sessionId, name = sessionId, header = { type: "session", id: sessionId }) {
  const path = join(fixtureDir, `${name}.jsonl`);
  writeFileSync(path, `${JSON.stringify(header)}\n{"type":"message"}\n`);
  return path;
}

function seed(runId, index, carrier, sessionId, overrides = {}) {
  const current = state();
  current[agentId(runId, index)] = {
    run: "v656", carrier, role: carrier.slice("shepherd:".length), session: sessionId,
    revision: 1, state: "active", failStops: 0, ...overrides,
  };
  writeFileSync(stateFile, JSON.stringify(current));
  return sessionFile(sessionId, `${runId}-${index}-${sessionId}`);
}

function operationsFor(runId, index) {
  const id = agentId(runId, index);
  return requests().filter(({ request }) => request.agent_id === id).map(({ operation }) => operation);
}

async function shutdown(handlers, id = "pi-parent-session") {
  await handlers.session_shutdown({ type: "session_shutdown", reason: "quit" }, context(id));
}

test("parent terminal observers use only Pi terminal public surfaces", async () => {
  const { handlers, eventHandlers } = await register();
  assert.equal(typeof handlers.tool_result, "function");
  assert.equal(typeof eventHandlers["subagent:foreground-complete"], "function");
  assert.equal(typeof eventHandlers["subagent:async-complete"], "function");
  assert.equal(eventHandlers["subagent:async-started"], undefined);
  await shutdown(handlers);
  assert.deepEqual(eventHandlers, {});
});

test("registered but inactive generic subagent provider is accepted", async () => {
  const before = requests().length;
  const { handlers } = await register();
  await handlers.session_start({ reason: "startup" }, context("inactive-provider-root"));
  assert.equal(requests().slice(before).some(({ operation }) => operation === "bind-root"), true);
  await shutdown(handlers, "inactive-provider-root");
});

test("absent or malformed generic subagent provider blocks mutation with exact remediation", async () => {
  const remediation = "Pi subagent provider unavailable. Run `pi install npm:pi-subagents`, then restart Pi.";
  for (const tools of [[], null, {}, new Error("malformed getAllTools"), [{ description: "missing name" }], [{ name: "Subagent" }]]) {
    const { handlers } = await register({}, tools);
    await handlers.session_start({ reason: "startup" }, context("provider-negative-root"));
    for (const toolName of ["write", "edit", "bash"]) {
      const verdict = await handlers.tool_call(
        { toolName, toolCallId: `provider-${toolName}`, input: { path: "x", command: "true" } },
        context("provider-negative-root"),
      );
      assert.deepEqual(verdict, { block: true, reason: remediation });
    }
    await shutdown(handlers, "provider-negative-root");
  }
});

test("root and child sessions use the same generic provider probe", async () => {
  const remediation = "Pi subagent provider unavailable. Run `pi install npm:pi-subagents`, then restart Pi.";
  const { handlers } = await register(childEnvironment({ PI_SUBAGENT_RUN_ID: "provider-child" }), []);
  await handlers.session_start({ reason: "startup" }, context("provider-child-session"));
  const verdict = await handlers.tool_call(
    { toolName: "write", toolCallId: "provider-child-write", input: { path: "x" } },
    context("provider-child-session"),
  );
  assert.deepEqual(verdict, { block: true, reason: remediation });
  assert.deepEqual(operationsFor("provider-child", 2), []);
  await shutdown(handlers, "provider-child-session");
});

test("Component canonical capabilities allow worker mutation but block worker and critic dispatch", async () => {
  const noDispatch = (role) => `Pi Component role ${role} no-dispatch contract blocks subagent`;
  for (const role of ["worker", "critic"]) {
    const runId = `no-dispatch-${role}`;
    const sessionId = `no-dispatch-${role}-session`;
    const { handlers } = await register(childEnvironment({
      PI_SUBAGENT_RUN_ID: runId,
      PI_SUBAGENT_CHILD_AGENT: `shepherd:${role}`,
    }));
    await handlers.session_start({ reason: "startup" }, context(sessionId));
    if (role === "worker") {
      const writeVerdict = await handlers.tool_call(
        { toolName: "write", toolCallId: "worker-write", input: { path: ".shepherd/runs/worker-marker" } },
        context(sessionId),
      );
      assert.equal(writeVerdict, undefined, "a registered transport must not remove canonical worker write authority");
    }
    const before = requests().length;
    const dispatchVerdict = await handlers.tool_call(
      { toolName: "subagent", toolCallId: `${role}-subagent`, input: { agent: "shepherd:worker" } },
      context(sessionId),
    );
    assert.deepEqual(dispatchVerdict, { block: true, reason: noDispatch(role) });
    assert.equal(requests().length, before, "no-dispatch must block before provider or native execution");
    await shutdown(handlers, sessionId);
  }
});

test("managed engineer and conductor retain canonical dispatch authority", async () => {
  for (const role of ["engineer", "conductor"]) {
    const runId = `dispatch-${role}`;
    const sessionId = `dispatch-${role}-session`;
    const { handlers } = await register(childEnvironment({
      PI_SUBAGENT_RUN_ID: runId,
      PI_SUBAGENT_CHILD_AGENT: `shepherd:${role}`,
    }));
    await handlers.session_start({ reason: "startup" }, context(sessionId));
    const verdict = await handlers.tool_call(
      { toolName: "subagent", toolCallId: `${role}-subagent`, input: { agent: "shepherd:worker" } },
      context(sessionId),
    );
    assert.equal(verdict, undefined);
    await shutdown(handlers, sessionId);
  }
});

test("absent provider blocks synthetic subagent calls before role authorization", async () => {
  const remediation = "Pi subagent provider unavailable. Run `pi install npm:pi-subagents`, then restart Pi.";
  const { handlers } = await register(childEnvironment({
    PI_SUBAGENT_RUN_ID: "no-provider-worker",
    PI_SUBAGENT_CHILD_AGENT: "shepherd:worker",
  }), []);
  await handlers.session_start({ reason: "startup" }, context("no-provider-worker-session"));
  const before = requests().length;
  const verdict = await handlers.tool_call(
    { toolName: "subagent", toolCallId: "no-provider-worker-subagent", input: { agent: "shepherd:worker" } },
    context("no-provider-worker-session"),
  );
  assert.deepEqual(verdict, { block: true, reason: remediation });
  assert.equal(requests().length, before);
  await shutdown(handlers, "no-provider-worker-session");
});

test("component and child startup failures block subagent before provider execution", async () => {
  const unavailable = await register({}, [{ name: "subagent" }], {
    componentModule: join(fixtureDir, "missing-component.mjs"),
  });
  await unavailable.handlers.session_start({ reason: "startup" }, context("component-unavailable"));
  let before = requests().length;
  let verdict = await unavailable.handlers.tool_call(
    { toolName: "subagent", toolCallId: "component-unavailable-subagent", input: { agent: "shepherd:worker" } },
    context("component-unavailable"),
  );
  assert.equal(verdict.block, true);
  assert.match(verdict.reason, /^Pi component unavailable:/);
  assert.equal(requests().length, before);
  await shutdown(unavailable.handlers, "component-unavailable");

  const failed = await register(childEnvironment({ PI_SUBAGENT_RUN_ID: "startup-failed" }));
  await failed.handlers.session_start({ reason: "startup" }, context("publish-fail"));
  before = requests().length;
  verdict = await failed.handlers.tool_call(
    { toolName: "subagent", toolCallId: "startup-failed-subagent", input: { agent: "shepherd:worker" } },
    context("publish-fail"),
  );
  assert.equal(verdict.block, true);
  assert.match(verdict.reason, /^Pi SessionStart binding failed closed \(startup\):/);
  assert.equal(requests().length, before);
  await shutdown(failed.handlers, "publish-fail");
});

test("malformed and unmanaged children cannot reach synthetic subagent transport", async () => {
  for (const [name, environment, reason] of [
    ["malformed", childEnvironment({ PI_SUBAGENT_CHILD_INDEX: "bad" }), /^Pi child environment failed closed:/],
    ["unmanaged", childEnvironment({ PI_SUBAGENT_CHILD_AGENT: "reviewer" }), /^non-Shepherd Pi child is not a Shepherd dispatch$/],
  ]) {
    const { handlers } = await register(environment);
    const sessionId = `${name}-subagent-child`;
    await handlers.session_start({ reason: "startup" }, context(sessionId));
    const before = requests().length;
    const verdict = await handlers.tool_call(
      { toolName: "subagent", toolCallId: `${name}-child-subagent`, input: { agent: "shepherd:worker" } },
      context(sessionId),
    );
    assert.equal(verdict.block, true);
    assert.match(verdict.reason, reason);
    assert.equal(requests().length, before);
    await shutdown(handlers, sessionId);
  }
});

test("attached success and terminal failures resolve exact children then stop", async () => {
  const { handlers } = await register();
  const runId = "attached-run";
  const results = ["success", "failed", "interrupted", "signalled", "timed-out", "manual-stop"].map((kind, index) => ({
    index,
    agent: "shepherd:engineer",
    sessionFile: seed(runId, index, "shepherd:engineer", `attached-${kind}`),
    ...(kind === "failed" ? { error: "failed" } : {}),
    ...(kind === "interrupted" ? { interrupted: true } : {}),
    ...(kind === "signalled" ? { processSignal: "SIGTERM" } : {}),
    ...(kind === "timed-out" ? { timedOut: true } : {}),
    ...(kind === "manual-stop" ? { stopped: true } : {}),
  }));
  handlers.tool_result({ toolName: "subagent", details: { runId, results } }, context());
  for (let index = 0; index < results.length; index += 1) {
    assert.deepEqual(operationsFor(runId, index), ["resolve", "stop"]);
    assert.equal(state()[agentId(runId, index)].revision, 2);
  }
  await shutdown(handlers);
});

test("attached workflow uses each explicit child runId instead of its carrier call id", async () => {
  const { handlers } = await register();
  const childRun = "workflow-child-run";
  const file = seed(childRun, 0, "shepherd:auditor", "workflow-child-session");
  handlers.tool_result({
    toolName: "subagent",
    details: {
      runId: "workflow-carrier-call",
      results: [{ index: 0, agent: "shepherd:auditor", sessionFile: file }],
      workflow: { value: [{ runId: childRun, results: [{ index: 0, agent: "shepherd:auditor", sessionFile: file }] }] },
    },
  }, context());
  assert.deepEqual(operationsFor(childRun, 0), ["resolve", "stop"]);
  assert.deepEqual(operationsFor("workflow-carrier-call", 0), []);
  await shutdown(handlers);
});

test("detached foreground waits for foreground-complete", async () => {
  const { handlers, eventHandlers } = await register();
  const file = seed("detached-run", 3, "shepherd:auditor", "detached-session");
  handlers.tool_result({
    toolName: "subagent",
    details: { runId: "detached-run", results: [{ index: 3, agent: "shepherd:auditor", sessionFile: file, detached: true }] },
  }, context());
  assert.deepEqual(operationsFor("detached-run", 3), []);
  eventHandlers["subagent:foreground-complete"]({
    runId: "detached-run", taskIndex: 3, agent: "shepherd:auditor", sessionFile: file, cwd: process.cwd(),
  });
  assert.deepEqual(operationsFor("detached-run", 3), ["resolve", "stop"]);
  await shutdown(handlers);
});

test("async completion uses explicit child run IDs and indexes out of array order", async () => {
  const { handlers, eventHandlers } = await register();
  const sevenRun = "async-seven-run";
  const twoRun = "async-two-run";
  const seven = seed(sevenRun, 7, "shepherd:discovery", "async-seven");
  const two = seed(twoRun, 2, "shepherd:critic", "async-two");
  eventHandlers["subagent:async-complete"]({
    runId: "async-container-run",
    cwd: process.cwd(),
    results: [
      { runId: sevenRun, index: 7, agent: "shepherd:discovery", artifactPaths: { outputPath: seven } },
      { runId: twoRun, index: 2, agent: "shepherd:critic", sessionFile: two },
    ],
  });
  assert.deepEqual(operationsFor(sevenRun, 7), ["resolve", "stop"]);
  assert.deepEqual(operationsFor(twoRun, 2), ["resolve", "stop"]);
  assert.deepEqual(operationsFor("async-container-run", 0), []);
  await shutdown(handlers);
});

test("duplicate and child-local-first terminals are exact idempotent closure", async () => {
  const { handlers, eventHandlers } = await register();
  const file = seed("duplicate-run", 1, "shepherd:engineer", "duplicate-session");
  const event = { runId: "duplicate-run", taskIndex: 1, agent: "shepherd:engineer", sessionFile: file };
  eventHandlers["subagent:foreground-complete"](event);
  eventHandlers["subagent:foreground-complete"](event);
  assert.deepEqual(operationsFor("duplicate-run", 1), ["resolve", "stop"]);

  const stoppedFile = seed("local-first-run", 4, "shepherd:auditor", "local-first-session", { state: "stopped", revision: 2 });
  eventHandlers["subagent:foreground-complete"]({
    runId: "local-first-run", taskIndex: 4, agent: "shepherd:auditor", sessionFile: stoppedFile,
  });
  assert.deepEqual(operationsFor("local-first-run", 4), ["resolve"]);
  const verdict = await handlers.tool_call({ toolName: "write", toolCallId: "after-local", input: { path: "x" } }, context());
  assert.equal(verdict?.reason?.includes("terminal lifecycle remains pending"), false);
  await shutdown(handlers);
});

test("failed stop remains pending, blocks mutation, and retries at safe boundaries", async () => {
  const { handlers, eventHandlers } = await register();
  await handlers.session_start({ reason: "startup" }, context());
  const file = seed("retry-run", 0, "shepherd:engineer", "retry-session", { failStops: 2 });
  eventHandlers["subagent:foreground-complete"]({
    runId: "retry-run", taskIndex: 0, agent: "shepherd:engineer", sessionFile: file,
  });
  const blocked = await handlers.tool_call({ toolName: "write", toolCallId: "blocked", input: { path: "x" } }, context());
  assert.equal(blocked.block, true);
  assert.match(blocked.reason, /remains pending|simulated stop failure/);
  assert.deepEqual(operationsFor("retry-run", 0), ["resolve", "stop", "stop"]);
  await handlers.agent_settled({}, context());
  assert.equal(state()[agentId("retry-run", 0)].state, "stopped");
  await shutdown(handlers);
});

test("uncorrelated terminal evidence never blocks mutation", async () => {
  for (const [runId, index, file] of [
    ["missing-run", 0, sessionFile("missing-session")],
    ["mismatch-run", 1, seed("mismatch-run", 1, "shepherd:engineer", "actual-session")],
  ]) {
    const { handlers, eventHandlers } = await register();
    await handlers.session_start({ reason: "startup" }, context());
    eventHandlers["subagent:foreground-complete"]({
      runId, taskIndex: index, agent: "shepherd:engineer",
      sessionFile: runId === "mismatch-run" ? sessionFile("forged-session", "forged") : file,
    });
    assert.equal(operationsFor(runId, index).includes("stop"), false);
    const verdict = await handlers.tool_call(
      { toolName: "write", toolCallId: `after-${runId}`, input: { path: "docs/report.md" } },
      context(),
    );
    assert.equal(verdict?.reason?.includes("terminal lifecycle"), false);
    assert.equal(verdict?.reason?.includes("observed child shutdown"), false);
    await shutdown(handlers);
  }
});

test("forged duplicate cannot replace an exact correlated pending stop", async () => {
  const { handlers, eventHandlers } = await register();
  await handlers.session_start({ reason: "startup" }, context());
  const file = seed("exact-pending-run", 4, "shepherd:engineer", "exact-pending-session", { failStops: 1 });
  eventHandlers["subagent:foreground-complete"]({
    runId: "exact-pending-run", taskIndex: 4, agent: "shepherd:engineer", sessionFile: file,
  });
  eventHandlers["subagent:foreground-complete"]({
    runId: "exact-pending-run", taskIndex: 4, agent: "shepherd:engineer",
    sessionFile: sessionFile("forged-session", "forged-exact-pending"),
  });
  const verdict = await handlers.tool_call(
    { toolName: "write", toolCallId: "retry-exact-pending", input: { path: "docs/report.md" } },
    context(),
  );
  assert.equal(state()[agentId("exact-pending-run", 4)].state, "stopped");
  assert.deepEqual(operationsFor("exact-pending-run", 4), ["resolve", "stop", "stop"]);
  assert.equal(verdict?.reason?.includes("terminal lifecycle"), false);
  await shutdown(handlers);
});

test("pre-correlation retries are bounded, deduplicated, and nonblocking", async () => {
  const { handlers, eventHandlers } = await register();
  await handlers.session_start({ reason: "startup" }, context());
  const event = {
    runId: "bounded-missing-run", taskIndex: 8, agent: "shepherd:engineer",
    sessionFile: sessionFile("bounded-missing-session"),
  };
  eventHandlers["subagent:foreground-complete"](event);
  eventHandlers["subagent:foreground-complete"](event);
  for (let attempt = 0; attempt < 10; attempt += 1) await handlers.agent_settled({}, context());
  assert.equal(operationsFor("bounded-missing-run", 8).length, 3);
  const verdict = await handlers.tool_call(
    { toolName: "edit", toolCallId: "after-bounded-retries", input: { path: "docs/report.md" } },
    context(),
  );
  assert.equal(verdict?.reason?.includes("terminal lifecycle"), false);
  assert.equal(operationsFor("bounded-missing-run", 8).length, 3);
  await shutdown(handlers);
});

test("non-Shepherd and non-dispatchable Shepherd carriers are ignored", async () => {
  const { handlers } = await register();
  const before = requests().length;
  for (const [index, agent] of ["reviewer", "shepherd:shepherd", "shepherd:planter"].entries()) {
    handlers.tool_result({
      toolName: "subagent",
      details: { runId: "ignored-run", results: [{ index, agent, sessionFile: sessionFile(`ignored-${index}`) }] },
    }, context());
  }
  assert.equal(requests().length, before);
  await shutdown(handlers);
});

test("unsafe session files and headers never reach native dispatch", async () => {
  const { handlers } = await register();
  const directory = join(fixtureDir, "session-dir");
  mkdirSync(directory);
  const target = sessionFile("symlink-target");
  const symlink = join(fixtureDir, "session-link.jsonl");
  symlinkSync(target, symlink);
  const oversize = join(fixtureDir, "oversize.jsonl");
  writeFileSync(oversize, `${"x".repeat(16_385)}\n`);
  const malformed = join(fixtureDir, "malformed.jsonl");
  writeFileSync(malformed, "{bad json}\n");
  const wrongType = sessionFile("wrong-type", "wrong-type", { type: "message", id: "wrong-type" });
  const invalidId = sessionFile("bad/id", "invalid-id");
  const before = requests().length;
  const files = [undefined, symlink, directory, oversize, malformed, wrongType, invalidId];
  files.forEach((file, index) => handlers.tool_result({
    toolName: "subagent",
    details: { runId: "unsafe-file-run", results: [{ index, agent: "shepherd:engineer", sessionFile: file }] },
  }, context()));
  assert.equal(requests().length, before);
  await shutdown(handlers);
});

test("session files are opened read-only, nonblocking, and without symlink following", () => {
  const source = readFileSync(new URL("../src/extension.mjs", import.meta.url), "utf8");
  assert.match(source, /constants\.O_RDONLY\s*\|\s*constants\.O_NONBLOCK\s*\|\s*\(constants\.O_NOFOLLOW \?\? 0\)/);
});

test("malformed run and index values fail closed without positional inference", async () => {
  const { handlers } = await register();
  const file = sessionFile("malformed-index-session");
  const before = requests().length;
  for (const [runId, index] of [["bad/run", 0], ["x".repeat(129), 0], ["valid-run", -1], ["valid-run", 1.5], ["valid-run", 1_000_000_000], ["valid-run", undefined]]) {
    handlers.tool_result({
      toolName: "subagent", details: { runId, results: [{ index, agent: "shepherd:engineer", sessionFile: file }] },
    }, context());
  }
  assert.equal(requests().length, before);
  await shutdown(handlers);
});

test("nested parent identity comes only from validated parent path", async () => {
  const parent = { runId: "parent-run", stepIndex: 5, agent: "shepherd:engineer" };
  const child = { runId: "nested-run", stepIndex: 2, agent: "shepherd:auditor" };
  const environment = childEnvironment({
    PI_SUBAGENT_RUN_ID: child.runId,
    PI_SUBAGENT_CHILD_INDEX: String(child.stepIndex),
    PI_SUBAGENT_PARENT_DEPTH: "2",
    PI_SUBAGENT_PARENT_PATH: JSON.stringify([parent, child]),
    PI_SUBAGENT_PARENT_RUN_ID: "forged-parent",
    PI_SUBAGENT_PARENT_CHILD_INDEX: "0",
  });
  const { handlers } = await register(environment);
  await handlers.session_start({ reason: "startup" }, context("nested-positive"));
  const start = requests().find(({ operation, request }) => operation === "start" && request.session_id === "nested-positive");
  assert.ok(start, "managed child session_start must issue a native start request");
  assert.equal(start.request.parent_agent_id, agentId(parent.runId, parent.stepIndex));
  assert.equal(start.request.capability_source, "pi-child-environment");
  await shutdown(handlers, "nested-positive");
});

test("malformed, truncated, self, non-integer, and mismatching ancestry fail closed", async () => {
  const child = { runId: "nested-negative", stepIndex: 2 };
  const badPaths = [
    "{bad",
    JSON.stringify([child]),
    JSON.stringify([{ runId: child.runId, stepIndex: child.stepIndex }, child]),
    JSON.stringify([{ runId: "parent", stepIndex: 1.5 }, child]),
    JSON.stringify([{ runId: "parent", stepIndex: 1 }, { runId: "other", stepIndex: 2 }]),
    undefined,
  ];
  for (const [index, path] of badPaths.entries()) {
    const { handlers } = await register(childEnvironment({
      PI_SUBAGENT_RUN_ID: child.runId,
      PI_SUBAGENT_CHILD_INDEX: String(child.stepIndex),
      PI_SUBAGENT_PARENT_DEPTH: "2",
      ...(path === undefined ? {} : { PI_SUBAGENT_PARENT_PATH: path }),
    }));
    const id = `nested-negative-${index}`;
    await handlers.session_start({ reason: "startup" }, context(id));
    assert.equal(requests().some(({ operation, request }) => operation === "start" && request.session_id === id), false);
    await shutdown(handlers, id);
  }
});

test("child terminal semantics and process listeners clean up on every path", async () => {
  const baseline = Object.fromEntries(["exit", "SIGINT", "SIGTERM"].map((name) => [name, process.listenerCount(name)]));

  const failed = await register(childEnvironment());
  await failed.handlers.session_start({ reason: "startup" }, context("publish-fail"));
  for (const name of Object.keys(baseline)) assert.equal(process.listenerCount(name), baseline[name]);
  await shutdown(failed.handlers, "publish-fail");

  const early = await register(childEnvironment({ PI_SUBAGENT_RUN_ID: "early-run" }));
  await early.handlers.session_start({ reason: "startup" }, context("early-session"));
  await early.handlers.message_end({ message: { role: "assistant", stopReason: "end_turn", content: [{ type: "text" }] } }, context("early-session"));
  assert.deepEqual(operationsFor("early-run", 2), ["start"]);
  await early.handlers.message_end({ message: { role: "assistant", stopReason: "stop", content: [{ type: "toolCall" }] } }, context("early-session"));
  assert.deepEqual(operationsFor("early-run", 2), ["start"]);
  await early.handlers.message_end({ message: { role: "assistant", stopReason: "stop", content: [{ type: "text" }] } }, context("early-session"));
  assert.deepEqual(operationsFor("early-run", 2), ["start", "stop"]);
  for (const name of Object.keys(baseline)) assert.equal(process.listenerCount(name), baseline[name]);
  await shutdown(early.handlers, "early-session");

  const stopFailure = await register(childEnvironment({ PI_SUBAGENT_RUN_ID: "listener-fail-run" }));
  await stopFailure.handlers.session_start({ reason: "startup" }, context("listener-stop-fail"));
  await stopFailure.handlers.agent_settled({}, context("listener-stop-fail"));
  for (const name of Object.keys(baseline)) {
    assert.equal(process.listenerCount(name), baseline[name], `${name} listener leaked after stop failure`);
  }
  const blocked = await stopFailure.handlers.tool_call({ toolName: "write", toolCallId: "listener-block", input: { path: "x" } }, context("listener-stop-fail"));
  assert.equal(blocked.block, true);
  await shutdown(stopFailure.handlers, "listener-stop-fail");
  for (const name of Object.keys(baseline)) assert.equal(process.listenerCount(name), baseline[name]);
});

test("malformed child environment and non-Shepherd child never publish", async () => {
  for (const environment of [
    childEnvironment({ PI_SUBAGENT_CHILD_INDEX: "bad" }),
    childEnvironment({ PI_SUBAGENT_CHILD_AGENT: "reviewer" }),
  ]) {
    const before = requests().length;
    const { handlers } = await register(environment);
    await handlers.session_start({ reason: "startup" }, context("invalid-child"));
    const verdict = await handlers.tool_call({ toolName: "write", toolCallId: "invalid", input: { path: "x" } }, context("invalid-child"));
    assert.equal(verdict.block, true);
    assert.equal(requests().length, before);
    await shutdown(handlers, "invalid-child");
  }
});
