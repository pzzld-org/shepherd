//! Deterministic scoped context filtering, ranking, and materialization.

#[cfg(feature = "alloc")]
use alloc::{string::String, vec::Vec};

use super::{AgentId, DispatchError, DispatchResult, LaneId, ProjectId, RunId};

/// The native resume envelope is deliberately bounded before an adapter injects
/// it into a host context window.
pub const MAX_RESUME_CONTEXT_ENTRIES: usize = 64;
pub const MAX_RESUME_CONTEXT_WORDS: usize = 6_000;
pub const MAX_RESUME_CONTEXT_TOKENS: usize = 32_768;

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct ContextEntry {
    pub id: AgentId,
    pub project_id: ProjectId,
    pub run: RunId,
    pub lane: Option<LaneId>,
    pub provenance: String,
    pub freshness: i64,
    pub words: usize,
    pub tokens: usize,
    pub priority: i32,
    pub content: String,
}

impl ContextEntry {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        id: impl Into<String>,
        project_id: ProjectId,
        run: RunId,
        lane: Option<LaneId>,
        provenance: impl Into<String>,
        freshness: i64,
        words: usize,
        tokens: usize,
        priority: i32,
        content: impl Into<String>,
    ) -> DispatchResult<Self> {
        let provenance = provenance.into();
        let content = content.into();
        let entry = Self {
            id: AgentId::new(id)?,
            project_id,
            run,
            lane,
            provenance,
            freshness,
            words,
            tokens,
            priority,
            content,
        };
        entry.validate()?;
        Ok(entry)
    }

    /// Validate a deserialized entry before it is injected into a host prompt.
    pub fn validate(&self) -> DispatchResult<()> {
        if self.provenance.is_empty()
            || self.provenance.len() > 256
            || self.provenance.chars().any(char::is_control)
            || self.freshness < 0
            || self.words == 0
            || self.tokens == 0
            || self.content.is_empty()
        {
            return Err(DispatchError::InvalidContext(self.provenance.clone()));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextQuery {
    pub project_id: ProjectId,
    pub run: RunId,
    pub lane: Option<LaneId>,
    pub min_freshness: i64,
    pub max_entries: usize,
    pub max_words: usize,
    pub max_tokens: usize,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct ContextBundle {
    pub entries: Vec<ContextEntry>,
    pub words: usize,
    pub tokens: usize,
}

impl ContextBundle {
    /// Validate a resume bundle against the resumed dispatch scope and the
    /// hard prompt-budget ceiling shared by every native adapter.
    pub fn validate_for_resume(
        &self,
        project_id: &ProjectId,
        run: &RunId,
        lane: Option<&LaneId>,
    ) -> DispatchResult<()> {
        if self.entries.len() > MAX_RESUME_CONTEXT_ENTRIES
            || self.words > MAX_RESUME_CONTEXT_WORDS
            || self.tokens > MAX_RESUME_CONTEXT_TOKENS
        {
            return Err(DispatchError::InvalidContext(
                "resume context exceeds the native prompt budget".into(),
            ));
        }

        let mut words = 0_usize;
        let mut tokens = 0_usize;
        for entry in &self.entries {
            entry.validate()?;
            if &entry.project_id != project_id || &entry.run != run {
                return Err(DispatchError::InvalidContext(
                    "resume context belongs to another project or run".into(),
                ));
            }
            if entry.lane.is_some() && entry.lane.as_ref() != lane {
                return Err(DispatchError::InvalidContext(
                    "resume context belongs to another lane".into(),
                ));
            }
            words = words.checked_add(entry.words).ok_or_else(|| {
                DispatchError::InvalidContext("resume context word count overflows".into())
            })?;
            tokens = tokens.checked_add(entry.tokens).ok_or_else(|| {
                DispatchError::InvalidContext("resume context token count overflows".into())
            })?;
        }
        if words != self.words || tokens != self.tokens {
            return Err(DispatchError::InvalidContext(
                "resume context counters do not match entries".into(),
            ));
        }
        Ok(())
    }
}

#[must_use]
pub fn materialize_context(entries: &[ContextEntry], query: &ContextQuery) -> ContextBundle {
    let mut candidates: Vec<&ContextEntry> = entries
        .iter()
        .filter(|entry| {
            entry.project_id == query.project_id
                && entry.run == query.run
                && entry.freshness >= query.min_freshness
                && (entry.lane.is_none() || entry.lane == query.lane)
        })
        .collect();
    candidates.sort_by(|left, right| {
        let left_exact = left.lane.is_some() && left.lane == query.lane;
        let right_exact = right.lane.is_some() && right.lane == query.lane;
        right_exact
            .cmp(&left_exact)
            .then_with(|| right.priority.cmp(&left.priority))
            .then_with(|| right.freshness.cmp(&left.freshness))
            .then_with(|| left.id.cmp(&right.id))
    });

    let mut bundle = ContextBundle::default();
    for entry in candidates {
        if bundle.entries.len() >= query.max_entries {
            break;
        }
        if bundle.words.saturating_add(entry.words) > query.max_words
            || bundle.tokens.saturating_add(entry.tokens) > query.max_tokens
        {
            continue;
        }
        bundle.words += entry.words;
        bundle.tokens += entry.tokens;
        bundle.entries.push(entry.clone());
    }
    bundle
}
