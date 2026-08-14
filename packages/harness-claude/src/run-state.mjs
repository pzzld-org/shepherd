// packages/harness-claude/src/run-state.mjs -- the JS side of release-gate criterion C.4
// (plan.md W4-S4 Action 4): "a `run.json` written by the Rust binary is read and advanced
// by the Claude adapter with no migration step." `run.json`'s schema and canonical-encoding
// rules are owned by `crates/core/src/run.rs` / `crates/core/src/run/canonical.rs`
// (out of this step's file scope -- `crates/**` is must-not-touch); this module is a
// byte-exact PORT of that encoder's documented behavior, read directly from that source, not
// guessed:
//
//   - Keys are recursively sorted at every nesting level (`canonical.rs`'s own comment:
//     "routing through `serde_json::to_value` first... `Map<String, Value>` iterates in
//     sorted key order, at every nesting level, recursively, for free" -- this module
//     reproduces that by sorting `Object.keys` at every level it writes, not just the top).
//   - 2-space indent, matching `push_indent`.
//   - ASCII-only: every codepoint above `U+007F` is written `\uXXXX` (astral codepoints as a
//     UTF-16 surrogate pair, `write_json_string`'s own documented behavior) -- JS's
//     `JSON.stringify` does not do this, so this module writes JSON text by hand exactly as
//     `canonical.rs` does, for the identical reason (a byte-exact cross-implementation match).
//   - No trailing newline in the serialized text itself; `crates/core/src/run/atomic.rs`
//     appends exactly one `\n` when it writes to disk -- `storeRunState` below does the same,
//     so a JS-written `run.json` and a Rust-written one are indistinguishable on disk.
//
// This module does NOT reproduce `models_run.py`'s legacy-shape migrations (the same
// deliberate omission `crates/core/src/run.rs`'s own module doc names under
// "## What this module is deliberately NOT") -- `advanceStatus` only ever moves the
// `status` field forward through the closed lifecycle; every other field round-trips
// unchanged, satisfying "no migration step" by construction rather than by care.

import { readFileSync, writeFileSync } from "node:fs";

/** `RunState::default_status` plus every later stage `crates/core/src/run.rs`'s module doc
 * names as the closed (but schema-unenforced) status vocabulary. */
export const RUN_STATUSES = Object.freeze(["planted", "planned", "executing", "closing", "closed"]);

/**
 * Move `status` one step forward through {@link RUN_STATUSES}. Idempotent at the terminal
 * state (`closed` stays `closed` -- there is nowhere further to advance). Throws on a
 * status this module does not recognize rather than silently leaving it unchanged: an
 * unrecognized value is a real divergence between this JS port and the Rust schema, not
 * something to paper over.
 *
 * @param {string} status
 * @returns {string}
 */
export function advanceStatus(status) {
  const index = RUN_STATUSES.indexOf(status);
  if (index === -1) {
    throw new Error(`cannot advance unrecognized run status \`${status}\` -- expected one of ${RUN_STATUSES.join(", ")}`);
  }
  return RUN_STATUSES[Math.min(index + 1, RUN_STATUSES.length - 1)];
}

/**
 * @param {string} path absolute path to a `run.json`.
 * @returns {object} the parsed document, every field (named or not) intact.
 */
export function loadRunState(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

/**
 * @param {string} path absolute path to write to.
 * @param {object} state
 */
export function storeRunState(path, state) {
  writeFileSync(path, `${toCanonicalJson(state)}\n`, "utf8");
}

/**
 * Advance `state.status` one lifecycle step and stamp `updated_at`, mirroring
 * `crates/core/src/run.rs`'s documented split: `RunState::store` does not stamp
 * `updated_at` itself ("that is a mutator's job"), so this mutator does, matching
 * `save_run`'s behavior the doc comment describes.
 *
 * @param {object} state a loaded `run.json` document.
 * @returns {object} a new object -- `state` is not mutated in place.
 */
export function advanceRunState(state) {
  return {
    ...state,
    status: advanceStatus(state.status ?? "planted"),
    updated_at: Math.floor(Date.now() / 1000),
  };
}

/**
 * @param {unknown} value
 * @returns {string} recursively-sorted, 2-space-indented, ASCII-only JSON text -- the exact
 *   text `crates/core/src/run/canonical.rs`'s `to_canonical_string` produces for the same
 *   value.
 */
export function toCanonicalJson(value) {
  const out = [];
  writeValue(value, 0, out);
  return out.join("");
}

function writeValue(value, depth, out) {
  if (value === null || value === undefined) {
    out.push("null");
  } else if (typeof value === "boolean") {
    out.push(value ? "true" : "false");
  } else if (typeof value === "number") {
    out.push(String(value));
  } else if (typeof value === "string") {
    writeJsonString(value, out);
  } else if (Array.isArray(value)) {
    writeArray(value, depth, out);
  } else {
    writeObject(value, depth, out);
  }
}

function pushIndent(out, depth) {
  out.push("  ".repeat(depth));
}

function writeArray(items, depth, out) {
  if (items.length === 0) {
    out.push("[]");
    return;
  }
  out.push("[\n");
  const inner = depth + 1;
  items.forEach((item, i) => {
    pushIndent(out, inner);
    writeValue(item, inner, out);
    out.push(i !== items.length - 1 ? ",\n" : "\n");
  });
  pushIndent(out, depth);
  out.push("]");
}

function writeObject(obj, depth, out) {
  const keys = Object.keys(obj).sort();
  if (keys.length === 0) {
    out.push("{}");
    return;
  }
  out.push("{\n");
  const inner = depth + 1;
  keys.forEach((key, i) => {
    pushIndent(out, inner);
    writeJsonString(key, out);
    out.push(": ");
    writeValue(obj[key], inner, out);
    out.push(i !== keys.length - 1 ? ",\n" : "\n");
  });
  pushIndent(out, depth);
  out.push("}");
}

const SHORT_ESCAPES = Object.freeze({
  '"': '\\"',
  "\\": "\\\\",
  "\b": "\\b",
  "\f": "\\f",
  "\n": "\\n",
  "\r": "\\r",
  "\t": "\\t",
});

function writeJsonString(s, out) {
  out.push('"');
  for (const ch of s) {
    const code = ch.codePointAt(0);
    if (SHORT_ESCAPES[ch]) {
      out.push(SHORT_ESCAPES[ch]);
    } else if (code < 0x20) {
      out.push(`\\u${code.toString(16).padStart(4, "0")}`);
    } else if (code < 0x80) {
      out.push(ch);
    } else if (code <= 0xffff) {
      out.push(`\\u${code.toString(16).padStart(4, "0")}`);
    } else {
      // Astral codepoint -- encode as a UTF-16 surrogate pair, matching
      // `write_json_string`'s `char::encode_utf16`.
      const high = 0xd800 + ((code - 0x10000) >> 10);
      const low = 0xdc00 + ((code - 0x10000) & 0x3ff);
      out.push(`\\u${high.toString(16).padStart(4, "0")}\\u${low.toString(16).padStart(4, "0")}`);
    }
  }
  out.push('"');
}
