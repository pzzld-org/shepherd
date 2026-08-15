---
title: Discovery — v6.4.5 planter mesh (GH state, milestones, git, carry-forward, ctx silo)
date: 2026-08-12
discovery_id: discovery-mesh-gh
sprint: v6.4.5
sources_consulted: 24
tool_calls_used: 33
time_used_minutes: 22
---

## Sources

- `gh issue list --repo FL03/shepherd --state open --limit 500 --json ...` (22 open issues, full sweep)
- `gh api search/issues?q=...` (8 targeted body-text searches: monorepo, compiled CLI, Rust CLI, codex-shepherd, pi-shepherd, harness-agnostic, Python CLI, binary distribution)
- `gh issue view` on #279, #278, #277, #274, #261, #235, #239, #266 (full bodies)
- `gh pr list --repo FL03/shepherd --state all --limit 100 --json ...` (97 PRs)
- `gh pr view 273` (the open v6.4.5 release PR)
- `gh api repos/FL03/shepherd/milestones --paginate` (59 milestones) + `gh api repos/FL03/shepherd/milestones/58`
- `git -C ~/src/fl03/shepherd log v6.4.4..HEAD --oneline`, `git status --porcelain`, `git branch --show-current`, `git show --stat` on all 3 commits
- `.shepherd/shepherd.toml` (full)
- `~/src/fl03/shepherd/CLAUDE.md`, `README.md`, `CHANGELOG.md` (top section)
- `.shepherd/runs/v641-dev0/seed.md`, `plan.md` (full)
- `.shepherd/docs/handoffs/` and `.shepherd/docs/reports/` directory listings (mtimes)
- `.shepherd/.gitignore`, `git ls-files | grep .shepherd/ctx`, `git log --all -- .shepherd/ctx/` (existence probes)
- `.claude-plugin/plugin.json` (version field)

## ROW 1 — Open issues, full sweep (CRITICAL)

**22 open issues total.** Zero carry a `non_issue_label` (`wontfix`/`tracking-future`/`design-question`/`rfc`) — the full 22 are actionable by the ledger's own definition.

### Class (a) — CLI / Python-port related — 3 issues

