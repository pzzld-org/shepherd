---
name: shepherd-context
slug: shepherd-context
version: 6.0.3
description: "Per-project SQLite registry backing /shepherd:ctx and the flock's Phase-0 fast-paths. Indexes code symbols, GitHub state, artifacts, memories, profiles, locks, and event logs."
metadata:
  triggers:
    - "/shepherd:ctx"
---

# /shepherd:ctx — Per-project Context Registry

You are reading the entry skill for `/shepherd:ctx`. The CLI lives at `${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/shctx`. The DB lives at `.shepherd/root.db` in the consumer project (or `.artifacts/root.db` for projects that opted into the legacy namespace via `init --artifacts`). Auto-detection prefers whichever directory already exists.

This skill is a quick reference. Operational detail lives in the sibling files (see "See also" below). When this file points at one, load it.

---

## Quick reference

- `shctx init [--artifacts]` — scaffold per-project namespace (`.shepherd/` by default; `--artifacts` opts into the legacy `.artifacts/`), create `root.db`, register host project (UUIDv7). Auto-detects an existing namespace dir if present.
- `shctx status` — row counts, refresh staleness, lock state, lint summary.
- `shctx refresh [--scope=symbols|github|artifacts|all]` — idempotent rebuild of cache zones.
- `shctx query <name> [--json|--md] [--key=val ...]` — run a named query from `queries/`.
- `shctx search <text> [--scope=symbols|artifacts|all] [--limit=N] [--md|--json]` *(v5.0.3)* — FTS5 full-text search over symbols + artifact content.
- `shctx inject <engineer|coder|auditor>` — emit a `[DB-CONTEXT]` block sized for that role.
- `shctx profile <list|show|enable|disable|sync>` — TOML profiles in `<namespace>/profiles/` ↔ `profiles_defs`.
- `shctx mem <add|search|list|pin|unpin>` — project memories (replaces external `remember` plugin).
- `shctx lock <show|acquire|release|reap>` — file lock at `<namespace>/shepherd.lock`.
- `shctx lint` — naming-convention check over the active namespace directory.
- `shctx migrate` — apply pending schema migrations from `schema/migrations/`.
- `shctx export <kind> [--out=path]` — markdown/JSON snapshot of a query or table.
- `shctx close-lane <lane-id> --sprint=<branch> [--issues=#a,#b] [--status=clean|partial|failed]` *(v5.0.3)* — record mid-sprint lane closure; auto-resolves carry-forward via `gh issue view --json state`; emits markdown patch for the ledger.
- `shctx worktree <list|gc|merge>` *(v5.0.3)* — worktree hygiene: list with age, prune stale `.claude/worktrees/agent-*` (`gc --older-than=<hours>`), cherry-pick + cleanup (`merge <agent-id> --strategy=theirs|prompt`).

All subcommands are project-scoped to the row in `projects` written by `init`.

---

## When to invoke

The conductor and the engineer both call into this skill via Bash. Direct invocations:

- **`shctx init`** — once per consumer-project bootstrap. Idempotent.
- **`shctx refresh --scope=all`** — at sprint open, per `[context].auto_refresh` in `shepherd.toml` (default `["on-sprint-open"]`).
- **`shctx query dedup-check --name=<symbol>`** — the conductor's DEDUP-GATE Layer 2 SQL fast-path (per `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/zero-duplicate-tolerance.md` + `doctrines/context-registry.md`). A hit pre-blocks dispatch citing `file_path:line`. A miss falls through to grep — grep remains the contract.
- **`shctx inject coder`** — emits a `[DB-CONTEXT]` block the engineer pastes into a coder brief's `[CONTEXT-INVENTORY]` section. See `examples/inject-coder.md`.
- **`shctx query open-issues --md`** — Phase 0 mesh row 1 fast-path (replaces an MCP/CLI hop).
- **`shctx query canonical-types --md`** — Phase 0 mesh row 12 fast-path (replaces hand-maintained markdown). *(v5.0.3: now defaults to `kind ∈ {struct, enum, trait, class, interface, type-alias}` — see `v_canonical_symbols` for the broader unfiltered view.)*
- **`shctx search "<text>"`** *(v5.0.3)* — FTS5 fast-path for natural-language queries ("which crate has the BookSnapshot type?", "did any close report mention the calibration cron?"). Queries the symbol index + artifact content.
- **`shctx close-lane <lane-id> --sprint=<branch> --issues=#…`** *(v5.0.3)* — conductor-side carry-forward auto-refresh after every wave-gate.
- **`shctx worktree gc`** *(v5.0.3)* — periodic stale-worktree pruning (recommended: end-of-day or end-of-sprint).
- **`shctx worktree merge <agent-id>`** *(v5.0.3)* — cherry-pick a coder's worktree HEAD onto the sprint branch + cleanup. Per `doctrines/conductor-cwd.md`, this is the conductor's preferred way to integrate a coder commit (no `cd` needed).

