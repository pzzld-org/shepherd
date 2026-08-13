/*
    Appellation: tests <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! Golden-byte tests against the Python oracle (`models_run.py`).
//!
//! There is no `conformance/cases/run-state/**` corpus yet for
//! `conformance/run.sh --impl=rust --suite=run-state` to run against — see
//! this lane's `Deviations` entry. Every "golden" literal below was
//! independently computed by running the REAL Python encoder
//! (`json.dumps(doc, indent=2, sort_keys=True)`, `ensure_ascii=True` by
//! default) against an equivalent document, not hand-written, so these are
//! oracle-checked even without the corpus.
#[cfg(not(feature = "std"))]
use alloc::{format, string::String, vec, vec::Vec};

use super::{LaneState, RunState};

/// A `run.json` shaped like a real one (`.shepherd/runs/v645/run.json`, with
/// its lane list trimmed to one row), plus a top-level unknown field and a
/// nested unknown field inside the lane -- proving BOTH invariants at once:
/// recursive sort (the top-level unknown key interleaves alphabetically with
/// the named ones; the nested one sorts inside its own object) and
/// round-trip preservation of fields this struct does not declare.
///
/// Golden text independently produced by:
/// ```python
/// json.dumps({
///     "schema_version": 1, "run": "v900-dev0", "kind": "sprint",
///     "branch": "v9.0.0-dev.0", "base": "main", "seed": "", "plan": "",
///     "status": "planted", "updated_at": 1786621458,
///     "lanes": [{
///         "id": "l1-engine", "plan": "lanes/l1-engine/plan.md",
///         "worktree": "", "branch": "", "state": "pending",
///         "accepted_commit": None, "merged": False, "updated_at": 0,
///         "nested_unknown": {"z": 1, "a": 2},
///     }],
///     "custom_future_field": {"b": 2, "a": 1},
/// }, indent=2, sort_keys=True)
/// ```
const GOLDEN_WITH_UNKNOWN_KEYS: &str = r#"{
  "base": "main",
  "branch": "v9.0.0-dev.0",
  "custom_future_field": {
    "a": 1,
    "b": 2
  },
  "kind": "sprint",
  "lanes": [
    {
      "accepted_commit": null,
      "branch": "",
      "id": "l1-engine",
      "merged": false,
      "nested_unknown": {
        "a": 2,
        "z": 1
      },
      "plan": "lanes/l1-engine/plan.md",
      "state": "pending",
      "updated_at": 0,
      "worktree": ""
    }
  ],
  "plan": "",
  "run": "v900-dev0",
  "schema_version": 1,
  "seed": "",
  "status": "planted",
  "updated_at": 1786621458
}"#;

fn source_document() -> serde_json::Value {
    serde_json::json!({
        "schema_version": 1,
        "run": "v900-dev0",
        "kind": "sprint",
        "branch": "v9.0.0-dev.0",
        "base": "main",
        "seed": "",
        "plan": "",
        "status": "planted",
        "updated_at": 1_786_621_458i64,
        "lanes": [{
            "id": "l1-engine",
            "plan": "lanes/l1-engine/plan.md",
            "worktree": "",
            "branch": "",
            "state": "pending",
            "accepted_commit": null,
            "merged": false,
            "updated_at": 0,
            "nested_unknown": {"z": 1, "a": 2},
        }],
        "custom_future_field": {"b": 2, "a": 1},
    })
}

/// The two non-negotiable properties, checked as one: keys sorted
/// recursively (top level AND inside the lane's own unknown-key bag) and
/// unknown keys preserved through deserialize -> serialize. This is the
/// `run::tests::unknown_keys_round_trip` acceptance target.
#[test]
fn unknown_keys_round_trip() {
    let state: RunState =
        serde_json::from_value(source_document()).expect("the fixture is a valid RunState");

    assert_eq!(
        state.extra.get("custom_future_field"),
        Some(&serde_json::json!({"a": 1, "b": 2})),
        "a top-level key RunState does not declare must survive parsing"
    );
    let lane = &state.lanes[0];
    assert_eq!(
        lane.extra.get("nested_unknown"),
        Some(&serde_json::json!({"a": 2, "z": 1})),
        "a key LaneState does not declare must survive parsing too"
    );

    assert_eq!(
        state.to_canonical_json(),
        GOLDEN_WITH_UNKNOWN_KEYS,
        "canonical output must match the Python oracle byte-for-byte"
    );

    // And the other direction: re-parsing the canonical text this struct
    // just emitted must reproduce an identical value. A round trip that
    // only works one way is not a round trip.
    let reparsed: RunState =
        serde_json::from_str(&state.to_canonical_json()).expect("canonical output re-parses");
    assert_eq!(reparsed, state);
}

/// Isolates the sort claim from the round-trip claim: no unknown keys here
/// at all, just named fields whose declaration order (`schema_version`,
/// `run`, `kind`, `branch`, ...) is deliberately NOT alphabetical, so a
/// passing test proves the output is sorted rather than coincidentally
/// matching declaration order.
#[test]
fn keys_are_recursively_sorted_even_with_no_unknown_keys() {
    let state = RunState {
        schema_version: 1,
        run: "v900-dev0".into(),
        kind: "sprint".into(),
        branch: "v9.0.0-dev.0".into(),
        base: "main".into(),
        seed: String::new(),
        plan: String::new(),
        status: "planted".into(),
        updated_at: 1_786_621_458,
        lanes: vec![LaneState {
            id: "l1-engine".into(),
            plan: "lanes/l1-engine/plan.md".into(),
            worktree: String::new(),
            branch: String::new(),
            state: "pending".into(),
            accepted_commit: None,
            merged: false,
            updated_at: 0,
            extra: Default::default(),
        }],
        extra: Default::default(),
    };

    let text = state.to_canonical_json();
    // "accepted_commit" < "branch" < "id" < "merged" < "plan" < "state" <
    // "updated_at" < "worktree" inside the lane object; "base" < "branch" <
    // "kind" < "lanes" < "plan" < "run" < "schema_version" < "seed" <
    // "status" < "updated_at" at the top. Assert the top-level order
    // directly rather than re-deriving the whole golden string twice.
    let top_level_keys: Vec<&str> = text
        .lines()
        .filter(|line| line.starts_with("  \"") && line.contains("\":"))
        .map(|line| {
            let after_quote = &line[3..];
            &after_quote[..after_quote.find('"').expect("closing quote")]
        })
        .collect();
    assert_eq!(
        top_level_keys,
        vec![
            "base",
            "branch",
            "kind",
            "lanes",
            "plan",
            "run",
            "schema_version",
            "seed",
            "status",
            "updated_at",
        ]
    );
}

/// Python's `json.dump` defaults to `ensure_ascii=True`: every codepoint
/// above `U+007F` is written as `\uXXXX`, astral codepoints as a UTF-16
/// surrogate pair. `serde_json` does not do this by default, which is
/// exactly the gap `crate::run::canonical` closes by hand. Covers a 2-byte
/// UTF-8 codepoint (`é`), a 3-byte one (`☕`), an astral 4-byte one needing a
/// surrogate pair (`🎉`), and the standard `\n`/`\t`/`\"`/`\\` escapes.
///
/// Golden text independently produced by:
/// ```python
/// json.dumps("café ☕ \U0001f389 line1\nline2\ttab \"quote\" back\\slash")
/// ```
#[test]
fn non_ascii_and_control_characters_escape_like_python() {
    let mut state = minimal_state();
    state.extra.insert(
        "note".into(),
        serde_json::Value::String(
            "café \u{2615} \u{1F389} line1\nline2\ttab \"quote\" back\\slash".into(),
        ),
    );

    let text = state.to_canonical_json();
    let expected_value =
        "\"caf\\u00e9 \\u2615 \\ud83c\\udf89 line1\\nline2\\ttab \\\"quote\\\" back\\\\slash\"";
    assert!(
        text.contains(&format!("\"note\": {expected_value}")),
        "expected the escaped literal {expected_value} in:\n{text}"
    );
    assert!(
        text.is_ascii(),
        "canonical output must be pure ASCII, matching ensure_ascii=True; got: {text}"
    );
}

fn minimal_state() -> RunState {
    serde_json::from_value(serde_json::json!({"run": "v1"})).expect("minimal doc parses")
}

/// A document carrying only the one required field must load with every
/// other field at the Python reference's default -- not fail, and not
/// silently substitute a DIFFERENT default.
#[test]
fn defaults_match_the_python_reference() {
    let state = minimal_state();
    assert_eq!(state.schema_version, 1);
    assert_eq!(state.run, "v1");
    assert_eq!(state.kind, "sprint");
    assert_eq!(state.branch, "");
    assert_eq!(state.base, "");
    assert_eq!(state.seed, "");
    assert_eq!(state.plan, "");
    assert_eq!(state.status, "planted");
    assert!(state.lanes.is_empty());
    assert_eq!(state.updated_at, 0);
    assert!(state.extra.is_empty());
}

/// `LaneState` carries the same `extra = "allow"` guarantee independently of
/// `RunState` -- a lane row is itself a document another implementation
/// might write extra fields into.
#[test]
fn lane_state_extra_round_trips_independently() {
    let lane: LaneState = serde_json::from_value(serde_json::json!({
        "id": "l9-example",
        "declared_state": "in-progress",
    }))
    .expect("lane document parses");

    assert_eq!(lane.id, "l9-example");
    assert_eq!(lane.state, "pending", "LANE default, not the unknown key");
    assert_eq!(
        lane.extra.get("declared_state"),
        Some(&serde_json::Value::String("in-progress".into()))
    );
}

/// Empty containers must render as `{}` / `[]`, not `{\n}` / `[\n]` --
/// `json.dumps({}, indent=2)` collapses them, and so must this.
#[test]
fn empty_containers_do_not_expand() {
    let state = minimal_state();
    let text = state.to_canonical_json();
    assert!(text.contains("\"lanes\": []"));
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
