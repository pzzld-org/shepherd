# Lane l5-vocabulary — run v651, wave 2

Deliverables **D10 (#324)** and **D11 (#319)**. Branch `v651-l5-vocabulary`, forked from
`b0ad8aa` (wave 1 merged, CI-green). Conductor-owned; root gates and closes.

`file_scope.exclusive`: `crates/cli/src/cmd/wave_a_models.rs`,
`crates/cli/tests/wave_a_models_cli.rs`, `crates/cli/src/cmd/wave_b2_seed.rs`,
`crates/cli/tests/wave_b2_seed_cli.rs`. Plus this lane's own namespace
(`.shepherd/runs/v651/lanes/l5-vocabulary/`) and one additive `CHANGELOG.md` bullet per
global constraint G10.

## Pre-fix reproduction (conductor-measured, base b0ad8aa)

Recorded verbatim in `evidence/prefix-reproduction.md`. Both defects are live:

- **#324** `shepherd models resolve shepherd --harness claude` -> `ERROR: unknown role:
  shepherd (...)`, exit 2, while `resolve root` -> `opus[1m]`, exit 0.
- **#319** `shepherd seed verify .shepherd/runs/v646/seed.md` -> 2 HARD failures, exit 1;
  `.shepherd/runs/v651/seed.md` -> 1 warn, exit 0.

## Wave A — three file-disjoint steps, dispatched as one batch

| Step | Owner | Scope |
|---|---|---|
| `L5-S1` | coder `l5s1-models` | `crates/cli/src/cmd/wave_a_models.rs`, `crates/cli/tests/wave_a_models_cli.rs` |
| `L5-S2` | coder `l5s2-seedgate` | `crates/cli/src/cmd/wave_b2_seed.rs`, `crates/cli/tests/wave_b2_seed_cli.rs` |
| falsification harness | coder `l5-sandbox` | `.shepherd/runs/v651/lanes/l5-vocabulary/` |

### L5-S1 — decided direction

`root` stays canonical on the `models` surface; `shepherd` is a **stated** alias resolving to
it. Forced by two facts outside this lane's scope: `crates/core/src/settings.rs:546`
`ModelsConfig.root` is the literal `[models]` TOML key, and `docs/configuration.md:84` is
cross-checked against those field names by `scripts/check-workspace.sh` rule
`rule_model_defaults_match_the_docs`. Renaming would ripple into `crates/core` and `docs/`,
both named in the step's NON-GOALS. `ROLES` stays 9 entries; the alias normalizes at the one
validation site; the error text and USAGE are derived from the consts so the three
enumerations cannot drift.

### L5-S2 — decided semantics, two rules

1. **The `file_scope` resolution check is scoped to a seed that has not yet run.** A sibling
   `close.md` means the run closed, so the seed is a record rather than a proposal and an
   unresolved path degrades to a warning naming the reason. Every other seed keeps today's
   HARD failure byte-identical. Rejected: a frontmatter-date comparison (the verdict would
   change with the calendar), and resolving against the commit the seed names (needs git
   archaeology, which `L6-S1` is removing from a gate this same sprint; `base: main` is a
   moving ref; and `hooks/scripts/seed_preflight_check.sh:64` verifies a temp-dir copy that
   has no commit at all).
2. **The declared `kind` selects the smell threshold, not the hard ceiling.** 400 is the HARD
   ceiling for every seed regardless of label, so relabelling down buys no slack; a
   `patch-seed` over 200 gets a warning that names the mislabel. Both constants keep their
   exact values — no number moves, which is what the v6.4.6 carry-forward required.

Measured corpus that forced this (no invented threshold survives it):

| seed | `kind` | lines | deliverables | scope entries | `sprint_size` |
|---|---|---|---|---|---|
| v645 | `patch-seed` | 200 | 8 | 13 | `XL` |
| v646 | `patch-seed` | 393 | 10 | 14 | `M` |
| v651 | `sprint-seed` | 388 | 13 | 27 | `M` |

v645 declares `patch-seed` and `sprint_size: XL` in the same frontmatter, so the label is
already self-contradicting in the corpus; and no measured signal separates v646 from v645
(8 vs 10 deliverables, 13 vs 14 scope entries). Any tier threshold split on those would be
reverse-engineered from the answer.

## Falsification standard

`sandbox.sh --mode expect-abort|expect-fixed`, matching `l1-resolution/sandbox.sh`. After the
fix, `--mode expect-abort` must fail loudly and exit 1. Six negative controls prove the #319
relaxation is not a disabled check, including the pair that differs only by the presence of a
sibling `close.md`, and a closed-run seed with a `TODO:` marker that must still HARD-fail —
that last one is what proves the rule is scoped to one check rather than a global bypass.

## Gate for this lane

`GATE-EXECUTION`: every acceptance quotes `test result: ok. N passed` with N > 0.
Baselines at the fork point: `cargo test --workspace --locked` 417 passed / 0 failed;
`cargo test -p shepherd-cli --locked` 203 passed; `bash hooks/tests/run.sh` 29 files, 1 failed
(`test_workflow_meta_gate.sh`, owned by `l6-gate-wiring` in this same wave — left alone).

## Status

Successor conductor from here down: the first conductor lost its shell to #333
mid-wave. Its design work was picked up cold from this file and NOT redone.

- [x] boot verify, pre-fix reproduction recorded
- [x] wave A implementation (L5-S1 + both L5-S2 rules landed and measured)
- [x] falsification harness `sandbox.sh`, verified in all four configurations
- [x] wave A review (read-only, adversarial) — see the note below
- [x] CHANGELOG bullet (single owner, `l5-changelog`, 46 insertions / 0 deletions)
- [x] lane gates green, evidence recorded in `evidence/wave-a-gates.md`
- [ ] commit + push (conductor) -> root gates and closes the lane

## Review note

The first wave review halted at ~150k tokens (#332) and returned a bare
`REDO.` with no findings. It was re-asked for its findings and produced two,
both against the lane namespace rather than the production Rust, which it
reported clean. Both are resolved:

- Its B1 was real, and was a defect in a `sandbox.sh` that the coder
  `l5-sandbox` landed over the conductor's verified one at 05:22:07 after
  ignoring two status checks and a stand-down. That version asserted a run id
  that `seed verify` never prints, so `--mode expect-fixed` exited 1 against a
  correctly fixed binary. Rejected and replaced with the verified harness.
- Its B2 followed from B1: the recorded transcripts no longer matched the file
  on disk. Resolved by the same restoration; transcripts re-recorded verbatim
  in `evidence/sandbox-falsification.md`.

Two narrower reviews were then dispatched over disjoint halves of the diff,
sized to stay clear of the #332 wall.

## Carried forward, not fixed here

- **A sixth vacuous gate.** `crates/cli/src/cmd/wave_b2_seed.rs`
  `deliverable_blocks` recognizes a priority only as bracketed
  `[CRITICAL|HIGH|MEDIUM|LOW]` or a `**Priority:**` line. The v646 seed spells
  all 10 deliverables `### N. Title — BLOCKER`, so zero deliverable blocks are
  detected there and the HARD "N deliverable block(s) carry a priority but no
  `**GH:**` anchor" check validates nothing on that seed. Measured: v645 8/8
  detected, v651 13/13, v646 0/10, and v646 carries zero `**GH:**` anchors in
  the whole file. Fixing it would grow a NEW hard failure on v646 and break
  L5-S2's own acceptance that v646 exit 0. Needs a scope amendment or a
  carry-forward, not a sprint-time patch.
- **The `kind` tiering question is unanswered.** No measured signal in the
  corpus separates v646 from v645, and v645 declares `patch-seed` with
  `sprint_size: XL` in one frontmatter. Any threshold would be reverse-derived
  from the desired answer. With the operator.
- **`role_tier` still has no `root` arm.** `crates/core/src/guard/engine.rs`
  maps `"shepherd" => Some("root")` and knows no role named `root`. #324 is
  closed on the `models` surface only; `crates/core` is `must_not_touch` for
  L5-S1 by its own NON-GOALS.
