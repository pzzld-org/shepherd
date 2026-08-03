# Old-issue triage — #18 through #39

**Date:** 2026-05-20
**Sprint:** v5.1.7 dev.0 — Lane W1 (IO-bound worker)
**Scope:** Open issues from the v5.0.9 / v5.1.0 / v5.1.1 era — triage classification and operator-pending close recommendations.

## Summary

```
superseded:       3
still-valid:     13
close-as-stale:   1
already-closed:   0
total in range:  17
```

**Recommended for operator close (4 issues):**
- #18 — shctx missing (SUPERSEDED by v5.0.10+ context-skill ship)
- #25 — chronic carries (SUPERSEDED by `carry-forward-refresh.md` + INTRO-COMBO-WAVE)
- #32 — temp `close #31 not_planned` (CLOSE-AS-STALE)
- #39 — teammate-conductor mode (SUPERSEDED by v5.1.6 `/shepherd:spawn` + `/shepherd:start --teammate`)

**Recommended to keep open (13 issues):**
- #19, #20, #21, #22, #23, #24, #26, #27, #28, #29, #30, #31, #33

**Comments posted this run:** 17 (one per open issue in range).

**No issues closed by this worker** — operator review pending per Lane W1 contract.

---

## #18 — v5.0.9: shctx binary missing despite docs referencing it as fast-path for Phase 0 mesh + DEDUP-GATE

**State:** OPEN
**Disposition:** SUPERSEDED
**Evidence:**
- `skills/context/scripts/shctx` exists in tree (5624-byte Bourne-Again shell script, executable).
- `skills/context/SKILL.md:18` documents the canonical install path at `${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/shctx`.
- DEDUP-GATE Layer 2 SQL fast-path lives in `shctx query dedup-check` per `doctrines/zero-duplicate-tolerance.md`.

**Recommendation:** close as resolved by v5.0.10+ context-skill reorganization. Optional follow-up: add a `docs/installing-shctx.md` callout for PATH-shadowing edge cases.
**Comment URL:** https://github.com/FL03/shepherd/issues/18#issuecomment-4504272156

---

## #19 — v5.0.9: bash_guard.sh + session_open.sh hooks render 'additionalContext' as terminal 'PreToolUse:Bash error'

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- `hooks/scripts/bash_guard.sh:15` still emits `{"additionalContext":"..."}` for Checks 4 and 5.
- `hooks/scripts/session_open.sh:80` still calls `emit_json_obj additionalContext "$msg"`.
- No `silent_mode` config, no `systemMessage` channel migration, no `[shepherd-info]` prefix found.

**Recommendation:** keep open. v5.1.6 did not touch hook output format. Defer to a future patch revisiting hook UX. Adopt `[shepherd-info]` prefix as a low-cost interim mitigation.
**Comment URL:** https://github.com/FL03/shepherd/issues/19#issuecomment-4504273496

---

## #20 — v5.0.9: dispatch procedure says 'omit subagent_type' but shepherd:* subagent_types work + are more token-efficient

**State:** OPEN
**Disposition:** STILL-VALID (intentionally — design decision)
**Evidence:**
- `skills/shepherd/SKILL.md:144` continues to prescribe inline-body-prepend with omitted `subagent_type` for every flock dispatch.
- The only `subagent_type` usage is for the `/shepherd:spawn` teammate-conductor handoff (`commands/spawn.md`) where the platform call shape requires it.
- The inline-body pattern is a version-currency safety net — guarantees the runtime sees the SAME profile the plugin shipped.

**Recommendation:** keep open as documentation-clarification request. Append one-line rationale to `SKILL.md:144` explaining the version-currency property.
**Comment URL:** https://github.com/FL03/shepherd/issues/20#issuecomment-4504274587

---

## #21 — wave-gate: missing mechanical check that all agent-* branches were cherry-picked onto sprint branch

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- No mechanical `git rev-list --right-only --count` or equivalent stray-commits scan found anywhere in `agents/`, `commands/`, `skills/`.
- `branching-model.md §V.1` checks merge-base ancestry for dev branches — does NOT iterate `agent-*` worktree branches per wave-gate.
- `agents/conductor.md:227` Step 0 says \"Surface any orphan `agent-*` branches\" but offers no mechanical procedure for the wave-gate phase.

