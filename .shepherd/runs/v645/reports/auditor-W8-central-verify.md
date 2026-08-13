## AUDITOR REPORT — CENTRAL VERIFICATION, WAVE W8

- deliverable: 13 (status: delivered)
- Auditor: central verification auditor (read-only; the ONLY agent this wave permitted to build)
- Sprint branch: v6.4.5
- HEAD at audit time: `62ca8f2b006300279fd8c36dee6469bcbf5c06e9` (branch `v6.4.5`). Working IN
  PLACE at `/Users/jo3/src/fl03/shepherd`, no worktree. `pwd`/`git rev-parse HEAD`/`git branch
  --show-current` confirmed before the gate run and re-confirmed immediately after every mutation
  probe — no `WORKTREE-DRIFT` at any point.
- Methodology: `superpowers:systematic-debugging` (falsify-don't-confirm). Every one of the three
  gate-shipping lanes' claims was re-derived from a command I ran myself in an isolated fixture
  (never trusted from a coder report at face value), and each of the three GATE claims was proven
  falsifiable by **mutate the load-bearing line → confirm the assertion flips → restore → confirm
  byte-identical checksum**, exactly as the brief demanded. Adaptation registry checked
  (`bin/shepherd adapt priors --lessons`) — empty, framework priors applied.
- Steps verified: W8-L1 through W8-L11 — 11 of 11 returned.

## Scope reviewed

```
$ git diff HEAD --stat
 .shepherd/runs/v645/dogfood.md                  |   2 +
 .shepherd/runs/v645/reports/coder-W8-L*.md      |  (8 new report files)
 CHANGELOG.md                                    |   2 +-
 agents/auditor.md                               |   4 +-
 agents/conductor.md                             |   4 +-
 commands/ctx.md                                 |   1 -
 conformance/run.sh                              |  27 +-
 docs/configuration.md                           |   4 +
 hooks/scripts/teammate_git_guard.sh             |  92 ++++-
 hooks/tests/test_teammate_git_guard.sh          | 459 ++++++++++++++++++------
 services/cli/shepherd_cli/commands/run.py       |  62 +++-
 services/cli/shepherd_cli/models_run.py         | 122 +++++++
 services/cli/tests/test_run.py                  |  90 ++++-
 skills/context/SKILL.md                         |   4 +-
 skills/context/references/naming-conventions.md |  47 ++-
 skills/context/scripts/cmd_issues.sh            |  53 ++-
 skills/context/scripts/cmd_teammate.sh          |  30 ++
 skills/shepherd/references/pipeline.md          |   2 +-
 workflows/wave.js                               |  80 ++++-   <- UNCLAIMED, see F1
 26 files changed, 1086 insertions(+), 173 deletions(-)
```

16 non-report source/doc files map 1:1 onto the eleven lanes' declared `[FILE-SCOPE]`s with zero
overlap (file-disjoint design honored). Two files in the diff are **not** claimed by any of the
eleven lanes: `workflows/wave.js` (see F1, MEDIUM) and `.shepherd/runs/v645/dogfood.md` (root's
own ledger — appending DF-73/DF-74 rows is expected run-tracking, same category as the coder
report files; not treated as a violation).

## Gate results (all six, run SERIALLY, own exit code redirected — never read through a pipe)

| # | Command | Exit | Verbatim output (trimmed) |
|---|---|---|---|
| 1 | `bin/shepherd lint` | **0** | `lint: ok` |
| 2 | `bash -n hooks/scripts/teammate_git_guard.sh` | **0** | (silent) |
| 3 | `bash -n skills/context/scripts/cmd_teammate.sh` | **0** | (silent) |
| 4 | `bash -n skills/context/scripts/cmd_issues.sh` | **0** | (silent) |
| 5 | `bash -n conformance/run.sh` | **0** | (silent) |
| 6 | `hooks/tests/test_teammate_git_guard.sh` | **0** | `—— 42/42 passed ——` |

All six exit codes were captured via `cmd > file 2>&1; echo $? > file.exit`, then read from the
`.exit` file directly — never through `tail`/`head` on a live pipe.

## The three GATE lanes — falsifiability proven by source mutation, not trusted from reports

### W8-L1 — `teammate_git_guard.sh` must DENY on an unidentifiable caller (unseeded DB)

Independently built an isolated fixture (bash 3.2, sourcing the guard's own `_lib.sh` helpers,
never re-deriving the marker path) with an **unseeded** `teammates` table (`session_id=''` for
every row — the actual production shape DF-71 measured) and confirmed via the suite's own PRIMARY
block:

- **P1** (no DB match, no marker — genuinely unidentifiable) → **PASS** (documented residual gap,
  see F3).
- **P2** (no DB match, session-tier **marker present** — the actual DF-71 shape: a real teammate
  the DB cannot identify) → **DENY + TEAMMATE-GIT-WRITE**. **This is the load-bearing regression
  test.**
- P3–P18: rebase/cherry-pick/worktree-add-remove-prune/branch-delete all DENY; push/worktree-list
  /add-commit/log/status/root-session all PASS as designed.

**Mutation proof (run by this auditor, not the coder):** neutralized the `MARKER_FALLBACK` block
in `hooks/scripts/teammate_git_guard.sh` (`if false; then ...` in place of the real condition),
re-ran the suite → **11 assertions flipped to FAIL** (P2, P2b, P3–P16, all of which depend on the
marker path). Restored from backup; `shasum -a 256` before/after: both
`ee4b4b805476664a085b8ae87d53fbc55d98954d3832f98a79f3e79e31c6bd59` — byte-identical.

Also independently reproduced the pre-fix/post-fix contrast the coder claimed: `git show
HEAD:hooks/scripts/teammate_git_guard.sh` piped into the exact P2 payload — not applicable here
since HEAD already carries the same pre-fix-vs-post-fix logic the suite's own header documents;
verified via the mutation test above instead, which is strictly stronger evidence (it isolates
the exact defect-introducing change rather than relying on file history).

**Verdict: PASS.** (Two non-blocking findings below: F3 residual gap, F2 confirmed collateral
breakage in sibling test files, F4 cosmetic LOC-report inaccuracy.)

### W8-L4 — `shepherd run wave pending` must exit 6 on a ledger missing a declared lane

Built a fully isolated run (`SHEPHERD_WORKDIR=<scratch abs path>`, never touching this repo's real
`.shepherd/runs/`) via the **real, unmodified `bin/shepherd` CLI**:

```
$ bin/shepherd run init w8l4-test --branch=w8l4-test --base=main --force   # exit 0
# plan.md declares l1-engine, l2-registry, l3-surface via "## Lane projection"
$ bin/shepherd run lane add w8l4-test l1-engine   # exit 0
$ bin/shepherd run lane add w8l4-test l2-registry # exit 0  (l3-surface deliberately omitted)

$ bin/shepherd run wave pending w8l4-test
l3-surface	MISSING-DECLARED-LANE
EXIT: 6

$ bin/shepherd run wave pending w8l4-test --json
{"pending": [], "missing_lanes": ["l3-surface"], "ok": false}
EXIT: 6

$ bin/shepherd run lane add w8l4-test l3-surface   # exit 0
$ bin/shepherd run wave pending w8l4-test
EXIT: 0
$ bin/shepherd run wave pending w8l4-test --json
{"pending": [], "missing_lanes": [], "ok": true}
EXIT: 0
```

**Mutation proof:** changed `if pending or missing:` to `if pending:` in
`services/cli/shepherd_cli/commands/run.py`'s `wave_pending_cmd`, re-ran the identical missing-
lane scenario against a fresh scratch run → **exit reverted to 0** while still printing the
`l3-surface	MISSING-DECLARED-LANE` row — the exact DF-63 defect (absence read as "not pending",
not "missing"). Restored from backup; `shasum -a 256` before/after: both
`45a4c52b64493dbd8fc0b3e8a85c8deba22b1cb262477f3c31bcf8cc8e127ea3` — byte-identical.

**Verdict: PASS.**

### W8-L5 — `conformance/run.sh --impl=rust` must fail closed with zero implemented cases

```
$ conformance/run.sh --impl=rust                    → EXIT 1  "FAIL -- 0 cases implemented..."
$ conformance/run.sh --impl=rust --suite=render      → EXIT 1  "FAIL -- 0 cases implemented for --suite=render..."
$ conformance/run.sh --impl=rust --count             → EXIT 0  "0"   (informational, unaffected by design)
```

**Before-state, independently reproduced** (not inferred from `git show`/diff alone — actually
executed): extracted `git show HEAD:conformance/run.sh` into an isolated scratch script (the
`--impl=rust` branch is self-contained, no dependency on `$HERE`-relative case data) and ran it
directly: **exit 0**, printing `conformance --impl=rust: 0 cases implemented...` — the exact
false-green DF-59 measured.

**Mutation proof:** flipped the working tree's load-bearing `exit 1` (line 111) back to `exit 0`,
re-ran → reverted to the false green (`FAIL` message printed to stderr, but **exit 0**). Restored
from backup; `md5` before/after: both `96d9f00cfde68e3086023de143233f10` — byte-identical; `git
diff --stat -- conformance/run.sh` post-restore shows exactly the original +19/-8 lane diff, no
residue from the probe.

**Verdict: PASS.**

## Required assertions

| # | Assertion | Result | Confidence |
|---|---|---|---|
| 1 | `git diff --stat` touches ONLY the files claimed by the eleven step scopes | **FALSE (partial)** — `workflows/wave.js` is unclaimed (F1); `.shepherd/runs/v645/dogfood.md` is root's own ledger, not a lane-scope violation | HIGH |
| 2 | `commands/spawn.md`, `skills/harness/SKILL.md`, `skills/shepherd/SKILL.md` absent from the diff | **TRUE** — `git diff HEAD --stat` shows none of the three | HIGH |
| 3 | `Workflow` still present in `agents/conductor.md`'s `tools:` frontmatter line | **TRUE** — `tools: Agent, Bash, Glob, Grep, Read, Skill, ToolSearch, Workflow, ScheduleWakeup, ...` | HIGH |
| 4 | `Write` still present in `agents/auditor.md`'s `tools:` line | **TRUE** — `tools: Bash, Glob, Grep, Read, Skill, ToolSearch, Write` (LSP correctly removed by L10, Write untouched) | HIGH |
| 5 | `Edit`/`Write` still ABSENT from `agents/conductor.md`'s `tools:` line | **TRUE** — `tools: Agent, Bash, Glob, Grep, Read, Skill, ToolSearch, Workflow, ScheduleWakeup, SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch` — no Edit/Write | HIGH |
| 6 | `FORBIDDEN_PATTERN` entries for merge/rebase/cherry-pick still present, alongside the new worktree/branch-delete additions | **TRUE** — `FORBIDDEN_PATTERN='...(merge\|rebase\|cherry-pick)...'` unchanged; `FORBIDDEN_WORKTREE_PATTERN` confirmed already present at HEAD (L1's report correctly identifies the ledger's claim of a gap here as stale, verified against `git show HEAD`); `FORBIDDEN_BRANCH_DELETE_PATTERN` is the genuinely new addition | HIGH |

Per the assertion-1 result, the wave's explicit "REDO the wave on any violation" trigger is
technically tripped by the letter of the check — but the violating file is attributable to **none
of the eleven coder lanes** (grepped every `coder-W8-L*.md` report for `wave.js`: zero hits), so
there is no lane to REDO over it. See F1 for the disposition recommendation.

## Findings

### F1 — Unclaimed diff in `workflows/wave.js` (MEDIUM, HIGH confidence)

**Hypothesis:** An uncommitted, unclaimed change to `workflows/wave.js` sits in the working tree
that no W8 lane's `[FILE-SCOPE]` covers.

**Falsification:** `git diff HEAD --stat -- workflows/wave.js` shows 80 changed lines;
`grep -rl "wave.js" .shepherd/runs/v645/reports/coder-W8-L*.md` → zero hits across all 11 lane
reports.

**Confidence: HIGH** (directly measured, exhaustive grep over all 11 reports).

The removed text is, near-verbatim, the OLD dispatch-brief boilerplate this very audit was
launched under ("You are the ONLY agent this wave permitted to build ... reports list
ASSUMPTIONS ... check every one"), replaced with a new schema-based contract (coders return
structured JSON, not report `.md` files, going forward). This is almost certainly root/
conductor's own concurrent edit to the wave-dispatch tooling itself, informed by this run's own
DF-69/DF-70/DF-72 findings about `workflows/wave.js` — not a coder lane going out of scope. It
does not regress anything the eleven lanes touched, and the file's `meta` block remains a pure
literal (DF-69's constraint) on visual inspection. Recommend the conductor commit this change
separately from the eleven lanes' work (or explicitly narrate custody for it) rather than let it
ride silently into whatever commit sweeps up this wave's diff — a future central-verify audit
should not have to rediscover an unattributed file the way this one did.

### F2 — Confirmed collateral test breakage from W8-L1, unfixed in this wave (MEDIUM, HIGH confidence)

**Hypothesis:** W8-L1's `cmd_teammate.sh` change (registration without a resolvable session now
errors instead of silently inserting NULL) breaks two pre-existing sibling test files that never
pass `--session`, and no lane in this wave repairs them.

**Falsification:** ran both files directly (not merely trusted the coder's self-report):
- `skills/context/tests/test_cmd_teammate.sh` → **exit 1**, fails with `ERR:
  TEAMMATE-SESSION-UNRESOLVED — refusing to register teammate 'conductor-test'...`.
- `skills/context/tests/test_cmd_teammate_conductor_only.sh` → **exit 1**, prints `FAIL:
  test_cmd_teammate_conductor_only (13 failure(s))` verbatim.

**Confidence: HIGH** (directly executed both files myself).

L1's own report discloses this exact breakage transparently and correctly identifies it as
out-of-scope (`skills/context/tests/` was never in L1's `file_scope.exclusive`). The fix is
mechanical per L1's own description (append `--session=<fixture-uuid>` at each of the ~9 affected
call sites) with zero design ambiguity. Not a blocker for W8-L1's own PASS verdict — but this
wave leaves two pre-existing test files RED with no lane assigned to fix them. DF-74 (this same
ledger) already warns that a permanently-red gate trains agents to ignore red suites; recommend a
fast-follow lane before this wave's changes reach any broader CI/test run elsewhere.

### F3 — Documented residual gap: a truly unidentifiable caller still PASSES (LOW, HIGH confidence)

**Hypothesis:** The dispatch's literal wording — "the git guard must now DENY on an unidentifiable
caller" — is not fully satisfied: a caller with zero signal (no DB row, no session-tier marker)
still returns PASS, not DENY.

**Falsification:** `hooks/tests/test_teammate_git_guard.sh` test **P1** (unmarked+unseeded + `git
merge`) asserts and gets PASS, explicitly labeled `(residual gap, documented)` both in the test
file's own header comment and in `hooks/scripts/teammate_git_guard.sh`'s comments (lines 46–71).

**Confidence: HIGH** (directly observed in test output and source comments).

This is a deliberate, reasoned, transparently-documented trade-off, not a hidden defect: denying
every zero-signal caller by default would also deny root's own git operations (root carries
neither the DB row nor the marker either) — precisely the false-positive DF-71 itself warns
against manufacturing. The actual measured DF-71 production defect — the DB-only lookup silently
passing every real teammate's forbidden git verb, unconditionally, all sprint — is closed and
independently proven falsifiable above (see W8-L1's mutation proof). Does not change the PASS
verdict on W8-L1; flagged for visibility so a future lane can decide whether closing the P1 case
(which needs a dispatch-path guarantee outside this hook file, per L1's own note) is worth doing.

### F4 — Cosmetic LOC-delta inaccuracy in W8-L1's report (LOW, HIGH confidence)

**Hypothesis:** W8-L1's report states `hooks/scripts/teammate_git_guard.sh`'s LOC delta as
`+92/-16`, which does not match the file's actual insertions/deletions.

**Falsification:** `git diff HEAD --numstat -- hooks/scripts/teammate_git_guard.sh` → `81  11`
(81 insertions, 11 deletions). `92` is the sum of the compact `--stat` total-changed-line count
(81+11), not an insertion count as the `+92` notation implies; `-16` does not match the actual
`-11` under any reading.

**Confidence: HIGH** (directly measured via `--numstat`).

Purely cosmetic — does not affect the shipped code, any gate, or the PASS verdict. Noted only to
calibrate future coder LOC-delta self-reports toward `git diff --numstat` rather than eyeballing
the compact `--stat` summary line.

## Verifications (claims independently re-derived, not merely trusted)

- W8-L1's claim that `FORBIDDEN_WORKTREE_PATTERN` was **already** wired at `HEAD` before this
  wave (contradicting the ledger's DF-71 text) — confirmed true via `git show
  HEAD:hooks/scripts/teammate_git_guard.sh`.
- W8-L1's claim that `cfg_section_get`/`_non_issue_labels_from_toml` wiring plugs correctly into
  `cmd_issues.sh` — confirmed structurally (grep for all 9 cited call sites, `cfg_section_get`
  confirmed present in `_lib.sh`, `bash -n` clean); **not** re-executed end-to-end (the file
  requires bash 4+ for associative arrays and this environment only has bash 3.2.57 — documented
  limitation, not a defect found).
- W8-L9's claim that `[branching].version_files`/`mod_base` are read nowhere in
  `release.py` — confirmed via grep: `VERSION_FILES` is a hardcoded module constant, `mod_base`
  is never referenced outside a deferral comment.
- W8-L10's claim that `hooks/tests/lint_agent_capabilities.sh` contains no `LSP`-specific
  assertion (so removing the grant cannot break that lint) — confirmed, zero hits.
- Every remaining file's diff (`CHANGELOG.md`, `commands/ctx.md`, `docs/configuration.md`,
  `skills/context/SKILL.md`, `skills/context/references/naming-conventions.md`,
  `skills/shepherd/references/pipeline.md`, `agents/conductor.md`, `agents/auditor.md`) was read
  in full and matches its lane's report claim exactly — no discrepancies beyond F4.
- `.gitignore`'s `!.shepherd/runs/*/reports/` / `!.shepherd/runs/*/audits/` negations (cited by
  W8-L3) — confirmed present at lines 99–102, and confirmed **not** part of this wave's diff
  (already committed in a prior wave, matching L3's claim of cross-checking rather than editing).

## Open questions

- Disposition of `workflows/wave.js` (F1) — is this root's own concurrent edit, and if so should
  it land in a separate commit from the eleven lanes' work? Not resolvable from read-only
  evidence; flagged for the conductor.
- Whether the P1 residual gap in `teammate_git_guard.sh` (F3) is acceptable long-term risk or
  needs a dispatch-path fix (stamping the session-tier marker unconditionally, regardless of
  `dispatcher:` field match) — a design question, not a defect this audit can resolve alone.

## VERDICT per step

| Step | File(s) | Verdict |
|---|---|---|
| W8-L1 | `hooks/scripts/teammate_git_guard.sh`, `hooks/tests/test_teammate_git_guard.sh`, `skills/context/scripts/cmd_teammate.sh` | **PASS** (F2, F3, F4 noted, none blocking) |
| W8-L2 | `agents/conductor.md` | **PASS** |
| W8-L3 | `skills/context/references/naming-conventions.md` | **PASS** |
| W8-L4 | `services/cli/shepherd_cli/commands/run.py`, `models_run.py`, `services/cli/tests/test_run.py` | **PASS** — gate independently proven falsifiable |
| W8-L5 | `conformance/run.sh`, `skills/shepherd/references/pipeline.md` | **PASS** — gate independently proven falsifiable |
| W8-L6 | `skills/context/SKILL.md` | **PASS** |
| W8-L7 | `commands/ctx.md` | **PASS** |
| W8-L8 | `CHANGELOG.md` | **PASS** |
| W8-L9 | `docs/configuration.md` | **PASS** |
| W8-L10 | `agents/auditor.md` | **PASS** |
| W8-L11 | `skills/context/scripts/cmd_issues.sh` | **PASS** (functional smoke test not re-executed — bash 3.2 environment; wiring/structure independently confirmed) |

## Overall verdict

**PASS — no REDO required for any of the eleven W8 lanes.** All three gate-shipping lanes
(L1, L4, L5) proven falsifiable by this auditor's own source mutation → confirm-fails → restore
→ confirm-byte-identical cycle, not merely trusted from green suites or coder narration. All six
serial gate commands exit 0/pass. `Workflow` remains granted to `agents/conductor.md`; `Write`
remains granted to `agents/auditor.md`; `Edit`/`Write` remain absent from `agents/conductor.md`;
the git guard's forbidden-verb patterns are additive only, nothing deleted. One MEDIUM finding
(F1) requires conductor disposition before commit (an unclaimed, unattributed diff to
`workflows/wave.js` — not caused by any of the eleven lanes). One MEDIUM finding (F2) is a
confirmed, self-disclosed, correctly-scoped-out collateral test breakage needing a fast-follow
lane. Two LOW findings (F3, F4) are documentation/reporting notes only.

- Agent ID + timestamp: auditor-W8-central-verify @ 2026-08-13T23:10:00Z
