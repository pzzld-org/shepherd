/*
    Appellation: guard-model <module>
    Created At: 2026.08.14:00:00:00
    Contrib: @FL03
*/
//! Typed values shared by guard parsing, evaluation, and serialization.

use alloc::{collections::BTreeMap, string::String, vec::Vec};

/// An engine failure, distinct from an allow, deny, or unresolved verdict.
#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
#[non_exhaustive]
pub enum GuardError {
    /// A request violates the typed input contract.
    #[error("{0}")]
    Input(String),
    /// A predicate document cannot be trusted or evaluated.
    #[error("{0}")]
    Predicate(String),
    /// A role document cannot be trusted.
    #[error("{0}")]
    Role(String),
    /// Explicit-path loading failed.
    #[cfg(feature = "std")]
    #[error("{0}")]
    Io(String),
    /// JSON text could not be decoded.
    #[cfg(feature = "json")]
    #[error("{0}")]
    Json(String),
}

/// A request or predicate-context value independent of a wire codec.
#[derive(Clone, Debug, PartialEq)]
pub enum GuardValue {
    /// An explicit JSON null.
    Null,
    /// A boolean value.
    Bool(bool),
    /// A signed integer value.
    Integer(i64),
    /// An unsigned integer value outside TOML's signed range.
    Unsigned(u64),
    /// A floating-point value.
    Float(f64),
    /// An owned string value.
    String(String),
    /// An ordered sequence.
    Array(Vec<Self>),
    /// A string-keyed object.
    Object(BTreeMap<String, Self>),
}

impl From<&str> for GuardValue {
    fn from(value: &str) -> Self {
        Self::String(value.into())
    }
}

impl From<String> for GuardValue {
    fn from(value: String) -> Self {
        Self::String(value)
    }
}

impl From<bool> for GuardValue {
    fn from(value: bool) -> Self {
        Self::Bool(value)
    }
}

impl From<i64> for GuardValue {
    fn from(value: i64) -> Self {
        Self::Integer(value)
    }
}

impl From<u64> for GuardValue {
    fn from(value: u64) -> Self {
        Self::Unsigned(value)
    }
}

impl GuardValue {
    pub(crate) fn as_str(&self) -> Option<&str> {
        match self {
            Self::String(value) => Some(value),
            _ => None,
        }
    }

    pub(crate) fn is_true(&self) -> bool {
        matches!(self, Self::Bool(true))
    }

    pub(crate) fn is_false(&self) -> bool {
        matches!(self, Self::Bool(false))
    }

    pub(crate) fn is_null(&self) -> bool {
        matches!(self, Self::Null)
    }

    pub(crate) fn is_truthy(&self) -> bool {
        match self {
            Self::Null | Self::Bool(false) => false,
            Self::Bool(true) => true,
            Self::Integer(value) => *value != 0,
            Self::Unsigned(value) => *value != 0,
            Self::Float(value) => *value != 0.0,
            Self::String(value) => !value.is_empty(),
            Self::Array(value) => !value.is_empty(),
            Self::Object(value) => !value.is_empty(),
        }
    }
}

/// One `[[rule]]` table from a predicate TOML document.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Rule {
    /// Stable rule identifier.
    pub id: String,
    /// Operator-facing reason text.
    pub description: String,
    /// Fact namespace the rule documents.
    pub subject: String,
    /// Action to which this rule applies.
    pub action: String,
    /// Name of the closed effect implementation.
    pub effect: String,
}

/// One heterogeneous `[[example]]` table from a predicate document.
#[derive(Clone, Debug, PartialEq)]
pub struct PredicateExample {
    /// Stable example name.
    pub name: String,
    /// Declared `allow` or `deny` example kind.
    pub kind: String,
    /// Acting role.
    pub role: GuardValue,
    /// Evaluated action.
    pub action: String,
    /// Explicit example context. Top-level extras are held separately.
    pub context: BTreeMap<String, GuardValue>,
    /// Expected decision.
    pub result: String,
    /// Optional attested halt code.
    pub halt_code: Option<String>,
    /// Optional explanatory note.
    pub note: Option<String>,
    /// Non-canonical top-level fields merged into evaluation context.
    pub extra: BTreeMap<String, GuardValue>,
}