**Recommendation:** keep open — HIGH severity. The 5-line scan is a near-trivial pipeline patch preventing silent data loss. Fold into `pipeline.md §V` WAVE-GATE checklist as a binding pre-gate step. Co-deliverable with #23 and #24.
**Comment URL:** https://github.com/FL03/shepherd/issues/21#issuecomment-4504275496

---

## #22 — zombie worktree-agent-* refs accumulate after force-remove with no cleanup step

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- `preflight-doctor.md` (`shctx doctor`) reports orphan worktree COUNT but does not auto-prune zombie refs.
- `skills/context/scripts/cmd_worktree.sh` (`shctx worktree gc`) handles worktree directories but no `git rev-parse --verify || git branch -D` sweep over `worktree-agent-*` refs.
- `branching-model.md §V.1` orphan detection is dev-branch-focused, not `worktree-agent-*` ref-focused.

**Recommendation:** keep open — LOW-MEDIUM severity. Suitable for a v5.1.x patch touching `shctx worktree gc`. The 4-line snippet from the issue body drops cleanly into `cmd_worktree.sh` as a new `shctx worktree prune-refs` subcommand.
**Comment URL:** https://github.com/FL03/shepherd/issues/22#issuecomment-4504276869

---

## #23 — engineer Phase 0 mesh: 'landed in tree' claims must be verified against sprint branch, not working directory or agent branches

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- `agents/engineer.md` Phase 0 mesh section (lines 221-235) prescribes mandatory ground-truth gathering but does not contain a sprint-branch-specific `git log <base>..<sprint> --oneline | grep <sha>` verification step.
- `skills/shepherd/references/agent-briefs.md:353` references `git log {patch_branch}..HEAD --oneline` for "fixed in current sprint" but appears in a generic agent-brief context, not the engineer mandate.
- INTRO-COMBO-WAVE regression auditor catches regressions AFTER plan is written, not unverified claims INSIDE Phase 0 mesh.

**Recommendation:** keep open — HIGH severity. Compounds with #21 and #24. Add a binding sub-step in engineer's Phase 0 mesh procedure. Co-deliverable in a single v5.1.x verification-discipline patch.
**Comment URL:** https://github.com/FL03/shepherd/issues/23#issuecomment-4504278038

---

## #24 — /shepherd:start Step 0: add agent-branch survey to surface orphaned committed work before loading handoff

**State:** OPEN
**Disposition:** STILL-VALID (partial coverage exists)
**Evidence:**
- `agents/conductor.md:227` Step 0 sub-step 2 surfaces orphan `agent-*` branches but points to `branching-model.md §V.1` which iterates DEV branches, not `agent-*` worktree branches.
- The specific `git rev-list --right-only --count` mechanical check proposed is NOT in the tree.
- `preflight-doctor.md` reports orphan worktree COUNT but does not enumerate commits-ahead per branch.

**Recommendation:** keep open — HIGH severity. Compounds with #21 (wave-gate scan) and #23 (engineer 'landed' verification). Extend `branching-model.md §V.1` with a §V.6 "Agent-branch survey" section.
**Comment URL:** https://github.com/FL03/shepherd/issues/24#issuecomment-4504278994

---

## #25 — completeness auditor does not detect multi-sprint chronic carries; chronic_threshold_patches not enforced across patch boundaries

**State:** OPEN
**Disposition:** SUPERSEDED
**Evidence:**
- `skills/shepherd/doctrines/carry-forward-refresh.md` implements exact mechanism: ledger diff at close, `patches_crossed` counter, automatic chronic-label application when threshold crossed.
- v5.1.1 added `@auditor (mode: carry-forward-disposition)` (`skills/shepherd/doctrines/intro-combo-wave.md:96-114`) as binding intro-mode auditor verifying every ledger entry's chronic-label status against the threshold rule.
- `skills/shepherd/references/agent-briefs.md:689-702` ships copy-paste intro-cfd brief with explicit "Apply chronic label per [ledger.chronic_threshold_patches] rule."
- `auditor-hypothesis-driven.md:222` binds intro-mode auditors to the concern.

