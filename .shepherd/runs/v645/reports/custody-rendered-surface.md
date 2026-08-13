---
title: What a conductor is actually TOLD — rendered boot-prompt custody surface
date: 2026-08-13
auditor: custody-rendered-surface-probe
sprint: v6.4.5
concern: dependency-topology (rendered-artifact custody surface, not gate hygiene)
mode: adhoc-probe (read-only, DF-68 falsifiability protocol)
methodology: superpowers:systematic-debugging (Phase 1 evidence-gathering; render as
  instrument, positive+negative control per finding, static doc comparison as pattern
  analysis)
---

## Scope reviewed

Rendered `services/cli/shepherd_cli/templates/boot-prompt.md.j2` for a realistic lane
boot (`lane_index: 7_of_8`, `git_custody: lane`, peers `l1-engine`/`l2-registry`/
`l3-surface`), via the repo's OWN CLI (`./bin/shepherd render`), never a hand read of the
template source. Compared the RENDERED text — the actual instrument a live
teammate-conductor obeys — against `agents/conductor.md` (full file) and
`skills/shepherd/SKILL.md:89`. Dynamically probed `hooks/scripts/teammate_git_guard.sh`
(the mechanical enforcement layer behind `TEAMMATE-GIT-WRITE`) in a throwaway sandbox
repo, plus ran its own canonical test suite, to settle the doc-vs-doc disagreement against
ground truth rather than adjudicating prose against prose. All scratch artifacts live
under `/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad`
(`boot-vars.json`, `boot-prompt-rendered.md`, `guard-sandbox/`, `guard-out-*.json`,
`guard-official-test.out`). Repo working tree untouched by this probe (verified via
`git status --porcelain` before/after — two pre-existing dirty entries,
`workflows/wave.js` and `.shepherd/runs/v645/reports/coder-L7-wave-js-hotfix.md`,
belong to concurrent lane activity, not this probe; neither was read or written here).

## Positive control (render instrument)

Claim under test: "the repo's own CLI can render `boot-prompt.md.j2` for a realistic
lane and the render is a faithful expansion of the vars supplied, not a canned/cached
string." Command, own exit code captured via redirect (never through a pipe):

```
./bin/shepherd render boot-prompt.md.j2 --vars-json boot-vars.json > boot-prompt-rendered.md 2> boot-prompt-render.stderr
echo "EXIT_CODE:$?" > boot-prompt-render.exit
```

Result: `EXIT_CODE:0`, empty stderr, 93-line output. Positive control — a distinctive
sentinel supplied only via `root_session_name` traces verbatim into the render, proving
this is a real Jinja expansion of MY input, not a fixture:

- Supplied: `"root_session_name": "shepherd-root @ CUSTODY-PROBE-SENTINEL-9f3a"`
- Rendered line 83: `ROOT-SESSION-NAME: shepherd-root @ CUSTODY-PROBE-SENTINEL-9f3a`

Corroborating trace-backs: `lane_index: "7_of_8"` → rendered line 90
`lane_index: 7_of_8`; `peer_teammate_names: ["l1-engine","l2-registry","l3-surface"]` →
rendered line 93 `peer_teammate_names: ["l1-engine", "l2-registry", "l3-surface"]`.

**Negative control, same instrument:** omitted `git_custody` from the vars file and
re-ran the identical command. `EXIT_CODE:4`, stderr `ERROR: undefined template
variable — boot-prompt.md.j2: 'git_custody' is undefined`, 0 bytes of stdout. The
renderer can both succeed (positive) and hard-fail (negative, StrictUndefined) on the
same instrument — the render tool itself is falsifiable in both directions.

## Full rendered output (93 lines, verbatim)

```
You are a spawned teammate-conductor.

BOOT INSTRUCTION
  On your FIRST turn, set session effort to the `Lead effort` pin below, then
  load /Users/jo3/.claude/plugins/cache/shepherd/shepherd/6.4.5/agents/conductor.md §Boot verification and begin — do
  NOT wait for a kickoff message. Your lane plan IS the instruction: read it
  from the `Lane plan` path below, keep it current as you walk it (check off
  steps, append `## Deviations` entries for every choice you make), and treat
  it as the single source of truth for your lane.
  conductor.md owns the boot checklist (§Boot verification), the lane walk
  (§Lane walk), and the WAVE-COMPLETE payload schema (§WAVE-COMPLETE + resume).

