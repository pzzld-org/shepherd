# v6.2.8 — Refinement sweep: modular skills, slim surface, harness integration (v2)

Status: EXECUTING. Author: root session 2026-07-06. Scope: v6.2.8 (PR #176 → squash-merge to main).
v2 incorporates 3-lens adversarial review (guard-mechanics / behavior-fidelity / operational) — 6
CRITICALs and ~30 amendments applied. Evidence base: `scripts/filetree.sh` baseline + `scripts/xref.py`
graph + 25-file behavior inventory + SYNTHESIS (30 overlap clusters, 61-entry guard registry, 20-item
risk list) at `/private/tmp/claude-501/-Users-jo3-src-fl03-shepherd/f921457f-0a68-4006-b466-d5999e99c9bd/scratchpad/inventory/`.

## 1. Outcome (measurable)

| metric | baseline | target | gate |
|---|---|---|---|
| prompt surface (filetree.sh words, PATCHED kinds — see §5.0) | 201,780 | ≤ 70,000 | filetree.sh after-table in PR body |
| spawn-path load (spawn.md + agents/shepherd.md + shepherd SKILL entry) | ~19,700w | ≤ 5,500w | wc -w sum |
| behavior change | — | ZERO, except §1.1 named removals | 4 suites green + guard registry intact + fidelity verifiers |
| doctrine file count | 71 + README + _candidates | 0 (dir deleted) | ls |
| skills | 3 | 6 modular | ls skills/ |
| shctx commands | 44 | 41 | dispatcher usage |

### 1.1 Named operator-directed removals (the ONLY behavior changes; everything else is wording)
1. `/shepherd:start` command + solo-conductor mode retired (operator: "cleaning everything up even on
   the command surface"; only load-bearing dependency — teammate boot — folds into conductor.md).
2. shctx `escalate` (hook `teammate_idle.sh:67` rewritten same commit), `watch`, `profile` (merged into
   `models`) pruned. `handoff` STAYS (close-pipeline stage in `cmd_sprint.sh:104` + planter gate + suite).
3. `_candidates/` promotion-pipeline template dropped (empty; process intentionally retired).
4. Unwired config keys `[focus].loop_default` / `loop_max_default` deleted from docs (prose-only,
   zero implementation call sites — verified; removing documentation lies, not behavior).

## 2. Target tree (NEW = does not exist today; all others rebuilt/slimmed in place)

```
skills/shepherd/SKILL.md                       REBUILT ≤10k chars — role map, dispatch table + halt codes
                                               (dispatch-tier-separation core), sprint contract, operator
                                               surface, principles, invocation map
skills/shepherd/references/pipeline.md         REBUILT — Stage Graph, lane law (primitive-axis-binding
                                               canonical), combo waves (intro+discovery merged), INTRO
                                               self-contained engineer, PLAN-GATE + CLOSE-GATE checklists
                                               (outcome seams 1-3, PLAN-MISSING-LOOP-CAP), wave review +
                                               REDO, hotfix ladder, DEDUP-GATE enforcement, gates (cargo-
                                               sequential, restoration exceptions VERBATIM, 6-ecosystem
                                               table VERBATIM), CLOSE-FINALIZE canonical git ops, chain-
                                               repair AMEND template VERBATIM, carry-forward+ledger,
                                               dispatch patterns (workflow-patterns)
skills/shepherd/references/flock.md            REBUILT — per-role briefs + write boundaries + dense per-
                                               role algorithms (critic cargo-reachability VERBATIM,
                                               auditor priors VERBATIM, wrapper-must-earn regex VERBATIM,
                                               coder 5-language tracking table VERBATIM), brief assembly
                                               (brief-cache-discipline), dispatch cascade/generosity/
                                               specialist, conductor cwd (§Ban 1/§Ban 2/§Mandatory
                                               verification heading text preserved), teammate bridge +
                                               anti-patterns (platform-alignment ops 40%)
skills/shepherd/references/operating-philosophy.md  NEW (content moved) — standalone file REQUIRED:
                                               session_open.sh:154 runtime -f check + test_shctx_locator
                                               .sh:43 grep the basename. Same basename, new dir.
skills/shepherd/references/invariant-matrix.md NEW (content moved ~intact, ≤20% cut) — 22-row guard-
                                               status ledger (live/deferred/gap)
skills/shepherd/references/escalation.md       NEW — spawn-escalation payload schema (7 mandatory fields
                                               VERBATIM) + prose-only halt-code index (each code defined
                                               EXACTLY once here unless owned by a specific section)
skills/shepherd/references/spawn-flags.md      NEW — --scope (scope-scale-workload), --parallel, --auto,
                                               --staged (staged-handoff contract §6)
skills/shepherd/references/seed-template.md    SLIMMED in place (SEED-GATE, TODO:/FIXME:, no-Lane-N kept;
                                               fix Lane N self-contradicting examples HERE AND in folded
                                               seed-anchored-by-issues content; absorbs seed-naming)
skills/shepherd/references/branching-model.md  SLIMMED (RELEASE-TRIGGER-DEVLAST clause, sprints_per_patch,
                                               v{X}.{Y}.{Z}-dev.{N} kept; absorbs version-scale-roadmap
                                               minus stale v5.1.x section — DELETED)
skills/shepherd/references/grading-rubric.md   SLIMMED — sole grade table; OUTCOME-REGRESSION grade-cap
                                               rule VERBATIM
skills/adaptation/SKILL.md                     NEW — harvest→store→inject→cite (self-improvement +
                                               adaptation-loop merged), decay-6, prior:<mem_id>, INSIGHTS
                                               taxonomy canonical (flock-cohesion), excellence bar
                                               canonical (agent-excellence). NO version: frontmatter.
skills/motivation/SKILL.md                     NEW — focus record + FOCUS-HEARTBEAT (two-legs VERBATIM),
                                               /goal templates §7, /loop discipline + caps (loop-templates
                                               doctrine), drive contract (coordinate-active-drive drive
                                               half; hook backstop = pointer to harness), SOAK (outcome
                                               seam 4), SENTINEL canonical (triple-gate ALL-THREE + 9-rail
                                               table + 7 SENTINEL-* codes VERBATIM). NO version: field.
skills/harness/SKILL.md                        NEW — Claude Code platform map: Agent Teams, Workflow tool,
                                               /loop, /goal, ToolSearch scope rule, tool-presence truth
                                               (NEVER ToolSearch for Workflow/TaskCreate/SendMessage),
                                               lazy-load economics, allowlist+PreToolUse pattern
                                               (capability-enforcement canonical), doc URLs for fresh
                                               pulls. NO version: field.
skills/harness/references/workflow-templates.md  REBUILT — compile-down + native-coordination merged
                                               (await-ordering, no-heartbeat-relay), workflow self-check,
                                               template library compressed
skills/harness/references/loop-templates.md    REBUILT — 8-part skeleton ONCE + unique rows (8153w→~1600w)
skills/thinking/SKILL.md                       Body VERBATIM (operator-authored); description trigger fix
                                               only. NO version: field.
skills/context/SKILL.md                        SLIMMED — shctx entry; absorbs context-registry + sqlite-
                                               canonical-state (merged), dedup detection (shape-dedup +
                                               zero-dup detection half), cache telemetry + event log +
                                               doctor + dir-watch (one line) + workdir hygiene
skills/context/references/toolkit.md           NEW (content moved) — toolkit.json full CLI contract +
                                               2-tier merge + invariants + curated-vs-discovered table
                                               (capability-discovery §II merged — canonical HERE, harness
                                               points to it)
skills/context/references/model-map.md         MOVED from doctrines/ — [models] table system
skills/context/references/schema.md            SLIMMED lightly (verify migration-0006 cache tables doc'd)
skills/context/references/naming-conventions.md SLIMMED
skills/context/references/profiles.md          SLIMMED
skills/context/references/handoff-template.md  UNTOUCHED (13 gsub tokens)
skills/context/styles/*.md                     SLIMMED ~40% (all 6 stay)
agents/*.md (9)                                SLIMMED — role contract + halt codes + skill-load list.
                                               conductor.md TEAMMATE-only + absorbs start.md T0 boot; strip
                                               conductor-solo branches (conductor.md:27, critic.md:78,
                                               engineer.md:67,180). planter.md absorbs plant.md content +
                                               INVERTS its 5 self-citations of commands/plant.md §Step N
                                               to its own sections + N=0 rule VERBATIM + SEED-READY emit
commands/spawn.md                              REBUILT ~1800w — preflight, teammate boot prompt canonical,
                                               dispatch, model pin; flag detail → spawn-flags.md
commands/start.md                              DELETED (§1.1); all 9 citing sites rewritten (planter,
                                               conductor×2, shepherd×2, spawn×2, flock, 2 doctrines-by-fold)
commands/{plant,ctx,focus,loop,cleanup,toolkit}.md  SLIMMED stubs → skills
docs/{configuration,customization,integration}.md   SLIMMED; delete unwired loop_default keys (§1.1.4);
                                               keep [memory].project_doctrines documented (consumer-project
                                               doctrine loading survives)
README.md                                      SLIMMED (dup tiers table)
examples/**                                    PATH SWEEP only (examples/minimal/CLAUDE.md:7, examples/
                                               rust-service/shepherd.toml:52 → new paths)
CLAUDE.md                                      UNTOUCHED
DELETED: skills/shepherd/doctrines/** (73 files), skills/shepherd/pipeline.md, flock.md,
         skills/shepherd/agents/*.reference.md (6), skills/shepherd/references/{agent-briefs,glossary,
         loop-templates,workflow-templates}.md, commands/start.md
```

Frontmatter `version:` fields: ONLY skills/shepherd/SKILL.md + skills/context/SKILL.md (release.yml:210,
260 hardcode this 2-file allowlist — new skills carry NO version field; no release.yml change).

## 3. shctx surface (44 → 41)
- PRUNE `escalate`: delete cmd_escalate.sh + dispatcher row + usage + rewrite `teammate_idle.sh:67`
  (drop open-escalations stat) SAME COMMIT + clean `conductor_write_guard.sh:140` regex token.
- PRUNE `watch`: delete cmd + dispatcher + usage (schema table stays, inert).
- MERGE `profile` → `models`: delete cmd_profile.sh + test_profile.sh (or fold assertions into
  test_models_resolve.sh); [models] table remains THE dispatch mapping system.
- KEEP `handoff` (close-pipeline stage; keep-slim usage text only).
- KEEP-SLIM usage text: export, lock, mailbox, panes, ready, toolkit. All else: keep.

## 4. Doctrine migration table (file-level; L6 retargets FROM this table)

| doctrine (skills/shepherd/doctrines/) | destination |
|---|---|
| dispatch-tier-separation | shepherd/SKILL.md §Dispatch law |
| root-shepherd-orchestration | shepherd/SKILL.md §Root contract |
| operating-philosophy | shepherd/references/operating-philosophy.md (standalone) |
| subtract-dont-add, use-mcp-not-cli | shepherd/SKILL.md §Principles |
| sprint-as-patch | shepherd/SKILL.md §Sprint contract |
| operator-signaling + mid-flight-operator-amendment (merged, cluster 24) | shepherd/SKILL.md §Operator surface |
| scope-scale-workload (merged w/ root-orch §VII walk, cluster 25) | shepherd/references/spawn-flags.md §--scope |
| lane-task-ownership, plugin-reload-escape | shepherd/references/pipeline.md |
| primitive-axis-binding | pipeline.md §Lane law (canonical) |
| stage-graph, pattern-b-overlap(DELETE; parallel_with doc survives) | pipeline.md §Stage Graph |
| intro-combo-wave + discovery-combo-wave (merged, cluster 10) | pipeline.md §Combo waves |
| engineer-self-contained-plan | pipeline.md §INTRO |
| flock-output-review | pipeline.md §Wave review + REDO |
| hotfix-dispatch | pipeline.md §Hotfix ladder (canonical) |
| workflow-patterns | pipeline.md §Dispatch patterns |
| chain-repair | pipeline.md §Phase-0 amendment (template VERBATIM) |
| outcome-enforcement | SPLIT: seams 1-3 → pipeline.md §Gates; seam 4 SOAK → motivation/SKILL.md |
| cargo-sequential-gates, gates-restoration, workspace-member-isolation-gate | pipeline.md §Gates |
| carry-forward-refresh + issue-ledger-awareness (merged, cluster 23) | pipeline.md §CLOSE |
| teammate-integration-authority | pipeline.md §CLOSE-FINALIZE |
| staged-handoff | spawn-flags.md §--staged |
| seed-naming + seed-anchored-by-issues (merged, cluster 26; fix Lane N examples) | references/seed-template.md |
| version-scale-roadmap (stale v5.1.x section DELETED) | references/branching-model.md |
| invariant-enforcement-matrix | references/invariant-matrix.md (≤20% cut) |
| spawn-escalation | references/escalation.md |
| dispatch-cascade, dispatch-generosity, specialist-dispatch | references/flock.md §Dispatch |
| brief-cache-discipline | flock.md §Brief assembly |
| auditor-readonly, auditor-hypothesis-driven, wrapper-must-earn (regex VERBATIM) | flock.md §@auditor |
| discovery-readonly | flock.md §@discovery |
| worker-patterns | flock.md §@worker |
| coder-brief-format-shared-artifacts, work-bound-to-tracking (table VERBATIM) | flock.md §@coder |
| worktree-confinement, worktree-base-drift (BASE-DRIFT sentence VERBATIM) | flock.md §Write boundaries |
| conductor-cwd (§Ban 1/§Ban 2/§Mandatory verification headings preserved) | flock.md §@conductor |
| claude-code-platform-alignment | SPLIT ~60/40: platform facts → harness/SKILL.md; ownership/
  anti-patterns/cmd_teammate bridge → flock.md §Teammate bridge |
| native-coordination + workflow-compile-down (merged, cluster 15) | harness/references/workflow-templates.md |
| workflow-tool-self-check | harness/references/workflow-templates.md |
| loop-templates (doctrine) | motivation/SKILL.md §Loop discipline |
| coordinate-active-drive | SPLIT: drive contract + per-lane-ONLY pruning warning (risk #12 VERBATIM)
  → motivation/SKILL.md; Stop-hook mechanics → harness/SKILL.md (one owner, cluster 11) |
| autonomous-sentinel | motivation/SKILL.md §Sentinel (canonical; adaptation points here) |
| adaptation-loop + self-improvement (merged, cluster 5) | adaptation/SKILL.md |
| agent-excellence | adaptation/SKILL.md §Excellence bar (canonical, cluster 16) |
| flock-cohesion | adaptation/SKILL.md §INSIGHTS (canonical taxonomy, cluster 19) |
| context-registry + sqlite-canonical-state (merged, cluster 14) | context/SKILL.md |
| shape-dedup + zero-duplicate-tolerance | SPLIT: detection/CLI/registry → context/SKILL.md §Dedup;
  DEDUP-GATE dispatch enforcement → pipeline.md §DEDUP-GATE |
| capability-discovery | SPLIT: §II table + registry → context/references/toolkit.md (canonical);
  §V tool-presence truth → harness/SKILL.md |
| toolkit | context/references/toolkit.md (full CLI contract) |
| cache-telemetry | context/SKILL.md §Cache telemetry |
| hook-event-log | context/SKILL.md §Event log |
| preflight-doctor | context/SKILL.md §Doctor |
| dir-watch | context/SKILL.md (one line) |
| workdir-prune | context/SKILL.md §Workdir hygiene |
| model-map | context/references/model-map.md (MOVED) |
| README, _candidates/ | DELETED (§1.1.3) |

## 5. Guard/test lockstep (L6 explicit checklist — §5 v1 was NOT exhaustive; this is)

0. **Tooling first (gate integrity)**: patch `scripts/filetree.sh kind_surface_of()` — add arms
   `skills/adaptation/SKILL.md|skills/motivation/SKILL.md|skills/harness/SKILL.md|skills/thinking/SKILL.md`
   → skill-entry; `skills/harness/references/*.md` → reference; retire dead arms (pipeline/flock,
   doctrines/*, agents/*.reference). Patch `scripts/xref.py`: doc_dir hardcode → graceful-absent; ADD
   `command` pattern `commands/([a-z0-9._-]+?)\.md`. BOTH before §10 gates run.
1. hooks/scripts/* messages citing `doctrines/<slug>.md` (21 files, fresh grep at execution) → §4 paths.
2. `session_open.sh:154` doctrine_path → `skills/shepherd/references/operating-philosophy.md`
   (test_shctx_locator.sh:43 basename grep keeps passing).
3. `test_engineer_self_contained.sh`: vars DOC(:21) MM(:22) WP(:23) → new paths; need-lines :54-55
   (flock.md → references/flock.md), :56-57 (invariant-matrix new path); dangling-citation regex :77-87
   rewritten to lint the NEW `references/`+`skills/` citation shapes (must stay a live check, not no-op).
4. `test_flock_output_review.sh`: DOC(:34), need-lines :66-67 (flock.md), :70-71 (invariant-matrix),
   citation loop — same treatment.
5. `dispatcher: conductor-solo`: NOT in dispatch_guard.sh/tests (verified zero hits) — the work is the
   4 agent-file branches (L3) + any hook message text mentioning solo. Skip `.artifacts/**` in greps.
6. `teammate_idle.sh:67` ESC stat removal (with escalate prune); `conductor_write_guard.sh:140` regex
   drops `escalate` + `profile[[:space:]]+sync` tokens (KEEPS handoff).
7. `user_prompt_submit.sh` /shepherd:start routing row removed.
8. Registry Category-A strings (SYNTHESIS §2) survive VERBATIM in destination files; all filename-shape
   patterns (#8-#13) unchanged.
9. `[memory].project_doctrines` consumer mechanism: config key + on_every_dispatch hook behavior
   unchanged and still documented.
10. Suites: hooks + ctx + llm + eval green before push.

## 6. Staged handoff (--staged): planter authored seed w/ operator → `shctx seed verify` green →
`shctx mailbox send` kind `seed-ready` to `shepherd-spawn-<slug>` (EXACT, test_staged_handoff.sh) →
SEED-READY banner → rest. Shepherd session: preflight → arm delayed start: `shctx mailbox recv
--kind=seed-ready` polled via ScheduleWakeup ≤270s; timeout `[spawn].staged_timeout_minutes` (default
90) → STAGED-TIMEOUT halt; on signal → seed verify → pipeline. No new schema.

## 7. /goal + /loop (motivation owns wording; /goal is operator-armed — sessions emit copy-paste lines)
Root at PLAN-GATE: `/goal all lanes of <branch> report CLOSE-FINALIZE, all test suites pass, and the
ROOT CLOSE REPORT has been emitted`. Planter at start: `/goal <slug>.seed.md exists, passes shctx seed
verify, and SEED-READY has been emitted`. Teammates: focus record + FOCUS-HEARTBEAT (goal is lead-only).
Harness states: survives --resume, small-model evaluator, auto-clears, 4k cap.

## 8. Rewrite rules (binding on every lane author)
1. Load-bearing lines: MUST/NEVER/exact numerals. Banned: should, consider, may want, generally,
   typically, ideally, try to, when possible, as needed.
2. Every ALL-CAPS halt code defined EXACTLY once (escalation.md index or owning section); elsewhere bare.
3. No version-history clauses. Exception: one-line WHY where the rule guards a documented past mistake
   (N=0, per-lane pruning, pause-retired).
4. Verbatim list: SYNTHESIS risks 3,4,5,6,10,11,**12**,13,14,15,16,17,18,20 + registry strings +
   SENTINEL 9-rail table + 7 SENTINEL-* codes + sentinel ALL-THREE clause.
5. Frontmatter descriptions ≤200 chars: what it does, then "Use when…".
6. Cross-refs: exact repo path + §anchor from §11 contract ONLY. Lint: path exists AND anchor heading
   exists.
7. Discovery report shape folds from agents/discovery.md BODY (reference file is stale).
8. Cross-skill dependency rule: a skill's load-bearing rules NEVER require another skill to be loaded.
   Owning skill carries the full rule; other skills carry a one-line restatement + pointer. Bare
   pointers forbidden for load-bearing content.
9. Expected-deletions allowlist for fidelity verifiers (NOT losses): conductor-solo branches, start.md
   solo pipeline, PAUSE-solo semantics, escalate/watch/profile shctx refs, _candidates process, stale
   v5.1.x roadmap section, unwired loop_default keys, version-history narration.

## 9. Execution lanes (worktrees; branches v6.2.8-l1..l5 off v6.2.8; merge train IN ORDER)

Pre-flight gate: `git status --porcelain` clean on root before any `git worktree add`.

| lane | owns | notes |
|---|---|---|
| L1 skills-new | skills/{adaptation,motivation,harness}/**, skills/thinking/SKILL.md | additive; internal fan: 3 authors + verifiers |
| L2 skill-shepherd | skills/shepherd/** | mini-flock: per-file authors (opus: SKILL.md, flock.md, pipeline.md; sonnet: slim-in-place), per-file verifier, REDO cap 3/file |
| L3 agents | agents/*.md | 9 authors; conductor/shepherd/planter opus |
| L4 commands | commands/*.md (delete start.md) | spawn opus |
| L5 context+docs | skills/context/**, docs/*.md, README.md, examples/** sweep | includes shctx prunes (scripts+tests+dispatcher) |
| L6 hooks-tests-tooling | hooks/**, skills/context/tests/**, scripts/{filetree.sh,xref.py} | runs on merged tree, §5 checklist |

Merge order L1→L2→L3→L4→L5 is LOAD-BEARING (anchors flow downstream) even though files are disjoint;
then L6 on the merged tree; suites green; single push. Lanes read the OLD tree + this design; all
cross-lane citations use §11 anchors. Joint-verification pass after L1+L2+L3 merge for every SPLIT
doctrine (outcome-enforcement, platform-alignment, coordinate-active-drive, shape-dedup/zero-dup,
capability-discovery) — one agent checks the two halves compose with no gap/no contradiction.

## 10. Verification
filetree.sh (patched) ≤70k; xref.py (patched) — zero dangling doctrine/command refs; 4 suites green;
determinism lint (banned-hedge grep); anchor lint (§8.6); joint split-doctrine verification; final
3-lens adversarial review; PR #176 body before/after table; squash-merge.

## 11. Anchor contract (FROZEN — citable section headings; lanes may add sections, never rename these)

- skills/shepherd/SKILL.md: `## Dispatch law` `## Root contract` `## Sprint contract` `## Operator
  surface` `## Principles` `## Invocation map`
- references/pipeline.md: `## Stage Graph` `## Lane law` `## Combo waves` `## INTRO` `## PLAN-GATE`
  `## DEDUP-GATE` `## Wave review + REDO` `## Hotfix ladder` `## Gates` `## CLOSE` `## CLOSE-FINALIZE`
  `## Phase-0 amendment` `## Dispatch patterns`
- references/flock.md: `## Dispatch` `## Brief assembly` `## @engineer` `## @critic` `## @coder`
  `## @auditor` `## @worker` `## @discovery` `## @conductor` `## Write boundaries` `## Teammate bridge`
- references/escalation.md: `## Escalation payload` `## Halt-code index`
- references/spawn-flags.md: `## --scope` `## --parallel` `## --auto` `## --staged`
- skills/harness/SKILL.md: `## Agent Teams` `## Workflow tool` `## Loops` `## Goals` `## ToolSearch`
  `## Tool presence` `## Lazy-load economics` `## Capability enforcement`
- skills/adaptation/SKILL.md: `## Loop contract` `## INSIGHTS` `## Excellence bar`
- skills/motivation/SKILL.md: `## Focus record` `## FOCUS-HEARTBEAT` `## Goals` `## Loop discipline`
  `## Drive contract` `## SOAK` `## Sentinel`
- agents/conductor.md: `## Boot verification` `## Halt codes` `## Hard prohibitions` `## Side-effect
  boundary`
- agents/shepherd.md: `## Hard prohibitions` `## Halt codes` `## Mandatory protocol` `## Two-meta-loading`
- agents/planter.md: `## Plant mode` `## Babysitter mode` `## Sprint numbering` `## Seed handoff`
- commands/spawn.md: `## Preflight` `## Teammate prompt` `## Spawn dispatch` `## Flags`
- Citers of old spawn-escalation §VI/§VII/§X/§XI and conductor `#13–#20` numbering: ALL rewritten to the
  anchors above (numbered-range citations forbidden going forward).
