# Specialist dispatch — when the conductor reaches outside the flock

> Origin: v5.1.1 (2026-05-16). Operator: "we still want to be open and flexible
> to allowing other agents to be used if better suited for a particular effort
> ... instead of dispatching a worker to do this thing use some specialized
> third party agent instead."
>
> v5.1.5 hardening: this doctrine now carries the canonical DISPATCH DECISION
> TREE, a SPECIALIST DISCOVERY procedure, and worked dispatch examples. The
> conductor's checklist routes every non-flock dispatch through this file.

Pre-v5.1.1, the flock was strictly closed at six. The conductor was forbidden
from dispatching `general-purpose`, `Explore`, `Plan`, `feature-dev:*`,
`pr-review-toolkit:*`, `superpowers:*`, or any other third-party agent — only
the six flock lanes (engineer, critic, coder, auditor, worker, discovery)
could fire.

v5.1.1 relaxes this for a narrow category: **specialist third-party agents
that fit a self-contained task better than the flock**. Specialists are an
exception lane, not a default. **The flock remains the primary dispatch
surface — flock-first is the doctrinal default.**

The flock is doctrinal because shepherd's discipline (Phase 0 mesh,
DEDUP-GATE, [SIBLING-LANES], hypothesis-driven audit, brief-cache ordering,
worktree confinement) lives in the flock's briefs. A `pr-review-toolkit:code-reviewer`
does not honor `doctrines/auditor-hypothesis-driven.md`. A `code-explorer`
does not run the canonical-types refresh that `@discovery` runs. Specialists
are augmentation, not replacement.

---

## DISPATCH DECISION TREE

> **Every non-flock dispatch routes through this tree. No shortcuts.**
> The conductor's checklist (`agents/conductor.md` §Step 0 + §"Anti-patterns")
> requires consulting this tree before any `subagent_type` is set on an
> `Agent({...})` call.

```
DISPATCH DECISION TREE — flock-first; specialist as exception

┌────────────────────────────────────────────────────────────────────┐
│ Q1. Is the task one of:                                            │
│   (a) plan authorship                                              │
│   (b) critic gating of a plan / money-path / merge                 │
│   (c) sprint-close audit grading                                   │
│   (d) in-sprint code implementation inside the Stage Graph         │
│                                                                    │
│   → YES → FLOCK-ONLY. No substitute exists.                        │
│            (a) → @engineer  (b) → @critic                          │
│            (c) → @auditor   (d) → @coder                           │
│            STOP. Dispatch the flock lane.                          │
│   → NO  → continue to Q2.                                          │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Q2. Does a flock lane handle this well?                            │
│   • Bounded research / monitoring / triage / cleanup → @worker     │
│   • Read-only orientation / synthesis / state inventory →          │
│     @discovery                                                     │
│   • Anything inside an in-flight sprint plan node → flock          │
│                                                                    │
│   → YES → DEFAULT: dispatch the flock lane.                        │
│            Flock-first is the doctrinal default. Reach for a       │
│            specialist only when Q3 actually clears.                │
│   → NO  → continue to Q3.                                          │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Q3. Is the task purpose-built for an existing specialist?          │
│   ALL of these MUST be true:                                       │
│   • Specialist appears in shepherd.toml [specialists].allowed      │
│     (or in the framework's default catalog when [specialists]      │
│     is absent).                                                    │
│   • Conductor has READ the specialist's description block in       │
│     THIS SESSION. Skim-and-fire is forbidden (see anti-pattern     │
│     "specialist dispatched without contract read").                │
│   • Specialist is read-only OR has clearly-bounded write surface.  │
│   • A flock-only dispatch would be strictly worse — measurably,    │
│     not vibes (e.g., specialist understands a tool-call pattern    │
│     @worker would burn 10+ MCP calls re-deriving).                 │
│                                                                    │
│   → YES → DISPATCH SPECIALIST. Surface in operator log per         │
│            §Operator communication. Tag the audit trail.           │
│   → NO  → continue to Q4.                                          │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Q4. None of the above clear.                                       │
│                                                                    │
│   → HALT. Surface to operator with halt_code: SPECIALIST-UNCLEAR.  │
│     Do NOT improvise. Do NOT dispatch general-purpose. Do NOT      │
│     stretch a flock lane outside its contract. Wait for operator   │
│     direction.                                                     │
└────────────────────────────────────────────────────────────────────┘
```

**Mnemonic:** *flock unless proven otherwise.* The decision tree is biased
toward the flock at every branch. Specialists win only when they clear Q3
in full — three "yes" answers, not two.

---

## When to dispatch a specialist

