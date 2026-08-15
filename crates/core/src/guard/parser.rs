/*
    Appellation: guard-parser <module>
    Created At: 2026.08.14:00:00:00
    Contrib: @FL03
*/
//! Parsers for predicate TOML and role Markdown frontmatter.

use alloc::{
    collections::BTreeMap,
    format,
    string::{String, ToString},
    vec::Vec,
};
use core::str::FromStr;

#[cfg(feature = "std")]
use super::GuardEngine;
use super::{GuardError, GuardValue, PredicateDoc, PredicateExample, RoleFact, Rule};

const CANONICAL_EXAMPLE_KEYS: &[&str] = &[
    "name",
    "kind",
    "role",
    "action",
    "context",
    "result",
    "halt_code",
    "note",
];
const YAML_1_1_IMPLICIT_WORDS: &[&str] = &["yes", "no", "true", "false", "on", "off", "null"];

/// Parse one `content/predicates/*.toml` source into typed guard values.
pub fn parse_predicate_toml(source_name: &str, contents: &str) -> Result<PredicateDoc, GuardError> {
    let root = toml::Table::from_str(contents).map_err(|error| {
        GuardError::Predicate(format!("{source_name}: malformed TOML: {error}"))
    })?;
    let predicate = root
        .get("predicate")
        .and_then(toml::Value::as_table)
        .ok_or_else(|| missing_predicate_id(source_name))?;
    let id = required_string(predicate, "id")
        .filter(|id| !id.is_empty())
        .map(String::from)
        .ok_or_else(|| missing_predicate_id(source_name))?;
    let version = optional_integer(predicate, "version", source_name, "[predicate]")?.unwrap_or(1);
    let description =
        optional_string(predicate, "description", source_name, "[predicate]")?.unwrap_or_default();

    let rules = parse_rules(source_name, root.get("rule"))?;
    let examples = parse_examples(source_name, root.get("example"))?;

    Ok(PredicateDoc {
        id,
        version,
        description,
        rules,
        examples,
    })
}

/// Parse the closed frontmatter subset used by guard role documents.
///
/// The portable grammar accepts a non-empty string `role`, flat boolean
/// `write_eligible` and `dispatchable` fields, and one inline `capabilities`
/// string array. Plain strings use the closed ASCII identifier grammar
/// `[A-Za-z][A-Za-z0-9_-]*`, excluding YAML 1.1 boolean/null words; values
/// outside that grammar must be quoted. Single-quoted strings decode doubled
/// quotes, while double-quoted YAML escape sequences remain unsupported.
/// A mapping colon must be followed by an ASCII space or the end of its line;
/// tabs are unsupported outside quotes; and `#` starts a comment only at the
/// start of a line or after an ASCII space. Block sequences, malformed quotes,
/// empty capability items, and commas inside quoted capability items are
/// rejected rather than reinterpreted.
pub fn parse_role_markdown(source_name: &str, contents: &str) -> Result<RoleFact, GuardError> {
    let mut delimiters = contents
        .lines()
        .enumerate()
        .filter_map(|(index, line)| is_frontmatter_delimiter(line).then_some(index));
    let Some(opening) = delimiters.next() else {
        return Err(missing_frontmatter(source_name));
    };
    let Some(closing) = delimiters.next() else {
        return Err(missing_frontmatter(source_name));
    };

    let lines: Vec<&str> = contents.lines().collect();
    let mut fields = BTreeMap::new();
    for line in &lines[opening + 1..closing] {
        let Some(line) = parse_frontmatter_line(source_name, line)? else {
            continue;
        };
        let Some((key, value)) = line.split_once(':') else {
            return Err(GuardError::Role(format!(
                "{source_name}: malformed YAML frontmatter line `{line}`"
            )));
        };
        if !value.is_empty() && !value.starts_with(' ') {
            return Err(GuardError::Role(format!(
                "{source_name}: malformed YAML frontmatter line `{line}`: mapping separator must be followed by an ASCII space"
            )));
        }
        let key = key.trim();
        let value = value.trim();
        if key == "capabilities" && value.is_empty() {
            return Err(GuardError::Role(format!(
                "{source_name}: `capabilities` must be an inline string array; block sequences are unsupported"
            )));
        }
        fields.insert(String::from(key), String::from(value));
    }

    let role = fields
        .get("role")
        .ok_or_else(|| GuardError::Role(format!("{source_name}: missing `role:` in frontmatter")))
        .and_then(|value| parse_role_string(source_name, value))?;
    let write_eligible = parse_yaml_bool(
        source_name,
        "write_eligible",
        fields.get("write_eligible"),
        false,
    )?;
    let dispatchable = parse_yaml_bool(
        source_name,
        "dispatchable",
        fields.get("dispatchable"),
        true,
    )?;
    let capabilities = match fields.get("capabilities") {
        None => Vec::new(),
        Some(value) => parse_yaml_string_array(source_name, "capabilities", value)?,
    };

    Ok(RoleFact {
        role,
        write_eligible,
        dispatchable,
        capabilities,
    })
}