| # | Title | Milestone | Labels |
|---|---|---|---|
| 239 | v6.4.1: complete the canonical Python CLI — port the last 7 shctx commands, retire the bash layer, ship ~/.shepherd global DB | none | none |
| 266 | 6.4.3: CLI venv unprovisioned on upgrade — every `shepherd` command dies with ModuleNotFoundError: typer, blocking /shepherd:spawn's mandated boot-prompt render | none | none |
| 235 | shctx PATH launcher globs only cache/fl03/shepherd/* — silently pins a stale binary (6.3.3) when the plugin ships under another publisher dir (pzzld) | none | none |

**#239 is the load-bearing one for this arc.** Its checklist (port `inject`/`plan`/`graph`/`adapt`/`loop`/`release`/`panes` to native Python, retire the bash shim) reads as DONE in prose but the issue itself is still open with unchecked boxes in GitHub — cross-checked against `.shepherd/runs/v641-dev0/plan.md` (see below): the port landed but bash-layer *deletion* was explicitly deferred ("W3 — bash-layer deletion deferred to a follow-up; SUBTRACT unmet... it is now a mechanical follow-up"). That follow-up never happened. #239 is the direct issue-anchor for "retire the Python CLI" — it already names the exact surface (the bash shim retirement) that a compiled-CLI arc would also have to finish or supersede.

### Class (b) — Pi/harness-portability (Pi/Codex/bridge) — 3 issues

| # | Title | Milestone | Labels |
|---|---|---|---|
| 279 | Create a Pi Agent compatible version of shepherd | v6.5.0 (#59) | tracking |
| 278 | feat(graph): make run-scoped graph state mandatory and keep project state flat | none | none |
| 277 | feat(context): scaffold durable run-local support directories | none | none |

**#279's body is literally empty** — bare title + `tracking` label + milestone assignment, no content, zero comments, zero linked issues found (checked via `gh issue view --comments`). It is a stub, not a spec; anchoring the arc's Pi-harness deliverable to it means the seed has to originate the actual scope.

**#278 and #277 are the real portability signal**, not #279. Both were filed *while dogfooding `FL03/codex-shepherd` v1.0.2* — #278's evidence section states "Verified against primary Shepherd `6.4.4` at commit `104d0730...` during the Codex Shepherd v1.0.2 parity sprint" and cites a concrete defect (`plan extract` writing outside the run boundary when no `--run` is given, and the flag being undocumented — "operators and harness bridges can miss the only explicit run-binding control"). #277 explicitly says "This was requested while dogfooding the `FL03/codex-shepherd` v1.0.2 sprint" and separately name-drops `FL03/axiom` for "lane-oriented run custody". Both are live cross-harness friction reports, not aspirational tracking — stronger anchors than #279 for "harness-agnostic" work.

### Class (c) — monorepo / packaging / distribution — 0 dedicated issues

No open issue is actually about consolidating shepherd + codex-shepherd + pi-shepherd into one repo or shipping a single compiled binary. One false-positive from the body-text search: **#261** contains the literal string "monorepo" but it refers to the *consumer* project's own repo layout ("Claude Code, shepherd 6.4.2, `/shepherd:spawn`, 4 lanes, `git_custody: lane`, bun workspaces monorepo") — unrelated to shepherd's own packaging. Reclassified to (d) below.

**This is the headline gap for class (c): the arc's core packaging/distribution deliverable has no existing issue to anchor to.** The nearest adjacent issues are #235 (publisher-dir/launcher globbing, packaging-adjacent) and #239 (CLI completion) — both already counted in class (a) since they're Python-CLI-specific bugs a compiled binary would structurally eliminate, not monorepo-consolidation asks.

### Class (d) — sprint-pipeline / doctrine — 11 issues

| # | Title | Milestone |
|---|---|---|
| 276 | Replace the SUBTRACT/LOC rule with the one that actually matters: no duplicate code, no renaming around a duplicate, write Rust functionally | none |
| 275 | SUBTRACT grades sprints on LOC, which is a bad proxy — a sprint that ships a new crate is auto-capped at C+ | none |
| 274 | Handoff path conflicts with project CONVENTIONS.md: spawn.md renders {run_dir}/handoff.md, projects file handoffs under docs/handoffs/ | none |
| 270 | Agent() completion never notifies the dispatching conductor — 3/3 across two lanes | none |
| 269 | lanes/{lane}/vars.json and plan.md are two sources of truth with no drift check | none |
| 268 | No sanctioned path for root to re-gate a plan after a legitimate mid-sprint correction | none |
| 267 | /shepherd:spawn Check 3 false-positives on the session's OWN team file | none |
| 263 | Workflow availability is decided by backendType, NOT tier or team membership | none |
| 262 | Nothing joins plan steps against the verdict ledger, so an unaudited step is invisible rather than red | none |
| 261 | Run artifacts live under a worktree-replicated path, so the wave gate reads a different physical file than lanes write | none (bug) |
| 237 | Live-custody doctrine: sprint flock coexisting with a live trading bot | none |

Note #276/#275 are directly relevant framing for a Rust-CLI arc — #276's title literally says "write Rust functionally," meaning the doctrine already anticipates a Rust-language shift for *some* surface, though its scope (the SUBTRACT grading rule) is process, not the CLI itself.

### Class (e) — other — 5 issues

181 (dispatch call-site template/compiler layer), 125 (mega-sprint casual-parallel design), 82 (workflow→conductor artifact-export contract), 53 (heartbeat-payload auto-relay), 47 (--scope=minor/version preflight completion) — all no milestone.

### CHANGELOG-vs-tracker anomaly (drift-risk, flag prominently)

**#266, #267, #268, #269, #270 are listed as "Fixed" in CHANGELOG.md's v6.4.4 section, and #261/#262/#263 are described as shipped/resolved in the v6.4.3 section — yet all 8 are still OPEN in the issue tracker.** Either the fixes shipped and nobody closed the issues (process gap between merge and issue-close), or the CHANGELOG overstates completion. This needs resolving before the arc seed cites CHANGELOG prose as ground truth for what's already done — verify against code, not the changelog, for any of these 8.

### Drift-risk: milestone coverage

**19 of 22 open issues (86%) carry no milestone at all**, including CLI-breaking bugs (#266: every `shepherd` command dies with `ModuleNotFoundError`; #235: fleet-wide stale-binary pinning) and an audit-integrity bug (#261: silent deletion of another lane's audit trail on merge — labeled `bug`). Only #279 (v6.5.0), #53, #47 (both v5.1.8, stale/legacy) have milestones. This is the single biggest structural drift-risk finding: near-total absence of milestone triage across the open backlog, with two production-affecting CLI defects sitting in the unassigned pool.

## ROW 2 — PRs (open + merged since v6.4.4)

**Open:** PR **#273 "v6.4.5"** (`head: v6.4.5` → `base: main`), opened 2026-08-06T01:41:14Z, last updated 2026-08-08T01:17:14Z, body is just a sign-off line ("Signed-off-by: FL03 <joe@pzzld.org>") — no description of scope. This is the standing release PR for the current patch arc; it has been open ~6 days without a CHANGELOG entry to match (see ROW 10).

**Merged since v6.4.4 (tag):** none — v6.4.4 is the most recent tag and #271 ("v6.4.4: the artifact schema stops contradicting itself...") plus release PR #265 are the last merges before the current v6.4.5 branch opened. Full merge history (97 PRs total, back to v5.0.7) confirms no PR has merged into `main` since v6.4.4 — everything since is uncommitted-to-main work sitting on the `v6.4.5` branch (3 commits, see ROW 4).

## ROW 3 — Milestones

**v6.4.5 milestone EXISTS: number 58**, `state: open`, `open_issues: 1, closed_issues: 0`, created 2026-08-06T01:45:59Z (same day PR #273 opened), **no description**. Its one "open issue" is PR #273 itself (GitHub counts PRs as issues) — confirmed via `search/issues?q=repo:FL03/shepherd+milestone:v6.4.5` returning exactly `#273`. **No actual GitHub issue is filed against the v6.4.5 milestone.** `gh issue list --milestone "v6.4.5"` returns `[]`.

**v6.5.0 milestone: number 59**, open, `open_issues: 1` = issue #279 (the empty Pi-port stub). This is the milestone the Pi-harness tracking issue is filed under, one version ahead of the current arc.

Per the brief: since v6.4.5's milestone carries no real issue content, **file at Phase 0** — the seed needs to originate deliverables and anchor them, rather than pull an existing milestone-scoped issue list.

## ROW 4 — git log + working tree

```
$ git -C ~/src/fl03/shepherd log v6.4.4..HEAD --oneline
104d073 update
dde94b7 update
249804f v6.4.5
```

Branch: `v6.4.5`. Working tree: **clean** (`git status --porcelain` empty output).

Commit contents (via `git show --stat`):
- `249804f "v6.4.5"` — version bump: `.claude-plugin/marketplace.json` + `.claude-plugin/plugin.json` (2 files, 3 lines).
- `dde94b7 "update"` — `.claude-plugin/marketplace.json` tweak + **new** `.githooks/open-sprint-pr` (117 lines added) — a new git hook script, undocumented by commit message.
- `104d073 "update"` — `.claude/shepherd.toml` → `.shepherd/shepherd.toml` (pure rename, 0 content changes) — confirms the config canonicalization README.md already documents ("canonical since v6.4.2; the legacy `.claude/shepherd.toml` keeps resolving forever").

**What's already landed:** version bump to 6.4.5, a config-path rename, and a new (uncommented, undocumented in CHANGELOG) `open-sprint-pr` git hook. Nothing substantive toward the CLI-retirement/monorepo theme has landed on this branch yet — it is effectively still at Phase 0.

## ROW 8/9 — Prior close + handoff

**No `close.md` or `handoff.md` exists anywhere in the repo** — searched both `.shepherd/runs/*/close.md`/`handoff.md` (empty result) and a repo-wide `find -iname` (empty result). This is true even for `v641-dev0`, whose own `plan.md` defines "Wave 5 — close" work that includes writing these exact artifacts under the new `.shepherd/runs/{run}/` schema. The schema that mandates `close.md`/`handoff.md` was itself defined by v641-dev0 and never populated by that same sprint — the artifacts were speced but not produced.

Legacy-location fallback: `.shepherd/docs/handoffs/` holds 8 files, **newest is `2026-06-12-v6.1.5-comprehensive-handoff.md`** (2 months stale relative to today, 2026-08-12, and pre-dates the v6.4.x run-scoped schema entirely). `.shepherd/docs/reports/` holds exactly one file, `2026-05-15-discovery-v51-readiness.md` (also stale, pre-v6.4).

**Conclusion: there is no usable "prior close" grade, blocker list, or explicit carry-forward to read for ROW 8/9.** The most recent structured planning artifact is `v641-dev0/plan.md`'s own `## Deviations` log (append-only, read below) — treat that as the closest available substitute for a close report.

