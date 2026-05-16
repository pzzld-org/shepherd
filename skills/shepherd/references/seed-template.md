# Sprint Seed Template (canonical)

This is the shape every seed authored by `/shepherd:plant` (or by the operator/main-chat when planting inline) must follow. The @engineer's Phase 0 mesh, the @critic's plan-gate, and the @auditor's completeness review all assume this structure.

A seed is **dense, drift-resistant, multi-phase, and parallel-aware**. Tables over prose; runnable acceptance over narrative; every reference verified at planting time.

---

## File path

```
{paths.plans}/{sprint_slug}.seed.md
```

For a patch under default config (`patch_branch_pattern = "v{X}.{Y}.{Z}"`, `sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"`), this resolves to e.g., `.artifacts/plans/v0.2.9-dev.5.seed.md`.

Patch-arc seeds drop the sprint suffix: `{paths.plans}/{patch_slug}.seed.md` → e.g., `.artifacts/plans/v0.2.9.seed.md`.

---

## Required frontmatter

```yaml
---
title: {sprint_branch} Seed — <one-line theme>
branch: {sprint_branch}
base: {patch_branch}
kind: sprint-seed                          # or: patch-seed | next-version-skeleton
status: ready-for-engineer                 # or: draft | needs-operator-review
date: <YYYY-MM-DD>                         # planter mesh date
revised: <YYYY-MM-DD>                      # last edit date
author: planter (opus) @ <session-id>      # or: main-chat | operator
prior_sprint: <prior {sprint_branch}>
prior_close_report: {paths.reports}/<date>-<prior sprint>-close.md
prior_handoff: {paths.docs}/<date>-<prior sprint>-close-handoff.md
patch_seed: {paths.plans}/{patch_slug}.seed.md
planter_mesh: {paths.reports}/<date>-planter-mesh.md
milestone: <GH-milestone-number-for-{patch_branch}>
sprint_dependencies: [<prior dev branch identifiers>]   # which prior sprints this depends on
parallel_with: [<other dev branch identifiers>]          # which other sprints can run concurrently
sprint_size: <XS | S | M | L | XL>          # T-shirt
file_scope:
  exclusive:                                # files this sprint OWNS — no parallel sprint touches them
    - <path>
  additive:                                 # files this sprint MAY edit (shared with parallel sprints under coordination)
    - <path>
---
```

The frontmatter is the machine-readable contract. The engineer's Phase 0 mesh and the critic's gate both parse it.

---

## Required body sections (in order)

### 1. North star — one paragraph, ≤ 4 sentences

The single most important sentence: what this sprint produces and why. No motivation paragraphs; no "why now" rhetoric. State the output. The reader should be able to tell, after one paragraph, whether this sprint matters to them.

### 2. Why this sprint (≤ 5 bullets)

Anchored to current state. Each bullet cites at least one of:
- A prior close report (`{paths.reports}/...`)
- A GH issue (`#NNN`)
- A memory entry (per `[memory].project_memory`)
- A research / design doc (`{paths.plans}/research/*.md`, `{paths.docs}/*.md`)
- A project doctrine (`[memory].project_doctrines/*.md`)

Bullets that lack citation are deleted. The seed is not a vibes document.

### 3. Sprint character — one paragraph

T-shirt size, parallel-safety summary, calendar shape (light vs heavy, observational vs implementation-heavy), expected wave count.

### 4. Phase 0 mesh mandate (table)

Table with columns: `#`, `Source`, `Query`, `Pass condition`. The engineer re-runs each row at plan-time and detects drift since the planter mesh.

The 12-row default (project-extensible via `[memory].project_doctrines/planter-mesh-extensions.md`):

