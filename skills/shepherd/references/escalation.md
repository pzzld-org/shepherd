---
name: escalation
description: Escalation payload schema (7 mandatory fields), failure-recovery protocols, and the halt-code index for teammate-root communication. Use when a teammate halts, resumes, stalls, or drops.
---

# Escalation

No platform session-resume exists for a stalled/crashed teammate-conductor.
Every unresolved question MUST reach root below.

## Escalation payload

Channels: **SendMessage** (primary, async, auto-resumes a stopped
teammate); **filesystem** —
`.artifacts/escalations/{sprint_slug}/{ISO8601-timestamp}-{role}.md`
(fallback; `~/.claude/tasks/{team-name}/config.json` runtime-owned —
NEVER pre-author it); **`TeammateIdle`** hook — sole
handler, BLOCKING, graceful-idle.

Every escalation MUST conform. **All 7 fields are
MANDATORY, none optional.** Root triages on `halt_code` +
`suggested_resolution`; MUST NOT free-read `question`.

- `role`: MANDATORY — `engineer|critic|coder|auditor|worker|discovery|conductor`
- `phase`: MANDATORY — `intro` | `body-wave-N` | `close-N`, not free text
- `halt_code`: MANDATORY — a code from this index or its owning section
- `question`: MANDATORY — one sentence; detail lives in `context_files`
- `blocking`: MANDATORY — `true` = sprint paused; `false` = notification
- `context_files`: MANDATORY — 0-5 absolute paths
- `suggested_resolution`: MANDATORY — `chain-repair|operator-question|hard-stop|null`

Specialized payload shapes (WAVE-COMPLETE, `PLAN-AUTHORSHIP-REQUEST`,
`PLAN-GATE-REQUEST`) carry the envelope subset their VERBATIM shape names
plus their own fields; the 7-field mandate binds free-form escalations. A
wave-complete notification reuses this envelope (`halt_code: null`,
`blocking: false`) as a commit trigger.

Two VERBATIM payload shapes: `PLAN-AUTHORSHIP-REQUEST` (`halt_code, phase,
blocking: true, context_files: [<sprint_slug>.plan.md,
<sprint_slug>.seed.md], amendment_summary`) and `PLAN-GATE-REQUEST`
(`halt_code, phase, blocking: true, context_files: [<plan>.md],
gate_question`).

**Resume.** SendMessage (`escalation_id, resolution, answer,
amended_files, resume_instruction`) or a file at
`.../resume/{escalation_id}.md`. `chain-repair` auto-resumes;
`operator-question` resumes after confirmation; `hard-stop` MUST NEVER
auto-resume.

**Heartbeat.** Liveness: the `teammates` table (`shctx teammate
liveness --stale-mins=5`); 5 minutes with no heartbeat MUST alert, NEVER
auto-recover. An idle conductor with no preceding WAVE-COMPLETE MUST send
status within 1 turn, else read as `TEAMMATE-STALL`. The conductor MUST
also heartbeat at every major phase boundary even while blocked — a
silent block is indistinguishable from a stall.

**Wave-boundary commit.** Teammate MUST fire wave-complete,
then wait for resume — timeout `[spawn].wave_ack_timeout_sec` (default
60s); on timeout, heartbeat and continue. Root MUST commit landed
artifacts every `TaskCompleted`:
```
git commit -m "chore({sprint_branch}/wave-K): wave-complete via spawn"
```
bounding worst-case loss to one wave.

## Failure semantics

Binding recovery protocols for channel/session failure; planter follows
without improvising.

- **Teammate stalls mid-wave.** Detect: heartbeat stale >5min. No
  `/resume` for in-process teammates — HEARTBEAT ALERT options: (1) wait,
  re-check in ~3min (may be mid long dispatch); (2) probe —
  `SendMessage(to: conductor, "heartbeat?")`; (3) declare stall. Loss:
  current wave's uncommitted artifacts. Recover (option 3): note last
  commit SHA, `rm -rf ~/.claude/teams/{team-name}/`, re-invoke
  `/shepherd:spawn`; teammate resumes from next unstarted wave.
- **Teammate session drops (no `TeammateIdle`).** Detect: session UUID
  absent from `~/.claude/sessions/`, heartbeat stopped. Loss: current
  wave + in-transit payloads. Recover: as stall; check
  `.artifacts/escalations/{sprint_slug}/` for a pre-drop file.
- **SendMessage delivery fails.** Fallback: read
  `.artifacts/escalations/{sprint_slug}/{timestamp}-{role}.md`; absent →
  treat as stall; resume via that file instead.
- **Root session drops.** Loss: all wave artifacts since last root
  commit. Recover: reconstruct state from the registry (teammates /
  escalations rows) + filesystem tree,
  commit `git status` deltas; a closed teammate leaves only
  git-committed work.
