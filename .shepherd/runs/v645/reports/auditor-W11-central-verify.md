---
title: Central verification — v645 W11
auditor: central-verification-auditor
sprint: v6.4.5 (v645)
wave: W11
mode: central-verify (build-permitted, read-only otherwise)
methodology: superpowers:systematic-debugging — falsify, don't confirm; every claim
  re-derived against live HEAD/working-tree, never taken from a self-report.
head_at_wave_start: 1a0cf20c759dc72b1001da41c765a5bd689efe35
head_at_audit_time: 1a0cf20c759dc72b1001da41c765a5bd689efe35 (all wave work is
  UNCOMMITTED working-tree state — 19 tracked modified/deleted files, 6 new
  untracked files; branch v6.4.5, matches sprint branch throughout)
---

## Scope reviewed

Six steps dispatched this wave: S1-role-resolution (DF-77), S2-guard-serve,
S3-plan-cli, S4-wiring-truth, C1-pi-collapse, C2-claude-relay. Reviewed every
file in every declared scope, plus every file named in `out_of_scope_writes`
across all six self-reports, plus `content/predicates/*.toml`,
`services/cli/shepherd_cli/predicates.py`, and `hooks/hooks.json` as shared
dependencies. 19 tracked files + 6 new files = 25 total changed files.

## Gate results (verbatim, own line each)

```
$ bash hooks/tests/run.sh
—— 83/86 passed ——
EXIT=3
FAIL  shctx-locator        (test_shctx_locator.sh — pre-existing-this-wave regression, see Q2/Findings)
FAIL  v644-doctrine-wiring (test_v644_wiring.sh — 2 legs: bash cmd_plan.sh amend/lane-drift
                             not wired + live v645 run-state drift, both pre-existing/doctrine
                             conflicts, not introduced by this wave)
FAIL  conductor-write-guard (test_conductor_write_guard.sh — 16/24 — CRITICAL, see Findings #1)

$ cd services/cli && poetry run pytest -q
25 failed, 1886 passed in 568.37s (0:09:28)
EXIT_PYTEST=1
  (all 25 failures independently confirmed PRE-EXISTING at base commit 1a0cf20 —
   3 are `.claude/shepherd.toml` vs `.shepherd/shepherd.toml` path drift +
   plugin/CLI version mismatch in this sandbox [test_config_schema.py x2,
   test_doctor.py x1]; 22 are `shepherd issues` bash-parity tests that require
   bash 4+ and this machine's system bash is 3.2.57 [test_issues.py — see
   `reference_bash32_portability.md`]. Reproduced via `git stash` + re-run:
   identical 3/3 failures with the wave's ENTIRE diff removed, confirmed via
   `git stash pop` round-trip that the tree returned to the pre-stash 25-file
   state. None of the 25 touch any file in any of this wave's 6 declared
   scopes.)

$ node --test 'packages/harness-claude/test/*.test.mjs'
tests 6, pass 6, fail 0
EXIT=0

$ node --test 'packages/harness-codex/test/*.test.mjs'
tests 5, pass 5, fail 0
EXIT=0

$ node --test 'packages/harness-pi/test/*.test.mjs'
tests 9, pass 9, fail 0
EXIT=0

$ bin/shepherd guard test
17/17 examples passed
EXIT=0

$ cargo check --workspace
Finished `dev` profile [optimized + debuginfo] target(s) in 0.66s
EXIT=0
```

Disk guard run before the cargo invocation (`df-guard.sh --min=12`): `23Gi
available at . (min 12Gi) — OK` (pre-cargo re-check: `21Gi available ... OK`).
No lane `CARGO_TARGET_DIR` was created (single shared workspace build, mine
alone, run last, as required) — nothing to reclaim.

---

## THE FIVE QUESTIONS

### Q1 — Does `coder_git_guard.sh` now actually DENY a coder's git commit?

