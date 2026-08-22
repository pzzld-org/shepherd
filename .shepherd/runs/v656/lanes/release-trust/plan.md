# Wave 2 release trust lane

Base: `e35cabf4453aea63117456c4b6823ce29582b18e`
Source: `.shepherd/runs/v656/plan.md`, lane `release-trust`

## Owned paths

- `.claude-plugin/marketplace.json`
- `.claude-plugin/plugin.json`
- `.claude/settings.json`
- `.github/dependabot.yml`
- `.github/workflows/release.yml`
- `Cargo.toml`
- `QUICKSTART.md`
- `README.md`
- `docs/integration.md`
- `package.json`
- `packages/harness-claude/README.md`
- `plugins/shepherd/.claude-plugin/plugin.json`
- `plugins/shepherd/.codex-plugin/plugin.json`
- `scripts/install-shepherd.ps1`
- `scripts/install-shepherd.sh`
- `scripts/tests/test-release-installers.sh`
- `scripts/tests/test-version-bump.py`
- `scripts/version-bump.py`
- `services/eval/evals/run_eval.sh`
- `SECURITY.md`
- `scripts/check-deps.mjs`
- `scripts/tests/test-dependency-policy.py`
- `services/eval/evals/cases/v656/release-trust_bad.txt`
- `services/eval/evals/cases/v656/release-trust_good.txt`
- `services/eval/rubrics/release-trust.rubric.json`
- `services/eval/tests/test_release_trust_eval_pair.sh`
- `.shepherd/runs/v656/lanes/release-trust/plan.md`
- `.shepherd/runs/v656/lanes/release-trust/evidence/**`

Installer and integration-document paths extend the seed list only because the
current-URL inventory test proved they are active installation/runtime surfaces.
Historical `.shepherd/runs/**` attribution remains untouched.

## Steps

- [x] Add ignored-runtime and tracked-unclassified version-authority controls.
- [x] Replace current install/runtime FL03 URLs while preserving history and attribution.
- [x] Publish one typed compatibility report across native/component/package versions.
- [x] Remove unsafe shared Claude permission and personal automation defaults.
- [x] Add SECURITY.md and npm/Cargo/Actions Dependabot coverage.
- [x] Add deterministic reachable high/critical ownership and expiring-waiver policy.
- [x] Measure current dependency findings; do not upgrade speculative/unreachable packages.
- [x] Add release-trust periodic eval pair and deterministic wiring.
- [x] Run the complete lane gate and record evidence.
- [ ] Receive independent PASS with no BLOCKER/HIGH.
- [ ] Commit owned paths without pushing.
