---
title: v5.1.3 cleanup report
date: 2026-05-19
sprint: v5.1.3-dev.1
author: Lane D implementer
---

# v5.1.3 cleanup report

Scope: per design spec `.artifacts/docs/specs/2026-05-19-v513-cleanup-caching-design.md` §"Lane D — General cruft cleanup". The repo is small; the audit confirmed it is healthier than expected. No deletions were performed; everything currently in the tree has at least one legitimate reference. Findings below; operator review recommended only for the items explicitly flagged.

## Dead-script audit

Methodology: for each `skills/context/scripts/cmd_*.sh` (excluding `cmd_refresh.sh`, owned by Lane C), grep for `shctx <cmd>` in markdown, `commands/`, `skills/`, and `cmd_<cmd>.sh` in `hooks/`/`skills/`. A "lonely" script (only referenced by its own source) is a candidate-for-removal — but the `shctx` dispatcher (`skills/context/scripts/shctx`) maps any subcommand `<cmd>` to `cmd_<cmd>.sh` via fallback rule (`*) echo "cmd_$1.sh" ;;`), so every script is reachable.

| Script | md refs | commands/skills refs | script refs | Disposition |
|---|---|---|---|---|
| cmd_audit.sh | 2 | 2 | 0 | KEEP — invoked via `shctx audit` |
| cmd_close-lane.sh | 4 | 5 | 2 | KEEP — documented + composed by `cmd_sprint.sh` |
| cmd_discovery.sh | 3 | 2 | 0 | KEEP — doctrine `discovery-readonly.md` + `shctx discovery` |
| cmd_doctor.sh | 8 | 8 | 4 | KEEP — preflight (`shctx doctor`) |
| cmd_export.sh | 2 | 3 | 0 | KEEP — `shctx export` documented in `skills/context/SKILL.md` |
| cmd_graph.sh | 6 | 7 | 1 | KEEP — `shctx graph trends` referenced by `dispatch-cascade.md` |
| cmd_handoff.sh | 0 | 1 | 1 | KEEP — internal stage of `cmd_sprint.sh close`; not user-facing |
| cmd_init.sh | 8 | 11 | 1 | KEEP — `shctx init` (bootstrap) |
| cmd_inject.sh | 7 | 6 | 0 | KEEP — `shctx inject coder` doctrine-anchored |
| cmd_insights.sh | 4 | 3 | 1 | KEEP — `shctx insights` per `flock-cohesion.md` |
| cmd_issues.sh | 2 | 1 | 0 | KEEP — `shctx issues` (issue ledger surface) |
| cmd_lint.sh | 4 | 3 | 5 | KEEP — `shctx lint` |
| cmd_lock.sh | 2 | 3 | 1 | KEEP — `shctx lock` (autorun/parallel coord) |
| cmd_mem.sh | 3 | 3 | 1 | KEEP — `shctx mem` (project memories) |
| cmd_migrate.sh | 4 | 6 | 3 | KEEP — `shctx migrate` (schema migrations) |
| cmd_pauses.sh | 4 | 4 | 2 | KEEP — `shctx pauses` per `pause-for-dependency.md` |
| cmd_plan.sh | 5 | 6 | 1 | KEEP — Stage Graph emission |
| cmd_profile.sh | 2 | 3 | 0 | KEEP — `shctx profile` (TOML profiles) |
| cmd_query.sh | 14 | 22 | 3 | KEEP — `shctx query` (most-used command) |
| cmd_ready.sh | 2 | 3 | 0 | KEEP — `shctx ready` |
| cmd_release.sh | 2 | 1 | 0 | KEEP — `shctx release` per `CLAUDE.md` Versioning section |
| cmd_search.sh | 3 | 5 | 0 | KEEP — `shctx search` (FTS5) |
| cmd_sprint.sh | 2 | 3 | 0 | KEEP — `shctx sprint` (sprint orchestration helper) |
| cmd_status.sh | 5 | 2 | 3 | KEEP — `shctx status` |
| cmd_style.sh | 5 | 3 | 0 | KEEP — `shctx style init <lang>` per `CLAUDE.md` |
| cmd_sync.sh | 2 | 4 | 0 | KEEP — `shctx sync` (test harness covered) |
| cmd_watch.sh | 2 | 3 | 1 | KEEP — `shctx watch` per `dir-watch.md` |
| cmd_worktree.sh | 8 | 9 | 2 | KEEP — `shctx worktree {list,gc,merge}` |

