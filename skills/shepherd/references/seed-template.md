---
title: seed-template
description: Canonical seed shape (frontmatter, 12 body sections, verification gate) every seed MUST follow. Use when authoring or parsing a seed.
---

# Seed Template (canonical)

A seed authored by `/shepherd:plant` (or inline by operator/main-chat) MUST follow this shape — the engineer's Phase-0 mesh, the critic's PLAN-GATE, and the auditor's completeness review all parse it. Dense, drift-resistant, parallel-aware: tables over prose, runnable acceptance over narrative, every reference verified at planting time.

## File path

```
{paths.plans}/{sprint_slug}.seed.md
```

e.g. `.artifacts/plans/v029-dev5.seed.md`. Patch-arc seeds drop the sprint suffix: `{paths.plans}/{patch_slug}.seed.md` (e.g. `.artifacts/plans/v029.seed.md`).

**Branches keep dots; filenames collapse them:** `X.Y.Z` → `XYZ`, `-dev.N` → `-devN`.

| Asset | Form | Example |
|---|---|---|
| Git branch (sprint) | dotted — `{sprint_branch_pattern}` | `v5.1.2-dev.3` |
| Git branch (patch) | dotted — `{patch_branch_pattern}` | `v5.1.2` |
| Seed file (sprint) | slug — `{sprint_slug_pattern}` | `v512-dev3.seed.md` |
| Seed file (patch) | slug — `{patch_slug_pattern}` | `v512.seed.md` |
| Plan file (sprint) | slug — `{sprint_slug_pattern}` | `v512-dev3.plan.md` |
| Close report | dated | `<date>-{sprint_slug}-close.md` |

`shepherd.toml [branching]` declares `patch_branch_pattern`, `sprint_branch_pattern`, `patch_slug_pattern`, `sprint_slug_pattern`. Absent `*_slug_pattern` → falls back to `*_branch_pattern`, warns at session start.

The `-devN` per-sprint suffix is ALLOWED (`/shepherd:spawn` and each `--parallel` lane read it). `references/branching-model.md`'s patch-scoped-only rule governs FINAL artifacts only (CHANGELOG, tags, release PR titles) and the patch-arc seed/plan — never the per-sprint seed.

## Required frontmatter

```yaml
---
title: {sprint_branch} Seed — <one-line theme>
branch: {sprint_branch}
base: {patch_branch}
kind: sprint-seed                          # | patch-seed | next-version-skeleton
status: ready-for-engineer                 # | draft | needs-operator-review
date: <YYYY-MM-DD>
revised: <YYYY-MM-DD>
author: planter (opus) @ <session-id>
prior_sprint: <prior {sprint_branch}>
prior_close_report: {paths.reports}/<date>-<prior sprint>-close.md
prior_handoff: {paths.docs}/<date>-<prior sprint>-close-handoff.md
patch_seed: {paths.plans}/{patch_slug}.seed.md
planter_mesh: {paths.reports}/<date>-planter-mesh.md
milestone: <GH-milestone-number-for-{patch_branch}>
sprint_dependencies: [<prior dev branch identifiers>]
parallel_with: [<other dev branch identifiers>]
sprint_size: <XS | S | M | L | XL>
file_scope:
  exclusive:                                # OWNED
    - <path>
  additive:                                 # MAY edit
    - <path>
---
```

Every key is load-bearing — parsed by both the engineer's Phase-0 mesh and the critic's PLAN-GATE.

## Required body sections (in order)

### 1. North star
≤4 sentences. State the output only — no motivation prose.

### 2. Why this sprint
≤5 bullets. Each cites ≥1 of: a prior close report, a GH issue `#NNN`, a memory entry, a research/design doc, a project doctrine, or a harvested lesson (`prior:<mem_id>`). An uncited bullet is deleted — the seed is not a vibes document.

### 2-bis. Priors / lessons carried forward
Run `shctx adapt priors --lessons --md`.

```markdown
| Prior id | Lesson (concern) | Guard this sprint applies |
|---|---|---|
| `prior:<mem_id>` | <one-line lesson> | <lane / acceptance / non-goal addressing it> |
```

Write "none (first cycle)" when empty. Citation + harvest/store/inject contract: `skills/adaptation/SKILL.md §Loop contract`.

### 3. Sprint character
T-shirt size, parallel-safety, calendar shape, expected wave count, recommended lane count (planter-recommended; engineer-decided post-plan). Lane-sizing floors are engineer authority: `references/pipeline.md §Lane law`.

