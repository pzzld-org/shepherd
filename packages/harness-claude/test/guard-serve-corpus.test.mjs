#!/usr/bin/env node
// packages/harness-claude/test/guard-serve-corpus.test.mjs -- run directly:
//   node packages/harness-claude/test/guard-serve-corpus.test.mjs
// T2-serve-wiring: replays every `content/predicates/*.toml` `[[example]]` through the NEW
// broker/client transport (`src/guard-serve-broker.mjs` + `src/guard-serve-client.mjs`) end to
// end -- a real `startGuardBroker()` bound to a throwaway socket, real `requestGuardVerdict()`
// calls against it, real `bin/shepherd guard serve` underneath. Same technique as
// `packages/harness-pi/test/guard-predicates.test.mjs` (this file's own `test/support/
// predicate-corpus.mjs` reader is the SAME shape, factored so both packages' corpus tests share
// one reader -- see that module's header) and `packages/harness-codex/test/guard-serve-corpus.
// test.mjs`'s own copy of this file's structure: the corpus itself must never drift between the
// three adapters' relays, only the shared engine decides.
//
// Proves the swap from `spawnSync(LAUNCHER, ["guard", "eval"], ...)` to the persistent-broker
// transport changed NOTHING about what gets decided -- every allow stays an allow, every deny
// (with its halt_code) stays exactly that deny, through the new wire.

import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { startGuardBroker } from "../src/guard-serve-broker.mjs";
import { requestGuardVerdict } from "../src/guard-serve-client.mjs";
import { loadPredicateExamples, CANONICAL_EXAMPLE_KEYS } from "./support/predicate-corpus.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const CONTENT_DIR = join(REPO_ROOT, "content");
const SHEPHERD_BIN = join(REPO_ROOT, "bin", "shepherd");

const socketDir = mkdtempSync(join(tmpdir(), "hc-corpus-"));
const socketPath = join(socketDir, "g.sock");

const broker = await startGuardBroker({ shepherdBin: SHEPHERD_BIN, contentDir: CONTENT_DIR, socketPath, idleTimeoutMs: 60_000 });
assert.ok(broker, "expected to win the bind race on a fresh throwaway socket path");

let checked = 0;
let allowCount = 0;
let denyCount = 0;

try {
  for (const spec of loadPredicateExamples(CONTENT_DIR)) {
    assert.ok(spec.examples.length > 0, `${spec.id}: predicate corpus carries zero examples`);
    for (const example of spec.examples) {
      const extras = Object.fromEntries(Object.entries(example).filter(([k]) => !CANONICAL_EXAMPLE_KEYS.has(k)));
      const context = { ...example.context, ...extras };

      const result = await requestGuardVerdict({
        shepherdBin: SHEPHERD_BIN,
        contentDir: CONTENT_DIR,
        payload: { harness: "claude", predicate: spec.id, role: example.role, action: example.action, context },
        socketPath,
      });
      assert.equal(result.ok, true, `${spec.id}/${example.name}: transport failed: ${result.detail}`);

      const expectedDecision = example.result === "allow" ? "allow" : "deny";
      assert.equal(
        result.engineResult.decision,
        expectedDecision,
        `${spec.id}/${example.name}: expected ${expectedDecision}, got ${result.engineResult.decision} (${result.engineResult.reason})`
      );
      if (example.halt_code) {
        assert.equal(result.engineResult.halt_code, example.halt_code, `${spec.id}/${example.name}: expected halt_code \`${example.halt_code}\``);
      }

      checked += 1;
      if (example.kind === "allow") allowCount += 1;
      else denyCount += 1;
    }
  }

  assert.ok(allowCount > 0 && denyCount > 0, "the full corpus across all predicates must carry both allow and deny cases");
} finally {
  broker.close();
  await broker.onClosed;
  rmSync(socketDir, { recursive: true, force: true });
}

console.log(`ok: ${checked} guard-predicate example(s) across every content/predicates/*.toml file matched via the new broker/client transport (${allowCount} allow, ${denyCount} deny)`);
