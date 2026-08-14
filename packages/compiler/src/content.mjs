// packages/compiler/src/content.mjs -- loads the two content/ record types the compiler
// consumes: content/roles/*.md (content/roles/coder.md et al, the W0-S8 single source of
// truth) and content/skills/*/SKILL.md. Both are read-only inputs -- this module never
// writes into content/.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { parseFrontmatter } from "./frontmatter.mjs";

/**
 * @typedef {object} Role
 * @property {string} role
 * @property {string} source
 * @property {string} modelHint
 * @property {boolean} writeEligible
 * @property {boolean} dispatchable
 * @property {string[]} capabilities
 * @property {string} writeScope
 * @property {string} body
 */

/**
 * @typedef {object} Skill
 * @property {string} name
 * @property {string} source
 * @property {"cross-harness"|"claude-only"|"unverified"} portability
 * @property {string} body
 */

const REQUIRED_ROLE_FIELDS = ["role", "write_eligible", "dispatchable", "capabilities"];
const REQUIRED_SKILL_FIELDS = ["name", "portability"];
const VALID_PORTABILITY = new Set(["cross-harness", "claude-only", "unverified"]);

/**
 * @param {string} contentDir absolute path to the `content/` directory.
 * @returns {Role[]} sorted by `role`, ascending -- emission order must be deterministic.
 */
export function loadRoles(contentDir) {
  const dir = join(contentDir, "roles");
  const roles = readdirSync(dir)
    .filter((f) => f.endsWith(".md"))
    .map((f) => parseRoleFile(join(dir, f), f));
  roles.sort((a, b) => a.role.localeCompare(b.role));
  return roles;
}

/**
 * @param {string} contentDir absolute path to the `content/` directory.
 * @returns {Skill[]} sorted by `name`, ascending.
 */
export function loadSkills(contentDir) {
  const dir = join(contentDir, "skills");
  const skills = readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => parseSkillFile(join(dir, e.name, "SKILL.md"), e.name));
  skills.sort((a, b) => a.name.localeCompare(b.name));
  return skills;
}

function parseRoleFile(path, filename) {
  const { attrs, body } = parseFrontmatter(readFileSync(path, "utf8"));
  for (const field of REQUIRED_ROLE_FIELDS) {
    if (!(field in attrs)) {
      throw new Error(`${path}: missing required frontmatter field \`${field}\``);
    }
  }
  if (typeof attrs.write_eligible !== "boolean") {
    throw new Error(`${path}: \`write_eligible\` must be true|false, got ${JSON.stringify(attrs.write_eligible)}`);
  }
  if (typeof attrs.dispatchable !== "boolean") {
    throw new Error(`${path}: \`dispatchable\` must be true|false, got ${JSON.stringify(attrs.dispatchable)}`);
  }
  if (!Array.isArray(attrs.capabilities) || attrs.capabilities.length === 0) {
    throw new Error(`${path}: \`capabilities\` must be a non-empty array`);
  }
  if (attrs.role !== filename.replace(/\.md$/, "")) {
    throw new Error(`${path}: \`role: ${attrs.role}\` does not match filename \`${filename}\``);
  }
  return {
    role: attrs.role,
    source: attrs.source ?? "",
    modelHint: attrs.model_hint ?? "",
    writeEligible: attrs.write_eligible,
    dispatchable: attrs.dispatchable,
    capabilities: attrs.capabilities,
    writeScope: attrs.write_scope ?? "",
    body,
  };
}

function parseSkillFile(path, dirname) {
  const { attrs, body } = parseFrontmatter(readFileSync(path, "utf8"));
  for (const field of REQUIRED_SKILL_FIELDS) {
    if (!(field in attrs)) {
      throw new Error(`${path}: missing required frontmatter field \`${field}\``);
    }
  }
  if (!VALID_PORTABILITY.has(attrs.portability)) {
    throw new Error(`${path}: \`portability\` must be one of ${[...VALID_PORTABILITY].join("|")}, got ${JSON.stringify(attrs.portability)}`);
  }
  if (attrs.name !== dirname) {
    throw new Error(`${path}: \`name: ${attrs.name}\` does not match directory \`${dirname}\``);
  }
  return {
    name: attrs.name,
    source: attrs.source ?? "",
    portability: attrs.portability,
    body,
  };
}