fn is_frontmatter_delimiter(line: &str) -> bool {
    line.trim_end_matches(char::is_whitespace) == "---"
}

fn parse_frontmatter_line<'a>(
    source_name: &str,
    line: &'a str,
) -> Result<Option<&'a str>, GuardError> {
    let mut single_quoted = false;
    let mut double_quoted = false;
    let mut characters = line.char_indices().peekable();
    let mut comment = None;
    while let Some((index, character)) = characters.next() {
        match character {
            '\t' if !single_quoted && !double_quoted => {
                return Err(GuardError::Role(format!(
                    "{source_name}: malformed YAML frontmatter line `{line}`: tabs are unsupported outside quoted values"
                )));
            }
            '\'' if !double_quoted && single_quoted => {
                if characters.peek().is_some_and(|(_, next)| *next == '\'') {
                    characters.next();
                } else {
                    single_quoted = false;
                }
            }
            '\'' if !double_quoted => single_quoted = true,
            '"' if !single_quoted => double_quoted = !double_quoted,
            '#' if !single_quoted && !double_quoted => {
                if index == 0 || line[..index].ends_with(' ') {
                    comment = Some(index);
                    break;
                }
                return Err(GuardError::Role(format!(
                    "{source_name}: malformed YAML frontmatter line `{line}`: comment marker must follow an ASCII space"
                )));
            }
            _ => {}
        }
    }
    let line = line[..comment.unwrap_or(line.len())].trim();
    Ok((!line.is_empty()).then_some(line))
}

#[derive(Clone, Copy)]
enum StringScalarError {
    EscapeSequence,
    ImplicitNonString,
    MalformedQuote,
    UnterminatedQuote,
}

fn parse_role_string(source_name: &str, value: &str) -> Result<String, GuardError> {
    let role = parse_yaml_string_scalar(value).map_err(|error| match error {
        StringScalarError::EscapeSequence => GuardError::Role(format!(
            "{source_name}: `role` does not support YAML escape sequences"
        )),
        StringScalarError::ImplicitNonString => {
            GuardError::Role(format!("{source_name}: `role` must be a non-empty string"))
        }
        StringScalarError::MalformedQuote => GuardError::Role(format!(
            "{source_name}: `role` contains a malformed quoted item"
        )),
        StringScalarError::UnterminatedQuote => GuardError::Role(format!(
            "{source_name}: `role` contains an unterminated quoted item"
        )),
    })?;
    if role.is_empty() {
        return Err(GuardError::Role(format!(
            "{source_name}: `role` must be a non-empty string"
        )));
    }

    Ok(role)
}

