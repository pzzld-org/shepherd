// packages/compiler/src/compile.mjs -- the compiler's ENTIRE public surface:
//   compile(target: "claude" | "codex" | "pi", options?) -> EmittedTree
// A pure function of content/: same content/ tree in, same EmittedTree out, every call
// (packages/compiler/test/reproducibility.test.mjs proves this). It never writes to disk --
// see packages/compiler/README.md and content/roles/coder.md §Prohibitions for why file
// scope stops at packages/compiler/: the concrete write onto agents/, skills/, or
// shepherd.codex.toml belongs to packages/harness-{claude,codex,pi} (W4-S4/S5/S6), which
// consume this return value.

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadRoles, loadSkills } from "./content.mjs";
import { emitClaude } from "./targets/claude.mjs";
import { emitCodex } from "./targets/codex.mjs";
import { emitPi } from "./targets/pi.mjs";
import { buildEmittedTree } from "./tree.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_CONTENT_DIR = join(HERE, "..", "..", "..", "content");

export const TARGETS = Object.freeze(["claude", "codex", "pi"]);

const EMITTERS = Object.freeze({
  claude: emitClaude,
  codex: emitCodex,
  pi: emitPi,
});

/**
 * @param {"claude"|"codex"|"pi"} target
 * @param {{contentDir?: string}} [options] `contentDir` overrides the discovered `content/`
 *   root -- exercised by packages/compiler/test/*, real callers never need it.
 * @returns {import("./tree.mjs").EmittedTree}
 */
export function compile(target, options = {}) {
  const emit = EMITTERS[target];
  if (!emit) {
    throw new Error(`unknown compile target \`${target}\` -- expected one of ${TARGETS.join(", ")}`);
  }
  const contentDir = options.contentDir ?? DEFAULT_CONTENT_DIR;
  const roles = loadRoles(contentDir);
  const skills = loadSkills(contentDir);
  const files = emit({ roles, skills });
  return buildEmittedTree(target, files);
}
