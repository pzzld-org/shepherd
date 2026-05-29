---
title: flock cohesion — agents as a coordinated group, not isolated dispatches
description: |
  Closes the structural gap where each dispatched agent reinvents context from
  scratch. Introduces the shared substrate: sibling-awareness in briefs, an
  INSIGHTS reporting channel for cross-lane discoveries, the insight registry,
  and the engineer's mesh row that consumes insights to drive next-sprint
  scope. Builds on the canonical-types index, the sprint-pattern registry,
  the pause registry, and the trace log — none of which talked to each other
  before v5.0.9.
introduced: v5.0.9
field_origin: |
  Operator observation 2026-05-13: "every agent feels isolated rather than
  acting as part of a larger group so the agents feel like they need to
  re-invent everything every time from scratch." This doctrine names and
  structures the gap.
---

# Doctrine — Flock Cohesion

## I. The gap this names

Before v5.0.9, shepherd's primitives addressed individual agents in
isolation: each `@coder` receives a brief, reads `[CONTEXT-INVENTORY]`,
runs its `[DO-NOT-DUPLICATE]` greps, writes its lane, returns. There was
no formal substrate for an agent to:

- **See what siblings are doing** in the same wave
- **Flag opportunities** they observed outside their lane scope
- **Build on prior agents' discoveries** without re-running the same exploration
- **Recognize that a thing they need is being built next door**

The result is the symptom the operator named: agents feel isolated. Each
re-derives the same context. Cross-cutting patterns surface only at audit
time, when it's too late to act mid-sprint.

The framework's existing primitives (canonical-types index, sprint-pattern
registry, pause registry, trace log) each addressed *one slice* of this
problem. v5.0.9 ties them together into a coherent **shared substrate**.

## II. The shared substrate (four channels)