**Result**: 0 candidates for removal. The `shctx` dispatcher's fallback case (`*) echo "cmd_$1.sh"`) means any subcommand name resolves to its script; all scripts are first-class reachable. The grep-based audit confirms each is additionally cited by documentation, doctrines, commands, or composed by other scripts.

Note on `cmd_handoff.sh`: 0 markdown references, but it IS invoked from `cmd_sprint.sh` line 104 (`run_stage handoff bash "$HERE/cmd_handoff.sh" create --branch="$branch"`). It is an internal stage of the sprint close pipeline rather than a user-facing subcommand; the lack of documentation is intentional (operators run `shctx sprint close`, which fans out).

## Stale doctrine references

Methodology: `rg -n "v4\.|v5\.0\.[0-5]|pre-4\.2|pre-v5\.0" skills/shepherd/doctrines/`. Each hit was read in its surrounding paragraph. Two classes emerged: (a) origin annotations / field-feedback citations (`> Field origin: shepherd v5.0.3 ...`) — these are legitimate historical context that clarifies *why* the doctrine exists, and removing them would impoverish the audit trail; (b) "Why the X" sections that describe the pre-v4.2/pre-v5.0 mechanism the doctrine replaced — these are framed as motivation, not as operative instructions.

| File | Hit (line) | Change made |
|---|---|---|
| `gates-restoration.md:18-19` | `v5.0.1 ... v5.0.3 codifies` | NO CHANGE — origin annotation in a quoted field-origin block; reads as historical |
| `conductor-cwd.md:23-25` | `v5.0.1 ... v5.0.3 codified ... v5.0.6 extends` | NO CHANGE — origin annotation tracking the doctrine's evolution |
| `worktree-base-drift.md:20-23, 50` | `v5.0.3 ... v5.0.4 codifies ... Empirical observation in v5.0.3` | NO CHANGE — origin annotation + empirical-observation timestamp |
| `stage-graph.md:19` | `pre-4.2.0 model` | NO CHANGE — section is titled "Why the graph"; explicitly historical motivation |
| `dispatch-cascade.md:22, 124` | `pre-v5.0.9 model`, `shctx graph trends, v5.0.10+` | NO CHANGE — `Why this exists` section is historical motivation; `v5.0.10+` is a forward-looking annotation on a planned feature |
| `pause-for-dependency.md:18` | `Three pre-v5.0.9 options were all bad` | NO CHANGE — sets up *why* PAUSE-FOR-DEPENDENCY exists; historical context |
| `zero-duplicate-tolerance.md:5, 56, 156` | `pre-4.2.0 model`, `Layer 2 SQL fast-path (v5.0.0+)`, `Code-style auto-attachment (v5.0.0+)` | NO CHANGE — `pre-4.2.0` framed as historical motivation; `v5.0.0+` annotations mark feature-introduction (operative, not stale) |
| `coder-brief-format-shared-artifacts.md:17-20, 103` | `v5.0.3 ... v5.0.4 codifies`, `Not in v5.0.4` | NO CHANGE — origin annotation; `Not in v5.0.4` is a deliberate scope-deferral note |
| `auditor-readonly.md:55` | `v5.0.3 conductor feedback` | NO CHANGE — origin annotation |
| `subtract-dont-add.md:28, 33` | `v5.0.3 ... v5.0.4 codifies` | NO CHANGE — origin annotation |
| `worktree-confinement.md:19, 23` | `v5.0.3 ... v5.0.4 codifies` | NO CHANGE — origin annotation |
| `context-registry.md:30` | `Behavior is unchanged from v4.x` | NO CHANGE — fallback-contract reference; operative (DB-absent path still falls back to markdown) |
| `flock-cohesion.md:215` | `## X. Roadmap (v5.0.10+)` | NO CHANGE — explicitly framed as forward-looking roadmap |