**Recommendation:** close as resolved by v5.1.0/v5.1.1 carry-forward-refresh + INTRO-COMBO-WAVE doctrines. If real-sprint regression observed, file new enforcement-gap issue.
**Comment URL:** https://github.com/FL03/shepherd/issues/25#issuecomment-4504280008

---

## #26 — /shepherd:start Step 0: scan for multiple *.plan.md files for current sprint and reconcile addendum plans

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- `agents/conductor.md:352` says `ls {paths.plans}/{sprint_slug}.plan.md` (singular).
- `skills/shepherd/SKILL.md:402` mirrors singular form.
- `version-scale-roadmap.md:96` doctrine says "one plan per patch by default" — intended invariant, but does not address sessions where in-flight addendum is created.

**Recommendation:** keep open — MEDIUM severity. Two-path resolution: (1) enforce the singular invariant (forbid `*.b.plan.md`, redirect to BRIEF-AMENDMENT REQUEST), or (2) support addendum plans (add plan enumeration step). Operator decision required.
**Comment URL:** https://github.com/FL03/shepherd/issues/26#issuecomment-4504281006

---

## #27 — feat: plan materialization — convert sprint plan structure into a GH issue tree as the canonical execution manifest

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- No `issue-driven-dispatch.md`, no `issue-tree-schema.md` in `skills/shepherd/doctrines/`.
- `shctx plan extract` materializes DAG to `<ns>/graph/state.json`, NOT a GH issue tree.
- Adjacent doctrines exist (`seed-anchored-by-issues.md`, `work-bound-to-tracking.md`) but do not make issue-binding a hard precondition for dispatch.
- v5.1.7's new `sqlite-canonical-state.md` pushes rows-canonical / markdown-views direction — parallel design, could coexist with GH-issue-tree manifest.

**Recommendation:** keep open as parent epic. Decompose into sub-issues #28, #29, #30 (per #31). Suitable for v5.2.0 minor sprint taking "plan materialization" as its theme.
**Comment URL:** https://github.com/FL03/shepherd/issues/27#issuecomment-4504282003

---

## #28 — feat(doctrine): `issue-driven-dispatch.md` — bind every agent dispatch to exactly one GH issue

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- No `skills/shepherd/doctrines/issue-driven-dispatch.md`.
- `work-bound-to-tracking.md` establishes ">50% bound" — explicitly allows pure-plumbing lanes without backing issues. Does NOT enforce per-dispatch invariant.
- `seed-anchored-by-issues.md` covers seed-time only, not dispatch-time.

**Recommendation:** keep open as sub-issue of #27. Block on parent epic decision. Doctrine well-specified; ready to land once materialization gate (#30) is built.
**Comment URL:** https://github.com/FL03/shepherd/issues/28#issuecomment-4504283087

---

## #29 — feat(doctrine): `issue-tree-schema.md` — canonical shape of the materialized sprint issue tree

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- No `skills/shepherd/doctrines/issue-tree-schema.md`.
- `shctx plan extract` materializes DAG to JSON not GH issue tree.
- Sprint milestone usage implicit but no schema constrains lane-issue / phase-issue body structure or label conventions.

**Recommendation:** keep open as sub-issue of #27. Block on parent epic decision. Schema is what the materialization gate (#30) validates against — co-deliverable with #28.
**Comment URL:** https://github.com/FL03/shepherd/issues/29#issuecomment-4504284309

---

## #30 — feat(pipeline): insert plan materialization gate at INTRODUCTION close, before first BODY dispatch

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- `pipeline.md` INTRODUCTION ends with PLAN-GATE → `shctx plan extract` (JSON, not GH).
- `agents/conductor.md` Step 1 materializes graph to `<ns>/graph/state.json` not to GH.
- No `MATERIALIZATION CONFIRMED` block; no `issue_read` verification loop; no halt-on-non-conforming-issue gate.

**Recommendation:** keep open as sub-issue of #27. Block on parent epic. Third leg of materialization triad with #28 + #29. Estimated ~30-line change.
**Comment URL:** https://github.com/FL03/shepherd/issues/30#issuecomment-4504285206

