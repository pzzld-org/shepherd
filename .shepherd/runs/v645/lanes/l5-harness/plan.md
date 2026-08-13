# Lane l5-harness — Harness truth, the content tree, and the npm skeleton

**Run:** v645
**Objective:** Wave 0 for the lane that owns everything the three harnesses read. Make a clean clone able to spawn (DF-01), align dispatch doctrine with the platform that actually ships (DF-02/DF-11), turn declared capability into probed capability (DF-04, and DF-17 at W0-S11 — the CRITICAL one, since role frontmatter grants tools the runtime does not deliver), convert the string-presence wiring tests into behaviour tests (DF-19), give the boundary gates real negative controls, stand up `packages/` and `content/`, and guard a recorded critic proof from silent invalidation (DF-22, W0-S15).
**Worktree:** /Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness
**Base commit:** 5be42280615c8dc5321061798240f476dffed645
**git_custody:** lane

## File scope

- Exclusive (OWNED):
  - `packages/`
  - `content/`
  - `agents/`
  - `commands/`
  - `skills/`
  - `hooks/`
  - `bin/`
  - `.github/workflows/`
- May read:
  - `crates/`
  - `scripts/`
  - `services/cli/`
  - `.shepherd/runs/v645/`
  - `.shepherd/shepherd.toml`

## Interfaces

- Consumes:
  - Nothing. Lane l5-harness has no Wave-0 predecessors outside itself.