impl PredicateExample {
    /// Merge top-level example extras with explicit context, which wins.
    pub fn flattened_context(&self) -> BTreeMap<String, GuardValue> {
        let mut context = self.extra.clone();
        context.extend(self.context.clone());
        context
    }
}

/// One parsed predicate TOML document.
#[derive(Clone, Debug, PartialEq)]
pub struct PredicateDoc {
    /// Stable predicate identifier.
    pub id: String,
    /// Predicate schema version.
    pub version: i64,
    /// Predicate-level description.
    pub description: String,
    /// Rules in declaration order.
    pub rules: Vec<Rule>,
    /// Examples in declaration order.
    pub examples: Vec<PredicateExample>,
}

/// Role facts read from one `content/roles/*.md` frontmatter block.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleFact {
    /// Stable role identifier.
    pub role: String,
    /// Whether the role may write in a dispatch-declared scope.
    pub write_eligible: bool,
    /// Whether the role may be dispatched.
    pub dispatchable: bool,
    /// Closed capability strings from the role document.
    pub capabilities: Vec<String>,
}

impl RoleFact {
    pub(crate) fn has_capability(&self, capability: &str) -> bool {
        self.capabilities.iter().any(|item| item == capability)
    }

    /// Structured Write/Edit/apply_patch needs the explicit native `write`
    /// capability. `write_eligible` alone also covers shell-mediated custody
    /// roles such as conductor and is not a general Write/Edit grant.
    pub(crate) fn permits_structured_write(&self) -> bool {
        self.write_eligible && self.has_capability("write")
    }
}

/// The three ordered guard outcomes.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum Decision {
    /// The requested operation is allowed.
    Allow,
    /// One or more predicate rules deny the operation.
    Deny,
    /// Required information was unavailable or malformed.
    Unresolved,
}

impl Decision {
    /// The versioned guard wire's lowercase spelling.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Allow => "allow",
            Self::Deny => "deny",
            Self::Unresolved => "unresolved",
        }
    }
}

/// One ordered guard verdict. Optional fields are omitted by the wire codec.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Verdict {
    /// Allow, deny, or unresolved.
    pub decision: Decision,
    /// Predicate that denied, if present.
    pub predicate: Option<String>,
    /// Comma-joined fired rules, if present.
    pub rule: Option<String>,
    /// Attested halt code, if present.
    pub halt_code: Option<String>,
    /// Operator-facing explanation, if present.
    pub reason: Option<String>,
    /// Facts needed to resolve an unresolved request.
    pub missing: Vec<String>,
}

impl Verdict {
    pub(crate) fn allow() -> Self {
        Self {
            decision: Decision::Allow,
            predicate: None,
            rule: None,
            halt_code: None,
            reason: None,
            missing: Vec::new(),
        }
    }

    pub(crate) fn unresolved(reason: impl Into<String>, missing: &[&str]) -> Self {
        Self {
            decision: Decision::Unresolved,
            predicate: None,
            rule: None,
            halt_code: None,
            reason: Some(reason.into()),
            missing: missing.iter().map(|item| String::from(*item)).collect(),
        }
    }

    pub(crate) fn deny(
        predicate: impl Into<String>,
        rule: impl Into<String>,
        halt_code: Option<String>,
        reason: impl Into<String>,
    ) -> Self {
        Self {
            decision: Decision::Deny,
            predicate: Some(predicate.into()),
            rule: Some(rule.into()),
            halt_code,
            reason: Some(reason.into()),
            missing: Vec::new(),
        }
    }
}