FAN-OUT VEHICLE (#263)
  Before your FIRST fan-out, run WORKFLOW-VEHICLE-PROBE once: read your own
  visible tool list for the literal token `Workflow`. This confirms WHICH
  SUBSTRATE you are on — it is not a check on whether a dormant grant is live.
    - PRESENT → you are a genuine Agent-Teams teammate. Compile each gate-free
      `parallel_with` clique into a Dynamic Workflow and dispatch it. Every
      `agent()` call pins BOTH `model:` and `agentType: "shepherd:<role>"`
      (#255) — the Workflow runtime never reads `shepherd.toml [models]`.
    - ABSENT → the Agent-Teams substrate was not live at spawn, so you are
      silently an Agent-tool subagent. `Workflow` is genuinely denied there.
      Fan out in-context via `Agent()` (whole clique in ONE message) and
      record the substrate in your WAVE-COMPLETE. That is CORRECT on this
      substrate and the only option — not a downgrade to apologize for.
  FANOUT-VEHICLE-DOWNGRADE fires only if you are on a LIVE teammate substrate
  and hand-roll in-context anyway. NEVER `ToolSearch` for `Workflow` to run
  the probe (WORKFLOW-SELFCHECK-TOOLSEARCH): it resolves DEFERRED tools only,
  so a null on a native primitive is a false negative by construction and
  establishes nothing. The visible tool list is the only oracle.

  REPORT THE PROBE BEFORE YOU DISPATCH, NOT AT WAVE-COMPLETE.
  Your FIRST message to root, on turn one and before ANY dispatch, is exactly:
      WORKFLOW-PROBE: present | absent
      FANOUT-VEHICLE: workflow | in-context
  Recording it only in WAVE-COMPLETE is too late by construction — that payload
  arrives AFTER every dispatch the probe was supposed to govern, so a lane can
  hand-roll its entire wave and disclose the vehicle afterwards, which is
  exactly how five lanes in v6.4.5 fanned out with zero probes reported and
  root never noticed. Root will not gate a wave whose probe was never sent.
  Send those two lines first. Then walk your lane.

HARD PROHIBITIONS (each BINDING; on any, REFUSE and
SendMessage(to: lead, halt_code: <code>, blocking: true)):
  - @engineer dispatch → WRONG-TIER-DISPATCH  (escalate PLAN-AUTHORSHIP-REQUEST)
  - @critic dispatch   → WRONG-TIER-DISPATCH  (escalate PLAN-GATE-REQUEST)
  - flock dispatch missing subagent_type: "shepherd:<role>" or set to
    general-purpose/Explore/Chat → DISPATCH-MISSING-SUBAGENT-TYPE
  - flock dispatch outside the closed six-role flock → DISPATCH-OFF-FLOCK
  - spawning a teammate (you are not a lead) → TEAMMATE-NESTING-ATTEMPT
  - git merge/rebase/cherry-pick onto a shared branch, or worktree
    add/remove/prune → TEAMMATE-GIT-WRITE (see `git_custody` below for your
    in-lane commit/push authority)
  Full contract: agents/conductor.md §Hard prohibitions.

LEDGER CUSTODY (#261)
  /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/auditor-verdicts.txt is ROOT-OWNED. Every verdict you
  record is appended there, at that exact ABSOLUTE path — NEVER at a
  worktree-relative copy composed by hand (e.g. a `.shepherd/runs/.../
  auditor-verdicts.txt` path taken relative to your own worktree's cwd).
  This file is replicated into every lane worktree as its own on-disk
  copy, and nothing in a relative path distinguishes one worktree's copy
  from the primary's: a lane that appends to its own local copy instead
  of the absolute path above is invisible to the boundary gate, and
  merging that lane's branch can silently delete a sibling lane's
  verdict rows. `Run dir:` below repeats this same absolute path — the
  two must always match.

INHERITED CONTEXT
  Profile:              /Users/jo3/.claude/plugins/cache/shepherd/shepherd/6.4.5/agents/conductor.md
  Model pin:            claude-sonnet-5
  Lead effort:          high
  CLAUDE.md path:       /Users/jo3/src/fl03/shepherd/CLAUDE.md
  Run dir:              /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645
  Active seed:          /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/seed.md
  Active plan:          /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/plan.md
  Lane plan (YOURS):    /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/lanes/l7-substrate/plan.md
  Prior close handoff:  /Users/jo3/src/fl03/shepherd/.shepherd/runs/v644/handoff.md
  Carry-forward issues: #263, #264
  Worktree path:        /Users/jo3/src/fl03/shepherd/.worktrees/v645-l7-substrate
  [BASE-COMMIT-EXPECTED]: 9283cdd0000000000000000000000000000000

ROOT-SESSION-NAME: shepherd-root @ CUSTODY-PROBE-SENTINEL-9f3a

INVOCATION-CONTEXT:
  dispatcher: teammate-conductor
  spawn_session: team-v645-1
  scope: sprint
  fanout_mode: lane
  lane_index: 7_of_8
  wave_index: 1_of_2
  git_custody: lane
  peer_teammate_names: ["l1-engine", "l2-registry", "l3-surface"]
```

(`toml_snapshot` was supplied as `""`; the `{% if toml_snapshot %}` block correctly
omitted it — empty string is falsy in Jinja. `parallel_index` was `null`; the
`{% if parallel_index is not none %}` block correctly omitted it too. Both are evidence
the conditional logic in the template is exercised correctly, not evidence about custody.)

## (a) Whether the conductor may write its own lane plan — quoted verbatim

Rendered, lines 6–9:

> Your lane plan IS the instruction: read it
> from the `Lane plan` path below, keep it current as you walk it (check off
> steps, append `## Deviations` entries for every choice you make), and treat
> it as the single source of truth for your lane.

This is the ONLY place in the rendered surface that speaks to lane-plan writes. It
unambiguously authorizes editing the file at `Lane plan (YOURS):` (line 77) — checking
off steps and appending `## Deviations` entries are both write operations.

**Verification against `agents/conductor.md` (disproved a hypothesized gap):** §Lane-plan
custody (lines 63–67) states this is "your OWNED file — the ONE write exemption to
prohibition #1 (`conductor_write_guard.sh` allows writes under your OWN
`{run_dir}/lanes/{lane}/`, nowhere else)" and lists the exact same two actions: check off
steps, append `## Deviations`. Hard Prohibition #1 (line 160) repeats the exemption
verbatim: "Exempt: your OWN `{run_dir}/lanes/{lane}/`". **Confidence: HIGH — no
narrower/wider gap on this axis; rendered text and profile text agree exactly.**

One thing the rendered surface omits that conductor.md carries: the `vars.json`
shadowing caveat (#269, lines 43–50) — that a plan.md-only correction is invisible to
the next dispatch and both files need the same edit, verified via
`shepherd plan lane-drift`. This is NOT a contradiction (the boot prompt explicitly
instructs loading `agents/conductor.md §Boot verification` before beginning, so the
detail is deferred, not omitted-and-lost), but it means the rendered surface ALONE is
insufficient for correct lane-plan custody — flagged in Open questions below since I
cannot verify from the render alone whether every real boot actually performs that load
before the first plan edit.

## (b) Whether the conductor may commit and push its lane branch — quoted verbatim

Rendered, the ENTIRE textual surface on this question is one parenthetical inside the
HARD PROHIBITIONS block (lines 51–53) plus one bare token in INVOCATION-CONTEXT (line 92):

> git merge/rebase/cherry-pick onto a shared branch, or worktree
> add/remove/prune → TEAMMATE-GIT-WRITE (see `git_custody` below for your
> in-lane commit/push authority)

> git_custody: lane

Note what is NOT rendered: nowhere does the rendered text state the MEANING of
`git_custody: lane` vs `git_custody: root` — that expansion ("`lane` — you commit +
push your own branch; `root` — root holds integration custody, you hand over a
committed, unpushed worktree") lives only in `agents/conductor.md:27`, reached only
via the BOOT INSTRUCTION's directive to load that file. The rendered surface hands the
conductor an opaque enum value and a promise that the meaning is "below" — but "below"
in the render is just the bare token again, not a definition. See Open questions.

**Verification against `agents/conductor.md` (no gap on the authorization itself):**
Line 14: "Read + commit + push + dispatch — commit AND push your OWN lane branch
directly". Hard Prohibition #1 (line 160): "Commits AND your lane-branch push are
yours". §WAVE-COMPLETE (line 150): "under boot `git_custody: lane` you commit (and MAY
push) your OWN lane branch, leaving no wave output uncommitted (#222)". §WAVE-COMPLETE
payload schema (line 137) requires `git_custody: {committed: true, ..., pushed: <bool>,
worktree_clean: true}`. §Lane walk (line 148) has an entire "Pre-push assertion (#242)"
paragraph beginning "Before EVERY push of your lane branch...". **All of this agrees
with the rendered pointer — commit+push of the OWN lane branch is authorized, never a
halt trigger. Confidence: HIGH.**

## (c) What TEAMMATE-GIT-WRITE covers — quoted verbatim

Rendered, lines 51–53 (the ONLY place TEAMMATE-GIT-WRITE is defined in the rendered
surface):

> git merge/rebase/cherry-pick onto a shared branch, or worktree
> add/remove/prune → TEAMMATE-GIT-WRITE

So the rendered scope is exactly four operations: merge, rebase, cherry-pick (each
qualified "onto a shared branch"), and worktree add/remove/prune. Push is explicitly
carved OUT via the trailing parenthetical (§b above).

## FINDING 1 — `skills/shepherd/SKILL.md:89` tells a conductor something WIDER than what it is actually told, and wider than what is mechanically enforced

**Hypothesis:** `SKILL.md:89`'s phrasing of the `TEAMMATE-GIT-WRITE` trigger set is
unqualified and includes `push` without the "onto a shared branch" qualifier the
rendered boot prompt and `pipeline.md:162` both carry, so a conductor consulting
`SKILL.md` directly (rather than only the rendered boot prompt) would be told push is
prohibited — contradicting its own role profile and the actual mechanical gate.

**Falsification:**

1. Exact text, `skills/shepherd/SKILL.md:89` (confirmed via `grep -n "^Root MUST NOT"`):

   > Git custody is root-exclusive: a teammate that runs `git rebase`/`merge`/`push`/`worktree` halts `TEAMMATE-GIT-WRITE` (`references/pipeline.md §CLOSE-FINALIZE`).

   This lists `push` in the same unqualified breath as `rebase`/`merge`/`worktree`,
   with no "onto a shared branch" or "own lane branch is exempt" qualifier anywhere in
   the sentence or its immediate context.

2. The RENDERED boot prompt (§b/§c above, lines 51–53) — the actual live instrument —
   excludes `push` from the `TEAMMATE-GIT-WRITE` trigger list and explicitly points to
   `git_custody` for "in-lane commit/push authority".

3. `agents/conductor.md:162` (Hard Prohibition #3): "`TEAMMATE-GIT-WRITE` covers
   cross-lane integration (rebase/merge/cherry-pick onto dev) + worktree
   add/remove/prune, **NOT your lane commit/push**." — directly contradicts
   `SKILL.md:89`'s unqualified reading.

4. `skills/shepherd/references/pipeline.md:162` (same skill's OWN companion doc, cited
   BY `SKILL.md:89` itself as `§CLOSE-FINALIZE`): "In-worktree `git add`/`git commit`
   are permitted; `git merge`/`rebase`/`push`/`cherry-pick` **onto a shared branch**
   are root-only" — here push IS qualified "onto a shared branch", unlike the
   unqualified line 89 that cites this very section.

5. `skills/shepherd/references/invariant-matrix.md:125` (row 30): "A teammate-conductor
   COMMITS and PUSHES its OWN lane branch...; only cross-lane integration
   (merge/rebase/cherry-pick onto dev, worktree lifecycle) is root's
   `TEAMMATE-GIT-WRITE`" — status column: `guard+test+doctrine`, `**live (tested)**`.

6. Ground truth, dynamically probed (own throwaway sandbox, git-init'd, under
   scratchpad — never in the shepherd repo): fed
   `hooks/scripts/teammate_git_guard.sh` a synthetic PreToolUse payload for a
   registered, non-retired teammate session against 5 commands. Own exit codes
   captured via redirect, read directly (never through a pipe):

   | Command | Result |
   |---|---|
   | `git rebase origin/dev` | **DENY** — `permissionDecision: "deny"`, `TEAMMATE-GIT-WRITE` |
   | `git push origin lane-branch` | **ALLOW** — silent, empty stdout, no denial |
   | `git worktree add ../foo dev` | **DENY** — `permissionDecision: "deny"`, `TEAMMATE-GIT-WRITE` |
   | `git commit -m wip` | **ALLOW** — silent, empty stdout, no denial |
   | `git branch -d some-old-branch` | **ALLOW** — silent, empty stdout, no denial (see Finding 2) |

   Both DENY and ALLOW outcomes were produced by the SAME instrument
   (`teammate_git_guard.sh`) against the SAME synthetic teammate session — satisfying
   the positive+negative control requirement for this claim.

7. Cross-checked against the project's OWN canonical test,
   `hooks/tests/test_teammate_git_guard.sh`, run unmodified: `17/17 passed`, including
   `PASS teammate + git push: PASS (lane-branch publish — #222)` and
   `PASS teammate + git rebase: DENY + TEAMMATE-GIT-WRITE`. This independently
   confirms my sandbox methodology reproduces the maintainers' own certified behavior,
   not an artifact of my synthetic setup.

**Conclusion:** `SKILL.md:89`'s unqualified inclusion of `push` is wider than (a) what
a conductor is actually told at boot (the rendered surface), (b) its own role profile
(`agents/conductor.md`, in 4 separate places), (c) the skill's own companion doc
(`pipeline.md:162`, correctly qualified), (d) the invariant matrix's explicit ledger
entry, and (e) the mechanically-enforced ground truth (`teammate_git_guard.sh`, tested
both statically and dynamically). Every other source agrees push-of-own-lane-branch is
authorized and not a `TEAMMATE-GIT-WRITE` trigger; `SKILL.md:89` alone reads as if it
prohibits it. **Confidence: HIGH — structurally verified against 6 independent sources,
including a live dynamic probe with both DENY and ALLOW outcomes from the same
instrument, plus the project's own passing test suite.**

This is a live-doctrine risk, not merely stale prose: `SKILL.md` is the top-level
shepherd contract file conductors and root both load; a conductor that reads it
literally (rather than only the boot-prompt-rendered summary) could misjudge its own
authority and either wrongly escalate a routine lane push to root as
`TEAMMATE-GIT-WRITE`, or a reviewer/auditor grading against `SKILL.md:89`'s literal text
could wrongly flag a correct, guard-permitted push as a violation.

## FINDING 2 — `agents/conductor.md` itself defines `TEAMMATE-GIT-WRITE`'s scope twice, with different content, and the wider version (`branch -d`) is neither rendered nor mechanically enforced

**Hypothesis:** `conductor.md §Side-effect boundary` (line 187) adds `branch -d` to the
`TEAMMATE-GIT-WRITE` scope beyond what `§Hard prohibitions #3` (line 162) states, and
this addition is untested and unenforced.

**Falsification:**

1. `conductor.md:162` (§Hard prohibitions #3): "`TEAMMATE-GIT-WRITE` covers cross-lane
   integration (rebase/merge/cherry-pick onto dev) + worktree add/remove/prune, NOT
   your lane commit/push." — no `branch -d`.

2. `conductor.md:187` (§Side-effect boundary): "Cross-lane git integration
   (rebase/merge/cherry-pick onto dev, `branch -d`, worktree add/remove/prune) and the
   registry lock are root-exclusive after all lanes close (`TEAMMATE-GIT-WRITE`,
   `TEAMMATE-LOCK-ATTEMPT`)" — `branch -d` IS listed here.

3. The rendered boot prompt (lines 51–53) matches the NARROWER §Hard prohibitions #3
   wording exactly (merge/rebase/cherry-pick onto a shared branch, worktree
   add/remove/prune) — `branch -d` is absent from what a conductor is actually told at
   boot.

4. Dynamic probe (same sandbox/instrument as Finding 1): `git branch -d
   some-old-branch` against a registered teammate session → **ALLOW** (silent, no
   denial) — `teammate_git_guard.sh`'s `FORBIDDEN_PATTERN`
   (`merge|rebase|cherry-pick`) and `FORBIDDEN_WORKTREE_PATTERN` (worktree
   add/remove/prune) never check the `branch` verb at all; its own header comment
   (lines 12–27) lists `git branch` only as a read-only allowed command, with no
   distinction drawn between `git branch` (list) and `git branch -d`/`-D` (mutate).

5. `hooks/tests/test_teammate_git_guard.sh` has no test case for `branch -d` in either
   direction (grepped for `branch -d` — zero hits) — the gap is untested, not merely
   unenforced-by-oversight-with-a-test-catching-it-elsewhere.

**Conclusion:** within `agents/conductor.md` alone, two sections disagree on
`TEAMMATE-GIT-WRITE`'s scope. The version that reaches the rendered boot prompt (and
matches the mechanical guard) is the NARROWER one; the WIDER one (`§Side-effect
boundary`, adding `branch -d`) is neither rendered to a live conductor nor mechanically
enforced nor tested. **Confidence: MEDIUM-HIGH** — the textual disagreement and the
guard's non-enforcement are both structurally verified (grep + dynamic probe); what
stays unverified is whether any teammate has ever actually attempted `branch -d` in
practice, since this is a narrower behavioral-risk claim than Finding 1 (branch
deletion of a lane branch is a much rarer teammate action than a routine wave push).

## Verifications (disproved hypotheses)

- **Hypothesized:** the rendered surface might narrow or omit the lane-plan
  write-exemption relative to `conductor.md`. **Disproved** — §(a) above; rendered
  text and `conductor.md §Lane-plan custody` / Hard Prohibition #1 agree exactly.
- **Hypothesized:** the render CLI might silently substitute a default/blank for a
  missing var rather than hard-failing (masking a custody-relevant field going
  unset). **Disproved** — the negative control (missing `git_custody`) produced exit
  4 and zero stdout bytes, not a silent blank.

## Open questions

- The rendered surface's ONLY expansion of `git_custody`'s meaning is the phrase
  "in-lane commit/push authority" — the actual `lane` vs `root` semantics live solely
  in `agents/conductor.md:27`, reached only via the BOOT INSTRUCTION's directive to
  load that file before acting. I cannot verify from the render alone whether a live
  conductor session reliably performs that load before its first git action, or
  whether (as with DF-65/DF-66/DF-67, all closed earlier in this same run) an opaque
  config token that is never expanded inline is itself the failure shape waiting to
  recur. LOW confidence — suggestive only, not structurally verified within this
  probe's scope (would require observing a live boot, not a static render).
- Whether any teammate conductor has ever actually attempted `git branch -d` on its
  own lane branch, and whether that action is even reachable given the lane's normal
  Stage-Graph walk (branch deletion is root's job at CLOSE-FINALIZE, not a step a
  conductor's own lane walk would normally emit) — Finding 2's gap may be
  theoretical/defense-in-depth rather than exploited. LOW confidence.

## Pattern delta

Not applicable — this is an ad hoc probe report (`custody-rendered-surface.md`), not a
`close`/`completeness` concern audit; no grade, no severity trend against prior
sprints tracked here.

## Grade

n/a — probe report, not a CLOSE-SWARM concern audit.

## Grade rationale

n/a.

## Output to conductor

```
## PROBE REPORT — rendered boot-prompt custody surface
- Mode: adhoc read-only probe (DF-68 falsifiability protocol)
- Render instrument: ./bin/shepherd render boot-prompt.md.j2 (repo's own CLI) — EXIT_CODE:0, positive control (sentinel trace-back) PASS; negative control (missing var) EXIT_CODE:4, StrictUndefined PASS
- Findings: HIGH=1 (SKILL.md:89 push-inclusion wider than rendered surface/profile/guard), MEDIUM=1 (conductor.md internal branch-d scope disagreement, unenforced/untested)
- Verifications (disproved): 2
- Open questions: 2
- Dynamic guard probe: teammate_git_guard.sh, own sandbox, 5 commands (2 DENY, 3 ALLOW) + official test suite 17/17 — both directions demonstrated on the same instrument
- Repo working tree: unmodified by this probe (verified git status before/after)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/custody-rendered-surface.md
- Agent ID + timestamp: custody-rendered-surface-probe @ 2026-08-13T00:00:00Z
```

## Concurrency note (added post-write, read-only recheck)

`skills/shepherd/SKILL.md` was under live concurrent edit by lane `l7-substrate`
during this probe (flagged in the task brief; this file was never touched by this
probe — verified via `git diff --stat -- skills/shepherd/SKILL.md`, read-only). The
concurrent edit inserted a new paragraph at (new) lines 79-80 — coincidentally the
`PROBE-FALSIFIABILITY` doctrine paragraph citing this same `DF-68` incident — which
shifted the sentence originally cited as `SKILL.md:89` down to `SKILL.md:91`. Content
is byte-identical (`git diff` shows a pure 2-line insertion above it, no modification
to the cited sentence itself): `grep -n "^Root MUST NOT"` now reports line 91 with the
exact same text quoted in Finding 1. The finding's substance and every quoted string
are unaffected; only the line number moved, and only because of the sprint's own
in-flight remediation of the exact failure class this probe investigates.
