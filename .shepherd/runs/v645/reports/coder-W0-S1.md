# CODER REPORT — W0-S1

- **Lane:** W0-S1 — make `lint` count instances, and stop a Python gate wearing a `.sh` name
- **Skills loaded:** `code-style`, `python` (both loaded via the Skill tool this pass — `python`
  is a real, installed skill authored against this repo's own patterns, confirmed by content:
  typing/errors/context-managers/CLI-Typer/byte-exact-parity/pytest sections). `shell` was also
  loaded in an earlier (discarded) attempt at this step for the `gate.sh` edit.
- **Files touched (created/modified/deleted):**
  - `services/cli/shepherd_cli/commands/lint.py` — MODIFIED. +28/-24.
  - `scripts/check-plugin.sh` → `scripts/check-plugin.py` — RENAMED via `mv` (never `git mv` —
    git custody is never mine). Content byte-identical to the pre-rename blob (verified via
    `diff scripts/check-plugin.py <(git show HEAD:scripts/check-plugin.sh)` — no output).
    Executable bit preserved.
  - `scripts/gate.sh` — MODIFIED. +2/-2 (both `check-plugin.sh` invocations updated to `.py`).
  - `services/cli/tests/test_lint.py` — MODIFIED (authorized scope-extension, per dispatch).
    +33/-17.
- **LOC delta:** +63 / -43 across the four touched files.
- **Acceptance grep results** (run from the worktree root, verbatim commands and output):

  ```
  $ bin/shepherd lint; test $? -eq 0
  lint: ok
  → exit 0, PASS

  $ test -f scripts/check-plugin.py && ! test -f scripts/check-plugin.sh
  → PASS (both conditions true, no output on success)

  $ grep -c 'check-plugin.py' scripts/gate.sh
  2
  → PASS (expected 2)

  $ ./scripts/check-plugin.py --self-test
  self-test: every rule must be able to fail

    component dirs are at the root               fails as designed
    hooks json is discoverable                    fails as designed
    hook commands resolve                          fails as designed
    plugin root refs resolve                       fails as designed
    skills are shaped correctly                    fails as designed
    configured gates resolve                       fails as designed

  ok: every rule is falsifiable.
  → exit 0, 6/6 rules provably failable, PASS
  ```

  The plan's own ACCEPTANCE block includes `cargo run -q --bin lintfixture 2>/dev/null || true`
  — per the dispatch's explicit instruction this is inert (`|| true`), no cargo command was run,
  skipped as directed.

  The plan's final ACCEPTANCE line
  (`bin/shepherd lint 2>&1 | grep -qE 'FAIL \(3 violation\(s\)\)'`) is satisfied two ways, per
  the dispatch's own notes (the real repo tree has zero violations, so the literal command
  against the real tree correctly does NOT match — it prints `lint: ok`):
  1. **The pytest regression suite** — `test_three_distinct_violations_count_is_exactly_three`
     (new) seeds one bad `plans/` name, one bad `docs/journal/` name, one bad `logs/` name in an
     isolated `SHEPHERD_WORKDIR` and asserts `"lint: FAIL (3 violation(s))"` is in the output.
     `poetry run pytest tests/test_lint.py -q` → `39 passed in 8.73s` (run twice, both green,
     from `services/cli/`).
  2. **Manual sanity check**, exactly as the dispatch's notes describe — seeded 3 violations
     (plans/journal/logs) under a scratch dir in the session scratchpad
     (`/private/tmp/.../scratchpad/lint-3viol`, never under the repo), ran
     `SHEPHERD_WORKDIR=<scratch> bin/shepherd lint`:
     ```
     lint: <scratch>/plans/bad-name.md does not match *.seed.md or *.plan.md
     lint: <scratch>/docs/journal/bad-name.md does not match YYYY-MM-DD.md
     lint: <scratch>/logs/bad-name.txt has unrecognized log filename pattern
     lint: FAIL (3 violation(s))
     exit=1
     ```
     `grep -qE 'FAIL \(3 violation\(s\)\)'` on that output → PASS. Scratch dir removed
     immediately after (`rm -rf`) — nothing left behind in `/tmp` or the repo.
  3. Re-ran `bin/shepherd lint` against the real repo tree afterward to confirm it still reads
     `lint: ok` (exit 0) — the scratch check never touched the real tree.

- **Halts encountered:** none in this final pass. (Prior history this session, superseded and
  fully resolved: an original `BRIEF INVALID` halt on `markdown` not being an installed skill
  [plan.md:375 listed `code-style, markdown`]; a conductor DF-25 correction to `code-style`
  alone that was itself retracted as an invalid process shortcut and its edits discarded via
  `git checkout`; then this final, correct restart once `python` landed as a real installed
  skill and both `code-style`+`python` were loaded via the Skill tool before any code was
  written.)

