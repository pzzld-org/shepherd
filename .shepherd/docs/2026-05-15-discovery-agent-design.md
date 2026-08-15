---
title: Discovery agent + plugin hardening — v5.1.1 design
date: 2026-05-15
author: opus 4.7 [1m] (shepherd self-edit)
status: design — operator-approved 2026-05-15
target_version: v5.1.1
---

# Shepherd v5.1.1 — Discovery agent + plugin hardening

## 1. Why v5.1.1 (minor)

Additive changes only. `@discovery` is a new agent (new file at `agents/`),
the hook layer gains new scripts (new files under `hooks/scripts/`), the
Stage Graph gains new node types (additive defaults, opt-in via plan), and
shepherd.toml gains new keys (all with sane defaults). No existing
consumer-facing surface breaks. CLAUDE.md's MAJOR-on-closed-flock-change
clause is framework-internal discipline; the operator-perceived contract is
that v5.x minor bumps are safe to install.

The change set targets the recurring field-feedback errors enumerated in
v5.0.1 → v5.0.8 corpus:

Field-feedback corpus consulted:
- `/Users/jo3/src/fl03/axiom/.artifacts/docs/shepherd_feedback_v501.md`
- `/Users/jo3/src/fl03/axiom/.artifacts/docs/shepherd-v503.feedback.md`
- `/Users/jo3/src/fl03/axiom/.artifacts/docs/shepherd-v505.feedback.md`
- `/Users/jo3/src/fl03/axiom/.artifacts/docs/shepherd-v508.feedback.md`

