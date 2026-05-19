# shepherd — changelog

Per-version history for the `shepherd` plugin (this repo). Format loosely based on [Keep a Changelog](https://keepachangelog.com/); follows [Semantic Versioning](https://semver.org/).

---

## v5.1.4 — 2026-05-19

### Teammate-conductor + planter/conductor profile split

v5.1.4 introduces `/shepherd:spawn` for teammate-driven sprint execution and
extracts the orchestrator behavior into two canonical profile files at
`agents/conductor.md` (sprint-runner) and `agents/planter.md` (seed-author +
ambient babysitter). Main chat stays lean as the planter while a spawned
teammate runs the sprint as conductor. `/shepherd:autorun` and
`/shepherd:parallel` retire into `/shepherd:spawn --auto` and
`/shepherd:spawn --parallel <N>` respectively — consolidated command surface
is `{plant, start, spawn, ctx}`.

#### New

- **`agents/conductor.md`** (445 lines, cyan, inherit model) — canonical
  sprint-runner profile adopted by `/shepherd:start` whether main chat or a
  spawned teammate is the runner. Lifts ~620 lines of orchestrator behavior
  from `SKILL.md`, `pipeline.md`, `flock.md`, `autorun.md`, `parallel.md`.
  Strict side-effect boundary (Hard Prohibition #12: no git writes, no
  filesystem cleanup outside dispatch). Tools list trimmed to GitHub
  read-only.
- **`agents/planter.md`** (582 lines, violet, `opus[1m]`) — dual-mode
  profile (plant + spawn babysitter). Lifts ~280 lines from
  `skills/shepherd/planter.md` + `commands/plant.md`. Adds 6/6 net-new
  babysitter subsections: escalation triage, git custody, cleanup
  stewardship, concurrent-write discipline, hand-back timing, observation
  contract. Tools list includes GitHub write tools per side-effect
  ownership.
- **`commands/spawn.md`** (995 lines) — `/shepherd:spawn` command with
  `--parallel <N>` (fan out N sibling teammate-conductors with planter-side
  dev-order merge gate, cap N ≤ 4) and `--auto` (sequential autopilot,
  fresh teammate context window per sprint, planter handles inter-sprint
  cleanup + git + handoff). Platform compatibility note for GitHub issue
  #31977.
- **`skills/shepherd/doctrines/spawn-escalation.md`** (750 lines) —
  canonical teammate↔planter escalation contract: SendMessage primary
  channel, filesystem durable fallback at `~/.claude/tasks/{team}/`,
  `PostToolUse`-driven heartbeat row in shctx, wave-boundary commit
  discipline (≤ 1 wave loss horizon for in-process teammates with no
  `/resume`).

#### Retired

- `/shepherd:autorun` → use `/shepherd:spawn --auto`
- `/shepherd:parallel` → use `/shepherd:spawn --parallel <N>`
- `commands/{autorun,parallel}.md` collapsed to thin delta notes
- `skills/shepherd/{autorun,parallel,planter}.md` collapsed to thin
  redirects pointing at the canonical successors

#### Refactored (thin-loader pattern)

- `commands/start.md`: 99 → 52 lines. Loads `agents/conductor.md` as a
  system-prompt addendum; Step 0 bootstrap preserved (shepherd.toml,
  branch detect, doctrines, handoff, CLAUDE.md).
- `commands/plant.md`: 138 → 52 lines. Loads `agents/planter.md`; Opus
  model gate preserved.
- `skills/shepherd/SKILL.md`: dispatch-procedure block collapsed to a
  pointer at `agents/conductor.md` (mitigates the R3 triple-drift risk
  surfaced by the D-LIFT survey).
- `skills/shepherd/flock.md`: new §VI Meta tier section listing planter
  and conductor profiles.
- `skills/shepherd/pipeline.md`: §IX/§X autorun-walk + parallel-walk now
  correctly attribute loop/fanout control to the **planter** (the
  conductor doesn't loop itself under `--auto`).
- `CLAUDE.md`: flock count corrected to six domain agents + two meta
  orchestrators; commands table updated with spawn row + retirement
  notice; file contracts expanded with `agents/conductor.md` and
  `agents/planter.md` invariants.

#### Phase 0 discovery reports

- `2026-05-19-teammate-api-discovery.md` (D-API) — Agent Teams platform
  surface: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true`, in-process
  teammateMode, SendMessage mailbox, `TeammateIdle`/`TaskCreated`/
  `TaskCompleted` hooks. Hard limits documented.
- `2026-05-19-profile-lift-survey.md` (D-LIFT) — ~620 + ~280 lines of
  lift identified by file:line range; 6 babysitter gaps cataloged as
  net-new; 5 overlap questions adopted with operator resolutions.
- `2026-05-19-teammate-subagent-roadmap.md` (R-ROADMAP) — GitHub issue
  #31977 (open, labeled `bug`) is the load-bearing constraint;
  tmux-mode teammates already have Agent tool. Verdict YES-EVENTUAL /
  MEDIUM. Design is forward-compatible — no spawn-side redesign when
  the bug fixes.
- `2026-05-19-flock-teammate-efficacy.md` (R-FLOCK) — per-agent matrix.
  Top-3 leaf-teammate candidates: `@discovery` > `@worker` > `@engineer`.
  Pattern B (peer-to-peer flock teammates) NOT recommended for v5.1.4 (no
  role attestation; deps already file-mediated).

#### Known limitations

- **In-process `teammateMode` + GitHub #31977**: teammate sessions in
  in-process mode do not expose the `Agent` tool, so a spawned teammate
  cannot dispatch the flock the way main chat can. **Workaround**: use
  tmux `teammateMode` for full functionality, or stay on `/shepherd:start`
  in main chat until the bug lands. See `commands/spawn.md
  §Platform compatibility` for the full table.

---

## v5.1.3 — 2026-05-19

### Cleanup, cache discipline, dispatch telemetry

v5.1.3 fixes the base. No new conductor capabilities, no new agent roles, no
semantic changes to the dispatch pipeline. The sprint is a focused sweep:
smaller, more stable agent prefixes; brief ordering that puts variable
content last so prompt caching can do its job; SubagentStop telemetry that
proves the wins are real; and a sweep of accumulated cruft.

#### Agent restructure (Lanes A1 + A2)

- **Five-agent prefix/reference split** — `agents/{engineer,coder,critic,worker,discovery}.md`
  trimmed to the cacheable prefix (frontmatter, identity, prohibitions,
  halt codes, mandatory protocol, report shape, "What you are NOT"); verbose
  reference catalogs extracted to `skills/shepherd/agents/<role>.reference.md`
  loaded on demand via Skill at agent startup.
- **`agents/auditor.md` trim** — same restructure; reference content extracted
  to `skills/shepherd/agents/auditor.reference.md`.
- **Inline `Greatness is the bar` preamble removed** — replaced with a single
  `> See doctrines/agent-excellence.md.` line per agent (doctrine already
  existed; the inline duplication just bloated every dispatch).
- **`tools:` frontmatter audit** — each agent's MCP tool list now contains
  only tools actually invoked by its documented protocol.

#### Brief assembly discipline (Lane B)

- **New doctrine `doctrines/brief-cache-discipline.md`** — stable framing first
  (`[ROLE]` → `[SKILLS]` → `[DOCTRINES]` → `[PROTOCOL-REMINDERS]`), variable
  content last (`[FILE-SCOPE]` → `[CONTEXT-INVENTORY]` → `[DO-NOT-DUPLICATE]` →
  `[ACCEPTANCE]` → `[NON-GOALS]` → `[WORKTREE]` → `[BASE-COMMIT-EXPECTED]`).
  Enforcement is post-hoc via the completeness auditor.
- **`pipeline.md` §V** gains a "Cache-first brief ordering" subsection citing
  the new doctrine.

#### Dispatch telemetry (Lane C)

- **New hook `hooks/scripts/subagent_telemetry.sh`** — captures cache stats
  per subagent dispatch (`cache_read_input_tokens`,
  `cache_creation_input_tokens`, `ephemeral_5m_input_tokens`,
  `ephemeral_1h_input_tokens`, `hit_rate`). Non-blocking on any failure;
  emits `parse_error` rows rather than silently no-op.
- **Registry schema migration 0006** — new `index_cache_usage` table and
  `v_cache_usage` view aggregating per sprint + role.
- **New `shctx query cache-usage`** — surfaces hit-rate per sprint + role.
- **`shctx refresh --scope=telemetry`** — ingests JSONL events into the
  registry idempotently.
- **New doctrine `doctrines/cache-telemetry.md`** — what's captured, where it
  lands, how it surfaces in close reports, threshold guidance (exploratory
  baseline for the first 2–3 sprints; < 40% aggregate hit-rate is a MEDIUM
  finding flag once baselines settle).

#### Cleanup (Lane D)

- Dead command-script sweep (no scripts removed; all `cmd_*.sh` reachable
  through the `shctx` dispatcher's dynamic dispatch or via internal stage
  composition in `cmd_sprint.sh`).
- Stale-reference audit across `skills/shepherd/doctrines/` and
  `skills/shepherd/{pipeline,planter,SKILL}.md` — all `v4.x` / `v5.0.x`
  references are legitimate historical-origin annotations; no operative
  references to removed mechanisms were found.
- `_candidates/` directory contains only its README (the promotion-pipeline
  doc); no orphan candidates to promote or delete.
- Gitignored-but-tracked sweep: zero hits.
- Version-source-of-truth files verified at 5.1.3 across `plugin.json`,
  `marketplace.json`, both SKILL frontmatters, README, and this changelog.

#### Version-scale roadmap doctrine (Lane E)

- **New doctrine `doctrines/version-scale-roadmap.md`** — codifies the
  four-tier scale factor: major `vX` (~1000 sprints, vision), minor `vX.Y`
  (~100 sprints, roadmap), patch `vX.Y.Z` (≤ 10 sprints, the planning unit),
  dev `vX.Y.Z-dev.N` (1 sprint, the execution branch — cut from the patch
  branch as a cushion). Extends `sprint-as-patch.md` upward by naming the
  three levels above the dev sprint.
- **`planter.md` §0** updated to anchor seed authorship at PATCH scope
  (seeds do not carry dev.N suffix).
- **`agents/engineer.md`** updated to cite the doctrine and clarify the
  engineer operates at DEV scope (decomposing the patch seed).

---

## v5.1.2 — 2026-05-17

### Hook teeth, anti-laziness preambles, dir-watch, specialist dispatch, slug naming, discovery registry

The v5.1.1 release landed the new doctrines + agent contracts; v5.1.2 lands
the matching hook teeth, registries, and consistency sweeps. Doctrines from
v5.1.1 now have machine-enforced guardrails instead of being agent-prompt
discipline alone.

#### Hook hardening

- **New `hooks/scripts/_lib.sh`** — shared library every hook sources.
  Exports `is_shepherd_project`, `resolve_namespace`, `json_field`,
  `json_response`, `emit_context`, `emit_deny`, `pass_silent`, `log_event`,
  `current_role`, `current_sprint`, `sprint_root`, `in_subworktree`.
  jq-preferred with python3 fallback. Every emit goes through `log_event`,
  which appends a JSONL entry to `<ns>/logs/hooks/YYYY-MM-DD.jsonl`.
- **New `hooks/scripts/agent_invocation_tagger.sh`** — `PreToolUse(Agent|Task)`
  parses the agent body's `# @<role>` header and writes
  `<ns>/dispatch/<sprint>/<tool_use_id>.json` so downstream hooks can make
  role-conditional decisions without re-parsing prompts.
- **New `hooks/scripts/discovery_capture.sh`** — `PostToolUse(Agent|Task)`
  indexes `## DISCOVERY REPORT` blocks to `<ns>/discoveries/<sprint>/<id>.json`
  for cross-sprint reuse.
- **New `hooks/scripts/dedup_write_guard.sh`** — `PreToolUse(Write|Edit)`
  scans @coder-emitted content for new public symbol declarations
  (rust / python / ts/js / go) and BLOCKS if the symbol already exists
  elsewhere in the workspace. The hook layer's expression of
  zero-duplicate-tolerance — the conductor's pre-dispatch DEDUP-GATE
  remains the primary check; this catches what slips through.
- **`bash_guard.sh` extensions** — adds three role-conditional BLOCK checks
  on top of the v5.1.0 commit-on-lane block: auditor invoking gates from a
  sub-worktree (false-CRITICAL prevention), @discovery invoking
  state-modifying Bash (read-only enforcement), parallel cargo invocations
  WARN, cd-into-worktree WARN.
- **`lock_guard.sh` extensions** — role-based write-path enforcement:
  @discovery may only Write to `{paths.reports}/<date>-discovery-*.md`;
  @auditor may only Write to `{paths.reports}/<date>-(intro-)audit-*.md`;
  @coder Write must land inside the recorded `[WORKTREE].Path` from
  `agent_invocation_tagger`'s dispatch record. Sprint-lock conflict still
  WARN-only (does not block).
- **`agent_pause_detector.sh` extension** — beyond writing the structured
  pause record to `<ns>/pauses/<id>.json`, the hook now ALSO auto-drafts a
  near-complete dispatch brief stub at `<ns>/pauses/<id>.brief.md` per
  the satellite role (coder / discovery / worker / auditor). The conductor
  reads a ready-to-fire brief instead of composing one from scratch.
- **`session_open.sh` extension** — fourth check: when HEAD matches the
  sprint branch pattern, verify the corresponding `plan.md` exists (slug
  OR legacy dotted form). Surfaces missing-plan as a warning so engineer
  dispatch isn't silently skipped.
- **`bash_post.sh` extension** — cwd-drift detection post-Bash; surfaces
  when the conductor's cwd has migrated into a sub-worktree.

#### Anti-laziness — `agent-excellence` doctrine + strive-higher preambles

- **New doctrine** `skills/shepherd/doctrines/agent-excellence.md` — every
  agent must aim higher than "ship code that compiles". Refuse lazy
  duplication, honor language idioms, halt rather than ship sub-standard
  work. Pairs with `dedup_write_guard.sh` (the hook teeth) and the
  zero-duplicate-tolerance doctrine.
- **Strive-higher preamble** prepended to all six `agents/*.md` so every
  flock-agent loads the excellence contract before the role-specific
  instructions.

#### Slug naming convention

- **New doctrine** `skills/shepherd/doctrines/seed-naming.md` — branches
  keep dots (`v5.1.2-dev.3`); filenames collapse them (`v512-dev3.seed.md`).
  Origin: operator caught the planter producing `v0.3.2-dev.5.seed.md`
  (dotted form bleeding from `{sprint_branch}`) when the convention had
  been the slug.
- **`shepherd.toml` schema extension** — `[branching].patch_slug_pattern`
  and `sprint_slug_pattern` added. If absent, framework falls back to
  branch pattern with a deprecation warning.
- **Templates + briefs migrated** to use `{sprint_slug}` / `{patch_slug}`
  for filename construction in `skills/shepherd/references/seed-template.md`,
  `skills/shepherd/references/agent-briefs.md`, `skills/shepherd/SKILL.md`,
  `skills/shepherd/pipeline.md`, `skills/shepherd/doctrines/preflight-doctor.md`,
  `skills/shepherd/doctrines/mid-flight-operator-amendment.md`,
  `skills/shepherd/doctrines/gates-restoration.md`, `commands/plant.md`,
  `commands/parallel.md`, `agents/engineer.md`.
  Branch placeholders preserved where the value is the literal branch
  (git commands, dispatch dir key, milestone target, etc.).
- **Examples in `examples/{axiom,minimal}/shepherd.toml`** include the new
  slug pattern keys.
- **`docs/configuration.md` §[branching]`** documents both pattern pairs.

#### Dir-watch — content-hash gating

- **New migration** `skills/context/schema/migrations/0005_watch_paths.sql` —
  registers watched directories and their last-seen content hash.
- **New `skills/context/scripts/cmd_watch.sh`** — `shctx watch
  add/mark/status/list/remove` over the watch_paths table.
- **New doctrine** `skills/shepherd/doctrines/dir-watch.md` — semantics,
  hashing strategy, integration points (engineer mesh, conductor pre-MESH
  fast-path).

#### Specialist dispatch

- **New doctrine** `skills/shepherd/doctrines/specialist-dispatch.md` —
  framework is "closed at six + specialist exceptions". The flock proper
  remains six; a specialist agent (security-reviewer, perf-analyzer, etc.)
  may be dispatched in addition when the seed names one explicitly.
- **`skills/shepherd/SKILL.md`** + **`skills/shepherd/flock.md`** language
  updated from "closed flock" to "closed at six + specialist exceptions".

#### Discovery registry CLI

- **New `skills/context/scripts/cmd_discovery.sh`** — `shctx discovery
  list/show/search/clear` over the `<ns>/discoveries/<sprint>/<id>.json`
  files captured by `discovery_capture.sh`. Engineer pulls cross-sprint
  discoveries at MESH without re-parsing report markdown.
- **`shctx` dispatcher** routes `discovery` and `watch` subcommands to
  their new handlers.

#### Plugin description trim

The verbose multi-version description in `.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` collapsed to a single capability
statement. Per-version detail lives here in CHANGELOG.md.

#### Deferred to v5.1.3

- **Lane B — CLI subcommand reorg** (`shctx workspace/brief/lane/discovery/
  watch/pauses` groups). Scope comparable to all six landed lanes
  combined; better as an isolated refactor.
- **`cmd_doctor.sh` extension** for v5.1.1+ surfaces (`<ns>/discoveries/`,
  `<ns>/dispatch/`, `<ns>/logs/hooks/` writability, intro-wave plan-node
  presence detection). The doctor exists at v5.0.4 baseline; v5.1.1
  surfaces uncovered.
- **`agent_insight_capture.sh` refactor to `_lib.sh`** — v5.0.9 logic still
  functions; refactor risk not worth the cleanup this patch.

---

## v5.1.1 — 2026-05-15

### Discovery agent + INTRO-COMBO-WAVE + hypothesis-driven auditor + sprint-as-patch

Per operator request: introduce `@discovery` (read-only orientation, no
terminal-mutating Bash, sole task is to comprehend) so the conductor and
engineer don't burn context on exploratory reads. Pair with an intro-mode
parallel wave at sprint open. Tighten auditor methodology via
`superpowers:systematic-debugging`. Reframe sprint scope as patch-equivalent
("every dev.N sprint IS a patch in scope").

- **New agent** `agents/discovery.md` — sixth lane in the flock. Sonnet, `thinking: high`, color blue. Tools: Read/Grep/Glob/NotebookRead/LSP, read-only Bash, MCP read-only, Web*, Skill, ToolSearch, TaskCreate/Get/List/Update, and Write restricted to `{paths.reports}/<date>-discovery-<id>.md`. NEVER: Edit, MCP write, Agent dispatch. Five canonical use-case patterns: PRE-MESH-DISCOVERY, PRE-HOTFIX-DISCOVERY, ARCHITECTURE-DISCOVERY, DOCTRINE-RECONCILIATION-DISCOVERY, MCP-STATE-DISCOVERY.
- **New doctrine** `skills/shepherd/doctrines/discovery-readonly.md` — `@discovery` contract, role boundaries vs `@worker` / `@auditor` / `@critic`, max-concurrent rules, report shape, cross-sprint reuse via `<ns>/discoveries/<sprint>/<id>.json`.
- **New doctrine** `skills/shepherd/doctrines/intro-combo-wave.md` — INTRO-COMBO-WAVE between SEED-VERIFY and MESH. Default composition: 3 discoveries (prior-close-audit-summary, canonical-types-freshness, gh-state-inventory) + 2 intro-mode auditors (regression, carry-forward-disposition). All read-only, all in one Agent batch. Engineer reads outputs as `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` in its MESH brief.
- **New doctrine** `skills/shepherd/doctrines/auditor-hypothesis-driven.md` — every finding now carries Hypothesis + Falsification attempt + Confidence. LOW-confidence findings land under `## Open questions`, not as GH issues. Bayesian finding-class weighting from sprint-patterns registry. Auditor loads `superpowers:systematic-debugging` as Step 1.
- **`agents/auditor.md` rewrite** — Step 1 loads `superpowers:systematic-debugging`. Three modes: `close` (grades), `regression` (intro mode, no grade), `carry-forward-disposition` (intro mode, no grade). Per-finding contract requires the hypothesis triple. Per-concern emphasis sections now lead with a hypothesis-first prompt. New `## Verifications` section for disproved hypotheses.
- **New doctrine** `skills/shepherd/doctrines/sprint-as-patch.md` — every `dev.N` sprint is operator-equivalent to a full patch. Planter sizes seeds at patch-grade; engineer authors plans at patch-grade body depth; critic rejects under-scoped seeds; auditor grades against patch-grade output expectation. T-shirt lane minimums revised: M → 4, L → 6, XL → 6/wave.
- **`skills/shepherd/planter.md` §0** — sprint-as-patch sizing made binding for planter seed authorship.
- **New doctrine** `skills/shepherd/doctrines/hook-event-log.md` — `<ns>/logs/hooks/YYYY-MM-DD.jsonl` schema, jq queries, retention guidance, anti-patterns (no live tailing, no secret logging).
- **New doctrine** `skills/shepherd/doctrines/preflight-doctor.md` — `shctx doctor` preflight semantics, exit-code matrix, integration with `/shepherd:start`.
- **`skills/shepherd/SKILL.md`** — six-agent flock table, INTRO-COMBO-WAVE in §1 INTRO checklist, sprint-as-patch impactfulness contract made binding, six new doctrines indexed in §XI file map, six new anti-patterns (#23–#28).
- **`skills/shepherd/flock.md`** — new `## @discovery` section between `@critic` and `@worker`. Six-agent flock language throughout.
- **`skills/shepherd/pipeline.md`** — `DISCOVERY` and `INTRO-COMBO-WAVE` node types added to §II stage taxonomy. New edge predicates: `on-research-complete`, `on-intro-wave-complete`, `on-intro-audit-complete`.
- **`skills/shepherd/references/agent-briefs.md`** — six discovery brief templates (D-A through D-F) + intro-mode auditor templates + INTRO-COMBO-WAVE single-message dispatch pattern.

#### Hook hardening + preflight (initial scope; full hook overhaul deferred to v5.1.1)

The v5.1.0 release lands the new doctrines + agent contracts; the matching
hook teeth + `shctx doctor` ship in v5.1.1. Doctrines/agent contracts are
the load-bearing change; hooks are the guardrail. Operator can adopt v5.1.0
with hooks left at v5.1.0-baseline; v5.1.1 will add:

- `hooks/scripts/_lib.sh` shared library (jq/python fallback, log_event)
- `hooks/scripts/agent_invocation_tagger.sh` (PreToolUse on Agent|Task)
- `hooks/scripts/discovery_capture.sh` (PostToolUse on Agent|Task)
- `bash_guard.sh` extension (auditor cwd guard + discovery state-modify block)
- `lock_guard.sh` extension (role-based write-path enforcement)
- `agent_pause_detector.sh` extension (auto-draft satellite brief stub)
- `skills/context/scripts/cmd_doctor.sh` (`shctx doctor` preflight)
- `<ns>/logs/hooks/YYYY-MM-DD.jsonl` event log activation

Doctrines/agent contracts are the load-bearing change; hooks are the
guardrail. Operator can adopt v5.1.1 with hooks left at the v5.1.0 baseline.

---

## v5.1.0 — released

### Flock cohesion — shared substrate across agents

Per operator observation: "every agent feels isolated rather than acting as part of a larger group so the agents feel like they need to re-invent everything every time from scratch." This release names the structural gap and lands the substrate.

- **New doctrine** `skills/shepherd/doctrines/flock-cohesion.md` — verbalizes the shared-substrate model. Four channels: canonical-types (static "what exists where"), graph state + trace (mechanical "who is doing what now"), pauses (synchronous "I need this"), and insights (asynchronous "I noticed this"). All four are read at MESH; written at DISPATCH and REPORT.
- **`[SIBLING-LANES]` brief block** (`skills/shepherd/references/agent-briefs.md`) — every wave dispatch brief now lists the other lanes in the wave with their `[FILE-SCOPE]` summaries and the symbols/artifacts they produce. The single most-requested affordance: agents finally see what their siblings are doing. Validity checklist updated.
- **`## INSIGHTS` report section** (`agents/coder.md`, `agents/worker.md`) — optional cross-lane observations any agent can append to their final report. Canonical kinds: `relocation`, `extension`, `duplication`, `consolidation`, `gap`, `nit`. Replaces the absent "I saw something interesting" channel.
- **New hook** `hooks/scripts/agent_insight_capture.sh` — `PostToolUse(Agent|Task)` parses `## INSIGHTS` blocks, writes one JSON record per entry to `<ns>/insights/<sprint>/<id>.json`. Silent when no INSIGHTS block is present.
- **New: `shctx insights <list|show|export|clear>`** (`skills/context/scripts/cmd_insights.sh`) — registry CLI. `export --md` renders as markdown for engineer mesh row 13 consumption.
- **`agents/engineer.md` Phase 0 mesh row 13** — engineer reads the prior sprint's insights at next-sprint mesh; decides per-kind how to action (relocation → consider scoping a lane; nit → aggregate before acting; etc.). Insights NOT actioned are surfaced under "Cross-lane insights not scoped this sprint" — operator visibility is the rule.

### Dispatch cascade — Stage Graph as rule engine

Per operator request: "create some type of rule engine layer that would allow the conductor to dispatch all agents using conditional links so agents cascade through the plan." The plan is now extractable into a machine-readable topology that `shctx graph` walks deterministically — the conductor's only LLM-driven step per tick is brief authoring + edge-label selection; routing is mechanical.

- **New doctrine** `skills/shepherd/doctrines/dispatch-cascade.md` — the plan IS the program; the conductor IS the interpreter; the Stage Graph IS the topology.
- **New: `shctx plan <extract|topology|validate>`** (`skills/context/scripts/cmd_plan.sh`) — parse plan.md's `## Stage Graph` YAML block, materialize `<ns>/graph/state.json`, pretty-print topology, run structural validation (acyclic, predicates resolve, parallel_with mutual).
- **New: `shctx graph <status|next|mark|trace|reset>`** (`skills/context/scripts/cmd_graph.sh`) — the walker. `next` returns the next-eligible batch honoring `parallel_with` cliques. `mark <id> --state=done --exit=<edge>` advances state and auto-promotes downstream nodes when their in_predicates are satisfied. `trace` is append-only at `<ns>/graph/trace.jsonl`.
- **New: `shctx pauses <list|show|resolve|clear>`** (`skills/context/scripts/cmd_pauses.sh`) — the PAUSE-FOR-DEPENDENCY registry. Hook captures pauses; conductor reads structured records via `show`; `resolve --satellite-sha=<sha>` marks completion.
- **New hook** `hooks/scripts/agent_pause_detector.sh` — `PostToolUse(Agent|Task)` parses agent output for `Halt code: PAUSE-FOR-DEPENDENCY`, extracts the structured satellite request, writes `<ns>/pauses/<id>.json`, and surfaces an `additionalContext` alert. Eliminates the LLM re-parsing step.
- **`adaptation-loop.md §V-bis`** — node-level telemetry from `trace.jsonl` (duration, exit-edge frequency, halt rate per node-type) feeds the sprint-pattern registry with finer-grained signal than sprint-level summaries.
- **`pipeline.md §V`** — walk algorithm now references the `shctx graph` runtime mechanization.

### Field feedback from v5.0.8 / axiom v0.3.2-dev.0

**§1 — `PAUSE-FOR-DEPENDENCY` primitive (most requested).** First-class Stage Graph escape hatch for mid-lane out-of-scope dependencies. Coder emits a structured halt → conductor dispatches an XS/S satellite `@coder` → `SendMessage` resumes the paused lane. Cap: 2 satellites/lane. Cherry-pick order invariant: satellite commit lands before resumed-lane commit.
- New: `skills/shepherd/doctrines/pause-for-dependency.md`
- `agents/coder.md` — `PAUSE-FOR-DEPENDENCY` halt code, trigger protocol, report shape
- `skills/shepherd/pipeline.md` — `PAUSE-FOR-DEPENDENCY` + `RESUME-LANE` stage taxonomy; `on-pause-dep` edge predicate; `§XV-quint` subgraph walkthrough

**§2 — Coder lane file-scope cap.** `agents/engineer.md` — soft cap of ≤3 files per lane MAY-MODIFY; single-file exception at >300 LOC.

**§3 — Parallel cherry-pick conflict documentation.** `skills/shepherd/references/branching-model.md §VII-bis` — file overlap between parallel lane branches is expected; how to resolve; STAGE-GRAPH-VIOLATION vs legitimate conflict.

**§4 — Conductor anchor drift hygiene.**
- New: `hooks/scripts/bash_post.sh` — `PostToolUse(Bash)` detects cwd drift into sub-worktrees
- `hooks/hooks.json` — wires the new PostToolUse hook
- `hooks/scripts/session_open.sh` — adds sprint-patterns.md absence warning
- `hooks/scripts/bash_guard.sh` — adds `cd`-into-worktree warning + corrected cargo-parallel regex (no longer false-positives on `cargo check && cargo test`)

**§5 — Cargo sequential gates doctrine.**
- New: `skills/shepherd/doctrines/cargo-sequential-gates.md`
- `skills/shepherd/pipeline.md §XV-sext` — referenced at WAVE-GATE
- `skills/shepherd/SKILL.md §2 BODY` — cross-referenced from gate sequence
- `hooks/scripts/bash_guard.sh` — Check 2: warn on backgrounded cargo invocations (`&` not `&&`)

**§6/§7 — /reload-plugins escape hatch + MCP preference.**
- New: `skills/shepherd/doctrines/plugin-reload-escape.md`
- `skills/shepherd/pipeline.md §XV-sept` — Phase 0 MCP availability + reload note

**§8 — Programmatic GH issue triage (`shctx issues classify`).** Replaces the per-sprint LLM enumeration pass with deterministic label/milestone/severity bucketing from the cached `index_issues` table.
- New: `skills/context/scripts/cmd_issues.sh` — subcommands `classify` and `list`; buckets `blocking-this-sprint`, `labeled-non-issue`, `tracking-future`, `drift-risk`, `unclassified`; `--unclassified-only` for focused LLM review
- `skills/context/scripts/shctx` — registers `issues` subcommand under the `<noun> <verb>` convention
- `agents/engineer.md` Phase 0 mesh row 1 — preferred path is `shctx issues classify`; MCP/gh enumeration is the fallback when cache is stale

**§9 — Sprint-patterns registry verification.**
- `hooks/scripts/session_open.sh` — surfaces `sprint-patterns.md` absence at session start
- `skills/shepherd/SKILL.md §1` — existence check added to INTRODUCTION checklist
- `skills/shepherd/doctrines/adaptation-loop.md` — on-first-close creation protocol

**§10 — Feedback classification.** `skills/shepherd/doctrines/adaptation-loop.md §VI-bis` — framework-generic vs project-specific feedback rule; framework-generic candidates are flagged in close reports for doctrine promotion.

### Fix: prevent dual-namespace split-brain between `.shepherd/` and `.artifacts/`

The root cause: `shctx init` (no flags) defaulted to `.shepherd/` on a fresh project while example `shepherd.toml` files had `[paths]` entries referencing `.artifacts/`. The conductor's Write calls then created `.artifacts/` as a directory side effect, leaving both namespaces present. `shctx_artifacts_root()` always preferred `.shepherd/` while the conductor kept reading `.artifacts/*` — split-brain until the operator migrated by hand.

- `scaffold.sh` — guard refuses to scaffold namespace X when namespace Y already carries the shctx `.gitignore` marker and X does not yet exist. Emits a clear error with remediation steps.
- `_lib.sh` — `shctx_artifacts_root()` now emits a stderr warning when both directories coexist; suppressed via `SHCTX_QUIET=1` in callers that handle this themselves.
- `cmd_doctor.sh` — reports the dual-namespace state as a `WARN` check with a fix instruction.
- `examples/minimal/shepherd.toml` — `[paths]` updated from `.artifacts/` to `.shepherd/` (the v5.0.0+ default); comment added explaining the namespace coupling.
- `examples/axiom/shepherd.toml` — comment added explaining `.artifacts/` is the legacy namespace for that project.
- `skills/context/SKILL.md`, `skills/shepherd/SKILL.md` — hardcoded `.artifacts/` references replaced with namespace-neutral `<namespace>/`.

---

## v5.0.7 — 2026-05-12

**Hotfix: hooks schema.** `hooks/hooks.json` was missing the top-level `"hooks"` wrapper key, causing plugin load failure (`expected record, received undefined`). All event handlers now correctly nested under `{"hooks": {...}}`. Version refs bumped across all five sources of truth.

---

## v5.0.6 — 2026-05-12

**Single-plugin-repo migration + conductor anchor discipline.** Two
independent threads:

1. **Repo isolation.** The plugin tree moved out of `plugins/shepherd/`
   to the repo root in earlier commits; this release finishes the
   migration so manifests, docs, the `shctx release` pipeline, and the
   test suite all agree the repo IS the plugin.
2. **Conductor anchor discipline.** Field feedback flagged a failure
   mode beyond the v5.0.3 cwd ban: the conductor's `git switch <agent-branch>`
   (for "inspection") and `git worktree add` from inside an existing
   worktree silently produced **worktrees-within-worktrees** state.
   v5.0.6 codifies the broader anchor invariant.

### Changed — doctrines

- **`doctrines/conductor-cwd.md` extended to anchor discipline.** Title
  + scope broadened from "conductor cwd" to "conductor anchor (cwd +
  HEAD + worktree context)". Three explicit bans with the correct
  alternative for each:
  - Ban 1 — `cd`/`pushd` into a worktree (the v5.0.3 cwd rule, preserved).
  - Ban 2 — `git switch` / `git checkout` to an `agent-*` lane branch.
    The conductor's HEAD MUST remain `{sprint_branch}` (or `{patch_branch}`/
    `{main_branch}` during release plumbing). Inspect agent branches via
    `git -C <worktree-path>` only.
  - Ban 3 — `git worktree add` from inside a worktree. Always run from
    the sprint root, or use `shctx worktree create-batch` which assumes it.
  Mandatory three-check verification (`pwd` / `git rev-parse --abbrev-ref
  HEAD` / `git rev-parse --git-dir == --git-common-dir`) added to the
  doctrine and wired into the §1 INTRO conductor checklist.

### Added — anti-pattern

- **SKILL.md anti-pattern #22** — `Conductor git switch/git checkout to an
  agent-* lane branch → HEAD drift → wrong-base worktrees → nesting`.
  Cross-references `doctrines/conductor-cwd.md` Ban 2 + Ban 3.

### Changed — anti-pattern

- **SKILL.md anti-pattern #15** sharpened to specify the drift mode (cwd)
  and link to `doctrines/conductor-cwd.md` Ban 1 — distinguishing it from
  the new HEAD-drift case in #22.

### Changed — repo isolation (single-plugin-repo migration finish)

- `.claude-plugin/marketplace.json` — drop the `fl03-skills` entry;
  shepherd `source` is now `.`; homepage URLs point at the repo root.
- `.claude-plugin/plugin.json` — homepage URL fixed; the `.shepherd/root.db`
  description typo corrected to `.artifacts/root.db`.
- `CLAUDE.md` rewritten for the root-level layout (the repo *is* the
  plugin; no more `plugins/shepherd/` prefix).
- `README.md` install section now leads with `/plugin marketplace add
  fl03/shepherd` and symlinks the repo root, not the old subpath.
- `CHANGELOG.md` no longer claims to cover `fl03-skills` (which now lives
  in its own repo).
- `examples/axiom/CLAUDE-snippet.md` — plugin URL + version pin fixed.
- `skills/shepherd/flock.md` — rephrased the `code-style` reference now
  that `fl03-skills/skills/code-style/` lives outside this repo.
- `skills/context/SKILL.md`, `skills/context/schema/0001_init.sql` —
  doctrine + schema header comments updated to the new layout.
- `skills/context/scripts/cmd_release.sh` — `VERSION_FILES` and
  `CHANGELOG_PATH` rebuilt against the root-level manifest set.
- `skills/context/scripts/cmd_doctor.sh` — config-doc pointer updated.
- `skills/context/tests/test_release.sh` — fixtures match the new bump
  targets.

### Added — adaptation loop (self-improvement)

- **`doctrines/adaptation-loop.md`** (new) — sprint pattern registry (`{paths.ctx}/sprint-patterns.md`): append-only, per-sprint. Write protocol: completeness auditor at CLOSE-SWARM. Read protocol: `@engineer` mesh row 10, `@planter` seed context. Conductor fires `[TREND]` alert at PAUSE when 3+ same-concern CRITICAL/HIGH across 3 consecutive sprints.
- **`agents/engineer.md`** — mesh row 10 (sprint-pattern registry), four action triggers (systemic risks / chronic carry-forwards / recurring halts / clean-streak concerns), plan-quality bar item, ENGINEER REPORT field.
- **`agents/engineer.md`** — mesh row 11 (prior close-audit reports self-learning hook): reads `{paths.reports}/*-audit-*.md`, surfaces `HF-this-sprint=no, carry=yes` findings into the carry-forward checklist; recurring deferred findings flagged `[CHRONIC-CANDIDATE]`.
- **`agents/critic.md`** — §6 sprint-pattern awareness, Pattern Echoes output section, clarified PROCEED WITH CHANGES vs RECONSIDER boundary.
- **`agents/auditor.md`** — completeness concern writes sprint-pattern journal entry (5-step); `## Pattern delta` report section.
- **`agents/worker.md`** — Pattern 5: sprint pattern registry backfill brief template.
- **`skills/shepherd/planter.md`** — mesh row 12 names `sprint-patterns.md`; §VI.A sprint-pattern seed-action table.

### Added — operator communication + session continuity

- **`skills/shepherd/SKILL.md` §VIII** — Operator communication norms: mandatory surface moments, status line format `[NODE] {node-id} → {outcome} | {one-sentence key finding}`, no-silent-proceeding rule, no walls-of-text rule.
- **`skills/shepherd/SKILL.md` §IX** — Session continuity: 5-step mid-sprint recovery protocol (locate plan → read walk trace → survey git log → check orphan worktrees → reconstruct walk position).

### Changed — language-agnostic gates

- `skills/shepherd/SKILL.md` §III and `skills/shepherd/flock.md` — gate sequence now uses `{gates.format}`, `{gates.check}`, `{gates.lint}` from `shepherd.toml [gates]` instead of hardcoded `cargo` commands. Language-skill auto-fix note added.
- `skills/shepherd/flock.md` — anti-pattern #17: missing sprint-pattern registry read at mesh time.

### Added — doctrines (axiom dev.8a field feedback)

- **`doctrines/work-bound-to-tracking.md`** (new) — every intentional gap in production code cites a GH issue number via a language-native stub primitive (`todo!("see #N")` / `throw new Error("TODO see #N")` / `raise NotImplementedError("see #N")` / `panic("TODO see #N")`). Enforcement: `@engineer` counts stubs at mesh, `@coder` must pair stub with GH issue, `@auditor` greps for naked TODO/FIXME/XXX/HACK.
- **`doctrines/mid-flight-operator-amendment.md`** (new) — four amendment types (clarification, feature addition, production regression, architectural decision) with defined conductor responses; dispatcher-patch ledger at `{paths.ctx}/dispatcher-patches/{sprint_branch}-pc-{N}.md`; HARD-STOP triggers (secret rotation, north-star change, security rollback).
- **`doctrines/_candidates/README.md`** (new) — promotion pipeline from project-specific memory to framework-intrinsic doctrine; candidate template with frontmatter; promotion checklist.
- **`doctrines/worktree-base-drift.md`** — `§Canonical no-isolation workaround (v5.0.6)`: when `isolation:"worktree"` defaults to `main`, drop isolation entirely; rely on file-disjoint `[FILE-SCOPE]`; coders commit directly to sprint branch. Documents what you lose (cherry-pick barrier, worktree-confinement enforcement) and mitigations (disjoint plan + post-wave `git diff --stat`).
- **`doctrines/conductor-cwd.md`** — `§HEAD advancement in no-isolation mode`: HEAD advancing as coders commit to the sprint branch is NOT a doctrine violation; the invariant is "HEAD stays on `{sprint_branch}`", not "HEAD stays pinned to dispatch-time SHA".

### Added — pipeline stages + dispatch patterns

- **`skills/shepherd/pipeline.md`** — `HOTFIX-DYNAMIC` stage type: variable-cardinality `@coder` batch derived from gate-error cluster analysis at walk-time (vs. pre-declared HOTFIX). Stage Graph YAML example included.
- **`skills/shepherd/pipeline.md` §XIII-bis** — Structured gate output + parallel HF dispatch: `--message-format=json --keep-going` collects full error surface; errors parsed and clustered by file-disjoint scope; one `@coder` per cluster dispatched in a single batch. Gate JSON artifacts stored in `.shepherd/runs/`.

### Added — standard worker dispatch templates

- **`skills/shepherd/references/agent-briefs.md`** — W-A/B/D/E standard worker brief templates:
  - **W-A** — test-surface audit (classify all tests into 4 buckets; 10 min, 30 calls)
  - **W-B** — Phase 0 mesh validation (GH issues + Sentry + deploy status; 15 min, 20 calls)
  - **W-D** — bulk GH issue triage + close script generation (20 min, 60 calls)
  - **W-E** — production diagnostic for regression amendments (15 min, 40 calls)

### Added — plugin hooks

- **`hooks/hooks.json`** (new) — plugin-shipped hooks activating automatically on install; three guards:
  - `SessionStart` → `session_open.sh`: verifies conductor HEAD is not on `agent-*`/`lane-*` branch and cwd is the primary worktree; warns on orphan sub-worktrees.
  - `PreToolUse(Bash)` → `bash_guard.sh`: blocks `git commit` when HEAD is on an agent/lane branch (`permissionDecision: deny`).
  - `PreToolUse(Write|Edit)` → `lock_guard.sh`: warns when `.artifacts/shepherd.lock` or `.shepherd/shepherd.lock` is held by a different session ID.

### Notes for upgraders

- The doctrine extension is **behavioral**, not schema-level — no
  migrations, no config changes, no breaking interface for consumer
  `shepherd.toml` files. Conductors that already honored `conductor-cwd.md`
  inherit Ban 2 + Ban 3 as the same intent, now explicit.
- Subagents (coders, auditors, workers) **may continue to freely inhabit
  worktrees**. The doctrine binds the conductor's session only; this is
  called out explicitly in the "When the rule does not apply" section.
- The session-open verification adds three `git rev-parse` calls. Negligible
  cost; catches drift before it produces silent breakage.
- **Hooks require jq or python3** in the shell environment at hook execution time. Both are standard on macOS and common Linux distributions.

---

## v5.0.4 — 2026-05-05

**v5.0.3 field-feedback batch + ctx production-grade pass + token-budget
pipelines.** Compiled live from the v5.0.3 conductor's working notes during
the axiom v0.3.0-dev.5 sprint
(`~/src/fl03/axiom/.artifacts/docs/shepherd-v503.feedback.md`). Every
addition cites the originating §. Plus operator-driven asks: ctx command
production-grade, multi-step automation pipelines, flag consistency, and
project-agnostic cleanup.

### Added — doctrines

- **`doctrines/worktree-base-drift.md`** *(§1)* — explicit ban on
  `Agent({ isolation: "worktree" })` for sprint coder dispatch. Conductor
  pre-creates worktrees from sprint HEAD via `shctx worktree create-batch`,
  then pastes `[WORKTREE-PATH]` and `[BASE-COMMIT-EXPECTED]` into briefs.
  Eliminates the v5.0.3 axiom dev.5 BASE-DRIFT pattern.
- **`doctrines/worktree-confinement.md`** *(§3)* — ALL coder writes
  (including `.shepherd/ctx/*.md`) MUST land under `[WORKTREE].Path`.
  Writes to sprint root are silently dropped from the cherry-pick;
  documented with the field origin and a worked example.
- **`doctrines/coder-brief-format-shared-artifacts.md`** *(§4)* — when
  multiple coder lanes write to the same shared file, the brief specifies
  Pattern A (line-range partition), Pattern B (footer-append), or
  Pattern C (single-author-per-file). Prevents cherry-pick conflicts.

### Added — references

- **`references/grading-rubric.md`** *(§9)* — explicit weight + numeric
  formula for synthesizing per-concern audit grades into a sprint-level
  grade. Default weights: completeness 0.35, code-quality 0.20,
  dependency-topology 0.20, data-flow 0.15, datastore-state 0.10.
  Overridable via `[gates.audit_weights]` in shepherd.toml.

### Added — context registry

- **`shctx worktree create-batch <lane-id…> [--from=<branch>]`** *(§1)* —
  pre-creates one worktree per lane-id at `.claude/worktrees/agent-<id>`
  rooted at the HEAD of `--from` (default: current branch). Emits
  `[BASE-COMMIT-EXPECTED] <SHA>` for the brief. Idempotent.
- **`shctx doctor [--md|--json]`** — first-class diagnostic / pre-flight:
  required binaries, namespace dir + project.json, schema version +
  pending migrations, lock state (held/stale/free), refresh staleness per
  zone, shepherd.toml locatability. Exit 0 / 1 / 2 (ok / fail / warn).
- **Multi-step pipelines (operator ask):**
  - **`shctx sync [--scope=…|--all]`** — refresh → lint → status.
  - **`shctx ready`** — init → migrate → refresh `--all` → lint → doctor.
  - **`shctx sprint open <branch>`** — lock acquire → refresh `--all` →
    lint → status.
  - **`shctx sprint wave <id> [--all]`** — refresh github+artifacts → lint
    (replaces `auto_refresh = ["on-wave-gate"]`).
  - **`shctx sprint close <branch>`** — close-lane (each known) → handoff
    create → worktree gc → lock release.
  - **`shctx audit`** — read-only validation: lint → doctor → status.
- **`shctx_gh_retry()` helper in `_lib.sh`** *(§8)* — 3× retry with
  exponential backoff for transient `gh` failures (504/502/503/timeout).
  Wired into `refresh-github.sh` + `cmd_close-lane.sh`.
- **`shctx export --all`** — bundles every export kind (canonical-types,
  open-issues, open-prs, recent-releases, drift-risk, mem) to a directory.
- **`shctx mem show <id>` + `shctx mem rm <id>`** — completes the mem CRUD
  surface (was add/list/search/pin/unpin).
- **`shctx lock release --force`** — explicit alias for force-clearing a
  stuck lock (parallel to `lock reap`).
- **Role-tailored `shctx inject`** *(token budget)* — engineer gets the
  full context surface (limit 80); coder gets a `[FILE-SCOPE]`-filtered
  subset (limit 30); auditor gets cross-cutting state only (limit 25).
  `--limit=N` overrides; `--full` removes the cap. Meaningful per-brief
  token reduction without quality compromise.

### Added — flag consistency

- **`--all` is the canonical universal flag** across `refresh`, `search`,
  `style init`, `worktree gc`, `lock release`, `export`. Aliases
  `--scope=all` where applicable; preserves backward compat. The
  inconsistency caller-side (`--all` here, `--scope=all` there) is
  resolved.

### Added — Stage Graph node taxonomy

- (No new node types; `WORKTREE-CREATE-BATCH` is now the conductor-inline
  predecessor of every `WAVE-IMPL` per `worktree-base-drift.md`.)

### Hardened — auditor discipline *(§2)*

- **`agents/auditor.md`** — new hard constraint: auditors verify
  `git rev-parse HEAD` matches the sprint root before invoking any gate
  command. `WORKTREE-DRIFT` halt code added. Every gate finding cites the
  gate's `Finished` or `error:` line verbatim as evidence.
- **`doctrines/auditor-readonly.md`** — adds the WORKTREE-DRIFT halt
  with field-origin attribution.

### Hardened — coder discipline *(§3)*

- **`agents/coder.md`** — new hard prohibition: NEVER write outside the
  worktree, including `.shepherd/ctx/*.md` artifacts. Cite
  `doctrines/worktree-confinement.md`.

### Hardened — SUBTRACT doctrine *(§5)*

- **`doctrines/subtract-dont-add.md`** — LOC-delta measurement scoped to
  `[gates.subtract_paths]` from `shepherd.toml`. Documentation, audit
  artifacts, plans, reports, journals are OUTSIDE scope by construction.
  Default glob is Rust-leaning (`crates/**/*.rs bin/**/*.rs **/*.toml
  **/*.sql`); override per-project for other languages.

### Hardened — pipeline.md

- New § XV-bis: worktree `target/` policy (worktrees DO share parent
  cache; coder no-cargo prohibition stays in force).
- New § XV-ter: `SendMessage` (existing agent) vs `Agent({...})` (new
  spawn) distinction for operator-directed amendments *(§7)*.
- New § XV-quater: shared-context append discipline (cross-ref).

### Compressed — token optimization (operator ask)

- **`SKILL.md` § VII anti-patterns** — collapsed from 18 verbose
  paragraphs to 21 single-line cues with doctrine cross-references.
  Authoritative content lives in the doctrines; the cue list is just
  the conductor's mental index.
- **Role-tailored inject** (above) — delivers the token savings where
  briefs are largest.

### Project-agnostic cleanup

- **`cmd_init.sh`**, **`styles/rust.md`**, **`doctrines/use-mcp-not-cli.md`**
  — replaced residual axiom-specific examples with project-agnostic
  placeholders. Bundled defaults are now neutral; project-specific
  details belong in the consumer's `.shepherd/styles/<lang>.md` and
  `.claude/doctrines/`.
- **`doctrines/conductor-cwd.md` + `gates-restoration.md`** — added
  "Project-agnostic principle:" preamble to each, separating the
  framework-intrinsic rule from its field-origin attribution.
- **Auto-detection** of `.shepherd/` vs `.artifacts/` audited across
  every script: only `_lib.sh` and `cmd_init.sh` reference either path
  literally; all other scripts route through `shctx_artifacts_root()`.
- **`[gates.subtract_paths]`** added to `docs/configuration.md` — gives
  projects an explicit knob for the SUBTRACT scope without baking
  language-specific globs into the framework.

### Tests

- 5 new tests: `test_doctor.sh`, `test_sync.sh`, `test_sprint_pipelines.sh`,
  `test_worktree_create_batch.sh`, `test_flag_aliases.sh`. Suite is now
  27/27 passing on macOS bash 3.2.

### Migration notes

- No new schema migrations — all v5.0.4 features run on the v5.0.3 schema
  (0001–0004). `shctx migrate` is a no-op for v5.0.3 → v5.0.4 upgrades.
- Coder briefs SHOULD now include `[WORKTREE-PATH]` (in addition to
  `[BASE-COMMIT-EXPECTED]` from v5.0.3). Pre-v5.0.4 conductors recording
  the SHA but no path keep working.
- `shctx inject coder --scope=<glob>` is new; old call form
  `shctx inject coder` still works (returns the unfiltered top-30 set).

### Pushed to v5.1+ (intentionally NOT in this patch)

- syn-based Rust symbol parser (drops shell regex)
- Vector embeddings on top of FTS5 for semantic search
- `index_imports` + `index_callers` cross-reference tables
- Hook-based engineer source-code-write filter (currently a doctrine)
- `shctx ctx-merge <file> <wt-1> <wt-2>` automated section-partitioned
  merger for shared `.shepherd/ctx/*.md` files
- Per-worktree `target/` isolation via `CARGO_TARGET_DIR` (currently
  documented in pipeline.md § XV-bis as opt-in via `[env]` block)

---

## v5.0.3 — 2026-05-05

**Field-feedback-driven discipline + tooling.** Compiled live from the v5.0.1
conductor's working notes during the axiom v0.3.0-dev.4 XL rescue sprint
(`~/src/fl03/axiom/.artifacts/docs/shepherd_feedback_v501.md`). Every
addition cites the originating §.

### Added — doctrines

- **`doctrines/conductor-cwd.md`** *(§2.1)* — the conductor never `cd`'s mid-Bash. Use `git -C <path>` and absolute paths instead. Bash's persistent cwd was causing conductor commits to land on worktree branches.
- **`doctrines/gates-restoration.md`** *(§2.4)* — when gates are red, run a conductor-inline `GATES-DISCOVERY` first to capture the FULL latent error inventory, then brief Lane 0 on all errors — not just the engineer-found subset. Cuts the 5–7-iteration hot-fix cascade pattern.

### Added — brief contract

- **`[BASE-COMMIT-EXPECTED]` block** in coder briefs *(§2.3)* — the conductor records `git rev-parse HEAD` of `{sprint_branch}` immediately before dispatch and pastes the SHA into the brief. The coder's new **Step 0.5** verifies and halts with `BASE-DRIFT` on mismatch (catches worktrees branched from `main` instead of the active sprint branch — the v5.0.1 cherry-pick storm).
- New halt code: **`BASE-DRIFT`** (alongside `BRIEF INVALID`, `CONTEXT-INVENTORY STALE`, `DUPLICATION RISK`, `BRIEF-AMENDMENT REQUEST`, `SCOPE OVERFLOW`).

### Added — context registry

- **`shctx search <text>`** *(§3)* — FTS5 fast-path over symbol index + artifact content. `--scope=symbols|artifacts|all`, `--md|--json`, `--limit=N`. Solves the "which crate has the BookSnapshot type?" / "did any close report mention X?" queries that grep returns thousands of false positives for.
- **`shctx close-lane <lane-id> --sprint=<branch> [--issues=#a,#b] [--status=...]`** *(§2.7)* — record a mid-sprint lane closure; auto-resolves carry-forward ledger entries by querying `gh issue view --json state`; emits a markdown patch the conductor commits to the ledger.
- **`shctx worktree list|gc|merge`** *(§4 P3)* — worktree hygiene helpers. `gc --older-than=<hours>` prunes stale `.claude/worktrees/agent-*`. `merge <agent-id> --strategy=theirs|prompt --no-cleanup` cherry-picks a coder's worktree HEAD onto the sprint branch with optional cleanup. Uses `git -C <path>` per `doctrines/conductor-cwd.md` — conductor never leaves sprint root.
- **`v_canonical_types` view tightened** *(§2.2)* — now filters to `kind ∈ {struct, enum, trait, class, interface, type-alias}` AND `visibility = pub`. The previous broad-query semantic moved to the new `v_canonical_symbols` view.
- **`auto_refresh = ["on-wave-gate"]` trigger** *(§2.8)* — fire `shctx refresh --scope=github,artifacts` after every `WAVE-GATE`. Combats stale carry-forward / dedup-ledger drift mid-sprint. Recommended for L/XL sprints.

### Added — schema migrations

- **`0003_canonical_types_filter.sql`** — recreates `v_canonical_types` with kind+visibility filters, adds `v_canonical_symbols` for broad queries, adds `lane_closures` table for the `close-lane` audit trail.
- **`0004_fts_search.sql`** — adds `index_fts_symbols` + `index_fts_artifacts` FTS5 virtual tables with sync triggers, plus a `content` column on `artifacts` so artifact body is searchable. Backfills both FTS tables for projects upgrading from older schemas.

### Added — Stage Graph node taxonomy

- **`GATES-DISCOVERY`** — conductor-inline; predecessor of any `WAVE-IMPL` whose mission is "restore the gates" (typically Wave 0 / Lane 0). Per `doctrines/gates-restoration.md`.
- **`LANE-CLOSE`** — conductor-inline (`shctx close-lane <lane-id>`); fires after each `WAVE-GATE` per lane. Carry-forward auto-resolution.

### Hardened — engineer prohibition

- **`agents/engineer.md` "DO NOT write source code" doctrine substantially stiffened** *(§2.5)*. Field origin: v5.0.1 commit `ffd9dbd7` where the engineer wrote `.rs` to "fix two clippy items". The new wording lists the specific path extensions banned, names the auditor `completeness` grep that catches the violation, and gives the alternative pattern (`BRIEF-AMENDMENT REQUEST` for a hot-fix coder lane). Plus a new "When you spot a bug while meshing" section that walks the discipline.

### Hardened — symbol extractor

- **`refresh-symbols.sh`** *(§2.2)* — now indexes `pub use` re-exports (single, group, and `as Alias` rename forms). `re-export` is a new `kind` value. Multi-line `pub trait Foo: Bar where ...` declarations are picked up via the line carrying the trait name.
- Conductor anti-patterns (15–18) added to `SKILL.md` §VII covering all the discipline shifts above (cwd, broad-sweep, base-drift, stale-ledger).

### Tests

- 4 new tests: `test_search.sh`, `test_close_lane.sh`, `test_canonical_types_filter.sh`, `test_pub_use_re_exports.sh`. Suite is now 22/22 passing on macOS bash 3.2.

### Migration notes

- Run `shctx migrate` once per project on upgrade. 0003 + 0004 apply idempotently. Existing projects' `artifacts.content` starts NULL and populates on next `shctx refresh --scope=artifacts`.
- `[context].auto_refresh` is additive. Add `"on-wave-gate"` to opt in; existing projects without the entry behave unchanged.
- `[BASE-COMMIT-EXPECTED]` becomes mandatory in v5.0.3 briefs. Conductors running pre-v5.0.3 plans should add it manually (the SHA from `git rev-parse HEAD` at dispatch time).

### Pushed to v5.1+ (intentionally NOT in this patch)

- syn-based Rust symbol parser (drops shell regex)
- Vector embeddings on top of FTS5 for semantic search
- `index_imports` + `index_callers` cross-reference tables
- Hook-based engineer source-code-write filter (currently a doctrine; would need user-project hook installation)

---

## v5.0.0 — 2026-05-XX

**MAJOR — adds context registry contract.**

- **DEFAULT CHANGE:** per-project namespace is now `.shepherd/` (auto-detects existing `.artifacts/`; `init --artifacts` opts back in).
- **NEW:** `/shepherd:ctx` command + bundled `shctx` CLI.
- **NEW:** Per-project SQLite registry at `.shepherd/root.db` (or `.artifacts/root.db` for legacy opt-in; schema 0001).
- **NEW:** Doctrine `context-registry.md` (cache vs canonical zones, fall-back contract).
- **NEW:** DEDUP-GATE Layer 2 SQL fast-path (`shctx query dedup-check`); grep remains contract.
- **NEW:** `[DB-CONTEXT]` block in coder briefs (optional in c; mandatory in d).
- **NEW:** `mem` subcommand replaces external `remember` plugin.
- **NEW:** Lock-coordinated autorun + parallel sessions (`.artifacts/shepherd.lock`).
- **NEW:** `shepherd.toml` `[context]`, `[context.refresh]`, `[context.lock]`, `[context.naming]` sections.
- **NEW:** Naming-convention enforcement (`shctx lint`).
- **NEW:** `shctx style <init|show|edit|list>` — per-language project style files at `.artifacts/styles/<lang>.md` (rust/python/typescript/go/shell/sql).
- **NEW:** Schema migration `0002_styles.sql` — `styles` table.
- **NEW:** Conductor mechanically injects `[CODE-STYLE]` block from `.artifacts/styles/<lang>.md` into every coder brief whose `[FILE-SCOPE]` matches a language.
- **NEW:** Doctrine `worker-patterns.md` — main-chat dispatch heuristics for non-code work (issue triage, deploy monitoring, branch cleanup, research, file org).
- **HARDENED:** Engineer brief now enforces seed → `superpowers:brainstorming` → `superpowers:writing-plans` load order; auditor `completeness` verifies trace.
- **HARDENED:** Auditor `completeness` checks `[CODE-STYLE]` presence on every code-touching coder lane.
- Self-host: this repo now scaffolds `.artifacts/` and registers its own design specs.

Migration from v4.2.0: run `shctx init` once; existing markdown artifacts continue to work. DB is optional in milestone (c); becomes contract-mandatory in milestone (d) of the v5.0.0 line.

---

## [4.2.0] — 2026-05-04

The Stage Graph release. Orchestration moves from the conductor's working memory into a declarative DAG the engineer's plan emits. Plus a hard zero-tolerance dedup contract enforced as a conductor-side pre-dispatch gate.

### Added

- **`skills/shepherd/pipeline.md`** — the Stage Graph contract. Defines node taxonomy, edge labels, walk algorithm, and the canonical sprint DAG. Pattern B is now a graph constraint (`parallel_with`); WORKER-IO is auto-batched with WAVE-1-IMPL by graph construction.
- **`skills/shepherd/doctrines/stage-graph.md`** — the principle: every plan emits a Stage Graph; every dispatch is a graph edge; off-graph dispatch is a process violation auditors catch.
- **`skills/shepherd/doctrines/zero-duplicate-tolerance.md`** — three-layer anti-duplication contract. Layer 1: engineer pre-populates `[CONTEXT-INVENTORY]` and `[DO-NOT-DUPLICATE]`. Layer 2 (the primary defense): conductor runs every dedup grep BEFORE the Agent batch fires; hits ≠ expected → dispatch BLOCKED, brief amended to "wire to existing", re-fire. Layer 3: coder-side fallback halt. Includes mechanical `[SKILLS]` auto-attachment per file scope, the `{paths.ctx}/canonical-types.md` workspace catalog contract, and cross-coder coherence rules.
- **`DEDUP-GATE` graph node** — runtime body of the Brief-Validity Checklist; predecessor of every WAVE-IMPL.
- **`CANONICAL-TYPES-REFRESH` worker node** — fires at every dev.0; refreshes `{paths.ctx}/canonical-types.md` so subsequent sprints' Phase 0 starts from a current workspace catalog.
- Stage decomposition hint section (§7-bis) in `references/seed-template.md` — the planter sketches a non-binding partial DAG; the engineer specializes it into the binding `## Stage Graph` plan section.
- Required `## Stage Graph` plan section per `agents/engineer.md` §"plan-quality bar".

### Changed

- **`skills/shepherd/SKILL.md` §III** — references the Stage Graph as the dispatch source-of-truth. Conductor checklists per §1/§2/§3 reformulated as graph-walk operations. Anti-patterns table extended (off-graph dispatch, stale canonical-types catalog, dedup-skip elevated to ZERO-TOLERANCE).
- **`skills/shepherd/flock.md` @coder Required-Skills Matrix** — conductor now MECHANICALLY computes `[SKILLS]` per file scope from `[skills.mandatory]` + `[skills.detection]` + `[skills.by_domain]`. Engineer's suggestions are a SUBSET, never authoritative. Skill-attachment audit at sprint close emits `SKILL-DRIFT` findings.
- **`skills/shepherd/flock.md` Brief-Validity Checklist** — IS the runtime body of the DEDUP-GATE node. Failure on any line BLOCKS dispatch.
- **`skills/shepherd/references/agent-briefs.md` Brief-Validity Checklist** — restructured into brief-shape / skills auto-attachment / anti-duplication pre-flight sections, each enforced before the Agent batch fires.
- **`agents/coder.md` Startup Protocol** — Step 2 now requires reading `{paths.ctx}/canonical-types.md` first; Step 3 (dedup grep) framed as a fallback tripwire (the conductor's pre-flight is the contract, not the coder's halt).
- **`agents/engineer.md`** — plan-quality bar requires `## Stage Graph` section; hard prohibitions extended to forbid omitting the graph.
- **`skills/shepherd/autorun.md`** — loop is "walk graph, then re-walk new graph for next sprint" instead of "remember the per-stage discipline". Cognitive load drops.
- Plugin manifest description updated to surface Stage Graph + DEDUP-GATE.

### Compatibility

Pre-4.2.0 plans without `## Stage Graph` continue to work — the conductor falls back to the §III §1/§2/§3 sequencing in `SKILL.md`. New plans (post-install) MUST emit the graph.

### Why this version

The pre-4.2.0 conductor re-derived dispatch sequencing at every decision point by reading SKILL.md §III + flock.md + the plan in working memory. Cognitive cost was high; failure modes (silent drift, skipped Pattern B, ad-hoc dispatch, **duplicate code re-introduced across sprints**) compounded. v4.2.0 moves orchestration from working memory to declarative artifact: the engineer emits the graph; the conductor walks it; deviation is structurally visible. Plus the DEDUP-GATE makes duplicate-code-shipping mechanically impossible — the conductor blocks the Agent batch before the coder ever sees it.

---

## [4.1.0]

GitHub-leverage release. Planter publishes patch arcs into GH milestone descriptions; sprint seeds remain local. Lane discipline anchored by GH issues. Full-ledger Phase 0 sweep (combats tunnel vision). Carry-forward chronic flagging at ≥ 2 patch crossings.

## [4.0.0]

Initial extracted-and-generalized cut from the v3.2.0 axiom-pinned skill. Closed-flock contract (5 agents: engineer, critic, coder, auditor, worker). Three-section sprint pipeline. Project-agnostic via `.claude/shepherd.toml`. Four commands (`plant`, `start`, `autorun`, `parallel`).

---

## Tagging

After this release lands on `main`:

```bash
git tag -a v4.2.0-shepherd -m "shepherd v4.2.0 — Stage Graph + DEDUP-GATE"
git push origin v4.2.0-shepherd
gh release create v4.2.0-shepherd --notes-from-tag --title "shepherd v4.2.0"
```
