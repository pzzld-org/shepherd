---
title: Wave-review audit — lane l6-guards, Wave 2, concern guard-fail-closed
date: 2026-08-13
auditor: shepherd:auditor
sprint: v645
concern: guard-fail-closed
mode: wave-review
methodology: superpowers:systematic-debugging (hypothesis -> falsification -> confidence); every fixture hand-fired against the live UNCOMMITTED worktree file in an independent scratch git repo (bash 3.2.57), not read from or trusted from the coder's/conductor's pasted output
prior_class_priors: empty registry (shctx adapt report: "no sprint metrics recorded yet -- first adaptation cycle lands at this sprint's close") -- framework priors applied
deliverable: 6 (status: delivered)
---

## Scope reviewed

`hooks/scripts/dispatch_guard.sh`, Checks 7 (`AUDIT-CONCERN-UNDECLARED`) and 8
(`DISPATCH-OWNERSHIP-RECORD`), as they currently sit UNCOMMITTED in
`/Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards` (base commit `ada05dd`, HEAD of
that worktree is still `ada05dd` -- nothing committed). Diff reviewed in full
(`git -C .worktrees/v645-l6-guards diff ada05dd -- hooks/scripts/dispatch_guard.sh`: 1
file changed, 190 insertions(+), 0 deletions -- confirmed additive-only). Also read
`hooks/scripts/_lib.sh` in full (the guard's only sourced library: `emit_deny`,
`emit_context`, `resolve_namespace`, `hook_db_path`, `json_field`), the lane plan in full
including `## Deviations` (both mid-wave retargets: Check 8's deny->recorder retarget, and
the perf-fix retarget), and `hooks/tests/test_dispatch_guard.sh`'s Check 6/7/8 sections
(read for context, not trusted as ground truth -- every claim it makes was independently
re-fired). Files reviewed: 2 (the guard, the shared lib) read in full; the lane plan and
test suite read for context and cross-checked, not merely trusted.

Session stayed at sprint root (`/Users/jo3/src/fl03/shepherd`, branch `v6.4.5`, no `cd`
into the worktree) throughout; all worktree inspection used `git -C
.worktrees/v645-l6-guards` and absolute-path `Read`. All hand-fired fixtures ran against
an independent scratch git repo (outside both the sprint root and the worktree) invoking
`bash .../hooks/scripts/dispatch_guard.sh` by absolute path with piped stdin JSON, and
against the real `hooks/tests/test_dispatch_guard.sh` run by absolute path, per the
brief's instruction not to `cd`.

## Findings summary

CRITICAL=1, HIGH=0, MEDIUM=0, LOW=0. Verifications (disproved concerns / confirmed
claims): 3. Open questions: 1.

## Findings

### FINDING 1 (CRITICAL) — Check 6's pre-existing, unrestructured `emit_context` exit
makes Checks 7 and 8 structurally unreachable for a teammate-conductor's `@auditor`/`@coder`
dispatch -- the exact topology that produced the DF-44 incident this lane exists to close

**Hypothesis.** `hooks/scripts/_lib.sh`'s `emit_context()` calls `exit 0` unconditionally
(lines 454-462). Check 6 (`PRIMITIVE-INVERSION`, pre-existing, unrestructured by this wave)
fires via `emit_context` whenever `teammate_mode == 1` AND `subagent_type` matches
`^shepherd:(coder|auditor)$` (lines ~301-319), and it sits textually *before* Check 7 (line
335) and Check 8 (line 399) in this file's documented "first-match-wins,
single-exit-per-invocation" architecture (the file's own header, and Check 8's own comment
block: "a check that fires via emit_deny/emit_context upstream has already exited before
this point"). `teammate_mode` is set to 1 primarily from `cwd == */.worktrees/*` (line
137-139) -- the PRIMARY, documented signal for a lane teammate-conductor's own working
directory. Therefore: any `@auditor` or `@coder` dispatch issued by a lane conductor from
inside its own `.worktrees/<lane>` cwd -- the two highest-volume dispatch types in this
sprint's actual execution model, and precisely the two `subagent_type`s Check 6 matches --
will trip Check 6 first under default config and NEVER reach Check 7's deny or Check 8's
recorder, regardless of how many `[CONCERN]` tags the prompt carries or whether the
registry is writable.