| Channel | What it carries | Owner | Lifecycle |
|---|---|---|---|
| `canonical-types.md` | The workspace's public symbols + canonical homes + aliases-to-avoid | `@worker` at dev.0; coders incremental at land time | Per-patch baseline, refreshed each dev.0 |
| `<ns>/graph/state.json` + trace | Wave roster, in-flight agents, completed dispatches | `shctx graph` walker | Per-sprint; trace append-only |
| `<ns>/graph/compiled/<seg>.workflow.js` | Compiled fanout segments (#77) | `shctx graph compile` | Regenerated deterministically from `state.json` |
| `<ns>/insights/<id>.json` | **Cross-lane observations from any agent** — relocations, extensions, duplications, consolidations | `agent_insight_capture.sh` hook + `shctx insights` | Cross-sprint; consumed by engineer at Phase 0 mesh row 13 (v5.0.9) |

The fourth channel is the new addition. The first three existed in pieces
already; this doctrine treats them as a unified substrate.

## III. Sibling-awareness in briefs

Every wave dispatch brief now includes a `[SIBLING-LANES]` section listing
the OTHER lanes in the same wave with their `[FILE-SCOPE]` summaries:

```
[SIBLING-LANES]
Wave 1 dispatches you plus these siblings (do NOT touch their MAY-MODIFY paths):
- Lane B (@coder) — crates/engine/src/{store,emit}.rs        — exposes pub fn emit_event
- Lane C (@coder) — crates/web/src/handlers/health.rs        — adds /health endpoint
- Lane D (@worker) — collects sentry baseline for past 48h
```

The brief author (engineer at MESH; conductor at dispatch) populates this
mechanically from the plan's Wave composition. The dispatched agent can:

1. **Avoid duplicating** something a sibling will produce (e.g., "wait,
   Lane B is exposing the symbol I need")
2. **Coordinate** through PAUSE-FOR-DEPENDENCY if a sibling's output is
   the dependency
3. **Flag** if a sibling's scope overlaps inappropriately

This single section eliminates the largest source of "I re-derived everything
from scratch" pain.

## IV. The INSIGHTS report channel (cross-lane discoveries)

Any agent may append an optional `## INSIGHTS` block to their final report.
This is the structured channel for things the agent noticed that are NOT
part of their `[ACCEPTANCE]` but are operationally valuable:

```
## INSIGHTS

- kind: relocation
  subject: crates/store/src/util.rs::normalize_id
  observation: This util is used by 3 lanes' upstream callers; it should
    live in crates/common, not crates/store.
  rationale: Reduces the dep cycle from store→web back to common→{store,web}.

- kind: extension
  subject: crates/engine/src/state.rs::Phase
  observation: Phase enum has 4 variants; lane work hints at a 5th (Drained).
    Worth a small follow-up to add it now.
  rationale: Avoids a future amendment when the new variant is needed.

- kind: duplication
  subject: format!("{:08x}", id) appears in 4 places
  observation: A `fn fmt_id(u32) -> String` helper would consolidate.
  rationale: Audit will flag the 4th hit next sprint anyway.

- kind: consolidation
  subject: crates/engine/Cargo.toml dev-deps
  observation: serde_json and tokio-test both present; only tokio-test used.
  rationale: Cleanup candidate for a future SUBTRACT lane.
```

**Insight kinds** (canonical taxonomy):

| Kind | Means | Typical actor on consumption |
|---|---|---|
| `relocation` | "This thing lives in the wrong module/crate" | Engineer adds a relocation lane in the next sprint |
| `extension` | "This thing should be extended while we're here" | Engineer decides: this-sprint Lane (small) or next-sprint scope |
| `duplication` | "I see N copies of this pattern" | Engineer adds a consolidation lane; auditor uses as evidence |
| `consolidation` | "Two things could merge / dead code present" | Auditor SUBTRACT input; engineer may schedule a SUBTRACT lane |
| `gap` | "Something is missing that the plan didn't anticipate" | Engineer evaluates: amendment, next-sprint lane, or accepted |
| `nit` | "Minor stylistic / naming observation" | Captured but not actioned individually |

Agents are **encouraged but never required** to emit insights. An empty
INSIGHTS section (or no section at all) is fine. Quality > quantity.

## V. Mechanization — `agent_insight_capture.sh` hook + `shctx insights`

The flow mirrors PAUSE-FOR-DEPENDENCY:

1. `PostToolUse(Agent|Task)` hook (`agent_insight_capture.sh`) — parses
   the agent's final response for `## INSIGHTS` blocks, extracts each
   entry, writes `<ns>/insights/<sprint>/<id>.json`.
2. `shctx insights list [--sprint=<branch>] [--kind=relocation|...]` —
   enumerate captured insights.
3. `shctx insights show <id>` — dump one record.
4. `shctx insights export [--sprint=<branch>] [--md]` — render markdown
   for inclusion in next sprint's mesh row 13.
5. `shctx insights clear [--older-than-days=N]` — prune.

The conductor reads structured JSON; no re-parsing of agent text.

## VI. Engineer Phase 0 mesh row 13 — insights review

Per `agents/engineer.md`, Phase 0 mesh now includes:

```
Mesh row 13 — cross-lane insights (v5.0.9, flock-cohesion.md)

shctx insights export --sprint=<previous-sprint-branch> --md

For each insight:
  • relocation / extension / consolidation / duplication / gap →
    consider scoping a lane in THIS sprint
  • nit → record but do not scope unless 3+ similar nits accumulate
  • Insights not actioned: surfaced under "Cross-lane insights
    NOT scoped this sprint" so the operator decides
```

Insights become the feedback loop that makes the flock self-improving:
every sprint's agents leave breadcrumbs for the next sprint's planner.

## VII. The cohesion model in one diagram

```
                Engineer (MESH)
                      │
       ┌──────────────┼──────────────┐
       │              │              │
       ▼              ▼              ▼
[CONTEXT-      [SIBLING-LANES]  ## INSIGHTS
 INVENTORY]    in each brief    in each report
       │              │              │
       │              │              │
       ▼              ▼              ▼
  canonical-      shctx graph    shctx insights
  types.md         state.json     <ns>/insights/
       │              │              │
       │              │              │
       └──────────────┼──────────────┘
                      │
                      ▼
            Engineer (next MESH, row 13)
            reads insights → next plan
```

The substrate is read at MESH, written at DISPATCH and REPORT, and grows
across sprints. No single agent has to "remember" anything — the substrate
remembers.

## VIII. Relationship to existing primitives

| Existing primitive | Relationship |
|---|---|
| `canonical-types.md` (zero-duplicate-tolerance.md) | The static "what exists where". Insights are the dynamic "what should change about where things exist." |
| `sprint-patterns.md` (adaptation-loop.md) | Sprint-level outcomes (grade, halts). Insights are sub-sprint agent discoveries. |
| Native coordination (native-coordination.md) | Cross-lane deps are graph edges (`await`-ordered in the compiled segment); out-of-scope work is a finding at close. Insights are async observations. |
| Trace log (dispatch-cascade.md) | Mechanical state transitions. Insights are semantic observations. |
| `[CONTEXT-INVENTORY]` (agent-briefs.md) | What the engineer pre-loaded for the agent. INSIGHTS are what the agent learned that the engineer didn't know. |

Together they form the **shared substrate** the operator named. No agent
is asked to "remember" — the substrate persists.

## IX. What this doctrine does NOT do

- **Does not turn agents into chatty broadcasters.** INSIGHTS are
  optional. An agent that adds 10 nit insights to every report is
  failing taste, not following doctrine.
- **Does not let agents mutate siblings' work.** `[SIBLING-LANES]` is
  read-only awareness. Cross-lane action still flows through the
  conductor (via PAUSE-FOR-DEPENDENCY or via the next-sprint plan).
- **Does not eliminate `[DO-NOT-DUPLICATE]` greps.** The substrate is
  additive — it complements but does not replace per-lane verification.
- **Does not auto-act on insights.** The engineer (with operator
  oversight) decides which insights become lanes. Auto-acting would
  reintroduce the silent-scope-expansion problem this framework rejects.

## X. Roadmap (v5.0.10+)

Hooks not built here but reasonable next steps:

- **`shctx insights consolidate`** — cluster similar insights across
  sprints to surface chronic patterns ("relocation suggested for
  normalize_id across 3 sprints").
- **`shctx insights demote/promote`** — operator-level disposition
  to control insight visibility (similar to ledger labels).
- **In-wave insight visibility** — let coders in Wave 2 read Wave 1's
  insights mid-sprint (currently only readable at sprint-close auditor
  pass and the next sprint's engineer pass).

These would deepen the flock-cohesion model. The v5.0.9 foundation
keeps the surface minimal and rigorous.

## XI. See also

- `references/agent-briefs.md` — `[SIBLING-LANES]` brief block
- `agents/coder.md`, `agents/worker.md`, `agents/auditor.md` — `## INSIGHTS` report section
- `agents/engineer.md` Phase 0 mesh row 13 — insights review
- `doctrines/zero-duplicate-tolerance.md` — canonical-types static substrate
- `doctrines/adaptation-loop.md` — sprint-pattern dynamic substrate (cross-sprint)
- `doctrines/native-coordination.md` — cross-agent dependency handling (pause-for-dependency retired, #70)
- `doctrines/dispatch-cascade.md` — graph topology + trace
- `hooks/scripts/agent_insight_capture.sh` — capture hook
- `skills/context/scripts/cmd_insights.sh` — insight registry CLI