Recurring theme: the conductor (and engineer's Phase 0 mesh) burns context
on read-only exploration — prior close audits, canonical-types reconciliation,
GH state inventory, error-cluster discovery. `@discovery` absorbs that load
into a sandboxed parallel agent. Net effect: conductor + engineer reason
deeper on less raw input.

## 2. `@discovery` — the sixth agent

### Identity
- **Model:** sonnet
- **Thinking:** high
- **Color:** blue
- **Dispatch mode:** single OR parallel (multiple discoveries fire in same
  Agent batch when scopes don't overlap)
- **System prompt:** `agents/discovery.md` (new file)
- **Distinct from `@worker`:** worker ACTS within a bounded budget (file ops,
  MCP writes, monitoring, branch cleanup). Discovery only READS, COMPREHENDS,
  and REPORTS. Discovery never produces a mutation.
- **Distinct from `@critic`:** critic reasons adversarially against a PLAN.
  Discovery answers QUESTIONS from sources. Critic produces a verdict;
  discovery produces a synthesis.
- **Distinct from `@auditor`:** auditor GRADES after the fact. Discovery
  ORIENTS before the fact. No grade, no severity.

### Tools (frontmatter `tools:` list)

Allowed:
- `Read`, `Grep`, `Glob`, `NotebookRead`, `LSP` — file/code reads
- `Bash` — by convention read-only (`git log`, `ls`, `rg`, `find`, `cat`,
  `gh issue list/view`, `gh pr view`, etc.) — agent system prompt enumerates
  the allowlist; auditor verifies post-hoc
- `Write` — restricted to `{paths.reports}/<date>-discovery-<id>.md` by
  hook (path-prefix check); any other Write target is denied
- `WebFetch`, `WebSearch`
- `Skill`, `ToolSearch`
- `TaskCreate`, `TaskGet`, `TaskList`, `TaskUpdate` — own subtask tracking
- `ListMcpResourcesTool`, `ReadMcpResourceTool`
- MCP read-only: github (`get_*`, `list_*`, `search_*`, `pull_request_read`,
  `issue_read`), supabase (`execute_sql` read-only, `list_*`, `get_*`),
  sentry (`search_*`, `find_*`, `get_*`)

Forbidden (never appears in frontmatter):
- `Edit`, `NotebookEdit` — no in-place mutation
- `Agent`, `Task` — discovery never dispatches
- MCP write tools (issue_write, apply_migration, create_*, update_*)

### Brief contract

```
[ROLE]               @discovery — read-only orientation

[QUESTION]
<one-sentence question to answer>

[SOURCES]
- <files, dirs, MCP queries, web URLs to consult>

[OUTPUT-PATH]        {paths.reports}/<date>-discovery-<id>.md

[BUDGET]
- Time: <max minutes>
- Max tool calls: <N>

[FORMAT]
- <Sectioned markdown — required headers: ## Findings, ## Open questions, ## Confidence>

[NON-GOALS]
- Do NOT propose code changes; surface facts, not recommendations.
- Do NOT dispatch other agents.
- Do NOT Write outside [OUTPUT-PATH].
- Do NOT run state-modifying Bash (rm, mv, >, >>, tee, gh issue create, ...).
```

### Report shape (Write to OUTPUT-PATH)

```markdown
---
title: Discovery — {question slug}
date: <YYYY-MM-DD>
discovery_id: <id>
sprint: {sprint_branch}
sources_consulted: <count>
---

# Discovery — {question}

## Sources
<bulleted list — paths, queries, URLs>

## Findings
<structured answer — tables, lists, citations>

## Open questions
<things sources didn't resolve>

## Confidence
HIGH | MED | LOW — <one-sentence justification>

## Suggested follow-ups (optional)
<questions for another discovery dispatch, or operator clarification>
```

### Return-to-conductor message

```
## DISCOVERY REPORT
- Question: <one line>
- Sources consulted: <count>
- Tool calls used: N / budget
- Time used: M / budget
- Report path: <abs path>
- Confidence: HIGH | MED | LOW
- Reporter: <agent-id> @ <ISO-8601>
```

The `discovery_capture.sh` hook parses this return and indexes it at
`<ns>/discoveries/<sprint>/<id>.json` for cross-sprint reuse.

### Use-case catalog (encoded in `references/agent-briefs.md`)

1. **`PRE-MESH-DISCOVERY`** — fires `parallel_with: [seed-verify]`; absorbs
   prior-close-audit ingestion, canonical-types refresh status, GH state
   inventory, sprint-pattern read. Engineer reads the report as
   `[DISCOVERY-CONTEXT]` instead of redoing the work.
2. **`PRE-HOTFIX-DISCOVERY`** — fires before `HOTFIX-DYNAMIC` to enumerate
   error clusters from `.shepherd/runs/wN-gate.json`. Replaces the
   conductor's inline `jq` pipeline with a delegated read-only dispatch.
3. **`ARCHITECTURE-DISCOVERY`** — operator-initiated when the conductor
   joins a session mid-sprint and needs to orient (read recent commits,
   open issues, current Stage Graph position, hot files).
4. **`DOCTRINE-RECONCILIATION-DISCOVERY`** — "does the codebase actually
   follow doctrine X?" Reads doctrine, greps codebase, reports adherence.
5. **`MCP-STATE-DISCOVERY`** — read-only MCP fan-out (GH + Sentry + Supabase
   advisors) consolidated into one report.

### Stage Graph integration

New node types added to `pipeline.md` §II:

| Type | Dispatch | Owner | Produces |
|---|---|---|---|
| `DISCOVERY` | Single or parallel `@discovery` | @discovery | Discovery report |
| `INTRO-COMBO-WAVE` | Parallel batch of `@discovery` + `@auditor` | both | Mesh inputs for engineer |

New edge labels:
- `on-research-complete` — fires from DISCOVERY when report written
- `on-intro-audit-complete` — fires from intro-audit auditor (regression-mode)
- `on-intro-wave-complete` — fan-in fires when ALL members of an INTRO-COMBO-WAVE
  have completed

#### The INTRO-COMBO-WAVE (sprint-start parallel orientation)

Inserted between `SEED-VERIFY` and `MESH`. Dispatches discoveries +
prior-sprint regression auditors in parallel.

```
SEED-VERIFY ──on-green──► INTRO-COMBO-WAVE ──on-intro-wave-complete──► MESH ──► PLAN-GATE ──► ...
                              │  (parallel batch)
                              ├─ discovery: prior-close-audit-summary
                              ├─ discovery: canonical-types-freshness
                              ├─ discovery: gh-state-inventory
                              ├─ auditor (intro mode): regression-check vs prior plan
                              └─ auditor (intro mode): carry-forward-disposition
```

Why combo: discoveries answer "what is the state right now"; intro-mode
auditors answer "did the prior sprint actually deliver what it promised
and is anything regressing". Both feed the MESH; engineer reads them
both as `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` in its brief.

Both lanes parallel-safe (read-only). The intro auditor uses a NEW concern:
`regression` (auditing what's at HEAD against the prior close report's
acceptance claims), distinct from the 5 close-time concerns.

YAML:

```yaml
- id: intro-combo-wave
  type: INTRO-COMBO-WAVE
  in_predicates: [{ predecessor: seed-verify, edge: on-green }]
  parallel_with: []
  agents:
    - { role: discovery, count: 3, briefs: [prior-close-audit-summary,
                                            canonical-types-freshness,
                                            gh-state-inventory] }
    - { role: auditor, count: 2, concerns: [regression,
                                            carry-forward-disposition] }
  out_edges:
    - { label: on-intro-wave-complete, target: mesh }
    - { label: on-hard-stop, target: hard-stop }

- id: mesh
  type: MESH
  in_predicates:
    - { predecessor: intro-combo-wave, edge: on-intro-wave-complete }
  ...
```

Default cardinality: 3 discoveries + 2 intro auditors = 5-agent parallel
batch. Configurable per-project via `shepherd.toml [stage_graph.intro_wave]`
(see §11 below). Operator may disable entirely (`intro_wave.enabled = false`).

When the engineer's plan includes the INTRO-COMBO-WAVE (default-on for L/XL
sprints, default-off for XS), the conductor auto-injects both
`[DISCOVERY-CONTEXT]` and `[INTRO-AUDIT-CONTEXT]` into the engineer's brief.
Engineer treats both as authoritative for its row of mesh — same model as
`[DB-CONTEXT]` for coders.

### Doctrine

New file: `doctrines/discovery-readonly.md`.

Rules:
1. Discovery is read-only. ANY mutation = process violation, grade-cap C+.
2. Discovery NEVER substitutes for `@worker` (which acts) or `@auditor`
   (which grades). If the dispatcher reaches for "worker but smaller", they
   want worker. If they reach for "auditor but earlier", they want auditor.
   Discovery is for "I need to understand X before deciding what to do".
3. Max 3 concurrent discoveries per wave. Beyond that, batch into one
   discovery with a broader question.
4. Discovery report at `{paths.reports}/<date>-discovery-<id>.md`. The
   `discovery_capture.sh` hook indexes the return for cross-sprint reuse;
   the conductor reads the file when consuming the result.
5. PRE-MESH-DISCOVERY result is REQUIRED reading for the engineer when
   present — auto-injected as `[DISCOVERY-CONTEXT]` in the engineer's brief.

## 3. Hook overhaul

### Shared library

New: `hooks/scripts/_lib.sh`.

Exports:
- `emit_context(msg)` — JSON `{"additionalContext": msg}` via jq or python
- `emit_deny(msg)` — JSON `{"permissionDecision":"deny","message":msg}`
- `log_event(hook_name, decision, fields_json)` — append to
  `<ns>/logs/hooks/YYYY-MM-DD.jsonl`
- `resolve_namespace()` — echoes `.shepherd` or `.artifacts` (legacy)
- `is_shepherd_project()` — returns 0 if `.claude/shepherd.toml` exists
- `extract_jq_or_py(input_var, path)` — JSON field extraction with fallback
- `current_role(tool_use_id)` — reads `<ns>/dispatch/<sprint>/<id>.json`
  (written by `agent_invocation_tagger.sh`) and echoes the agent role

Every existing hook is refactored to `source ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/_lib.sh`
at the top. Removes ~60 lines of duplicated jq-vs-python fallback per hook.

### Existing hooks — changes

| File | Changes |
|---|---|
| `session_open.sh` | + `is_shepherd_project` guard via lib; + plan-validity check (branch matches `branching.sprint_branch_pattern` → plan.md should exist; if plan.md exists → should contain `## Stage Graph` block); event log on every fire |
| `bash_guard.sh` | + Check 4: if agent role from `current_role` is `auditor`, and command invokes a gate tool from `shepherd.toml [gates]`, and `git rev-parse --abbrev-ref HEAD` doesn't match `[SPRINT-BRANCH]` recorded by the tagger → DENY with WORKTREE-DRIFT message; + Check 5: if role is `discovery`, deny state-modifying Bash patterns (`rm `, `mv `, `> `, `>> `, `tee `, `gh issue create`, `gh issue close`, `gh pr merge`, `gh pr close`, `git push`, `git commit`, `git checkout`, `git merge`, etc.) |
| `lock_guard.sh` | Refactored into existing lock-conflict logic AND a new write-path-guard mode: if role is `discovery`, deny Write unless path matches `{paths.reports}/*-discovery-*.md`; if role is `auditor`, deny Write unless path matches `{paths.reports}/*-audit-*.md`; if role is `coder`, deny Write outside the recorded `[WORKTREE].Path` |
| `bash_post.sh` | + log_event on every Bash post; existing cwd-drift logic preserved |
| `agent_pause_detector.sh` | Refactored to use lib only |
| `agent_insight_capture.sh` | Refactored to use lib only |

### New hooks

#### `hooks/scripts/agent_invocation_tagger.sh` (PreToolUse on Agent | Task)

Parses `tool_input.prompt` to identify the flock role being dispatched. The
agent system-prompt body starts with a canonical header (`# @auditor`,
`# @discovery`, etc.); the tagger reads the first 200 lines of the prompt,
greps for `^# @(engineer|critic|coder|auditor|worker|discovery)\b`, and
writes the result + the dispatch `tool_use_id` (from the hook input) to:

```
<ns>/dispatch/<sprint>/<tool_use_id>.json
```

Schema:
```json
{
  "tool_use_id": "<from hook input>",
  "agent_role": "discovery|worker|coder|auditor|critic|engineer",
  "sprint": "<current branch>",
  "dispatched_at": <unix-ts>,
  "model": "<from tool_input.model>",
  "sprint_branch_recorded": "<git rev-parse --abbrev-ref HEAD at dispatch>"
}
```

Downstream PreToolUse hooks (`bash_guard.sh`, `lock_guard.sh`) read this to
make role-conditional decisions.

#### `hooks/scripts/discovery_capture.sh` (PostToolUse on Agent | Task)

Mirror of `agent_insight_capture.sh` but for `## DISCOVERY REPORT` returns.
Indexes structured records to `<ns>/discoveries/<sprint>/<id>.json` so the
engineer's MESH (and the conductor's mid-walk decisions) can query without
re-parsing report text.

