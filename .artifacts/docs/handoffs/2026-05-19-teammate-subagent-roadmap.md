---
title: Teammate + Agent Tool — Roadmap Viability Research
date: 2026-05-19
status: complete
author: research-agent (main-chat)
gates: v5.1.4 Phase 0 — informs /shepherd:spawn design posture
---

# Teammate + Agent Tool — Roadmap Viability Research

> This report answers whether Anthropic has signalled that teammates will gain Agent tool
> (subagent dispatch) capability in the foreseeable future. It gates the v5.1.4 design
> decision: build `/shepherd:spawn` for permanent constraint, or forward-compat with eventual
> expansion?

---

## § Direct Evidence

### 1. Official docs confirm the restriction — with no caveat

The live `code.claude.com/docs/en/agent-teams` page (fetched 2026-05-19) lists, under **Limitations**:

> "No nested teams: teammates cannot spawn their own teams or teammates. Only the lead can
> manage the team."

Notably, the docs frame this as "no nested **teams**", but say nothing about single-level
subagent dispatch (the `Agent` tool). This creates a documentation gap that the community
has noticed and filed against.

Source: <https://code.claude.com/docs/en/agent-teams>

### 2. GitHub issue #31977 — open bug, tmux mode is the accidental workaround

**Title:** `[BUG] In-process team agents lack the Agent tool (cannot spawn subagents)`
**Status:** OPEN as of 2026-05-19
**Label:** `bug` ("Something isn't working")
**Anthropic staff response:** None recorded
**Linked PRs / milestone:** None

Key finding from the issue:

> "Using `--teammate-mode tmux` resolves the issue — teammates get full tool access
> including `Agent`."

This is the clearest signal in the dataset: the restriction is **mode-specific**, not
architectural. In tmux mode, teammates already have the Agent tool. In in-process mode
they do not. The issue is filed as a bug, not a feature request, implying Anthropic's
intended behavior is parity between modes.

Source: <https://github.com/anthropics/claude-code/issues/31977>

### 3. GitHub issue #32731 — docs gap report, closed as "not planned"

**Title:** `[DOCS] Teammates have fewer tools than subagents and cannot spawn anything —
restriction is broader than documented`
**Status:** CLOSED — "not planned"
**Anthropic staff response:** None
**Conclusion from the issue:** Restriction is described as an "underdocumented design
choice" rather than a defect. Framing: teammates are a "hub-and-spoke" context; only
the lead orchestrates.

The "not planned" closure is for the documentation PR, not a statement that the feature
restriction is permanent. No Anthropic engineer weighed in.

Source: <https://github.com/anthropics/claude-code/issues/32731>

### 4. Sub-agent docs confirm the asymmetry is known

The `code.claude.com/docs/en/sub-agents` page notes:

> "Team coordination tools such as SendMessage and the task management tools are always
> available to a teammate even when `tools` restricts other tools."

The `Agent` tool is conspicuously absent from this carve-out, confirming it is stripped
from teammates by policy (or in-process mode bug), not accidentally.

Source: <https://code.claude.com/docs/en/sub-agents>

---

## § Indirect Signals

### 5. Tmux mode parity implies eventual in-process fix is likely

