//! Versioned prompt measurement and hard context budgets.

use alloc::string::{String, ToString};
use core::fmt;

use unicode_segmentation::UnicodeSegmentation;

/// The stable algorithm identifier stored in compiler manifests.
pub const TOKENIZER_VERSION: &str = "shepherd-prompt-v1-uax29";

/// A bounded prompt surface.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum BudgetClass {
    Skill,
    AlwaysLoadedSkill,
    Role,
    Reference,
    Doctrine,
    Command,
    AlwaysLoadedBundle,
    HarnessSkillSet,
}

/// Measured prompt size using the versioned deterministic algorithm.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct Measurement {
    pub lines: usize,
    pub words: usize,
    pub utf8_bytes: usize,
    pub prompt_tokens: usize,
}

/// The release's pinned budget table.
pub struct BudgetLimits;

impl BudgetLimits {
    /// Return `(lines, Unicode words, UTF-8 bytes)` for one surface.
    #[must_use]
    pub const fn for_class(class: BudgetClass) -> (usize, usize, usize) {
        match class {
            BudgetClass::Skill => (100, 500, 6 * 1024),
            BudgetClass::AlwaysLoadedSkill => (60, 200, 3 * 1024),
            BudgetClass::Role => (100, 600, 7 * 1024),
            BudgetClass::Reference => (220, 1_500, 16 * 1024),
            BudgetClass::Doctrine => (160, 1_000, 12 * 1024),
            BudgetClass::Command => (140, 750, 9 * 1024),
            BudgetClass::AlwaysLoadedBundle => (300, 2_000, 22 * 1024),
            BudgetClass::HarnessSkillSet => (700, 3_500, 42 * 1024),
        }
    }
}

/// A deterministic budget violation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BudgetError {
    Empty {
        name: String,
    },
    Exceeded {
        name: String,
        metric: &'static str,
        actual: usize,
        limit: usize,
    },
}

impl fmt::Display for BudgetError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Empty { name } => write!(formatter, "{name}: prompt surface is empty"),
            Self::Exceeded {
                name,
                metric,
                actual,
                limit,
            } => write!(
                formatter,
                "{name}: {metric} budget exceeded ({actual} > {limit})"
            ),
        }
    }
}

#[cfg(feature = "std")]
impl std::error::Error for BudgetError {}

/// Measure physical lines, UAX #29 words, UTF-8 bytes, and approximate tokens.
///
/// Prompt tokens use `shepherd-prompt-v1-uax29`: each UAX #29 word contributes
/// at least one token and one token per four UTF-8 bytes; non-whitespace
/// punctuation contributes one token per scalar. This is intentionally model
/// neutral and versioned because Claude, Codex, and Pi may use different
/// tokenizers while sharing one conservative release gate.
#[must_use]
pub fn measure_text(text: &str) -> Measurement {
    let words = text.unicode_words().count();
    let prompt_tokens = text
        .split_word_bounds()
        .map(|segment| {
            if segment.chars().all(char::is_whitespace) {
                0
            } else if segment.unicode_words().next().is_some() {
                segment.len().div_ceil(4).max(1)
            } else {
                segment
                    .chars()
                    .filter(|character| !character.is_whitespace())
                    .count()
            }
        })
        .sum();

    Measurement {
        lines: text.lines().count(),
        words,
        utf8_bytes: text.len(),
        prompt_tokens,
    }
}

/// Measure and reject an empty or oversized surface.
pub fn validate_budget(
    name: &str,
    class: BudgetClass,
    text: &str,
) -> Result<Measurement, BudgetError> {
    if text.is_empty() {
        return Err(BudgetError::Empty {
            name: name.to_string(),
        });
    }
    let measured = measure_text(text);
    let (line_limit, word_limit, byte_limit) = BudgetLimits::for_class(class);
    for (metric, actual, limit) in [
        ("lines", measured.lines, line_limit),
        ("words", measured.words, word_limit),
        ("utf8_bytes", measured.utf8_bytes, byte_limit),
    ] {
        if actual > limit {
            return Err(BudgetError::Exceeded {
                name: name.to_string(),
                metric,
                actual,
                limit,
            });
        }
    }
    Ok(measured)
}
