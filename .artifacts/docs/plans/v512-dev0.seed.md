---
title: v5.1.2-dev.0 — anti-laziness teeth, CLI reorg, hook overhaul finish, naming convention fix
sprint_branch: v5.1.2-dev.0
sprint_slug:   v512-dev0
patch_branch:  v5.1.2
patch_slug:    v512
date: 2026-05-16
planter: opus 4.7 [1m] (inline, no /shepherd:plant invocation)
status: ready for engineer
sprint_size: L
prior_handoff:  release notes for v5.1.1 (git tag v5.1.1)
upstream_doc:   .artifacts/docs/specs/2026-05-16-v512-priorities.md
operator_cut:   B (Recommended)
operator_decisions:
  - seed-naming-fix: option a (sprint_slug config knob)
  - dedup-write-gate: BLOCK on hit
  - sprint-count: 1 (this sprint = the v5.1.2 patch)
  - agent-help: yes, parallel coder waves authorized
---

# v5.1.2-dev.0 — anti-laziness teeth + CLI reorg + finish hooks + naming convention fix

## North star (one sentence)

Land the structural teeth the v5.1.1 doctrines promised (hook teeth, CLI
reorg, dedup-block, strive-higher framing, discovery registry, sprint-slug
filename convention) so the v5.1.1 contracts go from aspirational to enforced.

## Why this sprint matters (real-work test)

v5.1.1 was load-bearing DOCTRINES. v5.1.2 is load-bearing ENFORCEMENT.
Without v5.1.2 teeth, the v5.1.1 contracts are docs without consequences —
the next sprint that touches a shepherd-consumer project still drifts
through the same lazy patterns. This sprint MUST ship operator-visible
improvement at runtime, not just doctrine.

Patch-grade impact (per `doctrines/sprint-as-patch.md`): every shepherd
operator's next sprint feels different — fewer duplicate symbols sneak in
(3a), CLI tab completion works (Theme 2), discovery cache cuts repeat
dispatches (Theme 5), seed filenames stop double-dotting (Theme N).

## Carry-forward from v5.1.1 (deferred items)

| Item | Origin | Lane target |
|---|---|---|
| `hooks/scripts/_lib.sh` | v5.1.1 CHANGELOG deferred | LANDED mid-stride (verify) |
| `hooks/scripts/agent_invocation_tagger.sh` | v5.1.1 CHANGELOG | LANDED (verify) |
| `hooks/scripts/discovery_capture.sh` | v5.1.1 CHANGELOG | LANDED (verify) |
| `bash_guard.sh` checks 4+5 (auditor cwd + discovery state-modify) | v5.1.1 CHANGELOG | Lane A |
| `lock_guard.sh` role-based write-path enforcement | v5.1.1 CHANGELOG | Lane A |
| `agent_pause_detector.sh` brief-stub auto-draft | v5.1.1 CHANGELOG | Lane A |
| `hooks.json` register new hooks | v5.1.1 CHANGELOG | Lane A |
| `cmd_doctor.sh` extension for v5.1.1 surfaces | v5.1.1 CHANGELOG | Lane D |
| `cmd_discovery.sh` (discovery registry) | v5.1.1 implicit (capture hook writes records nobody reads) | Lane D |

## Phase 0 mesh inputs (engineer must consume)

Before authoring the plan:

1. Read `.artifacts/docs/specs/2026-05-16-v512-priorities.md` (the upstream
   priorities doc — operator has approved Cut B).
2. Verify hooks already landed: `_lib.sh`, `agent_invocation_tagger.sh`,
   `discovery_capture.sh`. Ensure they're executable + their JSON output
   is parseable.
3. Read v5.1.1 CHANGELOG entry "Hook hardening + preflight (planned for
   v5.1.2+)" — the canonical list of remaining hook work.
4. Audit current `shctx` flat command surface (`skills/context/scripts/shctx`
   case statement) and produce a mapping table flat → grouped.
5. Verify seed-naming bug surface: grep `{sprint_branch}.seed.md` across
   plugin (already inventoried in priorities doc Theme N).
