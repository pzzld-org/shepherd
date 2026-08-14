// packages/compiler/src/skill-emit.mjs -- skill emission is identical structurally across
// all three targets (a `skills/<name>/SKILL.md` file, verbatim body, portability-filtered),
// so it lives here once rather than being re-implemented per src/targets/*.mjs
// (content/RECONCILIATION.md §Residual: only `harness` is claude-only; the other six skills,
// `cross-harness` or `unverified`, emit everywhere -- an `unverified` skill's Codex-side
// NUMBERS are unverified, not its harness-neutral prose, per that section's own resolution).

import { field, renderFrontmatterFile } from "./markdown.mjs";

/**
 * @param {"claude"|"codex"|"pi"} target
 * @param {import("./content.mjs").Skill} skill
 * @returns {boolean}
 */
export function shouldEmitSkillFor(target, skill) {
  if (skill.portability === "claude-only") return target === "claude";
  return true;
}

/**
 * @param {import("./content.mjs").Skill} skill
 * @returns {import("./tree.mjs").EmittedFile}
 */
export function emitSkillFile(skill) {
  // No `description` field: content/skills/*/SKILL.md carries only `name`/`source`/
  // `portability` (W0-S8's scope) -- a harness-specific description belongs to whichever
  // adapter step actually needs one, not fabricated here without a content/ source.
  const content = renderFrontmatterFile([field("name", skill.name)], skill.body);
  return {
    path: `skills/${skill.name}/SKILL.md`,
    kind: "skill",
    content,
    sourcePath: `content/skills/${skill.name}/SKILL.md`,
  };
}
