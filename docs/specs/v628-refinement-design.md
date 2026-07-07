# v6.2.8 — Refinement sweep: modular skills, slim surface, harness integration

Status: EXECUTING. Author: root session 2026-07-06. Scope: v6.2.8 (PR #176 → squash-merge to main).
Evidence base: `scripts/filetree.sh` baseline + `scripts/xref.py` graph + 25-file behavior inventory +
SYNTHESIS (30 overlap clusters, 61-entry guard-string registry, 20-item risk list) at
`/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/f921457f-0a68-4006-b466-d5999e99c9bd/scratchpad/inventory/`.

## 1. Outcome (measurable)

| metric | baseline | target | gate |
|---|---|---|---|
| prompt surface (filetree.sh words) | 201,780 | ≤ 70,000 | filetree.sh after-table in PR body |
| spawn-path load (spawn.md + agents/shepherd.md + shepherd SKILL entry) | ~19,700w (~26k tok) | ≤ 5,500w | wc -w sum |
| behavior change | — | ZERO | 4 suites green + guard registry intact + fidelity verifiers pass |
| doctrine file count | 71 + README | 0 (dir deleted) | ls |
| skills | 3 (2 monolith + thinking) | 6 modular | ls skills/ |

Standards (research-confirmed 2026-07-06, code.claude.com/docs): SKILL.md target <10k chars (operator
ceiling 2x = 20k); descriptions ~200 chars, trigger-specific; agent/command/skill bodies lazy-load —
cost is per-dispatch/per-invoke; conditional content lives in references/ read on demand; no version
history narration in prompt surface (current-state wording only — history is CHANGELOG/git's job).

## 2. Target tree (NEW = does not exist on v6.2.8 today)

```
skills/
  shepherd/SKILL.md                      REBUILT ≤10k chars — pipeline (INTRO/BODY/CLOSE), lane law,
                                         dispatch table + halt codes, hard stops, invocation map
  shepherd/references/pipeline.md        REBUILT — stage graph, PLAN/WAVE/CLOSE gates, CLOSE-FINALIZE
                                         canonical git ops (single copy), chain-repair AMEND template
  shepherd/references/flock.md           REBUILT — role table, per-role dispatch briefs + dense per-role
                                         algorithms (critic cargo-reachability VERBATIM, auditor priors
                                         VERBATIM), INSIGHTS pointer. Replaces flock.md + agent-briefs.md
                                         + 6× agents/*.reference.md
  shepherd/references/spawn-flags.md     NEW — --scope/--parallel/--auto/--staged detail (read on flag)
  shepherd/references/seed-template.md   SLIMMED in place (keeps SEED-GATE, TODO:/FIXME:, no-Lane-N —
                                         fix self-contradicting Lane N examples, risk #8)
  shepherd/references/branching-model.md SLIMMED (keeps RELEASE-TRIGGER-DEVLAST quoted clause,
                                         sprints_per_patch, v{X}.{Y}.{Z}-dev.{N} shape)
  shepherd/references/grading-rubric.md  SLIMMED — sole grade table (agent-briefs copy dies); keeps
                                         OUTCOME-REGRESSION grade-cap rule (risk #20)
  shepherd/references/escalation.md      NEW — spawn-escalation payload schema (7 mandatory fields
                                         VERBATIM, risk #13) + halt-code index (prose-only codes listed
                                         once, one line each)
  adaptation/SKILL.md                    NEW — harvest→store→inject→cite contract (self-improvement +
                                         adaptation-loop merged, cluster 5), decay-6, prior:<mem_id>,
                                         INSIGHTS taxonomy (canonical, cluster 19), agent-excellence bar
                                         (canonical strive-higher text, cluster 16), autonomous-sentinel
                                         triple-gate ALL-THREE language VERBATIM (risk #6)
  motivation/SKILL.md                    NEW — focus record + FOCUS-HEARTBEAT (two-legs distinction
                                         VERBATIM, risk #11), /goal wiring (operator-armed: session emits
                                         copy-paste line; lead-session-only fact), /loop self-paced use,
                                         coordinate-active-drive (drive contract + 2-nudge backstop
                                         pointer), outcome-enforcement seams (PLAN-MISSING-OUTCOME-
                                         VERIFICATION / OUTCOME-REGRESSION pairing VERBATIM, risk #20)
  harness/SKILL.md                       NEW — Claude Code capability map: Agent Teams (teammate-spawn,
                                         no nesting, no /resume, inherit-allowlist), Workflow tool
                                         (agent/pipeline/parallel), /loop modes, /goal semantics,
                                         ToolSearch scope rule, lazy-load economics, tool-allowlist +
                                         PreToolUse-hook pattern (canonical capability-enforcement block,
                                         cluster 17). Reference-links to code.claude.com/docs URLs for
                                         deterministic freshness pulls
  harness/references/workflow-templates.md  REBUILT — compile-down invariants + workflow self-check +
                                         await-ordering/no-heartbeat-relay (clusters 15, 20) + template
                                         library (compressed)
  harness/references/loop-templates.md   REBUILT — 8-part skeleton stated ONCE + per-loop unique rows
                                         (cluster 29: 8153w → ~1600w), FOCUS-LOOP lives in motivation,
                                         pointed to (cluster 27)
  thinking/SKILL.md                      KEEP body verbatim (operator-authored); frontmatter description
                                         gains trigger wording only
  context/SKILL.md                       SLIMMED — shctx entry: memory, dedup, locks, WAL DB, models
  context/references/schema.md           SLIMMED lightly (20%)
  context/references/naming-conventions.md  SLIMMED
  context/references/profiles.md         SLIMMED
  context/references/model-map.md        MOVED from doctrines/ — [models] table system (keep; test #52
                                         citation triad updated in same commit)
  context/references/handoff-template.md UNTOUCHED (13 gsub tokens, registry #59)
  context/styles/*.md                    SLIMMED ~40% (6 files stay — test_style.sh asserts existence)
agents/*.md (9)                          SLIMMED — role contract + halt codes + skill-load list; shared
                                         content becomes pointers. conductor.md TEAMMATE-only + absorbs
                                         start.md T0 boot checks. planter.md absorbs plant.md duplication
                                         (cluster 9) + N=0 rule VERBATIM (risk #14) + SEED-READY emit step
commands/spawn.md                        REBUILT ~1800w — preflight checks table, teammate boot prompt
                                         (canonical, cluster 6), dispatch, model pin; flag detail →
                                         spawn-flags.md; --staged delayed-start wait loop
commands/start.md                        DELETED — solo path retired; teammate boot folds into
                                         conductor.md + spawn boot prompt (no command indirection)
commands/{plant,ctx,focus,loop,cleanup,toolkit}.md  SLIMMED to operator-surface stubs pointing at skills
docs/{configuration,customization,integration}.md   SLIMMED (fix [focus].loop_default vs loop_max_default
                                         drift by reading cmd_config.sh/cmd_loop.sh source of truth, risk #19)
README.md                                SLIMMED (intra-file duplicate tiers table, cluster 30)
CLAUDE.md                                UNTOUCHED (operator-authored repo instructions)
skills/shepherd/doctrines/               DELETED (71 files + README + _candidates) — all load-bearing
                                         content folded per §4; hook/test citations retargeted per §5
skills/shepherd/pipeline.md, flock.md    DELETED (content → references/)
skills/shepherd/agents/*.reference.md    DELETED (content → references/flock.md)
skills/shepherd/references/{agent-briefs,glossary,workflow-templates,loop-templates}.md  DELETED
                                         (folded: briefs→flock.md, glossary→harness, templates→harness/references)
```

## 3. shctx surface (44 → 40)

PRUNE (verify zero-callers again at execution, then delete script + test + dispatcher row + usage line):
- `escalate` (0 external refs; spawn-escalation flow uses SendMessage payloads, not this cmd)
- `handoff` (1 ref; close-handoff template rendering unused by pipeline — staged handoff uses MAILBOX)
- `watch` (2 refs; dir-watch doctrine folds to a one-line mention; schema table stays, harmless)
- `profile` → MERGE into `models` (cmd_models.sh is the maintained heir; `[models]` table stays THE
  mapping system per operator directive). `shctx profile` alias may print a deprecation pointer for one
  version if trivially cheap; otherwise clean delete + test update.
KEEP-SLIM usage text: export, lock, mailbox (staged handoff dependency), panes, ready, toolkit.
Everything else: keep. `models resolve` untouched (test_models_resolve.sh).

## 4. Fold map (doctrine → destination; content-level, not file-copy)

skills/shepherd (SKILL.md or references/): dispatch-tier-separation, dispatch-cascade,
dispatch-generosity, specialist-dispatch, primitive-axis-binding, hotfix-dispatch, spawn-escalation,
wrapper-must-earn (keep smell-test regex VERBATIM, risk #15), chain-repair (AMEND template VERBATIM,
risk #10), stage-graph, root-shepherd-orchestration, flock-output-review, auditor-readonly,
auditor-hypothesis-driven, discovery-readonly, discovery-combo-wave + intro-combo-wave (merged,
cluster 10), engineer-self-contained-plan, worker-patterns, coder-brief-format-shared-artifacts,
operating-philosophy, subtract-dont-add, invariant-enforcement-matrix, operator-signaling +
mid-flight-operator-amendment (merged, cluster 24), teammate-integration-authority,
lane-task-ownership, scope-scale-workload, sprint-as-patch, version-scale-roadmap (DELETE stale
"Application to this repo" v5.1.x section, risk #9), seed-naming, seed-anchored-by-issues,
carry-forward-refresh + issue-ledger-awareness (merged, cluster 23), worktree-confinement,
worktree-base-drift (BASE-DRIFT halt sentence VERBATIM, risk #3), conductor-cwd (§Ban 1/§Ban 2/
§Mandatory verification header text preserved INSIDE the new home; hook pointer text updated in L6,
risk #1), cargo-sequential-gates, gates-restoration (exception list VERBATIM, risk #18), staged-handoff,
use-mcp-not-cli, plugin-reload-escape, work-bound-to-tracking (5-language primitive table VERBATIM,
risk #17), workspace-member-isolation-gate (6-ecosystem table VERBATIM, risk #16), hook-event-log.

skills/adaptation: adaptation-loop + self-improvement (merged), agent-excellence, flock-cohesion
(INSIGHTS taxonomy canonical), autonomous-sentinel, loop-templates(doctrine — sentinel/loop-cap rules).

skills/motivation: coordinate-active-drive (drive half), outcome-enforcement, focus command doctrine.

skills/harness: claude-code-platform-alignment, native-coordination + workflow-compile-down (merged,
cluster 15), workflow-patterns, workflow-tool-self-check, capability-discovery §II + toolkit table
(merged, cluster 18 — canonical table here; context skill points to it).

skills/context: context-registry + sqlite-canonical-state (merged, cluster 14), shape-dedup +
zero-duplicate-tolerance (dedup mechanism), model-map (as references/model-map.md), workdir-prune,
preflight-doctor, dir-watch (one line), cache-telemetry + brief-cache-discipline (cache discipline).

DELETE outright: pattern-b-overlap (superseded by stage-graph parallel_with — keep parallel_with field
doc in pipeline.md), doctrines/README.md (index dies with dir), _candidates/ (1 unadopted file).

## 5. Guard/test lockstep contract (lane L6, single commit with suites green)

The 61-entry registry in SYNTHESIS.md §2 is binding: every Category-A string survives VERBATIM in the
new home of its "lives in" file. Path retargets required (hook message text + test literals):
- hooks/scripts/* messages citing `doctrines/<slug>.md` (20 distinct paths, xref-counted) → new skill
  section paths.
- test_engineer_self_contained.sh: `WP=skills/shepherd/doctrines/workdir-prune.md` → new path; the
  model-map citation triad ("model-map.md", "shctx models resolve", "shctx models resolve conductor")
  must keep appearing in agents/shepherd.md, agents/conductor.md, commands/spawn.md.
- dispatch_guard.sh + tests: `dispatcher: conductor-solo` retired with start.md — critic dispatch gate
  becomes root-shepherd-only; test_dispatch_guard.sh updated; grep whole repo for `conductor-solo`.
- test_flock_output_review.sh greps agents/auditor.md for `WAVE-REVIEW VERDICT` and conductor/shepherd
  for `REDO loop`/`REDO-DIRECTIVE` — slimmed agents keep those exact strings.
- user_prompt_submit.sh `/shepherd:start` routing row removed.
- seed/plan/close/worktree filename-shape strings (#8-#13) unchanged everywhere.

## 6. Staged handoff (--staged) — refined contract

Planter session: seed authored with operator → `shctx seed verify` green → `shctx mailbox send` kind
`seed-ready` to `shepherd-spawn-<slug>` (EXACT values, test_staged_handoff.sh) with seed path + branch →
emit SEED-READY banner → rest. Shepherd session (spawned in parallel): preflight → detect --staged →
ARM DELAYED START: poll `shctx mailbox recv --kind=seed-ready` via ScheduleWakeup ≤270s cadence
(deterministic check, no latent polling); timeout `[spawn].staged_timeout_minutes` (default 90) →
STAGED-TIMEOUT halt to operator; on signal → `shctx seed verify` → normal pipeline. No new schema.

## 7. /goal + /loop integration (motivation skill owns wording)

/goal is operator-armed (native CLI command; sessions cannot invoke it). Deterministic templates:
- Root, at PLAN-GATE approval, emits copy-paste line: `/goal all lanes of <branch> report CLOSE-FINALIZE,
  all 4 test suites pass, and the ROOT CLOSE REPORT has been emitted`.
- Planter (standalone) emits at session start: `/goal <slug>.seed.md exists, passes shctx seed verify,
  and SEED-READY has been emitted to the mailbox`.
- Teammates: /goal unavailable (lead-only) → focus record + FOCUS-HEARTBEAT is the lane-outcome loop.
Facts stated in harness skill: goal survives --resume, small-model evaluator, auto-clears, 4k-char cap.

## 8. Rewrite rules (determinism — every lane author binds to these)

1. Load-bearing lines use MUST/NEVER/exact numerals. Banned on load-bearing lines: should, consider,
   may want, generally, typically, ideally, try to, when possible, as needed.
2. Every ALL-CAPS halt code from the old corpus appears in the new corpus EXACTLY ONCE as definition
   (references/escalation.md index or its owning section) and elsewhere only as bare code name.
3. No version-history clauses ("v6.0.9+", "(was X)", "retired #70") — state current rule only. The
   Rule-of-history exception: a rule that exists to prevent a documented past mistake keeps its one-line
   WHY (e.g. N=0 rule, per-lane worktree pruning).
4. Verbatim-preservation list = SYNTHESIS risk items 3,4,5,6,10,11,13,14,15,16,17,18,20 + all registry
   strings. Copy exact; do not paraphrase.
5. Descriptions (frontmatter): ≤200 chars, start with what it does, then "Use when...".
6. Cross-references: exact repo-relative path + § anchor. No "[[wiki]]" links, no dangling anchors —
   lint gate greps every cited path for existence.
7. Discovery report shape: agents/discovery.md body is CURRENT; discovery.reference.md is STALE — fold
   from the body, not the reference (risk #7).

## 9. Execution lanes (worktrees off v6.2.8; merge train; L6 last; suites green before push)

| lane | owns (disjoint) | output |
|---|---|---|
| L1 skills-new | skills/{adaptation,motivation,harness}/**, skills/thinking/SKILL.md frontmatter | 3 new skills + thinking desc |
| L2 skill-shepherd | skills/shepherd/** (rebuild; delete doctrines/, pipeline.md, flock.md, agents/, 4 references) | new shepherd skill |
| L3 agents | agents/*.md (9) | slim profiles |
| L4 commands | commands/*.md (delete start.md; rebuild spawn.md; slim 6) | 7 commands |
| L5 context+docs | skills/context/**, docs/*.md, README.md | slim context + docs; shctx prune (scripts+tests+dispatcher) |
| L6 hooks-tests | hooks/**, skills/context/tests/** path/literal retargets | suites green |

Authorship: opus for L2, L3(shepherd/conductor/planter), L4(spawn); sonnet elsewhere. EVERY rewritten
file gets an independent fidelity verifier (sonnet, adversarial): old file + new file + inventory notes
+ registry → verdict PASS/REDO with named losses. REDO cap 3.

## 10. Verification (task #5)

filetree.sh after-sweep (≤70k words); xref.py re-run (no dangling doctrine refs); 4 suites green;
determinism lint (banned hedge-words grep over rewritten load-bearing files); link lint (every cited
path exists); final 3-lens adversarial review (guard-mechanics / behavior-fidelity / modular-boundary)
before push; PR #176 body updated with before/after table; squash-merge to main.
