# D1 — harness capability matrix (Claude Code / Codex / Pi)

**Lane:** INTRO-COMBO-WAVE D1 · **Role:** `@discovery` (sonnet) · **Run:** v645
**Dispatcher:** `shepherd-engineer-v645` (`dispatcher: engineer-self-contained`)
**Date:** 2026-08-12 · **Cost:** 122,024 subagent tokens, 44 tool calls, 292s
**Confidence:** HIGH on Pi + sibling-port evidence (primary sources); MEDIUM on Codex
custom-prompt directory (see §Residual).

> Materialized by the engineer, not the reporter. The lane's completion notification
> routed to the task-tree owner (root) rather than to the dispatching teammate, so this
> file — not the transcript — is the durable record. See `dogfood.md` (sub-flock
> completion leak).

## Capability matrix

| Capability | Claude Code | Codex | Pi |
|---|---|---|---|
| Roles/agents (declarative role file) | native — `agents/*.md` frontmatter (`name`, `model`, `tools`, `color`) | native — built-in role types (`explorer`, `worker`) + `plugin_hooks`→`hooks`; no arbitrary named role, only two capability classes | absent as file-declared roles; a role = a CLI invocation (`pi --system-prompt`/`--append-system-prompt` + `--model` + `--tools`) |
| Slash commands | native — `commands/*.md` | native-adjacent — plugin marketplace prompt/command surface (exact dir UNVERIFIED) | native — `~/.pi/agent/prompts/*.md` / `.pi/prompts/*.md`; filename becomes `/name`; frontmatter `description` + `argument-hint` |
| Skills (Agent Skills spec) | native — `skills/*/SKILL.md` | native — `~/.codex/skills/*/SKILL.md` populated; flags `skill_search=true`, `skill_mcp_dependency_install=true` | native, lenient; `~/.pi/agent/skills/`, `.pi/skills/`, `~/.agents/skills/`, `.agents/skills/`; documents pointing at `~/.claude/skills` and `~/.codex/skills` via `settings.json` |
| Hooks / tool-call interception | native — `hooks/hooks.json`, matcher-based, shells out to scripts | native — flag `hooks=stable,true`; **live on this box** for `codex-shepherd@codex-shepherd:hooks/hooks.json`, 10 events | **no hook module** — "hooks do not exist as a module, they are extensions"; guards are `pi.on("tool_call", …)` in a TS extension, `{block, reason, terminate}`, `event.input` mutable in place |
| Teams / parallel dispatch | native — Agent Teams | native — flag `multi_agent=stable,true` (v2 off by default); `subagent_start`/`subagent_stop` events; **3 live-descendant global cap** per sibling parity doc | absent natively; third-party extension `@tintinweb/pi-subagents` only — EMULATABLE-IN-ADAPTER |
| Templates / render | shepherd-owned (`render.py`; `minijinja` planned) | no confirmed native templating beyond prompt files | native prompt-template engine, but a slash-command expander — not a render/manifest engine with `template_sha256`/`vars_sha256`/`output_sha256` |
| Config precedence | shepherd-owned chain (planned `crates/core/src/loader.rs`, 10 candidates / 4 tiers) | native — `~/.codex/config.toml`, `-c key=value` dotted overrides, `--profile` layering (**3 effective tiers**) | native — **2 tiers only**: `~/.pi/agent/settings.json` < `.pi/settings.json` (project, trust-gated) |
| Run state / cross-harness bus | shepherd-owned — `.shepherd/runs/{run}/` | consumes shepherd's filesystem contract only — "the filesystem is the only bridge… one canonical run" | not integrated; no native run-state concept, adapter-authored same as Codex |

## Pi probe — closes seed open question 4

All four CONFIRMED-BY-PROBE against the installed 0.84.1 binary and its bundled docs.

