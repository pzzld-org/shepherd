---
title: mid-flight-operator-amendment
description: |
  Protocol for handling operator amendments that arrive while a sprint is actively
  in-flight (coders dispatched, gates running, or results pending). Classifies
  amendments by type, defines the conductor response for each, and requires
  every amendment to be traceable in the close report.
introduced: v5.0.6
field-origin: axiom v0.3.1-dev.8a, 2026-05-12
---

# Mid-Flight Operator Amendment Protocol

## Why this exists

Sprint walks are not atomic. Operators observe the sprint in progress, notice mismatches between what's being built and what's needed, and amend. This is healthy — it's the whole point of a pause-and-inspect rhythm. But without a documented protocol, the conductor improvises a different response each time, and amendments become invisible to the close report and the next sprint's planning.

This doctrine standardizes four amendment types and the conductor response for each.

---

## I. Amendment classification

When the operator provides new information mid-sprint, classify it before acting:

| Type | Description | Example |
|---|---|---|
| **Clarification** | Resolves ambiguity in an existing lane — no new work, no new scope | "Package naming should be `axiom-dashboard`, not `axiom-ui`" |
| **Feature addition** | New work item not in the original seed or plan; fits within the sprint | "Develop criterion benchmarks under `crates/axiom/benches`" |
| **Production regression** | A live system is broken; the sprint must at minimum acknowledge it and dispatch a diagnostic or triage | "Memory leak is back; bots dark; gateway dark" |
| **Architectural decision** | Changes a foundational design choice; may affect multiple sprints or the current sprint's direction | "Redeemer should become a Worker pattern" |

---

## II. Response per type

### Clarification

1. Ask for confirmation via `AskUserQuestion` if the amendment could be read two ways.
2. Apply as a **dispatcher-patch** — amend the affected lane's brief inline, without engineer re-dispatch.
3. Log to the dispatcher-patch ledger at `{paths.ctx}/dispatcher-patches/{sprint_slug}-pc-{N}.md` (see §III).
4. Do NOT stop the active coder dispatch; fold into the NEXT brief if that coder is already in-flight.

### Feature addition

1. File a GH issue (`mcp__*__issue_write`) to anchor the new work: title, description, acceptance criteria.
2. Determine wave placement — can this run as a parallel-safe coder in the CURRENT wave, or does it need a new wave?
   - Current wave (parallel-safe, file-disjoint): add as a new lane to the next WAVE-IMPL batch.
   - Needs its own wave: add a `WAVE-N+1-IMPL` node to the Stage Graph (conductor inline amendment — brief the engineer if scope is L+, otherwise do it inline).
3. Log to the dispatcher-patch ledger.
4. If the addition pushes the sprint size above its T-shirt estimate, surface to operator: "This amendment makes the sprint L; do you want to defer one existing lane?"

### Production regression

1. File one GH issue per regression symptom (P0/P1 severity) — `mcp__*__issue_write`.
2. Dispatch a **W-E (production diagnostic) worker** immediately — do NOT wait for the current wave to complete. Fire W-E in parallel with whatever is running.
   - Brief: `[DELIVERABLE]` enumerate exact failure signals per regression issue; propose targeted HF coders per symptom; `[SOURCES]` fly logs, Sentry, Supabase advisors; `[BUDGET]` 15 min, 40 tool calls.
3. When W-E returns, use its recommendations to dispatch one or more HF coders targeting the regression — or, if the regression is out-of-scope for the sprint, mark the issue `deferred` with target sprint + justification.
4. Log to the dispatcher-patch ledger with P0/P1 severity tag.
5. Add a `§"Operator amendments"` section to the close report (see §IV).

### Architectural decision

1. Ask the operator for scope: "Does this affect the current sprint, or future sprints?"
   - Current sprint affected → surface to @critic as a mid-flight amendment (PROCEED or ESCALATE).
   - Future sprints only → file GH issue; write a spec stub at `{paths.docs}/specs/<date>-<topic>-design.md`; note in current sprint handoff.
2. If the current sprint's plan must change: treat as a soft HARD-STOP — surface to operator, optionally re-dispatch @engineer for a targeted plan revision.
3. Do NOT absorb architectural changes silently. The next engineer MUST know the design changed.

---

## III. Dispatcher-patch ledger

Every mid-flight amendment, regardless of type, gets a one-line entry in the dispatcher-patch ledger.

**Location:** `{paths.ctx}/dispatcher-patches/{sprint_slug}-pc-{N}.md` (sequential N per sprint)

**Entry format:**
```markdown
---
sprint: {sprint_branch}
patch-id: PC-{N}
type: clarification | feature-addition | production-regression | architectural-decision
timestamp: <ISO-8601>
gh-issue: #{N} (or "none")
operator-quote: "<verbatim operator text if present>"
---

## Summary
<one sentence: what was amended>

## Response
<what the conductor did: dispatcher-patch | new coder lane | W-E dispatch + HF | plan revision>

## Effect on Stage Graph
<"none" OR "added node {id}" OR "amended brief for {lane-id}">
```

The ledger is append-only within a sprint. At sprint close, the `completeness` auditor reads it and verifies every amendment has a disposition.

**Why verbatim operator quotes:** future engineers and planters reading the ledger should recover the operator's intent from their own voice, not the conductor's paraphrase.

---

## IV. Close report §"Operator amendments"

Every close report MUST include this section when one or more amendments occurred:

```markdown
## Operator amendments folded

| PC# | Type | GH# | Operator text | Disposition |
|---|---|---|---|---|
| PC-1 | clarification | — | "package naming should be X" | Folded into L3 brief inline |
| PC-2 | feature-addition | #1087 | "develop criterion benchmarks" | New Lane L1c dispatched, landed |
| PC-3 | production-regression | #1083 #1084 #1085 | "memory + bots + gateway dark" | W-E dispatched, HF-1 + HF-2 dispatched, partial fix landed, residual deferred to dev.9 |
```

If no amendments occurred, omit the section.

---

## V. What NOT to do

- **Do NOT silently absorb** an amendment into the active wave without filing an issue. Silent absorption makes the sprint non-reproducible.
- **Do NOT stop the sprint to re-plan from scratch** unless the operator explicitly says the sprint's north star has changed. In-flight re-seeding is expensive; fold what you can, defer what you can't.
- **Do NOT defer without a target.** Every deferral names a target sprint (`dev.{N}` or next patch), a target milestone, and a justification.
- **Do NOT apply architectural changes inline** without surfacing them. Architecture that changed mid-sprint must appear in the handoff so the next engineer plans from correct ground state.

---

## VI. HARD-STOP triggers within amendments

Some amendment content warrants a hard stop, not a fold:
- Amendment implies secret/credential rotation required
- Amendment implies the sprint's north star has changed (operator effectively is re-seeding mid-flight)
- Amendment reveals a security vulnerability in production that requires immediate rollback

When a hard stop is triggered, surface `HARD-STOP — mid-flight amendment: {reason}` to the operator and stop the walk.

---

## VII. Cross-doctrine references

- `doctrines/chain-repair.md` — mechanical vs substantive drift; architectural decisions may trigger chain-repair
- `doctrines/carry-forward-refresh.md` — production regressions that can't land in the current sprint become CRITICAL carry-forwards
- `doctrines/adaptation-loop.md` — amendment types and frequency are tracked in the sprint pattern registry
- `doctrines/stage-graph.md` — the Stage Graph is amended inline for feature additions (new node); the conductor documents the amendment in the walk trace
- `flock.md §worker @worker dispatch patterns` — W-E production diagnostic is a standard worker pattern
