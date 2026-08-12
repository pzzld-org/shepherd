# A3 — registry schema and ledger truth

**Reporter:** intro-mode `@auditor` · **Run:** v645 · **Materialized by:** root (payload landed in root's
notification stream, not the dispatching engineer's — see `dogfood.md` DF-11) · 2026-08-12

## Schema ground truth

| Claim | Mesh | File evidence | Live DB | Verdict |
|---|---|---|---|---|
| Migrations applied | 20 | 20 files in `skills/context/schema/migrations/` (0002-0021) | `schema_versions` has 21 rows | **CORRECTED** — 20 is the migrations-dir count; +1 baseline = 21 |
| Tables | 39 | `grep -c "CREATE TABLE"` across `schema/` = 39, exact match | **36 live** (34 base + 2 FTS5 virtual); 44 raw `sqlite_master` rows if you naively count the 8 FTS5 shadow tables | **CORRECTED** — 39 is a migration-history statement count |
| Views | 25 | `grep -c "CREATE VIEW"` = 25 (15 distinct names) | **14 live** | **CORRECTED** — `v_mailbox_unread_per_recipient` dropped in `0020_drop_mailbox.sql`, never recreated |
| Indexes | 40 | `grep -c "CREATE INDEX"` = 40 (36 distinct names) | **34 live** named (+34 `sqlite_autoindex_*`) | **CORRECTED** — the 2 mailbox indexes dropped with the table |
| Triggers | 7 | 7 `CREATE TRIGGER`, all unique, never redefined | 7 live | **CONFIRMED exact** |
| FTS5 external-content vtables | 2 | 2 `CREATE VIRTUAL TABLE … USING fts5` | `index_fts_symbols`, `index_fts_artifacts` | **CONFIRMED** |
| FTS5 sync triggers | 6 | — | `artifacts_ad/ai/au` + `index_symbols_ad/ai/au` (7th trigger is `trg_watch_paths_updated_at`, unrelated) | **CONFIRMED** |
| `json_valid()` CHECKs | 25 | 31 occurrences across full history | **24 live** across 19 tables | **CORRECTED** |
| State table | — | — | `schema_versions` = 21 rows; `PRAGMA user_version` = **0**, unused | **CONFIRMED** — decision 6's dependency holds |
| FTS5 tokenizer | — | — | `tokenize='unicode61 remove_diacritics 2'` verbatim on both vtables | **CONFIRMED verbatim** |

**Pattern:** every corrected number (39/25/40) is the count of `CREATE …` **statements written across
migration history**, not live objects. The mesh conflated authoring-history volume with runtime object
count — it includes rename-dance transients (`mem_entries_new`, `locks_history_new`, `focus_new`,
`mailbox_new`) and the fully-dropped `mailbox`. **A Rust port sized off the mesh over-provisions views and
indexes by roughly 40-70% and misses the mailbox drop entirely.**

## Migration count — 20 versus 21 resolved

`schema/0001_init.sql` lives **outside** `schema/migrations/`, at the schema-dir top level. Both runners
glob only `schema/migrations/[0-9][0-9][0-9][0-9]_*.sql` — Python
`services/cli/shepherd_cli/commands/migrate.py`, bash `skills/context/scripts/_lib.sh:281`
(`shctx_apply_pending_migrations`) — which is 20 files, 0002-0021. `0001_init.sql` is applied by a
**separate code path**, `shctx init`, confirmed by `_lib.sh:308-309`'s own comment: *"shctx init seeds only
0001 and migrations are applied by a SEPARATE shctx migrate."*

Root's bootstrap ran both, hence 21 rows. Not a bug — a framing gap in the mesh's "20 migrations" claim.
**A Rust runner that globs `migrations/*.sql` silently skips the baseline schema.** Seed decision 6 should
read 21, with the baseline named explicitly.

## Guard read surface

`grep -l sqlite3 hooks/scripts/*.sh` → **10 of 32** scripts read the DB directly:

| Script | Tables / views | Columns |
|---|---|---|
| `conductor_write_guard.sh:103` | `teammates` | `session_id, status` |
| `coordinate_drive_guard.sh:61,90,93,110,115,141,154` | `teammates`, `v_teammates_live`, `spawn_leads` | `session_id, status, last_seen_at, declared_state, team_name, ms_since_seen` |
| `deliverable_check.sh:25,29` | `deliverables` | `status, promised_at` |
| `session_open.sh:59,60,65` | `sprint_metrics`, `mem_entries` | `count(*)`, `kind, created_at, title` |
| `teammate_git_guard.sh:106` | `teammates` | `session_id, status` |
| `teammate_heartbeat.sh:54,76` | `teammates` | `session_id, status, team_name, spawned_at, last_seen_at, tmux_pane_id` |
| `teammate_idle.sh:59,60,64,65,76,77` | `teammates` | `teammate_name, session_id, status` |
| `worktree_lifecycle.sh:53,88-91,98-102` | `sqlite_master`, `worktrees` | `path, branch, tool_use_id, agent_role, sprint, created_at, status, removed_at` |
| `precompact_snapshot.sh:153,158,161-163` | `sqlite_master`, `pragma_table_info('focus')`, `focus` | `sprint, objective, active_node, ready_set, obligations, invariants, updated_at, lane` |
| `worktree_teardown_guard.sh:64` | `v_teammates_live` | `count(*)` |

**Minimum frozen surface for the Rust registry crate** — tables `teammates, deliverables, sprint_metrics,
mem_entries, worktrees, focus, spawn_leads` plus introspection (`sqlite_master`, `pragma_table_info`); view
`v_teammates_live`. Column union for `teammates`: `session_id, status, team_name, spawned_at,
last_seen_at, tmux_pane_id, declared_state, teammate_name`.

## Locked decision 3 — REFUTED

Decision 3 states *"All 32 guard scripts read SQLite directly and zero of them shell out to the CLI."*
**False.** `grep -n '/bin/shepherd' hooks/scripts/*.sh` finds functional invocations, not comments:

- `hooks/scripts/dups_write_guard.sh:65` — `result=$(printf '%s' "$content" | bash "$shctx" dups check --stdin --as "$file_path" --json …)` — drives the BLOCK/WARN decision.
- `hooks/scripts/seed_preflight_check.sh:64` — `report="$(bash "$shctx" seed verify "$tmp" …)"` — gates SEED-GATE.
- `hooks/scripts/teammate_idle.sh:57-58` — `"$ROOT/bin/shepherd" teammate heartbeat "$TEAMMATE" --note='idle'`.
- `hooks/scripts/teammate_idle.sh:88` — `STALLED=$("$ROOT/bin/shepherd" deliverable stalled --since-mins=10 …)`.
- `hooks/scripts/user_prompt_submit.sh:102` — `status_out=$("${PLUGIN_ROOT}/bin/shepherd" status …)`.

All other `shctx`/`bin/shepherd` strings in `hooks/scripts/` (all ~90 hits checked) are human-facing
`echo`, comment, or docstring. So the mesh is directionally right about the bulk of strings and wrong in
absolute terms: **5 real shellouts across 4 scripts.**

Critically, `dups_write_guard.sh`, `seed_preflight_check.sh`, and `user_prompt_submit.sh` are **not** in
the 10-script direct-SQL set — they touch DB state **exclusively** through the CLI. The load-bearing
compatibility surface therefore includes CLI subcommand behavior — `dups check --stdin --as --json`,
`seed verify`, `teammate heartbeat --note`, `deliverable stalled --since-mins`, `status` — not schema
shape alone. **A conformance oracle scoped to `sqlite_master` + `run.json` + template digests
under-scopes #281 and lets those five verbs drift silently.**

## Migration portability — decision 6 holds

All 21 files (`0001_init.sql` + 0002-0021) are pure, portable SQL. No Python f-strings, no dynamic SQL
construction, no data-backfill logic outside SQL. Verified:

- Both runners load each file as an opaque byte blob and execute verbatim. Python `migrate.py:308-315`
  (`fh.read()` → `conn.executescript(sql_text)`, sha256 of raw bytes → `schema_versions.checksum`); bash
  `_lib.sh:290` (`{ echo "PRAGMA busy_timeout=5000;"; cat "$f"; } | sqlite3 "$db"`, `shasum -a 256`).
- Rename-dance data preservation (`0009` locks_history, `0011` mem_entries, `0017` focus, `0016`/`0020`
  mailbox) uses pure `INSERT INTO x_new SELECT … FROM x; DROP TABLE x; ALTER TABLE x_new RENAME TO x;`.
- `PRAGMA journal_mode`/`foreign_keys` live **inside** the `.sql` files (portable). The only
  runner-injected PRAGMA is `busy_timeout=5000`, added independently by **both** runners at the connection
  level — operational, not schema DDL.
- No `%s`/`.format()`/f-string-brace smells in any `.sql`; the only `%s` hits are SQLite's own `strftime`.

**Scope note, not a violation:** `shepherd migrate --layout v2/v3/v4` (`migrate.py`) is a **different class**
of migration — workdir and filesystem layout moves (`root.db`→`shepherd.db`, `plans/`→`docs/plans/`),
implemented purely in Python with no `.sql` counterpart. Decision 6 covers only the 21 schema files and is
correct about those; **a Rust port must separately reimplement the layout migrations natively.**

**Minor finding:** `skills/context/schema/views/*.sql` (5 files) is a manually-maintained, self-labeled
*"reference copy only; not applied"* mirror of view bodies already defined inline in numbered migrations.
Byte-identical to the authoritative `0003_canonical_types_filter.sql` today, with zero runtime consumers
(`grep -rl "schema/views"` across `.py`/`.sh`/`.rs` is empty — neither runner's glob touches it). Harmless
now, but nothing tests the sync, so a future inline view edit can silently rot the mirror.

## Carry-forward disposition

| Issue | Claim | Code evidence | Verdict |
|---|---|---|---|
| **#239** retire bash layer | port last 7 commands, retire bash, ship `~/.shepherd` global DB | `bin/shepherd` header: *"the Python package is the sole owner of CLI logic — the loose `skills/context/scripts/cmd_*.sh` shell layer is retired behind this surface."* Python has 45 command modules vs 40 bash `cmd_*.sh`; **all 40 still present, plus 98 bash test files** | **PARTIALLY-FIXED** — routing moved, dead files never deleted |
| **#266** venv unprovisioned | `ModuleNotFoundError: typer` on upgrade | `bin/shepherd-venv-ensure` header cites #266; `venv_provisioned()` now checks `[ -x "$VENV_DIR/bin/shepherd" ]` OR a `typer` site-packages glob, replacing the old directory-existence test; `hooks/scripts/session_venv.sh` calls it at SessionStart | **GENUINELY-FIXED** |
| **#235** launcher glob | globs `cache/fl03/shepherd/*` only | `scripts/install-shctx-launcher.sh:147` — `CANDIDATES=("$CACHE_ROOT"/*/shepherd/*)`, publisher segment is a wildcard; `:138` explicitly refuses silent fallback citing "#235 bug class" | **GENUINELY-FIXED** |
| **#277** run-local support dirs | — | `services/cli/shepherd_cli/commands/init.py:261-294` scaffolds `archive/, scripts/, templates/, types/`; this session's `git status` shows them freshly created by root's bootstrap | **LIKELY-FIXED**, but scaffold is project-root-level, not per-run — see Open questions |
| **#278** mandatory run-scoped graph state | make run-scoping mandatory, keep project state flat | `graph.py` docstring: `--run=<name>` resolves to `<workdir>/runs/<run>/graph/` **when identifiable, else ALWAYS falls back to legacy `<workdir>/graph/`** | **PARTIALLY-FIXED** — opt-in with a legacy flat fallback; the "mandatory" bar in the title is not met |

## Seed open question 1 — ANSWERED

| Issue | CHANGELOG claim | Code check | Verdict |
|---|---|---|---|
| #261 | `verdicts.py`, `shepherd run ledger path\|check`, `.gitattributes merge=union` scaffold | `verdicts.py` exists; `run.py:830,867` `@ledger_app.command("path"/"check")`; `init.py:622-633` `_scaffold_gitattributes` — repo-root `.gitattributes` not materialized in this repo, so the function exists but was never exercised here (low severity) | **GENUINELY-FIXED** |
| #262 | `shepherd run wave verify` joins plan steps against the ledger | `run.py:926-936` `wave_verify_cmd`, surfaces `NO-VERDICT`/`UNRESOLVED-VERDICT`/`ORPHAN-VERDICT`/`MALFORMED-ROW` | **GENUINELY-FIXED** |
| #263 | doctrine: subagent-vs-teammate Workflow conflation, `WORKFLOW-VEHICLE-PROBE` | live in `skills/harness/SKILL.md`, `skills/shepherd/SKILL.md`, `references/{pipeline,wave-routine,invariant-matrix,escalation}.md`, `harness/references/workflow-templates.md` | **GENUINELY-FIXED** |
| #266 | venv provisioning check | see carry-forward table | **GENUINELY-FIXED** |
| #267 | `scripts/team-preflight.sh` fixes Check 3 false-positive | script exists | **GENUINELY-FIXED** |
| #268 | `shctx plan amend`, append-only `amendments[]` | `plan.py:772,830-853,1132` | **GENUINELY-FIXED** |
| #269 | `shctx plan lane-drift`, `${CLAUDE_PLUGIN_ROOT}` path fixes | `plan.py:860,930,1009-1094` fully implemented and wired into usage | **GENUINELY-FIXED** |
| #270 | doctrine: `Agent()` completion treated as absent, defensive poll upgrade | `"had no active task"` / `"Defensive poll"` in `references/{invariant-matrix,wave-routine}.md`, `harness/references/workflow-templates.md` | **GENUINELY-FIXED** |

**All 8 are safe to close at the code level.** None are false CHANGELOG claims.

## Findings

1. **HIGH** — Locked decision 3 is factually false; 5 functional CLI shellouts across 4 guard scripts. The
   Rust registry crate's compatibility surface is under-scoped if it targets schema alone. Confidence HIGH.
2. **MEDIUM** — Mesh's 39/25/40 are statement counts, not live objects (36/14/34). Anyone provisioning off
   them over-builds by 3 tables, 11 views, 6 indexes. Confidence HIGH.
3. **LOW** — `json_valid()` CHECK count is 24 live, not 25. Confidence HIGH.
4. **LOW** — Migration framing should read "20 in `migrations/` + 1 baseline applied by `shctx init`". A
   Rust runner globbing only `migrations/*.sql` skips the baseline. Confidence HIGH.
5. **MEDIUM** — #239 is PARTIALLY fixed: 40 `cmd_*.sh` + 98 bash test files remain on disk. Confidence HIGH.
6. **LOW** — #278 is PARTIALLY fixed: run-scoping is opt-in with an unconditional legacy flat fallback,
   documented in `graph.py`'s own docstring. Confidence HIGH.
7. **LOW** — `skills/context/schema/views/*.sql` is a zero-consumer manually-synced mirror with no drift
   check. Confidence MEDIUM.

## Open questions

- **#277** — code confirms project-root-level scaffolding exists and was exercised this session, but the
  issue title says "run-local", which may mean per-run subdirectories rather than project-global ones.
  Could not resolve from `init.py` alone within budget. Re-read the full issue body before closing.

No repo or DB writes were made; WRITE-SCOPE honored.