6. Read `superpowers:systematic-debugging` (auditor v5.1.1 contract) +
   `doctrines/discovery-readonly.md` + `doctrines/sprint-as-patch.md` —
   the load-bearing v5.1.1 doctrines this sprint enforces.
7. Verify shepherd.toml exists at `.claude/shepherd.toml` (just scaffolded;
   if engineer finds anomalies, halt and surface).

## Sprint lanes (engineer to refine; this is the planter's hint)

Five lanes, all parallel-safe (file-disjoint).

### Lane A — Hook teeth (high-priority)

[FILE-SCOPE]
- `hooks/scripts/bash_guard.sh` (extend with checks 4 + 5)
- `hooks/scripts/lock_guard.sh` (extend with role-based write-path)
- `hooks/scripts/agent_pause_detector.sh` (extend with brief-stub auto-draft)
- `hooks/scripts/session_open.sh` (refactor to use `_lib.sh`)
- `hooks/scripts/bash_post.sh` (refactor to use `_lib.sh`)
- `hooks/scripts/agent_insight_capture.sh` (refactor to use `_lib.sh`)
- `hooks/hooks.json` (register `agent_invocation_tagger.sh` + `discovery_capture.sh`)

[ACCEPTANCE]
- `jq empty hooks/hooks.json` passes
- `bash hooks/scripts/_lib.sh; echo $?` returns 0 (lib sourceable)
- Manual: rg "source.*_lib.sh" hooks/scripts/*.sh → all six existing hooks
- `bash_guard.sh` denies auditor agent invoking `cargo`/`pnpm`/`pytest` when HEAD ≠ sprint branch
- `lock_guard.sh` denies @discovery Write outside `{paths.reports}/*-discovery-*.md`
- `agent_pause_detector.sh` writes `<ns>/pauses/<id>.brief.md` alongside `<id>.json`

### Lane B — CLI subcommand reorg

[FILE-SCOPE]
- `skills/context/scripts/shctx` (dispatcher rewrite — subcommand routing)
- `skills/context/scripts/cmd_workspace.sh` (NEW — group dispatcher for search/query)
- `skills/context/scripts/cmd_brief.sh` (NEW — group dispatcher for inject + validate)
- `skills/context/scripts/cmd_lane.sh` (NEW — group dispatcher for close + ready; wraps existing cmd_close-lane.sh + cmd_ready.sh)
- `skills/context/scripts/cmd_discovery.sh` (NEW — registry CLI; also Lane D consumes)
- Existing flat `cmd_<verb>.sh` files retained as wrappers calling new dispatchers + deprecation hint to stderr
- `skills/context/SKILL.md` (update Quick reference with new tree)

[ACCEPTANCE]
- `shctx workspace search "foo"` works
- `shctx search "foo"` works AND emits one-line `[deprecated]` hint to stderr
- `shctx brief inject coder` works
- `shctx lane close <id>` works
- `shctx --help` shows the new tree
- All existing flat commands still functional (back-compat)

### Lane C — Anti-laziness layer

[FILE-SCOPE]
- `hooks/scripts/dedup_write_guard.sh` (NEW — PreToolUse(Write|Edit) hook)
- `hooks/hooks.json` (register dedup_write_guard — coordinates with Lane A)
- `skills/shepherd/doctrines/agent-excellence.md` (NEW)
- `agents/engineer.md` (prepend strive-higher preamble)
- `agents/critic.md` (prepend strive-higher preamble)
- `agents/coder.md` (prepend strive-higher preamble)
- `agents/auditor.md` (prepend strive-higher preamble — auditor.md already loads systematic-debugging; preamble is additive)
- `agents/worker.md` (prepend strive-higher preamble)
- `agents/discovery.md` (prepend strive-higher preamble)

[ACCEPTANCE]
- `dedup_write_guard.sh` parses pending Write|Edit content for `pub fn|pub struct|pub trait|pub enum|pub const` (Rust) / `def |class ` (Python) / `export function|export class|export interface` (TS) etc.
- For each new pub-symbol, runs `shctx workspace search --symbol="<name>"` (uses Lane B's new group)
- On hit: emits `{"permissionDecision":"deny","message":"DEDUP-HIT: <symbol> at <file:line>. Reuse, extend, or JUSTIFY-NEW in your report."}`
- Six agent system prompts all begin with the standardized preamble (`rg -l "Greatness is the bar" agents/` → 6 files)
- `skills/shepherd/doctrines/agent-excellence.md` exists and is referenced from `skills/shepherd/doctrines/README.md`

⚠ Coordination with Lane A: both modify `hooks/hooks.json`. Single-writer rule applies — Lane A owns the file; Lane C drafts a patch for Lane A to apply at WAVE-GATE. Per `doctrines/coder-brief-format-shared-artifacts.md`.

### Lane D — Discovery registry + reuse

[FILE-SCOPE]
- `skills/context/scripts/cmd_discovery.sh` (created in Lane B reorg; this lane fills the implementation)
- `skills/context/scripts/cmd_doctor.sh` (extend for v5.1.1 surfaces: intro-wave plan-node presence, `<ns>/discoveries/` dir, `<ns>/dispatch/` dir, `<ns>/logs/hooks/` writability)
- `skills/shepherd/flock.md` (add conductor pattern: "Before dispatching a discovery, run `shctx discovery search`")
- `skills/shepherd/doctrines/discovery-readonly.md` (add cross-sprint reuse §)

[ACCEPTANCE]
- `shctx discovery list [--sprint=<branch>]` lists records from `<ns>/discoveries/`
- `shctx discovery show <id>` prints structured record
- `shctx discovery search --question="<paraphrase>"` returns matches (≤ 2 sprints old)
- `shctx discovery clear --sprint=<branch>` purges sprint records
- `shctx doctor` checks: discoveries dir exists; dispatch dir exists; logs/hooks writable
- `flock.md` includes the pre-dispatch search pattern

⚠ Coordination with Lane B: this lane fills `cmd_discovery.sh` after Lane B scaffolds it. Lane B creates a stub; Lane D writes the real logic. Pattern B applicable: Lane D coder is dispatched in same wave or following wave depending on engineer decision.

### Lane E — `{sprint_slug}` config knob + seed-naming convention fix

[FILE-SCOPE]
- `docs/configuration.md` (document `sprint_slug_pattern` + `patch_slug_pattern` in `[branching]`)
- `examples/minimal/shepherd.toml` (add `sprint_slug_pattern` / `patch_slug_pattern`)
- `examples/axiom/shepherd.toml` (add same)
- `skills/shepherd/references/seed-template.md` (replace `{sprint_branch}.seed.md` → `{sprint_slug}.seed.md`; same for patch)
- `skills/shepherd/planter.md` (10+ references updated)
- `skills/shepherd/references/agent-briefs.md` (3 references updated)
- `skills/shepherd/pipeline.md` (1 reference updated)
- `skills/context/references/naming-conventions.md` (line 83 + add slug rule)
- `skills/context/scripts/cmd_lint.sh` (accept both forms during deprecation window)
- `skills/context/tests/test_refresh_artifacts.sh` (use slug form in fixture)
- `skills/context/examples/journal-entry.md` (use slug form)
- `skills/shepherd/doctrines/seed-naming.md` (NEW — explicit rule)

[ACCEPTANCE]
- `rg "{sprint_branch}\.seed\.md" skills/` returns 0 hits (all converted to `{sprint_slug}`)
- `rg "{sprint_slug_pattern}" docs/configuration.md examples/*/shepherd.toml` returns 3 hits
- `shctx lint` accepts both `v0.3.2-dev.5.seed.md` (legacy) and `v032-dev5.seed.md` (new) during transition; emits warning on legacy
- New doctrine cites the rule + examples

### Lane F (OPTIONAL — engineer's call) — Audit prior axiom seeds

If engineer decides Lane E warrants more thoroughness, dispatch a @worker
to rename existing axiom seed files from dotted to concatenated form. This
is consumer-project state, not shepherd-plugin state — strictly OPTIONAL
and operator-confirmed only.

## Non-goals (explicit)

- BINDING/RATIONALE doc split (Theme 1a) — v5.2.0 work
- `canonical-types.tsv` export (Theme 1b) — v5.2.0 work
- Brief deltas / symbol fingerprints (Themes 1c, 1d) — future
- Per-language file-pattern enforcement (Theme 3b) — v5.1.3 work; needs code-style skill rewrites across many files
- JUSTIFY-NEW report contract (Theme 3d) — held until 3a proves out; avoid double-enforcement
- Renaming axiom's existing dotted seed files — consumer-project state; v5.1.2 ships the convention + lint, operator renames at leisure

## Stage Graph hint (engineer refines to binding YAML)

```
SEED-VERIFY ──► INTRO-COMBO-WAVE ──► MESH ──► PLAN-GATE ──► DEDUP-GATE
                  │                                              │
                  ├─ disc:prior-close-audit-summary (v5.1.1 close)│
                  ├─ disc:canonical-types-freshness              │
                  ├─ disc:gh-state-inventory                     │
                  ├─ aud:regression (intro)                      │
                  └─ aud:carry-forward-disposition (intro)       │
                                                                 ▼
              WAVE-1-IMPL  ║  WORKER-IO
              (Lanes A, B, C, E concurrent — file-disjoint)      WAVE-1-GATE
              (Lane D depends on Lane B; sequence as Wave 2)
                                                                 │
              WAVE-2-IMPL                                         WAVE-2-GATE
              (Lane D — discovery registry + doctor ext)
                                                                 │
              WAVE-1-AUDIT (Pattern B with Wave 2)              │
                                                                 ▼
                                                          CLOSE-SWARM
                                                         (4 concerns)
                                                                 ▼
                                                          CLOSE-FINALIZE
