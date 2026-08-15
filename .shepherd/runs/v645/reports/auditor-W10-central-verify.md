---
title: W10 Central Verification — guard-engine build + 3-adapter predicate-interpreter collapse (10 steps)
date: 2026-08-13
auditor: central-verify (subagent, this dispatch)
sprint: v645
concern: central-verify (A1-A7, B1-B3 — the wave's only build-permitted agent)
mode: central-verify (read-only build/execute)
methodology: superpowers:systematic-debugging (falsify-don't-confirm; every
  claim grounded in a command run this session and its verbatim exit code;
  self-reports treated as zero-authority hypotheses, the diff and live HEAD
  as the only evidence)
---

## Repo / environment facts (verified first)

- `pwd` = `/Users/jo3/src/fl03/shepherd`, `git branch --show-current` = `v6.4.5`,
  `git rev-parse HEAD` = `c719ef380b9d3aff5d09dcb5d26cbe7949a6fc98`. No `WORKTREE-DRIFT`.
- `git status --porcelain` at start: 31 tracked modified files + 10 new
  untracked files. Every one of the 41 changed/new paths maps to exactly one
  declared step `file_scope.exclusive` (checked file-by-file below); no
  cross-scope violations, no orphan writes.
- `df-guard.sh --min=12` → `65Gi available at . (min 12Gi) — OK` before the
  one cargo invocation; isolated `CARGO_TARGET_DIR` used and deleted after.

## Serial gate results (exit codes read directly, never through a pipe)

| # | Command | Exit | Verbatim tail |
|---|---|---|---|
| 1 | `bash hooks/tests/run.sh` | **3** | `—— 83/86 passed ——` |
| 2 | `cd services/cli && poetry run pytest -q` | **1** | `25 failed, 1860 passed in 541.24s` |
| 3 | `node --test packages/harness-claude/test/` | **1** | `Error: Cannot find module '.../harness-claude/test'` (MODULE_NOT_FOUND) |
| 4 | `node --test packages/harness-codex/test/` | **1** | same MODULE_NOT_FOUND shape |
| 5 | `node --test packages/harness-pi/test/` | **1** | same MODULE_NOT_FOUND shape |
| 6 | `bin/shepherd guard test` | **0** | `17/17 examples passed` |
| 7 | `bash scripts/check-workflow-meta.sh --self-test` | **0** | `ok: every self-test control behaved as designed.` |
| 8 | `cargo check --workspace` (isolated target dir) | **0** | `Finished \`dev\` profile [optimized + debuginfo] target(s) in 7.52s`, zero warnings |

**Gates 3-5 (Node `--test <dir>/`) are a genuine Node v26.7.0 environment
quirk, not a defect in any diff.** Reproduced byte-for-byte identically in a
throwaway scratch directory with one trivial `node:test` file
(`/private/tmp/.../scratchpad/node-quirk-check`) — same
`Error: Cannot find module '.../test'`, same exit 1. The real signal, run as
literal-command fallback:
```
$ node --test 'packages/harness-claude/test/*.test.mjs'   → tests 6, pass 6, fail 0
$ node packages/harness-claude/test.mjs (custom runner)   → 6/6 test file(s) passed
$ node --test 'packages/harness-codex/test/*.test.mjs'    → tests 5, pass 5, fail 0
$ node --test 'packages/harness-pi/test/*.test.mjs'       → tests 8, pass 8, fail 0
```
All three adapters' full suites are green.

**Gate 1 (83/86, exit 3)** — the 3 failures are `shctx-locator`,
`v644-doctrine-wiring` (#268/#269), `v630-wiring` (#187/#183) — matches A3's
own self-report exactly, verbatim, including the exact sub-check names and
counts. Confirmed pre-existing/out-of-file-scope, not a regression this wave
introduced (A3's own diagnosis, cross-checked against the raw log).

**Gate 2 (25 failed / 1860 passed)** — every failure is one of two
pre-existing, unrelated root causes, re-confirmed directly:
- `test_config_schema.py` (2) — fixture looks for `.claude/shepherd.toml`;
  live config is `.shepherd/shepherd.toml` (repo-layout mismatch, untouched
  by this wave).
- `test_doctor.py::test_version_match_emits_no_row` (1) — installed `.venv`
  reports `6.4.4` vs `plugin.json`'s `6.4.5` (stale local install).
- `test_issues.py::test_bash_parity_*` (22) — every one traces to `ERROR:
  shctx issues requires bash 4+ (have 3.2.57(1)-release)`; this test file
  invokes plain macOS `bash`, unlike A3's own `_find_bash4()` discovery in a
  *different* test file.
None of the three NEW test files this wave added (`test_guard.py`,
`test_run_claim.py`, `test_lint_workdir.py`) appear anywhere in the failure
list — independently re-ran all three together: **48 passed** (31 + 10 + 7,
matching each coder's own claimed counts exactly).

---

## THE FOUR QUESTIONS

### Q1 — Does `shepherd guard eval` actually DENY something? Is it falsifiable?

Hand-built deny case:
```
$ echo '{"role":"coder","tool_name":"Bash","tool_input":{"command":"git commit -am x"}}' | bin/shepherd guard eval
{"decision": "deny", "predicate": "git-custody", "rule": "implementer-never-writes-git",
 "halt_code": "CODER-GIT-WRITE", "reason": "A role dispatched to implement one
 file-disjoint scope (coder) never performs any version-control write, under any
 circumstance — custody sits one tier up, always."}
```
Mutated `services/cli/shepherd_cli/predicates.py:431` (the one line every
`evaluate_predicate()` call returns through —
`return ("deny", fired) if fired else ("allow", [])` → forced to always
`return ("allow", [])`). Confirmed RED:
```
$ bin/shepherd guard test
FAIL dedup-gate/coder-writes-an-already-existing-public-symbol: expected 'deny' got 'allow'
FAIL git-custody/coder-attempts-a-commit: expected 'deny' halt_code='CODER-GIT-WRITE' got 'allow'
... (9 of 17 deny-examples now silently allow)
8/17 examples passed, exit=1
$ echo '{"role":"coder", ...git commit...}' | bin/shepherd guard eval
{"decision": "allow"}
```
Restored from a pre-mutation backup: `diff` empty, `sha256sum` identical
(`79e92dfa...ce6ce1dca` before and after), `git status --porcelain` for the
file unchanged (still `??`, untracked, same content), `bin/shepherd guard
test` green again (`17/17 examples passed`).

**Q1 answer: YES — the engine genuinely denies, and the PASS is proven
falsifiable, not merely asserted.**

### Q2 — Is codex-shepherd's guard still a no-op (DF-75)?

Did NOT read the tests, did NOT set `SHEPHERD_ROLE`. Drove the REAL hook
entrypoint (`packages/harness-codex/hooks/scripts/shepherd_guard.mjs`)
directly with a disposable `SHEPHERD_WORKDIR`, simulating the two real Codex
hook events in sequence:

```
STEP A — genuine PostToolUse(spawn_agent) dispatch tagging agent-audit-q2-1 as coder:
$ echo '{"hook_event_name":"PostToolUse","tool_name":"spawn_agent",
         "tool_input":{"task_name":"shepherd_coder_l6-guards",...},
         "tool_response":{"agent_id":"agent-audit-q2-1"}}' | node .../shepherd_guard.mjs
exit=0
$ cat dispatch/codex/<hash>.json
{"agent_id":"agent-audit-q2-1","agent_role":"coder","recorded_at":1786673279.214}

STEP B — genuine PreToolUse(Bash, git commit) from THAT SAME agent_id, no SHEPHERD_ROLE ever set:
$ echo '{"hook_event_name":"PreToolUse","tool_name":"Bash",
         "tool_input":{"command":"git commit -am audit-test"},
         "agent_id":"agent-audit-q2-1"}' | node .../shepherd_guard.mjs
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
 "permissionDecisionReason":"[CODER-GIT-WRITE] guard denied (git-custody/
 implementer-never-writes-git): ..."}}
exit=0

STEP C — an agent_id that NEVER got a PostToolUse dispatch record (the DF-75 regression itself):
$ echo '{"hook_event_name":"PreToolUse","tool_name":"Bash",
         "tool_input":{"command":"git commit -am audit-test"},
         "agent_id":"agent-ghost-never-dispatched"}' | node .../shepherd_guard.mjs
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
 "permissionDecisionReason":"role unresolved -- no dispatch record for agent
 \`agent-ghost-never-dispatched\`. ... DF-75 requires failing closed rather
 than allowing an unidentified dispatch to write."}}

STEP D (control) — no agent_id at all (root's own session, never dispatched): silent, exit=0
STEP E (control) — resolved coder doing `git status` (read-only): silent, exit=0
```

Role resolves via the REAL correlation path (`agent_id` — a genuine Codex
wire field per the module's own three converging evidence sources, cross-
checked independently against the installed `codex-shepherd@1.0.2` sibling's
`hooks/protocol.py`, which reads `agent_id`/`agent_type` off the identical
hook payload shape). A dispatched-but-never-tagged agent is now DENIED
(Step C), not silently allowed — this is the exact DF-75 regression, closed.

**Q2 answer: NO — the guard is no longer a no-op.** Role resolution works
through the real path with zero test-only scaffolding, and the specific
"marker present, record missing" case DF-75 exists to close now fails
closed. (Caveat, not a defect in this wave: this mechanism is per-adapter —
Claude's own relay has the *identical* unfixed gap; see the HIGH finding
under B3 below.)

### Q3 — Do all three adapters now reach ONE evaluator?

**Two of three do; the third deliberately does not, matching a pre-existing
design intent this wave did not invent.** Pre-wave `packages/harness-claude/
src/guard.mjs`'s own header (git-blame'd at HEAD, unrelated to this wave's
diff) already stated the target shape: *"guard predicates ... are
interpreted by exactly ONE evaluator on Claude and Codex ... with Pi's TS
interpreter as the sole SECOND one, kept in lockstep by a shared ... corpus."*
This wave delivered exactly that:

```
$ find packages -iname "predicates*" -o -iname "toml-lite*" | grep -v node_modules
packages/harness-pi/src/predicates.mjs        # the one remaining local interpreter, by design
$ git status --porcelain -- packages/harness-codex/src/predicates.mjs packages/harness-codex/src/toml-lite.mjs \
    packages/harness-codex/test/predicates.test.mjs packages/harness-codex/test/toml-lite.test.mjs
 D packages/harness-codex/src/predicates.mjs
 D packages/harness-codex/src/toml-lite.mjs
 D packages/harness-codex/test/predicates.test.mjs
 D packages/harness-codex/test/toml-lite.test.mjs
$ rg -n "predicates\.mjs|toml-lite" packages/ --glob '!**/node_modules/**'
packages/harness-pi/src/predicates.mjs:1: ...                       # its own file header
packages/harness-codex/README.md:48-49: ... (historical prose only, no import)
packages/harness-pi/test/guard-predicates.test.mjs:12:import {...} from "../src/predicates.mjs"
```
No live import of either deleted Codex module anywhere in `packages/`.
`git log --all --diff-filter=A -- packages/harness-claude/*predicat*` returns
nothing — harness-claude never had a local interpreter to delete; it was
already relay-shaped (buggy, but never a second interpreter). `grep -n "guard
eval" packages/harness-claude/src/guard.mjs` / codex's `shepherd_guard.mjs`
both confirm both relays now shell to `bin/shepherd guard eval`.

Pi's retained interpreter (`guard.ts` `evaluate()` + `predicates.mjs`, 242
lines) is a documented HALT, not an oversight — independently re-measured,
not merely trusted:
```
$ for i in 1 2 3 4 5; do /usr/bin/time -p sh -c 'echo {...} | bin/shepherd guard eval >/dev/null'; done
real 0.70 / 0.67 / 0.71 / 0.71 / 0.84   (worse than B2's own 430-600ms claim)
```
`extension.ts`'s `pi.on('tool_call', ...)` calls `evaluate()` synchronously,
in-process, on every tool call — no hooks.json subprocess boundary exists to
absorb a 700ms-per-call stall. B2's dated header comments in both files
record the measurement and the correct next shape (a long-lived `guard
serve` process), and neither file's logic changed (diff is comment-only,
`+28/-0`). `guard-predicates.test.mjs` still replays the *same*
`content/predicates/*.toml` corpus (`bin/shepherd guard test`'s own source)
— confirmed via `grep`, `8 allow / 9 deny` — so pi's interpreter cannot
silently drift from the shared corpus even though it isn't the shared code.

**One genuine risk surfaced by this question, not fixed this wave (see B3
finding below): harness-claude's relay reaches the one evaluator
structurally, but is not YET SAFE to wire live** — its payload never
supplies `role`, unlike Codex's now-complete `dispatch-record.mjs`
mechanism. Confirmed the relay is not materialized into the live
`hooks/hooks.json` today (`grep -n "guard-eval" hooks/hooks.json` → no
match); Claude's real, live enforcement today is still the independent bash
guards (`coder_git_guard.sh`, `teammate_git_guard.sh`, `dispatch_guard.sh`),
so there is no live blast radius from this gap — but it must close before
anyone materializes the relay.

### Q4 — What is the true SUBTRACT delta?

Literal command, as instructed:
```
$ git diff v6.4.4..HEAD --shortstat -- crates packages services skills hooks agents commands scripts
202 files changed, 16489 insertions(+), 412 deletions(-)
```
**This number does NOT measure W10.** `v6.4.4..HEAD` is 105 committed
commits (`git log --oneline v6.4.4..HEAD | wc -l`) spanning the entire
v6.4.5 dev sprint's W0 through W9 — W10 is still uncommitted working-tree
state and is invisible to this range entirely. Reporting +16077 net as "this
wave's" delta would be a misattribution; the honest wave-scoped number is
the current working tree:

```
$ git diff --shortstat -- crates packages services skills hooks agents commands scripts
31 files changed, 1051 insertions(+), 672 deletions(-)          # tracked only
+ 10 new untracked files, 2732 lines (100% additions, wc -l per file)
= W10-ONLY TOTAL: 3783 insertions(+), 672 deletions(-), NET +3111
```

**This is net-POSITIVE, not "strongly net-negative." Reporting it plainly,
not rounding it into a pass, per the brief's instruction.** Naming where the
lines went:

| Bucket | Lines | Nature |
|---|---:|---|
| A1 — brand-new shared engine (`predicates.py`+`guard.py`+`test_guard.py`) | +1396 | New infrastructure. `crates/cli` (the engine plan.md originally named) is still `Init`-only — there was no pre-existing Rust engine to relay onto, so the Python engine is a net-new build, not a subtraction target. |
| B1 — new DF-75 role-resolution (`dispatch-record.mjs`+test) | +306 | New capability, not a collapse — Codex never had this mechanism in any form. |
| A2/A5 — new regression suites (`test_run_claim.py`, `test_lint_workdir.py`) | +473 | Unrelated bugfix test coverage, bundled into this wave. |
| A6 — new meta-literal gate + test | +404 | Unrelated new gate (DF-69), bundled into this wave. |
| A4 — new SQL-escape regression test | +153 | Unrelated bugfix test, bundled into this wave. |
| A3 — hooks-suite hardening | +169 net | Bugfixes (malformed-payload gate, dead-code unstranding, 2 new suite registrations). |
| A7 — doctrine reconciliation | +21 net | Documentation-only. |
| B3 — Claude relay bugfix + integration test | +135 net | Real bugfixes (`unresolved` branch, `halt_code` surfacing) + a live integration test — not bloat, but also not a "collapse." |
| B2 — pi | +28 net | Comments only (the correctly-declared HALT). |
| **B1's own actual interpreter-collapse subset** (guard.mjs + shepherd_guard.mjs + hooks.json + README rewrite, minus the deleted `predicates.mjs`/`toml-lite.mjs`/their tests, EXCLUDING the new `dispatch-record.mjs`) | **−208** | **This is the one number that genuinely matches the "collapse" framing — isolated via `git diff --stat` on exactly those 9 files: 327 insertions, 535 deletions.** |

**The narrow "three interpreters collapse into one" sub-goal, isolated from
everything else bundled into this wave's dispatch, DID land net-negative
(−208, B1's own module deletion).** Claude never had a second interpreter to
delete (net 0 there was always structurally correct). Pi's interpreter was
correctly *not* collapsed (a measured, evidenced HALT, worth zero LOC
change). The wave's overall +3111 net comes almost entirely from work that
was never "collapse three into one" in the first place — a brand-new engine
that had no prior form to subtract from, plus five unrelated bugfixes/gates
each carrying their own mandatory regression test. **This is a real finding,
not a rounding error: whoever framed "this wave was supposed to be strongly
net-negative" conflated the wave's full 10-step scope with the narrower
3-step (B1/B2/B3) collapse mandate.** No individual step's diff is wrong or
bloated for it (A1 had to build the engine somewhere; A2–A7 are legitimate,
independently-tested fixes) — flagging this as a wave-level framing gap for
the conductor/engineer, not a REDO of any step.

---

## Per-step verdicts

| Step | Verdict | Notes |
|---|---|---|
| A1-guard-engine | **PASS** | 1396 new lines match exactly (918+158+320); `app.py` 1-line insertion confirmed. Q1's mutate/RED/restore cycle run directly against this step's own load-bearing line (predicates.py:431). |
| A2-run-claim | **PASS** | `run claim` independently proven read-only against the LIVE v645 run.json (sha256 identical before/after) and fail-closed on malformed JSON (exit 2, verbatim error). |
| A3-hooks-suite | **PASS** | `hooks/tests/run.sh` 83/86 exit=3 reproduced exactly, including the 3 named pre-existing failures. `run.sh`'s two new-suite registrations (`sql-quote-escaping`, `workflow-meta-literal`) confirmed present and correctly attributed to this step's own declared file scope. |
| A4-sql-escape | **PASS** | Fix confirmed complete (only comment-text occurrences of the broken pattern remain); reverted both files to pre-wave HEAD content and reproduced the EXACT predicted `sqlite3` parse error (2/4 RED), then restored byte-identical (diff empty). |
| A5-workdir-lint | **PASS** | Live `bin/shepherd lint` on this repo shows the new `lint: root=... files=5` banner and stays green; all 39 pre-existing `test_lint.py` tests re-run clean; `shctx_repo_root()`'s new plugin-manifest fallback is purely additive, confirmed by reading the diff directly. |
| A6-meta-gate | **PASS** | Self-test's negative control (`686084d`) independently resolved and confirmed to contain the real `whenToUse` concatenation; ran the gate against the live `workflows/wave.js` directly (1 file, `ok`). |
| A7-doctrine | **PASS** | Spot-checked 5 of 7 claimed fixes directly against the diff and cross-referenced sources: `TEAMMATE-GIT-WRITE` narrowing matches `teammate_git_guard.sh`'s actual `FORBIDDEN_PATTERN` (merge/rebase/cherry-pick/worktree only, no push/commit); `shctx teammate state <name>` and `shctx query dedup-check` are both real, live, working CLI surface (not invented); `declared_state` enum (`init│in-progress│idle│complete│error`) matches migration 0019 verbatim; DF-12 self-register addition in `engineer.md`/`spawn.md` matches the conductor's own pre-existing pattern. |
| B1-codex | **PASS** | Wire-format correction independently corroborated against the installed `codex-shepherd@1.0.2` sibling's real `hooks/protocol.py::denial()` (nested `hookSpecificOutput`, exactly as claimed — the OLD flat shape genuinely would have been silently ignored). DF-75 role resolution proven live end-to-end via Q2 above, through the real hook script, zero test-only scaffolding. |
| B2-pi | **PASS** | HALT independently re-measured and found MORE severe than self-reported (0.67-0.84s vs claimed 0.43-0.60s) — the decision to not collapse is correct and evidenced, not a shortcut. Zero functional change confirmed (`+28/-0`, comments only). |
| B3-claude-adapter | **PASS on its own declared scope, with ONE HIGH-severity, non-blocking-for-THIS-wave finding** — see below. |

### B3 HIGH finding (carried forward, not a REDO of B3's own diff)

**harness-claude's guard relay has NO role-resolution mechanism — confirmed
directly, not merely repeated from the self-report:**
```
$ cat packages/harness-claude/hooks/guard-eval.mjs
...
payload = { ...JSON.parse(raw || "{}"), harness: "claude" };   // no `role` key, ever
```
If this relay is wired into the live `hooks/hooks.json` before a Claude-side
analog of Codex's `dispatch-record.mjs` exists, **every** Write/Edit/Bash/
Agent/Workflow call from **every** role — including root's own legitimate
git operations — would hit the engine's missing-role `unresolved` path and
(after B3's own correct `interpretEngineResult` fix) be **denied project-
wide**. Confirmed NOT live today (`grep -n "guard-eval" hooks/hooks.json` →
no match; Claude's real enforcement today is the independent bash-guard
stack). Not blocking this wave — correctly out of B3's declared file scope,
correctly flagged as a prerequisite rather than silently risked. **Required
before any future step materializes this relay into `hooks/hooks.json`.**

---

## Findings summary

- CRITICAL: 0
- HIGH: 1 — harness-claude relay has no role-resolution mechanism; blocks
  future live-wiring only, zero live blast radius today (B3, above).
- MEDIUM: 1 — wave-level SUBTRACT framing gap: the narrow "collapse 3 into
  1" mandate (B1/B2/B3) genuinely landed net-negative in isolation (−208),
  but the wave as dispatched (10 steps) is net +3111 because five unrelated,
  individually-justified fixes/gates were bundled into the same wave and
  each shipped its own mandatory regression test. Not attributable to any
  one step's REDO; a framing issue for whoever scopes the next wave (Q4,
  above).
- LOW: 0
- Verifications (disproved, not merely asserted): Q1's mutate/RED/restore
  cycle; A4's revert/RED/restore cycle; A2's read-only sha256 proof + fail-
  closed malformed-JSON proof; A5's live-lint proof; A6's live-file proof;
  A7's 5 cross-referenced source checks; B1's independent wire-format
  corroboration + full 5-step live DF-75 role-resolution trace (Q2); B2's
  independent re-measurement of the HALT's own numbers; Q3's full
  interpreter-inventory + import-grep across `packages/`.
- Open questions: 0

## Recommendation to conductor

**All 10 steps: PASS. No REDOs.** Every self-reported claim checked against
this session's own commands and the live diff held up, several under direct
adversarial mutation. Two items need to travel forward, not backward:

1. **Before ANY future step wires `packages/harness-claude`'s guard relay
   into the live `hooks/hooks.json`**, it needs Claude's own analog of
   `dispatch-record.mjs` — B1's Codex mechanism is the proven template
   (`agent_invocation_tagger.sh` + `tool_use_id`-keyed dispatch record already
   exists for Claude; wiring the ENGINE relay to actually read it is the gap).
   Until then, do not treat harness-claude's guard.mjs as "the collapse is
   done" for Claude — it is code-complete and correctly relay-shaped, but not
   yet safe to activate.
2. **The next wave's own dispatch brief should separate "build the shared
   engine" (inherently net-new, inherently net-positive) from "collapse N
   existing interpreters onto it" (the only sub-goal that should be graded
   net-negative) when setting a SUBTRACT expectation** — conflating the two
   this wave produced a technically-accurate-but-misleading "net +3111"
   headline number over a wave that, on its own narrow terms, delivered
   exactly the collapse it promised (−208, B1's actual module deletion).
