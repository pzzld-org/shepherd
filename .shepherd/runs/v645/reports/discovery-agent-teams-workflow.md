---
title: Discovery — Can an in-process Agent Teams teammate invoke the Dynamic Workflow tool?
date: 2026-08-13
discovery_id: discovery-agent-teams-workflow
sprint: v6.4.5
sources_consulted: 8
tool_calls_used: 23
time_used_minutes: 18
---

## Sources

1. https://code.claude.com/docs/en/workflows — official Dynamic Workflows docs (fetched in full)
2. https://code.claude.com/docs/en/agent-teams — official Agent Teams docs (fetched in full)
3. https://code.claude.com/docs/en/sub-agents — official Subagents docs, "Available tools" / tool-filter section (fetched in full)
4. https://github.com/anthropics/claude-code/issues/29207 — "teammateMode: 'tmux' silently falls back to in-process since ~v2.1.50+" (fetched, no maintainer reply visible)
5. https://github.com/anthropics/claude-code/issues/31977 — "In-process team agents lack the Agent tool (cannot spawn subagents)" — closed as not planned (fetched)
6. https://github.com/anthropics/claude-code/issues/32731 — "[DOCS] Teammates have fewer tools than subagents and cannot spawn anything — restriction is broader than documented" — closed as not planned (fetched)
7. https://wmedia.es/en/tips/claude-code-subagent-background-tools — community write-up on the subagent tool-filter, corroborates `Workflow` in the "first filter" list (fetched)
8. https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md — searched for `Workflow` + `subagent`/`teammate`/`backendType` co-occurrences (fetched, no matching entries found)

Secondary (surfaced by WebSearch, titles/snippets only, not individually fetched — cited only where a claim is directly attributed):
- https://github.com/anthropics/claude-code/issues/23506 ("[BUG] Custom agents (--agent) cannot spawn subagents into teams - Task tool unavailable")
- https://github.com/anthropics/claude-code/issues/46424 ("[BUG] Agent tool not available to sub-agents — prevents orchestrator pattern")

## Findings

**F1 — VERDICT: an in-process teammate cannot invoke the Workflow tool, and this is not conditional on `backendType`.**
The official Subagents doc states the tool-availability rule as two filters applied to "every subagent": *"Subagents inherit the built-in tools and MCP tools available in the main conversation, narrowed by two filters: the first removes a short list of tools from every subagent... The first filter removes these tools, even when listed in the `tools` field: `Agent` [depth-limit-conditioned] · `AskUserQuestion` · `EndConversation` · `EnterPlanMode` · `ExitPlanMode` [unless permissionMode is plan] · `ScheduleWakeup` · `TaskOutput` · `WaitForMcpServers` · `Workflow`"* (source 3, `sub-agents` doc, "Available tools" section). The very next paragraph folds teammates into this same rule with only an additive exception: *"Teammates in agent teams additionally keep the task tools and cron tools: `TaskCreate`, `TaskGet`, `TaskList`, `TaskUpdate`, `CronCreate`, `CronDelete`, and `CronList`."* — i.e. teammates get MORE than a plain subagent (task/cron tools) but are never exempted from the first filter that strips `Workflow`. Nothing in this rule is keyed on `backendType` or `teammateMode`; it applies uniformly. This directly explains the observed error: *"Workflow is not available inside subagents"* is the generic denial for any Agent-tool-spawned context, teammates included, regardless of `in-process` vs `tmux` backend.

**F2 — what `backendType: "in-process"` means, and a documented discrepancy worth flagging.**
`backendType` (recorded per-member in `~/.claude/teams/{team}/config.json`) is a *display/execution-transport* setting, not a tool-permission setting: in-process teammates run "inside your main terminal," navigated via the agent panel; tmux/iTerm2-backed teammates get their own real terminal pane (source 2, "Choose a display mode"). The doc frames `backendType` purely as UI plumbing. However, GitHub issue #31977 (source 5, tested on v2.1.71, closed "not planned") empirically found that in-process teammates lack the `Agent` tool while switching to `--teammate-mode tmux` restored it — which *looks* like a `backendType`-gated tool difference, in tension with the official doc's framing of `Agent` removal as depth-limit-conditioned only (source 3, line "`Agent`, when the subagent is at the depth limit"). This is an unresolved conflict between the current official doc and a maintainer-closed-as-WAI bug report; see Open questions. It does **not**, however, change the `Workflow` answer — no source, including #31977 and the follow-up #32731, shows `Workflow` reappearing under tmux/iTerm2 backendType for a teammate.