#### `agent_pause_detector.sh` — extension: auto-draft dispatch brief stub

> Origin: operator clarification 2026-05-15. "Whenever a subagent 'pauses'
> because of out-of-scope work, the hook should trigger the conductor to
> consider, then dispatch the appropriate agent" — agent role per the
> pause report's `satellite_role` field, not hard-coded to worker.

Current behavior (v5.1.1): captures the structured PAUSE record to
`<ns>/pauses/<id>.json` and surfaces an additionalContext alert citing the
record path.

v5.1.1 extension: ALSO writes a ready-to-dispatch brief stub to
`<ns>/pauses/<id>.brief.md`. The brief stub is a near-complete brief in
the bracketed-section format for the role the paused agent requested. The
conductor reads the stub, makes any final adjustments, and dispatches —
the "feel" is that the pause auto-summons the next agent.

Stub shape (varies by `satellite_role`):

**For `satellite_role: coder`** — full coder brief stub with `[FILE-SCOPE]`,
`[ACCEPTANCE]`, `[NON-GOALS]` pre-populated from the pause record; the
conductor adds `[SKILLS]`, `[CONTEXT-INVENTORY]`, `[DO-NOT-DUPLICATE]`,
`[WORKTREE]`, `[BASE-COMMIT-EXPECTED]` (mechanical from current state).

