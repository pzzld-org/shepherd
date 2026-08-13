# @fl03/harness-codex

`packages/harness-codex` is the thin adapter over `@fl03/compiler`'s `codex` emission target.
Codex reads only `skills/` + `hooks/hooks.json` (the same relative path shepherd already uses)
+ `shepherd.codex.toml` -- confirmed against the installed `codex-shepherd@1.0.2` bundle, which
has no `prompts/`, `commands/`, or `agents/` directory at all, so emitting a Codex command
surface is a defect, not a gap. Roles do not compile to files the way Claude's `agents/*.md`
do; they compile to one `[agent_types]` TOML table mapping all 8 shepherd roles onto exactly
two Codex primitives, `explorer` (read-only) and `worker` (write-capable) -- every
`write_eligible: false` role from `content/roles/*.md` MUST compile to `explorer`, never
`worker`, because a Codex `explorer` cannot write at all (the structural hazard behind
read-only shepherd roles like `discovery`, `critic`, `auditor`, and `planter` having their
report materialization moved to the parent). This adapter also declares, rather than
discovers at runtime, Codex's hard `max_concurrent_children = 3` global descendant cap and
per-role `reasoning_effort` profiles (`sol/max`, `terra/high`, `terra/medium`) -- a model-pin
granularity Claude's `model:` frontmatter enum cannot express. Implemented in Wave 4 (W4-S5);
this package is the npm workspace skeleton only -- no adapter logic yet.
