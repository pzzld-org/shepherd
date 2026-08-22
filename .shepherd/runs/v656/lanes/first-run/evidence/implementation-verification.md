# First-run implementation verification

## Production finding

Issue #367 required no production parser change. The existing typed compatibility
schema accepts retired `paths.reports` as a string through ordinary loading and
layout-v5 migration loading. A wrong type still fails closed with both the
source file and dotted key. The new regression exercises both loader entry
points against the same typed and malformed inputs, so provenance cannot drift
between modes.

## First-run guidance

Authored `content/skills/spawn/SKILL.md` now stops before dispatch when the run
is absent or not planted and returns exactly one operator-owned transition:

`shepherd run init <run>` → invoke `plant` → invoke `spawn` again

Spawn does not initialize, plant, retry, or mutate project setup. It explicitly
forbids `shepherd init --confirm` as a spawn side effect. Compiler-owned Claude,
Codex, and compiler-package projections preserve that text. A scratch mutation
that removes the action makes projection checking fail.

## Deterministic regeneration

Monitor #73 exposed the unchanged aggregate Claude skill budget: the initial
90-word block exceeded 3,500 by 29. The same contract was reduced by 34 words;
no threshold changed. Monitor #74 then passed package-content generation,
locked CLI build, content-oracle generation/check, Claude generation/check,
and Codex generation/check.

## Focused verification

Monitor #77 exited 0:

- `cargo fmt --all -- --check`;
- both exact `paths.reports` loader regressions;
- compiler-package projection tests: `5/5`;
- first-run eval contract and full deterministic eval suite;
- plugin contract;
- CLI content compiler tests: `5/5`;
- compiler package, Claude, Codex, and oracle checks;
- `git diff --check`.

LSP diagnostics are clean for the changed Rust and Python tests.
