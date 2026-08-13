# CODER REPORT — W0-S10

- **Lane:** W0-S10 — the lane-plan template cannot render a spec-conformant plan (DF-16, HIGH)
- **Skills loaded:** `code-style` (loaded successfully). `markdown` — initially listed in `[SKILLS]`, does NOT exist in this environment (confirmed by direct `Skill()` invocation failure and exhaustive filesystem search — see "Halts encountered" below); corrected to `code-style` ALONE by the conductor's authorized mid-task correction (DF-25), independently verified against `.shepherd/shepherd.toml:39` (`by_domain = { shell = ["code-style"], markdown = ["code-style"] }` — a domain-key/skill-value table, not a skill name) and against the sibling halt already on record at `.shepherd/runs/v645/reports/coder-W0-S1.md`.
- **Files touched (created/modified/deleted):**
  - MODIFIED `services/cli/shepherd_cli/templates/lane-plan.md.j2`
  - CREATED `.shepherd/runs/v645/fixtures/lane-plan-spec.json` (scope-extension, pre-authorized by the conductor)
  - (report file itself: `.shepherd/runs/v645/reports/coder-W0-S10.md`, per Deliverable mandate, not file-scope production code)
- **LOC delta:**
  - `lane-plan.md.j2`: +20 / -6 (`git diff --stat`: "1 file changed, 20 insertions(+), 6 deletions(-)")
  - `lane-plan-spec.json`: +78 / -0 (new file, 78 lines; not a `*.rs` file so the ONE-LOC-rule Rust budget does not apply — noted for completeness, not as a governance claim)
- **Acceptance grep results:**

```
$ cd /Users/jo3/src/fl03/shepherd/.worktrees/v645-l4-conformance
$ bin/shepherd render lane-plan.md.j2 --vars-json .shepherd/runs/v645/fixtures/lane-plan-spec.json --out /tmp/lp.md
/tmp/lp.md
$ echo $?
0
$ grep -q 'must_not_touch' /tmp/lp.md && echo PASS || echo FAIL
PASS
$ grep -q 'parallel_with'  /tmp/lp.md && echo PASS || echo FAIL
PASS
$ grep -q 'W0-S10'         /tmp/lp.md && echo PASS || echo FAIL
PASS
```

  - `must_not_touch`: PASS
  - `parallel_with`: PASS
  - `W0-S10` (step_id rendered, not `step.id`): PASS
  - **Flag substitution used** (per the brief's own note that the plan's snippet might be imprecise): the plan's acceptance block used `--vars FILE`; the real `render` command (`services/cli/shepherd_cli/commands/render.py:7-8` docstring, confirmed by reading source) only defines `--vars-json FILE|-`. I used `--vars-json`, the actual flag.
  - DEDUP-GATE re-run (Step 3, before edit): `rg -n 'step\.id|step\.title' services/cli/shepherd_cli/templates/` → 1 line hit (`lane-plan.md.j2:57`, containing both patterns — matches the dispatch brief's phrasing "1 hit" and the plan.md formal entry's "expected 2 [pattern matches]"). Not a `DUPLICATION RISK`.
  - DEDUP-GATE re-run (after edit): same grep → 0 hits (`rg` exit 1 = no matches). Matches "expected 0 after."

- **Halts encountered:**
  1. `BRIEF INVALID — skill \`markdown\` listed in [SKILLS] not found. Halting.` — raised, then resolved by the conductor's authorized correction (DF-25): `[SKILLS]` for W0-S10 is `code-style` alone (`.shepherd/shepherd.toml`'s `by_domain` table has domain keys on the left, skill values on the right; `markdown` and `shell` both resolve to `code-style`, so whoever generated this plan's per-step `[SKILLS]` metadata copied the domain key instead of the skill value). Independently verified against `shepherd.toml:39` before resuming — did not take the conductor's word alone.
  2. No other halts. Worktree/base-commit verified clean (`pwd` = `[WORKTREE].Path`; `git rev-parse HEAD` = `5be42280615c8dc5321061798240f476dffed645` = `[BASE-COMMIT-EXPECTED]`) before any edit.