**For `satellite_role: discovery`** — full discovery brief stub with
`[QUESTION]`, `[SOURCES]`, `[OUTPUT-PATH]`, `[BUDGET]` pre-populated.

**For `satellite_role: worker`** — full worker brief stub with
`[DELIVERABLE]`, `[SOURCES]`, `[BUDGET]`, `[FORMAT]`, `[OUT-OF-SCOPE]`
pre-populated.

**For `satellite_role: auditor`** — full auditor brief stub with concern,
scope, and report path pre-populated (this is rare but supported — happens
when a coder asks for adversarial review of a partial implementation
before continuing).

The additionalContext surfaced to the conductor now includes:
- The pause record path
- The dispatch brief stub path
- A one-line dispatch suggestion
- The agent role the conductor should dispatch
- A pointer to `shctx pauses dispatch <pause_id>` which auto-prepares the
  Agent batch (v5.1.1 also adds this shctx subcommand)

Sample additionalContext:
```
[shepherd] PAUSE-FOR-DEPENDENCY captured (v5.1.1).
  Pause id:           20260515T141023-a3f9
  Paused agent role:  coder
  Paused agent:       agent-abc12345
  Lane:               L3-circuit-extension
  Satellite role:     discovery       ← what to dispatch next
  Satellite size:     S
  Records:
    Structured:       .shepherd/pauses/20260515T141023-a3f9.json
    Brief stub:       .shepherd/pauses/20260515T141023-a3f9.brief.md
  Next step:
    Read the brief stub, adjust if needed, then dispatch a @discovery
    using the stub. After the satellite completes:
      shctx pauses resolve 20260515T141023-a3f9 --satellite-sha=<sha>
      SendMessage to agent-abc12345 with the resume signal.
  Doctrine:           doctrines/pause-for-dependency.md §III–IV
```

