---
title: Wave-review audit — lane l5-harness, Wave 0
date: 2026-08-12
auditor: shepherd:auditor
sprint: v645
concern: wave-review-l5-harness
mode: wave-review
methodology: superpowers:systematic-debugging (hypothesis -> falsification -> confidence), re-run every coder acceptance command independently against live worktree state
prior_class_priors: empty registry (shctx adapt report: "no sprint metrics recorded yet") -- framework priors applied
deliverable: 3 (status: delivered)
---

## Scope reviewed

Lane l5-harness, Wave 0, 10 steps: W0-S2, W0-S5, W0-S6, W0-S7, W0-S8, W0-S11, W0-S12,
W0-S13, W0-S15 (planned) + W0-S16 (conductor ad-hoc). All work sits uncommitted in
`/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness` (17 changed/new paths).
Sources: lane plan (`lanes/l5-harness/plan.md` incl. `## Deviations`), sprint plan
`[ACCEPTANCE]` blocks per step, all 10 coder reports, live worktree git state, and
`discovery-d1-harness.md` for harness-capability cross-checks. Files reviewed: 17
changed/new paths across 10 step diffs, all 10 coder reports in full, lane plan.md,
lane vars.json + manifest, sprint plan.md step sections, `services/cli/shepherd_cli/
commands/plan.py` (`_lane_drift`), `skills/shepherd/references/wave-routine.md`.

## Findings summary

CRITICAL=0, HIGH=1, MEDIUM=0, LOW=1. Verifications (disproved concerns / confirmed
claims): 4. Open questions: 0.

## Findings

### FINDING 1 (HIGH) — lane l5-harness's own plan.md/vars.json pair is currently
drifted; the sprint's own wave-boundary gate would fail if run right now

**Hypothesis.** The l5-harness conductor has been hand-editing the rendered
`lanes/l5-harness/plan.md` (writing rich "DONE — coder-W0-Sn.md: ..." prose directly
into each step's `**Acceptance:**` line as coder reports land, and appending step
`W0-S16`) without regenerating the sibling `lanes/l5-harness/vars.json` — reproducing
live, inside this same wave, the exact #269 anti-pattern W0-S12 was dispatched to make
detectable.

**Falsification.** Ran `shepherd plan lane-drift v645` independently, twice (from the
sprint root and from the worktree root — result identical either way):

```
$ shepherd plan lane-drift v645
lane-drift: l5-harness: step COUNT differs -- plan.md has 10, vars.json has 9
lane-drift: l5-harness: step[0].acceptance DRIFT
    plan.md  : DONE — `coder-W0-S2.md`: real clean-clone repro (...)
    vars.json: ['Every runnable assertion in plan.md §W0-S2 [ACCEPTANCE] exits 0.']
... (7 more step[i].acceptance DRIFT entries, one per completed step)
lane-drift: l5-harness: step 'W0-S16' exists in plan.md but not in vars.json
lane-drift: FAIL (11 divergence(s)) — a correction reached one copy only. Mirror it
into the OTHER file before dispatching; vars.json is what the brief renders from.
EXIT=1
```

This directly contradicts W0-S12's own coder report (`reports/coder-W0-S12.md`),
which cites this exact command's exit-0 / "2 lane(s) agree" output as proof "#269
CONFIRMED WORKING." I confirmed the discrepancy is timing, not a coder defect:
`lanes/l5-harness/vars.json` mtime = 19:22 (lane boot); `plan.md.manifest.json`'s
recorded `vars_sha256` matches `boot-vars.json` byte-for-byte (`diff` shows only the
one JSON key `boot-vars.json` lacks, `acceptance`, which is metadata not content
drift) — i.e. `vars.json` has not been touched since boot. `plan.md` mtime = 19:57,
well after every coder report landed (last coder report `coder-W0-S4.md` at 19:55,
though W0-S4 is a different lane's — the point is plan.md was actively edited deep
into the wave). `skills/shepherd/references/wave-routine.md:63` states plainly:
"`shepherd plan lane-drift {run}` MUST exit 0 at every wave boundary (#269) ...
Exit 1 lists each divergence — mirror it and re-run, never wave past it." This is a
wave boundary (pre-WAVE-COMPLETE, pre-commit).

**Confidence: HIGH.** Structurally verifiable — deterministic CLI output, reproduced
twice from two different cwds, root-caused via file mtimes and a byte-diff of the two
vars.json snapshots, and the requirement it violates is unambiguous doctrine text at
`wave-routine.md:63`.

**Scope note.** This is NOT a defect in any of the 10 coders' diffs — none of them own
`vars.json`/`plan.md` (conductor-exclusive artifacts). It is the conductor's own
pre-WAVE-COMPLETE bookkeeping, currently out of sync. Action: regenerate
`lanes/l5-harness/vars.json` from the final lane plan (or re-render `plan.md` from an
updated `vars.json`, folding in W0-S16) before declaring WAVE-COMPLETE — root's own
wave-boundary gate (`wave-routine.md` root-gate step list) will independently catch
this exact condition otherwise. Ironic and worth naming explicitly: this is the live
#269 lived-experience defect recurring inside the very wave whose W0-S12 step exists to
detect it.

### FINDING 2 (LOW) — W0-S16's `rust.yml` -> `check-plugin.py` rename is merge-order
dependent on l4-conformance's W0-S1 rename

**Hypothesis.** `rust.yml` now invokes `./scripts/check-plugin.py`, but
`scripts/check-plugin.py` does not exist in the l5-harness worktree (l4-conformance
owns `scripts/`); if l5-harness's commit ever lands on a tree without l4-conformance's
rename already present, CI breaks (`no such file`).

