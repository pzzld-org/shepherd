---
title: v6.4.5 close audit — datastore-state
date: 2026-08-14
auditor: shepherd:auditor (datastore-state)
sprint: v6.4.5
concern: datastore-state
mode: close
methodology: superpowers:systematic-debugging (falsify, don't confirm) — every finding below is grounded in a command actually run, not a file merely read, per the brief's own evidentiary bar
prior_class_priors: registry empty at start of this cycle (`shctx adapt priors --lessons` returned nothing) — framework priors applied, no sprint-history weighting available
---

## Scope reviewed

- `crates/registry/src/migrate.rs`, `migrate/runner.rs`, `migrate/embedded.rs`, `tests/default.rs` — the 21-migration Rust port and its `sqlite_master` parity surface.
- `skills/context/schema/migrations/**` vs `crates/registry/src/migrate/sql/**` (vendoring drift).
- Every `hooks/scripts/*.sh` and `skills/context/scripts/*.sh` file that interpolates a shell value into a SQL string (grep-swept, then individually classified) — 25+ files inspected, ~120 interpolation sites read.
- `.shepherd/dispatch/v6.4.5/*.json` (all 64 records) — `agent_role`/`declared_source` provenance.
- `services/cli/shepherd_cli/models_run.py` (`run.json` atomic-write, canonical-JSON, `extra="allow"`) and its CLI callers in `commands/run.py`.
- `packages/harness-claude/src/guard-serve-broker.mjs` (socket-broker `/tmp` lifecycle) and `skills/context/scripts/cmd_prune.sh` / `services/cli/shepherd_cli/commands/prune.py` (dispatch/log/snapshot sweep, and its absence for run dirs).
- GH #285 (the tracked broken-escape issue) and its actual fix state at HEAD.

Method: for every claim below, either a command was run against a **throwaway copy** of the live registry DB or a **scratch, out-of-tree** reproduction (never the tracked repo state), or the repo's own code was executed read-only (never edited) against a synthetic payload in an isolated `SHEPHERD_WORKDIR`. No source file in this repo was modified at any point in this audit.

## Findings summary

| # | Severity | One-line | GH |
|---|---|---|---|
| 1 | CRITICAL | `run.json` has no write-serialization; concurrent lane registration silently loses a lane | #294 |
| 2 | CRITICAL | `cmd_teammate.sh` `status`/`retire` interpolate an unescaped name into SQL — proven exploitable | #295 (= DF-50, previously untracked in GH) |
| 3 | HIGH | The broken `${v//\'/\'\'}` idiom #285 called "duplicated three times" actually recurs live in 20 sites / 8 files | #296 |
| 4 | MEDIUM | `cmd_report.sh` — 5 CLI flags interpolated into SQL with **zero** escaping, UNION-exfiltration proven | #297 |
| 5 | LOW (informational) | DF-77's writer fix is correct in-tree but has never fired in production this sprint — installed plugin cache is pinned at v6.4.4 | not filed (structural, not a code bug) |
| 6 | LOW | `.shepherd/runs/<id>/` has no prune/archive path at all, unlike dispatch/logs/snapshots | not filed (currently 6.5M / 7 dirs, no urgency) |

Plus one clean, independently-verified area: the Rust/Python `sqlite_master` schema-parity surface (see Verifications).

## Findings

### 1. CRITICAL — `run.json` concurrent-writer lost-update race (no locking anywhere)

**Hypothesis:** `run.json`'s persistence layer protects against a crashed single writer (atomic tempfile+replace) but has no serialization for concurrent writers, so two lanes registering/updating around the same moment can silently lose one side's update.

**Falsification:** Seeded a fresh `run.json` via `save_run()` in a scratch workdir. Launched two real, barrier-synchronized OS processes (`services/cli/.venv/bin/python`, not threads — real interleaving) that each `load_run("race00")`, sleep inside the critical section, append a distinct `LaneState`, then `save_run()`:

```
lane-alpha: saved, in-memory lanes at save time = ['lane-alpha']
lane-beta:  saved, in-memory lanes at save time = ['lane-beta']
=== final run.json lanes ===
['lane-beta']
```

Both processes' in-memory view proves they read the same pre-write (empty) state concurrently — no observer effect. The final on-disk file holds only the last writer's stale view; `lane-alpha`'s registration vanished with no exception, no warning, exit 0 on both sides. Grepped `models_run.py` and every caller in `commands/run.py` for `flock`/`fcntl`/`filelock`/`import.*lock`: zero hits. Grepped `test_run.py`/`test_run_claim.py` for `concurren`/`race`/`threading`/`multiprocess`/`Popen`: zero hits — untested.

**Confidence:** HIGH — fully reproduced on demand, mechanism understood, no serialization exists anywhere in the code path.

**Why it matters:** the module's own docstring cites `RunState.missing_declared_lanes` as the DF-63 fix ("BLIND to a lane that was never `run lane add`-ed at all"). DF-63 closed the case where the call was never made. This race reopens the identical hole under concurrency **even when the call was made** — twelve waves of concurrent lane activity is exactly the load profile v6.4.5 itself ran under. Filed as #294.

### 2. CRITICAL — `cmd_teammate.sh` `status`/`retire`: unescaped `$name`, proven exploitable

**Hypothesis:** two of six `cmd_teammate.sh` subcommands never adopted the file's own `esc()` helper.

**Falsification:** copied `.shepherd/shepherd.db` to a scratch file (never the live DB). `SHCTX_DB=<copy> bash cmd_teammate.sh retire "nonexistent' OR '1'='1"` retired **all 6** teammate rows (verified via `SELECT` before/after), not the nonexistent named one. `SHCTX_DB=<copy> bash cmd_teammate.sh status "does-not-exist' OR '1'='1"` returned an arbitrary row — classic `WHERE`-bypass via `' OR '1'='1`.

**Confidence:** HIGH — live exploit reproduced twice, against a throwaway copy.

**Why it matters:** this is `.shepherd/runs/v645/dogfood.md` DF-50, logged MEDIUM and tagged FIX-THIS-RUN, and it is **still unfixed at HEAD b57d495** — the fix slipped. I escalate the severity: DF-50 reasoned exploitability away as "teammate names are framework-generated today," but the `name` argument is attacker-reachable at the CLI directly regardless of provenance, and a single crafted argument silently corrupting the entire live teammate registry is proven, not hypothetical. No GH issue existed for this before now. Filed as #295.

### 3. HIGH — the broken escape idiom GH #285 called "duplicated three times" recurs live in 20 sites / 8 files

**Hypothesis:** #285's own triage undercounted this defect class; the same broken `${v//\'/\'\'}` pattern (backslashes IN the replacement — inserts a literal `\` instead of doubling the quote) is still live elsewhere.

**Falsification:** Python regex scan (`//\\'/\\'\\'`, comment lines excluded) over every `*.sh` in the repo found 20 live occurrences across 8 files never named in #285: `precompact_snapshot.sh`(1), `teammate_heartbeat.sh`(3), `coordinate_drive_guard.sh`(3), `teammate_git_guard.sh`(2), `conductor_write_guard.sh`(1), `cmd_eval.sh`(9), `cmd_prune.sh`(1). Confirmed cmd_adapt.sh/cmd_loop.sh (#285's named sites) and `dispatch_guard.sh`'s `sql_lit()` are correctly fixed — clean.

Broke real `sqlite3` three independent ways:
- `cmd_prune.sh`'s `cur_esc` on a branch name with an apostrophe (git allows `'` in ref names — confirmed via `git check-ref-format --branch "foo'bar"`, exit 0) → `Error: in prepare, unrecognized token: "\"`.
- `teammate_heartbeat.sh`'s `esc` on a session-id shape with an apostrophe → same parse error, inside a `PreToolUse` hook that fires on **every tool call**.
- `cmd_eval.sh`'s `ra_esc` fed an **ordinary, non-adversarial** LLM-judge rationale (`"The response doesn't fully address the user's question."`) → same parse error.

`hooks/tests/test_sql_escaping.sh` — the regression test #285 shipped — exercises only `cmd_adapt.sh`/`cmd_loop.sh`; never extended to the other 8 files sharing the identical pattern.

**Confidence:** HIGH — mechanism proven on three independent sites via a real `sqlite3` parse; the site inventory is a deterministic grep, not a sample.

**Why it matters:** `cmd_eval.sh`'s site is the standout — `rationale` is `jq -r '.rationale'` straight from the judge model's own verdict JSON, so `shctx eval run --record` will crash (loud, via `set -eu`, not silent corruption) on a large fraction of ordinary English judge output, directly undermining the eval-recording pipeline CLAUDE.md's own doctrine depends on. Secondary: `coordinate_drive_guard.sh`'s own comment documents its fallback as intentionally **"fail-open... if the query errors"** — the exact bug class this sprint's dominant defect theme (a check whose precondition the runtime never supplies) targets, though current exploitability there is low since `session_id` is a Claude-Code-generated UUID, not attacker-shaped text. Filed as #296; commented on #285 to scope it to its original two sites and cross-reference the broader recurrence.

### 4. MEDIUM — `cmd_report.sh`: 5 CLI flags interpolated into SQL with zero escaping

**Hypothesis:** unlike the #285 class (broken escaping), this file has **no** escaping call anywhere — a different, previously-unflagged gap.

**Falsification:** against a throwaway DB copy, inserted a canary row (`mem_entries.title='SECRET-CANARY'`), then `SHCTX_DB=<copy> bash cmd_report.sh discovery --run="zzz' UNION SELECT 'LEAK','LEAK', body, NULL FROM mem_entries WHERE title='SECRET-CANARY' --"` rendered the canary's body verbatim into the discovery report — cross-table exfiltration via one CLI flag. `$sprint`/`$concern`/`$sev` (audit) and `$team` (teammates) share the identical unescaped-interpolation shape.

**Confidence:** HIGH — reproduced end-to-end through the real markdown-rendering path.

**Why it matters:** all four call sites are `SELECT`-only, so impact is read/exfiltration, not corruption — any row in the registry is reachable via a crafted flag. Not in `dogfood.md`'s DF list; a genuinely new finding, not a recurrence of a tracked one. Filed as #297.

### 5. LOW (informational) — DF-77's fix is correct in-tree but has never executed during this sprint's own dogfood run

**Hypothesis:** production dispatch records cannot demonstrate DF-77's fix, because the *installed* Claude Code plugin lags the branch being audited.

**Falsification:** all 64 records in `.shepherd/dispatch/v6.4.5/*.json` carry `agent_role: "unknown"` and the old (pre-fix) schema — including the **one** record (`toolu_018UXQLuNPjE2CUEHrr5XDKu.json`) written *after* the DF-77 fix commit (`6f2eaa9`, epoch 1786679622) landed; its own `sprint_branch_recorded` is `6f2eaa9`'s exact SHA. `/Users/jo3/.claude/plugins/cache/shepherd/shepherd/` contains only a `6.4.4/` directory; diffing its `hooks/scripts/agent_invocation_tagger.sh` against the repo's own confirms it is the pre-fix (prompt-header-grep) version. Directly invoking the repo's **own** fixed script against a synthetic payload in an isolated `SHEPHERD_WORKDIR` confirmed the in-tree fix is correct: `agent_role` resolved to `"auditor"` with the full new schema (`declared_tools`, `declared_source`, `session_id`, `observed_*`) populated.

**Confidence:** HIGH on the mechanism (plugin-cache pin confirmed by direct file diff); this is not a code defect, so no severity beyond LOW/informational and no GH issue filed.

**Why it matters:** every dispatch record written during v6.4.5's actual live execution — all 64, including this very close-swarm's own dispatches — was produced by the stale hook. Any completeness check reasoning "no new `agent_role:unknown` records since W11 landed" would be measuring plugin-cache lag, not the fix. Left for the `completeness` auditor to weigh against DF-77's FIXED-THIS-RUN claim; I record only the datastore-state mechanism (what the dispatch records themselves show).

### 6. LOW — `.shepherd/runs/<id>/` has no prune/archive mechanism

**Hypothesis:** unlike dispatch dirs/logs/snapshots, run directories accumulate with no sweep path at all.

**Falsification:** `services/cli/shepherd_cli/commands/run.py` defines 20 `@app.command`s (`init/rename/canonicalize/show/list/claim/migrate/set/lane add/lane set/wave accept/wave merged/wave pending/ledger path/ledger check/wave verify/layout`) — none named prune/archive/gc/delete. `cmd_prune.sh` explicitly sweeps `dispatch/<sprint>/` (age-gated, default 30d), logs, and snapshots, and never mentions `runs/`. `.shepherd/runs/` in this repo currently holds 7 dirs (`v500`, `v512-dev0`, `v514`, `v516`, `v517`, `v641-dev0`, `v645` — 6.5M total), none ever removed.

**Confidence:** HIGH on the absence (exhaustive command enumeration); LOW severity purely on current size — not an active problem yet.

**Contrast — what DOES clean up correctly:** the socket broker (`packages/harness-claude/src/guard-serve-broker.mjs`) is well-designed: idle-timeout triggers `shutdown()` which unlinks its `/tmp/shepherd-guard-*.sock`, and `bindSocket()` self-heals a stale leftover on the *next* start (probe-connect; ECONNREFUSED/ENOENT → unlink before rebind) — read the implementation, no finding there.

## Verifications

**The registry/Python migration parity CAN fail, and currently doesn't.** `crates/registry`'s `sqlite_master_dump_detects_a_missing_migration` negative-control test already proves the parity assertion is falsifiable (a schema missing 20 migrations does not byte-match the frozen fixture) — ran `cargo test -p shepherd-registry --lib` (isolated `CARGO_TARGET_DIR`, targeted, not workspace-wide) and got `test result: ok. 10 passed; 0 failed`, including that negative control and `sqlite_master_matches_the_frozen_python_capture`.

I additionally built an **independent** falsification never reusing repo test code: a from-scratch Python `sqlite3` dumper (not `conformance/lib/harness.py`, not the Rust runner) applying `crates/registry/src/migrate/sql/{0001_init.sql,migrations/*.sql}` in order and dumping `sqlite_master` in the same `type\tname\ttbl_name\tsql\n` shape. It matched `conformance/cases/guard-cli/status/ok/expected/sqlite_master.txt` byte-for-byte. I then mutated a **scratch copy** of the vendored SQL (never the repo's own files) two ways — skipping `0018_eval_runs.sql` entirely, and renaming the `artifacts_ai` trigger — and both mutations produced a real, expected diff against the frozen fixture. The assertion is genuinely load-bearing, not a gate-that-cannot-fail. `vendored_copies_match_source` (also green) independently confirms `crates/registry/src/migrate/sql/**` is byte-identical to `skills/context/schema/**` (only difference: a `.gitkeep`), so "Rust and Python schemas still agree" holds on both the DDL-source axis and the applied-schema axis.

**`run.json`'s three documented write guarantees hold, individually.** `extra="allow"` is set on both `RunState` and `LaneState` (`ConfigDict(extra="allow")`, `models_run.py:594,616`) — per #247, unknown keys round-trip. `atomic_write_json` (`models_run.py:751`) does exactly tempfile-in-target-dir → fsync → `os.replace` → fsync(dir), matching its docstring; `json.dump(..., sort_keys=True)` sorts recursively (Python's `json` module applies `sort_keys` at every nesting level, not just top-level). Only the FOURTH, unstated property — safety under concurrent writers — fails (Finding 1); the docstring itself never claims it ("a crashed writer never leaves a torn file" is the actual, narrower claim, and it's true).

**`teammate_idle.sh` and `worktree_lifecycle.sh` use the CORRECT escaping idiom, despite superficially resembling #285's broken form.** Empirically distinguished the two forms (`${v//\'/''}` — correct, no backslash in the replacement — vs `${v//\'/\'\'}` — broken): `bash -c 'TEAMMATE="o'"'"'brien"; echo "${TEAMMATE//\'"'"'/'"'"''"'"'}"'` → `o''brien` (valid SQL), confirmed against a real `sqlite3 :memory:` INSERT/SELECT round-trip. Both files are clean; not findings.

## Open questions

- Whether `RunState.missing_declared_lanes` (the DF-63 check) runs at a point in the wave-gate pipeline where it would actually observe Finding 1's dropped-lane race in practice, or whether the gate that reads `run.json` runs so much later than the concurrent registration window that the race is already resolved by the time anything checks — I did not trace the full wave-gate call graph to confirm timing overlap; the persistence-layer race is proven regardless, but its downstream blast radius depends on gate-check timing outside this concern's scope.
- Whether `cmd_report.sh`'s CLI flags are ever populated from anything other than a trusted operator's own terminal input in current usage (vs. e.g. a future automation piping an external string through `--sprint=`) — the injection is proven reachable at the CLI surface itself either way, but "who actually calls this with untrusted input today" is a completeness/usage-pattern question outside what I verified.

## Pattern delta

No prior-sprint `datastore-state` audit exists in the registry (`shctx adapt priors --lessons` returned nothing; this is the first cycle with sprint metrics recorded) — no severity-vs-prior trend available. Framework priors applied per the adaptation contract's own fallback.

**Cross-cutting observation worth flagging regardless:** three other v6.4.5 close-swarm auditors independently filed SQL-escaping findings the same day this audit ran — #291 (`cmd_init.sh`, zero escaping, proven arbitrary-SQL on a dirname), #292 (`refresh-github.sh`, escapes 4 of 7 interpolated fields, misses `labels`/`assignees`/`milestone`), plus this report's own #294–#297. Combined with #285's original two sites, the SQL-escaping-discipline gap now spans at least **7 distinct GH issues touching 12+ files** discovered in a single sprint's close audit. `Systemic risk: 3+ HIGH/CRITICAL in same concern across 3+ sprints` does not literally apply (this is the first sprint with the check even running), but the SAME class recurring 12+ times *within one sprint*, across four independent auditors, after the fix for the first instance (#285) was already believed to have closed the pattern, is exactly the shape that flag exists to catch. Recommend: consolidate `esc()`/`sql_lit()` into `_lib.sh` (already flagged as a deferred follow-up in both fixed files' own comments) and add a repo-wide static check — grep for the broken byte pattern, and for any `sqlite3`/`shctx_sql` call whose SQL string contains a bare `'$` not immediately preceded by a call to the shared helper — as a gate test, not a manual sweep, so the fourteenth instance can't land the same way the second through thirteenth did.

## Cache telemetry

`shctx query cache-usage --sprint=v6.4.5 --md` was not run — out of this concern's scope (belongs to the `completeness` auditor per the brief's own concern table; datastore-state's brief does not ask for it and I have no basis to assert a view is absent or present without running it).

## Grade

n/a (mode: close, but per the audit contract the numeric/letter grade is assigned holistically across all concerns by the conductor's close synthesis, not per-concern here — this report supplies the datastore-state findings input to that synthesis)

## Grade rationale

Two CRITICAL, one HIGH, one MEDIUM, two LOW findings. The dominant pattern is not any single bug but the SQL-escaping-discipline gap recurring 12+ times across a single sprint despite an early, believed-complete fix (#285) — a SUBTRACT-relevant signal: this sprint added a guard engine, a conformance corpus, and three harness adapters (net-positive per the intro), but the same defect class it explicitly tried to eradicate mid-sprint (#285) grew rather than shrank by close, and one already-logged, FIX-THIS-RUN-tagged defect (DF-50) slipped entirely unfixed. The registry/migration-parity surface (this concern's other major area) is genuinely clean, independently verified two ways. `run.json`'s concurrent-write gap (Finding 1) is a new, previously-undiscovered CRITICAL with no mitigating factor — it is silent, proven, and untested.

## Output to conductor

```
## AUDITOR REPORT
- deliverable: 22 (status: delivered)
- Concern: datastore-state
- Mode: close
- Files reviewed: ~30 (registry crate: 4; shell scripts individually classified: 25+; Python models/commands: 3; JS broker: 1)
- Findings: CRITICAL=2, HIGH=1, MEDIUM=1, LOW=2
- Verifications (disproved): 4 (registry parity falsifiability; run.json's 3 stated write guarantees hold individually; teammate_idle.sh/worktree_lifecycle.sh use the CORRECT idiom despite resembling #285's broken form; socket-broker /tmp lifecycle is clean)
- Open questions: 2
- GH issues filed: #294, #295, #296, #297 (+ comment on #285)
- Grade: n/a (close mode; conductor synthesizes across concerns)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/close-datastore-state.md
- Hot-fix-lane recommendations: 2 (Finding 1 run.json lock; Finding 2 cmd_teammate.sh esc() — both CRITICAL, both a one-file, low-risk patch + a regression test, both directly reproducible with the commands in this report)
- Sprint-pattern entry: written (see Pattern delta — cross-cutting SQL-escaping-discipline observation)
- Agent ID + timestamp: shepherd:auditor(datastore-state) @ 2026-08-14T09:45:31Z
```
