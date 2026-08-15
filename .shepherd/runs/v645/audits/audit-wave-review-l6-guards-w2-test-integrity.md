---
title: Wave-review audit — hooks/tests/test_dispatch_guard.sh (test-integrity)
date: 2026-08-13
auditor: shepherd:auditor
sprint: v645
lane: l6-guards
wave: w2 (lane's only wave)
concern: test-integrity
mode: wave-review
methodology: superpowers:systematic-debugging (Phase 1-3: reproduce, isolate, falsify) + hypothesis-driven per agents/auditor.md
prior_class_priors: empty registry (shctx adapt priors --lessons returned nothing; shctx adapt report confirms "first adaptation cycle lands at this sprint's close") — framework priors applied, no historical class weighting available
deliverable: 7 (status: delivered)
---

## Scope reviewed

- `hooks/tests/test_dispatch_guard.sh` (359 lines, uncommitted in
  `.worktrees/v645-l6-guards`) — the full file, not just the new Check 7/8 section, per the
  Deviations-recorded DOCTRINE FINDING that a silently-invalidated sibling fixture is
  indistinguishable from a real pass until the whole file runs.
- `hooks/scripts/dispatch_guard.sh` (486 lines, uncommitted, same worktree) as the file under
  test, specifically the post-perf-fix state (Checks 1-8, WAL/synchronous pragmas, deferred
  `tool_use_id`/`model` extraction, `[[ -d ]]`-guarded `mkdir -p`).
- Base commit `ada05dd` for both files, via `git -C .worktrees/v645-l6-guards diff ada05dd --
  <path>`, to separate this wave's changes from pre-existing content.
- 1 file read for cross-reference: `hooks/scripts/_lib.sh` (`resolve_namespace`, `hook_db_path`
  definitions, to verify the `$SHCTX_DB` vs `$SHEPHERD_WORKDIR` claim and the DB-path shape
  `ownership_evidence()`'s glob depends on).
- `.github/workflows/*.yml` (8 files) — read-only grep for `runs-on`/`container:` to check a
  root-execution risk I found independently (see Findings).
- Files reviewed count: 2 primary + 1 cross-reference + 8 CI configs (grep-only) = **11**.

All work ran at the sprint root (`/Users/jo3/src/fl03/shepherd`, branch `v6.4.5` — HEAD
unchanged throughout, confirmed before and after). No `cd` into the worktree; every command used
`git -C <path>` or an absolute path, per the brief's instruction. The worktree file was **never
mutated** by this audit — all invert/restore mutation testing ran against copies in an isolated
scratch directory (`.../scratchpad/isolated/hooks/{scripts,tests}/`), confirmed by an unchanged
`git -C .worktrees/v645-l6-guards diff --numstat` before and after (190/0 for the guard, 140/1
for the test file, identical both times).

## Findings summary

CRITICAL=0, HIGH=0, MEDIUM=0, LOW=1

## Findings

### LOW — Check 8's unwritable-registry fixture is not root-safe (latent, not currently triggered)

**Hypothesis:** the `chmod 500 .shepherd` simulation of an unwritable registry
(`hooks/tests/test_dispatch_guard.sh` lines 310-323, "Check 8: unwritable registry ->
additionalContext (fail-visible)") stops being load-bearing if the test process ever runs as
root, because root bypasses Unix DAC permission bits — the `sqlite3` write would succeed despite
`chmod 500`, so the guard would silently take its normal-pass branch instead of its
`emit_context`-degraded branch, inverting what the fixture name promises.

**Falsification:**
- `grep -rln chmod hooks/tests/*.sh` → only `test_dispatch_guard.sh` and
  `test_cli_venv_selfheal.sh` match; the latter's hits are `chmod +x` on fake binaries, unrelated
  to permission-denial simulation. This chmod-as-unwritable-dir pattern has **no established
  precedent** elsewhere in `hooks/tests/`, so it isn't inheriting a previously-vetted idiom.
- `grep -n 'runs-on\|container:' .github/workflows/*.yml` → every job uses a bare
  `runs-on: ubuntu-latest` (or a matrix over it); zero `container:` overrides anywhere in the 8
  workflow files. GitHub-hosted `ubuntu-latest` runners execute as the non-root `runner` user by
  default with no container image involved, so **today's actual CI behaves identically to a
  local non-root dev machine** — no live local-vs-CI divergence exists right now.
- Root's DAC-bypass behavior is standard, well-documented Unix kernel semantics (not tested
  live here, since deliberately running part of this suite as root inside a shared dev sandbox
  is out of scope for a read-only audit and not something I'll do without explicit authorization).

**Confidence:** MEDIUM — the mechanism (root bypasses `chmod`) is structurally certain; the
CI-config absence of `container:`/root-run paths is directly grepped and verified, not assumed.
What's NOT verified live is the actual root-run failure (I did not `sudo` and re-run the
suite), and there is currently zero path in this repo's CI or documented dev workflow that runs
as root, so likelihood-of-materializing is low. Severity LOW, not MEDIUM/HIGH: no current impact,
and it affects exactly one of 54 assertions.

**Recommendation (non-blocking, does not warrant REDO):** either skip/xfail this fixture when
`$(id -u)` is `0`, or add a one-line comment above the `chmod 500` noting the non-root
assumption, so a future container/CI change doesn't silently flip this assertion from testing
the fail-visible path to testing nothing, without anyone noticing the load-bearing property was
environment-conditional.

Recorded as `audit_findings` row id 38 (`shctx audit insert --concern=test-integrity
--severity=low`).

## Verifications (evidence for hypotheses tested and DISPROVED — i.e. the suspected defect was
absent; listed per the falsify-don't-confirm methodology, not as findings)

1. **[HYPOTHESIS 1 — suite claimed GREEN but might be stale/pre-perf-fix] DISPROVED.** Ran
   `bash hooks/tests/test_dispatch_guard.sh` three consecutive times against the file exactly as
   it sits in the worktree right now (post-perf-fix, uncommitted). All three runs: **exit 0, 54
   PASS, 0 FAIL**, identical output modulo timing. Command + result:
   ```
   $ out=$(bash .../hooks/tests/test_dispatch_guard.sh 2>&1); rc=$?
   EXIT CODE: 0
   $ echo "$out" | grep -c '^  PASS'   → 54
   $ echo "$out" | grep -c '^  FAIL'   → 0
   ```
   Wall time across 3 runs: 4.50s, 5.84s, 6.38s (`user` 1.65-1.94s, `sys` 2.37-3.30s dominated
   by per-fixture fork/exec — each of 54 fixtures spawns a fresh `bash` + `sqlite3` + `env`).
   This is higher than the lane plan's corrected `~3.7s` acceptance line — **flagged here as an
   open question, not a test-integrity finding**, since it's a performance number, not a
   correctness defect, and perf is explicitly carried by this sprint's own retraction history
   (see lane plan Deviations) rather than this concern. Plausible explanation: concurrent
   multi-lane Agent-Teams activity on this box during the audit (other lanes' gates/builds
   running at the same time) rather than a regression in the guard itself — I did not control
   for this since isolating CPU load is out of scope for test-integrity.

2. **[HYPOTHESIS 2 — some rule-group is not genuinely falsifiable] DISPROVED for all 5 groups
   independently re-tested (exceeds the "at least 3, ideally including 7 and 8" bar).**
   Built an isolated scratch copy (`hooks/scripts/{_lib.sh,dispatch_guard.sh,bash_guard.sh}` +
   `hooks/tests/test_dispatch_guard.sh`, never the real worktree files) and ran a genuine
   mutate → confirm RED → restore-from-`.orig` → confirm GREEN cycle for:
   - **Check 1** (`DISPATCH-MISSING-SUBAGENT-TYPE`): neutered the `case` pattern →
     3 FAIL (`missing subagent_type`, `general-purpose subagent_type`, `Explore subagent_type`),
     exit 1. Restored → 54/0/exit 0.
   - **Check 4c** (`ENGINEER-SUBFLOCK-VIOLATION`): made the guard condition unreachable →
     2 FAIL (`@coder`, `@worker` marked-dispatch fixtures), exit 1. Restored → 54/0/exit 0.
   - **Check 7** (`AUDIT-CONCERN-UNDECLARED`): made `concern_count -ne 1` unreachable →
     4 FAIL (zero-declaration, prose-mention, two-declaration BLOCK assertions, plus the
     CONTENT "Split into" assertion), exit 1. Restored → 54/0/exit 0.
   - **Check 8, record shape**: retargeted the `INSERT` to a nonexistent table
     (`dispatch_ownership_NOWHERE`) → 6 FAIL, including a genuinely interesting ripple: two
     unrelated Check-6 fixtures (`flag_handrolled_fanout = false`, `root ... coder dispatch`)
     ALSO went red, because the broken `INSERT` now surfaces as a real sqlite error that Check
     8's degraded-warn path correctly detects and emits as `additionalContext` even on dispatches
     those fixtures didn't intend to probe — concrete, independently-observed confirmation of
     the wave's own DOCTRINE FINDING (a new check's failure mode is only caught by running the
     WHOLE sibling file, not the new section alone). Restored → 54/0/exit 0.
   - **Check 8, fail-visible-warn shape**: silenced the `emit_context` call on a real `sqlite3`
     write failure → 1 FAIL (`Check 8: unwritable registry -> additionalContext (fail-visible)`),
     exit 1. Restored → 54/0/exit 0.
   Every mutation was syntax-checked (`bash -n`) before running. The real worktree file's
   `git diff --numstat` was identical (190/0, 140/1) before this exercise and after — confirmed
   the real file was never touched, corroborating (not merely trusting) the coder's own
   "real repo file never touched" claim for its own invert cycle.

3. **[HYPOTHESIS 3 — current Rule-7 inversion method might still be the fragile pattern-rename
   that corrupted `env`'s argv] DISPROVED, with one caveat.** I cannot directly inspect the
   coder's own ephemeral scratch-dir session (by design it leaves no artifact — the plan
   describes "mutate-in-isolated-scratch-dir → confirm RED → restore from `.orig`"). Two
   independent, observable proxies both support the "corrected" claim: (a) `git -C
   .worktrees/v645-l6-guards status --short` shows exactly the 4 expected modified tracked
   files and **zero untracked stray files** — no leftover `.orig`/pattern-rename artifacts,
   consistent with a clean restore; (b) I independently reproduced Check 7's falsification
   myself using a clean single-line condition swap (not a pattern-rename touching `env`'s
   argv) and it worked correctly on the first try (see #2 above) — proving a non-fragile
   method genuinely falsifies Check 7 on the CURRENT file, which is the substantive claim under
   test. Confidence: MEDIUM (process-internal claim corroborated by observable proxies, not
   directly witnessed).

4. **[HYPOTHESIS 4 — two disclosed fixture corrections might not match CURRENT guard behavior]
   DISPROVED for both.**
   - `has("Split into")` (capital S, case-sensitive `grep -q --`, no `-i`) at
     `test_dispatch_guard.sh:245` — verified against the CURRENT guard's actual denial text at
     `dispatch_guard.sh:355`: `msg+="Split into ${concern_count} separate dispatches, ..."` —
     exact literal match. Also confirmed live: the "Check 7: two [CONCERN] declarations" CONTENT
     assertion PASSED in all 3 full-suite runs.
   - Self-heal-not-warn: read `dispatch_guard.sh:463-469` — `[[ -d "$do_dir" ]] || do_mkdir_err=
     "$(mkdir -p "$do_dir" 2>&1)"` with `emit_context` firing ONLY if `$do_mkdir_err` is
     non-empty (i.e., only on an actual mkdir failure, never on the ordinary "didn't exist yet"
     case) — matches "absent namespace self-heals silently" exactly. Also independently
     inverted Check 8's record-write path (test #2 above) and confirmed the self-heal fixture
     (`Check 8: absent registry namespace self-heals silently`) is itself load-bearing (it
     failed when I broke the INSERT target).

5. **[HYPOTHESIS 5 — line-56 fixture might accidentally test something new instead of its
   original intent] DISPROVED.** Diffed against base (`git diff ada05dd`): the ONLY change to
   this line is adding `"prompt":"[CONCERN] code-quality"` to a fixture named `step:
   shepherd:auditor (no team_name)`. The fixture's original intent — confirming Checks 2/3 don't
   misfire on a root-tier `shepherd:auditor` subagent dispatch lacking `team_name` — is
   orthogonal to prompt content, so it's unaffected by the addition. The addition's ONLY effect
   is making the fixture also satisfy the newly-added Check 7 (which now fires on every
   `shepherd:auditor` dispatch), preventing a false-negative regression from an unrelated check.
   Confirmed this is not a redundant duplicate of the dedicated Check-7 positive control at line
   252-253 (`"Check 7: exactly one [CONCERN] declaration passes"`): the two fixtures exercise
   different check families (team_name/tier discipline vs. concern-count discipline) even though
   their payload shapes now overlap.

6. **[HYPOTHESIS 6 — a fixture might still misuse `$SHCTX_DB` to simulate an unwritable
   registry] DISPROVED.** `grep -n SHCTX_DB hooks/tests/test_dispatch_guard.sh` → zero matches.
   `grep -n SHEPHERD_WORKDIR hooks/tests/test_dispatch_guard.sh` → also zero matches — because
   the actual unwritable-registry fixture doesn't need either variable: it works directly in the
   test's `$tmp` sandbox cwd (`mkdir -p .shepherd; chmod 500 .shepherd`), relying on
   `resolve_namespace`'s default (cwd-relative `.shepherd`) rather than any env-var override.
   Cross-checked `resolve_namespace()` in `hooks/scripts/_lib.sh:184-195`: honors
   `$SHEPHERD_WORKDIR` then `$SHCTX_ROOT_OVERRIDE`, never `$SHCTX_DB` (confirming the lane
   plan's own correction was accurate) — moot for this file since it uses neither.

7. **[HYPOTHESIS 7 — `bash -n` might not be clean] DISPROVED.** `bash -n` clean on both
   `hooks/tests/test_dispatch_guard.sh` and `hooks/scripts/dispatch_guard.sh`.

8. **Corroborating evidence not explicitly requested but load-bearing for confidence:**
   `shellcheck --severity=warning` clean on both files; `shellcheck` default severity shows one
   `SC1091` (info, "not following source") on `dispatch_guard.sh:84` — confirmed via `git show
   ada05dd:hooks/scripts/dispatch_guard.sh | shellcheck` to be **byte-identical pre-existing**,
   matching the coder's own claim exactly. `hooks/tests/test_dispatch_guard.sh` has one
   pre-existing `SC2164` (`cd "$tmp"` without `|| exit`, line 47) — confirmed via the same-line
   diff check to be **unchanged by this wave** (not introduced by W2-G2), so not attributed to
   this wave's coder; noted for completeness, not filed as a finding against this concern.
   Also confirmed via full diff review that the new helpers (`expect_block_code`,
   `ownership_evidence`) are genuinely new, while `has()`/`is_context()` are correctly REUSED
   (unchanged in the diff, pre-existing from the Check-6 section) — no duplicate-helper
   reinvention.

## Open questions

- Wall-clock suite time measured at 4.5-6.4s vs. the lane plan's corrected ~3.7s acceptance line
  (see Verification #1) — plausibly explained by concurrent multi-lane activity on this shared
  box during the audit window, not independently controlled for. Not a test-integrity defect;
  flagging for whoever owns the regression/performance concern to re-measure under a quieter
  window before treating it as a live regression.
- Pre-existing `SC2164` at `hooks/tests/test_dispatch_guard.sh:47` (unchanged by this wave) —
  worth a future one-line fix (`cd "$tmp" || exit 1`) but out of this concern's and this wave's
  scope since it predates `ada05dd`... predates the wave, not the base commit specifically
  (confirmed present in `ada05dd` itself).

## Pattern delta

N/A — wave-review mode does not carry a grade or a Pattern delta section per `agents/auditor.md`
(Pattern delta is completeness/close-mode only).

## Cache telemetry

N/A — completeness/close-mode only.

## Grade

N/A — wave-review mode, PASS/REDO verdict only (see WAVE-REVIEW VERDICT below), no letter grade.

## Grade rationale

N/A (see above).

---

## WAVE-REVIEW VERDICT
- Lane / wave: l6-guards / w2
- review_verdict: PASS
- Checklist hits: intent=0, fragile-global=0, reinvention=0, passes-local-breaks-CI=0
  (the root-execution chmod risk found during this audit is recorded as a LOW `audit_findings`
  row, not a checklist hit — verified no ACTUAL local-vs-CI divergence exists today, since every
  workflow in `.github/workflows/*.yml` runs bare `ubuntu-latest` with no `container:`/root
  override; the checklist item requires a real current divergence, which this is not)
- Suggested redo: none (verdict is PASS)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/audits/audit-wave-review-l6-guards-w2-test-integrity.md
- Agent ID + timestamp: shepherd:auditor (test-integrity, l6-guards w2) @ 2026-08-13T21:40:00Z

## AUDITOR REPORT
- deliverable: 7 (status: delivered)
- Concern: test-integrity
- Mode: wave-review
- Files reviewed: 11 (2 primary uncommitted files under test + 1 cross-reference lib file + 8 CI
  workflow configs grepped)
- Findings: CRITICAL=0, HIGH=0, MEDIUM=0, LOW=1
- Verifications (disproved): 8
- Open questions: 2
- GH issues filed: none
- Grade: n/a (wave-review mode)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/audits/audit-wave-review-l6-guards-w2-test-integrity.md
- Hot-fix-lane recommendations: 0
- Sprint-pattern entry: skipped (wave-review mode does not carry Pattern delta; that's
  completeness/close-mode only per agents/auditor.md)
- Agent ID + timestamp: shepherd:auditor (test-integrity, l6-guards w2) @ 2026-08-13T21:40:00Z
