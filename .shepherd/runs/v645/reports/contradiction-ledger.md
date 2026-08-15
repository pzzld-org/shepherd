---
title: v6.4.5 contradiction ledger
date: 2026-08-13
auditor: "@auditor"
sprint: v6.4.5
concern: completeness (cross-subject contradiction synthesis)
mode: report-synthesis (not close/regression/carry-forward/wave-review)
methodology: consumes an already-completed adversarial citation audit (33 candidates, 23 survived, 10 refuted); this ledger neither re-runs greps nor adjudicates new claims — it sorts, batches, and reports coverage on the 23 survivors handed to it
prior_class_priors: n/a — synthesis task, no fresh falsification performed by this agent
---

## 1. Verdict

The codebase is **not internally consistent**, and the inconsistency has a repeatable shape, not a random scatter. Three fault lines account for 20 of the 23 survivors. **Fault line A — the git-custody push boundary** is the single most-repeated defect: `skills/shepherd/SKILL.md:91` states the push prohibition absolutely ("a teammate that runs `push` halts `TEAMMATE-GIT-WRITE`"), while `agents/conductor.md` (three separate lines: 14, 79, 160) and `skills/shepherd/references/pipeline.md:162` all qualify it to "push **onto a shared branch**" — four independent findings (`git-push-absolute-vs-qualified`, `pipeline_vs_skill_push_qualification`, `TEAMMATE-GIT-WRITE-push`, `GIT-CUSTODY-PUSH`) anchor on the same unqualified sentence in the same file. **Fault line B — declared vs. measured/enforced reality**: doctrine describes a capability, contract, or gate that the runtime does not actually provide or enforce — `tools:` frontmatter grants (`Workflow`, `Glob`, `Grep`, `LSP`) claimed "LIVE" or capability-guaranteeing but measured absent or runtime-scoped-only; a wave gate (`shepherd run wave pending`) documented to exit 6 on defect but that cannot detect a lane omitted from the ledger entirely; a `--impl=rust` acceptance predicate hard-coded to exit 0 regardless of outcome; a `non_issue_labels` config key that the implementation never reads; a `shctx` CLI described as a "thin alias/exec shim" to `bin/shepherd` when it is a standalone bash dispatcher that never calls `bin/shepherd`. **Fault line C — doctrine-vs-doctrine enumeration drift**: two or three canonical copies of the same list (operator-pause count: 5 vs. 6 vs. 7; `[branching]` config schema vs. `branching-model.md`'s prose; `declared_state` enum documented with 3 values vs. implemented with 4) disagree on cardinality because one copy was updated and its siblings were not. The remaining 3 findings (`role-tools-004`, `role-tools-005`, and half of `role-tools-006`) are softer — a granted-then-runtime-scoped tool and an undocumented-but-not-illogical Bash-mediated capability gap — and read more as clarity debt than active contradiction. Net: doctrine drifts from doctrine, and doctrine drifts from implementation, roughly in equal measure; no single layer is uniformly the "truth" the other should converge to.

## 2. Findings (CRITICAL first)

| # | id | subject | site A | site B | conflict (one line) | resolution |
|---|----|---------|--------|--------|----------------------|------------|
| 1 | `GATE-EXIT-CODE-MISMATCH` | gates | `pipeline.md:21` (exit 0 iff pending EMPTY, else exit 6) | `.shepherd/runs/v645/dogfood.md:123` (gate exits 0 against a 5-defect ledger) | The mechanical wave gate cannot distinguish a healthy ledger from one with an unregistered lane — a missing entry makes the gate greener, not redder. | Fix the gate to validate ledger completeness (not just pending-set emptiness) and exit 6 on defect, OR document the actual always-lenient-on-omission behavior in `pipeline.md`. |
| 2 | `shctx-alias-claim-vs-impl` | cli-surface | `skills/context/SKILL.md:13` ("alias shim" to `bin/shepherd`) | `skills/context/scripts/shctx:182-187` (standalone dispatcher, never calls `bin/shepherd`) | An alias must forward to its target; `shctx` is architecturally independent. | Correct `SKILL.md:13`'s description to "standalone bash dispatcher," or refactor `shctx` into a genuine thin wrapper. |
| 3 | `GIT-CUSTODY-PUSH` | ledger-lifecycle | `SKILL.md:91` (push forbidden, absolute) | `conductor.md:160` (push own lane branch, explicitly authorized) | Lane-branch push cannot be simultaneously forbidden and authorized for the conductor teammate. | Narrow `SKILL.md:91` to exclude lane-branch push, per `.shepherd/dispatcher-patches/v645-pc-1.md`; verify the enforcement guard (DF-68) permits lane push / denies cross-lane integration. |
| 4 | `git-push-absolute-vs-qualified` | git-custody | `SKILL.md:91` (unqualified) | `pipeline.md:162` (qualified: "onto a shared branch") + `conductor.md:14` | Same root sentence as #3, cited independently against `conductor.md:14` and `pipeline.md:162`. | Reword `SKILL.md:91` to carry the "onto a shared branch" qualifier `pipeline.md` already has. |
| 5 | `TEAMMATE-GIT-WRITE-push` | artifact-write | `SKILL.md:91` | `conductor.md:79` (`TEAMMATE-GIT-WRITE` covers cross-lane integration only, not lane commit/push) | Same root sentence as #3/#4, cited against a third `conductor.md` grant. | Same fix as #3 — narrow `SKILL.md:91`'s verb list. |
| 6 | `MODEL-PIN-LITERAL-VS-RESOLVE` | dispatch-law | `conductor.md:83` (Workflow `agent()` must pin literally, `[models]` never consulted) | `conductor.md:112` ("resolve each role's model via `shctx models resolve`") unscoped | Line 112 doesn't exclude Workflow dispatch, so a conductor could apply `[models]` resolution where line 83 forbids it. | Scope line 112 explicitly to in-context `Agent()` dispatch; restate the Workflow-pin rule adjacent to it. |
| 7 | `WORKFLOW-GRANT-LIVE-CLAIM-VS-RUNTIME` | teammate-substrate | `conductor.md:73` ("that grant is LIVE") | `skills/harness/SKILL.md:346` (DF-E1: measured tool list carried NONE of the granted tools, 3rd reproduction) | A frontmatter grant is asserted live while measurement shows it is not, on the same substrate. | Qualify `conductor.md:73` to "LIVE on a live Agent-Teams substrate (must be probed)," matching the PROBE step that already follows at line 75. |
| 8 | `OPERATOR-PAUSE-ENUMERATION` | operator-surface | `agents/shepherd.md:342-343` (5, with one pair collapsed) | `skills/motivation/SKILL.md:55` ("closed set of 7," includes end-of-scope ROOT CLOSE REPORT) | Three canonical sources (a third is `skills/shepherd/SKILL.md` ~line 120, 6 items) disagree on count and membership. | Pick one authoritative enumeration and propagate to all three files; fix the stale `agents/shepherd.md` cross-reference (118→120) in the same pass. |
| 9 | `LEARNINGS-DIR-SCHEMA-MISMATCH` | artifact-paths | `skills/bridge/SKILL.md:39` (`.shepherd/learnings/` is durable/tracked, paired with `ctx/`) | `naming-conventions.md:279-281` (tracked list includes `ctx/`, omits `learnings/`) | A schema contract silently drops half of a paired claim. | Add `learnings/` to the tracked list in `naming-conventions.md` (bridge's claim is the more specific, paired one). |
| 10 | `ACCEPTANCE-PREDICATE-RERUN-VS-UNFALSIFIABLE` | gates | `auditor.md:98` (mandatory re-run of every acceptance predicate; now-false caps grade) | `dogfood.md:119` (DF-59: `--impl=rust` hard-coded to exit 0, 0 cases run) | A predicate that cannot fail defeats the re-verification mandate by construction. | Amend `pipeline.md §Gates` to require falsifiability; fix `conformance/run.sh`'s `--impl=rust` branch (lines 90-101) to fail closed when no render suite exists. |
| 11 | `ctx-cmd-path-vs-invocation` | cli-surface | `commands/ctx.md:15` (Step 0 resolves `bin/shepherd`) | `commands/ctx.md:19-26` (Step 1 passes args to `shctx`, never uses the resolved path) | The resolved path is dead code; the command is ambiguous about which tool actually runs. | Remove the unused `bin/shepherd` resolution step from Step 0 (or wire Step 1 to actually use it). |
| 12 | `VERSION-FILES-UNDOCUMENTED` | versioning | `branching-model.md:33` (conductor bumps version files per `[branching.version_files]`) | `docs/configuration.md:170-179` (`[branching]` schema table — `version_files` absent) | Doctrine tells a conductor to read a config key the documented schema doesn't list. | Add `version_files` to `docs/configuration.md`'s `[branching]` table with type/default. |
| 13 | `role-tools-006-doctrines-tools-unreliable-enforcement` | role-tools | `hooks/tests/lint_agent_capabilities.sh:65-68` (`tools:` is declared intent only, proven to diverge from runtime) | `auditor.md:24` (cites `tools:` as a binding read-only/write-restriction contract) | The lint explicitly documents `tools:` as unverified prose; multiple role docs cite it as an enforcement boundary anyway. | **DEFERRED-UNTIL-L7** per the finding's own text — either wire runtime tool-list probes (DF-17 W0-S11) or relocate all capability claims off `tools:` onto doctrine-level enforcement; this is the L7 remediation's core thesis. |
| 14 | `NON-ISSUE-LABELS-CONFIG-MISMATCH` | ledger-lifecycle | `docs/configuration.md:296` (`non_issue_labels`, default list of 4) | `cmd_issues.sh:95` (`_classify_row()` hardcodes a disjoint 6-item list, never reads config) | A user-configurable override in the docs has zero effect on the actual classifier. | Wire `cmd_issues.sh` to read `non_issue_labels` from `shepherd.toml`, mirroring the existing `sprint_branch_pattern` TOML-read pattern (lines 62-63). |
| 15 | `teammate_git_guard_comment_vs_pattern` | git-custody | `teammate_git_guard.sh:87` (comment: forbidden verbs include `push`) | `teammate_git_guard.sh:90` (regex: `(merge\|rebase\|cherry-pick)` — no `push`) | The comment is stale; the enforced regex (and the upstream RULE section) is correct. | Delete `push` from the comment's forbidden-verb list at line 87. |
| 16 | `pipeline_vs_skill_push_qualification` | git-custody | `pipeline.md:162` (qualified: "onto a shared branch") | `SKILL.md:91` (unqualified) | Same root cause as #3/#4/#5, cited via `pipeline.md` this time. | Same fix as #3 — bundled into the same `SKILL.md:91` edit; tracked in `v645-pc-1.md`, **DEFERRED-UNTIL-L7** per the finding's own text. |
| 17 | `REPORTS-AUDITS-GITIGNORE-DOCUMENTATION-DRIFT` | artifact-paths | `naming-conventions.md:149-152` (`reports/`, `audits/` marked "ignored") | `.gitignore:98-102` (explicit `!` negation tracks both) | The table and the actual `.gitignore` (correct, per DF-61) disagree on tracked status. | Update `naming-conventions.md`'s status column from "ignored" to "tracked" for both rows. |
| 18 | `changelog-rewrite-claim-vs-bash-retention` | cli-surface | `CHANGELOG.md:254` ("bash retires behind `bin/shepherd`," `shctx` a "thin exec alias") | `shctx:182-187` (standalone dispatcher; CHANGELOG's own line 306 admits bash was "deliberately left") | The CHANGELOG entry contradicts both the code and itself two paragraphs later. | Correct `CHANGELOG.md:254` to state bash was ported for 7 commands but retained, not retired. |
| 19 | `MOD-BASE-UNDOCUMENTED` | versioning | `branching-model.md:46` (`[branching].mod_base` override, advanced) | `docs/configuration.md:170-179` (`mod_base` absent from schema) | Same shape as #12, second undocumented key in the same table. | Add `mod_base` to `docs/configuration.md`'s `[branching]` table, or mark it planned/reserved in `branching-model.md`. |
| 20 | `role-tools-003-auditor-lsp-unused` | role-tools | `auditor.md:6` (`tools:` includes `LSP`) | `auditor.md` (161 lines, zero other mentions of LSP) | A declared, never-invoked tool violates the project's own "declare only what's used" rule (v5.1.3 Lane A1). | Remove `LSP` from `auditor.md:6`'s `tools:` line. |
| 21 | `DECLARED_STATE_SCOPE-AMBIGUITY` | teammate-substrate | `commands/spawn.md:353` (documents `in-progress`/`complete`/`error`) | `cmd_panes.sh:57-60` (CASE statement also branches on `idle`) | `spawn.md` doesn't document the `idle` state the implementation actually uses. | Document the full `declared_state` enum (`init \| in-progress \| error \| complete \| idle`) and its lifecycle in `spawn.md`. |
| 22 | `role-tools-004-auditor-readonly-vs-write` | role-tools | `auditor.md:6` (`tools:` grants `Write` unconditionally) | `auditor.md:24` (prose restricts Write to report paths, `lock_guard.sh`-enforced) | Frontmatter offers a capability the prose runtime-scopes. | Not a contradiction to fix — capability-offer-plus-enforcement is a valid, working pattern; clarify the doctrine that `tools:` is an offer, not a guarantee (same clarification role-tools-006 needs). |
| 23 | `role-tools-005-conductor-prose-vs-frontmatter-gap` | role-tools | `conductor.md:7` (`tools:` omits `Edit`/`Write`) | `conductor.md:14` (prose: "commit AND push... directly") | Documented git-commit behavior isn't represented in declared tools (Bash covers it, but the gap is unclear). | Clarify in doctrine whether Bash-mediated file mutation counts toward write-capability, or grant `Write` explicitly. |

## 3. Fix waves

All 23 resolutions were mapped to their target file(s) and grouped so that **no two lanes in the same wave touch the same file**. Two findings that MUST share a file (e.g. both edit `docs/configuration.md`) are bundled into one lane, not split.

### Wave 1 — concurrent, file-disjoint (11 lanes, dispatchable now)

| Lane | Findings | File(s) |
|---|---|---|
| L1 | #15 | `hooks/scripts/teammate_git_guard.sh` (comment fix only — line 87) |
| L2 | #6, #23 | `agents/conductor.md` (line 112 model-pin scoping + tools/write-capability clarification) |
| L3 | #9, #17 | `skills/context/references/naming-conventions.md` (add `learnings/` to tracked list; flip `reports/`/`audits/` status to tracked) |
| L4 | #1 | `services/cli/shepherd_cli/commands/run.py` (`wave_pending_cmd`) + `services/cli/shepherd_cli/models_run.py` (`pending_merges` / add ledger-completeness check) — code fix chosen over the doc-only option to keep this lane disjoint from L5's `pipeline.md` edit |
| L5 | #10 | `skills/shepherd/references/pipeline.md` (§Gates falsifiability requirement) + `conformance/run.sh` (lines 90-101, DF-59 fail-closed fix) |
| L6 | #2 | `skills/context/SKILL.md` (line 13 — correct "alias shim" description) |
| L7 | #11 | `commands/ctx.md` (remove dead Step 0 path resolution) |
| L8 | #18 | `CHANGELOG.md` (line 254 — correct historical claim) |
| L9 | #12, #19 | `docs/configuration.md` (`[branching]` table: add `version_files`, `mod_base`) — `branching-model.md` edit not needed if the schema table is the corrected side |
| L10 | #20, #22 | `agents/auditor.md` (remove unused `LSP`; note Write-offer-vs-enforcement pattern) |
| L11 | #14 | `skills/context/scripts/cmd_issues.sh` (wire `non_issue_labels` TOML read, mirroring the `sprint_branch_pattern` pattern at lines 62-63) |

Findings #3, #4, #7, #21 do not appear above — see below.

### Batch FINAL — BLOCKED-ON-L7 (sequenced after Wave 1, not concurrent with it)

Every resolution that touches `commands/spawn.md`, `skills/harness/SKILL.md`, or `skills/shepherd/SKILL.md` per the task's explicit routing rule, **plus** the two findings whose own resolution text self-declares `DEFERRED-UNTIL-L7` / routes through `.shepherd/dispatcher-patches/v645-pc-1.md` (folding them in here avoids opening a second, redundant fix path for the same `SKILL.md:91` sentence):

| Findings | File(s) | Why blocked |
|---|---|---|
| #3, #4, #16 | `skills/shepherd/SKILL.md` (line 91 — the single sentence four findings converge on) | Named blocked file; also explicitly `DEFERRED-UNTIL-L7` / tracked in `v645-pc-1.md` |
| #5 | `skills/harness/SKILL.md` + `agents/conductor.md:73` | Named blocked file (`harness/SKILL.md`) |
| #8 | `skills/shepherd/SKILL.md` (~line 120) + `agents/shepherd.md` + `skills/motivation/SKILL.md` | Named blocked file; reconciliation requires all three, one of which is blocked |
| #21 | `commands/spawn.md` | Named blocked file |
| #13 | `hooks/tests/lint_agent_capabilities.sh` + multiple `agents/*.md` role files (unspecified) | Self-declared `DEFERRED-UNTIL-L7 (DF-17/DF-64/DF-65)` — architecture decision (probe-wiring vs. relocating capability claims) is a precondition, and is the stated core thesis of the L7 lane; bundling avoids a second fix pass over the same role files L7 is already touching |

Note: `agents/conductor.md` and `hooks/scripts/teammate_git_guard.sh` each get touched again in this later batch (conductor.md:73 by #5; teammate_git_guard.sh's enforcement rule, not just its comment, by #4). That's safe because this batch runs *after* Wave 1 completes, not concurrently with it — sequencing, not disjointness, is what protects those two files across the boundary.

## 4. SUBTRACT

**No — this does not net-remove lines.** This is an estimate (I did not implement any fix; I audited the resolution text only), broken out per finding:

- Pure removals: #20 (`-LSP`, ~1 line), #11 (`-`~3 lines, dead Step-0 removal) → **-4**
- Pure edits (reword/reclassify, ~net 0): #3/#4/#5/#16 (bundled `SKILL.md:91`), #15, #17, #2, #18, #9, #10(informational) → **~0**
- Additions (missing documentation or missing validation code that should already exist): #6 (+1), #7 (+3 est.), #8 (+3 est.), #12/#19 schema rows (+2), #23 idle-state docs (+5 est.), #10-gates falsifiability + DF-59 fix (+15 est.), #1 ledger-completeness code (+20 est.), #14 TOML-wiring code (+12 est.) → **~+61**
- #13 (role-tools-006) is architecture-dependent and excluded from the count — could land anywhere from +20 (relocate-claims doc note) to +100s (wire live probes across every role file); not estimable without a decision the finding itself defers.

**Net estimate: roughly +55 to +65 lines added, not subtracted**, before #13's undetermined delta. The dominant contributors are the CRITICAL gate-completeness fix (#1) and the DF-59 falsifiable-acceptance fix (#10) — both are missing *validation logic*, not surplus prose, so the addition is warranted, not bloat. Anyone expecting this ledger to be a cleanup pass should recalibrate: most of what's broken here is doctrine and gates that under-specify or under-enforce, not doctrine that over-specifies.

## 5. Coverage

**Swept and clean (2 subjects — genuine information, not absence of effort):**
- `fanout-vehicle` — audited, zero surviving contradictions.
- `lane-law` — audited, zero surviving contradictions.

**Findings present, subjects covered (11 distinct subject labels, 23 findings):** `gates` (2), `cli-surface` (3), `ledger-lifecycle` (2), `git-custody` (3), `artifact-write` (1), `dispatch-law` (1), `teammate-substrate` (2), `operator-surface` (1), `artifact-paths` (2), `versioning` (2), `role-tools` (4).

**Unswept per the operator's explicit coverage list (never returned — do not report as clean):** `git-custody`, `artifact-write`, `dispatch-law`, `model-map`, `gates`, `versioning`, `role-tools`.

**Coverage discrepancy — flagged, not resolved:** the "unswept" list above and the "findings present" list overlap on six of seven names (`git-custody`, `artifact-write`, `dispatch-law`, `gates`, `versioning`, `role-tools` all carry surviving findings in §2, sourced from the same input this ledger was built from). Only `model-map` is unswept with zero contradicting evidence either way, which is internally consistent. Separately, five subjects with surviving findings (`teammate-substrate`, `operator-surface`, `artifact-paths`, `cli-surface`, `ledger-lifecycle`) are named in neither the clean list nor the unswept list at all. I have not adjudicated this — I did not run the citation-audit dispatch and cannot tell whether the "unswept" label describes a *verification pass* that failed to return (distinct from the *first-pass sweep* that produced these findings, whose subject tags may predate or bypass that verification step) or whether the coverage bookkeeping itself is stale. Treat the "unswept: git-custody / artifact-write / dispatch-law / gates / versioning / role-tools" claim as **unresolved**, not as license to re-scope §2's findings under those subjects — they are reported here exactly as delivered, verified, and survived.

**What this ledger explicitly does NOT cover:** any subject outside the 14 named across the clean/unswept/findings-present lists above (no broader taxonomy was supplied); no runtime re-verification of any quote or file:line citation (that was the input citation-audit's job, already done); no adjudication of the 10 refuted candidates (correctly excluded per instruction); and `model-map` carries zero evidence in either direction — silence there means exactly that, nothing more.
