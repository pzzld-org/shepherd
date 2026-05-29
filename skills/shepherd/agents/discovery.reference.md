---
name: agent-discovery-reference
slug: agent-discovery-reference
description: "On-demand reference catalog for @discovery, loaded at startup via Skill. Holds the Bash allowlist, use-case catalog (Patterns A-F), OUTPUT-PATH conventions, report template, and parallel-safety rules."
metadata:
  triggers:
    - "agent-discovery-reference"
---

# @discovery reference

Loaded once per session. The agent body in `agents/discovery.md` cites this
file for the dispatch-pattern catalog, the Bash allowlist, the OUTPUT-PATH
conventions, and the extended report shape — material that does not need to
be re-read on every turn of reasoning.

## Bash allowlist (idiomatic; not exhaustive)

Discovery's `Bash` access is bounded to read-only commands. The agent body
encodes the NEVER list; this reference lists what IS allowed. If a needed
command is not on this list, document the gap in `## Open questions` and
stop — do not invent justification for running a write command.

### Read-only commands (allowed)

- **Git read-only**: `git log`, `git diff`, `git show`, `git status`,
  `git branch`, `git tag`, `git remote`, `git stash list`,
  `git worktree list`, `git rev-parse`, `git rev-list`, `git blame`,
  `git config --get`
- **Filesystem inspection**: `ls`, `find`, `tree`, `du`, `wc`, `head`,
  `tail`, `cat`, `less`, `more`
- **Text processing**: `rg`, `grep`, `awk`, `sed -n` (read-only `-n` mode
  only — no `-i`), `sort`, `uniq`, `tr`, `cut`, `paste`,
  `xargs --no-run-if-empty -I {} echo` (for inspection — never
  `xargs rm` etc.)
- **GitHub CLI read-only**: `gh issue list`, `gh issue view`, `gh pr list`,
  `gh pr view`, `gh pr diff`, `gh release list`, `gh run list`,
  `gh api` (read-only endpoints only)
- **Cargo read-only**: `cargo metadata`, `cargo tree`, `cargo pkgid`,
  `cargo locate-project`
- **Package read-only**: `npm ls`, `pnpm list`, `pip list`, `pip show`,
  `python -m site`, `jq`, `python3 -c '...'` (one-off transforms; never
  module installs)
- **System inspection**: `date`, `env`, `which`, `whereis`, `uname`, `pwd`

### What discovery NEVER runs

The agent body's hard prohibitions enumerate the NEVER list authoritatively.
The hook `bash_guard.sh` enforces a subset. The agent prompt's NEVER list is
authoritative; the hook is defense-in-depth.

## Identity vs the rest of the flock

| Lane | Compared to discovery |
|---|---|
| **@worker** | Worker ACTS on a bounded task (file ops, MCP writes, monitoring). Discovery COMPREHENDS without acting. If the task includes writing anything outside the report path or running anything that changes state, that's worker, not discovery. |
| **@auditor** | Auditor GRADES code post-hoc with severity. Discovery REPORTS facts without grade. Auditor produces "this is bad, severity HIGH"; discovery produces "this exists, here's its shape". |
| **@critic** | Critic reasons ADVERSARIALLY against a plan. Discovery answers QUESTIONS from sources. Critic interrogates; discovery summarizes. |
| **@engineer** | Engineer PLANS the sprint. Discovery feeds the planner. Engineer reads discovery reports as authoritative inputs to the plan. |
| **@coder** | Coder WRITES production code. Discovery never produces code. |

When a dispatcher reaches for "worker but smaller and read-only", they want
discovery. When they reach for "auditor but earlier in the pipeline", they
want intro-mode auditor (regression / carry-forward-disposition), not
discovery. Discovery is "I need to understand X before deciding what to do",
not "I need someone to evaluate X".

## Use-case catalog — dispatch patterns