**Falsification.** Hand-fired against the current (post-perf-fix) worktree file, in a
scratch git repo (`git init`, `.claude/shepherd.toml` present, bash 3.2.57 -- matches
production macOS bash):

```
payload: {"session_id":"s-df44","tool_name":"Agent",
  "cwd":"/Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards",
  "tool_input":{"subagent_type":"shepherd:auditor","model":"opus",
    "prompt":"Please audit code-quality, data-flow, dependency-topology, datastore-state,
              and completeness for this wave. Bundle all five into one report."}}
  # zero [CONCERN] tags -- the literal DF-44 shape

result: {"additionalContext":"[shepherd] PRIMITIVE-INVERSION (flag) -- hand-rolled
  fan-out where a compiled Dynamic Workflow is required (#263). ..."}
```

- `grep -o "AUDIT-CONCERN-UNDECLARED"` on the output: no match.
- `grep -o '"permissionDecision":"deny"'` on the output: no match (not a deny).
- `sqlite3 .shepherd/shepherd.db "SELECT * FROM dispatch_ownership WHERE session_id='s-df44';"`:
  `Error: in prepare, no such table: dispatch_ownership` -- Check 8 never ran either, the
  table was never even created.

Repeated with `subagent_type: shepherd:coder` and a `.worktrees` cwd: identical outcome
(Check 6 fires, no ownership row, `no such table: dispatch_ownership`).

Confirmed no config override is present: `grep -rn flag_handrolled_fanout` across the
worktree's `.claude/`/`.shepherd/` config surfaces returns nothing, so the check's stated
default (ON) is the live behavior. Confirmed no earlier check (1-5) intervenes in this path
-- with no `team_name`, no `dispatcher: engineer-self-contained` marker, and
`subagent_type=shepherd:auditor`, none of Checks 2/3/4/4'/4b/4c/5's conditions are met; the
single barrier between the payload and Check 7 is Check 6.