### 4. Phase 0 mesh mandate
The engineer re-runs each row at plan-time and detects drift since the planter mesh.

```markdown
| # | Source | Query | Pass condition |
|---|--------|-------|----------------|
| 1 | GH issues (FULL sweep) | `gh issue list --state open --limit 500` | classify per `[ledger.classify_into]`; surface drift-risk count |
| 2 | GH PRs | open + recently merged | activity since prior close |
| 3 | GH milestones | walk all open | version→work map |
| 4 | git log | `git log {patch_branch}..HEAD --oneline -30` | commits since cut |
| 5 | Sentry (`[mcp].sentry`) | search-events | error baseline vs prior |
| 6 | Datastore (`[mcp].supabase`) | schema + row counts | schema state, backlog |
| 7 | Deploy (`[cli].fly`) | `fly status` | healthy, last image ts |
| 8 | Prior close | `{paths.reports}/<date>-<prior sprint>-close.md` | grade, blockers, carry-forwards |
| 9 | Prior handoff | `{paths.docs}/<date>-<prior sprint>-close-handoff.md` | shipped, next |
| 10 | Project CLAUDE.md | "Current — v0.X.Y" | current state |
| 11 | Carry-forward ledger | `[ledger.carry_forward_file]` | chronic items surfaced |
| 12 | Knowledge silo | `{paths.ctx}/*.md` | structural-context inputs |
| 13 | **Dedup-grep gate** | grep before any new type dispatched | exists → "wire to existing" |
| 14 | **Wrapper-grep gate** | grep, per `references/flock.md §@auditor` | 0 hits, lane-modified files |
| 15+ | doctrine extensions | `[memory].project_doctrines/planter-mesh-extensions.md` | per project |
```

Output: `{paths.reports}/<date>-{sprint_slug}-phase0.md`.

### 5. Engineering decisions (locked)
Non-negotiable constraints (e.g. "Cumulative live cap: $50/7d"). Changing one is a critic-RED escalation.

### 6. Deliverables (issue-anchored)
Every deliverable cites a GH issue (or a "file at Phase 0" placeholder). Full change-spec, file scope, and acceptance live in the GH issue body, NEVER the seed. Lane decomposition, sequencing, and T-shirt sizes are engineer territory — the seed names WHAT must land, never HOW it's grouped. Target ≤8 lines per block:

```markdown
### <one-line deliverable name>  [<priority>]
- **GH:** <#NNN | file at Phase 0 — title: "<concise issue title>" | N/A — process deliverable>
- **Priority:** <CRITICAL | HIGH | MEDIUM | LOW>
- **Spec:** <one-line summary; full detail in #NNN body §Spec>
- **Acceptance:** <one-line runnable grep | "see #NNN body §Acceptance">
```

Two variants — placeholder (no GH issue yet) and process exception (no issue needed, `**Steps:**` replaces `**Spec:**`):

```markdown
### Stale book auto-clear  [MEDIUM]
- **GH:** *file at Phase 0 — title: "fix(quad): stale_book auto-clear on hot-upsert"*
- **Priority:** MEDIUM
- **Spec:** `quad_tick.rs:283-287`
- **Acceptance:** rg -n 'stale_book' returns 0 hits in prod logs post-deploy

### Sprint close  [MECHANICAL]
- **GH:** N/A — process
- **Priority:** MECHANICAL
- **Steps:** <numbered mechanical steps — OK inline>
- **Acceptance:** <runnable check or artifact path>
```

Phase-0 mesh files the placeholder's issue; the conductor inlines the number before dispatch.

**Prohibited in every deliverable:** prescriptive `Lane N` numbering — lane composition is the engineer's `## Stage Graph` authority (`references/pipeline.md §Stage Graph`); `shctx seed verify` HARD-blocks the `Lane N` token in a seed body.

**GH issue body** — one-line headings: `## Summary`, `## Evidence`, `## Spec` (numbered), `## File scope`, `## Acceptance` (runnable grep + expected count), `## Non-goals`, `## Sequencing` (`parallel-safe with #NNN` | `sequential after #MMM`), `## Cross-references`.

### 6-bis. Outcome verification
Every `**Acceptance:**` line MUST be a runnable predicate, never prose (grep+count, structural assertion, LOC floor, log/metric/DB query, health probe).

**Author once, reference thrice.** The predicate is authored ONCE in the GH issue's `## Acceptance`; the seed's `**Acceptance:**` and the engineer's `[ACCEPTANCE]` both REFERENCE it (`see #NNN body §Acceptance`) instead of re-typing — re-typing is how the two diverge.

Enforcement (SEED/PLAN-GATE/CLOSE/SOAK seams, `PLAN-MISSING-OUTCOME-VERIFICATION`, `OUTCOME-REGRESSION`, completeness cap): `references/pipeline.md §Gates`; soak: `skills/motivation/SKILL.md §SOAK`. Note `soak: T+1d, T+7d` on any deliverable that can regress post-delivery.

### 7. Wave composition (non-binding)
The planter MAY sketch a wave shape as a recommendation; the engineer's `## Stage Graph` (`references/pipeline.md §Stage Graph`) is the binding composition. Lane sizing is a post-plan, engineer-side projection, never per-wave: `references/pipeline.md §Lane law`.

```markdown
| Wave | Deliverables grouped (recommendation) | Depends on |
|------|----------------------------------------|------------|
| 1    | <deliverable headings from §6>          | —          |
| 2    | <deliverable headings>                  | Wave 1     |
```

### 8. Carry-forward dispositions

```markdown
| GH# | Item | Severity | First seen | Patches crossed | Disposition |
|---|---|---|---|---|---|
| #NNN | <title> | CRITICAL | <sprint> | N | LAND(Wave K) \| DEFER(dev.M) \| DROP |
```

Items crossing `[ledger.chronic_threshold_patches]` are flagged CHRONIC: `references/pipeline.md §CLOSE`.

### 9. Drift-risk items

```markdown
| GH# | Severity | Title | Why a drift risk |
|---|---|---|---|
| #... | CRITICAL | <title> | off-milestone, no carry-forward, production-affecting |
```

Operator decides: absorb, milestone-out-of-drift, or accept.

### 10. Non-goals
What this sprint explicitly does NOT do, with target slots for future work.

### 11. Open questions for critic
Ambiguities the planter could not resolve; the critic adjudicates at PLAN-GATE.

### 12. References
Every doc cited above, plus the patch-arc seed, the two most recent close reports/handoffs, memory entries, and research docs.

## Patch-arc seed shape

Same frontmatter with `kind: patch-seed`, `branch: {patch_branch}`, no `prior_sprint`/`parallel_with`.

- **A. Patch theme** — one paragraph, ≤4 sentences.
- **B. Sprint topology** — table: `Sprint | Theme | Size | Depends on | Parallel-safe with`.
- **C. Release-gate criteria** — numbered runnable checks before squash to main.
- **D. Cross-sprint dependencies** — directed graph, e.g. `dev.0 → dev.1 → [dev.2 || dev.3] → ... → dev.{last}`.
- **E. Carry-forward ledger snapshot** — inherited from the prior patch's close: slotted / deferred / dropped.
- **F. Patch-level non-goals** — target slots for future patches.

## Verification

The pre-flight is mechanical — same seed, same verdict — a script, not a prose checklist. Before `git add`, run:

```
shctx seed verify {paths.plans}/{sprint_slug}.seed.md
```

`shctx seed verify` (`skills/context/scripts/cmd_seed.sh`) is the single source of truth for the checklist and its numbers. HARD-fails (exit 1, blocks `SEED-GATE`) on: a hallucinated `file_scope` path; an over-cap footprint (**≤400 lines sprint / ≤200 lines patch-arc**); a `TODO:`/`FIXME:` marker; a prescriptive `Lane N` token; a priority-bearing deliverable with no `**GH:**` anchor. WARNS on a thin mesh (<8 rows), missing `milestone:`/`kind:`, or a `Sequencing:` judgment call. A path existing only after Phase 0 is exempted with a trailing `(NEW)` marker.

The same gate runs automatically as a `PreToolUse(Write)` hook (`hooks/scripts/seed_preflight_check.sh`, config `[seed].seed_gate = block | warn | off`) — a seed failing `SEED-GATE` cannot reach a spawn. Whether each line is genuinely runnable stays the planter's and `@critic`'s residual judgment.

## See also

- `agents/planter.md` — seed authorship
- `references/pipeline.md` — Stage Graph, Gates, CLOSE, Lane law
- `references/flock.md` — brief assembly, wrapper-grep gate
- `references/branching-model.md` — patch lifecycle
- `skills/adaptation/SKILL.md` — priors/lessons contract
- `skills/motivation/SKILL.md` — SOAK cadence
