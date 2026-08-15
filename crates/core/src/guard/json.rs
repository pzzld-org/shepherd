/*
    Appellation: guard-json <module>
    Created At: 2026.08.14:00:00:00
    Contrib: @FL03
*/
//! Byte-exact verdict serialization for the v6.4.5 guard wire.

use alloc::{collections::BTreeMap, fmt::Write, string::String};

use super::{Decision, GuardEngine, GuardError, GuardValue, Verdict};

impl GuardEngine {
    /// Decode one JSON request and evaluate it through the typed engine path.
    ///
    /// # Errors
    ///
    /// Returns [`GuardError::Json`] for malformed JSON. Decoded request-shape
    /// defects, including non-string raw roles, produce unresolved verdicts.
    pub fn evaluate_json(&self, contents: &str) -> Result<Verdict, GuardError> {
        let value: serde_json::Value = serde_json::from_str(contents)
            .map_err(|error| GuardError::Json(alloc::format!("malformed JSON: {error}")))?;
        self.evaluate(&GuardValue::from(value))
    }
}

impl From<serde_json::Value> for GuardValue {
    fn from(value: serde_json::Value) -> Self {
        match value {
            serde_json::Value::Null => Self::Null,
            serde_json::Value::Bool(value) => Self::Bool(value),
            serde_json::Value::Number(value) => {
                if let Some(value) = value.as_i64() {
                    Self::Integer(value)
                } else if let Some(value) = value.as_u64() {
                    Self::Unsigned(value)
                } else {
                    Self::Float(
                        value
                            .as_f64()
                            .expect("a serde_json Number is representable as i64, u64, or f64"),
                    )
                }
            }
            serde_json::Value::String(value) => Self::String(value),
            serde_json::Value::Array(values) => {
                Self::Array(values.into_iter().map(Self::from).collect())
            }
            serde_json::Value::Object(values) => Self::Object(
                values
                    .into_iter()
                    .map(|(key, value)| (key, Self::from(value)))
                    .collect::<BTreeMap<_, _>>(),
            ),
        }
    }
}

impl Verdict {
    /// Serialize the versioned guard wire in its pinned field order, spacing,
    /// and ASCII form.
    pub fn to_wire_json(&self) -> String {
        let mut output = String::from("{");
        let mut first = true;
        push_string_field(&mut output, &mut first, "decision", self.decision.as_str());

        match self.decision {
            Decision::Allow => {}
            Decision::Deny => {
                push_optional_string_field(
                    &mut output,
                    &mut first,
                    "predicate",
                    self.predicate.as_deref(),
                );
                push_optional_string_field(&mut output, &mut first, "rule", self.rule.as_deref());
                push_optional_string_field(
                    &mut output,
                    &mut first,
                    "halt_code",
                    self.halt_code.as_deref(),
                );
                push_optional_string_field(
                    &mut output,
                    &mut first,
                    "reason",
                    self.reason.as_deref(),
                );
            }
            Decision::Unresolved => {
                push_optional_string_field(
                    &mut output,
                    &mut first,
                    "reason",
                    self.reason.as_deref(),
                );
                if !self.missing.is_empty() {
                    push_separator(&mut output, &mut first);
                    push_wire_string(&mut output, "missing");
                    output.push_str(": [");
                    for (index, missing) in self.missing.iter().enumerate() {
                        if index != 0 {
                            output.push_str(", ");
                        }
                        push_wire_string(&mut output, missing);
                    }
                    output.push(']');
                }
            }
        }
        output.push('}');
        output
    }
}

fn push_optional_string_field(
    output: &mut String,
    first: &mut bool,
    key: &str,
    value: Option<&str>,
) {
    if let Some(value) = value {
        push_string_field(output, first, key, value);
    }
}

fn push_string_field(output: &mut String, first: &mut bool, key: &str, value: &str) {
    push_separator(output, first);
    push_wire_string(output, key);
    output.push_str(": ");
    push_wire_string(output, value);
}

fn push_separator(output: &mut String, first: &mut bool) {
    if *first {
        *first = false;
    } else {
        output.push_str(", ");
    }
}

fn push_wire_string(output: &mut String, value: &str) {
    output.push('"');
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\u{0008}' => output.push_str("\\b"),
            '\u{000c}' => output.push_str("\\f"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            character if character <= '\u{001f}' => {
                write!(output, "\\u{:04x}", u32::from(character))
                    .expect("writing a JSON escape to String cannot fail");
            }
            character @ '\u{0020}'..='\u{007e}' => output.push(character),
            character if character <= '\u{ffff}' => {
                write!(output, "\\u{:04x}", u32::from(character))
                    .expect("writing a JSON escape to String cannot fail");
            }
            character => {
                let codepoint = u32::from(character) - 0x1_0000;
                let high = 0xd800 + (codepoint >> 10);
                let low = 0xdc00 + (codepoint & 0x3ff);
                write!(output, "\\u{high:04x}\\u{low:04x}")
                    .expect("writing a surrogate pair to String cannot fail");
            }
        }
    }
    output.push('"');
}
