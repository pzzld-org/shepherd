---
name: shepherd-context
slug: shepherd-context
version: 6.3.0
description: "Per-project SQLite registry backing /shepherd:ctx — symbols, GitHub state, dedup, telemetry, locks. Use when reading or writing project context state."
metadata:
  triggers:
    - "/shepherd:ctx"
---

# /shepherd:ctx — Per-project Context Registry

The CLI lives at `${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/shctx`. The DB lives at `.shepherd/shepherd.db` (`.artifacts/shepherd.db`/`root.db` legacy, auto-detected), preferring whichever exists.

`shctx` is plugin-local and is NEVER on `$PATH`. A bare `shctx …` / `command -v shctx` returns absent BY DESIGN — always invoke the absolute path above. Reporting "shctx absent" from a `command -v` probe is the #1 false-negative — never do it. When `$CLAUDE_PLUGIN_ROOT` doesn't propagate (remote/web launches), `session_open` prints the resolved path at SessionStart (`[context].announce_shctx_path`, default `on`); fallback: the installed plugin dir, e.g. `~/.claude/plugins/shepherd/skills/context/scripts/shctx`.

Quick reference only — detail lives in the sibling `references/` files.

---

## Quick reference

- `init [--artifacts]` — scaffold namespace + DB, register project.
- `status` — row counts, refresh staleness, lock state.
- `refresh [--scope=symbols|shapes|github|artifacts|all]` — idempotent cache rebuild.
- `dups <scan|check|registry>` — field-shape duplicate detection. See §Dedup.
- `query <name> [--json|--md] [--key=val …]` — named query; `open-issues --md`/`canonical-types --md` are the Phase-0 mesh row-1/row-12 fast-paths (each replaces a markdown/MCP read), `dedup-check` feeds DEDUP-GATE.
- `search <text> [--scope=…] [--limit=N]` — FTS5 full-text search.
- `inject <engineer|coder|auditor>` — emit `[DB-CONTEXT]`.
- `mem <add|search|list|pin|unpin>` — memories.
- `toolkit <list|add|rm|pin|unpin|show|md|init|validate>` — tool-memory registry (`toolkit.json`).
- `lock <show|acquire|release|reap>` — file lock at `<namespace>/shepherd.lock`.
- `lint` / `migrate` / `export <kind> [--out=path]`.
- `close-lane <id> --sprint=<branch> […]` — mid-sprint closure.
- `worktree <list|gc|merge <agent-id>>` — manage `agent-*` worktrees; `merge` is the conductor's preferred no-`cd` way to integrate a coder commit.
- `loop <init|native-cmd|status|record|close|list|focus>` — Loop-Until-Done state.
- `config <init|claude-md|show|path|get>` — scaffold/inspect `shepherd.toml`.
- `adapt <roll|reflect|priors|report|recommend>` — adaptation loop.
- `eval <run|report|list>` — quality-score output via local Claude Code, never hosted.
- `doctor` — six-section preflight. See §Doctor.
- `prune` — reclaim accreted workdir + registry state. See §Workdir hygiene.

All subcommands are project-scoped to the row `init` writes in `projects`.

---

## Canonical state model

`<namespace>/shepherd.db` (gitignored by default) is canonical for operational/ephemeral state; the filesystem covers human-authored durable artifacts; markdown reports are views over rows via `shctx report <kind>` — never the reverse.

| Zone | Contents | Mode |
|---|---|---|
| Cache | `index_*`, `logs_events` (last 10K) | Rebuildable via `shctx refresh`; safe to delete. |
| Canonical — core | `projects`, `sessions`, `profiles_defs`, `mem_entries`, `artifacts`, `locks_history`, `schema_versions` | Not recoverable elsewhere. |
| Canonical — operational | `teammates`, `heartbeats`, `mailbox`, `escalations`, `deliverables`, `discovery_findings`, `audit_findings` | Row-canonical; migration `0007_canonical_state.sql`. |
| Canonical — loop/focus | `loops`, `loop_iterations`, `focus` | Migrations `0012_loop_state.sql` + `0013_focus.sql`. |
| File-canonical | `CLAUDE.md`, `agents/`, `commands/`, `skills/**/*.md`, `docs/{specs,plans,seeds}/`, `CHANGELOG.md`, `README.md`, `schema/*.sql` | Version-controlled, human-edited; DB never authoritative. |
| Disposable | Audit/discovery/close reports, status pages (`shctx report <kind>`) | Re-rendered on demand; may cache under `<ns>/cache/` (gitignored). |

