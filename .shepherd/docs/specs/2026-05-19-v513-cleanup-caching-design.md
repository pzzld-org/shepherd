---
title: v5.1.3 — cleanup, cache discipline, and dispatch telemetry
date: 2026-05-19
branch: v5.1.3-dev.1
base: v5.1.3
author: main-chat (designed via superpowers:brainstorming)
---

# v5.1.3 — cleanup, cache discipline, and dispatch telemetry

## North star

Every flock dispatch becomes cheaper and more consistent — through smaller, more stable agent prefixes; brief ordering that puts variable content last; SubagentStop telemetry that proves the wins are real; and a sweep of accumulated cruft.

## Why now

Through v5.1.2 the plugin has accumulated a functional but bloated foundation:

- Agent bodies range from 153 to 629 lines. The largest (`engineer.md` at 629) inlines ~200 lines of mesh row enumeration that is reference, not protocol — paid by every dispatch.
- The `Greatness is the bar` agent-excellence preamble is duplicated verbatim across all six agents (the doctrine itself already exists at `doctrines/agent-excellence.md`).
- Every agent's `tools:` frontmatter inlines a long list of MCP tools, many never invoked by the agent's documented protocol. Each unused tool definition contributes ~150–300 input tokens to every dispatch.
- We have no telemetry on how prompt caching is actually performing per role across a sprint. We cannot tell whether changes to agent structure help or harm cache hit rate.
- Several `cmd_*.sh` scripts under `skills/context/scripts/` are not referenced by any documented command or doctrine.
- Some doctrines and references survive from pre-v5.0 mechanisms and quote pipelines that no longer exist.

v5.1.3 fixes the base. No new conductor capabilities. No new doctrines beyond two narrowly-scoped ones (brief ordering + cache telemetry).

## Non-goals (explicit)

- No new agent roles. Flock stays at six.
- No new commands. Existing `/shepherd:*` surface unchanged.
- No semantic changes to the dispatch pipeline. The Stage Graph nodes/edges in `pipeline.md` are NOT touched except for the §V brief-ordering subsection.
- No version-cycle change. v5.1.3 ships off the current v5.1.3 patch branch; the next patch (v5.1.4 or v5.2.0) is a separate decision.
- No change to `examples/` configurations.

## Architecture — the four lanes

### Lane A1 — Five-agent restructure
**Owner**: agents/{engineer, coder, critic, worker, discovery}.md
**Mission**: aggressive prefix-from-reference split. Trim tools-list. Extract repeated preamble.

For each of the five agents:

1. **Body shape, top to bottom (the cacheable prefix)**:
   - Frontmatter (`name`, `color`, `model`, `thinking`, `description`, trimmed `tools`)
   - One-paragraph identity + `> See doctrines/agent-excellence.md.` (replacing the inline `Greatness is the bar` block)
   - Hard prohibitions (unchanged in semantics)
   - Halt codes table (unchanged)
   - Mandatory protocol steps (the Step-N sequence) — verbose reference catalogs extracted out
   - Output / report shape block (the canonical REPORT template)
   - "What you are NOT" guardrails (unchanged)

2. **Extracted reference** at `skills/shepherd/agents/<role>.reference.md` (NEW file per role), with frontmatter:
   ```yaml
   ---
   name: agent-<role>-reference
   description: |
     Reference material for @<role>. Loaded on demand via Skill at agent startup.
     Contains catalogs, templates, and per-dispatch emphasis content that is not
     needed for every line of agent reasoning.
   ---
   ```
   Each agent's protocol Step 1 (or equivalent first step) gains: "Load `shepherd:agent-<role>-reference` via the Skill tool." So the reference is loaded once per session and cached for the session's remaining turns.

3. **Per-agent extraction targets**:
   - `engineer.md` → reference: Phase 0 mesh row 1–14 enumeration, plan-quality bar checklist, plan body section template, proof-of-dispatch footer
   - `coder.md` → reference: PAUSE-FOR-DEPENDENCY full report template, INSIGHTS section template, dispatch pattern examples
   - `critic.md` → reference: pass-2 flag classification, verdict semantics extended prose
   - `worker.md` → reference: dispatch patterns 1–5, PAUSE-FOR-DEPENDENCY shape, INSIGHTS template
   - `discovery.md` → reference: Bash allowlist details, dispatch examples, OUTPUT-PATH conventions