**Falsification.**
```
$ ls .worktrees/v645-l5-harness/scripts/check-plugin.*
check-plugin.sh   # .py absent
$ ls .worktrees/v645-l4-conformance/scripts/check-plugin.*
check-plugin.py   # rename already applied there
```
Both worktrees are mutually consistent with the intended end-state (l5's `rust.yml`
correctly anticipates l4's rename); the risk is purely sequencing at merge/integration
time, not a coding defect. This was explicitly root-authorized as W0-S16 after W0-S13
correctly refused a scope-widening addendum (DF-27, documented in full in the lane
plan's `## Deviations`).

**Confidence: MEDIUM** (plausible-partial — depends on an integration-time merge order
this wave-review cannot observe directly).

**Disposition.** Not REDO-worthy for W0-S16 as dispatched; flagged for root/conductor
integration-sequencing awareness (l4-conformance's rename must land no later than
l5-harness's `rust.yml` update).

## Verifications (claims independently re-run, not just trusted)

1. **W0-S2 + W0-S5 merge on `commands/spawn.md`.** `git diff commands/spawn.md` read
   in full: Check 4b row present (W0-S2) AND all four W0-S5 corrections present
   (Pre-spawn tool check, Spawn dispatch, Self-contained engineer intro line,
   ENGINEER-TOPOLOGY-MISMATCH trigger wording) — neither edit reverts the other.
   Confidence: HIGH.
2. **W0-S12's `shctx plan amend` finding.** Independently ran `shctx plan amend` and
   `shepherd plan amend` at sprint root: `ERROR: unknown subcommand: amend` (exit 1)
   and `ERROR: --plan <path> required and must exist` (exit 2) respectively — matches
   the report exactly. `agents/shepherd.md:158` does document the unwired `shctx` form.
   Confidence: HIGH.
3. **W0-S15's guard.** `bash hooks/tests/test_plan_proof_guard.sh` (12/12 PASS, exit
   0), `bash hooks/scripts/plan_proof_guard.sh --self-test` (exit 0, message names
   `record-critique`), `bash hooks/tests/test_plan_proof_guard.sh --no-proof` (3/3
   PASS, exit 0) — all re-run against live worktree, all match the report. `hooks.json`
   parses as valid JSON and wires `plan_proof_guard.sh` into both `Write`/`Edit`
   `PreToolUse` matcher arrays. Confidence: HIGH.
4. **W0-S7's `check-deps.mjs` and W0-S13's `boundary-selftest.sh`.** Both re-run
   directly: `node packages/scripts/check-deps.mjs` (3/3 rules ok, exit 0),
   `--self-test` (3/3 fail-as-designed then real tree ok, exit 0);
   `bash .github/scripts/boundary-selftest.sh` (8/8 ok, exit 0). Both
   `.github/workflows/rust.yml` and `.github/workflows/boundaries.yml` parse as valid
   YAML after their respective W0-S13/W0-S16 edits (`yaml.safe_load`, no exception).
   Confidence: HIGH.
5. **W0-S6 and W0-S8 acceptance blocks**, re-run verbatim against the live worktree:
   `test_engineer_self_contained.sh` (PASS), `shepherd_mcp_available` resolves as a
   function, `rg -c '\.claude/shepherd\.toml'` on the two named files each shows 1
   qualified legacy-clause hit; `content/RECONCILIATION.md` exists, all 9
   `content/roles/*.md` present, all 9 carry `write_eligible:`. Confidence: HIGH.
6. **File-disjointness across all 10 steps.** Every one of 17 changed/new paths in
   `git -C worktree status --porcelain` maps to exactly one step's `file_scope`,
   except `commands/spawn.md` (W0-S2 + W0-S5, explicitly sequenced per the lane plan,
   verified compatible in item 1 above). No unintended collision. Confidence: HIGH.
7. **W0-S11's capability lint.** `bash hooks/tests/lint_agent_capabilities.sh` (exit
   0, observed-vs-declared scan present), `--self-test` (exit 1, deliberately —
   detects a fabricated `Glob` delta, proving the detector can fail), `rg -q
   'observed|runtime'` (exit 0) — all match the report. Confidence: HIGH.

## Open questions

None — every claim inspected either confirmed or is captured above as a named
finding.

## Cache telemetry

N/A — wave-review mode; cache telemetry is a completeness/close-mode check only.

## WAVE-REVIEW VERDICT

- Lane / wave: l5-harness / w0
- review_verdict: PASS
- Checklist hits: intent=0, fragile-global=0, reinvention=0, passes-local-breaks-CI=0
- (see Finding 1, HIGH, and Finding 2, LOW, above — both are conductor/integration
  process findings, not coder-diff defects against the four-item checklist; neither
  names a coder step whose work should be redone. Finding 1 is a BLOCKING
  pre-WAVE-COMPLETE action item for the conductor: `shepherd plan lane-drift v645`
  currently exits 1 and per `wave-routine.md:63` "MUST exit 0 at every wave boundary
  ... never wave past it" — resolve before declaring WAVE-COMPLETE, independent of
  this PASS verdict on the 10 coder diffs themselves.)
- Suggested redo: none (zero checklist hits against any of the 10 coder diffs)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/audits/audit-wave0-l5-harness-review.md
- Agent ID + timestamp: shepherd:auditor (wave-review, l5-harness w0) @ 2026-08-12T20:30:00Z