- **Decision + reasoning — Action 4 (underscore-flattening vs nested vocabulary):** ALIGNED to the plan schema's nested naming. `file_scope_exclusive`/`file_scope_may_read` → `file_scope.exclusive`/`file_scope.may_read`; `interfaces_consumes`/`interfaces_produces` → `interfaces.consumes`/`interfaces.produces`. Reasoning:
  1. `[USER-STYLE]` is explicit and directional: "The doctrine is the contract; the template conforms to it." This step exists BECAUSE the template invented a parallel vocabulary (`step.id`/`step.title`) diverging from doctrine's `step_id`. Fixing that one divergence while leaving a second, structurally identical divergence (flat vs. nested) in the same file would be inconsistent with the step's own stated purpose.
  2. Internal consistency: per-step access was already, and remains, nested (`step.actions`, `step.acceptance`, and now `step.file_scope.must_not_touch`) — Jinja's dot-notation resolves against dict keys natively, so nested access is free, not a workaround. Keeping the LANE-level vars flat while per-step vars are nested is a needless split vocabulary within one file.
  3. Verified zero coupling risk before deciding: `rg -n "file_scope_exclusive|file_scope_may_read|interfaces_consumes|interfaces_produces" --type py .` across the whole worktree returns zero hits — no Python caller hardcodes the flat key names (root/whatever materializes `vars.json` for this template is not itself a checked-in `.py` module I could find). `services/cli/tests/test_render.py` only asserts template-name membership (`"lane-plan.md.j2" <= names`), not this template's variable shape. So realigning carries no discovered blast radius, and I built the new fixture to the aligned shape myself (self-consistent, proven by the passing render above).
  4. `parallel_with` needed NO renaming either way — `agents/engineer.md §Lane projection` already lists it as a bare top-level field (`lane_id`, `member_steps`, `file_scope.exclusive`, `parallel_with`), so it was never part of the flattening question.

