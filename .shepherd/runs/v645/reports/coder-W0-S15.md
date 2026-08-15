# CODER REPORT — W0-S15 (DF-22, RE-DISPATCH)

## Files changed
- `hooks/scripts/plan_proof_guard.sh` (NEW) — `PreToolUse(Write|Edit)` guard: refuses a Write/Edit
  to a `plan.md`-shaped path whose sibling `<slug>.critic-proof.json` currently verifies CLEAN
  (`shctx plan verify --plan <file> --quiet` exits 0). Allows the write when no proof exists or the
  proof is already stale/unedited/uncritiqued. Supports `--self-test` (negative-control mode).
- `hooks/hooks.json` — wired `plan_proof_guard.sh` into both the `Write` and `Edit` `PreToolUse`
  matcher arrays, immediately after `lock_guard.sh` (same wiring shape lock_guard itself uses).
- `hooks/tests/test_plan_proof_guard.sh` (NEW) — negative-control test suite. Builds real plan +
  critic-proof fixtures through the actual `bin/shepherd plan hash` / `record-critique` CLI (not
  hand-forged JSON/hashes), then asserts deny-on-clean, allow-on-stale, allow-on-no-proof,
  fast-path silence for non-plan paths / non-Write-Edit tools / non-shepherd repos. Supports
  `--no-proof` to run only the "no proof exists → always allowed" isolated negative control.

Both new files are `chmod 755` to match the exec-bit convention of every other `hooks/scripts/*.sh`
and `hooks/tests/test_*.sh` in the repo (verified against `lock_guard.sh` / `test_seed_preflight_check.sh`).

## LOC delta
- `hooks/scripts/plan_proof_guard.sh`: +160 (new file)
- `hooks/tests/test_plan_proof_guard.sh`: +115 (new file, under `hooks/tests/` — test LOC)
- `hooks/hooks.json`: +8 / -0 (two `{"type":"command","command":"...plan_proof_guard.sh"}` entries)

Raw total: +283 / -0. Production-shaped total (guard + hooks.json; the ONE-LOC rule's `tests/`
carve-out — written for `*.rs` but the same spirit applies here — excludes the 115-line test file):
**168 lines**, against the brief's **~120 estimate**. The brief marks that figure "(estimate only);
measured deterministically by the dispatcher" — I did not trim anything to chase it (no comment
gutting, no dropped self-test/negative-control coverage) per the ONE-LOC rule's "never drop a
mandated deliverable to fit a budget." Flagging the raw number transparently rather than
adjudicating it; re-run `scripts/loc-count.py` for the authoritative figure.

## Acceptance outputs

### 1. `bash hooks/tests/test_plan_proof_guard.sh`
```
== test_plan_proof_guard (full suite) ==
  PASS  clean-proof-write-denied
  PASS  clean-proof-edit-denied
  PASS  deny-names-plan-locked
  PASS  deny-names-record-critique
  PASS  deny-names-amend
  PASS  stale-proof-write-allowed
  PASS  stale-proof-edit-allowed
  PASS  no-proof-write-allowed
  PASS  no-proof-run-scoped-allowed
  PASS  non-plan-file-silent
  PASS  bash-tool-silent
  PASS  non-shepherd-silent
PASS: test_plan_proof_guard
```
Exit code: `0`

