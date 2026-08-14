// packages/harness-pi/src/materialize.mjs -- writes compile('pi')'s EmittedTree onto disk
// under a caller-chosen directory. compile() itself never writes
// (packages/compiler/src/compile.mjs's header) -- this is the "concrete write" onto Pi's own
// `prompts/`/`skills/` layout that packages/compiler/README.md assigns to the harness
// adapters. Pure and deterministic: same tree + same outDir => same bytes on disk, every
// call (test/reproducibility.test.mjs proves this at the filesystem level, not just
// compile()'s in-memory digest).
//
// There is no hardcoded default for outDir anywhere in this package (see bin/materialize.mjs)
// -- this adapter never guesses at a real `~/.pi/agent/` or project `.pi/` install path and
// so can never silently overwrite an operator's live Pi configuration; the caller (an install
// script, an operator) always decides where the tree actually lands.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

/**
 * @param {import("../../compiler/src/tree.mjs").EmittedTree} tree
 * @param {string} outDir absolute path.
 * @returns {string[]} the absolute paths written, in tree order (already path-sorted).
 */
export function materialize(tree, outDir) {
  const written = [];
  for (const file of tree.files) {
    const target = join(outDir, file.path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, file.content, "utf8");
    written.push(target);
  }
  return written;
}

/**
 * Verifies a directory's on-disk contents exactly match a tree -- the filesystem-level
 * counterpart to `compile()`'s own digest equality.
 * @param {import("../../compiler/src/tree.mjs").EmittedTree} tree
 * @param {string} outDir absolute path.
 * @returns {{ok: true} | {ok: false, reason: string}}
 */
export function verifyMaterialized(tree, outDir) {
  for (const file of tree.files) {
    const target = join(outDir, file.path);
    if (!existsSync(target)) return { ok: false, reason: `missing \`${target}\`` };
    const onDisk = readFileSync(target, "utf8");
    if (onDisk !== file.content) return { ok: false, reason: `content drift at \`${target}\`` };
  }
  return { ok: true };
}