Rules: a new operational-state kind MUST land via a schema migration + `cmd_<sub>.sh`, NEVER an ad hoc file path. Agents MUST NOT write a markdown report as canonical output — verify a write landed by querying the row directly, NEVER by re-reading a rendered view. Coordinate concurrent writers with SQLite WAL + transactions, NEVER a markdown lock file.

---

## Dedup

Name-keyed dedup (`index_symbols`, `dedup-check.sql`) catches a reused identifier only — blind to a type restated under a new name; `query dedup-check --name=<symbol>` is its conductor-facing Layer-2 SQL fast-path (a hit pre-blocks citing `file_path:line`, a miss falls through to grep). `shctx dups` closes the name-blind gap; detection only — gate enforcement (`DEDUP-GATE` pre-dispatch check, `DUPLICATION-DRIFT` grade cap) is owned by `skills/shepherd/references/pipeline.md §DEDUP-GATE`.

`pub struct`/`pub enum` fingerprints (`field_name, normalized_type` pairs) cluster by:

    sim(a, b) = name_weight · jaccard(field_names) + (1 − name_weight) · jaccard(typed_pairs)

`name_weight` defaults `0.5`, threshold `0.7`, shapes below `dups_min_fields` (default `2`) excluded — tunable under `[dups]`.

- `shctx dups scan [--threshold F] [--fail-on …] [--update] [--json]` — census: `file:line` + consumer count, suggested canonical. `--update` persists to `index_struct_shapes`. `--fail-on {medium|high|foundation-blocking}` MUST exit non-zero for close gates; `foundation-blocking` = orphan canonical beside a live shadow.
- `shctx dups check <file> | --stdin --as <path>` — authoring gate: corpus types at/above threshold + canonical home; exits `5` above block threshold.
- `shctx dups registry show|allow|pin|update` — concept→canonical pin map + DO-NOT-MERGE allow-list, at `<ns>/dups-registry.json`.

Hook `dups_write_guard.sh` runs `dups check` on every `@coder` `.rs` write; `[dups].dups_hook` is `off | warn` (default) `| block`. A block-threshold match denies with `SHAPE-DEDUP BLOCKED — @coder Write would create a field-shape duplicate of an existing type.` Fails open on non-coder, non-Rust, no `python3`, or empty corpus.

---

## Cache telemetry

The `SubagentStop` hook `subagent_telemetry.sh` aggregates each dispatch's token usage and derives:

    hit_rate = cache_read / (cache_read + cache_creation + input)

`hit_rate` is `null`, not `0`, when the denominator is zero — null unmeasured, zero full price paid. Counts only, never prompt content. Rows roll up via `shctx refresh --scope=telemetry` into `index_cache_usage` (view `v_cache_usage`); the auditor embeds `shctx query cache-usage --sprint=<branch> --md` in the close report. Empty view = baseline not yet established, not a failure.

Per-role floors, target/alarm (report-only during baseline; post-baseline, sub-alarm surfaces MEDIUM for `@engineer`): `@coder` 60/40%, `@auditor` 55/35%, `@worker` 65/40%, `@discovery` 55/35%, `@critic` 50/30%, `@engineer` 30/15%. Separately, a lane-weighted sprint-wide mean hit-rate below 40% MUST surface its own MEDIUM finding, weighted so an engineer-heavy wave never drags a healthy coder swarm under alarm. Do NOT grade-cap on telemetry alone — it measures caching health, not correctness.

A hook failure MUST NOT block dispatch: a missing/unreadable transcript writes a degraded row (`parse_error` populated), never fails.

---

## Event log

Every hook fire appends one line to `<ns>/logs/hooks/YYYY-MM-DD.jsonl` via `log_event()` (`hooks/scripts/_lib.sh`), called before the first JSON emit or a silent exit. Fields: `ts`, `hook`, `decision` (`deny|warn|pass`), `tool`, `role`, `session_id`, `fields` (`cmd` truncated to 200 chars, `path`, `reason`, `rule`) — `deny` from `bash_guard.sh`/`lock_guard.sh`, `warn` from any `additionalContext` emission, `pass` from a silent exit. Gitignored, no automated rotation. The library MUST scrub secret-shaped values before writing a line. `shctx doctor`'s `[HOOKS]` section reads this log.