**Result**: 0 references updated. All `v4.x` / `v5.0.x` mentions in doctrines are either (a) origin annotations that document evolution, (b) historical motivation explaining *why* a doctrine exists, or (c) feature-introduction annotations marking when a capability landed. Removing or "updating to current state" any of them would lose useful provenance. Per the spec's "over-cleanup is worse than under-cleanup" guidance, no edits made.

## _candidates/ dispositions

`skills/shepherd/doctrines/_candidates/` contains exactly one file: `README.md` — the promotion-pipeline doc itself. There are no orphan candidate doctrines awaiting review.

| File | Decision | Reason |
|---|---|---|
| `_candidates/README.md` | KEEP IN PLACE | This is the promotion-pipeline doc; not a candidate, it's the directory's signature artifact. Documented in `doctrines/README.md`'s index implicitly via the candidate-template structure. |

**Result**: 0 candidates promoted, 0 deleted, 0 left as operator-review.

## Gitignored-but-tracked

Methodology: `git ls-files | while read f; do git check-ignore -q "$f" 2>/dev/null && echo "$f"; done`. Exit code 1 (no matches).

| File | Disposition |
|---|---|
| *(none)* | — |

**Result**: 0 files. The repo is clean on this dimension.

## Stale references in SKILL.md / pipeline.md / planter.md

Methodology: `rg -n "v4\.|pre-4\.2|pre-v5\.0|v5\.0\.[0-3]" skills/shepherd/{pipeline,planter,SKILL}.md`. `planter.md` returned 0 hits.

| File | Hit (line) | Change made |
|---|---|---|
| `SKILL.md:27` | `v5.0.0 introduced the context registry` | NO CHANGE — feature-introduction annotation in the skill's preamble; operative (consumers may still be on v5.0.x) |
| `SKILL.md:30` | `The v4.2.0 Stage Graph` | NO CHANGE — feature-introduction annotation; the Stage Graph is current |
| `SKILL.md:412` | `(v5.0.3 + v5.0.6)` | NO CHANGE — origin annotation in doctrine cross-reference table |
| `SKILL.md:413` | `(v5.0.3)` | NO CHANGE — origin annotation |
| `SKILL.md:430` | `(new in v5.0.0; shctx doctor added v5.1.1)` | NO CHANGE — version-introduction annotations |
| `pipeline.md:7` | `v4.2.0 introduces this artifact` | NO CHANGE — frontmatter description; historical-introduction note |
| `pipeline.md:23` | `The pre-4.2.0 model` | NO CHANGE — `Why a graph` section is explicitly historical motivation |
| `pipeline.md:56` | `per v5.0.3 §2.7` | NO CHANGE — citation to field feedback that drove the rule |
| `pipeline.md:114` | `SQL fast-path (v5.0.0+)` | NO CHANGE — feature-introduction annotation |
| `pipeline.md:631-640` | `## XV. Migration from pre-4.2.0 plans` | NO CHANGE — explicit migration section; operative for legacy consumers |
| `pipeline.md:644-664` | `## XV-bis. Worktree target/ policy (v5.0.4)` | NO CHANGE — operative policy with origin annotation |
| `pipeline.md:646` | `Question raised in v5.0.3` | NO CHANGE — origin annotation in §XV-bis |
| `pipeline.md:668` | `Field origin: shepherd v5.0.3` | NO CHANGE — origin annotation block |
| `pipeline.md:796-797` | `(v5.0.3)` | NO CHANGE — origin annotations on doctrine-cross-references |
| `planter.md` | *(no hits)* | — |

**Result**: 0 references updated. Same disposition logic as the doctrine sweep — every hit is either a feature-introduction annotation, an origin citation, or an explicitly-framed historical motivation section.

## Version consistency

Methodology: read each version-source-of-truth file named in `CLAUDE.md` "Versioning" section.

| File | Before | After |
|---|---|---|
| `.claude-plugin/plugin.json` `"version"` | 5.1.3 | 5.1.3 (VERIFIED) |
| `.claude-plugin/marketplace.json` plugin entry version | 5.1.3 | 5.1.3 (VERIFIED) |
| `.claude-plugin/marketplace.json` marketplace version | 5.1.3 | 5.1.3 (VERIFIED) |
| `skills/shepherd/SKILL.md` frontmatter `version:` | 5.1.3 | 5.1.3 (VERIFIED) |
| `skills/context/SKILL.md` frontmatter `version:` | 5.1.3 | 5.1.3 (VERIFIED) |
| `README.md` header | (no top-line version banner; first `## v5.0.0 — Context Registry` is a historical feature section, not a current-version banner — by repo convention the README leans on `CHANGELOG.md` for current-version) | unchanged |
| `CHANGELOG.md` latest entry | (was: v5.1.2) | v5.1.3 entry added (in progress) |

