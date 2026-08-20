#!/usr/bin/env python3
# Apply the v6.5.5 cleanup in two TDD phases.

from __future__ import annotations

import argparse
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(message)


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        fail(f"{path}: expected one replacement target, found {count}")
    path.write_text(text.replace(old, new, 1))


def append_once(path: Path, marker: str, block: str) -> None:
    text = path.read_text()
    if marker in text:
        return
    separator = "" if text.endswith("\n") else "\n"
    path.write_text(f"{text}{separator}\n{block.rstrip()}\n")


def apply_tests(root: Path) -> None:
    append_once(
        root / "crates/core/tests/run_state.rs",
        "fn legacy_map_lanes_normalize_to_sequence_and_preserve_audits()",
        r'''
/// Retired writers keyed lanes by lane id and used `run_id`. The reader must
/// normalize that wire shape without losing lane-local or top-level fields.
#[test]
fn legacy_map_lanes_normalize_to_sequence_and_preserve_audits() {
    let state: RunState = serde_json::from_value(serde_json::json!({
        "run_id": "legacy",
        "status": "executing",
        "lanes": {
            "V02-SETTLEMENT-TRUTH": {
                "status": "passed",
                "dependencies": ["A01"],
                "report": "reports/v02.md"
            },
            "V01-STATIC-CONTRACT": {
                "status": "passed",
                "dependencies": []
            }
        },
        "audits": {
            "critic": {"verdict": "pass"}
        }
    }))
    .expect("legacy map-keyed run state parses");

    assert_eq!(state.run, "legacy");
    let lane_ids: Vec<_> = state.lanes.iter().map(|lane| lane.id.as_str()).collect();
    assert_eq!(
        lane_ids,
        vec!["V01-STATIC-CONTRACT", "V02-SETTLEMENT-TRUTH"]
    );
    assert_eq!(state.lanes[0].state, "pending");
    assert_eq!(
        state.lanes[0].extra.get("status"),
        Some(&serde_json::json!("passed"))
    );
    assert_eq!(
        state.extra.get("audits"),
        Some(&serde_json::json!({"critic": {"verdict": "pass"}}))
    );

    let canonical: serde_json::Value =
        serde_json::from_str(&state.to_canonical_json()).expect("canonical state is JSON");
    assert!(canonical["lanes"].is_array());
    assert_eq!(canonical["lanes"][0]["id"], "V01-STATIC-CONTRACT");
    assert_eq!(canonical["lanes"][0]["status"], "passed");
    assert_eq!(
        canonical["audits"],
        serde_json::json!({"critic": {"verdict": "pass"}})
    );
}

/// A map key is authoritative for retired map-shaped documents. Silently
/// accepting a conflicting embedded id would make the normalized lane identity
/// depend on implementation details.
#[test]
fn legacy_map_lane_rejects_an_embedded_id_mismatch() {
    let error = serde_json::from_value::<RunState>(serde_json::json!({
        "run": "legacy",
        "lanes": {
            "L1": {"id": "other"}
        }
    }))
    .expect_err("conflicting lane identities must be rejected");

    assert!(
        error
            .to_string()
            .contains("does not match embedded id"),
        "unexpected error: {error}"
    );
}
''',
    )

    append_once(
        root / "crates/cli/tests/run_store.rs",
        "fn legacy_map_lanes_with_safe_noncanonical_ids_load_and_rewrite_to_current_shape()",
        r'''
#[test]
fn legacy_map_lanes_with_safe_noncanonical_ids_load_and_rewrite_to_current_shape() {
    let dir = fixture_dir("legacy-map-lanes");
    let path = dir.join("legacy/run.json");
    std::fs::create_dir_all(path.parent().expect("run parent")).expect("create run directory");
    std::fs::write(
        &path,
        br#"{
  "run_id": "legacy",
  "status": "executing",
  "lanes": {
    "V01_STATIC-CONTRACT": {
      "status": "passed",
      "dependencies": []
    }
  },
  "audits": {
    "critic": {"verdict": "pass"}
  }
}
"#,
    )
    .expect("write retired run shape");

    let store = RunStore::new(&path);
    let loaded = store.load().expect("retired run shape remains readable");
    assert_eq!(loaded.run, "legacy");
    assert_eq!(loaded.lanes[0].id, "V01_STATIC-CONTRACT");
    assert_eq!(
        loaded.extra.get("audits"),
        Some(&serde_json::json!({"critic": {"verdict": "pass"}}))
    );

    store
        .update(|run| {
            run.branch = "work/legacy".into();
            Ok(())
        })
        .expect("a legitimate update normalizes the retired wire shape");

    let normalized: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).expect("read normalized state"))
            .expect("normalized state is JSON");
    assert!(normalized["lanes"].is_array());
    assert_eq!(normalized["lanes"][0]["id"], "V01_STATIC-CONTRACT");
    assert_eq!(normalized["lanes"][0]["status"], "passed");
    assert_eq!(normalized["branch"], "work/legacy");
    assert_eq!(
        normalized["audits"],
        serde_json::json!({"critic": {"verdict": "pass"}})
    );

    cleanup(&dir);
}
''',
    )

    replace_once(
        root / "crates/cli/tests/wave_b2_run_cli.rs",
        '''        &[
            "run",
            "set",
            "v901-dev0",
            "--status",
            "executing",
            "--seed",
            "runs/v901-dev0/seed.md",
            "--plan",
            "runs/v901-dev0/plan.md",
        ][..],''',
        '''        &[
            "run",
            "set",
            "v901-dev0",
            "--kind",
            "patch-arc",
            "--branch",
            "work/v901-dev0",
            "--base",
            "main",
            "--status",
            "executing",
            "--seed",
            "runs/v901-dev0/seed.md",
            "--plan",
            "runs/v901-dev0/plan.md",
        ][..],''',
    )
    replace_once(
        root / "crates/cli/tests/wave_b2_run_cli.rs",
        '''    let show = invoke(&root, &["run", "show", "v901-dev0", "--json"]);
    assert_eq!(show.status.code(), Some(0));
    assert!(text(&show.stdout).contains("\\\"l1-engine\\\""));''',
        '''    let show = invoke(&root, &["run", "show", "v901-dev0", "--json"]);
    assert_eq!(show.status.code(), Some(0));
    let shown: serde_json::Value =
        serde_json::from_slice(&show.stdout).expect("run show --json emits JSON");
    assert_eq!(shown["kind"], "patch-arc");
    assert_eq!(shown["branch"], "work/v901-dev0");
    assert_eq!(shown["base"], "main");
    assert_eq!(shown["lanes"][0]["id"], "l1-engine");''',
    )

    append_once(
        root / "crates/cli/tests/claude_hook_cli.rs",
        "fn pretooluse_allows_repair_when_run_document_is_unreadable()",
        r'''
#[test]
fn pretooluse_allows_repair_when_run_document_is_unreadable() {
    let root = repository("unreadable-run-repair");
    fs::write(
        root.join(".shepherd/runs/v645/run.json"),
        b"{not valid json",
    )
    .expect("corrupt run fixture");

    let result = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "repair-session",
            "tool_use_id": "repair-tool",
            "tool_name": "Bash",
            "tool_input": {"command": "printf repair"}
        }),
    );
    assert!(
        result.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&result.stderr)
    );
    let output: serde_json::Value =
        serde_json::from_slice(&result.stdout).expect("repair allowance is JSON context");
    assert_eq!(output["hookSpecificOutput"]["hookEventName"], "PreToolUse");
    assert!(
        output["hookSpecificOutput"]["permissionDecision"].is_null(),
        "an infrastructure fault must not become a guard denial: {output}"
    );
    assert!(
        output["hookSpecificOutput"]["additionalContext"]
            .as_str()
            .is_some_and(|detail| {
                detail.contains("dispatch state unavailable, tool allowed")
            }),
        "the fail-open decision must remain visible: {output}"
    );

    fs::remove_dir_all(root).expect("remove fixture directory");
}
''',
    )

    append_once(
        root / "crates/cli/tests/codex_hook_cli.rs",
        "fn codex_pretooluse_allows_repair_when_run_document_is_unreadable()",
        r'''
#[test]
fn codex_pretooluse_allows_repair_when_run_document_is_unreadable() {
    let root = repository("unreadable-run-repair");
    fs::write(
        root.join(".shepherd/runs/v645/run.json"),
        b"{not valid json",
    )
    .expect("corrupt run fixture");

    let result = hook(
        &root,
        serde_json::json!({
            "hook_event_name": "PreToolUse",
            "session_id": "repair-session",
            "tool_use_id": "repair-tool",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** End Patch"}
        }),
    );
    assert!(
        result.status.success(),
        "stderr={}",
        String::from_utf8_lossy(&result.stderr)
    );
    let output: serde_json::Value =
        serde_json::from_slice(&result.stdout).expect("repair allowance is JSON context");
    assert_eq!(output["hookSpecificOutput"]["hookEventName"], "PreToolUse");
    assert!(
        output["hookSpecificOutput"]["permissionDecision"].is_null(),
        "an infrastructure fault must not become a guard denial: {output}"
    );
    assert!(
        output["hookSpecificOutput"]["additionalContext"]
            .as_str()
            .is_some_and(|detail| {
                detail.contains("dispatch state unavailable, tool allowed")
            }),
        "the fail-open decision must remain visible: {output}"
    );

    fs::remove_dir_all(root).expect("remove fixture directory");
}
''',
    )

    seed_test = root / "hooks/tests/test_seed_preflight_target_project.sh"
    if not seed_test.exists():
        seed_test.write_text(
            r'''#!/usr/bin/env bash
# Regression for #354: the seed gate follows the Write target, not hook cwd.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/seed_preflight_check.sh"

tmp="$(mktemp -d -t shepherd-seed-target.XXXXXX)"
trap 'rm -rf "$tmp"' EXIT

repo="$tmp/repo"
outside="$tmp/outside"
bin="$tmp/bin"
mkdir -p "$repo/.shepherd/runs/probe" "$outside" "$bin"
git -C "$repo" init --quiet
printf 'seed_gate = "block"\n' > "$repo/.shepherd/shepherd.toml"

cat > "$bin/shepherd" <<'SH'
#!/usr/bin/env bash
if [[ "${1:-}" == "seed" && "${2:-}" == "verify" ]]; then
  printf '%s\n' 'FAIL: synthetic hard failure'
  exit 1
fi
exit 2
SH
chmod +x "$bin/shepherd"

target="$repo/.shepherd/runs/probe/seed.md"
payload="$(
  jq -nc --arg path "$target" '{
    tool_name: "Write",
    session_id: "seed-target-session",
    tool_input: {
      file_path: $path,
      content: "# Seed\n\nTODO: replace this invalid fixture"
    }
  }'
)"

output="$(
  cd "$outside"
  PATH="$bin:$PATH" SHEPHERD_HOME="$tmp/home" bash "$HOOK" <<<"$payload"
)"

jq -e '
  .permissionDecision == "deny"
  and (.message | contains("synthetic hard failure"))
' >/dev/null <<<"$output"

printf '%s\n' "PASS: seed preflight resolves the target project outside hook cwd"
'''
        )


