---
name: loop
description: Run the Loop-Until-Done workflow pattern (Pattern 6) — dispatch a flock agent repeatedly until a "no new findings" condition is satisfied or the iteration cap is reached. Integrates with the native Claude Code /loop interval mechanism for long-horizon polling loops. v6.0.7+.
argument-hint: "[task-description | node-id] [--max <N>] [--agent <worker|discovery>] [--interval <duration>] [--until <condition-field>]"
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, SendMessage, WebFetch, WebSearch
---

# /shepherd:loop — Loop-Until-Done Pattern Executor

Run **Pattern 6 (Loop-Until-Done)** from `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/workflow-templates.md` as a first-class shepherd command. The loop dispatches a single flock agent repeatedly, reading a structured `new_findings` field from each iteration's report, and terminates when the field is false or the iteration cap is reached.

This command is the native shepherd entry point for convergent iteration: exhaustive research, iterative fix-until-gates-green, progressive audit refinement, and any task whose completion is defined by absence rather than a fixed count.

> **Relation to Claude Code `/loop`.** `/shepherd:loop` wraps the Loop-Until-Done pattern in shepherd's preflight, SQLite state, and agent dispatch discipline. The native `/loop` skill owns the wake clock; shepherd owns the per-iteration contract. The exact native invocation is never reconstructed by the model — `shctx loop native-cmd --id=<loop-id>` emits it deterministically from the loop's stored pacing (latent/deterministic split, `doctrines/operating-philosophy.md` §I.1).

### Pacing modes — pick how the wake clock runs

| Mode | Flag | Wake clock | Ends early? | Use for |
|------|------|-----------|-------------|---------|
| **In-session** | *(neither flag)* | shepherd drives `wake → act → probe → yield` in-session (`doctrines/coordinate-active-drive.md`) | yes (in-loop) | Tight loops you watch live — fix-until-green, short exhaustive search |
| **Self-paced** | `--self-paced` | native `/loop`, **dynamic** 1min–1hr delay it chooses (cache-window-aware) | **yes — automatically** when `new_findings: false` | Long-horizon work where the cadence should be chosen for you and the loop should stop itself |
| **Fixed interval** | `--interval <dur>` | native `/loop` at a **fixed** cadence you set | only via the stop instruction surfaced at convergence | Polling on a known period — CI every `5m`, a daily soak |

Self-paced is the native mode shepherd previously documented but never wired: no fixed timer to pick, and the loop ends itself when it converges instead of leaning on the operator to cancel.

