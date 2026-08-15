# Central verification — v645 W8R (REDO wave)

- Auditor: central-verify (READ-ONLY)
- Repo root: `/Users/jo3/src/fl03/shepherd` (all gates run from here — confirmed via `pwd` before every invocation)
- HEAD throughout: `62ca8f2b006300279fd8c36dee6469bcbf5c06e9` (branch `v6.4.5`) — unchanged start to finish
- Methodology: `superpowers:systematic-debugging` — every PASS below is grounded in a command I ran myself (not a coder self-report), and every shipped test that exists was mutated at a load-bearing line, confirmed red, then restored and confirmed byte-identical (md5 before/after).

## Serial gates — verbatim exit codes

Run one at a time, own exit code captured via `$?` written to a file, never read from a pipe.

| Command | Exit | Notes |
|---|---|---|
| `bin/shepherd lint` | `0` | Ran from `/Users/jo3/src/fl03/shepherd` (repo root, confirmed via `pwd` immediately before). Output: `lint: ok` — no path banner, no inspected-file count. **DF-72's remediation (walk to repo root + print banner + fail on zero-file) has NOT landed in this tree** — grepped `resolve_workdir` project-wide; no hit in `bin/shepherd` or any script this wave's 5 scopes touch. I mitigate the DF-72 risk the only way available (ran from confirmed repo root, not a subdirectory), but a green `lint` here is still not self-proving the way DF-72 demands it should be. Not a blocker for this wave — no R1-R5 scope touches lint or `bin/shepherd`. |
| `bash -n hooks/scripts/teammate_git_guard.sh` | `0` | |
| `bash -n skills/context/scripts/cmd_teammate.sh` | `0` | |
| `bash -n skills/context/scripts/cmd_issues.sh` | `0` | |
| `hooks/tests/test_teammate_git_guard.sh` | `0` | `—— 44/44 passed ——` (up from the pre-W8R 42/42 W8-L1 shipped — P19+P20 added) |
| `skills/context/tests/test_cmd_teammate.sh` | `0` | `PASS: test_cmd_teammate` |
| `skills/context/tests/test_cmd_teammate_conductor_only.sh` | `0` | `PASS: test_cmd_teammate_conductor_only` |
| `bin/shepherd run wave pending v645` | `0` | Empty stdout (no pending, no missing-declared-lane) — see R5 section, this is the DF-63/GATE-EXIT-CODE-MISMATCH gate R5 patches an upstream parser for. |

`cmd_issues.sh` has no gate in the list above that executes it — correct, per its own `BASH_VERSINFO[0] < 4` guard. This sandbox's only bash is system `/bin/bash` 3.2.57; no brewed bash 4+ exists (`ls /opt/homebrew/bin/bash /usr/local/bin/bash` → both absent). Verified R4 by an isolated bash-3.2-compatible harness instead (below) — same method the coder itself used and flagged for me to confirm.

## `git diff --stat` — assertion 1 (does it touch ONLY the five step scopes?)

**No, and that is expected, not a violation.** `HEAD` (`62ca8f2`) predates ALL of Wave 8, so the working tree carries Wave 8's 11 lanes' uncommitted output layered under W8R's 5 redo steps — exactly what every W8R coder's own report independently stated about this shared worktree. Verbatim `git diff --stat HEAD`: 30 files, `1457(+) 234(-)`.

I cross-referenced every one of the 30 files against the 11 `coder-W8-L*.md` reports present in the tree plus the 5 declared W8R scopes:

- **9 files fall inside the 5 W8R scopes** (with expected overlap where an R-step reworks an L-step's own file): `cmd_teammate.sh`(L1+R1), `test_cmd_teammate.sh`(R1-only), `test_cmd_teammate_conductor_only.sh`(R1-only), `teammate_git_guard.sh`(L1+R2), `test_teammate_git_guard.sh`(L1+R2), `agents/coder.md`(R3-only), `flock.md`(R3-only), `cmd_issues.sh`(L11+R4), `models_run.py`(L4+R5).
- **16 files map 1:1 to the 11 W8 lane reports' own declared `Files touched`** (L2→`agents/conductor.md`, L3→`naming-conventions.md`, L4→`run.py`+`test_run.py` (models_run.py already counted above), L5→`conformance/run.sh`+`pipeline.md`, L6→`SKILL.md`, L7→`commands/ctx.md`, L8→`CHANGELOG.md`, L9→`docs/configuration.md`, L10→`agents/auditor.md`, L11→`cmd_issues.sh` already counted) — verified by grepping each report's `Files touched`/acceptance-grep lines against the live diff content, not just the filename.
- **The 8 `coder-W8-L*.md` files under `.shepherd/runs/v645/reports/`** are the legitimate deliverables of those same 11 Wave-8 lanes (report-file convention, since retired by R3 itself — see `workflows/wave.js`'s uncommitted diff, which is the harness change that retires it, dated after these L-reports were written).
- **`workflows/wave.js` and `.shepherd/runs/v645/dogfood.md`** are root/conductor dispatch-harness bookkeeping (the `CODER_RESULT` schema + `DO NOT WRITE A REPORT FILE` instruction the diff introduces, and the DF-73/DF-74 ledger rows) — not attributable to any coder, this wave's or Wave 8's.

Every one of the 30 changed files is accounted for. **Zero unexplained files.** No REDO step wrote outside its own declared `file_scope.exclusive`.

## Assertion 2 — CLAUDE_SESSION_ID grep in `cmd_teammate.sh`

```
$ grep -n "CLAUDE_SESSION_ID" skills/context/scripts/cmd_teammate.sh
103:    # `${CLAUDE_SESSION_ID:-}` (cmd_deliverable.sh's convention) before
108:    # `$CLAUDE_SESSION_ID` at this call site is unconditionally the CALLER's
```

Both hits are inside comment prose explaining *why the fallback is wrong* — not live code. Also grepped `hooks/scripts/teammate_git_guard.sh` for the same string: zero hits, not applicable to that file. **CLAUDE_SESSION_ID is not used to resolve a teammate's session anywhere in the diff.** Confirmed further by mutation (R1 section below): I re-added the exact `${session:-${CLAUDE_SESSION_ID:-}}` fallback pattern and confirmed it is absent from the real tree by restoring to byte-identical md5.

## Assertion 3 — `bin/shepherd run wave pending v645` regression

Exit `0`, empty stdout, both before I touched anything and again in the final clean re-run after all mutate/restore cycles. R5 does not regress the running sprint — see R5 section for the direct proof its fix is a no-op on the *live* plan (all 5 real lanes still parse identically) while fixing the general case.

## Assertion 4 — `agents/auditor.md`, `agents/discovery.md`, `agents/worker.md` unchanged by R3

```
$ git diff --stat HEAD -- agents/auditor.md agents/discovery.md agents/worker.md
 agents/auditor.md | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)
```

`agents/discovery.md` and `agents/worker.md`: **zero diff, confirmed unchanged.** `agents/auditor.md` **does** carry a diff, but it is byte-for-byte the change `coder-W8-L10.md` (Wave 8, not W8R) reports authoring: `tools:` line drops `LSP`, plus one clarifying sentence that `tools:` is an offer not a guarantee. Verified the diff content against L10's report line-for-line — matches exactly, nothing additional. **R3 itself did not touch any of the three files** — confirmed, since R3's own file_scope is `agents/coder.md` + `flock.md` only and neither the auditor.md nor any other agent-file diff attributes to R3 under the file-accounting in the diff-stat section above.

---

## R1 — `skills/context/scripts/cmd_teammate.sh` — **PASS**

**Fix**: bare `register` with no `--session` is now a hard `exit 1` (`TEAMMATE-SESSION-UNRESOLVED`), no fallback of any kind. Read the full diff — the added block is 54 lines, and it is a comment-heavy hard-error gate, nothing else. Verified via:

1. **Grep** (above) — no live-code CLAUDE_SESSION_ID.
2. **Mutation 1 (defect-class reintroduction)**: patched `session="${session:-${CLAUDE_SESSION_ID:-}}"` immediately before the gate — the EXACT fallback the R1 header comment says was itself the bug. Ran both shipped suites: **still PASS, 0 red.** This is a genuine, distinct finding (below), not a false-negative on my part — I traced it: both test files unset `CLAUDE_SESSION_ID` before invoking (`env -u CLAUDE_SESSION_ID $CMD register ...`), so a reintroduced `${CLAUDE_SESSION_ID:-}` fallback resolves to empty *inside the test's own isolation* and the gate still fires. The suite cannot currently distinguish "no fallback exists" from "fallback exists but is starved by the harness's own env -u." Restored, md5-confirmed byte-identical.
3. **Mutation 2 (load-bearing gate itself)**: replaced `if [[ -z "$session" ]]; then` with `if false; then` (neutralizes the entire gate). Result: `test_cmd_teammate.sh` → `FAIL: register with no session exit code: 0 (want 1)`, exit 1. `test_cmd_teammate_conductor_only.sh` → 3 failures, exit 1. **Both suites correctly go red.** Restored: `md5sum` before/after identical (`12f1b7fe5be6bdbcbc52acb9adb22385`), suites green again.

**Findings**:
- **MEDIUM — test-design blind spot, not a current defect.** The negative test's `env -u CLAUDE_SESSION_ID` isolation (added correctly, to stop ambient-session false positives) has the side effect of neutralizing detection of a live-code reintroduction of the exact `${CLAUDE_SESSION_ID:-}` fallback this fix removes — proven by Mutation 1. Recommend a THIRD assertion: with `CLAUDE_SESSION_ID` explicitly SET to a bogus value and `--session` omitted, still assert `exit 1` / `TEAMMATE-SESSION-UNRESOLVED` / no row inserted. Confidence: HIGH (reproduced by direct mutation + execution).
- **HIGH, pre-existing, correctly documented, CLOSE-blocking — `commands/spawn.md:322` still documents `--session` as `[--session={team_session}]` (bracket = optional in this doc's own syntax).** Grepped live: confirmed present, unchanged. Any operator following that doc's literal register command post-this-fix now hits a hard `exit 1` where it previously silently succeeded. R1's own report names this as a known, out-of-scope gap ("a sibling wave owns commands/spawn.md this run") — but **no step in this W8R wave (R1-R5) touches `commands/spawn.md`**, and I found no sibling wave reference to it either. This is a real, live production trap until closed. Confidence: HIGH (grep-verified).

## R2 — `hooks/scripts/teammate_git_guard.sh` — **PASS**

**THE CENTRAL QUESTION, answered by direct execution** (standalone harness constructing real PreToolUse(Bash) JSON payloads + real session-tier marker files, piped into the live script — not the shipped suite, an independent live run):

| Case | Session | Marker | Command | Result | Required |
|---|---|---|---|---|---|
| 1 | root, unmarked, no DB row | none | `git merge origin/dev` | **ALLOWED** (empty stdout) | ALLOWED ✓ |
| 2a | root | `dispatcher: root-shepherd` | `git merge origin/dev` | **ALLOWED** | ALLOWED ✓ (the exact case the old suite couldn't see) |
| 2b | root | `dispatcher: root-shepherd` | `git worktree add ../x` | **ALLOWED** | ALLOWED ✓ |
| 2c | root | `dispatcher: root-shepherd` | `git branch -D somebranch` | **ALLOWED** | ALLOWED ✓ |
| 3a-g | teammate | `dispatcher: teammate-conductor` | merge / rebase / cherry-pick / worktree add / worktree remove / worktree prune / branch -D | **DENIED**, every one, `{"permissionDecision":"deny", ... "TEAMMATE-GIT-WRITE" ...}` | DENIED ✓ |
| 4a | root (marked) | `dispatcher: root-shepherd` | `git push origin lane-branch` | **ALLOWED** | ALLOWED ✓ |
| 4b | teammate | `dispatcher: teammate-conductor` | `git push origin lane-branch` | **ALLOWED** | ALLOWED ✓ |

All four required assertions hold, verbatim stdout captured for every case (available in this session's scratch dir if needed — every deny carries the full `TEAMMATE-GIT-WRITE` message text, every allow is silent empty stdout as designed).

**Falsifiability, per the dispatch's explicit instruction to mutate P19 and P20 specifically:**

1. **P19 mutation**: `[[ "$MARKER_DISPATCHER" == "teammate-conductor" ]] && MARKER_TEAMMATE=1` → `[[ -n "$MARKER_DISPATCHER" ]] && MARKER_TEAMMATE=1` (existence-only — the exact pre-rework adversarial-review defect (b)). Result: `hooks/tests/test_teammate_git_guard.sh` exit `3`, `FAIL P19 ... unexpected deny` **and** a second regression it also catches, `FAIL S16 ... unexpected deny` — `41/44 passed`. Restored: md5 identical (`2ab0cbb3f0512be428a16925fef049cc`), suite back to 44/44.
2. **P20 mutation**: reinserted the pre-rework ordering — `command -v sqlite3 || exit 0` + `[[ -f "$DB" ]] || exit 0` placed ABOVE the marker check (defect (a)). Result: exit `1`, `FAIL P20 ... marker + NO DB FILE (fresh worktree) + git merge: DENY` — `43/44 passed`. Restored: md5 identical, suite back to 44/44.

Both flip red on mutation, both restore clean. This is the load-bearing proof the dispatch demanded.

**Findings**: None blocking. The header/comment sync (push deliberately absent from `FORBIDDEN_PATTERN`, worktree + branch-delete both present) matches the live regex verbatim — checked directly, not by reading the comment.

## R3 — `agents/coder.md` + `skills/shepherd/references/flock.md` — **PASS**

Doc-only lane, no runtime assertion to mutate. Verified:
- Cited pointers `agents/coder.md:120`, `:151`, `flock.md:88` all check out against live content (confirmed by direct `sed -n` read).
- `grep -rln "CODER REPORT" --include="*.md" .` (excluding run artifacts): 6 files still reference the retired convention — `CHANGELOG.md`, `agents/conductor.md`, `agents/shepherd.md`, `agents/coder.md` (now only in explanatory prose describing the retirement, not a live template — confirmed by line content), `skills/shepherd/SKILL.md`, plus two `.shepherd/docs/` historical files. Matches R3's own stated out-of-scope list exactly.
- Cross-checked the specific claim that `agents/conductor.md` is NOT reconciled: `grep -n "Files touched" agents/conductor.md` → line 113 still reads `stage each coder's reported \`Files touched\` paths` (old backtick-quoted phrasing, not the new `files_touched` schema-field name). **Confirmed real, live inconsistency** — not blocking (conductor.md is out of R3's scope and R3 flagged it), but worth a fast-follow before this doctrine is considered fully landed: a reader of `agents/conductor.md` alone would not know the report-file convention is retired.
- No test shipped — expected and acceptable for a pure-doctrine change with no executable surface; the acceptance evidence is the grep verification above, independently reproduced.

## R4 — `skills/context/scripts/cmd_issues.sh` — **PASS**, with a real completeness gap

No test file in R4's scope, and none exists anywhere in the tree for this file (`find skills/context/tests -iname "*issues*"` → zero hits). Could not run `cmd_issues.sh` itself (bash 4+ gate, no brewed bash present). Built an isolated bash-3.2-compatible harness (extracted `_DEFAULT_NON_ISSUE_LABELS`/`_cfg_ledger_array_raw`/`_non_issue_labels_from_toml`/`_has_label`/`_classify_row` verbatim, sourced `_lib.sh` for real, exercised against real + synthetic `shepherd.toml` fixtures resolved through the actual `shctx_config_files()` precedence chain):

- Real project config (`.shepherd/shepherd.toml`) resolves to `wontfix / tracking-future / design-question / rfc` — matches docs default exactly.
- A fixture overriding to `wontfix / tracking-future / design-question / stale`: **override genuinely takes precedence** — an issue labeled `rfc` (not in the fixture list) classifies `unclassified`; one labeled `stale` (in the fixture list, not the hardcoded default) classifies `labeled-non-issue`. Proves the config is read and honored, not merely parsed and discarded.
- No `[ledger]` key present at all → empty result, caller correctly falls back to the hardcoded default (`deferred` → `unclassified`, no longer in the new default list; `wontfix` → `labeled-non-issue`, still in it).
- Multi-line TOML array form parses correctly (the whole reason `_cfg_ledger_array_raw` exists instead of the line-based `cfg_section_get`).
- **Malformed (unterminated) array**: `rc=3`, diagnostic to stderr, and — critically — does NOT silently fall back to the default. This is the fix's core safety property.

**Falsifiability**: mutated the awk `END` block's `exit 3` to `{ print val; exit 0 }` (silently returns the truncated value instead of failing loud). Re-extracted, reran harness: malformed-array test correctly flips to `FAIL: malformed array rc (got: 0)`. Restored: `md5sum` before/after identical (`9965c4201bcc5c6ce08cfdcd1bfe0c89`), `bash -n` clean, harness green again (9/9).

**Finding — MEDIUM-HIGH, completeness gap**: R4 shipped **zero permanent regression test** for this fix — no file in `file_scope.exclusive`, no pre-existing `test_cmd_issues.sh` picked it up. My 9-check harness (above) proves the fix correct today, but it lives only in this audit's scratch directory, not the tree — nothing protects this classification logic from regressing on the next touch. CLAUDE.md is explicit: "Every bug fix ships with a test AND an eval that would have caught the bug... 'I'll add tests later' is banned." Recommend: materialize `skills/context/tests/test_cmd_issues.sh` from this audit's harness before CLOSE, or accept the gap explicitly as a named follow-up issue.

## R5 — `services/cli/shepherd_cli/models_run.py` — **PASS**, with the same completeness gap, worse

Executed directly against the project's real venv (`services/cli/.venv` — has `pydantic`; system `python3` does not):

- **Bug repro** (plan text: empty `## Lane projection` → `{# comment #}` → `## Proof of dispatch` → prose → `## Lane status` table headed `lane_id` with a `bogus-lane` row): `parse_declared_lane_ids()` returns `[]`. Correct — does not adopt the later, wrong table.
- **Live-plan regression check**: read `.shepherd/runs/v645/plan.md` directly and parsed it — returns exactly `['l1-engine', 'l2-registry', 'l3-surface', 'l4-conformance', 'l5-harness']`, matching R5's own claimed trace. Confirms the fix is a no-op on the actual running sprint's plan (the real table is immediately followed by a blank line the pre-existing `saw_header` check already stops on) while fixing the general case.
- `bin/shepherd run wave pending v645` exits `0` both before and after — confirms no regression to the live gate (assertion 3, above).

**Falsifiability**: mutated `if _MARKDOWN_HEADING_RE.match(stripped): break` → `if False and _MARKDOWN_HEADING_RE.match(stripped): break` (neutralizes the fix). Reran the bug-repro: **returns `['bogus-lane']`** — reproduces the exact pre-fix defect verbatim. Restored: `md5sum` before/after identical (`b58d26e20f323d8377cd6ca6bf46c113`), `ast.parse` clean, bug-repro back to `[]`.

**Finding — HIGH, completeness gap, worse than R4's**: R5 shipped zero test, same as R4, but R5's own report explicitly acknowledges the gap and defers it to "whichever lane owns" `tests/test_run.py` — **no such lane exists in this wave** (R1-R5's scopes are fixed and none include `tests/test_run.py`), and it doesn't exist upstream either (`grep -n "test_parse_declared_lane_ids\|stops_at_next_heading\|MARKDOWN_HEADING" services/cli/tests/test_run.py` → zero hits, checked against the file's current, uncommitted-but-present W8-L4 state too). This is a dropped ball, not a scoping choice with a real owner: a fix to a gate in the DF-63 lineage (`GATE-EXIT-CODE-MISMATCH`, already flagged CRITICAL once this sprint) is landing with no regression coverage and no one holding the pen for it. Recommend materializing the exact test R5's own report proposes (`test_parse_declared_lane_ids_stops_at_next_heading`, using the existing `_write_lane_projection_plan` helper + DF-63 docstring convention already established in `tests/test_run.py`) before CLOSE.

---

## Summary verdict

| Step | Verdict | Blocking items |
|---|---|---|
| W8R-R1 | **PASS** | None blocking. MEDIUM test-design blind spot (env -u neutralizes exact-fallback-reintroduction detection) + HIGH pre-existing `commands/spawn.md:322` doc gap (real, live, no sibling covers it this wave) — both should be tracked, neither indicates R1's own code is wrong. |
| W8R-R2 | **PASS** | None. All four central-question cases verified by direct execution; both named mutations (P19, P20) proven falsifiable and cleanly restored. |
| W8R-R3 | **PASS** | None blocking. `agents/conductor.md:113` stale phrasing is a real, confirmed, correctly-out-of-scope gap — fast-follow recommended. |
| W8R-R4 | **PASS** | MEDIUM-HIGH: zero regression test shipped or pre-existing for this file; fix independently verified correct via a 9-check ad hoc harness (not in the tree). |
| W8R-R5 | **PASS** | HIGH: zero regression test, explicitly deferred to a "sibling" that does not exist in this wave or upstream; fix independently verified correct + confirmed no-op on the live plan + confirmed `wave pending` still exits 0. |

**No inversion-class defect found in this wave.** All five steps' load-bearing behavior was verified by direct execution (not self-report) and, where a shipped test existed (R1, R2), by mutating the exact lines the dispatch named and confirming red→restore→green. Where no test existed (R3 doc-only — acceptable; R4, R5 — not acceptable per CLAUDE.md), I built and ran my own falsifiable harness in place of the missing one and it holds; the gap is a completeness/process finding for CLOSE, not a REDO of correct code.

**Tree state**: every mutation performed during this audit was restored and md5-confirmed byte-identical before moving to the next check. Final `git diff --stat HEAD` is byte-identical to the pre-audit snapshot — this audit leaves zero net change on disk.

- Agent ID + timestamp: auditor-W8R-central-verify @ 2026-08-13T00:00:00Z (local session clock unavailable; date per environment context)
