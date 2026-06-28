---
name: focus
description: Start or refresh the sprint Focus Loop — write/update the durable focus record (objective, active node, obligations, invariants) and optionally enter interval-wake mode via the native Claude Code /loop. v6.0.9+.
argument-hint: "[--sprint=<branch>] [--objective=<text>] [--active-node=<id>] [--ready-set=<csv>] [--obligations=<json>] [--invariants=<json>] [--interval=<duration>] [--max=<N>] [--refresh]"
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch
---

# /shepherd:focus — Sprint Focus Loop

Start or refresh the **FOCUS-LOOP** — the orchestrator's own Loop-Until-Done orientation loop that keeps the sprint on-track across compaction events and wave boundaries. Each iteration re-reads the focus record, probes drive state, and advances the active Stage-Graph node.

The focus record is a durable, compact north-star artifact stored in `root.db` (via migration `0013_focus.sql`). Because it lives in SQLite it survives compaction natively. When `/compact` fires, the `precompact_snapshot.sh` hook denormalizes it into a rehydration digest so the orchestrator resumes its drive deterministically after the context reset.

> **Relation to `/shepherd:loop`.** `/shepherd:focus` is a thin, discoverability-friendly wrapper around `shctx loop init --kind=focus` + `shctx loop focus upsert`. For the full Loop-Until-Done pattern (generic agents, non-focus loops), use `/shepherd:loop` directly. See `commands/loop.md`.

---

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--sprint=<branch>` | current branch | Sprint branch name. Used as the focus record's primary key. |
| `--objective=<text>` | *(required on first call)* | Sprint north-star, one paragraph. Written at SEED-VERIFY; can be refreshed later. |
| `--active-node=<id>` | *(none)* | Current Stage-Graph node id. Updated at each WAVE-GATE. |
| `--ready-set=<csv>` | *(none)* | Comma-joined node ids representing the current cursor snapshot. |
| `--obligations=<json>` | *(none)* | JSON describing open lanes, undrained mail, and pending gates. |
| `--invariants=<json>` | *(none)* | JSON listing hold-true rules (e.g., `["no teammate git integration"]`). |
| `--max=<N>` | `[focus].loop_max_default` in `shepherd.toml`, or `8` | Iteration ceiling for this focus loop instance. |
| `--interval=<duration>` | *(none)* | When set, delegate the recurring wake schedule to the native Claude Code `/loop` skill (e.g., `--interval=10m`). |
| `--refresh` | *(flag)* | Update an existing focus record without re-running the full SEED-VERIFY init sequence. |

---

## Step 0 — Preflight

1. **Resolve sprint branch:** use `--sprint` if provided, otherwise `git rev-parse --abbrev-ref HEAD`.
2. **Read `shepherd.toml`** — load `[focus].loop_max_default` (default `8`) and `[focus].rehydrate` (`on`/`off`).
3. **Check for an existing focus record:**

   ```bash
   shctx loop focus show --sprint=<branch>
   ```

   If a record exists and `--refresh` is NOT set, surface the current record and ask the operator whether to refresh it or start a new focus loop instance.

---

## Step 1 — Write / refresh the focus record

```bash
shctx loop focus upsert \
  --sprint=<branch> \
  [--objective=<text>] \
  [--active-node=<id>] \
  [--ready-set=<csv>] \
  [--obligations=<json>] \
  [--invariants=<json>]
```

Surface the written record to the operator as a one-block summary:

```
FOCUS RECORD — <sprint>
objective:   <text or "not yet set">
active_node: <id or "·">
ready_set:   <csv or "·">
obligations: <json or "·">
invariants:  <json or "·">
updated_at:  <epoch>
```

---

## Step 2 — Register the focus loop (first call only)

If no active `kind=focus` loop exists for this sprint, register one:

```bash
LOOP_ID=$(shctx loop init \
  --task="focus loop for sprint <branch>" \
  --kind=focus \
  --agent=orchestrator \
  --max=<max> \
  --until=new_findings \
  [--interval=<duration>])
```

Store `LOOP_ID`. Every subsequent phase-boundary call records an iteration against it.

---

## Step 3 — Interval mode (optional)

When `--interval <duration>` is specified, delegate the recurring wake schedule to the native Claude Code `/loop` skill. Do **not** hand-build the invocation — emit it deterministically from the loop's stored pacing (latent/deterministic split, `doctrines/operating-philosophy.md` §I.1):

1. Surface the loop plan (same format as `/shepherd:loop`).
2. Read and surface the exact native invocation for the operator to run:
   ```bash
   shctx loop native-cmd --id=<loop-id> --command="/shepherd:focus --sprint=<branch> --refresh"
   # fixed 10m ⇒ /loop 10m /shepherd:focus --sprint=<branch> --refresh
   ```

Each interval wake-up re-enters at Step 0 with `--refresh`, reads the current focus record, records one iteration, and exits.

> **No `--self-paced` for the focus loop.** Unlike a convergent loop, FOCUS-LOOP terminates at **CLOSE-FINALIZE**, not on a quiet `new_findings: false` phase — so the native self-paced "end early on `false`" would stop the orchestrator drive mid-sprint. The focus loop uses a fixed `--interval` (or in-session drive) only; self-paced is reserved for terminate-on-`false` loops (`commands/loop.md §Pacing modes`).

---

## Step 4 — Phase-boundary recording

At each major phase boundary (WAVE-GATE, CLOSE-FINALIZE), the conductor calls:

```bash
# Update the focus record with the new node cursor:
shctx loop focus upsert --sprint=<branch> \
  --active-node=<new-node> \
  --ready-set=<new-ready-csv> \
  --obligations='<updated-json>'

# Record the iteration:
shctx loop record \
  --id=<loop-id> \
  --iteration=<N> \
  --new_findings=<true|false> \
  --summary="<one-line findings summary or 'none'>"
```

---

## Halt codes

| Code | Trigger | Resolution |
|------|---------|-----------|
| `LOOP-CAP` | Focus loop hit `--max` iterations | Extend with `--max <higher-N>` or close the sprint |
| `LOOP-STATE-MISSING` | `--refresh` given but no active focus loop found | Run without `--refresh` to init a new loop |

---

## See also

- `commands/loop.md` — full Loop-Until-Done pattern (generic loops, all agents)
- `skills/context/SKILL.md` — `shctx loop` + `shctx loop focus` verb reference
- `skills/shepherd/references/workflow-templates.md` §FOCUS-LOOP — named composite definition
- `doctrines/workflow-patterns.md` §Circuit-breaker invariants — Pattern 6
- `docs/configuration.md` — `[focus]` and `[compaction]` sections