4. **Tools-list audit**: for each agent, the implementer reads the protocol body, identifies actually-invoked tools, and keeps only those in `tools:`. Default permissive lists are not acceptable. Conservative bias: keep a tool if there is a documented invocation; drop if the documentation never names it.

5. **Acceptance for Lane A1**:
   - `wc -l agents/{engineer,coder,critic,worker,discovery}.md` reports each at ≤ 60% of pre-restructure line count (engineer: ≤ 380; auditor: handled by A2; others: ≤ 220)
   - `rg "Greatness is the bar" agents/` returns 0 hits (replaced by doctrine reference)
   - `ls skills/shepherd/agents/*.reference.md` shows five files (matching the five agents this lane owns)
   - Each new reference file has valid frontmatter (`name:` line begins with `agent-` prefix)
   - The five trimmed agent bodies each contain a documented Skill load directive for their reference
   - Each agent's `tools:` line, after the trim, contains no MCP tool whose name does not appear in the documented protocol of that agent

### Lane A2 — Auditor restructure + completeness extensions
**Owner**: agents/auditor.md (full owner; no other lane may touch this file)
**Mission**: same restructure as A1 PLUS the two completeness extensions Lanes B and C would otherwise need to land. Folding them here avoids file conflict in Wave 2.

Steps:
1. Apply the same restructure pattern as A1: identity → prohibitions → halt codes → mandatory steps → report shape → "What you are NOT".
2. Extract reference content to `skills/shepherd/agents/auditor.reference.md`:
   - Per-concern emphasis (close + intro modes)
   - Per-finding contract template (hypothesis-driven shape)
   - Bayesian finding-class weighting full prose
   - Grade rubric prose and per-grade meaning table
3. Trim `tools:`.
4. **Completeness-concern extension #1 (Brief-order verification)**: add to the `completeness` per-concern emphasis a new verification step — "Read the conductor's dispatch run-log entries for this sprint (from `agent_invocation_tagger.sh` output under `.artifacts/runs/` or wherever the existing tagger writes); for each brief captured, verify the bracketed-section order matches `doctrines/brief-cache-discipline.md`. File LOW per dispatch on violation; aggregate as MEDIUM if > 30% of dispatches violate."
5. **Completeness-concern extension #2 (Cache telemetry table)**: add a `## Cache telemetry` subsection to the close-mode report template. Step content: "Run `shctx query cache-usage --sprint={current_sprint} --md` and embed the table. If `v_cache_usage` view absent (telemetry data not yet collected), note 'telemetry view absent — establishing baseline'. Threshold guidance: aggregate hit-rate < 40% across the sprint is a MEDIUM finding for investigation."

6. **Acceptance for Lane A2**:
   - `wc -l agents/auditor.md` reports ≤ 280 lines (down from 459)
   - `ls skills/shepherd/agents/auditor.reference.md` exists with valid frontmatter
   - `rg "brief-cache-discipline" agents/auditor.md` returns ≥ 1 hit (cites the new doctrine in completeness emphasis)
   - `rg "Cache telemetry" agents/auditor.md` returns ≥ 1 hit (cites the new close-report subsection)
   - `rg "shctx query cache-usage" agents/auditor.md` returns ≥ 1 hit (the actual query the auditor will run)

### Lane B — Brief assembly discipline
**Owner**: `skills/shepherd/doctrines/brief-cache-discipline.md` (NEW), `skills/shepherd/pipeline.md` (modify §V), optionally `skills/shepherd/references/agent-briefs.md` (modify if it conflicts with new ordering)
**Depends on**: Lane A1 + A2 landing (the agent restructure changes what protocol-reminders looks like)

Steps:
1. Create `skills/shepherd/doctrines/brief-cache-discipline.md`. Sections:
   - **Origin**: v5.1.3 (2026-05-19). Operator: "every agent within the flock needs to leverage prompt caching to prevent degradation of outputs."
   - **The principle**: a brief is a user message. The conductor builds it inline. The caching runtime caches stable prefixes. Therefore: stable framing first, variable content last.
   - **Stable framing block** (top of every brief; deterministic order): `[ROLE]` → `[SKILLS]` → `[DOCTRINES]` → `[PROTOCOL-REMINDERS]`. Each is a short, recyclable block. The conductor's brief-template macros (whether textual or implicit) reuse these verbatim across every dispatch in a sprint.
   - **Variable content block** (bottom; dispatch-specific): `[FILE-SCOPE]` → `[CONTEXT-INVENTORY]` → `[DO-NOT-DUPLICATE]` → `[ACCEPTANCE]` → `[NON-GOALS]` → `[WORKTREE]` → `[BASE-COMMIT-EXPECTED]`. These are the per-lane / per-dispatch fields the engineer populates.
   - **The rule**: every bracketed section from the stable block must appear before any bracketed section from the variable block. Prose interleaving is allowed.
   - **Enforcement**: the completeness auditor verifies post-hoc. There is no pre-dispatch hook gate — the rule is structural discipline, not a runtime guard.
   - **Why ordering matters**: the runtime places implicit cache breakpoints at major content transitions in a long user message. Placing variable content at the bottom means the stable prefix is reused across dispatches in the same conductor session, even when file-scope and acceptance change.
