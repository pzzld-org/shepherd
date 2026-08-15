# v6.0.3 — self-improvement + adaptability loop closure (#94 / #95)

- **Branch:** `v6.0.3`  ·  **Scope:** minor-feature depth over existing surfaces (slim wiring, not a new engine)
- **Design:** Option A — new slim `shctx adapt` over a new `sprint_metrics` table + reuse `mem_entries` for lesson priors. File-based `insights` store untouched.
- **Principle:** SQLite-canonical (`sqlite-canonical-state.md`), bounded, graceful first-run (empty store == today's behavior).

## Verified facts (build on these)

- `audit_findings` table (schema 0007) IS the harvest source — populated by `shctx audit insert` (one row/finding, from `agents/auditor.md`). Columns: project_id, sprint_branch, concern, severity(info/low/medium/high/critical), finding, gh_issue, created_at.
- `mem_entries` (via `cmd_mem.sh`) is the prior store: (id, project_id, kind, title, body, tags[json], pinned, created_at, updated_at). `shctx mem add --kind= --title= --body= --tags=`.
- Migrations: `cmd_migrate.sh` applies `schema/migrations/[0-9]{4}_*.sql` ascending, records `schema_versions`. Next free number = **0009**.
- Dispatcher `skills/context/scripts/shctx`: add `adapt` to the `case` allow-list (line ~97) + a usage stanza. `script_for` auto-resolves `cmd_adapt.sh`.
- `_lib.sh` helpers: `shctx_sql`, `shctx_project_id`, `shctx_now`, `shctx_uuid7`, `shctx_skill_root`, `shctx_artifacts_root`.
- `cmd_inject.sh` emits the `[DB-CONTEXT]` block per role — the inject seam for priors into engineer/planter briefs.
- Spawn Check 8 (`commands/spawn.md:304`) currently: static `avg_sprint_minutes=90, avg_api_per_sprint=200`, "uses `{paths.ctx}/sprint-patterns.md` averages if present."

## PINNED vocabulary (copy verbatim everywhere)

- Table: **`sprint_metrics`** · migration **`0009_sprint_metrics.sql`** · schema_version **9**
- Command: **`shctx adapt roll`** (write @ CLOSE-FINALIZE) · **`shctx adapt priors`** (read @ open) · **`shctx adapt report`** (view)
- Memory prior: `mem_entries.kind = `**`prior`** · tags = concern name(s) + optional file-area
- Read flags: `shctx adapt priors --metrics` (numeric averages) · `--lessons` (prior mem_entries) · `--all` (default) · `--json|--md`
- Measurement signal: a plan/seed that consumed a prior cites its id — `prior:<mem_id>` or `metrics(N sprints)` — in its rationale.

---

## LAYER 1 — foundation (executable; author + verify by running)

### F1. `skills/context/schema/migrations/0009_sprint_metrics.sql` (NEW)
```sql
-- shepherd v6.0.3 — adaptation metrics priors (#94). One row per sprint close.
BEGIN;
CREATE TABLE sprint_metrics (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sprint_branch TEXT NOT NULL,
  grade         TEXT,
  sprint_size   TEXT CHECK(sprint_size IS NULL OR sprint_size IN ('XS','S','M','L','XL')),
  lane_count    INTEGER,
  wave_count    INTEGER,
  loc_add       INTEGER,
  loc_del       INTEGER,
  wall_minutes  REAL,
  api_calls     INTEGER,
  findings_json TEXT CHECK(findings_json IS NULL OR json_valid(findings_json)),
  created_at    INTEGER NOT NULL,
  UNIQUE(project_id, sprint_branch)
);
CREATE INDEX idx_sprint_metrics_project ON sprint_metrics(project_id, created_at DESC);

CREATE VIEW v_sprint_metrics_avg AS
  SELECT project_id,
         COUNT(*)            AS n,
         AVG(wall_minutes)   AS avg_wall_minutes,
         AVG(api_calls)      AS avg_api_calls,
         AVG(lane_count)     AS avg_lane_count,
         AVG(loc_add+loc_del) AS avg_loc_delta
  FROM sprint_metrics GROUP BY project_id;

INSERT INTO schema_versions VALUES (9, strftime('%s','now')*1000, 'sprint_metrics-0009');
COMMIT;
```
(Confirm `projects` FK + `schema_versions` insert shape match 0007/0008 conventions when authoring.)

### F2. `skills/context/scripts/cmd_adapt.sh` (NEW)
Subverbs (mirror `cmd_mem.sh`/`cmd_insights.sh` style; use `_lib.sh` helpers; `set -eu -o pipefail`):

- **`roll --sprint=<branch> [--grade= --size= --lanes= --waves= --loc-add= --loc-del= --wall-min= --api=]`**
  1. `INSERT OR REPLACE INTO sprint_metrics (...)` for the sprint (idempotent on UNIQUE(project,sprint_branch)).
  2. Harvest: query `audit_findings` for this sprint where `severity IN ('high','critical')`; for each distinct (concern[,file-area]), upsert a `mem_entries` row `kind='prior'`, `title="prior: <concern> — guard <area>"`, `body=<short lesson incl. sprint + finding gist>`, `tags=json([concern,...])`. **Dedupe**: skip if an identical-title `kind='prior'` already exists (bounded growth).
  3. Print a one-line summary: `adapt roll: sprint_metrics row + K prior(s) harvested`.
- **`priors [--metrics|--lessons|--all] [--json|--md]`** (read; graceful when empty)
  - `--metrics`: select from `v_sprint_metrics_avg` for the project; emit `avg_sprint_minutes`, `avg_api_per_sprint`, `avg_lane_count`, sample `n`. If `n=0` → emit nothing (caller falls back to static defaults).
  - `--lessons`: select recent `mem_entries WHERE kind='prior'` (cap ~10), emit as bullet priors with id.
  - `--all` (default): both. `--md` for brief injection, `--json` for tooling.
- **`report [--md]`**: render the SQLite-canonical replacement for `sprint-patterns.md` (the materialized view per `sqlite-canonical-state.md`).

### F3. Register in `skills/context/scripts/shctx`
- Add `adapt` to the `case` allow-list on line ~97.
- Add a usage stanza under "Subcommands": `adapt <roll|priors|report> [args]  (v6.0.3 #94/#95) — metrics→dispatch + lesson priors`.

### F4. `skills/context/tests/test_cmd_adapt.sh` (NEW)
Seed a temp DB: insert a couple `audit_findings` (high) + run `shctx adapt roll --sprint=test --grade=B --lanes=4 --wall-min=70 --api=150`; assert a `sprint_metrics` row exists, `v_sprint_metrics_avg.n=1`, and `≥1 mem_entries kind='prior'`; run `shctx adapt priors --metrics --json` and assert avg fields present. Follow the `tests/test_cmd_*.sh` harness pattern.

**Verify L1:** `bash skills/context/scripts/cmd_migrate.sh` (or `shctx migrate`) applies 0009; `shctx adapt roll/priors` smoke; `bash skills/context/tests/run.sh` green.

---

## LAYER 2 — wiring (coder fan-out, file-disjoint; verbatim pinned names)

- **`skills/context/scripts/cmd_inject.sh`** — for roles `engineer` + `planter` (and conductor INTRO), append the output of `shctx adapt priors --lessons --md` to the `[DB-CONTEXT]` block (guard: omit section if empty).
- **`commands/spawn.md` Check 8** — replace static fallback wording: read `shctx adapt priors --metrics`; if `n>0` use real `avg_sprint_minutes`/`avg_api_per_sprint`/`avg_lane_count` and label `(from priors: N sprints)`; else the existing static defaults labeled `(defaults — no priors yet)`.
- **`agents/engineer.md` + `skills/shepherd/agents/engineer.reference.md`** — Phase-0 mesh: the adaptation row consumes `[DB-CONTEXT]` priors (lessons) + metrics; require the plan rationale to **cite the prior id** when a prior shaped a lane/acceptance (the measurement signal). (Also reconcile the row-10 vs row-11 numbering drift noted in passover.)
- **`agents/planter.md` + `commands/plant.md`** — seed authorship reads priors (lessons) and cites them in the seed's guardrails section.
- **`skills/shepherd/references/seed-template.md`** — add a `## Priors / lessons carried forward` section (lists prior ids + the guard each implies; "none (first cycle)" when empty).

## LAYER 3 — doctrine (coder fan-out, file-disjoint)

- **`skills/shepherd/doctrines/adaptation-loop.md`** — REWRITE from advisory-markdown to **SQLite-canonical**: registry is `sprint_metrics` + `audit_findings` + `mem_entries(kind=prior)`; the markdown `sprint-patterns.md` becomes the `shctx adapt report` view; write protocol = `shctx adapt roll` at CLOSE-FINALIZE (supersedes the completeness-auditor markdown append); read protocols (engineer/planter/spawn) cite `shctx adapt priors`. Replace §VI "Does not change dispatch rules" — it now **does**, mechanically, via Check 8 + lane guidance. Keep graceful/bounded notes.
- **`skills/shepherd/doctrines/self-improvement.md`** (NEW) — the harvest→inject contract: close-swarm `audit_findings` → `mem_entries(prior)` at close; inject at plant + engineer Phase-0; measurement (prior id cited). Cross-ref `adaptation-loop.md`, `grading-rubric.md`, `sqlite-canonical-state.md`.
- **`skills/shepherd/doctrines/README.md`** — index `self-improvement.md`.
- **`skills/shepherd/doctrines/agent-excellence.md`** — reference `self-improvement.md` (lessons feed forward).

## Harvest trigger (CLOSE-FINALIZE)

`agents/conductor.md` CLOSE-FINALIZE sequence + `agents/shepherd.md` close path call `shctx adapt roll --sprint=<branch> --grade=<G> --lanes=<L> --wall-min=<M> --api=<A> [--loc-* --size --waves]` once per sprint close, BEFORE PAUSE. The completeness auditor's markdown-append step in `adaptation-loop.md §II` is replaced by this call.

## Acceptance (the issues' bar)

- Second sprint's Check-8 estimate provably differs from static defaults, traceable to `sprint_metrics` (`shctx adapt priors --metrics` shows n≥1). [#94]
- A HIGH `audit_findings` from sprint N appears as a `mem_entries(prior)` and is surfaced in sprint N+1's `[DB-CONTEXT]`, cited in the plan/seed. [#95]
- `bash skills/context/tests/run.sh` green incl. new `test_cmd_adapt.sh`. Empty store ⇒ unchanged behavior. `adaptation-loop.md` is SQLite-canonical; `self-improvement.md` indexed.

## Build order

L1 (author + verify by running) → fold passover findings → L2 + L3 coder fan-out (file-disjoint, verbatim pinned names) → run shctx tests → commit + push to v6.0.3.
