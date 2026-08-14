// packages/harness-pi/src/roles.mjs -- a narrow, independent reader of content/roles/*.md's
// `role`, `write_eligible`, `model_hint`, `dispatchable`, and `capabilities` fields (the five
// this package needs). packages/compiler/src/compile.mjs's own header states compile()/TARGETS
// are that package's ENTIRE public surface -- content.mjs is its internal parser, not a
// contract this adapter should depend on -- so this stays a second, small, purpose-built
// reader over content/** (this step's file_scope.may_read) rather than an import of
// @fl03/compiler internals. It reads content/ live on every call, so it can never drift from
// the source of truth the way a hand-copied table would.
//
// Tier is NOT a content/roles/*.md frontmatter field. ROLE_TIER below is transcribed from
// two primary sources: skills/shepherd/SKILL.md §Dispatch law ("root dispatches @engineer,
// @critic, @auditor, @worker, @discovery... A teammate-conductor dispatches @coder, @auditor,
// @worker, @discovery; it NEVER dispatches @engineer/@critic") and
// content/predicates/dispatch-scope.toml's own rule prose ("Only the root orchestrator
// (shepherd) may dispatch the plan-author (engineer) or gating (critic) roles..."; "An
// implementer role (coder, worker, discovery, auditor, critic) never dispatches..."). Note
// `critic` is an implementer AS A DISPATCHER (rule 3's own list) while also being a
// root-exclusive TARGET (rule 2) -- those are different axes, kept as two separate exports
// (ROLE_TIER vs PLAN_OR_GATE_TARGET_ROLES) rather than conflated into one field.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

/** @typedef {{role: string, writeEligible: boolean, modelHint: string, dispatchable: boolean, capabilities: string[]}} RoleFact */
/** @typedef {Map<string, RoleFact>} RoleFacts */

export const ROLE_TIER = Object.freeze({
  shepherd: "root",
  planter: "meta",
  conductor: "lane-lead",
  engineer: "plan-author",
  critic: "implementer", // dispatch-scope.toml rule `implementer-roles-never-dispatch`
  coder: "implementer",
  auditor: "implementer",
  discovery: "implementer",
  worker: "implementer",
});

// dispatch-scope.toml rule `plan-authorship-and-gating-are-root-tier-exclusive`'s target set.
export const PLAN_OR_GATE_TARGET_ROLES = Object.freeze(new Set(["engineer", "critic"]));

/** @param {string} contentDir absolute path to content/ @returns {RoleFacts} keyed by role id */
export function loadRoleFacts(contentDir) {
  const dir = join(contentDir, "roles");
  const facts = new Map();
  for (const filename of readdirSync(dir).filter((f) => f.endsWith(".md"))) {
    const text = readFileSync(join(dir, filename), "utf8");
    const frontmatter = text.split(/^---\s*$/m)[1] ?? "";
    const role = matchScalar(frontmatter, "role");
    if (!role) throw new Error(`${filename}: missing \`role:\` in frontmatter`);
    facts.set(role, {
      role,
      writeEligible: matchScalar(frontmatter, "write_eligible") === "true",
      modelHint: matchScalar(frontmatter, "model_hint") ?? "",
      dispatchable: matchScalar(frontmatter, "dispatchable") === "true",
      capabilities: matchArray(frontmatter, "capabilities"),
    });
  }
  return facts;
}

function stripComment(line) {
  const hash = line.indexOf("#");
  return hash === -1 ? line : line.slice(0, hash);
}

function matchScalar(frontmatter, key) {
  for (const raw of frontmatter.split("\n")) {
    const line = stripComment(raw).trim();
    if (line.startsWith(`${key}:`)) return line.slice(key.length + 1).trim();
  }
  return undefined;
}

function matchArray(frontmatter, key) {
  const value = matchScalar(frontmatter, key);
  if (!value || !value.startsWith("[")) return [];
  return value
    .slice(1, value.lastIndexOf("]"))
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}
