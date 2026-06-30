---
name: spawn
description: |
  The PRIMARY command for substantive sprint work. Spawn teammate-conductor(s) to
  execute a sprint while main chat adopts the root-shepherd profile
  (agents/shepherd.md). Uses the native Agent Teams teammate-spawn (v2.1.178+: no
  setup step, no TeamCreate tool, no env-var or tmux requirement — available across
  CLI / web / remote / cloud entrypoints). Operator-explicit invocation only — refuses
  from teammate sessions (nested spawn forbidden). For a single in-chat sprint with no
  teams, use /shepherd:start (solo).

  v5.1.6 introduces:
    - Root-shepherd tier — main chat adopts agents/shepherd.md (not planter.md);
      planter loads only under /shepherd:plant or when seed work is delegated mid-spawn.
    - Lane-per-conductor fanout (default) — after the plan, root projects it into
      vertical LANES (cohesive slices ACROSS waves) and spawns one teammate-conductor
      PER LANE via Agent Teams; the lane count is constant across waves (never
      per-wave), and a lane's teammate may be refreshed per wave for fresh context.
      Many small focused lanes beat fewer broad ones (doctrines/primitive-axis-binding.md).
    - --scope flag — workload scaling per doctrines/scope-scale-workload.md.
    - INTRO-COMBO-WAVE always-on under spawn — every sprint gets a grounded plan.
    - Teammate-conductor write restrictions — returns structured payloads; root
      materializes artifacts. Engineer/critic dispatch root-tier-exclusive.

  Three flags extend the base behavior (compose orthogonally):
    --scope <value>    sprint | patch | minor | version (default sprint)
                       sprint  = one dev.N (current /shepherd:spawn behavior)
                       patch   = full patch (≡ retired --auto; sequential or parallel)
                       minor   = experimental; operator double-confirm
                       version = experimental; operator double-confirm + resource warning
    --parallel <N>     Fan out N sibling teammates for sprint-level concurrency (only
                       valid for --scope >= patch; ≤ 4 for patch; refused for minor/version
                       in v5.1.6). Within each sprint, lane-per-conductor fanout still
                       applies internally.
    --auto             ALIAS for --scope patch (preserved for operator muscle memory).
    --staged           Two-session overlap: orient / discover NOW, then WAIT for a
                       `seed-ready` signal from a concurrent /shepherd:plant session
                       before authoring the plan. A missing seed is the EXPECTED start
                       state, not a seedless-run trigger. Reuses the SQLite mailbox;
                       opt-in. Full spec: doctrines/staged-handoff.md.
argument-hint: "[ sprint_slug ] [ --scope sprint|patch|minor|version ] [ --parallel <N> | --auto ] [ --staged ]"
allowed-tools: Agent, Bash, Edit, Glob, Grep, Read, Skill, Write, ToolSearch, TaskCreate, TaskGet, TaskList, TaskUpdate, SendMessage, WebFetch, WebSearch
---

# /shepherd:spawn — Teammate-Conductor Dispatch

Spawn a teammate session to run a full sprint pipeline while this main-chat session
stays lean as the ambient planter and babysitter. The teammate boots with the conductor
profile pre-loaded, invokes `/shepherd:start` against the inherited sprint scope, and
surfaces hard stops back to you through a structured escalation channel. Main chat
monitors heartbeats, responds to escalations, owns all git operations, and executes
the post-sprint merge sequence.

> **Mechanical contract** — file paths, polling cadence, hook events, lock semantics,
> multiplex triage, halt-code → action map, heartbeat format — lives in
> `skills/shepherd/doctrines/spawn-escalation.md`. This command does NOT re-state those
> mechanics; it cites the doctrine and stays focused on the operator-visible contract.

---

## § Smooth path (happy-path walkthrough)

A single-sprint spawn on a green project, no flags, no escalations:

```
[1]  operator types:  /shepherd:spawn
[2]  preflight        Check 1 (teams available)      → advisory (no hard gate)
                      Check 2 (Claude version)       → advisory (no hard gate)
                      Check 3 (no active team)       → OK
                      Check 4 (shepherd.toml)        → OK
                      (Check 5 skipped — no --parallel / --auto)
[3]  main chat        adopts root-shepherd profile (agents/shepherd.md)
[4]  root             INTRO-COMBO-WAVE — dispatches in parallel:
                        • @discovery × N (gather sprint ground-truth: repo state,
                          open issues, prior-close artifacts, dependency graph)
                        • @auditor × 2 (intro mode: regression audit + carry-forward
                          + freshness certification of discovered context)
                      ↳ wave completes → sprint context is CERTIFIED current
[5]  root             materializes INTRO context artifacts from wave payloads
[6]  root             dispatches @engineer (plan authorship) → @critic (plan gate)
                        → plan-approval gate passes
[7]  root             projects approved plan into vertical LANES
                      builds per-lane teammate boot prompts (seed + certified context
                      + handoff + carry-forwards + shepherd.toml snapshot)
[8]  root             pre-creates all lane worktrees (git worktree add) and emits
                      [WORKTREE-READY] BEFORE spawning teammates (#97)
[9]  root             issues the natural-language teammate-spawn instruction (referencing
                      the shepherd:conductor subagent definition, model: sonnet)
                      → teammate sessions created
[10] root             ENTERS FOCUS-LOOP (wake → act → probe; see [10a] below)
[10a] root            confirms liveness (shctx teammate liveness until each lane
                      active/heartbeating); scaffolds wave-gate tasks; iterates
                      coordinate cycle until CLOSE-FINALIZE
[11] teammate         loads agents/conductor.md (TEAMMATE mode), fires
                      /shepherd:start --teammate; walks lane micro-Stage-Graph
[12] teammate         at lane close: SendMessage(to: lead, halt_code: null,
                      phase: "body-wave-N-lane-{id}") → root commits wave via
                      TaskCompleted hook
[13] teammate         at CLOSE-FINALIZE: emits CONDUCTOR CLOSE REPORT, idles
[14] root             verifies close report → rebase-merge → cuts next dev branch
                      → updates carry-forward ledger → runs cleanup stewardship
[15] root             emits PLANTER REPORT and hands back to the operator
```

> **Multi-sprint scopes (`--scope patch`/`--auto`/`--parallel`):** the INTRO-COMBO-WAVE
> fires **fresh per sprint** — discovery + intro-auditors re-run from the new baseline
> at the top of each iteration. No sprint inherits a stale prior wave result.

For `--parallel <N>` the smooth path forks at [9]: N teammates spawn into N
worktrees after a collision pre-check; root babysits all N in parallel;
merges land in dev-order. For `--auto` the loop wraps [4]–[14] per sprint with
root-authored inter-sprint handoffs between iterations.

Escalations interrupt this path — consult `skills/shepherd/doctrines/spawn-escalation.md`
for the full halt → resume contract.

---

## § Platform compatibility

**Status (v2.1.178+):** The conductor-as-teammate path works **without any special
setup**. Spawning a teammate no longer needs a setup step (no `TeamCreate` tool — removed
v2.1.178), and Agent Teams is available **across Claude Code entrypoints — CLI, web,
remote, and cloud-container sessions included**. A spawned teammate boots as a full Claude
Code session with the `Agent` tool, so its `/shepherd:start --teammate` can dispatch the
flock exactly as main chat does.

- **No env-var step required to spawn.** Where a build still gates Agent Teams behind
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, set it once; otherwise the feature is available by
  default. Shepherd does NOT hard-refuse on the flag (see Preflight Check 1).
- **No tmux required.** `tmux`/iTerm2 split panes are an **optional display mode** for live
  per-teammate observability, NOT a prerequisite. In-process (the default, any terminal)
  and remote/cloud sessions spawn and dispatch teammates fine. (The historical in-process
  Agent-tool gap, `anthropics/claude-code#31977`, no longer blocks the flow.)

| Display mode | Conductor-as-teammate | Flock dispatch inside teammate | Notes |
|---|---|---|---|
| native / in-process (default) | Works | Available | no setup; any terminal; web/remote/cloud |
| `tmux` / iTerm2 split panes    | Works | Available | optional — adds live per-pane observability |

