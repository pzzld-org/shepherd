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