This makes the nested-subagent feel concrete: the conductor doesn't compose
the satellite brief; the hook does. The conductor's residual judgment is
"is the stub correct?" (review + dispatch) rather than "what do I need to
write?".

New supporting subcommand: `shctx pauses dispatch <pause_id>` (in
`skills/context/scripts/cmd_pauses.sh`). It echoes the brief stub to
stdout (operator-pipeable into the Agent dispatch) and updates the pause
record's status to `dispatched`. Optional `--print-only` flag for inspection.

### Event log

Path: `<ns>/logs/hooks/YYYY-MM-DD.jsonl`. Gitignored.

Entry shape:
```json
{
  "ts": "2026-05-15T14:23:11Z",
  "hook": "bash_guard",
  "decision": "deny|warn|pass",
  "tool": "Bash|Write|Edit|Agent",
  "role": "coder|auditor|discovery|...",
  "fields": { "cmd": "...", "reason": "..." }
}
```

Rotation: nothing automated (operator decides); the file is per-day so
manual cleanup is `rm <ns>/logs/hooks/2026-04-*.jsonl`.

### `hooks.json` updates

Re-organized to match new lifecycle. PreToolUse(Agent | Task) gains the
`agent_invocation_tagger.sh` BEFORE existing pause/insight hooks (so the
role-tag is written before any role-conditional check fires). The new
`discovery_capture.sh` joins PostToolUse(Agent|Task) alongside pause/insight.

## 4. `shctx doctor` — preflight command

Implemented at `skills/context/scripts/cmd_doctor.sh`. Invoked via
`shctx doctor`.

Output sections:

| Section | Checks |
|---|---|
| [GIT] | HEAD on expected branch; cwd is sprint root; no sub-worktree drift; sub-worktree count (informational) |
| [PLAN] | plan.md presence for current sprint branch; Stage Graph block present in plan; canonical-types.md freshness (date stamp) |
| [CTX REGISTRY] | root.db presence + size; migration version vs schema/migrations latest; sprint-patterns.md presence + entry count |
| [HOOKS] | hooks.json validity (jq parse); each hook script present + executable; event log writable |
| [MCP] | each `[mcp].*=true` in shepherd.toml → check tool prefix callable (best-effort via ToolSearch) |
| [LOCK] | shepherd.lock presence + held-by-current-session check |

Exit codes:
- 0 — all green
- 1 — warnings only
- 2 — errors (operator action required)

Non-blocking — informational only. Designed for `/shepherd:start` SessionStart
hook to invoke automatically (output appended to additionalContext) and for
manual operator runs.

## 5. Auditor upgrade — systematic-debugging discipline

Auditor today: walks a concern checklist, files findings. Reactive.

Auditor v5.1.1: hypothesis-driven, falsify-don't-confirm, evidence-bound,
inspired by `superpowers:systematic-debugging`.

Changes to `agents/auditor.md`:

1. **System prompt opening** — load `superpowers:systematic-debugging` via
   the Skill tool as a mandatory first step. Apply its discipline (hypothesis
   formation, narrow the search, falsify before confirm) to every finding.

