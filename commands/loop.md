---
name: loop
description: Run the Loop-Until-Done pattern (Pattern 6) — dispatch a flock agent repeatedly until new_findings is false or the iteration cap is reached. Integrates with native Claude Code /loop.
argument-hint: "[task-description | node-id] [--max <N>] [--agent <worker|discovery>] [--interval <duration>] [--until <condition-field>]"
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, SendMessage, WebFetch, WebSearch
---

# /shepherd:loop — Loop-Until-Done Pattern Executor

Dispatches a single flock agent (`@worker`/`@discovery`) repeatedly, reading `new_findings` from each report, until it is false or the cap is reached — native entry point for convergent iteration (`skills/harness/references/workflow-templates.md` §Pattern library, item 6).

## Pacing modes

- `--max <N>` (`5`) — mandatory. >5 needs justification in the brief; >10 needs live operator acknowledgement.
- `--agent <role>` (`worker`) — `worker` (write-capable) or `discovery` (read-only).
- Neither flag — in-session: shepherd drives wake→act→probe→yield (`skills/motivation/SKILL.md` §Drive contract); ends in-loop.
- `--interval <dur>` (none) — native `/loop`, fixed cadence; ends only via stop instruction at convergence. Exclusive with `--self-paced`.
- `--self-paced` (off) — native `/loop`, dynamic 1min–1hr delay; ends automatically on `new_findings: false`. Unsound for watch loops (terminate on `true`) — use `--interval`.
- `--until <field>` (`new_findings`) — structured `true`/`false` field from the report.
- `--resume <loop-id>` (none) — resume an in-progress loop; skips preflight.
- `--scope <read-only|write>` (auto from `--agent`) — DEDUP-GATE scope declaration.

## Step 0 — Preflight (skip if `--resume`)

0.1. Load shepherd context via the Skill tool (`skills/shepherd/SKILL.md`) if not already loaded this session.
0.2. Read `.claude/shepherd.toml` — missing → warn, use defaults; validation failure → HALT.
0.3. Validate `--max`/`--agent`/`--interval`/`--self-paced` exclusivity — halt codes below. `--max > 10` → HALT for live operator acknowledgement.

Register state, emits `loop-id`:

```bash
shctx loop init --task="<task-description>" --max=<N> --agent=<role> --until=<field> [--interval=<duration> | --self-paced]
```

Surface:

```
LOOP PLAN
task:    <task-description>
agent:   @<role>
max:     <N> iterations
until:   report.<field> == false
pacing:  <fixed:<dur> | self-paced | in-session>
loop-id: <loop-id>
```

## Step 1 — Load agent + build the brief

Read `agents/<role>.md` in full as the per-iteration system prompt: stable prefix + variable `[ITERATION-CONTEXT]` tail (`skills/shepherd/references/flock.md` §Brief assembly). Report contract:

```
new_findings: true | false
```

If `true`, also emit `findings_summary: [...]`. A report without it is `LOOP-REPORT-INVALID`.

## Step 2 — Resume

`shctx loop status --id=<loop-id>`: `iteration >= max` → Step 5; `done` → surface "already completed", exit.

## Step 3 — Iterate

DEDUP-GATE (Layer 1) before write-capable `@worker` dispatch: `shctx dedup check --task="<...>" --iteration=$i`. Dispatch, record:

```bash
shctx loop record --id=<loop-id> --iteration=$i --new_findings=<true|false> --summary="<...>"
```

Branch: `false` → Step 4. `true` and `$i < max` → next iteration. `true` and `$i >= max` → Step 5. Missing field → HALT `LOOP-REPORT-INVALID`.

## Step 4 — LOOP-DONE

Emit `## Loop summary — <loop-id>` (status converged, iterations, per-iteration findings); `shctx loop close --id=<loop-id> --status=converged`. Self-paced self-cancels; fixed `--interval` surfaces "stop with `/loop stop`."

## Step 5 — LOOP-DONE-CAPPED

Emit the cap report — options: A. resume with higher `--max`; B. accept, handle manually; C. escalate to a sprint lane — then `shctx loop close --id=<loop-id> --status=cap-reached`. HALT, wait. NEVER auto-extend the cap.

## Delegated mode (native `/loop`)

`--interval`/`--self-paced`: Steps 0–1 run once; the native invocation is surfaced verbatim, never hand-built. Shepherd never silently schedules a native loop on the operator's behalf — print the command and stop; the operator runs it (`skills/shepherd/SKILL.md` §Operator surface):

```bash
shctx loop native-cmd --id=<loop-id>
# self-paced ⇒  /loop /shepherd:loop --resume <loop-id>
# fixed 5m   ⇒  /loop 5m /shepherd:loop --resume <loop-id>
```

Each wake re-enters at `--resume <loop-id>` (Step 2), runs one iteration (Step 3), exits.

## Halt codes

- `LOOP-INVALID-AGENT` — `--agent` not `worker`/`discovery`.
- `LOOP-INVALID-INTERVAL` — `--interval` unparseable or paired with `--self-paced`.
- `LOOP-REPORT-INVALID` — report missing `new_findings`.
- `LOOP-CAP` — findings still open at `--max`.
- `LOOP-STATE-MISSING` — `--resume` references an unknown loop.

## Per-role loop templates

`worker` state-reconcile → WORKER-CONVERGENCE (max 5); `worker` monitoring → WORKER-WATCH (max 20); `worker` outcome-soak → SOAK-LOOP (max 6); `discovery` → DISCOVERY-EXHAUST (max 4). SOAK-LOOP re-runs a *closed* sprint's seeded predicates, flagging `OUTCOME-REGRESSION` on false — detection-only, NEVER auto-remediation (`skills/motivation/SKILL.md` §SOAK). `@coder`/`@auditor`/`@engineer` variants + the orchestrator FOCUS-LOOP are authored in Stage Graph YAML, not via this command. Full catalog: `skills/harness/references/loop-templates.md`.

## See also

- `skills/harness/references/workflow-templates.md` §Pattern library — full pattern definition
- `skills/motivation/SKILL.md` §Loop discipline — circuit-breaker invariants
- `skills/shepherd/references/flock.md` §@worker, §@discovery — loop body executors
