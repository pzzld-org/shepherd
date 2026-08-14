# @fl03/harness-codex

`packages/harness-codex` is the thin adapter over `@fl03/compiler`'s `codex` emission target.
Codex reads only `skills/` + `hooks/hooks.json` (the same relative path shepherd already uses)
+ `shepherd.codex.toml` -- confirmed against the installed `codex-shepherd@1.0.2` bundle, which
has no `prompts/`, `commands/`, or `agents/` directory at all, so emitting a Codex command
surface is a defect, not a gap (`test/materialize.test.mjs` asserts this directly). Roles do
not compile to files the way Claude's `agents/*.md` do; they compile to one `[agent_types]`
TOML table mapping all 8 shepherd roles onto exactly two Codex primitives, `explorer`
(read-only) and `worker` (write-capable) -- every `write_eligible: false` role from
`content/roles/*.md` compiles to `explorer`, never `worker`, because a Codex `explorer` cannot
write at all (`packages/compiler/src/targets/codex.mjs` enforces this; this adapter consumes
that tree verbatim). This adapter declares, rather than discovers at runtime, Codex's hard
`max_concurrent_children = 3` global descendant cap (compiler-emitted) plus its own per-role
`[models]`/`[profiles."<name>"]` `reasoning_effort` pins (`src/model-profile.mjs`) -- a
model-pin granularity Claude's `model:` frontmatter enum cannot express, resolved from
content/roles/*.md's own `model_hint` rather than any Claude-specific model token (so
`opus[1m]`'s `[1m]` context-window suffix, Claude-Code-specific, never leaks into a Codex
profile name).

## Layout

- `src/materialize.mjs` -- `buildCodexTree()` (compile('codex') + this adapter's own
  `[models]`/`[profiles.*]` augmentation, byte-identical across calls -- proven in
  `test/reproducibility.test.mjs`) and `materialize(targetDir)` (writes the tree to disk,
  default this package's own root, so `shepherd.codex.toml` + `skills/**` below are real,
  committed files, not just code that could produce them).
- `src/model-profile.mjs` -- `model_hint` -> Codex `[profiles."<name>"]` resolution.
- `src/dispatch-record.mjs` -- Codex's own analog of
  `hooks/scripts/agent_invocation_tagger.sh` + `current_role()` (DF-75). No Claude-shaped
  identifier exists at Codex's spawn time (`agent_id` is runtime-assigned only once
  `spawn_agent`/`collaborationspawn_agent` returns), so this module tags a spawned agent at
  `PostToolUse(spawn_agent|collaborationspawn_agent)` -- where the original `tool_input`
  (role-bearing `task_name`/`message`) and the `tool_response` (the assigned `agent_id`) are
  both present in one event -- and resolves it back on every later guarded call, which carries
  `agent_id` on its own `PreToolUse` payload. See this module's own header for the three
  independent sources that verified this wire shape (a discovery report, the installed
  `codex-shepherd@1.0.2` sibling's own working code, and `strings` on the installed `codex`
  binary) rather than assuming it.
- `src/guard.mjs` -- DF-75/CRITICAL fixed here: the previous `decideForToolCall` opened with
  `if (!role) return { result: "allow" }`, where `role` came from a `SHEPHERD_ROLE` env var
  nothing set for a Codex subprocess -- every branch fell through to allow, permanently. Now a
  thin relay (mirrors `packages/harness-claude/src/guard.mjs`'s own shape): `buildGuardDecision`
  resolves role via `src/dispatch-record.mjs` (no marker -> allow without touching the engine;
  marker + no record -> deny, loudly, the exact case that used to be a silent allow; marker +
  resolved role -> forward to the engine) and never interprets a predicate itself. Interpretation
  collapsed onto the shared `shepherd guard eval` engine (`services/cli/shepherd_cli/predicates.py`)
  -- the two prior hand-rolled interpreters this package carried (`src/predicates.mjs`,
  `src/toml-lite.mjs`, plus a third copy of the git-subcommand tokenizer inside this file) are
  deleted; that engine owns all three now, replaying every `content/predicates/*.toml`
  `[[example]]` itself (`shepherd guard test`).
- `hooks/hooks.json` + `hooks/scripts/shepherd_guard.mjs` -- the live wiring:
  `PostToolUse(spawn_agent|collaborationspawn_agent)` tags the spawn; `PreToolUse(apply_patch|Bash)`
  guards writes. Wire format verified, not assumed identical to Claude's own flat
  `{"permissionDecision":"deny",...}` shape: Codex's real `PreToolUse` deny is
  `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}`
  -- confirmed against the installed `codex-shepherd@1.0.2` bundle's own `protocol.py`/tests
  AND against `strings` on the installed `codex` binary itself (`src/guard.mjs`'s module header
  has the full citation trail).
- `bin/apply.mjs` -- CLI: `node bin/apply.mjs [--dir=<targetDir>] [--check]`.
- `shepherd.codex.toml`, `skills/**` -- the real materialized output, regenerate via
  `npm run apply` (or `node bin/apply.mjs`) after any `content/` change.

Implemented in Wave 4 (W4-S5); guard made real in v6.4.5 W10 (DF-75).
