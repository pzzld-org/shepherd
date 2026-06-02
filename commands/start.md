---
name: start
description: Run one complete sprint end-to-end (engineer → critic → coder waves → auditor swarm → close), then PAUSE for operator sign-off before opening the next sprint. For continuous or multi-sprint modes, see /shepherd:spawn (--scope and --parallel flags). v5.1.6+ adds --teammate flag for sessions spawned by /shepherd:spawn.
argument-hint: "[ --teammate ]   default: solo full-pipeline; --teammate: lane-execute the assigned brief"
allowed-tools: Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, SendMessage, WebFetch, WebSearch
---

# /shepherd:start — Single Sprint Execution (solo)

Execute **one sprint** end-to-end then stop and wait for the operator.

> **Boundary (v6.0.2).** `/shepherd:spawn` is the **primary** command for substantive sprint work — root + teammate-conductor **lanes** (Agent Teams) with **Dynamic Workflow** step execution, the full parallel substrate. `/shepherd:start` is the **solo, lightweight** path: one sprint, in main chat, **no teams, no lanes** (the conductor walks the plan in-session, compiling its own gate-free fan-out). Use `start` for small / single-focus sprints or backward-compat; reach for `spawn` for real parallel work. The two are **disjoint execution paths** (`doctrines/root-shepherd-orchestration.md §I-bis`), not a wrapper relationship. For continuous or multi-sprint modes, see `/shepherd:spawn` (`--scope` and `--parallel <N>`).

## Two invocation paths (v5.1.6+)

| Invocation | Used by | Pipeline |
|---|---|---|
| `/shepherd:start` (no flag) | Main chat in solo mode | Full pipeline — load `agents/conductor.md` (SOLO), Phase 0 mesh, INTRO-COMBO-WAVE (default-on M+), `@engineer`, `@critic`, coder waves, audit swarm, close. |
| `/shepherd:start --teammate` | Teammate session spawned by `/shepherd:spawn` (v5.1.6+) | Lane-execute only — load `agents/conductor.md` (TEAMMATE), skip Phase 0 / INTRO / engineer / critic (root already did those), read assigned lane brief from inherited context, walk lane's micro-Stage-Graph (DEDUP-GATE → IMPL → LANE-CLOSE), surface WAVE-COMPLETE via SendMessage. |

The `--teammate` flag is intended for sessions that have been spawned by `/shepherd:spawn` and carry the `INVOCATION-CONTEXT.dispatcher: teammate-conductor` boot-prompt block. The flag should NOT be used by main-chat operators — it skips work main chat is supposed to do (engineer, critic, plan authorship). Mismatch detection: if `--teammate` is invoked but no `INVOCATION-CONTEXT` boot block is present, HALT with `TEAMMATE-FLAG-MISUSED` and refuse.

The remainder of this document describes the **solo path** (no `--teammate`). For the teammate path, jump to §"Teammate path (`--teammate` flag)" below.

## Step 0 — Auto-orient (ALWAYS first, every invocation)

1. **Load shepherd skill context** — invoke `shepherd` via the Skill tool. This loads `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/SKILL.md` and the conductor quick reference.

2. **Read shepherd.toml** — `.claude/shepherd.toml` (or `.local.toml` override). If missing, surface a warning and proceed with framework defaults per `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md`. If the file fails validation, STOP and surface the error.

3. **Detect current branch** — `git branch --show-current`. Match against `[branching].sprint_branch_pattern`. If on a sprint branch → that is the active sprint. If on the patch branch → cut the next sprint branch first, per `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/branching-model.md` §II.

4. **Load project doctrines** — read every `*.md` under `[memory].project_doctrines` (default `.claude/doctrines/`) and inject as a preamble to every flock dispatch this session.

5. **Fetch most recent handoff** — `ls -t {paths.docs}/*-close-handoff.md | head -1`. Read it. Extract: what shipped last sprint, current carry-forwards + GH issue numbers, deploy state, first task for this sprint.

6. **Read project CLAUDE.md** — current workspace state, active version, deploy state, in-progress context.

7. **Synthesize orientation** internally (one paragraph — not shown unless operator asks):
   - Sprint identity (version + sprint slot)
   - Prior close grade + outstanding blockers
   - Carry-forwards that must land this sprint
   - What the seed says the north-star is

Then proceed to Step 1.

---

## Step 1 — Load conductor profile

Read `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` in full and adopt it as a system-prompt addendum for this session. The conductor profile is the single source of truth for sprint-runner behavior: pipeline structure, dispatch rules, Stage Graph walk algorithm, gate discipline, close synthesis, halt codes, and operator communication norms. All behavioral prescriptions for running the sprint live there.

---

## Step 2 — Run pipeline

Execute the three-section pipeline per `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` §§Step 1–3 (INTRODUCTION → BODY → CLOSE). After CLOSE-FINALIZE completes and the CONDUCTOR CLOSE REPORT is emitted, this command halts and waits for operator sign-off — single-sprint discipline enforced. Re-invoke `/shepherd:start` for the next sprint, or `/shepherd:spawn --scope patch` for the teammate-driven sequential autopilot.

---

## Teammate path (`--teammate` flag) — v5.1.6+

When invoked as `/shepherd:start --teammate`, the session is a spawned teammate. The execution path is materially different.

