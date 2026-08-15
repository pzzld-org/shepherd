/*
    Appellation: run <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! `run.json` — the machine state of one shepherd run (#282).
//!
//! This module is the canonical, harness-neutral state contract. Two
//! compatibility properties are deliberately load-bearing:
//!
//! 1. **Keys are recursively sorted.** [`RunState::to_canonical_json`] emits
//!    stable bytes at every nesting level, not just the top one.
//! 2. **Unknown keys round-trip.** [`RunState::extra`] and
//!    [`LaneState::extra`] preserve forward-compatible fields across a
//!    load/store cycle instead of silently dropping them.
//!
//! Legacy document normalization belongs to the native CLI's locked RunStore
//! migration boundary. The pure core owns only the typed state and canonical
//! encoding; it does not guess filesystem identity or mutate a run.
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
#[cfg(feature = "alloc")]
use alloc::{collections::BTreeMap, string::String, vec::Vec};

#[cfg(feature = "std")]
mod atomic;
mod canonical;
mod lane;

#[cfg(test)]
mod tests {
    /*
        Appellation: tests <module>
        Created At: 2026.08.13:00:00:00
        Contrib: @FL03
    */
    //! Golden-byte tests for the canonical native encoding. CLI-level run
    //! transitions are additionally frozen under `conformance/cases/core/run`.

    use super::RunState;

    fn minimal_state() -> RunState {
        serde_json::from_value(serde_json::json!({"run": "v1"})).expect("minimal doc parses")
    }

    #[cfg(feature = "std")]
    mod atomic_io {
        use super::minimal_state;
        use crate::run::atomic::write_and_rename;

        fn unique_temp_dir(label: &str) -> std::path::PathBuf {
            let nanos = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after the epoch")
                .as_nanos();
            let dir = std::env::temp_dir().join(format!("shepherd-core-run-{label}-{nanos:x}"));
            std::fs::create_dir_all(&dir).expect("create temp test dir");
            dir
        }

        /// `store` then `load` must reproduce an equal value, the file on disk
        /// must be exactly the canonical text plus one trailing newline (the
        /// byte `atomic_write_json`'s `handle.write("\n")` adds), and no `.tmp`
        /// artifact may survive a successful write.
        #[test]
        fn store_then_load_round_trips_with_exact_bytes() {
            let dir = unique_temp_dir("roundtrip");
            let path = dir.join("run.json");

            let mut state = minimal_state();
            state.branch = "v9.0.0-dev.0".into();
            state.updated_at = 1_786_621_458;

            state.store(&path).expect("store succeeds");

            let on_disk = std::fs::read_to_string(&path).expect("file exists");
            let mut expected = state.to_canonical_json();
            expected.push('\n');
            assert_eq!(on_disk, expected);

            let leftovers: Vec<_> = std::fs::read_dir(&dir)
                .expect("dir readable")
                .filter_map(Result::ok)
                .filter(|entry| entry.file_name() != "run.json")
                .collect();
            assert!(
                leftovers.is_empty(),
                "no tempfile should survive a successful store: {leftovers:?}"
            );

            let loaded = super::RunState::load(&path).expect("load succeeds");
            assert_eq!(loaded, state);

            let _ = std::fs::remove_dir_all(&dir);
        }

        /// A second `store` to the same path must replace it atomically --
        /// there is no moment where the file is truncated or missing, and the
        /// old content is fully gone afterward (a torn write would leave a
        /// mixture of old and new bytes; this asserts the end state only, since
        /// asserting mid-write atomicity needs a concurrent reader, which is
        /// what `os.replace`/`rename`'s POSIX guarantee is for).
        #[test]
        fn store_overwrites_an_existing_file_cleanly() {
            let dir = unique_temp_dir("overwrite");
            let path = dir.join("run.json");

            let mut first = minimal_state();
            first.status = "planted".into();
            first.store(&path).expect("first store succeeds");

            let mut second = minimal_state();
            second.status = "closed".into();
            second.store(&path).expect("second store succeeds");

            let loaded = super::RunState::load(&path).expect("load succeeds");
            assert_eq!(loaded.status, "closed");

            let _ = std::fs::remove_dir_all(&dir);
        }

        /// `load` on a missing file is a clean error, not a panic.
        #[test]
        fn load_missing_file_errors() {
            let dir = unique_temp_dir("missing");
            let path = dir.join("does-not-exist.json");
            assert!(super::RunState::load(&path).is_err());
            let _ = std::fs::remove_dir_all(&dir);
        }

        /// Regression for the `File::create` bug this module was fixed for:
        /// `File::create` opens `O_CREAT|O_TRUNC`, not `O_CREAT|O_EXCL`, so two
        /// *different OS processes* independently computing the same
        /// `(nanos, counter)` candidate from `temp_path` could both "succeed" at
        /// opening it -- the second silently truncating the first's in-flight
        /// tempfile out from under it, no error to either side. This drives
        /// `write_and_rename` directly (rather than `RunState::store`) with an
        /// injected candidate sequence, so the collision is deterministic --
        /// not dependent on a real two-process race or wall-clock timing.
        ///
        /// The first candidate is a file this test has already created (playing
        /// the role of "another writer's in-flight tempfile"); the second is
        /// genuinely free. A correct `write_and_rename` must retry past the
        /// first (via `create_new`'s `AlreadyExists`) rather than truncating it,
        /// and the FINAL bytes at `target` must be exactly this write's
        /// content -- never a splice of two writers, never truncated.
        #[test]
        fn store_recovers_from_a_temp_name_collision() {
            let dir = unique_temp_dir("collision");
            let target = dir.join("run.json");

            let colliding = dir.join(".run.json-collision-1.tmp");
            std::fs::write(&colliding, b"stale bytes from another writer's tempfile\n")
                .expect("seed the colliding candidate");
            let free = dir.join(".run.json-collision-2.tmp");

            let mut candidates = vec![colliding.clone(), free.clone()].into_iter();
            let contents = "{\"run\":\"collision-probe\"}";

            write_and_rename(&target, contents, || {
                candidates
                    .next()
                    .expect("only two candidates are needed to prove the retry")
            })
            .expect("write_and_rename must retry past the collision and still succeed");

            // The complete, correct bytes landed at `target` -- not a mix of
            // the collision placeholder and this write, and not truncated
            // partway through.
            let on_disk = std::fs::read_to_string(&target).expect("target exists");
            assert_eq!(on_disk, format!("{contents}\n"));

            // The colliding candidate is untouched: `create_new` failing on it
            // means it was never opened, let alone truncated, by this call --
            // exactly the guarantee `File::create` did not give.
            let untouched =
                std::fs::read_to_string(&colliding).expect("the colliding file must still exist");
            assert_eq!(untouched, "stale bytes from another writer's tempfile\n");

            // The candidate that actually succeeded was renamed onto `target`,
            // so nothing should be left behind at its own path.
            assert!(
                !free.exists(),
                "the successful tempfile must be renamed away, not left behind"
            );

            let _ = std::fs::remove_dir_all(&dir);
        }
    }
}

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
/// Every field but [`run`](Self::run) carries a compatibility default, so a
/// document missing an optional key still loads. `run` is the one field every
/// document must supply.
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
    /// It remains a string so a future value can round-trip before a newer
    /// mutator knows how to transition it.
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
    /// The run's lifecycle status. The native mutation boundary validates
    /// the closed vocabulary (`planted`, `planned`, `executing`, `closing`,
    /// `closed`); the transfer type remains forward-compatible.
    #[serde(default = "default_status")]
    pub status: String,
    /// One row per lane this run has registered.
    #[serde(default)]
    pub lanes: Vec<LaneState>,
    /// Unix epoch seconds of the last write. [`RunState::store`] stamps this
    /// itself; a caller-supplied value here is only ever a starting point.
    #[serde(default)]
    pub updated_at: i64,
    /// Every top-level key this document carries that the fields above do
    /// not name. See the module's `## Unknown keys round-trip` property:
    /// this is what makes that true, and it is not decorative — dropping it
    /// prevents a forward-compatible field-loss regression.
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

