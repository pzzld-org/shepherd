/*
    Appellation: run <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! `run.json` — the machine state of one shepherd run (#282).
//!
//! This is a **port**, not a redesign. `services/cli/shepherd_cli/models_run.py`
//! is the reference implementation and the behavioral oracle; this module
//! reproduces its two load-bearing, already-measured properties rather than
//! inventing new ones:
//!
//! 1. **Keys are recursively sorted.** `models_run.py:627` writes with
//!    `json.dump(..., indent=2, sort_keys=True)`. [`RunState::to_canonical_json`]
//!    (via `canonical`) reproduces that byte-for-byte, at every nesting
//!    level, not just the top one.
//! 2. **Unknown keys round-trip.** `models_run.py:485` / `:507` use pydantic's
//!    `extra = "allow"` on both `RunState` and `LaneState` — a deliberate
//!    #247 fix: other shepherd implementations (prior bash versions,
//!    codex-shepherd) and this CLI's own future versions write fields this
//!    struct does not name, and a prior closed schema (`extra = "forbid"`)
//!    rejected 100% of live `run.json` files (33 and 17 validation errors on
//!    two measured runs), because every mutator goes through the loader.
//!    [`RunState::extra`] and [`LaneState::extra`] are the same fix here: a
//!    load -> store round trip preserves every field this struct does not
//!    declare, instead of silently dropping it.
//!
//! ## What this module is deliberately NOT
//!
//! `models_run.py` also carries `normalize_run_document` / `load_run_with_migrations`
//! — a legacy-shape migration layer that renames `run_id` -> `run`, reshapes a
//! dict-keyed `lanes` into the current list, and coerces an ISO8601
//! `updated_at` into epoch seconds. That is CLI-mutator policy layered on top
//! of the schema, not the schema itself, and #282's produced surface is
//! exactly `RunState` + `load` + `store` + `to_canonical_json` — nothing
//! wider. Porting the migration layer is a separate, later step's job.
//!
//! ## The engine boundary
//!
//! [`RunState`] and [`LaneState`] compile under the `json` feature alone (the
//! `alloc` floor: no filesystem, no clock). [`RunState::load`] and
//! [`RunState::store`] additionally require `std`, because a `Path` and a
//! `File` both presume a filesystem an embedder may not have. Nothing here
//! reaches for `clap`, `anyhow`, `std::process`, or branches on [`crate::Harness`]
//! — see `crates/core/src/lib.rs`'s `## The boundary` section and the
//! `engine-boundary` CI job that enforces it.
#[cfg(not(feature = "std"))]
use alloc::{collections::BTreeMap, string::String, vec::Vec};
#[cfg(feature = "std")]
use std::collections::BTreeMap;

#[cfg(feature = "std")]
mod atomic;
mod canonical;
mod lane;

#[cfg(test)]
mod tests;

pub use self::lane::LaneState;

#[cfg(feature = "std")]
use crate::error::Result;

fn default_schema_version() -> u32 {
    1
}

fn default_kind() -> String {
    String::from("sprint")
}

fn default_status() -> String {
    String::from("planted")
}

/// The `run.json` document — the machine state of one shepherd run.
///
/// Every field but [`run`](Self::run) carries a default matching
/// `models_run.py`'s `RunState`, so a document missing an optional key loads
/// the same way pydantic's model does rather than failing closed. `run`
/// itself has no default in the reference implementation either: it is the
/// one field a caller must supply.
///
/// Fields are `pub` for the same reason `settings::ShepherdConfig`'s are:
/// this is a data-transfer type read across the crate boundary by every
/// consumer, not an invariant-guarding abstraction.
#[derive(Clone, Debug, PartialEq, serde::Deserialize, serde::Serialize)]
pub struct RunState {
    /// The `run.json` schema version. `1` today; nothing has needed a `2` yet.
    #[serde(default = "default_schema_version")]
    pub schema_version: u32,
    /// The run identifier — the sprint slug, or the patch slug for a
    /// patch-arc run. The one field with no default: every `run.json` names
    /// the run it is the state of.
    pub run: String,
    /// `"sprint"` or `"patch-arc"`. A plain `String`, not a closed enum: the
    /// Python reference types this the same way (`kind: str = "sprint"`),
    /// deliberately, so a value neither side has named yet still round-trips
    /// instead of failing to parse.
    #[serde(default = "default_kind")]
    pub kind: String,
    /// The run's git branch, `""` until one is cut.
    #[serde(default)]
    pub branch: String,
    /// The base ref this run branched from, `""` until set.
    #[serde(default)]
    pub base: String,
    /// Repo-relative path to `seed.md`, `""` until the run is planted.
    #[serde(default)]
    pub seed: String,
    /// Repo-relative path to `plan.md`, `""` until the run is planned.
    #[serde(default)]
    pub plan: String,
    /// The run's lifecycle status. `RUN_STATUSES` in the Python reference
    /// names a closed vocabulary (`planted`, `planned`, `executing`,
    /// `closing`, `closed`) but does not enforce it at the schema level for
    /// the same round-trip reason `kind` is a plain string here.
    #[serde(default = "default_status")]
    pub status: String,
    /// One row per lane this run has registered.
    #[serde(default)]
    pub lanes: Vec<LaneState>,
    /// Unix epoch seconds of the last write. [`RunState::store`] stamps this
    /// itself, mirroring `save_run`'s `state.updated_at = int(time.time())`
    /// — a caller-supplied value here is only ever a starting point.
    #[serde(default)]
    pub updated_at: i64,
    /// Every top-level key this document carries that the fields above do
    /// not name. See the module's `## Unknown keys round-trip` property:
    /// this is what makes that true, and it is not decorative — dropping it
    /// is the exact #247 regression the Python reference was fixed for.
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

impl RunState {
    /// Serialize to the canonical `run.json` text: recursively sorted keys,
    /// 2-space indent, ASCII-only — the byte-exact match for
    /// `models_run.py:627`'s `json.dump(payload, indent=2, sort_keys=True)`.
    /// See `canonical` for exactly what that requires beyond
    /// `serde_json`'s own pretty printer, and why.
    ///
    /// Does not include the writer's trailing newline; [`RunState::store`]
    /// (or a caller writing to a different sink) adds that at the point of
    /// writing, matching `atomic_write_json`'s separate `handle.write("\n")`.
    ///
    /// Infallible by signature, matching the produced interface. This can
    /// only panic if `extra` carries a `serde_json::Value` built from a NaN
    /// or infinite float via the non-parsing constructors (`Value::from`) —
    /// unreachable here, because every `Value` this struct ever holds either
    /// came from parsing valid JSON (whose numbers cannot be NaN/Infinity by
    /// construction) or was built by a caller who already had a valid
    /// `Value` to assign.
    #[must_use]
    pub fn to_canonical_json(&self) -> String {
        canonical::to_canonical_string(self)
            .expect("RunState never carries a NaN/Infinity float: see this method's doc comment")
    }

    /// Load and parse one `run.json`. Tolerant the way the Python reference's
    /// schema is tolerant — a document missing an optional field parses;
    /// every field this struct does not name round-trips via `extra` — but
    /// does NOT apply `models_run.py`'s legacy-shape migrations (`run_id` ->
    /// `run`, dict-keyed `lanes`, ISO8601 `updated_at`). See the module docs'
    /// `## What this module is deliberately NOT`.
    ///
    /// # Errors
    ///
    /// Returns [`crate::Error::Unknown`] if `path` cannot be read, or
    /// [`crate::Error::Serialization`] if its contents are not a valid
    /// `RunState` document.
    #[cfg(feature = "std")]
    pub fn load(path: &std::path::Path) -> Result<Self> {
        let bytes = std::fs::read(path)
            .map_err(|error| crate::Error::unknown(format!("read {}: {error}", path.display())))?;
        serde_json::from_slice(&bytes)
            .map_err(|error| crate::Error::Serialization(format!("{}: {error}", path.display())))
    }

    /// Persist this state atomically: tempfile in `path`'s directory ->
    /// fsync -> rename -> fsync(dir). Reproduces `models_run.py:615-639`'s
    /// `atomic_write_json` bytes and sequencing exactly; see `atomic` for
    /// the step-by-step correspondence.
    ///
    /// Unlike `save_run`, does not stamp [`RunState::updated_at`] itself —
    /// that is a mutator's job in this split (the engine writes what it is
    /// given; a CLI adapter decides when "now" is). A caller that wants
    /// `save_run`'s exact behavior sets `updated_at` before calling this.
    ///
    /// # Errors
    ///
    /// Returns [`crate::Error::Unknown`] if any step of the write sequence
    /// (directory creation, tempfile write, fsync, rename, or the closing
    /// directory fsync) fails.
    #[cfg(feature = "std")]
    pub fn store(&self, path: &std::path::Path) -> Result<()> {
        self::atomic::atomic_write(path, &self.to_canonical_json())
    }
}
