// packages/compiler/src/targets/claude.mjs -- Claude Code target: `agents/<role>.md` for
// every role (all 9 -- Claude has no dispatch TABLE the way Codex does, only files, so root
// (`shepherd`) and the meta-tier `planter` are files here exactly like every other role; see
// content/RECONCILIATION.md row 4, which excludes root from a *compiled table*, a concept
// Claude doesn't have) plus `skills/<name>/SKILL.md` for every skill this harness may load.

import { capabilitiesToClaudeTools } from "../capabilities.mjs";
import { array, field, quoted, renderFrontmatterFile } from "../markdown.mjs";
import { emitSkillFile, shouldEmitSkillFor } from "../skill-emit.mjs";

/**
 * @param {{roles: import("../content.mjs").Role[], skills: import("../content.mjs").Skill[]}} content
 * @returns {import("../tree.mjs").EmittedFile[]}
 */
export function emitClaude({ roles, skills }) {
  const files = roles.map((role) => emitRoleFile(role));
  for (const skill of skills) {
    if (shouldEmitSkillFor("claude", skill)) files.push(emitSkillFile(skill));
  }
  return files;
}

function emitRoleFile(role) {
  const tools = capabilitiesToClaudeTools(role.capabilities);
  const content = renderFrontmatterFile(
    [
      field("name", role.role),
      // `model_hint`, not a resolved `model:` value: mapping the abstract hint onto
      // Claude's closed `sonnet|opus|haiku|fable` enum is per-harness adapter work
      // (discovery-d1-harness.md §Core vs adapter split (b)), not something content/
      // itself encodes.
      field("model_hint", role.modelHint),
      field("tools", array(tools)),
      field("dispatchable", String(role.dispatchable)),
      field("write_eligible", String(role.writeEligible)),
      field("write_scope", quoted(role.writeScope)),
    ],
    role.body
  );
  return { path: `agents/${role.role}.md`, kind: "role", content, sourcePath: `content/roles/${role.role}.md` };
}
