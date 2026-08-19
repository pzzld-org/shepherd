# Lane l12-carrier — the published plugin ships a manifest naming files it does not contain

Run `v651`. Worktree `/Users/jo3/src/pzzld/shepherd/.worktrees/v651-l12-carrier`, branch
`v651-l12-carrier`, base `a0ca9a1`. Ledger: issue #339.

`plan.md` predates this lane and contains no `l12` projection. This file is the dispatch
brief self-healed into the lane namespace, per the lane-executor boot contract. Root
confirmed it will not retro-fit `plan.md`.

## File scope (exclusive)

Granted at dispatch: `plugins/shepherd/**`, `scripts/check-plugin.py`, `skills/plant/**`,
`bin/**`, `hooks/tests/test_plugin_contract.sh`.

Granted by root mid-lane, after l12 escalated three blockers (all verified by root before
granting): `content/skills/**`, `content/RECONCILIATION.md`, `.shepherd-generated.json`,
`hooks/hooks.json`. `skills/**` widens from `skills/plant/**` because `skills/` is a
compiler output and cannot be edited one directory at a time.

Not ours: `scripts/tests/test-release-*.sh` and `scripts/create-release-tar.sh` (l11),
`crates/**` (l4), `content/roles/**`, `content/predicates/**` (l2, closed).

## Defects

| # | Defect | Fix |
|---|---|---|
| D1 | Carrier ships a manifest naming 7 hook scripts it does not contain. Dead since 6.4.9. | Extend the symlink carrier with `hooks/scripts`. |
| D2 | Carrier declares a `bin/` on PATH it never packages, so bare `shepherd` never resolves. | Ship a Rust-CLI resolver shim + carrier link; move hooks.json under the gate. |
| D3 | `check-plugin.py` scans only the repo's `hooks.json`, never the carrier's, so D1 and D2 validate clean. | Scan every `hooks.json`, resolve each against its OWN plugin root. |
| D4 | `/shepherd:plant` deleted in v6.4.5 and never restored. | Author `content/skills/plant/SKILL.md`; let the compiler emit the carriers. |
| D5 | (found by l12) `compile --target claude --check` RED on the lane base: root hand-edited a compiler output in `cc07276`, compounded it in `0e2d27b`. | Move the block into the authored source, regenerate. |
| D6 | (found by l12) `test_plugin_contract.sh`'s falsification is vacuous: the scratch copy omits `.agents/` and `content/`, so the checker exits non-zero with NO drift injected. Green since the hour it was written. | Two-sided control: assert the undrifted baseline exits 0 FIRST, then drift. |

D5 and D6 are root's own defects, introduced this sprint. Attribute them as such in close.

## Waves

- **A** — L12-S1 `bin/shepherd` + `plugins/shepherd/{bin,hooks/scripts}` links.
        L12-S2 content authority repair (D5) + `plant` (D4) + regeneration. File-disjoint.
- **B** — L12-S3 `hooks/hooks.json` rewrite + `scripts/check-plugin.py` rules (D2, D3).
- **C** — L12-S4 `hooks/tests/test_plugin_contract.sh` falsification (D6) + carrier-script
        falsification, which the brief names as the deliverable's core.

Every wave gated by a read-only wave review before commit. No critic, no gate role
dispatched from this lane (#332); gates escalate to root.

## Constraints

- bash 3.2 ignores `set -e` for a line-initial `[[ ]]` (#340). Every assertion is
  `[[ ... ]] || { printf 'FAIL: <requirement>\n' >&2; exit 1; }`.
- Compiled skills 261-435 words, agent cards 308-553. Harness-neutral vocabulary.
- Baselines on `v6.5.1`: `cargo test --workspace --locked` 428/0. `bash hooks/tests/run.sh`
  29/29. `./scripts/check-plugin.py` green AND WRONG. `compile --target claude --check` RED.
- Commit to `v651-l12-carrier` and push. No merge to `v6.5.1`. Do not touch PR #328.

## Falsification is the deliverable

Twelve gates in this repository have been found this sprint that existed and could not
fail. l12 found the thirteenth. Every rule this lane adds must be shown going RED on a
drifted carrier, by command, in the close report.
