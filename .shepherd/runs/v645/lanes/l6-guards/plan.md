# Lane l6-guards — Make dispatch doctrine mechanical (DF-44)

**Run:** v645
**Objective:** Two dispatch rules that are written down and unenforced get a mechanical guard, and the guard that enforces them gets its first self-test. This lane exists because root violated `agents/auditor.md:92` on a live lane's wave-review gate and nothing stopped it. Prose doctrine is advisory; only what a hook denies is binding.
**Worktree:** /Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards
**Base commit:** ada05dd
**git_custody:** lane

## File scope

- Exclusive (OWNED):
  - `hooks/scripts/dispatch_guard.sh`
  - `hooks/tests/test_dispatch_guard.sh` (EXTEND — see Deviations: this file already
    exists and is wired into `hooks/tests/run.sh`; there is no top-level `tests/` dir
    in this repo)
  - `skills/context/scripts/cmd_teammate.sh`
  - `skills/context/tests/test_cmd_teammate.sh` (EXTEND — see Deviations)
- May read:
  - `agents/auditor.md`, `agents/conductor.md`, `agents/shepherd.md`
  - `hooks/hooks.json`, `hooks/scripts/*.sh` (for the emit_deny/emit_context idiom)
  - `tests/` (for the existing gate-test idiom)
  - `.shepherd/runs/v645/dogfood.md`
- MUST NOT TOUCH: `crates/**` (l1 and l2 are live in those trees), `conformance/**`

## Steps

Three steps, file-disjoint, dispatch all three as **separate `@coder`s**. Do not write any
of them yourself — that is DF-42, recorded against l2-registry this same wave.

- [ ] W2-G1 — `hooks/scripts/dispatch_guard.sh`: Check 7 (deny) + Check 8 (recorder, retargeted)
- [ ] W2-G2 — `hooks/tests/test_dispatch_guard.sh` (extend existing)
- [ ] W2-G3 — `skills/context/scripts/cmd_teammate.sh`: `status`/`register`/`retire` crash

### W2-G1 — `hooks/scripts/dispatch_guard.sh`: Checks 7 and 8

Checks 1–6 exist; append 7 and 8 using the file's existing `emit_deny` / `emit_context`
idiom and its existing session-role detection (see Check 4's teammate-session handling
around line 107 — reuse it, do not invent a second mechanism).

**Check 7 — `AUDIT-CONCERN-UNDECLARED` (deny).**
Any dispatch with `subagent_type` = `shepherd:auditor` whose `tool_input.prompt` does not
declare exactly one concern is refused.
- zero `[CONCERN]` declarations → deny, message names the required form
- two or more → deny, message says to split into N dispatches, one concern each
- exactly one → pass
The authority is `agents/auditor.md:92`: *"brief's `concern` field is authoritative —
NEVER collapse two into one report."* The deny text MUST cite that line and MUST list the
valid concern slugs it found or expected, so the fix is mechanical for the dispatcher.
Match the declaration as a line of the form `[CONCERN] <slug>`; be strict about the form
(a prose mention of the word "concern" is not a declaration) and say so in the message.

**Check 8 — `DISPATCH-OWNERSHIP-RECORD` (recorder, NEVER a deny — retargeted mid-wave, see
Deviations).** Original spec was `WAVE-GATE-USURPED`, a deny rule for root usurping a live
lane conductor's wave-review gate. Root retracted that finding: it never happened (root
misattributed a completion that merely *routed* to its session — dispatched by the
l2-registry conductor — as its own dispatch). **A deny-guard for a violation that has never
occurred is exactly the waste this lane exists to argue against, so the deny is gone.**

The REAL, twice-confirmed defect: a teammate's `Agent()` dispatch completes into the
task-tree owner's session, not the dispatcher's — so nothing in the framework answers "who
dispatched this agent." Check 8 becomes a pure OBSERVER: on every `Agent()`/`Task` dispatch
where `subagent_type` starts `shepherd:`, append an ownership row to the registry before
passing (never denies, never blocks):
- dispatching session id, `subagent_type`, model
- lane, if resolvable from cwd or a `.worktrees/<lane>` path in the prompt (null otherwise
  — do not guess)
- the `[CONCERN]` slug when Check 7 found exactly one
- timestamp, and whatever join key the PreToolUse payload actually carries — inspect the
  real payload shape and use what is really there, do NOT assume a `tool_use_id` field
  exists
