# Specialist dispatch — when the conductor reaches outside the flock

> (v5.1.1: opened a narrow exception so specialized third-party agents could
> be used for self-contained tasks the flock doesn't serve. v5.1.5 hardening
> added the canonical DISPATCH DECISION TREE, SPECIALIST DISCOVERY procedure,
> and worked examples below. The conductor's checklist routes every
> non-flock dispatch through this file.)

Pre-v5.1.1 the flock was strictly closed at six: no `general-purpose`,
`Explore`, `Plan`, `feature-dev:*`, `pr-review-toolkit:*`, `superpowers:*`,
or other third-party agent — only engineer/critic/coder/auditor/worker/
discovery could fire.

v5.1.1 relaxes this for one narrow category: **specialist third-party
agents that fit a self-contained task better than the flock.** Specialists
are an exception lane, not a default — **flock-first is the doctrinal
default.**

The flock is doctrinal because shepherd's discipline (Phase 0 mesh,
DEDUP-GATE, [SIBLING-LANES], hypothesis-driven audit, brief-cache ordering,
worktree confinement) lives in the flock's briefs. A
`pr-review-toolkit:code-reviewer` doesn't honor
`doctrines/auditor-hypothesis-driven.md`; a `code-explorer` doesn't run the
canonical-types refresh `@discovery` runs. Specialists augment, they don't
replace.

---

## DISPATCH DECISION TREE

> **Every non-flock dispatch routes through this tree. No shortcuts.** The
> conductor's checklist (`agents/conductor.md` §Step 0 + §"Anti-patterns")
> requires consulting this tree before any `subagent_type` is set on an
> `Agent({...})` call.

```
DISPATCH DECISION TREE — flock-first; specialist as exception

┌────────────────────────────────────────────────────────────────────┐
│ Q1. Is the task: (a) plan authorship, (b) critic-gating a plan /    │
│     money-path / merge, (c) sprint-close audit grading, or          │
│     (d) in-sprint code implementation inside the Stage Graph?       │
│   → YES → FLOCK-ONLY, no substitute: (a) @engineer (b) @critic      │
│            (c) @auditor (d) @coder. STOP.                          │
│   → NO  → continue to Q2.                                          │
└────────────────────────────────────────────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Q2. Does a flock lane handle this well?                             │
│   • Bounded research/monitoring/triage/cleanup → @worker            │
│   • Read-only orientation/synthesis/state inventory → @discovery    │
│   • Anything inside an in-flight sprint plan node → flock           │
│   → YES → DEFAULT: dispatch the flock lane. Reach for a specialist  │
│            only when Q3 actually clears.                           │
│   → NO  → continue to Q3.                                          │
└────────────────────────────────────────────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Q3. Is the task purpose-built for an existing specialist? ALL true: │
│   • Specialist is in shepherd.toml [specialists].allowed (or the    │
│     framework's default catalog when [specialists] is absent).     │
│   • Conductor has READ the specialist's description block THIS     │
│     SESSION — skim-and-fire is forbidden.                          │
│   • Specialist is read-only OR has clearly-bounded write surface.  │
│   • A flock-only dispatch would be strictly worse, measurably —    │
│     not vibes.                                                     │
│   → YES → DISPATCH SPECIALIST. Surface in operator log; tag audit. │
│   → NO  → continue to Q4.                                          │
└────────────────────────────────────────────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Q4. None of the above clear.                                        │
│   → HALT. Surface halt_code: SPECIALIST-UNCLEAR. Do NOT improvise,  │
│     do NOT dispatch general-purpose, do NOT stretch a flock lane    │
│     outside its contract. Wait for operator direction.              │
└────────────────────────────────────────────────────────────────────┘
```

**Mnemonic:** *flock unless proven otherwise.* Every branch is biased
toward the flock. Specialists win only when Q3 clears in full — three
"yes" answers, not two.

---

## When to dispatch a specialist

All must hold (the long-form Q3 conditions):

