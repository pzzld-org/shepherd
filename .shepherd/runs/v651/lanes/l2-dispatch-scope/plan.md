---
lane: l2-dispatch-scope
run: v651
branch: v651-l2-dispatch-scope
worktree: .worktrees/v651-l2-dispatch-scope
base_commit: c7cc9c0
deliverables: [D5, D6]
issues: [323, 320]
source: ".shepherd/runs/v651/plan.md — projection of L2-S1 and L2-S2; the master plan is the authority"
status: executing
---

# Lane l2-dispatch-scope — self-healed projection

The run's `lanes/l2-dispatch-scope/plan.md` was absent at boot. This file is the master
plan's lane projection, recovered per the conductor boot contract. It restates nothing the
master plan does not already say; `.shepherd/runs/v651/plan.md` governs on any conflict.

## Steps

| Step | Deliverable | Wave | State |
|---|---|---|---|
| `L2-S1` | D5 (#323) + the `test_native_cli_contract.sh` failure | A | reproduced |
| `L2-S2` | D6 (#320) | B | measured |

## File scope (exclusive to this lane)

- `content/predicates/dispatch-scope.toml`
- `content/predicates/write-boundary.toml`
- `crates/compiler/package-content/content/predicates/dispatch-scope.toml` (generated projection)
- `crates/core/src/guard/engine.rs`
- `crates/core/tests/guard.rs`
- `hooks/tests/test_native_cli_contract.sh`

Anything outside this list is an escalation to root, not a lane decision.

## W0-GATE — discharged before any fix

- `evidence/issue-323.md` — `conductor -> planter` and `conductor -> shepherd` both `allow`.
- `evidence/issue-320.md` — `Write` denies, `Bash` allows, same role, same destination.

## Scope amendments granted by root (commit `4603686`)

1. `crates/cli/tests/guard_cli.rs` added to this lane — it was assigned to no lane, and the
   plan's own L2-S1 action 2 (add a `[[example]]`) could not be completed without it.
   Implemented as a parsed `N == M && N > 0` assertion, not a bumped literal.
2. `crates/compiler/package-content/**` replaces the single enumerated projection file,
   scoped as "whatever `scripts/generate-compiler-package-content.py --write` produces".

## Progress

- [x] boot verified (worktree, base `c7cc9c0`, clean tree, plan readable)
- [x] `W0-GATE` reproduction recorded for #323 and #320
- [x] `L2-S1` implemented (6 files + scope-amended `crates/cli/tests/guard_cli.rs`)
- [ ] `L2-S1` wave review clean
- [ ] `L2-S1` committed
- [ ] `L2-S2` implemented
- [ ] `L2-S2` wave review clean
- [ ] `L2-S2` committed
