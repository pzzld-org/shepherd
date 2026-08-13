# Lane l5-harness — Harness truth, the content tree, and the npm skeleton

**Run:** v645
**Objective:** Wave 0 for the lane that owns everything the three harnesses read. Make a clean clone able to spawn (DF-01), align dispatch doctrine with the platform that actually ships (DF-02/DF-11), turn declared capability into probed capability (DF-04, and DF-17 at W0-S11 — the CRITICAL one, since role frontmatter grants tools the runtime does not deliver), convert the string-presence wiring tests into behaviour tests (DF-19), give the boundary gates real negative controls, stand up `packages/` and `content/`, and guard a recorded critic proof from silent invalidation (DF-22, W0-S15).
**Worktree:** /Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness
**Base commit:** 5be42280615c8dc5321061798240f476dffed645
**git_custody:** lane

## File scope

- Exclusive (OWNED):
  - `packages/`
  - `content/`
  - `agents/`
  - `commands/`
  - `skills/`
  - `hooks/`
  - `bin/`
  - `.github/workflows/`
- May read:
  - `crates/`
  - `scripts/`
  - `services/cli/`
  - `.shepherd/runs/v645/`
  - `.shepherd/shepherd.toml`

## Interfaces

- Consumes:
  - Nothing. Lane l5-harness has no Wave-0 predecessors outside itself.
- Produces:
  - `content/` single-source role and skill tree (consumed by W4's compiler)
  - `packages/` npm workspace skeleton (consumed by W4 distribution)
  - a runtime role-capability probe (consumed by every later dispatch)

## Do not duplicate

- ``.shepherd/runs/v645/reports/discovery-d1-harness.md` already contains the probed capability matrix for all three harnesses — read it before writing any adapter assumption`
- ``hooks/tests/test_v644_wiring.sh` is the anti-pattern W0-S12 replaces (grep-for-prose); `scripts/check-workspace.sh --self-test` is the pattern to copy`

## Steps

### W0-S2: a clean clone can spawn (DF-01)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S2 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S2 [ACCEPTANCE] exits 0.']
### W0-S5: dispatch doctrine matches the platform that actually ships (DF-02, DF-11, DF-E1)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S5 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S5 [ACCEPTANCE] exits 0.']
### W0-S6: declared capability becomes probed capability (DF-04, DF-E2)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S6 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S6 [ACCEPTANCE] exits 0.']
### W0-S7: `packages/` npm workspace skeleton

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S7 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S7 [ACCEPTANCE] exits 0.']
### W0-S8: `content/` single-source tree and the drift reconciliation

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S8 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S8 [ACCEPTANCE] exits 0.']
### W0-S11: role capability guarantees are unverified at runtime (DF-17, CRITICAL)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S11 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S11 [ACCEPTANCE] exits 0.']
### W0-S12: convert string-presence "wiring tests" into behavior tests (DF-19, HIGH)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S12 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S12 [ACCEPTANCE] exits 0.']
### W0-S13: give the boundary gates real negative controls (A1 finding #1)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S13 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S13 [ACCEPTANCE] exits 0.']
### W0-S15: a recorded critic proof must not be silently invalidated (DF-22)

- [ ] Read `.shepherd/runs/v645/plan.md` §W0-S15 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** ['Every runnable assertion in plan.md §W0-S15 [ACCEPTANCE] exits 0.']

## Lane acceptance

- [ ] `bash scripts/gate.sh full` exits 0
- [ ] `bash scripts/check-plugin.sh --self-test` exits 0
- [ ] a clean clone reaches a spawnable state without a manual `shctx init`
- [ ] every role's declared `tools:` is asserted against a RUNTIME probe, not a text grep
- [ ] `hooks/hooks.json` refuses a write to a plan carrying a valid critic proof

## Non-goals

- `conformance/`
- `scripts/`
- `services/cli/`
- `CHANGELOG.md`
- `README.md`
- `.claude-plugin/plugin.json` — all owned by lane l4-conformance this wave
- `crates/**` — no lane owns it in Wave 0
- Do NOT re-argue the operator's Option B scope decision; it is DECIDED

## Deviations

(append-only — the conductor records every mid-lane modification or choice
here: what changed, why, and the step affected; never rewrite prior entries)