def apply_implementation(root: Path) -> None:
    replace_once(
        root / "crates/core/src/run.rs",
        '''//! Legacy document normalization belongs to the native CLI's locked RunStore
//! migration boundary. The pure core owns only the typed state and canonical
//! encoding; it does not guess filesystem identity or mutate a run.''',
        '''//! Legacy wire-shape normalization is a pure decoding concern and lives here:
//! map-keyed lanes and the retired `run_id` key load into the current typed
//! shape. Filesystem identity and mutation remain native CLI concerns.''',
    )
    replace_once(
        root / "crates/core/src/run.rs",
        '''use alloc::{collections::BTreeMap, string::String, vec::Vec};''',
        '''use alloc::{collections::BTreeMap, format, string::String, vec::Vec};''',
    )
    replace_once(
        root / "crates/core/src/run.rs",
        '''fn default_status() -> String {
    String::from("planted")
}

/// The `run.json` document''',
        '''fn default_status() -> String {
    String::from("planted")
}

fn deserialize_lanes<'de, D>(
    deserializer: D,
) -> core::result::Result<Vec<LaneState>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::Deserialize as _;
    use serde::de::Error as _;

    #[derive(serde::Deserialize)]
    #[serde(untagged)]
    enum LaneCollection {
        Sequence(Vec<LaneState>),
        Map(BTreeMap<String, serde_json::Value>),
    }

    match LaneCollection::deserialize(deserializer)? {
        LaneCollection::Sequence(lanes) => Ok(lanes),
        LaneCollection::Map(entries) => entries
            .into_iter()
            .map(|(id, mut raw)| {
                let object = raw.as_object_mut().ok_or_else(|| {
                    D::Error::custom(format!("lane `{id}` must be a JSON object"))
                })?;
                match object.get("id") {
                    Some(serde_json::Value::String(existing)) if existing == &id => {}
                    Some(serde_json::Value::String(existing)) => {
                        return Err(D::Error::custom(format!(
                            "lane map key `{id}` does not match embedded id `{existing}`"
                        )));
                    }
                    Some(_) => {
                        return Err(D::Error::custom(format!(
                            "lane `{id}` has a non-string embedded id"
                        )));
                    }
                    None => {
                        object.insert("id".into(), serde_json::Value::String(id.clone()));
                    }
                }
                serde_json::from_value(raw).map_err(D::Error::custom)
            })
            .collect(),
    }
}

/// The `run.json` document''',
    )
    replace_once(
        root / "crates/core/src/run.rs",
        '''    pub run: String,''',
        '''    #[serde(alias = "run_id")]
    pub run: String,''',
    )
    replace_once(
        root / "crates/core/src/run.rs",
        '''    #[serde(default)]
    pub lanes: Vec<LaneState>,''',
        '''    #[serde(default, deserialize_with = "deserialize_lanes")]
    pub lanes: Vec<LaneState>,''',
    )
    replace_once(
        root / "crates/core/src/run.rs",
        '''    /// parses, and every unknown field round-trips via `extra`. Legacy-shape
    /// migration (`run_id`, dict-keyed lanes, or timestamp coercion) belongs
    /// to the native CLI's locked RunStore boundary.''',
        '''    /// parses, every unknown field round-trips via `extra`, and retired
    /// `run_id` plus map-keyed lane shapes normalize into the current form.''',
    )

    replace_once(
        root / "crates/cli/src/run_store.rs",
        '''            validate_id("lane", &lane.id)?;''',
        '''            validate_lane_id(&lane.id)?;''',
    )
    replace_once(
        root / "crates/cli/src/run_store.rs",
        '''fn validate_id(kind: &str, value: &str) -> RunStoreResult<()> {
    let bytes = value.as_bytes();
    let valid = (1..=64).contains(&bytes.len())
        && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit());
    let valid = valid
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'-');
    if valid {
        Ok(())
    } else {
        Err(RunStoreError::Validation(format!(
            "unsafe {kind} id `{value}`"
        )))
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]''',
        '''fn validate_id(kind: &str, value: &str) -> RunStoreResult<()> {
    let bytes = value.as_bytes();
    let valid = (1..=64).contains(&bytes.len())
        && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit());
    let valid = valid
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'-');
    if valid {
        Ok(())
    } else {
        Err(RunStoreError::Validation(format!(
            "unsafe {kind} id `{value}`"
        )))
    }
}

fn validate_lane_id(value: &str) -> RunStoreResult<()> {
    let bytes = value.as_bytes();
    let valid = (1..=64).contains(&bytes.len()) && bytes[0].is_ascii_alphanumeric();
    let valid = valid
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(*byte, b'-' | b'_'));
    if valid {
        Ok(())
    } else {
        Err(RunStoreError::Validation(format!(
            "unsafe lane id `{value}`"
        )))
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]''',
    )

    replace_once(
        root / "crates/cli/src/cmd/wave_b2_run.rs",
        '''    Set {
        run: String,
        #[arg(long, default_value = "")]
        status: String,
        #[arg(long, default_value = "")]
        seed: String,
        #[arg(long, default_value = "")]
        plan: String,
    },''',
        '''    Set {
        run: String,
        #[arg(long, default_value = "")]
        kind: String,
        #[arg(long, default_value = "")]
        branch: String,
        #[arg(long, default_value = "")]
        base: String,
        #[arg(long, default_value = "")]
        status: String,
        #[arg(long, default_value = "")]
        seed: String,
        #[arg(long, default_value = "")]
        plan: String,
    },''',
    )
    replace_once(
        root / "crates/cli/src/cmd/wave_b2_run.rs",
        '''    Layout {
        run: String,
        #[arg(long)]
        repair: bool,
        #[arg(long)]
        json: bool,
    },
}

#[derive(''',
        '''    Layout {
        run: String,
        #[arg(long)]
        repair: bool,
        #[arg(long)]
        json: bool,
    },
}

struct RunSetFields {
    kind: String,
    branch: String,
    base: String,
    status: String,
    seed: String,
    plan: String,
}

#[derive(''',
    )
    replace_once(
        root / "crates/cli/src/cmd/wave_b2_run.rs",
        '''            RunAction::Set {
                run,
                status,
                seed,
                plan,
            } => set(&mut context, &run, &status, &seed, &plan),''',
        '''            RunAction::Set {
                run,
                kind,
                branch,
                base,
                status,
                seed,
                plan,
            } => set(
                &mut context,
                &run,
                RunSetFields {
                    kind,
                    branch,
                    base,
                    status,
                    seed,
                    plan,
                },
            ),''',
    )
    replace_once(
        root / "crates/cli/src/cmd/wave_b2_run.rs",
        '''fn set(
    context: &mut ExecutionContext,
    run: &str,
    status: &str,
    seed: &str,
    plan: &str,
) -> Result<(), CliError> {
    if status.is_empty() && seed.is_empty() && plan.is_empty() {
        return usage("nothing to set (pass --status, --seed, and/or --plan)");
    }
    if !status.is_empty() && !RUN_STATUSES.contains(&status) {
        return usage(format!(
            "invalid --status: {status} (valid: {})",
            RUN_STATUSES.join(", ")
        ));
    }
    update(context, run, |state| {
        if !status.is_empty() {
            state.status = status.into();
        }
        if !seed.is_empty() {
            state.seed = seed.into();
        }
        if !plan.is_empty() {
            state.plan = plan.into();
        }
        Ok(())
    })?;
    output(context, &format!("updated {run}"))
}''',
        '''fn set(
    context: &mut ExecutionContext,
    run: &str,
    fields: RunSetFields,
) -> Result<(), CliError> {
    if fields.kind.is_empty()
        && fields.branch.is_empty()
        && fields.base.is_empty()
        && fields.status.is_empty()
        && fields.seed.is_empty()
        && fields.plan.is_empty()
    {
        return usage(
            "nothing to set (pass --kind, --branch, --base, --status, --seed, and/or --plan)",
        );
    }
    if !fields.kind.is_empty() && !matches!(fields.kind.as_str(), "sprint" | "patch-arc") {
        return usage("invalid --kind: sprint | patch-arc");
    }
    if !fields.status.is_empty() && !RUN_STATUSES.contains(&fields.status.as_str()) {
        return usage(format!(
            "invalid --status: {} (valid: {})",
            fields.status,
            RUN_STATUSES.join(", ")
        ));
    }
    update(context, run, move |state| {
        if !fields.kind.is_empty() {
            state.kind = fields.kind;
        }
        if !fields.branch.is_empty() {
            state.branch = fields.branch;
        }
        if !fields.base.is_empty() {
            state.base = fields.base;
        }
        if !fields.status.is_empty() {
            state.status = fields.status;
        }
        if !fields.seed.is_empty() {
            state.seed = fields.seed;
        }
        if !fields.plan.is_empty() {
            state.plan = fields.plan;
        }
        Ok(())
    })?;
    output(context, &format!("updated {run}"))
}''',
    )

    replace_once(
        root / "hooks/scripts/_lib.sh",
        '''is_shepherd_project() {
  local ns
  ns="$(resolve_namespace 2>/dev/null || true)"
  [[ -n "$ns" && -f "$ns/shepherd.toml" ]]
}''',
        '''is_shepherd_project() {
  local start="${1:-.}" ns
  ns="$(resolve_namespace "$start" 2>/dev/null || true)"
  [[ -n "$ns" && -f "$ns/shepherd.toml" ]]
}''',
    )
    replace_once(
        root / "hooks/scripts/_lib.sh",
        '''cfg_get() {
  local key="$1" f v''',
        '''cfg_get() {
  local key="$1" repo="${2:-}" f v''',
    )
    replace_once(
        root / "hooks/scripts/_lib.sh",
        '''  done < <(shepherd_config_files)
  printf '%s' ""
  return 0
}

# Section-aware companion to cfg_get''',
        '''  done < <(shepherd_config_files "$repo")
  printf '%s' ""
  return 0
}

# Section-aware companion to cfg_get''',
    )

    replace_once(
        root / "hooks/scripts/seed_preflight_check.sh",
        '''input=$(cat)
is_shepherd_project || exit 0
shepherd_require_jq_policy || exit 0

tool=$(json_field "$input" '.tool_name')
[[ "$tool" == "Write" ]] || exit 0

file_path=$(json_field "$input" '.tool_input.file_path')
[[ -z "$file_path" ]] && file_path=$(json_field "$input" '.tool_input.path')
# Two naming shapes are gated (v6.4.1 — the rename hazard, res_12 §3):''',
        '''input=$(cat)
# Without the optional source-tree parser, retain the historical cwd-based
# fail-open boundary. With jq available, applicability is resolved from the
# actual Write target below rather than from the hook process's cwd.
if ! shepherd_jq_available; then
  is_shepherd_project || exit 0
  shepherd_require_jq_policy || exit 0
fi

tool=$(json_field "$input" '.tool_name')
[[ "$tool" == "Write" ]] || exit 0

file_path=$(json_field "$input" '.tool_input.file_path')
[[ -z "$file_path" ]] && file_path=$(json_field "$input" '.tool_input.path')
# Two naming shapes are gated (v6.4.1 — the rename hazard, res_12 §3):''',
    )
    replace_once(
        root / "hooks/scripts/seed_preflight_check.sh",
        '''case "$file_path" in
  *.seed.md) ;;
  */runs/*/seed.md|runs/*/seed.md) ;;
  *) exit 0 ;;
esac

mode="$(cfg_get seed_gate)"; [[ -n "$mode" ]] || mode="block"''',
        '''case "$file_path" in
  *.seed.md) ;;
  */runs/*/seed.md|runs/*/seed.md) ;;
  *) exit 0 ;;
esac

target_dir="$(dirname "$file_path")"
case "$target_dir" in
  /*) ;;
  *) target_dir="$PWD/$target_dir" ;;
esac
while [[ ! -d "$target_dir" ]]; do
  parent="$(dirname "$target_dir")"
  [[ "$parent" != "$target_dir" ]] || break
  target_dir="$parent"
done
is_shepherd_project "$target_dir" || exit 0

mode="$(cfg_get seed_gate "$target_dir")"; [[ -n "$mode" ]] || mode="block"''',
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("tests-only", "implementation"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    if not (root / "Cargo.toml").is_file():
        fail(f"not a shepherd checkout: {root}")

    if args.phase == "tests-only":
        apply_tests(root)
    else:
        apply_implementation(root)


if __name__ == "__main__":
    main()
