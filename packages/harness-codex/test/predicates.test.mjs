#!/usr/bin/env node
// packages/harness-codex/test/predicates.test.mjs -- run directly:
//   node packages/harness-codex/test/predicates.test.mjs
// Loads content/predicates/*.toml's OWN `[[example]]` blocks (not a hand-transcribed copy)
// and asserts src/predicates.mjs's `evaluate()` reproduces every declared `result` -- proving,
// against the spec's real fixture corpus rather than invented cases, that all four predicates
// carry at least one `allow` AND one `deny` case (the dispatch brief's own acceptance
// language) and that this adapter's interpreter agrees with every one of them.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadRoles } from "../../compiler/src/content.mjs";
import { buildEnv, evaluate, loadPredicates } from "../src/predicates.mjs";
import { parsePredicateToml } from "../src/toml-lite.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTENT_DIR = join(HERE, "..", "..", "..", "content");
const PREDICATES_DIR = join(CONTENT_DIR, "predicates");

const predicates = loadPredicates(CONTENT_DIR);
const env = buildEnv(loadRoles(CONTENT_DIR).map((r) => r.role));

let total = 0;
const seenByPredicate = new Map(); // predicateId -> Set<"allow"|"deny">

for (const file of readdirSync(PREDICATES_DIR).filter((f) => f.endsWith(".toml")).sort()) {
  const doc = parsePredicateToml(readFileSync(join(PREDICATES_DIR, file), "utf8"));
  const predicateId = doc.predicate.id;
  assert.ok(doc.example.length > 0, `${file}: [predicate].id \`${predicateId}\` carries zero [[example]] blocks`);

  for (const example of doc.example) {
    total += 1;
    assert.ok(
      example.result === "allow" || example.result === "deny",
      `${file} example \`${example.name}\`: result must be allow|deny, got ${JSON.stringify(example.result)}`
    );

    // Flatten: an example's top-level scalar fields (role, action, target_role, path,
    // symbol, target_branch, ...) plus its nested `context = { ... }` object, exactly as a
    // real caller assembling a decision context would.
    const { action, context, kind, name, halt_code: _haltCode, note: _note, result, ...rest } = example;
    const flat = { ...rest, ...(context ?? {}) };

    const decision = evaluate(predicateId, action, flat, predicates, env);
    assert.equal(
      decision.result,
      result,
      `${file} example \`${name}\` (kind=${kind}): evaluate() returned \`${decision.result}\`, TOML declares \`${result}\``
    );

    if (!seenByPredicate.has(predicateId)) seenByPredicate.set(predicateId, new Set());
    seenByPredicate.get(predicateId).add(result);
  }
}

for (const [predicateId, results] of seenByPredicate) {
  assert.ok(results.has("allow"), `predicate \`${predicateId}\` has no allow-kind example`);
  assert.ok(results.has("deny"), `predicate \`${predicateId}\` has no deny-kind example`);
}

// dispatch-scope.toml's rule 2 names these two role ids directly in its own description
// (src/predicates.mjs's PLAN_OR_GATE_ROLES) -- a drift tripwire against content/roles/*.md
// ever dropping either id.
for (const roleId of ["engineer", "critic"]) {
  assert.ok(env.flockRoles.has(roleId), `flock role \`${roleId}\` (dispatch-scope.toml's plan/gate rule) is missing from loadRoles()`);
}

console.log(`ok: ${total} content/predicates/*.toml example(s) across ${seenByPredicate.size} predicate(s), every predicate carries an allow AND a deny case, evaluate() agrees with all of them`);
