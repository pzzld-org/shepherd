# content/ — reconciliation against codex-shepherd@1.0.2

`content/` is the harness-neutral source of truth this sprint introduces. It does not yet
drive `agents/`, `commands/`, `skills/`, or `hooks/` — those stay hand-authored on Claude
until a later wave wires the compiler. This document is the drift ledger: it names every
divergence between the current Claude tree and the installed `codex-shepherd@1.0.2` bundle
(evidence: `.shepherd/runs/v645/reports/discovery-d1-harness.md` §Engineer follow-up,
Hazard 8) and records a real decision for each, not just a restatement of the row.

## Capability vocabulary (the compile target every `content/roles/*.md` uses)

The contract, per `[USER-STYLE]`: name the abstract verb, never the concrete tool — tool
names are exactly what differs per harness. Every role's `capabilities` list MUST be
**complete**, not a delta: Pi's `--tools` flag is a strict *replacing* allowlist (discovery
report, Pi probe), so an adapter compiling `capabilities` into `--tools` has to see every
verb a role needs in one place, never assume "built-ins minus a few."

| capability | meaning | Claude tool(s) it maps to today | Pi `--tools` target |
|---|---|---|---|
| `read` | read a file from the working tree | `Read`, `NotebookRead` | later-wave Pi adapter names the concrete tool |
| `search` | pattern/glob discovery over the tree | `Glob`, `Grep` | " |
| `shell` | execute a local command | `Bash` | " |
| `write` | create/modify files inside the role's granted scope | `Write`, `Edit` | " |
| `report-write` | write ONLY to one narrow, brief-declared output path — a *narrower* fact than `write`, used instead of it | `Write` (path-scoped by a `PreToolUse` guard) | " |
| `skill-load` | load a packaged skill body | `Skill` | " |
| `tool-discovery` | resolve a deferred/MCP capability by name at runtime | `ToolSearch` | " |
| `dispatch` | fan out to another role as a subordinate execution unit | `Agent`, `Workflow` | " |
| `message-peer` | direct message to a peer or lead session | `SendMessage` | " |
| `task-tracking` | shared best-effort task-list read/write | `TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate` | " |
| `web-research` | fetch/search external web sources | `WebFetch`, `WebSearch` | " |
| `ask-operator` | interactive operator question (sole-holder capability) | `AskUserQuestion` | " |
| `schedule-wakeup` | arm a future self-wake | `ScheduleWakeup` | " |
| `code-intelligence` | LSP-grade symbol/reference resolution | `LSP` | " |

The Pi-tool-name column is deliberately left as a pointer, not a guess: the discovery report
confirms `--tools` is a strict replacing allowlist (closes seed open question 4) but never
enumerated Pi's own tool names per capability — inventing them here would be exactly the
kind of unverified claim the coder protocol forbids. A later-wave Pi adapter closes that
column against the live binary.

## `write_eligible` — a hard fact, not a convention (Hazard 1)

Codex's `explorer` agent type cannot write files at all; `worker` can. `[agent_types]` in
the installed `shepherd.codex.toml` maps all 8 dispatched shepherd roles onto exactly those
two primitives. A role whose write-eligibility exists only as prose in `agents/*.md`
compiles into a broken Codex adapter the first time a nominally-read-only Claude role is
mapped to `worker` (over-grants a write Codex will actually allow) or a write-capable Claude
role is mapped to `explorer` (silently strips writes Codex will actually deny). Every
`content/roles/*.md` therefore carries `write_eligible: true|false` as a top-level fact,
derived from whether the role's `agents/*.md` `tools:` frontmatter grants `Write`/`Edit` —
**with one documented exception**: `conductor` carries no `Write`/`Edit` tool grant at all,
yet commits, pushes its own lane branch, and writes narrowly under its own
`{run_dir}/lanes/{lane}/` — all via `Bash`. Codex's explorer/worker split is about whether
the *role* can mutate the filesystem/repo at all, not which Claude tool token achieves it;
a literal "has `Write`/`Edit`" check would misclassify conductor as `explorer` and silently
strip its git-custody capability on a Codex port. `conductor.md` is `write_eligible: true`
with that Bash-mediated exception spelled out in its own file, not smoothed over.

## Drift matrix + decisions

| # | Claude | Codex 1.0.2 | Decision |
|---|---|---|---|
| 1 | `skills/adaptation` (one file) | `adapt` + `self-improvement` (split, unilateral) | **Re-merge at the source, split only at emission.** `content/skills/adaptation/SKILL.md` stays ONE canonical file — re-splitting the source to match Codex's drift would just move the dual-maintenance problem, not fix it (`[DO-NOT-DUPLICATE]`'s whole point). A later-wave Codex emitter MAY compile the one source into two physical skill files if Codex's skill-trust/discovery model benefits from the split; that keeps Codex's already-installed skill names stable without re-introducing a second hand-maintained copy upstream. |
| 2 | `skills/harness` | absent | **Claude-only by design — confirmed, not emitted.** The whole skill is Agent Teams / Workflow-tool / `ToolSearch` platform mechanics that have no Codex analog (Codex's own concurrency/dispatch model is `spawn_agent` + a 3-descendant cap, an entirely different primitive). `content/skills/harness/` carries a stub marking it Claude-only rather than a fabricated abstract rendering of facts that are true of exactly one harness. |
| 3 | `commands/plant.md` + `agents/planter.md` | `skills/plant` | **The role file is canonical; the command is a thin invocation wrapper, not new content.** `commands/plant.md` contributes zero facts `content/roles/planter.md` doesn't already carry (mesh, authorship, prohibitions, report shape) — it only names the Claude-specific entry point (`/shepherd:plant`) for a contract the role file states in full. Codex's `skills/plant` is the same relationship on that harness: a skill-shaped invocation surface over the same role contract. Neither harness's invocation surface is itself a reconciliation target; `content/roles/planter.md` is. |
| 4 | 9× `agents/*.md` | zero role files → `[agent_types]` TOML | **Roles compile to a table, root excluded.** `content/roles/*.md` (all 9, including `shepherd.md`) is the canonical per-role source; a later-wave Codex emitter folds it into `[agent_types]`, keyed by each file's `role:` field, `write_eligible` selecting `explorer`/`worker`. `shepherd.md` (root) is excluded from the compiled table on BOTH harnesses — root is never itself a dispatched agent type, it's the top-level session (`dispatchable: false` in its role file) — which is exactly why the installed Codex config maps "8 shepherd roles," not 9: the table was never missing root, root was never a candidate. |
| 5 | 7 skills | 8 skills | **Not an independent divergence — it's row 1, counted twice.** The `+1` is entirely the `adaptation` → `adapt` + `self-improvement` split. Row 1's decision (one source, two-file compile only at Codex's emission boundary) resolves this row too: `content/skills/` carries 7 canonical directories; a Codex emitter is free to produce 8 physical files from those 7 sources without that fan-out ever becoming a second source of truth. |

## Residual / not reconciled this pass

The discovery report probed `adaptation` and `harness` specifically against the installed
Codex bundle; it did not independently verify whether `bridge`, `context`, `motivation`,
`shepherd`, or `thinking` have a Codex-side counterpart, drifted or otherwise. Rather than
invent a decision the evidence doesn't support, `content/skills/{bridge,context,motivation,
shepherd,thinking}/SKILL.md` below are authored straight from the Claude source with no
Codex-side claim attached — closing that gap is future discovery work, not a guess made here.
