---
name: focus
description: Start or refresh the sprint Focus Loop — the durable focus record and the FOCUS-HEARTBEAT drift-guard, with optional interval-wake mode via the native Claude Code /loop.
argument-hint: "[--sprint=<branch>] [--lane=<id>] [--objective=<text>] [--active-node=<id>] [--ready-set=<csv>] [--obligations=<json>] [--invariants=<json>] [--interval=<duration>] [--max=<N>] [--refresh] [--heartbeat]"
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch
---

# /shepherd:focus — Sprint Focus Loop

Start or refresh the **FOCUS-LOOP** — the orchestrator's own orientation loop, re-anchored by the **FOCUS-HEARTBEAT** on long stretches. Durable in `root.db`, survives `/compact`. Wraps `shctx loop init --kind=focus` + `focus upsert`; generic pacing → `/shepherd:loop` (`commands/loop.md`).

## Flags

- `--sprint=<branch>` (current branch), `--lane=<id>` (none) — record key `(sprint, lane)`; lane = teammate-conductor north-star.
- `--objective=<text>` (required first call) — sprint north-star, one paragraph.
- `--active-node=<id>` (none) — Stage-Graph node, updated per WAVE-GATE.
- `--ready-set` / `--obligations` / `--invariants` (none) — cursor snapshot, open lanes/mail/gates, hold-true rules.
- `--max=<N>` (default `8`) — iteration ceiling.
- `--interval=<duration>` (none) — delegate the recurring wake to native `/loop`.
- `--refresh` (flag) — update existing record, skip SEED-VERIFY init.
- `--heartbeat` (flag) — emit one heartbeat block now; read-only.

## Step 0 — Preflight

Resolve `--sprint` (else `git rev-parse --abbrev-ref HEAD`). Read `.claude/shepherd.toml` `[focus].rehydrate` (`on`/`off`). Run `shctx loop focus show --sprint=<branch>`; record exists and `--refresh` absent → ask: refresh or new.

## Step 1 — Write / refresh the record

```bash
shctx loop focus upsert --sprint=<branch> [--objective=<text>] [--active-node=<id>] [--ready-set=<csv>] [--obligations=<json>] [--invariants=<json>]
```

```
FOCUS RECORD — <sprint>
objective:   <text or "not yet set">
active_node: <id or "·">
ready_set:   <csv or "·">
obligations: <json or "·">
invariants:  <json or "·">
updated_at:  <epoch>
```

## Step 1b — Re-anchor (FOCUS-HEARTBEAT)

On `--heartbeat`, or automatically per `[focus].heartbeat_actions`/`heartbeat_interval`, re-read the record fresh — never from working memory — and emit. The block is variable content — NEVER cached into a brief prefix (`skills/shepherd/references/flock.md` §Brief assembly):

```
[FOCUS-HEARTBEAT] iter=<i> · since-anchor=<N actions | Tm>
objective:   <one line>
active_node: <id> — <short label>
invariants:  <hold-true rules, comma-joined>
next_action: <the single next concrete step>
drift:       on-node | [DRIFT-WARN] self → <correction>
```

On-node → resume. Wandered → `[DRIFT-WARN] self`: stop, return to `active_node`, file the digression. `heartbeat_interval` is the deterministic leg — the ONLY one that guarantees a re-anchor. `heartbeat_actions` is a soft nudge — NOT a counted guarantee.

## Step 2 — Register the loop (first call)

```bash
LOOP_ID=$(shctx loop init --task="focus loop for sprint <branch>" --kind=focus --agent=orchestrator --max=<max> --until=new_findings [--interval=<duration>])
```

## Step 3 — Interval mode (optional)

Never hand-build the invocation — emit it deterministically:

```bash
shctx loop native-cmd --id=<loop-id> --command="/shepherd:focus --sprint=<branch> --refresh"
```

No `--self-paced`: FOCUS-LOOP terminates at CLOSE-FINALIZE, not on `new_findings: false` (`commands/loop.md` §Pacing modes).

## Step 4 — Phase-boundary recording

At WAVE-GATE / CLOSE-FINALIZE, upsert the node cursor then `shctx loop record --id=<loop-id> --iteration=<N> --new_findings=<true|false> --summary="<...>"`.

## Halt codes

- `LOOP-CAP` — hit `--max`; extend `--max <higher-N>` or close the sprint.
- `LOOP-STATE-MISSING` — `--refresh` given, no active loop; run without `--refresh`.

## See also

- `commands/loop.md` — full Loop-Until-Done pattern (generic loops)
- `skills/motivation/SKILL.md` §Focus record, §FOCUS-HEARTBEAT — canonical