---

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max <N>` | `5` | Iteration ceiling. Mandatory; values > 5 require justification in the loop brief; values > 10 require a live operator acknowledgement before the loop starts. |
| `--agent <role>` | `worker` | Flock agent to dispatch per iteration. Valid: `worker`, `discovery`. Write-capable iteration goes to `@worker`; read-only orientation goes to `@discovery`. |
| `--interval <duration>` | *(none)* | When set, delegate iteration scheduling to the native Claude Code `/loop` skill at the given **fixed** interval (e.g., `5m`, `1h`). Each wake re-enters this command with `--resume <loop-id>`. |
| `--self-paced` | off | Delegate to native `/loop` with **no fixed interval** — the platform picks a dynamic 1min–1hr delay per wake (cache-window-aware) and ends early when the loop converges. For long-horizon work where the cadence should be chosen for you. Mutually exclusive with `--interval`. |
| `--until <field>` | `new_findings` | The structured field the conductor reads from the agent's report to determine termination. Must be `true`/`false` valued. Override only when the agent's report uses a different field name. |
| `--resume <loop-id>` | *(none)* | Resume an in-progress loop (used by interval wake-ups). Skips preflight; reads state from SQLite registry. |
| `--scope <read-only\|write>` | auto-from-agent | Explicit scope declaration for DEDUP-GATE. Inferred from `--agent` by default (`discovery` → read-only; `worker` → write). |

---

## Step 0 — Preflight

Skip to Step 3 if `--resume <loop-id>` is present.

1. **Load shepherd context** — invoke `shepherd` via the Skill tool to load `SKILL.md` and the framework context.

2. **Read shepherd.toml** — `.claude/shepherd.toml`. If missing, surface warning and use defaults. If validation fails, HALT with error.

3. **Validate flags:**
   - `--max` must be a positive integer. If absent, default to 5 and surface: "Loop cap set to 5 (default). Override with `--max <N>`."
   - If `--max > 10`, surface: "Loop cap > 10 requires operator acknowledgement. Confirm you want `--max <N>` iterations." — wait for operator confirmation before proceeding.
   - `--agent` must be `worker` or `discovery`. Any other value → HALT: `LOOP-INVALID-AGENT`.
   - `--interval` duration must be parseable (e.g., `5m`, `30s`, `1h`). Invalid format → HALT: `LOOP-INVALID-INTERVAL`.
   - `--self-paced` and `--interval` are mutually exclusive (pick one pacing mode). Both → HALT: `LOOP-INVALID-INTERVAL`. `--self-paced` needs no duration.

4. **Register loop state** in SQLite (pass the pacing mode — `--interval=<dur>`, `--self-paced`, or neither for in-session):
   ```bash
   shctx loop init \
     --task="<task-description>" \
     --max=<N> \
     --agent=<role> \
     --until=<field> \
     [--interval=<duration> | --self-paced]
   ```
   This emits a `loop-id` (e.g., `loop-20260604-001`). Store it — every subsequent step references it.

5. **Surface loop plan to operator** (one block):
   ```
   LOOP PLAN
   task:        <task-description>
   agent:       @<role>
   max:         <N> iterations
   until:       report.<field> == false
   pacing:      <fixed:<dur> | self-paced | in-session>
   loop-id:     <loop-id>
   ```
   Proceed immediately (no confirmation needed unless `--max > 10`).

---

## Step 1 — Load agent profile

Read `${CLAUDE_PLUGIN_ROOT}/agents/<role>.md` (as specified by `--agent`) in full. This is the system prompt injected into the agent's brief. For `--agent worker`, load `agents/worker.md`. For `--agent discovery`, load `agents/discovery.md`.

---

## Step 2 — Construct iteration brief template

Build the per-iteration brief template. The brief is **stable across all iterations** (prefix-cacheable) except for the `[ITERATION-CONTEXT]` tail block, which is variable (current iteration number, prior findings summary). Cache discipline per `doctrines/brief-cache-discipline.md` applies: stable framing first, variable tail last.

**Brief structure:**

```
[AGENT-PROFILE]
<contents of agents/<role>.md>

[TASK]
<task-description from invocation>

[LOOP-CONTRACT]
You are iteration $i of $max in a Loop-Until-Done dispatch.
Your report MUST include a top-level field:

  new_findings: true | false

Set new_findings: true if you discovered actionable items this iteration.
Set new_findings: false if this iteration surfaced nothing new.

If new_findings: true, also emit:
  findings_summary:
    - <finding 1>
    - <finding 2>
    ...

Do NOT omit new_findings. A report without this field is LOOP-REPORT-INVALID.

