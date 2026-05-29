# Sprint Seed Template (canonical)

This is the shape every seed authored by `/shepherd:plant` (or by the operator/main-chat when planting inline) must follow. The @engineer's Phase 0 mesh, the @critic's plan-gate, and the @auditor's completeness review all assume this structure.

A seed is **dense, drift-resistant, multi-phase, and parallel-aware**. Tables over prose; runnable acceptance over narrative; every reference verified at planting time.

---

## File path

```
{paths.plans}/{sprint_slug}.seed.md
```

For a patch under default config (`patch_slug_pattern = "v{X}{Y}{Z}"`, `sprint_slug_pattern = "v{X}{Y}{Z}-dev{N}"`), this resolves to e.g., `.artifacts/plans/v029-dev5.seed.md`. Filenames collapse the version triplet (`X.Y.Z` → `XYZ`) and the `-dev.N` suffix (`-dev.N` → `-devN`) per `doctrines/seed-naming.md`. Branches keep dots; filenames don't.

Patch-arc seeds drop the sprint suffix: `{paths.plans}/{patch_slug}.seed.md` → e.g., `.artifacts/plans/v029.seed.md`.

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

Output path: `{paths.reports}/<date>-{sprint_slug}-phase0.md`.

### 5. Engineering decisions (locked) — bullets

Constraints that the engineer + coders + auditors must respect. Examples:
- "Cumulative live cap: $50/7d. `BudgetRegistry` enforces."
- "Hot-fix cap: 3 concurrent < S-size patches."
- "Demotion criterion: live win-rate < 0.45 over ≥ 30 fills."

Each decision is **non-negotiable for this sprint**. If the engineer wants to change one, that's a critic-RED escalation.

### 6. Deliverables (issue-anchored) — v6.0.0

> **Origin of the rename:** FL03/shepherd #67 (2026-05-27). The pre-v6.0.0
> §6 was titled "MUST-LAND lanes — numbered, issue-anchored" and prescribed
> a `Lane N` numbering format with explicit `Sequencing:` directives. That
> conflicts with operator-binding doctrine: **lane decomposition is the
> engineer's exclusive authority**, not the planter's. The planter names
> WHAT must land; the engineer (and the conductor under its plan) decides
> HOW to parallelize and group deliverables into lanes for dispatch.

Every deliverable has the same compact shape — **detailed change spec, full
file scope, and long-form acceptance live in the backing GH issue body, NOT
in the seed**. The seed entry is a routing pointer (per
`doctrines/seed-anchored-by-issues.md`).

```markdown
### <one-line deliverable name>  [<priority>]

- **GH:** <#NNN | file at Phase 0 — title: "<concise issue title>" | N/A — process deliverable>
- **Priority:** <CRITICAL | HIGH | MEDIUM | LOW>
- **Spec:** <one-line summary; full details in #NNN body §Spec>
- **Acceptance:** <one-line runnable grep | "see #NNN body §Acceptance">
```

Deliverable block target: **≤ 8 lines**. If you need more, push detail into
the GH issue body and link it.

What the seed does **NOT** prescribe (engineer-territory):

- **Lane numbering** (`Lane 1`, `Lane 2`, ...). The engineer composes lanes
  in the plan based on file-disjointness, T-shirt sizing, and the wave
  decomposition. Seed deliverables are unordered routing pointers.
- **Sequencing directives** (`sequential after Lane K`, `parallel-safe with
  Lane M`). The engineer's `## Stage Graph` block in the plan encodes
  parallel-safety via `parallel_with` and predicate edges. If a deliverable
  has a hard dependency on another (e.g., a public re-export needed by a
  sibling), state the dependency in the GH issue body's `## Depends on`
  section; the engineer reads it during MESH and composes accordingly.
- **T-shirt sizes per deliverable**. The sprint as a whole has a T-shirt
  size (in frontmatter `sprint_size`). Per-deliverable sizing is the
  engineer's analysis at plan-time; the planter may RECOMMEND in the GH
  issue body but does not bind.

**Process-deliverable exception** (closeout / release-pipeline /
retrospective / audit-swarm / milestone population): set `**GH:** N/A —
process` and keep the inline shape:

```markdown
### <process deliverable name>  [<priority>]

- **GH:** N/A — process
- **Priority:** <...>
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

### 7. Wave composition (NON-BINDING recommendation — engineer composes `waves × steps`)

The planter MAY sketch a wave shape so the engineer doesn't invent
structure from scratch, but this is a recommendation only. The engineer's
`## Stage Graph` in the plan is the binding **`waves × steps`** composition
(lanes, if any, are the engineer's post-plan spawn projection —
`doctrines/primitive-axis-binding.md`).

```markdown
| Wave | Deliverables grouped (planter recommendation) | Depends on |
|------|----------------------------------------------|------------|
| 1    | <deliverable headings from §6>               | —          |
| 2    | <deliverable headings>                       | Wave 1     |
| 3    | <test consolidation>                         | Wave 2     |
```

The engineer is free to re-group, split, or merge waves based on Phase 0
mesh findings, file-disjointness analysis, and per-deliverable T-shirt
sizing. Per `agents/engineer.md`: decompose each wave into many narrow
**steps** (substantive LOC floor by T-shirt); and under `/shepherd:spawn`,
the engineer's post-plan **lane projection** meets the **total** lane
minimum (M ≥ 6, L ≥ 8, XL 10–15 — total vertical slices, **never** per-wave).
Per-step / per-lane scope ≤ 5 files; split mercilessly if exceeded. These are
engineer-side, not planter prescription.

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
| #NNN | <title> | CRITICAL | <prior sprint> | N | LAND (Wave K) | DEFER to dev.{M} | DROP (operator-marked) |
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

- [ ] Every deliverable in §6 has a `**GH:**` line
- [ ] Every existing `#NNN` resolves
- [ ] Every file path resolves
- [ ] Phase 0 mesh table has 8+ rows
- [ ] Deliverable blocks stay under 8 lines (per v6.0.0 §6 contract)
- [ ] Sprint T-shirt size matches deliverable count (recommendation only)
- [ ] At least one deliverable is CRITICAL or HIGH priority
- [ ] No `TODO:` / `FIXME:` markers
- [ ] No `Lane N` numbering or `Sequencing:` directives in seed body (per v6.0.0; engineer's authority)
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
