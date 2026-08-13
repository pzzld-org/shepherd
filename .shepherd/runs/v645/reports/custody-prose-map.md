---
title: Change map — every site stating/implying/enforcing the two custody rules
date: 2026-08-13
auditor: shepherd:auditor (custody-prose-map, ad-hoc discovery/mapping task — no grade)
sprint: v6.4.5 (run v645)
scope: read-only; no edits, no commits, no stages
head_at_write_time: 1441b5d38ffd93307ce3e81853c6289e40df2108 (branch v6.4.5)
methodology: superpowers:systematic-debugging Phase 1 (multi-angle evidence gathering,
  falsify-don't-confirm) + PROBE-FALSIFIABILITY (DF-68) — every ALLOW claim paired with a
  DENY from the same instrument in the same run, and vice versa; own exit code read via
  file redirect, never through a pipe.
rules:
  R1: "who may write {run_dir}/lanes/{lane}/plan.md"
  R2: "which git operations a teammate-conductor may run"
operator_grant: "conductors may write their own lane plan and may freely commit and push
  to their assigned worktree"
---

## Scope reviewed

Full repo tree at `/Users/jo3/src/fl03/shepherd`, excluding `.git/`, `target/`,
`.worktrees/*` (other lanes' isolated checkouts — reading the shared root tree is
sufficient since `commands/spawn.md`, `skills/harness/SKILL.md`, `skills/shepherd/SKILL.md`
are being edited live, uncommitted, directly in this shared worktree by `l7-substrate`,
confirmed via `git status --porcelain` and `git diff --stat` below). Swept: `agents/`,
`commands/`, `skills/` (incl. `references/`), `hooks/` (scripts + tests + `hooks.json`),
`services/cli/` (Python source, tests, Jinja templates), `content/` (cross-implementation
role/skill sources + `RECONCILIATION.md`), `docs/`, `.shepherd/CONVENTIONS.md`,
`.shepherd/docs/specs/*.spec.md`, `.shepherd/dispatcher-patches/*`, `CHANGELOG.md`,
`packages/`, `examples/`. Four independent search angles run separately (halt-code, verb,
path-shape, file-class) per the brief, plus direct reads of every implicated
guard/template/test file rather than trusting grep alone.

**Concurrency note.** `git status --porcelain` at write time shows `commands/spawn.md`,
`skills/harness/SKILL.md`, `skills/shepherd/SKILL.md` as modified-uncommitted
(`l7-substrate`, live). Their diffs (`git diff --stat`) touch only the DF-64/65/66/68
substrate-verification material, not the custody sections cited below — but line numbers
in those three files are a **snapshot at HEAD 1441b5d + uncommitted worktree state**, not
stable; re-grep the anchor text, don't trust the line number, once `l7-substrate` lands.
No file was written, staged, or committed by this task.

## Runtime instruments — PROBE-FALSIFIABILITY (positive + negative control, same instrument, same run)

Both custody rules are mechanically enforced by two `PreToolUse` hooks, both wired in
`hooks/hooks.json` (`teammate_git_guard.sh` on the `Bash` matcher line 41;
`conductor_write_guard.sh` on `Bash`/`Write`/`Edit` matchers lines 57/86/111). Ran each
guard's own canonical test suite directly, own exit code captured via file redirect
(never piped through `tail`/`head`):

```
$ bash hooks/tests/test_teammate_git_guard.sh > out.txt 2>&1; echo $? > out.exit
$ cat out.exit
0
$ cat out.txt   (17/17 passed)
```

**R2 — `teammate_git_guard.sh` (own instrument, one run, both directions present):**
| Control | Case | Result |
|---|---|---|
| POSITIVE (ALLOW) | `teammate + git push` | `PASS (lane-branch publish — #222)` |
| POSITIVE (ALLOW) | `teammate + git add` / `git commit` | `PASS (in-worktree allowed)` |
| NEGATIVE (DENY) | `teammate + git merge` | `DENY + TEAMMATE-GIT-WRITE` |
| NEGATIVE (DENY) | `teammate + git rebase` | `DENY + TEAMMATE-GIT-WRITE` |
| NEGATIVE (DENY) | `teammate + git cherry-pick` | `DENY + TEAMMATE-GIT-WRITE` |
| NEGATIVE (DENY) | `teammate + git worktree add/remove/prune` | `DENY + TEAMMATE-GIT-WRITE` (each) |

```
$ bash hooks/tests/test_conductor_write_guard.sh > out.txt 2>&1; echo $? > out.exit
$ cat out.exit
0
$ cat out.txt   (24/24 passed)
```

**R1 — `conductor_write_guard.sh` (own instrument, one run, both directions present):**
| Control | Case | Result |
|---|---|---|
| POSITIVE (ALLOW) | `teammate + marker + own lane plan (relative path)` | `PASS (lane custody)` |
| POSITIVE (ALLOW) | `teammate + marker + own lane dir file (absolute path)` | `PASS (lane custody)` |
| NEGATIVE (DENY) | `teammate + marker + sibling lane's plan.md` | `DENY` |
| NEGATIVE (DENY) | `teammate + marker + master runs/plan.md` | `DENY` |
| NEGATIVE (DENY) | `solo conductor (no session-tier marker) + lane-shaped path` | `DENY` |

Both suites' exit code `0` was read from `out.exit` (`echo $? > out.exit; cat out.exit`),
not inferred from a pipe. Both rules therefore have a proven POSITIVE and a proven
NEGATIVE from the identical instrument in the identical run — satisfies DF-68; nothing
below is reported as a bare "denied" or "allowed" without this pairing.

Two independent parallel probes already exist in this run's `reports/` directory and
corroborate the above with a deeper instrument (a real `boot-prompt.md.j2` render via
`./bin/shepherd render`, and a scratchpad-sandbox direct-execution six-invocation matrix):
`.shepherd/runs/v645/reports/custody-rendered-surface.md` and
`.shepherd/runs/v645/reports/custody-lane-plan-write.md`. Cited below where they surface a
site this sweep also found, or one additional site (Finding 2 of the rendered-surface
probe) folded in here for completeness.

## R1 — who may write `{run_dir}/lanes/{lane}/plan.md`

| # | Site | Asserts | Verdict |
|---|---|---|---|
| 1 | `agents/conductor.md:37-67` (`## Lane-plan custody`) | "It is your OWNED file — the ONE write exemption to prohibition #1 ... Keep it live as you walk: check off each step, record acceptance results, append a `## Deviations` entry" | **AGREES** |
| 2 | `agents/conductor.md:63` | "`conductor_write_guard.sh` allows writes under your OWN `{run_dir}/lanes/{lane}/`, nowhere else" | **AGREES** |
| 3 | `agents/conductor.md:160` (known starting point, re-verified) | "Exempt: your OWN `{run_dir}/lanes/{lane}/` — the guard allows lane-plan custody writes there ... every other artifact write stays denied" | **AGREES** |
| 4 | `hooks/scripts/conductor_write_guard.sh:113-139` | Implements the exact carve-out: matches the session-tier marker's `lane_plan` field's `runs/<run>/lanes/<lane>` path segment; Edit/Write inside it → `pass_silent`; else falls through to the deny message | **AGREES** (mechanical enforcement, proven live above) |
| 5 | `hooks/scripts/plan_proof_guard.sh:25-31` | "A lane plan is a `plan.md` too but is CONDUCTOR-rendered and never gains a critic-proof sidecar, so it always reads CRITIC-PROOF-MISSING here and is left untouched — no special-casing needed to keep the conductor's own lane-plan writes unobstructed" | **AGREES** (a THIRD, independent guard designed around the same custody fact; `--self-test` run, exit 0, own positive+negative controls pass) |
| 6 | `hooks/hooks.json:232-236` | `type: "agent"` PreToolUse hook `if: "Edit(*/runs/*/lanes/*/plan.md)"`, prompt text: "v6.4.1 conductor-owned lane plan at runs/{run}/lanes/{lane}/plan.md" — a claim-verification pass, never a denial | **AGREES** |
| 7 | `hooks/hooks.json:238-242` | Same, for `Write(*/runs/*/lanes/*/plan.md)` | **AGREES** |
| 8 | `agents/engineer.md` (`§Lane projection`) | "Root materializes the projection as per-lane plan files ... the conductor-OWNED file its boot brief references by PATH (`agents/conductor.md §Lane-plan custody`)" | **AGREES** |
| 9 | `services/cli/shepherd_cli/templates/lane-plan.md.j2:1-9` (comment header, rendered into every lane's actual plan file) | "Conductor-owned lane plan ... the conductor OWNS it from boot to LANE-CLOSE — checking off steps, recording acceptance results, and appending to `## Deviations` for every mid-lane choice" | **AGREES** |
| 10 | `services/cli/shepherd_cli/commands/plan.py:1012-1015` (`_cmd_lane_drift` docstring) | "the conductor reads, owns and edits `{run_dir}/lanes/{lane}/vars.json}` [sic — plan.md] (`agents/conductor.md §Lane-plan custody`)" | **AGREES** |
| 11 | `commands/spawn.md:197-201` (rendered boot-brief contract) | "`Lane plan (YOURS): {run_dir}/lanes/{lane}/plan.md` ... The conductor reads and OWNS that file (`agents/conductor.md §Lane-plan custody`)" | **AGREES** — not deferred-blocking (this specific line is outside the l7-substrate diff hunks; verified via `git diff -- commands/spawn.md`) |
| 12 | `.shepherd/CONVENTIONS.md:21` | `lanes/{lane}/plan.md   # tracked, conductor-owned` | **AGREES** |
| 13 | `skills/context/references/naming-conventions.md:146` | `{run_dir}/lanes/{lane}/plan.md` — "Lane plan (checkbox steps + append-only `## Deviations`)" — tracked | **AGREES** |
| 14 | `skills/shepherd/references/seed-template.md:26` | Lists `lanes/{lane}/plan.md` among the fixed run-dir files | **AGREES** (neutral/informational — doesn't itself state WHO writes it) |
| 15 | `skills/shepherd/references/wave-routine.md:62-64` | "A lane's brief renders from `lanes/{lane}/vars.json` while the conductor owns `lanes/{lane}/plan.md`; a correction that reached only one of them means the next dispatch briefs from the stale copy" | **AGREES** |
| 16 | `skills/shepherd/references/flock.md:50` | "A lane brief carries the lane-plan PATH ... conductor-owned (`agents/conductor.md`) — never a pasted plan slice" | **AGREES** |
| 17 | `skills/bridge/SKILL.md:35,67,77` | `lanes/{lane}/plan.md` — content-shape-required (not merely path-compatible); "MUST carry `## Steps` ... `## Lane acceptance` ... `## Deviations`" | **AGREES** |
| 18 | `content/roles/conductor.md:22-24,41-44,49-50` (cross-implementation portable role spec) | "commits and pushes its own lane branch and writes narrowly under its own lane namespace" / "the one exception is its own lane plan file, kept live as steps complete" | **AGREES** — independent, condensed, cross-harness-portable restatement; NOT one of the three deferred files |
| 19 | `content/RECONCILIATION.md:41-57` (`## write_eligible — a hard fact, not a convention`) | "`conductor` carries no `Write`/`Edit` tool grant at all, yet commits, pushes its own lane branch, and writes narrowly under its own `{run_dir}/lanes/{lane}/` — all via `Bash`" | **AGREES** — explicit cross-implementation doctrine, explains WHY the fact must survive a Codex port |
| 20 | `hooks/tests/test_conductor_write_guard.sh:267-319` | 24-case suite; own-lane ALLOW (relative + absolute), sibling-lane DENY, master-plan DENY, no-marker-solo-conductor DENY | **AGREES** (proven live, §Runtime instruments above) |

**No conflicting site found for R1.** Every site swept — prose, template, guard, test,
and cross-implementation doctrine — agrees with the operator's grant. This matches both
parallel probes' independent conclusions.

## R2 — which git operations a teammate-conductor may run

| # | Site | Asserts | Verdict |
|---|---|---|---|
| 1 | `agents/conductor.md:79` (known starting point, re-verified) | "you commit and push your OWN lane branch — `TEAMMATE-GIT-WRITE` covers cross-lane integration, not your lane commit/push" | **AGREES** |
| 2 | `agents/conductor.md:160` (known starting point, re-verified) | "Commits AND your lane-branch push are yours — stage + commit your lane and push your OWN lane branch directly (`git -C <path>`), no `@worker` for a routine commit/push; cross-lane rebase/merge/cherry-pick and worktree lifecycle stay root's" | **AGREES** |
| 3 | `agents/conductor.md:162` (known starting point, re-verified) | "In-lane commits and your lane-branch push are yours (#1); `TEAMMATE-GIT-WRITE` covers cross-lane integration (rebase/merge/cherry-pick onto dev) + worktree add/remove/prune, NOT your lane commit/push" | **AGREES** |
| 4 | `agents/conductor.md:175` (new — not in the known-five) | "`CONDUCTOR-WRITE-DENIED` — the write guard denied an Edit/Write or an FS/registry-mutating Bash call outside your own `{run_dir}/lanes/{lane}/` (**git is unrestricted**); dispatch `@worker`" | **AGREES** |
| 5 | `agents/conductor.md:187` (known starting point, re-verified) | "Cross-lane git integration (rebase/merge/cherry-pick onto dev, `branch -d`, worktree add/remove/prune) and the registry lock are root-exclusive after all lanes close (`TEAMMATE-GIT-WRITE` ...); you commit and push your OWN lane branch (#222)" | **AGREES**, but see #16 below — internally inconsistent with `conductor.md:162` on whether `branch -d` is in scope |
| 6 | `hooks/scripts/teammate_git_guard.sh:12-56` (full header contract + implementation) | "A teammate session MAY (within its OWN lane worktree/branch): git add, git commit ... git push (publish its OWN lane branch) ... MUST NOT: git merge / git rebase / git cherry-pick / git worktree add|remove|prune" | **AGREES** — mechanical enforcement, proven live above |
| 7 | `hooks/scripts/conductor_write_guard.sh:12-19,162-168` | "v6.3.1: git is NO LONGER blocked here ... the CONDUCTOR commits its lane's coder output DIRECTLY (and at root/solo tier pushes + rebases too) ... Cross-lane INTEGRATION onto the dev branch stays root-exclusive for a TEAMMATE-conductor, but that seam is teammate_git_guard.sh's job, not this hook's" | **AGREES** |
| 8 | `commands/spawn.md:202-206` | "`git_custody: root\|lane` — structured and binding (#230). `lane` (default): in-worktree git add/commit AND your OWN lane-branch git push are YOURS (`agents/conductor.md §Lane walk`); `root`: root holds integration custody" | **AGREES** — live at current line ~241 post-l7-substrate-insertion; text unchanged, only offset shifted; verified via fresh grep at write time |
| 9 | `commands/spawn.md:290` (worktree-add prohibition, current line, shifted from the known `:252`) | "A teammate that creates its own worktree raises `TEAMMATE-GIT-WRITE`" | **AGREES** (worktree ADD only — never mentions push) |
| 10 | `services/cli/shepherd_cli/templates/boot-prompt.md.j2:73-75` (rendered into every teammate-conductor's ACTUAL boot text) | "git merge/rebase/cherry-pick onto a shared branch, or worktree add/remove/prune → TEAMMATE-GIT-WRITE (see `git_custody` below for your in-lane commit/push authority)" | **AGREES** — the single most load-bearing site: this is literally what a live conductor reads, not documentation about it. Independently confirmed by `.../custody-rendered-surface.md`'s own render-instrument probe |
| 11 | `services/cli/shepherd_cli/templates/boot-prompt.md.j2:118` + `lane-plan.md.j2:16` | `git_custody: {{ git_custody }}` rendered field, default `lane` | **AGREES** |
| 12 | `hooks/scripts/coder_git_guard.sh:4-8` | "committing and pushing the coder's output are the conductor's/root's" | **AGREES** (adjacent — confirms conductor holds push authority, from the coder-boundary side) |
| 13 | `skills/shepherd/references/invariant-matrix.md:125` (row 30) | "A teammate-conductor COMMITS and PUSHES its OWN lane branch ... only cross-lane integration ... is root's `TEAMMATE-GIT-WRITE`" — status column: `guard+test+doctrine` / `live (tested)` | **AGREES** — but this row's own citation list (`teammate_git_guard.sh`, `spawn.md`, `conductor.md §Hard prohibitions`, `escalation.md`, `test_teammate_git_guard.sh`) does **not** cover the five CONFLICT/AMBIGUOUS sites below (#14-#17, #19), so the row's "live (tested)" status overstates doctrine-wide coverage even though the guard+test themselves are genuinely live and tested |
| 14 | **`skills/shepherd/SKILL.md:91`** (known starting point, current line post-insertion — was `:89`) | "Git custody is root-exclusive: a teammate that runs `git rebase`/`merge`/**`push`**/`worktree` halts `TEAMMATE-GIT-WRITE`" | **CONFLICTS** — lists `push` among denied verbs with no branch qualifier; contradicts #1-#13. **DEFERRED-UNTIL-L7-LANDS** (`skills/shepherd/SKILL.md` is a live l7-substrate edit target; this exact sentence is outside the current diff hunk but the file itself is claimed) |
| 15 | **`agents/shepherd.md:327-332`** (NOT in the known five — new site found by this sweep) | "`LANE-INTEGRATE` is root's review-before-merge seam ... a teammate attempting a `merge`/`rebase`/`push`/`cherry-pick` or `worktree add/remove/prune` raises `TEAMMATE-GIT-WRITE`" | **CONFLICTS** — same shape as #14 (push grouped with the genuinely-denied integration verbs), in a file that is **not** deferred (`agents/shepherd.md` ≠ any of the three collision files) |
| 16 | **`agents/conductor.md:187` vs `:162`** (internal inconsistency within the SAME file, cross-referenced from `.../custody-rendered-surface.md` Finding 2, independently re-verified here) | `:162` lists `TEAMMATE-GIT-WRITE` scope as "rebase/merge/cherry-pick onto dev + worktree add/remove/prune" (no `branch -d`); `:187` lists "rebase/merge/cherry-pick onto dev, `branch -d`, worktree add/remove/prune" (`branch -d` added) | **CONFLICTS internally** — the rendered boot prompt and the mechanical guard both match the NARROWER `:162` wording; `branch -d` is neither rendered to a live conductor nor checked by `teammate_git_guard.sh`'s `FORBIDDEN_PATTERN`/`FORBIDDEN_WORKTREE_PATTERN` (verified: the guard's verb list is `merge`, `rebase`, `cherry-pick`, plus worktree `add`/`remove`/`prune` only — no `branch` check at all) |
| 17 | **`skills/shepherd/references/wave-routine.md:92`** (NOT in the known five — new site found by this sweep) | "the only differences from the root driver: (a) scope = one lane, not the sprint; (b) integration (rebase/merge/**push**) defers to root (`TEAMMATE-GIT-WRITE`)" | **CONFLICTS** — same shape again (push grouped with rebase/merge as deferring to root); not deferred (`skills/shepherd/references/wave-routine.md` ≠ `skills/shepherd/SKILL.md`) |
| 18 | `skills/shepherd/references/pipeline.md:162` (`§CLOSE-FINALIZE`/`§LANE-INTEGRATE`, cited BY `skills/shepherd/SKILL.md:91`'s own footnote) | "In-worktree `git add`/`git commit` are permitted; `git merge`/`rebase`/**`push`**/`cherry-pick` onto a shared branch are root-only" | **AMBIGUOUS→effectively CONFLICTS** — the "onto a shared branch" qualifier technically distinguishes it from #14/#15/#17 (a lane branch isn't shared), but it still visually groups `push` with the three genuinely-denied verbs in one root-only list, which is the exact misreading the dispatcher-patch (`.shepherd/dispatcher-patches/v645-pc-1.md`) says root ITSELF made this session when authoring the `l7-substrate` brief. Not deferred |
| 19 | `skills/shepherd/references/escalation.md:57-64` (`## Heartbeat` → "Wave-boundary commit") | "Teammate MUST fire wave-complete, then wait for resume ... **Root MUST commit landed artifacts** every `TaskCompleted`: `git commit -m "chore(...): wave-complete via spawn"`" | **CONFLICTS / STALE** — reads as the pre-#222 model (root does the wave-boundary commit), contradicting the current model where the conductor commits its own lane directly. Not deferred; LOW-MEDIUM confidence this section was simply never updated for #222 rather than describing a still-live alternate mode (no mode qualifier is stated) |
| 20 | `docs/permissions.md:69-71` (operator-facing `settings.json` allowlist guidance) | "Do NOT blanket-allow `Bash(git commit:*)`, `Bash(git push:*)`, or `Bash(git rebase:*)`. Git custody is deliberately gated; leave those to prompt so an unexpected integration always surfaces" | **TENSION, not a strict conflict** — advises interactive-prompt gating for `push` generally, which is operationally incompatible with the documented unattended-teammate model (`commands/spawn.md`: "For unattended lanes, launch root in `acceptEdits`/auto mode"). Doesn't name conductor vs root; a literal reading would stall every lane push on a human who isn't there. Flagged as an open question, not filed as a hard CONFLICT (LOW confidence on operator intent) |
| 21 | `hooks/tests/test_v639_wiring.sh:57-62` | `have commands/spawn.md 'lane-branch git push are YOURS'`; `missing hooks/scripts/teammate_git_guard.sh 'merge\|rebase\|push'` (asserts push NOT grouped as forbidden in the guard) | **AGREES** — proven live, exit 0, in this sweep's own run |
| 22 | `content/roles/conductor.md:41-44,51-52` | "stage and commit the reviewed files directly ... and push this lane's own branch — this is the one general-purpose write this role performs" / "Never spawns another lead, writes cross-lane, or performs cross-lane version-control integration" | **AGREES** |
| 23 | `content/RECONCILIATION.md:52-56` | "yet commits, pushes its own lane branch, and writes narrowly under its own `{run_dir}/lanes/{lane}/` — all via `Bash`" | **AGREES** |
| 24 | `content/roles/shepherd.md:34-36` | "Close: ... run every close-time version-control operation itself (rebase-merge the run branch forward, delete it, cut the next one) — this role's own git custody, never delegated" | **AGREES** (silent on mid-sprint lane push; scoped to root's OWN close-time integration, no contradiction) |
| 25 | `CHANGELOG.md:259,401-402,533,1444,1817-1819` | Full narrative of the #222/#187/#99 resolution history; explicitly names `skills/shepherd/SKILL.md`'s prior contradiction and states the intended single model | **HISTORICAL — AGREES with current grant, not itself an enforcement site** (documents the resolution, doesn't enforce it) |

## Summary — sites beyond the known five

The known starting points (`agents/conductor.md:79,160,162,187` — all AGREE — and
`skills/shepherd/SKILL.md:89`/now `:91` — CONFLICTS) were re-verified and hold. This sweep
found **five additional CONFLICT/tension sites the known-five list did not name**:

1. `agents/shepherd.md:331` — CONFLICTS, same "push grouped with merge/rebase/cherry-pick" shape, **not deferred**.
2. `skills/shepherd/references/wave-routine.md:92` — CONFLICTS, same shape, **not deferred**.
3. `skills/shepherd/references/pipeline.md:162` — AMBIGUOUS-effectively-CONFLICTS (the "onto a shared branch" qualifier saves it technically but not practically — this is the exact sentence the dispatcher-patch says root itself misread), **not deferred**.
4. `agents/conductor.md:162` vs `:187` — internal inconsistency on whether `branch -d` is in `TEAMMATE-GIT-WRITE`'s scope (cross-validated against `.../custody-rendered-surface.md` Finding 2), **not deferred**.
5. `skills/shepherd/references/escalation.md:57-64` — stale pre-#222 "root commits" wording, **not deferred**.

Plus one operational tension (not a doctrine conflict): `docs/permissions.md:69-71`'s
blanket "don't pre-allow push" advice sits awkwardly against the unattended-teammate
operating model.

**"Finding only the known five means the sweep was too narrow" — confirmed and satisfied.**
16 additional AGREE sites and 5 additional CONFLICT/tension sites were found beyond the
five given, across guard scripts, rendered templates, Python source, hook wiring,
cross-implementation doctrine, and test suites — not just prose.

## Deferred (inside `l7-substrate`'s live edit targets — flagged, not edited)

| File | Custody content found | Status |
|---|---|---|
| `commands/spawn.md` | Line 12-13: "root ... **runs every git operation**, and executes the post-sprint merge" (header summary — overbroad if read literally against the `git_custody: lane` default two sections later); lines ~241/290 (current, shifted): AGREE sites (#8/#9 in the R2 table) | **DEFERRED-UNTIL-L7-LANDS** — the header line is a candidate CONFLICT-by-overbroad-summary, flagged here, not touched |
| `skills/harness/SKILL.md` | **Zero custody hits** — the one `cherry-pick` grep match (`:358`, "wave-gate cherry-pick" hook naming) is unrelated to git custody | **DEFERRED-UNTIL-L7-LANDS** (nothing to fix here re: R1/R2, confirmed by direct read, not just grep) |
| `skills/shepherd/SKILL.md` | Line 91 (current, was `:89`): the known CONFLICT site, text unchanged by the live diff (diff only inserts a `PROBE-FALSIFIABILITY` paragraph earlier in the file, at what is now lines 79-80) | **DEFERRED-UNTIL-L7-LANDS** — confirmed still present verbatim as of HEAD 1441b5d + current uncommitted state |

## Files swept with zero custody hits (breadth evidence, not exhaustive)

`commands/start.md`, `commands/plant.md`, `commands/focus.md`, `commands/loop.md`,
`commands/cleanup.md`, `commands/ctx.md`, `content/skills/shepherd/SKILL.md`,
`docs/configuration.md` (one unrelated "custody" hit — cross-harness run ownership, a
different meaning of the word, `:162`), `packages/harness-codex/`, `packages/compiler/`,
`packages/harness-pi/`, `examples/`.

## Open questions

- `skills/shepherd/references/escalation.md:57-64`'s "Root MUST commit landed artifacts
  every `TaskCompleted`" — genuinely stale pre-#222 text, or a still-intentional
  description of a SOLO/no-teammate mode with no mode qualifier stated? LOW confidence on
  intent; the text itself is unambiguous but its applicability is not stated.
- `docs/permissions.md:69-71`'s blanket "don't pre-allow push" advice — intended as a
  human-operator-session-only recommendation (root's own interactive session, where a
  human IS present to answer the prompt), or as guidance that was never reconciled with
  the unattended-teammate `acceptEdits`/auto-mode operating model `commands/spawn.md`
  itself documents? LOW confidence.
- Whether `conductor_write_guard.sh` fires end-to-end against a genuine live in-process
  Agent-Teams teammate's real `Write`/`Edit` call (vs. direct script execution with a
  synthetic payload, which is what every control above used) — flagged as an open
  question by the parallel `custody-lane-plan-write.md` probe; not re-tested here since
  spawning a live teammate is out of scope for a read-only mapping task.

## Provenance

- HEAD at write time: `1441b5d38ffd93307ce3e81853c6289e40df2108` (branch `v6.4.5`).
- `git status --porcelain` confirmed three files modified-uncommitted by `l7-substrate`
  (`commands/spawn.md`, `skills/harness/SKILL.md`, `skills/shepherd/SKILL.md`) — none
  touched by this task.
- Test suites run for evidence (own exit code via file redirect, not pipe):
  `hooks/tests/test_teammate_git_guard.sh` (17/17, exit 0),
  `hooks/tests/test_conductor_write_guard.sh` (24/24, exit 0),
  `hooks/tests/test_v639_wiring.sh` (exit 0, includes the #222 push-not-blocked assertions),
  `hooks/scripts/plan_proof_guard.sh --self-test` (exit 0, own positive+negative controls).
- Cross-referenced (read-only): `.shepherd/runs/v645/reports/custody-rendered-surface.md`,
  `.shepherd/runs/v645/reports/custody-lane-plan-write.md`.
- Scratch artifacts (test outputs, exit-code files):
  `/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/584d4292-bcf5-4461-ae9e-ff122471bc30/scratchpad/`.