- Produces:
  - `content/` single-source role and skill tree (consumed by W4's compiler)
  - `packages/` npm workspace skeleton (consumed by W4 distribution)
  - a runtime role-capability probe (consumed by every later dispatch)

## Do not duplicate

- ``.shepherd/runs/v645/reports/discovery-d1-harness.md` already contains the probed capability matrix for all three harnesses — read it before writing any adapter assumption`
- ``hooks/tests/test_v644_wiring.sh` is the anti-pattern W0-S12 replaces (grep-for-prose); `scripts/check-workspace.sh --self-test` is the pattern to copy`

## Steps

### W0-S2: a clean clone can spawn (DF-01)

- [x] Read `.shepherd/runs/v645/plan.md` §W0-S2 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** DONE — `coder-W0-S2.md`: real clean-clone repro (`shctx doctor` 2-fail -> 0-fail, zero hand-run `shctx init`). All acceptance commands passed, verbatim output recorded.
### W0-S5: dispatch doctrine matches the platform that actually ships (DF-02, DF-11, DF-E1)

- [x] Read `.shepherd/runs/v645/plan.md` §W0-S5 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** DONE — `coder-W0-S5.md`: `commands/spawn.md` + `skills/harness/SKILL.md` corrected, layered cleanly on top of W0-S2's edit (verified, neither reverts the other). All 3 acceptance greps passed.
### W0-S6: declared capability becomes probed capability (DF-04, DF-E2)

- [x] Read `.shepherd/runs/v645/plan.md` §W0-S6 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** DONE (conductor-narrowed scope, see Deviations) — `coder-W0-S6.md`: `shepherd_mcp_available` added to `_lib.sh`, the two named stale `.claude/shepherd.toml` refs corrected. Redispatch (DF-25) succeeded.
### W0-S7: `packages/` npm workspace skeleton

- [x] Read `.shepherd/runs/v645/plan.md` §W0-S7 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** DONE — `coder-W0-S7.md`: workspace skeleton + `check-deps.mjs` gate with 3 rules, self-test, and a real-tree positive-control run. All acceptance commands passed.
### W0-S8: `content/` single-source tree and the drift reconciliation

- [x] Read `.shepherd/runs/v645/plan.md` §W0-S8 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** DONE — `coder-W0-S8.md`: 9 `content/roles/*.md` (all carrying `write_eligible`), `content/skills/*`, `content/RECONCILIATION.md` with a real decision per drift row, `content/predicates/*.toml`. Redispatch (DF-25) succeeded.
### W0-S11: role capability guarantees are unverified at runtime (DF-17, CRITICAL)

- [x] Read `.shepherd/runs/v645/plan.md` §W0-S11 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** DONE — `coder-W0-S11.md`: observed-vs-declared capability delta wired into `lint_agent_capabilities.sh` + `agent_invocation_tagger.sh`; `--self-test` proves it can fail. Redispatch (DF-25) succeeded.
### W0-S12: convert string-presence "wiring tests" into behavior tests (DF-19, HIGH)

- [x] Read `.shepherd/runs/v645/plan.md` §W0-S12 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** DONE — `coder-W0-S12.md`: every `need` assertion replaced with a real invocation or `UNVERIFIABLE-IN-TEST`; discovered a NEW live defect in the process — `shctx plan amend` is unreachable (`ERROR: unknown subcommand`) though `agents/shepherd.md:158` prescribes it verbatim; `shepherd plan amend` is the real form. Flagged to root/wave-review for disposition.
### W0-S13: give the boundary gates real negative controls (A1 finding #1)

- [x] Read `.shepherd/runs/v645/plan.md` §W0-S13 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** DONE — `coder-W0-S13.md`: 3 synthetic negative-control fixtures, `boundary-selftest.sh`, wired ahead of the 3 real gates in `boundaries.yml`. Cross-lane `rust.yml` addendum correctly REFUSED (DF-27); redispatched separately as W0-S16.
### W0-S15: a recorded critic proof must not be silently invalidated (DF-22)

- [x] Read `.shepherd/runs/v645/plan.md` §W0-S15 and execute its [ACTIONS] verbatim. The plan is the brief; this file is the index.
- **Acceptance:** DONE — `coder-W0-S15.md`: `plan_proof_guard.sh` (PreToolUse Write|Edit) + `hooks.json` wiring + `test_plan_proof_guard.sh` negative-control suite. Redispatch (DF-25) succeeded.
### W0-S16: fix `rust.yml`'s `check-plugin.sh` reference ahead of L4's rename (ad-hoc, conductor-authored)

- [x] Cross-lane fix: `.github/workflows/rust.yml:138,140` `check-plugin.sh` -> `check-plugin.py`, ahead of l4-conformance's W0-S1 rename (`.github/workflows/` is this lane's exclusive scope, not L4's).
- **Acceptance:** DONE — `coder-W0-S16.md`: surgical 2-line diff, both acceptance greps passed (0 remaining `.sh` refs, 2 `.py` refs).

## Lane acceptance

- [x] `bash scripts/gate.sh full` exits 0 — confirmed via this lane's own pre-push hook run (rustfmt, workspace invariants + self-test, plugin contract + self-test, clippy default+full, tests, 23-combo feature matrix, supply chain — all green, 59s) at commit `4ee106a`. (`scripts/` is L4's exclusive scope, not mine — I did not invoke this by hand; the repo's pre-push hook ran it.)
- [ ] `bash scripts/check-plugin.sh --self-test` exits 0 — STALE reference, see Deviations note: L4's W0-S1 renames this to `check-plugin.py`; not runnable as literally written once that lands. `.github/workflows/rust.yml` (mine) already updated (W0-S16); this template line in `## Lane acceptance` itself was not mine to fix.
- [x] a clean clone reaches a spawnable state without a manual `shctx init` — W0-S2, verified against a real clean clone.
- [x] every role's declared `tools:` is asserted against a RUNTIME probe, not a text grep — W0-S11 (CRITICAL), verified.
- [x] `hooks/hooks.json` refuses a write to a plan carrying a valid critic proof — W0-S15, verified via `test_plan_proof_guard.sh`.

## Non-goals

- `conformance/`
- `scripts/`
- `services/cli/`
- `CHANGELOG.md`
- `README.md`
- `.claude-plugin/plugin.json` — all owned by lane l4-conformance this wave
- `crates/**` — no lane owns it in Wave 0
- Do NOT re-argue the operator's Option B scope decision; it is DECIDED

## Deviations

(append-only — the conductor records every mid-lane modification or choice
here: what changed, why, and the step affected; never rewrite prior entries)

- **[Wave 0 dispatch, boot]** `WORKFLOW-VEHICLE-PROBE`: read my own visible tool list
  (top-level tools + the deferred-tool registry surfaced via ToolSearch this session) —
  the literal token `Workflow` is present in NEITHER. Per `agents/conductor.md` §Lane
  walk, a genuinely-absent `Workflow` means the Agent-Teams substrate was not live at
  spawn for this session, so I am silently an Agent-tool subagent regardless of my boot
  brief's teammate framing. Fan-out vehicle = in-context `Agent()`, whole `parallel_with`
  clique in ONE message — the correct and only option on this substrate, not a downgrade.
  `fanout: "in-context"`, `fanout_downgrade_reason: "workflow-absent-from-tool-list"`,
  `workflow_tool: "absent"`. NEVER used ToolSearch to run this probe itself
  (`WORKFLOW-SELFCHECK-TOOLSEARCH` avoided) — only to load already-known deferred-tool
  schemas (SendMessage/Task*), which is a different action.
- **[Wave 0 dispatch, boot]** Batch-1 fan-out = W0-S2, W0-S6, W0-S7, W0-S8, W0-S11,
  W0-S12, W0-S13, W0-S15 — all eight are mutually file-disjoint (verified by reading
  every step's `file_scope.exclusive` in `.shepherd/runs/v645/plan.md` before dispatch).
  W0-S5 is explicitly withheld from this batch: it shares `commands/spawn.md` with
  W0-S2 and the plan declares `predecessors: [W0-S2]` for exactly that reason
  (`plan.md:861-864`). W0-S5 dispatches after W0-S2's coder output is verified present
  in the worktree.
- **[W0-S6, dispatch]** SCOPE CORRECTION. The plan's literal `[ACCEPTANCE]` for W0-S6
  demands zero repo-wide hits of `.claude/shepherd.toml` (excluding CHANGELOG.md). I
  ran that grep myself before dispatch: 100+ hits across `services/cli/**`,
  `docs/configuration.md`, `examples/**`, `crates/core/tests/loader.rs`, `README.md`,
  and dozens of `hooks/tests/*.sh` fixtures. The overwhelming majority are CORRECT,
  intentional references to a real, permanently-supported legacy config tier
  (`docs/configuration.md`: "`.claude/shepherd.toml` pre-v6.4.2, honored forever").
  The plan's premise ("every hit resolves to nothing") is false for the corpus as a
  whole and true only for the two files the plan's own Evidence text names:
  `skills/shepherd/SKILL.md:20` and `hooks/tests/test_engineer_self_contained.sh`.
  Most implicated files are also outside this lane's `file_scope` entirely (owned by
  l4-conformance or unowned this wave) — a repo-wide rewrite is not mine to make and
  would break a documented backward-compat guarantee. I narrowed the coder's dispatched
  acceptance target to the two named files only, and extended the coder's writable
  scope to include `hooks/tests/test_engineer_self_contained.sh` (verified no other
  step/lane claims it — `grep -n test_engineer_self_contained .shepherd/runs/v645/plan.md`
  shows only W0-S6). Escalated to root as a non-blocking BRIEF-AMENDMENT via
  `SendMessage` — the lane proceeds on the corrected scope without waiting on a reply.
- **[W0-S13, dispatch]** Extended file_scope.exclusive to include the NEW
  `.github/scripts/boundary-selftest.sh` (the plan's actions/acceptance require this
  path but its file_scope.exclusive line only named `.github/workflows/boundaries.yml`).
  New sibling path under `.github/`, not `.github/workflows/` — no other lane or step
  claims `.github/scripts/`. Mechanical, not escalated.
- **[W0-S15, dispatch]** Extended file_scope.exclusive to include the NEW
  `hooks/tests/test_plan_proof_guard.sh` (referenced by the plan's own acceptance
  script but omitted from the exclusive list). `hooks/` is wholly owned by lane
  l5-harness this wave per the lane-level file scope, and no sibling step in this
  batch touches that path. Mechanical, not escalated.
- **[Wave 0 dispatch]** All eight coder briefs instruct the coder to write its full
  CODER REPORT to `.shepherd/runs/v645/reports/coder-<step_id>.md` and treat that file,
  not the chat return, as the contracted deliverable — per root's explicit boot
  instruction (DF-14 / GH #270: a dispatched agent's async completion can misroute).
- **[Wave 0 dispatch, DF-25 — root dispatcher-patch]** Every one of my eight briefs'
  `[SKILLS]` line was wrong: I wrote `code-style, shell` (W0-S2/S6/S11/S12/S13/S15) or
  `code-style, typescript`/`code-style, markdown` (W0-S7/W0-S8) — reading `shell` and
  `markdown` off `.shepherd/shepherd.toml [skills.by_domain]`'s KEYS. Those are domain
  keys, not skill slugs; the VALUES both resolve to the single skill `code-style`, and
  `typescript` was never in the config at all — I added it myself by wrong analogy.
  `agents/coder.md §Skills to load` treats a listed-but-uninstalled skill as a hard
  halt, no substitution. W0-S6, W0-S8, W0-S11, W0-S13 halted `BRIEF INVALID` on this
  before touching a file (confirmed via their written reports — zero files changed,
  worktree HEAD still clean at base commit); W0-S2/S12/S15 use the identical wrong
  line and are presumed likely to halt the same way once they reach it; W0-S7 (typescript)
  had already written real files (`packages/`, `package.json`) before this was caught —
  left running rather than duplicate-dispatched, to avoid a file-scope collision; its
  report will be checked for the same defect when it lands.
  **Fix, applied uniformly: `[SKILLS]` for every W0-S* step in this lane is `code-style`
  only** ([project].language = markdown, whose only by_domain skill is code-style,
  already covered by mandatory; no step writes `.rs` so `rust` is never added).
  Re-dispatched W0-S6, W0-S8, W0-S11, W0-S13 unchanged except that one line. Root
  logged the root cause as **DF-25**: nothing validates a brief's `[SKILLS]` entries
  against the installed skill set before dispatch, so the failure only surfaces after
  a coder has already spent its startup budget. Proposed to root as a candidate W0/W1
  step: a `shctx` verb (e.g. `shctx skills validate <brief-or-step-id>`) the conductor
  runs before every coder/auditor dispatch, checking each `[SKILLS]` entry against the
  real installed set (this repo's `skills/*/SKILL.md` dirs plus the user's global
  `~/.claude/skills/*`), failing closed with the exact bad slug before any Agent() call
  — turns this class of defect into a pre-dispatch millisecond check instead of a
  burned coder run.
- **[Cross-lane, W0-S13 addendum REFUSED — DF-27]** L4's W0-S1 renames
  `scripts/check-plugin.sh` -> `scripts/check-plugin.py`; `.github/workflows/rust.yml:138,140`
  still invoke the old name and `.github/workflows/` is my lane's exclusive scope, so the
  fix was mine. I tried to fold it into the already-in-flight W0-S13 coder via a
  `SendMessage` addendum (asserting `.github/workflows/` broadly as its scope). The coder
  correctly REFUSED: its own brief scoped it to `boundaries.yml` only, the addendum tried
  to widen that inline, and it could not authenticate the sender (a message claiming to be
  from its own conductor is unverifiable from inside the dispatch). Root backed the coder
  over me and made it binding for the rest of the sprint: a conductor may narrow a brief or
  correct a factual error inline, but may NEVER widen `[FILE-SCOPE]` by message — widening
  is a re-dispatch with an amended brief, always. Root logged this as DF-27, the mirror of
  W0-S2's coder self-substituting on a missing skill instead of halting (the two sibling
  coders made opposite calls under similar pressure; W0-S13's was the correct one under
  this specific rule). Redispatched the `rust.yml` fix as its own single-purpose coder
  step (`W0-S16`, ad-hoc, not in the original plan) rather than retrying the inline route.
- **[Cross-lane note]** Root/L4 found `scripts/gate.sh` does not loop over `[gates.extra]`
  at all — registering a checker there does not make it BLOCK anything, only
  close-finalize-ledger it. None of my W0 steps' acceptance assumes `[gates.extra]`
  enforcement (all use their own `--self-test` idiom, invoked directly), so this doesn't
  change any of my steps, but noting it so I don't introduce that assumption later in the
  lane.
- **[Cross-lane note]** DF-25's aftermath produced two corrections from root worth
  recording precisely: (1) `shell` and `markdown` were genuinely wrong (`by_domain` keys,
  not skills) — `code-style` alone is correct for every `.md`/`.sh`-only step in this
  lane, confirmed and not walked back. (2) The general rule I initially over-applied was
  wrong: `flock.md:54`'s mechanical extension map (`.py`->`python`, `.ts`->`typescript`,
  `.go`->`go`) IS doctrine, not an error, for any FUTURE step with a `.py`/`.ts`/`.go` file
  in scope — none of my Wave-0 steps had one, but a `.ts`-scoped step is coming in W4
  (the Pi adapter). Root has since authored and installed both `~/.claude/skills/python/
  SKILL.md` and `~/.claude/skills/shell/SKILL.md`; `typescript` is still genuinely missing
  and root is authoring it next — **any W4 step of mine with `.ts` files in scope must
  hold until that lands**, per root's explicit instruction.