The fact that tmux-mode teammates already have the `Agent` tool (per issue #31977) means
the toolset difference is a **backend implementation gap**, not a deliberate permanent
architectural split. When the in-process backend catches up to the tmux backend, this
restriction disappears automatically. This is an engineering backlog item, not a policy
decision.

### 6. Agent teams feature is still experimental

`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` remains the enabling flag. The feature shipped
at v2.1.32 (Feb 2026); operator is at v2.1.144. The "experimental" label typically
means Anthropic is still hardening the feature — tool parity across modes is a natural
hardening milestone.

### 7. Anthropic's managed-agents direction implies deeper nesting

The `anthropic.com/engineering/managed-agents` post (found in search, May 2026)
describes the Managed Agents roadmap as: "a lead agent can delegate to specialist
subagents working in parallel on a shared filesystem, each with its own model, prompt,
and tools." This is precisely the pattern that in-process teammates currently cannot do.
The architectural direction confirms Anthropic wants deeper delegation chains — they are
building toward it in Managed Agents, which informs what Claude Code teammates will
eventually support.

Source: <https://www.anthropic.com/engineering/managed-agents>

---

## § Workarounds Documented by Anthropic or Community

### Workaround A — Use tmux mode (Anthropic-adjacent, confirmed in issues)

Set `--teammate-mode tmux` or `"teammateMode": "tmux"` in `settings.json`. In tmux mode,
teammates have the full Agent tool and can dispatch subagents. This is the only confirmed
workaround. Downside: requires tmux or iTerm2; the operator's current setting is
`"in-process"`.

Source: <https://github.com/anthropics/claude-code/issues/31977>

### Workaround B — Conductor stays in lead; teammates remain leaf workers

The official Anthropic stance (doc + issue #32731 framing) is: "teammates delegate
nothing; all orchestration flows through the lead." Shepherd's current single-context
subagent model (lead dispatches @engineer / @critic / @coder / @auditor via Agent tool)
is entirely consistent with this. The constraint does not affect the existing
`/shepherd:start` / `autorun` / `parallel` flows — those run in the lead session.
It only affects a hypothetical future where a teammate session *itself* tries to be a
conductor.

### Workaround C — shctx registry as explicit delegation proxy (community pattern)

Several community writeups (Shipyard, DeveloperDigest, Lushbinary) describe using a
shared task registry (SQLite or file-based) to proxy cross-agent coordination. This is
exactly what shepherd's shctx already implements. The pattern is stable regardless of
whether teammates gain the Agent tool.

Sources:
- <https://shipyard.build/blog/claude-code-multi-agent/>
- <https://www.developersdigest.tech/blog/claude-code-agent-teams-subagents-2026>

---

## § Verdict

**YES-EVENTUAL**

The restriction is confirmed real and active in in-process mode. However, the evidence
points to an engineering backlog item rather than a deliberate permanent decision:

1. Tmux-mode teammates already have the Agent tool — parity gap, not policy gap.
2. GitHub issue #31977 is open, labelled `bug`, not `wont-fix`.
3. Anthropic's public Managed Agents direction describes deeper delegation as the
   intended architectural end state.
4. No Anthropic engineer has posted a "this is intentional and will not change" statement
   on any relevant issue.

There is no imminent release signal (no PR, no milestone, no staff acknowledgement on
the bug). But the structural evidence makes eventual parity likely once the in-process
backend matures past its current experimental state.

---

## § Confidence Level

**MEDIUM**

High confidence that the restriction is a backend implementation gap (not policy), based
on the tmux parity evidence. Low confidence on timeline — no public roadmap commitment,
no staff engagement on the open bug. "YES-EVENTUAL" could take one month or twelve.

---

## § Recommended Design Posture

Design v5.1.4's `/shepherd:spawn` command around the **permanent constraint** as the
baseline, but architect it to be forward-compatible with minimal friction. Concretely:
the command should spawn a teammate and hand it a well-scoped, single-context task (a
leaf role: coder, auditor, worker) rather than a conductor role. All orchestration —
`Agent` tool dispatch, flock sequencing, sprint state — remains in the lead session,
which already has the Agent tool and uses it today. This is not a regression from the
current model; it is the current model with a new spawn surface. When Anthropic closes
issue #31977 and in-process teammates gain the Agent tool, the same `/shepherd:spawn`
architecture can be extended to allow a teammate to act as a sub-conductor for a
sub-sprint without redesigning the coordinator contract. The one concrete design rule
that buys forward-compat at zero cost: keep the teammate's task boundary explicit
(a named slot in the sprint manifest, a registry row, a clear deliverable) so that if
a future teammate does dispatch its own subagents, those results flow back to the same
slot the conductor already tracks.

---

## Sources

| # | URL | What it contributes |
|---|-----|---------------------|
| 1 | <https://code.claude.com/docs/en/agent-teams> | Official limitations section; no-nested-teams rule; no roadmap note |
| 2 | <https://github.com/anthropics/claude-code/issues/31977> | Open bug: in-process mode missing Agent tool; tmux mode has it |
| 3 | <https://github.com/anthropics/claude-code/issues/32731> | Docs gap closed "not planned"; no Anthropic staff comment on intentionality |
| 4 | <https://github.com/anthropics/claude-code/issues/24316> | Feature request: richer teammate customization; open, no milestone |
| 5 | <https://code.claude.com/docs/en/sub-agents> | Confirms tool carve-out: SendMessage always available; Agent is not |
| 6 | <https://www.anthropic.com/engineering/managed-agents> | Managed-agents roadmap implies deeper delegation intent |
| 7 | <https://shipyard.build/blog/claude-code-multi-agent/> | Community workaround: registry-mediated coordination |
| 8 | <https://www.developersdigest.tech/blog/claude-code-agent-teams-subagents-2026> | Tool count diff confirmed (~25 subagent vs ~20 teammate) |