1. **Purpose-built fit** — e.g. `pr-review-toolkit:code-reviewer` for PR
   review, `sentry:seer` for Sentry triage, `claude-md-management:claude-md-improver`
   for CLAUDE.md maintenance, `claude-code-guide` for Claude Code questions.
2. **Read-only OR clearly-bounded effect** — no broad-write "general-purpose"
   specialists.
3. **Description read THIS session, fit verified.** Discovered from the
   **visible available-agents list only** — NEVER `ToolSearch` (an agent
   type is not a deferred tool; see SPECIALIST DISCOVERY §Step 2). Never
   dispatch off a prior session's skim.
4. **Equivalent flock dispatch would be strictly worse** — `@worker`
   handles most things; specialists win only when purpose-built prompts
   measurably beat it.

## When NOT to dispatch a specialist

Hard NEVER (Q1 blocks these doctrinally):

- **Plan authorship** — `@engineer`'s lane, no substitute.
- **Critic gating** of plans/money-paths/merges — `@critic` only.
- **Sprint-close audit grading** — `@auditor` in close mode; specialists may
  augment, never replace the grade.
- **Code implementation** in the sprint plan — `@coder` only; no
  code-write specialists for graph-encoded lanes.
- **Any task needing shepherd's own discipline** (Phase 0 mesh, DEDUP-GATE,
  [SIBLING-LANES]) — specialists don't honor these contracts by default.

