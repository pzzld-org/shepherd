---
name: shepherd-context
slug: shepherd-context
version: 6.2.7
description: "Per-project SQLite registry backing /shepherd:ctx and the flock's Phase-0 fast-paths. Indexes code symbols, GitHub state, artifacts, memories, profiles, locks, event logs, and the tool toolkit."
metadata:
  triggers:
    - "/shepherd:ctx"
---

# /shepherd:ctx — Per-project Context Registry

You are reading the entry skill for `/shepherd:ctx`. The CLI lives at `${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/shctx`. The DB lives at `.shepherd/shepherd.db` in the consumer project (or `.artifacts/shepherd.db` for the legacy namespace). Legacy `root.db` is auto-detected for projects that predate v6.1.2. Auto-detection prefers whichever directory + filename already exists.

> **`shctx` is plugin-local and NEVER on `$PATH` (v6.1.8).** `command -v shctx` / `which shctx` / a bare `shctx …` returns **absent BY DESIGN** — that is *not* evidence of absence and must never be treated as such. Always invoke it by the absolute path `${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/shctx`. If `$CLAUDE_PLUGIN_ROOT` is unset in your shell (it does not always propagate into the Bash tool — notably on some remote/web launches), the SessionStart `session_open` hook prints the resolved absolute path at session start (`[context].announce_shctx_path = on` by default); you can also resolve it from the installed plugin dir (e.g. `~/.claude/plugins/shepherd/skills/context/scripts/shctx`). Reporting "shctx absent" from a `command -v` probe is the #1 false-negative — don't.

This skill is a quick reference. Operational detail lives in the sibling files (see "See also" below). When this file points at one, load it.

---

## Quick reference