fn parse_yaml_string_scalar(value: &str) -> Result<String, StringScalarError> {
    let value = value.trim();
    if value.starts_with('"') {
        if value.len() < 2 || !value.ends_with('"') {
            return Err(StringScalarError::UnterminatedQuote);
        }
        let inner = &value[1..value.len() - 1];
        if inner.contains('\\') {
            return Err(StringScalarError::EscapeSequence);
        }
        if inner.contains('"') {
            return Err(StringScalarError::MalformedQuote);
        }
        return Ok(String::from(inner));
    }
    if value.starts_with('\'') {
        if value.len() < 2 || !value.ends_with('\'') {
            return Err(StringScalarError::UnterminatedQuote);
        }
        let inner = &value[1..value.len() - 1];
        let mut decoded = String::new();
        let mut characters = inner.chars().peekable();
        while let Some(character) = characters.next() {
            if character != '\'' {
                decoded.push(character);
            } else if characters.next_if_eq(&'\'').is_some() {
                decoded.push('\'');
            } else {
                return Err(StringScalarError::MalformedQuote);
            }
        }
        return Ok(decoded);
    }
    if value
        .chars()
        .any(|character| matches!(character, '\'' | '"'))
    {
        return Err(StringScalarError::MalformedQuote);
    }
    if !is_plain_yaml_string(value) {
        return Err(StringScalarError::ImplicitNonString);
    }
    Ok(String::from(value))
}

fn is_plain_yaml_string(value: &str) -> bool {
    let mut characters = value.chars();
    characters
        .next()
        .is_some_and(|first| first.is_ascii_alphabetic())
        && characters
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
        && !YAML_1_1_IMPLICIT_WORDS
            .iter()
            .any(|word| value.eq_ignore_ascii_case(word))
}

fn parse_yaml_bool(
    source_name: &str,
    key: &str,
    value: Option<&String>,
    default: bool,
) -> Result<bool, GuardError> {
    let Some(value) = value else {
        return Ok(default);
    };
    if value.eq_ignore_ascii_case("true") {
        Ok(true)
    } else if value.eq_ignore_ascii_case("false") {
        Ok(false)
    } else {
        Err(GuardError::Role(format!(
            "{source_name}: `{key}` must be a boolean"
        )))
    }
}

fn parse_yaml_string_array(
    source_name: &str,
    key: &str,
    value: &str,
) -> Result<Vec<String>, GuardError> {
    let value = value.trim();
    if !value.starts_with('[') || !value.ends_with(']') {
        return Err(GuardError::Role(format!(
            "{source_name}: `{key}` must be an inline string array"
        )));
    }
    let inner = value[1..value.len() - 1].trim();
    if inner.is_empty() {
        return Ok(Vec::new());
    }

    let mut quote = None;
    let mut characters = inner.chars().peekable();
    while let Some(character) = characters.next() {
        match quote {
            None if matches!(character, '\'' | '"') => quote = Some(character),
            Some('"') if character == '"' => quote = None,
            Some('"') if character == '\\' => {
                return Err(GuardError::Role(format!(
                    "{source_name}: `{key}` does not support YAML escape sequences"
                )));
            }
            Some('\'') if character == '\'' => {
                if characters.next_if_eq(&'\'').is_none() {
                    quote = None;
                }
            }
            Some(_) if character == ',' => {
                return Err(GuardError::Role(format!(
                    "{source_name}: `{key}` does not support commas inside quoted items"
                )));
            }
            _ => {}
        }
    }
    if quote.is_some() {
        return Err(GuardError::Role(format!(
            "{source_name}: `{key}` contains an unterminated quoted item"
        )));
    }
    if inner.split(',').any(|item| item.trim().is_empty()) {
        return Err(GuardError::Role(format!(
            "{source_name}: `{key}` does not support empty items"
        )));
    }
    inner
        .split(',')
        .map(|item| {
            parse_yaml_string_scalar(item).map_err(|error| match error {
                StringScalarError::EscapeSequence => GuardError::Role(format!(
                    "{source_name}: `{key}` does not support YAML escape sequences"
                )),
                StringScalarError::ImplicitNonString => {
                    GuardError::Role(format!("{source_name}: `{key}` must contain only strings"))
                }
                StringScalarError::MalformedQuote => GuardError::Role(format!(
                    "{source_name}: `{key}` contains a malformed quoted item"
                )),
                StringScalarError::UnterminatedQuote => GuardError::Role(format!(
                    "{source_name}: `{key}` contains an unterminated quoted item"
                )),
            })
        })
        .collect()
}

