## CODER REPORT
- Lane: W8-L4
- Skills loaded: `python`, `code-style` (python.md). No project-specific language skill was
  listed for this dispatch (the ledger's pointer doesn't carry a literal `[SKILLS]` block — see
  INSIGHTS below); `python` + `code-style` are the correct mandatory-minimum pair for a `.py`
  `[FILE-SCOPE]`, so I loaded them rather than halting on a technicality when the brief text
  itself was otherwise fully actionable.
- Files touched (created/modified/deleted):
  - `/Users/jo3/src/fl03/shepherd/services/cli/shepherd_cli/commands/run.py` (modified)
  - `/Users/jo3/src/fl03/shepherd/services/cli/shepherd_cli/models_run.py` (modified)
  - `/Users/jo3/src/fl03/shepherd/services/cli/tests/test_run.py` (modified — see scope note below)
- LOC delta: run.py +56/-6, models_run.py +122/-0, test_run.py +89/-1 (all Python; the ONE-LOC
  rule is `*.rs`-scoped, so none of this counts against any Rust LOC budget)
- Acceptance grep results:
  - `grep -n "def missing_declared_lanes" services/cli/shepherd_cli/models_run.py` → line 637 —
    PASS (the completeness check exists as a `RunState` method, alongside `pending_merges`)
  - `grep -n "missing_declared_lanes" services/cli/shepherd_cli/commands/run.py` → line 698,
    `wave_pending_cmd` calls it — PASS (wired into the gate, not just defined)
  - `grep -n "if pending or missing" services/cli/shepherd_cli/commands/run.py` → line 714 —
    PASS (exit 6 fires on EITHER the #242 pending set OR a missing declared lane)
  - `grep -n "def test_wave_pending_gate_exit_code_mismatch_df63" services/cli/tests/test_run.py`
    → line 175 — PASS (falsifiable regression test present)
  - Falsifiability, direct CLI verification (see below) — PASS: exit 6 on the DF-63 shape, exit 0
    once fixed.
- Halts encountered: none. One scope note (not a formal halt, no live escalation channel
  available in this dispatch — flagged transparently instead, see below).
- Summary: Fixed #1 `GATE-EXIT-CODE-MISMATCH` / DF-63. `wave pending`'s #242 pending-set check
  (`RunState.pending_merges`) only ever iterates `state.lanes` — a lane that was fully worked but
  never `run lane add`-ed has zero rows there, so it was structurally invisible: absence read as
  "not pending" instead of "missing", which is exactly how the gate exited 0 against a live
  5-defect ledger (DF-63's `l3-surface` case). Added `models_run.parse_declared_lane_ids` (pure
  text parser: reads a run's `plan.md`, finds `## Lane projection`, extracts the `lane_id` column
  of its table, lowercases/strips backtick decoration) and `RunState.missing_declared_lanes`
  (declared-minus-registered set difference, case-insensitive). `wave_pending_cmd` now reads
  `plan.md` via a new `_plan_text_or_empty` helper, computes both `pending` and `missing`, and
  raises exit 6 if either is non-empty — printing `lane<TAB>sha` rows for pending-merge lanes
  (unchanged) and new `lane<TAB>MISSING-DECLARED-LANE` rows for declared-but-unregistered ones.
  `--json` output shape changed from a bare list to `{"pending": [...], "missing_lanes": [...],
  "ok": bool}` (a deliberate breaking change — no consumer outside `test_run.py` parses this
  shape; grepped `agents/`, `commands/`, `skills/` for `wave pending` callers, all check exit
  code only, never `--json`). Absence of a `plan.md` or of a `## Lane projection` section is
  never an error — it means "nothing declared," so the check is a no-op, keeping every
  pre-#1 run backward compatible. Verified this exact backward-compat path directly (see below).

  **Falsifiability evidence (RESOURCE DISCIPLINE #256 — I did not run pytest; I drove the real
  CLI directly, `${PY} -m shepherd_cli ...`, in an isolated scratch tmp dir, which is the
  deliverable itself, not "the project's test/build command"):**
  ```
  # run plan declares 3 lanes (l1-engine, l2-registry, l3-surface); only 2 registered
  $ shepherd run wave pending v641-dev0
  l3-surface	MISSING-DECLARED-LANE
  EXIT CODE (missing lane, text mode): 6
  $ shepherd run wave pending v641-dev0 --json
  {"pending": [], "missing_lanes": ["l3-surface"], "ok": false}
  EXIT CODE (missing lane, --json): 6

  # after `run lane add v641-dev0 l3-surface`
  $ shepherd run wave pending v641-dev0
  EXIT CODE (complete ledger, text mode): 0
  $ shepherd run wave pending v641-dev0 --json
  {"pending": [], "missing_lanes": [], "ok": true}
  EXIT CODE (complete ledger, --json): 0
  ```
  Also replayed DF-63's *exact* measured live shape (the real `.shepherd/runs/v645/plan.md`
  parsed to `['l1-engine','l2-registry','l3-surface','l4-conformance','l5-harness']`; fed
  DF-63's own measured `run.json` lane set `['l4-conformance','l5-harness','l1-engine',
  'l2-registry','l6-guards']` — `l3-surface` absent, `l6-guards` extra) directly through
  `RunState.missing_declared_lanes`: returns exactly `['l3-surface']`, i.e. this fix catches the
  precise defect DF-63 measured, not just a synthetic analog. Also regression-checked: (a) the
  pre-existing #242 pending-merge-only path (no `plan.md` at all) still exits 0/6/0 correctly
  through accept→pending→merged; (b) a plan declaring `L1-engine` (uppercase, the live doc's
  actual casing) against a registered `l1-engine` (lowercase, the grammar `validate_id` enforces)
  correctly resolves as complete — case-insensitive comparison confirmed. `python -m py_compile`
  on all three touched files — clean (syntax check only, not the build/test command).

  **Scope note:** the dispatch named exactly two files as `file_scope.exclusive`
  (`commands/run.py`, `models_run.py`). The finding's own acceptance bar — "falsifiability is
  mandatory... write the test that FAILS... and PASSES... A gate that cannot fail is the sixth
  instance of that defect this run — do not add a seventh" — is a mandated deliverable I could
  not satisfy without a test file. No other W8 lane in this wave's table touches
  `services/cli/tests/`, so I added the falsifiable test (plus one regression test) to
  `services/cli/tests/test_run.py`, the existing home for this exact command's other tests, and
  updated one pre-existing test's `--json` assertion to match the (justified, non-consumed-
  elsewhere) shape change. Flagging this explicitly per the LOC-BUDGET-GOVERNANCE rule rather
  than silently expanding scope or silently dropping the mandated test.
- Reporter: coder-W8-L4 @ 2026-08-13T18:00:00Z

## INSIGHTS
- kind: gap — this brief's pointer (`.shepherd/runs/v645/reports/contradiction-ledger.md
  §W8-L4`) does not resolve: the ledger has no `W8-L4` heading or bracketed
  `[SKILLS]`/`[FILE-SCOPE]`/etc. brief block anywhere in it (confirmed via
  `grep -n "SKILLS\]\|FILE-SCOPE\]\|W8-L4"` — zero hits). The dispatch message itself carried
  the operative brief inline (file scope, finding #1 text, DF-63 cross-reference). Same shape
  already flagged by `coder-W7-S1.md`'s INSIGHTS — now measured a second time on the same run,
  confirming this is systemic to ledger-driven FIX-THIS-RUN dispatches, not a one-off.
- kind: extension — `parse_declared_lane_ids` reads ONLY the run's own `plan.md`. A future
  extension worth flagging: `wave_verify_cmd` (#262, the step/verdict join) already has an
  independent "declared" source in `verdicts.enumerate_plan_steps` (per-lane `plan.md` files
  under `lanes/*/`). The two "declared" concepts (lane projection vs. per-lane step plans) are
  siblings, not yet joined — a run could theoretically declare a lane in `## Lane projection`
  whose `lanes/<lane>/plan.md` was never materialized at all. Out of this finding's scope (#1 is
  specifically about the `run.json` ledger vs. the lane projection), but worth a future DF entry
  if `lanes/<lane>/plan.md` absence turns out to be a live failure mode too.
