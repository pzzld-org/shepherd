---
title: W9 Central Verification — 5 fixes closing gaps prior waves missed/deferred
date: 2026-08-13
auditor: central-verify (subagent, this dispatch)
sprint: v645
concern: central-verify (five-step wave: W9-F1..F5)
mode: central-verify (read-only build/execute — the wave's only agent permitted to build)
methodology: superpowers:systematic-debugging (falsify-don't-confirm; every claim
  grounded in a command run this session, its verbatim exit code, and — for
  every load-bearing line touched or exercised — a mutate/confirm-RED/restore/
  confirm-byte-identical cycle)
---

## Repo / environment facts (verified first)

- `pwd` = `/Users/jo3/src/fl03/shepherd` (repo root — confirmed via `git rev-parse
  --show-toplevel` matching cwd) for every gate command below.
- `git rev-parse --abbrev-ref HEAD` = `v6.4.5`; `git rev-parse HEAD` =
  `6f540a11357c8bb90da2ae24f4f2af07ae08b2f2`. No `WORKTREE-DRIFT`.
- **Shared, non-isolated checkout, confirmed live.** Mid-audit, `git status`
  surfaced unrelated modified/untracked files under `packages/compiler/`
  (README.md, package.json, test.mjs modified; `bin/`, `src/`, `test/` new) that
  were **absent** from my very first `git status`/`git diff --stat` at the start
  of this dispatch. This is a concurrent sibling process writing to the same
  working tree in real time — not part of any W9-F1..F5 file scope. Verified
  disjoint via `git stash push -u -- <the 6 W9 paths>`, which left
  `packages/compiler/*` completely undisturbed in the stash-popped working tree
  (byte-for-byte, `git status` before/after stash identical for those paths).
  Flagging so the conductor does not misread `packages/compiler` as a W9
  violation, or (conversely) fold my checks-run-at-different-timestamps into a
  false "scope creep" reading of W9 itself.

## Assertion 1 — `git diff --stat` touches only the five step scopes

```
$ git diff --stat -- agents/conductor.md commands/spawn.md \
    services/cli/shepherd_cli/templates/boot-prompt.md.j2 workflows/wave.js
 agents/conductor.md                                |  2 +-
 commands/spawn.md                                  | 51 ++++++++++++++----
 .../cli/shepherd_cli/templates/boot-prompt.md.j2   | 15 +++++-
 workflows/wave.js                                  | 62 +++++++++++++++++-----
 4 files changed, 104 insertions(+), 26 deletions(-)
```
Plus the two new untracked files matching W9-F2/F3's own declared scope
(`skills/context/tests/test_cmd_issues.sh`, `services/cli/tests/test_models_run.py`).
**PASS** — restricted to the five declared step scopes; the only other dirty
paths in the tree (`packages/compiler/*`) are demonstrably a concurrent
sibling's work, not W9's (see above).

## Assertion 2 — `CLAUDE_SESSION_ID` not used to resolve a teammate's session

```
$ git diff -- skills/context/scripts/cmd_teammate.sh
(empty — file untouched by this wave)
$ grep -n CLAUDE_SESSION_ID skills/context/scripts/cmd_teammate.sh
103:    # `${CLAUDE_SESSION_ID:-}` (cmd_deliverable.sh's convention) before
108:    # `$CLAUDE_SESSION_ID` at this call site is unconditionally the CALLER's
```
Both hits are inside a comment block (`cmd_teammate.sh:91-137`, the W8R-R1
correction note) **explaining why that fallback must never be reintroduced** —
there is no live code path using `$CLAUDE_SESSION_ID` to resolve a subject
teammate's session. `register` still hard-requires `--session` (line 138-144)
and errors `TEAMMATE-SESSION-UNRESOLVED` (exit 1) otherwise. **PASS** — F1 did
not reintroduce the fallback.

## Assertion 3 — `bin/shepherd run wave pending v645` still exits 0

```
$ ./bin/shepherd run wave pending v645 ; echo "exit=$?"
exit=0
$ ./bin/shepherd run wave pending v645 --json
{"pending": [], "missing_lanes": [], "ok": true}
```
**PASS.** `missing_lanes: []` also directly exercises the DF-63 fix
(`parse_declared_lane_ids`, W9-F3's own subject) against the live run ledger —
consistent with `test_live_v645_plan_still_yields_its_five_lanes` (see F3
below).

## Assertion 4 — `agents/conductor.md` line 7 (`tools:` frontmatter) unchanged, `Workflow` present

```
$ git diff -U0 -- agents/conductor.md
@@ -113 +113 @@ At every walk-tick:
-- **FLOCK-OUTPUT REVIEW** ... stage each coder's reported `Files touched` ...
+- **FLOCK-OUTPUT REVIEW** ... stage each step's `files_touched` paths ...
```
Only line 113 changed — confirmed via `-U0` (zero-context diff shows exactly
one hunk, one line). Line 7 read directly:
```
tools: Agent, Bash, Glob, Grep, Read, Skill, ToolSearch, Workflow, ScheduleWakeup, SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate, WebFetch, WebSearch
```
`Workflow` present, line byte-identical to pre-wave. **PASS.**

---

## Per-step verdicts

### W9-F1 — `commands/spawn.md` + `boot-prompt.md.j2` (spawn contract / self-register split)

**VERDICT: PASS on declared scope, with ONE HIGH-severity blocking finding
requiring a follow-up hotfix before this wave/sprint is mergeable.**

Verified by execution, not self-report:

1. **Register WITH `--session` succeeds:**
   ```
   $ ./skills/context/scripts/shctx teammate register auditor-test-w9f1 \
       --team=w9-central-verify --type=conductor --session=w9-central-verify-fake-session-<ts>
   exit_code=0
   D582B34A-1E68-4616-A85F-2314CD356FB2
   ```
2. **Bare register (no `--session`) FAILS LOUDLY:**
   ```
   $ ./skills/context/scripts/shctx teammate register auditor-test-w9f1-bare \
       --team=w9-central-verify --type=conductor
   exit_code=1
   ERR: TEAMMATE-SESSION-UNRESOLVED — refusing to register teammate 'auditor-test-w9f1-bare' with no session id.
     Pass --session=<the teammate's own session uuid>. Root cannot infer it: the
     native Agent-spawn primitive returns name@team-id, never a session uuid (DF-12).
     See DF-71 in .shepherd/runs/v645/dogfood.md for the full defect + follow-up.
   ```
   (Both test rows pruned/retired after verification — registry left clean.)
3. **Self-register line renders in the STABLE block, not per-lane** — rendered
   (not read) via `./bin/shepherd render boot-prompt.md.j2 --vars-json ...`
   (full 22-key vars object including `teammate_name`, exit 0):
   ```
   6:      shctx teammate register <name> --team=team-1 --type=conductor --session="$CLAUDE_SESSION_ID"
   ...
   3:BOOT INSTRUCTION
   23:FAN-OUT VEHICLE (#263)
   53:HARD PROHIBITIONS ...
   66:LEDGER CUSTODY (#261)
   79:INHERITED CONTEXT        <- per-lane region starts here
   96:INVOCATION-CONTEXT:      <- lane_index/wave_index/parallel_index live here
   ```
   Line 6 (self-register) sits inside `BOOT INSTRUCTION`, well before
   `INHERITED CONTEXT`/`INVOCATION-CONTEXT`. **Then proved the stable-prefix
   invariant holds across two different lanes** by rendering with
   `teammate_name=...-l1`/`lane_index=1_of_5` vs `...-l2`/`lane_index=2_of_5`
   and diffing byte-for-byte:
   ```
   prohibitions_at = 3328
   shared_prefix_len = 4937   (>= prohibitions_at -> PASS)
   divergence starts at: 'e name:        shepherd-conductor-v645-l1' (INHERITED CONTEXT / Teammate name:)
   ```
   The design choice — the instruction text uses the **literal placeholder**
   `<name>` (never `{{ teammate_name }}`) inside the stable block, deferring
   substitution to the teammate's own read of `INHERITED CONTEXT` further down —
   is what makes this work; embedding the real per-lane `teammate_name` value
   directly in the boot-instruction line would have broken the #243 shared-prefix
   contract. Confirmed sound.

**BLOCKING FINDING (HIGH, falsified not asserted).** Adding `teammate_name` as
a new StrictUndefined-required template var, with no accompanying fixture
update, breaks **two previously-green gate tests at HEAD** that render this
exact template with a vars object that predates the new key:

- Hypothesis: `services/cli/tests/test_render.py::test_boot_prompt_stable_prefix_ordering`
  and `crates/render/src/env.rs::tests::end_to_end_matches_python_corpus` both
  hard-code a vars object without `teammate_name` and will now fail exit-4 /
  panic under StrictUndefined.
- Falsification:
  ```
  $ services/cli/.venv/bin/python -m pytest tests/test_render.py -k boot_prompt -v
  FAILED tests/test_render.py::test_boot_prompt_stable_prefix_ordering
  AssertionError: ERROR: undefined template variable — boot-prompt.md.j2: 'teammate_name' is undefined
  assert 4 == 0

  $ CARGO_TARGET_DIR=/tmp/w9-central-verify-target cargo test -p shepherd-render \
      --features json env::tests::end_to_end_matches_python_corpus -- --exact
  thread '...' panicked at crates/render/src/env.rs:220:37:
  boot-prompt.md.j2: render: undefined value (in <string>:102)
  test result: FAILED. 0 passed; 1 failed
  ```
  Full `cargo test -p shepherd-render --features json` (isolated
  `CARGO_TARGET_DIR`, disk-guard run first — `df-guard: 94Gi available at .
  (min 12Gi) — OK`): **6 passed, 1 failed** — only `end_to_end_matches_python_corpus`
  is red; `matches_python_settings` and all filter/manifest tests unaffected.
- **Confirmed pre-wave-innocent / this-wave-caused**, not a pre-existing gap:
  stashed the 6 W9 files (`git stash push -u -- agents/conductor.md
  commands/spawn.md services/cli/shepherd_cli/templates/boot-prompt.md.j2
  workflows/wave.js services/cli/tests/test_models_run.py
  skills/context/tests/test_cmd_issues.sh`), re-ran the render-suite check —
  N/A directly (the var didn't exist pre-wave, so the test passed at baseline
  by construction) — then popped the stash back; `sha256sum` and `git status`
  before/after match exactly what this report opened with.
- Confidence: HIGH (both failures reproduced directly, verbatim output
  captured, root cause is the exact mechanism the W9-F1 coder itself predicted
  in its own assumptions — self-report and tree agree here).
- **Coder's own scope is correct and was NOT the place to fix this** —
  `crates/render/src/env.rs` and `services/cli/tests/test_render.py` are both
  outside W9-F1's `[FILE-SCOPE]`; expanding into them would itself have been a
  scope violation. This is a genuine cross-file consequence, not a defect in
  the diff under review.
- **Required before WAVE-COMPLETE / merge:** a hotfix (cardinality H=2 — both
  files are a single coherent fix) that (a) adds `"teammate_name": "..."` to
  `test_boot_prompt_stable_prefix_ordering`'s `base_vars` in
  `services/cli/tests/test_render.py`, and (b) adds the same key to the
  `boot-prompt.md.j2` case's vars JSON in `crates/render/src/env.rs` AND
  recomputes its frozen SHA-256 (currently
  `54d2fd3cc144c6c041a03ce88d9ffa468b2747acb70ce889c5dcad623d69064f`) against
  the new byte-identical Python output. Per pipeline.md's hotfix ladder, `H=2`
  is a single batched Dynamic Workflow dispatched by whichever lead owns the
  finding — not a reason to REDO W9-F1's own (correct) diff.
- Also confirmed: the self-contained `@engineer` registration line in
  `commands/spawn.md` (`shctx teammate register {engineer_name} --team=...
  --type=engineer`, no `--session`) carries the IDENTICAL DF-12 defect and is
  explicitly marked `KNOWN GAP, not this step's scope` inline
  (`commands/spawn.md:323`) rather than silently left broken — verified the
  comment exists verbatim. Correctly deferred, not swept under the rug.

### W9-F2 — `skills/context/tests/test_cmd_issues.sh` (new regression suite for `cmd_issues.sh`)

**VERDICT: PASS — falsifiability proven on all three named load-bearing lines.**

```
$ bash -n skills/context/tests/test_cmd_issues.sh ; echo exit=$?
exit=0
$ skills/context/tests/test_cmd_issues.sh ; echo exit=$?
test_cmd_issues: all assertions passed
exit=0
```

Three independent mutate → confirm RED (verbatim) → restore → confirm
byte-identical cycles, each against `skills/context/scripts/cmd_issues.sh`
(sha256 `94019f9562e302bd3ec9436b4c97453626859db0bb16e4b88169f916f1dec9d5`
before and after every cycle, `diff` empty every time):

1. **`_DEFAULT_NON_ISSUE_LABELS` (line 80)** — reverted to the old buggy
   default (`deferred/wontfix/invalid/duplicate/question`). RED:
   `FAIL: default.tracking-future: expected 'labeled-non-issue' got
   'unclassified'`.
2. **`_nil_src` fallback expression (line 215)** — forced it to always use the
   hardcoded default, ignoring any `non_issue_cfg` override. RED:
   `FAIL: single-line.override-applies: expected 'labeled-non-issue' got
   'unclassified'`.
3. **The multi-line closing-bracket guard in `_cfg_ledger_array_raw`
   (lines 115-118)** — made the opening `key = [` line print+exit
   unconditionally instead of only when it also closes on that line,
   reintroducing the exact historical truncation bug the suite's own
   docstring describes. RED: `FAIL: multi-line.override-applies: expected
   'labeled-non-issue' got 'unclassified'` — precisely the "documented
   override no-ops silently" regression this suite exists to pin.

All three restores confirmed via `sha256sum` match + `diff` empty +
`git status --porcelain` empty for the file + suite green again.

### W9-F3 — `services/cli/tests/test_models_run.py` (new unit suite for `parse_declared_lane_ids`)

**VERDICT: PASS — falsifiability proven; matches the file's own documented
PROVE-IT-CAN-FAIL evidence exactly.**

```
$ services/cli/.venv/bin/python -m pytest tests/test_models_run.py -v
13 passed in 1.01s
```

Mutation: disabled the section-boundary `break` in
`shepherd_cli/models_run.py:562` (`if _MARKDOWN_HEADING_RE.match(stripped):
break`), reintroducing the pre-W8R-R5 unbounded scan. RED, exactly as the
test file's docstring predicted verbatim:
```
FAILED test_empty_lane_projection_section_never_adopts_a_later_lane_id_tables
AssertionError: ... assert ['l9-decoy'] == []
```
Only that one test failed; the other 12 (including the parametrized
separator-row variants, backtick/case normalization, no-separator-row, and
the live-plan regression guard) stayed green under the same mutation —
precisely targeted. Restored: sha256
`fe28b016eb2951b7a1c024e4c59f611c6ec9ada011af3ac3c835b91257eb829c` matches
before/after, `diff` empty, `git status --porcelain` empty, full 13/13 green
again.

`test_live_v645_plan_still_yields_its_five_lanes` independently corroborated
against the live run: `./bin/shepherd run wave pending v645 --json` →
`missing_lanes: []` on the same 5-lane plan.

### W9-F4 — `agents/conductor.md` (FLOCK-OUTPUT REVIEW clause — `files_touched` routing citation)

**VERDICT: PASS.**

`git diff -U0` shows exactly one changed line (113); nothing else in the file
moved. Both cited doctrinal sources checked verbatim, not taken on faith:

- `skills/harness/SKILL.md` (Workflow tool section): "...fan out subagents in
  the background and return one consolidated result. Intermediate results
  live in script variables, not conversation context." — present verbatim.
- `skills/shepherd/references/flock.md` §@coder, "`files_touched` routing"
  paragraph: "The wave's own return value aggregates every step's
  `files_touched` and carries it back to whichever lead invoked the workflow —
  root, a teammate-conductor, or a self-contained engineer." — present
  verbatim (line 90).

Line 7 `tools:` frontmatter confirmed unchanged, `Workflow` present (Assertion
4 above). The coder's choice to cite flock.md's own in-context-`Agent()`-
fallback caveat rather than duplicate it inline matches this repo's stated
policy that `agents/conductor.md` never duplicates an agent body — a
reasonable SUBTRACT-consistent call, not a gap.

### W9-F5 — `workflows/wave.js` (per-step `specIn`: plan vs inline brief-shape fix)

**VERDICT: PASS.**

```
$ node --check workflows/wave.js ; echo exit=$?
exit=0
```

Per the brief's explicit instruction that `node --check` alone cannot catch a
non-literal `meta` (DF-69: syntactically valid, semantically unloadable),
independently verified `meta` is still a pure literal by extracting the exact
`export const meta = { ... }` block (brace-matched, not line-numbered) and
stripping every single-quoted string literal, then checking for `+`, `` ` ``,
`...`, `(`:
```
FORBIDDEN TOKEN COUNTS (post-strip): {'+': 0, '`': 0, '...': 0, '(': 0}
PASS: meta block is a pure literal
```
Confirmed via `git diff -U0` that this diff never touches the `meta` block at
all (the changed hunk starts at line 16, after `meta` closes at line 9) — the
DF-69 property was already true pre-wave and remains true.

Functionally exercised the new `specIn`/`specBlock`/`scopeFallback` branch
logic in isolation (extracted the exact snippet via string-slice, evaluated
with `new Function` against four input combinations, avoiding the unrelated
pre-existing top-level-`return`-in-an-ESM-context mismatch between Node's
`import()` semantics and the real Workflow loader's execution model — that
mismatch is pre-existing across the whole file, untouched by this diff, and
irrelevant to what changed):
```
plan set, no specIn on step        -> specIn=plan,   points at §<id> in plan.md
plan set, specIn=inline override   -> specIn=inline, "no plan section backs this step"
no plan set at all                 -> specIn=inline  (fail-safe default)
no plan set, specIn=plan requested -> specIn=inline  (cannot honor "plan" with no plan path — fail-safe wins)
```
All four match the args-contract comment's documented semantics exactly,
including the safety property that a step cannot force `plan` mode when
`args.plan` itself is unset.
```
$ grep -rn "no plan path supplied" . --include="*.js" --include="*.md" --include="*.sh" --include="*.py"
(no matches, exit 1)
```
Confirms the removed literal string has no other referrer, as claimed.

---

## Full regression sweep (beyond the brief's explicit command list — run because
central-verify is the only build-permitted agent this wave, and "gates broken
at HEAD" must be caught here or nowhere)

```
$ services/cli/.venv/bin/python -m pytest tests/ -q
26 failed, 1809 passed in 451.43s
```

Triaged all 26:

- **1 caused by this wave** — `test_render.py::test_boot_prompt_stable_prefix_ordering`
  (W9-F1's blocking finding, above).
- **25 pre-existing, unrelated to any of the five steps** — confirmed by
  re-running 4 representative failures (one from each remaining cluster)
  against the pre-wave baseline (`git stash push -u -- <6 W9 paths>` ...
  `git stash pop`, verified clean round-trip):
  - `test_config_schema.py::test_dogfood_claude_shepherd_toml_validates_clean`,
    `test_validate_against_the_real_dogfood_repo_config` — both look for
    `.claude/shepherd.toml`; this checkout's live config lives at
    `.shepherd/shepherd.toml` (confirmed via `resolve_workdir()` and `shepherd
    config validate`'s own stdout). Pre-existing repo-layout/fixture mismatch.
  - `test_doctor.py::test_version_match_emits_no_row` — installed CLI reports
    `6.4.4` while `plugin.json` says `6.4.5` (stale `.venv` install, an
    environment-provisioning fact, not a code defect).
  - 22× `test_issues.py::test_bash_parity_*` — every one traces to the same
    root cause, verified verbatim on one representative case:
    ```
    bash_proc ... 'ERROR: shctx issues requires bash 4+ (have 3.2.57(1)-release).'
    ```
    `test_issues.py` invokes plain `bash` (macOS system bash 3.2.57) with no
    bash4+ discovery, unlike W9-F2's own `_find_bash4()` — a pre-existing gap
    in a DIFFERENT, untouched test file.
  - All 4 representative failures reproduced byte-for-byte identically with
    the 6 W9 files stashed back to their pre-wave HEAD content — conclusively
    pre-existing, not introduced by W9-F1..F5.

`hooks/tests/run.sh`'s already-ledgered DF-74 (3/84 macOS TMPDIR-symlink
failures) was not re-run — out of scope for this dispatch and already tracked
open in `.shepherd/runs/v645/dogfood.md`.

## `bin/shepherd lint`

```
$ pwd
/Users/jo3/src/fl03/shepherd
$ ./bin/shepherd lint
lint: ok
exit=0
```
Ran from the repo root (confirmed above). Located, not just green: confirmed
`resolve_workdir()` independently resolves to
`/Users/jo3/src/fl03/shepherd/.shepherd` (the real, populated artifacts tree —
`ls .shepherd` shows 20+ real subdirectories including `runs/`, `logs/`,
`docs/`), ruling out DF-72's "empty tree, false pass" failure mode for this
run. Note: `bin/shepherd lint` does **not yet** implement the DF-69-mandated
`workflows/*.js` meta-literal-purity check (`grep -n
"workflow|meta|BinaryExpression" services/cli/shepherd_cli/commands/lint.py`
→ no hits) — this is why the brief correctly demanded a manual strip-literal
check for W9-F5 rather than trusting lint's green. Not a new finding: DF-69's
own ledger entry already states this gate is unshipped ("the GATE is the
actual deliverable and is NOT yet done").

## Cleanup performed

- Pruned/retired the two test teammate rows created during F1 verification
  (`auditor-test-w9f1`, `auditor-test-w9f1-bare`).
- Deleted the isolated `CARGO_TARGET_DIR=/tmp/w9-central-verify-target` after
  the last cargo invocation (disk discipline; `df-guard.sh --min=12` run
  before every cargo call, OK each time — 94Gi available).
- No source files left mutated: every mutate/restore cycle (F1's exploratory
  render-only work never mutated a file; F2's 3 cycles; F3's 1 cycle) ended
  with `sha256sum` match + `git status --porcelain` empty for the file in
  question.

## Findings summary

- CRITICAL: 0
- HIGH: 1 — W9-F1's `teammate_name` addition breaks 2 previously-green gate
  tests at HEAD (`test_render.py::test_boot_prompt_stable_prefix_ordering`,
  `crates/render/src/env.rs::tests::end_to_end_matches_python_corpus`);
  blocking, hotfix required (H=2) before WAVE-COMPLETE/merge.
- MEDIUM: 0
- LOW: 0
- Open questions: 0
- Verifications (disproved / could-have-failed-but-didn't): 4 (assertions
  1-4) + 5 per-step falsifiability cycles (F1's render/stable-prefix proof,
  F2 ×3, F3 ×1) + F5's meta-purity strip-check and specIn branch-logic
  isolation test.

## Step verdicts (recap)

| Step | Verdict | Blocking |
|---|---|---|
| W9-F1 | PASS (own scope) | YES — HIGH finding above, hotfix H=2 before merge |
| W9-F2 | PASS | none |
| W9-F3 | PASS | none |
| W9-F4 | PASS | none |
| W9-F5 | PASS | none |

## Recommendation to conductor

Do not treat W9 as fully mergeable until the H=2 hotfix lands (add
`teammate_name` to both frozen fixtures + recompute the Rust SHA-256 digest).
None of the five coders' own diffs need to be redone — every one is correct,
narrowly scoped, and independently verified against live HEAD by execution,
not self-report. The one gap is a cross-file consequence explicitly predicted
by W9-F1's own coder and explicitly outside every declared `[FILE-SCOPE]` this
wave — a hotfix-lane job, not a REDO.