Preflight does NOT gate on `teammateMode` or tmux — the operator chooses the display mode;
the spawn capability does not depend on it.

---

## § Preflight

Run every check before issuing the teammate-spawn instruction. Refuse with a clear error if any check fails.

### Check 0 — Operator-only invocation (v5.1.6+)

`/shepherd:spawn` is **operator-explicit-only**. Nested spawn from within a teammate
session is forbidden.

**PRIMARY guarantee is structural, not signal-based.** The Agent Teams platform forbids
a teammate from creating a team at all — the lead is fixed, no nested teams, one team at
a time. A non-lead session cannot spawn a team, so a nested spawn cannot occur even
if this check were absent. shepherd's operator-explicit-only rule is therefore consistent
with — and largely redundant to — this platform guarantee. (Source:
code.claude.com/docs/en/agent-teams.)

**Best-effort secondary signals** (defense in depth; ANY positive → refuse). Note that a
spawned teammate session receives **NO identity environment variable** — only `CLAUDECODE`
and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` are set in its env (per
`anthropics/claude-code#35447`, closed not-planned; GitHub issue #93, live-docs-verified
2026-05-29). Any legacy-convention env vars below read **empty** on the live platform — they
are retained only as a cheap belt-and-suspenders check, never as the load-bearing signal:

| # | Signal | Source | Note |
|---|---|---|---|
| 1 | Current session `cwd` is under a shepherd `.worktrees/` path | filesystem | reliable shepherd-controlled signal |
| 2 | Current session's system prompt addendum contains `INVOCATION-CONTEXT.dispatcher: teammate-conductor` | boot prompt | reliable shepherd-controlled signal |
| 3 | `$CLAUDE_AGENT_TEAMMATE_NAME` / `$CLAUDE_PROJECT_SESSION_TYPE` / `$CLAUDE_AGENT_PARENT_SESSION_ID` non-empty | legacy env convention | reads EMPTY on live platform (#93); do NOT rely on it |

If ANY positive (or, in practice, if the platform rejects the teammate spawn because you are
not a lead):
```
/shepherd:spawn — REFUSED: nested spawn forbidden.

Teammate-conductors cannot spawn teammates. The Agent Teams platform forbids a
non-lead from creating a team (lead is fixed; no nested teams; one team at a time),
so teammate spawning is structurally unavailable to you, and shepherd discipline forbids
out-of-tier dispatch (per doctrines/dispatch-tier-separation.md).

If you need plan amendment or scope expansion, surface the request to the root
shepherd via SendMessage(to: lead, halt_code: PLAN-AUTHORSHIP-REQUEST) instead.

If you are the operator and this error fires unexpectedly, confirm your session is a
clean main-chat session (not running under a shepherd .worktrees/ path) and re-invoke.
```

This check is the FIRST gate. It runs before any other preflight.

### Check 1 — Agent Teams availability (ADVISORY, not a hard gate)

Agent Teams no longer requires a setup step and is available across Claude Code
entrypoints (web / remote / cloud-container included). **Do NOT hard-refuse spawn on the
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` flag** — many builds enable teams by default, and
the flag's absence is no longer evidence the feature is off.

```bash
echo "${CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS}"   # advisory only
```

- Set (`true`/`1`) → confirmed; proceed.
- Empty → emit the advisory below and **proceed anyway**. The real authority is whether the
  teammate-spawn succeeds at runtime; if the platform actually rejects it (e.g. a build that
  still gates teams behind the flag), surface that platform error and tell the operator to
  set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true` in `~/.claude/settings.json` `env.*` and
  re-invoke. Do not pre-emptively refuse.

```
[ADVISORY] CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS is not set. Agent Teams is typically
available without it (v2.1.178+). Proceeding; if the runtime rejects the teammate spawn,
set the flag in ~/.claude/settings.json (env.*) and re-invoke /shepherd:spawn.
```

### Check 2 — Claude Code version (ADVISORY, not a hard gate)

```bash
claude --version   # advisory only
```

Agent Teams (and the no-setup teammate-spawn, v2.1.178) ship in current Claude Code; the
old v2.1.32 floor is historical. Do NOT hard-refuse on version — note the detected version
and proceed. If a genuinely ancient build lacks the teammate-spawn, the runtime surfaces
that directly; act on the real signal, not a pre-emptive version gate.

### Check 3 — No active team (one-team-per-lead limit)

```bash
ls ~/.claude/teams/ 2>/dev/null
```

If non-empty with a `config.json` carrying `members[]`, an active team is already
running. Per D-API §11: a lead can only manage one team at a time. Refuse and direct
the operator to either complete the prior sprint's hand-back, or inspect
`~/.claude/teams/` and clear stale config after confirmation.

### Check 4 — shepherd.toml (scaffold-then-proceed)

```bash
ls .claude/shepherd.toml 2>/dev/null || ls .local.toml 2>/dev/null
```

If missing, **scaffold then proceed** (v6.1.5 #15): run `shctx config init` to write
`.claude/shepherd.toml` from the bundled minimal template (idempotent; derives
`[project].name` + `[gates]` from the repo's build manifest, realigns `[paths]` to the
active namespace), emit a one-line `[CONFIG] scaffolded .claude/shepherd.toml` notice,
and PROCEED. Non-blocking — root is action-biased (`doctrines/operator-signaling.md`);
do NOT stop for confirmation. The operator can refine `[branching]`/`[gates]` later.

### Check 5 — Flag-specific preflight

**For `--parallel <N>`:**

1. **Collision pre-check (HARD-STOP).** Read `file_scope.exclusive` from each of N
   seeds. Any path claimed by >1 sprint is a collision. Also flag shared build-manifest
   paths (`Cargo.toml`, `package.json`, `pyproject.toml`, `go.mod`, `*.lock`, `*.sum`,
   `build.gradle`, or anything in `[project].build_manifest_paths`). Surface ALL
   collisions in one block:
   ```
   [COLLISION REPORT]
   path: src/foo/bar.rs
     claimed by: v515-dev1 (exclusive), v515-dev2 (exclusive)

   Re-scope the colliding seeds before retrying /shepherd:spawn --parallel.
   ```
   Operator must amend the seeds; planter does not auto-resolve.
2. **N within bounds (HARD-STOP).** N must be 2..`[spawn].max_parallel` — resolve
   the cap via `shctx config get max_parallel 4` (default **4**, the historical
   hard cap; v6.1.5 #10 makes it configurable for rate-limited plans). N=1 is just
   base spawn; N above the cap saturates the lead's `TeammateIdle` handler.
3. **N seeds available.** Exactly N `{paths.plans}/{sprint_slug}.seed.md` files
   must exist. Missing → hard stop; operator runs `/shepherd:plant` for the gap.
4. **No dev-order cycle.** If `sprint_dependencies` contains a cycle, the merge
   gate would deadlock — refuse.

**For `--auto`** (aliased to `--scope patch` in v5.1.6+):

1. **Patch boundary detection (HARD-STOP).** Read `shepherd.toml [branching]` to
   enumerate dev.N branches. Identify `dev.LAST` (precedence: `[version].dev_total`
   → seed count → operator prompt). If undeterminable, prompt:
   ```
   [PROMPT] /shepherd:spawn --scope patch: Cannot determine the last dev sprint.
   How many dev sprints does this patch contain? (current: dev.{N})
   ```
   Operator input is mandatory before the loop begins.
2. **Min-grade configured.** `[autorun].min_grade` must be set in `shepherd.toml`.
   If absent, default to `B` and warn.

### Check 6 — Scope sprint enumeration (v5.1.6+)

For every `--scope` value, enumerate the concrete sprint list before any spawn. Reads
seeds from `{paths.plans}/` and verifies presence:

```
[SCOPE ENUMERATION]
Scope: {scope}
Patch boundary: dev.0..dev.{LAST}
Concrete sprint list:
  - v{X}.{Y}.{Z}-dev.0  → {paths.plans}/v{XYZ}-dev0.seed.md       [seed: present | MISSING]
  - v{X}.{Y}.{Z}-dev.1  → {paths.plans}/v{XYZ}-dev1.seed.md       [seed: present]
  - ...

Total sprints: {N}
Missing seeds: {M}
```

For multi-sprint walks (this enumeration runs for `--scope patch|minor|version`), a
missing seed REFUSES the spawn — direct the operator to run `/shepherd:plant
{sprint_slug}` for each gap. Per `doctrines/scope-scale-workload.md §III`. (Seeds are
load-bearing here: the walk plan and `--parallel` collision check read them. A single
`--scope sprint` spawn is the inline-plant case — its `SEED-AUTHOR` node plants a missing
seed in-session rather than refusing (see Hard-stop #2 and
`doctrines/operator-signaling.md §"Seed is recommended, not required"`).)

### Check 7 — Scope confirmation for minor/version (v5.1.6+)

For `--scope minor`: require operator to type the literal string `confirm minor`
(case-insensitive, exact phrase). Refuse otherwise.

For `--scope version`: surface the resource-estimate warning block AND require
operator to type `confirm version`:

```
/shepherd:spawn --scope version: ESTIMATED 1000-sprint walk.

This will consume:
  - Token budget: ~$N estimated (based on prior-sprint averages)
  - Wall time: ~M days estimated
  - GitHub API rate budget: ~K calls

This is experimental in v5.1.6 — single-minor walks have been validated;
cross-minor walks are deferred. Refuse will route you to a less ambitious scope.

Confirm by typing the exact phrase: confirm version
```

Refuse if confirmation absent.

### Check 8 — Resource estimate (info-only, always surfaced)

Always emit before spawning:

```
[RESOURCE ESTIMATE]
Sprints: {N}
Estimated wall time: ~{N × avg_sprint_minutes} minutes
Estimated GitHub API calls: ~{N × avg_api_per_sprint}
Worktree count peak: {parallel_N} concurrent worktrees
```

Estimates read `shctx adapt priors --metrics`. With measured history (`n>0`) use the
real `avg_sprint_minutes` / `avg_api_per_sprint` / `avg_lane_count` from `sprint_metrics`,
and label the block `(from priors: N sprints)`. With an empty store, fall back to the
conservative static defaults (avg_sprint_minutes=90, avg_api_per_sprint=200) and label it
`(defaults — no priors yet)`. The second sprint's estimate therefore provably differs from
the cold-start default (#94). Per `doctrines/adaptation-loop.md §V`.

**Cache-TTL recommendation (v6.0.5).** For `--scope >= patch` and long `--auto` loops,
surface a one-line nudge to set **`ENABLE_PROMPT_CACHING_1H=1`** (1-hour prompt-cache
TTL). A multi-wave run outlives the 5-minute default between waves, so without it the
cached brief/system prefixes expire and re-bill at full input rate. Claude
subscriptions request 1h automatically; API-key / Bedrock / Vertex / Foundry need the
flag. Per `doctrines/cache-telemetry.md` + `docs/configuration.md §[spawn]`.

---

## § --scope flag (v5.1.6+)

`--scope` declares workload scale. Default: `sprint`. Full semantics in
`doctrines/scope-scale-workload.md`.

| Value | Sprint count | Behavior |
|---|---|---|
| `sprint` (default) | 1 | One `dev.N`. Lane-per-conductor fanout within the sprint's waves. |
| `patch` | ~sprints_per_patch (default 10) | Full patch dev.0..dev.LAST. Equivalent to retired `--auto`. |
| `minor` | ~patches_per_minor × sprints_per_patch | Experimental. Requires `confirm minor` phrase. |
| `version` | ~minors × patches × sprints | Experimental. Requires `confirm version` phrase + resource warning. |

Composition with `--parallel <N>`:

- `--scope sprint --parallel <N>`: N concurrent file-disjoint sprints from current patch (the v5.1.5 model). Each sprint internally uses lane-per-conductor.
- `--scope patch --parallel <N>`: N concurrent sprints from the patch's pool. Each sprint internally uses lane-per-conductor.
- `--scope minor` / `--scope version` + `--parallel >1`: REFUSED in v5.1.6 (cross-patch parallel not validated).

Within EVERY sprint (regardless of scope/parallel), the engineer's post-plan **lane projection** (the vertical slice of the `waves × steps` plan — `doctrines/primitive-axis-binding.md`) determines how many teammate-conductors root spawns: **one per lane** (the lane count, constant across waves — NOT a per-wave count; a lane's teammate may be refreshed per wave for fresh context, which is not a new lane). This is the implicit fanout; no flag controls it (the plan does).

`--auto` is preserved as a stable alias for `--scope patch`. Both forms work; `--scope patch` is canonical.

---

## § Adopt the root-shepherd profile (v5.1.6+)

Main chat (this session) becomes the **root shepherd** for the lifetime of the spawn.

1. Read `${CLAUDE_PLUGIN_ROOT}/agents/shepherd.md` (full file).
2. Adopt as system-prompt addendum.
3. Cite mandatory doctrines:
   - `doctrines/root-shepherd-orchestration.md` (root tier behavioral contract)
   - `doctrines/dispatch-tier-separation.md` (who-can-dispatch-whom matrix)
   - `doctrines/scope-scale-workload.md` (--scope semantics)

**Two-meta-loading (shepherd + planter):** if `agents/planter.md` is already loaded (operator ran `/shepherd:plant` earlier in this session), the shepherd profile **augments** rather than replaces. Per `doctrines/root-shepherd-orchestration.md §V`:
- Outer frame: shepherd (this profile) — owns engineer/critic, teammate coordination, artifact materialization.
- Inner frame: planter — seed authorship, mesh writing, cleanup stewardship.

The shepherd profile delegates seed work to planter mode inline when needed (mid-spawn amendments). On spawn close, planter regains its primary write authority for cleanup stewardship.

> `agents/shepherd.md` frontmatter is `model: inherit`. If this session is Sonnet and the operator intends ultra-parallel spawn coordination, recommend switching to Opus now (the engineer + critic dispatched FROM shepherd are individually pinned to Opus + Sonnet, so the root tier's own reasoning model is the bottleneck for coordination quality).

---

## § Build the teammate prompt

Construct the teammate's boot prompt before issuing the teammate-spawn instruction. The
prompt carries all inherited context the teammate needs without re-asking main chat, and
is supplied as the teammate's instructions inside that instruction.

### Required context block (v5.1.6+ — lane-per-conductor model)

```
You are a spawned teammate-conductor for the shepherd framework.

Your main chat (the lead session) is the root shepherd. It owns engineer/critic
dispatch, materializes your returned payloads as artifacts, runs all git operations,
and executes the post-sprint merge sequence. You are a wave-executor (or
lane-executor under lane-per-conductor fanout) reporting up.

ROOT-SESSION-NAME: shepherd-root @ {main_chat_session_id}

INVOCATION-CONTEXT:
  dispatcher: teammate-conductor
  spawn_session: {team_id}
  scope: {sprint|patch|minor|version}
  fanout_mode: {lane|sprint}            # lane = lane-per-conductor (default); sprint = scope>sprint concurrent sprints
  lane_index: {i_of_L_w}                # lane index within its wave (lane mode only)
  wave_index: {w_of_W}                  # wave index within plan (lane mode only)
  parallel_index: {i_of_N}              # sprint-fanout index (sprint mode only)
  peer_teammate_names: [list]           # sibling teammates in this wave for peer SendMessage

IDENTITY
  Role: conductor (TEAMMATE MODE)
  Profile: ${CLAUDE_PLUGIN_ROOT}/agents/conductor.md  (load IMMEDIATELY at Step 0; detect TEAMMATE mode via the INVOCATION-CONTEXT above per `agents/conductor.md §Conductor modes`. Run Step T0 §Verify invocation context (commands/start.md) — all four checks MUST pass before any dispatch. Hard prohibitions in TEAMMATE mode (per `agents/conductor.md §Hard prohibitions #13–#20` + the HARD PROHIBITIONS block below) are BINDING.)
  Escalation channel: skills/shepherd/doctrines/spawn-escalation.md
  Tier-separation doctrine: skills/shepherd/doctrines/dispatch-tier-separation.md

INHERITED CONTEXT
  CLAUDE.md path:          {project_claude_md_path}
  Active seed path:        {paths.plans}/{sprint_slug}.seed.md
  Active plan path:        {paths.plans}/{sprint_slug}.plan.md
  Your assigned lane:      {lane_id from plan}  (lane mode only)
  Lane brief slice:        {paste lane's seven-bracketed section + steps}
  Prior close handoff:     {paths.docs}/{prior_handoff_filename}
  Carry-forward GH issues: {comma-separated #NNN from handoff}
  Worktree path:           {abs_path}/.worktrees/{sprint_slug}-{lane_id}
  worktree_status:         pre-created   # root created this before you booted (#97); do NOT git worktree add
  shepherd.toml snapshot:  inline below

--- shepherd.toml snapshot ---
{paste full .claude/shepherd.toml content here}
--- end snapshot ---

FIRST ACTION
  Invoke /shepherd:start --teammate. (v5.1.6+) Do this on your FIRST turn,
  immediately, WITHOUT waiting for a kickoff message from root — your lane
  brief below IS the instruction to begin (v6.0.5,
  doctrines/coordinate-active-drive.md §III). Idling to be told to start is the
  teammate side of the dispatch-boundary deadlock.

  The --teammate flag signals lane-execute mode:
    - Skip Phase 0 mesh / INTRO-COMBO-WAVE / @engineer / @critic (root already did those).
    - Load agents/conductor.md and self-detect TEAMMATE mode.
    - Read the lane brief from this INHERITED CONTEXT block.
    - WORKFLOW SELF-CHECK (once, at lane start): is the token `Workflow` in your visible
      tool list? NEVER ToolSearch for it — that returns nothing by design and is the
      WORKFLOW-SELFCHECK-TOOLSEARCH anti-pattern. Record `workflow_tool: present|absent`
      in your first WAVE-COMPLETE. (doctrines/workflow-tool-self-check.md)
    - Walk lane micro-Stage-Graph: DEDUP-GATE → IMPL (@coder for lane scope) →
      FLOCK-OUTPUT REVIEW → LANE-CLOSE. FLOCK-OUTPUT REVIEW (mandatory, #167): a
      `@auditor` in `mode: wave-review` returns `review_verdict: PASS|REDO` against the
      four-item checklist; emit WAVE-COMPLETE only on PASS, force the named author to
      redo on REDO (≤3 iterations → `REDO-CAP-EXCEEDED`). Never forward a coder's
      self-gate-green claim. (doctrines/flock-output-review.md)
    - For EACH gate-free agent fan-out segment in your lane (e.g. WAVE-IMPL coders,
      lane AUDIT): IF `workflow_tool: present`, run `shctx graph compile
      --segment=<entry-node> --verify`, execute the emitted `<seg>.workflow.js`
      out-of-context, then `shctx graph mark <nodes>` — this is YOUR benefit (clean
      context + ≤16 background agents), not a tax. Fall back to an in-context `Agent(...)`
      batch ONLY if the runtime fails. IF `workflow_tool: absent` (web/remote, #146), run
      the segment as one in-context `Agent(...)` batch — the correct degrade path.
      Do NOT hand-roll in-context Agent step fan-out where the tool is present.
      (doctrines/workflow-compile-down.md + workflow-tool-self-check.md + dispatch-cascade.md §IV-bis)
    - Surface WAVE-COMPLETE via SendMessage (include `review_verdict: PASS` +
      `reviewer`, and the `workflow_tool` field). A WAVE-COMPLETE missing the review
      evidence is refused by root as `DISPATCH-CONTRACT-VIOLATION` (#167).

  Do NOT invoke /shepherd:start without --teammate — that triggers SOLO mode
  full-pipeline behavior, which is wrong for a teammate (it would re-engineer the plan,
  re-critic, etc.). The lane brief above is your complete instruction set; --teammate
  binds you to it.

ESCALATION RULES — summary; full contract at spawn-escalation doctrine
  On any Halt code from agents/conductor.md §Halt codes:
    1. Stop the walk at the current node.
    2. Write the escalation payload to
         .artifacts/escalations/{sprint_slug}/{ISO-timestamp}-{role}.md
       (schema in spawn-escalation §III).
    3. Call SendMessage(to: lead) with the same payload.
    4. Do NOT proceed until you receive a resume reply.
    5. Heartbeat (v6.0.3 — #98):
       a. SendMessage a one-line status at EVERY major phase boundary — even when
          blocked on a background task (e.g. a long cargo test).
       b. If you go idle WITHOUT having sent WAVE-COMPLETE, then on your next wake
          SendMessage(to: lead) a status within 1 turn carrying
          {phase, last_node, in_flight_task}. Canonical rule: spawn-escalation §V
          "Idle-without-WAVE-COMPLETE".

HARD PROHIBITIONS WHILE SPAWNED (v6.0.0 — each tied to a halt code)
  Each prohibition is BINDING. If you find yourself constructing the
  forbidden call, REFUSE and SendMessage(to: lead, halt_code: <code>,
  blocking: true). Full contract: doctrines/dispatch-tier-separation.md
  §IV-bis.
  - MUST REFUSE @engineer dispatch.
      halt_code: WRONG-TIER-DISPATCH  (escalate PLAN-AUTHORSHIP-REQUEST)
  - MUST REFUSE @critic dispatch.
      halt_code: WRONG-TIER-DISPATCH  (escalate PLAN-GATE-REQUEST)
  - MUST REFUSE every flock dispatch missing `subagent_type:
    "shepherd:<role>"` or set to `general-purpose` / `Explore` / `Chat`.
      halt_code: DISPATCH-MISSING-SUBAGENT-TYPE
  - MUST REFUSE every flock dispatch with `subagent_type` outside the
    closed-flock-six (no specialist clearance per
    doctrines/specialist-dispatch.md).
      halt_code: DISPATCH-OFF-FLOCK
  - MUST NOT attempt to spawn teammates — you are not a lead.
    Teammate spawning is lead-only and nested teams are platform-forbidden
    and structurally impossible (the platform rejects a non-lead's
    team-create). Your dispatches are subagents only (`@coder`/
    `@auditor`/`@worker`/`@discovery` for your lane) via
    `Agent`/`Task` — a DISJOINT tool family from teammate spawning.
      halt_code: TEAMMATE-NESTING-ATTEMPT
  - MUST REFUSE writing artifact files (plans, reports, handoffs, close
    docs, audit reports). Return structured payloads via SendMessage;
    root materializes. Edit/Write authority is restricted to worktree-
    local questions.md and to your dispatched @coder's writes within its
    own scope.
      halt_code: TEAMMATE-ARTIFACT-WRITE
  - MUST REFUSE git commit / push / branch -d / rebase / worktree add /
    worktree remove. Git is root's exclusive domain. See
    agents/conductor.md §Side-effect boundary (TEAMMATE mode table).
      halt_code: TEAMMATE-GIT-WRITE
  - MUST REFUSE acquiring or releasing .artifacts/shepherd.lock.
      halt_code: TEAMMATE-LOCK-ATTEMPT
  - MUST REFUSE spawning further teammates or invoking /shepherd:spawn.
      halt_code: TEAMMATE-NESTING-ATTEMPT (same as above)
  - MUST REFUSE pushing to any remote branch not owned by the active
    sprint (and even that push belongs to root).
      halt_code: TEAMMATE-GIT-WRITE

## Cargo discipline (binding)

- `--frozen` on EVERY cargo invocation. No exceptions.
- `CARGO_TARGET_DIR=target/.lanes/<your-lane-slug>` on EVERY cargo invocation
  (yours + every coder/worker subagent you dispatch).
- Cargo gates SERIAL only (per `doctrines/cargo-sequential-gates.md`).
- `cargo fix` FORBIDDEN.

Your lane-slug is `<derived from teammate_name>`.

WAVE-BOUNDARY COMMIT PROTOCOL
  At lane completion (LANE-CLOSE):
    1. SendMessage(to: lead) wave-complete payload:
         {phase: "body-wave-N-lane-{lane_id}", halt_code: null, blocking: false,
          context_files: ["<lane-output-summary-path>"],
          loc_delta: {add: N, del: M},
          acceptance_results: {<grep>: <count>, ...}}
    2. TaskCompleted fires automatically on lane-scope task completion.
  Root shepherd commits your lane's work after ALL lanes in your wave have
  closed (per dev-order or peer-order merge gate; see spawn-escalation §VI).

  WAVE-GATE MECHANICAL DEPENDENCY (v6.0.3 — #100):
    Root TaskCreates a "wave-{N}-gate-{sprint_slug}" marker per wave boundary at
    spawn. Each lane's wave-(N+1) IMPL task is then TaskUpdate'd with
    addBlockedBy:["<gate task id>"] (addBlockedBy is a TaskUpdate field, NOT a
    TaskCreate arg). A task with unresolved blockedBy CANNOT be claimed, so no lane
    starts wave N+1 until root releases the gate via
    TaskUpdate(taskId:"<gate>", status:"completed") after the wave-N gate passes.
    Do NOT begin a next-wave step whose task is still blocked.

PEER COMMUNICATION (where supported by platform)
  Sibling teammates in the same wave are listed in INVOCATION-CONTEXT.peer_teammate_names.
  You MAY SendMessage(to: peer_name) for:
    - Wave-internal status (your lane done; informing peer waiting on your symbol).
    - Cross-lane discovery sharing (read-only mesh applicable to a sibling).
    - Joint dispute pre-surface (siblings spot conflicting interpretations).
  You MUST NOT use peer messaging for:
    - Plan amendments (root only).
    - Critic gating (root only).
    - Source-code conflict resolution (worktrees are file-disjoint by design).

TEAMMATE IDENTITY
  Name: shepherd-{lane|parallel|auto}-{sprint_slug}[-{lane_id}]
  Session transcript: ~/.claude/projects/<project-path>/<session-uuid>.jsonl
```

### Dynamic field resolution

| Token | Source |
|---|---|
| `{project_claude_md_path}` | `pwd`/CLAUDE.md (absolute) |
| `{paths.plans}/{sprint_slug}.seed.md` | `shepherd.toml [paths]` + sprint detect |
| `{paths.docs}/{prior_handoff_filename}` | `ls -t {paths.docs}/*-close-handoff.md \| head -1` |
| `{carry-forward GH issues}` | handoff doc's carry-forward section |
| `shepherd.toml snapshot` | full contents of `.claude/shepherd.toml` |
| `{sprint_slug}` | `shepherd.toml [branching].sprint_branch_pattern` + current dev.N |

---

### Pre-spawn worktree creation (v6.0.3 — #97)

Root MUST create every lane worktree on disk BEFORE spawning teammates. Path +
branch are deterministic from `lane_id`:

    for each lane:  git worktree add .worktrees/{sprint_slug}-{lane_id} {sprint_branch}
    git worktree list      # verify every lane worktree exists

Emit a `[WORKTREE-READY]` block (lane → worktree path). The teammate-spawn is GATED on it:
it MUST NOT fire until all lane worktrees exist. A teammate never creates its own
worktree — that is a `TEAMMATE-GIT-WRITE` violation. Eliminates the boot-time
`ANOMALY: worktree missing` round-trip.

---

## § Spawn dispatch

The lead session spawns teammates via the **native teammate-spawn** — a
**natural-language instruction** to spawn one teammate per lane, each referencing the
**`shepherd:conductor` subagent definition** as its agent type. The team forms
automatically when the first teammate is spawned; the lead↔teammate channel after spawn is
**`SendMessage`** (plus the shared task list).

> **PLATFORM CHANGE — `TeamCreate`/`TeamDelete` were REMOVED in Claude Code v2.1.178.**
> Do NOT call a `TeamCreate` tool — it does not exist. Spawning a teammate no longer needs a
> setup step (no team to "create" or name first), and the team is cleaned up automatically on
> session exit (no `TeamDelete`). Just issue the spawn instruction below; the runtime forms
> the team. (Source: code.claude.com/docs/en/agent-teams, v2.1.178 note.)

```
Spawn instruction (natural language), e.g.:

  "Spawn one teammate per lane to run sprint {sprint_slug}, each using the
   shepherd:conductor agent type, model: sonnet. Name them
   shepherd-conductor-{sprint_slug}[-{lane_id}]. Give each teammate the boot/lane
   context below (from § Build the teammate prompt) as its instructions. Each
   teammate BEGINS ITS LANE IMMEDIATELY upon spawn (its first action is
   /shepherd:start --teammate) — it does NOT wait for a further go-signal."
```

> **Kickoff is part of the dispatch (v6.0.5).** A teammate that waits for a
> "begin" message while the root waits for a teammate event is a mutual-wait
> deadlock that looks exactly like the passive-wait pause. The instruction above
> states the teammate self-starts; the root then **confirms liveness**
> (`shctx teammate liveness` until each lane is `active`/heartbeating) BEFORE it
> considers the dispatch complete. A lane still `booting` with no heartbeat is a
> probe candidate, not a working lane. Per `doctrines/coordinate-active-drive.md §III`.

Each spawned teammate is created **from the `shepherd:conductor` subagent definition**
(`agents/conductor.md`), so it inherits that definition's `tools:` and `model`. The
per-teammate boot/lane context (INVOCATION-CONTEXT, INHERITED CONTEXT, lane brief) is
supplied per § Build the teammate prompt and carried in the teammate-spawn instruction.

### Model pin requirement (mandatory — v6.0.9)

**Every teammate MUST be spawned with an explicit `model: sonnet` pin in the
teammate-spawn instruction.** Do NOT rely on the `shepherd:conductor` subagent
definition's `model: sonnet` frontmatter to propagate — empirically, teammates
have inherited the lead session's model instead of the subagent definition's
(v6.0.9 regression: an Opus 4.8 lead session caused every teammate to run at
Opus 4.8, multiplying costs by the lane count). The intended conductor model is
`sonnet` per `agents/conductor.md` frontmatter; enforce it explicitly.

**Include the pin in the natural-language instruction**, e.g.:

```
"Create a team to run sprint {sprint_slug}. Spawn one teammate per lane named
 shepherd-conductor-{sprint_slug}[-{lane_id}], each of agent type
 shepherd:conductor, model: sonnet. ..."
```

**PRE-SPAWN COST ADVISORY.** Check the lead session's active model before
spawning teammates:

```bash
# If the lead session is pinned to an Opus-tier model:
echo "[COST ADVISORY] Lead session is Opus. Without an explicit 'model: sonnet' pin
in the spawn instruction, every teammate may inherit Opus 4.8 (cost ↑↑↑ — one
lane × {N} lanes × Opus token rates). Verify the pin is present before proceeding,
or provide an explicit operator override confirming Opus is intentional."
```

If the operator explicitly authorizes Opus teammates (e.g. an L/XL sprint where
plan quality justifies the cost), record the override in the session-start status
block and proceed. Otherwise, refuse to spawn until the `model: sonnet` pin
is present in the instruction.

> **Teammate vs subagent (live-docs-verified, #93; v2.1.178 update):** a **teammate** is a
> long-lived peer session — spawned via the native teammate-spawn referencing the
> `shepherd:conductor` agent type, addressed after spawn via `SendMessage`. A **subagent** is
> an ephemeral `Agent`/`Task` dispatch that runs and returns a result to its caller. They are
> different primitives: `Agent`/`Task` spawn **subagents only — never a teammate**. The
> `team_name` parameter on `Agent`/`Task` is **accepted but ignored** (deprecated, v2.1.178);
> it is NOT how a teammate is created and must not be relied on as a discriminator. There is
> no `TeamCreate` tool. (Source: code.claude.com/docs/en/agent-teams.)

Teammate names you give in the spawn instruction are honored where the runtime allows; the
team itself is stored under a session-derived name. The runtime materializes the team config
at `~/.claude/teams/{team-name}/config.json` — written and owned by the runtime; do NOT
pre-author or edit it. Hook routing keys off the predictable `shepherd-conductor-{sprint_slug}`
teammate-name prefix (surfaced as `teammate_name` in team-lifecycle hook-input JSON).

### Post-spawn confirmation

```
[SPAWN] teammate shepherd-conductor-{sprint_slug} dispatched.
        Team config: ~/.claude/teams/shepherd-conductor-{sprint_slug}/config.json
        Teammate transcript: ~/.claude/projects/<project>/<session-uuid>.jsonl
        Babysitter mode: active. Monitoring TeammateIdle + TaskCompleted hooks.
        Heartbeat threshold: 5 min. Alert on staleness.
        Sprint: {sprint_slug}
        Operator dashboard: /shepherd:loop {dashboard_cadence} shctx dash
        Coordinate cycle: ENTERING NOW — root does not pause for the operator.
```

`{dashboard_cadence}` resolves from `shctx config get dashboard_cadence 3m`.

**Root now enters the FOCUS-LOOP by default.** Immediately after emitting the
`[SPAWN]` block, root activates the `focus_loop_id` opened at SEED-VERIFY
(`shctx loop init --kind=focus`) and drives coordinate mode as repeating
**wake → act → probe** iterations until CLOSE-FINALIZE. Root does NOT yield to the
operator at the dispatch boundary — operating the FOCUS-LOOP is the default
coordinate-mode driver, not merely a backstop. Gatable via `[focus].loop_default`
(default "on"). Per `doctrines/coordinate-active-drive.md`; backstopped by
`hooks/scripts/coordinate_drive_guard.sh`.

**This confirmation is NOT a turn-end.** Emit it, then proceed in the SAME flow
into the coordinate cycle (confirm liveness → scaffold wave-gates → wake → act →
probe → yield-to-events). The root ends its turn only to yield to the platform
event system (which auto-resumes it) or at an enumerated operator-pause, never as
a passive wait after the `[SPAWN]` line. Per `doctrines/coordinate-active-drive.md
§II/§IV`; backstopped by `hooks/scripts/coordinate_drive_guard.sh`.

### Operator observability — the sprint dashboard (v6.1.5 #13)

Root drives via the FOCUS-LOOP and platform events; the **operator** watches via a
one-glance dashboard. `shctx dash` composes the primitives the root already
maintains — focus north-star, graph completion %, live teammates (idle/verdict),
mailbox + escalation fan-in, active loops, and GitHub-cache staleness — into a
single read-only snapshot. It builds nothing new; it just collates existing views.

Run it once, or loop it at a cadence so a long spawn stays observable without
polling each primitive by hand:

```
shctx dash                       # one snapshot
/shepherd:loop 3m shctx dash     # refresh every 3 min while the sprint runs
```

`/shepherd:loop <interval> shctx dash` is the recommended monitoring recipe for a
running spawn. The interval defaults to `[spawn].dashboard_cadence` (v6.1.5 #10;
resolve via `shctx config get dashboard_cadence 3m` — default **3m**, widen to 5m+
for slow sprints). The dashboard is purely observational: it never mutates state,
so it is safe to loop alongside the root's coordinate cycle. For deeper
teammate-pane inspection, see `shctx panes
status` (`skills/context/scripts/cmd_panes.sh`).

---

## § Teammate tool feed

The teammate-conductor needs a specific tool surface to walk the Stage Graph. The planter is responsible for ensuring it gets fed correctly.

### What the teammate inherits

**The teammate inherits the lead session's permission mode** — but tool *availability* is a separate axis. In teammate mode (any display mode — tmux or in-process), the teammate boots as a full Claude Code session with the default tool set (including `Agent` and `SendMessage`) plus any plugin-registered tools the lead has access to. The conductor profile's `tools:` frontmatter at `agents/conductor.md` is the canonical capability list; the lead must ensure each tool in that list is registered in its session before spawning.

### Required tools for a teammate-conductor

| Tool | Why the conductor needs it |
|---|---|
| `Agent` | Dispatch flock lanes (engineer, critic, coder, auditor, worker, discovery). Without this the teammate cannot walk the Stage Graph. |
| `Bash`, `Edit`, `Read`, `Write`, `Glob`, `Grep` | Plan / report / handoff authoring, gate execution at WAVE-GATE, brief assembly. |
| `Skill` | Load `code-style:<lang>`, language-mastery, doctrine skills. |
| `ToolSearch` | Discover deferred **tool calls** at runtime — MCP tools (`mcp__github__*`, `mcp__sentry__*`, …) + on-demand utilities. **NOT for agents/teammates** — those come from the visible available-agents list (`doctrines/specialist-dispatch.md §Step 2`). |
| `SendMessage` | Escalation channel back to planter per `spawn-escalation.md §V`. |
| `Task*` | Track in-flight wave state. |
| `WebFetch`, `WebSearch` | Doctrine cross-reference, dependency docs. |
| `mcp__plugin_github_github__*` (read-only set) | Issue ledger, PR / commit awareness for Phase 0 mesh. |
| `mcp__plugin_sentry_sentry__search_*` | Error-monitoring discovery during INTRO-COMBO-WAVE. |
| `mcp__plugin_supabase_supabase__{execute_sql,list_*,get_advisors}` | Datastore-state audit concern. |

### Planter pre-spawn tool check

Before issuing the teammate-spawn instruction, the planter SHOULD verify:

1. The `Agent` tool is registered in the lead session (so the spawned teammate inherits it for flock subagent dispatch — `Agent` spawns subagents, NOT teammates). If not (e.g. plugin not loaded), HALT with:
   ```
   /shepherd:spawn — REFUSED: Agent tool not registered in lead session.
   The teammate-conductor needs Agent tool inheritance to dispatch the flock.
   Run /reload-plugins, verify, and re-invoke.
   ```
2. The MCP servers referenced in `agents/conductor.md tools:` are connected (use `/mcp` or `ListMcpResourcesTool`). If a server is missing, the conductor will degrade per `doctrines/plugin-reload-escape.md` — surface a `[WARN]` line at spawn time so the operator knows.
3. The conductor's profile path is readable: `ls ${CLAUDE_PLUGIN_ROOT}/agents/conductor.md`.

### What the teammate does NOT inherit

- **Conversation history.** The teammate boots fresh. Inject all needed context via the boot prompt (per § Build the teammate prompt).
- **Open file context** the lead had loaded. The teammate must `Read` files it needs.
- **Permission grants** beyond the default permission mode. Auto-approved tool calls in the lead don't carry over.
- **Task list.** Teammates share ONE team list. Every TaskCreate title MUST be
  prefixed "{lane_id}: <description>" and you MUST TaskUpdate(owner: <your-teammate-name>)
  immediately after creating it. Only claim/work/complete tasks whose title prefix
  matches YOUR lane id. Violations: TASK-LANE-MISMATCH. Canonical:
  doctrines/lane-task-ownership.md.

### Display mode (tmux optional, not required)

Per § Platform compatibility above, the native teammate-spawn works in **any** display
mode — in-process (default, any terminal) and remote/cloud sessions included — and spawned
teammates expose the `Agent` tool, so they can dispatch the flock. `tmux`/iTerm2 split panes
are an **optional** display mode for live per-teammate observability, not a prerequisite.
(The historical in-process Agent-tool gap, `anthropics/claude-code#31977`, no longer blocks
the flow.)

---

## § --parallel flag

`/shepherd:spawn --parallel <N>` fans out N sibling teammates inside the lead's
single team. N is 2–4 (preflight Check 5). Each teammate runs one sprint end-to-end
via `/shepherd:start`. Planter babysits all N concurrently.

Base spawn behavior (§ Adopt the planter profile, § Build the teammate prompt,
§ Spawn dispatch) applies per teammate. Incremental behaviors below; full triage
and resume mechanics in `skills/shepherd/doctrines/spawn-escalation.md §X`.

### Worktree-per-teammate setup

Each teammate runs in its own git worktree for filesystem isolation:

```bash
# For each teammate i in 1..N:
git worktree add .worktrees/{sprint_slug_i} {sprint_branch_i}
```

Include the absolute worktree path in each teammate's INHERITED CONTEXT block:
```
WORKTREE PATH:  {abs_path}/.worktrees/{sprint_slug}
All file reads and writes MUST use this path as the working root.
```

Planter removes each worktree as its teammate's sprint closes (see § Cleanup below).

### Teammate naming convention

`shepherd-parallel-{sprint_slug}` (distinguishes from single-spawn
`shepherd-conductor-{sprint_slug}`). The `TeammateIdle` hook routes by
`teammate_name`; the `shepherd-parallel-` prefix is the routing key.

### Multiplexed escalation + dev-order merge gate

With N teammates active, escalations arrive concurrently. The triage protocol
(CRITICAL preemption, FIFO same-level, mid-triage suspension, status board,
cross-teammate dependency halts via `CROSS-DEP-WAIT`, PARALLEL-COLLISION response)
is fully specified at `skills/shepherd/doctrines/spawn-escalation.md §X`. Planter-side
implementation lives at `agents/planter.md §Multi-teammate triage (--parallel mode)`.

Dev-order merge gate: sprint dev.N+1 may NOT be merged to the patch branch until
dev.N's PR is merged — even if dev.N+1 closes first. Detection, hold, and release
are pinned at `agents/planter.md §Multi-teammate triage > Dev-order merge gate
enforcement`.

### Cleanup at each teammate close

When a teammate's sprint closes:

1. Verify close report (per base hand-back checklist).
2. Apply merge gate. If held → write pending-merge marker, skip merge.
3. If not held → rebase-merge dev.N onto patch branch.
4. `git worktree remove --force .worktrees/{sprint_slug}` (only when branch is
   already merged).
5. Update the multiplexed status board (mark CLOSED).
6. Update the carry-forward ledger for this sprint.
7. **Do NOT run full cleanup stewardship** (agent-* branches, shepherd.lock) until
   ALL N teammates have closed. Full cleanup is end-of-run only.

### Hard stops specific to --parallel

In addition to base hard stops:

- **Collision detected after spawn** — `PARALLEL-COLLISION`; pause all affected
  teammates before addressing. Resolution flow in `spawn-escalation.md §X`.
- **>1 simultaneous CRITICAL halt** — operator priority required:
  ```
  [HARD STOP] Multiple simultaneous CRITICAL halts detected.
  Teammates in CRITICAL state: {list}.
  Presenting all CRITICAL payloads now.
  ```
- **Teammate count drops to 0** — unrecoverable without operator input; stall alert.
- **Dev-order cycle** — refused at Check 5; cycles deadlock the merge gate.

---

## § --auto flag

`/shepherd:spawn --auto` runs a sequential autopilot loop. Planter spawns one
teammate per sprint, waits for close, does all inter-sprint work, then spawns the
next — until the patch is exhausted or a termination condition fires.

**Core win**: each sprint gets a fresh context window. Prior-sprint accumulated
context does not degrade the next sprint's dispatch quality. The planter holds
continuity; the conductor resets.

Base spawn behavior applies per loop iteration. Full loop-boundary contract
(terminal `TaskCompleted` naming, context inheritance, operator pause window) at
`skills/shepherd/doctrines/spawn-escalation.md §XI`.

### Loop structure

```
[AUTO INIT]
  1. Read shepherd.toml → determine dev.N (current) through dev.LAST
  2. Preflight Check 5 --auto: confirm patch boundary + min_grade
  3. Emit loop plan: "Auto-loop will run dev.N through dev.LAST ({M} sprints)."
  4. 10-second pre-spawn countdown; operator may interrupt.

[FOR each dev.N in dev_order]:

  [SPAWN]
    Build teammate prompt + spawn the teammate (referencing shepherd:conductor).
    Emit: "[AUTO] Sprint {N}/{LAST}: shepherd-auto-{sprint_slug} spawned."

  [BABYSIT]
    Full base babysit (wave commits, heartbeat, escalation).
    Escalation reaches operator-question or hard-stop → AUTO LOOP PAUSES.
    "[AUTO PAUSE] Sprint dev.{N} requires operator input. Resolve and
    type 'resume auto' to continue."

  [SPRINT CLOSE]
    Receive CONDUCTOR CLOSE REPORT via TeammateIdle.
    Execute inter-sprint work (see below).

  [TERMINATION CHECK]
    If dev.LAST → EXIT LOOP → emit PLANTER REPORT (auto-mode variant).
    If grade < [autorun].min_grade → apply [autorun].on_grade_floor (v6.1.5 #10;
        resolve via `shctx config get on_grade_floor abort`):
          abort (default) → EXIT LOOP → AUTO ABORT REPORT (historical behavior).
          pause           → surface ONE operator decision (re-spawn / continue /
                            stop) and honor it — do NOT auto-continue.
          continue        → log GRADE-FLOOR to walk status; proceed to dev.N+1.
    If error_budget_remaining == 0 → EXIT LOOP → AUTO ABORT REPORT.
    If operator interrupted → EXIT LOOP → AUTO ABORT REPORT.
    Otherwise → continue to dev.N+1.

[END LOOP]
```

Teammate naming: `shepherd-auto-{sprint_slug}`.

### Inter-sprint work

The planter's exclusive domain between two spawned teammates. Authoritative
10-step checklist lives at `agents/planter.md §Sprint rollover (--auto mode) >
Inter-sprint work checklist`. Summary:

1. Verify close report (grade, carry-forwards, handoff path, GH dispositions).
2. Catchup commit any uncommitted wave artifacts.
3. Rebase-merge dev.N onto patch branch; verify green gate.
4. Open PR (standalone last dev) or accumulate (mid-patch).
5. Delete dev.N branch (confirm merged).
6. Cut dev.N+1 off the updated patch branch.
7. **Author the handoff doc** for dev.N+1 — continuity bridge for the
   zero-context incoming teammate. Schema and required sections at
   `agents/planter.md §Sprint rollover > Handoff document authorship`. Target
   60–120 lines.
8. Update carry-forward ledger.
9. Update error budget counter.
10. Emit inter-sprint status, then apply `[autorun].inter_sprint_pause` (v6.1.5
    #10; resolve via `shctx config get inter_sprint_pause brief`):
    - `brief` (default) — short (~5s) window, then proceed (historical behavior).
    - `signoff` — hard pause; wait for an explicit operator sign-off (`resume
      auto`) before opening dev.N+1. Turns the walk semi-attended.
    - `none` — proceed immediately; no inter-sprint window.

Any step failure → `[AUTO PAUSE]` with the failing step identified. Do not
re-attempt without operator confirmation.

### Termination conditions

| Condition | Code | Planter action |
|---|---|---|
| `dev.LAST` closed cleanly | LAST-DEV | Full cleanup stewardship; final PLANTER REPORT |
| Grade < `[autorun].min_grade` | GRADE-FLOOR | Per `[autorun].on_grade_floor`: `abort` (default) AUTO ABORT; `pause` one operator decision; `continue` log + next sprint |
| `error_budget_remaining == 0` | BUDGET-ZERO | AUTO ABORT |
| Operator interrupt | OPERATOR-INTERRUPT | AUTO ABORT after current inter-sprint work completes |
| Escalation needs operator | ESCALATION-PAUSE | LOOP PAUSES (not terminates); resumes on confirmation |

### Auto ABORT REPORT shape

```
## AUTO ABORT REPORT
- Termination code: {code}
- Sprint at termination: dev.{N} (of dev.{LAST})
- Grade at termination: {grade}
- Error budget remaining: {N}
- Handoff doc (manual continuation): {path}
- Last committed SHA on patch branch: {sha}
- Carry-forwards pending: {list or "see ledger"}
- Recommended action: /shepherd:spawn dev.{N+1} (manual)
  or /shepherd:spawn --auto dev.{N+1}..dev.{LAST} (resume auto)
```

### Hard stops specific to --auto

In addition to base hard stops:

- **Inter-sprint step fails** — `[AUTO PAUSE]` until operator types `'resume auto'`.
- **Handoff doc missing or malformed** — auto-pause; do not spawn into a context vacuum.
- **Teammate stalls > 10 min** — auto-specific threshold (vs. 5 min base);
  `[AUTO PAUSE]` and suspend the loop.

---

## § Root-shepherd responsibilities (v5.1.6+; was "babysitter")

While the teammate-conductor(s) run the sprint, this main-chat session is the
**root shepherd**. Full behavioral contract: `agents/shepherd.md` + `doctrines/root-shepherd-orchestration.md`. Mechanical channel contract: `skills/shepherd/doctrines/spawn-escalation.md`. When planter is also loaded (two-meta), the cleanup-stewardship responsibilities cite `agents/planter.md §Babysitter mode §3` directly.

Summary (one screen):

| Responsibility | Trigger | Action | Source |
|---|---|---|---|
| **Active-drive loop** | Every coordinate wake (incl. right after spawning teammates) | wake → act (drain mail/idle) → probe (liveness + per-lane `git diff --stat`) → yield-to-events; NEVER passive-wait for operator | `coordinate-active-drive.md` §IV |
| Hook monitoring | `TeammateIdle` / `TaskCreated` / `TaskCompleted` fires | Read mailbox; route by `halt_code` | doctrine §II, §VI |
| Mailbox polling | `TeammateIdle` BLOCKING | Inspect `halt_code`; null+`blocking:false` = wave-complete; non-null = escalation | doctrine §III |
| Wave-boundary commit | `TaskCompleted` on wave-scope task | `git commit -m "chore(dev.N/wave-K): wave-complete via spawn"` (DO NOT defer) | doctrine §VI |
| Escalation triage | non-null `halt_code` | chain-repair / operator-question / hard-stop categorisation | planter.md §Babysitter mode §1 |
| Heartbeat staleness | >5 min no new shctx row | Alert operator; do NOT auto-recover | doctrine §V |
| Cleanup at sprint close | CLOSE-FINALIZE report received | Rebase-merge, cut next branch, prune worktrees, release lock, emit PLANTER REPORT | planter.md §Babysitter mode §3 + §5 |

**The most critical responsibility is wave-boundary commits.** The one-wave loss
horizon exists ONLY if commits land at every boundary. Full contract:
`skills/shepherd/doctrines/spawn-escalation.md §VI`.

---

## § Hard stops — when /shepherd:spawn must refuse

Preflight-driven (Checks 1–3) plus run-state guards:

1. Preflight Check 3 (active team already running) fails. (Checks 1 & 2 are advisory — they do NOT hard-stop; the runtime is the authority on team availability.)
2. **No active seed (conditional — seed is recommended, not required).** A missing
   `{paths.plans}/{sprint_slug}.seed.md` is a HARD stop ONLY for `--parallel` and
   multi-sprint `--scope` (patch/minor/version) walks, where seeds are load-bearing
   for collision detection (Check 5) and walk enumeration (Check 6) — there route the
   operator to `/shepherd:plant` for each gap. A single `--scope sprint` spawn does
   NOT refuse: its walk opens on the `SEED-AUTHOR` node (`pipeline.md` §II/§IV), which
   on a missing seed emits ONE turn-ending confirm and plants the seed **inline** —
   the planter inner frame (`agents/planter.md §Plant mode`, two-meta-loading) authors
   it from the operator's reply + the planter mesh, and it must pass `shctx seed verify`
   (the `SEED-GATE`) before the walk falls through to `INTRO-COMBO-WAVE`. Per
   `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/operator-signaling.md §"Seed is
   recommended, not required"`. A seedless single-sprint spawn is self-sufficient, not a
   dead-end; planting up front with `/shepherd:plant` stays the happy path.
3. **Corrupted shepherd.lock** — `.artifacts/shepherd.lock` non-empty, timestamp
   < 30 min with matching active process. Surface; do not spawn.
4. **Active rebase in progress** — `REBASE_HEAD` or `MERGE_HEAD` present;
   spawning mid-rebase produces undefined teammate branch state.
5. **Nested-team attempt** — if this command fires inside a teammate session,
   refuse. The platform forbids a non-lead from creating a team (lead is fixed; no
   nested teams; one team at a time), so this is structurally impossible as well as
   doctrinally prohibited (#93, live-docs-verified 2026-05-29).

Parallel-specific and auto-specific hard stops are listed in the respective sections
above. Failure modes (stall, session drop, SendMessage failure, planter drop) and
recovery semantics live at `skills/shepherd/doctrines/spawn-escalation.md §VII`.

---

## § Open questions

> **Live-docs reconciliation (#93; v2.1.178 update):** the live-docs-verified mechanism
> supersedes the older `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md`
> "D-API" assumptions wherever they conflict. In particular, teammates are spawned via
> the lead's **native teammate-spawn instruction** referencing the `shepherd:conductor`
> subagent definition (NO `TeamCreate` tool — removed v2.1.178) — NOT via an ephemeral
> `Agent({ subagent_type, prompt })` subagent call — and no teammate-identity env var exists.

- **OQ-1 (RESOLVED, #93): teammate agent type.** The teammate's agent type
  is the **`shepherd:conductor` subagent definition** (`agents/conductor.md`),
  referenced by name in the lead's natural-language teammate-spawn instruction (NOT a
  model slug on an ephemeral `Agent` subagent call). The teammate inherits that definition's
  `model:` and `tools:` frontmatter. No `subagent_type` model-slug decision is required.
- **OQ-2 (RESOLVED, #93): teammate name propagation.** Names are
  **lead-chosen** in the teammate-spawn natural-language instruction (e.g.,
  `shepherd-conductor-{sprint_slug}[-{lane_id}]`). The runtime records them in the team
  config and surfaces them as `teammate_name` in team-lifecycle hook-input JSON. There
  is no `name:` field on an `Agent` call and no prompt-body parsing involved.
- **OQ-3 (LOW): `TeammateIdle` routing on ambiguous `teammate_type`.** Hook payload may
  show a model slug, `"conductor"`, or custom string for `teammate_type`. Route by the
  predictable `teammate_name` (`shepherd-conductor-{slug}`, lead-chosen at spawn),
  not `teammate_type`.
- **OQ-4 (MEDIUM, --parallel): Cross-worktree build-manifest contention.** The
  collision check guards `file_scope.exclusive`. Some build tools (cargo shared
  registry cache, npm shared `node_modules`) may still contend on paths outside the
  worktree. Treat as known gap for v5.1.4; mitigation via
  `[project].build_manifest_paths` extension.
- **OQ-5 (LOW, --auto): `resume auto` signal mechanism.** Operator typing
  `'resume auto'` is recognised as text, not a formal tool call. A robust mechanism
  (e.g., `TaskCreate` with resume subject) is deferred.
- **OQ-6 (LOW, --parallel + --auto): Teammate naming collisions across sessions.**
  Re-running `--parallel`/`--auto` without full team cleanup may collide with
  existing `~/.claude/teams/` entries. The one-team-per-lead Check 3 partially
  guards. Mitigation: verify `ls ~/.claude/teams/` is empty before any multi-sprint
  run.

---

## § See also

- `agents/planter.md` — full planter/babysitter contract; §Babysitter mode; §Multi-teammate triage (--parallel); §Sprint rollover (--auto)
- `agents/conductor.md` — conductor profile; §Side-effect boundary; §Hard prohibitions #12; §Escalation protocol
- `skills/shepherd/doctrines/spawn-escalation.md` — **escalation channel contract** (paths, schema, resume shape, heartbeat, wave-boundary commits, failure semantics); §X multiplexed escalation; §XI sequential autopilot
- `commands/start.md` — the command the teammate invokes after boot
- `commands/plant.md` — seed authorship mode (prerequisite for a well-prepared spawn)
- `docs/configuration.md` — shepherd.toml schema + Agent Teams setup
- `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md` — D-API report (historical; superseded by live-docs reconciliation #93 2026-05-29 wherever the spawn call-shape or identity-signal conflicts — see § Open questions)
- `.artifacts/docs/specs/2026-05-19-v514-spawn-and-profiles-design.md` — v5.1.4 design spec
