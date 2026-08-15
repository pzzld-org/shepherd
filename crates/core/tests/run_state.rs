/*
    Appellation: run_state <test>
    Contrib: @FL03
*/
//! Golden-byte tests for the canonical native `run.json` contract.
//!
//! Integration tests: these exercise only the public API, so they live here and
//! not inside `src/`. The four `atomic_io` cases that remain inline in
//! `crates/core/src/run.rs` do so because they reach `crate::run::atomic`, a
//! private module an integration test cannot see.
//!
//! Wired via `[[test]] required-features = ["std", "json"]` -- `run` is gated on
//! `json`, so without that this file would silently build against a crate with
//! no `run` module at all.

use shepherd_core::run::{LaneState, RunState};

/// A `run.json` shaped like a real one (`.shepherd/runs/v645/run.json`, with
/// its lane list trimmed to one row), plus a top-level unknown field and a
/// nested unknown field inside the lane -- proving BOTH invariants at once:
/// recursive sort (the top-level unknown key interleaves alphabetically with
/// the named ones; the nested one sorts inside its own object) and
/// round-trip preservation of fields this struct does not declare.
///
/// The literal below pins those bytes directly; changing the encoder requires
/// an intentional versioned-contract update.
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

fn minimal_state() -> RunState {
    serde_json::from_value(serde_json::json!({"run": "v1"})).expect("minimal doc parses")
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
        "canonical output must match the pinned run-state bytes"
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

/// The pinned run-state wire contract writes every codepoint above `U+007F`
/// as `\uXXXX` and astral codepoints as a UTF-16 surrogate pair. `serde_json`
/// does not do this by default, which is exactly the gap
/// `crate::run::canonical` closes by hand. Covers a 2-byte
/// UTF-8 codepoint (`é`), a 3-byte one (`☕`), an astral 4-byte one needing a
/// surrogate pair (`🎉`), and the standard `\n`/`\t`/`\"`/`\\` escapes.
#[test]
fn non_ascii_and_control_characters_use_pinned_wire_escapes() {
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
        "canonical output must be pure ASCII; got: {text}"
    );
}

/// A document carrying only the one required field must load with every
/// other field at the run-state contract's default, not fail or silently
/// substitute a different default.
#[test]
fn defaults_match_the_run_state_contract() {
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
