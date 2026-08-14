/*
    Appellation: lane <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! One lane's registration row inside `run.json`'s `lanes` array.
#[cfg(feature = "alloc")]
use alloc::{collections::BTreeMap, string::String};

fn default_lane_state() -> String {
    String::from("pending")
}

/// One lane's registration + boundary-merge ledger row.
///
/// Mirrors `models_run.py`'s `LaneState`: same fields, same defaults, same
/// `extra = "allow"` round-trip guarantee (#247) — a lane document written
/// by a different shepherd implementation, or a future version of this one,
/// keeps whatever fields this struct does not name through a load -> store
/// cycle instead of losing them.
#[derive(Clone, Debug, PartialEq, serde::Deserialize, serde::Serialize)]
pub struct LaneState {
    /// The lane identifier, e.g. `"l1-engine"`. No default: every lane row
    /// names the lane it describes.
    pub id: String,
    /// Repo-relative path to this lane's `plan.md`, `""` until the run is
    /// planned.
    #[serde(default)]
    pub plan: String,
    /// This lane's worktree path, `""` until one is created.
    #[serde(default)]
    pub worktree: String,
    /// This lane's git branch, `""` until one is cut.
    #[serde(default)]
    pub branch: String,
    /// The lane's lifecycle state. `LANE_STATES` in the Python reference
    /// names a closed vocabulary (`pending`, `in-progress`, `complete`,
    /// `error`) but, like [`crate::run::RunState::status`], is not enforced
    /// as a closed type here for the same round-trip reason.
    #[serde(default = "default_lane_state")]
    pub state: String,
    /// The #242 boundary-merge ledger: the commit a `WAVE-COMPLETE`
    /// acceptance recorded for this lane, `None` until one has been.
    #[serde(default)]
    pub accepted_commit: Option<String>,
    /// The other half of the #242 ledger: whether [`accepted_commit`](Self::accepted_commit)
    /// has actually landed on the integration branch. A wave gate's "pending
    /// merges" set is exactly the lanes with a commit recorded here and
    /// this still `false`.
    #[serde(default)]
    pub merged: bool,
    /// Unix epoch seconds this lane row was last written.
    #[serde(default)]
    pub updated_at: i64,
    /// Every key this lane's document carries that the fields above do not
    /// name. See [`crate::run::RunState::extra`] for why this exists.
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}
