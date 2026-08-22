# Historical pre-rebase reproduction

This file preserves the original `6837e109...` reproduction only. It is not
final-state evidence. Current base, implementation, projection, and gate results
are recorded in `status-and-diff.md`, `implementation-verification.md`, and
`issue-369-authored-spawn.md`.

# Issue #369 final authored spawn evidence

Reviewed diff base: `2d7fb8030f6f0095ebdf5f79817ad4c81bf09867`.
Current worktree HEAD before lane commit: `2d7fb8030f6f0095ebdf5f79817ad4c81bf09867`.

The original reproduction showed that absent-state recovery was missing. The
current authored source now stops before dispatch, returns the single ordered
operator action, and forbids implicit project initialization. Compiler-owned
projections carry the same policy.

## Projection checks

- `content/skills/spawn/SKILL.md`: ordered action=yes; implicit-init prohibition=yes.
- `skills/spawn/SKILL.md`: ordered action=yes; implicit-init prohibition=yes.
- `plugins/shepherd/codex/skills/spawn/SKILL.md`: ordered action=yes; implicit-init prohibition=yes.
- `crates/compiler/package-content/content/skills/spawn/SKILL.md`: ordered action=yes; implicit-init prohibition=yes.

## Current authored source

```text
     1	---
     2	name: spawn
     3	description: "Turn a planted seed into a gated plan by dispatching one engineer that orients through a composite discovery wave first. Use to advance a run from planted to planned."
     4	source: skills/spawn/SKILL.md
     5	portability: cross-harness
     6	---
     7	
     8	# spawn — a seed becomes a plan
     9	
    10	```
    11	plant --[spawn]--> engineer --[discovery wave]--> plan
    12	```
    13	
    14	One engineer owns the transition. Root dispatches it and does not author the plan itself.
    15	
    16	## Absent planted state
    17	
    18	If `shepherd run show <run>` reports absent or not planted, stop and return this
    19	operator-owned sequence:
    20	
    21	`shepherd run init <run>` → invoke `plant` → invoke `spawn` again
    22	
    23	Spawn never initializes, plants, retries, or mutates project setup. Never run
    24	`shepherd init --confirm` as a spawn side effect; report that separate prerequisite and stop.
    25	
    26	## Preconditions
    27	
    28	Each is a command, not a judgement. A failure stops the spawn and is reported with its
    29	exact output.
    30	
    31	- `shepherd run show <run>` reports status `planted`.
    32	- `shepherd seed verify .shepherd/runs/<run>/seed.md` exits 0.
    33	- `shepherd doctor` reports a dispatchable namespace.
    34	- No `plan.md` exists for the run. Spawning over a plan is a replan and needs the operator.
    35	
    36	## Step 1 — dispatch the engineer
    37	
    38	Exactly one `shepherd:engineer`, with generic subagent `model` set to the exact
    39	`shepherd models resolve engineer --harness HARNESS` output. Root passes the run id and
    40	seed path, which the engineer reads whole.
    41	
    42	## Step 2 — the engineer orients before it plans
    43	
    44	The engineer dispatches one composite discovery wave and waits for it. The wave is a
    45	dynamic workflow of two agent kinds running concurrently against one run:
    46	
    47	- **auditor** — measure the repository against what the seed claims. Every deliverable
    48	  asserting a defect gets reproduced; every deliverable asserting something already exists
    49	  gets confirmed present. Report `file:line` evidence or a contradiction.
    50	- **discovery** — resolve the external unknowns the seed names: upstream documentation,
    51	  release notes, API surfaces, prior art.
    52	
    53	For `auditor` and `discovery`, set generic subagent `model` to the exact
    54	`shepherd models resolve ROLE --harness HARNESS` output. Use wide ordinary-tier fanout
    55	with one bounded brief per agent. Re-dispatch prose without evidence once, then drop it.
    56	
    57	## Step 3 — the plan
    58	
    59	The engineer authors `plan.md` from the seed plus the wave's evidence. A seed claim the
    60	wave contradicted is corrected in the plan and the contradiction is recorded — a seed is
    61	evidence, not instruction. Lanes are file-disjoint, and every lane names its acceptance
    62	and its gate.
    63	
    64	## Step 4 — the gate
    65	
    66	`shepherd plan verify --run <run>` must pass, then one `shepherd:critic` reviews the plan.
    67	Critic RED returns to step 3. On green, `shepherd run set <run> --status planned`.
    68	
    69	## What spawn never does
    70	
    71	Root does not fan out. It dispatches the engineer, relays the gate, and moves run status.
    72	Lane execution is `start`, after a plan exists.
```

Monitor #74 passed deterministic regeneration and Monitor #77 passed the full
focused lane suite. Historical `baseline-*` and other original reproduction
files intentionally retain the pre-rebase `6837e109...` observation context;
this file is the final-state evidence against the accepted lane base.