[ITERATION-CONTEXT]
iteration:       $i / $max
prior_findings:  <summary of all findings from iterations 1..$i-1, or "none" for i=1>
loop_id:         <loop-id>
```

---

## Step 3 — Resume (interval wake-up path)

When re-entered with `--resume <loop-id>`:

1. Read loop state from SQLite: `shctx loop status --id=<loop-id>`
2. Extract: `iteration`, `max`, `agent`, `until`, `findings_so_far`
3. If `iteration >= max` → jump to Step 6 (LOOP-DONE-CAPPED)
4. If loop state = `done` → surface: "Loop `<loop-id>` already completed. Nothing to do." and exit
5. Proceed to Step 4 with recovered state.

---

## Step 4 — Iterate

Fire iteration `$i` (starting at 1):

1. **DEDUP-GATE** (Layer 1): if this is a write-capable `@worker` loop and a prior iteration already addressed the current task scope, surface a deduplication warning before dispatching. Read: `shctx dedup check --task="<task-description>" --iteration=$i`.

2. **Dispatch agent** with the constructed brief (iteration-context tail updated for current `$i`).

3. **Receive report.** Extract `report.<until-field>` (default: `report.new_findings`).

4. **Record iteration** in SQLite:
   ```bash
   shctx loop record \
     --id=<loop-id> \
     --iteration=$i \
     --new_findings=<true|false> \
     --summary="<findings_summary or 'none'>"
   ```

5. **Branch:**
   - `new_findings: false` → jump to Step 5 (LOOP-DONE)
   - `new_findings: true` AND `$i < max` → increment `$i`, return to top of Step 4
   - `new_findings: true` AND `$i >= max` → jump to Step 6 (LOOP-DONE-CAPPED)
   - Report missing `new_findings` field → HALT: `LOOP-REPORT-INVALID` (surface the raw report excerpt and ask operator whether to treat as true or false for this iteration)

---

## Step 5 — LOOP-DONE (clean termination)

`new_findings` was false. The loop converged.

1. **Emit loop summary:**
   ```
   ## Loop summary — <loop-id>
   status:        converged
   iterations:    $i / $max
   task:          <task-description>
   agent:         @<role>

   ### Finding inventory (all iterations)
   iteration 1: <summary or "no findings">
   iteration 2: <summary or "no findings">
   ...
   ```

2. **Finalize in SQLite:** `shctx loop close --id=<loop-id> --status=converged`

3. **Cancel the native schedule** (delegated modes): a `--self-paced` loop ends itself automatically when it reports `new_findings: false` — nothing to cancel. For a fixed `--interval`, surface "Loop converged after $i iterations. Stop the native schedule with `/loop stop` (or stop re-invoking)."

4. Surface to operator and stop.

---

## Step 6 — LOOP-DONE-CAPPED (cap reached)

`$i >= max` but `new_findings` is still true. The loop hit its ceiling.

1. **Emit cap report:**
   ```
   ## Loop summary — <loop-id>
   status:        cap-reached
   iterations:    $max / $max
   task:          <task-description>
   agent:         @<role>

   ### Finding inventory (all iterations)
   <per-iteration summaries>

   ### Open findings at cap
   <list of findings from the final iteration>

   LOOP-CAP: The loop reached --max $max with findings still present.
   Options:
     A. Re-invoke with --resume <loop-id> --max <higher-N> to continue
     B. Accept current state and handle open findings manually
     C. Escalate to a sprint lane for systematic resolution
   ```

2. **Finalize in SQLite:** `shctx loop close --id=<loop-id> --status=cap-reached`

3. HALT and wait for operator decision. Do NOT auto-extend the cap.

---

## Delegated mode — integrating with Claude Code `/loop` (fixed + self-paced)

When `--interval <dur>` OR `--self-paced` is set, shepherd delegates the wake clock to the native Claude Code `/loop` skill. The invocation string is **emitted deterministically** by `shctx loop native-cmd` — shepherd does not reconstruct it (latent/deterministic split):

**First invocation (operator runs):**
```
/shepherd:loop <task> --max 20 --agent worker --self-paced     # dynamic native cadence
/shepherd:loop <task> --max 20 --agent worker --interval 5m    # fixed cadence
```

1. Shepherd runs Steps 0–1 (preflight + register loop state, emitting `<loop-id>`).
2. Shepherd reads the exact native invocation and surfaces it verbatim:
   ```bash
   shctx loop native-cmd --id=<loop-id>
   # self-paced ⇒  /loop /shepherd:loop --resume <loop-id>
   # fixed 5m   ⇒  /loop 5m /shepherd:loop --resume <loop-id>
   ```
   Surface the printed line and instruct the operator to run it (print-and-confirm — shepherd does not silently schedule a native loop on the operator's behalf, per `doctrines/operator-signaling.md`).

**Each wake-up (Claude Code `/loop` triggers):**
```
/shepherd:loop --resume <loop-id>
```
The command re-enters at Step 3 (resume), runs exactly one iteration (Step 4), then exits — the native `/loop` skill handles the next wake. In **self-paced** mode the platform also chooses each delay and ends the loop early once an iteration reports `new_findings: false`; in **fixed** mode it wakes on the set period until the stop instruction.

**Termination:** On LOOP-DONE / LOOP-DONE-CAPPED the command surfaces the stop guidance (self-paced self-terminates; fixed is cancelled with `/loop stop`).

> **Note:** Self-paced fits long-horizon work where the cadence should be chosen for you and the loop should stop itself (exhaustive discovery, a soak that may converge early). Fixed `--interval` fits known-period polling (CI every `5m`, a daily outcome soak). Tight fix-until-green loops you watch live want neither flag (in-session drive).

---

## Circuit-breaker invariants

Per `doctrines/workflow-patterns.md §Circuit-breaker invariants — Pattern 6`:

| Invariant | Enforcement |
|-----------|-------------|
| `--max` declared before first dispatch | Step 0.3 validation; default = 5 |
| Values > 10 require operator acknowledgement | Step 0.3 confirmation prompt |
| `new_findings` field present in every report | Step 4.3 field check; LOOP-REPORT-INVALID on absence |
| Cap-exceeded is HALT, not silent exit | Step 6; never auto-extend |
| Interval mode surfaces stop instruction on convergence | Step 5.3 |

---

## Halt codes

| Code | Trigger | Resolution |
|------|---------|-----------|
| `LOOP-INVALID-AGENT` | `--agent` is not `worker` or `discovery` | Use a valid agent role |
| `LOOP-INVALID-INTERVAL` | `--interval` format unparseable | Use `5m`, `30s`, `1h` format |
| `LOOP-REPORT-INVALID` | Agent report missing `new_findings` field | Operator decides: treat as true/false for this iteration |
| `LOOP-CAP` | Iterations reached `--max` with findings still present | Operator extends cap, accepts state, or escalates |
| `LOOP-STATE-MISSING` | `--resume <loop-id>` references unknown loop | Check `shctx loop list` for active loop IDs |

---

## Examples

**In-session exhaustive search:**
```
/shepherd:loop "find all TODO comments across the codebase" --agent discovery --max 5
```

**Iterative fix-until-gates-green:**
```
/shepherd:loop "fix failing tests" --agent worker --max 8
```

**Long-horizon CI monitoring (interval mode):**
```
/shepherd:loop "check CI status on origin/main" --agent worker --max 20 --interval 5m
```

**Resume a paused loop:**
```
/shepherd:loop --resume loop-20260604-001
```

---

## Per-role loop templates

Every applicable flock role and meta-orchestrator has a ready-to-use loop template in
`skills/shepherd/references/loop-templates.md`. Templates declare intent, iterator agent,
loop body shape (Probe → Act → Branch), termination predicate, default `--max`, the named
composite they specialize, and anti-patterns.

The `--agent` flag selects the iterator. The templates map to `--agent` as follows:

| `--agent` | Template | Composite | Default `--max` |
|-----------|----------|-----------|-----------------|
| `worker` (state-reconcile) | WORKER-CONVERGENCE | CONVERGENCE-LOOP | 5 |
| `worker` (monitoring) | WORKER-WATCH | WATCH-LOOP | 20 |
| `worker` (outcome soak) | SOAK-LOOP | WATCH-LOOP | 6 |
| `discovery` | DISCOVERY-EXHAUST | Pattern 6 generic | 4 |

> **SOAK-LOOP (post-close outcome re-verification).** A `--agent worker --interval`
> variant that re-runs a *closed* sprint's seeded acceptance predicates (`seed §6`) against
> live state on a post-close cadence, surfacing `OUTCOME-REGRESSION` if a promised-true
> predicate now returns false. It is detection-only — never auto-remediation. Invoke:
> ```
> /shepherd:loop "soak outcomes for <sprint>" --agent worker --interval 1d --max 6
> ```
> See `references/loop-templates.md §SOAK-LOOP` (template) and
> `doctrines/outcome-enforcement.md §Seam 4` (the close→soak seam it serves).

The `--agent` flag currently accepts `worker` and `discovery`. The `@coder`,
`@auditor`, and `@engineer` loop variants (CODER-CONVERGENCE, AUDITOR-REFINE,
ENGINEER-PLAN-REFINE) and the orchestrator FOCUS-LOOP are authored directly in Stage Graph
YAML by the engineer — they are not driven via the `/shepherd:loop` command entry point. Full
template definitions for all roles are in `references/loop-templates.md`.

When in doubt about which template to use, consult the quick-selection table at the top of
`references/loop-templates.md`. A loop whose template alignment cannot be stated is a loop
that needs a plan revision before it fires.

---

## See also

- `skills/shepherd/references/loop-templates.md` — per-role loop template catalog; copy-paste Stage Graph shapes for coder, discovery, worker, auditor, engineer, and orchestrator
- `skills/shepherd/doctrines/loop-templates.md` — binding doctrine: principle, circuit-breaker invariants, enforcement surface; introduced v6.1.2
- `skills/shepherd/references/workflow-templates.md` §Pattern 6 — Loop-Until-Done — full pattern definition
- `doctrines/workflow-patterns.md` §Circuit-breaker invariants — Pattern 6 — binding invariants
- `doctrines/coordinate-active-drive.md` — `wake → act → probe → yield` cycle that in-session loops implement
- `doctrines/worker-patterns.md` — `@worker` patterns for the loop body executor
- `doctrines/discovery-readonly.md` — `@discovery` patterns for read-only loop body
- `${CLAUDE_PLUGIN_ROOT}/skills/context/SKILL.md` — `shctx loop` verbs referenced above
