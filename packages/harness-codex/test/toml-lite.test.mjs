#!/usr/bin/env node
// packages/harness-codex/test/toml-lite.test.mjs -- run directly:
//   node packages/harness-codex/test/toml-lite.test.mjs

import assert from "node:assert/strict";
import { parsePredicateToml } from "../src/toml-lite.mjs";

const sample = `
# a full-line comment
[predicate]
id = "sample"
version = 1
description = "a description with, a comma inside it"

[[rule]]
id = "r1"
action = "fs.write"
effect = "deny_if_false"

[[example]]
name = "e1"
kind = "allow"
action = "fs.write"
context = { write_eligible = true, path_in_dispatch_write_scope = true }
result = "allow"
`;

const doc = parsePredicateToml(sample);
assert.equal(doc.predicate.id, "sample");
assert.equal(doc.predicate.version, 1);
assert.equal(doc.predicate.description, "a description with, a comma inside it");
assert.equal(doc.rule.length, 1);
assert.equal(doc.rule[0].effect, "deny_if_false");
assert.equal(doc.example.length, 1);
assert.deepEqual(doc.example[0].context, { write_eligible: true, path_in_dispatch_write_scope: true });
assert.equal(doc.example[0].result, "allow");

assert.throws(() => parsePredicateToml("key = \"value\""), /before any \[section\]/);
assert.throws(() => parsePredicateToml("[predicate]\nbroken line"), /malformed line/);

console.log("ok: toml-lite parses [section]/[[array]] headers, quoted/bool/int scalars, and single-level inline tables");