A specialist dispatch is appropriate when ALL of the following hold (these
are the long-form Q3 conditions):

1. **Task is well-handled by an existing specialized agent.** The
   specialist is purpose-built for the surface — e.g., `pr-review-toolkit:code-reviewer`
   for PR review augmentation, `sentry:seer` for Sentry investigation,
   `claude-md-management:claude-md-improver` for CLAUDE.md maintenance,
   `claude-code-guide` for Claude Code feature questions.
2. **Specialist is read-only OR has clearly-bounded effect.** The
   conductor knows what state the specialist can mutate. No
   "general-purpose" specialists with broad write surface.
3. **Conductor has seen the specialist's description in this session
   and verified the fit.** Specialists discovered via the available-agents
   list, `ToolSearch`, or the operator-installed catalog. Never dispatch
   a specialist whose contract you haven't read THIS SESSION (people
   skim across sessions; mis-briefed specialists produce garbage).
4. **Equivalent flock dispatch would be strictly worse.** The flock's
   `@worker` can do most things — specialists only win when their
   purpose-built prompts produce measurably better output.

## When NOT to dispatch a specialist

Hard NEVER cases (these are doctrinal — Q1 of the decision tree blocks them):

- **Plan authorship.** That's `@engineer`'s lane. No specialist substitutes.
- **Critic gating** of plans / money-paths / merges. That's `@critic`. No substitutes.
- **Sprint-close audit grading.** That's `@auditor` in close mode. Specialists
  may augment but never replace the close-time grade.
- **Code implementation in the sprint plan.** That's `@coder`. Specialists
  with code-write capability are off-limits for graph-encoded code lanes.
- **Any task where the framework's discipline (Phase 0 mesh, DEDUP-GATE,
  [SIBLING-LANES], etc.) needs to apply.** Specialists don't honor
  shepherd's contracts by default.

Additionally forbidden as substitutes:

- **`general-purpose`** — explicitly forbidden by the framework. It is NOT
  a specialist; it is an unconstrained generic agent. If `@worker` feels
  heavy, the answer is a tighter `@worker` brief, not `general-purpose`.
- **`Explore`** — same prohibition. `@discovery` is the read-only synthesis
  lane; it carries the framework's `[QUESTION]/[SOURCES]/[BUDGET]/[FORMAT]`
  contract that `Explore` does not.

---

## SPECIALIST DISCOVERY

When the decision tree clears Q3, the conductor still has to *find* the
right specialist. The discovery procedure is mechanical, not improvisational:

### Step 1 — Check the available-agents list

Every session prompt enumerates available agents under a system-reminder
block (e.g., `pr-review-toolkit:code-reviewer`, `feature-dev:code-architect`,
`code-simplifier:code-simplifier`, `plugin-dev:plugin-validator`, …). The
conductor scans this list first. If the candidate specialist is not in the
list, it is NOT currently registered — skip to Step 4 (Plugin reload).

### Step 2 — Load the specialist's tool schema via ToolSearch

Specialists registered as Agent subagent types are dispatched through the
generic `Agent({...})` shape. If a related tool (e.g., the plugin's own
slash-command tool) is deferred, load its schema before fire:

```
ToolSearch(query="select:<plugin>:<agent>", max_results=1)
ToolSearch(query="select:pr-review-toolkit:code-reviewer", max_results=1)
ToolSearch(query="select:sentry:seer", max_results=1)
```

For keyword discovery when the exact name is unknown:

```
ToolSearch(query="pr review augmentation", max_results=5)
ToolSearch(query="silent failure detection", max_results=5)
```

A schema return confirms the tool/agent is callable in this session. A
"no match" return means it is NOT available — skip to Step 4.

### Step 3 — Read the description block and cross-check authorization

For every candidate specialist:

1. **Read the description block** — usually in the available-agents list
   under the specialist's name. Confirm the surface matches the task. A
   `pr-review-toolkit:silent-failure-hunter` is for finding silent failures,
   not for general code review.
2. **Cross-check against `shepherd.toml [specialists].allowed`** — if the
   project has a list, the candidate MUST appear there. If the project
   omits `[specialists]`, the framework's default catalog applies (see
   §Specialist catalog below).
3. **Confirm read-only or bounded write surface** — agents whose
   description includes write/Edit/Bash without bounds are unsuitable
   for specialist dispatch. Prefer read-only specialists; reach for
   bounded-write only when the task explicitly requires it.

If any check fails: do NOT dispatch. Fall back to `@worker` with a tighter
brief, or HALT for operator direction.

### Step 4 — Plugin reload + discovery escape hatch

When the specialist *should* be available but isn't currently registered
(e.g., the operator installed the plugin but the catalog is stale):

