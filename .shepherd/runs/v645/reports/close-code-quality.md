---
title: audit-code-quality
date: 2026-08-14
auditor: "@auditor (code-quality)"
sprint: v6.4.5
concern: code-quality
mode: close
methodology: hypothesis-driven, falsify-don't-confirm (superpowers:systematic-debugging)
prior_class_priors: "adaptation registry empty at this sprint's close (shctx adapt report / shctx adapt priors --lessons both returned no rows) — framework priors used, no sprint-specific weighting available yet."
---

## Scope reviewed

Read `git diff v6.4.4..HEAD -- hooks/ packages/ services/ skills/ scripts/ bin/` (167 files,
+16,959/-478 in this scoped tree; the sprint-wide `git diff v6.4.4..HEAD --shortstat` is
453 files / +46,611/-696). Sampled deliberately rather than top-to-bottom:

- **`packages/harness-claude/src`** — the guard-serve broker/client/engine trio in full
  (`guard-serve-broker.mjs`, `guard-serve-client.mjs`, `guard-serve-engine.mjs`,
  `guard-broker-main.mjs`, 572+71 lines), `guard.mjs`, `dispatch-record.mjs`, README. Ran
  `node --test packages/harness-claude/test/guard-serve-transport.test.mjs
  packages/harness-claude/test/guard-serve-corpus.test.mjs` live.
- **`packages/harness-codex/src`** — `guard.mjs`, `dispatch-record.mjs`, diffed byte-for-byte
  against the Claude analogs to test the "unjustified duplication" hypothesis.
- **`packages/compiler/src`** — all 7 files (406 lines) plus `test/`; ran the three test
  files directly with `node --test`.
- **`packages/harness-pi/src/guard-client.ts`** — read in full to verify the "verbatim port"
  claim in `guard-serve-engine.mjs`'s header.
- **`hooks/scripts/`** — `_lib.sh`, `conductor_write_guard.sh`, `coder_git_guard.sh`,
  `teammate_git_guard.sh`, `dispatch_guard.sh`, `bash_guard.sh`, `session_open.sh`,
  `agent_invocation_tagger.sh` in full; grepped every changed `.sh` file for
  `2>/dev/null || true`, `|| echo <default>`, embedded NUL bytes, and TODO/FIXME/XXX/HACK.
  Ran `bash hooks/tests/test_coder_git_guard.sh`, `bash hooks/tests/test_sql_escaping.sh`
  live.
- **`skills/context/scripts/`** — `cmd_adapt.sh`, `cmd_loop.sh`, `cmd_teammate.sh`,
  `cmd_eval.sh`, `cmd_audit.sh`, `cmd_signal.sh`, `cmd_mem.sh`, `cmd_query.sh`,
  `cmd_deliverable.sh`, `cmd_discovery.sh`, `cmd_prune.sh` — grepped for the GH #285
  SQL-escaping idiom across all of them to check for recurrence beyond the two named sites.
- **`services/cli/shepherd_cli/`** — `commands/doctor.py`, `commands/plan.py`,
  `commands/run.py`, `commands/guard.py`, `predicates.py`, `models_run.py` — every
  `except` clause in every file touched this sprint, checked for bare/silent catches.
- Full repo-wide (all files touched this sprint) Python byte-scan for embedded NUL bytes;
  full repo-wide grep for `TODO|FIXME|XXX|HACK` in changed code (not skill prose).

**Not sampled in depth** (left to sibling concerns or out of budget): `services/cli/tests/`
internals beyond spot-checking imports; `packages/harness-pi/src` beyond `guard-client.ts`;
`scripts/tests/fixtures/stage-graph`; the conformance corpus under `conformance/`; the full
453-file sprint diff outside the four trees named in the brief.

## Findings summary

CRITICAL=0, HIGH=1, MEDIUM=2, LOW=1 (tracked). Zero TODO/FIXME/XXX/HACK markers left in
shipped code. Zero bare/silent `except`/empty-catch found in sprint-touched Python or JS.
The sprint's own thesis — collapsing three predicate interpreters into one — holds up under
direct inspection: the git-subcommand tokenizer, the interpreted-verdict shapes, and the
`content/predicates/*.toml` loader all trace to exactly one canonical implementation
(`services/cli/shepherd_cli/predicates.py`), not a fourth reimplementation.

