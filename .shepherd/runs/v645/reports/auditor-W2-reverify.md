---
title: Central re-verification audit — W2 Wave 2 REDOs (W2-S1 minijinja + l6 sql_lit)
date: 2026-08-13
auditor: shepherd:auditor
sprint: v645
concern: regression-reverify (central re-verification of two REDOs, read-only, build-permitted)
mode: close (single central re-verify pass)
methodology: superpowers:systematic-debugging (falsify, don't confirm) — every claim below is
  backed by a command I ran myself in this session (not by re-reading the coder/auditor reports'
  self-described outcomes), including two from-scratch mutation-testing rigs built independently
  of the ones the original coder/auditor reports describe.
deliverable: 10 (status: delivered)
---

## Scope reviewed

- `/Users/jo3/src/fl03/shepherd` (primary checkout, branch `v6.4.5`, HEAD
  `e7358a0d82aa1d70ea0d22829b67b0d6e95dd2bd`, no worktree): `crates/render/src/env.rs`,
  `crates/render/src/filters.rs`, `crates/render/src/manifest.rs`, `crates/render/Cargo.toml`,
  `crates/render/src/lib.rs`, `Cargo.lock`. `git status --short` at session start confirmed
  exactly these paths (+2 new report files) changed/untracked.
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards` (branch `agent-v645-l6-guards`, HEAD
  `ada05dd3b749956e4aeeaf8bf2eedc1ca5b14930`, uncommitted, read via `git -C ... diff`/`status`
  only — never entered as `cwd`, per the read-only mandate): `hooks/scripts/dispatch_guard.sh`,
  `hooks/tests/test_dispatch_guard.sh`, `skills/context/scripts/cmd_teammate.sh`,
  `skills/context/tests/test_cmd_teammate.sh`.
- `df-guard.sh --min=12` passed before every cargo invocation (13Gi → 12Gi minimum maintained
  throughout; scratch `target/` dirs deleted after use to reclaim disk, confirmed back to 13Gi
  available at the end).

## VERDICT summary

| Item | Verdict | Blocking? |
|---|---|---|
| A. W2-S1 minijinja/tojson fix | **PASS** | — |
| B. l6 `sql_lit()` fix | **PASS** | — |
| C. Regression check (Check 6/7/8 ordering, manifest.rs unchanged) | **PASS** | — |

**No blocking items remain in either REDO.** Both are independently re-verified by direct
execution, not by trusting the coder/auditor reports' self-described outcomes.

---

## A. W2-S1 (`crates/render`) — PASS

### A1. Both mandated cargo commands, run serially, exit code read from a file (never a pipe)

```
$ CARGO_TARGET_DIR=target/.central cargo test -p shepherd-render > .../test-default.log 2>&1
$ echo "ACTUAL_EXIT: $?" >> .../test-default.log
...
test env::tests::matches_python_settings ... ok
test result: ok. 1 passed; 0 failed
     Running tests/default.rs ...
test provenance_hashing_is_sha256_over_raw_bytes ... ok
test rendering_is_reproducible ... ok
test result: ok. 2 passed; 0 failed
ACTUAL_EXIT: 0
```

```
$ CARGO_TARGET_DIR=target/.central cargo test -p shepherd-render --features full > .../test-full.log 2>&1
$ echo "ACTUAL_EXIT: $?" >> .../test-full.log
...
running 7 tests
test env::tests::matches_python_settings ... ok
test filters::tests::sorted_tojson_key_order ... ok
test manifest::tests::undefined_variable_is_hard_error ... ok
test manifest::tests::digests_reproduce ... ok
test filters::tests::negative_control_builtin_tojson_diverges ... ok
test manifest::tests::vars_digest_is_order_independent ... ok
test env::tests::end_to_end_matches_python_corpus ... ok
test result: ok. 7 passed; 0 failed
     Running tests/default.rs ...
test result: ok. 2 passed; 0 failed
ACTUAL_EXIT: 0
```

Both exit 0. `filters::tests::negative_control_builtin_tojson_diverges` — the specific test
`auditor-W2-central-verify.md` FINDING 1 reported failing with `ErrorKind::UnknownFilter` (exit
101) — now passes on the `full` leg. This reproduces the coder's own claimed result
independently (I ran the commands myself, not trusted the coder's log).

### A2. "Does the code now agree with the docs?" — verified empirically, not by reading the comment

`env.rs`'s rewritten doc block claims: under `json`/`full`, minijinja's builtin `tojson` and this
crate's `sorted_tojson` override both compile in (override wins); under bare `default`, **both**
compile out together and the `Environment` has **no** `tojson` filter at all (hard
`ErrorKind::UnknownFilter`, no degraded fallback).

I did not trust this claim by reading it — I built two standalone scratch binaries (outside
`crates/render`, so no source edit) that depend on `shepherd-render` via a path dependency and
call `shepherd_render::env::build()` directly:

**Probe 1 — default features (no `json`):**
```rust
let env = shepherd_render::env::build();
let result = env.template_from_str("{{ value | tojson }}").unwrap().render(&ctx);
```
```
$ cargo run   # shepherd-render default-features=false, features=["std"]
RENDERED_ERR: kind=UnknownFilter detail=unknown filter: filter tojson is unknown (in <string>:1)
```
Confirms: under bare `default`, there is genuinely **no** `tojson` filter, builtin or override —
exactly as the doc now claims, not a comment I merely read.

**Probe 2 — `full` feature:**
```
$ cargo run   # shepherd-render default-features=false, features=["full"]
RENDERED_OK: {"a": "x", "b": 1}
```
Sorted-key, non-HTML-escaped output — our override, confirmed live, not via the crate's own test.

### A3. Negative control genuinely falsifiable — proved by mutation on an isolated mirror

Built a self-contained ad-hoc Cargo workspace in scratch (copies of `crates/render` +
`crates/core`, symlinked to the real `services/cli/shepherd_cli/templates/` for the
`include_str!` corpus — read-only reference, never a source edit) so the real checkout was never
touched:

1. Baseline: mirror matches real source byte-for-byte (`diff` confirmed) — full-feature suite
   passes 7/7 (same as A1).
2. **Removed the override registration** (`env.add_filter("tojson", ...)` commented out) in the
   mirror only:
   ```
   test filters::tests::sorted_tojson_key_order ... FAILED
   test env::tests::end_to_end_matches_python_corpus ... FAILED
   test filters::tests::negative_control_builtin_tojson_diverges ... FAILED
     assertion `left != right` failed: builtin tojson ... must diverge ...
     left:  "{\"a\":\"R\\u0026D...\",\"b\":1}"
     right: "{\"a\":\"R\\u0026D...\",\"b\":1}"    <- IDENTICAL, proving the assert_ne! is load-bearing
   test result: FAILED. 4 passed; 3 failed
   ```
   The negative control itself flips from pass to fail, and the failure is exactly "both sides
   now render the same builtin output" — the precise condition the test exists to catch.
3. **Restored** the mirror's `env.rs` to a byte-identical copy of the real source (`diff` confirmed
   zero difference) and reran: 7/7 pass again, `ACTUAL_EXIT: 0`.

This closes the audit brief's specific ask: "confirm the negative control is genuinely
falsifiable: remove the override, watch it fail, restore it." Done, on an isolated mirror, real
checkout never touched (`git status --short` before/after this mutation shows the same 8 paths,
unchanged).

### A4. LOC delta

```
$ python3 scripts/loc-count.py HEAD crates/render
+10/-0  crates/render/src/lib.rs
+88/-0  src/env.rs
+131/-0 src/filters.rs
+116/-0 src/manifest.rs
TOTAL: +345/-0 (net 345)
```
Matches the coder-W2-S1-redo report's claimed numbers exactly.

### A5. `manifest.rs` (W2-S2) unchanged, corroborated two ways

- Content read in full: structurally identical to what `auditor-W2-central-verify.md`'s
  Verifications section describes (digest triad, canonicalization via `serde_json::to_vec`,
  `undefined_variable_is_hard_error`), and its 3 tests still pass in the full-feature run above.
- `stat -f "%Sm"` mtimes: `manifest.rs` last modified `15:28:33`, while `env.rs`/`filters.rs`/
  `Cargo.toml` (the files this redo touched) were last modified `15:41:00`–`15:42:28` — mtimes
  are consistent with manifest.rs predating and being untouched by this redo, corroborating (not
  proving, since the file is untracked/no git history to diff against) the coder's `git status`
  claim.

**Item A verdict: PASS.** Both mandated commands exit 0; the negative control is proved
falsifiable by an independent from-scratch mutation (not the coder's own mutation, a fresh one I
built); the code-vs-docs claim is verified by direct execution against the compiled artifact, not
by reading a comment; `manifest.rs` is corroborated unchanged.

---

## B. l6 `sql_lit()` fix (`.worktrees/v645-l6-guards`, uncommitted) — PASS

### B1. Scope discipline — confirmed by execution, not by trusting the coder report

```
$ git -C .worktrees/v645-l6-guards log --oneline -1
ada05dd chore(v645): DF-41 CRITICAL — both Wave-1 acceptance predicates verify nothing
```
Unchanged from the expected base commit — **no commit was made**, confirming `CODER-GIT-WRITE`
discipline held.

```
$ git -C .worktrees/v645-l6-guards diff --raw
:100755 100755 fe831a3 0000000 M  hooks/scripts/dispatch_guard.sh
:100755 100755 e21ccd1 0000000 M  hooks/tests/test_dispatch_guard.sh
:100755 100755 0b2b7ea 0000000 M  skills/context/scripts/cmd_teammate.sh
:100755 100755 d888a37 0000000 M  skills/context/tests/test_cmd_teammate.sh
```
`cmd_teammate.sh`'s mode is `100755 → 100755` (no delta from HEAD) — the executable-bit
regression `auditor-W2-guard-fail-closed.md` FINDING 2 flagged (`100755→100644`) is fixed;
`ls -la` confirms `-rwxr-xr-x`. Content of `cmd_teammate.sh`/its test is the pre-existing 4-branch
unbound-`$1` fix (the same fix the original audit's own Q4 mutation section describes reverting
and re-catching) — consistent with the redo coder's claim of read-only access to that file in
this REDO.

**Minor discrepancy noted, non-blocking (recorded as `audit_findings` row 42, LOW):** the
original audit's own "Scope reviewed" section cites `cmd_teammate.sh` as `+12/-7`; `git diff
--numstat` here shows `8 4` (4 hunks × 1 deletion + 2 insertions = 8 insertions, 4 deletions).
Content is verified correct and matches the described fix exactly — this is a citation-accuracy
nit in the *original* audit's own report text, not a functional defect in the redo.

### B2. Apostrophe round-trip — driven against the REAL worktree script with fresh crafted stdin, independent of the coder's own added test

Built my own ephemeral git repo + `.claude/shepherd.toml`, piped a JSON payload (built with
`python3 json.dumps`, not hand-quoted, to rule out shell-quoting artifacts) directly at
`hooks/scripts/dispatch_guard.sh` in the real worktree:

```
$ printf '%s' '{"session_id": "sA-o'"'"'brien", ..., "tool_input": {"subagent_type": "shepherd:coder", "model": "claude-o'"'"'brien-sonnet", ...}}' \
  | bash .worktrees/v645-l6-guards/hooks/scripts/dispatch_guard.sh
(no deny — silent pass)
$ sqlite3 -separator '|' <tmpns>/.shepherd/shepherd.db "SELECT session_id, subagent_type, model FROM dispatch_ownership;"
sA-o'brien|shepherd:coder|claude-o'brien-sonnet
```
The row exists and both apostrophe-bearing fields (`session_id`, `model`) round-tripped **exactly
intact** — not merely "the guard didn't deny" (which, per the brief, proves nothing, since Check
8 never denies). This directly answers the brief's core ask.

### B3. Adversarial DROP-TABLE-shaped input — confirmed inert, table intact

```
$ printf '%s' '{"session_id": "s-drop'"'"'; DROP TABLE dispatch_ownership; --", ...}' \
  | bash dispatch_guard.sh
(no deny)
$ sqlite3 <tmpns>/.shepherd/shepherd.db ".tables"
dispatch_ownership          <- table survives
$ sqlite3 <tmpns>/.shepherd/shepherd.db "SELECT COUNT(*) FROM dispatch_ownership;"
2                            <- both this row and B2's row present, no extras, no loss
$ sqlite3 <tmpns>/.shepherd/shepherd.db "SELECT session_id FROM dispatch_ownership;"
sA-o'brien
s-drop'; DROP TABLE dispatch_ownership; --
```
The adversarial string is stored as an inert literal, exactly as supplied — no injection, no row
loss, no crash.

### B4. Real test suite, exit code and pass count read directly

```
$ bash .worktrees/v645-l6-guards/hooks/tests/test_dispatch_guard.sh
...
test_dispatch_guard: OK — #89 inversions + dispatch-class #66 violations mechanically blocked; clean dispatches pass
```
`grep -c "^  PASS"` → **61**. `grep -c "^  FAIL"` → **0**. `$? ` → **0**. Matches the coder
report's claimed `61/61 PASS, exit 0` exactly, independently re-run.

### B5. New apostrophe test genuinely falsifiable — proved by an independent mutation rig (mirror, not the coder's own scratch)

Mirrored `dispatch_guard.sh`/`_lib.sh`/`bash_guard.sh`/`test_dispatch_guard.sh` into a fresh
scratch dir (never touching the real worktree):

1. Baseline mirror: 61/61 PASS, exit 0.
2. Mutated **only the mirror's** `sql_lit()` back to the original broken
   `printf "'%s'" "${v//\'/\'\'}"`:
   ```
   FAIL  RECORD Check 8: apostrophe-bearing row did not round-trip (want s-apos-o'brien|claude-o'brien-sonnet, got: <no row>)
   FAIL  RECORD Check 8: DROP-TABLE-shaped session_id mishandled (want ... count 1, got: <no row> / count 0)
   59 PASS / 2 FAIL, exit 1
   ```
   Exactly 2 of 61 fail — both, and only, the two new DB-record assertions. The corresponding
   `expect_pass` (never-denies) assertions for the same two fixtures **still pass** on the
   mutant — direct, independently-reproduced confirmation that a non-deny-only assertion cannot
   catch this defect class, and that the new RECORD assertions are what gives it teeth.
3. `diff` against the real worktree file confirms the real file was never touched throughout;
   `git -C .worktrees/v645-l6-guards diff --stat` and `log --oneline -1` unchanged before/after.

**Item B verdict: PASS.** The fix is verified correct by direct execution against the real
script with independently-crafted stdin (not the coder's own test), the DB row is confirmed
round-tripped exactly (not just "didn't deny"), adversarial input is confirmed inert, the real
suite is 61/61 PASS exit 0, and falsifiability is proved by an independent mutation rig, not by
re-reading the coder's own mutation-testing narrative.

---

## C. Regression check — PASS

### C1. Check 6 still does not pre-empt Checks 7/8 in `.worktrees` topology

Physical layout, re-confirmed by `grep -n`: Check 7 at line 275, Check 8 at line 314, Check 6 at
line 449 — Check 6 still sits after 7/8.

**Live proof**, driven with a fresh crafted payload (not reused from either prior report) against
the real worktree script, `cwd` set to a `.worktrees/lane-a`-shaped path:

```
$ printf '%s' '{"session_id":"sA","cwd":"<tmp>/.worktrees/lane-a","tool_name":"Agent",
  "tool_input":{"subagent_type":"shepherd:auditor","prompt":"Review the auth module and also the DB migration and also the frontend routing."}}' \
  | bash dispatch_guard.sh
{"permissionDecision":"deny","message":"[shepherd] AUDIT-CONCERN-UNDECLARED — refused. ..."}
```
Correctly denied by Check 7, not silently absorbed by Check 6's weaker `PRIMITIVE-INVERSION`
flag.

**Mutation proof**, built independently (not the original audit's mutation, a fresh one): copied
`dispatch_guard.sh` into scratch, physically moved the Check 6 block (lines 448–495) to before
Check 7 (line 274) — the exact pre-fix ordering — via a scripted line-range move (not hand-edited,
to avoid transcription risk), confirmed `bash -n` syntax-valid, then ran the real test suite
against the mutant:

```
FAIL  BLOCK  Check 7 (teammate .worktrees cwd, #93 topology): bundled multi-topic prompt, zero [CONCERN]
  (expected deny+AUDIT-CONCERN-UNDECLARED, got: {"additionalContext":"[shepherd] PRIMITIVE-INVERSION (flag) ...")
FAIL  RECORD Check 8 (teammate .worktrees cwd): no matching row ...
59 PASS / 2 FAIL, exit 1
```
Exactly 2 of 61 assertions fail — both, and only, the two `.worktrees`-cwd topology-specific
fixtures — byte-for-byte reproducing the exact regression class this wave exists to have fixed.
All 59 other assertions, including the root-topology Check 7/8 fixtures, still pass on the
mutant. Real worktree file confirmed untouched throughout (`diff` against the mutant shows the
real file still contains the fixed ordering; `git diff --stat`/`log --oneline -1` unchanged).

### C2. W2-S2's `manifest.rs` unchanged

See A5 above — corroborated via content read + mtime + the coder report's own `git status`
claim + all 3 of its tests still passing identically in this session's own `--features full` run.

**Item C verdict: PASS.**

---

## Non-blocking, informational (out of this reverify's blocking scope)

- `audit_findings` row 42 (LOW): original audit's own cited diff-stat for `cmd_teammate.sh`
  (`+12/-7`) does not match `git diff --numstat` (`8 4`) — a citation nit in that report's own
  text, content itself verified correct.
- FINDING 2 (MEDIUM, non-blocking) from `auditor-W2-central-verify.md` — the cross-crate
  duplicated JSON-tree-writer shape between `crates/core::run::canonical` and
  `crates/render::filters` — remains unfixed by design (both steps' `crates/core/**`
  `must_not_touch` blocks the shared-home refactor); the redo coder answered it without fixing,
  as instructed. Still worth a follow-up GH issue for whichever step next touches `crates/core`.
  Not filed here (read-only; issue creation was not requested by this dispatch).
- Pre-existing malformed-JSON fail-open at the top of `dispatch_guard.sh` (confirmed present in
  `HEAD` before either diff, per the original audit) — out of scope for both REDOs, unchanged,
  not re-verified again here since neither REDO touched that code path.
- `clippy --all-targets -D warnings` was not run in this reverify — out of the two-command scope
  the original W2-S1 dispatch specified and not requested by this reverify's brief either; noted
  so it is not silently assumed clean.

## Disk/build discipline

`df-guard.sh --min=12` passed before every cargo invocation. All scratch `CARGO_TARGET_DIR`s
(`target/.central`, the two ad-hoc mutation-mirror workspaces' `target/`, the tojson-probe
`target/`) were deleted after use; `df-guard.sh --min=12` re-confirmed 13Gi available at the end
of this session, up from the 12Gi floor mid-session. No workspace-wide build was ever run; every
cargo invocation used an isolated `CARGO_TARGET_DIR`, serial, no `cargo fix`.

## Output to conductor

```
## AUDITOR REPORT
- deliverable: 10 (status: delivered)
- Concern: regression-reverify (central re-verification of two REDOs)
- Mode: close (single central re-verify pass)
- Files reviewed: 8 (env.rs, filters.rs, manifest.rs, Cargo.toml, lib.rs [primary checkout];
  dispatch_guard.sh, test_dispatch_guard.sh, cmd_teammate.sh + its test [l6 worktree, read-only])
- Findings: CRITICAL=0, HIGH=0, MEDIUM=0, LOW=1 (citation nit in the ORIGINAL audit's own report
  text, non-blocking, recorded as audit_findings row 42)
- Verifications (disproved/confirmed by direct execution): 9 — (A) both mandated cargo test
  commands exit 0; (A) negative control genuinely falsifiable by independent mutation; (A)
  code-vs-docs claim verified by direct probe execution, both feature legs; (A) manifest.rs
  unchanged (mtime + content + passing tests); (B) apostrophe row round-trips exactly via
  independently-crafted stdin; (B) DROP-TABLE-shaped input inert, table intact; (B) real suite
  61/61 PASS exit 0; (B) apostrophe test falsifiable by independent mutation; (C) Check 6 still
  does not pre-empt Check 7/8, live + independent mutation reproduces the exact regression class
- Open questions: 0
- GH issues filed: none (read-only; recommend one follow-up for the FINDING-2 shared-JSON-writer
  duplication once a future step touches crates/core, per the original central-verify audit)
- Grade: n/a (central re-verification pass, not close-mode concern audit)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/auditor-W2-reverify.md
- Hot-fix-lane recommendations: 0 — both REDOs verified clean, no further redo required
- Sprint-pattern entry: written (audit_findings row id 42, concern=regression-reverify,
  severity=low)
- Agent ID + timestamp: shepherd:auditor (W2-reverify, central) @ 2026-08-13T20:53:30Z
```

## VERDICT

**PASS — both REDOs, all three items (A, B, C).** No blocking items remain. Every claim above is
grounded in a command I ran myself this session (fresh crafted stdin, fresh mutation rigs built
independently of the ones the coder/auditor reports describe, direct exit-code capture via file
redirection never a pipe) — not in re-reading or trusting the prior reports' self-described
outcomes. The wave gate may proceed.