1. **Surface the unavailability explicitly** — same shape as
   `doctrines/plugin-reload-escape.md` (the MCP-tool reload pattern):
   ```
   [SHEPHERD] Specialist unavailability detected:
     • <plugin>:<agent> referenced in shepherd.toml [specialists].allowed
       but not visible in the available-agents list and ToolSearch returns
       no match.
   Run /reload-plugins to refresh the agent catalog. If still unavailable
   after reload, shepherd degrades to @worker (lower fidelity).
   ```
2. **Wait for operator reload** — `/reload-plugins` is operator-only; the
   conductor cannot call it.
3. **Re-check after reload:**
   - If now visible → proceed with Step 3.
   - If still unavailable → degrade to `@worker` with a tighter brief AND
     annotate the operator surface line: "specialist degraded — @worker
     fallback; specialist unavailable post-reload". Log to mesh report.
   - If the task strictly requires the specialist (e.g., a tool only the
     specialist can call) → HALT with `halt_code: SPECIALIST-UNAVAILABLE`
     and surface to operator.

**Do NOT silently degrade.** Same principle as MCP-tool unavailability —
hidden fallback hides misconfiguration. Per
`doctrines/plugin-reload-escape.md`.

---

## Specialist catalog (project-specific)

Specialists are project-specific. Each project's `shepherd.toml` MAY enumerate
allowed specialists with their dispatch conditions:

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
"pr-review-toolkit:code-reviewer"        = "use to augment @auditor close-mode on PRs that already have a grade"
"pr-review-toolkit:silent-failure-hunter" = "use on WAVE-IMPL output when error-handling lanes shipped — augmentation, NOT replacement of @auditor"
"sentry:seer"                            = "use for Sentry triage when @worker would do > 10 sequential MCP calls"
"claude-md-management:claude-md-improver" = "use for CLAUDE.md audits before sprint open"
"claude-code-guide"                      = "use mid-sprint to investigate unfamiliar Claude Code features (hooks, SDK, slash commands)"
```

When `[specialists]` is absent, the framework allows the canonical specialists
listed above with their default dispatch conditions, subject to the decision
tree's Q3 gating.

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

Note the key differences from a flock dispatch:

- **`subagent_type` IS set** to the specialist's registered type — just as a
  flock dispatch sets `shepherd:<role>` (MANDATORY since v6.0.0, GH #20). The
  difference is the *identity source*: a specialist's behavior comes from its
  own plugin's registered subagent, not from a shepherd `agents/*.md` body.
- **`prompt` follows the specialist's own brief contract**, not the
  shepherd flock-brief shape. Read the specialist's docs/help first.
- **`model: sonnet` + high effort** is the default (matches the flock's
  cost/quality target for everything but `@engineer`).

---

## Worked examples — flock-first; specialist as augmentation

> These examples show realistic shepherd sprint scenarios where Q3 clears.
> Each one names the trigger, the dispatch shape, and the operator-surface
> line. None replace a flock lane; each augments one.

### Example A — PR review augmentation on a feature branch that already has a close-audit grade

**Trigger:** dev.3 closes with `@auditor` grading B+. The patch is about
to merge to `main`; the operator wants a second pair of eyes specifically
on the PR diff shape (commit hygiene, review-thread coverage) before
merging — a surface `@auditor` does NOT optimize for.

**Why specialist (Q3 clears):**
- `@auditor` already shipped the close-mode grade — duplicating that work
  is waste.
- `pr-review-toolkit:code-reviewer` is purpose-built for PR-shape review
  (commits, review threads, gh diff formatting).
- Read-only; bounded by PR number.

**Dispatch:**

```json
Agent({
  "description": "specialist:pr-review-toolkit:code-reviewer: augment close-audit on PR #142",
  "subagent_type": "pr-review-toolkit:code-reviewer",
  "model": "sonnet",
  "prompt": "PR #142 (v5.1.5 patch merge). Close-audit grade B+ already filed at .artifacts/reports/2026-05-19-v515-close.md. Review PR-shape concerns ONLY: commit hygiene, scope creep across the diff, review-thread coverage. Do NOT re-grade code quality — that's the auditor's lane. Output: a comment-ready summary to paste into the PR thread."
})
```

**Operator surface line:**

```
[NODE] specialist:pr-review-toolkit:code-reviewer → on-no-finding | PR #142 PR-shape clean
```

### Example B — Investigating an unfamiliar Claude Code feature mid-sprint

**Trigger:** mid-sprint, `@coder` returns `PAUSE-FOR-DEPENDENCY` asking
how Claude Code's `SubagentStop` hook event fires when a teammate session
exits abnormally. The conductor does not have this fact at hand; neither
do shepherd's doctrines. `@discovery` could synthesize from public docs,
but `claude-code-guide` is purpose-built for exactly this question class.

**Why specialist (Q3 clears):**
- `@discovery` would burn time re-deriving Claude Code platform mechanics.
- `claude-code-guide` knows hooks/SDK/slash-command semantics natively.
- Read-only; deliverable is a 2-paragraph answer.

**Dispatch:**

```json
Agent({
  "description": "specialist:claude-code-guide: SubagentStop semantics on abnormal exit",
  "subagent_type": "claude-code-guide",
  "model": "sonnet",
  "prompt": "Question: When a Claude Code teammate session (spawned via Agent Teams) exits abnormally (operator kill, timeout, network drop), does the parent's SubagentStop hook fire? If yes, what payload does it carry? If no, what's the canonical detection pattern? Output: 2 short paragraphs + a code snippet if applicable. This is for shepherd plugin v5.1.5 — escalation channel hardening."
})
```

**Operator surface line:**

```
[NODE] specialist:claude-code-guide → on-finding | SubagentStop fires with exit_code only; abnormal-exit detection requires heartbeat timeout
```

### Example C — Running `silent-failure-hunter` on WAVE-IMPL output as augmentation, not replacement

**Trigger:** Wave 2 IMPL just landed three coder lanes that all touched
error-handling paths (retry logic, MCP fallback, gate-failure recovery).
`@auditor` is already dispatched in Pattern-B overlap for the standard
five concerns. The operator wants additional specifically-tuned scrutiny
for silently-swallowed failures — a class `pr-review-toolkit:silent-failure-hunter`
is purpose-built to find.

**Why specialist (Q3 clears):**
- `@auditor` `code-quality` concern covers general patterns but
  `silent-failure-hunter`'s heuristics are tighter for this specific risk.
- This is **augmentation, not replacement** — `@auditor` still ships the
  grade; the specialist contributes one extra concern lane.
- Read-only; scoped to the wave's `[FILE-SCOPE]` union.

**Dispatch:**

```json
Agent({
  "description": "specialist:pr-review-toolkit:silent-failure-hunter: augment wave-2 audit on error-handling lanes",
  "subagent_type": "pr-review-toolkit:silent-failure-hunter",
  "model": "sonnet",
  "prompt": "Augmentation lane for wave-2 audit on v5.1.5-dev.3. File scope (union of lanes): src/retry.rs, src/mcp_fallback.rs, src/gate.rs. @auditor is concurrently grading via standard concerns; you focus narrowly on swallowed errors / unwrap-without-context / log-and-continue patterns. Findings ride on top of @auditor's report — your output appends to .artifacts/reports/2026-05-19-w2-silent-failures.md. Do NOT grade; do NOT file the wave's primary findings — that's @auditor."
})
```

**Operator surface line:**

```
[NODE] specialist:pr-review-toolkit:silent-failure-hunter → on-finding | 2 swallowed errors in src/mcp_fallback.rs; auditor folding into close-report
```

### Example D — CLAUDE.md health check before opening a new sprint (optional fourth example)

**Trigger:** the planter is about to author dev.0 of a new patch and the
project's CLAUDE.md has not been audited in 3 patches. `@worker` could
read CLAUDE.md and produce a summary, but `claude-md-management:claude-md-improver`
applies a templated quality rubric.

**Why specialist (Q3 clears):**
- Purpose-built for CLAUDE.md health; mechanical rubric application.
- Read-then-recommend (writes ONLY when explicitly invited by operator).

**Dispatch:**

```json
Agent({
  "description": "specialist:claude-md-management:claude-md-improver: audit CLAUDE.md before dev.0",
  "subagent_type": "claude-md-management:claude-md-improver",
  "model": "sonnet",
  "prompt": "Audit the CLAUDE.md at repo root (and any nested CLAUDE.md). Output the quality report ONLY — do NOT apply patches. Patches will be applied by an @coder lane in dev.0 if the operator signs off."
})
```

**Operator surface line:**

```
[NODE] specialist:claude-md-management:claude-md-improver → on-finding | 3 gaps: missing version-source table, stale layout section, missing meta-tier note
```

---

## Plugin reload + discovery

> Companion subsection to SPECIALIST DISCOVERY §Step 4 — kept distinct so
> the conductor's checklist can cite either by anchor.

When the conductor references a specialist plugin/agent that isn't currently
registered in the session:

1. **Detect** via Step 1 (available-agents list) + Step 2 (ToolSearch returns
   no match).
2. **Decide** which response applies:

   | Situation | Response |
   |---|---|
   | Specialist listed in `shepherd.toml [specialists].allowed`, plugin should be installed | Surface `/reload-plugins` request to operator. Wait for reload signal. |
   | Specialist NOT in `allowed`, conductor is improvising | STOP — this is the anti-pattern "conductor reaches for general-purpose because @worker felt heavy." Fall back to flock. |
   | Reload requested, post-reload still unavailable, task has flock-acceptable substitute | Degrade to flock (`@worker` / `@discovery`) with explicit annotation in the operator log. |
   | Reload requested, post-reload still unavailable, task strictly requires the specialist | HALT with `halt_code: SPECIALIST-UNAVAILABLE`. Operator decides. |

3. **Surface** the path taken on the operator log — never hide the
   substitution.

See also `doctrines/plugin-reload-escape.md` (the MCP-tool analogue —
identical philosophy: flag, don't silently degrade).

---

## Skills vs agents — important distinction

Many "third-party tools" the operator might mention (e.g., `supabase:supabase`,
`finance`, `rust`) are SKILLS that load into a session, not AGENTS that get
dispatched. Skills are loaded via `Skill(skill="<slug>")` inside any
agent's dispatch — they're not separate dispatches.

This doctrine governs AGENTS (things you `Agent(...)` into existence).
Skills are loaded by whichever lane needs them — the framework already
supports this via the `[SKILLS]` block in coder/engineer briefs.

## Operator communication

When the conductor dispatches a specialist, the operator surface line includes
the specialist origin:

```
[NODE] specialist:pr-review-toolkit:code-reviewer → on-no-finding | PR #34 clean
[NODE] specialist:sentry:seer → on-finding | 3 active issues, 2 above thresholds
[NODE] specialist:claude-code-guide → on-finding | SubagentStop fires with exit_code only
```

This makes specialist dispatches visible in the audit trail; they're not
hidden inside the flock-dispatch log.

## Audit trail

The `agent_invocation_tagger.sh` hook (v5.1.2) records every dispatched
agent's role. For specialists, `agent_role` becomes `specialist:<plugin>:<slug>`
(e.g., `specialist:pr-review-toolkit:code-reviewer`). The completeness
auditor at sprint close verifies specialist dispatches were:

- Pre-authorized in `shepherd.toml [specialists].allowed`
- Used for a task the decision tree's Q3 permits
- Logged + surfaced to the operator

Specialist dispatch outside the allowed list → process violation; grade-cap C+.

## Anti-patterns this doctrine catches

1. **Conductor dispatches `general-purpose` because "@worker felt heavy."** No.
   `general-purpose` is explicitly forbidden — it is NOT a specialist; it
   is an unconstrained generic agent that breaks shepherd's discipline-
   loss boundary. If `@worker` feels heavy, the answer is a tighter
   `@worker` brief, not `general-purpose`. The discipline shepherd encodes
   (bounded brief, deliverable, budget) IS the value-add — discarding it
   discards the framework.
2. **Conductor dispatches `Explore`.** Same prohibition. `@discovery` is the
   read-only synthesis lane with the framework's contract.
3. **Specialist used in place of `@critic` / `@engineer` / `@auditor` / `@coder`.**
   Hard never. Those lanes are doctrinal — Q1 of the decision tree blocks.
4. **Conductor dispatches specialist without reading its contract THIS session.**
   People skim across sessions; the description block in a prior session is
   not authoritative for this one. Read it again. Mis-briefed specialists
   produce garbage.
5. **Specialist dispatch hidden from operator surface.** Every specialist
   dispatch surfaces in the operator log; the audit trail names the plugin
   + slug.
6. **Skipping the decision tree.** Any non-flock dispatch that lands in the
   session without Q1→Q4 evaluation is a process violation. The conductor's
   checklist requires citing the cleared question (Q3) before dispatch.
7. **Silent specialist degradation.** Specialist unavailable, conductor
   falls back to `@worker` without an operator-surface annotation. Per
   §Plugin reload + discovery — always annotate.

## See also

- `flock.md` §I — the canonical six-lane flock and dispatch procedure
- `doctrines/agent-excellence.md` — when in doubt, the flock is the default; strive-higher framing
- `doctrines/plugin-reload-escape.md` — MCP-tool unavailability analogue
- `doctrines/worker-patterns.md` — when @worker is the right answer (most of the time)
- `hooks/scripts/agent_invocation_tagger.sh` — records specialist origin
- `agents/conductor.md` §Hard prohibitions + §Anti-patterns — flock-first reinforcement
- `SKILL.md` §I (v5.1.1+) — "closed at six + specialist exceptions per doctrine"
