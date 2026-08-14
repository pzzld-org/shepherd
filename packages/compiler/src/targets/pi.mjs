// packages/compiler/src/targets/pi.mjs -- Pi target. Pi has no file-declared-role primitive
// either (discovery-d1-harness.md capability matrix: "absent as file-declared roles; a role
// = a CLI invocation"), but unlike Codex it *does* have a native per-file prompt mechanism
// (`~/.pi/agent/prompts/*.md` / `.pi/prompts/*.md`, filename -> `/name`) that is the closest
// available carrier for a role's system-prompt content, so each role emits there -- every
// role, all 9, mirroring Claude's file-per-role shape rather than Codex's single table,
// because content/ has no evidence Pi's own dispatch model draws the same root/table
// distinction Codex's `[agent_types]` does (no primary source for that was probed this pass;
// see discovery-d1-harness.md §Residual). `capabilities` is carried through as the raw
// abstract vocabulary list, unresolved: RECONCILIATION.md's vocabulary table leaves Pi's
// `--tools` column a pointer on purpose ("a later-wave Pi adapter names the concrete tool"),
// so resolving it here would be exactly the unverified claim the coder protocol forbids.

import { array, field, quoted, renderFrontmatterFile } from "../markdown.mjs";
import { emitSkillFile, shouldEmitSkillFor } from "../skill-emit.mjs";

/**
 * @param {{roles: import("../content.mjs").Role[], skills: import("../content.mjs").Skill[]}} content
 * @returns {import("../tree.mjs").EmittedFile[]}
 */
export function emitPi({ roles, skills }) {
  const files = roles.map((role) => emitRolePrompt(role));
  for (const skill of skills) {
    if (shouldEmitSkillFor("pi", skill)) files.push(emitSkillFile(skill));
  }
  return files;
}

function emitRolePrompt(role) {
  const content = renderFrontmatterFile(
    [
      // No `description`/`argument-hint`: Pi's native prompt frontmatter supports both
      // (discovery-d1-harness.md capability matrix), but content/roles/*.md carries neither
      // -- adding them here would be inventing data, not emitting it.
      field("name", role.role),
      field("capabilities", array(role.capabilities)),
      field("dispatchable", String(role.dispatchable)),
      field("write_eligible", String(role.writeEligible)),
      field("write_scope", quoted(role.writeScope)),
    ],
    role.body
  );
  return { path: `prompts/${role.role}.md`, kind: "role", content, sourcePath: `content/roles/${role.role}.md` };
}
