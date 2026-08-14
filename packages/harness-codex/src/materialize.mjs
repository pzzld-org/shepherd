// packages/harness-codex/src/materialize.mjs -- the Codex adapter's one job: take
// @fl03/compiler's `compile('codex')` EmittedTree and put it on disk at Codex's own real
// paths (`shepherd.codex.toml`, `skills/<name>/SKILL.md` -- same relative layout the installed
// `codex-shepherd@1.0.2` bundle uses), augmented with the per-role model-profile pin
// compile('codex') deliberately leaves unresolved (src/model-profile.mjs). Every
// `EmittedFile.content` other than the config file is written byte-for-byte verbatim, per
// packages/compiler/src/compile.mjs's own contract ("this IS what an adapter writes verbatim
// to `path`"); the config file is compiler content plus one appended, disjoint TOML block --
// never a re-parse or mutation of what the compiler already produced.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "../../compiler/src/compile.mjs";
import { loadRoles } from "../../compiler/src/content.mjs";
import { buildEmittedTree } from "../../compiler/src/tree.mjs";
import { ROOT_MODEL_HINT, resolveProfile } from "./model-profile.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_CONTENT_DIR = join(HERE, "..", "..", "..", "content");
export const DEFAULT_TARGET_DIR = join(HERE, "..");
const CONFIG_PATH = "shepherd.codex.toml";

/**
 * @param {{contentDir?: string}} [options]
 * @returns {import("../../compiler/src/tree.mjs").EmittedTree} `compile('codex')`'s tree,
 *   with `shepherd.codex.toml`'s content extended by a `[models]`/`[profiles.*]` block --
 *   still sorted, still deduplicated, still digested over the FINAL bytes (buildEmittedTree
 *   recomputes the digest here; it is not compile()'s own, since the bytes differ).
 */
export function buildCodexTree(options = {}) {
  const contentDir = options.contentDir ?? DEFAULT_CONTENT_DIR;
  const compiled = compile("codex", { contentDir });
  const modelBlock = renderModelBlock(loadRoles(contentDir));
  const files = compiled.files.map((file) =>
    file.path === CONFIG_PATH ? { ...file, content: file.content + modelBlock } : file
  );
  return buildEmittedTree("codex", files);
}

/** @param {import("../../compiler/src/content.mjs").Role[]} roles @returns {string} */
function renderModelBlock(roles) {
  const tableRoles = roles.filter((role) => role.modelHint !== ROOT_MODEL_HINT);
  const profiles = new Map();
  const lines = ["[models]"];
  for (const role of tableRoles) {
    const profile = resolveProfile(role.modelHint);
    lines.push(`${role.role} = "${profile.name}"`);
    profiles.set(profile.name, profile);
  }
  lines.push("");
  for (const profile of [...profiles.values()].sort((a, b) => a.name.localeCompare(b.name))) {
    lines.push(`[profiles."${profile.name}"]`);
    lines.push(`reasoning_effort = "${profile.reasoningEffort}"`);
    lines.push("");
  }
  return "\n" + lines.join("\n");
}

/**
 * Writes `buildCodexTree()`'s files to `targetDir` (default: this package's own root, so
 * `packages/harness-codex/shepherd.codex.toml` + `packages/harness-codex/skills/**` are the
 * real, committed materialization the plan's [ACCEPTANCE] `grep`s against).
 * @param {string} [targetDir]
 * @param {{contentDir?: string}} [options]
 * @returns {import("../../compiler/src/tree.mjs").EmittedTree}
 */
export function materialize(targetDir = DEFAULT_TARGET_DIR, options = {}) {
  const tree = buildCodexTree(options);
  for (const file of tree.files) {
    const dest = join(targetDir, file.path);
    mkdirSync(dirname(dest), { recursive: true });
    writeFileSync(dest, file.content, "utf8");
  }
  return tree;
}
