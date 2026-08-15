#!/usr/bin/env node

let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const request = JSON.parse(input);
  const operation = process.argv[3];
  if (operation === "bind-root") {
    process.stdout.write(JSON.stringify({
      schema: "shepherd.root-session/1",
      project_id: "0192f6e8-7b2c-7abc-8def-0123456789ab",
      run: "v645",
      harness: request.harness,
      session_id: request.session_id,
      role: (request.role_carrier ?? "shepherd:shepherd").replace(/^shepherd:/, ""),
      mode: request.mode,
      bound_at: 1,
      expires_at: 1 + request.lease_ms,
    }));
    return;
  }
  process.stdout.write(JSON.stringify({
    schema: "shepherd.identity-resolution/1",
    project_id: "0192f6e8-7b2c-7abc-8def-0123456789ab",
    run: "v645",
    harness: request.harness,
    agent_id: request.agent_id ?? "agent-a",
    agent_type: request.agent_type ?? "engineer",
    role: "engineer",
    lane: "l1",
    session_id: request.session_id,
    write_scope: ["crates/**"],
    write_paths: ["crates/core/src/lib.rs"],
    path_in_write_scope: true,
    tool_use_id: request.tool_use_id ?? "tool-a",
    mode: "execution",
    state: "active",
  }));
});
