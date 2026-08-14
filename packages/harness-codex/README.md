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
- `src/predicates.mjs` + `src/toml-lite.mjs` -- a hand-rolled reader/interpreter of
  `content/predicates/*.toml`'s declarative guard spec (decision 2: shared data, one
  interpreter's worth of logic per harness). `test/predicates.test.mjs` loads every one of the
  four files' own `[[example]]` blocks and asserts `evaluate()` reproduces every declared
  `allow`/`deny` result -- including a documented fix for `write-boundary.toml`'s rule 1,
  which reads "denied outright" but is contradicted by its own worked example (see
  `src/predicates.mjs`'s module header).
- `src/guard.mjs` -- the pure decision core behind `hooks/scripts/shepherd_guard.mjs`, wiring
  `write-boundary` (via `apply_patch`) and `git-custody` (via `Bash` git-subcommand parsing,
  read-only verbs excluded). **Named gap**, not a silent no-op: `dedup-gate` and
  `dispatch-scope` are loaded and fully evaluable (proven against the corpus in
  `test/predicates.test.mjs`) but not yet live-hooked, because their context (a dedup-registry
  hit lookup; a dispatcher's role/tier from a Codex-side dispatch record) needs infrastructure
  this step's file scope doesn't include -- no Codex-side analog of
  `hooks/scripts/agent_invocation_tagger.sh` exists yet to tag a `spawn_agent` call with the
  acting role, so this adapter trusts a `SHEPHERD_ROLE` env var and fails OPEN on an
  unset/unrecognized role, exactly like every existing Claude-side guard does for a dispatch it
  cannot identify. Closing that gap is `spawn_agent` interception work (W4-S1's "auto-wire the
  launcher" or a dedicated follow-up), not this adapter's.
- `hooks/hooks.json` + `hooks/scripts/shepherd_guard.mjs` -- the live PreToolUse wiring, same
  `{"permissionDecision":"deny","message":"..."}` JSON contract Claude's own
  `hooks/scripts/_lib.sh` and the installed `codex-shepherd@1.0.2` bundle's `shepherd_hook.py`
  both already use.
- `bin/apply.mjs` -- CLI: `node bin/apply.mjs [--dir=<targetDir>] [--check]`.
- `shepherd.codex.toml`, `skills/**` -- the real materialized output, regenerate via
  `npm run apply` (or `node bin/apply.mjs`) after any `content/` change.

Implemented in Wave 4 (W4-S5).