---

## #31 — chore: close — tracking comment for #27 sub-issues

**State:** OPEN
**Disposition:** STILL-VALID (housekeeping)
**Evidence:**
- Issue body is a tracking comment cross-referencing #28, #29, #30 as sub-issues of #27.
- All sub-issues still OPEN; parent #27 still OPEN.

**Recommendation:** keep open until #27 closes. Close automatically as part of the #27 close action.
**Comment URL:** https://github.com/FL03/shepherd/issues/31#issuecomment-4504286275

---

## #32 — temp

**State:** OPEN
**Disposition:** CLOSE-AS-STALE
**Evidence:**
- Title is literally `temp`.
- Body is literally `close #31 not_planned` — a directive, not a tracked work item.
- Created 2026-05-14, untouched since.
- #31 is STILL-VALID; this temp issue's directive is moot.

**Recommendation:** close as stale. No tracked work, no decision pending, no signal value.
**Comment URL:** https://github.com/FL03/shepherd/issues/32#issuecomment-4504287220

---

## #33 — v5.1.1: seed-density-by-distance doctrine — lighter seeds for sprints further from execution

**State:** OPEN
**Disposition:** STILL-VALID
**Evidence:**
- No `skills/shepherd/doctrines/seed-density-by-distance.md` (or equivalent).
- `agents/planter.md:160-163` mentions "skeletons for the rest of the patch" but does not enumerate the N=0/N=1/N=2/N>=3 ladder, line-count thresholds, or storage-location rules.
- `skills/shepherd/references/seed-template.md:28` enumerates seed `kind` values but does not define density-by-distance.
- No `shctx plant --skeleton` subcommand.

**Recommendation:** keep open — MEDIUM priority. Low-risk addition: a single doctrine file + brief addendum to `planter.md §III`. Suitable for v5.1.x or v5.2.0.
**Comment URL:** https://github.com/FL03/shepherd/issues/33#issuecomment-4504288147

---

## #39 — feat(shepherd:start): teammate-conductor mode for Agent Teams context isolation

**State:** OPEN
**Disposition:** SUPERSEDED
**Evidence:**
- v5.1.6 introduced `/shepherd:spawn` (`commands/spawn.md`) implementing teammate-conductor mode end-to-end with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true` env-var gate.
- v5.1.6 added `agents/shepherd.md` root-tier profile — main chat as babysitter pattern.
- v5.1.6 added `/shepherd:start --teammate` flag (`commands/start.md:17-21`) — lane-execute-only behavior.
- `skills/shepherd/doctrines/root-shepherd-orchestration.md` codifies orchestration pattern.
- `skills/shepherd/doctrines/dispatch-tier-separation.md` codifies context-degradation isolation property.

Implementation shape differs from the original proposal (dedicated `/shepherd:spawn` command rather than env-var-triggered branching inside `/shepherd:start`) but substantively equivalent — cleaner separation of concerns.

**Recommendation:** close as resolved by v5.1.6 root-shepherd + teammate-conductor delivery (#42). If operators want env-var auto-detect ergonomic enhancement, file a new issue.
**Comment URL:** https://github.com/FL03/shepherd/issues/39#issuecomment-4504289359

---

## Closing notes

- Triage performed by Lane W1 of v5.1.7 dev.0 sprint (IO-bound worker, autonomous).
- No issues closed by this worker per Lane W1 contract — operator review pending.
- Three structural themes surfaced across STILL-VALID issues:
  1. **Verification-discipline patch** (#21 + #23 + #24): wave-gate stray-commit scan + engineer Phase 0 `landed` verification + Step 0 agent-branch survey. Co-deliverable; estimated v5.1.8 patch sprint.
  2. **Plan materialization epic** (#27 + #28 + #29 + #30 + #31): GH-issue-tree as canonical execution manifest. Parent epic; suitable for v5.2.0 minor sprint.
  3. **Planter UX** (#33): seed-density-by-distance doctrine. Single doctrine file; could ride any v5.1.x patch.
- Hook-UI noise (#19), worktree-ref cleanup (#22), and dispatch-procedure rationale (#20) are independent small-touch items that could land opportunistically.
