# v6.0.3 — coherence remediation (full passover fixes)

- **Branch:** `v6.0.3`  ·  **Source:** validation passover `werc4cjbk` (7 concerns, ~35 findings)
- **Order:** Wave A (executable + canonical halt tables — author+verify) → Wave B (doctrine/doc fan-out) → Wave C (verify+commit+push) → then #94/#95.
- Per-finding detail lives in the passover output; this spec pins cross-file decisions + designs the executable fixes.

## PINNED cross-file decisions (copy verbatim)

### Meta-orchestrator count
Always: **three meta-orchestrators (root `agents/shepherd.md`, conductor `agents/conductor.md`, parallel-meta `agents/planter.md`)**. Fix every "two meta-orchestrators" / 2-of-3 listing.

### `--auto` policy
**Preserved as a stable alias for `--scope patch`.** The "deprecated v5.2.0 / removed v6.0.0" timeline is **rescinded** — delete all deprecation+removal text (spawn.md frontmatter+body, scope-scale-workload.md §V). Keep the `§--auto` section as live documentation.

### `SCOPE OVERFLOW`
Canonical form = **`SCOPE OVERFLOW`** (space, matching `agents/coder.md` halt table). Fix the hyphenated `SCOPE-OVERFLOW` in `brief-cache-discipline.md`.

### PAUSE-FOR-DEPENDENCY (retired v6.0.1 #70) — replacement wording
Replace every active instruction with: *"Express cross-lane dependencies as graph-edge await ordering (engineer-composed); for genuine cross-teammate hand-off use Agent Teams `SendMessage`; out-of-sprint work → file a finding at close. (PAUSE-FOR-DEPENDENCY retired v6.0.1 #70, per `doctrines/native-coordination.md`.)"* Files: `agent-briefs.md` (lines 99,135 — **injected into every coder brief**), `flock-cohesion.md` (§III 71/126/208), `dispatch-cascade.md` (frontmatter+§VI 147), `specialist-dispatch.md` (340), `brief-cache-discipline.md` (101). For `adaptation-loop.md` (178/189): historical table rows may keep the label tagged "(retired v6.0.1)"; the forward-looking rule at 189 must use the await-edge replacement.

### Canonical halt-code roster — `agents/conductor.md §Halt codes` (the canonical registry per spawn-escalation §III)
Add a **Tier** column (`CRITICAL`=P0 preempt / `BLOCKING` / `NOTIFY`) and these rows (verbatim names):

| Code | Tier | Meaning (concise) |
|---|---|---|
| `TEAMMATE-ARTIFACT-WRITE` (TEAMMATE) | BLOCKING | Attempted `Edit`/`Write` of artifact files outside worktree scope; return the artifact via `SendMessage` payload, root materializes. |
| `TEAMMATE-LOCK-ATTEMPT` (TEAMMATE) | BLOCKING | Attempted acquire/release of `.artifacts/shepherd.lock`; root owns the lock. |
| `TEAMMATE-FLAG-MISUSED` | NOTIFY | `--teammate` used with no valid INVOCATION-CONTEXT boot block; session refuses pre-run; no root action. |
| `TEAMMATE-BOOT-MALFORMED` (TEAMMATE) | BLOCKING | Boot prompt missing/malformed dispatcher/lane-brief/root-session fields; root inspects spawn record + re-spawns corrected. |
| `SPECIALIST-UNCLEAR` | BLOCKING | Specialist identity/scope ambiguous; operator clarifies before dispatch. Per `specialist-dispatch.md`. |
| `SPECIALIST-UNAVAILABLE` | BLOCKING | Specialist `subagent_type` errored/unavailable after reload; operator substitutes or aborts. Per `specialist-dispatch.md`. |
| `BASE-DRIFT` | CRITICAL | Worktree HEAD ≠ `[BASE-COMMIT-EXPECTED]`; re-create worktree via `shctx worktree create-batch` before re-dispatch. Per `worktree-base-drift.md`. |
| `DISPATCH-TEAMMATE-TYPE-MISMATCH` (v6.0.0) | BLOCKING | Flock dispatch set `team_name` with `subagent_type ≠ shepherd:conductor`. Per `dispatch-tier-separation.md §IV-bis.2`. |
| `WORKTREE-DRIFT` | BLOCKING | Auditor invoked with pwd/HEAD ≠ sprint root; dispatch auditor from primary worktree. Per `auditor-readonly.md`. |
| `MODE-MISMATCH` | NOTIFY | Auditor brief `mode` ≠ concern type; conductor re-briefs with correct mode. |
| `PRIMITIVE-INVERSION` (flag) | NOTIFY | Non-blocking flag from `dispatch_guard.sh` (additionalContext, not deny). Per `primitive-axis-binding.md §IV`. No SendMessage required. |