- `shctx init [--artifacts]` — scaffold per-project namespace (`.shepherd/` by default; `--artifacts` opts into the legacy `.artifacts/`), create `shepherd.db` (legacy `root.db` honored), register host project (UUIDv7). Auto-detects an existing namespace dir if present.
- `shctx status` — row counts, refresh staleness, lock state, lint summary.
- `shctx refresh [--scope=symbols|shapes|github|artifacts|all]` — idempotent rebuild of cache zones (`shapes` indexes struct/enum field shapes for `dups`, v6.1.8).
- `shctx dups <scan|check|registry>` *(v6.1.8, #157)* — field-shape similar-struct detection: catches the renamed-shadow duplicate (same field shape, different name) that name-matching dedup is blind to. `scan` censuses + clusters; `check` is the PreToolUse/Phase-0 authoring gate; `registry` curates concept→canonical pins + the DO-NOT-MERGE allow-list. See `doctrines/shape-dedup.md`.
- `shctx query <name> [--json|--md] [--key=val ...]` — run a named query from `queries/`.
- `shctx search <text> [--scope=symbols|artifacts|all] [--limit=N] [--md|--json]` *(v5.0.3)* — FTS5 full-text search over symbols + artifact content.
- `shctx inject <engineer|coder|auditor>` — emit a `[DB-CONTEXT]` block sized for that role.
- `shctx profile <list|show|enable|disable|sync>` — TOML profiles in `<namespace>/profiles/` ↔ `profiles_defs`.
- `shctx mem <add|search|list|pin|unpin>` — project memories (replaces external `remember` plugin).
- `shctx toolkit <list|add|rm|pin|unpin|show|md|init|validate>` *(v6.1.2)* — the tool registry (`toolkit.json`, local ⊕ user-global). Commonly-used MCP/skill/plugin/CLI tools so a session never forgets a capability exists; surfaced at session start and injected as `[TOOLKIT]` in briefs.
- `shctx lock <show|acquire|release|reap>` — file lock at `<namespace>/shepherd.lock`.
- `shctx lint` — naming-convention check over the active namespace directory.
- `shctx migrate` — apply pending schema migrations from `schema/migrations/`.
- `shctx export <kind> [--out=path]` — markdown/JSON snapshot of a query or table.
- `shctx close-lane <lane-id> --sprint=<branch> [--issues=#a,#b] [--status=clean|partial|failed]` *(v5.0.3)* — record mid-sprint lane closure; auto-resolves carry-forward via `gh issue view --json state`; emits markdown patch for the ledger.
- `shctx worktree <list|gc|merge>` *(v5.0.3)* — worktree hygiene: list with age, prune stale `.claude/worktrees/agent-*` (`gc --older-than=<hours>`), cherry-pick + cleanup (`merge <agent-id> --strategy=theirs|prompt`).
- `shctx loop <init|native-cmd|status|record|close|list|focus>` *(v6.0.9; native-cmd + --self-paced v6.2.0)* — SQLite-backed Loop-Until-Done state. Backs `/shepherd:loop` and the Focus Loop runtime. Loop state is canonical (survives compaction). `init --task --max [--kind --agent --until --interval | --self-paced]` emits a `loop-id` of form `loop-YYYYMMDD-NNN`; `native-cmd --id [--command]` prints the exact native `/loop` invocation deterministically from the loop's stored pacing; `status --id`; `record --id --iteration --new_findings --summary`; `close --id --status`; `list [--active|--all]`. Sixth verb `focus <upsert|show> --sprint` reads/writes the focus record (objective, active_node, ready_set, obligations, invariants) from migration `0013_focus.sql`.
- `shctx config <init|claude-md|show|path|get>` — scaffold/inspect the project binding. `init` writes `.claude/shepherd.toml` from the bundled template (idempotent); `claude-md` *(v6.2.0)* materializes the portable operating doctrine into the repo's `CLAUDE.md` as a fenced, never-clobber managed block (`--force` re-syncs only the block); `get <key> [def]` is the uniform `cfg_get` read path.
- `shctx adapt <roll|reflect|priors|report|recommend>` — the adaptation loop. `roll --sprint --grade … [--wall-min --api]` writes one `sprint_metrics` row + harvests HIGH/CRITICAL findings into priors at CLOSE-FINALIZE (pass `--wall-min`/`--api` to power the cost trend + Check 8 sizing); `reflect --sprint --note` *(v6.2.0)* stores a one-line close reflection; `priors --metrics|--lessons` feeds dispatch sizing + brief injection; `report --trends` is the deterministic trend detector; `recommend` turns measured averages into a dispatch recommendation.
- `shctx eval <run|report|list>` *(v6.2.3)* — quality-score a LATENT agent output (a conductor reflection, a discovery report, a seed, …) against a rubric, judged by the **local Claude Code** via the `services/llm` contract (never a hosted API). `run --kind=K [--sprint=B] [--input-file|--input|-] [--threshold --model --record --json|--md]` builds the judge prompt from `services/eval/rubrics/<K>.rubric.json`, parses the per-dimension scores, and computes a deterministic weighted overall vs the threshold; `--record` writes `eval_runs` (migration `0018`, surfaced by `shctx dash` + `eval report|list`). The scores are latent; the overall + verdict + DB row are deterministic. The pure judge lives in `services/eval`; this is the registry-side glue. See `services/eval/README.md`.

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
| **Canonical (core)** | `projects`, `sessions`, `profiles_defs`, `mem_entries`, `artifacts`, `locks_history`, `schema_versions` | Not recoverable elsewhere. Persistence required. |
| **Canonical (v5.1.7+ operational)** | `teammates`, `heartbeats`, `mailbox`, `escalations`, `deliverables`, `discovery_findings`, `audit_findings` | Operational state added by migration `0007_canonical_state.sql`. Not recoverable elsewhere. Persistence required. |
| **Canonical (v6.0.9 loop/focus)** | `loops`, `loop_iterations`, `focus` | Loop state and focus record added by migrations `0012_loop_state.sql` + `0013_focus.sql`. Survive compaction natively. Persistence required. |

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
