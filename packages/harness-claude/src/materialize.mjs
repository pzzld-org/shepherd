// packages/harness-claude/src/materialize.mjs -- the concrete disk write
// packages/compiler/src/compile.mjs's own header names as this adapter's job ("the
// concrete write onto agents/, skills/, or shepherd.codex.toml belongs to
// packages/harness-{claude,codex,pi}"). Pure with respect to `content/`: given the same
// finalized tree, writes the same bytes to the same relative paths under `targetDir` every
// call. `targetDir` is always caller-supplied -- this module never assumes or defaults to
// the live repo root, so exercising it (packages/harness-claude/test/materialize.test.mjs)
// never touches `agents/`, `skills/`, or `hooks/` outside a throwaway temp directory.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

/**
 * @param {import("../../compiler/src/tree.mjs").EmittedTree} tree a finalized tree (see
 *   `finalize.mjs`) -- every `EmittedFile.path` is relative to the target harness's own
 *   root, per that shape's own doc comment.
 * @param {string} targetDir absolute path to materialize `tree.files` under.
 * @returns {string[]} the absolute paths written, in the same order as `tree.files`
 *   (already sorted by path -- see `tree.mjs`).
 */
export function materialize(tree, targetDir) {
  const written = [];
  for (const file of tree.files) {
    const absolute = join(targetDir, file.path);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, file.content, "utf8");
    written.push(absolute);
  }
  return written;
}