> **Begin immediately (v6.0.5).** A spawned teammate invokes `/shepherd:start --teammate` on its FIRST turn, without waiting for a "go" message from root — the lane brief in the boot prompt is the instruction to start. A teammate that idles waiting to be told to begin is the teammate side of the dispatch-boundary deadlock the root's active-drive contract closes (`doctrines/coordinate-active-drive.md §III`).

### Step T0 — Verify invocation context (v6.0.0 — hardened checklist)

Read the boot-prompt addendum for an `INVOCATION-CONTEXT` block. **All four checks below must pass in order.** Stop at the first failure with the named halt code.

**Check 1 — `INVOCATION-CONTEXT` block present.**

The block must exist with the required field shape:

```
ROOT-SESSION-NAME: shepherd-root @ <session-id>
INVOCATION-CONTEXT:
  dispatcher: teammate-conductor
  spawn_session: <team-id>
  scope: <sprint|patch|...>
  fanout_mode: <lane|sprint>
  lane_index: <i_of_L_w>       # lane mode only
  wave_index: <w_of_W>         # lane mode only
  ...
```

Missing block → HALT with `TEAMMATE-FLAG-MISUSED` and surface:

```
/shepherd:start --teammate: REFUSED — no INVOCATION-CONTEXT block found in boot prompt.

This flag is intended for sessions spawned by /shepherd:spawn. Main-chat solo
operators should invoke /shepherd:start (no flag) for the full pipeline.
```

**Check 2 — `dispatcher` field is `teammate-conductor`.**

Other values (e.g., `root-shepherd`, `solo-conductor`, missing) → HALT with `TEAMMATE-BOOT-MALFORMED` and `SendMessage(to: lead, halt_code: TEAMMATE-BOOT-MALFORMED, blocking: true)`. Do not guess what the operator meant — boot prompt is the contract.

**Check 3 — Lane brief slice present in boot prompt.**

The boot prompt must include the assigned lane's seven-bracketed-section brief slice (`[ROLE]`, `[FILE-SCOPE]`, `[CONTEXT-INVENTORY]`, `[DO-NOT-DUPLICATE]`, `[ACCEPTANCE]`, `[NON-GOALS]`, `[WORKTREE]` or per the wave's micro-Stage-Graph). Missing → HALT with `TEAMMATE-BOOT-MALFORMED`. A teammate without a lane brief has nothing to execute.

**Check 4 — `ROOT-SESSION-NAME` populated.**

Missing root-session identifier means escalation routing is broken — `SendMessage(to: lead, ...)` calls won't reach root. HALT with `TEAMMATE-BOOT-MALFORMED`.

All four checks pass → proceed to Step T1.

### Step T1 — Load conductor profile in TEAMMATE mode

Read `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` and self-detect TEAMMATE mode per §"Conductor modes" (signals 3 and 4 — boot prompt contains the relevant blocks). Surface:

```
[SESSION-START] mode=teammate | lane={lane_id} | wave={wave_index} | sprint={sprint_slug}
```

### Step T2 — Read assigned lane brief

The boot prompt includes the lane brief slice (lane_id, wave, file_scope, parallel_with, steps, acceptance). This is your ENTIRE instruction set. Do NOT re-mesh; do NOT re-engineer; do NOT re-critic — root already did those.

### Step T3 — Walk the lane's micro-Stage-Graph

A typical lane walk:

1. **DEDUP-GATE** — run `[DO-NOT-DUPLICATE]` greps from the lane brief. Block if any unexpected hits.
2. **IMPL** — dispatch `@coder` with the lane brief as the coder's brief. The coder writes to the worktree at `INVOCATION-CONTEXT.worktree_path`. Single coder per lane is the norm; complex lanes may warrant `@worker` or `@discovery` support.
3. **LANE-CLOSE** — read coder output, verify `[ACCEPTANCE]` greps, prepare WAVE-COMPLETE payload.

Throughout: peer messaging permitted per `agents/conductor.md §Teammate-to-teammate communication` (status updates, joint pre-surface). No artifact writes (root materializes); no engineer/critic dispatch (root-tier-exclusive); no git commits (root commits on wave-complete).

### Step T4 — Surface WAVE-COMPLETE

```
SendMessage(to: lead, {
  phase: "body-wave-{wave_index}-lane-{lane_id}",
  halt_code: null,
  blocking: false,
  context_files: ["<lane-output-summary>"],
  loc_delta: {add: N, del: M},
  acceptance_results: {<grep>: <count>, ...}
})
```

Then idle. Root materializes your wave artifacts, runs the wave-gate after all sibling lanes close, and decides next action.

### Step T5 — Pause for resume

You are an ephemeral teammate. After WAVE-COMPLETE, you remain available for follow-up dispatch (hot-fix, second wave) from root. If root sends a resume reply with another lane brief, walk that lane through T3–T4. If root closes the team, you exit.

---

## See also

- `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` — full conductor profile; §"Conductor modes" for solo vs teammate mode detection
- `${CLAUDE_PLUGIN_ROOT}/agents/shepherd.md` — root-tier profile (the dispatcher behind `--teammate`)
- `${CLAUDE_PLUGIN_ROOT}/commands/spawn.md` — teammate-spawn entry (`--scope`, `--parallel`)
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/flock.md` — per-agent dispatch rules
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/dispatch-tier-separation.md` — three-tier dispatch matrix
- `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` — shepherd.toml schema