Also forbidden as substitutes: **`general-purpose`** (an unconstrained
generic agent, not a specialist — tighten the `@worker` brief instead) and
**`Explore`** (same prohibition; `@discovery` carries the
`[QUESTION]/[SOURCES]/[BUDGET]/[FORMAT]` contract `Explore` doesn't).

---

## SPECIALIST DISCOVERY

Once the tree clears Q3, finding the right specialist is mechanical:

### Step 1 — Check the available-agents list (the ONE authority)

Every session prompt enumerates available agents in a system-reminder
block. Scan it first — **this list is the only authority for whether a
specialist is callable.** In it → dispatch it. Not in it → not currently
registered, skip to Step 4 (plugin reload).

### Step 2 — Dispatch via `Agent({subagent_type})` — NEVER `ToolSearch` for the agent

A specialist is a **subagent**, dispatched via `Agent({subagent_type:
"<plugin>:<agent-slug>"})`. **Subagent types are NOT tools — never
`ToolSearch` targets.** If the name is in the Step-1 list, just dispatch
it; there's no schema to "load" first.

> **`ToolSearch select:pr-review-toolkit:code-reviewer` is the
> `SUBAGENT-DISCOVERY-TOOLSEARCH` anti-pattern** — it returns nothing *by
> design* (an agent type isn't a deferred tool), the same class of mistake
> as `ToolSearch`-ing for `Workflow`/`TaskCreate`/`SendMessage`
> (`references/glossary.md`, `doctrines/workflow-tool-self-check.md §II`).
> A nothing-result is **NEVER** evidence the specialist is absent — read
> the available-agents list instead.

`ToolSearch` IS correct for a **deferred TOOL CALL** a lane needs — an MCP
tool (`mcp__github__*`, `mcp__sentry__*`, `mcp__supabase__*`) or on-demand
utility:

```
ToolSearch(query="github issues", max_results=5)   # finds mcp__github__list_issues, …
ToolSearch(query="sentry", max_results=5)          # finds mcp__sentry__search_events, …
```

Split is mechanical: `ToolSearch` discovers **tools**; the visible
available-agents list discovers the **agent** you dispatch.

### Step 3 — Read the description block and cross-check authorization

For every candidate: (1) read the description block, confirm the surface
matches the task (a `silent-failure-hunter` is for silent failures, not
general code review); (2) cross-check `shepherd.toml [specialists].allowed`
— if present, the candidate MUST appear there, else the framework's
default catalog applies (§Specialist catalog); (3) confirm read-only or
bounded write surface — unbounded write/Edit/Bash is unsuitable, prefer
read-only.

Any check fails → do NOT dispatch. Fall back to `@worker` with a tighter
brief, or HALT for operator direction.

### Step 4 — Plugin reload + discovery escape hatch

When a specialist *should* be available but isn't registered (stale
catalog after install):

1. Surface unavailability explicitly (same shape as
   `doctrines/plugin-reload-escape.md`):
   ```
   [SHEPHERD] Specialist unavailability detected:
     • <plugin>:<agent> referenced in shepherd.toml [specialists].allowed
       but not visible in the available-agents list.
   Run /reload-plugins to refresh the agent catalog. If still unavailable
   after reload, shepherd degrades to @worker (lower fidelity).
   ```
2. Wait for operator reload (`/reload-plugins` is operator-only).
3. Re-check: visible now → proceed with Step 3. Still unavailable → degrade
   to `@worker` with a tighter brief AND annotate the operator surface
   ("specialist degraded — @worker fallback"). If the task strictly
   requires the specialist → HALT with `halt_code: SPECIALIST-UNAVAILABLE`.

**Do NOT silently degrade** — same principle as MCP-tool unavailability
(`doctrines/plugin-reload-escape.md`).

---

## Specialist catalog (project-specific)

Each project's `shepherd.toml` MAY enumerate allowed specialists with
dispatch conditions:

```toml
[specialists]
allowed = [
  "pr-review-toolkit:code-reviewer",
  "pr-review-toolkit:silent-failure-hunter",
  "pr-review-toolkit:type-design-analyzer",
  "feature-dev:code-explorer",
  "feature-dev:code-architect",
  "code-simplifier:code-simplifier",
  "sentry:seer",
  "claude-md-management:claude-md-improver",
  "claude-code-guide",
  "plugin-dev:plugin-validator",
  "plugin-dev:skill-reviewer",
  "supabase:supabase",      # skill, not agent — distinct (see §Skills below)
]

[specialists.dispatch_rules]
"pr-review-toolkit:code-reviewer"        = "augment @auditor close-mode on PRs that already have a grade"
"pr-review-toolkit:silent-failure-hunter" = "use on WAVE-IMPL error-handling output — augmentation, NOT replacement of @auditor"
"sentry:seer"                            = "Sentry triage when @worker would need > 10 sequential MCP calls"
"claude-md-management:claude-md-improver" = "CLAUDE.md audits before sprint open"
"claude-code-guide"                      = "mid-sprint Claude Code feature questions (hooks, SDK, slash commands)"
```

When `[specialists]` is absent, the framework allows the canonical
specialists above with their default dispatch conditions, subject to the
decision tree's Q3 gating.

---

## Dispatch model

```
Agent({
  description: "specialist:<slug>: <one-line task>",
  subagent_type: "<plugin>:<agent-slug>",   # e.g., "pr-review-toolkit:code-reviewer"
  model: "sonnet",                           # always sonnet; matches flock defaults
  prompt: "<the brief — specialists have their own brief contracts>"
})
```

Differences from a flock dispatch: `subagent_type` IS set (mandatory since
v6.0.0, GH #20) but the identity source is the specialist's own plugin, not
a shepherd `agents/*.md` body; `prompt` follows the specialist's own brief
contract, not shepherd's flock-brief shape (read its docs first);
`model: sonnet` + high effort is the default, matching the flock's
cost/quality target for everything but `@engineer`.

---

## Worked examples — flock-first; specialist as augmentation

> Realistic scenarios where Q3 clears. Each names the trigger, the dispatch
> shape, and the operator-surface line. None replace a flock lane — each
> augments one.

**A — PR-shape review augmenting a completed close-audit.** Trigger: dev.3
closed with `@auditor` grading B+; operator wants a second pass on PR-shape
(commit hygiene, review-thread coverage) before merge — a surface
`@auditor` doesn't optimize for. Q3 clears: no duplicated work, purpose-built
fit, read-only/bounded by PR number.
```json
Agent({
  "description": "specialist:pr-review-toolkit:code-reviewer: augment close-audit on PR #142",
  "subagent_type": "pr-review-toolkit:code-reviewer",
  "model": "sonnet",
  "prompt": "PR #142. Close-audit grade B+ already filed at .artifacts/reports/2026-05-19-v515-close.md. Review PR-shape ONLY: commit hygiene, scope creep, review-thread coverage. Do NOT re-grade code quality. Output: comment-ready summary."
})
```
`[NODE] specialist:pr-review-toolkit:code-reviewer → on-no-finding | PR #142 PR-shape clean`

**B — Unfamiliar Claude Code feature mid-sprint.** Trigger: `@coder` files a
`BRIEF-AMENDMENT REQUEST` asking how `SubagentStop` fires on abnormal
teammate exit; neither the conductor nor shepherd's doctrines have this
fact. Q3 clears: `claude-code-guide` is purpose-built for platform
mechanics; read-only, 2-paragraph deliverable. *(Cross-lane dependencies:
express as graph-edge await ordering, or `SendMessage` for genuine
hand-off; out-of-sprint work files a finding at close —
`doctrines/native-coordination.md`.)*
```json
Agent({
  "description": "specialist:claude-code-guide: SubagentStop semantics on abnormal exit",
  "subagent_type": "claude-code-guide",
  "model": "sonnet",
  "prompt": "When a Claude Code teammate (Agent Teams) exits abnormally, does the parent's SubagentStop hook fire? What payload / what's the detection pattern? 2 short paragraphs + code snippet if applicable."
})
```
`[NODE] specialist:claude-code-guide → on-finding | SubagentStop fires with exit_code only; abnormal-exit detection requires heartbeat timeout`

**C — Silent-failure augmentation on error-handling lanes.** Trigger: Wave
2 landed three coder lanes touching error-handling (retry, MCP fallback,
gate-failure recovery); `@auditor` already runs standard concerns, operator
wants tuned scrutiny for swallowed failures. Q3 clears: this is
augmentation not replacement — `@auditor` still ships the grade; read-only,
scoped to the wave's `[FILE-SCOPE]`.
```json
Agent({
  "description": "specialist:pr-review-toolkit:silent-failure-hunter: augment wave-2 audit on error-handling lanes",
  "subagent_type": "pr-review-toolkit:silent-failure-hunter",
  "model": "sonnet",
  "prompt": "File scope: src/retry.rs, src/mcp_fallback.rs, src/gate.rs. @auditor concurrently grades via standard concerns; you focus narrowly on swallowed errors/unwrap-without-context/log-and-continue. Append findings to .artifacts/reports/2026-05-19-w2-silent-failures.md. Do NOT grade or file primary findings — that's @auditor."
})
```
`[NODE] specialist:pr-review-toolkit:silent-failure-hunter → on-finding | 2 swallowed errors in src/mcp_fallback.rs; auditor folding into close-report`

**D — CLAUDE.md health check before opening a sprint.** Trigger: planter is
about to author dev.0 and CLAUDE.md hasn't been audited in 3 patches;
`claude-md-management:claude-md-improver` applies a templated rubric
`@worker` would have to re-derive. Read-then-recommend only.
```json
Agent({
  "description": "specialist:claude-md-management:claude-md-improver: audit CLAUDE.md before dev.0",
  "subagent_type": "claude-md-management:claude-md-improver",
  "model": "sonnet",
  "prompt": "Audit CLAUDE.md at repo root (and any nested). Output the quality report ONLY — do NOT apply patches; those land via @coder in dev.0 if the operator signs off."
})
```
`[NODE] specialist:claude-md-management:claude-md-improver → on-finding | 3 gaps: missing version-source table, stale layout section, missing meta-tier note`

---

## Plugin reload + discovery

> Companion to SPECIALIST DISCOVERY §Step 4 — kept distinct so the
> conductor's checklist can cite either by anchor.

When a referenced specialist isn't registered: **detect** via Step 1 (name
absent from the available-agents list — never via `ToolSearch`, a miss
proves nothing); **decide** the response:

| Situation | Response |
|---|---|
| Listed in `shepherd.toml [specialists].allowed`, should be installed | Surface `/reload-plugins` request; wait for reload. |
| NOT in `allowed`, conductor is improvising | STOP — the "general-purpose because @worker felt heavy" anti-pattern. Fall back to flock. |
| Reload requested, still unavailable, flock-acceptable substitute exists | Degrade to flock (`@worker`/`@discovery`) with explicit operator-log annotation. |
| Reload requested, still unavailable, task strictly requires the specialist | HALT with `halt_code: SPECIALIST-UNAVAILABLE`. Operator decides. |

**Surface** the path taken on the operator log — never hide the
substitution. See also `doctrines/plugin-reload-escape.md` (the MCP-tool
analogue — same philosophy: flag, don't silently degrade).

---

## Skills vs agents — important distinction

Many "third-party tools" an operator might mention (`supabase:supabase`,
`finance`, `rust`) are SKILLS loaded into a session via
`Skill(skill="<slug>")` inside any agent's dispatch — not separate
dispatches. This doctrine governs AGENTS (things you `Agent(...)` into
existence); skills load via whichever lane needs them (the `[SKILLS]`
block in coder/engineer briefs).

## Operator communication

Every specialist dispatch surfaces its origin on the operator line:

```
[NODE] specialist:pr-review-toolkit:code-reviewer → on-no-finding | PR #34 clean
[NODE] specialist:sentry:seer → on-finding | 3 active issues, 2 above thresholds
[NODE] specialist:claude-code-guide → on-finding | SubagentStop fires with exit_code only
```

This keeps specialist dispatches visible in the audit trail, never hidden
inside the flock-dispatch log.

## Audit trail

`agent_invocation_tagger.sh` (v5.1.2) records every dispatched agent's
role; for specialists `agent_role` becomes `specialist:<plugin>:<slug>`.
The close-time completeness auditor verifies specialist dispatches were
pre-authorized in `[specialists].allowed`, used for a task Q3 permits, and
logged/surfaced. Specialist dispatch outside the allowed list → process
violation, grade-cap C+.

## Anti-patterns this doctrine catches

1. **Dispatching `general-purpose`** because "`@worker` felt heavy" — forbidden;
   it's an unconstrained generic agent that discards shepherd's discipline.
   Tighten the `@worker` brief instead.
2. **Dispatching `Explore`** — same prohibition; `@discovery` is the
   read-only synthesis lane with the framework's contract.
3. **Specialist in place of `@critic`/`@engineer`/`@auditor`/`@coder`** —
   hard never, Q1 blocks it.
4. **Dispatching a specialist without reading its contract THIS session** —
   a prior session's skim isn't authoritative; mis-briefed specialists
   produce garbage.
5. **Specialist dispatch hidden from operator surface** — every dispatch
   surfaces plugin + slug in the audit trail.
6. **Skipping the decision tree** — any non-flock dispatch landing without
   Q1→Q4 evaluation is a process violation.
7. **Silent specialist degradation** — falling back to `@worker` without an
   operator-surface annotation. Always annotate (§Plugin reload + discovery).
8. **`ToolSearch`ing to "discover"/"confirm" a specialist/subagent/teammate
   type** — `SUBAGENT-DISCOVERY-TOOLSEARCH` (§Step 2). Agent types are NOT
   deferred tools; they live in the available-agents list and dispatch via
   `Agent({subagent_type})` (teammates via native teammate-spawn). Same
   class as `WORKFLOW-SELFCHECK-TOOLSEARCH`
   (`doctrines/workflow-tool-self-check.md §II`).

## See also

- `flock.md` §I — the canonical six-lane flock and dispatch procedure
- `doctrines/agent-excellence.md` — when in doubt, the flock is the default; strive-higher framing
- `doctrines/plugin-reload-escape.md` — MCP-tool unavailability analogue
- `doctrines/worker-patterns.md` — when @worker is the right answer (most of the time)
- `hooks/scripts/agent_invocation_tagger.sh` — records specialist origin
- `agents/conductor.md` §Hard prohibitions + §Anti-patterns — flock-first reinforcement
- `SKILL.md` §I (v5.1.1+) — "closed at six + specialist exceptions per doctrine"
