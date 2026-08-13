# @fl03/compiler

`packages/compiler` is the pure emitter that turns `content/` -- the single-source-of-truth
tree of `content/roles/*.md` (with a `write_eligible` fact per role), `content/skills/*/SKILL.md`,
and `content/predicates/*.toml` authored in W0-S8 -- into the concrete artifact tree each
harness actually reads. Its whole public surface is `compile(target: 'claude' | 'codex' | 'pi')
-> EmittedTree`: Claude gets `agents/*.md` + `commands/*.md` + `skills/*/SKILL.md` +
`hooks/hooks.json`; Codex gets *only* `skills/` + `hooks/hooks.json` + `shepherd.codex.toml`,
with roles mapped onto its two native primitives (`explorer` read-only, `worker` write-capable)
and `write_eligible: false` enforced against ever compiling to a `worker`; Pi gets
`~/.pi/agent/prompts/*.md` slash commands, skills, and TypeScript extensions -- Codex receives
no command surface at all, because it has nowhere to put one (confirmed against the installed
`codex-shepherd@1.0.2` bundle, not assumed). This package is a plain tree-to-tree emitter, never
a second template engine -- `crates/render` owns templating, and the compiler's job stops at
mapping the abstract capability vocabulary (`read`, `search`, `shell`, `report-write`,
`dispatch`) onto each harness's concrete mechanism. Implemented in Wave 4 (W4-S3); this package
is the npm workspace skeleton only -- no parsing, emission, or `compile()` implementation yet.
