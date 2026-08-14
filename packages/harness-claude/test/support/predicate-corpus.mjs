// packages/harness-claude/test/support/predicate-corpus.mjs -- a narrow, local
// `content/predicates/*.toml` reader for corpus-replay tests (T2-serve-wiring), SHARED between
// `packages/harness-claude/test/guard-serve-corpus.test.mjs` and
// `packages/harness-codex/test/guard-serve-corpus.test.mjs` (cross-package import, same
// convention `packages/harness-codex/src/guard-serve-*.mjs` already establish for production
// code -- test support code gets the same "factor it once" treatment).
//
// Same technique as `packages/harness-pi/test/guard-predicates.test.mjs`'s own local
// `loadPredicateExamples`/`parsePredicateFile` (not importable: those are unexported top-level
// functions in a script this step's file scope cannot touch, and that package is TypeScript-only
// tooling harness-claude/harness-codex do not share -- see `src/guard-serve-engine.mjs`'s header).
// Reads `content/predicates/*.toml` LIVE on every call -- a corpus change is caught the next test
// run, never a hand-copied fixture list, matching `src/roles.mjs`'s own "reads content/ live"
// philosophy this monorepo already established.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

export const CANONICAL_EXAMPLE_KEYS = new Set(["name", "kind", "role", "action", "context", "result", "halt_code", "note"]);

/**
 * @param {string} contentDir absolute path to `content/`.
 * @returns {Array<{id: string, examples: Array<Record<string, unknown>>}>} one entry per
 *   `content/predicates/*.toml` file, sorted by filename.
 */
export function loadPredicateExamples(contentDir) {
  const dir = join(contentDir, "predicates");
  return readdirSync(dir)
    .filter((f) => f.endsWith(".toml"))
    .sort()
    .map((f) => parsePredicateFile(join(dir, f)));
}

function parsePredicateFile(path) {
  let id;
  const examples = [];
  let current;
  let section;

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