**SEED-DRIFT canonicalization (three codes, pin everywhere):** `SEED-DRIFT-MECHANICAL` (conductor self-handles — amend seed, re-fire MESH), `SEED-DRIFT-SUBSTANTIVE` (conductor cannot self-handle: SOLO→surface to operator, TEAMMATE→`SendMessage(halt_code: SEED-DRIFT-SUBSTANTIVE)` to root), and `SEED-DRIFT-DETECTED` (root-side triage name in shepherd.md for the incoming SEED-DRIFT-SUBSTANTIVE). Replace bare `SEED-DRIFT` in planter.md:351, pipeline.md:126.
**`DEV.LAST-NO-GRANT`:** add inline meaning ("operator must confirm release grant via sprint-completion signal before CLOSE-FINALIZE proceeds").

### `agents/shepherd.md §Halt codes (root-side)` — add triage rows
For each teammate-surfaced code above (TASK-LANE-MISMATCH, TEAMMATE-ARTIFACT-WRITE, TEAMMATE-LOCK-ATTEMPT, TEAMMATE-FLAG-MISUSED, TEAMMATE-BOOT-MALFORMED, SPECIALIST-UNCLEAR, SPECIALIST-UNAVAILABLE) + `SEED-DRIFT-DETECTED`. Mirror the meaning + the root action.

---

## WAVE A — executable + canonical tables (author + VERIFY by running)

### A1 — CRITICAL: 0007 never migrated + repair  *(code-style: shell/sql)*
1. `git mv skills/context/schema/0007_canonical_state.sql skills/context/schema/migrations/0007_canonical_state.sql`.
2. In the moved file: make idempotent — `CREATE TABLE IF NOT EXISTS` for all 7 tables; `DROP VIEW IF EXISTS <v>;` before each `CREATE VIEW`. **Remove** the self-inserted `INSERT INTO schema_versions (...) VALUES (7,...)` line (the runner inserts it).
3. Delete `skills/context/schema/migrations/0007.md` (placeholder) OR convert to a `--` comment header in the SQL.
4. **`cmd_migrate.sh` repair:** change the apply predicate from `(( v > current ))` to **gap-fill** — apply any `migrations/NNNN_*.sql` whose `version` is NOT already present in `schema_versions` (`SELECT 1 FROM schema_versions WHERE version=$v`). This repairs DBs stuck at v8-missing-v7 (and the dogfood DB at v7-missing-v8). Keep ascending order.
5. **Verify:** temp-DB `shctx init` → `shctx migrate` → assert all 7 v7 tables + 0008 worktrees exist; `bash skills/context/tests/run.sh` green.

### A2 — HIGH: `shctx sprint open` broken (locks_history CHECK)  *(code-style)*
New migration `skills/context/schema/migrations/0009_locks_mode_sprint.sql`: recreate `locks_history` with the mode CHECK expanded to include `'sprint'` and `'spawn'` (SQLite CHECK change = create-new + copy rows + drop + rename, inside a txn; preserve all columns/indexes). No self-insert schema_versions. Fix `tests/test_sprint_pipelines.sh` to assert `lock:    acquired`.
> **Feature renumber:** the #94 `sprint_metrics` migration moves to **`0010_sprint_metrics.sql`** (update the self-improvement spec).

### A3 — canonical halt tables (author the cross-file core)
`agents/conductor.md §Halt codes` (add Tier column + roster above + Q1–Q3→Q4 on line 32) and `agents/shepherd.md §Halt codes (root-side)` (triage rows). Author these myself — every Wave-B file references them.

### A4 — MEDIUM/LOW executable  *(code-style)*
- `skills/context/schema/views/canonical-types.sql` → sync to 0003 (`WHERE s.kind IN ('struct','enum','trait','class','interface','type-alias')`) + "reference copy only" comment.
- `skills/context/scripts/cmd_query.sh` → when an optional `:param` is unsupplied, strip the predicate (or bind explicit NULL with `(:p IS NULL OR col=:p)` semantics that actually work under the CLI). Fixes `cache-usage.sql --sprint` zero-rows.
- `hooks/tests/run.sh` → wire in `test_worktree_lifecycle.sh` (pattern of `test_dispatch_guard.sh`).

---

## WAVE B — doctrine/doc fan-out (file-disjoint coders; pinned vocab above)

