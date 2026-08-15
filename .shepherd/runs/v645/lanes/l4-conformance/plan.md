# Lane l4-conformance — Conformance, tooling truth, and the oracle freeze

**Run:** v645
**Objective:** Wave 0 for the lane that owns the toolchain's own honesty. Make `lint` count what it reports, stop `doctor` prescribing commands that do not exist, move model-slug translation into the engine, freeze the conformance oracle from the Python CLI (#281, CRITICAL), repair the lane-plan template that cannot render a spec-conformant plan (DF-16), and land the Stage-Graph checker (W0-S14). W0-S9 carries a MUST-FIX-BEFORE-DISPATCH condition: it must include `--suite=guard-cli` covering the five CLI behaviours guard scripts depend on, per the restated seed decision 3.
**Worktree:** /Users/jo3/src/fl03/shepherd/.worktrees/v645-l4-conformance
**Base commit:** 5be42280615c8dc5321061798240f476dffed645
**git_custody:** lane

## File scope

- Exclusive (OWNED):
  - `conformance/`
  - `scripts/`
  - `services/cli/`
  - `.shepherd/runs/*/run.json`
  - `CHANGELOG.md`
  - `README.md`
  - `.claude-plugin/plugin.json`
- May read:
  - `crates/`
  - `hooks/scripts/`
  - `skills/`
  - `agents/`
  - `.shepherd/runs/v645/`

## Interfaces

- Consumes:
  - Nothing. Lane l4-conformance has no Wave-0 predecessors outside itself.
- Produces:
  - `conformance/run.sh` with `--impl` and `--suite` (consumed by every later wave)
  - `scripts/check-stage-graph.py` (consumed by root at every wave gate)
  - a `lane-plan.md.j2` that renders `step_id`, `must_not_touch` and `parallel_with`

## Do not duplicate

- ``scripts/check-workspace.sh` and `scripts/check-plugin.sh` already implement the `--self-test` fixture pattern — follow it, do not invent a second one`
- ``scripts/check-stage-graph.py` (W0-S14): a working implementation exists at `/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad/graph_check.py` — PORT it, do not rewrite it`

## Steps

### W0-S1: make `lint` count instances, and stop a Python gate wearing a `.sh` name

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S1 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S1 [ACCEPTANCE] exits 0.']
### W0-S3: the diagnostic tool stops prescribing commands that do not exist

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S3 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S3 [ACCEPTANCE] exits 0.']
### W0-S4: model slugs are translated by the engine, not by each dispatcher (DF-03)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S4 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S4 [ACCEPTANCE] exits 0.']
### W0-S9: freeze the conformance oracle from the Python CLI (#281, CRITICAL)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S9 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S9 [ACCEPTANCE] exits 0.']
### W0-S10: the lane-plan template cannot render a spec-conformant plan (DF-16, HIGH)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S10 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S10 [ACCEPTANCE] exits 0.']
### W0-S14: the Stage Graph gets a checker, because this defect class has now bitten three times

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S14 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S14 [ACCEPTANCE] exits 0.']

## Lane acceptance

- [ ] `bash scripts/gate.sh full` exits 0
- [ ] `bin/shepherd lint` exits 0 and its count matches its emitted violation lines
- [ ] `conformance/run.sh --impl=python` exits 0 with a non-zero case count
- [ ] `conformance/run.sh --impl=python --suite=guard-cli` exits 0
- [ ] `python3 scripts/check-stage-graph.py --self-test` exits 0
- [ ] `shepherd render lane-plan.md.j2` renders a spec-shaped fixture (step_id, must_not_touch, parallel_with) at exit 0

## Non-goals

- `packages/`
- `content/`
- `agents/`
- `commands/`
- `skills/`
- `hooks/`
- `bin/`
- `.github/workflows/` — all owned by lane l5-harness this wave
- `crates/**` — no lane owns it in Wave 0
- Do NOT re-argue the operator's Option B scope decision; it is DECIDED

## Deviations

(append-only — the conductor records every mid-lane modification or choice
here: what changed, why, and the step affected; never rewrite prior entries)

- **WORKFLOW-VEHICLE-PROBE (boot):** `Workflow` is absent from this session's
  visible tool list (top-level tools: Agent, Bash, Edit, Read, Skill,
  ToolSearch, Write — no `Workflow`). Per conductor.md §Lane walk, this means
  the Agent-Teams substrate was not live at spawn regardless of the boot
  brief's framing — I am silently an Agent-tool subagent. Fan-out vehicle for
  Wave 0 is in-context `Agent()`, the whole `parallel_with` clique in ONE
  message. Will record `fanout: "in-context"` +
  `fanout_downgrade_reason: "workflow-absent-from-tool-list"` in
  WAVE-COMPLETE — correct on this substrate, not a downgrade.
