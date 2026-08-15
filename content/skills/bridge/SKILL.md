---
name: bridge
description: "Coordinate Shepherd sessions across Claude, Codex, or Pi through shared durable artifacts. Use when dispatch, handoff, resume, or state exchange crosses harness or session boundaries."
source: skills/bridge/SKILL.md
portability: cross-harness
---

# bridge — the cross-shepherd coordination contract

Coordinate implementations without exposing harness internals. A capability that cannot
fit this contract stays adapter-local.

## The filesystem is the bus

No shared task list, cross-harness inbox, or tool-name assumption. Coordination uses
`.shepherd/runs/<run>/`: versioned `run.json`, native dispatch records, and canonical
seed/plan/lane/report/checkpoint artifacts. Cross-run knowledge lives only in
`.shepherd/ctx/`. An unknown schema version is foreign and read-only. Identifiers match
`[a-z0-9][a-z0-9-]*`; separators, `..`, absolute paths, and Unicode lookalikes are invalid.
Timestamps belong in structured state, not rendered prose.

## Content contract vs. path contract

Path agreement does not imply content agreement. Consumers trust only versioned fields or
required sections named by the contract. A file at the right path with missing required
content is invalid; reconstruct it from its canonical parent or halt before execution.

## Custody

`run.json` declares one writer per lane path and branch. Every other participant treats it
as foreign. The root session binding owns run-level state and cross-lane integration. A
non-custodian requests a change through a durable event and never force-writes.

## Dispatch envelope

Cross-harness work uses a versioned native dispatch record naming agent id/type, role,
lane, scope, acceptance, capability contract, and result path. Completion uses a closed
status vocabulary plus verifiable evidence. Missing or mismatched identity fails closed.

## Non-goals

No shared live messaging across harnesses. No cross-harness model/effort mapping — each
implementation resolves its own model map; the bridge carries roles, never model ids. No
shared loop/scheduling primitive — each implementation reconstructs a loop from its own
local primitives.
