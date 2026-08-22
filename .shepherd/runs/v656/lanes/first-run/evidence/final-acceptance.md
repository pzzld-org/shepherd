# First-run final acceptance

## Scope

Issue #367 required no production parser change. One shared typed compatibility
path accepts string `paths.reports` values in ordinary and migration loading;
wrong types fail with source-file and dotted-key provenance. Issue #369 now
returns one operator-owned absent-state sequence:

`shepherd run init <run>` → invoke `plant` → invoke `spawn` again

Spawn does not initialize, plant, retry, mutate project setup, or invoke
`shepherd init --confirm` as a side effect.

## Verification

Monitor #74 passed deterministic package, locked CLI build, oracle, Claude, and
Codex regeneration/checks. Monitor #77 passed formatting, both exact loader
regressions, projection tests `5/5`, eval contracts, plugin checks, CLI content
compiler `5/5`, package/Claude/Codex/oracle checks, and `git diff --check`.
LSP diagnostics were clean. No threshold changed.

## Independent review

Initial review found stale base/source evidence. Two REDO rounds repaired every
BLOCKER/HIGH and also every MEDIUM/LOW evidence issue. Fresh final read-only
review workflow `748559dd-a169-46bf-8efd-03cbbeb22e67` returned `PASS` with no BLOCKER, HIGH, MEDIUM, or LOW
and made no edits.

## Acceptance

Accepted for root integration. Final exact-pushed-commit cross-harness,
cold-start Pi, full-gate, periodic-eval, and `110/110` conformance acceptance
remains release-level work.
