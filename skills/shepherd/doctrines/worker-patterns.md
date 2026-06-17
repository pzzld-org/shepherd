# Worker dispatch patterns — when conductor offloads non-code work

`@worker` is the flock's bounded-task executor. The conductor uses it to keep its own context lean and focused on plan walking + dispatch decisions. This doctrine codifies WHEN to dispatch and WHAT briefs work well.

**Default posture: worker-first for bounded ops** (`doctrines/dispatch-generosity.md`). When a task fits the heuristic below, dispatch `@worker` rather than inlining it into your own turn. Inlining a worker-shaped task is the most common form of flock under-utilization — and because gate-free fan-out compiles out-of-context (the Workflow tool is enabled across entrypoints; `doctrines/workflow-compile-down.md`), dispatching a worker costs your context window LESS than inlining, not more. When in doubt, dispatch.

## Heuristic — when to dispatch worker (not inline)

Dispatch worker when ANY of the following hold:

- Task is IO-bound for > 5 minutes (deploy log tail, build watch, pulse-poll an external system).
- Task involves > 10 MCP calls in sequence (issue triage, schema enumeration, batch label changes).
- Task produces a structured deliverable that doesn't need to land in main-chat context (research summary, classification table, file-organization report).
- Task can run in parallel with main-chat work without contention.
- Inlining would consume > ~1000 tokens for an operation that produces a small final answer.

Inline ONLY when: the result is a one-line answer the conductor needs immediately for the next dispatch decision, AND producing it is trivial (a single read/grep). Everything heavier is a `@worker` dispatch (`doctrines/dispatch-generosity.md §III`).

## Brief shape for non-code work

```
@worker brief
DELIVERABLE: <one sentence — the artifact that lands>
SCOPE: <tight bound — files, MCP scope, time window>
INPUTS: <required reads — paths, MCP queries, prior artifacts>
OUTPUT FORMAT: <markdown table | JSONL | summary paragraph | ...>
BUDGET: <time / tokens / iterations>
HALT CONDITIONS: <what the worker should refuse>
```

## Pattern catalog

### Issue-ledger triage

When the engineer's Phase 0 mesh surfaces > 30 open issues, dispatch worker:

```
DELIVERABLE: classify all open issues into {drift-risk, current-milestone, non-issue, tracking-future} per the ledger schema; report as markdown table.
SCOPE: GitHub `state:open`; full ledger.
INPUTS: open-issue list (already in DB via `shctx query open-issues --json`); `[ledger.classify_into]` from shepherd.toml.
OUTPUT FORMAT: markdown table — `| # | title | bucket | reason |`.
BUDGET: 15 min, 5K tokens.
HALT CONDITIONS: contradictory labels — flag and continue.
```

### Deploy monitor

After a deploy, watch logs:

```
DELIVERABLE: tail deploy logs for 15 min; report Sentry-error count + sample lines.
SCOPE: `fly logs` (or equivalent) for current app.
OUTPUT FORMAT: 1-paragraph summary + table of errors.
BUDGET: 15 min wall.
HALT CONDITIONS: deploy rolled back — exit immediately and surface.
```

### Branch cleanup

After a sprint close:

```
DELIVERABLE: list local + origin branches matching {sprint_branch_pattern} that are merged into {patch_branch}; recommend deletions; do NOT execute (operator confirms).
INPUTS: `git branch --merged`, `git branch -r --merged`.
OUTPUT FORMAT: markdown table — `| branch | last commit date | recommend |`.
BUDGET: 5 min.
```

### Research summary (web/MCP scrape)

When a design decision needs external context:

```
DELIVERABLE: 5-bullet summary of <topic> with citations; flag any operator-prior-art references.
INPUTS: <specific URLs | search queries>.
OUTPUT FORMAT: markdown bullets, each with [source] suffix.
BUDGET: 10 min, 8K tokens.
HALT CONDITIONS: no authoritative sources found — surface "insufficient" and exit.
```

### File organization (non-code)

When `.artifacts/` accumulates clutter:

```
DELIVERABLE: classify .artifacts/docs/journal/*.md into {keep, archive, prune}; recommend rotation; do NOT delete.
INPUTS: `ls -la .artifacts/docs/journal/`, `shctx query mem-search --q=<term>` for cross-references.
OUTPUT FORMAT: 3-column table.
BUDGET: 5 min.
```

## Anti-patterns

- **"Worker should write code."** No — `@coder` writes code. Worker owns bounded non-code deliverables.
- **"Worker can run inline; same context."** Wrong — the point of dispatch is context isolation. If the work is so small that dispatch overhead exceeds the value, inline it; otherwise dispatch.
- **"Worker decides when to halt."** No — `HALT CONDITIONS` are explicit in the brief. The conductor designs the halt; the worker honors it.
- **"Worker reads the full project."** Wrong — `INPUTS` are explicit. Workers do not browse.
- **"Worker can call other agents."** Wrong — workers are leaf dispatches. They never compose flock work.

## See also

- `flock.md` § @worker — full agent contract.
- `references/agent-briefs.md` § @worker — copy-paste templates.
- `agents/worker.md` — system prompt body.
