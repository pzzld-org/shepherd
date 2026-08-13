---
title: Wave-review audit — guard-fail-closed (W2, dispatch_guard.sh Checks 7/8 + cmd_teammate.sh)
date: 2026-08-13
auditor: shepherd:auditor
sprint: v645
concern: guard-fail-closed
mode: wave-review
methodology: superpowers:systematic-debugging (falsify, don't confirm) — every claim below is
  backed by a command actually run against the real worktree file (or an isolated mirror of it
  for mutation testing), not by reading the diff.
---

## Scope reviewed

Uncommitted diff in `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards` (branch
`agent-v645-l6-guards`, HEAD `ada05dd3b749956e4aeeaf8bf2eedc1ca5b14930`):

- `hooks/scripts/dispatch_guard.sh` (+190) — Check 7 `AUDIT-CONCERN-UNDECLARED` (deny), Check 8
  `DISPATCH-OWNERSHIP-RECORD` (observer), relocated above Check 6; `PRAGMA journal_mode=WAL;
  PRAGMA synchronous=NORMAL;`.
- `hooks/tests/test_dispatch_guard.sh` (+211/-1)
- `skills/context/scripts/cmd_teammate.sh` (+12/-7, **and a file-mode change 100755→100644**)
- `skills/context/tests/test_cmd_teammate.sh` (+29)

All testing below was run either directly against the real files in the worktree (read-only —
piping crafted stdin in, never writing) or against byte-identical mirrors copied into
`/private/tmp/.../scratchpad/guard-audit/` for mutation testing, so the worktree is never
touched by a mutation. Verified clean at the end: `git diff --stat` in the worktree is
unchanged from the start of this audit (4 files, same insert/delete counts).

## Q1 — REACHABILITY

**Physical layout (verified by reading, then proven by execution):** Check 7 is at
`dispatch_guard.sh:274-311`, Check 8 at `:313-436`, Check 6 at `:438-484` — i.e. Check 6 now
sits **after** 7 and 8. The file executes top-to-bottom with first-match-wins (`emit_deny`/
`emit_context`/`pass_silent` all end in `exit 0`), so this ordering is the only thing that
matters for reachability.

**Enumerated short-circuits ahead of Check 7/8** (checks 1-5): Check 1 (missing/`general-
purpose`/`Explore`/`Chat` subagent_type), Check 2 (teammate + `team_name` set), Check 3
(`team_name` set + role ≠ conductor), Check 4/4' (teammate dispatching `@engineer`/un-marked
`@critic`), Check 4b (`@engineer` subagent with `mode: self-contained`), Check 4c (marked
engineer-self-contained dispatch to a non-{discovery,auditor,critic} role), Check 5 (off-flock
`shepherd:x`). None of these can fire for a legitimate `shepherd:auditor` dispatch **unless**
`team_name` is also (incorrectly) set on it — in which case Check 2/3 correctly take priority
over Check 7, since a malformed team_name/role pairing is a more fundamental error than an
undeclared concern. This is correct prioritization, not a masking bug.

**Live proof the reorder fix holds**, driven with crafted stdin against the real
`hooks/scripts/dispatch_guard.sh`:

```
$ PAYLOAD='{"session_id":"sA","cwd":"<repo>/.worktrees/lane-a","tool_name":"Agent",
  "tool_input":{"subagent_type":"shepherd:auditor","prompt":"Review the auth module and
  also the DB migration and also the frontend routing."}}'
$ printf '%s' "$PAYLOAD" | dispatch_guard.sh
{"permissionDecision":"deny","message":"[shepherd] AUDIT-CONCERN-UNDECLARED — refused. ..."}
```

A teammate-topology (`.worktrees` cwd) `shepherd:auditor` dispatch with a bundled, zero-
`[CONCERN]` prompt — the exact DF-44 shape — is correctly denied by Check 7, not silently
absorbed by Check 6. Also verified: Check 6 still fires correctly for the role it targets
(`shepherd:coder`/`shepherd:auditor` in teammate mode) **and** Check 8 still records its
ownership row for that same dispatch before Check 6 exits:

```
$ printf '%s' '{"session_id":"sB","cwd":".../.worktrees/lane-b","tool_name":"Agent",
  "tool_input":{"subagent_type":"shepherd:coder","model":"sonnet","prompt":"implement the fix"}}' \
  | dispatch_guard.sh
{"additionalContext":"[shepherd] PRIMITIVE-INVERSION (flag) ..."}
$ sqlite3 .shepherd/shepherd.db "SELECT session_id,subagent_type,model,lane,tool FROM dispatch_ownership WHERE session_id='sB';"
sB|shepherd:coder|sonnet|lane-b|Agent
```

Also verified the `engineer-self-contained` marker does not accidentally shield an auditor
dispatch from Check 7 via Check 4c (4c only blocks non-{discovery,auditor,critic} targets, so
`shepherd:auditor` correctly falls through to 7), and that mixed-case `subagent_type` (e.g.
`Shepherd:Auditor`) is normalized via `st_lc` before every check, including 7.

**Verdict on Q1: no remaining pre-emption. The specific defect this audit was commissioned to
re-check — Check 6 exiting before 7/8 could run in the `.worktrees` teammate topology — is
fixed and reachability is confirmed by direct execution, not just by reading the line numbers.**
See Q4 for the mutation-testing proof that this exact regression class is now caught by the
suite.

## Q2 — FAIL-CLOSED

| Input | Behavior | Fail-closed? |
|---|---|---|
| Malformed JSON (truncated/invalid) | `json_field` returns empty for **every** field including `.tool_name`; the top-of-file `case "$tool" in Agent\|Task) ;; *) exit 0 ;; esac` gate then treats the empty tool name as "not Agent/Task" and exits with **zero checks run**, no deny, no context, nothing on stdout. | **NO — fail-open.** Reproduced live: a malformed payload carrying `subagent_type: "general-purpose"` (Check 1's own textbook denial case) and separately one carrying `subagent_type: "shepherd:evil"` (Check 5's case) both sail through completely ungated (`exit=0`, empty stdout). **Confirmed pre-existing**: the identical gap exists in the `HEAD` (pre-diff, committed) copy of the file — this diff neither introduces nor worsens it, and it applies uniformly to all 8 checks, not specifically to 7/8. Flagged because Q2 asked directly, and because the header's claim that Check 7 is "LOAD-BEARING and MECHANICAL" is only true for well-formed JSON. |
| `jq` absent (PATH built with every `/usr/bin/*` binary except `jq` symlinked in, `python3`+`sqlite3` present) | `json_field` falls back to the `python3` branch. Verified Check 1 (`general-purpose` → `DISPATCH-MISSING-SUBAGENT-TYPE`) and Check 7 (auditor, zero `[CONCERN]` → `AUDIT-CONCERN-UNDECLARED`) both still deny correctly. Check 8's own SQL-literal building does not use `jq` at all (only `json_field` does, for `tool_use_id`/`model` extraction), and its write still succeeded and the row was recorded (`sNJ3\|shepherd:coder`). | **YES — fail-closed maintained**, both for the deny checks and for Check 8's degrade-and-continue design. |
| Registry DB present but a corrupt (non-SQLite) file | `sqlite3` fails with `file is not a database (26)`; Check 8 emits `additionalContext` ("registry write failed... Dispatch PASSED WITHOUT the ownership record — this observer NEVER blocks") and passes. No crash, no deny. | **Correct by design** — Check 8 is documented as a pure, never-denying observer; this is fail-*visible*, not fail-closed, which is the intended contract for this specific check. |
| Registry DB locked by a concurrent writer (`BEGIN IMMEDIATE` held for 8s by a second `python3`/sqlite3 connection while the guard tries to write) | Guard's `PRAGMA busy_timeout=5000` waits, then gives up with `database is locked (5)`, emits the same degrade warning, and passes. Measured wall-clock: **exactly 5s** before the guard released control. | Correct (never denies), but see Q3 — this is a genuine, measured **latency** cost on every dispatch under registry contention, worth a MEDIUM note. |
| `cwd` field entirely absent from the JSON (not empty-string, the key itself missing) | Well-formed `shepherd:auditor` + one `[CONCERN]` dispatch passes silently as expected; `lane` column recorded as SQL `NULL` (not fabricated, not defaulted to something plausible-looking). | **Correct.** |
| `tool_input` missing `subagent_type` entirely (key absent, not empty string) | `json_field` returns empty, `st_lc=""` matches Check 1's `""` case exactly the same as an explicit empty string would → `DISPATCH-MISSING-SUBAGENT-TYPE` deny. | **YES — fail-closed.** |

