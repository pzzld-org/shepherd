#!/usr/bin/env node
// packages/harness-claude/test/finalize.test.mjs -- run directly:
//   node packages/harness-claude/test/finalize.test.mjs
// This step's dispatch brief, verbatim: "the emitted tree must match what agents/,
// commands/, skills/, and hooks/ already look like today... diff your emission against them
// and report every divergence: a divergence is either a compiler bug, a content gap, or
// drift in the hand-maintained tree, and which one it is matters." This test IS that diff,
// made deterministic and pinned rather than a one-off latent-space read: it fails the moment
// a NEW, unaccounted-for divergence appears, and documents (inline, per assertion) which of
// the three buckets each currently-known one falls into.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "../../compiler/src/compile.mjs";
import { parseFrontmatter } from "../../compiler/src/frontmatter.mjs";
import { finalizeClaudeTree } from "../src/finalize.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const AGENTS_DIR = join(REPO_ROOT, "agents");

/** Frontmatter KEY set only (order-preserving), read with a test-local regex rather than
 * `parseFrontmatter` -- `agents/*.md`'s `tools:` line is an unbracketed CSV, a different
 * grammar than `content/`'s bracketed-array form `parseFrontmatter` is built for, so this
 * helper only needs the key names, never the values. */
function handFrontmatterKeys(text) {
  const block = text.split(/^---\s*$/m)[1] ?? "";
  return block
    .split(/\r?\n/)
    .map((line) => line.match(/^(\w+):/)?.[1])
    .filter(Boolean);
}

// Fields `content/roles/*.md` adds that no hand-maintained `agents/*.md` has today --
// intentional, per W0-S8's whole purpose (a new machine-readable write-boundary contract),
// not a defect.
const EXPECTED_ADDED = new Set(["dispatchable", "write_eligible", "write_scope"]);
// Fields the hand-maintained tree carries that `content/roles/*.md` has no source for at
// all -- a genuine CONTENT GAP (not this adapter's to invent; see `finalize.mjs`'s own doc
// comment and `packages/compiler/src/targets/claude.mjs`'s `model_hint` field comment).
const KNOWN_CONTENT_GAP_FIELDS = new Set(["color", "description", "effort"]);
// `capabilitiesToClaudeTools`'s current output is a strict SUPERSET of every hand-maintained
// role's granted tools, never a subset -- verified for exactly these two extra grants, both
// traceable to `packages/compiler/src/capabilities.mjs`'s capability table (a COMPILER-layer
// fact, out of this step's file scope to change; flagged for follow-up in the coder report).
const KNOWN_EXTRA_TOOLS_BY_ROLE = Object.freeze({
  auditor: new Set(["NotebookRead", "LSP"]),
  // discovery's hand-granted tools already include NotebookRead (its `read` capability's
  // extra grant is not "extra" there -- the one role where compiled and hand-maintained
  // tools already agree exactly).
  discovery: new Set(),
  // planter's `dispatch` capability maps to [Agent, Workflow] (capabilities.mjs), but
  // agents/planter.md grants only Agent -- unlike every other `dispatch`-capable role
  // (conductor, engineer, shepherd all carry Workflow by hand). Unexplained anywhere in
  // planter.md's body; flagged as an open divergence (compiler-bug-or-hand-tree-drift,
  // undetermined which) rather than silently resolved either way.
  planter: new Set(["NotebookRead", "Workflow"]),
  // worker's `write` capability maps to [Write, Edit] (capabilities.mjs), but
  // agents/worker.md grants only Write -- consistent with content/roles/worker.md's own
  // `write_scope`: "*.md deliverables only... never source" (worker creates new report
  // files; it does not edit existing ones in place). The capability table does not carry
  // that Write/Edit distinction; flagged as a compiler-layer finding, not resolved here.
  worker: new Set(["NotebookRead", "Edit"]),
  DEFAULT: new Set(["NotebookRead"]),
});

const finalized = finalizeClaudeTree(compile("claude"));
const roleFiles = finalized.files.filter((f) => f.kind === "role");
assert.equal(roleFiles.length, 9, "expected all 9 roles to compile to a Claude agent file");

const handFiles = new Set(readdirSync(AGENTS_DIR).filter((f) => f.endsWith(".md")));
let compared = 0;

for (const file of roleFiles) {
  const role = file.path.replace(/^agents\//, "").replace(/\.md$/, "");
  const filename = `${role}.md`;
  if (!handFiles.has(filename)) continue; // no hand-maintained counterpart to diff against
  compared += 1;

  const { attrs: compiledAttrs } = parseFrontmatter(file.content);
  const handText = readFileSync(join(AGENTS_DIR, filename), "utf8");
  const handKeys = handFrontmatterKeys(handText);
  const handTools = handText.match(/^tools:\s*(.+)$/m)[1].split(",").map((s) => s.trim());

  assert.equal(compiledAttrs.name, role, `role \`${role}\`: compiled name mismatch`);

  const compiledKeys = new Set(Object.keys(compiledAttrs));
  const added = [...compiledKeys].filter((k) => !handKeys.includes(k));
  const removed = handKeys.filter((k) => !compiledKeys.has(k));
  assert.deepEqual(
    new Set(added),
    EXPECTED_ADDED,
    `role \`${role}\`: fields added vs agents/${filename} changed -- was ${JSON.stringify([...EXPECTED_ADDED])}, now ${JSON.stringify(added)}`
  );
  for (const field of removed) {
    assert.ok(
      KNOWN_CONTENT_GAP_FIELDS.has(field),
      `role \`${role}\`: NEW content-gap field \`${field}\` (agents/${filename} has it, content/roles/${role}.md has no source for it) -- update KNOWN_CONTENT_GAP_FIELDS if this is expected`
    );
  }

  const compiledTools = new Set(compiledAttrs.tools);
  const missing = handTools.filter((t) => !compiledTools.has(t));
  assert.deepEqual(missing, [], `role \`${role}\`: compiled tools DROPPED a hand-granted tool: ${JSON.stringify(missing)}`);
  const extra = [...compiledTools].filter((t) => !handTools.includes(t));
  const expectedExtra = KNOWN_EXTRA_TOOLS_BY_ROLE[role] ?? KNOWN_EXTRA_TOOLS_BY_ROLE.DEFAULT;
  assert.deepEqual(
    new Set(extra),
    expectedExtra,
    `role \`${role}\`: compiled tools grant an unaccounted-for extra: ${JSON.stringify(extra)}, expected ${JSON.stringify([...expectedExtra])}`
  );
}

assert.equal(compared, 9, "expected all 9 roles to have a hand-maintained agents/*.md counterpart (root `shepherd` too -- RECONCILIATION row 4 excludes root only from Codex's compiled TABLE, not from Claude's per-role FILE shape)");

console.log(`ok: diffed ${compared} role(s) against agents/*.md -- every divergence is accounted for (added: write-boundary fields, removed: color/description/effort content gap, extra tools: NotebookRead + auditor's LSP)`);
