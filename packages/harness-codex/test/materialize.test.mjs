#!/usr/bin/env node
// packages/harness-codex/test/materialize.test.mjs -- run directly:
//   node packages/harness-codex/test/materialize.test.mjs
// Exercises materialize() against a scratch directory (never this package's own committed
// tree) and checks the shape the plan's [ACCEPTANCE] greps for, plus the codex-has-no-command-
// surface non-goal one level down from packages/compiler/test/codex-no-command-surface.test.mjs
// (this adapter's OWN augmented tree, not just the compiler's raw one).

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildCodexTree, materialize } from "../src/materialize.mjs";

const tree = buildCodexTree();
assert.ok(tree.files.length > 0);
for (const file of tree.files) {
  assert.ok(
    !file.path.startsWith("commands/") && !file.path.startsWith("prompts/") && !file.path.startsWith("agents/"),
    `buildCodexTree() emitted \`${file.path}\` -- Codex has no command/prompt/per-role-file surface`
  );
}

const config = tree.files.find((f) => f.path === "shepherd.codex.toml");
assert.ok(config, "buildCodexTree() must emit shepherd.codex.toml");
assert.match(config.content, /max_concurrent_children = 3/);
assert.match(config.content, /\[agent_types\]/);
assert.match(config.content, /\[models\]/);
assert.match(config.content, /\[profiles\."standard"\]/);
assert.match(config.content, /\[profiles\."reasoning-high"\]/);
// every non-root role in [agent_types] also gets a [models] pin, and vice versa
const agentTypeRoles = [...config.content.matchAll(/^(\w+) = "(?:worker|explorer)"$/gm)].map((m) => m[1]);
const modelRoles = [...config.content.matchAll(/^(\w+) = "(?:standard|reasoning-high)"$/gm)].map((m) => m[1]);
assert.deepEqual([...agentTypeRoles].sort(), [...modelRoles].sort());

const scratch = mkdtempSync(join(tmpdir(), "harness-codex-test-"));
try {
  const written = materialize(scratch);
  assert.equal(written.digest, tree.digest);
  const onDisk = readFileSync(join(scratch, "shepherd.codex.toml"), "utf8");
  assert.equal(onDisk, config.content);
  for (const file of tree.files.filter((f) => f.kind === "skill")) {
    assert.equal(readFileSync(join(scratch, file.path), "utf8"), file.content);
  }
} finally {
  rmSync(scratch, { recursive: true, force: true });
}

console.log(`ok: materialize() writes ${tree.files.length} file(s) verbatim, no command surface, [agent_types]/[models] role sets match`);
