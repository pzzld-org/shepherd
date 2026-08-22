# First-run compatibility lane

Owner: shepherd:conductor v656-first-run
Base: 2d7fb8030f6f0095ebdf5f79817ad4c81bf09867
Source: `.shepherd/runs/v656/plan.md`, lane `First-run compatibility`
Issues: #367, #369

## Owned product and test files

- `crates/core/tests/loader.rs`
- `content/skills/spawn/SKILL.md`
- `skills/spawn/SKILL.md`
- `plugins/shepherd/codex/skills/spawn/SKILL.md`
- `.shepherd-generated.json`
- `conformance/content-target-final.json`
- `crates/compiler/package-content/SHA256SUMS`
- `crates/compiler/package-content/content/skills/spawn/SKILL.md`
- `scripts/generate-content-oracle.py`
- `scripts/tests/test-generate-compiler-package-content.py`
- `services/eval/evals/run_eval.sh`
- `services/eval/evals/cases/v656/first-run_good.txt`
- `services/eval/evals/cases/v656/first-run_bad.txt`
- `services/eval/rubrics/first-run.rubric.json`
- `services/eval/tests/test_first_run_eval_pair.sh`
- `.shepherd/runs/v656/lanes/first-run/plan.md`
- `.shepherd/runs/v656/lanes/first-run/evidence/**`

## Steps

- [x] Reproduce ordinary-load and migration behavior for typed `paths.reports`, plus wrong-type rejection.
- [x] Reproduce absent planted-state spawn guidance and baseline gates.
- [x] Add only the missing source-named loader regression if typed behavior is already green.
- [x] Update authored spawn guidance with one explicit initialize-run, plant-seed, spawn sequence and no implicit `shepherd init --confirm`.
- [x] Regenerate canonical, Codex, and compiler package projections with existing scripts.
- [x] Add deterministic projection tests, negative controls, and the v656 eval pair.
- [x] Run independent adversarial audits and repair every blocker/high reported in REDO rounds.
- [x] Run all lane gates and record durable evidence.
- [x] Receive a final independent PASS with no blocker/high.
- [x] Commit only owned paths without pushing.
