# Discovery agents are read-only — comprehension without mutation

`@discovery` is the sixth lane in the shepherd flock (v5.1.1+). It exists to
absorb the conductor's and engineer's read-only exploration load: prior-state
ingestion, codebase orientation, GH state inventory, error-cluster analysis,
research summarization. The discovery agent COMPREHENDS and REPORTS; it never
acts, grades, or proposes.

## Why a sixth lane

Pre-v5.1.1, the conductor and engineer absorbed all read-only exploration
into their own context. Phase 0 mesh routinely read prior close reports,
canonical-types.md, sprint-patterns.md, GH issue listings, advisor
findings — all before the engineer wrote a single plan line. That cost
context the deeper reasoning needed.

`@discovery` offloads this work to a parallel agent. The conductor / engineer
read the discovery report (a structured synthesis) as authoritative for
its scope, freeing their context for the harder reasoning the discovery
report enables.

This is structurally analogous to `@auditor`'s role at sprint close — except
auditors GRADE work that landed (post-hoc with severity), while discoveries
SYNTHESIZE state that exists (pre-hoc, neutral facts). Different verb;
different lane.

## The contract — what discovery DOES and does NOT

| Action | OK | Not OK |
|---|---|---|
| Read source files | ✅ | |
| Run read-only Bash (git log, rg, ls, gh issue list) | ✅ | |
| Query MCP read-only (issue_read, search_*, list_*) | ✅ | |
| WebFetch / WebSearch | ✅ | |
| Write to `{paths.reports}/<date>-discovery-<id>.md` | ✅ | |
| Edit any file | | ❌ |
| Write outside `[OUTPUT-PATH]` | | ❌ |
| Run state-modifying Bash (`rm`, `git commit`, etc.) | | ❌ |
| MCP write (issue_write, apply_migration, ...) | | ❌ |
| Dispatch other agents | | ❌ |
| Propose code changes | | ❌ — surface facts, not recommendations |
| Grade / score / assign severity | | ❌ — that's auditor's lane |

The agent's frontmatter `tools:` list omits Edit, MCP write tools, and Agent —
the absence is the sandbox. `bash_guard.sh` enforces the state-modifying
Bash block at the hook layer.

## When to dispatch discovery vs. worker vs. auditor

| Verb | Lane |
|---|---|
| "Comprehend X for me" | `@discovery` |
| "Synthesize N sources into one answer" | `@discovery` |
| "Read prior reports, surface what's still open" | `@discovery` |
| "Tail logs for 15 min" | `@worker` (acts over time) |
| "Triage 50 issues with label changes" | `@worker` (MCP writes) |
| "Audit lane-K for code quality" | `@auditor` (grades severity) |
| "Verify the prior sprint's acceptance still holds" | `@auditor` in `regression` intro-mode |

When the dispatcher hesitates between worker and discovery, the test is
**does the work mutate state?** If yes → worker. If no, but it acts (monitors,
queries, fans out) over time → worker. If purely read-and-synthesize →
discovery.

When the dispatcher hesitates between discovery and auditor, the test is
**does the work require a verdict?** If yes → auditor. If the output is
facts the dispatcher will weigh → discovery.

## Dispatch parallelism

Multiple discoveries dispatched in one Agent batch is the NORM. Discoveries
don't write source, don't share build artifacts, don't mutate registries.
Cap: **5 concurrent discoveries per Agent batch** (operator-tunable via
`shepherd.toml [stage_graph.intro_wave].parallel_max`).

When multiple discoveries are dispatched together, their `[OUTPUT-PATH]`
values MUST be unique. The brief author (engineer or conductor) is
responsible for ensuring this — typically by including the `discovery_id` in
the filename.

## Report shape (authoritative)

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
<one bullet per distinct source>

## Findings
<structured answer with INLINE citations — every claim cites a source>

## Open questions
<unresolved items as questions, not directives>

## Confidence
HIGH | MEDIUM | LOW — <one-sentence justification>

