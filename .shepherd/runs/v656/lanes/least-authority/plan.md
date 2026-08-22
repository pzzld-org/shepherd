# v656 lane plan: Native least authority

Owning lead: shepherd:conductor run v656 least-authority
Base commit: 6837e109ab618e3d22cb34c637de8ed7b7da7c69
Source: `.shepherd/runs/v656/plan.md`, lane `Native least authority`

## Exclusive scope

- `crates/cli/src/cmd/native_hook.rs`
- `crates/cli/src/dispatch_service.rs`
- `crates/cli/tests/dispatch_cli.rs`
- `crates/cli/tests/claude_hook_cli.rs`
- `crates/core/src/dispatch/portable.rs`
- `crates/core/src/dispatch/record.rs`
- `crates/core/src/dispatch/scope.rs`
- `crates/core/src/guard/engine.rs`
- `crates/core/src/guard/model.rs`
- `crates/core/tests/dispatch.rs`
- `crates/core/tests/guard.rs`
- `content/predicates/write-boundary.toml`
- `crates/compiler/package-content/content/predicates/write-boundary.toml`
- `crates/compiler/package-content/SHA256SUMS`
- `services/eval/evals/run_eval.sh`
- `services/eval/evals/cases/v656/least-authority_good.txt`
- `services/eval/evals/cases/v656/least-authority_bad.txt`
- `services/eval/rubrics/least-authority.rubric.json`
- `services/eval/tests/test_least_authority_eval_pair.sh`
- `.shepherd/runs/v656/lanes/least-authority/**`

## Steps

- [x] Boot verify worktree, base, source plan, owner, and clean lane scope.
- [x] Run exact baseline lane gates and reproduce #320/#334.
- [x] TDD RED tests for truthful dispatch scope and fail-closed Bash.
- [x] Smallest Rust-native implementation plus predicate and eval updates.
- [x] Adversarial auditor review and repairs until clean.
- [x] Final scoped gates and evidence.

The root session approved the listed scope expansions required by compiler-owned projection, dispatch-model invariants, hook integration, and eval wiring. Root retains commit and integration custody. No threshold change or issue mutation.
