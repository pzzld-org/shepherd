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
- [x] `L2-S1` wave review clean (verdict PASS; findings text never returned, conductor re-verified independently)
- [x] `L2-S1` committed as `05aa4cd`
- [x] `L2-S2` implemented
- [x] `L2-S2` verified by conductor against ground truth (CLI path, independent of the test harness)
- [ ] `L2-S2` committed

## D6 (#320) disposition

The asymmetry is **intended at this boundary** and out of this lane's reach to remove.
`write-boundary` governs the typed write surface only; `evaluate_bash_tool` never consults
it. Closing it means statically inferring filesystem effects from arbitrary shell, which G2
makes a critic-RED escalation. Pinned by
`write_boundary_governs_write_but_bash_performing_the_identical_write_allows` in
`crates/core/tests/guard.rs`, with a third assertion proving `Bash` is not simply unguarded.
#320 closes citing `evidence/issue-320.md`.
