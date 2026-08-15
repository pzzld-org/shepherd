/*
    Appellation: filters <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! The one custom Jinja filter this crate registers: `tojson`.
//!
//! ## Why the builtin cannot be reused
//!
//! minijinja's own `tojson` (its `builtins` feature reserves the
//! registration slot; its separate `json` feature -- turned on by this
//! crate's own `json` feature, see `Cargo.toml` -- compiles the filter
//! body) is not a drop-in for Shepherd's Markdown JSON contract, two
//! independent ways, either alone breaking `output_sha256`: (1) it
//! unconditionally HTML-escapes
//! `<`/`>`/`&`/`'` (built for embedding JSON in an HTML `<script>` tag --
//! wrong for Markdown values that legitimately contain `&`/`'`); (2) it
//! does not sort map keys.
//!
//! ## Why this is not a second JSON serializer
//!
//! `[DO-NOT-DUPLICATE]` names `RunState::to_canonical_json` (#282, W1-S1)
//! as the workspace's one canonical sorted-JSON writer. It cannot be
//! reused directly: its backing `to_canonical_string` is `pub(crate)`
//! inside `shepherd_core` (`crates/core/**` is `must_not_touch` here
//! regardless), and even public, its format is a DELIBERATELY different
//! serialization -- 2-space indent, `ensure_ascii=True`, matching
//! the canonical run-state writer -- not this filter's single-line
//! `separators=(", ", ": "), ensure_ascii=False` format.
//! What IS shared is the mechanism, not a function call: neither crate
//! implements the recursive sort as code -- it falls out of
//! `serde_json::Map`'s storage for free, since this workspace never turns
//! on `preserve_order` (see `Cargo.toml`'s dependency comment). Only the
//! final text-formatting step below is new, because `serde_json` has no
//! `Formatter` hook for `ensure_ascii=False` with Python's separators.
#[cfg(all(feature = "alloc", not(feature = "std")))]
use alloc::{
    format,
    string::{String, ToString},
};

use minijinja::{Error, ErrorKind, Value};

/// `tojson` filter override with recursively sorted keys and the frozen format
/// `json.dumps(value, sort_keys=True, separators=(", ", ": "), ensure_ascii=False)`.
/// Register with `env.add_filter("tojson", sorted_tojson)`, as
/// [`crate::env::build`] does.
///
/// # Errors
///
/// Returns a minijinja [`Error`] if `value` cannot be represented as JSON
/// at all. Canonical callers pass plain strings, lists, or maps built from
/// already-JSON-shaped context data; this path exists because
/// [`serde_json::to_value`] is fallible in general.
pub fn sorted_tojson(value: Value) -> Result<String, Error> {
    let tree: serde_json::Value = serde_json::to_value(&value).map_err(|error| {
        Error::new(
            ErrorKind::InvalidOperation,
            format!("tojson: value is not JSON-serializable: {error}"),
        )
    })?;
    let mut out = String::new();
    write_value(&tree, &mut out);
    Ok(out)
}

fn write_value(value: &serde_json::Value, out: &mut String) {
    match value {
        serde_json::Value::Null => out.push_str("null"),
        serde_json::Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        serde_json::Value::Number(n) => out.push_str(&n.to_string()),
        serde_json::Value::String(s) => write_json_string(s, out),
        serde_json::Value::Array(items) => write_array(items, out),
        serde_json::Value::Object(map) => write_object(map, out),
    }
}

fn write_array(items: &[serde_json::Value], out: &mut String) {
    out.push('[');
    for (i, item) in items.iter().enumerate() {
        if i != 0 {
            out.push_str(", ");
        }
        write_value(item, out);
    }
    out.push(']');
}

fn write_object(map: &serde_json::Map<String, serde_json::Value>, out: &mut String) {
    out.push('{');
    // `serde_json::Map` without the `preserve_order` feature is a
    // `BTreeMap`: iteration order IS sorted order, at every nesting level
    // -- see the module docs' "not a second JSON serializer" section.
    for (i, (key, val)) in map.iter().enumerate() {
        if i != 0 {
            out.push_str(", ");
        }
        write_json_string(key, out);
        out.push_str(": ");
        write_value(val, out);
    }
    out.push('}');
}

/// JSON-quote `s` the way `json.dumps(..., ensure_ascii=False)` does: the
/// standard `"`/`\`/control-character escapes, and nothing else. Every
/// codepoint at or above `U+0080` -- and `U+007F` itself -- passes through
/// as UTF-8 untouched, unlike `crates/core::run::canonical`'s
/// `ensure_ascii=True` writer, which escapes everything above `U+007F`.
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
            c => out.push(c),
        }
    }
    out.push('"');
}

#[cfg(test)]
mod tests {
    /// Byte-exact compatibility vector exercising every property the
    /// builtin gets wrong at once: an unsorted top level, an unsorted
    /// nested map, an HTML-sensitive string, and a non-ASCII string.
    /// Rendered through `crate::env::build()`'s registered filter (not a
    /// direct function call) so a registration regression fails this test
    /// too, not just a logic regression.
    #[test]
    fn sorted_tojson_key_order() {
        let env = crate::env::build();
        let ctx = serde_json::json!({
            "value": {
                "b": 1,
                "a": [1, 2, {"z": 1, "y": 2}],
                "amp": "R&D <tag> 'quote' \"dq\"",
                "uni": "café ❤",
            }
        });
        let rendered = env
            .template_from_str("{{ value | tojson }}")
            .expect("template compiles")
            .render(&ctx)
            .expect("template renders");
        assert_eq!(
            rendered,
            r#"{"a": [1, 2, {"y": 2, "z": 1}], "amp": "R&D <tag> 'quote' \"dq\"", "b": 1, "uni": "café ❤"}"#,
        );
    }

    /// The negative control the spec mandates: "a parity test that cannot
    /// fail is not a parity test." Renders the SAME value through
    /// minijinja's un-overridden BUILTIN `tojson` (a plain
    /// `Environment::new()`, override never registered) and asserts it
    /// produces DIFFERENT bytes than `crate::env::build()`'s registered
    /// filter -- proving the override is load-bearing. If this assertion
    /// ever starts failing, the override silently stopped registering.
    #[test]
    fn negative_control_builtin_tojson_diverges() {
        let ctx = serde_json::json!({"value": {"b": 1, "a": "R&D <tag> 'q'"}});

        let naked = minijinja::Environment::new();
        let builtin = naked
            .template_from_str("{{ value | tojson }}")
            .expect("template compiles")
            .render(&ctx)
            .expect("template renders");

        let ours = crate::env::build()
            .template_from_str("{{ value | tojson }}")
            .expect("template compiles")
            .render(&ctx)
            .expect("template renders");

        assert_ne!(
            builtin, ours,
            "builtin tojson (HTML-escaped, unsorted) must diverge from the registered \
             sorted_tojson override -- identical output here means the override never took effect"
        );
    }
}
