# Lane l7-substrate — CONDUCTOR SUMMARY

- Run: v645, sprint branch v6.4.5, git_custody: root (in place, no worktree)
- Base commit (boot): c17ad80
- Dispatch vehicle: Dynamic Workflow, `workflows/wave.js`, Run ID **wf_c0b8e79e-32b**
  (transcript: `subagents/workflows/wf_c0b8e79e-32b/journal.jsonl`)
- `WORKFLOW-VEHICLE-PROBE`: PRESENT — `Workflow` was in my own visible tool list
  (tmux-backed teammate substrate, consistent with DF-68). Compiled and dispatched a
  Dynamic Workflow per doctrine; no in-context `Agent()` fan-out downgrade.

## Pre-dispatch blocker, resolved before the lane wave

`workflows/wave.js`'s `meta` object built its `whenToUse` field via string concatenation
(`+`), which the Workflow tool's "meta must be a pure literal" parser rejects
(`BinaryExpression` not allowed). This blocked the ONLY sanctioned fan-out vehicle for
every future caller, not just this lane. Filed and fixed as a single-file HOTFIX
(cardinality H=1 → one `@coder` subagent, direct `Agent()` dispatch, not a Workflow —
Workflow was what was broken): report at
`.shepherd/runs/v645/reports/coder-L7-wave-js-hotfix.md`. Landed at commit `1441b5d`
("fix(workflows): wave.js meta was not a pure literal, so it never loaded; file
DF-69/DF-70") — already committed by the time the central auditor ran, ahead of my lane's
own git-custody boundary (I did not commit it myself; per hard prohibition #1 I dispatched
`@coder` for the write, and root/the shared working tree picked up the commit).

## Steps — central auditor verdict (`auditor-L7-central-verify.md`)

| Step | File | Verdict |
|---|---|---|
| L7-S1 | `commands/spawn.md` | **PASS** |
| L7-S2 | `skills/harness/SKILL.md` | **PASS** |
| L7-S3 | `skills/shepherd/SKILL.md` | **PASS** |

**Overall: PASS, no REDO required.** Every acceptance predicate independently re-run by
the central auditor against live HEAD (not taken from coder self-reports), two findings
mutation-tested for falsifiability (DF-60-non-reapplication check, `auto`-settled-claim
check) — both proven able to fail before being trusted to pass. `bin/shepherd lint`: PASS
(exit 0). `hooks/tests/run.sh`: exit 3, 3/84 assertions failing inside
`test_config_precedence.sh` — root-cause-traced to a pre-existing macOS `/private/var` vs
`/var` TMPDIR-symlink mismatch, byte-identical test file and library between base c17ad80
and HEAD, **not caused by this lane, not a REDO trigger**.

One LOW, non-blocking finding (F1): both L7-S1 and L7-S2 coder self-reports understated
their own match counts / LOC delta (e.g. L7-S2 claimed `+44/-1`, actual `+57/-1`) — content
was correct in both cases, only the self-report bookkeeping was off. No action required.

## Files changed (working tree, uncommitted — git custody is root's)

```
 commands/spawn.md        | 66 ++++++++++++++++++++++++++++++++++++++----------
 skills/harness/SKILL.md  | 58 +++++++++++++++++++++++++++++++++++++++++-
 skills/shepherd/SKILL.md |  2 ++
 3 files changed, 112 insertions(+), 14 deletions(-)
```

- `commands/spawn.md` — Check 1 rewritten from a bare env-key check into a 5-step
  resolve-and-print substrate check: env check (necessary, not sufficient) → compute and
  PRINT predicted `backendType` from `teammateMode` (explicitly `UNRESOLVED`/UNTESTED for
  `auto`, never guessed from the lead's own `$TMUX`) → state plainly what each backend
  carries (tmux: Workflow+ScheduleWakeup, no ungranted write tools; in-process: loses
  Workflow+ScheduleWakeup, has been observed gaining ungranted Edit/Write/Artifact — DF-65
  containment consequence, called out explicitly) → correct post-spawn oracles
  (`backendType`/`tmuxPaneId` in team config.json, `tmux -L claude-swarm-<lead-pid> ls`,
  bare `tmux ls` named and forbidden) → permission-mode inheritance (unchanged).
- `skills/harness/SKILL.md` — added the DF-68 mechanism (tmux-backed teammate = separate
  CLI process = MAIN session = outside the sub-agents tool filter; in-process = subagent,
  hits the filter), the dedicated-socket fact + false-negative-by-construction explanation
  for bare `tmux ls`, the `teammateMode`-read-at-spawn-not-session-start fact, and a
  measured tool-delta tally for both backends. `WORKFLOW-VEHICLE-PROBE` occurrences
  unchanged (4, all pre-existing) — additions only, no rewrite of the existing probe rule.
- `skills/shepherd/SKILL.md` — added exactly one new paragraph, `PROBE-FALSIFIABILITY`,
  immediately after the existing `WORKFLOW-VEHICLE-PROBE` paragraph (left byte-identical —
  verified by the auditor via `diff` on the exact line, plus a mutation test proving the
  identity check can actually fail). Cites DF-68 by pointer, ties to the existing auditor
  Hypothesis+Falsification+Confidence discipline as its analogue.

## Blocking items for root

None blocking this lane's own close — verdict is PASS. Three items the central auditor
surfaced as explicitly out of L7's scope, flagged for root's attention:

1. **Disk headroom**: `df-guard.sh --min=12` currently fails (9.4Gi free / 98% full). No
   gate this lane ran needed cargo, but the next cargo-invoking wave in this run will hit
   it immediately.
2. **Pre-existing, unfiled test failure**: `hooks/tests/run.sh` exit 3,
   `test_config_precedence.sh` — 3/84 assertions red on a macOS TMPDIR realpath mismatch,
   unrelated to this lane, appears unfiled in dogfood.md or GH. Recommend root file it.
3. **Cross-run duplicate dispatch (not an L7 defect)**: a second coder report
   `coder-W7-S3.md` targeted the identical deliverable as `L7-S3` (same file, same
   `PROBE-FALSIFIABILITY` paragraph) under a different lane-id. That coder's own
   `[DO-NOT-DUPLICATE]` grep caught it and made zero writes — no double-write occurred,
   confirmed by the central auditor via `git diff`. Worth a mesh-time same-deliverable
   cross-run check so two lane-ids are never issued for one file+deliverable again.

## Git custody

`git_custody: root` per boot brief. I have made **zero commits and zero pushes** — the
working tree carries my lane's 3-file diff uncommitted, exactly as instructed
("Leave the tree dirty and hand it back"). The one hotfix commit (`1441b5d`) and other
concurrent commits visible in `git log` (`2fea02d`, `df47686`) were NOT made by me; they
reflect other concurrent activity in this shared in-place working tree (no worktree
isolation for this lane) and none of them intersect this lane's 3 files
(`git diff c17ad80 HEAD -- commands/spawn.md skills/harness/SKILL.md skills/shepherd/SKILL.md`
→ empty).

- Agent: shepherd-conductor-v645-l7-substrate
- Reports: `coder-L7-S1.md`, `coder-L7-S2.md`, `coder-L7-S3.md`,
  `coder-L7-wave-js-hotfix.md`, `auditor-L7-central-verify.md` (all under
  `.shepherd/runs/v645/reports/`)