fn missing_frontmatter(source_name: &str) -> GuardError {
    GuardError::Role(format!("{source_name}: missing YAML frontmatter"))
}

fn parse_rules(source_name: &str, value: Option<&toml::Value>) -> Result<Vec<Rule>, GuardError> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    let array = value.as_array().ok_or_else(|| {
        GuardError::Predicate(format!("{source_name}: `rule` must be an array of tables"))
    })?;

    array
        .iter()
        .enumerate()
        .map(|(index, value)| {
            let table = value.as_table().ok_or_else(|| {
                GuardError::Predicate(format!(
                    "{source_name}: rule #{} must be a table",
                    index + 1
                ))
            })?;
            Ok(Rule {
                id: required_rule_string(source_name, table, index, "id")?,
                description: optional_string(
                    table,
                    "description",
                    source_name,
                    &format!("rule #{}", index + 1),
                )?
                .unwrap_or_default(),
                subject: required_rule_string(source_name, table, index, "subject")?,
                action: required_rule_string(source_name, table, index, "action")?,
                effect: required_rule_string(source_name, table, index, "effect")?,
            })
        })
        .collect()
}

fn parse_examples(
    source_name: &str,
    value: Option<&toml::Value>,
) -> Result<Vec<PredicateExample>, GuardError> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    let array = value.as_array().ok_or_else(|| {
        GuardError::Predicate(format!(
            "{source_name}: `example` must be an array of tables"
        ))
    })?;

    array
        .iter()
        .enumerate()
        .map(|(index, value)| parse_example(source_name, index, value))
        .collect()
}

fn parse_example(
    source_name: &str,
    index: usize,
    value: &toml::Value,
) -> Result<PredicateExample, GuardError> {
    let table = value.as_table().ok_or_else(|| {
        GuardError::Predicate(format!(
            "{source_name}: example #{} must be a table",
            index + 1
        ))
    })?;
    let label = format!("example #{}", index + 1);
    let context = match table.get("context") {
        None => BTreeMap::new(),
        Some(toml::Value::Table(context)) => context
            .iter()
            .map(|(key, value)| (key.clone(), toml_value(value)))
            .collect(),
        Some(_) => {
            return Err(GuardError::Predicate(format!(
                "{source_name}: {label} `context` must be a table"
            )));
        }
    };
    let extra = table
        .iter()
        .filter(|(key, _)| !CANONICAL_EXAMPLE_KEYS.contains(&key.as_str()))
        .map(|(key, value)| (key.clone(), toml_value(value)))
        .collect();

    Ok(PredicateExample {
        name: required_example_string(source_name, table, index, "name")?,
        kind: required_example_string(source_name, table, index, "kind")?,
        role: table
            .get("role")
            .map(toml_value)
            .ok_or_else(|| missing_example_field(source_name, index, "role"))?,
        action: required_example_string(source_name, table, index, "action")?,
        context,
        result: required_example_string(source_name, table, index, "result")?,
        halt_code: optional_string(table, "halt_code", source_name, &label)?,
        note: optional_string(table, "note", source_name, &label)?,
        extra,
    })
}

fn required_rule_string(
    source_name: &str,
    table: &toml::Table,
    index: usize,
    key: &str,
) -> Result<String, GuardError> {
    required_string(table, key)
        .map(String::from)
        .ok_or_else(|| {
            GuardError::Predicate(format!(
                "{source_name}: rule #{} missing string `{key}`",
                index + 1
            ))
        })
}

fn required_example_string(
    source_name: &str,
    table: &toml::Table,
    index: usize,
    key: &str,
) -> Result<String, GuardError> {
    required_string(table, key)
        .map(String::from)
        .ok_or_else(|| missing_example_field(source_name, index, key))
}

fn missing_example_field(source_name: &str, index: usize, key: &str) -> GuardError {
    GuardError::Predicate(format!(
        "{source_name}: example #{} missing `{key}`",
        index + 1
    ))
}

