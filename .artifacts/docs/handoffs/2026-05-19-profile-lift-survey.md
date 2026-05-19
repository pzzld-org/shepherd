---
title: Profile Lift Survey — v5.1.4 design (conductor + planter profile extraction)
date: 2026-05-19
status: Phase 0 deliverable — D-LIFT discovery report
producer: D-LIFT discovery agent (sonnet, Explore subagent, read-only)
audience: engineer authoring agents/conductor.md + agents/planter.md
spec: ../specs/2026-05-19-v514-spawn-and-profiles-design.md
---

# Profile Lift Survey — v5.1.4 Design

**Lift surface summary:** ~620 lines lift to conductor profile, ~280 lines lift to planter profile, ~150 lines net-new for babysitter behaviors.

---

## 1. Conductor profile — content sources

Content that should land in `agents/conductor.md`:

- `skills/shepherd/SKILL.md:57–58` — Conductor identity statement ("Main chat. Sonnet. You plan, dispatch, validate, and tie off. You write .md only — never source code, build files, or shell. The flock writes the code.")
- `skills/shepherd/SKILL.md:63–76` — §0 "Read shepherd.toml first" — config-load discipline (resolving `{patch_branch}`, `{sprint_branch}`, `{paths.*}`, `{gates.*}` tokens)
- `skills/shepherd/SKILL.md:80–116` — §I "The flock (closed at six)" — full agent roster table, dispatch procedure, flock-closed rule, inline-vs-dispatch heuristic, specialist-exception policy
- `skills/shepherd/SKILL.md:119–141` — §II "Branch topology" — patch/sprint branch patterns, non-negotiable list
- `skills/shepherd/SKILL.md:144–270` — §III "Three-section sprint pipeline + Stage Graph" — complete §1 INTRO checklist (20 items), §2 BODY walk-tick checklist + "real work" test + body-depth heuristic table, §3 CLOSE checklist + adaptation signal, sprint-as-patch impactfulness contract
- `skills/shepherd/SKILL.md:273–283` — §IV "Coder brief contract" — seven-section shape, mandatory lane counts by T-shirt, mandatory skills attachment
- `skills/shepherd/SKILL.md:287–298` — §V "Hard stops (every command)" — six universal stop conditions
- `skills/shepherd/SKILL.md:301–307` — §VI "Carry-forward + label discipline" — CRITICAL/HIGH no-defer rule, once-deferred rule, milestone/sprint-slot discipline, tracking-future treatment
- `skills/shepherd/SKILL.md:311–342` — §VII "Anti-patterns" (27 items)
- `skills/shepherd/SKILL.md:347–367` — §VIII "Operator communication norms" — mandatory surface moments, status-line format
- `skills/shepherd/SKILL.md:370–382` — §IX "Session continuity (mid-sprint recovery)" — 5-step re-orientation protocol
- `skills/shepherd/pipeline.md:1–111` — §I–§II "Why a graph" + "Stage taxonomy" (21 node types, HOTFIX-DYNAMIC cardinality, `## Stage Graph` YAML node structure)
- `skills/shepherd/pipeline.md:119–155` — §III "Edge predicates" (20 canonical edge labels)
- `skills/shepherd/pipeline.md:158–264` — §IV "Canonical sprint graph"
- `skills/shepherd/pipeline.md:268–319` — §V "Conductor's walk algorithm" + cache-first brief ordering
- `skills/shepherd/pipeline.md:322–339` — §VI "Pattern B is a graph shape"
- `skills/shepherd/pipeline.md:343–365` — §VII "Hot-fix subgraphs" (4-node HOTFIX DAG, paste-verbatim discipline)
- `skills/shepherd/pipeline.md:367–381` — §VIII "CLOSE subgraph" — 5-concern table, `on-grade-cap` semantics
- `skills/shepherd/pipeline.md:383–417` — §IX–§X "Autorun walk" + "Parallel walk"
- `skills/shepherd/pipeline.md:551–625` — §XIII-bis "Structured gate output + parallel HF dispatch"
- `skills/shepherd/pipeline.md:628–756` — §XIV–§XV — graph customization, pre-4.2.0 migration, worktree `target/` policy, SendMessage-vs-spawn mechanics, shared-context append discipline, PAUSE-FOR-DEPENDENCY subgraph
- `skills/shepherd/flock.md:1–14` — header + conductor identity (rule: conductor NEVER writes source files)
- `skills/shepherd/flock.md:46–70` — `@auditor` dispatch reference (swarm mode, concern table, Pattern B timing, READ-ONLY rule)
- `skills/shepherd/flock.md:72–240` — `@coder` dispatch reference (parallel-safe rules, brief contract, Brief-Validity Checklist, worktree lifecycle, required-skills matrix)
- `skills/shepherd/flock.md:242–256` — `@critic` dispatch reference (trigger conditions, pass-2 flag classification)
- `skills/shepherd/flock.md:258–288` — `@engineer` dispatch reference (mandatory skills, sandwich-plan discipline, phase 0 → plan → proof-of-dispatch-footer)
- `skills/shepherd/flock.md:290–327` — `@discovery` + `@worker` dispatch references
- `skills/shepherd/flock.md:350–407` — §III "Dispatch discipline summary" + §IV "Carry-forward + GH label/milestone" + §V "Anti-patterns" (17 items)
- `skills/shepherd/autorun.md:1–170` — autorun behavioral contract (loop semantics, sprint-through grant, per-sprint critic-pass-2 fast path, between-wave gates, sprint-close, hard stops, termination)
- `skills/shepherd/parallel.md:1–83` — multi-sprint worktree mode
- `skills/shepherd/doctrines/pause-for-dependency.md:87–119` — §III "Conductor protocol" (6-step inline table)
- `skills/shepherd/doctrines/worker-patterns.md:1–103` — worker dispatch heuristic + brief shape + 5 patterns + anti-patterns

