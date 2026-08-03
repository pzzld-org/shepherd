---
title: v6.5.0-dev.0 Seed — CLI completion, run-scoped artifacts, templating, planning refinement
branch: claude/plugin-robustness-planning-2xd9mi
base: main
kind: sprint-seed
status: approved
date: 2026-08-02
author: operator (Joe) + session a496101e
prior_close_report: n/a (operator-directed robustness sprint)
milestone: v6.5.0
sprint_size: XL
file_scope:
  exclusive:
    - services/cli/
    - skills/context/scripts/
    - skills/context/references/
    - skills/shepherd/references/
    - agents/
    - commands/
    - hooks/
    - .shepherd/ (NEW)
  additive:
    - .claude/shepherd.toml
    - .gitignore
    - CHANGELOG.md
    - .claude-plugin/plugin.json
---

# North star

One canonical Python CLI (bash shctx layer retired), one Jinja2 template engine
for every prompt/template surface, one standard `.shepherd/runs/{run}/` layout
for all run-scoped artifacts, and a planning contract refined with
superpowers-derived discipline — nothing forced, no new skills.

# Why this sprint

- Operator directive (2026-08-02): nail down procedures, contracts, interfaces;
  learn from fl03/codex-shepherd file management and obra/superpowers planning.
- #239: port the last 7 shctx commands, retire bash, ship ~/.shepherd.
- #244/#243/#181: deterministic prompt lineage; five placeholder dialects exist
  for one job (survey res_12 §2); prefix-cache-hostile composition documented.
- #230/#242/#220/#59: contract robustness failures observed in live sprints.
- 19 stale open issues closed during Phase 0 orientation (board 46 → 27).

# Engineering decisions (locked)

1. `.shepherd/` is the only project-visible namespace; `.artifacts/` legacy.
2. Run identity: `{run}` == sprint slug (e.g. `v650-dev0`); patch-arc runs use
   the patch slug. Identifiers sanitized to `[a-z0-9-]`.
3. Run layout: `runs/{run}/{run.json,seed.md,mesh.md,plan.md,phase0.md,
   close.md,handoff.md,lanes/{lane}/plan.md,graph/,dispatch/,reports/,audits/}`.
4. Tracked in git: seed/mesh/plan/phase0/close/handoff + lane plans. Ignored:
   graph/, dispatch/, gates, snapshots, tmp (durable knowledge compounds,
   run state is disposable — codex-shepherd gitignore split).
5. `run.json` is CLI-written and schema-validated — never latent-space-written.
6. Conductors OWN `runs/{run}/lanes/{lane}/plan.md` — checkbox step tracking,
   append-only `## Deviations` log, acceptance results. Write guard scopes the
   conductor to its own lane dir.
7. Jinja2 (StrictUndefined, trim_blocks, lstrip_blocks) is the single render
   engine; templates are package data under `shepherd_cli/templates/`; project
   `.shepherd/templates/` overrides. Deterministic: no timestamps in rendered
   bodies; lineage manifest (template sha + vars sha + output sha) sits beside
   the output, mirroring the graph-compile manifest precedent.
8. Stable-prefix rule: shared/static blocks first, per-lane/per-session
   variables last, in every rendered prompt (boot prompt inversion fixed).
9. Profiles: `.shepherd/profiles/{profile}/style.md` (project) overlays
   `~/.shepherd/profiles/{profile}/style.md` (user) overlays bundled
   `skills/context/styles/{lang}.md`. `~/.shepherd` is the user-level home
   (SHEPHERD_HOME override; hosts the future global DB).
10. Superpowers stays optional: its discipline is internalized in our plan
    contract; `superpowers:*` skills load only if installed, never grade-cap.

# Deliverables (issue-anchored)

- Complete Python CLI: port adapt, inject, plan, graph, loop, panes, release;
  re-point pipeline commands off bash; retire skills/context/scripts. [#239]
- CLI bug fixes with regression tests: parameterized SQL [#234], graph-next
  cursor [#225], teammate upsert retrofit + register-lead port [#241, #223],
  worktree root resolution in Python [#221, #231] (landed), publisher-agnostic
  launcher + doctor version check [#235].
- Jinja2 engine + `shepherd render` + templates for handoff, config-init,
  inject, boot prompt, seed/plan/lane-plan scaffolds. [#244, #243, #181]
- `.shepherd/runs/{run}/` layout: run command group, layout-v3 migration,
  lint patterns, hook path fixes (seed gate path-segment match), gitignore
  split, repo self-migration off `.artifacts/`. [#130, #27–#30 supersession]
- Planning refinement: engineer plan contract with Interfaces blocks,
  no-placeholder law, self-review; lane plans materialized as files;
  boot prompt carries paths not pasted briefs; structured `git_custody`
  boot field [#230]; wave accept/merge ledger in run.json [#242]; spawn
  substrate preflight [#220]; gates.extra enforcement [#59].
- Hook identity gates: coordinate_drive_guard positive session-tier marker
  [#232, #228]; liveness scoping + reboot stale-sweep [#229].
- Profiles restructure per operator directive (2026-08-02, mid-sprint).

# Non-goals

- No dogfooding (no /shepherd:spawn run this sprint) — operator-explicit.
- No live-custody doctrine [#237 → deferred, seed template gains an optional
  operational-state extension slot only].
- No mega-sprint --parallel redesign [#125], no heartbeat payload relay [#53],
  no --scope minor/version completion [#47], no workflow export contract at
  the segment seam [#82] (dormant until Dynamic Workflows reactivation).
- No GH-issue-tree materialization [#27–#30 close as superseded by run files].