**Result**: All canonical version sources at 5.1.3. README's lack of a top-line version banner is the existing convention; current version is tracked via CHANGELOG and the plugin/marketplace manifests.

## CHANGELOG.md entry

Pasted verbatim from the new entry added at `CHANGELOG.md` line 7 onward:

```markdown
## v5.1.3 — 2026-05-19 (in progress)

### Cleanup, cache discipline, dispatch telemetry

v5.1.3 fixes the base. No new conductor capabilities, no new agent roles, no
semantic changes to the dispatch pipeline. The sprint is a focused sweep:
smaller, more stable agent prefixes; brief ordering that puts variable
content last so prompt caching can do its job; SubagentStop telemetry that
proves the wins are real; and a sweep of accumulated cruft.

#### Agent restructure (Lanes A1 + A2)
- five-agent prefix/reference split (engineer/coder/critic/worker/discovery)
- auditor.md trim with reference extraction
- `Greatness is the bar` inline preamble replaced by doctrine reference
- `tools:` frontmatter audited per-agent

#### Brief assembly discipline (Lane B)
- new doctrine `doctrines/brief-cache-discipline.md` (stable framing first, variable content last)
- `pipeline.md` §V gains "Cache-first brief ordering" subsection

#### Dispatch telemetry (Lane C)
- new hook `hooks/scripts/subagent_telemetry.sh` (per-dispatch cache stats)
- registry schema migration 0006 (`index_cache_usage`, `v_cache_usage`)
- `shctx query cache-usage` + `shctx refresh --scope=telemetry`
- new doctrine `doctrines/cache-telemetry.md`

#### Cleanup (Lane D)
- dead-script sweep (0 removals; all scripts reachable via dispatcher fallback)
- stale-reference audit (0 updates; all historical references are legitimate origin/motivation annotations)
- `_candidates/` review (0 promotions, 0 deletions)
- gitignored-but-tracked sweep (0 hits)
- version-source-of-truth files verified at 5.1.3
```

(Full prose in `CHANGELOG.md`; the table above is the compressed summary.)

## Summary

- Files deleted: 0
- Files moved: 0
- Files updated: 1 (`CHANGELOG.md` — added v5.1.3 entry)
- Files created: 1 (this report)
- Candidates for operator review: 0
- Acceptance grep status: PASS
  - `.artifacts/docs/handoffs/2026-05-19-v513-cleanup-report.md` exists with all named sections
  - `grep -E "## v5\.1\.3" CHANGELOG.md` returns 1 hit
  - `git ls-files | ... git check-ignore` returns 0 lines
  - All version-source-of-truth files report 5.1.3

## Things to surface to operator (suspicious but not acted upon)

1. **`cmd_handoff.sh` has zero user-facing documentation.** It's invoked exclusively from `cmd_sprint.sh`'s `close` flow. This is intentional per design (handoff is a sprint-close stage, not a standalone subcommand), but if the operator wants either (a) documentation of the internal stage or (b) graduation of `shctx handoff create` to a documented subcommand, that's a future call.

2. **`pipeline.md` §XV "Migration from pre-4.2.0 plans"** could be marked `(historical — all current plans on v5.0+ emit Stage Graphs)` if the operator agrees no consumer is still on a pre-4.2.0 plan. Did not touch on the principle that operative migration sections may still be useful to keep verbatim for old consumers discovering this repo.

3. **Doctrine `flock-cohesion.md` §X "Roadmap (v5.0.10+)"** — worth a pass at sprint open of the next major to either land or punt the items there. Currently aspirational; was not in this sprint's scope.

4. **`README.md` has no top-line current-version banner.** Other plugins in the ecosystem often put `**Version**: v5.1.3` at the top. The shepherd README defers to CHANGELOG. If a top-line banner is wanted, that's a one-line addition — operator call.
