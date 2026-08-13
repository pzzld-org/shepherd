# @fl03/harness-pi

`packages/harness-pi` is the thin adapter over `@fl03/compiler`'s `pi` emission target for the
`@earendil-works/pi-coding-agent` CLI: `~/.pi/agent/prompts/*.md` slash commands (filename
becomes `/name`), `~/.pi/agent/skills/` (or the project-local `.pi/skills/` variant), and a
TypeScript extension loaded via jiti as a default-exported
`(pi: ExtensionAPI) => void | Promise<void>` (confirmed against the installed 0.84.1 binary and
its bundled docs -- TypeScript works without a compile step). Pi has no hook module at all
("hooks do not exist as a module, they are extensions"), so this is the one adapter of the
three that must re-interpret the shared predicate spec as a second real TypeScript
interpreter -- `pi.on('tool_call', ...)` fires after `tool_execution_start` and before
execution, receives `{toolName, toolCallId, input}` with `input` mutable in place, and returns
`{block, reason?, terminate?}` to deny -- kept in lockstep with the Rust evaluator by a shared
allow/deny case corpus, not by discipline (decision 1). Two further per-harness constraints this
adapter must honor: `--tools` is a **replacing**, not additive, allowlist, so every role's full
desired tool set must be enumerated explicitly (never "built-ins minus a few"); and Pi has no
native team/subagent primitive, so multi-agent dispatch is declared absent here rather than
emulated via the unvetted third-party `@tintinweb/pi-subagents` extension. `setModel()` is
session-global, meaning per-role model pinning costs one subprocess per role rather than a
frontmatter flag. Implemented in Wave 4 (W4-S6); this package is the npm workspace skeleton
only -- no adapter logic yet.
