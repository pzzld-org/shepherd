// packages/harness-codex/src/toml-lite.mjs -- a minimal, hand-rolled reader for the flat
// TOML subset content/predicates/*.toml actually uses: a `[predicate]` table, `[[rule]]` and
// `[[example]]` arrays-of-tables, and `key = value` lines where value is a double-quoted
// string, a bare integer, `true`/`false`, or a single-level `{ k = v, k2 = v2 }` inline table.
//
// WHY NOT A TOML LIBRARY. Mirrors packages/compiler/src/frontmatter.mjs's own reasoning for
// hand-frontmatter over a YAML dependency: content/predicates/*.toml's shape is a narrow,
// fully-enumerated subset -- no arrays-of-scalars, no nested inline tables, no multi-line
// strings, no escaped quotes, no comma inside a quoted value -- verified with `rg` across the
// entire corpus at authorship time (four files, ~35 rule/example blocks), not guessed. Adding
// `@iarna/toml` or similar for a shape this regular would be a new build-manifest dependency
// this coder's brief has no standing approval to add (agents/coder.md §Prohibitions).

/**
 * @typedef {object} TomlDoc
 * @property {Record<string, string|number|boolean>} predicate the `[predicate]` table.
 * @property {Record<string, string>[]} rule every `[[rule]]` block, in file order.
 * @property {Record<string, string|number|boolean|Record<string, string|boolean>>[]} example
 *   every `[[example]]` block, in file order; `context` (when present) is itself a flat
 *   `{ k: v }` object.
 */

/**
 * @param {string} text raw `content/predicates/<id>.toml` file contents.
 * @returns {TomlDoc}
 */
export function parsePredicateToml(text) {
  const doc = { predicate: {}, rule: [], example: [] };
  /** @type {Record<string, unknown>|null} */
  let current = null;

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line === "" || line.startsWith("#")) continue;

    const arrayHeader = line.match(/^\[\[(\w+)\]\]$/);
    if (arrayHeader) {
      const record = {};
      (doc[arrayHeader[1]] ??= []).push(record);
      current = record;
      continue;
    }

    const tableHeader = line.match(/^\[(\w+)\]$/);
    if (tableHeader) {
      current = doc[tableHeader[1]] ??= {};
      continue;
    }

    const sep = line.indexOf(" = ");
    if (sep === -1) {
      throw new Error(`toml-lite: malformed line (expected "key = value"): ${JSON.stringify(rawLine)}`);
    }
    if (!current) {
      throw new Error(`toml-lite: key/value line appears before any [section]/[[array]] header: ${JSON.stringify(rawLine)}`);
    }
    current[line.slice(0, sep).trim()] = parseValue(line.slice(sep + 3));
  }

  return doc;
}

/** @param {string} raw @returns {string|number|boolean|Record<string, unknown>} */
function parseValue(raw) {
  const trimmed = raw.trim();
  if (trimmed.startsWith('"')) return trimmed.slice(1, trimmed.lastIndexOf('"'));
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (trimmed.startsWith("{")) return parseInlineTable(trimmed);
  if (/^-?\d+$/.test(trimmed)) return Number(trimmed);
  throw new Error(`toml-lite: unsupported value: ${JSON.stringify(raw)}`);
}

/** @param {string} raw a `{ k = v, k2 = v2 }` span. @returns {Record<string, unknown>} */
function parseInlineTable(raw) {
  const inner = raw.slice(raw.indexOf("{") + 1, raw.lastIndexOf("}")).trim();
  const table = {};
  if (inner === "") return table;
  // Safe over this corpus only: no inline-table value ever contains a literal `,` (verified
  // with `rg -o '\{[^}]*\}' content/predicates/*.toml | rg ',' | rg '"[^"]*,[^"]*"'` -- zero
  // hits), so a flat comma split never mis-cuts a quoted string mid-value.
  for (const pair of inner.split(",")) {
    const sep = pair.indexOf("=");
    if (sep === -1) {
      throw new Error(`toml-lite: malformed inline-table pair: ${JSON.stringify(pair)}`);
    }
    table[pair.slice(0, sep).trim()] = parseValue(pair.slice(sep + 1));
  }
  return table;
}
