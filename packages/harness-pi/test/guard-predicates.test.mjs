#!/usr/bin/env node
// packages/harness-pi/test/guard-predicates.test.mjs -- run directly:
//   node --experimental-strip-types test/guard-predicates.test.mjs
// Replays every content/predicates/*.toml `[[example]]` (the shared allow/deny case corpus,
// decision 1) through src/guard-client.ts's GuardClient -- a REAL, live `bin/shepherd guard
// serve` child process, the exact same path src/extension.ts's `tool_call` handler drives
// (C1-pi-collapse). This is the "kept in lockstep... not by discipline" proof, now stronger
// than before: it no longer replays the corpus against a second, hand-written TS
// interpreter (deleted this step, src/guard.ts) that could quietly drift from
// content/predicates/*.toml's real semantics -- it replays against the one authoritative
// engine (services/cli/shepherd_cli/predicates.py) every harness shares, through this
// package's own relay client, so a bug in the RELAY (not just the corpus) is caught here too.
//
// This reads content/predicates/*.toml live via a narrow local reader (below), matching
// src/roles.mjs's own "reads content/ live on every call" philosophy -- a corpus change is
// caught on the next run, never a hand-copied fixture list.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { GuardClient } from "../src/guard-client.ts";
import { loadRoleFacts } from "../src/roles.mjs";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const CONTENT_DIR = join(REPO_ROOT, "content");
const SHEPHERD_BIN = join(REPO_ROOT, "bin", "shepherd");
const CANONICAL_EXAMPLE_KEYS = new Set(["name", "kind", "role", "action", "context", "result", "halt_code", "note"]);

// -- a narrow, local content/predicates/*.toml reader (this step's file_scope.may_read),
// the same [predicate]/[[rule]]/[[example]] grammar src/predicates.mjs's now-deleted parser
// read, trimmed to only what a corpus-replay test needs (`id` + `examples`; `[[rule]]` blocks
// are parsed and discarded so their `key = value` lines never leak into the following
// example). Lives in the test file since production code has no remaining need to parse the
// corpus itself -- only to relay a resolved check against it.
function loadPredicateExamples(contentDir) {
  const dir = join(contentDir, "predicates");
  return readdirSync(dir)
    .filter((f) => f.endsWith(".toml"))
    .sort()
    .map((f) => parsePredicateFile(join(dir, f)));
}

function parsePredicateFile(path) {
  let id;
  const examples = [];
  let current; // the table currently being populated
  let section; // "predicate" | "rule" | "example" -- which kind `current` is

  for (const raw of readFileSync(path, "utf8").split("\n")) {
    const line = raw.trim();
    if (line === "" || line.startsWith("#")) continue;
    if (line === "[predicate]") {
      current = {};
      section = "predicate";
      continue;
    }
    if (line === "[[rule]]") {
      current = {};
      section = "rule";
      continue;
    }
    if (line === "[[example]]") {
      current = {};
      section = "example";
      examples.push(current);
      continue;
    }
    const eq = line.indexOf(" = ");
    if (eq === -1 || !current) continue;
    const key = line.slice(0, eq);
    const value = parseTomlValue(line.slice(eq + 3));
    current[key] = value;
    if (section === "predicate" && key === "id") id = value;
  }

  if (id === undefined) throw new Error(`${path}: missing [predicate] id`);
  return { id, examples };
}

function parseTomlValue(raw) {
  const value = raw.trim();
  if (value === "true") return true;
  if (value === "false") return false;
  if (value.startsWith('"') && value.endsWith('"')) return value.slice(1, -1);
  if (value.startsWith("{") && value.endsWith("}")) return parseInlineTable(value);
  if (/^-?\d+$/.test(value)) return Number(value);
  throw new Error(`unparseable TOML scalar: \`${raw}\``);
}

function parseInlineTable(raw) {
  const inner = raw.slice(1, -1).trim();
  const table = {};
  if (inner === "") return table;
  for (const pair of splitInlinePairs(inner)) {
    const eq = pair.indexOf("=");
    table[pair.slice(0, eq).trim()] = parseTomlValue(pair.slice(eq + 1).trim());
  }
  return table;
}

function splitInlinePairs(inner) {
  const parts = [];
  let inQuotes = false;
  let start = 0;
  for (let i = 0; i < inner.length; i += 1) {
    if (inner[i] === '"') inQuotes = !inQuotes;
    if (!inQuotes && inner[i] === ",") {
      parts.push(inner.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(inner.slice(start));
  return parts.map((p) => p.trim()).filter(Boolean);
}

// roleFacts is loaded but unused directly here (the live engine resolves its own role facts
// server-side) -- kept as a sanity check that this adapter's own reader agrees content/roles/
// is readable at all before spending a subprocess spawn on it.
assert.ok(loadRoleFacts(CONTENT_DIR).size > 0, "content/roles/*.md must yield at least one role fact");

const client = await GuardClient.spawn(SHEPHERD_BIN, CONTENT_DIR);

let checked = 0;
let allowCount = 0;
let denyCount = 0;

try {
  for (const spec of loadPredicateExamples(CONTENT_DIR)) {
    assert.ok(spec.examples.length > 0, `${spec.id}: predicate corpus carries zero examples`);
    for (const example of spec.examples) {
      // Extra top-level fields (target_role, target_branch, path, symbol, ...) merge into
      // context -- the engine reads them uniformly, the fixture doesn't need a bespoke shape.
      const extras = Object.fromEntries(Object.entries(example).filter(([k]) => !CANONICAL_EXAMPLE_KEYS.has(k)));
      const context = { ...example.context, ...extras };

      const verdict = await client.evaluate({ predicateId: spec.id, role: example.role, action: example.action, context });
      const expectedAllow = example.result === "allow";

      assert.equal(
        verdict.allow,
        expectedAllow,
        `${spec.id}/${example.name}: expected ${example.result}, got ${verdict.allow ? "allow" : "deny"} (${verdict.reason})`
      );
      if (example.halt_code) {
        assert.equal(verdict.haltCode, example.halt_code, `${spec.id}/${example.name}: expected halt_code \`${example.halt_code}\`, got \`${verdict.haltCode}\``);
      }

      checked += 1;
      if (example.kind === "allow") allowCount += 1;
      else denyCount += 1;
    }

    const kinds = new Set(spec.examples.map((e) => e.kind));
    assert.ok(kinds.has("allow"), `${spec.id}: corpus has no allow case`);
    assert.ok(kinds.has("deny"), `${spec.id}: corpus has no deny case`);
  }

  assert.ok(allowCount > 0 && denyCount > 0, "the full corpus across all predicates must carry both allow and deny cases");
} finally {
  client.close();
}

console.log(`ok: ${checked} guard-predicate example(s) across every content/predicates/*.toml file matched via a live guard-serve relay (${allowCount} allow, ${denyCount} deny)`);
