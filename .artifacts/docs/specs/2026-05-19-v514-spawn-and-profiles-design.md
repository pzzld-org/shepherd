---
title: v5.1.4 — /shepherd:spawn + planter & conductor profiles
date: 2026-05-19
branch: v5.1.4
status: design (operator-approved approach C, profile-only consumption, two profiles)
scope_tier: patch  # per doctrines/version-scale-roadmap.md (≤ 10 dev sprints)
supersedes: planning portions of .artifacts/docs/plans/v514-teammate-parallel.seed.md
            (the parallel/registry/telemetry portions defer to v5.1.5+)
---

# v5.1.4 — `/shepherd:spawn` + planter/conductor profile split

## Problem

Long sprints saturate main-chat context. By wave 3 of an L/XL sprint, the conductor
is operating under compression — losing fidelity on carry-forwards, gate verdicts,
and earlier wave decisions. Today's `/shepherd:start` runs the conductor pipeline
directly in main chat, so context degradation accumulates across sprints in a
persistent session.

Claude Code's Agent Teams feature provides a clean escape: spawn a teammate to run
the conductor, leave main chat lean. Issue #39 proposes an env-gated teammate
branch inside `/shepherd:start`. This design completes the architectural shift:
main chat becomes a permanent **planter-style babysitter** alongside any spawned
teammate-conductor — proactively reading context, answering escalations the flock
can't resolve alone, and owning the side-effects (git, cleanup, conflict
resolution) the conductor shouldn't touch.

## Non-goals (explicitly deferred)

The v5.1.4 seed (`.artifacts/docs/plans/v514-teammate-parallel.seed.md`) covers
a much larger surface — registry-mediated parallel coordination, build-manifest
locks, per-teammate cache-telemetry aggregation. Those defer to v5.1.5+.
This patch ships the **foundation only**: spawn + profiles + escalation channel.

Out of scope for v5.1.4:
- Multi-teammate fanout in `/shepherd:parallel` (still single-operator multi-worktree)
- Registry tables `parallel_assignments`, `parallel_locks`, `parallel_ready`
- `shctx parallel *` subcommands
- Build-manifest single-writer lock
- Per-teammate cache-telemetry aggregation
- Live RPC between teammates
- Teammate role/permission system
- Auto-spawning by env var (`/shepherd:spawn` is explicit, never automatic)

## North star

- Main chat = permanently lean, adopts the **planter profile** as ambient mode
- A spawned teammate adopts the **conductor profile** to run the sprint end-to-end
- The same conductor profile drives `/shepherd:start` whether main chat or teammate
  is the runner — single source of truth
- Escalations from the teammate flock surface to main chat through a precise
  return-and-resume protocol; teammate context stays focused on execution

## Architecture

```
Main chat (planter profile — ambient, permanently lean)
  ├─ Operator dialog, escalation responses, proactive context read
  ├─ Git ops (commits, branches, merges, conflict resolution)
  ├─ Cleanup (zombie worktrees, registry locks, agent-* branches)
  ├─ `/shepherd:plant`  → planter profile in seed-authorship mode
  ├─ `/shepherd:start`  → planter profile + runs conductor in main chat
  └─ `/shepherd:spawn`  → planter profile + spawns teammate
        └── Teammate session (conductor profile)
              ├── /shepherd:start internally (first action)
              ├── Phase 0 mesh via @discovery × N (parallel batch)
              ├── @engineer (Opus) plan + @critic (Sonnet) gate
              ├── @coder × N waves (parallel batches)
              ├── @auditor × 3-5 close swarm (parallel batch)
              └── Close report → returns to main chat planter
```

**Profile-only consumption.** Conductor and planter profiles are persona docs
adopted as system-prompt addenda by whoever runs the command. No nested Agent
dispatch via the Agent tool — that path stays available for future v5.1.5+
experiments but is not wired in this patch.

**The flock stays closed at 6 domain agents** (engineer, critic, coder, auditor,
worker, discovery). Planter and conductor are meta-orchestrators, not domain
members. They live in `agents/` to match file convention but are distinguished
in `skills/shepherd/flock.md` as the meta tier.

## Components

### 1. `agents/conductor.md` — NEW (conductor profile)