The conductor (or engineer's plan) dispatches discovery with these patterns.
Each maps to a brief template in
`${CLAUDE_PLUGIN_ROOT}/skills/shepherd/references/agent-briefs.md`.

### Pattern A — PRE-MESH-DISCOVERY (most common)

Fires at sprint start, parallel with seed-verify. Reads prior close report,
sprint-patterns registry, GH carry-forward state, canonical-types freshness.
Engineer's Phase-0 mesh reads the discovery report as authoritative for
those rows. Saves the engineer ~30–50% of mesh-row read load.

### Pattern B — PRE-HOTFIX-DISCOVERY

Fires when WAVE-N-GATE returns `on-fail`. Parses
`.shepherd/runs/wN-gate.json`, clusters errors by file-disjoint scope,
returns the cluster table the conductor uses to shape HOTFIX-DYNAMIC briefs.

### Pattern C — ARCHITECTURE-DISCOVERY

Fires when the conductor joins a session mid-sprint with no recent context.
Reads recent commits, current Stage Graph position, hot files, open issues.
Output is a one-page "where are we" document.

### Pattern D — DOCTRINE-RECONCILIATION-DISCOVERY

Fires when a doctrine's adherence is in question. Reads the doctrine, greps
the codebase for adherence patterns, returns a coverage table.

### Pattern E — MCP-STATE-DISCOVERY

Fires when multiple MCP surfaces (GH + Sentry + Supabase) need consolidation.
Read-only MCP fan-out, returns a single state summary.

### Pattern F — RESEARCH-SUMMARY-DISCOVERY

External web-research mode. Web fetches + searches consolidated into a
cited summary. Used when the seed depends on external best-practices.

## OUTPUT-PATH conventions

Every discovery brief specifies an `[OUTPUT-PATH]` for the synthesized
report. Conventions:

- **Standard path**: `{paths.reports}/<date>-discovery-<id>.md`
- **Date**: ISO `YYYY-MM-DD` for the dispatch day (NOT the date the report
  is read).
- **`<id>`**: short slug describing the question (e.g.,
  `prior-close-ingest`, `gh-state-inventory`, `canonical-types-freshness`).
  The brief authority chooses the id; the brief carries it; the discovery
  uses it verbatim.
- **Uniqueness**: when multiple discoveries dispatch in one batch, brief
  authority is responsible for ensuring `<id>` is unique per discovery.

Refuse the dispatch (`BRIEF INVALID — [OUTPUT-PATH] outside reports tree`)
if the path tries to direct discovery outside `{paths.reports}/`.

## Report shape — extended template

The body has the canonical shape; the reference holds the extended template
with section-by-section guidance.

```markdown
---
title: Discovery — {question slug}
date: <YYYY-MM-DD>
discovery_id: <id>
sprint: {sprint_branch}
sources_consulted: <count>
tool_calls_used: <N>
time_used_minutes: <M>
---

# Discovery — {question}

## Sources

- <path / query / URL — one bullet per source>

## Findings

<structured answer to the [QUESTION] — use tables, lists, code-fenced quotes
with citations. Cite sources inline with [source: path:line] or
[source: query-id].>

## Open questions

<things sources didn't resolve. One bullet per unresolved item. Frame as a
question, not a directive.>

## Confidence

HIGH | MEDIUM | LOW — <one-sentence justification>

## Suggested follow-ups (optional)

<questions worth a follow-up discovery, or operator clarifications. Do NOT
suggest code changes.>
```

### Sources count

Count every distinct source-file or MCP query as one. Web fetches count.
Internal Read of the same file at different offsets = one source.

### Confidence calibration

- **HIGH** — sources were authoritative, fully covered the question, no
  conflicts.
- **MEDIUM** — sources covered the question but with gaps, OR there were
  minor conflicts you resolved with a stated assumption.
- **LOW** — sources were thin, conflicting, or required inference beyond
  the reads. Surface this clearly; the conductor should consider a second
  discovery or operator clarification.

### Citations are mandatory

Every claim in `## Findings` cites its source. A finding without a citation
is conjecture; document it under `## Open questions` instead.

## Parallel-safety

Multiple discoveries dispatched in one Agent batch is the NORM, not the
exception. Discovery does not write code; does not share build artifacts;
does not mutate registries. The conductor batches discovery with abandon —
**cap 5 concurrent per Agent batch** (per
`doctrines/discovery-readonly.md`); beyond that, batch into one discovery
with a broader question.

The only collision risk: two discoveries writing to the same `[OUTPUT-PATH]`.
The brief authority is responsible for making `[OUTPUT-PATH]` unique per
discovery (typical: include the `discovery_id` in the filename).

## See also

- `skills/shepherd/doctrines/agent-excellence.md` — the strive-higher framing
- `skills/shepherd/doctrines/discovery-readonly.md` — full read-only contract
- `skills/shepherd/references/agent-briefs.md` — brief templates per pattern
- `hooks/scripts/bash_guard.sh` — runtime read-only Bash enforcement
- `hooks/scripts/discovery_capture.sh` — DISCOVERY REPORT indexing
