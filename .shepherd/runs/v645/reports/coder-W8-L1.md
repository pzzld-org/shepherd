## CODER REPORT

- Lane: W8-L1 (DF-71 CRITICAL — `teammate_git_guard.sh` inert-guard fix)
- Skills loaded: `shell`, `code-style` (no `shell.md` in code-style — applied shared principles)
- Files touched (created/modified/deleted):
  - `hooks/scripts/teammate_git_guard.sh` (modified)
  - `hooks/tests/test_teammate_git_guard.sh` (modified — full restructure)
  - `skills/context/scripts/cmd_teammate.sh` (modified)
- LOC delta (git diff --stat, all shell — the ONE-LOC rule's `*.rs` scope does not
  apply to this lane): `+466 / -115` across the three files (`teammate_git_guard.sh`
  +92/-16 net-of-context lines shown as `92 ++++++-`; `test_teammate_git_guard.sh`
  +459/-... full rewrite; `cmd_teammate.sh` +30`)
- Acceptance grep results:
  - Brief carried no literal `[ACCEPTANCE]` grep list (see BRIEF-SHAPE note below);
    the closest is DF-71's own three named parts. Verified each directly, empirically:
    - (a) "registration without a resolvable session is an ERROR" — PASS. Confirmed
      live: `cmd_teammate.sh register conductor-test --team=team-a --type=conductor
      --pane='%5'` (no `--session`) now exits 1 with `ERR:
      TEAMMATE-SESSION-UNRESOLVED` instead of silently inserting NULL.
    - (b) "worktree add/remove/prune + branch -d/-D added to FORBIDDEN_PATTERN;
      push deleted from stale comment" — PARTIAL-AS-STATED / DONE-AS-NEEDED. See
      the BRIEF-INACCURACY finding below: worktree add/remove/prune was **already**
      wired (verified empirically against `git show HEAD`, before my changes) —
      DF-71's claim that it wasn't is stale. `branch -d/-D/--delete` was the
      genuine gap and is now added and verified DENY (also verified empirically
      against pre-fix `HEAD` — silently PASSED there, now DENIES). The stale
      `push` mention in the `:87` comment is corrected (comment now explains push
      is deliberately excluded, not merely deleted-and-silent).
    - (c) "FAIL CLOSED on an unidentifiable caller, using a signal that actually
      exists at runtime" — PASS. Implemented via the existing, already-live
      `session_tier_marker()` (`hooks/scripts/_lib.sh`), the same signal
      `coordinate_drive_guard.sh` and `conductor_write_guard.sh` already trust for
      the identical root-vs-teammate question. Empirically verified falsifiable
      (see below): DENY on a marked-but-DB-unregistered teammate session;
      unchanged PASS for root/bystander sessions.
  - `hooks/tests/test_teammate_git_guard.sh`: 42/42 passing (ran directly — see
    RESOURCE-DISCIPLINE note below for why this was in-scope to execute).
- Halts encountered: none (no BRIEF INVALID / BASE-DRIFT / CONTEXT-INVENTORY
  STALE / DUPLICATION RISK triggered) — but two findings below are surfaced per
  the halt-adjacent protocols even though they didn't block me from finishing.

### BRIEF-SHAPE note (not a halt)

The pointer `.shepherd/runs/v645/reports/contradiction-ledger.md §W8-L1` does not
contain a `W8-L1` section, nor `[SKILLS]/[CONTEXT-INVENTORY]/[DO-NOT-DUPLICATE]/
[USER-STYLE]/[NON-GOALS]/[ACCEPTANCE]` bracket headers, nor a `[WORKTREE]`/
`[BASE-COMMIT-EXPECTED]` block (verified: `grep -n "W8" contradiction-ledger.md`
→ no hits; the ledger's own Wave-1 table stops at L11 and has no W8 lane at all).
The dispatch prompt itself carried the operative contract instead: `WORK IN`,
`file_scope.exclusive`, and DF-71's row in `dogfood.md` ("read that row ... it is
the contract"). I treated the dispatch prompt + the DF-71 row as the brief per
that explicit instruction, verified `pwd` == `/Users/jo3/src/fl03/shepherd` and
`git rev-parse HEAD` == `df47686` (matches `gitStatus` at session start — no
worktree/base-commit drift), and proceeded rather than halting on a formality,
since the substantive content needed to do correct, scoped work was present and
unambiguous. Flagging this so the conductor can backfill a proper `§W8-L1` ledger
entry for provenance.

### BRIEF-INACCURACY finding: worktree add/remove/prune was already fixed

DF-71's text states: "Add `worktree (add|remove|prune)` and `branch -d`/`branch
-D` to FORBIDDEN_PATTERN at :90 ... **neither is currently matched**." I verified
this against `git show HEAD:hooks/scripts/teammate_git_guard.sh` before touching
anything: `FORBIDDEN_WORKTREE_PATTERN` (a **second**, already-wired pattern, not
merged into `FORBIDDEN_PATTERN`) has matched `git worktree add/remove/prune`
since commit `3eb4d6a` (2026-06-09) — `git log -p --follow` on the file confirms
it, and I reproduced it live: `git worktree remove --force ...` from a seeded
matching session **already DENIED** on `HEAD`, before any of my edits. Only
`branch -d/-D` was the genuine, unmatched gap. I did not re-add worktree
patterns (would be `DUPLICATION RISK` against the file's own existing code) —
I only added `FORBIDDEN_BRANCH_DELETE_PATTERN` and folded the existing worktree
pattern into the combined header/VERBS/MSG documentation so all three shapes
are described consistently. This is a genuine drift between the audit ledger's
text and the file's actual state at dispatch time (the ledger's DF-71 audit
likely ran against an earlier snapshot, or conflated the *comment's* stale
`push`-without-`worktree` wording with the *regex's* actual — already correct —
coverage). Recommend the ledger/dogfood.md row be annotated, not re-litigated.

### Part (a) — session-required registration: confirmed collateral breakage (needs a follow-up, out of my scope)

`cmd_teammate.sh register` now resolves `--session`, else `${CLAUDE_SESSION_ID}`
(matching the one existing env-fallback convention in this codebase,
`cmd_deliverable.sh:29`), else `exit 1` with `ERR: TEAMMATE-SESSION-UNRESOLVED`.
This is exactly what the brief specified ("wire cmd_teammate.sh so a registration
without a resolvable session is an ERROR, not a silent NULL"). I ran the two
existing `skills/context/tests/` suites that call `register` (outside my
`[FILE-SCOPE]`, read-only inspection) to measure the blast radius honestly rather
than guess, and confirmed:

- `skills/context/tests/test_cmd_teammate.sh:23` — **now fails** (`register
  conductor-test --team=team-a --type=conductor --pane='%5'`, no `--session`).
- `skills/context/tests/test_cmd_teammate_conductor_only.sh` — **now fails** at
  lines 33, 37, 41, 53, 63, 74, 76 (seven `register ... --team=... --type=...`
  calls, none pass `--session`). Lines 45/57 (the critic/coder ROLE-INVALID
  refusal tests) are **unaffected** — the role gate runs before my session
  check and already rejects those calls for a different reason.

This is a **known, confirmed, mechanical** follow-up: each site needs
`--session=<any-fixture-uuid>` appended (these are ephemeral test DBs; any
non-empty placeholder session id works, since the assertions being tested are
unrelated to session identity). It is a one-line-per-call-site fix, zero design
ambiguity. `skills/context/tests/` is **not** in my `[FILE-SCOPE].exclusive`
(only `skills/context/scripts/cmd_teammate.sh` is), so I did not touch it —
surfacing this explicitly rather than silently shipping a change I know breaks
two sibling test files. This is the intended, documented trade-off the dispatch
itself named ("Do the code side only ... note the doc follow-up") extended one
layer further than `commands/spawn.md`: **every** caller that omits `--session`
now errors loudly, by design, until follow-up work supplies real session ids.
I checked `commands/spawn.md` itself (blocked file, read-only) and
`hooks/tests/test_v630_wiring.sh` (string-matches spawn.md's prose, never
executes `cmd_teammate.sh` — unaffected) for completeness; no other caller in
the repo invokes `register` without `--session` besides the two files above.

Deeper architecture note (not invented, confirmed by two independent existing
findings — DF-12 in this same `dogfood.md`, and `skills/harness/SKILL.md`'s "No
per-teammate identity env var exists ... teammate identity arrives ONLY in
hook-input JSON, never an env var a script reads"): **no caller in this codebase
currently has a proven way to supply a teammate's own session uuid at
registration time.** `Agent(subagent_type, name)` returns `name@team-id`, never
a session uuid; a teammate cannot read its own session id from any env var
either. So this fix converts a *silent* defect into a *loud* one precisely as
directed, but does not by itself give `commands/spawn.md`'s documented
`register <name> ... [--session={team_session}]` call anything real to
substitute for `{team_session}` — that remains open and is exactly the doc-side
follow-up the dispatch flagged as blocked/out of scope. Part (c) below does NOT
depend on this being resolved (see next section), so `teammate_git_guard.sh`
itself is no longer blocked by this gap even though `cmd_teammate.sh` now is.

### Part (c) — the signal that actually exists at runtime (found, wired, no invention needed)

The brief's own escape hatch — "if no such signal exists, say so ... that is a
legitimate blocking finding" — did not apply: a signal **does** exist and is
already proven live. `hooks/scripts/_lib.sh`'s `session_tier_marker()` +
`user_prompt_submit.sh`'s stamp-at-boot logic (`<ns>/tmp/session-tier-<session>`)
already answers exactly "is this session a native teammate-spawn" independent of
the `teammates` DB table, and two other guards
(`coordinate_drive_guard.sh:71`, `conductor_write_guard.sh:130`) already trust it
for the identical root-vs-teammate distinction. Root's own top-level session
never receives this marker (confirmed by `user_prompt_submit.sh`'s own comment:
an operator-typed prompt never carries the anchored
`[INVOCATION-CONTEXT].dispatcher:` field), so marker-presence alone safely
identifies "this is a teammate" without any DB dependency and without risking
the false-positive the brief explicitly warned about ("root ... produce zero
rows, so a naive flip denies root's own git").

`teammate_git_guard.sh` now: on a zero-row `teammates` lookup, checks (1) is
there a row with this EXACT `session_id` that's merely status-excluded
(retired/crashed) — if so, definitively not a concern, skip the marker; (2)
else, is the session-tier marker file present — if so, treat as a teammate and
DENY forbidden verbs; (3) else, unchanged fail-open. Step (1) is an addition
beyond the brief's literal text, added after my own test suite caught a real
regression (see FALSIFIABILITY below) — it makes the retired-teammate exemption
precise (keyed on registry proof) instead of accidentally defeated by a stale
marker file.

**Documented residual gap (not hidden):** a teammate whose first prompt didn't
match `user_prompt_submit.sh`'s `TIER_DISP_RE` (a malformed/unrecognized
`dispatcher:` value) is neither DB-registered nor marker-stamped and still
falls through to allow. No further runtime signal distinguishes that case from
inside a single `PreToolUse(Bash)` hook; closing it needs the dispatch path
itself to guarantee the marker, which is outside `hooks/scripts/`.

**Documented accepted trade-off:** a marker persists on disk from boot until
process cleanup; a teammate retired mid-run whose session_id was *never*
recorded (so step (1) above can't prove it) and whose marker file is still
present will be DENIED on a stray post-retirement git call, rather than
allowed. This is deliberate — DENY-and-surface is the recoverable failure
direction (harness shutdown is documented SLOW, `skills/harness/SKILL.md`); an
unreviewed merge onto `dev` is not. Covered by test `P16`.

### FALSIFIABILITY (empirical, run live — not asserted)

Per the brief's explicit demand ("prove your fix falsifiable — show the
assertion failing before the fix and passing after"), I extracted
`git show HEAD:hooks/scripts/teammate_git_guard.sh` into a scratch copy and ran
the exact P2 payload (unseeded DB row, session-tier marker present, `git merge
origin/dev`) against both versions, in a throwaway repo (not this checkout):

- **Pre-fix (`HEAD`)**: empty stdout — silent PASS. This is DF-71's measured
  production defect, reproduced live, not inferred.
- **Post-fix (working tree)**: `{"permissionDecision":"deny",...
  "Identity   : session-tier marker (teammates.session_id not yet populated —
  DF-71)"...}`.

Repeated for part (b) (`git branch -d`, seeded matching session): pre-fix
silent PASS, post-fix DENY. Scratch artifacts were created under and cleaned
from the session scratchpad / `mktemp -d`, nothing left in the repo.

`hooks/tests/test_teammate_git_guard.sh` was run directly (42/42 pass) — this is
my own file, in `[FILE-SCOPE].exclusive`, a self-contained `<2s` shell script
touching no `cargo`/build system and no shared `target/` lock, so I read the
`RESOURCE DISCIPLINE (#256)` prohibition as scoped to the project's aggregate
build/test command (cargo, `bin/shepherd lint`, etc.), not to executing a bash
test file I authored to satisfy an explicit brief requirement I could not
otherwise honestly claim to have met.

### Assumptions needing central-verifier confirmation

1. `hooks/scripts/_lib.sh`'s `session_tier_marker`/`resolve_namespace` exports
   are unchanged by any concurrent sibling wave this run (I read but did not
   modify `_lib.sh`; `grep -n session_tier_marker _lib.sh` confirmed the
   function signature I depend on).
2. `skills/context/tests/test_cmd_teammate.sh` and
   `test_cmd_teammate_conductor_only.sh` need the `--session=<fixture-uuid>`
   follow-up noted above before the central verifier's full suite run — without
   it, those two files will show as newly failing and should NOT be mistaken
   for a regression in `cmd_teammate.sh` itself; they need one flag each.
3. No Rust/cargo files were touched; the LOC-budget governance clause
   (`loc-count.py`, `*.rs`-scoped) does not apply to this lane's deliverables.

### Summary

Fixed DF-71 CRITICAL: `teammate_git_guard.sh`'s SQL-only teammate identity check
matched zero rows for every teammate all sprint (confirmed empirically, not just
cited) because `teammates.session_id` was never populated; the guard now falls
back to the already-live `session_tier_marker` signal two sibling guards already
trust, closing the false-allow while explicitly preserving root's own git and a
documented, tested exemption for known-retired teammates. Added the missing
`git branch -d/-D/--delete` block (worktree add/remove/prune was already wired,
contrary to the ledger's text) and corrected the stale `push` comment.
`cmd_teammate.sh register` now refuses a session-less registration loudly
instead of inserting NULL silently, with the confirmed collateral impact on two
out-of-scope test files documented above for follow-up. The test suite was
restructured so the unseeded (production-representative) database is the
primary case and the old seeded fixture is secondary, and the core regression
was proven falsifiable empirically against the pre-fix script, not merely
asserted.

- Reporter: coder-W8-L1 @ 2026-08-13T22:32:58Z