Lifts orchestrator behavior currently scattered across `skills/shepherd/SKILL.md`,
`skills/shepherd/flock.md`, `skills/shepherd/pipeline.md`, and `commands/start.md`.

Single source of truth for the **sprint-runner role**:
- Phase 0 mesh structure (INTRO-COMBO-WAVE: discoveries + intro-mode auditors)
- Plan-then-gate (`@engineer` Opus → `@critic` Sonnet pass-1/pass-2)
- Wave dispatch contract (parallel-safe, file-disjoint, bracketed brief)
- Hot-fix policy (< S each, max 3 concurrent)
- Pattern B overlap (auditor of Wave N runs with coder of Wave N+1)
- Audit swarm structure (3-5 by concern: code-quality, data-flow, dependency-topology, completeness)
- Close synthesis (grade + memory + doctrine updates + handoff write)
- **Escalation protocol** — when to halt and return to the planter (see doctrine §3)
- **Side-effect boundary** — what conductor does NOT do (git writes, filesystem
  cleanup outside dispatch scope, registry lock acquisition)

Adopted by `/shepherd:start` as a system-prompt addendum. Whether main chat or
a teammate is the runner is irrelevant to the profile itself — the profile
just describes "how to be the conductor".

### 2. `agents/planter.md` — NEW (planter profile)

Lifts planter behavior currently in `skills/shepherd/planter.md` + `commands/plant.md`
into a flock-style persona doc. Extends with the **babysitter-during-spawn**
responsibilities:

- **Seed authorship** (existing planter mode): read everything, write
  drift-resistant sprint seeds
- **Ambient read** (new): when a teammate-conductor is active, periodically
  refresh awareness of project state — open issues, deploy state, datastore
  state, sentry errors, git log
- **Escalation responder** (new): when the teammate flock pings with an
  unresolvable question, surface to the operator and reply
- **Git custodian** (new): commits, branch creation/deletion, rebase-merge
  operations, conflict resolution
- **Cleanup steward** (new): worktree pruning, lock release, agent-* branch
  cleanup, dedup checks

Adopted by `/shepherd:plant` AND `/shepherd:spawn`. Same profile, two
invocation modes:
- Plant mode → seed-authorship dominant; ambient read on demand
- Spawn mode (with active teammate) → ambient read + escalation responder dominant;
  seed authorship on demand

### 3. `commands/spawn.md` — NEW (spawn command)

Main chat invokes; spawns a teammate via the Agent Teams API; teammate's first
action is `/shepherd:start` against the inherited sprint scope.

Documents:
- **Detection** — verify teammate API availability at invocation (refuses with a
  clear error if unavailable, points to Phase 0 discovery report)
- **Inheritance** — what the teammate receives at boot:
  - Path to `CLAUDE.md`
  - Path to active sprint seed (`{paths.plans}/{sprint_slug}.seed.md`)
  - Path to latest close handoff
  - Carry-forward GH issue numbers
  - `shepherd.toml` snapshot
  - Conductor profile (`agents/conductor.md`)
- **Escalation channel** — how teammate-conductor reaches the planter
  (precise shape pinned by Phase 0 discovery; see doctrine §3)
- **Babysitter responsibilities** — what main chat does while teammate is active
  (planter profile delta: ambient read cadence, escalation queue check, git
  operations not blocked by teammate state)
- **Completion** — what happens when teammate returns the close report
  (planter writes handoff doc; planter handles rebase-merge + branch cleanup
  + cuts next dev branch)
- **Failure modes** — teammate stall, teammate session drop, escalation timeout

### 4. `skills/shepherd/doctrines/spawn-escalation.md` — NEW (doctrine)

The precise contract between teammate-conductor and main-chat-planter:

- **Halt conditions** — when conductor must stop and surface (re-cite
  existing hard-stops + add: any sub-agent return with HALT signal)
- **Escalation shape** — what the teammate writes to surface a question:
  - File: `.artifacts/escalations/<sprint>/<timestamp>-<role>.md`
  - Schema: `{role, phase, question, blocking, context_files[]}`
  - OR (if Phase 0 discovery confirms): direct return-to-main-chat with a
    sentinel envelope
