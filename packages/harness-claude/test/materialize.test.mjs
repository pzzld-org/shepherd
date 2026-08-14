#!/usr/bin/env node
// packages/harness-claude/test/materialize.test.mjs -- run directly:
//   node packages/harness-claude/test/materialize.test.mjs
// Proves `materialize()` writes every finalized file to its expected relative path with
// byte-identical content, and ONLY inside the caller-supplied `targetDir` -- never the live
// repo root (this test's own `targetDir` is a throwaway `mkdtemp` directory, exercising
// exactly the same call a real materialization step would make without ever touching
// `agents/`, `skills/`, or `hooks/` outside file scope).

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { compile } from "../../compiler/src/compile.mjs";
import { finalizeClaudeTree } from "../src/finalize.mjs";
import { materialize } from "../src/materialize.mjs";

const tree = finalizeClaudeTree(compile("claude"));
const targetDir = mkdtempSync(join(tmpdir(), "harness-claude-materialize-"));

try {
  const written = materialize(tree, targetDir);
  assert.equal(written.length, tree.files.length, "materialize() must write exactly one path per emitted file");

  for (const file of tree.files) {
    const absolute = join(targetDir, file.path);
    assert.ok(written.includes(absolute), `materialize() did not report writing ${absolute}`);
    const onDisk = readFileSync(absolute, "utf8");
    assert.equal(onDisk, file.content, `${file.path}: on-disk content does not match the emitted tree`);
  }

  // A role file and a skill file land at genuinely different subdirectories -- proves the
  // relative-path materialization actually creates nested directories, not just siblings.
  const roleAbs = join(targetDir, "agents", "coder.md");
  const skillAbs = join(targetDir, "skills", "adaptation", "SKILL.md");
  assert.ok(tree.files.some((f) => join(targetDir, f.path) === roleAbs), "expected agents/coder.md in the finalized tree");
  assert.ok(tree.files.some((f) => join(targetDir, f.path) === skillAbs), "expected skills/adaptation/SKILL.md in the finalized tree");
  assert.equal(readFileSync(roleAbs, "utf8"), tree.files.find((f) => f.path === "agents/coder.md").content);
  assert.equal(readFileSync(skillAbs, "utf8"), tree.files.find((f) => f.path === "skills/adaptation/SKILL.md").content);

  console.log(`ok: materialize() wrote ${written.length} file(s) under a throwaway temp dir, every byte matching the emitted tree`);
} finally {
  rmSync(targetDir, { recursive: true, force: true });
}
