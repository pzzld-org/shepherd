# @fl03/harness-claude

`packages/harness-claude` is the thin adapter over `@fl03/compiler`'s `claude` emission
target -- the native Claude Code plugin surface: declarative role files (`agents/*.md`
frontmatter -- `name`, `model`, `tools`, `color`), `commands/*.md` slash commands,
`skills/*/SKILL.md`, and `hooks/hooks.json` (matcher-based tool-call interception that shells
out to scripts). Claude is the harness with native Agent Teams and a native Workflow tool, so
this adapter's guard layer does not need a second interpreter the way Pi's does: hooks shell
out to the shared Rust predicate evaluator directly. Its distinguishing constraint versus the
other two adapters is `model:` being a closed enum (`sonnet | opus | haiku | fable`) rather than
Codex's `reasoning_effort` profiles or Pi's session-global `setModel()`. Logic identical across
two or more adapters belongs in `@fl03/compiler` or the shared Rust core, never duplicated here
-- this package stays thin. Implemented in Wave 4 (W4-S4); this package is the npm workspace
skeleton only -- no adapter logic yet.