## Findings

### HIGH — the sprint's largest new abstraction has zero call sites in this repo's live config

**Hypothesis**: the guard-serve broker (`packages/harness-claude/src/guard-serve-{broker,
client,engine}.mjs` + `hooks/guard-broker-main.mjs` + `guard.mjs`'s `buildGuardHooksEntry()`
+ `dispatch-record.mjs` — ~600+ new lines, explicitly the sprint's single largest new
abstraction per this audit's own brief) is not actually wired into anything this repository's
own Claude Code install runs.

**Falsification**:
```
$ grep -n "guard-eval\|harness-claude" hooks/hooks.json
(no output)

$ python3 -c "
import json
d = json.load(open('hooks/hooks.json'))
def walk(o):
    if isinstance(o, dict):
        if 'command' in o: print(o['command'])
        for v in o.values(): walk(v)
    elif isinstance(o, list):
        for x in o: walk(x)
walk(d)" | grep -i guard
${CLAUDE_PLUGIN_ROOT}/hooks/scripts/bash_guard.sh
${CLAUDE_PLUGIN_ROOT}/hooks/scripts/teammate_git_guard.sh
${CLAUDE_PLUGIN_ROOT}/hooks/scripts/coder_git_guard.sh
... (18 more, all hooks/scripts/*.sh, zero packages/ entries)
```
All 22 guard command entries in the live `hooks/hooks.json` are the pre-existing bash-native
scripts. `guard-eval.mjs` — the one entrypoint `buildGuardHooksEntry()` produces
(`node ${CLAUDE_PLUGIN_ROOT}/packages/harness-claude/hooks/guard-eval.mjs`) — is absent.
`packages/harness-claude/README.md` confirms this is a known, disclosed gap, not an
oversight this audit is the first to notice: *"Materializing onto the LIVE `agents/`/`skills/`
tree at the repo root is a future step's job, not this one's — `packages/harness-claude/` is
this step's entire file scope."* `guard.mjs`'s own docstring for `buildGuardHooksEntry()`
says the same: *"Consumed by whatever future step materializes `packages/harness-claude/`'s
output onto the live `hooks/hooks.json` (out of this step's file scope)."*

The code itself is good: `node --test packages/harness-claude/test/guard-serve-transport.test.mjs
packages/harness-claude/test/guard-serve-corpus.test.mjs` passes 2/2 live, and the assertions
are real mutation tests, not manufactured preconditions — `engine killed mid-session -> next
request denies in 1ms`, `stale socket file recovered from in 97ms`, `an idle broker (250ms
timeout) self-terminated`, `an engine that never starts fails closed in 1012ms`, plus a live
measured `LATENCY cold=116ms | warm avg=0.184ms`. This is not a "gate that cannot fail."

**Why this still matters at HIGH**: the CHANGELOG's own v6.4.5 entry, under "one evaluator,
and the CLI stops paying for itself," states *"All three adapters now evaluate through one
implementation, with a conformance gate that goes red on any divergence."* Read against this
repository's actual enforcement surface, that is true of the Codex and Pi packages' relation
to their own distribution targets but not of the Claude adapter's relation to *this*
repository's own live plugin install: every Write/Edit/Bash/Agent/Workflow call in this very
session is still evaluated exclusively by the bash-native guards, never by the shared engine.
The measured 450–535ms → sub-ms win is real for the isolated code path and not yet realized
anywhere a user or this sprint's own dogfood run would feel it. Shipping ~600 lines of new,
well-tested production machinery that has no live call site is the same shape of risk as the
sprint's own "gate that cannot fail" class one level up the stack: not a false-green test, but
a false-green *narrative* — "the collapse happened" is true in `packages/`, not yet true in
`hooks/hooks.json`.

**Recommendation**: either (a) file the wiring step explicitly (it does not appear to have its
own GH issue today — a `grep -rn "guard-eval\|hooks.json" ` over open issues found nothing
naming this specific gap) and land it before touting the latency number as delivered, or
(b) if the deferral is intentional pending further validation, say so explicitly in the
CHANGELOG rather than "all three adapters now evaluate through one implementation."

**Confidence**: HIGH — mechanically verified against the live config file, not inferred from
a report.

### MEDIUM — a reproducibility-critical source file is permanently unreadable to `git diff`

**Hypothesis**: `packages/compiler/src/tree.mjs` (new, W4, commit `c719ef3`) contains a
literal encoding defect that breaks standard code-review tooling.

**Falsification**:
```
$ file packages/compiler/src/tree.mjs
packages/compiler/src/tree.mjs: data

$ python3 -c "
d = open('packages/compiler/src/tree.mjs','rb').read()
print(len(d), d.count(b'\x00'))"
2257 3

$ git diff v6.4.4..HEAD -- packages/compiler/src/tree.mjs
diff --git a/packages/compiler/src/tree.mjs b/packages/compiler/src/tree.mjs
new file mode 100644
index 0000000..82d3094
Binary files /dev/null and b/packages/compiler/src/tree.mjs differ
```
`digestFiles()`'s separator strings — meant to read as `" "` and `"  "` per the surrounding
JSDoc and per how Claude Code's own file-reading tool renders the file (it silently displays
the NUL bytes as blank space, which is how this defect stayed invisible to review) — are
literal `\x00` bytes in the committed source, not the escape sequence `"\0"`. The file
functions correctly at runtime (`node -e 'import("./packages/compiler/src/tree.mjs").then(m =>
console.log(JSON.stringify(m.buildEmittedTree("claude",[{path:"a.md",content:"hello",
kind:"skill",sourcePath:"x"}]))))'` produces a correct digest), so this is not a functional
bug. But it means `git diff`, `git log -p`, and `git blame` on this file — whose entire
purpose is the reproducibility contract `packages/compiler/test/reproducibility.test.mjs`
proves — will print "Binary files … differ" forever, for every future change, defeating
line-level review of the one file in the package most load-bearing for correctness.

Confirmed isolated: a byte-scan of every file touched this sprint (167 files under the four
trees this audit covers) found this is the only file carrying an embedded NUL byte.

**Confidence**: HIGH — mechanically verified, not a style opinion.

### MEDIUM — the sprint fixed a dead-code pattern in one guard script and left an identical instance in its sibling, one wave earlier, in the same sprint

**Hypothesis**: `hooks/scripts/coder_git_guard.sh` still carries the exact anti-pattern a
sibling guard script explicitly diagnosed and removed later in this same sprint.

**Falsification**:
```
$ grep -n 'current_role.*|| echo unknown' hooks/scripts/coder_git_guard.sh
88:ROLE="$(current_role "$TOOL_USE_ID" "$SPRINT" 2>/dev/null || echo unknown)"

$ bash -c 'source hooks/scripts/_lib.sh; current_role x y; echo "exit=$?"'
unknownexit=0
```
`current_role()` (`hooks/scripts/_lib.sh:588`) always exits 0 — every branch ends in a
`printf`, several explicitly `|| printf 'unknown'`-guarded — so `|| echo unknown` on line 88
can never execute; whatever `current_role()` prints is what `ROLE` gets, always. This is
precisely what `hooks/scripts/conductor_write_guard.sh` (W12, commit `b57d495`, the sprint's
final wave) diagnosed and removed one wave later, in a comment that names the exact
mechanism:

> `current_role() always exits 0 (its own contract — every branch ends in a printf, several
> explicitly `|| printf 'unknown'`-guarded), so a fallback on non-zero exit here never fires;
> dropped rather than left as dead error-handling that looks like a safety net but is not
> one.`

`coder_git_guard.sh` was itself rewritten one wave earlier in the same sprint (W11, commit
`6f2eaa9`, "DF-77 — the guard that had never denied anything") — touched, extensively, and
the identical dead fallback survived that rewrite untouched. `bash_guard.sh`'s own call
(`role=$(current_role "$tool_use_id" "$sprint")`, no fallback) shows the correct form was
already present elsewhere in the same directory before either wave ran.

Functionally harmless — `bash hooks/tests/test_coder_git_guard.sh` passes 33/33 live, and the
fallback value never diverges from what `current_role()` actually returns. This is a
consistency/hygiene finding, not a live defect: the sprint named this exact anti-pattern as
worth removing, in this exact function, in a sibling file, and did not sweep the one other
call site carrying it.

**Confidence**: HIGH — mechanically verified (the `_lib.sh` function body, the live exit-code
test, and the git log ordering of the two commits).

### LOW (tracked, GH #285 open) — the now-correct SQL-escaping idiom is duplicated 4 times, not consolidated

**Hypothesis**: GH #285's broken SQL quote-escaping (`${v//\'/\'\'}`, which does not double a
quote on bash 3.2) still reproduces at close, and/or its fix reproduces the sprint's own
duplication thesis in miniature.