### `.shepherd/runs/v641-dev0/` — full read

**seed.md** (v6.4.1-dev.0, approved, XL sprint, 2026-08-02): North star = "One canonical Python CLI (bash shctx layer retired)... one standard `.shepherd/runs/{run}/` layout." Deliverables anchor to #239 (CLI port), #244/#243/#181 (template engine), #230/#242/#220/#59 (contract robustness). Explicit non-goals: no live-custody doctrine work (#237 deferred), no mega-sprint redesign (#125), no heartbeat relay (#53), no --scope completion (#47), no workflow export contract (#82) — **all five of those non-goal issues are still open today**, confirming they were correctly deferred and never picked back up.

**plan.md**: 5-wave plan (CLI foundations → 7 command ports → bash retirement+hooks → doctrine sweep → close). Global constraint: "Bash parity before bash deletion... Net-negative LOC on production source (bash deletion ≈ −4,400 dominates)."

**Deviations (append-only log, the closest thing to a close report):**
- **W1**: a `bin/shepherd` cwd bug found live (poetry `-C` sets cwd, breaking relative-path args) — fixed by exec'ing the venv interpreter directly.
- **W3 — the load-bearing one for this arc**: *"bash-layer deletion deferred to a follow-up; SUBTRACT unmet... The deletion itself was NOT attempted, because it is not a `rm`: 45 scripts + `_lib.sh` go, and with them the 50 bash tests... Starting that with insufficient budget risks a half-deleted tree... Consequence, stated plainly: the sprint is net-POSITIVE (+15,810) against v6.4.1, so the SUBTRACT gate is UNMET, not silently passed. Sequenced steps are in Wave 3 above; it is now a mechanical follow-up."* This is a direct, named, unresolved carry-forward: 45 bash scripts + `_lib.sh` + 50 bash-only tests still exist and still need deletion. This is exactly the kind of debt a "retire the Python CLI for a single compiled canonical CLI" arc must either finish or explicitly supersede — deleting the bash shim becomes moot if the Python CLI itself is being replaced, but the 50 bash-only test assertions (`test_shim_passthrough`, `test_liveness_verdict_parity`, and others) are coverage that has to be ported to whatever replaces both layers, not just deleted.
- **W4**: two smaller implementation notes (conductor lane-plan custody enforced via hook not frontmatter; #229 stale-sweep uses `crashed` not `stale` due to a CHECK-constraint mismatch).

## ROW 10 — CLAUDE.md / README.md / CHANGELOG.md claimed state

**README.md** states: *"Current version: **6.4.4**."* (Versioning section, bottom of file.)

**`.claude-plugin/plugin.json`** already reports `"version": "6.4.5"` — **README.md is stale by one patch**, confirming the version-bump automation (or manual bump) updates the plugin manifest before the docs, and nobody has synced README yet on this branch.

**CHANGELOG.md** has no `## v6.4.5` heading at all (`grep -n "6.4.5" CHANGELOG.md` returns nothing) — the top entry is still `## v6.4.4 — 2026-08-06`. So the branch is version-bumped in the manifest, has an open release PR, and a milestone — but zero release notes written yet.

**CLAUDE.md** (this repo's own, i.e. shepherd dogfooding itself) is the *generic* project CLAUDE.md template (services-first architecture, latent-vs-deterministic split, tests/evals mandate, confusion protocol) — it does not claim a specific shepherd version or roadmap; it is process doctrine, not a state claim.

## ROW 11 — Carry-forward ledger

**`shepherd.toml [ledger]` says:** `carry_forward_file = ".shepherd/ctx/carry-forward.md"`, `phase_0_full_ledger = true`, `chronic_threshold_patches = 2`, `non_issue_labels = ["wontfix","tracking-future","design-question","rfc"]`.

**The file does not exist. Neither does the directory.** `.shepherd/ctx/` is absent from this checkout entirely — confirmed three ways: `ls .shepherd/` lists only `.gitignore, CONVENTIONS.md, docs, profiles, runs, shepherd.toml` (no `ctx/`); `git ls-files | grep .shepherd/ctx` returns nothing; `git log --all -- .shepherd/ctx/` returns nothing (never tracked, ever, in this repo's history). `.shepherd/.gitignore` ignores `root.db*`, `shepherd.lock`, `project.json`, `tmp/`, `logs/` — the SQLite registry and its lockfiles — which is consistent with `ctx/` being a runtime-provisioned directory (`shctx init && shctx refresh --scope=all` per the README quickstart) that has never been run against this repo checkout.

**Zero chronic items can be reported — not because there are none, but because the ledger substrate was never bootstrapped here.** This is itself a Phase-0 action item for the seed: run `shctx init && shctx refresh --scope=all` (or equivalent) before any carry-forward disposition can happen, or explicitly acknowledge the ledger is starting from zero for this arc.

## ROW 12 — Knowledge silo (`.shepherd/ctx/`)

**Cannot be read — the directory does not exist** (see ROW 11). No `*.md` files to enumerate or summarize. This nulls out the "flag anything touching CLI architecture, packaging, distribution, portability, or a prior port attempt" instruction for this row specifically — that signal instead came from `.shepherd/runs/v641-dev0/{seed,plan}.md` (ROW 8/9, the actual prior CLI-port attempt) and from issue bodies #278/#277 (the codex-shepherd cross-harness friction, ROW 1 class b).

Adjacent non-ctx docs worth noting since they sit in the same conceptual space (`.shepherd/docs/specs/`, 15 files, not part of the `[paths].ctx` silo but the closest analog): titles include `2026-05-04-shepherd-context-design.md`, `2026-05-04-shepherd-context-addendum.md`, `workspace-symbol-graph-research.md`, `v628-refinement-design.md`, `v630-dispatch-pin-dsl-decision.md` — none of these titles reference CLI-language choice, monorepo consolidation, or Pi/Codex portability by name; a full-text pass was out of budget scope for this row given the ctx-silo redirect above.

## ALSO — issue #279 (Pi port tracking) full detail

- **Title:** "Create a Pi Agent compatible version of shepherd"
- **State:** OPEN, milestone **v6.5.0** (#59), label **`tracking`**
- **Body: empty string.** Zero comments. `gh issue view 279 --comments` returns `"comments": []`.
- **No linked issues found** — neither in body (there is no body) nor via GitHub's linked-issues surface (none returned by the API call).
- **Practical implication:** #279 is a placeholder anchor only. It establishes that Pi-compatibility is on the roadmap (one version ahead, v6.5.0, not v6.4.5) but carries zero scope. The seed cannot lift requirements from it — it can only cite the issue number as the eventual home for Pi-specific deliverables, or propose amending #279's body once the arc's actual Pi/harness scope is defined. #278 and #277 (both class-b, ROW 1) carry the real technical content for cross-harness friction today.

## SEED-ANCHORS

| GH# | Title | Which arc deliverable it could anchor |
|---|---|---|
| 239 | v6.4.1: complete the canonical Python CLI — port last 7 shctx commands, retire bash layer, ship ~/.shepherd global DB | "Retire the Python CLI" deliverable's direct predecessor/superseder — the outstanding bash-shim deletion (45 scripts + `_lib.sh` + 50 bash-only tests, per v641-dev0 Deviations) becomes moot under a compiled-CLI replacement, but the 50 test assertions are coverage that must migrate, not vanish. Close or explicitly supersede this issue in the seed. |
| 266 | CLI venv unprovisioned on upgrade — ModuleNotFoundError: typer, blocks /shepherd:spawn boot-prompt render | Direct motivating pain for "single compiled canonical CLI" — a compiled binary has no venv-provisioning failure mode at all. Strong "why we're doing this" citation. |
| 235 | shctx PATH launcher globs only cache/fl03/shepherd/* — silently pins a stale binary under a different publisher dir | Direct motivating pain for packaging/distribution consolidation — publisher-dir/launcher fragility is a packaging problem a monorepo + single binary structurally removes. |
| 279 | Create a Pi Agent compatible version of shepherd | The nominal Pi-harness tracking issue (milestone v6.5.0) — empty stub, needs the seed to write real scope into it (or supersede with a new issue) before it can anchor deliverables. |
| 278 | feat(graph): make run-scoped graph state mandatory and keep project state flat | Concrete codex-shepherd cross-harness defect (undocumented `--run` flag, state escaping run boundary) — anchors the "harness-agnostic monorepo" contract-boundary work with a real reproduction, better than #279. |
| 277 | feat(context): scaffold durable run-local support directories | Concrete codex-shepherd cross-harness request (run-local `assets/docs/figures/learnings/memory/scripts/` dirs) — anchors the shared-schema-across-harnesses deliverable with a real ask, better than #279. |
| 276 | Replace the SUBTRACT/LOC rule — no duplicate code, no renaming around a duplicate, write Rust functionally | Doctrine issue that already names "Rust" as a target language for some surface — relevant if the compiled-CLI decision lands on Rust; the seed should reconcile with whichever lane owns the language decision (explicitly out of this discovery's scope per NON-GOALS). |
| 261 | Run artifacts live under a worktree-replicated path — wave gate reads a different physical file than lanes write | Not a monorepo issue despite the keyword hit (its "monorepo" reference is the consumer project's own bun-workspaces layout) — anchors sprint-pipeline/doctrine hardening instead, unrelated to this arc's core theme. Listed for completeness, not recommended as a class (a)/(b)/(c) anchor. |

## Open questions

- Are #266/#267/#268/#269/#270/#261/#262/#263 genuinely fixed (CHANGELOG says yes, tracker says open)? Needs a code-level check, not covered by this read-only pass — the seed should not assume either answer.
- Is `.shepherd/ctx/` absence intentional for this checkout (e.g., a fresh clone that never ran `shctx init`) or a symptom of a broader provisioning gap across FL03/shepherd clones? Not determinable from this repo alone.
- What is the intended relationship between #239 (finish the Python CLI) and the new arc's "retire the Python CLi" theme — supersede, close-as-obsolete, or fold its remaining scope (bash-test migration) into the new work? Not something this discovery can decide (NON-GOALS: no architecture proposals).
- No GitHub issue currently names "codex-shepherd" or "pi-shepherd" as a monorepo target explicitly — is there an out-of-band design doc (Linear, private repo, Joe's own notes) not visible to `gh`/filesystem search that already scopes the consolidation? Not found in this pass.

## Confidence

**HIGH** for ROW 1–4, ROW 10, and the #279/#278/#277/#261 body-text findings — all directly sourced from `gh`/`git` command output, not inferred.
**HIGH** for ROW 8/9/11/12 absence findings — confirmed via multiple independent negative-existence checks (find, git ls-files, git log --all), not a single missed grep.
**MEDIUM** on the SEED-ANCHORS table's "which deliverable" mapping — that judgment call is this report's synthesis, not a sourced fact; treat the anchor suggestions as a starting point for the seed author, not settled scope.

## Suggested follow-ups (optional)

- A second discovery pass (or the engineer's own read) against `services/cli/shepherd_cli/` and `skills/context/scripts/` to get an exact current LOC/file count for the "retire Python CLI" deliverable's actual surface area — this pass stayed GitHub/git/doc-level per the row list and did not walk source.
- Confirm with Joe whether `codex-shepherd`/`pi-shepherd` monorepo consolidation has design material outside this repo (Linear, a private doc) before the seed treats class (c) as a from-scratch scope.
- Resolve the CHANGELOG-vs-tracker anomaly (8 issues) as its own Phase-0 action — closing stale issues or correcting the CHANGELOG is cheap and removes ambiguity before the arc seed cites either as ground truth.

## DISCOVERY REPORT
- Question: Execute planter mesh rows 1,2,3,4,8,9,10,11,12 for the v6.4.5 patch arc (retire Python CLI for a compiled canonical CLI; consolidate shepherd + codex-shepherd + pi-shepherd into one harness-agnostic monorepo) — issue-anchorable facts for the arc seed.
- Sources consulted: 24
- Tool calls used: 33
- Time used: 22 minutes
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/discovery-mesh-gh.md
- Confidence: HIGH
- Status: complete
- Anomalies: (1) 8 issues (#261,#262,#263,#266,#267,#268,#269,#270) marked "Fixed"/shipped in CHANGELOG.md v6.4.3/v6.4.4 but still OPEN in the tracker; (2) 19/22 open issues (86%) carry no milestone, including two production-affecting CLI bugs (#266, #235) and one audit-integrity bug (#261); (3) `.shepherd/ctx/` (the carry-forward ledger + knowledge-silo directory) does not exist anywhere in this repo's git history — ROW 11 and ROW 12 are structurally empty, not "no chronic items"; (4) no `close.md`/`handoff.md` exists anywhere under `.shepherd/runs/`, including for v641-dev0, whose own plan.md defines that schema; (5) README.md claims version 6.4.4 while `.claude-plugin/plugin.json` already reads 6.4.5, and CHANGELOG.md has no v6.4.5 entry yet; (6) class (c) monorepo/packaging has zero dedicated open issues — the arc's core deliverable has no existing anchor.
- Reporter: @discovery
