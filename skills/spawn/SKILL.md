---
name: spawn
description: "Turn a planted seed into a gated plan by dispatching one engineer that orients through a composite discovery wave first. Use to advance a run from planted to planned."
---

# spawn — a seed becomes a plan

```
plant --[spawn]--> engineer --[discovery wave]--> plan
```

One engineer owns the transition. Root dispatches it and does not author the plan itself.

## Preconditions

Each is a command, not a judgement. A failure stops the spawn and is reported with its
exact output.

- `shepherd run show <run>` reports status `planted`.
- `shepherd seed verify .shepherd/runs/<run>/seed.md` exits 0.
- `shepherd doctor` reports a dispatchable namespace.
- No `plan.md` exists for the run. Spawning over a plan is a replan and needs the operator.

## Step 1 — dispatch the engineer

Exactly one `shepherd:engineer`, at the tier `shepherd models resolve engineer` returns.
Root passes the run id and the seed path. Root does not summarize the seed; the engineer
reads it whole.

## Step 2 — the engineer orients before it plans

The engineer dispatches one composite discovery wave and waits for it. The wave is a
dynamic workflow of two agent kinds running concurrently against one run:

- **auditor** — measure the repository against what the seed claims. Every deliverable
  asserting a defect gets reproduced; every deliverable asserting something already exists
  gets confirmed present. Report `file:line` evidence or a contradiction.
- **discovery** — resolve the external unknowns the seed names: upstream documentation,
  release notes, API surfaces, prior art.

Width follows tier. These are sonnet and haiku roles, so the wave is wide and every agent
carries one bounded brief. An agent returning prose instead of evidence is re-dispatched
once, then dropped.

## Step 3 — the plan

The engineer authors `plan.md` from the seed plus the wave's evidence. A seed claim the
wave contradicted is corrected in the plan and the contradiction is recorded — a seed is
evidence, not instruction. Lanes are file-disjoint, and every lane names its acceptance
and its gate.

## Step 4 — the gate

`shepherd plan verify --run <run>` must pass, then one `shepherd:critic` reviews the plan.
Critic RED returns to step 3. On green, `shepherd run set <run> --status planned`.

## What spawn never does

Root does not fan out. It dispatches the engineer, relays the gate, and moves run status.
Lane execution is `start`, after a plan exists.
