//! Typed compiler input, target profiles, emitted files, and errors.

use alloc::{
    collections::{BTreeMap, BTreeSet},
    string::{String, ToString},
    vec,
    vec::Vec,
};
use core::fmt;

use crate::{BudgetError, Measurement};

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum Target {
    Claude,
    Codex,
    Pi,
}

impl Target {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Claude => "claude",
            Self::Codex => "codex",
            Self::Pi => "pi",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Portability {
    CrossHarness,
    ClaudeOnly,
    Unverified,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleInput {
    pub role: String,
    pub description: String,
    pub model_hint: String,
    pub write_eligible: bool,
    pub dispatchable: bool,
    pub capabilities: Vec<String>,
    pub write_scope: String,
    pub body: String,
    pub source_path: String,
    pub source_content: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SkillInput {
    pub name: String,
    pub description: String,
    pub portability: Portability,
    pub body: String,
    pub source_path: String,
    pub source_content: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct CompileInput {
    pub roles: Vec<RoleInput>,
    pub skills: Vec<SkillInput>,
}

/// Harness-native resolution for one authored `model_hint`.
///
/// A Claude or Pi profile resolves to `model`; a Codex profile resolves to
/// `profile` plus `reasoning_effort`. Concrete provider-specific Pi targets stay
/// in runtime configuration, so only `inherit-caller` has a canonical Pi model.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ModelResolution {
    pub model: Option<String>,
    pub profile: Option<String>,
    pub reasoning_effort: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HarnessProfile {
    pub target: Target,
    pub max_concurrent_children: usize,
    pub tools_by_capability: BTreeMap<String, Vec<String>>,
    pub unsupported_capabilities: BTreeSet<String>,
    pub model_by_hint: BTreeMap<String, ModelResolution>,
}

impl HarnessProfile {
    #[must_use]
    pub fn claude() -> Self {
        let mut tools = BTreeMap::new();
        for (capability, concrete) in [
            ("read", &["Read", "NotebookRead"][..]),
            ("search", &["Glob", "Grep"][..]),
            ("shell", &["Bash"][..]),
            ("write", &["Write", "Edit"][..]),
            ("report-write", &["Write"][..]),
            ("skill-load", &["Skill"][..]),
            ("tool-discovery", &["ToolSearch"][..]),
            ("dispatch", &["Agent", "Workflow"][..]),
            ("message-peer", &["SendMessage"][..]),
            (
                "task-tracking",
                &["TaskCreate", "TaskGet", "TaskList", "TaskUpdate"][..],
            ),
            ("web-research", &["WebFetch", "WebSearch"][..]),
            ("ask-operator", &["AskUserQuestion"][..]),
            ("schedule-wakeup", &["ScheduleWakeup"][..]),
            ("code-intelligence", &["LSP"][..]),
        ] {
            tools.insert(
                capability.to_string(),
                concrete.iter().map(ToString::to_string).collect(),
            );
        }
        Self {
            target: Target::Claude,
            max_concurrent_children: 3,
            tools_by_capability: tools,
            unsupported_capabilities: BTreeSet::new(),
            model_by_hint: BTreeMap::from([
                (
                    "inherit-caller".into(),
                    ModelResolution {
                        model: Some("inherit".into()),
                        ..ModelResolution::default()
                    },
                ),
                (
                    "reasoning-high".into(),
                    ModelResolution {
                        model: Some("opus[1m]".into()),
                        ..ModelResolution::default()
                    },
                ),
                (
                    "standard".into(),
                    ModelResolution {
                        model: Some("sonnet".into()),
                        ..ModelResolution::default()
                    },
                ),
                (
                    "economy".into(),
                    ModelResolution {
                        model: Some("haiku".into()),
                        ..ModelResolution::default()
                    },
                ),
            ]),
        }
    }

    #[must_use]
    pub fn codex() -> Self {
        Self {
            target: Target::Codex,
            max_concurrent_children: 3,
            tools_by_capability: BTreeMap::new(),
            unsupported_capabilities: BTreeSet::new(),
            model_by_hint: BTreeMap::from([
                ("inherit-caller".into(), ModelResolution::default()),
                (
                    "reasoning-high".into(),
                    ModelResolution {
                        profile: Some("reasoning-high".into()),
                        reasoning_effort: Some("high".into()),
                        ..ModelResolution::default()
                    },
                ),
                (
                    "standard".into(),
                    ModelResolution {
                        profile: Some("standard".into()),
                        reasoning_effort: Some("medium".into()),
                        ..ModelResolution::default()
                    },
                ),
                (
                    "economy".into(),
                    ModelResolution {
                        profile: Some("economy".into()),
                        reasoning_effort: Some("low".into()),
                        ..ModelResolution::default()
                    },
                ),
            ]),
        }
    }

    #[must_use]
    pub fn pi() -> Self {
        let tools_by_capability = BTreeMap::from([
            ("read".into(), vec!["read".into()]),
            ("report-write".into(), vec!["write".into()]),
            ("search".into(), vec!["grep".into(), "find".into()]),
            ("shell".into(), vec!["bash".into()]),
            ("dispatch".into(), vec!["subagent".into()]),
            ("write".into(), vec!["write".into(), "edit".into()]),
        ]);
        Self {
            target: Target::Pi,
            max_concurrent_children: 3,
            tools_by_capability,
            unsupported_capabilities: BTreeSet::from([
                "ask-operator".into(),
                "code-intelligence".into(),
                "message-peer".into(),
                "schedule-wakeup".into(),
                "skill-load".into(),
                "task-tracking".into(),
                "tool-discovery".into(),
                "web-research".into(),
            ]),
            // Provider-specific Pi targets are project configuration, not
            // compiler policy. Inheritance is the only provider-neutral launch
            // instruction; every other portable hint remains unresolved here.
            model_by_hint: BTreeMap::from([
                (
                    "inherit-caller".into(),
                    ModelResolution {
                        model: Some("inherit".into()),
                        ..ModelResolution::default()
                    },
                ),
                ("reasoning-high".into(), ModelResolution::default()),
                ("standard".into(), ModelResolution::default()),
                ("economy".into(), ModelResolution::default()),
            ]),
        }
    }

    #[must_use]
    pub fn canonical() -> [Self; 3] {
        [Self::claude(), Self::codex(), Self::pi()]
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EmittedKind {
    Role,
    Skill,
    Config,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EmittedFile {
    pub path: String,
    pub kind: EmittedKind,
    pub content: String,
    pub source_path: String,
    pub source_sha256: String,
    pub content_sha256: String,
    pub measurement: Measurement,
}

/// Target-final launch and policy facts for one role carrier.
///
/// This is the language-neutral boundary adapters consume. They must not
/// reparse authored Markdown or maintain their own model/tool tables.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EmittedRole {
    pub role: String,
    pub carrier_path: String,
    pub description: String,
    pub model_hint: String,
    pub model: Option<String>,
    pub profile: Option<String>,
    pub reasoning_effort: Option<String>,
    pub tools: Vec<String>,
    pub unsupported_capabilities: Vec<String>,
    pub capabilities: Vec<String>,
    pub write_eligible: bool,
    pub dispatchable: bool,
    pub write_scope: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EmittedTree {
    pub target: Target,
    pub roles: Vec<EmittedRole>,
    pub files: Vec<EmittedFile>,
    pub digest: String,
    pub tokenizer_version: &'static str,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompileError {
    Invalid(String),
    Budget(BudgetError),
}

impl fmt::Display for CompileError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => formatter.write_str(message),
            Self::Budget(error) => fmt::Display::fmt(error, formatter),
        }
    }
}

impl From<BudgetError> for CompileError {
    fn from(error: BudgetError) -> Self {
        Self::Budget(error)
    }
}

#[cfg(feature = "std")]
impl std::error::Error for CompileError {}