- **`--tools` is a REPLACING allowlist.** Verbatim: "Comma-separated allowlist of tool
  names to enable. Applies to built-in, extension, and custom tools." Only the named
  tools are enabled. `--no-builtin-tools, -nbt` exists independently ("Disable built-in
  tools by default but keep extension/custom tools enabled"); `--no-tools, -nt` disables
  all by default. **Seed open question 4 is answered — the doc-only caveat can close.**
- **Extension loading is jiti, confirmed twice.** (1) `package.json` of
  `@earendil-works/pi-coding-agent@0.84.1` lists `"jiti": "2.7.0"` as a direct runtime
  dep; (2) bundled `docs/extensions.md`: "Extensions are loaded via jiti… TypeScript
  works without compilation." Entry point: default-exported factory
  `(pi: ExtensionAPI) => void | Promise<void>`, from `~/.pi/agent/extensions/*.ts` or
  `.pi/extensions/*.ts` (trust-gated), single-file or `index.ts`, or an npm/git package
  declaring `"pi": {"extensions": ["./src/index.ts"]}`. `pi -e <path>` loads one file.
- **Native concepts:** slash commands native; skills native; hooks NOT a module;
  teams/subagents absent natively; named roles absent as a file format.
- **Guard surface:** `tool_call` fires after `tool_execution_start`, before execution;
  handler receives `{toolName, toolCallId, input}` with `input` mutable in place; return
  `{block: true, reason?, terminate?}` to deny. `terminate` applies only if every
  finalized result in the batch is terminating.

## Codex surface

Source: locally installed `codex-cli 0.147.0` + live `~/.codex/config.toml`,
`~/.codex/AGENTS.md`, `~/.codex/skills/`. No web fetch needed.

- **Config:** `~/.codex/config.toml` (TOML); `-c key=value` dotted overrides;
  `--profile <name>` layers `$CODEX_HOME/<name>.config.toml`; `--strict-config` errors on
  unrecognized fields.
- **AGENTS.md:** present and populated (16 KB) at `~/.codex/AGENTS.md`.
- **Subagents:** `multi_agent = stable, true`; `multi_agent_v2 = stable, false`;
  `subagent_start`/`subagent_stop` hooks live.
- **Hooks:** `hooks = stable, true`; `--dangerously-bypass-hook-trust` confirms
  trust-gating. Ten events keyed `"<plugin>@<marketplace>:hooks/hooks.json:<event>:…"`:
  `session_start`, `session_end`, `stop`, `pre_tool_use`, `post_tool_use`, `pre_compact`,
  `post_compact`, `subagent_start`, `subagent_stop`, `user_prompt_submit`.
  **Codex reads the same relative path shepherd already uses: `hooks/hooks.json`.**
- **Skills:** native, populated, with `skill_search` + `skill_mcp_dependency_install`.
- **Marketplace:** `codex plugin {add,list,marketplace,remove}`. `~/.codex/config.toml`
  carries a live `[marketplaces.codex-shepherd]` → `https://github.com/FL03/codex-shepherd.git`
  (synced `2026-08-08T21:55:34Z`, rev `2fe3e092`) — **the sibling port is installed and
  running as a real Codex plugin on this machine right now.**

## Sibling port evidence (codex-shepherd v1.0.2)

**#277 — durable run-local support directories.** The canonical run layout had no
destination for run-scoped design docs, diagrams, checks, assets, or continuity; those
spilled into cross-run `.shepherd/docs/`, `.shepherd/scripts/`, `.shepherd/ctx/`,
breaking the run boundary as soon as a second harness touched the project. Adds
`assets/`, `docs/`, `figures/`, `learnings/`, `memory/`, `scripts/` with promotion rules.

**#278 — run-scoped graph state mandatory.** `shepherd plan extract` without `--run`
silently wrote flat `.shepherd/graph/` instead of failing closed, and `--help` did not
expose `--run`. Project-global state was polluted and had to be stripped from a release
candidate by hand. Contract: every graph write requires an unambiguous run id or fails
closed with `RUN-REQUIRED`.

**`docs/parity.md` — what actually broke:**

1. **Write ownership is incompatible.** "Read-only role reports return to the root for
   materialization because Codex explorers do not own files." Claude subagents can
   `Write` in a scoped path; Codex `explorer` cannot write at all. Every read-only
   shepherd role (`discovery`, `critic`, `auditor`, `planter`) had report materialization
   moved to the parent. Structural, not cosmetic.
2. **Harness skill fully REPLACED, not translated.** Agent Teams, Dynamic Workflow,
   `SendMessage`, teammate events have zero Codex counterpart; the port binds to Codex
   `spawn_agent` + lifecycle hooks + a hard **3 pending/live descendant global cap**.
3. **Deferred entirely:** `/shepherd:*` commands and aliases; the SQLite `shctx` registry,
   symbol graph, GitHub cache, rendered views; tmux/worktree lifecycle; Agent
   Teams/Workflow adapters; `/loop`, `/goal`, soak, sentinel; prompt-cache telemetry and
   Claude model pins; automatic environment install; automated GH milestone/issue mutation.
4. **Codex-only mechanisms with no Claude analog:** MultiAgent V2 encrypts the child
   message before `PreToolUse` and appends a random `_sb_<16hex>` suffix to the effective
   task name so parallel same-type children disambiguate without Claude's
   `session_meta`/FIFO binding. `shepherd.codex.toml` supplies hook-injected per-role
   model profiles (Sol/max for planter+engineer, Terra elsewhere).
5. **Compaction/continuity differs.** Atomic `PLUGIN_DATA` state + compact rehydration is
   Codex's own primitive, distinct from `run.json` continuity.
6. **Role/skill drift already happened.** Codex has a `plant` skill with **no Claude-side
   source**; Claude's `adaptation` became Codex's `adapt` + `self-improvement`
   unilaterally.

## Core vs adapter split

**(a) MUST live in shared core — identical semantics required across all three:**
guard-predicate evaluation (seed decision 2); run state / `run.json` canonical shape,
atomic write, config-precedence resolution (decision 12); registry schema (decision 3);
the abstract role/capability vocabulary (`read`, `search`, `shell`, `report-write`,
`dispatch`) so `content/roles/*.md` compiles identically regardless of tool naming;
migration SQL (decision 6) and the conformance oracle (#281).

**(b) genuinely per-harness adapter work:** dispatch transport (Agent Teams vs
`spawn_agent`+3-cap vs child-process-per-role with `SHEPHERD_ROLE`); write-boundary
enforcement *mechanism* (tools: frontmatter vs explorer/worker binary split vs
`--tools`/`--no-builtin-tools` at spawn); slash-command emission; per-role model pinning
(frontmatter vs subprocess `--model` vs `shepherd.codex.toml` two-tier); skill emission
plus each harness's differing trust gate.

**(c) native-model incompatibilities — the real port hazards:** write ownership;
concurrency ceiling; model-pin granularity (Pi `setModel()` is session-global → one
subprocess per role, so role-switch = process spawn); no native Pi team primitive; Pi's
guard layer is a second real interpreter, kept in lockstep by discipline not
construction; Codex hook taxonomy already diverges; config tier counts differ 4/3/2.

## Hazards (ranked by blast radius)

1. **Write-boundary mismatch** — Codex `explorer` cannot write, so every read-only
   shepherd role's contract breaks unless `content/roles/*.md` encodes write-eligibility
   as a hard fact. Threatens `content/roles/*.md` and every `hooks/scripts/*guard*.sh`.
2. **Pi has zero native team/subagent primitive**; only an unvetted third-party
   extension. Threatens the Pi adapter's whole dispatch row and the lane fan-out model.
3. **Codex 3-descendant global cap desyncs from Stage Graph wave sizing** tuned for
   Agent Teams. Threatens `crates/core` scheduling semantics.
4. **Pi per-role pinning forces one subprocess per role**, inverting the cost model
   `model:` frontmatter assumes.
5. **Hook-event taxonomies diverge** (Codex has 4–5 events Claude lacks; `PreCompact`
   splits into `pre_compact`/`post_compact`) with no mapping table defined. Threatens
   "guard predicates are data" (decision 2).
6. **Pi `--tools` is strict-replacing, not additive** — a compiler assuming "built-ins
   minus a few" silently under-provisions every Pi role.
7. **Config tier-count mismatch (4/3/2)** — threatens `loader.rs` if it assumes every
   harness fills all four tiers.
8. **Role/skill drift already happened once for real** — "author once, compile per
   harness" cannot start from a drifted baseline; the `content/` migration needs an
   explicit reconciliation pass against *current* codex-shepherd, not just future
   drift prevention.

## Residual / UNVERIFIED

1. **Codex custom-prompt/command directory** — not located this pass; no bare
   `~/.codex/prompts/` found. Gates the content compiler's Codex slash-command emitter.
   *Closed by the engineer post-hoc — see `## Engineer follow-up` below.*
2. **Whether `crates/core/loader.rs`'s 4-tier chain degrades gracefully** for harnesses
   with fewer real tiers (Codex 3, Pi 2). Carried into the plan as a step acceptance.

## Engineer follow-up — residual 1 CLOSED

Root flagged residual 1 as load-bearing (it gates the content compiler's Codex
slash-command emitter). The engineer probed the installed `codex-shepherd@1.0.2`
bundle directly. **Answer: there is no Codex slash-command surface at all.**

Bundle contract, from `~/.codex/plugins/cache/codex-shepherd/codex-shepherd/1.0.2/`:

```
.codex-plugin/plugin.json     # declares ONE component path: "skills": "./skills/"
hooks/                        # hooks.json + *.py (Python, not shell)
scripts/
skills/
shepherd.codex.toml
```

No `prompts/`, no `commands/`, no `agents/`. `~/.codex/prompts` and `~/.codex/commands`
do not exist on this box either. So the parity doc's "`/shepherd:*` slash commands
deferred" is **structural, not a scoping choice** — Codex has nowhere to put one.

**Compiler consequence:** `content/` emits a command surface for Claude
(`commands/*.md`) and Pi (`~/.pi/agent/prompts/*.md`) ONLY. Emitting a Codex command
target is a defect, not a gap.

Three further primary-evidence facts from `shepherd.codex.toml`:

- `max_concurrent_children = 3` — the 3-descendant cap is **declared in config**,
  confirming the parity doc from source rather than by report.
- `[agent_types]` maps all 8 shepherd roles onto exactly **two** Codex primitives
  (`explorer` = read-only, `worker` = write). **Roles compile to a TOML table, not
  files** — `agents/*.md` has no Codex counterpart, which is the mechanism behind
  Hazard 1 (write ownership).
- `[models]`/`[profiles]` carry `reasoning_effort` (`sol/max`, `terra/high`,
  `terra/medium`), which Claude's `model:` frontmatter pin cannot express.

**Hazard 8 drift matrix, now concrete** (Claude tree vs installed Codex 1.0.2):

| Claude | Codex | Reconciliation needed |
|---|---|---|
| `skills/adaptation` | `adapt` + `self-improvement` | 1→2 split, unilateral |
| `skills/harness` | absent | Claude-only by design — confirm, don't emit |
| `commands/plant.md` + `agents/planter.md` | `skills/plant` | command+agent → skill |
| 9 × `agents/*.md` | zero role files | → `[agent_types]` TOML table |
| 7 skills | 8 skills | net +1 |

This matrix is the input to the `content/` reconciliation step in the plan; it is a
numbered step with runnable acceptance, not a prose note.
