/*
    Appellation: canonical <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! Recursively-sorted, ASCII-only JSON text — the byte-exact match for
//! `models_run.py:627`'s `json.dump(payload, indent=2, sort_keys=True)`.
//!
//! Two properties `serde_json`'s own pretty printer does not give for free,
//! and both matter for a byte-exact port:
//!
//! - **Recursive sort.** A derived `Serialize` impl visits fields in
//!   declaration order; `#[serde(flatten)]` merges `extra` in afterward,
//!   sorted only within itself. Neither interleaves the way Python's
//!   `sort_keys=True` interleaves every key at a level, named field or not.
//!   Routing through [`serde_json::to_value`] first fixes this as a side
//!   effect of `serde_json::Map`'s storage: with the `preserve_order` cargo
//!   feature off — checked in `crates/core/Cargo.toml`; this workspace never
//!   turns it on — `Map<String, Value>` iterates in sorted key order, at
//!   every nesting level, recursively, for free.
//! - **ASCII-only output.** Python's `json.dump` defaults to
//!   `ensure_ascii=True`: every codepoint above `U+007F` is written as
//!   `\uXXXX`, astral codepoints as a UTF-16 surrogate pair. `serde_json`
//!   writes UTF-8 straight through. There is no `Formatter` hook for this
//!   that is safely usable under this crate's `alloc`-only floor (the
//!   `io::Write`-backed `Serializer`/`Formatter` machinery is a `std`-shaped
//!   API), so this module writes JSON text by hand from a
//!   [`serde_json::Value`] tree instead of delegating to `serde_json`'s
//!   writer at all. That also makes the sort-and-escape behavior exhaustively
//!   testable in one place rather than split across a trait impl.
#[cfg(feature = "alloc")]
use alloc::{
    format,
    string::{String, ToString},
};

use serde_json::Value;

/// Serialize `value` the way `models_run.py:627` serializes `run.json`:
/// recursively sorted keys, 2-space indent, ASCII-only.
///
/// Internal: the fallible half. [`crate::run::RunState::to_canonical_json`]
/// wraps this to match its documented infallible signature; see that
/// method's doc comment for exactly why the `expect` there is sound.
pub(crate) fn to_canonical_string<T>(value: &T) -> serde_json::Result<String>
where
    T: serde::Serialize,
{
    // `to_value` first: this is what makes the sort recursive (see module
    // docs). It never touches a filesystem or a `Write` impl -- it builds
    // the `Value` tree entirely in memory, so this call is available at the
    // `alloc` floor.
    let tree = serde_json::to_value(value)?;
    let mut out = String::new();
    write_value(&tree, 0, &mut out);
    Ok(out)
}

/// 2 spaces per indent level, matching Python's `indent=2`.
fn push_indent(out: &mut String, depth: usize) {
    for _ in 0..depth {
        out.push_str("  ");
    }
}

fn write_value(value: &Value, depth: usize, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        // `Number::to_string` matches Python's integer repr for every value
        // this domain actually carries (`schema_version`, `updated_at`, and
        // any integer-valued field a foreign implementation's `extra` bag
        // contributes). Byte-exact float formatting is not chased here: no
        // field this crate declares is a float, and the two encoders' float
        // reprs (Rust's ryu vs Python's `repr`) are not guaranteed identical
        // on every value -- a real but out-of-scope gap for a struct with no
        // float fields of its own.
        Value::Number(n) => out.push_str(&n.to_string()),
        Value::String(s) => write_json_string(s, out),
        Value::Array(items) => write_array(items, depth, out),
        Value::Object(map) => write_object(map, depth, out),
    }
}

fn write_array(items: &[Value], depth: usize, out: &mut String) {
    if items.is_empty() {
        out.push_str("[]");
        return;
    }
    out.push_str("[\n");
    let inner = depth + 1;
    let last = items.len() - 1;
    for (i, item) in items.iter().enumerate() {
        push_indent(out, inner);
        write_value(item, inner, out);
        if i != last {
            out.push(',');
        }
        out.push('\n');
    }
    push_indent(out, depth);
    out.push(']');
}

fn write_object(map: &serde_json::Map<String, Value>, depth: usize, out: &mut String) {
    if map.is_empty() {
        out.push_str("{}");
        return;
    }
    out.push_str("{\n");
    let inner = depth + 1;
    let last = map.len() - 1;
    // `serde_json::Map` without the `preserve_order` feature is a
    // `BTreeMap`; iteration order IS sort order. This is the entire
    // mechanism behind "recursively sorted" -- there is no explicit sort
    // call anywhere in this module because none is needed.
    for (i, (key, val)) in map.iter().enumerate() {
        push_indent(out, inner);
        write_json_string(key, out);
        out.push_str(": ");
        write_value(val, inner, out);
        if i != last {
            out.push(',');
        }
        out.push('\n');
    }
    push_indent(out, depth);
    out.push('}');
}

/// JSON-quote `s` the way Python's `json.dump(..., ensure_ascii=True)` does:
/// the standard `"`/`\`/control-character escapes (identical between the two
/// encoders -- both follow the same JSON spec table), plus every codepoint
/// above `U+007F` written as `\uXXXX` (a UTF-16 surrogate pair above
/// `U+FFFF`), which `serde_json` does NOT do by default.
fn write_json_string(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c if c.is_ascii() => out.push(c),
            c => {
                let mut units = [0u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    out.push_str(&format!("\\u{:04x}", unit));
                }
            }
        }
    }
    out.push('"');
}
