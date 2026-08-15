/*
    Appellation: harness <module>
    Created At: 2026.08.12:15:31:26
    Contrib: @FL03
*/

/// The agent harnesses shepherd governs.
///
/// This is a **value the engine carries, never a branch the engine takes.** If
/// engine logic ever reads this to decide behavior, the harness coupling this
/// crate exists to prevent has leaked in. Adapters branch; the engine does not.
#[derive(
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    strum::AsRefStr,
    strum::Display,
    strum::EnumCount,
    strum::EnumIs,
    strum::EnumString,
    strum::IntoStaticStr,
    strum::VariantNames,
)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
#[cfg_attr(feature = "serde", serde(rename_all = "snake_case"))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
#[strum(ascii_case_insensitive, serialize_all = "snake_case")]
#[non_exhaustive]
pub enum Harness {
    #[strum(to_string = "claude", serialize = "claude_code")]
    #[cfg_attr(feature = "serde", serde(rename = "claude", alias = "claude_code"))]
    ClaudeCode,
    Codex,
    Pi,
    PrimeAgent,
}
