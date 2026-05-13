---
title: PAUSE-FOR-DEPENDENCY — agent-initiated satellite dispatch
description: |
  Generic Stage Graph primitive for mid-task out-of-scope dependencies. ANY
  flock agent (coder primarily; worker secondarily; auditor rarely) can emit
  a structured halt → conductor dispatches a satellite agent of the appropriate
  role → SendMessage resumes the paused agent. Replaces silent scope expansion,
  TODO comments, and heavyweight engineer amendment for localized gaps.
introduced: v5.0.9
field_origin: shepherd v5.0.8 conductor feedback (axiom v0.3.2-dev.0) §1
generalized: v5.0.9 — operator request: "available for *any* agent"
---

# Doctrine — PAUSE-FOR-DEPENDENCY

A mid-task agent discovers their acceptance criteria require something
outside their scope (a missing public symbol, a file the brief did not
authorize, data that hasn't been collected). Three pre-v5.0.9 options were
all bad: silent scope expansion (caught by audit), TODO/deferred comment
(banned), or engineer `BRIEF-AMENDMENT REQUEST` (forces a full plan
revision + critic re-gate). PAUSE-FOR-DEPENDENCY is the fourth: agent
halts with a structured satellite request, conductor dispatches an XS/S
satellite agent, then `SendMessage`s the paused agent to resume.

## I. Who pauses (general availability)

The primitive is **agent-agnostic** — the framework wiring is the same
regardless of role. Expected frequency:

| Role | Primary trigger | Notes |
|---|---|---|
| `@coder` | Missing public symbol outside `[FILE-SCOPE]` | Primary user; full operational guide in `agents/coder.md §PAUSE-FOR-DEPENDENCY` |
| `@worker` | Missing data, config, or external resource the brief presumed available | Secondary user; emits the same structured report with worker-appropriate `target_path` (e.g., a config file, a cached query result) |
| `@auditor` | Missing audit input (rare — auditors are read-only) | Pauses if a referenced report file is absent; satellite is usually a `@worker` to materialize the file |
| `@engineer` | Almost never — engineers handle scope drift via `BRIEF-AMENDMENT REQUEST`, not PAUSE | Pausing during plan authorship means the seed was incomplete; route to operator instead |
| `@critic` | Never — critic is gated dispatch, no satellites | If critic finds the plan structurally invalid, the verdict is `RED` not a pause |

The satellite agent's **role** is chosen by the conductor based on what's
missing, not by who paused:

- Missing **code** (symbol, type, export) → satellite is `@coder`
- Missing **data, config, or research artifact** → satellite is `@worker`
- Missing **review or sign-off** → escalate to operator (not a satellite)

## II. Agent-side trigger + report (any role)

**Trigger:** during execution, the agent determines acceptance cannot be met
without (a) a thing that does not exist in the workspace, AND (b) the thing
lives outside the agent's explicit scope, AND (c) no parallel-sibling agent
is producing it.

**Before pausing, the agent must verify** the thing doesn't already exist
(role-specific check — `rg` for symbols, `ls` for files, `shctx query` for
data). If verification passes, the agent emits the standard report and
stops:

```
## <ROLE> REPORT — PAUSE-FOR-DEPENDENCY

- Lane: <brief-id>
- Halt code: PAUSE-FOR-DEPENDENCY
- Role: coder | worker | auditor
- Reason: <one sentence>
- Satellite brief request:
    target_path:         <file(s) that need the thing>
    file_scope_proposed: <files the satellite MAY MODIFY/PRODUCE>
    work:                <what the satellite does — max 3 sentences>
    estimated_size:      XS | S
    new_symbol_or_path:  <exact identifier or path needed>
    satellite_role:      coder | worker
    acceptance:          <runnable command that succeeds when the satellite is done>
- State at pause:
    branch:   <worktree branch, or 'n/a' for workers>
    wip_sha:  <7-char SHA, or 'none' / 'n/a'>
- Resume condition: <what I need to see before continuing>
- Reporter: <agent-id> @ <ISO-8601 timestamp>
```

Role-specific operational guidance:
- **Coders**: `agents/coder.md §PAUSE-FOR-DEPENDENCY` (canonical bash greps)
- **Workers**: emit the same report; `target_path` may be a config/data
  artifact; `satellite_role` is usually `worker` unless code is needed.
- **Auditors**: read-only; if pausing, `satellite_role: worker` to
  materialize the missing input.

## III. Conductor protocol

| Step | Action |
|---|---|
| 1 | **Hook auto-captures** the pause: `agent_pause_detector.sh` writes the structured request to `.shepherd/pauses/<id>.json` and surfaces a context alert. The conductor reads from the JSON, not by re-parsing the agent's text. |
| 2 | **Validate.** `estimated_size` must be XS or S. `file_scope_proposed` disjoint from active/pending agents. `new_symbol_or_path` must not already exist (re-run the appropriate check). |
| 3 | **Dispatch satellite** of `satellite_role` with `isolation: "worktree"`. Standard 7-section brief. Commit template: `fix(dev.N/satellite-<lane-id>): <work-summary>`. `[NON-GOALS]`: "Do not implement the paused agent's task; produce the satellite deliverable only." |
| 4 | **After satellite commits:** rebase satellite onto sprint branch FIRST. Record SHA. Run `shctx pauses resolve <id> --satellite-sha=<sha>`. |
| 5 | **Resume.** `SendMessage` to the paused agent's id with the resume signal. |
| 6 | **Await resumed REPORT**, then proceed to `WAVE-N-GATE` (coder pauses) or the agent's normal join point (worker / auditor pauses). |

Escalation: if `estimated_size` is M+, OR the same lane already has 2
active satellites, return `BRIEF-AMENDMENT REQUEST` to the engineer
instead — the plan itself was wrong, not just the dep surface.

## IV. Mechanization (hook + shctx)

The pause flow is **hook-mechanized** end-to-end:

1. `PostToolUse(Agent)` hook (`hooks/scripts/agent_pause_detector.sh`) —
   parses agent output for `Halt code: PAUSE-FOR-DEPENDENCY`, extracts
   the structured satellite request, writes
   `.shepherd/pauses/<uuid>.json`, and injects an `additionalContext`
   alert into the conductor's stream.
2. `shctx pauses list` — enumerate active pauses (status=active).
3. `shctx pauses show <id>` — dump the JSON for one pause (the conductor
   reads structured fields, not free-form text).
4. `shctx pauses resolve <id> --satellite-sha=<sha>` — mark as resolved
   after the satellite lands; records resolution timestamp + SHA.
5. `shctx pauses clear` — prune resolved pauses older than N days.

The hook eliminates the LLM parsing step; the registry eliminates manual
state tracking. The conductor's only LLM-driven step is the satellite
brief authoring (Step 3).

## V. Cap rules

| Rule | Limit | On violation |
|---|---|---|
| Satellite size | XS or S only | Escalate to `BRIEF-AMENDMENT REQUEST` |
| Satellites per paused agent | ≤ 2 | 3rd pause → escalate; the task was under-decomposed |
| Satellite scope | ≤ 2 files / artifacts | Split or escalate |
| Recursive pause | Satellites CANNOT pause | Satellite halts with `BRIEF-AMENDMENT REQUEST` instead |

A paused agent needing 3+ satellites signals the engineer plan was
under-scoped; the auditor flags this in CLOSE-SWARM as a planning-quality
observation (not a grade-cap — a signal for the next plan).

## VI. Cherry-pick order invariant (coder pauses)

For coder pauses, the git log on the sprint branch MUST read:
`<sprint base> → <satellite commit> → [other wave commits] → <resumed lane commit>`

Reasons: resumed lane's compile depends on satellite's symbol; `git
bisect` identifies provider before consumer. WAVE-AUDIT verifies the
ordering. Reversed order → `STAGE-GRAPH-VIOLATION` finding.

Worker pauses produce no commits and have no ordering constraint —
the resume signal is "the artifact is now present".

## VII. PAUSE-FOR-DEPENDENCY vs. BRIEF-AMENDMENT

| Path | Use when | Owner | Plan cost |
|---|---|---|---|
| `PAUSE-FOR-DEPENDENCY` | Task goal correct; one specific thing absent | Agent → conductor (hook + inline dispatch) | None — satellite is ephemeral subgraph |
| `BRIEF-AMENDMENT REQUEST` | Task goal, scope, or non-goals must change | Agent → conductor → engineer | Engineer revision + critic re-gate |

## VIII. Stage Graph encoding

Structurally anticipated (like HOTFIX-DYNAMIC, cardinality at runtime — see
`pipeline.md §II`). Engineer doesn't pre-declare; conductor adds the
subgraph when a pause is detected:

```yaml
- id: pause-dep-<agent-id>
  type: PAUSE-FOR-DEPENDENCY            # conductor-inline validate
  in_predicates: [{ predecessor: <any-agent-node>, edge: on-pause-dep }]
  out_edges:
    - { label: on-satellite-dispatched, target: satellite-<agent-id> }
    - { label: on-hard-stop,            target: hard-stop }

- id: satellite-<agent-id>
  type: HOTFIX                          # reuses HOTFIX dispatch shape (≤ S)
  agents: [{ role: <coder|worker>, count: 1, brief-ref: satellite-brief-<agent-id> }]
  out_edges:
    - { label: on-coder-complete, target: resume-<agent-id> }
    - { label: on-hard-stop,      target: hard-stop }

- id: resume-<agent-id>
  type: RESUME-LANE                     # conductor SendMessage
  out_edges:
    - { label: on-coder-complete, target: <agent's-normal-join-point> }
```

## IX. See also

- `agents/coder.md §PAUSE-FOR-DEPENDENCY` — coder-side operational guide
- `agents/worker.md` — worker-side pause is symmetric; same report shape
- `pipeline.md §II` (stage taxonomy) + `§XV-quint` (subgraph walkthrough)
- `pipeline.md §XV-ter` — `SendMessage` vs spawn mechanics (used at Step 5)
- `hooks/scripts/agent_pause_detector.sh` — `PostToolUse(Agent)` mechanization
- `skills/context/scripts/cmd_pauses.sh` — `shctx pauses` registry CLI
- `doctrines/worktree-confinement.md` — satellite coder writes inside its own worktree
- `doctrines/stage-graph.md` — ephemeral nodes ARE structural; not ad-hoc
