---
title: adaptation-loop
description: |
  SQLite-canonical self-improvement loop. Each sprint close writes one
  sprint_metrics row and harvests HIGH/CRITICAL audit_findings into
  mem_entries(kind='prior'); the engineer, planter, and spawn dispatcher read
  those measured averages and lessons back. Requires no operator annotation and
  — as of v6.0.4 — mechanically shapes dispatch sizing, not just plan content.
introduced: v5.0.6
---

# Adaptation Loop — Sprint Pattern Registry (SQLite-canonical)

> **v6.0.4 (#94/#95):** re-grounded from an advisory markdown file
> (`{paths.ctx}/sprint-patterns.md`) onto the registry DB. The markdown file is
> retired; its human-readable view is now `shctx adapt report`. See
> `doctrines/sqlite-canonical-state.md` and `doctrines/self-improvement.md`.

## Why this exists

The shepherd flock has no cross-session memory by default. Each sprint starts from the seed and the prior handoff — one sprint old. Over a patch cycle, recurring finding types, persistent halt codes, grade-cap patterns, and real timing/effort costs accumulate with no mechanism to surface them to planning.

The adaptation loop gives the system **sprint-level memory without operator annotation**. At each close the conductor records what the sprint cost and what it taught; at each open the engineer, planter, and spawn dispatcher read those facts back. The registry is the project DB (`${SHEPHERD_WORKDIR}/root.db` — default `.shepherd/root.db`, or `.artifacts/root.db` for legacy projects; auto-detected) — the canonical store per `doctrines/sqlite-canonical-state.md` — so the signal survives sessions, is queryable, and is bounded by construction.

---

## I. The registry — three DB tables, one view

| Store | Written by | Holds |
|---|---|---|
| `sprint_metrics` (one row / sprint, `UNIQUE(project_id,sprint_branch)`) | `shctx adapt roll` at CLOSE-FINALIZE | grade, size, lane/wave counts, LOC delta, **wall_minutes**, **api_calls**, findings summary |
| `audit_findings` | `shctx audit insert` (auditor, per `doctrines/sqlite-canonical-state.md`) | per-finding concern / severity / hypothesis / finding — the **harvest source** |
| `mem_entries(kind='prior')` | `shctx adapt roll` (harvested from HIGH/CRITICAL `audit_findings`) | one deduped lesson per recurring concern; tags = concern name(s) |

The human-readable registry — the old `sprint-patterns.md` — is now a **materialized view**: `shctx adapt report [--md|--json]`. Never hand-edit the tables; never re-introduce a markdown registry file.

---

## II. Write protocol — `shctx adapt roll` at CLOSE-FINALIZE

The **conductor** (solo) / **root shepherd** (spawn) runs exactly one `roll` per sprint close, after CLOSE-SWARM and before PAUSE:

```bash
shctx adapt roll --sprint=<branch> --grade=<G> [--size=XS|S|M|L|XL] \
                 [--lanes=N] [--waves=N] [--loc-add=N] [--loc-del=N] \
                 [--wall-min=R] [--api=N]
```

`roll` does two things atomically:
1. **Metrics** — `INSERT OR REPLACE` one `sprint_metrics` row (idempotent on the sprint branch; re-running a close is safe).
2. **Harvest** — for each HIGH/CRITICAL `audit_findings` row of this sprint, upsert a `mem_entries(kind='prior')` lesson titled `prior: <concern>`, deduped by title so growth stays bounded (a recurring concern yields one prior, not one-per-occurrence). See `doctrines/self-improvement.md`.

This **supersedes** the v5.x step where the completeness auditor hand-appended a markdown entry. The auditor's job is now only to **file findings** via `shctx audit insert`; the conductor's `roll` turns them into durable priors. If `roll` fails (DB locked, etc.), note it in the close report under anomalies and continue — do **not** block CLOSE-FINALIZE.

---

## III. Read protocol — engineer at mesh time

**When:** Phase 0 mesh, as the sprint-patterns mesh row.

```bash
shctx adapt priors --metrics --md   # measured averages
shctx adapt priors --lessons --md   # recent prior lessons (cap 10), each with its id
```

Empty store ⇒ both emit nothing; the engineer notes "no pattern history yet — first adaptation cycle lands at this close" and proceeds (unchanged from a cold start).

**What to act on:**

| Signal | Action |
|---|---|
| A `prior:` lesson names a concern relevant to this sprint's scope | Add or strengthen a coder lane / `[ACCEPTANCE]` criterion targeting it. **Cite the prior id** (`prior:<mem_id>`) in the lane rationale — that citation is the measurement signal (§VII). |
| `--metrics` shows real averages (`n≥1`) | Size lanes/waves against measured `avg_lane_count` and `avg_sprint_minutes`, not gut feel — see §V. |
| Same concern recurs across multiple priors | Classify as **systemic risk** in the mesh summary; give it a dedicated lane. |

---

## IV. Read protocol — planter at seed time

**When:** `/shepherd:plant`, reading context before writing seed content.

```bash
shctx adapt priors --lessons --md
```

| Signal | Seed action |
|---|---|
| Systemic-risk prior (recurring HIGH/CRITICAL concern) | Add an explicit mitigation lane; name the concern + mitigation. **Cite the prior id** in the seed's guardrails section. |
| Chronic carry-forward (GH# unclosed across patches, per `carry-forward-refresh.md`) | MUST-LAND CRITICAL lane in the earliest sprint slot. |
| Clean store / no relevant prior | Seed's "Priors / lessons carried forward" section reads "none (first cycle)". |

---

## V. Dispatch sizing — the loop now changes dispatch (v6.0.4)

Before v6.0.4 the loop only informed plan *content*. It now **mechanically shapes dispatch sizing**:

- **Spawn Check 8** (`commands/spawn.md`) reads `shctx adapt priors --metrics`. With `n>0` it uses measured `avg_sprint_minutes` / `avg_api_per_sprint` / `avg_lane_count`, labeled `(from priors: N sprints)`. With an empty store it falls back to the static defaults, labeled `(defaults — no priors yet)`. See `doctrines/scope-scale-workload.md`.
- **Engineer lane guidance** sizes wave/lane counts against the same measured averages.

This is the one place the adaptation loop is **not** advisory: a second sprint's estimate provably differs from the cold-start default, traceable to `sprint_metrics` (acceptance #94).

---

## VI. Conductor trend surface at PAUSE — mechanized

After CLOSE-FINALIZE, before PAUSE, the conductor runs one command — it does **not** eyeball the report:

```bash
shctx adapt report --trends   # deterministic; emits nothing on a healthy streak
```

`--trends` computes the three §VI signals in pure SQL over the **last 3 recorded sprints** and prints an informational **TREND ALERT** block (it does **not** block PAUSE) when any fires:

- a HIGH/CRITICAL `audit_findings` concern recurring across **all** of the last 3 sprints,
- a sprint **grade trending strictly downward** (e.g. A → B → C) across those 3 sprints,
- **cost rising sharply** — newest `wall_minutes` or `api_calls` ≥ 1.5× the oldest of the last 3.

Insufficient history (< 3 closes) ⇒ it emits nothing (graceful), exactly like a cold start. Because the detection is mechanized, the conductor surfaces the block verbatim instead of re-deriving the trend from a table read — no judgement call, no skipped scan on exhausted context.

### VI.b — `shctx adapt recommend` and prior decay

Two companion surfaces keep the loop actionable and bounded:

- **`shctx adapt recommend [--md|--json]`** turns the measured `sprint_metrics` averages + recurring priors into a concrete dispatch **RECOMMENDATION** — a suggested lane count, a t-shirt size band, and watch-concerns. Empty store ⇒ `no history yet, use defaults` (graceful). The engineer `[DB-CONTEXT]` injects `recommend --md` (omit-when-empty) so the next plan opens with measured sizing guidance, not gut feel.
- **Prior decay** runs inside `shctx adapt roll`. Every recurring concern refreshes its prior's `updated_at` (last-seen); any **unpinned** prior not re-seen across `SHCTX_ADAPT_DECAY_SPRINTS` sprint closes (default **6**) is pruned. **Pinned priors are never pruned.** Decay is what keeps the store bounded over a long version arc even as concerns rotate — see `doctrines/self-improvement.md` "Bounded & graceful".

---

## VII. The measurement signal

The loop is only working if priors are *consumed*, not merely *written*. A plan or seed that acted on a prior **cites it** in its rationale — `prior:<mem_id>` (a harvested lesson) or `metrics(N sprints)` (a sizing decision). Absence of any citation across several sprints with a non-empty store is itself a signal that the read protocol is being skipped.

---

## VIII. Feedback classification — project-specific vs framework-generic

When the conductor saves a `feedback_*.md` memory mid-sprint (`shctx mem add`), classify it: **project-specific** stays in project memory; **framework-generic** ("every Rust/Python/Go shepherd project will hit this…") is additionally flagged in the close report as a candidate for shepherd doctrine promotion. The conductor never pushes doctrine changes to the shepherd repo — it only flags the candidate.

---

## IX. What the adaptation loop does NOT do

- **Does not override operator decisions.** Trend alerts are recommendations.
- **Does not bloat the registry.** One `sprint_metrics` row per sprint (idempotent); priors deduped by concern. Bounded by construction.
- **Does not create labels.** Chronic labeling stays with `doctrines/carry-forward-refresh.md`; the loop surfaces candidates.
- **Does not break a cold start.** Empty store ⇒ identical to today's first-sprint behavior; every read is graceful-empty.

> Changed in v6.0.4: it **does** now change dispatch *sizing* (§V) — mechanically, via Check 8 and lane guidance. That is the deliberate exception to the old "does not change dispatch" rule.

---

## X. Cross-doctrine references

- `doctrines/self-improvement.md` — the harvest→inject contract (audit_findings → priors → briefs); companion to this doctrine
- `doctrines/sqlite-canonical-state.md` — why the registry is DB-canonical and the markdown file is a generated view
- `doctrines/scope-scale-workload.md` — spawn `--scope` sizing; Check 8 consumes `shctx adapt priors --metrics`
- `references/grading-rubric.md` — the grade fed to `shctx adapt roll --grade`
- `doctrines/carry-forward-refresh.md` — chronic-label authority; the loop surfaces candidates, this applies labels
- `doctrines/agent-excellence.md` — lessons feed forward so the flock does not relearn the same failure