---

## Cache vs canonical

See `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/context-registry.md` for the full doctrine.

| Zone | Tables | Mode |
|---|---|---|
| **Cache** | `index_*`, `logs_events` (last 10K) | Rebuildable from source/MCP at any time. Safe to delete. |
| **Canonical** | `projects`, `sessions`, `profiles_defs`, `mem_entries`, `artifacts`, `locks_history`, `schema_versions` | Not recoverable elsewhere. Persistence required. |

The DB is gitignored by default. Treat it as a build artifact unless your team has a specific reason to commit it.

---

## Refresh contract

`shctx refresh` is idempotent and scope-bounded:

- `--scope=symbols` — re-extract code symbols (Rust via `cargo metadata` + `syn`; other languages via tree-sitter or skipped). Updates `index_symbols`, `index_concepts`.
- `--scope=github` — re-pull GitHub state via `gh`. Updates `index_issues`, `index_prs`, `index_releases`, `index_milestones`.
- `--scope=artifacts` — re-hash files in the active namespace matching configured kinds. Updates `artifacts`.
- `--scope=all` — runs all three sequentially.

Stale TTL lives in `[context.refresh]`. If `refreshed_at` exceeds `ttl_minutes`, downstream callers (engineer, conductor) re-refresh before reading. See `references/schema.md`.

---

## Failure modes

- `sqlite3` missing → install it (`brew install sqlite` / `apt install sqlite3`). Hard stop.
- `gh` missing → `refresh --scope=github` skips silently with a warning. Other scopes unaffected.
- `cargo` missing → `refresh --scope=symbols` skips Rust extraction with a warning.
- DB missing → run `shctx init`. Engineer/conductor fall back to markdown reads.
- Schema out of date → run `shctx migrate`. Required after every plugin upgrade.
- Lock held by stale session → `shctx lock reap` clears entries whose `acquired_at` exceeds `[context.lock].stale_after_minutes`.

---

## Naming conventions

Namespace paths follow strict patterns; `shctx lint` enforces them. See `references/naming-conventions.md`.

- **Date-only** (`YYYY-MM-DD.md`) — human-editable artifacts (journal entries).
- **Timestamped** (`YYYY-MM-DDTHH-MM-SS.*`) — machine-generated tmp/cache/log files in `tmp/` and `logs/`.

The plugin's `init` writes `<namespace>/CONVENTIONS.md` — the same table, mirrored into the consumer project for quick local reference.

---

## See also

- `references/schema.md` — full table-by-table reference, view definitions, JSON1 query patterns.
- `references/profiles.md` — profile model (modifier/extension/override), TOML format, sync semantics.
- `references/naming-conventions.md` — file naming rules (also copied as `<namespace>/CONVENTIONS.md` on init).
- `examples/inject-coder.md` — sample `[DB-CONTEXT]` block as it appears in a coder brief.
- `examples/profile-modifier.toml` — modifier profile example (skip critic for XS sprints).
- `examples/profile-extension.toml` — extension profile example (post-wave security scan).
- `examples/journal-entry.md` — sample `<namespace>/docs/journal/YYYY-MM-DD.md` layout.
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/context-registry.md` — doctrine: cache vs canonical, fall-back contract.
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/zero-duplicate-tolerance.md` — DEDUP-GATE Layer 2 SQL fast-path.
- `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` — `[context]`, `[context.refresh]`, `[context.lock]`, `[context.naming]` sections.