- **Resume shape** — how the planter's reply re-enters the teammate (file
  reply OR re-dispatch with appended context)
- **Heartbeat** — teammate writes a status row every N minutes; planter
  notices staleness within M minutes
- **Failure semantics** — what happens if no resume arrives; what
  rotates/expires/recovers

≤ 200 lines. Single doctrine, no fanout into sub-files.

### 5. Modified — `commands/start.md`

Thin refactor: existing body retained, but lifts the conductor-behavior
prescriptions into `agents/conductor.md`. The start command becomes a
five-step wrapper:
1. Load shepherd skill context
2. Load conductor profile (`agents/conductor.md`)
3. Auto-orient (existing Step 0)
4. Run pipeline per the conductor profile
5. PAUSE at sprint close

### 6. Modified — `commands/plant.md`

Same pattern: lifts planter-behavior prescriptions into `agents/planter.md`.
The plant command stays Opus-pinned, but its body becomes a thin loader.

### 7. Modified — `commands/parallel.md` and `commands/autorun.md`

Minimal in v5.1.4. Document that the spawn-aware variants (`parallel --spawn`,
`autorun --spawn`) are NOT in this patch. Leave a `## Future` section noting
the v5.1.5 path.

### 8. Modified — `skills/shepherd/SKILL.md` and `skills/shepherd/flock.md`

Add the meta-tier:
- 6 domain agents (engineer, critic, coder, auditor, worker, discovery) —
  unchanged
- 2 meta agents (planter, conductor) — new section
- Link to profile files

### 9. Modified — `CLAUDE.md`

Update flock count language (currently says "closed at five"; reality is six
+ now two meta). Clarify the meta tier doesn't open the closed-flock contract.

### 10. Modified — `.claude-plugin/plugin.json`, `marketplace.json`, `README.md`, `CHANGELOG.md`

Version sync to v5.1.4 (plugin.json already done in df764b6; verify others).

## Phase decomposition

Eight phases. Each phase ≤ one wave's worth of work. Phase 0 is BLOCKING.

### Phase 0 — Discovery (BLOCKING, parallel)

Two parallel `@discovery` agents (sonnet, background):