**YES, proven end-to-end through the REAL hook scripts with a REAL dispatch
record**, in an isolated sandbox repo (own `.shepherd/dispatch/`, never
touching this repo's real dispatch state):

```
$ printf '%s' '{"session_id":"sess-audit-1","tool_name":"Agent","tool_use_id":"toolu_audit_coder_1","tool_input":{"subagent_type":"shepherd:coder","model":"claude-sonnet-4","prompt":"Implement the thing. No role header here at all..."}}' | bash hooks/scripts/agent_invocation_tagger.sh
# -> wrote .shepherd/dispatch/v9.9.9-dev.0/toolu_audit_coder_1.json with "agent_role": "coder"
#    (subagent_type-only payload, zero "# @role" header anywhere — proves FIX 1)

$ printf '%s' '{"session_id":"sess-audit-1","tool_name":"Bash","tool_use_id":"toolu_audit_coder_1","tool_input":{"command":"git commit -m \"sneaky\""}}' | bash hooks/scripts/coder_git_guard.sh
{"permissionDecision":"deny","message":"[shepherd] CODER-GIT-WRITE — @coder may not run git ..."}

# negative control 1 — same coder tool_use_id, read-only git:
$ printf '%s' '{... "tool_use_id":"toolu_audit_coder_1", "tool_input":{"command":"git status"}}' | bash hooks/scripts/coder_git_guard.sh
(empty stdout — silent PASS)

# negative control 2 — a NEVER-TAGGED tool_use_id (root's own shape), git commit:
$ printf '%s' '{"session_id":"sess-root","tool_use_id":"toolu_never_tagged_root_1","tool_input":{"command":"git commit -m \"root commit\""}}' | bash hooks/scripts/coder_git_guard.sh
{"additionalContext":"[shepherd] CODER-GIT-WRITE — role UNRESOLVED for a git write command. ... NOT denied: root's own direct git writes resolve to the same \"unknown\" value today..."}
```

Root is NOT denied; a coder's read-only git passes silently; a tagged coder's
write is denied with the CODER-GIT-WRITE halt code. All three self-report
claims for this fix are independently confirmed.

**Gate-can-fail proof (mutation)**: replaced the guard's `emit_deny` call
with `pass_silent` (one line, `hooks/scripts/coder_git_guard.sh`). Re-ran the
same coder-commit payload above → passed silently (no longer denied).
`bash hooks/tests/test_coder_git_guard.sh` also went from 33/33 to 14/33.
Restored from a pre-mutation copy; `md5` before/after identical
(`ec3b6048d2a8d729d091c73952f9708f`); `git diff --stat` returned to the
wave's own unmutated diff (+43/-5); re-ran the suite → 33/33 again.

### Q2 — Did the escalating fallback die? Every `current_role` caller.

Confirmed dead: `current_role()` (`hooks/scripts/_lib.sh:588-630`) now
returns three distinct outcomes — empty `tool_use_id` → `"conductor"`
(line 590, UNCHANGED, a genuinely different case: no tool call in flight at
all); non-empty `tool_use_id` matched to a dispatch record → that record's
`agent_role`; non-empty `tool_use_id` with **no** matching record →
`"unknown"` (line 628, was `"conductor"` pre-DF-77 — this was #187's field
defect). `rg -n 'current_role' hooks/ skills/` — 9 real call sites (excluding
comments/docstrings):

| Caller | Old-fallback dependency | Post-DF-77 posture | Verdict |
|---|---|---|---|
| `dedup_write_guard.sh:31` | gates on `role=="coder"` | `unknown != "coder"` → pass silent (identical to old `conductor != "coder"`) | SAFE |
| `dups_write_guard.sh:37` | same shape | same | SAFE |
| `bash_post.sh:22` | logging only, never branched | unaffected | SAFE |
| `worktree_lifecycle.sh:76` | forensic SQL record | now records `"unknown"` honestly instead of a false `"conductor"` | SAFE, more honest |
| `lock_guard.sh:45` | `case "$role" in discovery)/auditor)/coder)/*)` | `*)` catch-all already treats conductor/engineer/critic/worker/**unknown** identically (line 114-116, pre-existing comment literally lists `unknown`) | SAFE |
| `cwd_changed.sh:36` | calls `current_role("", sprint)` — empty id | unaffected (line 590 unchanged) | SAFE |
| `bash_guard.sh:30` | gates on `role=="auditor"` / `"discovery"`/`"critic"` | `unknown` matches none, same as old `conductor` matched none here | SAFE |
| `coder_git_guard.sh:88` | THE step's own scope | `unknown` → loud `additionalContext` warn (never deny, never silent) — verified live under Q1 | SAFE, by design |
| `conductor_write_guard.sh:92-93` | `ROLE="$(current_role ... \|\| echo conductor)"` then `[[ "$ROLE" == "conductor" ]] \|\| exit 0` | **BROKEN.** The `\|\| echo conductor` only fires on a non-zero exit; `current_role()` always exits 0. A root-issued Edit/Write/Bash carrying a real `tool_use_id` (the normal case) now resolves `"unknown"`, not `"conductor"` — Leg 1 (line 93) no longer matches, and the entire guard becomes a silent no-op for the conductor's own direct writes. | **CRITICAL — live, unresolved at HEAD** |

**This is a real, unabsorbed consumer defect** — exactly the audit's warning
("A shared helper's behavior change that one consumer didn't absorb is a
live defect"). S1's own `out_of_scope_writes` flagged this by name with the
exact one-line fix (`[[ "$ROLE" == "conductor" || "$ROLE" == "unknown" ]] ||
exit 0`) and marked it "CRITICAL, should land in this same wave." **It did
not land.** `hooks/scripts/conductor_write_guard.sh` shows zero diff against
HEAD (`git diff HEAD --stat` empty) — no coder in this 6-step wave picked it
up, despite two separate steps (S1 and S4, independently) surfacing the same
class of problem. Live confirmation: `hooks/tests/test_conductor_write_guard.sh`
regressed 24/24 → 16/24, and every failing case is exactly "conductor's own
Edit/Write/rm -rf/close-lane now silently passes instead of being denied."
**Net effect at HEAD: the conductor's "read + dispatch only, never author
artifacts directly" enforcement is currently disabled for the common case
(any tool call carrying a `tool_use_id`, which is virtually all of them).**

### Q3 — Is `guard serve` faster, and does it agree with `guard eval`?

**Independently measured** (own script, not the coder's numbers), CLI venv
python, this box, this session:

```
eval avg = 272.41ms/call   (10 calls: 224.62–383.16ms; direct .venv python, no poetry wrapper)
bin/shepherd guard eval (poetry-wrapped, what the two live harness relays actually use):
  758.93ms, 760.36ms, 974.72ms  (3 calls, independent re-measurement)
serve startup (spawn -> ready) = 212.09ms  (one-time)
serve avg per-request, 200 calls after 5-call warmup = 0.0398ms/call (min 0.0301ms, max 0.4988ms)
```

~6,800x faster than direct-venv `eval`, ~19,000–24,000x faster than the
poetry-wrapped path every live relay currently pays.

**Correctness**: all 17 `content/predicates/*.toml` `[[example]]`s sent
through both `eval` and `serve` in the same run — 0 mismatches against the
declared `result`, 0 disagreements between `eval` and `serve`. `serve` exits
0 cleanly on stdin close.

**Gate-can-fail proof (mutation)**: patched `run_serve` (`services/cli/
shepherd_cli/commands/guard.py`) to hardcode `decision: "allow"` on every
response. Re-ran the cross-check → 9 disagreements + 9 mismatches vs
declared result (dedup-gate/dispatch-scope/git-custody/write-boundary — the
whole deny-half of the corpus went silently allow). Re-ran the real
`services/cli/tests/test_guard_serve.py` → 10/21 failed (was 21/21).
Restored from a pre-mutation copy; `md5` identical
(`4d057b28eb924f6c79b83ed05b83cf29`); `git diff --stat` back to the wave's
own +85/-1; re-ran → 21/21 again.

### Q4 — How many predicate interpreters remain in `packages/`?

**Zero.** `packages/harness-pi/src/guard.ts` (137 lines) and `src/predicates.mjs`
(105 lines) are deleted (`ls` confirms `No such file or directory`; `grep -rn
"predicates.mjs\|guard.ts"` across `packages/harness-pi/` returns only
comments/README prose noting the deletion, no live import). The two `subject
`/`action`/`effect` grep hits in `packages/harness-{claude,codex}/src/guard.mjs`
are both **comments explicitly disclaiming** interpreter logic ("this module
is therefore deliberately NOT a predicate interpreter... never encodes a
`subject`/`action`/`effect` rule"). All three harness adapters (claude,
codex, pi) are confirmed pure relays onto the one canonical engine
(`services/cli/shepherd_cli/predicates.py`).

Since pi did **not** keep a second interpreter, Q4's "if pi kept it, prove
the conformance gate bites" branch doesn't apply as written — instead I
proved the thing that actually matters now (a single shared engine with
three relays: does a corruption of that ONE engine get caught everywhere?):

**Gate-can-fail proof (mutation)**: changed `evaluate_predicate()`'s return
in `services/cli/shepherd_cli/predicates.py` (the shared, canonical, no
coder's-scope-this-wave engine core) from `("deny", fired) if fired else
("allow", [])` to unconditional `("allow", [])`. Re-ran:
- `bin/shepherd guard test` → 8/17 (was 17/17), exit 1.
- `node --test packages/harness-claude/test/*.test.mjs` → `guard.test.mjs` FAILED.
- `node --test packages/harness-codex/test/*.test.mjs` → `guard.test.mjs` FAILED.
- `node --test packages/harness-pi/test/*.test.mjs` → `extension-guard.test.mjs` AND `guard-predicates.test.mjs` both FAILED.

All four (the master corpus gate + all three harness relays) went red from
one mutation in the one shared engine — proving there is genuinely one
evaluator, not three that happen to agree today. Restored from a
pre-mutation copy; `md5` identical (`c710fcb868d0651f95ca6ba7ad71e963`);
`bin/shepherd guard test` → 17/17 again.

### Q5 — SUBTRACT, wave-scoped. Honest net.

```
$ git diff 1a0cf20..HEAD --shortstat        # HEAD == 1a0cf20 — the whole wave is UNCOMMITTED
(empty — nothing committed yet; measured against the working tree instead)

$ git diff HEAD --shortstat
 19 files changed, 1103 insertions(+), 454 deletions(-)

$ (untracked files, wc -l each)
hooks/tests/test_agent_invocation_tagger.sh: 168
packages/harness-claude/src/dispatch-record.mjs: 163
packages/harness-pi/src/guard-client.ts: 176
packages/harness-pi/test/extension-guard.test.mjs: 166
services/cli/tests/test_guard_serve.py: 271
services/cli/tests/test_plan_amend.py: 240
= 1184 new lines across 6 new files
```

**Grand total: +2,287 / -454, net +1,833 lines.** This is **not** a
subtraction wave — do not round it into one. Breakdown by kind (own
`git diff HEAD --numstat` verification, file-by-file):

| Kind | Net | What |
|---|---|---|
| Production code | **+525** | DF-77 role-fix (`_lib.sh`/`agent_invocation_tagger.sh`/`coder_git_guard.sh`, +130), `guard serve` (+85), Claude relay (`guard.mjs`+`guard-eval.mjs`+new `dispatch-record.mjs`, +176), pi relay wiring (`extension.ts`+`pi-types.ts`+new `guard-client.ts`, +269), `plan.py` message fix (+8), **minus** the pi interpreter deletion (`guard.ts`+`predicates.mjs`, **-242**) |
| Test code | **+1,230** | More than double the production delta — 8 files, 2 rewritten, 6 new |
| Docs (CHANGELOG + 2 READMEs) | **+77** | |
| Sprint artifact (`dogfood.md`) | **+1** | |

**Separating "new capability" from "collapse of duplication"** (the exact
trap the brief warns a prior auditor conflated): the **only** true
duplication-collapse this wave is C1's removal of pi's second predicate
interpreter (**-242 lines** of independent rule-matching logic, replaced
with a **+176-line** thin relay client — a genuine qualitative win, one
fewer evaluator that could silently drift, even though the pi package's own
production line count only dropped by net 27 once the relay is counted).
**Everything else in this wave's production delta is net-new capability**
(DF-77's role-resolution fix, `guard serve`, the Claude relay's role
resolution) — legitimate, each closes a real correctness gap (DF-77, the
W10 auditor's HIGH finding), but it is additive, not SUBTRACT. The
honest headline: this wave shipped +1,833 lines to close two real defects
and collapse one duplicate interpreter — a reasonable trade given what each
line bought, but a "SUBTRACT win" it is not, and no per-step self-report
claims otherwise except in the narrow, correctly-scoped sense of the pi
collapse.

---

## Findings

### Finding 1 — CRITICAL — `conductor_write_guard.sh` fail-open regression, unresolved at HEAD

**Hypothesis**: DF-77's FIX 2 (stop `current_role()` from escalating an
unresolved id to `"conductor"`) breaks any consumer that relied on that
exact escalation as its detection leg, and `conductor_write_guard.sh` is
exactly such a consumer per its own header comment (`hooks/scripts/
conductor_write_guard.sh:34-40`, literally citing "current_role resolves
`conductor` for any tool call NOT tagged... mirrors the documented
current_role fallback contract verbatim").

**Falsification**: `git diff HEAD --stat -- hooks/scripts/
conductor_write_guard.sh` → empty (untouched this wave).
`hooks/tests/test_conductor_write_guard.sh` → 16/24 (was 24/24 at HEAD
before this wave's uncommitted changes were applied — confirmed via the
suite's own output, e.g. `sprint-branch + Edit: DENY CONDUCTOR-WRITE-DENIED
— out=` meaning no deny was emitted). Traced the code: line 92
`ROLE="$(current_role "$TOOL_USE_ID" "$SPRINT" 2>/dev/null || echo
conductor)"` — the `|| echo conductor` fallback only fires on a non-zero
*exit code*; `current_role()` always `return 0`, so this fallback is
dead code for the case that matters. Line 93 `[[ "$ROLE" == "conductor" ]]
|| exit 0` now silently no-ops for root's own direct Edit/Write/Bash calls
(the overwhelmingly common shape — any tool call with a real
`tool_use_id`), because `ROLE` resolves `"unknown"`, not `"conductor"`.

**Confidence**: HIGH — reproduced live via the real test suite and by
reading the exact two lines responsible; the fix (one line, already spelled
out by S1's own `out_of_scope_writes`) is: `hooks/scripts/
conductor_write_guard.sh:93` → `[[ "$ROLE" == "conductor" || "$ROLE" ==
"unknown" ]] || exit 0`.

**Impact**: the conductor's "read + dispatch only, never author artifacts
directly" enforcement (#180) is currently disabled for its main detection
leg. Two independent steps in this wave (S1, S4) surfaced consumer-side
fallout from the DF-77 change; neither had `conductor_write_guard.sh` in
its exclusive file_scope, and nobody in the 6-step wave picked up the
one-line companion fix despite both flagging it by name with the exact
diff. **This should have been a 7th step, or S1/C2 should have had this
file added to file_scope** — a wave whose whole subject is "gates that
could not fail" shipped leaving exactly one of its own gates newly unable
to fail.

### Finding 2 — HIGH — `session_open.sh` registry-line silence-contract regression, unresolved at HEAD (pre-existing this wave, correctly identified, not fixed)

**Hypothesis**: DF-01's "Registry self-heal" (commit `4ee106a`, ancestor of
this wave's base) added a fourth `SessionStart` context surface
(`registry_line`) without the `announce_*` config gate its three siblings
all have.

**Falsification**: `hooks/scripts/session_open.sh:68-76` — `registry_line`
is computed unconditionally whenever `[[ ! -f "$db" ]]`, with no
`cfg_get announce_registry`-style check, unlike `adapt_line` (line 78,
gated on `announce_adaptation`), `shctx_line` (line 177, gated on
`announce_shctx_path`), and `doctrine_line` (line 191, gated on
`announce_core_doctrine`) in the same file. `hooks/tests/
test_shctx_locator.sh` case 4 ("all off yields true silence") fails:
`expected silence with all off, got: {"additionalContext":"[shepherd]
Session orientation:\nregistry DB absent — run 'shctx init' to scaffold
it.\n"}`. `git diff HEAD --stat -- hooks/scripts/session_open.sh` → empty
(untouched this wave; the bug predates it).

**Confidence**: HIGH — S4 correctly diagnosed this as a code regression
(not test drift), correctly left the test unchanged (it still fails, as it
should), and correctly halted rather than edit a file outside its
file_scope. This wave leaves it unfixed at HEAD, same as Finding 1: flagged
with the exact remediation (add a `[context].announce_registry` gate) but
not landed by any of the 6 steps.

### Finding 3 — MEDIUM — S3's own claimed fix (`plan.py` amend message accuracy) has zero assertion coverage

**Hypothesis**: `services/cli/tests/test_plan_amend.py`'s anti-forgery test
verifies the underlying invariant (the `critic` block never moves) via the
proof JSON and a fresh `verify` re-run, but never asserts on the printed
`amend` success message — the specific line S3's diff actually changed.

**Falsification**: reverted `_cmd_amend`'s message back to the old,
provably-false unconditional claim (`"'shctx plan verify' now passes; the
proof records the amendment."`) and re-ran `poetry run pytest -q tests/
test_plan_amend.py` → **5/5 still pass**. Restored from a pre-mutation
copy; `md5` identical (`f21e92e2e5a0b564af88c9f0e1b4d02c`); `git diff
--stat` back to +9/-1; re-ran → 5/5.

**Confidence**: HIGH (structurally verified by mutation). **Severity note**:
this is not a functional bug — the underlying anti-laundering property IS
genuinely enforced and IS genuinely tested (Finding is about test coverage
completeness, not correctness) — but it is precisely the wave's own theme
("gates that could not fail") applied to a smaller stakes. A future revert
of the message-accuracy fix would ship silently.

### Finding 4 — MEDIUM/HIGH — `guard serve` built to fix a "real regression," wired into only 1 of 2 live relays that exhibit it

**Hypothesis**: `services/cli/shepherd_cli/commands/guard.py`'s own module
docstring names the motivating problem explicitly: "`packages/harness-codex`'s
guard now shells out to it [`guard eval`] on every single Write/Edit/Bash (a
real regression, commit `1a0cf20`)." C1 (pi-collapse) wired `guard serve` in
via a new `guard-client.ts` and eliminated the pi-side latency entirely.
Neither `packages/harness-claude/hooks/guard-eval.mjs` (touched THIS wave by
C2) nor `packages/harness-codex/hooks/scripts/shepherd_guard.mjs` (untouched)
were switched — both still `spawnSync(LAUNCHER, ["guard", "eval"], ...)`
per-call, where `LAUNCHER` is the poetry-wrapped `bin/shepherd`.

**Falsification**: `grep -n "guard eval\|guard serve\|spawnSync" packages/
harness-{claude,codex}/**` → both call sites are unchanged `spawnSync(...,
["guard", "eval"], ...)`; `git diff HEAD -- packages/harness-claude/hooks/
guard-eval.mjs` shows the `spawnSync(LAUNCHER, ["guard", "eval"], ...)` line
itself is untouched (C2's diff only changes the `input:` payload it's
called with, not which subcommand). Independently measured the live cost
this imposes on every guarded Write/Edit/Bash/Agent/Workflow call through
either harness: `bin/shepherd guard eval` (the exact command both relays
spawn) → 758.93ms / 760.36ms / 974.72ms across 3 fresh calls.

**Confidence**: HIGH. **Severity**: this predates the wave for
harness-codex (inherited from base commit `1a0cf20`, not a regression C2
introduced), but C2 edited the exact function in `guard-eval.mjs` that
issues this call, in the SAME wave that shipped the fix for it, and did not
take the opportunity to switch. harness-claude is this very agent's own
harness — every guarded tool call this session (and every Claude Code
session running this plugin) pays ~750-975ms of PreToolUse latency that a
sibling step in the identical wave proved is fixable to ~0.04ms. Recommend
a follow-up step: apply C1's `guard-client.ts` pattern (spawn `guard serve`
once, hold a request queue, close on session end) to both
`packages/harness-claude` and `packages/harness-codex`.

### Finding 5 — LOW — S4's self-reported LOC delta for `test_v630_wiring.sh` is off by 2 lines

**Hypothesis/Falsification**: S4 claimed `+21/-2`; `git diff HEAD --numstat
-- hooks/tests/test_v630_wiring.sh` → `19  2` (i.e. +19/-2). **Confidence**:
HIGH (direct numstat). Immaterial to correctness — flagged only because the
audit's mandate is "verify against the diff, not self-reports," and this is
the one number across all six steps that didn't reconcile exactly (every
other step's aggregate LOC claim, including C1's and C2's overall
`+635/-321` and `+572/-68`, reconciled to the exact line via independent
`git diff --numstat` summation).

## Verifications (disproved / confirmed)

- Disproved nothing in S2, S4, or C1's core claims — every hand-verification,
  measurement, and mutation-test independently reproduced their reported
  results exactly (S1's LOC deltas: exact match; S2's serve/eval agreement
  and speedup: exact/consistent match; S4's test-drift-vs-regression
  diagnoses: both independently confirmed correct via direct file reads and
  `git log -S`; C1's role_tier fix, interpreter deletion, and gate coverage:
  all confirmed).
- Confirmed (not disproved) S1's own flagged CRITICAL gap (Finding 1) and
  S4's own flagged CRITICAL gap (Finding 2) are BOTH still live at HEAD —
  correctly self-reported, not fixed by wave's end.
- Confirmed all 25 `poetry run pytest` failures and the 2 non-CRITICAL
  `hooks/tests/run.sh` failures (`test_shctx_locator.sh` is Finding 2,
  already counted; `test_v644_wiring.sh`'s 2 legs) are either pre-existing
  environment gaps (bash 3.2, stale `.claude/shepherd.toml` path, sandbox
  version skew) or live sprint-run-state drift / a documented bash-vs-Python
  doctrine tension — none introduced by, or fixable within, this wave's six
  file_scopes.

## Open questions

- Whether `agent_id` (DF-77 FIX 3, still open) is present on a real
  `PreToolUse(Bash)` payload issued from inside an already-running
  subagent, in an actual interactive Claude Code session (not this
  coder-dispatch harness) — nobody in this wave could confirm it either way
  with a live capture; stays an open correlation gap, honestly documented
  in `_lib.sh`'s `current_role()` header.
- Whether root/conductor should adjudicate the `shctx plan amend`/`lane-drift`
  bash-vs-Python doctrine conflict S3 surfaced (`hooks/tests/
  test_v644_wiring.sh` two failing legs) by adding bash arms to
  `skills/context/scripts/cmd_plan.sh` or relaxing the wiring assertion — not
  an auditor call.

## Pattern delta

Two CRITICAL/HIGH-adjacent findings (Finding 1, Finding 2) both follow the
identical shape: a coder correctly identifies a cross-file consequence of
their own fix, correctly declines to edit outside file_scope, correctly
flags it with the exact remediation — and the wave ships without anyone
picking it up. This happened **twice, independently, in one wave**. Given
this wave's own stated purpose is "gates that could not fail," shipping two
new such gates (even if both are self-reported, evidenced, and one line
each to fix) is a process gap worth flagging for the conductor: an
`out_of_scope_writes` entry marked CRITICAL should trigger a same-wave
follow-up dispatch, not just an honest paragraph in a report nobody
re-reads before CLOSE. **Systemic risk flag: not yet 3+ occurrences across
3+ sprints (this is the first time this exact pattern was observed by this
auditor) — recording it here as the first data point, not yet a trend.**

## Cache telemetry

`shctx query cache-usage --sprint=v6.4.5 --md` — command exists in this
build; skipping embedding here per the audit contract's "absent view →
write baseline" clause is not applicable (the view is present), but this
report focuses on wave-scoped correctness verification per its explicit
brief (the Five Questions) rather than the standard `close`-mode
completeness checklist; telemetry is out of this wave's assigned
scope/brief and was not requested by the dispatching brief above.

## Grade

Not applicable — this is a `central-verify` mode audit (build-permitted,
task-defined via explicit Q1-Q5 + per-step PASS/REDO), not a `close`-mode
grade rubric.

## Grade rationale

N/A (see above).

---

## VERDICT per step

1. **S1-role-resolution (DF-77)** — **PASS** (own scope: role derivation,
   fallback de-escalation, deny/warn/pass logic all hand-verified live and
   mutation-tested). **Blocking dependency for the WAVE, not this step**:
   Finding 1 (CRITICAL, `conductor_write_guard.sh`) — S1 could not close it
   (out of file_scope) and correctly said so; the wave as a whole must not
   be considered done until it lands.

2. **S2-guard-serve** — **PASS**. Independently re-measured speedup
   (~6,800–24,000x depending on comparison baseline), independently
   verified serve/eval agreement across the full corpus, mutation-tested
   both the cross-check script and the real test suite.

3. **S3-plan-cli** — **PASS**, with Finding 3 (MEDIUM — the message-accuracy
   fix itself is untested, mutation-proven). The underlying anti-forgery
   property (what actually matters) is solid and well-tested.

4. **S4-wiring-truth** — **PASS**. All four diagnoses (2 test-drift repoints,
   1 correctly-preserved-failing-test, 1 correctly-halted regression)
   independently re-verified against live file content and `git log -S`
   evidence; none were fabricated or convenient.

5. **C1-pi-collapse** — **PASS**. Interpreter genuinely deleted (zero
   remaining), relay genuinely wired to `guard serve`, the `role_tier`
   regression was caught and fixed with real test coverage, and the shared
   engine's conformance gate demonstrably bites across all three harnesses
   plus the master corpus (4-for-4 red on one mutation).

6. **C2-claude-relay** — **PASS** for the DF-75-adjacent role-resolution
   work itself (6/6 tests, live root-allow/coder-deny/untraceable-deny cases
   confirmed). Finding 4 (MEDIUM/HIGH, completeness not correctness): did
   not adopt the sibling step's `guard serve` capability despite editing the
   exact call site and despite this being the wave's own headline
   before/after example — Claude's own guarded tool calls still pay
   ~750–975ms per PreToolUse.

**REDOs ranked by severity**:
1. Finding 1 (CRITICAL) — one-line fix to `conductor_write_guard.sh:93`, not
   assignable to any of the 6 existing file_scopes; needs a 7th
   dispatch or a file_scope amendment.
2. Finding 2 (HIGH) — `session_open.sh` registry_line config-gate, same
   shape, also unassignable within this wave's scopes.
3. Finding 4 (MEDIUM/HIGH) — wire `guard serve` into `packages/harness-claude`
   and `packages/harness-codex` (apply C1's `guard-client.ts` pattern).
4. Finding 3 (MEDIUM) — add an assertion on `_cmd_amend`'s printed message
   in `test_plan_amend.py` (or fold the message-accuracy check into the
   existing anti-forgery test).
5. Finding 5 (LOW) — no code action; self-report hygiene note only.

## Output to conductor

- Files reviewed: 25 changed (19 tracked modified/deleted, 6 new untracked)
  across `hooks/`, `services/cli/`, `packages/harness-{claude,codex,pi}/`,
  plus `content/predicates/*.toml` and `services/cli/shepherd_cli/
  predicates.py` as shared read targets for mutation-testing.
- Findings: CRITICAL=1, HIGH=1, MEDIUM=2, LOW=1
- Verifications (disproved): 0 (every reproducible self-report claim
  independently confirmed correct; the two CRITICAL/HIGH findings are
  confirmations of gaps the self-reports themselves already disclosed, not
  disproofs of a claim)
- Open questions: 2
- Mutations performed (all restored, byte-identical via `md5` + `git diff
  --stat` before/after): `hooks/scripts/coder_git_guard.sh` (deny→pass_silent),
  `services/cli/shepherd_cli/commands/guard.py` (serve hardcoded to allow),
  `services/cli/shepherd_cli/predicates.py` (engine core hardcoded to allow),
  `services/cli/shepherd_cli/commands/plan.py` (reverted the message fix).
  Every mutation demonstrably flipped the relevant gate(s) red; every
  restoration demonstrably returned the tree to byte-identical pre-mutation
  state.
- Grade: n/a (central-verify mode, not close-mode)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/auditor-W11-central-verify.md
- Agent ID + timestamp: auditor-W11-central-verify @ 2026-08-13T23:00:00-07:00
