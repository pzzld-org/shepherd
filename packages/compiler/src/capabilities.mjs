// packages/compiler/src/capabilities.mjs -- the abstract capability vocabulary
// (content/RECONCILIATION.md §Capability vocabulary) mapped onto Claude's concrete tool
// grants. This table is transcribed verbatim from that section, which is the one place in
// content/ authorized to name a concrete Claude tool token.
//
// Pi's column is deliberately NOT encoded here: RECONCILIATION.md leaves it a pointer
// ("later-wave Pi adapter names the concrete tool") because the discovery report never
// enumerated Pi's own tool names per capability -- inventing them would be exactly the
// unverified claim the coder protocol forbids. compile('pi') therefore carries each role's
// `capabilities` list through unchanged; packages/harness-pi (W4-S6) closes that column
// against the live binary.

/** @type {Record<string, string[]>} */
export const CLAUDE_TOOLS_BY_CAPABILITY = Object.freeze({
  read: ["Read", "NotebookRead"],
  search: ["Glob", "Grep"],
  shell: ["Bash"],
  write: ["Write", "Edit"],
  "report-write": ["Write"],
  "skill-load": ["Skill"],
  "tool-discovery": ["ToolSearch"],
  dispatch: ["Agent", "Workflow"],
  "message-peer": ["SendMessage"],
  "task-tracking": ["TaskCreate", "TaskGet", "TaskList", "TaskUpdate"],
  "web-research": ["WebFetch", "WebSearch"],
  "ask-operator": ["AskUserQuestion"],
  "schedule-wakeup": ["ScheduleWakeup"],
  "code-intelligence": ["LSP"],
});

/**
 * Maps a role's abstract capability list onto Claude's concrete `tools:` frontmatter value,
 * deduped, order preserved by first occurrence (deterministic given a deterministic input).
 *
 * @param {string[]} capabilities
 * @returns {string[]}
 */
export function capabilitiesToClaudeTools(capabilities) {
  const seen = new Set();
  const tools = [];
  for (const capability of capabilities) {
    const mapped = CLAUDE_TOOLS_BY_CAPABILITY[capability];
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
  return tools;
}