| File | Fixes (passover refs) |
|---|---|
| `commands/spawn.md` | line 396 `#13–#17`→`#13–#20`; line 186 `§Agent Teams` ref → point to the in-file setup or new configuration.md section; apply `--auto` policy (drop removal text). |
| `commands/start.md` | ensure TEAMMATE-FLAG-MISUSED / TEAMMATE-BOOT-MALFORMED match the now-canonical roster names. |
| `agents/engineer.md` | line 196 `§V.2`→`§II.1`. |
| `agents/planter.md` | line 155 `§VIII-bis` dangling → inline the GitHub-leverage discipline (patch-milestone rules) into the checklist item; line 351 SEED-DRIFT→SEED-DRIFT-SUBSTANTIVE. |
| `agents/coder.md` | confirm `SCOPE OVERFLOW` (space); purge any PAUSE residue. |
| `agents/auditor.md` | MODE-MISMATCH / WORKTREE-DRIFT now in conductor table — align references. |
| `skills/shepherd/references/agent-briefs.md` | **PAUSE purge** (99,135) — the injected coder brief; SCOPE OVERFLOW form. |
| `skills/shepherd/references/branching-model.md` | SCOPE OVERFLOW form (316). |
| `skills/shepherd/doctrines/flock-cohesion.md` | PAUSE purge (§III). |
| `skills/shepherd/doctrines/dispatch-cascade.md` | PAUSE retired in frontmatter+§VI. |
| `skills/shepherd/doctrines/specialist-dispatch.md` | PAUSE (340); SPECIALIST-* now in conductor table. |
| `skills/shepherd/doctrines/brief-cache-discipline.md` | PAUSE (101) + SCOPE OVERFLOW form. |
| `skills/shepherd/doctrines/adaptation-loop.md` | PAUSE residue (178 tag retired; 189 await-edge replacement). *(Feature rewrites this later — minimal touch now.)* |
| `skills/shepherd/doctrines/agent-excellence.md` | SCOPE OVERFLOW form. |
| `skills/shepherd/doctrines/claude-code-platform-alignment.md` | **CRITICAL #2:** §II task-list row owner → DUAL; §V TaskCreated/TaskCompleted → "Consumed for lane routing + wave-gate enforcement (v6.0.3 #100/#102)"; note shepherd uses TaskCreate/TaskUpdate + the `wave-{N}-gate-{sprint_slug}` marker. |
| `skills/shepherd/doctrines/spawn-escalation.md` | **CRITICAL #3:** §II — correct the phantom: TaskCreated/TaskCompleted are NOT registered hooks; root routes by the `"{lane_id}: "` title prefix observed via `TeammateIdle` / `SendMessage` WAVE-COMPLETE payloads. §VI P0 → reference the new Tier column. frontmatter `updated: v6.0.3`; annotate v6.0.3 additions inline; `planter`→`root shepherd (or planter when delegated)`. |
| `skills/shepherd/doctrines/lane-task-ownership.md` | line 17 phantom-hook correction (own #102 file) — same as spawn-escalation. |
| `skills/shepherd/doctrines/workflow-compile-down.md` | frontmatter `status: evaluation`→`binding`, `targets`→`since: v6.0.1`; §XI invert "no compile path ships" → "compile-down IS the primary path (v6.0.1 #76); hand-rolled dispatch is fallback"; fold the inline callout. |
| `skills/shepherd/doctrines/scope-scale-workload.md` | §V `--auto` removal promise → alias policy. |
| `skills/shepherd/doctrines/README.md` | **add the 20 missing index rows** (dispatch-tier-separation, root-shepherd-orchestration, primitive-axis-binding, dispatch-cascade, spawn-escalation, scope-scale-workload, sqlite-canonical-state, claude-code-platform-alignment, specialist-dispatch, invariant-enforcement-matrix, flock-cohesion, agent-excellence, brief-cache-discipline, cache-telemetry, cargo-sequential-gates, dir-watch, plugin-reload-escape, seed-naming, version-scale-roadmap, workspace-member-isolation-gate). |
| `CLAUDE.md` | line 9 + line 21 meta-count→three (+ add `shepherd` to layout); line 18 marketplace source = `{"source":"github","repo":"FL03/shepherd"}`; line 36 planter "retired redirect" (drop "5-line"); line 104 hooks "As of v6.0.3" + Write variant + TaskCreated/Completed not-handled note. |
| `README.md` | header command box + ctx/cleanup; file map rows 323/325/326 (commands incl. ctx/cleanup; agents 6 domain + 3 meta; planter redirect note). |
| `skills/shepherd/SKILL.md` | line 433 meta-count→three; add `/shepherd:cleanup` trigger. |
| `skills/context/references/schema.md` | add the 7 v5.1.7 tables+views; `.artifacts/`→`.shepherd/` paths; remove/mark "deferred sprints (0003_sprints.sql)" (nonexistent). |
| `skills/context/SKILL.md` | canonical-table list (61–65) += 7 v5.1.7 operational tables (split core/operational rows). |

## Hooks LOW (defer — need platform confirmation, do NOT guess)
type:agent `model` field + `if:` glob-vs-tool semantics → file as a tracked note/issue; do not edit blind.

## WAVE C — verify + commit + push
`bash skills/context/tests/run.sh` + `bash hooks/tests/run.sh` green; halt-code grep (referenced⊆defined); doctrine index complete (50/50); meta-count grep; PAUSE-FOR-DEPENDENCY only in retired-context; `shctx migrate` on temp DB applies 0007+0008+0009. Commit per concern-group, push to `v6.0.3`.
