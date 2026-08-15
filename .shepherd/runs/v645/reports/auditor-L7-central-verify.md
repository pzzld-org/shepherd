## AUDITOR REPORT — CENTRAL VERIFICATION, LANE l7-substrate

- Auditor: shepherd-conductor-v645-l7-substrate (central verification auditor, read-only)
- Sprint branch: v6.4.5
- Base commit: c17ad80 (dispatch-stated); actual HEAD at audit time: `1441b5d` — two commits
  ahead of c17ad80 (`2fea02d` root-output-budget amendment, `1441b5d` the wave.js meta-literal
  hotfix named in the dispatch). Working IN PLACE, no worktree, at
  `/Users/jo3/src/fl03/shepherd`.
- Methodology: `superpowers:systematic-debugging` (falsify-don't-confirm) — every acceptance
  claim re-derived from a command I ran myself, never taken from a coder report; every
  grep-based check proven falsifiable by mutation before being trusted.
- Steps verified: L7-S1 (`commands/spawn.md`), L7-S2 (`skills/harness/SKILL.md`), L7-S3
  (`skills/shepherd/SKILL.md`)

## Pre-flight

```
$ pwd && git branch --show-current && git rev-parse HEAD
/Users/jo3/src/fl03/shepherd
v6.4.5
1441b5d38ffd93307ce3e81853c6289e40df2108
```
No `WORKTREE-DRIFT`: every gate below ran at this same HEAD, in place, before and after.

```
$ bash /Users/jo3/.claude/plugins/cache/shepherd/shepherd/6.4.4/scripts/df-guard.sh --min=12
df-guard: 9Gi available at . (min 12Gi) — INSUFFICIENT
exit 1
```
Disk is at 98% capacity (9.4Gi free of 460Gi). Per doctrine this guard gates cargo
invocations; I confirmed neither `bin/shepherd lint` (a bash entrypoint that shells to
`poetry run` / `python3 -m shepherd_cli`, `grep -n cargo bin/shepherd` → 0 hits) nor
`hooks/tests/run.sh` (the two `cargo` hits inside it are literal test-fixture strings passed
to `bash_guard.sh`, never executed) invoke `cargo`, so I proceeded without a build. **Flagging
the 9.4Gi/98%-full headroom to root as an operational risk independent of this lane's PASS** —
see Open questions.

## Steps to verify — results

### L7-S1 — `commands/spawn.md` — PASS

Re-ran every acceptance grep myself (not the coder's counts, my own):
```
$ grep -n "teammateMode" commands/spawn.md        → 7 matches (lines 51,116,132,133,134,135,144)
$ grep -n "claude-swarm-<lead-pid>" commands/spawn.md → 2 matches (lines 138, 157)
$ grep -n "backendType" commands/spawn.md          → 7 matches
$ grep -n "UNTESTED" commands/spawn.md             → 1 match, line 141: "What `\"auto\"` resolves
   to on any given box is UNTESTED"
$ grep -c "^### Check 1" commands/spawn.md         → 1
```
All PASS. `git diff -- commands/spawn.md` read in full (66 lines changed, +53/-13 via
`git diff --numstat`): Check 1 is rewritten into 5 numbered steps (env check + folded probe
note; compute/print predicted `backendType`; state what each backend carries; confirm via
correct oracles, bare `tmux ls` explicitly named and forbidden; permission-mode inheritance,
unchanged). No settled/unhedged claim about what `teammateMode: "auto"` resolves to — see
lane-specific check 3 below for the adversarial version of this check.

**Minor report-accuracy discrepancy (non-blocking):** the coder's own report cites match
counts of 5 for `teammateMode`/`backendType` (actual 7) and calls the UNTESTED-language and
permission-mode-inheritance items "step 5"/"step 6" (actual numbered-list positions are step 2
and step 5 respectively — the list has 5 items total, not 6). Content is correct; the
self-report's own bookkeeping is off. See Findings.

### L7-S2 — `skills/harness/SKILL.md` — PASS

```
$ grep -n "claude-swarm-<lead-pid>" skills/harness/SKILL.md → 2 (lines 76, 332)
$ grep -n "tmux ls" skills/harness/SKILL.md                 → 2 (lines 78, 327) — both inside
   sentences stating it reads the DEFAULT socket and is a false-negative-by-construction;
   neither recommends it as an oracle. Read in full context (offsets 60-99 and 300-344).
$ grep -n "teammateMode" skills/harness/SKILL.md            → 1, line 70, spawn-time semantics
   present verbatim: "`teammateMode` is read at SPAWN time, never at session start..."
$ grep -n "separate.*CLI process\|separate.*claude.*process" skills/harness/SKILL.md → 2
   (lines 84, 165)
$ grep -c "WORKFLOW-VEHICLE-PROBE" skills/harness/SKILL.md  → 4, all pre-existing, none of the
   four hunks in `git diff -- skills/harness/SKILL.md` touch this string (confirmed by reading
   every hunk — the diff only adds three new bullets under `## Agent Teams`, one new paragraph
   under `## Workflow tool` citing `Run ID: wf_020292db-fef`, one new paragraph under
   `## Tool presence`, and one new paragraph on tool-delta tallies near the end)
```
`git diff --numstat` → +57/-1. All hunks read line-by-line; every new claim is attributed to
DF-64/DF-65/DF-68 and is consistent with the corresponding rows in
`.shepherd/runs/v645/dogfood.md` (cross-checked verbatim — the `Run ID: wf_020292db-fef` and
`shepherd-probe-v645-wf`/`backendType: tmux` facts in the diff match DF-68's own evidence
column exactly). No blanket "all teammates uniformly lose/keep Workflow" claim found (the
`## Workflow tool` "Genuinely absent" bullet stays scoped to the substrate-absent case, as the
coder reported).

**Report-accuracy discrepancy (non-blocking):** coder claimed LOC delta +44/-1; actual
`git diff --numstat` is +57/-1, a 13-line (~30%) undercount. See Findings.

### L7-S3 — `skills/shepherd/SKILL.md` — PASS

```
$ grep -n "PROBE-FALSIFIABILITY" skills/shepherd/SKILL.md → 1, line 79
$ grep -n "positive control" skills/shepherd/SKILL.md     → 1, line 79
$ grep -n "DF-68" skills/shepherd/SKILL.md                → 1, line 79
$ git diff --numstat -- skills/shepherd/SKILL.md          → 2  0  (2 insertions, 0 deletions)
```
Matches the coder's report exactly. Content read in full: the new paragraph sits immediately
after the untouched WORKFLOW-VEHICLE-PROBE paragraph (line 77) and a blank separator (line 78),
before `## Root contract`. It correctly cites `agents/auditor.md §Per-finding contract`
(verified this is in fact my own role's contract — Hypothesis + Falsification + Confidence) as
the analogue it generalizes.

**Cross-run duplicate dispatch, self-corrected — not an L7 defect, flagged for root.** A
second, independent coder report exists at
`.shepherd/runs/v645/reports/coder-W7-S3.md`, dispatched for the *identical* deliverable
(same target file, same `PROBE-FALSIFIABILITY` paragraph) under a different lane-id
(`W7-S3` vs `L7-S3`). That coder's own `[DO-NOT-DUPLICATE]` grep caught the existing L7-S3
paragraph, correctly made **zero writes**, and filed an INSIGHTS entry recommending a
mesh-time cross-run duplicate-target check. I independently confirmed via `git status` and
`git diff` that no double-write occurred — `skills/shepherd/SKILL.md`'s diff is exactly the
2-line L7-S3 paragraph, nothing more. This is a dispatch-planning gap (two lane-ids issued for
one file+deliverable), not a coder-side violation, and it did not touch my file-scope check.
Recorded in Open questions for root; not a REDO trigger for L7.

## Lane-specific items (dispatch-required)

**1. FILE-SCOPE DISCIPLINE — PASS.**
```
$ git diff --name-only
commands/spawn.md
skills/harness/SKILL.md
skills/shepherd/SKILL.md
```
Exactly the three expected files, nothing else. `workflows/wave.js` does NOT appear here
because its hotfix is already committed at HEAD (`1441b5d`), not a working-tree diff — matches
the dispatch's own framing ("already-landed"). Confirmed no other tracked file shows as
modified in the working tree **at the time this check ran**. See addendum at the end of this
report — `workflows/wave.js` began showing as a live working-tree modification later in this
same audit session, from concurrent lane activity, not from anything L7 or I did.

Note for root, not a scope violation against L7: `git diff --name-only c17ad80 HEAD` (i.e.
committed history since the stated base, not the working tree) shows 5 files across 2
commits — `workflows/wave.js`, `.shepherd/runs/v645/dogfood.md`,
`.shepherd/runs/v645/reports/coder-L7-wave-js-hotfix.md` (the named hotfix, commit `1441b5d`)
plus `agents/shepherd.md` and `.shepherd/dispatcher-patches/v645-pc-1.md` (commit `2fea02d`,
"hard output budget on the root profile" — not named in this dispatch's "one hotfix" framing).
Since this is an in-place shared working tree, this is almost certainly a concurrent,
unrelated lane's already-landed commit, and it does not intersect L7's three files
(`git diff c17ad80 HEAD -- commands/spawn.md skills/harness/SKILL.md skills/shepherd/SKILL.md`
→ empty, confirming none of those two extra commits touched anything in L7's scope). Flagging
only because the dispatch undercounted committed history by one commit; not a finding against
L7.

**2. DF-60 RETRACTED remediation NOT executed — PASS.**
```
$ grep -n "DF-60" .shepherd/runs/v645/dogfood.md
```
→ Row present, status `RETRACTED`, text: "**SUPERSEDED BY DF-68 — DO NOT EXECUTE.** ... every
deletion prescribed below would remove a live capability from the plugin."

```
$ grep -n "^tools:" agents/conductor.md
tools: Agent, Bash, Glob, Grep, Read, Skill, ToolSearch, Workflow, ScheduleWakeup, SendMessage,
TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
$ git status --porcelain -- agents/conductor.md    → (empty, untouched)
$ git diff c17ad80 HEAD -- agents/conductor.md     → (empty, no diff in committed history either)
```
`Workflow` grant intact; file completely untouched by this wave.

```
$ diff <(git show c17ad80:skills/shepherd/SKILL.md | sed -n '77p') \
       <(sed -n '77p' skills/shepherd/SKILL.md)
(no output — byte-identical)
```
The WORKFLOW-VEHICLE-PROBE PRESENT branch is byte-identical to base c17ad80, verbatim,
including "**Present** → you are on a live Agent-Teams teammate substrate: compile and dispatch
a Dynamic Workflow." DF-60's prescribed deletion of this branch did not happen.

**Falsifiability proof (mutation test):** I replaced this exact sentence in the live file with
a stand-in for what DF-60's remediation would have produced ("**Present** → deleted per DF-60
remediation, this branch is dead code."), re-ran the same byte-identity diff, and confirmed it
now returns a non-empty diff with exit code 1 — proving the check can actually fail, not just
pass by construction. Restored from a pre-mutation `cp` backup (not `git checkout`, to avoid
any risk to other lanes' legitimate uncommitted edits sharing this working tree) and confirmed
MD5 `7c441d9bf1c57b2795dd82b39dab8f7e` before and after, byte-identical restore.

**3. NO NEW TEXT ASSERTS A SETTLED RESOLUTION FOR `teammateMode: "auto"` — PASS.**
Read every hunk of `git diff -- commands/spawn.md` (reproduced in full above under L7-S1).
The only `"auto"`-specific text is: `` `teammateMode: "auto"` → predicted `backendType=UNRESOLVED`.
**Do not** guess tmux vs. in-process from `$TMUX`/`$TERM_PROGRAM`/`it2` presence — that
inference is UNSOUND... **What `"auto"` resolves to on any given box is UNTESTED** and MUST be
measured via the oracles in step 4 — say so explicitly rather than asserting an outcome. ``
Properly hedged throughout; no flat "auto resolves to X" claim anywhere in the diff.

**Falsifiability proof (mutation test):** I injected a fabricated settled claim
(`` `teammateMode: "auto"` resolves to in-process on this box, settled. ``) in place of the
real hedged bullet, confirmed `grep -n 'resolves to in-process on this box, settled'
commands/spawn.md` matches (proving a REDO-worthy violation of item 3 would be caught) and that
`grep -c 'backendType=UNRESOLVED' commands/spawn.md` drops to 0. Restored from backup;
confirmed MD5 `0ef1b953dc7503ec5b524f13a450a487` before and after, byte-identical.

**4. Standard wave-review checklist — PASS, zero hits.**
- Intent: each step's own acceptance predicates hold under my independent re-run (all three
  step sections above).
- No fragile global: no build flag, workspace feature, or env var was added; all three diffs
  are prose-only additions to doctrine/command markdown.
- No reinvention: cross-checked that the three files cross-reference rather than re-derive —
  `skills/harness/SKILL.md:139` points at `commands/spawn.md:73` as the canonical
  discriminator; `commands/spawn.md` step 4 and `skills/harness/SKILL.md`'s oracle bullets
  state the identical `tmux -L claude-swarm-<lead-pid> ls` + `backendType` oracle without
  contradiction. `PROBE-FALSIFIABILITY` (L7-S3) does not pre-exist anywhere else in the
  codebase outside dogfood.md/report/custody artifacts (`grep -rn "PROBE-FALSIFIABILITY"
  --include="*.md" .` confirms the only doctrine-file hit is the new line 79).
- No passes-local-breaks-CI: no code, CI config, or test file was touched by any of the three
  steps; see gate results below for the one pre-existing, unrelated failure I found and ruled
  out as caused by this wave.
- Additional code-quality sweep: `git diff -- <3 files> | grep -nE '^\+.*\b(TODO|FIXME|XXX|
  HACK)\b'` → 0 hits. No merge-conflict markers in any of the 3 files. Heading counts sane
  (`### Check 1 —` = 1, `## Dispatch law` = 1, `## Agent Teams`/`## Workflow tool`/
  `## Tool presence` = 1 each — no duplicated/orphaned sections introduced).

## Gates (run SERIALLY, own exit code read immediately after each command, never through a pipe)

```
$ bin/shepherd lint > lint-out.txt 2>&1; echo $? > lint-exit.txt
$ cat lint-exit.txt
0
$ tail -1 lint-out.txt
lint: ok
```
**PASS.**

```
$ [ -x hooks/tests/run.sh ] && echo EXECUTABLE
EXECUTABLE
$ hooks/tests/run.sh > hookstest-out.txt 2>&1; echo $? > hookstest-exit.txt
$ cat hookstest-exit.txt
3
$ tail -1 hookstest-out.txt
—— 81/84 passed ——
```
**NOT a clean PASS — reporting the true exit code, not laundering it.** 3 of 84 assertions
failed, all inside `test_config_precedence.sh` (`config-files-full-chain-in-order`,
`artifacts-namespace-tiers-1-2`, plus the suite-level `FAIL config-precedence` rollup line).
Failure symptom: expected path list starts with `/private/var/folders/...`, actual starts with
`/var/folders/...` for macOS `$TMPDIR` — a symlink-resolution mismatch (`/private/var` vs
`/var`) in the config-file-chain assertion, unrelated in every particular to substrate/teammate
doctrine.

**Root-cause check for whether this wave caused it (falsify, don't assume):**
```
$ git diff c17ad80 HEAD -- hooks/tests/test_config_precedence.sh   → (empty)
$ grep -n 'LIB=' hooks/tests/test_config_precedence.sh
LIB="$(cd ../scripts && pwd)/_lib.sh"
$ git diff c17ad80 HEAD -- hooks/scripts/_lib.sh                    → (empty)
$ git log --oneline -3 -- hooks/tests/test_config_precedence.sh
894b3fe fix: restore the plugin root layout and gate it
a8fbbbb update
b2f0f06 v6.4.2: bug-hunt, optimization, and the harness-neutral config pipeline (#258)
```
The test file and the library it exercises (`_lib.sh`) are both byte-identical between base
`c17ad80` and HEAD — neither was touched by any commit in this wave's range, and none of L7's
three files (all markdown) can affect bash path-resolution logic. Last real change to the test
predates this wave by three commits (`894b3fe`). **Verdict: pre-existing, environmental
(macOS TMPDIR realpath symlink), unrelated to L7 — not a REDO trigger for this lane**, but a
genuine unfiled failure at current HEAD that root should know about (`no passes-local-breaks-CI`
checklist item: this is "fails locally too," the opposite failure mode, so it does not trip
that item either).

The exit-3 state itself is proof the suite is a live, falsifiable gate (it is currently red on
an unrelated axis) — I did not additionally need to mutate this specific suite to prove
falsifiability, since it is observably not vacuously green.

## Findings

**F1 — Coder self-report count/numbering inaccuracies (L7-S1, L7-S2). Severity: LOW.**
- Hypothesis: coders wrote their acceptance-check bullet lists from a first-draft read rather
  than re-grepping after their own edits settled, so counts/positions drifted from the final
  file.
- Falsification: `grep -n "teammateMode" commands/spawn.md` → 7 matches vs. coder-claimed 5;
  `grep -n "backendType" commands/spawn.md` → 7 vs. claimed 5; coder's "Check 1 step 5"/"step
  6" citations for the UNTESTED-language and permission-mode-inheritance bullets are actually
  step 2 and step 5 (list has 5 items, not 6) — re-confirmed via
  `grep -n "^[0-9]\. \*\*" commands/spawn.md`. L7-S2's claimed LOC delta `+44/-1` vs. actual
  `git diff --numstat` `+57/-1`, a 13-line undercount.
- Confidence: HIGH (directly grep/numstat-verified against the live file, not inferred).
- Impact: none on correctness — every underlying acceptance predicate independently re-verified
  true above. This is a report-accuracy defect only; flagged because the coder report is itself
  a durable artifact per this project's own principle, and imprecise self-verification bullets
  erode trust in future coder self-reports even when the delivered content is correct.
- Not a REDO trigger.

## Verifications (disproved hypotheses)

- Hypothesized DF-60 was silently re-applied under cover of this wave → DISPROVED:
  `agents/conductor.md` untouched, WORKFLOW-VEHICLE-PROBE PRESENT branch byte-identical to
  base, both via direct diff and mutation-tested for falsifiability.
- Hypothesized `commands/spawn.md`'s new backend-resolution step asserts a settled `auto`
  outcome → DISPROVED: text is explicitly hedged ("UNTESTED," "predicted," "MUST be measured"),
  confirmed by reading every diff hunk and mutation-testing the detector.
- Hypothesized the wave introduced a file outside its declared scope → DISPROVED: `git diff
  --name-only` returned exactly the 3 expected files when the check ran (see addendum for a
  later, unrelated, concurrent-lane change to a 4th file).
- Hypothesized `hooks/tests/run.sh`'s exit-3 was caused by this wave's edits → DISPROVED: the
  failing test file and its library dependency are byte-identical between base c17ad80 and
  HEAD; last real change predates this wave by 3 commits.

## Open questions

- Root should be told the tree is at 9.4Gi/98% disk (`df-guard.sh --min=12` currently fails).
  Neither gate I ran needed cargo, but any lane in this run that does will hit `df-guard`
  first — worth clearing space before the next cargo-invoking wave.
- `test_config_precedence.sh`'s `config-files-full-chain-in-order` and
  `artifacts-namespace-tiers-1-2` assertions are currently failing at HEAD on a `/private/var`
  vs `/var` TMPDIR-symlink mismatch, pre-existing and unrelated to this wave, and appears
  unfiled in `dogfood.md` or any GH issue I could find by grep. Recommend root file this
  separately — out of my scope to file since it is unrelated to the L7 lane I was dispatched to
  verify.
- Dispatch text said HEAD carried "one already-landed... hotfix to workflows/wave.js"; actual
  committed history since c17ad80 carries two commits (`2fea02d` root-output-budget,
  `1441b5d` the named wave.js hotfix). Confirmed neither touches any of L7's three files;
  flagging only for dispatch-accuracy, not as a finding against this lane.
- The `L7-S3`/`W7-S3` duplicate-dispatch-for-the-same-deliverable (see L7-S3 section above) is
  a mesh-planning gap worth a conductor-side fix (same-wave-different-run-id disjointness check
  keyed on target file + deliverable, not just raw path), already self-flagged as an INSIGHTS
  entry by the W7-S3 coder. Not an L7 defect.
- **URGENT, flagged for root, explicitly out of my mandate to investigate:** near the end of
  this audit session, `git status --porcelain` began showing `workflows/wave.js` as modified in
  the working tree — it was NOT present in any `git status`/`git diff --name-only` snapshot I
  took earlier in this same session. `git diff --stat -- workflows/wave.js` at that point
  showed `1 file changed, 1 insertion(+), 167 deletions(-)` — the file's content collapsed from
  168 lines (the full workflow, `meta`/args-contract/phase logic) to what appears to be a
  single line. This is almost certainly concurrent activity from another lane sharing this
  in-place working tree (e.g. a `W7` lane; `coder-W7-S1.md`/`coder-W7-S2.md` reports also
  appeared in `.shepherd/runs/v645/reports/` during this same window, confirming other lanes
  were actively landing work concurrently) rather than anything caused by L7 or by me — I
  touched only the 3 backed-up-and-restored files documented above, verified byte-identical
  before and after via MD5. I did **not** investigate further per the dispatch's explicit
  instruction to ignore `workflows/wave.js`, and made no attempt to diagnose, fix, or even
  fully read the new content, staying strictly read-only and in scope. Given this file is the
  compiled Dynamic Workflow currently driving wave execution in this very run, root should
  check on it directly rather than treat this as resolved by my non-investigation.
  **Update, same session, before final return:** `workflows/wave.js` no longer appears in `git status --porcelain` at all — it has since dropped out of the working-tree diff entirely (neither modified nor different from whatever landed at the new HEAD `df47686`, an unrelated `feat(models)` commit — confirmed via `git diff --name-only c17ad80 df47686 -- commands/spawn.md skills/harness/SKILL.md skills/shepherd/SKILL.md` returning empty, i.e. still no intersection with L7 scope). Reads as a transient in-flight write from a concurrent lane that completed/committed normally, not a lasting corruption. Recorded for the audit trail; still not something I investigated further, per mandate.

## VERDICT

| Step | File | Verdict |
|---|---|---|
| L7-S1 | commands/spawn.md | **PASS** |
| L7-S2 | skills/harness/SKILL.md | **PASS** |
| L7-S3 | skills/shepherd/SKILL.md | **PASS** |

Lane-specific checks 1-4: all **PASS**. `bin/shepherd lint`: **PASS** (exit 0). `hooks/tests/run.sh`:
**exit 3**, 3/84 assertions failing, root-cause-traced and confirmed pre-existing/unrelated to
this wave (byte-identical test+library files between base and HEAD) — not attributed to L7, not
a REDO trigger for any of the three steps.

**Overall: PASS, no REDO required.** One LOW, non-blocking report-accuracy finding (F1). Three
items for root's attention that are explicitly out of L7's scope (disk headroom,
config-precedence pre-existing failure, and the workflows/wave.js concurrent-activity
observation above — the last one time-sensitive).

- Agent ID + timestamp: shepherd-conductor-v645-l7-substrate @ 2026-08-13T22:09:08Z (initial);
  addendum observed and appended before final return, same session.
