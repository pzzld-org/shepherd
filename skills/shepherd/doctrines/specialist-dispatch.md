# Specialist dispatch — when the conductor reaches outside the flock

> Origin: v5.1.1 (2026-05-16). Operator: "we still want to be open and flexible
> to allowing other agents to be used if better suited for a particular effort
> ... instead of dispatching a worker to do this thing use some specialized
> third party agent instead."

Pre-v5.1.1, the flock was strictly closed at six. The conductor was forbidden
from dispatching `general-purpose`, `Explore`, `Plan`, `feature-dev:*`,
`pr-review-toolkit:*`, `superpowers:*`, or any other third-party agent — only
the six flock lanes (engineer, critic, coder, auditor, worker, discovery)
could fire.

v5.1.1 relaxes this for a narrow category: **specialist third-party agents
that fit a self-contained task better than the flock**. Specialists are an
exception lane, not a default. The flock remains the primary dispatch surface.

## When to dispatch a specialist

A specialist dispatch is appropriate when ALL of the following hold:

1. **Task is well-handled by an existing specialized agent.** The
   specialist is purpose-built for the surface — e.g., `code-review:code-review`
   for PR review, `sentry:seer` for Sentry investigation, `claude-md-management:claude-md-improver`
   for CLAUDE.md maintenance.
2. **Specialist is read-only OR has clearly-bounded effect.** The
   conductor knows what state the specialist can mutate. No
   "general-purpose" specialists with broad write surface.
3. **Conductor has seen the specialist's description and verified the fit.**
   Specialists discovered via `ToolSearch` or by reading the available-skills
   list. Never dispatch a specialist whose contract you haven't read.
4. **Equivalent flock dispatch would be strictly worse.** The flock's
   `@worker` can do most things — specialists only win when their
   purpose-built prompts produce measurably better output (e.g., a
   PR-review specialist understands GH review conventions; a Sentry
   specialist knows the MCP tool patterns).

## When NOT to dispatch a specialist

Hard NEVER cases:

- **Plan authorship.** That's `@engineer`'s lane. No specialist substitutes.
- **Critic gating** of plans / money-paths / merges. That's `@critic`. No substitutes.
- **Sprint-close audit grading.** That's `@auditor` in close mode. Specialists
  may augment but never replace the close-time grade.
- **Code implementation in the sprint plan.** That's `@coder`. Specialists
  with code-write capability are off-limits.
- **Any task where the framework's discipline (Phase 0 mesh, DEDUP-GATE,
  [SIBLING-LANES], etc.) needs to apply.** Specialists don't honor
  shepherd's contracts by default.

## Specialist catalog (project-specific)

Specialists are project-specific. Each project's `shepherd.toml` MAY enumerate
allowed specialists with their dispatch conditions:

```toml
[specialists]
allowed = [
  "code-review:code-review",
  "sentry:seer",
  "claude-md-management:claude-md-improver",
  "supabase:supabase",      # skill, not agent — distinct (see §Skills below)
]

[specialists.dispatch_rules]
"code-review:code-review"           = "use for PR review when @auditor close-mode is overkill"
"sentry:seer"                       = "use for Sentry triage when @worker would do > 10 sequential MCP calls"
"claude-md-management:claude-md-improver" = "use for CLAUDE.md audits before sprint open"
```

When `[specialists]` is absent, the framework allows the canonical specialists
listed above with their default dispatch conditions.

## Dispatch model

```
Agent({
  description: "specialist:<slug>: <one-line task>",
  subagent_type: "<plugin>:<agent-slug>",   # e.g., "code-review:code-review"
  model: "sonnet",                           # always sonnet; matches flock defaults
  prompt: "<the brief — specialists have their own brief contracts>"
})
```

Note the key differences from a flock dispatch:

- **`subagent_type` IS set** (flock dispatches omit it). The specialist's
  identity comes from the registered subagent type, not from injecting an
  `agents/*.md` body.
- **`prompt` follows the specialist's own brief contract**, not the
  shepherd flock-brief shape. Read the specialist's docs/help first.
- **`model: sonnet` + high effort** is the default (matches the flock's
  cost/quality target for everything but `@engineer`).

## Skills vs agents — important distinction

Many "third-party tools" the operator might mention (e.g., `supabase:supabase`,
`finance`, `rust`) are SKILLS that load into a session, not AGENTS that get
dispatched. Skills are loaded via `Skill(skill="<slug>")` inside any
agent's dispatch — they're not separate dispatches.

This doctrine governs AGENTS (things you `Agent(...)` into existence).
Skills are loaded by whichever lane needs them — the framework already
supports this via the `[SKILLS]` block in coder/engineer briefs.

## Operator communication

When the conductor dispatches a specialist, the operator surface line includes
the specialist origin:

```
[NODE] specialist:code-review:code-review → on-no-finding | PR #34 clean
[NODE] specialist:sentry:seer → on-finding | 3 active issues, 2 above thresholds
```

This makes specialist dispatches visible in the audit trail; they're not
hidden inside the flock-dispatch log.

## Audit trail

The `agent_invocation_tagger.sh` hook (v5.1.2) records every dispatched
agent's role. For specialists, `agent_role` becomes `specialist:<plugin>:<slug>`
(e.g., `specialist:code-review:code-review`). The completeness auditor at
sprint close verifies specialist dispatches were:

- Pre-authorized in `shepherd.toml [specialists].allowed`
- Used for a task the doctrine permits
- Logged + surfaced to the operator

Specialist dispatch outside the allowed list → process violation; grade-cap C+.

## Anti-patterns this doctrine catches

1. **Conductor dispatches `general-purpose` because "@worker felt heavy."** No.
   `general-purpose` is explicitly forbidden. Worker is the lane for bounded
   tasks; specialist is the lane for purpose-built tools.
2. **Specialist used in place of `@critic` / `@engineer` / `@auditor`.** Hard
   never. Those lanes are doctrinal.
3. **Conductor dispatches specialist without reading its contract.** Read the
   specialist's description + skills before fire. Specialists have their own
   brief shapes; mis-briefing them produces garbage.
4. **Specialist dispatch hidden from operator surface.** Every specialist
   dispatch surfaces in the operator log; the audit trail names the plugin
   + slug.

## See also

- `flock.md` §I — the canonical six-lane flock
- `doctrines/agent-excellence.md` — when in doubt, the flock is the default
- `hooks/scripts/agent_invocation_tagger.sh` — records specialist origin
- `SKILL.md` §I (v5.1.1+) — "closed at six + specialist exceptions per doctrine"
