// packages/harness-pi/src/tools.mjs -- closes content/RECONCILIATION.md's Pi `--tools`
// column, deliberately left a pointer there ("a later-wave Pi adapter names the concrete
// tool"). Confirmed against the actual installed @earendil-works/pi-coding-agent@0.84.1
// binary's own tool registry (/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent
// /dist/core/tools/index.js: `allToolNames = new Set(["read","bash","edit","write","grep",
// "find","ls"])`) -- the real source, not `--help` text alone. `--tools` is a REPLACING
// allowlist (discovery-d1-harness.md's Pi probe, confirmed twice against primary docs in
// discovery-harness-portability.md), so PI_TOOLS_BY_CAPABILITY must enumerate every tool a
// capability needs, and a role's full set is the union over ALL its capabilities -- never a
// subtractive "built-ins minus a few."

export const PI_BUILTIN_TOOLS = Object.freeze(["read", "bash", "edit", "write", "grep", "find", "ls"]);

// Capabilities with NO Pi tool at all -- verified absent from PI_BUILTIN_TOOLS above, and no
// bundled extension supplies one either (dist/extensions/ ships only a `llama` model-provider
// extension, no task/web/dispatch/ask/schedule/LSP tool). Each is a genuine harness gap
// (discovery-harness-portability.md §4 portability verdict), declared here rather than mapped
// to a plausible-looking but invented tool name.
export const PI_UNSUPPORTED_CAPABILITIES = Object.freeze([
  "skill-load", // native via --skill discovery/flag, not an invocable tool
  "tool-discovery", // no Pi equivalent of Claude's ToolSearch
  "dispatch", // no native subagent primitive (discovery-d1-harness.md)
  "message-peer", // no mailbox/SendMessage primitive
  "task-tracking", // no shared task-list primitive
  "web-research", // no builtin web fetch/search tool
  "ask-operator", // no interactive-question primitive distinct from normal chat
  "schedule-wakeup", // no scheduling primitive
  "code-intelligence", // pi-lens LSP is a CLI flag (--no-lsp), not a --tools name
]);

const PI_TOOLS_BY_CAPABILITY = Object.freeze({
  read: ["read"],
  search: ["grep", "find"],
  shell: ["bash"],
  write: ["write", "edit"],
  // Same tool as `write` -- Pi's allowlist has no path-scoped write primitive; the narrower
  // report-write SCOPE is enforced by src/extension.ts's guard layer, not by tool selection.
  "report-write": ["write"],
});

/**
 * @param {string[]} capabilities a role's content/roles/*.md `capabilities` list.
 * @returns {{tools: string[], unsupported: string[]}} `tools` is the full REPLACING set for
 *   `--tools`, deduped, order preserved by first occurrence; `unsupported` lists capabilities
 *   this role has that Pi cannot grant at all.
 */
export function resolvePiTools(capabilities) {
  const seen = new Set();
  const tools = [];
  const unsupported = [];
  for (const capability of capabilities) {
    if (PI_UNSUPPORTED_CAPABILITIES.includes(capability)) {
      unsupported.push(capability);
      continue;
    }
    const mapped = PI_TOOLS_BY_CAPABILITY[capability];
    if (!mapped) {
      throw new Error(`unknown capability \`${capability}\` -- not present in content/RECONCILIATION.md's vocabulary table`);
    }
    for (const tool of mapped) {
      if (!seen.has(tool)) {
        seen.add(tool);
        tools.push(tool);
      }
    }
  }
  return { tools, unsupported };
}