```

5 lanes total (A, B, C, D, E). Wave 1 fires A, B, C, E concurrently
(file-disjoint). Lane D fires Wave 2 (needs Lane B's stub).

Pattern B: Wave 1 auditors fire alongside Wave 2 coder.

## Sprint impactfulness bar

- ≥ 5 parallel coder lanes (this seed proposes 5; if engineer drops below, reject back to planter)
- Operator-visible runtime change: dedup hook blocks (3a); CLI subcommands work (2); slug filenames stop bringing periods back (Theme N)
- SUBTRACT delta: minimal expected; mostly additive doctrine + cli reorg. Allowed exception per `subtract-dont-add.md` for foundational enforcement layers.
- Release-notes-eligible at close: yes — every Cut B item is operator-visible

## Operator review checklist (before /shepherd:start)

- [ ] `.claude/shepherd.toml` scaffolded (just landed)
- [ ] Sprint branch `v5.1.2-dev.0` cut from `v5.1.2` (NOT YET — conductor to do this at sprint open)
- [ ] PR #34 (v5.1.2 → main) status confirmed open
- [ ] Operator confirms 5-lane decomposition acceptable (or pushes back to planter)
- [ ] Engineer model = Opus per shepherd.toml? (CURRENT SESSION IS OPUS — engineer dispatch should also be Opus per default model table)

## Dispatch recommendation

When operator says "go":

1. Conductor cuts `v5.1.2-dev.0` from `v5.1.2` head
2. Dispatches INTRO-COMBO-WAVE (3 discoveries + 2 intro auditors, 1 batch)
3. Reads outputs into `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]`
4. Dispatches @engineer with this seed + carry-forward GH#s + injected contexts
5. Engineer authors `v512-dev0.plan.md` (NOTE — slug form, per Theme N)
6. @critic gates the plan
7. WAVE-1-IMPL fires Lanes A, B, C, E + WORKER-IO in one message batch
8. WAVE-1-GATE → WAVE-2-IMPL (Lane D) + Pattern B Wave 1 audits
9. CLOSE-SWARM (4 auditors) → CLOSE-FINALIZE
10. Rebase-merge into `v5.1.2`; PR #34 carries the merged content; operator merges PR via gh

## Open seed questions (none — operator already answered)

All Cut B decisions confirmed in 2026-05-16 transcript. Engineer proceeds.
