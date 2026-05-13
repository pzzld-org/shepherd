---
title: PAUSE-FOR-DEPENDENCY — coder-initiated satellite dispatch
description: |
  First-class Stage Graph primitive for when a coder discovers an out-of-scope
  dependency mid-lane. Replaces the three bad options (silent scope expansion,
  TODO comment, one-line escalation) with a structured halt → satellite dispatch
  → resume flow the conductor can walk deterministically.
introduced: v5.0.9
field_origin: shepherd v5.0.8 conductor feedback (axiom v0.3.2-dev.0) §1
---

# Doctrine — PAUSE-FOR-DEPENDENCY

## Why this exists

Mid-lane, a coder sometimes discovers that completing their `[FILE-SCOPE]` requires
a public API, struct extension, or module-level change that lives in a *different*
crate or file — outside `[FILE-SCOPE]`. Before v5.0.9, the coder had three options:

1. **Silently expand scope** — banned by `[NON-GOALS]` + `wrapper-must-earn.md`;
   auditors catch and grade-cap as `STAGE-GRAPH-VIOLATION`.
2. **Punt with a TODO comment** — banned explicitly by `agents/coder.md`
   Hard Prohibitions; auditors grep for `TODO|FIXME|XXX|HACK` and fail.
3. **Escalate via "BRIEF-AMENDMENT REQUEST"** — exists as a one-line escape
   hatch in `agents/coder.md` but isn't a Stage Graph node, has no conductor
   handler, and requires an engineer amendment cycle (full plan revision + critic
   re-gate), which is heavyweight for a localized dependency gap.

**PAUSE-FOR-DEPENDENCY** is the fourth option: the coder owns the request; the
conductor orchestrates a bounded satellite dispatch; the paused lane resumes after
the satellite lands. No silent expansion, no TODO, no full plan revision.

---

## I. Coder protocol — when to emit PAUSE-FOR-DEPENDENCY

**Trigger condition:** during Step 4 (write code), the coder determines that
completing the acceptance criteria for their lane requires a change to a file
**not in their `[FILE-SCOPE]` MAY-MODIFY list**, AND:

- The required change is bounded (XS or S — a new public fn, a struct field,
  a re-exported type), AND
- The required change is not already in another lane in the SAME wave (if it
  is, the conductor should sequence the lanes; this is a lane-ordering issue,
  not a satellite issue).

**What to check first (before pausing):**

```bash
# 1. Is the symbol I need already exported somewhere?
rg -n "pub fn <needed_fn>\|pub struct <needed_struct>" --type rs

# 2. Is it in a [CONTEXT-INVENTORY] entry I missed?
# Re-read the [CONTEXT-INVENTORY] section of the brief.

# 3. Is another coder in this wave touching that file?
# Re-read the wave's lane list. If yes, wait or reorder — do NOT pause.
```

Only if all three checks fail: emit PAUSE-FOR-DEPENDENCY.

**What to do at pause time:**

1. Commit any WIP to the worktree branch:
   ```bash
   git -C "$WORKTREE_PATH" add <files touched so far>
   git -C "$WORKTREE_PATH" commit -m "wip(dev.N/<lane>): PAUSE-FOR-DEPENDENCY checkpoint"
   ```
   If nothing is written yet, no commit needed — note "no WIP" in the report.

2. Return the structured PAUSE report (see below). Do NOT continue writing code.

**Structured PAUSE report (replaces the normal CODER REPORT on pause):**

```
## CODER REPORT — PAUSE-FOR-DEPENDENCY

- Lane: <brief-id / lane name>
- Halt code: PAUSE-FOR-DEPENDENCY
- Reason: <one sentence: what is missing and why it blocks lane completion>
- Satellite brief request:
    target_path:       <file(s) that need the new/extended symbol>
    file_scope_proposed: <exact files the satellite MAY MODIFY>
    work:              <what the satellite needs to do — max 3 sentences>
    estimated_size:    XS | S
    new_symbol:        <exact identifier the satellite must introduce>
    acceptance:        `rg "<new_symbol>" <target_path>` → 1 hit
- Lane state at pause:
    branch:   <worktree branch name>
    wip_sha:  <7-char SHA of checkpoint commit, or "none — no WIP yet">
- Resume condition: <what the coder needs to see in HEAD before resuming>
  (e.g., "pub fn foo exported from crates/engine/src/lib.rs")
- Agent ID + timestamp: <id> @ <ISO-8601>
```

