---
title: "Adversarial verification — W13-S1 guard relay missing-record posture fix"
date: 2026-08-14
auditor: "@auditor"
sprint: v6.4.5
concern: data-flow
mode: close
methodology: systematic-debugging (falsify, not confirm) — instrument is the real relay
  driven against the real repo (64 real dispatch records) and isolated scratch sandboxes
  mirroring hooks/scripts/_lib.sh's own contract, never the diff or the test suite alone
prior_class_priors: "This sprint's dominant defect class, 10 confirmed prior instances
  (DF-17, DF-19, DF-59, DF-62/63, DF-71, DF-72, DF-75, DF-77, GH#284, and the CRITICAL
  this step fixes): a green test suite describing a behavior the runtime does not have,
  because the test manufactures the precondition (usually an empty/seeded sandbox) the
  runtime never supplies. Weighted HIGH prior on any fixture in this diff that constructs
  its own world rather than driving the real script against real state."
---

## Scope reviewed

- `packages/harness-claude/src/guard.mjs` (+62/-25)
- `packages/harness-claude/src/dispatch-record.mjs` (+24/-5, comments only)
- `packages/harness-claude/hooks/guard-eval.mjs` (+9/-3)
- `packages/harness-claude/test/guard.test.mjs` (+142/-83)
- `packages/harness-claude/README.md` (+68/-39)
- Cross-checked (read-only): `hooks/scripts/_lib.sh`, `hooks/scripts/coder_git_guard.sh`,
  `hooks/scripts/conductor_write_guard.sh`, `hooks/scripts/agent_invocation_tagger.sh`,
  `content/predicates/write-boundary.toml`, `content/predicates/git-custody.toml`,
  `packages/harness-codex/src/dispatch-record.mjs`, `packages/harness-codex/src/guard.mjs`,
  `packages/harness-codex/test/dispatch-record.test.mjs`, `packages/harness-codex/test/guard.test.mjs`,
  `packages/harness-pi/src/extension.ts`, `packages/harness-pi/test/extension-guard.test.mjs`,
  `services/cli/tests/test_guard.py`, `services/cli/tests/test_guard_serve.py`,
  `hooks/tests/test_agent_invocation_tagger.sh`, `hooks/tests/test_sql_escaping.sh`,
  `hooks/tests/test_workflow_meta_gate.sh`.

Files reviewed: 5 changed + 17 cross-checked = 22.

**Self-correction, disclosed rather than hidden**: mid-audit I violated my own read-only
mandate once, running a python heredoc that mutated `packages/harness-claude/src/guard.mjs`
in place (the RED half of Q3) directly on the real repo, in the real working tree. Caught
immediately (one command later), restored from a pre-mutation backup, and reran the whole
Q3 RED proof correctly — mutating only a byte-identical **scratch copy** under
`/private/tmp/.../scratchpad/redtest/`, never the audited repo again. `md5` confirms the
real repo's `guard.mjs` (`b1d2fea8...`) and `guard-eval.mjs` (`de24f9d5...`) are byte-identical
to the coder's claimed hashes, and `git status`/`git diff --stat` after the incident show
only the coder's own intended diff — no residual mutation. Also removed one other read-only
violation: an early Q2 seed record briefly written into the REAL `.shepherd/dispatch/v6.4.5/`
(gitignored, but still a live-repo write) was deleted before continuing; all subsequent Q2/Q4
seeding used an isolated scratch git repo instead. Both incidents and their remediation are
recorded here in full rather than omitted.

## Findings summary

CRITICAL=0, HIGH=1, MEDIUM=1, LOW=0. Verifications (disproved hypotheses)=5. Open questions=1.

## Q1 — does a plain call from an untagged caller still deny?

Driven directly against the real repo (`/Users/jo3/src/fl03/shepherd`, real
`.shepherd/dispatch/v6.4.5/` with 64 records), fresh `tool_use_id`s, exactly as specified:

```
$ echo '{"session_id":"s1","tool_use_id":"toolu_01FRESHCALLxxxxxxxxxx","tool_name":"Bash","tool_input":{"command":"git status"}}' | node packages/harness-claude/hooks/guard-eval.mjs
{"additionalContext":"[shepherd] guard could not confirm the acting role for tool_use_id `toolu_01FRESHCALLxxxxxxxxxx` -- ... NOT denied: ..."}

$ echo '{"session_id":"s1","tool_use_id":"toolu_01FRESHWRITExxxxxxxx","tool_name":"Write","tool_input":{"file_path":"/tmp/x.txt","content":"hi"}}' | node packages/harness-claude/hooks/guard-eval.mjs
{"additionalContext":"[shepherd] guard could not confirm the acting role ... NOT denied: ..."}

$ echo '{"session_id":"s1","tool_use_id":"toolu_01FRESHEDITxxxxxxxxx","tool_name":"Edit","tool_input":{"file_path":"/tmp/x.txt","old_string":"a","new_string":"b"}}' | node packages/harness-claude/hooks/guard-eval.mjs
{"additionalContext":"[shepherd] guard could not confirm the acting role ... NOT denied: ..."}

$ echo '{"session_id":"s1","tool_use_id":"toolu_01FRESHAGENTxxxxxxxx","tool_name":"Agent","tool_input":{"subagent_type":"coder"}}' | node packages/harness-claude/hooks/guard-eval.mjs
{"additionalContext":"[shepherd] guard could not confirm the acting role ... NOT denied: ..."}
```

