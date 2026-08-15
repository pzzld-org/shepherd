# Luna documentation reconciliation

**Run:** `v645`
**Release:** `6.4.5`
**Owner:** Luna
**Scope:** public README, Claude plugin metadata, `docs/*.md`, and package README surfaces

## Outcome

Public documentation now describes one canonical native Rust `shepherd` CLI,
the typed `fl03:shepherd@6.4.5` WebAssembly Component Model boundary, thin
Claude/Codex/Pi adapters, Pi's required `SubagentProvider`, layout-v5 namespace
ownership, flat cross-run docs, and run-scoped artifacts.

The docs no longer promise the retired Python, Bash, Poetry, or JavaScript
compiler/guard authorities. Stable refusal-only native routes are named as
unsupported instead of being presented as working workflows.

## Files reconciled

- `README.md` rewritten around the canonical Rust build, command surface,
  Component Model targets, adapter contract, prompt budgets, and layout-v5.
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` now describe
  the harness-neutral engine instead of a six-agent Claude-only framework.
- `docs/configuration.md` now documents typed project/user tiers, migration-only
  legacy inputs, fixed layout-v5 paths, run ownership, secret hygiene, and the
  compiler's measured limits.
- `docs/integration.md` now documents the WIT boundary, three adapter limits,
  Pi provider requirements, shared identity/resume, and package gates.
- `docs/customization.md` now documents project doctrines, profiles, skills,
  branch patterns, and the rule that host-specific behavior stays in adapters.
- `docs/memory.md` now distinguishes `.shepherd/ctx`, the native registry, run
  artifacts, user defaults, and host-native prose memory.
- `docs/permissions.md` now describes host authorization, fail-closed behavior,
  descriptor-safe materialization, and narrow Claude permissions without
  recommending bypass modes.
- Package READMEs were audited against the current adapter/runtime cutover. The
  Claude, Codex, Pi, and component-runtime READMEs state that no adapter owns a
  second CLI or materializer.

## Claims intentionally not made

- No prebuilt binary matrix or hosted installer is claimed. The release workflow
  must provide and verify those assets before the README can advertise them.
- `sync` and `worktree` are documented as unsupported native routes.
- `eval run`, `dups --stdin`, `insights clear`, and arbitrary `export --out`
  writes are documented as refusal-only boundaries.
- No claim is made that the final v6.4.5 gate is green while the concurrent CLI
  Wave F work is still compiling.

## Verification

Passed:

- Markdown relative-link scan for `README.md` and `docs/*.md`: no missing local
  targets.
- `git diff --check`: clean for the documentation scope.

Blocked outside Luna's docs-only scope:

- `python3 scripts/check-plugin.py` reports two non-executable generated Claude
  hook files:
  `packages/harness-claude/hooks/dispatch-lifecycle.mjs` and
  `packages/harness-claude/hooks/guard-eval.mjs`.
  Root must resolve those file-mode/plugin-contract failures before calling the
  package or full gate green.

The package adapter tests and native gates were not altered or represented as
green by this documentation pass.

## Handoff

Root should review command examples against the final compiled `--help`, fix
the two hook executable bits or their contract, then rerun the full package,
Component, native, conformance, and layout gates. No commit or push was made by
Luna.
