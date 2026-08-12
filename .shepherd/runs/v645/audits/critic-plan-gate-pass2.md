# PLAN-GATE critic review — pass 2

**Reporter:** `shepherd:critic` (sonnet, `dispatcher: engineer-self-contained`) · **Run:** v645
**Target:** `.shepherd/runs/v645/plan.md` @ 2,356 lines · **Materialized by:** root (`dogfood.md` DF-11 /
GH #270) · 2026-08-12
**Cost:** 203,490 subagent tokens, 58 tool calls, 860s
**Registry:** `audit_findings` rows 11-16 (`pass2-` prefix), `deliverables` row 2 (`delivered`)

## Verdict

**PROCEED WITH CHANGES**

## Both pass-1 HIGH findings are fixed — verified against Stage Graph bytes, not prose

- **Finding 1 (decomposition).** `WAVE-2-IMPL.in_predicates = [{from: PLAN-GATE-POST-Q1, label: on-green}]`
  — the *only* path to it is `W1-GATE → OPERATOR-GATE-Q1 (pause) → PLAN-REVISION-POST-Q1 →
  PLAN-GATE-POST-Q1`. `W1-GATE.out_edges` no longer names `WAVE-2-IMPL` at all. **A conductor walking the
  graph mechanically cannot reach module-granularity Wave 2/3 steps without a fresh `@engineer`
  decomposition and a fresh `@critic` gate.** The explicit banner before Wave 2 ("Waves 2-3 are NOT
  dispatched from this plan") reinforces it in prose, but the graph *enforces* it, which is what matters.
  `W2-S3..S16`/`W3-S1..S29` remain module-granularity, correctly so — they are now labeled as scope/gate
  inputs for the post-Q1 decomposition, not dispatchable steps.
- **Finding 2 (stage graph).** `OPERATOR-GATE-Q1` is a real `type: pause` node between `W1-GATE` and
  everything downstream. Edge vocabulary (`on-amend`, `on-hard-stop`) is canonical, not invented.
  `PLAN-REVISION-POST-Q1` correctly carries exactly ONE `in_predicates` entry rather than a
  mutually-exclusive OR-join — the collapse for "both operator answers route through ONE node" is right.

## New findings this pass

### 1. `pass2-stage-graph-post-q1-deadlock` — HIGH, dispatcher-patch

**The Q1 fix introduced its own deadlock.** `PLAN-GATE-POST-Q1.out_edges` includes
`{to: PLAN-REVISION-POST-Q1, label: on-yellow}`, but `PLAN-REVISION-POST-Q1.in_predicates` has only
`{from: OPERATOR-GATE-Q1, label: on-amend}` — no entry matching `(PLAN-GATE-POST-Q1, on-yellow)`.

The critic verified the satisfaction mechanism directly rather than assuming it
(`skills/context/scripts/cmd_graph.sh` `_cmd_mark`): a downstream `in_predicate` is satisfied only on an
**exact `(predecessor, edge)` match**. The edge is dangling — mechanically dead. Compounding it,
`PLAN-REVISION-POST-Q1` is `type: single-agent`, not `type: loop`, so even a correct predicate could not
re-enter an already-`done` node; no reset transition exists in the state machine. **If the post-Q1 critic
pass returns YELLOW the conductor has no ready node and cannot invent one** — not hypothetical, since the
original `PLAN-GATE` returned exactly that once this sprint.

**Fix (one line, pure graph topology):** replace `PLAN-GATE-POST-Q1`'s
`{to: PLAN-REVISION-POST-Q1, label: on-yellow}` with `{to: HARD-STOP, label: on-yellow}`. Mirrors the
original `PLAN-GATE`/`PLAN-REVISION` pair, which has no loop-back either, and matches doctrine: revise
ONCE, pass-2 GREEN → READY, else ESCALATED.

### 2. `pass2-outcome-verification-q6-oracle-scope` — HIGH, dispatcher-patch

**The engineer's CRITIC-RED escalation on locked decision 3 is upheld.** Independently re-verified:
`grep -nE '(bash )?"?\$?(shctx|bin/shepherd)"? [a-z]' hooks/scripts/*.sh` isolated to executed lines gives
**exactly 5** CLI shellouts across **exactly 4** scripts — `dups_write_guard.sh:65`,
`seed_preflight_check.sh:64`, `teammate_idle.sh:57,88`, `user_prompt_submit.sh:102` — and `grep -c sqlite3`
on each confirms **3 of the 4 touch DB state exclusively through the CLI** (zero direct `sqlite3` calls).
#281's oracle as specified would let all five drift silently.

**The critic picked Option 1 (widen the oracle).** Option 2 is new invasive scope on live guards; Option 3
alone does not close the gap by the engineer's own admission.

**MUST-FIX-BEFORE-DISPATCH on `W0-S9`**, which sits in `WAVE-0-IMPL`, the first dispatchable wave. Add
Action 6 — *"Build `--suite=guard-cli` capturing exact stdout, exit code, and JSON shape for the 5 named
commands"* — and one `[ACCEPTANCE]` line: `conformance/run.sh --impl=python --suite=guard-cli; test $? -eq 0`.
Fully specified; a conductor applies it with no engineer redesign. **Decision 3's exact wording remains the
operator's call and does not block dispatch.**

### 3. `pass2-stage-graph-close-finalize-gradecap` — MEDIUM, dispatcher-patch

`CLOSE-SWARM`'s `on-grade-cap` out-edge to `CLOSE-FINALIZE` has no matching `in_predicates` entry on
`CLOSE-FINALIZE` (only `on-no-finding` is listed). Same dangling-edge defect class as #1, verified against
the same mark mechanism. **Pre-existing — not introduced by this revision — newly found this pass.**
One-line fix: add `{from: CLOSE-SWARM, label: on-grade-cap}` to `CLOSE-FINALIZE.in_predicates`. Any point
before Wave 4 closes is fine.

### 4. `pass2-mesh-correction-verb-split-inconsistency` — LOW, dispatcher-patch

The Wave2/Wave3 group-count split appears with three unreconciled figures. The current triad — 14
Typer-native / 29 hand-parsed / 27 real Wave-3 steps, 43 total — is self-consistent and is what Q1's sizing
table actually uses. But `W2-S3..S16`'s own "Measured scope" paragraph still states stale pre-A2 figures
("107 leaf verbs… 23 modules"), and Q2's "Open questions" still poses "29 vs 21" as unresolved even though
the Wave 3 section resolved it in the same document ("my earlier figure of 21 was wrong"). Not
scope-changing, but a coder or future engineer citing the stale numbers would misbrief Wave 3.

### 5. `pass2-seed-drift-classification-observation` — LOW, observation only

The SEED DRIFT MECHANICAL classification for #235/#266 is "defensible but borderline" against Phase-0
doctrine's own "implicates the sprint theme" escalation trigger, since the drift falsifies the seed's *own
headline justification examples*. The underlying facts were verified true: the v6.4.3 fix landed with 19
regression tests and zero live hits, and the Codex `prompts`/`commands` directories are genuinely absent on
this box (`find ~/.codex`). **Not blocking — recorded for the operator's awareness.**

## Dispositions from pass 1 — spot-checked, all genuinely applied

- **#3 (`worktrees`, tier a → 8 objects):** confirmed. `C10` lists all 8 by name including `worktrees`;
  `W1-S2 [ACCEPTANCE]` loops the existence check over all 8 plus `v_teammates_live`.
- **#5 (seeded `PRAGMA compile_options` predicate):** confirmed restored verbatim in `W1-S2 [ACCEPTANCE]` —
  `sqlite3 "$DB" "PRAGMA compile_options;" | grep -q ENABLE_FTS5` — with a note explaining why it does not
  contradict the assert-behavior-not-flag rule for `ENABLE_JSON1`.
- **#4, #6, #7, #8, #9, #10:** all independently spot-checked against live bytes (`Cargo.toml` for
  `tracing-subscriber` and `resolver = "3"`, the DF-07 causal-claim hedging, the `render.py` /
  `models_graph.py` exclusion). All genuinely applied.

## Unstated assumptions

- The Option-A recommendation assumes the harness-agnostic layer (`content/` + compiler + 3 adapters) is
  genuinely decoupled from the Rust verb surface. The critic checked the load-bearing table (`content/`,
  Codex TOML, Pi TS extension, guard scripts, `run.json`) against decision 5 (Python stays canonical until
  parity) and **it holds** — every consuming surface is satisfiable against the existing Python engine
  today. Not falsified.
- The headline figures are **exact, not approximate**:
  `find services/cli/shepherd_cli -name '*.py' -not -path '*__pycache__*' | xargs wc -l` = **42,560**;
  `find crates -name '*.rs' -not -path '*/target/*' | xargs wc -l` = **1,363**. The
  registry-crate-does-not-exist claim also checks out (241 lines across `lib.rs`/`error.rs`/`build.rs`/
  `tests/default.rs`).

## Scope cuts

**None proposed.** No new scope recommended — every fix is a bounded edit to an already-existing bracketed
section or graph node.

## Cheaper alternatives

For Q6, Option 2 (rewrite the 4 guards to read SQLite directly) is a genuinely new, invasive, unseeded
refactor — correctly rejected in favor of Option 1.

## Alignment check

- **The critic explicitly declined to arbitrate Q1 Option A versus Option B**: *"This remains operator's
  call, not mine to arbitrate; I did not manufacture a preference between A and B."* It found the trade-off
  stated fairly, with a real counter-argument (the predicate-spec dual-interpreter concern) and an honest
  fallback ("if the critic judges that reasoning wrong, Option A collapses"). It did not judge it wrong —
  the table is well-evidenced.
- The SUBTRACT-versus-parity-before-deletion tension (Q1-bis) is surfaced honestly with two concrete
  resolution paths and a clear recommendation — amend the seed with `expected_loc_delta`/`subtract_floor`
  before Wave 0. Sound.

## Questions the dispatcher must answer

- Fold in the two MUST-FIX conditions before their respective dispatch points: the `PLAN-GATE-POST-Q1` edge
  fix (before the sprint can ever reach a second Q1-gate pass) and the `W0-S9` guard-cli suite addition
  (before `WAVE-0-IMPL` dispatches).
- Confirm the `CLOSE-FINALIZE` `in_predicates` fix lands before `CLOSE-SWARM` ever runs.
- **No engineer revision is required for any of the above** — all four are fully-specified,
  conductor-appliable edits.