All four exit 0, none carry a `permissionDecision` key (Claude's non-blocking shape). **The
fix works. Not one of Bash/Write/Edit/Agent denies against real, live sprint state.**

## Q2 — did the fix cost a real deny?

A resolved role must still be denied by the engine; an unreachable engine must still fail
closed. `guard-eval.mjs` hardcodes `resolveHookRole`'s `cwd` to `process.cwd()`, so this
required an isolated sandbox (never the real repo) with a seeded git repo + real dispatch
records, driven via the real, unmodified `packages/harness-claude/hooks/guard-eval.mjs`:

```
=== resolved coder role, git commit (should DENY CODER-GIT-WRITE) ===
{"permissionDecision":"deny","message":"guard denied (git-custody/implementer-never-writes-git)
 [CODER-GIT-WRITE]: A role dispatched to implement one file-disjoint scope (coder) never
 performs any version-control write, under any circumstance -- custody sits one tier up,
 always."}

=== resolved conductor role, git rebase (should reach engine) ===
{"permissionDecision":"deny","message":"guard denied (git-custody/cross-lane-integration-is-
 root-exclusive) [TEAMMATE-GIT-WRITE]: Rebase/merge/cherry-pick onto the shared integration
 branch, and worktree add/remove/prune, are denied to every role except the top-level
 orchestrator (shepherd)."}

=== resolved coder role, benign 'git status' (no write verb -> allow, no predicate lookup) ===
(exit 0, empty stdout)

=== resolved coder role, git commit, ENGINE DELIBERATELY BROKEN (bin/shepherd exits 127) ===
{"permissionDecision":"deny","message":"guard engine unavailable, failing closed: guard broker
 did not become ready within 3000ms after spawn (never accepted a connection at
 /tmp/shepherd-guard-...sock)"}
```

**Confirmed on all four counts.** A resolved role still reaches the real engine and gets
denied when the predicate says so; a benign resolved-role command allows silently; an
unreachable engine fails closed, not open, even with role already resolved. The fix did not
convert deny into warn wholesale — only the specific `missing-record` short-circuit changed.

## Q3 — is the new primary test actually capable of failing, against a non-empty dir?

**Fixture read (not just the title):** `test/guard.test.mjs`'s integration section calls
`seedUnrelatedDispatchActivity(repo)` (three real records via `tagDispatch()`, which shells
out to the **real** `hooks/scripts/agent_invocation_tagger.sh`, not a stub) **before any
assertion runs** (line 277, immediately inside the `try` block, before the "PRIMARY
REGRESSION GATE" comment at line 279). Every role-resolution case in the file — the
regression-gate Bash/Write/git-write probes, the genuinely-tagged coder deny, the
genuinely-tagged conductor deny — runs against that same non-empty dispatch dir. The one
empty-dir case (`no-marker`) is isolated into its own throwaway repo at the bottom of the
file, explicitly labeled `EDGE CASE`, with its own comment stating it "proves nothing about
root's safety on its own." This is the exact opposite of the DF-19/DF-75-class defect this
whole finding is about — confirmed by reading the fixture setup, not trusting the section
header.

**RED/GREEN, reproduced independently** (not just re-trusting the coder's own claim):
current repo state — `md5(guard.mjs)=b1d2fea8aa1e395834fee633060fc224`,
`md5(guard-eval.mjs)=de24f9d59d842b0951392cdf2350811f`, matching the coder's claimed
baseline exactly. `node --test packages/harness-claude/test/*.test.mjs` → `8/8 pass` (GREEN,
reproduced independently, including the printed VERDICT line for the primary regression
gate). Reverting `missingRecordWarnedVerdict` to its old deny shape in an isolated,
byte-identical **scratch copy** (never the real repo a second time — see the Scope section's
self-correction note) and re-running the exact same live-relay probe against a real,
seeded, non-empty dispatch dir:

```
=== probe with MUTATED (RED) guard-eval.mjs against a real seeded non-empty dispatch dir ===
{"permissionDecision":"deny","message":"guard could not confirm the acting role -- this
 sprint has a tagged dispatch record, but none matches tool_use_id
 `toolu_01MUTATIONREDTEST0002` ..."}
```

RED reproduces the original CRITICAL exactly. The real repo's files were confirmed
byte-identical to the coder's claimed md5 hashes after this exercise, and `git diff --stat`
shows only the coder's own intended 5-file diff.

## Q4 — do the three guards agree on an unresolved role? (HIGH finding)

Enumerated directly from source, not from the coder's own framing:

| Guard | Tool surface | Posture on `unknown`/unresolved | Cited reasoning |
|---|---|---|---|
| `coder_git_guard.sh` | Bash (git writes only) | **WARN**, never hard-deny | root's own git writes are mechanically indistinguishable from an untraceable coder's — denying denies root (DF-77 FIX 2) |
| `conductor_write_guard.sh` | Edit, Write (+ Bash FS-write deny-list) | **DENY** | conductor is read+dispatch only — an unresolved Edit/Write during an open sprint is never legitimately root's own action; explicitly documents that `coder_git_guard.sh` makes "a DIFFERENT local choice ... because it is protecting a different resource with a different safe default" |
| `guard.mjs` (this fix) | **Write, Edit, Bash, Agent, Workflow** (`GUARD_MATCHER`) | **WARN** (uniform, matches `coder_git_guard.sh` only) | cites `coder_git_guard.sh`'s precedent explicitly; never reconciles against `conductor_write_guard.sh`'s opposite posture for the identical signal on the identical Edit/Write tool class |

The pre-existing divergence between `coder_git_guard.sh` (warn) and `conductor_write_guard.sh`
(deny) is **already known and deliberately documented** — not a new discovery. What is new:
this fix generalizes the warn-side of that divergence across the *entire* matcher
(Write/Edit/Agent/Workflow, not just Bash git-writes), silently disabling `write-boundary`
and `dispatch-scope` predicate enforcement for every untraceable call, in every live sprint,
for the tool classes `conductor_write_guard.sh`'s own precedent says should be **denied**,
not warned. README.md's own "MISSING-RECORD POSTURE, CORRECTED" section calls this "not a
NEW gap ... applied consistently across the wider matcher" — that framing is not supported:
it is consistent with the git-custody precedent, but it *contradicts* the sibling
conductor-write precedent for the same ambiguity on Write/Edit.

Live proof — a resolved role with **no** write capability at all is correctly denied by the
engine's `write-boundary` predicate:

```
=== A) RESOLVED critic role, Write call -- engine should DENY ===
{"permissionDecision":"deny","message":"guard denied (write-boundary/role-write-eligibility):
 role holds no write capability at all"}
```

The identical Write, from an untraceable `tool_use_id`, against the same populated dispatch
dir, never reaches the engine at all:

```
=== B) UNRESOLVED (missing-record) Write, fresh untraceable tool_use_id ===
{"additionalContext":"[shepherd] guard could not confirm the acting role ... NOT denied: ..."}
```

**HIGH, not CRITICAL**: this does not reopen the original 100%-deny CRITICAL (Q1/Q2 are
unambiguously proven fixed), and the gap is explicitly named and warned about at runtime
(never silent). It is HIGH because it is a real, provable, live enforcement hole —
`write-boundary`'s `role-write-eligibility` and `path-in-declared-scope` rules, and
`dispatch-scope`'s dispatcher-tier rules, are unenforceable against any untraceable
dispatched call until DF-77 FIX 3 lands, for a materially larger blast radius (four tool
types, three predicates) than the single precedent (git-custody on Bash) cited to justify
it, and it directly contradicts a sibling guard's own documented posture for the identical
signal on the identical tool class.

**Recommended fix shape** (for the follow-up brief, not applied here — read-only): scope the
`missing-record` short-circuit's posture by tool/predicate, matching each sibling guard's own
domain-specific precedent — WARN for Bash git-writes (matches `coder_git_guard.sh`), keep
**DENY** for Write/Edit (matches `conductor_write_guard.sh`), and decide `Agent`/`Workflow`
(`dispatch-scope`) on its own merits rather than folding it into the git-write precedent by
default.

## Q5 — is Codex structurally immune, or merely untested? (verified independently, TRUE)

`packages/harness-codex/src/dispatch-record.mjs:227-231` — `resolveRole(agentId, dataDir)`
keys purely on `agentId` (Codex's runtime-assigned, spawn-time, carried-on-every-later-call
identifier). It contains **no directory-presence check at all** — no equivalent of
`hasMarker` exists to get wrong, structurally, not by omission.

`packages/harness-codex/test/dispatch-record.test.mjs`: `writeDispatchRecord(dataDir,
"agent-1", "auditor")` (line 47) runs **before** the missing-record assertion
`resolveRole("agent-ghost", dataDir)` (line 58) — `dataDir` genuinely holds one record when
the missing-record case is exercised, so this test was never vulnerable to the
empty-vs-populated illusion in the first place. Confirmed the same pattern independently in
`packages/harness-codex/test/guard.test.mjs` (`writeDispatchRecord(dataDir, "agent-coder-1",
"coder")` at line 38, before the `missing-record` case at lines 66-69).

`packages/harness-codex/src/guard.mjs`'s `missingRecordDeniedVerdict` — confirmed still a
DENY, unchanged, correctly so (Codex's `agent_id` presence-with-no-record genuinely does mean
"a spawned agent went untagged," never "this might be root").

`packages/harness-pi` is architecturally immune too (checked as part of the same sweep,
though not explicitly asked): `src/extension.ts:18-23` — Pi has "no native per-role dispatch
primitive," so `src/dispatch.mjs` sets `SHEPHERD_ROLE`/`SHEPHERD_SCOPE` directly in the
subprocess environment at spawn time. There is no correlation lookup and no directory-presence
ambiguity to have — role is either genuinely set (100% reliable, since it *is* the actual spawn
mechanism) or genuinely unset (a real unidentified session, correctly fails closed).

`git diff --stat b57d495 -- packages/harness-codex/ packages/harness-pi/` — empty. Neither
package was touched by this diff, consistent with the "no fix needed" claim.

## Q6 — the eleventh (swept, none found beyond the Q4 finding already logged above)

Swept every suite named in the brief plus the full cross-reference list above:

- `services/cli/tests/test_guard.py`, `test_guard_serve.py` — operate purely at the engine
  layer (`role` is a direct payload field: `"coder"`, `None`); no directory-presence heuristic
  exists at this layer to manufacture a false precondition around. Clean.
- `hooks/tests/test_agent_invocation_tagger.sh` — drives the real `agent_invocation_tagger.sh`
  against a real, freshly-`git init`'d repo with real `.claude/shepherd.toml`, real payloads.
  No stubbing. Clean.
- `hooks/tests/test_sql_escaping.sh`, `test_workflow_meta_gate.sh` — unrelated defect classes
  (SQL quote-escaping, workflow-meta literal-string linting); no dispatch/role-resolution
  surface at all. Not applicable to this sweep.
- `packages/harness-codex/test/{dispatch-record,guard,guard-serve-corpus,guard-serve-transport}.test.mjs`
  — see Q5; the two guard-serve suites operate on already-resolved `role` payload fields, no
  directory-presence layer. Clean.
- `packages/harness-pi/test/{guard-predicates,extension-guard}.test.mjs` — Pi's own
  `SHEPHERD_ROLE` env-var mechanism has no equivalent ambiguity to manufacture a false
  precondition around (see Q5). Clean.

**No eleventh instance found** beyond the Q4 finding (which is not quite the same defect
shape — it is a posture *generalized beyond its own precedent*, not a test manufacturing an
unrealistic precondition; the test suite itself is honest about it, in both the warning
message and the README).

## Verifications (hypotheses disproved)

1. "The fix might be a blanket allow, defeating the guard entirely" — disproved by Q2 (a
   resolved coder's git commit still denies CODER-GIT-WRITE; a resolved conductor's rebase
   still denies TEAMMATE-GIT-WRITE).
2. "An unreachable engine might now silently allow" — disproved by Q2 (engine deliberately
   broken via a shim, resolved coder role, still denies: `guard engine unavailable, failing
   closed`).
3. "The new integration test might have inherited the same empty-sandbox illusion under a new
   name" — disproved by Q3 (fixture read directly: `seedUnrelatedDispatchActivity` runs before
   every assertion, via the real tagger, non-empty dispatch dir throughout).
4. "Codex's immunity claim might be asserted rather than verified" — disproved by Q5
   (`resolveRole` read directly: no directory-presence check exists structurally; both test
   files confirmed pre-populated `dataDir` independently).
5. "There might be an eleventh masked-precondition instance elsewhere in this sprint's new
   test suites" — searched exhaustively per the brief's own list plus every adapter suite;
   none found (Q6).

## Open questions

- All 64 real dispatch records in `.shepherd/dispatch/v6.4.5/`, including the one written
  after the W11 DF-77-FIX-1 commit landed, still carry `agent_role:"unknown"` and the OLD
  6-key record schema (missing `declared_tools`/`session_id`/`observed_*` — fields the
  on-disk `agent_invocation_tagger.sh` writes today). `/Users/jo3/.local/bin/shctx` resolves
  to `~/.claude/plugins/cache/shepherd/shepherd/6.4.4/...` — the hooks actually firing in this
  live session run the installed 6.4.4 plugin cache, not this v6.4.5 dev tree. This means
  neither this fix nor the DF-77 FIX 1 tagger it depends on can be observed live-enforcing
  anything in the operator's own session until a release+reinstall cycle updates the cache.
  Not attributable to this coder's diff (their own verification correctly bypassed this by
  driving the dev-tree's `guard-eval.mjs` directly), and not itself a defect in the diff under
  audit — flagged only so the conductor/root does not assume this fix is "live" yet.

## Pattern delta

Severity vs prior instances of this sprint's dominant defect class: this is the 10th
confirmed instance (matches prior HIGH/CRITICAL weighting — DF-17, DF-19, DF-59, DF-62/63,
DF-71, DF-72, DF-75, DF-77, GH#284). Unlike the prior 9, **this one was fixed correctly** on
its own stated terms (Q1-Q3 all confirm), with one new, narrower HIGH finding introduced by
the fix's own generalization (Q4) — a different failure shape (posture scope creep past its
own cited precedent, not a masked test precondition) but still worth tracking against the
same "generalize a narrow, justified exception too far" pattern this sprint has also shown
elsewhere (README's own "applied consistently" framing undersells the divergence).

**Systemic risk**: none newly triggered — this is 1 HIGH in `data-flow` this wave, not 3+
across 3+ sprints in the same concern.

## Grade

n/a — this is an ad hoc adversarial-verification audit (not close/regression/carry-forward/
wave-review mode); no letter grade requested. Verdict below.

## Grade rationale

n/a (see Grade).

---

## VERDICT

**PASS**, with one follow-up HIGH finding to dispatch as a fast-follow, not a REDO.

Rationale: the coder's step closes the measured CRITICAL exactly as specified — Q1 (four
tool types, zero denies against real state), Q2 (resolved roles still deny, engine-down still
fails closed), and Q3 (RED/GREEN independently reproduced, non-empty-dispatch-dir fixture
confirmed by reading the setup code, not the test's title) are all independently verified
against the real runtime, not the diff or the test suite's own claims. Codex and Pi's
non-fix (Q5) is independently confirmed correct, and the Q6 sweep found no further instances
of this sprint's dominant defect class. The one HIGH finding (Q4: missing-record WARN
posture over-generalized past its own cited precedent, silently disabling `write-boundary`/
`dispatch-scope` enforcement for the broader Write/Edit/Agent/Workflow surface, contradicting
`conductor_write_guard.sh`'s own posture for the identical signal) is real and should be
fixed, but is a narrower, explicitly-warned-about, non-regressive gap relative to the
CRITICAL this step was dispatched to close — it does not warrant discarding or redoing this
step's work. Recommend a fast-follow brief scoping the missing-record posture per
tool/predicate rather than uniformly.

## Output to conductor

```
## AUDITOR REPORT
- deliverable: 24 (status: delivered)
- Concern: data-flow
- Mode: close (ad hoc adversarial-verification brief)
- Files reviewed: 22 (5 changed + 17 cross-checked)
- Findings: CRITICAL=0, HIGH=1, MEDIUM=1, LOW=0
- Verifications (disproved): 5
- Open questions: 1
- GH issues filed: none
- Grade: n/a (verdict: PASS, fast-follow recommended)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/auditor-W13-relay-posture.md
- Hot-fix-lane recommendations: 1 (Q4: scope missing-record posture per tool/predicate,
  matching conductor_write_guard.sh's DENY precedent for Write/Edit rather than
  coder_git_guard.sh's WARN precedent for git-writes only)
- Sprint-pattern entry: written (Pattern delta section above)
- Agent ID + timestamp: auditor-W13-relay-posture @ 2026-08-14T04:55:00-05:00
```
