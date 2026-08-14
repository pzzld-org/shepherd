// packages/harness-pi/src/predicates.mjs -- hand-rolled reader for content/predicates/*.toml,
// mirroring packages/compiler/src/frontmatter.mjs's philosophy (a narrow, fully-enumerated
// subset, not a TOML library dependency -- verified against every content/predicates/*.toml
// file at authorship time with `rg`, not guessed). The grammar used there is exactly
// [predicate] / [[rule]] / [[example]] array-of-tables, scalar `key = value` lines, and
// single-line inline tables for `context = { ... }` -- no multi-line arrays or tables appear
// anywhere in the corpus, so this reader never needs to handle them.
//
// This module is the shared allow/deny case corpus src/guard.ts's tests replay directly
// (decision 1, discovery-d1-harness.md: "kept in lockstep by the shared allow/deny case
// corpus, not by discipline") -- reading content/predicates/*.toml live means a change there
// is caught by test/guard-predicates.test.mjs on the next run, never silently drifts from a
// hand-copied fixture list.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

/** @typedef {{id: string, description: string, subject: string, action: string, effect: string}} Rule */
/** @typedef {{name: string, kind: "allow"|"deny", role: string, action: string, context: Record<string, unknown>, result: "allow"|"deny", halt_code?: string, note?: string, [extra: string]: unknown}} Example */
/** @typedef {{id: string, version: number, description: string, rules: Rule[], examples: Example[]}} PredicateSpec */

/** @param {string} contentDir absolute path to content/ @returns {PredicateSpec[]} sorted by id */
export function loadPredicates(contentDir) {
  const dir = join(contentDir, "predicates");
  const specs = readdirSync(dir)
    .filter((f) => f.endsWith(".toml"))
    .map((f) => parsePredicateFile(join(dir, f)));
  specs.sort((a, b) => a.id.localeCompare(b.id));
  return specs;
}

function parsePredicateFile(path) {
  const rules = [];
  const examples = [];
  let predicate = null;
  let current = null;

  for (const raw of readFileSync(path, "utf8").split("\n")) {
    const line = raw.trim();
    if (line === "" || line.startsWith("#")) continue;
    if (line === "[predicate]") {
      current = predicate = {};
      continue;
    }
    if (line === "[[rule]]") {
      current = {};
      rules.push(current);
      continue;
    }
    if (line === "[[example]]") {
      current = {};
      examples.push(current);
      continue;
    }
    const eq = line.indexOf(" = ");
    if (eq === -1 || !current) continue;
    current[line.slice(0, eq)] = parseTomlValue(line.slice(eq + 3));
  }

  if (!predicate) throw new Error(`${path}: missing [predicate] header`);
  return { id: predicate.id, version: predicate.version, description: predicate.description, rules, examples };
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

// Splits "a = 1, b = \"x, y\"" on top-level commas only, quote-aware so a comma inside a
// quoted value (none present in the corpus today, guarded anyway) never mis-splits.
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