## Doctor

`shctx doctor` runs a six-section preflight — `[GIT]` (branch, sprint-root cwd, orphan worktrees), `[PLAN]` (plan + Stage Graph + canonical-types freshness), `[CTX REGISTRY]` (DB size, migration version, adaptation sprint count), `[HOOKS]` (hooks.json validity, script presence, event-log activity), `[MCP]` (`[mcp].*=true` tool callability), `[LOCK]` (session match). Exit `0` all-green, `1` warnings-only, `2` errors — non-blocking.

Required before `--parallel <N>`; recommended before `/shepherd:spawn`/`--auto`. Pre-init → flags missing `project.json` and `namespace dir`. Post-init → reports `id=<uuid>`, `shepherd.db` size, `schema_version`. Flags: `--section=<name>`, `--json` (carries `.summary`/`.checks` keys), `--quick` (skips MCP).

## Workdir hygiene

`shctx prune` reclaims accreted workdir + registry state without touching outcomes. `--dry-run` (default) writes the plan to `/tmp/shepherd-prune-<epoch>/plan.csv`, removing nothing; `--confirm` MOVES targets into that dir, reversible via `mv` back.

Eligible only when ALL THREE hold: not the current git branch, terminal state, older than the age floor. `index_releases`, the current `focus`, `sprint_metrics`, pinned, doctrine, or decision-kind `mem_entries`, unresolved `escalations`, pending `deliverables`, active `locks`/`loops`, the whole `index_*`/`projects` core, and the tracked `.artifacts/docs/` subtree (plans, seeds, reports) are NEVER candidates. On-disk sweeps (stale dispatch dirs, aged logs, precompact snapshots) execute under `--confirm`. DB-row sweeps are preview-only — eligible-row counts (`logs_events`, terminal `heartbeats`/`mailbox`/`loops`, closed-sprint `discovery_findings`/`audit_findings`, released `locks_history`) are reported, nothing deleted, enabled incrementally. Every DB `DELETE` MUST be table-guarded — a DB missing a later migration is skipped, never errored. `--vacuum` is opt-in, requires `--confirm`. Config: `[prune] logs_days=60 dispatch_days=30 snapshots_keep=20 findings_sprints=6`.

Per-path `git`/`fs` content-hash tracking exists at the schema layer for change detection; no hook consumes it yet.

## Refresh contract

`shctx refresh` is idempotent, scope-bounded: `symbols` re-extracts (Rust via `cargo metadata`+`syn`; else tree-sitter or skipped); `github` re-pulls via `gh`; `artifacts` re-hashes namespace files; `all` runs all three. `[context].auto_refresh` (default `["on-sprint-open"]`) fires `refresh --scope=all` automatically at sprint open. TTL lives in `[context.refresh]`; past `ttl_minutes`, callers re-refresh first.

## Failure modes

- `sqlite3` missing → hard stop, install.
- `gh` missing → `refresh --scope=github` skips silently, warns; other scopes unaffected.
- `cargo` missing → `refresh --scope=symbols` skips Rust extraction, warns.
- DB missing → run `shctx init`, fall back to markdown.
- Schema out of date → run `shctx migrate` after every plugin upgrade.
- Lock held by a stale session → `shctx lock reap` clears entries past `stale_after_minutes`.

## Naming conventions

Namespace paths are date-only vs timestamped (see `references/naming-conventions.md`), enforced by `shctx lint`. `shctx init` writes `<namespace>/CONVENTIONS.md`, mirrored into the consumer project.

## See also

- `references/schema.md` — tables, views, JSON1 query patterns.
- `references/profiles.md` — profile model (modifier/extension/override), TOML format.
- `references/model-map.md` — `[models]` role→model table (`shctx models resolve <role>`).
- `references/toolkit.md` — `toolkit.json` two-tier CLI contract, curated-vs-discovered table.
- `examples/inject-coder.md` — sample `[DB-CONTEXT]` block.
- `skills/shepherd/references/pipeline.md §DEDUP-GATE` — dedup gate + `DUPLICATION-DRIFT` cap.
- `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` — `[context]`/`[dups]`/`[prune]` sections.
