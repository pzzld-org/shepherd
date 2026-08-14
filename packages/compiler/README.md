# @fl03/compiler

`packages/compiler` is the pure emitter that turns `content/` -- the single-source-of-truth
tree of `content/roles/*.md` (with a `write_eligible` fact per role) and
`content/skills/*/SKILL.md` authored in W0-S8 -- into the concrete artifact tree each harness
actually reads. Its whole public surface (`src/compile.mjs`) is
`compile(target: 'claude' | 'codex' | 'pi') -> EmittedTree`: Claude gets `agents/*.md` (all 9
roles -- Claude has no dispatch table, only files) + `skills/*/SKILL.md`; Codex gets *only*
`shepherd.codex.toml` (one `[agent_types]` table, root excluded, `write_eligible` selecting
`explorer`/`worker`, `max_concurrent_children = 3` declared) + `skills/`, and **no** command,
prompt, or per-role-file surface at all -- confirmed against the installed
`codex-shepherd@1.0.2` bundle, not assumed (`packages/compiler/test/codex-no-command-surface.test.mjs`);
Pi gets `prompts/*.md` (all 9 roles, mirroring Claude's per-file shape) + `skills/`, with each
role's abstract `capabilities` list carried through unresolved -- Pi's `--tools` concrete
mapping is a later-wave adapter's job, not this compiler's. This package is a plain
tree-to-tree emitter, never a second template engine -- `crates/render` owns templating, and
the compiler's job stops at mapping the abstract capability vocabulary (`read`, `search`,
`shell`, `report-write`, `dispatch`, ...) onto each harness's concrete mechanism.

`compile()` never writes to disk -- it returns an in-memory `EmittedTree` (see
`src/tree.mjs` for the exact shape); the three harness adapters (`packages/harness-claude`,
`packages/harness-codex`, `packages/harness-pi`, W4-S4/S5/S6) are the ones that materialize it
onto their own package directories. `compile()` is a pure function of `content/`: two calls
produce byte-identical output (`test/reproducibility.test.mjs`), which is also the CLI's
`--check` semantics:

```
node packages/compiler/bin/compile.mjs --target=<claude|codex|pi> [--check] [--list]
```

Implemented in Wave 4 (W4-S3).

## `content/predicates/*.toml`

Guard-predicate specs are shared data the Rust engine and Pi's TS layer interpret directly
(decision 2, `discovery-d1-harness.md` §Core vs adapter split); they are not part of any
target's `EmittedTree` and this compiler does not parse them -- "wiring the guard layer" is
W4-S4/S5/S6's job, over `content/predicates/` directly.