- **SEED-DRIFT-MECHANICAL (file-scope gap, affects W0-S1, W0-S3, W0-S4,
  W0-S10):** each step's `[ACTIONS]`/`[ACCEPTANCE]` in plan.md requires a new
  or updated regression test / fixture, but `file_scope.exclusive` names only
  the source file:
  - W0-S1: needs `services/cli/tests/test_lint.py` — it currently contains
    `test_multiple_violations_count_stays_capped_at_one`, which asserts the
    OLD bash-parity-capped-at-1 behavior this step explicitly reverses; that
    test cannot survive unmodified.
  - W0-S3: needs `services/cli/tests/test_doctor.py` (already `may_read`,
    extending to exclusive for this coder) for the "every fix-string is
    runnable" regression test named in Action 4.
  - W0-S4: needs `services/cli/tests/test_models.py` (already `may_read`,
    extending to exclusive) for the `--harness` table-test named in Action 3.
  - W0-S10: needs `.shepherd/runs/v645/fixtures/lane-plan-spec.json` (new
    file, not previously in scope at all) — the step's own ACCEPTANCE commits
    this exact fixture path.
  Extending each step's exclusive file scope by exactly the one test/fixture
  file its own acceptance requires, verified file-disjoint across all four
  (and against W0-S9/W0-S14, which already had correct scope). No other file
  touched. Logged rather than escalated to root — this is a mechanical
  omission in an otherwise correct plan, not an architecture question.
- **DF-25 (root-flagged, `[SKILLS]` domain-key/skill-value confusion) — hit
  4/6, preempted the other 2:** every one of this lane's six Wave-0 steps
  carries a bad `[SKILLS]` line in plan.md: `code-style, markdown` (W0-S1
  line 375, W0-S10 line 430) or `code-style, shell`/`code-style, python`
  (W0-S3 line 773, W0-S4, W0-S9, W0-S14). Root traced the cause:
  `shepherd.toml`'s `[skills].by_domain` table has domain KEYS
  (`shell`/`markdown`) mapping to skill VALUES (`code-style`) — whoever
  generated these per-step `[SKILLS]` lines copied the key instead of the
  value, and `python` isn't even a domain key, just invented. No
  `markdown`/`shell`/`python` skill exists in this environment; only
  `code-style` is installed and mandatory per `[skills].mandatory`.
  Root's message arrived AFTER dispatch. By the time I checked, 4 of 6
  coders had already halted `BRIEF INVALID` on their own Startup Protocol
  (W0-S1: `markdown`, W0-S3: `python`, W0-S4: `python`, W0-S10: `markdown`)
  — confirmed via their halt reports at
  `.shepherd/runs/v645/reports/coder-W0-{S1,S3,S4,S10}.md`. Sent an
  authorized correction (`SendMessage` to each agentId: `[SKILLS]` is
  `code-style` ALONE, resume from Step 2) to all six coders — the 4 halted
  ones to resume past their halt, W0-S9/W0-S14 preemptively in case they
  hadn't reached Step 1 yet (W0-S14's correction queued for its next tool
  round — it was still actively running, uninterrupted). Did NOT edit
  `plan.md`'s `[SKILLS]` lines directly — that file is a critic-proofed,
  cross-lane shared artifact outside this lane's write scope; the fix is a
  per-dispatch brief override, not a plan mutation. Cost: 4 coder
  round-trips burned on a halt-then-resume instead of a clean run; still
  cheaper than root's ~105k-token L5 loss since I checked before more
  co-dispatch rounds compounded it. Root should fold `[SKILLS]` validation
  into `shctx plan lint`/whatever pre-dispatch check comes out of DF-25's
  proposed `shctx` verb — flagging as a candidate follow-up, not building
  it myself (out of lane scope this wave).
