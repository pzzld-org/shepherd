---
name: bridge
---

# bridge — the cross-shepherd coordination contract

The one contract letting two shepherd implementations coordinate on the same repository
without either knowing the other's harness internals. A change here is meant to replicate
to every implementation; a capability that can't be expressed through this contract
belongs to one implementation, never to the bridge.

## The filesystem is the bus

Implementations never talk harness-to-harness — no shared task lists, no cross-harness
inboxes, no tool-name assumptions. They coordinate exclusively through the project-visible
run-artifact tree: a shared run-state file (schema-versioned; a reader seeing a version
higher than it understands treats the run as foreign and read-only), the seed/plan/lane-
plan prose artifacts (identical shape in every implementation), and durable learnings/
context directories (shared read, single writer per file). Identifiers everywhere are
`[a-z0-9][a-z0-9-]*` — no path separators, no `..`, no absolute paths; timestamps live in
the run-state file, never in artifact bodies, so a byte-stable render stays diffable.

## Content contract vs. path contract

Two implementations agreeing WHERE an artifact lives is not the same guarantee as agreeing
WHAT it must contain. An artifact this contract names required sections or fields for is
content-contracted — a consumer may assume nothing about its interior beyond what's named.
An artifact the contract only names a path for is path-compatible only — the path is the
whole guarantee, and a consumer must not assume a stronger one. Observed failure mode: one
implementation wrote a real file at the right path with none of the required sections — a
well-formed empty box a second implementation's boot check took as real instruction. The
self-healing response is to reconstruct the missing content from the parent plan before
executing, never to treat an empty-shaped file as valid instruction.

## Custody

Single-writer per path, claimed through the run-state file: registering a lane with its
worktree/branch fields populated makes it FOREIGN to every other participant — no writes
under its path, no commits to its branch, no worktree access. The run's root custodian is
whichever implementation created the run-state file; only it mutates run-level fields and
executes cross-lane integration. A non-custodian needing a run-level change writes a
best-effort signal and waits — never assumes, never force-writes.

## Dispatch envelope

Work crossing the bridge — one implementation authoring work another will execute — is a
file carrying a fixed, machine-readable header (role, a stable node id, scope, an
acceptance predicate, a report path) and a fixed completion footer (a closed four-value
status vocabulary, plus a non-empty pointer to verifiable evidence) — both grammar-checked
by the consumer; a report missing either is unfinished, not merely terse.

## Non-goals

No shared live messaging across harnesses. No cross-harness model/effort mapping — each
implementation resolves its own model map; the bridge carries roles, never model ids. No
shared loop/scheduling primitive — each implementation reconstructs a loop from its own
local primitives.