impl RunState {
    /// Serialize to the canonical `run.json` text: recursively sorted keys,
    /// 2-space indent, and ASCII-only.
    /// See `canonical` for exactly what that requires beyond
    /// `serde_json`'s own pretty printer, and why.
    ///
    /// Does not include the writer's trailing newline; [`RunState::store`]
    /// (or a caller writing to a different sink) adds that at the point of
    /// writing.
    ///
    /// Infallible by signature, matching the produced interface. The
    /// `.expect(...)` below can never actually panic, for a reason specific
    /// to `serde_json` rather than to how `extra` gets populated: encoding a
    /// NaN or infinite `f64` is not a `serde_json::Error` in the first
    /// place. `serde_json::Number::from_f64` returns `None` for a
    /// non-finite float, and `Value`'s float-serialization path treats that
    /// `None` as `Value::Null` — so a NaN/Infinity float silently becomes
    /// JSON `null`, not a serialization failure. There is therefore no code
    /// path through this struct's serialization that can produce a
    /// `serde_json::Error` at all, regardless of what `extra` holds.
    #[must_use]
    pub fn to_canonical_json(&self) -> String {
        canonical::to_canonical_string(self)
            .expect("RunState never carries a NaN/Infinity float: see this method's doc comment")
    }

    /// Load and parse one `run.json`. A document missing an optional field
    /// parses, and every unknown field round-trips via `extra`. Legacy-shape
    /// migration (`run_id`, dict-keyed lanes, or timestamp coercion) belongs
    /// to the native CLI's locked RunStore boundary.
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
    /// fsync -> rename -> fsync(dir). See `atomic` for the exact sequence.
    ///
    /// It does not stamp [`RunState::updated_at`] itself. The engine writes
    /// what it is given; the native mutator decides when "now" is.
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