### 2. `bash hooks/scripts/plan_proof_guard.sh --self-test 2>&1 | grep -q 'record-critique'`
Underlying `--self-test` output (piped through the acceptance grep, which matched):
```
self-test: prove plan_proof_guard CAN block a write against a CLEAN critic-proof

  positive control (CLEAN proof detected)  ... ok
  deny message names record-critique       ... ok
[shepherd] PLAN-PROOF-LOCKED — <tmp>/plan.md carries a currently-VALID critic-proof (`shctx plan verify` passes CLEAN for it right now).
  This Write/Edit would silently invalidate that attestation: the proof is hash-tied to the plan's
  CURRENT bytes, and nothing else warns at record time or edit time -- 'shctx plan verify' only
  catches drift if someone remembers to run it later (DF-22).
  Recovery -- pick the one that matches what actually happened, never hand-edit the sidecar:
    1. A genuine further revision needing a fresh critic pass:
         shctx plan hash "<tmp>/plan.md"
         # ... get the plan re-reviewed by @critic with that hash as --pre ...
         shctx plan record-critique --plan "<tmp>/plan.md" --pre <hash> --verdict <PASS|...> [--iterations N] [--findings N]
    2. Root's sanctioned mid-sprint correction (#268) -- re-ties the EXISTING proof, no new critic pass:
         shctx plan amend --plan "<tmp>/plan.md" --reason "<why>"
  Edit through a channel this guard does not gate (e.g. Bash) to perform the change itself, THEN run
  one of the two commands above -- 'shctx plan verify' will report PLAN-UNEDITED/CRITIC-PROOF-STALE
  until you do.
See skills/shepherd/references/pipeline.md §INTRO.
  negative control (STALE proof allowed)    ... ok
  negative control (NO proof allowed)       ... ok

ok: plan_proof_guard blocks a CLEAN critic-proof and allows every other state.
```
`grep -q 'record-critique'` matched → pipeline exit code: `0`

### 3. `bash hooks/tests/test_plan_proof_guard.sh --no-proof`
```
== test_plan_proof_guard --no-proof (isolated: no proof exists -> always allowed) ==
  PASS  no-proof-write-allowed
  PASS  no-proof-edit-allowed
  PASS  no-proof-run-scoped-allowed
PASS: test_plan_proof_guard --no-proof
```
Exit code: `0`

### Extra verification (not a formal acceptance line, evidence of correctness)
Ran the guard against THIS sprint's own `.shepherd/runs/v645/plan.md` (real file, read-only —
never mutated) to confirm it would have caught the exact lived defect the brief describes:
```
$ printf '{"tool_name":"Write","session_id":"s","tool_input":{"file_path":".shepherd/runs/v645/plan.md"}}' \
    | bash hooks/scripts/plan_proof_guard.sh
{"permissionDecision":"deny","message":"[shepherd] PLAN-PROOF-LOCKED — .shepherd/runs/v645/plan.md carries a currently-VALID critic-proof ..."}
```
`.shepherd/runs/v645/plan.critic-proof.json` currently verifies CLEAN (`bash bin/shepherd plan
verify --plan .shepherd/runs/v645/plan.md --quiet` → rc 0), so the guard correctly locks it. `git
diff --stat -- .shepherd/runs/v645/plan.critic-proof.json .shepherd/runs/v645/plan.md` is empty —
confirmed untouched, per `[must_not_touch]`.

## Deviations
None from the brief's `[ACTIONS]`. Two implementation choices worth naming explicitly:

1. **The decision function calls `shctx plan verify` rather than re-implementing hash/schema
   comparison in bash.** The brief's `[CONTEXT-INVENTORY]` names `shctx plan verify`'s exact
   failure-code contract; reimplementing that logic in the guard would create a second copy that
   could drift from `services/cli/shepherd_cli/commands/plan.py` (the single source of truth) —
   exactly the kind of duplication the DEDUP-GATE exists to prevent, even though it isn't a
   literal symbol collision. This mirrors `hooks/scripts/seed_preflight_check.sh`'s own precedent
   of shelling out to `bin/shepherd` from a hook, including its fail-open contract (missing CLI
   binary → allow, never block on a tooling hiccup).