---

## 2. Planter profile — content sources

Content that should land in `agents/planter.md`:

- `commands/plant.md:1–138` — full slash-command body (model gate, behavioral overlay load, planter mesh table, seed authorship per scope, verification checklist, hand-off report block, hard prohibitions)
- `skills/shepherd/planter.md:1–46` — §0 "Version-scale sizing" + §I "Identity" — model pin (opus), role, inputs/outputs, lifetime, "not a flock agent, not a seventh lane" identity
- `skills/shepherd/planter.md:49–97` — §II "Drift-resistance contract" — 8-property table (verifiable, anchored, specific, sized, ranked, bounded, phased, reproducible)
- `skills/shepherd/planter.md:99–132` — §III "Density discipline" — GH-issue anchor rule, 8 formatting rules, 150–300 line seed target
- `skills/shepherd/planter.md:134–197` — §IV–§V "Multi-phase doctrine" + "Phase 0 ground-truth handling" — phase decomposition, conditional links, parallel-safe grouping, lane minimums by T-shirt, INTRO-COMBO-WAVE planning, 12-row mesh table, delta-check
- `skills/shepherd/planter.md:199–215` — §VI "Carry-forward propagation" — 3-path disposition (placed/deferred/dropped), ledger update, arc rebuild
- `skills/shepherd/planter.md:216–240` — §VI.A "Sprint pattern registry" — 4-row adaptation signal table
- `skills/shepherd/planter.md:241–300` — §VII "Anti-patterns" (12 items)
- `skills/shepherd/planter.md:303–415` — §VIII–§XII "Output discipline" + milestone leverage + dedup-not-an-arc + Phase 0 gate rows + workspace knowledge silo + multi-sprint arc planning + verification checklist + anti-pollution discipline
- `skills/shepherd/planter.md:417–457` — §XIII–§XV "Hand-off back to conductor" + "Inheritance from the conductor" (Sonnet vs Opus divergence table)

---

## 3. Babysitter-during-spawn — net-new gaps

Behaviors needed for planter-while-teammate-conductor-active mode that are NOT in any current file:

1. **Escalation response protocol** — when the spawned conductor surfaces a hard stop or RECONSIDER back to the planter session, how does the planter triage? Does it amend the seed and re-seed, or escalate to operator? Chain-repair doctrine covers conductor-inline but not cross-session.
2. **Git custody during spawn** — can the planter push a new seed to `{paths.plans}/` while the conductor's sprint is in-flight on the same worktree root? Safe write perimeter while a teammate is active? `doctrines/conductor-cwd.md` only addresses single-conductor case.
3. **Cleanup stewardship** — when a spawned conductor closes dev.N, does the planter session do anything? Verify close report before authoring dev.N+1?
4. **Concurrent write conflict discipline** — if planter writes dev.N+1 seed while conductor runs dev.N, both may want to write to `{paths.reports}/` or `{paths.ctx}/canonical-types.md`. `doctrines/coder-brief-format-shared-artifacts.md` covers coder-vs-coder; planter-vs-conductor unaddressed.
5. **Planter session hand-back timing** — current model: session ends after `/shepherd:plant` commits seeds. If operator wants planter to STAY OPEN and babysit, there is no defined "ambient monitoring mode". Net-new.
6. **Read-only observation contract during babysit** — planter in babysitter mode should be read-only from source tree (like @discovery) but may legitimately update seeds mid-flight if conductor surfaces chain-repair request. Boundary needs a rule.

---

## 4. Existing flock-agent file shape (template for new profiles)

The six agents in `agents/*.md` share a consistent shape that new profile files should match.

**YAML frontmatter:**
- `name:` — short role name
- `color:` — display color (blue, red, yellow, orange, green)
- `model:` — `sonnet` or `opus[1m]`
- `thinking:` — `high` or `max`
- `description:` — multi-line with 1–3 concrete `<example>` blocks (context → user turn → assistant turn → `<commentary>`)
- `tools:` — explicit comma-separated tool list (no glob patterns)