Confirmed this is not a hypothetical topology: the lane plan's own `## Deviations` section
(`DISPATCHER-PATCH from root`) states the actual DF-44 incident -- the five-concern bundled
`@auditor` dispatch this entire lane exists to make "mechanically impossible" -- was issued
by "l2-registry conductor," i.e. a lane teammate-conductor, which by the same
`.worktrees/<lane>` convention this guard itself relies on (cited in its own header:
"a shepherd teammate runs in a `.worktrees/` worktree,
commands/spawn.md §Worktree-per-teammate") was necessarily running with `teammate_mode=1`.
**Check 7 as shipped would not have denied the literal historical incident it cites as its
own motivating authority (agents/auditor.md:92, DF-44).**

The file's own header comment claims: "Check 7 (concern-declaration discipline) is
LOAD-BEARING and MECHANICAL: it fires on every `shepherd:auditor` dispatch." This claim is
false as shipped -- it fires only when `teammate_mode == 0` (root dispatching directly, not
via a lane conductor), which is the minority topology in this sprint's actual execution
model (dispatch happens overwhelmingly through teammate-conductors operating from their own
lane worktrees, per this very audit's own `[ROLE]` header: "dispatcher: teammate-conductor
(l6-guards)").

Contributing evidence: `hooks/tests/test_dispatch_guard.sh`'s Check 7 and Check 8 fixture
sections (lines 233-352) contain zero fixtures that set a `.worktrees` `cwd` or a teammate
env var -- every Check 7/8 fixture in the new suite runs with `teammate_mode=0` by
construction (the shared `P()` helper never sets `cwd`), so the suite's 100% pass rate is
fully consistent with this gap and provides no coverage against it. (This observation is
recorded here for `guard-fail-closed` since it is the direct cause of the gap going
undetected; the suite's own completeness is `test-integrity`'s concern to grade, not
duplicated as a second finding here.)

**Confidence: HIGH** -- directly, repeatedly reproduced against the live uncommitted file
via independent hand-fired fixtures (not the coder's or conductor's pasted output), with
the exact historical incident's dispatcher topology independently confirmed from the lane
plan's own record.

**Suggested fix (same file, `hooks/scripts/dispatch_guard.sh`, no change to Checks 1-6's
own logic required):** relocate the Check 7 and Check 8 blocks to execute *before* Check 6
(i.e. immediately after Check 5, ahead of Check 6's `if` block) -- a pure textual
reordering. This lets Check 7's deny (a hard violation) and Check 8's non-denying record
run first; Check 6's advisory flag still fires afterward for any dispatch that survives
both, unchanged in its own content or logic. A deny/record must not be preemptable by a
lower-priority advisory flag that happens to be declared earlier in file order. Add at
least one regression fixture per check with a `.worktrees` `cwd` (or teammate env var) set,
so this exact class of bug cannot regress silently again.

## Verifications (claims independently re-run, not just trusted)

### V1 -- Check 7's own DENY/DENY/PASS logic is correct (disproved: "Check 7 is broken")

Hand-fired 3 fixtures against the current worktree file, scratch repo, `teammate_mode=0`
(no `.worktrees` cwd, no teammate env vars):

- Zero `[CONCERN]` declarations -> deny; message cites `agents/auditor.md:92` verbatim
  ("brief's `concern` field is authoritative -- NEVER collapse two into one report."),
  states "declarations found: 0", and explicitly states a prose mention of the word
  "concern" does not count.
- Two `[CONCERN]` declarations (`code-quality`, `data-flow`) -> deny; message lists
  "Found 2: code-quality, data-flow." and "Split into 2 separate dispatches, one [CONCERN]
  <slug> each."
- Exactly one `[CONCERN]` declaration -> silent pass (empty stdout, rc=0).

All three match spec exactly. **Confidence: HIGH.** The defect in Finding 1 is purely about
*reachability* under `teammate_mode=1`, not about Check 7's own conditional logic, which is
correctly implemented.

### V2 -- Check 8 never denies; both fail-visible branches name the real underlying error
(disproved: "Check 8 has a hidden deny path" / "the mkdir-vs-sqlite3 branch split silenced
one of the error messages")

`grep -n emit_deny` across the file returns 9 hits; the only one inside or after Check 8's
code range (line 362 onward) is the line-357 hit, which is textually *inside Check 7's*
block (Check 7: 323-361; Check 8: 362-486) -- zero `emit_deny` calls anywhere in Check 8's
own code.

Hand-fired both fail-visible branches independently, using `SHEPHERD_WORKDIR=<bad-path>`
(confirmed via direct read of `hooks/scripts/_lib.sh:184-205` that `resolve_namespace()`
honors `SHEPHERD_WORKDIR`/`SHCTX_ROOT_OVERRIDE`, never `$SHCTX_DB` -- that is the
skills-side `shctx_db_path()`'s variable, `services/cli/shepherd_cli/resolution.py:183`, a
different code path entirely; the coder's stated correction in the lane plan is accurate):

- `SHEPHERD_WORKDIR` routed through a regular file (mkdir -p must fail): output
  `additionalContext` = "registry directory create failed", `error:` field = the real
  `mkdir` stderr ("mkdir: .../blocker-file: Not a directory"). No deny, rc=0.
- `SHEPHERD_WORKDIR` pointed at an existing `chmod 000` directory (sqlite3 open must fail):
  output `additionalContext` = "registry write failed", `error:` field = the real `sqlite3`
  stderr ("unable to open database file"). No deny, rc=0.

Both split branches (mkdir vs. sqlite3, split mid-wave per the perf fix) independently name
the real underlying error -- confirms the lead's specific flag (item 5) is a non-issue: the
split did not leave either branch warning without naming what actually failed.

Also independently confirmed, on a well-formed dispatch with `teammate_mode=0` (so Check 6
does not intervene): a genuinely inspectable row is written with correct
`session_id`/`subagent_type`/`model`/`concern_slug` fields; `lane` correctly resolves from
either a `.worktrees/<lane>` segment in `cwd` or, absent that, from a `.worktrees/<lane>`
substring in the prompt; and `lane` is correctly left `NULL` (not fabricated) when neither
source contains a worktree path. **Confidence: HIGH.**

### V3 -- Checks 1-6 unrestructured; perf fix did not change DENY/RECORD/fail-visible
behavior; static checks clean (disproved: "the diff touched existing checks" / "the perf
fix silently changed behavior" / "bash -n or shellcheck are not actually clean")

`git -C .worktrees/v645-l6-guards diff ada05dd --stat -- hooks/scripts/dispatch_guard.sh`:
`1 file changed, 190 insertions(+)` -- zero deletions; `grep '^-'` on the diff (excluding
the `--- a/...` file header line) returns nothing. `bash -n`: clean, exit 0. `shellcheck
--severity=warning`: clean, exit 0, zero findings. `PRAGMA journal_mode=WAL` confirmed
genuinely active (not just claimed): `.shepherd/shepherd.db-wal` and `-shm` sidecar files
were created on every write during this session's fixture runs. Full
`hooks/tests/test_dispatch_guard.sh` run (absolute path, no `cd`): every printed line
`PASS`, 0 `FAIL`, ~3.9s wall (within noise of the plan's accepted ~3.7s figure on a
possibly-loaded box; not flagged as its own finding since the plan explicitly says "do not
chase 2s" and this is not a regression against the corrected baseline). **Confidence:
HIGH.**

## Open questions

- Whether Check 6's own `PRIMITIVE-INVERSION` reminder text should be extended to
  explicitly warn "downstream Checks 7/8 were also skipped by this exit" so an operator
  reading only Check 6's flag has a chance to notice the compounding gap even before
  Finding 1's reordering fix lands -- this is a secondary/defense-in-depth question, not a
  substitute for the reordering fix itself, and is left open rather than asserted as a
  requirement since the reordering fix alone fully closes the gap. (LOW confidence either
  way on whether it's worth the extra text; belongs in `## Open questions` per the
  no-low-confidence-findings rule.)

## Cache telemetry

N/A -- wave-review mode; cache telemetry is a completeness/close-mode check only.

## Pattern delta

N/A -- wave-review mode; pattern delta is a completeness/close-mode check only.

## Grade

N/A -- wave-review mode does not grade (PASS/REDO only, see verdict block below).

## Grade rationale

N/A -- wave-review mode.

## WAVE-REVIEW VERDICT

- Lane / wave: l6-guards / w2
- review_verdict: REDO
- Checklist hits: intent=1, fragile-global=0, reinvention=0, passes-local-breaks-CI=0
- Suggested redo: { author: W2-G1 coder (dispatch_guard.sh, agent `a0b78876849fcdc8a` per
  the lane plan), scope: `hooks/scripts/dispatch_guard.sh` only, change: relocate the
  Check 7 (`AUDIT-CONCERN-UNDECLARED`) and Check 8 (`DISPATCH-OWNERSHIP-RECORD`) blocks to
  execute immediately after Check 5 and before Check 6 -- a pure textual reordering, zero
  logic change inside Checks 1-6 or inside Check 7/8 themselves -- so a deny/record is never
  preemptable by Check 6's lower-priority advisory flag; add at least one Check 7 and one
  Check 8 regression fixture with a `.worktrees` `cwd` set (or a teammate env var) to
  `hooks/tests/test_dispatch_guard.sh` (W2-G2's file) so this class of bug has coverage
  going forward. }
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/audits/audit-wave-review-l6-guards-w2-guard-fail-closed.md
- Agent ID + timestamp: shepherd:auditor (wave-review, l6-guards w2, concern
  guard-fail-closed) @ 2026-08-13T19:28:13Z