- **[Wave 0, DF-35 — root's defect, not mine, but binding on my future dispatches]** All
  ten of this wave's coder reports (`coder-W0-{S2,S5,S6,S7,S8,S11,S12,S13,S15,S16}.md`)
  were written to the absolute MAIN-REPO path
  `/Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/`, per root's own DF-14
  boot instruction — which named a path without pinning it to the worktree. That path is
  OUTSIDE `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/`, so every one of my
  coders wrote a file outside its own confinement boundary; a sibling lane's coder (L4,
  W0-S10) correctly REFUSED an analogous out-of-worktree instruction and that refusal is
  what surfaced this. Root confirmed it is root's defect (logged DF-35), retracted nothing
  about the ten landed reports (no REDO, no rework), and gave the corrected convention for
  every future dispatch in this lane: brief coders to write reports to their
  WORKTREE-RELATIVE run dir (`{worktree}/.shepherd/runs/v645/reports/coder-<step>.md` —
  confirmed this directory already exists, empty, in my worktree), then `git add -f` them
  at commit time since `.gitignore:58` excludes `.shepherd/runs/**` except
  seed/mesh/plan/phase0/close/handoff.md. Applying this from W4 onward. Structural gap
  worth carrying into WAVE-COMPLETE as root asked: the coder confinement contract has NO
  enforcement mechanism (no hook, no guard) — it lived entirely in `agents/coder.md` prose
  and depended on each coder honouring it; nine of my ten did not even notice the breach
  (the instruction came baked into their original brief, not as a suspicious inline
  addendum), and only a sibling lane's coder catching an analogous case surfaced it at all.
- **[Note]** The lane's own `## Lane acceptance` line 2 (`bash scripts/check-plugin.sh
  --self-test`) will go stale the moment L4's W0-S1 rename (`check-plugin.sh` ->
  `check-plugin.py`) lands — `scripts/` is L4's exclusive scope, not mine, so I cannot fix
  this line myself even though it lives in my own lane plan's fixed template text (authored
  by the engineer, not by me). Flagging for root/close rather than silently leaving it
  wrong; W0-S16 already updated the ONE reference that was actually mine to fix
  (`.github/workflows/rust.yml`).