---

## II. Conductor protocol — handling a PAUSE-FOR-DEPENDENCY report

When a coder returns a `PAUSE-FOR-DEPENDENCY` report, the conductor walks these
steps **inline** (no new graph nodes need to be added ad-hoc — the satellite
dispatch IS the PAUSE-FOR-DEPENDENCY Stage Graph node, see §III):

### Step 1 — Validate the satellite request

Before dispatching, verify:

- `estimated_size` is `XS` or `S`. If `M` or larger: the paused lane is
  fronting work that should have been its own wave lane — the engineer's plan
  was under-scoped. Escalate via `BRIEF-AMENDMENT REQUEST` to the engineer
  (NOT a satellite dispatch). Surface to the operator.
- `file_scope_proposed` is disjoint from every OTHER currently-active or
  pending coder lane. If it overlaps, resolve the ordering conflict first.
- `new_symbol` does not already exist (run the `[DO-NOT-DUPLICATE]` check on
  `new_symbol`). If it exists, update the paused coder's brief with the
  existing symbol's location and `SendMessage` to resume immediately.

### Step 2 — Dispatch the satellite coder

Dispatch a `@coder` with `isolation: "worktree"` for the satellite work. The
satellite brief follows the standard seven-section format from
`references/agent-briefs.md`, with:

- `[FILE-SCOPE]` = `file_scope_proposed` from the report
- `[NON-GOALS]` = "Do not implement the paused lane's feature; expose the
  symbol only."
- `[ACCEPTANCE]` = the `acceptance` grep from the report
- Size cap: if the satellite brief cannot be written as XS or S, halt —
  the request is over-scoped for a satellite (see §IV cap rules).
- Commit template: `fix(dev.N/satellite-<lane-id>): expose <new_symbol>`

### Step 3 — After satellite commits

Once the satellite coder returns a CODER REPORT with acceptance greps passing:

1. Rebase the satellite's worktree commit onto the sprint branch FIRST
   (before the paused lane resumes). Cherry-pick order matters — see §V.
2. Record the satellite SHA.
3. `SendMessage` to the paused coder with:
   ```
   RESUMED — satellite landed. <new_symbol> now at <file_path>:<line>.
   Satellite commit: <sha>. Your WIP checkpoint: <wip_sha or "none">.
   Continue from where you left off. Confirm the new symbol is visible
   before writing code.
   ```

### Step 4 — Paused coder resumes

