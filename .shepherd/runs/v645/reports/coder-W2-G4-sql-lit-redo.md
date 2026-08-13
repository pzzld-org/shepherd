---
title: REDO — sql_lit() broken quote-doubling (W2, dispatch_guard.sh Check 8)
date: 2026-08-13
coder: shepherd:coder (W2-G4-sql-lit-redo)
sprint: v645
lane: l6-guards
redo_of: auditor-W2-guard-fail-closed.md (Finding 1, HIGH — blocking)
worktree: /Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards (branch agent-v645-l6-guards)
base_commit_verified: ada05dd (HEAD at start, matches expected)
---

## What was wrong

`sql_lit()` at `hooks/scripts/dispatch_guard.sh:340-349` used
`printf "'%s'" "${v//\'/\'\'}"` to escape values before interpolating them into
the SQL Check 8 (`DISPATCH-OWNERSHIP-RECORD`) writes to `dispatch_ownership`.
That bash parameter-expansion form does **not** double a quote — it inserts a
literal backslash ahead of the doubled quote:

```
$ v="o'brien"
$ printf "'%s'" "${v//\'/\'\'}"
'o\'\'brien'          # WRONG — backslash + two quotes, not valid SQL escaping
```

sqlite3 then rejects the resulting `INSERT` (`unrecognized token`), Check 8's
own `elif ! do_err="$(sqlite3 "$do_db" "$do_sql" 2>&1)"` branch fires, and the
dispatch passes with only an `additionalContext` degrade warning — Check 8
never denies by design, so nothing on stdout signals the row was lost. Any
`session_id`/`subagent_type`/`model`/`lane`/`concern_slug` containing an
apostrophe silently failed to be recorded, defeating the forensic
attribution DF-44 exists to provide.

## The fix

Replaced the escaping expression with the same `sed "s/'/''/g"` idiom this
diff's own `skills/context/scripts/cmd_teammate.sh:24` `esc()` already uses
(that file is `must_not_touch` for this REDO — I read it, did not edit it):

```bash
# before
printf "'%s'" "${v//\'/\'\'}"

# after
printf "'%s'" "$(printf '%s' "$v" | sed "s/'/''/g")"
```

**Why the sed idiom is correct where the expansion was not:** `sed
"s/'/''/g"` performs a literal, greedy find-and-replace of every `'` with
`''` (SQL's own quote-escaping rule — a doubled quote inside a quoted string
literal is a literal quote character, not an escape-then-char sequence). It
has no backslash-interpretation step to go wrong. Verified directly against
a real `sqlite3` parser, both plain and adversarial input:

```
$ sqlite3 :memory: "SELECT 'o''brien' AS test;"
o'brien
$ sqlite3 :memory: "SELECT 'a''; DROP TABLE x; --' AS test;"
a'; DROP TABLE x; --
```

Both round-trip to the exact original string, and the DROP-TABLE-shaped
value lands as an inert string value (it is inside a already-closed,
correctly-quoted literal — the parser never sees it as a new statement).
The bash `${v//\'/\'\'}` form fails because its replacement text is a
literal 4-character sequence `\'\'` (backslash, quote, backslash, quote) —
bash param-expansion replacement strings do not "double the quote", they
substitute the literal replacement text verbatim, and a stray backslash in a
SQL string literal is meaningless/invalid there.

Kept `sql_lit()`'s existing contract unchanged (returns a full quoted
literal, or the bare word `NULL` for empty/unset) — only the internal
escaping mechanism changed. Documented the defect and the fix inline in the
function's doc comment so a future reader sees why the sed form is
mandatory, not a style preference.

## Test added

`hooks/tests/test_dispatch_guard.sh`, appended after the existing Check 8
fixtures, two new cases:

1. **Apostrophe round-trip** — `session_id="s-apos-o'brien"`,
   `model="claude-o'brien-sonnet"`. Asserts (a) the guard never denies
   (`expect_pass`, table stakes) AND (b) queries
   `.shepherd/shepherd.db` directly via `sqlite3 -separator '|'
   "SELECT session_id, model FROM dispatch_ownership WHERE
   subagent_type='shepherd:coder';"` and asserts the returned row equals
   `"${APOS_SESSION}|${APOS_MODEL}"` **exactly** — the literal apostrophe,
   not escaped, not dropped, not corrupted.
2. **Adversarial DROP-TABLE-shaped `session_id`** —
   `"s-drop'; DROP TABLE dispatch_ownership; --"`. Asserts the guard never
   denies, the row's `session_id` equals the adversarial string exactly, and
   `SELECT COUNT(*) FROM dispatch_ownership` is exactly `1` — the table
   survives and no extra/missing rows resulted from the payload being
   (mis)parsed as executable SQL.

This directly targets the brief's stated requirement: asserting only "did
not deny/crash" is insufficient because Check 8 never denies regardless of
whether the write succeeded — that non-signal is exactly what let the
original defect ship green. Both new assertions query the DB and check the
exact recorded value, not just the guard's stdout.

### Falsifiability proof (mutation testing, scratch mirror only — real worktree never touched)

Per the shell skill's "a checker that has never been shown to fail is not
known to check anything," I proved the new assertions actually detect the
regression, without ever mutating the real worktree files:

1. Copied `dispatch_guard.sh` + `_lib.sh` + `bash_guard.sh` +
   `test_dispatch_guard.sh` (already containing my fix + new tests) into
   `/private/tmp/.../scratchpad/sql-lit-mutation/`.
2. Ran the scratch suite: **61 PASS, 0 FAIL, exit 0** (baseline green,
   confirms the fix + new tests work together).
3. Mutated **only the scratch copy** of `sql_lit()` back to the original
   broken `${v//\'/\'\'}` expansion (verified via `grep` the mutation
   landed).
4. Reran the scratch suite: **exit 1**, exactly 2 of 61 assertions failed —
   both, and only, the two new record-verification checks:
   ```
   FAIL  RECORD Check 8: apostrophe-bearing row did not round-trip
     (want s-apos-o'brien|claude-o'brien-sonnet, got: <no row>)
   FAIL  RECORD Check 8: DROP-TABLE-shaped session_id mishandled
     (want s-drop'; DROP TABLE dispatch_ownership; -- / count 1,
      got: <no row> / count 0)
   ```
   The corresponding `expect_pass` (never-denies) assertions for both
   fixtures still PASSED on the mutant — direct, reproduced confirmation
   that a non-deny assertion alone cannot catch this class of defect, and
   that the new RECORD assertions are what gives it teeth.
5. Re-verified the real worktree file still contains the fix
   (`grep -n "sed \"s/'/''/g\"" hooks/scripts/dispatch_guard.sh` →
   both the doc-comment mention and the live code line, at 344/357).
6. Ran the real worktree suite one final time (not through a pipe — read
   directly): **61 PASS, 0 FAIL, exit 0.**

## Final suite result (real worktree, not scratch)

```
$ bash /Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards/hooks/tests/test_dispatch_guard.sh
... (61 PASS lines, 0 FAIL) ...
test_dispatch_guard: OK — #89 inversions + dispatch-class #66 violations mechanically blocked; clean dispatches pass
```

Exit code read directly from the command (`bash hooks/tests/test_dispatch_guard.sh` executed standalone, then `$?` inspected immediately — no pipe): **0**.

Count: **61/61 PASS** (57 baseline + 4 new: 2 `expect_pass` + 2 manual
DB-record assertions, from the 2 new fixtures added). No FAIL, no SKIP other
than the pre-existing root-uid skip guard (not triggered in this run).

## Scope discipline

- Touched only `hooks/scripts/dispatch_guard.sh` and
  `hooks/tests/test_dispatch_guard.sh` (the exclusive `[FILE-SCOPE]` for
  this REDO).
- `skills/context/scripts/cmd_teammate.sh` and
  `skills/context/tests/test_cmd_teammate.sh` — read only, never edited.
  Confirmed their executable-bit repair (100755) already landed
  (`git diff --raw` shows `:100755 100755` — no mode delta), consistent
  with root handling that in parallel as stated in the dispatch.
- No git write commands run (`git status`/`diff`/`log`/`rev-parse` only,
  per `CODER-GIT-WRITE`). Worktree left uncommitted, as instructed —
  handoff is this report + the four now-uncommitted files (2 touched by me,
  2 untouched, all still uncommitted from the original wave).
- No `cargo`/build/lint tool run.

## Out of scope — noted, not fixed (per the dispatch, already GH-queued)

- The malformed-JSON fail-open at the top of `dispatch_guard.sh`
  (pre-existing, affects all 8 checks uniformly, present in HEAD before this
  diff) — untouched.
- The identical broken `${v//\'/\'\'}` pattern in
  `skills/context/scripts/cmd_adapt.sh:101` and `cmd_loop.sh:101` — outside
  this REDO's `[FILE-SCOPE]`, untouched. Same root-cause bug as the one
  fixed here; worth the same `esc()`-idiom fix as its own follow-up.

## Files touched

- `hooks/scripts/dispatch_guard.sh` — `sql_lit()` escaping fix + doc comment
  explaining the defect and the fix (net +9 lines vs. the pre-REDO state of
  this diff; file remains executable, mode unchanged).
- `hooks/tests/test_dispatch_guard.sh` — 2 new fixtures + DB-query
  assertions (net +47 lines vs. the pre-REDO state of this diff).

(Both files were already part of a larger uncommitted wave diff against base
commit `ada05dd` before this REDO started — `git diff --stat` against HEAD
therefore shows the whole wave's additions, not just this session's delta;
the deltas above are this session's actual edits, reported precisely since
I authored both edits directly.)

## Halts encountered

None.

## Summary

Fixed the HIGH-severity SQL-literal escaping defect in `sql_lit()` by
replacing the broken bash parameter-expansion doubling with the
already-proven `sed "s/'/''/g"` idiom from this same diff's
`cmd_teammate.sh:esc()`, verified end-to-end against a real `sqlite3` parse
including adversarial input. Added two regression tests that query the
registry DB directly and assert the exact recorded value, not just the
absence of a deny/crash, closing the exact blind spot the audit identified.
Proved the tests are falsifiable via scratch-mirror mutation testing without
ever touching the real worktree files. Final real-worktree suite: 61/61
PASS, exit 0.

- Reporter: shepherd:coder (W2-G4-sql-lit-redo) @ 2026-08-13T15:45:00Z