**Falsification**: the specific defect is fixed and verified live —
`bash hooks/tests/test_sql_escaping.sh` → `4/4 passed`, including an apostrophe round-trip and
a DROP-TABLE-shaped adversarial payload through both `cmd_adapt.sh` and `cmd_loop.sh`.
`hooks/scripts/dispatch_guard.sh`'s `sql_lit()` (the auditor-found original instance) is
independently fixed and commented with the same rationale. But the correct one-line idiom
(`sed "s/'/''/g"`) is now implemented **four separate times** — `cmd_teammate.sh`'s `esc()`
(pre-existing, correct), `cmd_adapt.sh`'s `esc()`, `cmd_loop.sh`'s `esc()`, and
`dispatch_guard.sh`'s `sql_lit()` — none sourced from a shared `_lib.sh`, despite both
relevant `_lib.sh` files existing and each site's own comment naming the gap: *"duplicated
here rather than sourced because it belongs in the shared `_lib.sh`, which is a sibling's
scope this wave — see #285 follow-up to consolidate."* GH #285 (state: OPEN, verified via
`gh issue view 285`) tracks the consolidation explicitly. This is disclosed, not hidden, and
each of the 4 sites is individually correct today — the residual risk is only that a 5th
call site written without reading these comments could reintroduce the original bug, since
there is still no single function to reach for.

