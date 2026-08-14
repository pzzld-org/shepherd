// packages/compiler/src/markdown.mjs -- renders a `---`-delimited frontmatter block plus a
// markdown body. The write-side mirror of frontmatter.mjs's read-side parser, kept just as
// narrow: an ordered list of pre-formatted "key: value" lines, joined around a body. Callers
// build each line explicitly via `field`/`quoted`/`array` rather than this module inferring a
// representation -- there is exactly one way to write a bool, a quoted string, or an array
// here, matching the one way content/ itself already reads them (frontmatter.mjs).

/**
 * @param {string[]} fieldLines pre-formatted `"key: value"` lines, in emission order.
 * @param {string} body
 * @returns {string} a complete file, frontmatter + blank line + body, newline-terminated.
 */
export function renderFrontmatterFile(fieldLines, body) {
  const trimmedBody = body.trim();
  // A bare `---` thematic break inside the body would look like the frontmatter's closing
  // fence to any parser reading this file, corrupting it silently. Verified absent across
  // the whole content/ corpus at authorship time (`rg -n '^---$'` over every role/skill
  // body) -- fail loudly rather than assume that stays true forever.
  if (/^---\s*$/m.test(trimmedBody)) {
    throw new Error("role/skill body contains a bare `---` line, which would corrupt the emitted frontmatter fence");
  }
  return ["---", ...fieldLines, "---", "", trimmedBody, ""].join("\n");
}

/** @param {string} key @param {string} value @returns {string} */
export function field(key, value) {
  return `${key}: ${value}`;
}

/** Wraps free text as a frontmatter double-quoted scalar. @param {string} text */
export function quoted(text) {
  return `"${text}"`;
}

/** Renders a frontmatter inline array. @param {string[]} items */
export function array(items) {
  return `[${items.join(", ")}]`;
}
