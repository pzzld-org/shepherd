---
name: start
description: "Begin execution from a gated plan. Root perspective by default, where root drives every wave itself; --lane hands one lane to one conductor."
source: skills/start/SKILL.md
portability: cross-harness
---

# start — perspective decides who dispatches

The flag picks who owns fan-out.

## Preconditions

- `shepherd run show <run>` reports `planned` or `executing`.
- `shepherd plan verify --run <run>` exits 0.

## Root perspective, the default

Root drives. One `shepherd:engineer` ledgers the plan and stops; it authors no execution.
Root then runs the waves itself — discovery and initialization, then execution —
dispatching each implementer at `shepherd models resolve <role>` under one bounded
workflow per wave. No conductor, no lane ledger.

Use it when splitting into lanes would cost more than it saves.

## Lane perspective, `--lane <lane>`

One lane, one conductor, no root fan-out.

- The lane exists in the plan, is not closed, and its file scope is disjoint from every
  lane in flight.
- `shepherd run lane add <run> <lane>`, passing `--worktree` and `--branch` when it
  executes outside the root checkout.
- One `shepherd:conductor` at `shepherd models resolve conductor`. Orientation is
  abbreviated: `lanes/<lane>/plan.md` already carries the phases, so the brief names the
  run, lane, scope, acceptance, and gate, and references the plan.

The conductor drives; it owns lane outcomes and output fidelity.
`shepherd:worker` and `shepherd:coder` execute tasks, an adversarial
`shepherd:auditor` verifies behind them, and a failed verification forces redo. It may not dispatch plan-author or gate roles — those escalate to root.

Then root stops and waits.

## Close

Root closes lanes; conductors never close themselves.
`shepherd close-lane --run <run> <lane> --status clean`. A lane that failed closes with
its real status.