- **D-API**: Claude Code Agent Teams API surface
  - Env vars (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` and any siblings)
  - Lifecycle (spawn, lifetime, drop semantics)
  - Communication channel (shared filesystem, return envelopes, sentinels)
  - Dispatch shape (CLI command, tool call, hook event)
  - Identity (teammate ID, role tagging, per-teammate config)
  - Version requirements (minimum Claude Code version)
  - Output: `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md`

- **D-LIFT**: Conductor/planter logic survey
  - Read all existing `commands/*.md` and `skills/shepherd/*.md`
  - Identify exact line ranges that describe:
    - Conductor behavior (pipeline, dispatch, gating, hot-fix policy, audit)
    - Planter behavior (read-everything, seed authorship, drift resistance)
    - Babysitter behavior (currently missing — note gaps)
  - Recommend the lift surface for each profile
  - Output: `.artifacts/docs/handoffs/2026-05-19-profile-lift-survey.md`

If D-API reveals teammate APIs are not yet usable for what spawn requires,
scope amends to "ship profiles + start/plant refactor only; spawn deferred".
Operator confirms before phase 1.

### Phase 1 — Profile authorship (conductor + planter)

Author `agents/conductor.md` and `agents/planter.md` per the lift survey.
Two parallel coder lanes (file-disjoint).

### Phase 2 — `commands/spawn.md` + escalation doctrine

Author `commands/spawn.md` and `skills/shepherd/doctrines/spawn-escalation.md`
per the API discovery findings. Single lane (the spawn command and its
doctrine are tightly coupled).

### Phase 3 — Thin-loader refactor of start.md and plant.md

Lift body content per the lift survey; replace with thin loaders that
adopt the corresponding profile. Two parallel coder lanes (file-disjoint).

### Phase 4 — Skill / CLAUDE.md / docs synchronization

Update `skills/shepherd/SKILL.md`, `skills/shepherd/flock.md`, `CLAUDE.md`,
`commands/parallel.md`, `commands/autorun.md`. Single lane.

### Phase 5 — Version + changelog sync

`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `README.md`,
`CHANGELOG.md` — verify all aligned at v5.1.4. Single lane via `shctx release`
dry-run + apply.

### Phase 6 — Self-test

Without invoking the teammate API (which has cost): manually verify
- `/shepherd:start` skill still loads the conductor profile cleanly
- `/shepherd:plant` skill still loads the planter profile cleanly
- `commands/spawn.md` is syntactically a valid command (frontmatter, body,
  no orphan refs to missing files)
- All path citations in profiles + spawn doctrine resolve

### Phase 7 — Audit swarm + PR

Standard close: completeness auditor verifies all phase outputs landed;
code-quality auditor reviews the new profiles for clarity; data-flow auditor
traces the escalation channel for soundness. Then PR `v5.1.4 → main` per
`feedback_pr_required_not_bypass`.

## D-LIFT findings (Phase 0 partial — survey landed 2026-05-19)

Survey at `.artifacts/docs/handoffs/2026-05-19-profile-lift-survey.md`. Numbers:

- ~620 lines lift to conductor profile (from SKILL.md + pipeline.md + flock.md + autorun.md + parallel.md + 2 doctrines)
- ~280 lines lift to planter profile (from skills/shepherd/planter.md + commands/plant.md)
- ~150 lines net-new for 6 babysitter-during-spawn behaviors (escalation response, git custody, cleanup stewardship, concurrent-write discipline, hand-back timing, read-only observation contract)

**Operator-decision questions (adopted resolutions):**

| Q | Resolution |
|---|---|
| SKILL.md fate | **Thin-loader** — quick-reference index, points at `agents/conductor.md` for full protocol |
| Divergence table canonical | **Live in `agents/conductor.md`** as "what makes me different from planter"; planter cites |
| autorun.md fate | **Thin to delta only** — loop semantics + sprint-through grant + autorun hard stops; pre-sprint discipline cites conductor profile |
| skills/shepherd/planter.md survival | **Retire** — 5-line redirect at the old path; canonical content moves to `agents/planter.md` |
| pause-for-dependency.md | **Reference, don't embed** — conductor.md cites the doctrine |

**Refactor risks tracked in survey §6** — the medium-severity risks (R3: triple drift of dispatch procedure across SKILL.md + flock.md + new conductor.md; R5: autorun.md silent divergence after lift) are mitigated by enforcing ONE canonical location per piece of content.

## D-API findings (Phase 0 complete — discovery landed 2026-05-19)

Report at `.artifacts/docs/handoffs/2026-05-19-teammate-api-discovery.md`. Verdict: **mature enough to ship `/shepherd:spawn` in v5.1.4** with one major design constraint absorbed.

**Confirmed platform facts:**

| Fact | Value |
|---|---|
| Env var | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true` (string `true`, not `=1`) |
| Teammate mode | `in-process` (per operator config) |
| Min Claude Code version | v2.1.32 (operator on v2.1.144) |
| Spawn mechanism | `Agent` tool dispatch from the lead session |
| Communication primary | `SendMessage` (platform mailbox) |
| Communication durable | `~/.claude/tasks/{team-name}/` shared filesystem |
| Lifecycle hooks | `TeammateIdle` (BLOCKING, fires in lead), `TaskCreated`, `TaskCompleted` |
| Heartbeat | NO platform primitive — shim via `PostToolUse` writing shctx rows |

**Hard limits (load-bearing for design):**

- **No nested teams** — teammate cannot spawn its own teammates; subagent dispatch via Agent tool is still available
- **One team per lead session** — `/shepherd:spawn` refuses if a team is already active
- **No session resumption for in-process teammates** — if a teammate stalls, work is lost (no `/resume`); planter MUST commit at wave boundaries so the loss horizon is one wave at most
- **No per-teammate config at spawn** — the conductor profile is loaded by the teammate via its own `/shepherd:start` invocation, not injected by the spawner

**Adopted escalation channel design:**

Primary: `SendMessage` (mailbox). Conductor surfaces an escalation by calling `SendMessage(to: lead, payload: <structured>)`. Planter watches `TeammateIdle` hook firing (BLOCKING in lead context — natural pause point) or reads the mailbox proactively in ambient mode.

Durable fallback: filesystem at `~/.claude/tasks/{team-name}/` — for transcripts, audit trail, and recovery if the SendMessage path is unavailable.

Heartbeat: shctx `PostToolUse` hook writes a row per teammate tool call (timestamp, role, phase). Planter staleness check polls the row; threshold = 5 minutes inactivity → alert operator.

**Wave-boundary commit discipline (new requirement, from "no /resume"):**

The planter MUST commit on every `TaskCompleted` hook fire for a wave-scope task. The conductor signals wave completion via SendMessage AND TaskCompleted; planter commits the wave's work to the dev branch. If the teammate then stalls in the next wave, only THAT wave's work is lost.

This makes the side-effect boundary stricter: conductor produces wave artifacts in the worktree but never commits; planter commits on every wave boundary signal.

## Open questions (engineer's plan resolves these)

1. ~~**Escalation channel shape**~~ — RESOLVED by D-API. SendMessage primary, filesystem durable, shctx heartbeat shim.

2. **Heartbeat cadence** — every dispatch? every N minutes? Both?

3. **Conductor model inheritance** — conductor profile says "inherit" (no
   explicit model). Confirm that `/shepherd:start` inside a teammate inherits
   the teammate's model selection (which the operator picks at spawn time).

4. **Planter profile model** — should `agents/planter.md` frontmatter specify
   Opus (matching `/shepherd:plant`), or stay inherit so main chat's session
   model wins? Recommend: `inherit` to keep planter flexible. Operator
   already picks Opus for main chat per `currentDate` env hint.

5. **Auto-spawn detection** — `/shepherd:spawn` is explicit (never automatic
   in this patch). Should `/shepherd:start` print a HINT when teammate API is
   detected ("you may want `/shepherd:spawn` instead")? Recommend: yes, but
   non-blocking; just a one-line nudge.

6. **Multiple concurrent spawns** — in v5.1.4 we allow 1 teammate at a time
   (spawn refuses if a teammate is already active). v5.1.5 lifts this to N.

7. **Backwards compatibility** — does the profile-only refactor break any
   existing skill consumer? `/shepherd:autorun` calls into start logic;
   confirm the thin-loader refactor doesn't break that path.

## Carry-forwards from v5.1.3

- Brief-cache-discipline doctrine — extends to spawn briefs. The teammate's
  initial brief must follow the same bracketed-section discipline so
  prompt caching engages from boot.
- Cache telemetry hook — captures teammate dispatches too (transparent).
  Per-teammate aggregation defers to v5.1.5.
- SubagentStop hook — already wired; extend to track teammate completion
  in v5.1.5 (no change this patch).

## Risk register

- **R1: Teammate API not yet expressive enough** → Phase 0 detects; scope
  amends to ship profiles + refactor only; spawn ships in v5.1.5
- **R2: Profile lift creates drift between profile and start.md** → Phase 6
  self-test catches; CLAUDE.md adds an invariant note
- **R3: Escalation channel design wrong** → ship behind a doctrine; iterate
  in v5.1.5+. Doctrine is cheaper to revise than command body
- **R4: `/shepherd:autorun` breaks** → Phase 6 self-test includes autorun
  smoke; if breaks, hotfix coder lane in close
- **R5: Operator workflow disruption** — main chat behavior changes (now
  planter-by-default) → README + CHANGELOG note clearly; existing
  invocations still work without spawn

## Sprint t-shirt

M. Eight phases but most are thin. Two new profile files (≤ 500 lines each),
one new command file (~300 lines), one new doctrine (≤ 200 lines), thin-
loader refactor of two existing commands (~50 line delta each), version
sync. No registry schema changes, no hook changes (beyond stating that
existing hooks continue to work), no new skill body.

## Proof of dispatch

- design authored by: main-chat @ 2026-05-19
- approach: C (Phase-0-discovery-gated, A-leaning if APIs are mature)
- operator confirmation: 2026-05-19 ("we need (A) + ... any additional
  improvements ... two profiles ... planter + conductor")
- supersedes: parallel/registry portions of `v514-teammate-parallel.seed.md`
- next step: discovery agents (D-API + D-LIFT) dispatched in parallel;
  engineer plan written once both reports land