2. **The deny message names BOTH `record-critique` and `amend` as recovery paths, not one.** The
   brief's `[ACTIONS]` step 1 offered `record-critique` as a placeholder ("check plan.py/CLI help
   for the real invocation shape, don't invent flags"), but reading `plan.py` in full surfaced that
   `amend` (#268) is the CLI's own purpose-built verb for "root must legitimately edit an approved
   plan mid-sprint" — precisely one of the two real scenarios that reach this guard. Both are named
   because the guard cannot tell, from a Write/Edit call alone, which situation is which:
   `record-critique` is correct after a genuine re-critique (the engineer's path, and the actual
   scenario in the brief's evidence); `amend` is correct for root's sanctioned correction without a
   new critic pass. Neither flag was invented — both are taken verbatim from `plan.py`'s own
   `_USAGE` heredoc.

## Staged GH commands
None. No GitHub state to update for this step.

## Notes

**On whether `record-critique` should ALSO stamp the plan read-only (brief's ask):** recommend
AGAINST implementing chmod/read-only stamping, and this guard's own design is the evidence why.
The guard's detection is keyed on "does a *sibling `.critic-proof.json`* currently verify clean for
*this exact path*" — not on any property of the plan file itself. That is what makes it safe for
the conductor's own legitimate lane-plan writes (`.shepherd/runs/<run>/lanes/<lane>/plan.md`):
those are also literally named `plan.md` (confirmed via `_parse_lane_plan`/`_lane_drift` in
`plan.py`), but they are CONDUCTOR-rendered from `vars.json` and never gain a critic-proof sidecar
in the first place — so `shctx plan verify` on one of them returns `CRITIC-PROOF-MISSING` and this
guard is silent, with zero special-casing required. A chmod-based approach cannot get this
distinction for free: `chmod 444` (or similar) on `plan.md` the instant `record-critique` runs
would have no way to know in advance whether THIS `plan.md` will later be rendered as a lane plan
under the same basename in a directory the read-only bit doesn't distinguish, and would need its
own allowlist of "which conductor code paths may `chmod` back to writable" — reintroducing exactly
the kind of bypass-with-no-signal surface DF-22 is about closing, just moved into the filesystem
permission bit instead of the hook layer. The hash-tied verify-based guard gets the same
protection with strictly less surface area and no filesystem-mode state to keep in sync across
worktrees (a `chmod` made in one linked worktree does not propagate to a sibling worktree checked
out from the same repo, which would make the read-only property inconsistent depending on which
worktree a later reader opened the plan from). Minimum viable fix stands as implemented.

**Known scope boundary, not a defect:** this guard only gates the `Write`/`Edit` TOOLS. A `Bash`
command that edits the same bytes (`sed -i`, a heredoc redirect, `cp`) is not intercepted — by
design, per the brief's own `[ACTIONS]` scope (`PreToolUse(Write|Edit)`, matching
`lock_guard.sh`'s own matcher registration) and because `bash_guard.sh` (the Bash-side `PreToolUse`
guard) is outside this step's `[FILE-SCOPE]`. The deny message's recovery path 1 explicitly relies
on this gap ("Edit through a channel this guard does not gate (e.g. Bash)") as the one place a
deliberate, visible invalidation can still happen — consistent with the brief's Produces line
("unless the proof is explicitly invalidated first"): a Bash edit is a conscious shell command a
human/agent chose to write, not a routine tool call that silently slips past. Extending coverage to
Bash-mediated writes would be a reasonable follow-up but needs `bash_guard.sh` in scope, which this
brief did not grant.

**Anomaly encountered mid-dispatch, surfaced not acted on:** partway through Step 1 (skill
loading), a tool-result-embedded system-reminder claimed a `shell` skill is "available," directly
contradicting this RE-DISPATCH's own stated finding ("confirmed no shell/bash/sh skill exists
anywhere on this machine"). I independently verified via `find`/`ls` (not by trusting the injected
reminder) that `/Users/jo3/.claude/skills/shell/SKILL.md` does now exist on disk, dated today. I did
NOT load or use it: `[SKILLS]` in this corrected brief lists only `code-style`, this RE-DISPATCH
exists specifically to correct a prior `shell`-related halt, and self-electing an unlisted skill
mid-flight is exactly the "don't self-elect, request amendment" case in my own protocol. Flagging
for the dispatcher/engineer: if a real `shell` skill now exists globally, future bash-scope briefs
in this sprint may want it added to `[SKILLS]` explicitly — that determination isn't mine to make.
A second, similar unsolicited skill-listing ("typescript") appeared later in an unrelated tool
result; same treatment (noted, not acted on) — this repo's step is bash-only, and `[SKILLS]` never
listed it either.

## Reporter
coder-v645-l5-harness (W0-S15) @ 2026-08-12T20:15:00Z