## Q3 — WAL/synchronous under a concurrent writer

`grep -rn "dispatch_ownership"` across the repo shows **zero other consumers** — Check 8 is a
pure write sink; nothing in this codebase reads `dispatch_ownership` back to make a decision, and
Check 8 itself never re-reads what it just wrote. So there is **no code path where a stale WAL
read could change a guard's decision** — the pragmas can only affect (a) latency and (b)
durability-on-crash of the forensic rows themselves, never correctness of a deny/allow verdict.

Measured effects:
- **Latency**: under an actual held write lock (see Q2 table), the guard's own dispatch call
  stalls up to `busy_timeout=5000` (measured 5.0s) before degrading. This is a real, user-visible
  cost added to every `Agent`/`Task` dispatch under contention — not a fail-closed violation
  (still passes, per design), but a MEDIUM operational finding worth tracking, since a lane
  fanning out several dispatches in quick succession could each eat up to 5s if two hooks land
  on the DB at once.
- **Cross-hook compatibility**: `journal_mode` is a persistent property of the DB *file*, so once
  Check 8 sets WAL on first write, every other hook that touches the same `shepherd.db`
  (`teammate_idle.sh`, `coordinate_drive_guard.sh`, `conductor_write_guard.sh` — none of which set
  their own `journal_mode`) inherits WAL passively. Verified live that a plain `sqlite3` read/write
  against the now-WAL file (mimicking `teammate_idle.sh`'s style of query) still works with no
  special handling required (`-shm`/`-wal` sidecar files created transparently, `CREATE TABLE`
  + `SELECT` from a second connection both succeed). No raw-file-copy backup pattern exists
  anywhere in the repo that WAL's multi-file layout could break (`grep 'cp .*\.db'` — no hits).
- **`synchronous=NORMAL`** is per-connection (confirmed by reading `_lib.sh` and SQLite's own
  documented semantics — not independently re-derived here) and is only ever set by Check 8's
  own connection; every other hook's connection still defaults to `synchronous=FULL`. So the
  durability trade-off (a NORMAL commit's most recent WAL frames can be lost on a hard
  crash/power-loss, though the DB stays structurally consistent) is scoped to
  `dispatch_ownership` rows only, which — given there is no reader yet — is a low-stakes,
  correctly-scoped trade for a forensic table.

## Q4 — TEST INTEGRITY (mutation testing)

Baseline: the real, in-place suite passes **57/57** (`bash hooks/tests/test_dispatch_guard.sh`
→ `test_dispatch_guard: OK`). A byte-identical mirror (dispatch_guard.sh + _lib.sh + bash_guard.sh
+ test_dispatch_guard.sh copied into scratch, confirmed clean 57/57 baseline first) was used for
all mutations below, so **the real worktree file was never edited**.

**Mutation 1 — neuter Check 7's deny condition** (`concern_count -ne 1` → `concern_count -eq
999`, i.e. never true): 5 of 57 assertions correctly failed — all 3 `expect_block_code` zero/two-
declaration cases, the content assertion, and (critically) the `.worktrees`-cwd topology fixture,
whose output on the mutant reverted to Check 6's `PRIMITIVE-INVERSION` flag — direct proof that
without Check 7, the topology-specific fixture correctly detects the fallback to the wrong,
weaker check.

**Mutation 2 — flip Check 8's registry-write-failed path from `emit_context` to `emit_deny`**
(violating the documented "NEVER blocks" invariant): 2 of 57 assertions correctly failed (the
`expect_context` and the explicit `is_deny`-must-be-false assertion), both with the mutant's
actual deny JSON shown in the failure diagnostic.

**Mutation 3 — reintroduce the original defect**: physically moved the Check 6 block back to
*before* Check 7/8 (the exact pre-fix topology this audit exists to re-verify). Result: **exactly
2 of 57 assertions failed — both, and only, the two new `.worktrees`-cwd topology fixtures**
(`Check 7 (teammate .worktrees cwd...)` and `Check 8 (teammate .worktrees cwd): no matching
row`). All 55 other assertions, including the *root-topology* Check 7/8 fixtures, still passed.
This is definitive: it reproduces, byte-for-byte, the failure mode described in the audit brief
("the guard's own 54-assertion suite passed green" despite the bug) and proves the two new
topology-specific fixtures — and *only* those two — are what gives this regression class teeth.
Without them, this exact defect would ship green again.

**cmd_teammate.sh — reverted the 4 fixed branches to the unsafe `name="$1"; shift` form**
(mirrored the whole `skills/context/` tree into scratch first, confirmed a clean baseline `PASS:
test_cmd_teammate`): the mutated suite correctly failed (`FAIL: status with no name exit code: 1
(want 2)`). Manually reproduced the raw crash the fix eliminates, in the mutant's own directory
(so `_lib.sh` sourcing resolves correctly):
```
$ bash cmd_teammate.sh status
cmd_teammate.sh: line 183: $1: unbound variable
exit=1
```
vs. the fixed version's clean `usage(); exit 2`. All 4 branches (`register`, `heartbeat`,
`status`, `retire`) share the identical `name="${1:-}"; shift || true; [[ -n "$name" ]] || {
usage; exit 2; }` pattern already used by the pre-existing `state` branch (confirmed unmodified/
already-safe by diff inspection) — this is exactly the "match the existing idiom" move the
project's style rules ask for, and it is proven falsifiable.

## Q5 — Findings (prose asserted vs. behavior exercised)

### FINDING 1 (HIGH) — `sql_lit()`'s quote-escaping is broken; Check 8 silently fails to record any dispatch field containing an apostrophe

`dispatch_guard.sh:347`: `printf "'%s'" "${v//\'/\'\'}"`. Extracted this function **verbatim**
from the real file (`awk` range-copy, not retyped) and ran it in isolation:

```
$ sql_lit "o'brien"
'o\'\'brien'          # xxd: 27 6f 5c 27 5c 27 62 72 69 65 6e 27  →  'o\'\'brien'
```

That is a literal **backslash** inserted before each doubled quote — not the `''` SQL requires.
Reproduced end-to-end against the live, running guard (payload built with `python3 json.dumps`
to rule out any shell-quoting artifact in my own test harness):

```json
{"session_id":"sInj","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:coder","model":"o'brien"}}
```
```
$ dispatch_guard.sh < payload.json
{"additionalContext":"[shepherd] DISPATCH-OWNERSHIP-RECORD degraded — registry write failed.
  ... error: Error: in prepare, unrecognized token: \"...
  Dispatch PASSED WITHOUT the ownership record — this observer NEVER blocks."}
$ sqlite3 .shepherd/shepherd.db "SELECT * FROM dispatch_ownership;"
(no rows)
```

So: no SQL injection (the mis-escaping happens to still neutralize an adversarial `'; DROP
TABLE...--` payload by accident — table confirmed still present, zero rows inserted either way),
but a genuine **correctness** defect: any legitimate `session_id`/`subagent_type`/`model`/`lane`/
`concern_slug` containing an apostrophe silently fails to be recorded (fail-visible, not fail-
open — consistent with Check 8's "never deny" contract, so this is not a security/fail-closed
violation, but it does directly undermine the DF-44 forensic-attribution purpose Check 8 exists
to serve). **Zero test coverage** in the new 57-assertion suite exercises an apostrophe in any
recorded field.

This is not a new bug pattern — `grep` across `hooks/scripts/*.sh skills/context/scripts/*.sh`
turns up **three different escaping idioms already in this codebase**, and I tested all three
against the same input:

| Site | Pattern | Output for `o'brien` | Correct? |
|---|---|---|---|
| `dispatch_guard.sh:347` (this diff), `cmd_adapt.sh:101`, `cmd_loop.sh:101` | `printf "'%s'" "${v//\'/\'\'}"` | `'o\'\'brien'` | **NO** — spurious backslash, invalid SQL |
| `cmd_query.sh:35` | `v=${v//\'/''}` | `'obrien'` | **NO** — silently *drops* the apostrophe (worse: silent data corruption, no error) |
| `cmd_teammate.sh:24` (`esc()`) | `sed "s/'/''/g"` | `'o''brien'` | **YES** — verified round-trips correctly through a live `sqlite3` parser |

The correct idiom (`esc()`) already exists **in this same diff's own `cmd_teammate.sh`** — this
diff touches that file and does not reuse it, instead copying the broken pattern from
`cmd_adapt.sh`/`cmd_loop.sh`. Verified the fix works by testing the `esc()` idiom standalone
against both a plain and an adversarial input, round-tripped through a real `sqlite3 :memory:`
parse (`SELECT 'o''brien' AS test;` → `o'brien`; the DROP-TABLE-shaped adversarial string parses
as an inert string literal, table intact). This is a **wave-review "no reinvention" hit**:
reinventing (and this time getting wrong) something the same PR already implements correctly
two files away.

*(Informational, out of this diff's FILE-SCOPE, not a blocker here: the identical broken pattern
in `cmd_adapt.sh`/`cmd_loop.sh` is pre-existing and arguably more exploitable there, since those
handle free-text adaptation/loop notes rather than dispatch_guard.sh's mostly enum/regex-
constrained fields. Worth its own GH issue.)*

### FINDING 2 (MEDIUM) — `cmd_teammate.sh` lost its executable bit

`git diff --summary`: `mode change 100755 => 100644 skills/context/scripts/cmd_teammate.sh`.
Confirmed via `ls -la` and confirmed this is the *only* mode change across all four in-scope
files. Searched every caller in the repo (`hooks/scripts/*.sh`, `services/cli/**/*.py`,
`services/cli/tests/conftest.py`, `skills/context/tests/*.sh`, `commands/*.md`) — every real
invocation explicitly prefixes `bash` (`bash "$ROOT/skills/context/scripts/cmd_teammate.sh"`,
`["bash", str(CMD_TEAMMATE_SH), ...]`), so nothing currently breaks. It is nonetheless an
unintended regression against the file's own established convention — the original authoring
plan (`.shepherd/runs/v517/plan.md:514`) explicitly states "Make executable: `chmod +x
skills/context/scripts/cmd_teammate.sh`" — and no test in the diff asserts the mode, so a future
caller that invokes it directly (`./cmd_teammate.sh ...`, or any PATH-based dispatch relying on
the shebang) would silently break with `Permission denied`.

### FINDING 3 (MEDIUM) — Pre-existing fail-open on malformed JSON (context, not a blocker for this wave)

See Q2 table. Confirmed present in `HEAD` before this diff (ran the same malformed payload
against `git show HEAD:hooks/scripts/dispatch_guard.sh`, identical silent `exit=0`). Out of this
diff's `FILE-SCOPE` in the narrow sense (the top-of-file tool-name gate is untouched by this
diff), but directly answers a question the audit brief explicitly asked, and it means the
"LOAD-BEARING and MECHANICAL" claim in the new Check 7 header comment is conditional on
well-formed JSON reaching the script — worth a follow-up GH issue, not a redo item for this wave.

### FINDING 4 (LOW) — `[CONCERN]` counting has no quoting/context awareness

A prompt that legitimately quotes a `[CONCERN] <slug>`-shaped example line (e.g. an auditor
brief that includes doctrine text like "declare it like this: `[CONCERN] data-flow`" alongside
its own real `[CONCERN] code-quality` declaration) inflates the count to 2 and produces a false-
positive deny:
```
prompt: "[CONCERN] code-quality\nNote: ... e.g.\n[CONCERN] data-flow\nReview naming."
→ {"permissionDecision":"deny", ... "[CONCERN] declarations found: 2" ...}
```
Fails **closed** (the safe direction), so this is not a security/fail-closed problem, but it's an
undocumented false-positive class not covered by the header's design note ("a prose mention of
the word 'concern' is NOT a declaration" addresses the zero-count false-negative direction, not
this over-count direction). Confirmed tab-indented `[CONCERN]` tags match correctly (no gap
there).

### FINDING 5 (LOW, informational) — one prose performance claim not reproduced, one confirmed

- The `~91ms/invocation (fsync-per-write)` claim justifying the switch away from default
  rollback-journal mode: my own spot-check (20 fresh-process inserts each, this machine) measured
  rollback-journal at ~6.3ms/invocation and WAL+NORMAL at ~8.8ms/invocation (process-spawn
  overhead dominated both, and WAL was not faster in this small single-writer test). Inconclusive
  either way — different filesystem/fsync semantics (APFS vs. presumably Linux ext4) plausibly
  explain the gap — but the diff ships no reproducible benchmark artifact, so the number is
  asserted in prose only. Does not affect correctness (verified separately under Q2/Q3).
- The `~30x cheaper` claim for skipping `mkdir -p` when the directory already exists: reproduced
  and *exceeded* — measured ~72x (0.019ms builtin `[[ -d ]]` vs. 1.39ms `mkdir -p` fork+exec, same
  process, 1000 iterations each). Confirmed accurate, not a finding.
- The claim that `tool_use_id`/`.tool_input.model` field shapes are "confirmed live... not
  guessed": verified against `agent_invocation_tagger.sh:73,77`, which extracts the identical two
  paths (`.tool_use_id` top-level, `.tool_input.model`) from the same PreToolUse event. Accurate.

### Open question (LOW confidence, not asserted as a finding)

`run_guard()` in the test harness (`hooks/tests/test_dispatch_guard.sh:24`) discards stderr
(`2>/dev/null`) and swallows the exit code (`|| true`), and `expect_silent` only checks
`[[ -z "$out" ]]`. This means a genuine mid-script crash (nonzero exit, no JSON emitted) would be
indistinguishable from an intentional `pass_silent`. I looked for a concrete way to trigger this
in Check 7/8's own new code and did not find one — every external-command call in the added code
is guarded with `|| true`/`2>/dev/null` fallbacks — so I'm not asserting this as a finding, just
flagging it as a latent test-harness gap worth a look separately from this wave.

## VERDICT: REDO

**Blocking items:**

1. **Fix `sql_lit()` in `dispatch_guard.sh:340-349`** (Finding 1, HIGH). Replace the broken
   `${v//\'/\'\'}` expansion with the already-correct, already-in-this-diff `cmd_teammate.sh`
   `esc()` idiom (`sed "s/'/''/g"`) or equivalent — verified working end-to-end against a real
   `sqlite3` parse, including the adversarial DROP-TABLE-shaped input, in this audit. Add a test
   case with an apostrophe in at least `session_id` or `model` asserting the row is actually
   recorded (not just that the guard doesn't deny/crash).
2. **Restore the executable bit on `skills/context/scripts/cmd_teammate.sh`** (Finding 2,
   MEDIUM) — `chmod 755`, matching every other script in `skills/context/scripts/` and the
   file's own original authoring convention.

**Not blocking, recommend follow-up GH issues (out of this diff's FILE-SCOPE):**
- The malformed-JSON fail-open at the top of `dispatch_guard.sh` (Finding 3) — pre-existing,
  affects all 8 checks uniformly, confirmed present in `HEAD` before this diff.
- The same broken `${v//\'/\'\'}` escaping pattern in `cmd_adapt.sh:101` and `cmd_loop.sh:101`
  (Finding 1's context) — pre-existing, arguably more exploitable there (free-text fields).

**Everything else holds.** The specific, sharpest defect this audit was commissioned to re-check
— Check 6 pre-empting Checks 7/8 in the `.worktrees` teammate topology — is genuinely fixed,
proven by direct execution against crafted stdin and by reintroducing the exact regression via
mutation (which is caught by, and only by, the two new topology-specific test fixtures). The
`cmd_teammate.sh` unbound-`$1` fix is correct and provably falsifiable. Fail-closed behavior
holds for every scenario the brief asked about except the two items above and the pre-existing,
out-of-scope malformed-JSON gap.

## Checklist hits

- intent: 1 (Finding 1 — Check 8's forensic-attribution intent is undermined for apostrophe-
  bearing fields, though the check's fail-closed/never-deny contract itself is intact)
- fragile-global: 0
- reinvention: 1 (Finding 1 — broken quote-escaping duplicated instead of reusing this same
  diff's own `cmd_teammate.sh` `esc()`)
- passes-local-breaks-CI: 0 (both blocking findings degrade gracefully rather than breaking CI;
  flagged as correctness/hygiene defects, not CI-breakers)

## Suggested redo

- { author: coder (W2-l6-guards lane), scope: `hooks/scripts/dispatch_guard.sh:340-349`
  (`sql_lit()`), change: replace the broken bash parameter-expansion quote-doubling with the
  proven-correct `sed`-based idiom already used by `skills/context/scripts/cmd_teammate.sh`'s
  `esc()`, and add a regression test asserting a row with an apostrophe in a recorded field is
  actually inserted. }
- { author: coder (W2-l6-guards lane), scope: `skills/context/scripts/cmd_teammate.sh` (file
  mode only), change: `chmod 755` to restore the executable bit lost in this diff. }

## Output to conductor

- deliverable: n/a (wave-review mode; no `audit_findings` DB insert performed — `shctx` context
  registry was not reachable/initialized as a `shctx audit insert` target from this read-only
  audit pass; findings recorded in this report file per the wave-review contract, verdict is the
  authoritative record for the gate)
- Concern: guard-fail-closed
- Mode: wave-review
- Files reviewed: 4 (`hooks/scripts/dispatch_guard.sh`, `hooks/tests/test_dispatch_guard.sh`,
  `skills/context/scripts/cmd_teammate.sh`, `skills/context/tests/test_cmd_teammate.sh`)
- Findings: HIGH=1, MEDIUM=2, LOW=2
- Verifications (disproved hypotheses): 4 — (1) Check 6 no longer pre-empts 7/8 in the
  `.worktrees` topology, proven live + by mutation; (2) jq-absent still fails closed via the
  python3 fallback; (3) WAL/synchronous cannot alter any guard decision (no read-then-decide
  path exists) and doesn't break other hooks' reads of the shared DB; (4) the `~30x cheaper`
  mkdir-skip claim is accurate (measured ~72x)
- Open questions: 1 (test-harness exit-code masking in `run_guard`/`expect_silent` — no concrete
  crash found to trigger it, flagged for separate review)
- review_verdict: REDO
- Report path: `/Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/auditor-W2-guard-fail-closed.md`
- Agent ID + timestamp: shepherd:auditor (W2, concern=guard-fail-closed) @ 2026-08-13T00:00:00Z
