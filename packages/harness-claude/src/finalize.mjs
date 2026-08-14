// packages/harness-claude/src/finalize.mjs -- the one piece of real adapter logic this
// package owns: turn @fl03/compiler's `claude` EmittedTree (model_hint UNRESOLVED, per
// packages/compiler/src/targets/claude.mjs) into the tree Claude Code actually reads
// (`model:` resolved). Every other transform is identity -- skill and config files pass
// through byte-for-byte, matching [USER-STYLE] "adapters are thin."
//
// Frontmatter is parsed and re-rendered using the compiler's OWN narrow, hand-rolled
// primitives (`frontmatter.mjs` / `markdown.mjs`) rather than a second implementation --
// content/RECONCILIATION.md's whole point is one grammar, read and written in one place.
// The final tree is rebuilt through the compiler's own `buildEmittedTree` too, so the
// reproducibility contract (sorted files, sha256 digest) that
// packages/compiler/test/reproducibility.test.mjs proves for `compile()` itself extends,
// unmodified, to this adapter's own finalized output.

import { parseFrontmatter } from "../../compiler/src/frontmatter.mjs";
import { array, field, quoted, renderFrontmatterFile } from "../../compiler/src/markdown.mjs";
import { buildEmittedTree } from "../../compiler/src/tree.mjs";
import { resolveModel } from "./model.mjs";

/**
 * @param {import("../../compiler/src/tree.mjs").EmittedTree} tree `compile("claude")`'s
 *   return value. Throws if `tree.target !== "claude"` -- this transform is Claude-specific.
 * @returns {import("../../compiler/src/tree.mjs").EmittedTree} the same tree with every
 *   `role` file's `model_hint:` line resolved to a concrete `model:` line; `skill` files
 *   pass through unchanged.
 */
export function finalizeClaudeTree(tree) {
  if (tree.target !== "claude") {
    throw new Error(`finalizeClaudeTree expects a 'claude' EmittedTree, got '${tree.target}'`);
  }
  const files = tree.files.map((file) => (file.kind === "role" ? resolveRoleModel(file) : file));
  return buildEmittedTree("claude", files);
}

function resolveRoleModel(file) {
  const { attrs, body } = parseFrontmatter(file.content);
  const model = resolveModel(attrs.model_hint);
  const content = renderFrontmatterFile(
    [
      field("name", attrs.name),
      field("model", model),
      field("tools", array(attrs.tools)),
      field("dispatchable", String(attrs.dispatchable)),
      field("write_eligible", String(attrs.write_eligible)),
      field("write_scope", quoted(attrs.write_scope)),
    ],
    body
  );
  return { ...file, content };
}