- **Placement decisions (not explicitly dictated by the brief, made explicit here):**
  - `must_not_touch` is **per-step only** — confirmed against `agents/engineer.md §Plan structure` (step schema: `step_id`, `file_scope{exclusive,may_read,must_not_touch}`, `predecessors`, `estimated_loc`, `actions`, `acceptance`, `interfaces`) vs. `§Lane projection` (lane schema: `lane_id`, `member_steps`, `file_scope.exclusive`, `parallel_with` — no `must_not_touch`). Rendered inside the `steps` loop as `step.file_scope.must_not_touch`, labeled `**must_not_touch:**` (mirroring the file's existing precedent of using the raw field name as a label for machine-relevant fields, e.g. the pre-existing `**git_custody:** {{ git_custody }}` line).
  - `parallel_with` is **lane-level only** (same `§Lane projection` citation) — added as a new `## Parallel lanes` section, placed directly after `## File scope` (before `## Interfaces`), since the brief itself frames the two together: "precisely the information the file-disjointness contract rests on."
  - `### {{ step.step_id }}: {{ step.actions[0] }}` for the step heading — chose the "map to first action line" option Action 1 offers over "omit the title," because `services/cli/shepherd_cli/commands/plan.py`'s `_LANE_STEP_RE = re.compile(r"^###\s+(?P<id>[^:]+):\s*(?P<title>.+?)\s*$")` (used by `_parse_lane_plan`/`_lane_drift`, feature #269, read for context only — NOT in file scope, NOT edited) requires a non-empty group after the colon; an id-only heading (`### W0-S10`) would fail that regex's `(?P<title>.+?)` (one-or-more) requirement. Confirmed the resulting heading (`### W0-S10: Change \`step.id\` -> \`step_id\` and drop...`) parses cleanly against that regex during manual review of the rendered `/tmp/lp.md`.

- **Deviations/blockers:**
  1. **Gitignore blocks committing the mandated fixture.** `.shepherd/runs/**` is ignored per `.gitignore:58`, with explicit exceptions only for `seed.md`, `mesh.md`, `plan.md`, `phase0.md`, `close.md`, `handoff.md`, and `lanes/*/plan.md` (confirmed via `git check-ignore -v .shepherd/runs/v645/fixtures/lane-plan-spec.json` → matched `.gitignore:58`). There is **no exception for a `fixtures/` subdirectory**, so `.shepherd/runs/v645/fixtures/lane-plan-spec.json` — which Action 3 explicitly says to "Commit" — will be silently skipped by a normal `git add`. The conductor will need either `git add -f .shepherd/runs/v645/fixtures/lane-plan-spec.json` at commit time, or a `.gitignore` amendment adding `!.shepherd/runs/*/fixtures/` (matching the existing exception style). `.gitignore` is outside my `file_scope` — flagging, not fixing.
  2. **Two out-of-scope downstream consumers are coupled to the field names this fix corrects** (read for context only, per "reading is fine" — neither is in `file_scope.exclusive` or `file_scope.may_read`, neither was edited):
     - `services/cli/shepherd_cli/commands/plan.py`'s `_parse_lane_plan`/`_lane_drift` (#269 lane-drift detection) hard-codes `for field in ("id", "title", "acceptance")` when comparing a rendered `plan.md` against its `vars.json`. Post-fix, the rendered `"title"` field now holds the step's first action text (there being no `title` in doctrine), while a doctrine-conformant `vars.json` correctly carries no `title` key at all — so `_lane_drift` will report a **permanent, spurious `title` DRIFT finding on every step of every lane** once real lane plans render through the corrected template. This is a genuine forward-looking regression risk of the DF-16 fix landing without a companion fix to `plan.py`. Recommend a follow-up step: update `_LANE_STEP_RE`'s consumers to key off `step_id` and either drop the `title` comparison entirely or redefine it as a derived (non-authoritative) display field excluded from drift comparison.
     - `services/cli/shepherd_cli/verdicts.py`'s `_PLAN_STEP_ID_RE = re.compile(r"\bW(?P<wave>\d+)-L(?P<lane>\d+)-S(?P<step>\d+)\b")` (used by `enumerate_plan_steps`, #262 ledger join) expects a `W<wave>-L<lane>-S<step>` id shape (e.g. `W3-L4-S1`), but the plan schema's real `step_id` values are wave-step only (`W<wave>-S<step>`, e.g. `W0-S10`, confirmed live in `plan.md` for every Wave-0 step). This mismatch **pre-dates this fix** — no lane plan could render at all under `StrictUndefined` before today, so this regex was already untested against real output — and is unrelated to Actions 1-4. Flagging as a pre-existing gap, not something introduced by or in scope for this step.
  3. No `cargo` commands run. No `git` write commands run (only read-only `git rev-parse`, `git status`, `git diff --stat`, `git check-ignore`, `git ls-files` for verification). No files outside `[FILE-SCOPE]` were edited.

- **Summary:** Fixed the `step.id`/`step.title` → `step_id`/first-action-line defect (Action 1), added `must_not_touch` (per-step) and `parallel_with` (lane-level, new `## Parallel lanes` section) to the rendered output (Action 2), committed-in-worktree a spec-shaped fixture and proved the fix by an actual render + grep pass, not just a source grep (Action 3), and aligned the top-level flattened variable names to the plan schema's nested vocabulary after confirming zero caller coupling (Action 4). Surfaced two out-of-scope downstream consumers (`plan.py`'s `_lane_drift`, `verdicts.py`'s `_PLAN_STEP_ID_RE`) whose hard-coded assumptions will misbehave against the corrected template — both flagged, neither touched.

## INSIGHTS

- kind: gap — `services/cli/shepherd_cli/commands/plan.py::_lane_drift`/`_parse_lane_plan` (#269) hard-codes `id`/`title` field comparison against rendered lane plans; once `lane-plan.md.j2` renders `step_id`-shaped headings with no real `title` field (this fix), every step of every lane will show a permanent spurious `title` DRIFT finding unless `plan.py` is updated in a follow-up step to compare `step_id` and drop/redefine the fabricated `title` comparison.
- kind: gap — `services/cli/shepherd_cli/verdicts.py::_PLAN_STEP_ID_RE` expects step ids shaped `W<wave>-L<lane>-S<step>` (e.g. `W3-L4-S1`), but the live plan schema's `step_id` values are wave-step only (`W<wave>-S<step>`, e.g. `W0-S10`) — this #262 ledger-join regex has likely never matched real rendered output, since no lane plan could render at all before this fix (`StrictUndefined` errored first). Pre-existing, unrelated to DF-16, worth a dedicated defect ticket.
- kind: gap — `.gitignore:58`'s `.shepherd/runs/**` ignore block has explicit exceptions for `seed.md`/`mesh.md`/`plan.md`/`phase0.md`/`close.md`/`handoff.md`/`lanes/*/plan.md` but none for a `fixtures/` subdirectory, so the fixture this step's Action 3 mandates committing will be silently skipped by a plain `git add` — needs `git add -f` or a new `!.shepherd/runs/*/fixtures/` exception line.

- **Reporter:** coder-W0-S10 @ 2026-08-13T00:44:34Z