```markdown
| # | Source | Query | Pass condition |
|---|--------|-------|----------------|
| 1 | GitHub issues (FULL ledger sweep) | `mcp__plugin_github_github__list_issues({state: "open", per_page: 500})` | classify per `[ledger.classify_into]`; surface drift-risk count |
| 2 | GitHub PRs                         | open + recently merged                                                | recent activity since prior close |
| 3 | GitHub milestones                  | walk all open milestones                                              | which version targets which work |
| 4 | git log                            | `git log {patch_branch}..HEAD --oneline -30`                          | commits since branch cut |
| 5 | Sentry (if `[mcp].sentry`)         | `mcp__plugin_sentry_sentry__search_events`                            | error baselines vs prior sprint |
| 6 | Datastore (if `[mcp].supabase`)    | schema query + key-table row counts                                   | schema state, migration backlog |
| 7 | Deploy state (if `[cli].fly`)      | `fly status`                                                          | deploy healthy, last image timestamp |
| 8 | Prior close                        | `{paths.reports}/<date>-<prior sprint>-close.md`                      | grade, blockers, carry-forwards |
| 9 | Prior handoff                      | `{paths.docs}/<date>-<prior sprint>-close-handoff.md`                 | what shipped, what's next |
| 10 | Project CLAUDE.md                 | local read of "Current — v0.X.Y" section                              | current state confirmed |
| 11 | Carry-forward ledger              | `[ledger.carry_forward_file]`                                         | chronic items surfaced |
| 12 | Workspace knowledge silo          | `{paths.ctx}/*.md`                                                    | structural-context inputs |
| 13 | **Dedup-grep gate**               | language-specific grep BEFORE any new type lane is dispatched         | If type exists, lane REPLACED with "wire to existing" |
| 14 | **Wrapper-grep gate**             | per `doctrines/wrapper-must-earn.md`, language-specific grep          | Hits in lane-modified files: 0. Pre-existing → wrapper-debt-ledger.md |
| 15+ | (project-doctrine extensions)    | per `planter-mesh-extensions.md`                                      | per project |
```

Output path: `{paths.reports}/<date>-{sprint_branch}-phase0.md`.

### 5. Engineering decisions (locked) — bullets

Constraints that the engineer + coders + auditors must respect. Examples:
- "Cumulative live cap: $50/7d. `BudgetRegistry` enforces."
- "Hot-fix cap: 3 concurrent < S-size patches."
- "Demotion criterion: live win-rate < 0.45 over ≥ 30 fills."

Each decision is **non-negotiable for this sprint**. If the engineer wants to change one, that's a critic-RED escalation.

### 6. MUST-LAND lanes — numbered, issue-anchored

Every lane has the same compact shape — **detailed change spec, full file scope, and long-form acceptance live in the backing GH issue body, NOT in the seed**. The seed lane is a routing pointer (per `doctrines/seed-anchored-by-issues.md`).

```markdown
### Lane N — <one-line lane name>  [<priority>]

- **GH:** <#NNN | file at Phase 0 — title: "<concise issue title>" | N/A — process lane>
- **Priority:** <CRITICAL | HIGH | MEDIUM | LOW>
- **Size:** <XS | S | M | L | XL>
- **Trigger:** <unconditional | "<runnable check>" returns Z at Phase 0>   ← only for conditional lanes
- **Spec:** <one-line summary; full details in #NNN body §Spec>
- **Acceptance pointer:** <one-line runnable grep | "see #NNN body §Acceptance">
- **Sequencing:** <parallel-safe with Lane M | sequential after Lane K>   ← only if non-default
```

Lane block target: **≤ 10 lines**. If you need more, push detail into the GH issue body and link it.

**Process-lane exception** (closeout / release-pipeline / retrospective / audit-swarm / milestone population): set `**GH:** N/A — process lane` and keep the inline shape:

```markdown
### Lane N — <process lane name>  [<priority>]

- **GH:** N/A — process lane
- **Priority:** <...>
- **Size:** <...>
- **Steps:** <numbered list of mechanical steps; OK to be inline>
- **Acceptance:** <runnable check or artifact path>
```

### GH issue body template (what the seed POINTS to)

When a seed lane says "file at Phase 0", the engineer's Phase 0 mesh runs `mcp__plugin_github_github__issue_write` with this body:

```markdown
## Summary
<one paragraph — what + why>

## Evidence
<data, diagnostic output, code citations>

## Spec
1. <numbered change steps>
2. ...

## File scope
- <path 1>
- <path 2>

## Acceptance
- <runnable grep + expected count>
- <runnable grep + expected count>

## Non-goals
- <reserved for other sprints>

## Sequencing
- <parallel-safe with #NNN | sequential after #MMM>

## Cross-references
- Seed: <path>
- Prior close: <path>
- Memory: <path>
- Doctrines invoked: <list>
```

### 7. Wave composition — table

```markdown
| Wave | Lanes | Parallel? | Depends on | T-shirt total |
|------|-------|-----------|------------|---------------|
| 1    | A, B, C | parallel  | —          | M             |
| 2    | D, E    | parallel  | Wave 1     | S             |
| 3    | tests   | parallel  | Wave 2     | XS            |
```

Minimum lanes per sprint size: M→3 in Wave 1; L→4 in Wave 1; XL→4 per wave.

### 7-bis. Stage decomposition hint (NON-BINDING — engineer finalizes)

Per `doctrines/stage-graph.md` and `pipeline.md`, the engineer's plan emits a binding `## Stage Graph` (full DAG). The seed sketches a **non-binding hint** so the engineer doesn't invent structure from scratch.

```markdown
## Stage decomposition hint

phase-0          MESH                                     [unconditional, runs first]
phase-A          WAVE-1-IMPL  (parallel: A1, A2, A3)      [unconditional after PLAN-GATE on-green]
                 WORKER-IO    (parallel_with: WAVE-1-IMPL) [batched at Wave 1 START]
phase-A-gate     WAVE-1-GATE                              [conductor inline; on-pass → phase-B]
phase-B          WAVE-2-IMPL  (parallel: B1, B2)          [Pattern B: parallel_with WAVE-1-AUDIT]
                 WAVE-1-AUDIT (auditors on Wave 1 output) [Pattern B: parallel_with WAVE-2-IMPL]
phase-B-gate     WAVE-2-GATE                              [conductor inline]
phase-tests      WAVE-3-IMPL  (parallel: T1)              [conditional on phase-B-gate on-pass]
phase-close      CLOSE-SWARM (3–5 auditors by concern)    [unconditional after final wave-gate]
                 → CLOSE-FINALIZE                          [on-no-finding OR on-grade-cap]
hot-fix          HOTFIX (≤3 concurrent, ≤S each)          [conditional on any AUDIT on-finding]
hard-stops       any node may exit on on-hard-stop        [terminal]
```

The engineer specializes this into the binding YAML graph at `## Stage Graph` of the plan, with explicit `in_predicates`, `out_edges`, `parallel_with`, and `agents` blocks per node (per `pipeline.md` §XII).

### 8. Carry-forward dispositions — table

```markdown
| GH# | Item | Severity | First seen sprint | Patches crossed | Disposition this sprint |
|---|---|---|---|---|---|
| #NNN | <title> | CRITICAL | <prior sprint> | N | LAND in Lane K | DEFER to dev.{M} | DROP (operator-marked) |
```

Items crossing `[ledger.chronic_threshold_patches]` boundaries are flagged CHRONIC.

### 9. Drift-risk items not in this sprint's scope — table

```markdown
| GH# | Severity | Title | Why it's a drift risk |
|---|---|---|---|
| #... | CRITICAL | <title> | not on current milestone, no carry-forward, but production-affecting |
```

Per `doctrines/issue-ledger-awareness.md`. The operator decides whether to absorb, milestone-out-of-drift, or accept the drift risk.

### 10. Non-goals — bullets

Verbatim from operator + planter analysis. What this sprint EXPLICITLY DOES NOT do. Reserved for future sprints with named target slots.

### 11. Open questions for critic — bullets

Ambiguities the planter couldn't resolve from operator intent + mesh evidence. The critic adjudicates these at plan-gate time.

### 12. References — list

Every doc cited above, plus:

- The patch-arc seed
- Prior close reports + handoffs (most recent 2)
- Memory entries (project + framework doctrines)
- Research / design docs

---

## Patch-arc seed shape (when planting `arc`)

The patch-arc seed has the same frontmatter (with `kind: patch-seed`, `branch: {patch_branch}`, no `prior_sprint`, no `parallel_with`).

Body sections specific to patch-arc:

### A. Patch theme — one paragraph

What this entire patch (`{patch_branch}`) is about. ≤ 4 sentences.

### B. Sprint topology — table

```markdown
| Sprint | Theme | Size | Depends on | Parallel-safe with |
|---|---|---|---|---|
| dev.0 | setup, carryover, cleanup | M | — | dev.1 (no overlap) |
| dev.1 | <theme> | L | dev.0 | dev.2, dev.3 |
| dev.2 | <theme> | M | dev.0 | dev.1, dev.3 |
| ... | | | | |
| dev.{last} | release pipeline | S | all prior | — |
```

### C. Release-gate criteria — numbered

```markdown
1. <runnable check that must pass before release>
2. <runnable check>
```

These are the criteria the dev.{last} release pipeline verifies before squashing to main.

### D. Cross-sprint dependencies — directed graph

```markdown
dev.0 → dev.1 → dev.2 → [dev.3 || dev.4] → dev.5 → ... → dev.{last}
```

### E. Carry-forward ledger snapshot — table

Carry-forwards INHERITED from the prior patch's close. Each gets either:
- Slotted into a sprint
- Deferred with target slot
- Dropped with operator-marked won't-fix

### F. Patch-level non-goals — bullets

What this patch EXPLICITLY DOES NOT do. Items reserved for future patches with named target slots.

---

## Verification (planter pre-commit)

Before `git add` and `git commit`, the planter runs (per `planter.md` §X):

- [ ] Every MUST-LAND lane has a `**GH:**` line
- [ ] Every existing `#NNN` resolves
- [ ] Every file path resolves
- [ ] Phase 0 mesh table has 8+ rows
- [ ] Lane blocks stay under 10 lines
- [ ] Sprint T-shirt size matches lane composition
- [ ] At least one MUST-LAND lane is CRITICAL
- [ ] No `TODO:` / `FIXME:` markers
- [ ] Seed footprint ≤ 400 lines (sprint) / ≤ 200 lines (patch-arc)

A seed that fails any check is fixed before commit.

---

## See also

- `planter.md` — the planter's behavioral contract (who writes seeds)
- `pipeline.md` — the binding Stage Graph the engineer emits (this seed sketches a hint)
- `doctrines/stage-graph.md` — graph-as-dispatch-contract principle
- `doctrines/seed-anchored-by-issues.md` — lane-anchoring discipline
- `doctrines/issue-ledger-awareness.md` — full-ledger Phase 0 sweep (drives mesh row 1)
- `doctrines/wrapper-must-earn.md` — wrapper-grep gate (drives mesh row 14)
- `doctrines/carry-forward-refresh.md` — chronic flagging (drives §8 dispositions)
- `agent-briefs.md` — how lanes become coder briefs
- `branching-model.md` — patch lifecycle context
