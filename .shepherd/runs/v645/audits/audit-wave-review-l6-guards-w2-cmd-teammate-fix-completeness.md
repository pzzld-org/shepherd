---
title: Wave-review audit — cmd_teammate.sh unbound-variable fix completeness
date: 2026-08-13
auditor: shepherd:auditor
sprint: v6.4.5 (run v645)
concern: cmd-teammate-fix-completeness
mode: wave-review
methodology: superpowers:systematic-debugging (falsify-don't-confirm)
prior_class_priors: adaptation registry empty at time of audit (`shctx adapt report` — "no
  sprint metrics recorded yet"; `shctx adapt priors --lessons` — empty) — framework priors
  applied, no lesson-specific reweighting available.
---

## Scope reviewed

Lane `l6-guards`, wave 2, step W2-G3 (mid-wave-widened to include the `heartbeat` fold-in).
Two uncommitted files in the lane worktree, diffed against base `ada05dd`:

- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards/skills/context/scripts/cmd_teammate.sh` (+8/-4)
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards/skills/context/tests/test_cmd_teammate.sh` (+25/-0)

Files reviewed: 2. This is a coder self-report relayed through a lead (twice), independently
re-verified here per the lane plan's explicit PASS-gating requirement (`## Deviations`,
"W2-G3 COMPLETE ... Holding this uncommitted ... commit custody is PASS-gated on an
INDEPENDENT `@auditor` wave-review verdict").

All investigation ran read-only against the worktree: no edits, no commits. Falsification
of the regression suite's load-bearing-ness (Hypothesis 5) required inverting the fix and
re-running tests; this was done exclusively against an isolated scratch copy of
`skills/context/` under the audit scratchpad, never against the real worktree file — verified
byte-identical to the worktree original both before and after each restore, and `git status`/
`git diff --numstat` on the worktree confirmed unchanged (+8/-4, +25/-0) throughout.

## Findings summary

CRITICAL=0, HIGH=0, MEDIUM=0, LOW=2

## Findings

### LOW — Diff-stat self-report inaccuracy

**Hypothesis:** The report's claimed `cmd_teammate.sh` diff stat (+12/-4) is inflated/
inaccurate versus the real diff.

**Falsification:** `git -C .worktrees/v645-l6-guards diff ada05dd --numstat -- skills/context/scripts/cmd_teammate.sh`
→ `8	4	skills/context/scripts/cmd_teammate.sh`. Root's WAVE-COMPLETE relay in the lane
plan (`## Deviations`, "W2-G3 COMPLETE (heartbeat fold-in included)") states "cumulative
`cmd_teammate.sh` +12/-4, `test_cmd_teammate.sh` +25/-0". The test-file figure is exactly
right; the script figure is not. Manual line count confirms the real number: each of the
four fixed branches (register/heartbeat/status/retire) removes exactly 1 line and adds
exactly 2 (default-assignment line + new guard line) = 4 removed / 8 added, matching
`--numstat` exactly.

**Confidence:** HIGH (directly measured via `git diff --numstat`, cross-checked by manual
line count of the diff hunks).

**Impact:** No functional impact — the code itself is correct and complete (see other
findings/verifications below). This is a report-accuracy defect: a metric relayed through
two hops (coder → lead-conductor → append-only WAVE-COMPLETE record) drifted from ground
truth and nothing caught it before landing in the durable plan record.

### LOW — Test-hygiene nit: shared usage-substring across 4 distinct branch assertions

**Hypothesis:** The four no-name regression assertions in `test_cmd_teammate.sh` are
weakened by grepping the identical literal usage substring for every branch instead of a
branch-specific line, and this could tautologically pass regardless of which branch broke.

**Falsification:** Read `skills/context/tests/test_cmd_teammate.sh` lines 56/61/66/71 — all
four assertions (status/register/retire/heartbeat) grep for the identical literal
`"shctx teammate status <name>"`, not each branch's own usage() line (e.g.
`"shctx teammate register <name> ..."` for the register assertion). Then independently
inverted all four branches back to the pre-fix `name="$1"` form, one at a time, in an
isolated scratch copy (never the real worktree file — confirmed via `diff` byte-identical to
the worktree original after each restore, and `git status`/`--numstat` on the real worktree
unchanged throughout). Each inversion produced its own distinct, correctly-attributed FAIL
line:
- `FAIL: register with no args exit code: 1 (want 2)`
- `FAIL: retire with no name exit code: 1 (want 2)`
- `FAIL: heartbeat with no name exit code: 1 (want 2)`
- `FAIL: status with no name exit code: 1 (want 2)`

Each was then restored and the suite reconfirmed GREEN (`PASS: test_cmd_teammate`). The
shared usage-substring is NOT a false-pass risk today — the `rc==2` check and the
`*"unbound variable"*` absence check in the same assertion block already carry the real
regression-catching weight, and `usage()` prints its whole 8-line block on every legitimate
invocation regardless of branch, so the substring is present whenever `usage()` genuinely
fires.

**Confidence:** HIGH (empirically demonstrated via 4/4 independent invert-to-RED, restore-
to-GREEN cycles).

**Impact:** Cosmetic/style only. Recommend (non-blocking): grep each branch's own usage
line for tighter, self-documenting assertions — the current form works only because
`usage()` prints the whole block every time, an implicit coupling a future per-subcommand
usage refactor could silently break without these tests noticing.

## Verifications

All items below were independently re-derived from source and/or live execution, not
trusted from the coder/lead report.

1. **All four branches fixed with the claimed pattern.** Read `cmd_teammate.sh` directly:
   `register` (L51-52), `heartbeat` (L136-137), `status` (L185-186), `retire` (L250-251) all
   show `name="${1:-}"; shift || true` immediately followed by
   `[[ -n "$name" ]] || { usage; exit 2; }`. Matches `state`'s pre-existing reference shape
   in substance (differs in one respect noted below, not a defect).

2. **`liveness` and `prune` genuinely untouched and genuinely clean.** Read both branches in
   full (L189-223, L224-248): both are flag-only parsers (`--stale-mins=`, `--confirm`,
   `--name=`, `--crashed`), no bare positional `$1` read anywhere in either.

3. **No-name crash behavior, live-fired.** Ran all four subcommands with no name against an
   isolated, schema-migrated scratch DB (mirroring the test harness's own bootstrap, never
   the live project registry):
   ```
   $ bash cmd_teammate.sh status    -> RC=2, prints full usage() text, no trace
   $ bash cmd_teammate.sh register  -> RC=2, prints full usage() text, no trace
   $ bash cmd_teammate.sh retire    -> RC=2, prints full usage() text, no trace
   $ bash cmd_teammate.sh heartbeat -> RC=2, prints full usage() text, no trace
   ```
   None produced a raw bash "unbound variable" trace. Matches the claim exactly.

4. **`status <real-name>` returns real JSON.** From the sprint root, against the live
   project registry (read-only `SELECT`, no mutation):
   ```
   $ bash .worktrees/v645-l6-guards/skills/context/scripts/cmd_teammate.sh status \
       shepherd-conductor-v645-l1-engine
   [{"id":"2901870D-...","teammate_name":"shepherd-conductor-v645-l1-engine", ...
     "status":"idle","declared_state":"complete"}]
   RC=0
   ```

5. **All four regression assertions independently proven load-bearing.** For each of
   register/retire/heartbeat/status: inverted the fix to the pre-fix `name="$1"` (no
   default/no guard) form in an isolated scratch copy of `skills/context/`, reran
   `test_cmd_teammate.sh`, confirmed RED with the exact expected `FAIL:` message (not just
   nonzero exit), restored, reconfirmed GREEN, and diffed the restored scratch copy against
   the real worktree file (byte-identical). The real worktree file was never touched at any
   point (`git status --short` / `git diff --numstat` unchanged across the entire
   investigation). Raw crash text confirmed for register/retire specifically:
   `line 51: $1: unbound variable` / `line 249: $1: unbound variable`, `RC=1` — exactly the
   defect class the fix eliminates.

6. **SQL-escaping gap confirmed present, confirmed unfixed, confirmed not masked.**
   `status` (L187) and `retire` (L252) still interpolate raw `'$name'` into SQL with no
   `esc()` call, unlike `register` (L100-103), `heartbeat` (L148/161), and `state` (L175-176)
   which all escape via `esc()`. Fired `status "o'brien"` against an isolated DB post-fix:
   `Error: in prepare, near "brien": syntax error` — confirms the gap is fully reachable for
   any non-empty name, i.e. the unbound-variable guard (which only fires on an *empty* name)
   does not mask it in any way. The lane plan's `## Deviations` accurately characterizes this
   as reported-not-fixed, correctly out of W2-G3's scope per root's explicit instruction, and
   the coder did not silently patch or silently drop it from the report.

7. **Full suite green.** `bash skills/context/tests/run.sh` → `—— 50/50 passed ——` (measured
   directly, ~81s wall time). Confirms the plan's claim. Note: the audit brief's premise that
   the report claimed "50/50 before, higher after" the heartbeat addition does not match what
   the plan actually records — both the pre-heartbeat (L304) and post-heartbeat (L352) entries
   say "50/50". This is expected and not a discrepancy: 50 is the *file* count from
   `run.sh` (one file, `test_cmd_teammate.sh`, gets more *assertions* inside it, not a new
   file), so the file-level tally is correctly unchanged by an in-file assertion addition.
   `ctx_tests = "bash skills/context/tests/run.sh"` is a named gate in `.shepherd/shepherd.toml`,
   confirming this suite is a wired gate, not an orphaned local-only script (no
   "passes-local-breaks-CI" risk for this concern).

8. **`bash -n` clean on both files**, confirmed directly (`bash -n cmd_teammate.sh`,
   `bash -n test_cmd_teammate.sh` — both silent/exit 0).

9. **Structural note (not a finding):** the four newly-fixed branches place
   `[[ -n "$name" ]] || { usage; exit 2; }` *immediately* after `shift`, before any flag-
   parsing loop. `state` (the branch they were modeled on) places the equivalent check
   *after* its flag-parsing loop, which means `state --set=foo` with no name would silently
   absorb `--set=foo` as the name value rather than erroring (untouched pre-existing
   behavior, out of scope here, not exercised by this diff). The new branches' ordering is
   incidentally more robust than the reference shape they copied. Worth a future backport to
   `state`, not blocking here.

## Open questions

None — all eight brief hypotheses were resolved to a definite confirm/disconfirm with direct
evidence; nothing was left at suggestive-only confidence.

## Pattern delta

N/A — wave-review mode carries no grade and this section is scoped to completeness/close
mode per `agents/auditor.md`.

## Cache telemetry

N/A — wave-review mode; scoped to completeness/close mode per `agents/auditor.md`.

## Grade

N/A (wave-review mode — PASS/REDO verdict only, no letter grade).

## Grade rationale

N/A.

## WAVE-REVIEW VERDICT

- Lane / wave: l6-guards / w2
- review_verdict: **PASS**
- Checklist hits: intent=0, fragile-global=0, reinvention=0, passes-local-breaks-CI=0
- Suggested redo: none
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/audits/audit-wave-review-l6-guards-w2-cmd-teammate-fix-completeness.md
- Agent ID + timestamp: shepherd:auditor @ 2026-08-13T00:00:00Z

## AUDITOR REPORT

- deliverable: 8 (status: delivered)
- Concern: cmd-teammate-fix-completeness
- Mode: wave-review
- Files reviewed: 2
- Findings: CRITICAL=0, HIGH=0, MEDIUM=0, LOW=2
- Verifications (disproved): 0 hypotheses disproved — all 8 brief hypotheses CONFIRMED as
  reported; 9 independent verification items recorded (see `## Verifications`)
- Open questions: 0
- GH issues filed: none (both findings are LOW, non-blocking, recorded as audit_findings
  rows 39/40 — not escalated to GH per LOW-severity handling)
- Grade: n/a (wave-review)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/audits/audit-wave-review-l6-guards-w2-cmd-teammate-fix-completeness.md
- Hot-fix-lane recommendations: 0
- Sprint-pattern entry: skipped (wave-review mode carries no `## Pattern delta` — completeness/close only)
- Agent ID + timestamp: shepherd:auditor @ 2026-08-13T00:00:00Z