**Confidence**: HIGH on the duplication count; the severity is LOW because the defect itself
is fixed and the gap is already tracked by the operator.

## Verifications (disproved)

1. "GH #285's broken SQL escaping still exists in `cmd_adapt.sh`/`cmd_loop.sh` at close" —
   disproved; both use the correct `esc()`/sed idiom, proven by a live regression test
   round-tripping an apostrophe and a DROP-TABLE-shaped payload through real sqlite3 rows.
2. "`dispatch_guard.sh`'s `sql_lit()` still carries the broken parameter-expansion doubling" —
   disproved; fixed, with an inline comment naming the exact prior failure mode and citing
   the `sqlite3 :memory:` verification that caught it.
3. "The duplicate `resolveRole` implementations in `packages/harness-claude/src/
   dispatch-record.mjs` and `packages/harness-codex/src/dispatch-record.mjs` are wasteful
   reinvention" — disproved; the two harnesses have structurally different correlation
   primitives (Claude's `tool_use_id` marker-file scheme vs. Codex's `agent_id` wire field),
   and Claude's own module deliberately shells out to the existing bash `current_role()`
   rather than re-deriving the lookup in JS, precisely to avoid a second copy of the
   correlation rule.
4. "The guard-serve broker's tests are shallow / manufactured preconditions, the sprint's
   dominant 'gate that cannot fail' pattern" — disproved as literally stated; the transport
   tests kill the engine mid-session, corrupt the socket, and force an idle-timeout, all
   independently confirmed against the real production socket path in a prior wave's audit
   and reproduced here. (Reframed into the HIGH finding above, which is a different claim:
   not that the tests are fake, but that the tested code has no live caller.)
5. "TODO/FIXME/XXX/HACK markers were left behind in shipped code this sprint" — disproved;
   a full scan of every changed `.sh`/`.py`/`.mjs`/`.ts` file under the four trees found zero
   hits (one prose mention of the word "TODO" inside `skills/shepherd/references/flock.md`,
   discussing dispatch-law text, not a marker).
6. "Bare/silent exception handling hides real errors in `services/cli`" — disproved; every
   broad `except Exception` in files touched this sprint carries a `# noqa: BLE001` plus an
   inline rationale (process-boundary, advisory-only-by-contract, or bash-parity), and none
   discard the exception without reporting it somewhere (a malformed-line JSON response, a
   CRITIC-PROOF-MISSING message, or explicit bash-parity silence for a check bash itself
   never performed).