The paused coder:
1. Verifies the new symbol is present: `rg "<new_symbol>" <path>` → 1 hit.
2. Resumes from WIP checkpoint (or from scratch if no WIP).
3. Commits using the original lane commit template (not the satellite's).
4. Returns the normal CODER REPORT.

---

## III. Stage Graph encoding

The engineer's plan does NOT need to pre-declare PAUSE-FOR-DEPENDENCY nodes —
they're discovered at runtime. When a coder pauses, the conductor adds two
ephemeral nodes to its in-memory walk:

```yaml
# (added at runtime when coder-<lane-id> returns PAUSE-FOR-DEPENDENCY)
- id: pause-dep-<lane-id>
  type: PAUSE-FOR-DEPENDENCY
  in_predicates: [{ predecessor: wave-N-impl-<lane-id>, edge: on-pause-dep }]
  agents: []    # conductor-inline
  out_edges:
    - { label: on-satellite-dispatched, target: satellite-<lane-id> }

- id: satellite-<lane-id>
  type: HOTFIX    # reuses HOTFIX dispatch shape; satellite is ≤ S
  in_predicates: [{ predecessor: pause-dep-<lane-id>, edge: on-satellite-dispatched }]
  agents: [{ role: coder, count: 1, brief-ref: satellite-brief-<lane-id> }]
  out_edges:
    - { label: on-coder-complete, target: resume-<lane-id> }
    - { label: on-hard-stop, target: hard-stop }

- id: resume-<lane-id>
  type: RESUME-LANE    # conductor SendMessage + await resumed coder
  in_predicates: [{ predecessor: satellite-<lane-id>, edge: on-coder-complete }]
  agents: []    # conductor sends message to the PAUSED coder agent
  out_edges:
    - { label: on-coder-complete, target: wave-N-gate }
    - { label: on-hard-stop, target: hard-stop }
```

The PAUSE-FOR-DEPENDENCY → satellite → RESUME-LANE subgraph resolves BEFORE
the `WAVE-N-GATE` node can fire. The gate waits for ALL lanes, including the
resumed lane.

**Stage taxonomy additions (v5.0.9):**

| Type | Dispatch shape | Owner | Produces |
|---|---|---|---|
| `PAUSE-FOR-DEPENDENCY` | Conductor inline (validate + dispatch satellite) | Conductor | satellite brief + SendMessage resume trigger |
| `RESUME-LANE` | Conductor inline (SendMessage to paused coder; awaits resumed CODER REPORT) | Conductor | resumed lane commit |

---

## IV. Cap rules (anti-scope-creep guardrails)

| Rule | Limit | Enforcement |
|---|---|---|
| Satellite size cap | XS or S only | Conductor validates `estimated_size` before dispatch; M+ → escalate to engineer, not satellite |
| Satellite count per lane | Max 2 per lane | If a lane triggers 3+ satellites, the lane scope was wrong — escalate to BRIEF-AMENDMENT; auditor flags as `STAGE-GRAPH-VIOLATION` |
| Satellite scope | XS/S size AND ≤ 2 files | A satellite touching > 2 files is scoped too broadly; split or escalate |
| Satellite recursion | Satellites CANNOT pause for sub-satellites | If a satellite hits its own out-of-scope dep, it returns `BRIEF-AMENDMENT REQUEST` to the conductor, NOT a recursive PAUSE |

**Why 2-satellite cap?** A lane needing 3+ satellite fixes signals the original
lane scope was under-decomposed — the engineer's plan was incorrect, not just the
dependency surface. At that point, the cost of satellite overhead exceeds the cost
of a plan amendment. The conductor surfaces this as a process observation in the
close report.

---

## V. Cherry-pick order invariant

Satellite commits MUST land on the sprint branch BEFORE the paused lane's resumed
commit. The git log on the sprint branch MUST read:

```
<sprint base>
  ↓
<satellite commit: fix(dev.N/satellite-<lane-id>): expose <new_symbol>>
  ↓
<other concurrent wave commits, if any>
  ↓
<resumed lane commit: fix(dev.N/<lane-id>): <original subject>>
```

This is a hard ordering rule:
- Ensures the resumed lane's commit compiles against the satellite's change.
- Ensures `git bisect` can identify the satellite as the provider and the
  resumed lane as the consumer.
- Auditors verify the ordering at WAVE-GATE via `git log --oneline -N` inspection.

Violation (resumed commit lands before satellite) → `STAGE-GRAPH-VIOLATION`
finding in WAVE-AUDIT.

---

## VI. Relation to BRIEF-AMENDMENT REQUEST

These are two distinct escalation paths for different problems:

| Escalation | Trigger | Owner | Plan impact |
|---|---|---|---|
| `BRIEF-AMENDMENT REQUEST` | Plan itself was wrong — scope, dep graph, or non-goal conflict | Coder → conductor → engineer | Requires engineer revision + critic re-gate |
| `PAUSE-FOR-DEPENDENCY` | Plan was right but a localized dep was undiscovered | Coder → conductor (inline satellite) | No plan revision; satellite is ad-hoc XS/S dispatch |

Use PAUSE-FOR-DEPENDENCY when the original lane's goal is correct but ONE
specific symbol is missing. Use BRIEF-AMENDMENT when the lane's goal, file scope,
or non-goals need to change.

---

## VII. See also

- `agents/coder.md` — halt table (PAUSE-FOR-DEPENDENCY row) + Step 4 implementation
- `pipeline.md` §II — stage taxonomy (PAUSE-FOR-DEPENDENCY + RESUME-LANE rows)
- `pipeline.md` §XV-ter — SendMessage vs spawn mechanics (the RESUME-LANE step uses SendMessage)
- `doctrines/worktree-confinement.md` — satellite coder writes inside its own worktree
- `doctrines/stage-graph.md` — ephemeral node additions are still graph-walk, not ad-hoc dispatch
- `references/agent-briefs.md` — satellite brief follows standard seven-section format