2. Modify `skills/shepherd/pipeline.md` §V (dispatch shape) to add a "Cache-first brief ordering" subsection that cites the doctrine and links to it. Three-paragraph addition is sufficient.
3. Read `skills/shepherd/references/agent-briefs.md` (existing brief templates); if any template emits sections in an order that violates the new rule, reorder them. Verify by re-reading.

Acceptance for Lane B:
- `ls skills/shepherd/doctrines/brief-cache-discipline.md` exists
- Doctrine has all named sections (Origin, principle, stable framing, variable content, rule, enforcement, why ordering matters)
- `rg "brief-cache-discipline" skills/shepherd/pipeline.md` returns ≥ 1 hit
- `rg "Cache-first brief ordering" skills/shepherd/pipeline.md` returns ≥ 1 hit
- `skills/shepherd/references/agent-briefs.md` brief templates emit sections in the canonical order (stable bracketed first, variable bracketed second) — verifiable by reading

### Lane C — Cache telemetry stack
**Owner**: `hooks/scripts/subagent_telemetry.sh` (NEW), `hooks/hooks.json` (modify), `skills/context/schema/migrations/0006_cache_telemetry.sql` (NEW), `skills/context/schema/views/cache-usage.sql` (NEW or inline in migration), `skills/context/queries/cache-usage.sql` (NEW), `skills/context/scripts/cmd_refresh.sh` (modify — add `telemetry` scope), `skills/shepherd/doctrines/cache-telemetry.md` (NEW). Does NOT modify agents/auditor.md (that's Lane A2's owner).

Steps:

1. **The hook** `hooks/scripts/subagent_telemetry.sh`:
   - Trigger: investigate which Claude Code hook event provides the subagent's per-turn API usage. Candidates in priority order:
     a) `SubagentStop` event with transcript path payload — parse the transcript JSON for per-turn `usage` objects
     b) `Stop` event inside the subagent's own session — same parse
     c) `PostToolUse` with matcher `Agent`/`Task` on the parent session — the result text doesn't carry usage, but if Claude Code exposes the subagent's usage via the hook payload, capture there
   - Implementation: pick the event that actually exposes `cache_read_input_tokens` / `cache_creation_input_tokens` / `ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`. If none expose these directly, document the gap and write a degraded hook that captures whatever IS available (`input_tokens`, `output_tokens`) plus a `parse_error: "<reason>"` field. The lane SHOULD NOT silently no-op on missing fields.
   - Output: one JSONL line appended to `.artifacts/logs/events-YYYY-MM-DD.jsonl` with shape:
     ```json
     {
       "ts": "ISO-8601",
       "event_type": "cache_usage",
       "session_id": "...",
       "role": "coder|engineer|critic|auditor|worker|discovery|main-chat",
       "agent_id": "agt-...",
       "sprint": "<best-effort branch name>",
       "turns": N,
       "input_tokens": N,
       "output_tokens": N,
       "cache_read_input_tokens": N,
       "cache_creation_input_tokens": N,
       "ephemeral_5m_input_tokens": N,
       "ephemeral_1h_input_tokens": N,
       "hit_rate": <float, 0..1>,
       "parse_error": null
     }
     ```
   - Failure discipline: all errors are non-blocking. Exit 0 even on parse failure. Emit an event with `parse_error` populated.
   - Wire-up in `hooks/hooks.json`: add the new event handler under whichever event the lane chose. Update the matching `.claude-plugin/hooks.json` if separate; verify both files stay in sync.