## Suggested follow-ups (optional)
<questions worth another discovery, or operator clarifications — never code suggestions>
```

**Confidence calibration:**
- **HIGH** — sources were authoritative, fully covered the question, no conflicts
- **MEDIUM** — sources covered the question with gaps OR minor resolved conflicts
- **LOW** — sources thin / conflicting / required inference. Surface this; the
  conductor should consider another discovery or operator clarification.

Citations are MANDATORY in `## Findings`. A claim without citation is conjecture
— document it under `## Open questions` instead.

## Conductor consumption

When a discovery report exists for an upstream node's input, the conductor's
brief-authoring inserts an inline reference block:

```
[DISCOVERY-CONTEXT]
## Source: {paths.reports}/<date>-discovery-<id>.md
<Findings section quoted verbatim>
[/DISCOVERY-CONTEXT]
```

For PRE-MESH-DISCOVERY (the most common case), the engineer's brief auto-
injects `[DISCOVERY-CONTEXT]` for every discovery in the INTRO-COMBO-WAVE.
Engineer reads them as authoritative for the rows of Phase 0 mesh they cover.

## Cross-sprint reuse

The `discovery_capture.sh` hook indexes every DISCOVERY REPORT return at
`<ns>/discoveries/<sprint>/<id>.json` with structured metadata. Before
dispatching a new discovery, the conductor SHOULD run:

```bash
shctx discovery search --question="<paraphrase>"
```

to check if a recent discovery already answered the question. If yes, and
the discovery is still fresh (< 2 sprints old), reuse it instead of
dispatching again.

## Hard rules

1. **Discovery is read-only.** Any mutation = process violation. Auditor
   files `DISCOVERY-WRITE-VIOLATION` finding; grade-caps C+ for the sprint.
2. **Discovery never dispatches.** No Agent / Task tool. Decomposition
   stays within one discovery's context.
3. **Discovery never grades.** No severity, no quality score, no A-F grade.
   If a finding implies severity, surface the fact; let the consumer decide.
4. **Discovery never proposes code.** "Suggested follow-ups" surface
   research questions, not patches. If the discovery agent notices code that
   should change, it surfaces the fact in `## Findings`; the conductor or
   engineer decides what to do.
5. **PRE-MESH-DISCOVERY result is REQUIRED reading for the engineer** when
   present — auto-injected as `[DISCOVERY-CONTEXT]` in the engineer's brief.
   Engineer ignoring discovery context = process violation, surfaced by the
   completeness auditor.
6. **Cap: 5 concurrent discoveries per Agent batch.** Beyond that, batch
   into one discovery with a broader question.

## Capability enforcement (v6.0.1, GH #74)

The read-only contract is **capability-enforced**, not prose- or graph-enforced — it holds even when a non-conductor dispatcher invokes the agent (e.g. a Claude Code Dynamic Workflow runtime, which runs spawned agents in `acceptEdits` and auto-approves edits with no orchestrator in the loop — `workflow-compile-down.md §VII`). Three independent layers:

1. **Allowlist (the primary guarantee).** `agents/discovery.md`'s `tools:` frontmatter grants no `Edit`/`NotebookEdit`, no `mcp__plugin_supabase_supabase__execute_sql`, no `issue_write`, and no other mutating MCP verb — the absence is the sandbox. The runtime grants only the listed tools.
2. **Path-scope hook (the retained `Write` verb).** `hooks/scripts/lock_guard.sh` (PreToolUse(Write|Edit), Check 1) denies any `@discovery` write whose path does not match `{paths.reports}/<date>-discovery-<id>.md`. `Write` is retained only because this hook scopes it (GH #74 "Option B"); `bash_guard.sh` additionally blocks state-modifying Bash.
3. **Lint (regression guard).** `hooks/tests/lint_agent_capabilities.sh` (wired into `hooks/tests/run.sh`) fails if `discovery` — or `auditor`/`critic` — ever regains a mutating verb, or keeps `Write` without the path-scope hook registered.

## See also

- `agents/discovery.md` — the system prompt body
- `doctrines/intro-combo-wave.md` — discovery in the sprint-open parallel wave
- `references/agent-briefs.md` § @discovery — brief templates per pattern
- `doctrines/auditor-hypothesis-driven.md` — the parallel "neutral facts" → "graded findings" relationship
- `skills/context/SKILL.md` — `shctx discovery search` / `list` for cross-sprint reuse
