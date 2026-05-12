# Context registry — single queryable source of context

The shepherd context registry (`.shepherd/root.db` by default; `.artifacts/root.db` for projects on the legacy namespace — the `shctx` CLI auto-detects which is in use) is the per-project SQLite store that backs `/shepherd:ctx`. It is the **single queryable source of context** for the flock — code symbols, GitHub issues/PRs/releases/milestones, project memories, profiles, lock history, sprint metadata (in milestone d), and an event log.

## Cache vs canonical zones

| Zone | Tables | Mode |
|---|---|---|
| **Cache** (derived) | `index_*`, `logs_events` (last 10K) | Rebuildable from source/MCP at any time. Safe to delete. |
| **Canonical** | `projects`, `sessions`, `profiles_defs`, `mem_entries`, `artifacts`, `locks_history`, `schema_versions`, `sprints_*` (milestone d) | Not recoverable elsewhere. Persistence required. |

The DB is **gitignored by default**. Consumers may opt to commit it; for most projects, treat it as a build artifact.

## When to read the DB

- **Engineer Phase 0 mesh row 1** (open-issue ledger): `shctx query open-issues --md` is the fast-path.
- **Engineer Phase 0 mesh row 12** (workspace knowledge silo): `shctx query canonical-types --md` replaces the markdown read.
- **Conductor DEDUP-GATE Layer 2** (per `zero-duplicate-tolerance.md`): `shctx query dedup-check --name=<symbol>` is the SQL pre-check before the slower per-lane grep. Grep remains source of truth.
- **Coder briefs** (milestone c, optional): engineer populates `[DB-CONTEXT]` via `shctx inject coder`. Becomes mandatory in milestone d.
- **Auditor close-time checks**: `shctx query open-issues`, `drift-risk`, plus (in milestone d) `sprints_*` queries.

## When to refresh

- At sprint open, per `[context].auto_refresh` (default `["on-sprint-open"]`).
- After any commit that adds new public types (refresh `--scope=symbols`).
- At engineer dispatch time if `index_issues.refreshed_at` older than `[context.refresh].ttl_minutes`.

## Fall-back contract (milestone c)

If the DB is absent, the flock falls back to markdown reads. Behavior is unchanged from v4.x. The DB is **optional in milestone c**, **mandatory in milestone d**.

## Anti-patterns

- **"The DB row says X exists, so I'll skip the grep."** Wrong — DB is a cache; grep remains the contract for DEDUP-GATE Layer 2. SQL is the fast-path, not the gate.
- **"I'll edit `canonical-types.md` by hand."** OK in milestone c. In milestone d, hand edits are flagged as drift; the file becomes generated.
- **"I'll commit the DB to the repo."** Allowed; not recommended unless your team has a specific reason. Default posture is gitignored.
- **"I don't need to call `shctx migrate` — schema is fine."** Wrong on every plugin upgrade. Run `shctx migrate` after pulling new shepherd versions.

## See also

- `pipeline.md` §II — DEDUP-GATE node.
- `doctrines/zero-duplicate-tolerance.md` — Layer 1/2/3 model.
- `${CLAUDE_PLUGIN_ROOT}/skills/context/SKILL.md` — CLI quick reference.
- `<namespace>/docs/specs/2026-05-04-shepherd-context-design.md` — full design spec (`<namespace>` is `.shepherd/` by default, `.artifacts/` for legacy opt-in projects).
