---
name: agent-worker-reference
slug: agent-worker-reference
description: |
  Reference catalog for @worker. Loaded on demand at agent startup via Skill,
  so per-dispatch content stays out of the agent's stable system-prompt prefix.
  Contains the dispatch pattern catalog (Patterns 1–5), the full
  PAUSE-FOR-DEPENDENCY report template, and the INSIGHTS section template.
metadata:
  triggers:
    - "agent-worker-reference"
---

# @worker reference

Loaded once per session. The agent body in `agents/worker.md` cites this file
for the dispatch pattern catalog, the PAUSE-FOR-DEPENDENCY report shape, and
the optional INSIGHTS section.

## Common dispatch patterns

Each pattern is an example of how the conductor (or engineer's plan) shapes a
worker brief. Brief authors may adapt fields; the canonical shape stays the
same.

### Pattern 1 — Monitor a deploy

```
[DELIVERABLE]   Tail fly logs for 15 min after deploy. Report Sentry-error count + 3 sample log lines per error class.
[SOURCES]       fly logs --app <name> -n 0 -f, mcp__plugin_sentry_sentry__search_events
[BUDGET]        15 min, 50 tool calls
[FORMAT]        Table: error_class | count | sample_line
```

### Pattern 2 — Bulk-issue triage

```
[DELIVERABLE]   Classify every open issue into {blocking, non-issue, tracking-future, drift-risk} per ledger schema.
[SOURCES]       gh issue list --state open --limit 500 --json number,title,labels,milestone
[BUDGET]        20 min, 30 tool calls
[FORMAT]        Markdown table at .artifacts/reports/<date>-issue-triage.md
```

### Pattern 3 — Research summary

```
[DELIVERABLE]   Summarize <doc> against <question>; under 200 words.
[SOURCES]       <doc path>
[BUDGET]        5 min, 10 tool calls
[FORMAT]        Plaintext, under 200 words
```

### Pattern 4 — Branch cleanup audit

```
[DELIVERABLE]   List all local + remote branches matching {orphan pattern}; recommend keep/delete per branch.
[SOURCES]       git branch --all, git log per branch HEAD
[BUDGET]        10 min, 50 tool calls
[FORMAT]        Table: branch | last_commit | recommendation | reason
```

### Pattern 5 — Sprint pattern registry backfill

Use when `{paths.ctx}/sprint-patterns.md` is absent or missing several
sprints' entries (e.g., after installing the adaptation loop mid-patch-cycle).

```
[DELIVERABLE]   Read the last N close-time audit reports and synthesize one sprint-patterns.md entry
                per missing sprint, appending in chronological order.
[SOURCES]       {paths.reports}/*-close.md, {paths.reports}/*-audit-completeness.md
[BUDGET]        15 min, 40 tool calls
[FORMAT]        Append-mode write to {paths.ctx}/sprint-patterns.md (create with header if absent)
[OUT-OF-SCOPE]  Do NOT modify source code. Do NOT create GH issues. Write only to sprint-patterns.md.
```

Note: this pattern is only needed for backfill. Going forward, the
completeness auditor writes entries at each sprint close automatically (per
`doctrines/adaptation-loop.md §II`).

## PAUSE-FOR-DEPENDENCY — full report template

> Full protocol: `doctrines/pause-for-dependency.md`. Workers are secondary
> users (after coders) of this primitive. Emit it when an authorized task
> presumed an artifact (config file, data export, cached query, deploy log)
> that turns out to be absent AND outside your scope.

### Trigger conditions (all three must hold)

1. A required input file / data source / config does not exist in the
   workspace.
2. Producing it falls outside your `[DELIVERABLE]` scope.
3. No parallel-sibling agent is producing it.

### Pre-pause verification

Before pausing, verify the thing is not already elsewhere — `ls`, `shctx
search`, `mcp__plugin_*__list_*` — depending on what is missing.

### Report shape (emit IN PLACE OF the normal WORKER REPORT)

```
## WORKER REPORT — PAUSE-FOR-DEPENDENCY

- Lane: <brief-id>
- Halt code: PAUSE-FOR-DEPENDENCY
- Role: worker
- Reason: <one sentence>
- Satellite brief request:
    target_path:         <file/data path that's missing>
    file_scope_proposed: <files/artifacts the satellite produces>
    work:                <what the satellite does — max 3 sentences>
    estimated_size:      XS | S
    new_symbol_or_path:  <exact path or identifier needed>
    satellite_role:      worker  (or coder if code is needed)
    acceptance:          <runnable command that succeeds when satellite done>
- State at pause:
    branch:   n/a
    wip_sha:  n/a
- Resume condition: <what I need to see before continuing>
- Reporter: <agent-id> @ <ISO-8601 timestamp>
```

### Cap

Max **2 pauses per dispatch**. A 3rd indicates the brief was structurally
under-scoped; emit `BRIEF-AMENDMENT REQUEST` instead.

The conductor's `agent_pause_detector.sh` hook captures this report and
writes it to `.shepherd/pauses/<id>.json` automatically. The conductor
dispatches the satellite, then `SendMessage`s you to resume.

## Optional: ## INSIGHTS (cross-lane observations)

Workers see the workspace differently from coders — you sweep across crates,
run queries, scan logs. You are often the first to notice structural
patterns (duplicated config across services, drift between deploys, etc.).
Per `doctrines/flock-cohesion.md`, you MAY append a `## INSIGHTS` section to
your WORKER REPORT for the engineer's next-sprint planning.

```
## INSIGHTS

- kind: relocation | extension | duplication | consolidation | gap | nit
  subject: <symbol, file path, or operational artifact you observed>
  observation: <one sentence>
  rationale: <one sentence>
```

Optional. Skip if you have nothing structural to surface. Use the same
canonical kinds as coders. The `agent_insight_capture.sh` hook auto-records
each entry.

### Insight kinds (canonical)

| Kind | When to use |
|---|---|
| `relocation` | A symbol or file lives in the "wrong" package/module and would clarify things to move |
| `extension` | A type/trait/function would benefit from a small extension to support a real use case you saw |
| `duplication` | Two or more places implement the same logic and a consolidation pass would help |
| `consolidation` | Multiple small artifacts could merge into one (the inverse of relocation; SUBTRACT candidate) |
| `gap` | A capability the workspace should have but does not — observed missing during your task |
| `nit` | Style or naming observation; aggregate sparingly — never one nit per report |

## See also

- `skills/shepherd/doctrines/agent-excellence.md` — strive-higher framing
- `skills/shepherd/doctrines/pause-for-dependency.md` — full PAUSE protocol
- `skills/shepherd/doctrines/flock-cohesion.md` — INSIGHTS rationale
- `skills/shepherd/doctrines/adaptation-loop.md` — sprint-patterns registry
