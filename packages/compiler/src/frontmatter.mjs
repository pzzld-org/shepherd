// packages/compiler/src/frontmatter.mjs -- a minimal, hand-rolled parser for the flat
// `---`-delimited frontmatter block every content/roles/*.md and content/skills/*/SKILL.md
// file carries (content/RECONCILIATION.md, content/roles/coder.md).
//
// WHY NOT A YAML LIBRARY. The frontmatter this repo actually writes is a strict subset of
// YAML -- flat `key: value` pairs, bracketed inline arrays, double-quoted strings, full-line
// `#` comments, and trailing `  #` inline comments -- never a nested mapping, block scalar,
// or anchor. Adding a general YAML dependency to parse a shape this narrow would be a new
// build-manifest dependency for a problem five regexes already solve exactly, and every shape
// below is verified against the real corpus (`rg` across content/roles/ + content/skills/
// during authorship), not guessed.

/**
 * @param {string} text raw file contents, frontmatter block first.
 * @returns {{attrs: Record<string, string|boolean|string[]>, body: string}}
 */
export function parseFrontmatter(text) {
  const lines = text.split(/\r?\n/);
  if (lines[0]?.trim() !== "---") {
    throw new Error("missing frontmatter opening `---`");
  }

  const attrs = {};
  let i = 1;
  for (; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim() === "---") {
      i++;
      break;
    }
    if (line.trim() === "" || line.trimStart().startsWith("#")) continue; // blank / full-line comment
    const sep = line.indexOf(": ");
    if (sep === -1) {
      throw new Error(`malformed frontmatter line (expected "key: value"): ${JSON.stringify(line)}`);
    }
    attrs[line.slice(0, sep).trim()] = parseScalar(line.slice(sep + 2));
  }
  if (i > lines.length) {
    throw new Error("frontmatter block never closed with a second `---`");
  }

  return { attrs, body: lines.slice(i).join("\n") };
}

/** @param {string} raw @returns {string|boolean|string[]} */
function parseScalar(raw) {
  const trimmed = raw.trim();

  if (trimmed.startsWith('"')) {
    const close = trimmed.lastIndexOf('"');
    return trimmed.slice(1, close);
  }

  if (trimmed.startsWith("[")) {
    const close = trimmed.indexOf("]");
    return trimmed
      .slice(1, close)
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }

  // An unquoted scalar may carry a trailing `  # comment` (two-or-more spaces then `#`).
  const commentAt = trimmed.search(/\s{2,}#/);
  const value = (commentAt === -1 ? trimmed : trimmed.slice(0, commentAt)).trim();
  if (value === "true") return true;
  if (value === "false") return false;
  return value;
}