**F3 — `teammateMode` values and what each resolves to** (source 2, "Choose a display mode"):
- `"in-process"` — default since v2.1.179 (was `"auto"` before that). All teammates run inside the main terminal.
- `"auto"` — split panes if already inside a tmux session, or if the terminal is iTerm2 with the `it2` CLI installed; falls back to in-process otherwise.
- `"tmux"` — enables split-pane mode, auto-detecting tmux vs. iTerm2 based on the terminal.
- `"iterm2"` — added v2.1.186; forces iTerm2 native split panes explicitly, requires the `it2` CLI, errors with an install command if missing.
Each spawned teammate's *actual* resolved backend is recorded per-member as `backendType` (`"in-process"` or `"tmux"`) in `config.json` — `teammateMode` is the requested setting, `backendType` is the realized outcome, and issue #29207 (source 4) documents a live bug where a TTY check can silently force `backendType: "in-process"` even when `teammateMode: "tmux"` was explicitly configured, matching the local measured facts exactly.

**F4 — the "not available inside subagents" denial is about the Agent-tool substrate, not the in-process backend.**
Per source 3, the first filter is described as applying to "every subagent" unconditionally — not scoped to background-vs-foreground (that's the *second* filter) and not scoped to `backendType`. Being spawned via the `Agent` tool substrate at all (standalone subagent, teammate, foreground or background, in-process or tmux) is sufficient to lose `Workflow`. The doc's own comparison table in the Workflows page (source 1) frames Subagents / Skills / Agent teams / Workflows as four *peer* orchestration primitives where "who holds the plan" differs — it does not describe any of the first three as being able to invoke the fourth. The one place a related note exists — *"Agents that other features run, such as workflow agents and agent team teammates, follow their own limits instead"* (source 3, Concurrent subagent limit section) — is scoped narrowly to the concurrency-limit mechanism (the 20-concurrent-subagent cap), not to tool-filtering; it does not carve teammates out of the `Workflow`-removal filter.

**F5 — no source describes a working config where a teammate invokes Workflow.**
Extensive search (source 1, 2, 3, plus targeted queries for "teammate ... Workflow ... ultracode", "teammate successfully invoked Workflow") turned up zero examples, official or community, of a teammate driving a Dynamic Workflow. The only documented triggers for Workflow are session-level and human-input-gated: typing `ultracode` or a natural-language "use a workflow" request at the interactive prompt, in an IDE panel, in a Remote Control client, or in an SDK call whose input is stamped `{ kind: "human" }`; and `/effort ultracode` for the whole session (source 1, "Where the keyword works"). The doc explicitly excludes `-p` prompts, unstamped SDK input, scheduled-task prompts, and webhook/PR-comment-relayed input from triggering a workflow — none of these exclusions mention teammates directly, but a teammate's spawn prompt is Claude-composed delegation input, not human-typed input, so it would not qualify as a trigger route even if the `Workflow` tool weren't already stripped by the first filter. The local fact that `shepherd:conductor`'s agent-registry entry lists `Workflow` among its granted tools is consistent with `conductor` being intended to run as the *main/lead* session (which keeps the full main-session tool pool) rather than as a spawned subagent or teammate — the grant would resolve to a no-op/error if `conductor` were itself dispatched via the `Agent` tool as a subagent or teammate, per F1/F4, though no source directly tests this specific case (see Open questions).

**F6 — Agent Teams and Dynamic Workflows are not documented as composable/nestable, in either direction.**
Two independent restrictions compound here, both from source 2 and source 3:
- Teammate → Workflow: blocked (F1).
- Teammate → nested team/subagent spawn at all: blocked — *"No nested teams: teammates cannot spawn their own teammates. Only the lead can manage the team"* and *"No background subagents from in-process teammates: an in-process teammate's own subagents run in the foreground... because a teammate's background work can't outlive the lead's process"* (source 2, Limitations).
- The reverse direction (a Workflow-spawned `agent()` starting its own Agent Team) is not addressed by any source found; the Workflows doc describes workflow-spawned agents only as isolated `agent()`/`pipeline()` workers that "never talk to each other" (source 1's design, corroborated by secondary summaries), which by the same first-filter rule (source 3) would themselves also lack `Workflow`, and there is no `TeamCreate` mention anywhere in the Workflows doc's tool/script surface.
Net: the two primitives are peer, mutually exclusive orchestration modes selected by the main/lead session — not nestable inside one another in the sources reviewed.

## Open questions

- Does the `Agent`-tool in-process-vs-tmux discrepancy in issue #31977/#32731 (both closed "not planned," tested on v2.1.62–v2.1.71) still reproduce on the current documented baseline (v2.1.178+, per source 2's own version note)? The current official doc frames `Agent` removal as depth-limit-conditioned, not `backendType`-conditioned — either the doc is stale/incomplete on this point, or the underlying behavior changed since those issues were filed. Not resolved by any source found.
- Would `shepherd:conductor`'s `Workflow` grant silently no-op (rather than error) if `conductor` were ever dispatched as a subagent/teammate instead of as the main session? Not directly tested in any source.
- No changelog entry was found pinning the exact version `Workflow` was first added to the subagent first-filter removal list — the CHANGELOG search (source 8) surfaced only subagent-concurrency/depth-limit entries (v2.1.198, v2.1.212, v2.1.217–219, v2.1.221), none mentioning `Workflow` by name.
- Whether a Dynamic Workflow script's `agent()` calls can themselves form or join an Agent Team is unaddressed by any source consulted; flagged as adjacent to, but outside, the original question.

## Confidence

**HIGH** on the core verdict (F1, F4, F6): the official `sub-agents` doc's tool-filter table is unambiguous, current (matches the exact error string in the measured local facts), and independently corroborated by a community write-up (source 7) and by the closed-as-WAI GitHub issue #32731's empirical tool-count testing.

**MEDIUM** on the `backendType`/`Agent`-tool discrepancy in F2: the underlying GitHub reports (#29207, #31977, #32731) are 5-6 months old relative to today and closed as "not planned" or without visible maintainer resolution; current behavior could differ from what they document, and the official doc itself doesn't corroborate `Agent`-tool in-process/tmux gating.

## Suggested follow-ups

- If `shepherd:conductor` needs guaranteed `Workflow` access, confirm empirically (small live test) that it runs as the session's lead/main agent rather than being dispatched via `Agent`/teammate spawn — the docs make this the deciding factor, not any team-config flag.
- If fan-out is needed *from* a teammate, the documented path is: have the teammate report back to the lead, and have the **lead** (which is the main session and never subject to the subagent tool filters) start the Dynamic Workflow instead.

## DISCOVERY REPORT
- Question: In Claude Code's Agent Teams, can a spawned teammate whose team-config row reads `"backendType": "in-process"` use the Dynamic Workflow tool (the `Workflow` tool) to drive its own fan-out? Are Agent Teams and Dynamic Workflows composable/nestable?
- Sources consulted: 8 (primary, fetched in full) + 2 secondary (title/snippet only)
- Tool calls used: 23
- Time used: 18 minutes
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/discovery-agent-teams-workflow.md
- Confidence: HIGH (core verdict) / MEDIUM (backendType-Agent-tool sub-question)
- Status: complete
- Anomalies: Official docs (code.claude.com/docs/en/sub-agents) frame `Agent`-tool removal as depth-limit-conditioned, not `backendType`-conditioned, while GitHub issues #31977/#32731 (closed "not planned," tested v2.1.62-71) empirically found in-process teammates lack `Agent` while tmux-backend teammates have it — a doc-vs-bug-report conflict not resolved by any source found. This conflict does NOT affect the `Workflow`-tool verdict, which is unconditional across both backends in every source.
- Reporter: @discovery