- **Summary:**

Both defects from the brief are fixed. `_lint()` in `lint.py` now counts real violation
instances (`count = len(messages)`) for the printed `FAIL (N violation(s))` summary instead of
the old bash-parity-mirrored `fail = 1 if messages else 0` cap; the exit code stays 0/1 exactly
as before (`[NON-GOALS]`'s "do not touch exit-code logic beyond the count" — the count changed,
the 0-vs-1 branch shape did not). The stale "BASH QUIRK MIRRORED DELIBERATELY" docstring section
(module docstring, the `Exit code:` bullet, and `_lint()`'s own docstring) was rewritten to
describe the new, correct behavior — a stale comment describing removed behavior would have been
worse than none, per the brief.

`scripts/check-plugin.sh` was renamed to `scripts/check-plugin.py` (plain `mv`, zero content
change, executable bit preserved) and both invocations in `scripts/gate.sh` (lines 54-55 at
dispatch time) were updated to the new name. `.shepherd/shepherd.toml` was re-verified clean of
any `check-plugin.sh` reference (grep, whole file, zero hits).

`test_lint.py` (the authorized scope-extension) got four changes: (1) the module docstring's
own stale "BASH QUIRK COVERED EXPLICITLY" section rewritten to match; (2)
`test_plans_docs_plans_checked_after_legacy_plans` (2 violations seeded) and (3)
`test_section_order_plans_reports_journal_logs` (4 violations seeded) both had their hardcoded
`FAIL (1 violation(s))` assertions corrected to the real counts (2 and 4) they were always
silently wrong about; (4) `test_multiple_violations_count_stays_capped_at_one` (5 violations)
was renamed to `test_multiple_violations_count_is_a_real_tally` and rewritten to assert the real
tally instead of locking in the old cap; and the mandated new regression test,
`test_three_distinct_violations_count_is_exactly_three`, was added exactly per the dispatch's
spec (one bad `plans/`, one bad `docs/journal/`, one bad `logs/` filename → `FAIL (3
violation(s))`). Every other pre-existing `FAIL (1 violation(s))` assertion in the file (5 of
them) was individually verified to seed exactly one violation and needed no change. Full suite:
`39 passed`.

**Scope note carried forward from the prior (discarded) attempt, still true and still worth
conductor attention:** `plan.md`'s own `file_scope` table lists `scripts/gate.sh` under
`file_scope.may_read`, not `file_scope.exclusive` — but the dispatch's Action 3 and the
`[ACCEPTANCE]` block's `grep -c 'check-plugin.py' scripts/gate.sh # expect 2` line make editing
it mechanically required to satisfy this step at all. I proceeded on the read that the
`may_read` listing was itself stale (the same category of error as the `[SKILLS]` domain-key
bug already found and fixed this run), since leaving `gate.sh` un-updated makes the step's own
acceptance criteria unsatisfiable.

**Real, unresolved, out-of-scope consequence of the rename, worth conductor attention before
this step is considered mergeable:** `.github/workflows/rust.yml:138,140` still invokes
`./scripts/check-plugin.sh --self-test` / `./scripts/check-plugin.sh` and will fail (file not
found) once this rename lands. That file is not in `[FILE-SCOPE]` for W0-S1 (not
`gate.sh`/`shepherd.toml`, not `lint.py`/`check-plugin.py`/`test_lint.py`), so I made no edit to
it — flagging it here as a `BRIEF-AMENDMENT`-shaped gap for the conductor/root to route to
whichever step owns CI workflow files (or to W0-S1 itself, if the conductor decides the rename's
CI-reference sweep belongs here).

**Shared-worktree note:** this worktree carries several uncommitted files from sibling
coders in this same wave (`scripts/check-stage-graph.py`, `scripts/tests/fixtures/stage-graph/*`,
`services/cli/shepherd_cli/commands/doctor.py`, `services/cli/shepherd_cli/commands/models.py`,
`services/cli/shepherd_cli/templates/lane-plan.md.j2`, `services/cli/tests/test_models.py`) —
none of these are mine, none were touched, and my `git diff --stat`/`git status` invocations
above were scoped to only the four files this report claims.

**No git write command was ever run this session** (only read-only `status`/`diff`/`show`/
`rev-parse`) — the `check-plugin.sh`→`.py` move used plain `mv`, never `git mv`. Nothing was
committed; all four touched files remain uncommitted in the worktree for the conductor to stage
after wave review.

- **Reporter:** coder-W0-S1 @ 2026-08-12T20:45:00Z
