#!/usr/bin/env node
// packages/compiler/test/codex-no-command-surface.test.mjs -- run directly:
//   node packages/compiler/test/codex-no-command-surface.test.mjs
// Operationalizes plan.md W4-S3's [NON-GOALS]: "Do NOT emit a Codex command target -- Codex
// has nowhere to put one, so emitting it is a defect rather than a gap"
// (discovery-d1-harness.md §Engineer follow-up: no `prompts/`, no `commands/`, no `agents/`
// exist anywhere in the installed Codex bundle or on `~/.codex/`). A negative control: this
// would fail loudly the day someone "fixes" Codex's missing command surface by inventing one.

import assert from "node:assert/strict";
import { compile } from "../src/compile.mjs";

const tree = compile("codex");
assert.ok(tree.files.length > 0, "compile('codex') must emit at least one file");

for (const file of tree.files) {
  assert.ok(
    !file.path.startsWith("commands/") && !file.path.startsWith("prompts/") && !file.path.startsWith("agents/"),
    `compile('codex') emitted \`${file.path}\` -- Codex has no command/prompt/per-role-file surface to put it in`
  );
}

console.log(`ok: compile('codex')'s ${tree.files.length} file(s) carry no command, prompt, or per-role-file surface`);
