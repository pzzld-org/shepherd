---
title: self-improvement
description: |
  The flock must not relearn the same failure twice. A HIGH/CRITICAL audit
  finding in sprint N is harvested into a durable lesson and injected into the
  briefs that author sprint N+1 — so the engineer and planter see the guard
  before they repeat the mistake. Bounded, graceful-empty, citation-measured.
introduced: v6.0.4
---

# Self-Improvement — harvest the close, inject the open

## Principle

A finding the auditors raised once is a lesson the flock paid for. If the next sprint's planning never sees it, the flock pays again. Self-improvement closes that gap **mechanically**: the costliest findings of each close become first-class lessons that the next plan and seed are handed, without operator annotation and without unbounded memory growth.

This is the `#95` companion to the adaptation loop's `#94` metrics path. Both live on the registry DB; see `doctrines/adaptation-loop.md` and `doctrines/sqlite-canonical-state.md`.

## The contract — four steps

```
harvest (close)  →  store (prior)  →  inject (open)  →  cite (measure)
 audit_findings     mem_entries        [DB-CONTEXT]      prior:<mem_id>
 HIGH/CRITICAL      (kind='prior')     engineer+planter   in plan/seed
```

### I. Harvest — at CLOSE-FINALIZE

`shctx adapt roll --sprint=<branch> …` (run once per close by the conductor / root shepherd) reads this sprint's HIGH/CRITICAL `audit_findings` and, for each distinct concern, upserts one lesson. Only HIGH/CRITICAL are harvested — info/low/medium findings stay in `audit_findings` for the record but are not promoted to priors (signal, not noise).

### II. Store — `mem_entries(kind='prior')`

One row per recurring concern, **deduped by title** so a concern that recurs across sprints yields a single prior, not one-per-occurrence:

- `title` = `prior: <concern>`
- `body`  = `[<severity>] sprint <branch>: <finding gist>` (single line)
- `tags`  = `[<concern>]` (JSON; the area the lesson guards)

Dedup-by-title is what keeps the store bounded — the load-bearing property. The `'prior'` kind was added to the `mem_entries.kind` CHECK in migration `0011`.

### III. Inject — at plant and engineer Phase-0

`shctx inject <role>` appends `shctx adapt priors --lessons --md` to the `[DB-CONTEXT]` block for the **engineer** and **planter** roles (omitted entirely when the store is empty — see graceful-empty below). The lessons therefore arrive in the exact briefs that author the next sprint:

- `/shepherd:plant` — the planter reads priors before writing seed guardrails.
- engineer Phase-0 mesh — the engineer reads priors as the sprint-patterns mesh row.

### IV. Cite — the measurement signal

A plan or seed that acted on a prior **cites its id** (`prior:<mem_id>`) in the relevant lane/guardrail rationale. Citation is how we prove the loop is consumed, not merely populated (acceptance #95: a HIGH finding from sprint N appears as a prior surfaced in sprint N+1's `[DB-CONTEXT]` and is cited). Absence of citations across several sprints with a non-empty store means the read protocol is being skipped.

## Bounded & graceful — the invariants

- **Bounded:** dedup-by-title caps priors at one-per-concern; only HIGH/CRITICAL harvested.
- **Bounded over long arcs (decay):** every recurrence refreshes a prior's last-seen (`updated_at`); an **unpinned** prior not re-seen across `SHCTX_ADAPT_DECAY_SPRINTS` sprint closes (default 6) is pruned on the next `roll`. So as concerns rotate across a multi-patch version arc the store self-cleans and stays bounded — stale lessons drop out, **pinned** lessons never do.
- **Graceful-empty:** an empty store makes every read emit nothing; plant and Phase-0 behave exactly as a cold start. Empty store == today's behavior.
- **Idempotent:** re-running a close's `roll` neither duplicates the metrics row nor re-harvests existing priors.

## What this is NOT

- **Not a replacement for issue tracking.** Chronic items still get GH issues + labels via `doctrines/carry-forward-refresh.md`; priors are planning *guidance*, not a ledger.
- **Not auto-applied.** A prior is surfaced to the engineer/planter, who weigh it — it does not silently mutate a plan.
- **Not a log.** Deduped lessons, not an audit trail; the full per-finding record stays in `audit_findings`.

## Cross-doctrine references

- `doctrines/adaptation-loop.md` — the metrics half (#94) and the registry overview; this doctrine is its harvest→inject half (#95)
- `doctrines/sqlite-canonical-state.md` — `audit_findings` + `mem_entries` are canonical DB state; `shctx adapt report` is the generated view
- `references/grading-rubric.md` — severity definitions that gate what gets harvested (HIGH/CRITICAL)
- `doctrines/agent-excellence.md` — "refuse the lazy path / no silent drift"; priors are how a lesson learned once is enforced forward