- **Operator interrupts (Ctrl-C).** Teammate orphaned: no commits, no
  escalations answered. Recover: manual cleanup `rm -rf
  ~/.claude/teams/shepherd-conductor-{sprint_slug}/`. Prevention: send a
  "clean stop" SendMessage first.

## Halt-code index

Every prose-only ALL-CAPS code is defined here, only here; elsewhere cite
the bare name.

- `BRIEF INVALID`: missing a required field
- `CONTEXT-INVENTORY STALE`: symbol/path absent
- `DUPLICATION RISK`: overlaps a symbol
- `SCOPE OVERFLOW`: edit outside `[FILE-SCOPE]`
- `CODER-GIT-WRITE`: a @coder ran a git write (commit/add/reset/checkout/…); git custody is the conductor's, PASS-gated (`hooks/scripts/coder_git_guard.sh`, `agents/coder.md`)
- `BRIEF-AMENDMENT REQUEST`: amendment requested
- `SEED DRIFT`: no longer matches repo state
- `ROOT-INTRO-USURPED`: root ran a discovery/intro wave alongside a self-contained engineer
- `SPECIALIST-UNCLEAR` / `-UNAVAILABLE`: ambiguous or unavailable
- `TASK-LANE-MISMATCH`: claimed outside lane
- `STAGE-GRAPH-VIOLATION`: invents/skips/reorders node
- `SUBTRACT-VIOLATION`: sprint net-positive, unauthorized
- `OUTCOME-REGRESSION`: seeded predicate now false; grade capped
- `PLAN-MISSING-OUTCOME-VERIFICATION`: deliverable lacks runnable predicate
- `LEDGER-DISCIPLINE-VIOLATION`: entry missing disposition
- `SENTINEL-*` (7 codes): triple-gate violation; canonical `skills/motivation/SKILL.md §Sentinel`
- `LOOP-CAP`: loop exceeded `--max`
- `LOOP-REPORT-INVALID`: report missing `new_findings`
- `PLAN-MISSING-LOOP-CAP`: loop dispatched with no cap
- `DISPATCH-WRONG-ROLE`: routed to wrong role
- `CIRCULAR-RUBRIC`: rubric references itself
- `TOURNAMENT-CONTAMINATION`: judge saw another candidate's
- `COMPOSITION-TOO-DEEP`: nested dispatch too deep
- `WAVE-GATE-NOT-RELEASED`: gate never released
- `WAVE-COMPLETE-UNVERIFIED`: teammate claimed `WAVE-COMPLETE` but `git -C <lane-worktree> log <BASE-COMMIT-EXPECTED>..HEAD` is empty (branch + worktree HEAD still at base) — refuse the wave, do not release the gate, probe the teammate (#152)
- `CROSS-TEAMMATE-DISPUTE`: teammates read scope differently
- `SEED-DRIFT-DETECTED`: substantive drift (theme/money-path/secret boundary) — escalate, never rewrite intent
- `SEED-DRIFT-MECHANICAL`: fixable premise slip (moved path, stale symbol) — verify, amend, re-fire
- `CROSS-DEP-WAIT`: blocks on another sprint's artifact
- `PARALLEL-COLLISION`: two sprints claim one path
- `GATES-BROKEN`: merge leaves a gate red
- `TEAMMATE-STALL`: idled with no preceding WAVE-COMPLETE
- `WORKFLOW-SELFCHECK-TOOLSEARCH`: ToolSearches for `Workflow` vs checking
- `TEAMMATE-BOOT-MISSING`: `INVOCATION-CONTEXT` boot block wholly absent — not spawned by `/shepherd:spawn`
- `TEAMMATE-BOOT-MALFORMED`: boot block present but fails a Boot verification check (a lead-authored non-canonical brief carrying `BOOT-FORMAT: lead-attested` substance-checks the required facts instead of the header shape — `agents/conductor.md §Boot verification`)
- `TEAMMATE-ARTIFACT-WRITE`: writes a plan/report/handoff
- `TEAMMATE-LOCK-ATTEMPT`: touches `.artifacts/shepherd.lock`
- `DISCOVERY-WRITE-VIOLATION`: `@discovery` mutates
- `SKILL-DRIFT`: skill contradicts repo state
- `LOOP-STALL`: no progress before its cap
- `PLAN-INVALID-INTERVAL`: loop interval invalid

Flag-specific codes: `SCOPE-*` §--scope, `STAGED-TIMEOUT` §--staged,
`GRADE-FLOOR`/`BUDGET-ZERO` §--auto — all at
`skills/shepherd/references/spawn-flags.md`.
