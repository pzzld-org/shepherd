---
name: focus
description: Start or refresh the sprint Focus Loop — write/update the durable focus record (objective, active node, obligations, invariants), re-anchor via the FOCUS-HEARTBEAT (the root's own drift guard for long stretches), and optionally enter interval-wake mode via the native Claude Code /loop. v6.0.9+ (heartbeat v6.2.2).
argument-hint: "[--sprint=<branch>] [--objective=<text>] [--active-node=<id>] [--ready-set=<csv>] [--obligations=<json>] [--invariants=<json>] [--interval=<duration>] [--max=<N>] [--refresh] [--heartbeat]"
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch
---

# /shepherd:focus — Sprint Focus Loop

Start or refresh the **FOCUS-LOOP** — the orchestrator's own Loop-Until-Done orientation loop that keeps the sprint on-track across compaction events and wave boundaries. Each iteration re-reads the focus record, probes drive state, and advances the active Stage-Graph node.

The **FOCUS-HEARTBEAT** (v6.2.2) extends this with a cadenced self-re-anchor *within* a long active stretch — when no compaction or teammate event forces a wake — so the root re-reads the objective and checks its **own** drift before it compounds. This is the fix for "root wandered after hours": the event-driven loop re-anchors at every wake, but a long uninterrupted FOCUS-ACT stretch has no wake. See [Step 1b](#step-1b--re-anchor-focus-heartbeat-v622).

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
| `--heartbeat` | *(flag)* | Emit the `[FOCUS-HEARTBEAT]` re-anchor block from the current record and run the self-drift-check now — a manual heartbeat tick (v6.2.2). Read-only on the record (writes nothing); use mid-stretch when you sense the root drifting. |

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

## Step 1b — Re-anchor (FOCUS-HEARTBEAT, v6.2.2)

The **FOCUS-HEARTBEAT** is the orchestrator's own drift guard over a long active
stretch. The FOCUS-LOOP re-anchors at every wake; a long FOCUS-ACT stretch with no
teammate event has no wake — so the north-star recedes and the root drifts. On
`--heartbeat`, and automatically every `[focus].heartbeat_actions` orchestrator
actions (or `[focus].heartbeat_interval` wall-clock) inside a long stretch, the
orchestrator re-reads the record (`shctx loop focus show`) and emits:

```
[FOCUS-HEARTBEAT] iter=<i> · since-anchor=<N actions | Tm>
objective:   <the sprint / lane north-star, one line>
active_node: <id> — <short label>
invariants:  <hold-true rules, comma-joined>
next_action: <the single next concrete step toward active_node>
drift:       on-node | [DRIFT-WARN] self → <correction>
```

Then the **self-drift-check**: did the last stretch advance `active_node` within
`invariants`? On-node → resume. Wandered into adjacent / unseeded work →
`[DRIFT-WARN] self`: stop, return to `active_node`, and **file** the digression
(finding / carry-forward / issue) rather than chase it inline (bounded —
`subtract-dont-add.md`). Read the record **fresh** — never restate the objective
from working memory, because drift is exactly when working memory has gone stale.
The block is variable content the orchestrator emits; it never enters a cached
brief prefix (`doctrines/brief-cache-discipline.md`).

The two cadence legs are not equal. `[focus].heartbeat_interval` is the
**deterministic** leg: it delegates the clock to the native `/loop` (Step 3), so a
real wake fires on a real schedule — the only leg that *guarantees* a re-anchor on a
long unattended stretch, and the right one to set because timing belongs in a
mechanism, not an in-reply estimate (`doctrines/operating-philosophy.md §I.1`).
`[focus].heartbeat_actions` is a **soft, best-effort self-prompt** (default on): the
orchestrator re-anchors after roughly N significant actions. It is a latent estimate,
not a counted guarantee (nothing backs it but your own judgement), so treat it as a
zero-cost nudge and rely on `heartbeat_interval` when a guarantee matters.

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
- `skills/shepherd/references/workflow-templates.md` §FOCUS-LOOP — named composite definition + the FOCUS-HEARTBEAT re-anchor cadence
- `doctrines/coordinate-active-drive.md` §IV-b.3 — the root self-drift leg of the coordinate PROBE
- `doctrines/workflow-patterns.md` §Circuit-breaker invariants — Pattern 6
- `docs/configuration.md` — `[focus]` and `[compaction]` sections