fn missing_predicate_id(source_name: &str) -> GuardError {
    GuardError::Predicate(format!("{source_name}: missing [predicate].id"))
}

fn required_string<'a>(table: &'a toml::Table, key: &str) -> Option<&'a str> {
    table.get(key).and_then(toml::Value::as_str)
}

fn optional_string(
    table: &toml::Table,
    key: &str,
    source_name: &str,
    owner: &str,
) -> Result<Option<String>, GuardError> {
    match table.get(key) {
        None => Ok(None),
        Some(toml::Value::String(value)) => Ok(Some(value.clone())),
        Some(_) => Err(GuardError::Predicate(format!(
            "{source_name}: {owner} `{key}` must be a string"
        ))),
    }
}

fn optional_integer(
    table: &toml::Table,
    key: &str,
    source_name: &str,
    owner: &str,
) -> Result<Option<i64>, GuardError> {
    match table.get(key) {
        None => Ok(None),
        Some(toml::Value::Integer(value)) => Ok(Some(*value)),
        Some(_) => Err(GuardError::Predicate(format!(
            "{source_name}: {owner} `{key}` must be an integer"
        ))),
    }
}

fn toml_value(value: &toml::Value) -> GuardValue {
    match value {
        toml::Value::String(value) => GuardValue::String(value.clone()),
        toml::Value::Integer(value) => GuardValue::Integer(*value),
        toml::Value::Float(value) => GuardValue::Float(*value),
        toml::Value::Boolean(value) => GuardValue::Bool(*value),
        toml::Value::Datetime(value) => GuardValue::String(value.to_string()),
        toml::Value::Array(values) => GuardValue::Array(values.iter().map(toml_value).collect()),
        toml::Value::Table(values) => GuardValue::Object(
            values
                .iter()
                .map(|(key, value)| (key.clone(), toml_value(value)))
                .collect(),
        ),
    }
}

#[cfg(feature = "std")]
impl GuardEngine {
    /// Load guard content from one explicit `content/` path.
    ///
    /// A missing predicates or roles directory is an empty, degraded corpus,
    /// matching the pinned role-source contract. This function never searches upward or
    /// reads process environment variables.
    pub fn load_content(content_dir: impl AsRef<std::path::Path>) -> Result<Self, GuardError> {
        let content_dir = content_dir.as_ref();
        let mut predicates = Vec::new();
        for path in sorted_sources(&content_dir.join("predicates"), "toml")? {
            let contents = std::fs::read_to_string(&path)
                .map_err(|error| GuardError::Io(format!("{}: {error}", path.display())))?;
            let source_name = path
                .file_name()
                .and_then(std::ffi::OsStr::to_str)
                .unwrap_or("<non-utf8 predicate filename>");
            predicates.push(parse_predicate_toml(source_name, &contents)?);
        }

        let mut role_facts = Vec::new();
        for path in sorted_sources(&content_dir.join("roles"), "md")? {
            let contents = std::fs::read_to_string(&path)
                .map_err(|error| GuardError::Io(format!("{}: {error}", path.display())))?;
            let source_name = path
                .file_name()
                .and_then(std::ffi::OsStr::to_str)
                .unwrap_or("<non-utf8 role filename>");
            role_facts.push(parse_role_markdown(source_name, &contents)?);
        }
        Self::new(predicates, role_facts)
    }
}

#[cfg(feature = "std")]
fn sorted_sources(
    directory: &std::path::Path,
    extension: &str,
) -> Result<Vec<std::path::PathBuf>, GuardError> {
    if !directory.is_dir() {
        return Ok(Vec::new());
    }
    let entries = std::fs::read_dir(directory)
        .map_err(|error| GuardError::Io(format!("{}: {error}", directory.display())))?;
    let mut paths = Vec::new();
    for entry in entries {
        let entry =
            entry.map_err(|error| GuardError::Io(format!("{}: {error}", directory.display())))?;
        let path = entry.path();
        if path.extension().and_then(std::ffi::OsStr::to_str) == Some(extension) {
            paths.push(path);
        }
    }
    paths.sort();
    Ok(paths)
}