2. **Schema** `skills/context/schema/migrations/0006_cache_telemetry.sql`:
   - Create `index_cache_usage` table with columns: `project_id`, `ts`, `session_id`, `role`, `agent_id`, `sprint`, `turns`, `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `ephemeral_5m_input_tokens`, `ephemeral_1h_input_tokens`, `hit_rate` (REAL), `parse_error` (TEXT nullable)
   - Indexes on `(project_id, sprint)` and `(project_id, role, ts)`
   - View `v_cache_usage` aggregating per sprint + role: `sprint`, `role`, `dispatches`, `avg_hit_rate`, `total_input`, `total_cache_read`, `total_cache_creation`, `avg_first_turn_creation` (proxy for system-prompt size — derived from rows where `turns = 1` ideally, or smallest-turn rows per session as a proxy)
   - `INSERT INTO schema_versions (version, applied_at, checksum) VALUES (6, unixepoch(), 'cache-telemetry-v5.1.3');`

3. **Refresh scope** in `cmd_refresh.sh`: add a `telemetry` scope that:
   - Reads `.artifacts/logs/events-*.jsonl` files
   - Filters for `event_type=='cache_usage'`
   - INSERTs into `index_cache_usage` (idempotent — use ON CONFLICT DO NOTHING keyed on `(session_id, agent_id, ts)`)
   - Reports rows inserted

4. **Query** `skills/context/queries/cache-usage.sql`:
   ```sql
   -- usage: shctx query cache-usage [--sprint=<branch>]
   SELECT sprint, role, dispatches, avg_hit_rate, total_input,
          total_cache_read, total_cache_creation
   FROM v_cache_usage
   WHERE project_id = :project_id
     AND (:sprint = '' OR sprint = :sprint)
   ORDER BY sprint DESC, role;
   ```

5. **Doctrine** `skills/shepherd/doctrines/cache-telemetry.md`:
   - **Origin**: v5.1.3 (2026-05-19).
   - **What it captures**: per-dispatch usage including the four cache-related fields.
   - **Where it lands**: event log JSONL → registry view via `shctx refresh --scope=telemetry`.
   - **How it's surfaced**: completeness auditor in close report (per Lane A2).
   - **Threshold guidance** (informational, evolving baselines): for the first 2–3 sprints, threshold is exploratory. After three sprints of data, the doctrine is updated with per-role expected hit-rate ranges. Below 40% aggregate hit-rate across a sprint is a MEDIUM finding flag.
   - **Failure modes**: missing transcript, missing fields, hook errors — all surface as `parse_error` rows, never block dispatch.
   - **Privacy / size note**: the event log includes per-dispatch counts only. No prompt content. JSONL is gitignored per existing `.artifacts/logs/` convention.

Acceptance for Lane C:
- `ls hooks/scripts/subagent_telemetry.sh` exists, executable bit set (`test -x`)
- `jq '.hooks | keys' hooks/hooks.json` includes the new event handler
- `ls skills/context/schema/migrations/0006_cache_telemetry.sql` exists
- `sqlite3 :memory: < <(cat skills/context/schema/0001_init.sql skills/context/schema/migrations/0002_styles.sql skills/context/schema/migrations/0003_canonical_types_filter.sql skills/context/schema/migrations/0004_fts_search.sql skills/context/schema/migrations/0005_watch_paths.sql skills/context/schema/migrations/0006_cache_telemetry.sql) ".tables" | tr ' ' '\n' | grep -q "^index_cache_usage$"`
- `ls skills/context/queries/cache-usage.sql` exists
- `rg "telemetry" skills/context/scripts/cmd_refresh.sh` returns ≥ 1 hit (scope wired up)
- `ls skills/shepherd/doctrines/cache-telemetry.md` exists with all named sections

### Lane D — General cruft cleanup
**Owner**: targeted file deletions + stale-reference edits across the tree; explicitly does NOT touch any `agents/*.md` file (those are A1/A2's exclusive scope)
**Mission**: identify and either remove or document-as-historical anything in the plugin that is no longer wired up.

Steps (each produces a finding list; the implementer then acts on each finding):

1. **Dead command scripts**: for each `skills/context/scripts/cmd_*.sh`, run `rg "shctx (\w+ )?<cmd>" -t md ${CLAUDE_PLUGIN_ROOT}` (replacing `<cmd>` with the script's command name). If 0 doc references AND not in `commands/*.md`, mark candidate-for-removal. Implementer reviews each candidate manually (don't auto-delete; some scripts may be wired through `_lib.sh` indirection).
2. **Stale doctrine references**: for each `doctrines/*.md`, grep for `v4\.`, `v5\.0\.[0-5]`, or specific deprecated mechanism names. For each hit, the implementer reads the doctrine and either updates the reference to current state, or moves the doctrine to `doctrines/_candidates/` if obsolete.
3. **Orphan files in `doctrines/_candidates/`**: list them; for each, decide promote-to-main or delete. Document in CHANGELOG.
4. **Gitignored content that's been committed**: `git ls-files | xargs -I{} sh -c 'git check-ignore -q "{}" && echo "TRACKED+IGNORED: {}"'`. Each hit is a candidate for `git rm --cached`.
5. **Stale references in `pipeline.md` / `planter.md` / `SKILL.md`**: grep for `v4\.`, `pre-4.2`, `pre-v5.0`. Treat each finding as a manual review and update.
6. **README + CHANGELOG verification**: ensure version mentions match `5.1.3` consistently; add a v5.1.3 CHANGELOG entry stub summarizing this sprint's work.

Acceptance for Lane D:
- Cleanup report saved to `.artifacts/docs/handoffs/2026-05-19-v513-cleanup-report.md` listing: files removed, doctrines moved to `_candidates/`, stale references updated, gitignored-but-tracked files dispositioned.
- `git ls-files | xargs -I{} sh -c 'git check-ignore -q "{}" && echo {}' | wc -l` returns 0 (no tracked+ignored files remaining), OR every remaining hit has a documented exception in the cleanup report.
- `CHANGELOG.md` has a v5.1.3 entry (initial stub; final write at sprint close).
- All version-source-of-truth files (per CLAUDE.md "Versioning") report `5.1.3`.

## Lane dependencies and wave plan

Wave 1 (parallel, 3 lanes — all file-disjoint):
- Lane A1 (agents/{engineer,coder,critic,worker,discovery}.md + their references)
- Lane A2 (agents/auditor.md + its reference + completeness extensions)
- Lane D (cleanup; does not touch agents/*.md)

Wave 2 (parallel, 2 lanes — file-disjoint with each other; both run after Wave 1 because they need final agent state for verification, but Lane B + Lane C touch different files):
- Lane B (brief-cache-discipline doctrine + pipeline.md §V edit + agent-briefs.md reorder if needed)
- Lane C (telemetry hook + migration + query + cache-telemetry doctrine)

The auditor.md completeness extensions for both new doctrines are landed by A2 in Wave 1 (forward-declared); they reference doctrines that don't exist until Wave 2 finishes. This is acceptable because the auditor only LOADS the doctrine at audit time, not at sprint open; by the time the auditor runs, Wave 2 is done.

## Verification (post-Wave 2)

Manual main-chat verification:
1. All five Wave 1 + Wave 2 lane acceptance grep blocks pass.
2. `git diff v5.1.3...HEAD --stat` shows the expected file set: 6 modified agents, 6 new agent reference skills, 2 new doctrines, 1 modified pipeline.md, 1 new hook, 1 new schema migration, 1 new query, 1 modified cmd_refresh.sh, 1 modified hooks.json, 1 modified hooks/hooks.json (sync target), CHANGELOG entry, cleanup report.
3. `bash hooks/tests/run.sh` passes (existing test harness).
4. `bash skills/context/tests/run.sh` passes (existing test harness).
5. No `cargo`/`pnpm`/`pytest` exists in this repo — there are no language gates to run. The plugin is markdown + bash; lint via existing test harnesses is the highest gate.
6. Smoke-test the telemetry hook by triggering one toy Agent dispatch and verifying a `cache_usage` event lands in `.artifacts/logs/events-*.jsonl`.

## Out-of-scope acknowledgements

- The `parse_error` analytics path (alerting on persistent telemetry parse failures) is not implemented in v5.1.3. If telemetry shows persistent parse errors after a sprint, v5.1.4 can add a guard.
- Per-role hit-rate baselines in the cache-telemetry doctrine remain "exploratory" until 2–3 sprints of data are collected. v5.1.3 ships the capture; v5.1.4+ refines the thresholds.
- Conversion of inline preamble references in skills outside `agents/` (e.g., per-language style skills) is not in scope. They have a different cache profile and don't dispatch as flock roles.

## Proof of dispatch

- design author: main-chat @ 2026-05-19
- branch: v5.1.3-dev.1 (off v5.1.3)
- supersedes: nothing (this is the first design for v5.1.3)
- waves: 2 (Wave 1: A1 + A2 + D in parallel; Wave 2: B + C in parallel)
- status: APPROVED-BY-OPERATOR — proceeding to parallel dispatch
