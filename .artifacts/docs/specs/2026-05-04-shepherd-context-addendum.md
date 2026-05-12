# Shepherd v5.0.0 Context Registry — Addendum (operator follow-up)

| Field | Value |
|---|---|
| Spec ID | `2026-05-04-shepherd-context-addendum` |
| Status | **Approved for implementation** |
| Date | 2026-05-04 |
| Parent | `2026-05-04-shepherd-context-design.md` (commit `b7b1e7d`) |

This addendum captures four scope expansions raised after the parent spec was approved. Where the parent spec is silent, this addendum binds.

## A1. Engineer brief: seed → brainstorming → writing-plans is mandatory

The engineer's plan-authorship pipeline already names `superpowers:brainstorming` + `superpowers:writing-plans`. That naming is **promoted from "load these skills" to a hard runtime check**:

- The engineer brief MUST start with: read seed → invoke `superpowers:brainstorming` → invoke `superpowers:writing-plans` → emit `## Stage Graph` per `pipeline.md`.
- Skipping either skill is a process violation; auditor `completeness` flags it. Plan-grade caps at C+.
- The output is a drift-resistant, parallel-optimized plan with binding Stage Graph (already in v4.2.0 contract; v5.0.0 sharpens enforcement).

## A2. Per-language code-style generation (`shctx style`)

Every consumer project gets per-language style files at `.artifacts/styles/{lang}.md`. These are **operator-editable, project-local, and tracked in git**.

- Bundled defaults ship at `plugins/shepherd/skills/context/styles/{lang}.md` for: `rust`, `python`, `typescript`, `go`, `shell`, `sql`. Defaults reference (and expand on) the existing `fl03-skills/skills/code-style/` ledger.
- New subcommand `shctx style <init|show|edit|list>`:
  - `init <lang>` — copy plugin default to `.artifacts/styles/<lang>.md` (idempotent — no overwrite if exists)
  - `init --all` — bootstrap all six languages
  - `show <lang>` — `cat .artifacts/styles/<lang>.md`
  - `list` — `ls .artifacts/styles/`
  - `edit <lang>` — open `$EDITOR` on the file
- Schema migration `0002_styles.sql` adds:
  ```sql
  CREATE TABLE styles (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    language    TEXT NOT NULL,
    source_path TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    UNIQUE(project_id, language)
  );
  ```
  Note: this re-numbers the deferred sprints schema to `0003_sprints.sql` (milestone d).

**Conductor auto-attachment:** the conductor's mechanical `[SKILLS]` computation (per `doctrines/zero-duplicate-tolerance.md`) gains a step — for every detected language in `[FILE-SCOPE]`, prepend the project-local `.artifacts/styles/{lang}.md` content as a `[CODE-STYLE]` block in the coder brief. The bundled `code-style` skill remains the universal ledger; `[CODE-STYLE]` is the project-specific override layer.

## A3. Flock membership stays closed at five

The doctrine `flock.md` says the flock is closed at five (engineer, critic, coder, auditor, worker). Adding members is a major contract change beyond v5.0.0 scope. Instead:

- **Worker dispatch patterns are codified** in a new doctrine `doctrines/worker-patterns.md`.
- **Conductor offloads to worker** for: research summaries (web/MCP scraping), monitoring (deploy logs, build watches), MCP batch operations (issue triage, schema queries), file organization, branch cleanup, data analysis with bounded deliverable.
- **The conductor explicitly does NOT inline these tasks** when they would consume > ~1000 tokens of context for an IO-bound operation.

The doctrine is the contract; brief templates live in `references/agent-briefs.md` § @worker (already there — extended in this work).

## A4. Engineer-side seed enforcement

A new auditor sub-check (the `completeness` concern) verifies:

1. The engineer's plan cites the seed at top.
2. The plan's `## Stage Graph` parses cleanly per `pipeline.md`.
3. Every coder lane brief has `[CODE-STYLE]` populated when its `[FILE-SCOPE]` contains source files.
4. Every coder lane brief has `[DB-CONTEXT]` populated (optional in milestone c — auditor warns; required in d — auditor flags).

Violations: process-violation finding, plan-grade caps at C+ for first violation, F for repeat.

## Phasing impact

All four additions land in milestone (c) (`v5.0.0-dev.0..N`). No change to milestone (d) scope.

## Acceptance addendum (extends parent §18)

11. `shctx style init rust` produces `.artifacts/styles/rust.md` from the bundled default.
12. `shctx style init --all` produces all six language files.
13. `migrate` applies `0002_styles.sql` cleanly on a v5.0.0 baseline DB.
14. New doctrine `worker-patterns.md` exists and is referenced from `flock.md` § @worker.
15. Engineer brief enforces seed → brainstorming → writing-plans (auditor verifies).
16. Conductor `[SKILLS]` computation prepends `[CODE-STYLE]` block from `.artifacts/styles/<lang>.md` for every coder lane that touches a matched language.