- **Fail-visible, not fail-open, not fail-closed.** Reuse the EXACT registry read/write path
  `hooks/scripts/teammate_idle.sh` / `hooks/scripts/coordinate_drive_guard.sh` use
  (`_lib.sh`'s `resolve_namespace` + `hook_db_path`) — do not open a second code path. If
  the registry is unwritable/unreadable, `emit_context` a warning naming the reason and
  PASS. Never deny on this check, ever, under any condition.

Both checks land in one file, so they are ONE coder, not two. That is the counterweight's
write test (`SKILL.md §Fan-out counterweight` rule 1): file-disjointness authorizes
concurrent writes, and these two are not disjoint.

### W2-G2 — `hooks/tests/test_dispatch_guard.sh` (EXTEND, not NEW — see Deviations)

`dispatch_guard.sh`'s checks 7 and 8 (added by W2-G1) have **zero** tests as of this
plan's authoring. A checker never shown to fail is not known to check anything. This
step ADDS fixtures for checks 7 and 8 to the EXISTING suite at
`hooks/tests/test_dispatch_guard.sh` (14936 bytes, checks 1–6 already covered,
`expect_block`/`expect_pass`/`expect_context`/`expect_silent` helpers already defined
— reuse them, do not redefine). Do not create a new top-level `tests/` directory.

One deliberately-broken fixture per rule, asserting the guard **DENIES** — checks 1, 2, 3,
4, 4b, 4c, 5, 7 (Check 8 is now a non-denying recorder — retargeted mid-wave, see
Deviations — it has NO deny fixture) — plus at least two positive controls asserting a
well-formed dispatch PASSES (a legal `shepherd:coder` step dispatch, and a legal
single-concern `shepherd:auditor` dispatch). Feed each fixture as PreToolUse JSON on stdin
and assert on **exit code and on the halt code in stderr separately** — a test that only
checks non-zero exit passes on the wrong rule firing.

For Check 8 specifically (recorder, not a deny rule): assert a well-formed
`shepherd:auditor` dispatch PASSES (no deny) AND leaves an ownership row in the registry,
and assert an unwritable/unreadable registry still PASSES with an `additionalContext`
warning rather than denying.

Follow the existing `hooks/tests/test_dispatch_guard.sh` idiom (same file, same
helpers) and keep it in the fast tier: pure stdin/stdout, no compilation, under 2s
total. bash 3.2 only — no `${var,,}`, no `declare -A`, no `mapfile`
(`~/.claude/skills/shell/SKILL.md`).

**Write this step against the CONTRACT above, not against W2-G1's implementation.** The two
steps run concurrently and that is deliberate: if the test and the guard disagree, that
disagreement is the signal. Run the suite only after both coders return.

### W2-G3 — `skills/context/scripts/cmd_teammate.sh`: `status`/`register`/`retire`/`heartbeat` crash

`shctx teammate status <name>` dies with `cmd_teammate.sh: line 183: $1: unbound variable`.
The `status)` branch reads `name="$1"` after the dispatcher has already consumed the
subcommand, so `$1` is unset under `set -u`. Fix the branch, and check the sibling branches
in the same `case` for the same defect rather than patching only the reported one.

**Widened mid-wave (see Deviations): `heartbeat)` at line ~136 has the identical defect**
(`name="$1"; shift` with no default) — found by the W2-G3 coder itself as an out-of-scope
report, folded in by root since it is the same defect in the same `case` in a file already
in this step's exclusive scope. Fix it using the same `name="${1:-}"; shift || true` +
explicit `[[ -n "$name" ]] || { usage; exit 2; }` pattern as the other three branches, with
its own regression test. **`liveness` and `prune` are confirmed clean** (flag-only
parsing, no bare positional) — do not touch them.

Add a regression test asserting `status` with a name returns a row and `status` with **no**
name exits non-zero with a usage message rather than a bash trace. The existing `shctx`
command tests live at `skills/context/tests/` (confirmed — `test_cmd_teammate.sh` already
covers `register`/`heartbeat`/`state`/`liveness`/`prune`/`retire`); add the new cases
there, following its existing idiom. Also check `register` (line ~51) and `retire`
(line ~247) — same `name="$1"` pattern with no default, same `set -u` exposure; `state`
(line ~166) already uses `name="${1:-}"` safely and is the reference fix shape.

## Acceptance

Per step, and none of these are satisfied by a command that exits 0 while printing nothing —
DF-41 was exactly that defect twice over. Read what each command actually prints.

- W2-G1: `bash -n hooks/scripts/dispatch_guard.sh` clean; shellcheck clean; Check 7
  demonstrated DENYING by hand with fixture JSON pasted into the report; Check 8
  demonstrated as a non-denying recorder — a well-formed dispatch PASSES and produces an
  ownership row, and an unwritable registry PASSES with a visible warning (never a deny).
  **Perf line corrected mid-wave (root's own retraction, see Deviations):** the suite's
  PRE-WAVE baseline already ran 2.37-2.48s (40 fixtures) before Check 7/8 touched anything
  — the original `<2s` line in this plan was baseline-unaware and unachievable when
  written. Measured under load-free conditions, Check 7/8 add ~7-9ms/fixture (54 fixtures
  now) → accept ~3.7s total. Do NOT chase 2s.
- W2-G2: `hooks/tests/test_dispatch_guard.sh` runs green, and **every** assertion (not
  just the new ones — the full file) is shown to be load-bearing — invert one fixture per
  rule, confirm the suite goes red, restore. Report the count of rules proven able to
  fail. If any rule cannot be made to fail, that is a finding about the guard, not about
  the test, and it gets escalated, not worked around.
- W2-G3: the regression assertions in `skills/context/tests/test_cmd_teammate.sh` pass for
  ALL FOUR fixed branches (`status`/`register`/`retire`/`heartbeat`) — each proven
  load-bearing by inverting the fix and confirming red, then restoring, matching the
  discipline already demonstrated for `status`; `shctx teammate status
  shepherd-conductor-v645-l1-engine` returns JSON; `shctx teammate status`/`register`/
  `retire`/`heartbeat` each with no name exit non-zero with a usage message, not a trace.
  SQL-escaping in `status`/`retire` (missing `esc()` around `$name`) is OUT of this step's
  scope — report only, root places it as its own step.
- Lane-wide: `./scripts/gate.sh fast` green (rustfmt/workspace/plugin invariants — this
  lane touches none of those, expected no-op) AND `hooks/tests/run.sh` green (the actual
  fast-tier runner for `hooks/tests/test_dispatch_guard.sh` — `gate.sh fast` does not
  invoke it) AND `bash skills/context/tests/run.sh` green (or
  `skills/context/tests/test_cmd_teammate.sh` directly if `run.sh` is slow) for W2-G3.

## Audit

Wave-review is split by concern — **one `[CONCERN]` per `@auditor` dispatch**, which is the
rule this lane exists to enforce, so do not violate it while landing it:

1. `[CONCERN] guard-fail-closed` — does check 7 actually deny; does check 8 (recorder,
   retargeted mid-wave — never denies) genuinely record an ownership row on a well-formed
   dispatch AND degrade visibly (warning, still pass) rather than silently on an
   unwritable/unreadable registry, for BOTH checks' registry-touching paths?
2. `[CONCERN] test-integrity` — is every assertion in the new suite load-bearing, or does
   any pass tautologically?
3. `[CONCERN] cmd-teammate-fix-completeness` — added mid-wave (see Deviations): W2-G3's
   original scope had no dedicated audit concern. Does the fix genuinely cover all four
   branches (`register`/`status`/`retire`/`heartbeat`) with the safe `${1:-}` + explicit
   guard pattern; are `liveness`/`prune` actually untouched and actually clean; is the
   SQL-escaping gap in `status`/`retire` accurately characterized (still present, correctly
   left unfixed per root's instruction, not silently patched or silently dropped from the
   report); does every one of the four regression assertions independently prove
   load-bearing (re-run each invert-to-red, not just trust the coder's report of having
   done so)?

Three concerns, three dispatches. Not one brief with two (or three) headings.

## Do not duplicate

- `emit_deny`, `emit_context`, `pass_silent`, `json_field` already exist in
  `hooks/scripts/dispatch_guard.sh`. Use them. Do not write a second JSON field reader.
- The teammate registry already has a read path used by `teammate_idle.sh` and
  `coordinate_drive_guard.sh`. Reuse it for Check 8.
- Check 6 already handles the fan-out-vehicle flag. Checks 7 and 8 are additive; do not
  restructure 1–6.

## Deviations

- **Boot materialization (Check 3, self-healing).** This lane plan predates/sits outside
  the standard `shepherd render lane-plan.md.j2` pipeline — the master plan's
  `## Lane projection` table (`{run_dir}/plan.md:2163`) lists only 5 lanes (L1/L2/L3/L4/L5);
  `l6-guards` is an ad-hoc 6th lane root spawned reactively mid-sprint (see the boot brief's
  "WHY THIS LANE EXISTS": root's own `agents/auditor.md:92` violation). So there is no
  `## Lane projection` row to reconstruct from, and none was needed: this plan already
  carries full, specific step content (far more detailed than a projection row would give),
  just under non-canonical headers — `## Acceptance` instead of `## Lane acceptance`, and
  steps in prose rather than a literal per-step `**Acceptance:**` line. Per §Boot
  verification's substance-over-form principle (applied analogously — the FACTS are
  extractable in any form), I am treating `## Acceptance` above as satisfying the
  `## Lane acceptance` requirement rather than duplicating it under a second header, and
  I added a 3-line `- [ ]` checkbox tracker directly above `### W2-G1` so each step can be
  checked off in place. This `## Deviations` section itself was absent and is added now,
  append-only from here forward.
- **`vars.json` step-content check.** `shepherd plan lane-drift v645 --lane l6-guards`
  reports FAIL (plan.md steps not mirrored in vars.json). Inspected `vars.json` directly:
  it carries only spawn metadata (`root_session_name`, `worktree_path`, `base_commit`, …)
  and has NO step-title/action/acceptance fields at all — for any of the 5 standard lanes
  OR this one. There is nothing in it to drift out of sync with, because this ad-hoc lane
  never went through the `render lane-plan.md.j2` step-content render pass #269 warns
  about. Every `@coder`/`@auditor` brief this lane dispatches is composed directly from
  THIS file's prose (`## Steps` conductor.md's Lane-walk WAVE-IMPL: "brief composed from
  the lane plan"), never from a vars.json render — so the #269 shadow risk does not apply
  here. Re-run `lane-drift` after any correction to this plan regardless, per doctrine.
- **SEED-DRIFT-MECHANICAL: W2-G2's target file was stale (DEDUP-GATE hit).** Ran the
  `## Do not duplicate` greps before WAVE-IMPL as required. The plan's original File
  scope named `tests/test_dispatch_guard.sh` as NEW, but this repo has no top-level
  `tests/` directory at all, and `hooks/tests/test_dispatch_guard.sh` already exists
  (220 lines, checks 1-6 covered, `expect_block`/`expect_pass`/`expect_context`/
  `expect_silent` helpers defined, wired into `hooks/tests/run.sh`'s invocation loop and
  referenced by `.github/workflows/claude-review.yml`/`release.yml`). Dispatching W2-G2
  against the stale path would have either failed outright or created a duplicate,
  unwired test file, exactly the DF-41 shape this lane exists to prevent one meta-level
  up. This is a moved-path/stale-symbol slip (conductor.md Mid-lane recovery), fixable
  without a root escalation: corrected File scope + W2-G2 + Acceptance sections above to
  target the EXISTING file (EXTEND, not create). Same check for W2-G3: confirmed
  `skills/context/tests/test_cmd_teammate.sh` already exists and already covers
  register/heartbeat/state/liveness/prune/retire, corrected the step to point there
  instead of inventing a fallback the plan's own contingency clause allowed for but the
  repo doesn't need. Also confirmed via direct read of `cmd_teammate.sh` that the
  `name="$1"` (no default, no shift guard) defect the plan named for `status` (line 183)
  is shared by `register` (line 51) and `retire` (line 247); `state` (line 166) already
  uses the safe `name="${1:-}"` form and is the fix's reference shape, folded into
  W2-G3's brief.
- **WORKFLOW-VEHICLE-PROBE (#263), run once before first fan-out.** Read my own visible
  tool list for the literal token `Workflow` (never `ToolSearch`, that resolves the
  deferred registry only and would be `WORKFLOW-SELFCHECK-TOOLSEARCH`). Result:
  NEGATIVE. `Workflow` is absent from both my directly-loaded tools (Agent, Bash, Edit,
  Read, Write, Artifact, Skill, ToolSearch) and the deferred-tool listing (SendMessage,
  TaskCreate/Get/List/Update, WebFetch, WebSearch, Monitor, EnterWorktree/ExitWorktree,
  Cron*, NotebookEdit, MCP tools, no `Workflow`, and no `Glob`/`Grep` either). This
  matches the engineer's own W0 probe result recorded at `{run_dir}/plan.md` §Proof of
  dispatch (same negative, same missing Glob/Grep), the Agent-Teams substrate was not
  live at spawn for this sprint's dispatching tiers. Per §Lane walk's negative branch:
  fan out in-context via `Agent()`, whole `parallel_with` clique in ONE message.
  `fanout: "in-context"`, `fanout_downgrade_reason: "workflow-absent-from-tool-list"`,
  correct and the only option here, not a downgrade to apologize for.
- **Dispatch with `name:` refused (flat roster).** All three coders were first dispatched
  with `name:` set (l6-w2-g1/g2/g3) so I could address them individually. All three were
  refused: "Teammates cannot spawn other teammates — the team roster is flat." Matches the
  engineer's own recorded "Flat-roster correction" at `{run_dir}/plan.md` §Proof of
  dispatch (DF-02's extension). Re-dispatched identically without `name:` (unnamed
  subagents); all three launched successfully, addressable afterward by their returned
  `agentId`.
- **W2-G1 brief correction (self-caught, post-dispatch).** My W2-G1 brief asserted Check 8
  "mirrors the existing ROOT-INTRO-USURPED shape one section over in this same file" without
  verifying it first. Grepped after dispatch: `ROOT-INTRO-USURPED` is a real halt code but
  lives only in prose doctrine (`skills/shepherd/references/escalation.md:107`,
  `agents/engineer.md:71`, `pipeline.md:60`) — it is NOT implemented anywhere in
  `hooks/scripts/dispatch_guard.sh`. Sent a `SendMessage` correction to the dispatched agent
  immediately (before it could waste time searching for nonexistent code), telling it to
  structure Check 8 like any of Checks 1-6 instead. No plan-content fix needed here since
  the error was only in the dispatched brief text, not in this file, but recording it per
  the append-only Deviations discipline since it's a mid-lane correction.
- **DISPATCHER-PATCH from root: Check 8 retargeted from a deny rule to a recorder.** Root
  retracted the finding this entire lane's original `WAVE-GATE-USURPED` deny check was
  built on: root checked its own transcript and found it authored zero `Agent()` auditor
  dispatches this session — the audit it believed was its own was dispatched by the
  l2-registry conductor, and its completion merely routed into root's session (the same
  routing defect the sprint has hit repeatedly — completions land with the task-tree
  owner, not the dispatcher). Root then wrote a CRITICAL finding accusing itself of a
  violation that never occurred and specified a deny-guard to prevent it. A deny-guard for
  a thing that has never happened is exactly the waste this lane exists to argue against.
  Check 7 (`AUDIT-CONCERN-UNDECLARED`) is UNCHANGED and re-confirmed: the bundled
  five-concern dispatch was real, just misattributed to the wrong author (l1-engine
  independently shipped an eight-item bundled brief in the same wave — two lanes, two
  instances). Check 8 is now `DISPATCH-OWNERSHIP-RECORD`: a non-denying observer that logs
  dispatcher/subagent_type/model/lane/concern-slug/timestamp for every `shepherd:*`
  dispatch, fail-visible (warn+pass) on an unwritable registry, NEVER a deny. Amended
  above: W2-G1's Check 8 spec, the `## Steps` checkbox line, the `## Acceptance` W2-G1 and
  W2-G2 lines (dropped the Check-8 deny fixture, added recorder-behavior assertions), and
  the `## Audit` concern-1 description. W2-G2's step text and W2-G3 needed no other
  changes — root confirmed W2-G3 (sibling-branch widening) was exactly right as scoped.
  Relayed both corrections to the already-dispatched W2-G1 and W2-G2 coders via
  `SendMessage` rather than waiting for their first return, since I had no evidence either
  was far enough into the deny-shaped Check 8 for a mid-course correction to cost more than
  finishing wrong — root's own instruction was to ship the retarget unless sunk cost said
  otherwise, and I had no signal of sunk cost either way.
- **W2-G3 completion routed to root, not me (4th instance today, per root).** Same
  misrouting defect as every other dispatch this sprint. Root relayed: clean PASS, all
  three named branches fixed via the `state` branch's existing safe pattern, load-bearing
  proven by inverting `status`'s fix to RED then restoring, full suite 50/50 green,
  `+26/-6`.
- **Root's plan text was wrong about the test path, not my execution.** Root independently
  confirmed (via its own `ls tests/`) that its original lane-plan prose
  (`tests/test_dispatch_guard.sh`) assumed a top-level `tests/` dir that does not exist,
  and that `hooks/tests/test_dispatch_guard.sh` — what I retargeted W2-G2 to at boot, see
  the earlier SEED-DRIFT-MECHANICAL entry above — is correct. Crediting this explicitly as
  root's plan-authoring error, per root's own request, not a self-correction of my
  execution.
- **`heartbeat)` unbound-`$1` fold-in (scope widened by root).** The W2-G3 coder found
  `heartbeat)` (line ~136) has the identical defect to the three branches it was asked to
  fix, correctly reported it as out-of-scope rather than silently widening. Root folded it
  into W2-G3 (same file, same case, same defect class, already in this step's exclusive
  scope) rather than spinning a separate step for one more branch. Amended `## Steps`
  (W2-G3 header + body) and `## Acceptance` above. Sent a follow-up `SendMessage` to the
  W2-G3 coder (agent `a338975964367b955`, resumed from transcript) asking for the same fix
  + regression test on `heartbeat)`, confirming `liveness`/`prune` stay untouched (root
  confirmed both clean — flag-only parsing).
- **SQL-escaping defect in `status`/`retire` — reported up, NOT fixed here.** The W2-G3
  coder also found `status)` and `retire)` interpolate `$name` into SQL without `esc()`
  (unlike `register`/`heartbeat`/`state`, which do escape) — the same shape as the
  already-fixed #234 apostrophe bug. Root classified this as a DIFFERENT defect class from
  the unbound-variable fix (SQL construction, not shell arg-parsing) and explicitly said
  not to fold it in — it gets its own step and its own test, placed by root. Recording it
  here per root's instruction to report it in WAVE-COMPLETE rather than work around it;
  NOT included in this lane's `## Steps`/`## Acceptance` and NOT fixed by W2-G3.
- **CANONICAL-HEADER GAP (root finding, applies to all three of my dispatches).** Root
  identified that my coder briefs used ad-hoc section names
  (`[INVOCATION-CONTEXT]`/`[FILE-SCOPE]`/`[HARD-RULES]`/`[TASK]`/`[ACCEPTANCE]`/`[REPORT
  FORMAT]`) instead of the seven canonical bracketed headers `agents/coder.md` §Startup
  Protocol Step 0 actually parses: `[SKILLS] [CONTEXT-INVENTORY] [DO-NOT-DUPLICATE]
  [USER-STYLE] [FILE-SCOPE] [NON-GOALS] [ACCEPTANCE]` (a coder is supposed to HALT
  `BRIEF INVALID` on a missing one — the W2-G3 coder judged its `[TASK]` prose sufficient
  and proceeded instead, which avoided a cascade but means the shape violation went
  unenforced, not unreal). Root's point: dispatching to a `@coder` at all is not by itself
  what makes DEDUP-GATE/`[SKILLS]`/`[DO-NOT-DUPLICATE]` run — the BRIEF HEADERS are what
  make them run, and mine didn't carry them. Sent header-retrofit `SendMessage`s to the
  two still-in-flight coders (W2-G1 `a0b78876849fcdc8a`, W2-G2 `a3d2c2cae1ade0151`) mapping
  my existing content onto the seven canonical headers + explicit `[SKILLS]: code-style,
  shell` (neither original brief told them to load a Skill at all — a real gap, not just a
  labeling one). W2-G3's heartbeat fold-in follow-up also uses canonical headers. Applying
  this to every remaining dispatch in this lane, including wave-review.
- **W2-G3 COMPLETE (heartbeat fold-in included) — relayed by root, not received directly
  (DF-46 confirmed structural, not a routing accident).** All four branches
  (`register`/`heartbeat`/`status`/`retire`) fixed with the identical
  `name="${1:-}"; shift || true` + `[[ -n "$name" ]] || { usage; exit 2; }` pattern;
  `liveness`/`prune` independently reconfirmed clean (flag-only parsing) and left
  untouched; `heartbeat`'s invert-to-RED repeated exactly as `status`'s was, both restored
  green; full `skills/context/tests/run.sh` 50/50; cumulative `cmd_teammate.sh` +12/-4,
  `test_cmd_teammate.sh` +25/-0; SQL-escaping in `status:187`/`retire:252` confirmed
  UNFIXED as instructed (vs `esc()` at :111/:148/:176) — carried to root for its own step,
  not fixed here. **Holding this uncommitted, not committing it now despite root's "stage
  and commit W2-G3" instruction**: this lane is ONE wave (three file-disjoint steps, not
  three waves), and conductor.md Hard Prohibition #10 + §Lane walk are explicit — commit
  custody is PASS-gated on an INDEPENDENT `@auditor` wave-review verdict, never a coder's
  (or a relaying lead's) self-report alone, and this lane exists specifically to make that
  kind of prose-vs-mechanical distinction binding. Root's own review of the coder's report
  is thorough but is not the audited gate. Added concern 3 above (`cmd-teammate-fix-
  completeness`) precisely because W2-G3 had no dedicated audit concern before now. Will
  stage + commit all three steps' files together as ONE wave commit once W2-G1 and W2-G2
  land and all three `[CONCERN]` auditor dispatches return PASS. Told root this explicitly
  rather than silently deferring the instruction unremarked.
- **W2-G3 crossed into `skills/context/**`, not `hooks/**`** — root flagged this is old
  l4-conformance territory; l4 is complete and merged, so no live file-scope collision, but
  noting it since this lane's own `## File scope` MUST NOT TOUCH list only names
  `crates/**`/`conformance/**` and didn't anticipate this. No action needed, recorded per
  root's request for the WAVE-COMPLETE payload.
- **DF-46 mechanism (root finding): `shepherd:coder`'s tool grant excludes `SendMessage` by
  design** (Bash/Edit/Glob/Grep/Read/Skill/ToolSearch/Write only — `agents/coder.md:7`), so
  a coder's ONLY output channel is its return value, which routes to the task-tree owner
  (root), never to the dispatching conductor. This is structural, not a misconfiguration —
  every coder I dispatch is fire-and-never-hear-back BY CONSTRUCTION, canonical headers do
  nothing to fix it (root's own correction to its earlier instruction: briefs fix what an
  agent KNOWS, not what it can SAY). Practical mitigation per root: tell root at dispatch
  time so root can relay: done for W2-G1/W2-G2 already (agent IDs given at dispatch), and
  I've asked root explicitly to relay those two completions since I have no other channel
  to receive them.
- **W2-G1 coder reports done — UNCOMMITTED, sitting in the worktree diff, NOT git history.**
  Relayed by root (coder report, not a review). Per the earlier PASS-gated determination:
  nothing here is committed and nothing here is a verified wave-review outcome yet — this
  is the coder's claimed diff, held in
  `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l6-guards/hooks/scripts/dispatch_guard.sh`,
  pending the `guard-fail-closed` auditor's independent re-verification before I stage or
  commit anything. Claimed: `+157/-0`, that file only, checks 1-6 unrestructured, reusing
  existing `emit_deny`/`emit_context`/`json_field`/`teammate_mode` idioms as instructed.
  Claimed: Check 7 (`AUDIT-CONCERN-UNDECLARED`) fired by hand for all three cases
  (zero/two/one `[CONCERN]`); Check 8 (`DISPATCH-OWNERSHIP-RECORD`) demonstrated as a
  non-denying observer with a real inspectable row and a lane-resolved row from a worktree
  cwd, degraded path proven (structurally-unwritable registry → `additionalContext`
  warning, no deny); `bash -n` clean; `shellcheck --severity=warning` clean (one
  pre-existing `SC1091` reported byte-identical against `ada05dd`); 54/54 against W2-G2's
  independently-authored suite. ALL of the above is the coder's self-report relayed through
  root, not yet independently verified by an `@auditor` — that verification is
  `guard-fail-closed`'s job at wave-review, still pending.
  Three questions I'd raised, answered by root (not decided by me alone): (1) denied
  dispatches get no ownership row — correct as shipped, do not restructure; a
  never-became-an-agent dispatch has no "owner" subject; an attempted-violation audit log
  is a different, real, but separately-scoped W2 decomposition item root is carrying.
  (2) **`$SHCTX_DB` acceptance guidance in my own brief was WRONG** — verified myself
  directly (`grep -n` against the base-commit `ada05dd` checkout, PRE-EXISTING code, not
  anything landed this sprint): `resolve_namespace()` at `hooks/scripts/_lib.sh:184` honors
  `$SHEPHERD_WORKDIR`/`$SHCTX_ROOT_OVERRIDE`, never `$SHCTX_DB` (that's the skills-side
  `shctx_db_path()`'s variable, a different code path entirely). The coder caught this
  independently in its own worktree copy and used a
  working equivalent rather than reporting a false pass — exactly the DF-41/DF-47
  "acceptance predicate that verifies nothing" family, caught before it shipped. **Sent an
  urgent correction to the W2-G2 coder** (still in flight, may have inherited the same bad
  `$SHCTX_DB` guidance from my own briefs for its fail-visible fixture) telling it to use
  `SHEPHERD_WORKDIR` instead and re-verify if it already built that fixture the wrong way.
  Carrying this in WAVE-COMPLETE per root's request so no other lane inherits it.
  (3) perf (one extra `sqlite3` spawn per `shepherd:*` dispatch) — accepted, not optimized,
  correctness on the audit trail is worth it at sprint-scale dispatch volume.
  **Follow-up, reported not fixed**: `dispatch_ownership`'s inline `CREATE TABLE IF NOT
  EXISTS` needs a real versioned migration under `skills/context/schema/migrations/` —
  correctly out of W2-G1's exclusive scope (that path + `shctx_ensure_migrated` both live
  outside `hooks/scripts/dispatch_guard.sh`, and l2-registry is live in migration
  territory); root is placing it as its own step.
  **Worth keeping**: the coder empirically verified on bash 3.2.57 that
  `var="$(pipeline)"` as the LAST element of a `&&`/`||` list DOES trigger `-e` under
  `pipefail` (contrary to "assignment absorbs command-substitution failure" folklore) and
  guarded every risky assignment with `|| true` on that basis — independent empirical
  confirmation of `shell/SKILL.md`'s documented exception, on the actual target shell,
  not assumed.
- **W2-G2 coder reports done — UNCOMMITTED, same PASS-gated status as W2-G1 above.**
  Relayed by root (coder report, not yet an independent auditor verdict). Claimed: 55
  assertions green; 10 of 10 rule-groups (1, 2, 3, 4, 4b, 4c, 5, 7, plus both Check-8
  recorder shapes) proven genuinely falsifiable by mutate-in-isolated-scratch-dir →
  confirm RED → restore from `.orig`, real repo file never touched (`git diff --numstat`
  confirmed clean afterward) — the exact discipline the lane plan's Acceptance section
  demands, not a self-report of having done it. Notable: the coder caught its OWN false
  GREEN (a fragile pattern-rename left a stray positional arg corrupting `env`'s argv,
  producing a passing result it didn't trust; redid it as a clean multi-line block
  replace, confirmed genuinely RED) — a coder finding a tautology in its own verification
  method, not just in the thing under test. Two disclosed fixture corrections: a
  case-sensitive `has("split")` vs the guard's actual `"Split into..."` string, and its
  own wrong assumption that an absent registry namespace should warn — the landed guard
  self-heals silently via `mkdir -p` (matching every other hook, which is correct) — it
  repurposed the fixture into a positive self-heal assertion rather than deleting it. Also
  fixed a PRE-EXISTING line-56 fixture (bare `shepherd:auditor`, no prompt) that passed
  before Check 7 existed and now legitimately fails it — added
  `"prompt":"[CONCERN] code-quality"`, preserving the fixture's original intent rather
  than papering over the new failure.
- **PERF REGRESSION (found by W2-G2, root's earlier "accept it" call retracted for the
  fast tier specifically).** Measured, not estimated: Check 8's `CREATE TABLE IF NOT
  EXISTS` + `CREATE INDEX IF NOT EXISTS` + `INSERT` with no pragma tuning costs +83ms per
  invocation (207ms vs 124ms against a byte-identical pre-Check-7/8 guard). The suite has
  ~40 dispatching fixtures → 0.8s baseline becomes 10.9s, a 13× regression against this
  lane's own stated <2s fast-tier acceptance line (`## Acceptance` above, now amended).
  Root's earlier perf answer ("accept it, dozens of dispatches per sprint") was right for
  PRODUCTION and wrong for the FAST TIER, which runs on every commit — root retracted it
  explicitly rather than let a wrong call stand once the real number existed. **Dispatched
  a perf-fix follow-up to the W2-G1 coder** (resumed `a0b78876849fcdc8a`, same scope,
  MUST NOT re-touch Checks 1-7 or Check 8's logic, only its connection pragmas/write
  pattern): `PRAGMA journal_mode=WAL` + `PRAGMA synchronous=NORMAL` on the Check-8
  connection first; batching/deferring the write is in scope if pragmas alone don't clear
  2s; thinning W2-G2's fixtures to hide the regression is explicitly out. Re-measure
  required before this closes.
- **DOCTRINE FINDING (W2-G2's second insight, root asked this carried into WAVE-COMPLETE):
  a new mechanical check landing SILENTLY invalidated an unrelated, pre-existing positive-
  control fixture** (the line-56 case above) and nothing caught it except running the
  WHOLE sibling file after landing, not just the new section. Standing recommendation for
  the wave routine: after a coder lands a NEW mechanical check, re-run sibling suites IN
  FULL as a mandatory step, not spot-check the new section alone — a silently-invalidated
  pre-existing positive control is a false-GREEN risk indistinguishable from a real pass
  until the whole file runs.
- **PERF CORRECTIONS (root retracted its own 13x-regression call and the <2s target;
  perf fix ACCEPTED at ~3.7s, not chasing 2s).** Two errors, both root's, both self-
  identified: (1) the `<2s` line this plan stated was baseline-unaware — the coder
  measured `git show ada05dd:hooks/scripts/dispatch_guard.sh` (zero Check 7/8 code) at
  2.37-2.48s across 3 runs, already over budget before this wave touched anything; (2) the
  13x figure (0.8s->10.9s) was measured while 22 concurrent `rustc` processes were live on
  the box — a load artifact, not a steady-state number. Corrected arithmetic: baseline
  ~59-62ms/fixture x 54 fixtures (fixture count rose 40->54 across the wave) ~ 3.19-3.35s
  before Check 7/8 does any work; actual 3.68-3.73s -> genuine per-dispatch cost ~7-9ms,
  not the 83ms figure taken under contention. Decision: accept ~3.7s, do not chase 2s;
  closing the remaining gap would mean touching Checks 1-6's own overhead or the runner's
  execution model, correctly outside this step. Amended `## Acceptance` above to the
  corrected line. **Pre-existing, separately-reportable finding, root is carrying it**:
  `hooks/tests/test_dispatch_guard.sh` was ALREADY ~2.4s against its stated `fast`-tier
  2s budget before this sprint touched it — a real fast-tier violation nobody had
  measured, predating every lane here.
- **W2-G1 perf-fix specifics, kept for the record (all still UNCOMMITTED, coder-reported
  via root's relay, pending `guard-fail-closed` auditor verification):** `PRAGMA
  journal_mode=WAL` confirmed active (`PRAGMA journal_mode` -> `wal`, was `delete`); two
  additional disclosed micro-optimizations — deferred `tool_use_id`/`model` `json_field()`
  extraction into Check 8's own block (Checks 1-6 denials stop paying for two subprocess
  spawns they never read) and `mkdir -p` guarded behind a `[[ -d ]]` builtin check after
  measuring the fork cost (1.24ms vs 0.04ms); connection-holding investigated and
  correctly ruled out (every hook here is a fresh OS process, no persistent daemon exists
  in this codebase — the coder checked rather than assumed). Claimed 54/54 across three
  consecutive runs, `bash -n` clean, `shellcheck --severity=warning` clean. **Flag for the
  `guard-fail-closed` auditor specifically**: the fail-visible warning text changed from
  `"registry write failed"` to `"registry directory create failed"` because the `mkdir`
  and `sqlite3` error paths are now separate branches — contract unchanged (never deny,
  always warn-and-pass, name path/subagent_type/tool_use_id/real error), but the auditor
  MUST confirm the split didn't leave a path that warns without actually naming the real
  error underneath it.
- **WORKFLOW-VEHICLE-PROBE re-verification, urgent, mid-wave — retracted in full, root's
  error not mine.** Root demanded a one-line re-answer (`Workflow`: present/absent) after
  discovering `agents/conductor.md`'s frontmatter grants `Workflow` and reasoning my three
  coders/three auditors should have compiled to Dynamic Workflows. Re-checked both my
  directly-loaded tool list and the deferred-tool listing: `Workflow` absent from both,
  same as `Glob`/`Grep`, unchanged from my boot-time probe (this file, earlier entry).
  Root verified independently (GH #263: availability follows `backendType`; in-process
  teammates are denied regardless of the frontmatter grant) and retracted in full — my
  `Agent()` fan-outs stand as correct, no `FANOUT-VEHICLE-DOWNGRADE`, nothing to redo.
  Root also found the master plan already recorded this exact fact at its own
  `plan.md:17-18` and that `plan.md:253` pre-refutes the theory root was chasing (that
  DF-46's routing defect might be a Workflow-vs-Agent() artifact) by citing GH #270 as
  vehicle-independent — root's own escalation cost was "one grep it never ran." Nothing
  changes for this lane's record or its auditors' grading.
  **One real, narrower finding survives root's retraction, carried forward per root's
  request**: reporting the `WORKFLOW-VEHICLE-PROBE` result to the dispatching lead BEFORE
  the first fan-out (not only inside `WAVE-COMPLETE`, which lands after every dispatch it
  would have governed) closes a real visibility gap — I probed and recorded correctly at
  boot, but root had no way to know the answer until asking directly, an hour and several
  dispatches later. Root has updated `boot-prompt.md.j2` for future spawns; does not apply
  retroactively to this session (`shepherd` on PATH resolves the 6.4.4 plugin cache, not
  this working tree — DF-54, root's problem to carry, not mine to fix).
- **LANE OWNERSHIP RE-ATTRIBUTION (root's error, not mine; work ships unchanged).** The
  master plan's `## Lane projection` fixes five lanes "total and constant across waves"
  (L1-L5) and assigns `agents/`, `commands/`, `skills/`, `hooks/`, `bin/` to L5-harness
  "for the entire sprint... no other lane writes them at any point, so the ownership claim
  needs no temporal argument to hold." l6-guards was created mid-Wave-1 as a reactive 6th
  lane over exactly that territory — the same "disjoint only because of sequencing" error
  the master plan itself names one paragraph above the table (originally an engineer
  rejecting an L4/L5 overlap draft) and root now names against its own l6-guards decision:
  W4-S3 (the `content/` compiler) emits into `hooks/`, so L5 WILL write these files.
  Root: nothing about this lane's next steps changes — finish the three auditors, one wave
  commit, WAVE-COMPLETE. Carrying root's two requested items into that payload verbatim:
  (1) **ownership re-attribution** — this wave's commits count as L5-harness territory for
  the close report's lane accounting, not a sixth lane's; (2) **hard input to W4-S3** —
  the compiler MUST treat `dispatch_guard.sh` Checks 7/8, `test_dispatch_guard.sh`'s
  Check-7/8 fixtures, and the four `cmd_teammate.sh` branch fixes as pre-existing content
  to PRESERVE, never as a tree to regenerate from scratch; an unabsorbed W4-S3 run would
  silently revert this entire lane three waves from now.
- **Cargo concurrency cap never applied (root's finding, does not touch this lane).** The
  master plan caps concurrent `CARGO_TARGET_DIR` holders at 2 (L1+L2 only; L3 builds only
  at its wave gate against shared warm `target/`; L4/L5 build no Rust at all). Root never
  enforced it — three lanes built concurrently, the swap monitor fired four times. Noted
  for completeness since it's readable in the same plan.md; l6-guards touches no `crates/`
  and holds no `CARGO_TARGET_DIR`, so it neither caused nor is affected by this.
- **`[CONCERN] test-integrity` — PASS (1 of 3 wave-review auditors in).** Agent
  `ab4d2db8254fc5ee9`, report at
  `{run_dir}/audits/audit-wave-review-l6-guards-w2-test-integrity.md`. Independently
  re-ran invert->confirm-RED->restore on 5 rule-groups itself (checks 1, 4c, 7, both
  Check-8 shapes) in an isolated scratch copy, all genuinely RED broken, real worktree
  files untouched (`git diff --numstat` identical before/after). All 7 briefed hypotheses
  tested and disproved: 54/0 across 3 runs post-perf-fix; Rule 7's inversion confirmed as
  the corrected clean-block form; both disclosed fixture corrections verified against live
  guard behavior; line-56 fixture confirmed non-colliding with the dedicated Check-7
  positive control; zero `$SHCTX_DB` anywhere in the file, `resolve_namespace()` confirmed
  `$SHEPHERD_WORKDIR`/`$SHCTX_ROOT_OVERRIDE`-only; `bash -n` clean both files.
  **One LOW, fixed in-wave rather than carried** (root's call left to me — took it,
  cheap and squarely this lane's thesis): the Check-8 unwritable-registry fixture used
  `chmod 500 .shepherd`, which the root unix user bypasses — run as root, the registry
  stays writable, no warning fires, and the assertion passes for the wrong reason. Latent,
  not live (auditor checked all 8 workflow files, confirmed no `container:`/root
  override — no current CI divergence), but a passes-for-the-wrong-reason assertion is
  precisely the DF-41 family this whole suite exists to eliminate. Dispatched the one-line
  fix (fail loudly / skip visibly on `EUID==0` rather than proceeding into an assertion
  that cannot hold) to the resumed W2-G2 coder (`a3d2c2cae1ade0151`).
- **`[CONCERN] cmd-teammate-fix-completeness` — PASS, 2 LOW, both folded into this round.**
  Agent `a87f31b783804aa6b`, report at
  `{run_dir}/audits/audit-wave-review-l6-guards-w2-cmd-teammate-fix-completeness.md`. All
  four branches confirmed carrying the exact pattern, all four regressions independently
  proven load-bearing in isolated scratch copies, `50/50` on `ctx_tests`, and the
  SQL-escaping gap confirmed present, unfixed, and NOT masked by the unbound-variable fix
  (`status "o'brien"` still errors identically post-fix — the two defect classes stayed
  genuinely independent). **Correction to my own earlier log entry**: I recorded the
  relayed `cmd_teammate.sh` diff-stat as `+12/-4`; the auditor's MEASURED actual is
  `+8/-4`. Correcting it here — `+8/-4` is the real number, `test_cmd_teammate.sh`'s
  `+25/-0` was right. LOW 2: the four no-name regression assertions grep the same literal
  usage-text substring rather than each branch's own output line — proven NOT a
  false-pass risk (4/4 still invert-to-RED correctly), but the coupling is loose enough to
  tighten. Dispatched to the resumed W2-G3 coder (`a338975964367b955`).
- **`[CONCERN] guard-fail-closed` — REDO. CRITICAL=1. This is the sharpest finding of the
  sprint and it lands on this lane's own thesis.** Agent `ab2cceb8c5d6030ef`. Check 6
  (`PRIMITIVE-INVERSION`, pre-existing, correctly left unrestructured) calls
  `emit_context()`, which unconditionally `exit 0`s, whenever `teammate_mode==1` (`cwd`
  under `.worktrees/`) and `subagent_type` is `shepherd:coder`/`shepherd:auditor` — and it
  sits TEXTUALLY BEFORE Checks 7 and 8. So it swallows every teammate-conductor's
  coder/auditor dispatch before either new check ever runs. The auditor did not infer
  this — it fired the LITERAL DF-43 shape (bundled 5-topic prompt, zero `[CONCERN]` tags,
  `cwd` under `.worktrees/v645-l6-guards`) against the live uncommitted file in an
  independent scratch repo and got only Check 6's advisory, no deny, and
  `dispatch_ownership` was never even created. My own Deviations log already names the
  real incident's actual topology — dispatched by the l2-registry CONDUCTOR, from a
  worktree — which is exactly the unreachable path. **The suite passed 54/54 while this
  was true because no fixture sets a `.worktrees` cwd** — every assertion exercised the
  root topology, where Check 6 never fires. W2-G2 proved every assertion COULD fail;
  nobody had asked whether the code under test was REACHABLE in the topology it targets.
  REDO scoped exactly as the auditor specified, dispatched as two coder follow-ups:
  (1) **W2-G1** (`hooks/scripts/dispatch_guard.sh` only) — relocate the Check 7 and Check
  8 blocks to execute immediately after Check 5 and before Check 6; pure textual
  reordering, zero logic change inside Checks 1-6 or 7/8. (2) **W2-G2**
  (`hooks/tests/test_dispatch_guard.sh` only) — add at least one Check-7 and one Check-8
  fixture with a `.worktrees` cwd set, proven RED against the CURRENT (pre-reorder)
  ordering first (that inversion IS the point), then GREEN after the reorder lands.
  Root's instruction: re-dispatch both coders, re-run `guard-fail-closed` ONLY once both
  land — `test-integrity` and `cmd-teammate-fix-completeness` are settled, re-auditing
  either is waste (their LOW fold-ins above are coder-side fixes, not re-audits).
  **Everything else in this report held**: Check 7's deny/pass logic, Check 8's
  never-deny guarantee and both fail-visible branches, the additive-only diff, `bash -n`/
  `shellcheck` clean. The defect is reachability and ordering, nothing else in the logic
  itself.
- **DISPATCH ERROR (mine): used `Agent()` instead of `SendMessage()` for the REDO round,
  risking a concurrent-write collision.** Dispatched all three REDO/follow-up fixes
  (W2-G1 relocation, W2-G2 fixtures+EUID, W2-G3 tightening) as brand-new `Agent()` calls
  instead of `SendMessage`-resuming the three original coders who already owned this
  worktree's context — the same pattern I'd used correctly for every prior follow-up this
  wave. Caught it immediately after dispatch. Checked all three originals: `a0b78876849fcdc8a`
  and `a338975964367b955` had no active task (idle, safely stood down, no collision).
  `a3d2c2cae1ade0151` had ALREADY COMPLETED the EUID-guard fix before my stand-down message
  arrived (confirmed by the resume call returning "stopped (completed)") — so no active
  concurrent write occurred there either, but it was close: had that agent still been
  mid-edit on `hooks/tests/test_dispatch_guard.sh` when the fresh `a4f661df7f6b3c346` also
  started writing to the same file, that would have been a genuine collision risk this
  lane's own file-disjointness discipline exists to prevent, just at the wrong granularity
  (same file, two sessions, not two different files). Resolved: told all three originals to
  stand down and make no further edits; the three fresh agents (`a8f6760abbf960f12` for
  W2-G1, `a4f661df7f6b3c346` for W2-G2, `a55486aefa2b49f9b` for W2-G3) are now sole owners
  of their files for this round. Told `a4f661df7f6b3c346` explicitly to re-verify the EUID
  guard's presence before acting rather than assume its own brief's premise, since the
  premise (item 2 possibly already done) turned out to be literally true.
- **W2-G1-REDO coder reports done — still UNCOMMITTED, sitting in the worktree diff, NOT
  git history; relayed by root, who says it independently re-verified rather than only
  accepting the report.** Agent `a8f6760abbf960f12`. Claimed: check order now
  `1, 2, 3, 4, 4b, 4c, 5, 7, 8, 6` (`grep -n "^# Check "`), pure relocation (486 lines
  before and after, `git diff --stat ada05dd` inside the worktree shows `190 insertions,
  0 deletions` against the uncommitted copy — this diffs the WORKING TREE against
  `ada05dd`, not a commit range, since nothing here is committed yet), done via a
  line-slice/reassemble with asserts on each slice boundary rather than retyping. Claimed:
  firing the literal DF-43 shape (bundled 5-topic prompt, zero `[CONCERN]` tags, cwd under
  `.worktrees/v645-l6-guards`) now gets the deny, not Check 6's advisory — the exact
  invocation that silently passed before. Claimed: full matrix re-confirmed — 1-concern
  non-teammate silent-pass+row, 2-concern deny (Check 8 never reached, no table created),
  teammate `.worktrees` coder now gets BOTH an ownership row AND Check 6's advisory
  (coexistence is the fix), `sqlite3` absent still fail-visible-warns, exit 0, never
  blocks; real worktree DB confirmed to have no `dispatch_ownership` table (no test
  pollution). One disclosed gap: the REDO brief didn't restate canonical bracketed
  headers and the coder proceeded rather than halting on a mechanical reorder of
  already-written code — root's own DF-49 finding, not mine, logged for completeness.
  ALL of the above is still a coder self-report relayed through a lead — the binding
  verification is the re-run `guard-fail-closed` auditor, still pending, once the other
  two REDO/fold-in coders land.
- **ROOT CAUSE OF THE FAN-OUT SUBSTRATE FOUND (root's finding, fully vindicates the
  boot-time probe and every downgrade decision this lane made).** `~/.claude/settings.json`
  sets `teammateMode: "auto"`; this session has no `TMUX` and `TERM_PROGRAM` is
  `Apple_Terminal`, not iTerm2 — with neither an own-session backend available, `auto`
  fell back to `in-process` for all six teammates this sprint (team config confirms it).
  In-process teammates run inside the lead's own process and the harness gates them as
  subagents verbatim — which is exactly why the real `Workflow` invocation above returned
  "not available inside subagents." So: the boot-time `WORKFLOW-VEHICLE-PROBE` was right,
  the in-context `Agent()` downgrade was right, GH #263 was right, `plan.md:17` was right,
  and every hand-rolled fan-out in this lane (three coders, three auditors, this REDO
  round) was the correct and only vehicle for the substrate actually given. The operator's
  separate claim that a genuine teammate CAN drive Dynamic Workflows was also right — ours
  simply never were genuine session-backed teammates. **Carrying into WAVE-COMPLETE as a
  root-owned finding, per root's explicit request**: spawn preflight must resolve the
  EFFECTIVE `teammateMode` (the configured mode plus `TMUX`/`TERM_PROGRAM`), and on a
  resolved `in-process` outcome, say so loudly and downgrade to root-drives-workflows
  rather than spawning conductors that can never compile one.
- **W2-G2-REDO coder reports done — still UNCOMMITTED, sitting in the worktree diff, NOT
  git history; relayed by root.** Agent `a4f661df7f6b3c346`. Claimed: two `.worktrees`-cwd
  fixtures added (Check 7 and Check 8), `+207/-2`, 54->57 assertions. Claimed proof method:
  reconstructed a faithful PRE-RELOCATION snapshot from its own earlier `Read` output
  (caught that a naive `cp` at that point would have captured the sibling's already-landed
  reorder instead of the actual regression — verified snapshot line count + check ordering
  matched pre-relocation), proved both new fixtures RED against that snapshot, then
  mutation-tested each against the FIXED file with only its own target check defeated
  (Check 7's condition neutered / Check 8's `INSERT` swapped for `SELECT 1`) and got RED
  for the right reason both times — falsifiability argued in both directions, not just one.
  **Doctrine call surfaced, root decided it, not me**: the pre-existing `#172
  engineer-self-contained` fixture dispatches `shepherd:auditor` with
  `dispatcher: engineer-self-contained` and no `[CONCERN]` tag — pre-relocation Check 6
  pre-empted it (vacuous pass), post-relocation Check 7 correctly denies it. Coder
  correctly refused to touch it under its own `[NON-GOALS]` and flagged it instead of
  guessing. **Root's ruling: the FIXTURE is wrong, add `[CONCERN]`, no carve-out.**
  `agents/auditor.md:92` is unqualified and shouldn't be qualified — the engineer's own
  discovery wave is >=3 intro-auditors split by area, concern-splitting BY CONSTRUCTION,
  so an intro auditor with no declared concern is the identical defect to a wave-review
  auditor with none; carving out `engineer-self-contained` would exempt exactly the
  dispatch shape where bundling temptation is highest. One-line fix authorized: add
  `[CONCERN]` to that fixture, same shape as the earlier line-56 fix, preserving its
  original `#172` topology intent — dispatched to `a4f661df7f6b3c346` (the fixture is in
  its file scope; this message IS the authorization it was waiting for).
  **Standing convention (root asked this carried into WAVE-COMPLETE as its own finding,
  stronger statement of DF-56 than root's own framing)**: any fixture asserting
  non-deny/non-record behavior at a teammate/`.worktrees` topology MUST set a real `cwd`
  field, never merely mention `.worktrees/` in a prompt string — a prose-only mention
  silently under-tests the `cwd`-gated branch, which is exactly how the pre-existing
  `OWN_LANE_PAYLOAD`-style fixture under-tested for however long before this wave's
  reachability finding surfaced it.
- **W2-G3-followup coder reports done — still UNCOMMITTED, sitting in the worktree diff,
  NOT git history; relayed by root. Last of the three follow-up coders in.** Agent
  `a55486aefa2b49f9b`. Verdict PASS. Claimed root cause: `usage()` prints the same static
  8-line block for every subcommand, so all four no-name assertions were borrowing the
  `status` line as a generic "usage printed" marker instead of each checking its own
  branch. Retargeted each to its own subcommand's line (`register <name> --team=`,
  `retire <name>`, `heartbeat <name>`), verified each pattern matches exactly one line
  with no cross-matches (`register <name> --team=` confirmed not matching
  `register-lead <team_id>`). `+5/-0`, one file, `cmd_teammate.sh` untouched and
  byte-verified against baseline. Proof claimed as a 4x4 invert matrix with a perfect
  diagonal — each of the four branches broken in turn, all four assertions run against
  each break, every broken branch fails ONLY its own assertion:
  `BROKEN=register -> register RED, others PASS`; `BROKEN=status -> status RED, others
  PASS`; `BROKEN=retire -> retire RED, others PASS`; `BROKEN=heartbeat -> heartbeat RED,
  others PASS`. Decoupling proven, not asserted — a stronger standard than the single
  invert-to-red I originally asked for.
  **All three follow-up/REDO coders are now in.** The single remaining piece before the
  `guard-fail-closed` re-audit is the authorized `#172` `[CONCERN]` one-liner, dispatched
  to `a4f661df7f6b3c346` and still pending.
