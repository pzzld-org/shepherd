# Probe: Teammate Workflow tool access

Session: shepherd-probe-v645-wf@session-892c33c2 (agent-type shepherd:conductor)

## Environment

```
TMUX=/private/tmp/tmux-501/claude-swarm-21575,31409,0
PID=32657 PPID=31434
claude-swarm: 1 windows (created Thu Aug 13 16:42:59 2026)
  PID  PPID COMMAND
31434 31409 /Users/jo3/.local/share/claude/versions/2.1.229 --agent-id shepherd-probe-v645-wf@session-892c33c2 --agent-name shepherd-probe-v645-wf --team-name session-892c33c2 --agent-color blue --parent-session-id 584d4292-bcf5-4461-ae9e-ff122471bc30 --agent-type shepherd:conductor --dangerously-skip-permissions --effort xhigh --model sonnet
```

Notes: `TMUX` is set (running inside a tmux session named `claude-swarm`), confirming this is a real Agent-Teams teammate process, not an in-context Agent-tool subagent. `PPID` resolves to a `claude` binary invocation carrying `--agent-type shepherd:conductor`, `--team-name session-892c33c2`, `--parent-session-id 584d4292-bcf5-4461-ae9e-ff122471bc30` — native teammate-spawn flags.

## Tool inventory

Tools with full schemas visible directly in my tool definitions at session start:

```
Agent
Bash
Read
Skill
ToolSearch
Workflow
ScheduleWakeup
```

Tools named (but deferred — schema not loaded until ToolSearch'd) in a system-reminder surfaced after my first Bash call:

```
SendMessage
TaskCreate
TaskGet
TaskList
TaskUpdate
WebFetch
WebSearch
```

Also noted: an MCP server `MCP_DOCKER` reported "still connecting" (its `mcp__MCP_DOCKER__*` tools not yet enumerated).

Total distinct tool names visible to me across both categories: 14 (`Agent`, `Bash`, `Read`, `Skill`, `ToolSearch`, `Workflow`, `ScheduleWakeup`, `SendMessage`, `TaskCreate`, `TaskGet`, `TaskList`, `TaskUpdate`, `WebFetch`, `WebSearch`). This matches the `shepherd:conductor` agent-type tool list from the system reminder's agent roster **except** that list also names `Glob` and `Grep`, which I do NOT see anywhere in my own visible tool set (neither as a direct schema nor as a deferred-tool name). Reporting this discrepancy honestly rather than omitting it — it is not something the probe asked me to resolve.

`Workflow` is present verbatim in my directly-defined tool schema (not inferred, not via ToolSearch).

WORKFLOW-TOKEN: PRESENT

## Workflow call attempt

Tool invoked: `Workflow`

Call:
```js
export const meta = {
  name: 'teammate-workflow-probe',
  description: 'One-agent probe proving a teammate can drive a Dynamic Workflow',
  phases: [{ title: 'Probe', detail: 'single haiku agent' }],
}
phase('Probe')
const r = await agent('Reply with exactly the token PROBE-OK and nothing else.', {
  agentType: 'shepherd:worker',
  model: 'haiku',
  label: 'probe',
})
return { got: r }
```

Full result (verbatim tool output):
```
Workflow launched in background. Task ID: wkcy7agb2
Summary: One-agent probe proving a teammate can drive a Dynamic Workflow
Transcript dir: /Users/jo3/.claude/projects/-Users-jo3-src-fl03-shepherd/337d245e-0708-413b-bb21-f2ac46d27f6b/subagents/workflows/wf_020292db-fef
Script file: /Users/jo3/.claude/projects/-Users-jo3-src-fl03-shepherd/337d245e-0708-413b-bb21-f2ac46d27f6b/workflows/scripts/teammate-workflow-probe-wf_020292db-fef.js
(Edit this file with Write/Edit and re-invoke Workflow with {scriptPath: "/Users/jo3/.claude/projects/-Users-jo3-src-fl03-shepherd/337d245e-0708-413b-bb21-f2ac46d27f6b/workflows/scripts/teammate-workflow-probe-wf_020292db-fef.js"} to iterate without resending the script.)
Run ID: wf_020292db-fef
To resume after editing the script: Workflow({scriptPath: "/Users/jo3/.claude/projects/-Users-jo3-src-fl03-shepherd/337d245e-0708-413b-bb21-f2ac46d27f6b/workflows/scripts/teammate-workflow-probe-wf_020292db-fef.js", resumeFromRunId: "wf_020292db-fef"}) — completed agents return cached results (cached results may themselves be empty — inspect journal.jsonl before assuming there is something to recover).

You will be notified when it completes. Use /workflows to watch live progress.
```

No error was returned; the runtime accepted the script, assigned Task ID `wkcy7agb2` / Run ID `wf_020292db-fef`, and launched it in the background (not yet observed to completion as of this report — the probe brief only asked whether the call itself was accepted or rejected, not to await/verify the inner agent's `PROBE-OK` output).

WORKFLOW-CALL: ACCEPTED

## Post-hoc: workflow completion (arrived after this report was first written)

The background task notified completion before this report was finalized. Verbatim:

```
<task-id>wkcy7agb2</task-id>
<status>completed</status>
<summary>Dynamic workflow "One-agent probe proving a teammate can drive a Dynamic Workflow" completed</summary>
<result>{"got":"PROBE-OK"}</result>
<usage><agent_count>1</agent_count><agents_done>1</agents_done><agents_error>0</agents_error><agents_skipped>0</agents_skipped><agents_empty_result>0</agents_empty_result><subagent_tokens>14987</subagent_tokens><tool_uses>0</tool_uses><duration_ms>5085</duration_ms></usage>
```

The inner `shepherd:worker` haiku agent returned exactly `PROBE-OK`, and the workflow's `return { got: r }` carried it through. End-to-end confirmation: this teammate session compiled and dispatched a real Dynamic Workflow, it ran a real subagent, and the result flowed back — not just an accepted-but-unverified call.