2. **Per-finding evidence contract.** Today findings cite location +
   pattern. Add MANDATORY:
   - **Hypothesis** — one-sentence prediction of the failure mode
   - **Falsification attempt** — the grep/test/query you ran that would
     have disproved the hypothesis (and didn't)
   - **Confidence** — HIGH / MEDIUM / LOW based on falsification depth
   
   No finding lands without these three. "I think this is bad" is replaced
   with "I predicted X; I ran Y to disprove; Y returned Z; the prediction
   stands."

3. **New concern: `regression` (intro-wave mode)** — auditor in intro mode
   does NOT grade the current sprint; it verifies the PRIOR sprint's
   acceptance claims still hold at HEAD. Reads prior close report's
   `[ACCEPTANCE]` blocks, re-runs each runnable grep, files findings on
   mismatches. No grade emitted in intro mode.

4. **New concern: `carry-forward-disposition` (intro-wave mode)** —
   auditor reads carry-forward ledger, verifies each entry's status (still
   open, silently closed, label drift, stale). Files findings on
   discrepancies. Surfaces drift the planter/engineer must address before
   MESH.

5. **Bayesian finding-class weighting.** Auditor reads
   `<ns>/sprint-patterns.md` for prior false-positive rates per finding
   class (e.g., `WORKTREE-DRIFT` historically real 90% of the time;
   `wrapper-must-earn` violations 60% real). Spend deeper falsification
   effort on high-real-rate classes. Surfaces `confidence` based on the
   weight.

6. **Output additions:** report frontmatter gains `mode: close | regression
   | carry-forward-disposition`; intro-mode reports written to
   `{paths.reports}/<date>-intro-audit-<concern>.md`.

## 6. Doctrine additions

| File | Owns |
|---|---|
| `doctrines/discovery-readonly.md` | NEW — `@discovery` contract, role boundaries, when to dispatch, max-concurrent rules, report shape |
| `doctrines/intro-combo-wave.md` | NEW — INTRO-COMBO-WAVE shape, intro-auditor regression mode, plan-gate interaction, opt-out via shepherd.toml |
| `doctrines/auditor-hypothesis-driven.md` | NEW — systematic-debugging discipline for auditors; falsify-don't-confirm; per-finding evidence contract |
| `doctrines/sprint-as-patch.md` | NEW — each `dev.N` sprint = patch-equivalent in scope and protocol impact; planter sizes seeds at patch-grade, engineer plans at patch-grade body depth |
| `doctrines/hook-event-log.md` | NEW — event log schema, retention guidance, operator query examples |
| `doctrines/preflight-doctor.md` | NEW — when to run `shctx doctor`, exit-code semantics, integration with `/shepherd:start` |

`doctrines/README.md` gets entries for the six new doctrines.

### Sprint-as-patch framing (key operator clarification 2026-05-15)

The user's binding clarification: **every `dev.N` sprint within shepherd is
operator-equivalent to a full patch.** Sprints are NOT incremental nano-steps
on a monolithic patch; each sprint IS a substantial protocol advance. Planter
seeds and engineer plans must be sized accordingly:
- Sprint scope ≅ what an operator would normally call a patch
- 4-8 coder lanes, multi-wave, real-work test always applies, deletion + new
  features per sprint, end-of-sprint release-notes-eligible
- Patch-arc seed (`{patch_branch}.seed.md`) becomes the version-arc bundling
  of N patch-grade sprints, not the master plan from which sprints are tiny shards

This re-frames §III sprint-impactfulness in SKILL.md and the seed-shaping
guidance in planter.md / references/seed-template.md.

## 7. Skill-file updates

- `skills/shepherd/SKILL.md`:
  - frontmatter `version: 5.1.1`
  - description updated: "Six-agent flock (engineer, critic, coder, auditor, worker, discovery)"
  - §I table: add `@discovery` row
  - §III INTRO checklist: PRE-MESH-DISCOVERY optional
  - §VII anti-patterns: new entries — discovery substituting for worker, discovery dispatched when conductor inline would do
  - §XI file map: new doctrine references

- `skills/shepherd/flock.md`:
  - §I dispatch table: add `@discovery`
  - §II per-agent reference: add `@discovery` section between `@coder` and `@critic`
  - §III dispatch discipline: discovery parallel-safety = same as worker