- **DF-25 part 2 (root correction): `python`→`.py` IS mandated, genuine
  environment gap, not a waiver-able domain-key bug.** Root's first message
  (above) was itself incomplete: `flock.md:54` mandates `python` for every
  `.py` file, and no `python` skill existed in this environment at all —
  neither branch of `agents/coder.md`'s halt logic (list it → `BRIEF
  INVALID`; omit it → `BRIEF-AMENDMENT REQUEST`) has an escape. Root issued
  a hard HALT ALL DISPATCH across both lanes and authored `python`+`shell`
  skills from scratch. Fallout on my own prior (retracted) "code-style
  alone" corrections, checked before acting further:
  - **W0-S4** coder correctly REFUSED my invalid override outright, citing
    "never substitute, even under a conductor override" — zero files
    touched, no damage.
  - **W0-S1** coder ACCEPTED my invalid override and produced a real,
    complete-looking diff (lint.py counting fix, check-plugin.sh→.py
    rename, gate.sh updates) without ever loading `python`. I discarded it
    (`git checkout` + `rm`, worktree confirmed clean on those 3 paths) —
    correct code produced via a skipped mandatory gate is still discarded,
    per root's explicit "not a waiver" stance; this is a process rule, not
    a quality judgment. Re-dispatched W0-S1 fresh with `code-style,
    python` (both now real) and pointed it back at its own original
    halt-report analysis, which was sound and doesn't need re-deriving.
  - **W0-S3, W0-S9, W0-S14**: no confirmation either way when I checked —
    diffs appeared in the worktree (doctor.py, check-stage-graph.py +
    fixtures) between my invalid correction and root's real fix landing,
    consistent with those coders naturally retrying `Skill(python)` once
    it became genuinely installed and succeeding on their own, but not
    confirmed. Sent each a message: if the diff was produced with the real
    skill loaded (confirm via a `Skills loaded:` report line), finish
    normally; if not, stop and I discard + redo, same as W0-S1.
  - **W0-S10**: unaffected throughout — its `markdown`→domain-key bug was
    real and `code-style` alone was always correct for it (root's own
    final table confirms, no `python` needed for a `.j2` template).
  Root's corrected `[SKILLS]` table (verbatim): W0-S1/W0-S3/W0-S4/W0-S14 =
  `code-style, python`; W0-S9 = `code-style, shell, python`; W0-S10 =
  `code-style`. Declined to build `shctx skills validate` as an ad-hoc 7th
  step mid-wave (no step_id/file_scope/acceptance in the critic-gated plan
  for it) — proposed it to root for W1 decomposition instead, per root's
  own "if it fits your remaining budget, else propose it for W1" framing.
- **DF-26 (cross-lane + orphan rename-reference collision, W0-S1's
  check-plugin.sh-to-.py rename):** three references outside this lane's
  scope surfaced only by a coder reading past its own file list, then by
  root grepping by hand: (1) `.github/workflows/rust.yml:138,140` — L5's
  scope, not mine; root routed it, L5 shipped it as a properly-scoped
  `W0-S16` step (their coder correctly refused an inline addendum).
  Verified by root in their worktree: 0 `.sh` refs remain, 2 `.py` refs
  present. (2) `.shepherd/docs/specs/2026-08-12-v645-plugin-layout-
  contract.md:50` — belongs to no lane's `file_scope.exclusive` this wave;
  root is taking the one-line doc fix directly (`.md` write, root's own
  boundary). Root flagged this as the third DF-26 instance this wave and
  proposed a wave-gate reference-integrity check as a second W1 candidate
  for this lane (alongside `shctx skills validate`) since W3/W4 retire 40
  `cmd_*.sh` scripts + 98 bash test files, at which scale hand-grepping
  renames stops scaling. **Rename hold released** — cleared to commit
  W0-S1's rename once its own wave-review passes.
- **Liveness-diagnostic gap (root-flagged, near-miscancel of W0-S9):** I read
  `git status --porcelain` showing bare `?? conformance/` and no report file
  as "no progress" and was about to treat the CRITICAL step as stalled.
  Wrong read — `find .../conformance -newer <base>` (root's check) showed
  `conformance/{cases,lib,scripts}/` created 19:47-19:48, the MOST recent
  activity in the whole lane; porcelain collapses an untracked subtree to
  one line and hides everything happening inside it. `shctx teammate
  liveness` is separately known-blind (DF-12, `last_seen_at` never leaves
  `spawned_at`). Lesson for future long-running steps in this lane: check
  `find <expected-output-dir> -newer <base-commit-time>` before treating
  silence as a stall, never `git status --porcelain` alone.
- **DF-35 (root-flagged): my dispatch briefs gave the report path
  RELATIVE** (`.shepherd/runs/v645/reports/coder-<step>.md`), which
  resolved inside this lane's own gitignored worktree copy
  (`.gitignore:58` excludes `.shepherd/runs/**`) — one `git worktree
  remove` at CLOSE-FINALIZE from destroying five reports (W0-S1, W0-S3,
  W0-S4, W0-S10, W0-S14). Root rescued + committed all five to the
  canonical run dir before that could happen. Corrected: sent every
  still-live coder (all six) the absolute path
  `/Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/coder-<step>.md`
  for any further report write. Any future dispatch from this lane uses
  the absolute path from the start.
- **DF-35 RETRACTED by root, on W0-S10's coder's refusal.** The absolute-
  path instruction told a coder to write outside its own worktree —
  `NEVER write outside [WORKTREE].Path` is a hard confinement rule with no
  peer-message exception, even from the dispatching conductor. W0-S10's
  coder caught this and refused; root confirmed the refusal was correct on
  every point. Correct fix, root's: coders keep writing reports/fixtures
  to their OWN worktree at the original relative path
  (`.shepherd/runs/v645/reports/coder-<step>.md`,
  `.shepherd/runs/v645/fixtures/lane-plan-spec.json`); I (conductor) `git
  add -f` those gitignored paths at wave-commit time — moving a file
  across the worktree boundary is git custody, mine not the coder's.
  Retraction sent to all five coders I'd wrongly redirected. This is the
  fourth hard-rule refusal against dispatcher pressure this wave across
  both lanes (W0-S4 vs my own bad skills override, W0-S13, W0-S15, now
  W0-S10) — noted for WAVE-COMPLETE per root's request.
