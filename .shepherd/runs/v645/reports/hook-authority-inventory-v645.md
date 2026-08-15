# v6.4.5 registered hook authority inventory

Canonical machine-readable source:
`python3 hooks/scripts/hook_authority_inventory.py --json`.

The strict result is green: **3 thin native/component adapters, 6
telemetry-only adapters, 0 independent policy/state authorities, and 0
nondeterministic agent policies.**

| Class | Registered target | Registration |
| --- | --- | --- |
| Thin component/native adapter | `packages/harness-claude/hooks/dispatch-lifecycle.mjs` | SessionStart, SubagentStart, SubagentStop |
| Thin component/native adapter | `packages/harness-claude/hooks/guard-eval.mjs` | PreToolUse: Write, Edit, Bash, Agent, Workflow |
| Thin native adapter | `hooks/scripts/seed_preflight_check.sh` | PreToolUse: Write |
| Telemetry-only | `hooks/scripts/agent_insight_capture.sh` | PostToolUse: Agent, Task |
| Telemetry-only | `hooks/scripts/bash_post.sh` | PostToolUse: Bash |
| Telemetry-only | `hooks/scripts/cwd_changed.sh` | CwdChanged |
| Telemetry-only | `hooks/scripts/discovery_capture.sh` | PostToolUse: Agent, Task |
| Telemetry-only | `hooks/scripts/precompact_snapshot.sh` | PreCompact |
| Telemetry-only | `hooks/scripts/subagent_telemetry.sh` | SubagentStop |

## Strict closure

The inventory refuses a registered hook when any of the following is true:

- an entry is `type: agent` or lacks an explicit classification;
- a command invokes `shctx`, `services/cli`, or a
  plugin-local `bin/shepherd` launcher;
- a thin adapter directly invokes Python or SQLite;
- telemetry produces a deny/verdict or writes policy/state with SQLite;
- a registered target has no exact entry in the inventory.

Read-only SQLite inspection in the compaction snapshot remains telemetry
evidence only. It cannot block, deny, or update registry state.

## Native boundary

The two Node entries delegate lifecycle and guard decisions to the shipped
component/native surface. The seed shell adapter only invokes
`shepherd seed verify <path>`; without jq it fails closed because it
is a PreToolUse policy adapter. All remaining shell registrations either
record run-scoped evidence or skip with a diagnostic if jq is unavailable.

This inventory intentionally does not claim native parity for retired shell
policies. Those behaviors are absent from the active registry rather than
silently represented as no-op enforcement.

## Evidence

~~~text
python3 -m py_compile hooks/scripts/hook_authority_inventory.py
python3 hooks/scripts/hook_authority_inventory.py --self-test
python3 hooks/scripts/hook_authority_inventory.py --check
python3 hooks/scripts/hook_authority_inventory.py --strict
~~~

All four commands passed in this lane.
