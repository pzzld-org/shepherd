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
    schemars::JsonSchema,
    serde::Deserialize,
    serde::Serialize,
    strum::AsRefStr,
    strum::Display,
    strum::EnumCount,
    strum::EnumIs,
    strum::EnumString,
    strum::IntoStaticStr,
    strum::VariantNames,
)]
#[serde(rename_all = "snake_case")]
#[strum(ascii_case_insensitive, serialize_all = "snake_case")]
#[non_exhaustive]
pub enum Harness {
    ClaudeCode,
    Codex,
    Pi,
    PrimeAgent,
}
