---
name: start
description: "Dispatch one conductor from root to execute one planned lane, with no root fan-out. Use to begin lane execution once a plan is gated."
---

# start — root hands one lane to one conductor

```
plan --[start]--> conductor
```

A direct dispatch. Root spawns no wave, runs no workflow, and adds no orientation pass.
Whatever fan-out the lane needs, the conductor owns.

## Preconditions

- `shepherd run show <run>` reports status `planned` or `executing`.
- `shepherd plan verify --run <run>` exits 0.
- The named lane exists in the plan and is not already closed.
- The lane's file scope is disjoint from every lane currently in flight.

## The dispatch

Register the lane, then dispatch it:

- `shepherd run lane add <run> <lane>`, passing `--worktree` and `--branch` when the lane
  executes outside the root checkout.
- One `shepherd:conductor` at the tier `shepherd models resolve conductor` returns. The
  brief carries the run, the lane, its file scope, its acceptance, and its gate, and
  references the plan rather than restating it.

Then root stops. Root is not the conductor's supervisor loop; it records the transition
and waits.

## Conductor custody

The conductor owns its implementation waves, its reviews, its redo, and its lane handoff,
and dispatches implementers at their own tier. It may not dispatch plan-author or gate
roles — those escalate to root.

## Close

The conductor returns lane evidence. Root runs
`shepherd close-lane --run <run> <lane> --status clean`, and the verdict lands in the
ledger. A lane that failed closes with its real status, not `clean`. Root closes lanes;
conductors never close themselves.