## Open questions

- Whether the guard-serve wiring gap (HIGH finding above) already has a tracking issue this
  audit did not find via `gh issue view`/local grep — worth a conductor/root check before
  filing a duplicate.
- Whether `packages/compiler/src/tree.mjs`'s NUL bytes originated from a Write-tool escaping
  bug worth its own defect report against the authoring tool itself, separate from fixing
  this one file — out of this audit's scope to diagnose further.

## Grade

B-

## Grade rationale

The sprint's own stated thesis — collapsing three predicate interpreters into one — holds up
under direct inspection, not just report-reading: the git-subcommand tokenizer, the
interpreted-verdict shapes, and the TOML predicate loader all trace to exactly one canonical
implementation, and the code sampled across `packages/`, `hooks/scripts/`, and
`services/cli/` is disciplined — no TODO markers left behind, no bare excepts, exception
handling that is annotated and reasoned rather than swallowed, and self-documenting headers
that mostly hold up when checked against the actual runtime contract. That would place this
concern in A-/B+ territory on its own. It is held down to B- by one HIGH finding — the
sprint's single largest new abstraction (the guard-serve broker) is fully built and
genuinely well-tested but has zero call sites in this repository's own live `hooks/hooks.json`,
so the sprint's headline "one evaluator" claim is true of the source tree and not yet true of
this repo's actual enforcement surface — plus two MEDIUM findings (a reproducibility-critical
compiler source file rendered permanently binary-looking to git by embedded NUL bytes, and a
dead-code fallback the sprint explicitly diagnosed and removed in one guard script while
leaving the identical instance untouched in a sibling script edited one wave earlier). None
of the three are CRITICAL, none broke a test, and two of the three were independently
falsifiable as harmless in isolation — but per the letter rubric ("MEDIUM/HIGH findings; real
work mostly delivered"), a HIGH finding forecloses A/A-/B+/B regardless of how clean the
surrounding code is.

## Output to conductor

```
## AUDITOR REPORT
- deliverable: 20 (status: delivered)
- Concern: code-quality
- Mode: close
- Files reviewed: ~45 read in full (guard-serve trio + guard-broker-main + guard.mjs x2 +
  dispatch-record.mjs x2 + compiler/src full 7 files + guard-client.ts + 8 hooks/scripts/*.sh
  in full + 11 skills/context/scripts/*.sh greped + 6 services/cli/*.py); 167 files' diffs
  scanned programmatically (TODO/FIXME grep, NUL-byte scan, `|| echo`/`2>/dev/null || true`
  grep) across the four trees named in the brief.
- Findings: CRITICAL=0, HIGH=1, MEDIUM=2, LOW=1
- Verifications (disproved): 6
- Open questions: 2
- GH issues filed: none (GH #285 already open and cited, not duplicated)
- Grade: B-
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/close-code-quality.md
- Hot-fix-lane recommendations: 1 (wire packages/harness-claude's guard-eval.mjs into
  hooks/hooks.json, or explicitly re-scope the CHANGELOG claim — see HIGH finding)
- Sprint-pattern entry: skipped (adaptation registry empty this sprint — first cycle lands at
  this close per project memory; no `shctx adapt` write attempted, none required by this
  concern's contract)
- Agent ID + timestamp: auditor-code-quality-v645 @ 2026-08-14T00:00:00Z
```