**Markdown body:**
- H1 identity line: `# @role — Short Title`
- One-sentence role identity + excellence doctrine cite
- `## Hard prohibitions` — numbered NEVER list, grounded in field origins
- `## Halt codes` — table of `Code | Meaning`
- `## Mandatory protocol` — Step N numbered sections
- `## Output to main chat` — verbatim code block of expected report shape
- `## What you are NOT` — bullets differentiating from adjacent roles
- Optional: `## Final reminder`

**Key difference for profiles:** `agents/conductor.md` and `agents/planter.md` are NOT dispatched via the Agent tool. They are injected as behavioral overlays into the main-chat or teammate session by the slash command. Dispatch procedure in SKILL.md §I applies to the six flock agents; the profile files work analogously but are self-applied.

---

## 5. Overlap and ownership — operator decisions needed

| # | Ambiguity | Recommended resolution |
|---|---|---|
| Q1 | SKILL.md §I (flock roster + dispatch procedure) — does SKILL.md become thin-loader or keep condensed copy? | **Thin-loader.** SKILL.md becomes pure quick-reference index; canonical conductor behavior lives in `agents/conductor.md`. SKILL.md retains a 1-paragraph "see agents/conductor.md for full sprint runner protocol" pointer. |
| Q2 | Divergence table (planter.md §XIV) — canonical location? | **Live in `agents/conductor.md`** as "What makes me different from planter". `agents/planter.md` cites it. Avoids two copies drifting. |
| Q3 | autorun.md fate after conductor lift | **Thin to delta only.** Keep loop semantics + sprint-through grant + autorun-specific hard stops. Per-sprint discipline becomes "see conductor profile". |
| Q4 | SKILL.md planter line (line 88–89) | Mechanical update — point at `agents/planter.md`. |
| Q5 | `skills/shepherd/planter.md` survival | **Retire.** Replace with a 5-line redirect pointing at `agents/planter.md`. Avoids two-file maintenance burden. |
| Q6 | `pause-for-dependency.md` conductor protocol | **Reference, don't embed.** `agents/conductor.md` cites the doctrine. Doctrine is canonical for the cross-agent protocol. |

---

## 6. Refactor risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | `commands/autorun.md:14–15` hardcodes "Identical to /shepherd:start Step 0" — breaks if start.md thins | Low | Update autorun.md to load `agents/conductor.md` directly, drop the cross-reference |
| R2 | `commands/autorun.md:26–32` "Everything else is identical to /shepherd:start" — becomes stale prose | Low | Replace with "per agents/conductor.md" pointer |
| R3 | Dispatch procedure repeated in `SKILL.md:96–116` + `flock.md:25–42` + (new) `agents/conductor.md` — triple drift | **Medium** | Pick ONE canonical (conductor.md); SKILL.md + flock.md become thin pointers |
| R4 | `SKILL.md §X` invocation table references plant.md "loads behavioral overlay" | Low | Update table entry to point at agents/planter.md |
| R5 | `autorun.md:116–148` "Per-sprint discipline" — subset of full conductor protocol; silent divergence risk | **Medium** | After lift, autorun.md REMOVES the subset (cites conductor.md instead). Single source of truth. |
| R6 | `flock.md:1–14` + `SKILL.md:57–58` carry slightly-different conductor identity one-liners | Low | Reconcile during lift; both files cite agents/conductor.md identity |
| R7 | `commands/plant.md:38` hardbinds to `skills/shepherd/planter.md` | Low | Update binding to `agents/planter.md`; skills/shepherd/planter.md becomes 5-line redirect |
| R8 | `commands/parallel.md:23–24` loads conductor superpowers — redundant if profile already loads them | Low | Document but don't fix; double-load burns context but doesn't break |

---

## 7. Recommended phase order for the engineer's plan

1. **Phase 1A (parallel):** Author `agents/conductor.md` (deduplicating the SKILL.md + flock.md + pipeline.md + autorun.md content per the line ranges above)
2. **Phase 1B (parallel):** Author `agents/planter.md` (lift from planter.md + plant.md, add §3 babysitter gaps as net-new sections)
3. **Phase 2:** Thin-loader refactor of `commands/start.md` + `commands/plant.md` (depends on 1A + 1B)
4. **Phase 3:** `skills/shepherd/SKILL.md` + `skills/shepherd/flock.md` reconciliation (R3 + R6 fix)
5. **Phase 4:** `skills/shepherd/autorun.md` thin (R1 + R2 + R5 fix)
6. **Phase 5:** `skills/shepherd/planter.md` retirement (5-line redirect; per Q5)
7. **Phase 6:** Verification — all path bindings resolve; smoke-load each command file