- `skills/shepherd/pipeline.md`:
  - §II stage taxonomy: add DISCOVERY node
  - §III edge predicates: add `on-research-complete`
  - §IV canonical graph: add PRE-MESH-DISCOVERY between SEED-VERIFY and MESH (optional, plan-gated)
  - §XIII anti-patterns: discovery without `on-research-complete` edge

- `skills/shepherd/references/agent-briefs.md`:
  - Add `## @discovery` section with brief template + 5 use-case examples

- `skills/context/SKILL.md`:
  - frontmatter `version: 5.1.1`
  - Add `shctx doctor` command reference

## 8. Plugin metadata

Files to bump in lockstep (per CLAUDE.md "version sources of truth"):

- `.claude-plugin/plugin.json` → 6.0.0
- `.claude-plugin/marketplace.json` → 6.0.0
- `skills/shepherd/SKILL.md` frontmatter → 6.0.0
- `skills/context/SKILL.md` frontmatter → 6.0.0
- `README.md` header → 6.0.0
- `CHANGELOG.md` → v5.1.1 entry with migration notes

`CLAUDE.md` (repo) updated: "flock remains closed at six (engineer, critic,
coder, auditor, worker, discovery). Non-code work without a research signal
goes to @worker; comprehension and orientation go to @discovery."

## 9. Migration notes (for CHANGELOG)

**Breaking:**
- The flock contract opens to six lanes. Consumer projects that mechanically
  enumerated "the five flock agents" need to update to six. Practically
  affects: project doctrines referencing flock-size, custom dispatch wrappers,
  audit-concern lists.

**Additive (no consumer change required):**
- New `@discovery` agent; existing dispatches unchanged.
- New `DISCOVERY` stage node; existing graphs continue to work without it.
- New hooks; existing hook behavior preserved.
- New `shctx doctor` command.

**Operator action required at upgrade:**
- None mandatory. `@discovery` is OPT-IN per sprint (engineer may or may not
  include PRE-MESH-DISCOVERY).
- Recommended: run `shctx doctor` once after install to verify hooks load.

## 10. Build sequence

Single working session — no multi-day fragmentation. Order matters because
later tranches depend on earlier:

1. **Agent + doctrines** — `agents/discovery.md`, `doctrines/discovery-readonly.md`,
   `doctrines/intro-combo-wave.md`, `doctrines/auditor-hypothesis-driven.md`,
   brief templates in `references/agent-briefs.md`, SKILL.md / flock.md /
   pipeline.md updates. Discovery + intro-wave callable.
2. **Auditor upgrade** — rewrite `agents/auditor.md` to hypothesis-driven mode
   + intro-wave regression/carry-forward concerns. Audit report shape extended.
3. **Hook lib + role tagger** — `_lib.sh`, `agent_invocation_tagger.sh`,
   `discovery_capture.sh`. Refactor existing hooks to use lib. Update
   `hooks.json` lifecycle ordering.
4. **Hook teeth** — `bash_guard.sh` checks 4+5 (auditor cwd, discovery
   state-mod block), `lock_guard.sh` write-path filter, `session_open.sh`
   plan-validity check.
5. **`shctx doctor`** — `cmd_doctor.sh` + dispatch registration in
   `shctx` main script. New doctrines: `hook-event-log.md`,
   `preflight-doctor.md`.
6. **Version bump + CHANGELOG** — lockstep update across the 6 manifests
   + README + CLAUDE.md.

## 11. shepherd.toml additions

```toml
[stage_graph]
# Existing keys preserved...

[stage_graph.intro_wave]
enabled                  = true   # default true for new projects
default_discoveries      = ["prior-close-audit-summary", "canonical-types-freshness", "gh-state-inventory"]
default_intro_auditors   = ["regression", "carry-forward-disposition"]
disable_for_tshirt       = ["XS"]   # skip intro wave for tiny sprints
parallel_max             = 5
```

## 12. Open questions

None blocking. The discovery agent's exact tool list may need a follow-up
patch after the first few use-case runs reveal which MCP read-tools matter
in practice; the v5.1.1 list is the conservative starting set.

---

End of design.
