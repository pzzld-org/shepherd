---
title: v6.4.5 close audit — completeness
date: 2026-08-14
auditor: shepherd-auditor-v645-completeness
sprint: v6.4.5
concern: completeness
mode: close
methodology: hypothesis-driven, falsify-don't-confirm (superpowers:systematic-debugging); every
  acceptance line re-run verbatim against HEAD b57d495, not read from a wave report
prior_class_priors: none — shctx adapt priors empty (first adaptation cycle lands at this close)
---

## Scope reviewed

All seven seed §6 deliverables' literal `Acceptance:` lines, re-run against HEAD `b57d495`
(verified `git rev-parse HEAD` matches, worktree clean apart from a sibling auditor's live
edit to `packages/harness-claude/*` and this run's own report files). The SUBTRACT
accounting (`git diff v6.4.4..HEAD --shortstat`) against the seed's `sprint_metadata`
pre-authorization block. All 78 rows of `.shepherd/runs/v645/dogfood.md`, read in full.
The one operator amendment in `.shepherd/dispatcher-patches/v645-pc-1.md`. GH issues
#284–#293 (the last four filed live during this close swarm, one by this auditor).

Not in scope / not independently re-derived: a full session-transcript brief-order audit
(dispatch run-log ordering) and a full `workflow_tool`/`fanout` trace census beyond what
`dogfood.md` DF-57/DF-60/DF-64–68 already establish in exhaustive, independently-verified
detail — see Open questions.

## Findings summary

CRITICAL=3, HIGH=4, MEDIUM=1, LOW=0. Verifications (disproved): 3. Open questions: 2.

## Findings

### F1 — CRITICAL — SUBTRACT-VIOLATION per the seed's own pre-authorization terms

**Hypothesis:** the close ends net-positive without W4 (#266, Python/bash retirement)
landing, and the seed's own `sprint_metadata` note states that exact scenario is explicitly
NOT covered by the SUBTRACT pre-authorization.

**Falsification.** `seed.md` §frontmatter:
```
sprint_metadata:
  expected_loc_delta: -40000   # at full-arc completion (W4 retirement landed)
  subtract_floor: 45000        # ceiling on the intermediate positive excursion
  subtract_note: "Net-positive pre-authorized ONLY between first Rust surface and W4
  retirement. A close that ends positive is a genuine SUBTRACT-VIOLATION, not covered."
```
Measured: `git diff v6.4.4..HEAD --shortstat` → **465 files changed, 48675 insertions(+),
699 deletions(-)** (net **+47,976**), re-run twice, both `..` and `...` forms agree
(`v6.4.4` is an ancestor of HEAD, merge-base identical). This EXCEEDS the 45,000-line
ceiling even under the generous "intermediate excursion" reading — and the close brief's
own cited figures (453 files, +46,611/-696, net +45,915) *also* exceed the ceiling, by 915
lines; my independent re-measurement at the identical stated HEAD is 2,061 lines larger
still (see F1-note below). Separately and more decisively: F6 below confirms W4 (#266) has
not landed — 132 tracked `.py` files remain under `services/cli`, 102 `poetry`/
`venv-ensure` references remain repo-wide, and the sprint's own final wave *added* a new
~1,280-line Python guard engine rather than retiring surface. Per the seed's own words,
a net-positive close without W4 landed is **"not covered… a genuine SUBTRACT-VIOLATION,"**
not merely over a soft ceiling.

**F1-note (measurement discrepancy, disclosed rather than silently reconciled):** the
close brief cites 453 files / +46,611 / -696 at this same HEAD; my direct re-run of
`git diff v6.4.4..HEAD --shortstat` on the stated HEAD (`b57d495`, confirmed via
`git rev-parse HEAD`) returns 465 / +48,675 / -699. Both tag and merge-base checks confirm
`v6.4.4` is correctly resolved and unambiguous (`git show-ref` finds exactly one
`refs/tags/v6.4.4`). I was not able to fully reconcile the ~12-file/~2,000-line delta in
the time available (excluding `Cargo.lock` alone accounts for 918 of it); regardless of
which figure is used, both are past the 45,000 ceiling, so the finding stands under either
number.

**Confidence:** HIGH — read directly from the seed's own frontmatter and a repeatable git
command against the stated HEAD.

**Grading effect:** per `skills/shepherd/references/grading-rubric.md`, an unauthorized
SUBTRACT-VIOLATION caps the sprint grade at **C+**; this is a genuine violation of the
seed's own stated terms, not merely an absent pre-authorization.

### F2 — CRITICAL — #280 acceptance item 6 (npm dependency gate) fails at HEAD; regression introduced in the sprint's own final commit

**Hypothesis:** `packages/harness-codex` depends on `packages/harness-claude`, violating
#280's own written acceptance spec item 6 ("no `harness-*` package imports a sibling
harness"), and the checker built to enforce this is invoked by nothing in the toolchain, so
the violation shipped silently.

**Falsification:**
```
$ node packages/scripts/check-deps.mjs
checking 4 package(s): @fl03/compiler, @fl03/harness-claude, @fl03/harness-codex, @fl03/harness-pi
  no adapter depends on another adapter        FAILED
      @fl03/harness-codex: depends on adapter package `@fl03/harness-claude`
  adapter scoped deps are allowlisted          FAILED
      @fl03/harness-codex: depends on `@fl03/harness-claude`, which is neither
      `@fl03/compiler` nor a `@fl03/cli-*` platform package
::error::2 dependency-rule violation(s).
$ echo $?
1
```
`node packages/scripts/check-deps.mjs --self-test` confirms every rule is genuinely
falsifiable (not tautological) before re-confirming the real tree fails. `grep -rn
check-deps .github/workflows/*.yml packages/*/package.json` → **0 hits** — the checker is
wired into no CI job and no package script. This is an **OUTCOME-REGRESSION**, not a
pre-existing gap: `git show b57d495~1:packages/harness-codex/package.json` has NO
`harness-claude` dependency; `git log -p` shows it was added in `b57d495` — **the sprint's
own final commit** ("W12 — close the loop"), which wired a shared guard-serve broker
between the Claude and Codex adapters via a direct cross-package import rather than through
the compiler or a platform package. `check-deps.mjs` itself was authored in Wave 0
(`4ee106a`), so it was green for the entire sprint until the last commit broke it, and
nothing re-ran it before HEAD landed. **Independently discovered and filed by a sibling
auditor as GH #290** (created 2026-08-14T05:24:40Z, same session) while I was verifying it;
this finding corroborates #290 rather than duplicating it.

**Confidence:** HIGH — reproduced the checker's exit code directly, confirmed via
`--self-test`, and traced the exact commit that introduced the regression via `git show`/
`git log -p`.

### F3 — CRITICAL — dogfood.md DF-64/DF-65's own prescribed remediation was not built, despite a "FIX-THIS-RUN" disposition

**Hypothesis:** DF-64 and DF-65 (both CRITICAL) demand retiring `hooks/tests/
lint_agent_capabilities.sh`'s static text-grep and replacing it with a runtime capability
probe at teammate spawn that HALTs on any delta between a role's declared `tools:`
frontmatter and its observed runtime tool list. Neither landed.

**Falsification:** `hooks/tests/lint_agent_capabilities.sh` still exists, its header still
describes a static grep over `agents/*.md` `tools:` allowlists (not a runtime probe), and
it is still invoked at `hooks/tests/run.sh:122-124`. `grep -rln 'capability.probe\|
CAPABILITY.PROBE\|tool.*mismatch\|WORKFLOW-VEHICLE-PROBE' commands/ agents/` finds only
the pre-existing `WORKFLOW-VEHICLE-PROBE`, which is scoped to the single token `Workflow`
and says nothing about the `Glob`/`Grep`/`ScheduleWakeup` deltas DF-64/DF-65 measured, nor
does it run at teammate spawn with HALT semantics — it is a conductor self-check, not the
spawn-time enforcement DF-64/65 name. DF-64's own row text: *"Retire
`lint_agent_capabilities.sh`'s text-grep entirely; it has now missed this defect twice."*
That has not happened.

**Confidence:** HIGH — read the live file and its wiring directly; grepped for the
prescribed replacement mechanism and found none.

**Note:** this is distinct from the sprint's dominant "gate that cannot fail" pattern (a
test manufacturing its own precondition) — `lint_agent_capabilities.sh` is not tautological,
it correctly checks what it checks (declared frontmatter tokens). The defect is that its
own authors, twice over (DF-17 then DF-64/65), documented it as *measuring the wrong
layer* and prescribed its retirement, and the retirement did not happen even though the
row is tagged FIX-THIS-RUN.

### F4 — HIGH — #239 (canonical verb parity) acceptance fails: 0 cases, exit 1

**Falsification:**
```
$ conformance/run.sh --impl=rust; echo REAL_EXIT:$?
conformance --impl=rust: FAIL -- 0 cases implemented (Rust port not yet built -- W1-W3)
REAL_EXIT:1
```
Matches the close brief's own stated expectation; independently re-verified here rather
than taken on faith. **Confidence: HIGH.**

### F5 — HIGH — #282 (Rust core engine) acceptance fails: 0 cases for `run-state`, exit 1

**Falsification:**
```
$ conformance/run.sh --impl=rust --suite=run-state; echo REAL_EXIT:$?
conformance --impl=rust: FAIL -- 0 cases implemented for --suite=run-state (Rust port not
yet built -- W1-W3)
REAL_EXIT:1
```
The `run-state` conformance suite (`conformance/cases/run-state/`) does not exist —
`ls conformance/cases/` returns only `core` and `guard-cli`, exactly as DF-41 recorded.
**Confidence: HIGH.**

### F6 — HIGH — #235 (distribution/launcher) acceptance is entirely unmet, plus a new bash-3.2 bug in the one launcher artifact that exists

**Falsification, npm distribution half:** `grep -rl optionalDependencies --include=
package.json` (repo-wide, excluding `node_modules`) → **0 hits**. No `packages/cli-*` or
platform-triple package directories exist. `.github/workflows/release.yml` has 0 hits for
`arm64`/`musl`/`windows`/`optionalDependencies`/`cross`. `npm query ".workspace" --json`
(the literal command in GH #280's own acceptance block) returns `[]` because `npm install`
has never been run/committed at the workspace root — no `package-lock.json`, no
`node_modules/` (confirmed clean install works: `npm install --package-lock-only` succeeds
in 184ms with 0 vulnerabilities; the resulting lockfile was deleted after the probe to
preserve read-only discipline). GH #235 is still **OPEN**.

**Falsification, launcher half (newly discovered, filed as GH #293):**
`scripts/install-shctx-launcher.sh` writes a launcher whose no-resolution diagnostic path
crashes before it can fire, on this exact machine (bash 3.2.57, the same box every gate in
this sprint runs on):
```
$ SHCTX_CACHE_ROOT=/tmp/empty-cache /tmp/probe/shctx status
/tmp/probe/shctx: line 109: CANDIDATES[@]: unbound variable
```
Root cause: `shopt -s nullglob; CANDIDATES=(...)` followed by `for c in
"${CANDIDATES[@]}"` under `set -eu`, a genuinely empty array — the classic bash <4.4
empty-array-under-nounset gap this project's own portability notes already name. Exit code
is still non-zero, so `no-resolution-exits-non-zero` passes, but
`no-resolution-prints-diagnostic` fails:
```
$ bash scripts/tests/test_shctx_launcher.sh
  FAIL  no-resolution-prints-diagnostic   expected "no shepherd plugin install found",
                                          got="...: line 109: CANDIDATES[@]: unbound variable"
—— 18/19 passed ——
```
`scripts/tests/test_shctx_launcher.sh` is **not** wired into `hooks/tests/run.sh` (0 hits
for `scripts/tests` in that file), so this one red test is invisible in the sprint's
headline `86/87` count — a second, previously-unfiled instance of the sprint's "not
reflected in the reported tally" pattern.

**Confidence:** HIGH — both halves reproduced directly, not inferred.

### F7 — HIGH — #266 (Python/bash retirement) acceptance moved further away, confirmed with exact counts

**Falsification:**
```
$ find services/cli -name '*.py' -not -path '*/.venv/*' | wc -l
132
$ rg -n 'shepherd-venv-ensure|poetry' --glob '!CHANGELOG.md' | wc -l
102
$ git diff v6.4.4..HEAD --stat -- services/cli
24 files changed, 4277 insertions(+), 123 deletions(-)
```
including two brand-new files — `predicates.py` (+918) and `commands/guard.py` (+242) — a
~1,280-line Python guard-predicate engine landed this sprint. `bin/shepherd guard eval`
resolves to this Python implementation (`python -m shepherd_cli guard eval`, verified via
`--help`), not to a Rust `crates/cli` subcommand: `crates/cli/src/cmd.rs` still declares
exactly one variant, `Init` — DF-76's exact finding, unresolved at HEAD in the way DF-76's
own row prescribed ("Build `shepherd guard eval` in `crates/cli`"). The three harness
adapters therefore still relay guard evaluation to Python, not to the "shared Rust engine"
locked decision 8 names as the arc's structural answer.

**Confidence:** HIGH.

**Argument stated fairly, per the brief's instruction:** there is a genuine, defensible
counter-argument — the `[[example]]`-style conformance corpus and `predicates.py`'s design
mirror `crates/core/src/run.rs`'s existing pattern closely enough that a Rust port is
plausibly cheap once written. That argument does not change the measurement: 132 `.py`
files and 102 `poetry`/venv references are the state at HEAD, `rg` returns non-zero, and
the acceptance line is binary. The argument is a reason to expect F7 to close faster next
sprint, not evidence that it is closed now.

### F8 — MEDIUM — dogfood.md's own per-row disposition tags are not reliable in isolation (DF-12 case study)

**Falsification:** `dogfood.md` line 71 (the DF-12 row, HIGH) ends `| FIX-THIS-RUN |`.
The same document's summary "Disposition map" (lines 16–30, dated *after Wave 0*) lists
DF-12 under **"OPEN — the liveness cluster."** DF-71 (much later in the same document)
states outright: *"DF-12 recorded that `session_id` is never populated and is still OPEN;
nothing since has wired it."* Live re-verification against the running registry:
```
$ sqlite3 .shepherd/shepherd.db "SELECT teammate_name, COALESCE(NULLIF(session_id,''),
  '<EMPTY>'), status FROM teammates"
shepherd-engineer-v645|<EMPTY>|idle
shepherd-conductor-v645-l4-conformance|<EMPTY>|idle
... (all 6 rows: <EMPTY>)
```
DF-71's eventual fix (`--session` required, per `cmd_teammate.sh` and `commands/spawn.md`
both now confirmed to enforce it) landed **prospectively** but the **backfill** half of its
own remediation ("make it REQUIRED and backfill") never ran — all six of this sprint's own
teammates carry an empty `session_id` at close.

**Confidence:** HIGH for the disposition-inconsistency claim (read directly); MEDIUM for
"this generalizes to other rows" — I spot-checked DF-56 (fix verified landed: Checks 7/8
now precede Check 6 in `dispatch_guard.sh`, matching its remediation exactly), DF-68
(fix verified landed: `commands/spawn.md` Check 1 now resolves the predicted `backendType`
and names the correct `tmux -L claude-swarm-<lead-pid>` oracle), and DF-71 (fix verified
landed: `FORBIDDEN_WORKTREE_PATTERN` added, `44/44` test suite includes both a push-allowed
positive control (S4) and an unseeded-DB fail-closed case (P20)) — all three checked out.
DF-12 is the one exception found among a five-row sample, which is why this is filed
MEDIUM rather than treated as a systemic ledger-integrity problem.

## Verifications (disproved)

1. **Hypothesis:** DF-56's "REDO ISSUED" disposition (not literally "FIXED") means the
   Check-6-before-Check-7/8 unreachability bug is still live. **Disproved:**
   `grep -n '^# Check [0-9]' hooks/scripts/dispatch_guard.sh` shows the order is now
   `0,1,2,3,4,4b,4c,5,7,8,6` — Checks 7 and 8 execute before Check 6, exactly as DF-56's
   remediation demanded.
2. **Hypothesis:** #283 (Rust registry) acceptance is unmet, symmetric with #282/#239.
   **Disproved:** `cargo test -p shepherd-registry --lib -- migrate::` → `10 passed; 0
   failed`, including `sqlite_master_matches_the_frozen_python_capture` and
   `compile_options_include_fts5`. The order-normalized `sqlite_master` byte-parity and
   `ENABLE_FTS5` acceptance criteria are both genuinely, mechanically satisfied.
3. **Hypothesis:** the operator's dispatcher-patch (`v645-pc-1.md`, conductor lane-commit
   and lane-push authority) was folded into prose but never proven at the guard level, the
   pattern the patch itself warned against ("the prose fix alone would ship a lie").
   **Disproved:** `skills/shepherd/SKILL.md` now reads "`TEAMMATE-GIT-WRITE` covers
   CROSS-LANE INTEGRATION ONLY… a conductor's OWN lane commit and its OWN lane-branch
   `push` are the conductor's, full stop… (`.shepherd/dispatcher-patches/v645-pc-1.md`)",
   and `hooks/tests/test_teammate_git_guard.sh` is 44/44 green with both a positive control
   (`S4 seeded: teammate + git push: PASS`) and negative controls (cross-lane
   merge/rebase/cherry-pick/worktree-add/branch-d all DENY), plus a fail-closed case on a
   missing DB file (`P20`). Both halves of the amendment — prose and enforcement — are
   genuinely landed.

## Open questions

1. **The 453-vs-465-file SUBTRACT discrepancy (F1-note) is not fully reconciled.** Both
   figures breach the 45,000-line ceiling, so it does not change F1's verdict, but a future
   auditor should not assume either number is exact without re-running the command fresh.
2. **Full brief-order and workflow_tool/fanout trace census not independently re-derived.**
   `dogfood.md` (DF-57, DF-60, DF-64–68) already contains an exhaustive, mechanically
   re-verified investigation of the substrate/fan-out axis that goes well beyond what a
   fresh pass in the time available could add; I did not find a `workflow_tool`/`fanout`
   field omission in the rows I sampled, but I did not enumerate all 12 waves' WAVE-COMPLETE
   traces individually. Low-confidence, so left here rather than turned into a finding.

## Pattern delta

No prior close report exists for this project (`shctx adapt report` → "no sprint metrics
recorded yet — first adaptation cycle lands at this sprint's close"), so there is no
severity-vs-prior or 3-sprint trend to compute. `Systemic risk: none (insufficient
history)`.

Within-sprint pattern, stated plainly because it is the loudest signal in the audit: the
close brief names nine "gate that cannot fail" instances as the dominant defect class.
This audit's strongest finding (F2) is a close relative but structurally distinct — not a
gate that manufactures its own precondition, but a **real, falsifiable, correctly-red gate
that nothing invokes**, broken by the sprint's own final commit. F3 is a third variant: a
CRITICAL row whose own prescribed fix (retire a stale checker) was written down twice and
actioned neither time. All three variants share one root cause the sprint itself named
repeatedly and precisely (DF-68): *"a null measurement is evidence only if the instrument
has been shown able to return the positive."* The close report's "Landed, verified at
close" list is itself such an instrument for `check-features.sh --targets`, the npm
dependency gate, and `npm install` state — none of which it mentions running.

## Cache telemetry

`shctx query cache-usage --sprint=v6.4.5 --md` returned no output (empty result set, exit
0) — telemetry view absent — establishing baseline. Skipped per contract; no cap applied.

## Grade

**C**

## Grade rationale

Two of seven seed-anchored CRITICAL/HIGH deliverables pass their literal acceptance line
cleanly and rigorously (#281 conformance oracle: 15/15, exit 0, checksum present; #283
Rust registry: 10/10 gate tests including a byte-exact `sqlite_master` fixture diff and a
live `ENABLE_FTS5` `PRAGMA` assertion). One (#280) is genuinely half-landed — the Rust
workspace half is clean (`cargo metadata` 5 members, `check-features.sh --targets` 27/27,
`cargo check --workspace` clean per the close brief) — but its own written acceptance item
6 (the npm dependency-boundary gate) is red at HEAD, regressed by the sprint's own final
commit, and was invoked by nothing until this audit and a concurrent sibling independently
found it (F2). Four of seven (#282, #239, #235, #266) fail their literal acceptance outright,
with #266 having moved backward rather than forward. Layered on top: a SUBTRACT-VIOLATION
against the seed's own explicit pre-authorization terms (F1) and a CRITICAL dogfood row
whose prescribed fix was never built despite a FIX-THIS-RUN label (F3). Per
`skills/shepherd/references/grading-rubric.md`, the SUBTRACT-VIOLATION alone caps the
concern at C+; the volume and severity of failed acceptance lines (4 of 7 outright, plus a
regressed CRITICAL gate) is the "multiple HIGH findings… SUBTRACT violation" shape of the
**C** row rather than the softer C+ cap.

What keeps this from D: the sprint's own self-monitoring was exceptional and is the reason
most of these findings have paper trails at all. `.shepherd/runs/v645/dogfood.md`'s 78
entries are unusually rigorous — falsified with mutation tests, positive/negative controls,
and honest self-refutation (DF-07, DF-44, DF-53 all struck by the run's own later evidence
rather than left to stand). Six new GH issues (#284–#289) were filed this sprint, all
independently confirmed here as real, correctly scoped, and non-duplicate; a seventh
(#290) was filed live by a sibling auditor converging on the same npm-dependency finding
this report reached independently; an eighth (#293) was filed by this audit. The one
operator amendment (`v645-pc-1.md`) is fully and verifiably landed, both prose and
enforcement, with positive and negative test controls (Verification 3). Most of the
dogfood ledger's CRITICAL rows genuinely do carry a verified fix (spot-checked DF-56,
DF-68, DF-71 in addition to the seven acceptance lines above). This is a sprint that found
its own defects honestly and mostly fixed what it found — the grade reflects that the seed's
own bar, measured at close, was not met on a majority of its named deliverables, not that
the process was undisciplined.

## Output to conductor

```
## AUDITOR REPORT
- deliverable: 25 (status: delivered)
- Concern: completeness
- Mode: close
- Files reviewed: 7 seed deliverables (acceptance re-run), dogfood.md (78 rows), 1
  dispatcher-patch, 6 pre-existing + 4 newly-observed GH issues
- Findings: CRITICAL=3, HIGH=4, MEDIUM=1, LOW=0
- Verifications (disproved): 3
- Open questions: 2
- GH issues filed: #293 (new); corroborated #290 (sibling-filed, same session)
- Grade: C
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/close-completeness.md
- Hot-fix-lane recommendations: 2 (F2 npm dependency-gate regression + CI wiring; F6
  launcher unbound-variable diagnostic crash, GH #293)
- Sprint-pattern entry: skipped (no prior close report exists for this project — first
  adaptation cycle lands at this close, per shctx adapt report)
- Agent ID + timestamp: shepherd-auditor-v645-completeness @ 2026-08-14T09:44:55Z
```
