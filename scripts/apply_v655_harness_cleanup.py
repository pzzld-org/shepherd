#!/usr/bin/env python3
"""Apply the v6.5.5 harness-agnostic regression fixes on the CI checkout."""

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement target, found {count}")
    target.write_text(text.replace(old, new, 1))


def write(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


# #352: normalize only at RunStore's locked serialization boundary. The core
# transfer type remains canonical and harness-neutral.
replace_once(
    "crates/cli/src/run_store.rs",
    """            let state = RunState::load(&self.path)?;
            self.validate_readable(&state)?;
""",
    """            let bytes = std::fs::read(&self.path)
                .map_err(|source| RunStoreError::io(\"read state\", &self.path, source))?;
            let state = decode_compatible(&bytes, &self.path)?;
            self.validate_readable(&state)?;
""",
)
replace_once(
    "crates/cli/src/run_store.rs",
    """            let mut state = RunState::load(&self.path)?;
            self.validate_writable(&state)?;
""",
    """            let bytes = std::fs::read(&self.path)
                .map_err(|source| RunStoreError::io(\"read state\", &self.path, source))?;
            let mut state = decode_compatible(&bytes, &self.path)?;
            self.validate_writable(&state)?;
""",
)
replace_once(
    "crates/cli/src/run_store.rs",
    '            validate_id("lane", &lane.id)?;\n',
    '            validate_lane_id(&lane.id)?;\n',
)
replace_once(
    "crates/cli/src/run_store.rs",
    """fn validate_id(kind: &str, value: &str) -> RunStoreResult<()> {
""",
    r'''fn decode_compatible(bytes: &[u8], path: &Path) -> RunStoreResult<RunState> {
    let mut document: serde_json::Value = serde_json::from_slice(bytes)
        .map_err(|error| RunStoreError::Validation(format!("{}: {error}", path.display())))?;
    normalize_legacy_run_document(&mut document, path)?;
    serde_json::from_value(document)
        .map_err(|error| RunStoreError::Validation(format!("{}: {error}", path.display())))
}

/// Normalize the pre-v1 map-shaped run document without discarding unknown
/// top-level or lane fields. Canonical bytes are written only after a caller
/// performs a legitimate locked mutation.
fn normalize_legacy_run_document(
    document: &mut serde_json::Value,
    path: &Path,
) -> RunStoreResult<()> {
    let object = document.as_object_mut().ok_or_else(|| {
        RunStoreError::Validation(format!(
            "{}: run document must be a JSON object",
            path.display()
        ))
    })?;

    let canonical_run = object.get("run").cloned();
    let legacy_run = object.remove("run_id");
    match (canonical_run, legacy_run) {
        (None, Some(value)) => {
            object.insert("run".into(), value);
        }
        (Some(canonical), Some(legacy)) if canonical != legacy => {
            return Err(RunStoreError::Validation(format!(
                "{}: conflicting `run` and legacy `run_id` values",
                path.display()
            )));
        }
        _ => {}
    }

    let Some(lanes) = object.get_mut("lanes") else {
        return Ok(());
    };
    if !lanes.is_object() {
        return Ok(());
    }
    let serde_json::Value::Object(legacy_lanes) = std::mem::take(lanes) else {
        unreachable!("object shape checked above")
    };
    let mut rows: Vec<_> = legacy_lanes.into_iter().collect();
    rows.sort_by(|left, right| left.0.cmp(&right.0));
    let mut normalized = Vec::with_capacity(rows.len());

    for (lane_key, mut value) in rows {
        let lane = value.as_object_mut().ok_or_else(|| {
            RunStoreError::Validation(format!(
                "{}: legacy lane `{lane_key}` must be a JSON object",
                path.display()
            ))
        })?;
        match lane.get("id") {
            None => {
                lane.insert("id".into(), serde_json::Value::String(lane_key.clone()));
            }
            Some(serde_json::Value::String(id)) if id == &lane_key => {}
            Some(serde_json::Value::String(id)) => {
                return Err(RunStoreError::Validation(format!(
                    "{}: legacy lane key `{lane_key}` conflicts with embedded id `{id}`",
                    path.display()
                )));
            }
            Some(_) => {
                return Err(RunStoreError::Validation(format!(
                    "{}: legacy lane `{lane_key}` has a non-string id",
                    path.display()
                )));
            }
        }

        if let Some(status_value) = lane.remove("status") {
            let status = status_value.as_str().ok_or_else(|| {
                RunStoreError::Validation(format!(
                    "{}: legacy lane `{lane_key}` has a non-string status",
                    path.display()
                ))
            })?;
            let mapped = legacy_lane_state(status);
            match lane.get("state") {
                None => {
                    lane.insert("state".into(), serde_json::Value::String(mapped.into()));
                }
                Some(serde_json::Value::String(state)) if state == mapped => {}
                Some(serde_json::Value::String(state)) => {
                    return Err(RunStoreError::Validation(format!(
                        "{}: legacy lane `{lane_key}` status `{status}` conflicts with state `{state}`",
                        path.display()
                    )));
                }
                Some(_) => {
                    return Err(RunStoreError::Validation(format!(
                        "{}: legacy lane `{lane_key}` has a non-string state",
                        path.display()
                    )));
                }
            }
        }
        normalized.push(value);
    }
    *lanes = serde_json::Value::Array(normalized);
    Ok(())
}

fn legacy_lane_state(status: &str) -> &str {
    match status {
        "passed" | "pass" | "completed" | "done" => "complete",
        "failed" | "failure" | "fail" => "error",
        "running" | "active" | "executing" | "in_progress" => "in-progress",
        "blocked" | "queued" | "not_started" => "pending",
        other => other,
    }
}

/// Legacy orchestration lane ids used upper-case phase labels. They remain
/// path-safe, while new lane creation continues to use the stricter canonical
/// lower-case validator in the command surface.
fn validate_lane_id(value: &str) -> RunStoreResult<()> {
    let bytes = value.as_bytes();
    let valid = (1..=64).contains(&bytes.len()) && bytes[0].is_ascii_alphanumeric();
    let valid = valid
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || *byte == b'-');
    if valid {
        Ok(())
    } else {
        Err(RunStoreError::Validation(format!(
            "unsafe lane id `{value}`"
        )))
    }
}

fn validate_id(kind: &str, value: &str) -> RunStoreResult<()> {
''',
)
replace_once(
    "crates/cli/src/run_store.rs",
    """    fn decode(store: &RunStore, parent: &OwnedFd) -> RunStoreResult<RunState> {
        serde_json::from_slice(&read_regular(store, parent, "run.json")?).map_err(|error| {
            RunStoreError::Validation(format!("{}: {error}", store.path.display()))
        })
    }
""",
    """    fn decode(store: &RunStore, parent: &OwnedFd) -> RunStoreResult<RunState> {
        decode_compatible(
            &read_regular(store, parent, \"run.json\")?,
            &store.path,
        )
    }
""",
)

# #355: branch and base are ordinary run metadata and must be mutable through
# the same locked state transition as status/seed/plan.
replace_once(
    "crates/cli/src/cmd/wave_b2_run.rs",
    """        #[arg(long, default_value = "")]
        plan: String,
    },
    Lane {
""",
    """        #[arg(long, default_value = "")]
        plan: String,
        #[arg(long, default_value = "")]
        branch: String,
        #[arg(long, default_value = "")]
        base: String,
    },
    Lane {
""",
)
replace_once(
    "crates/cli/src/cmd/wave_b2_run.rs",
    """                status,
                seed,
                plan,
            } => set(&mut context, &run, &status, &seed, &plan),
""",
    """                status,
                seed,
                plan,
                branch,
                base,
            } => set(
                &mut context,
                &run,
                &status,
                &seed,
                &plan,
                &branch,
                &base,
            ),
""",
)
replace_once(
    "crates/cli/src/cmd/wave_b2_run.rs",
    """    seed: &str,
    plan: &str,
) -> Result<(), CliError> {
    if status.is_empty() && seed.is_empty() && plan.is_empty() {
        return usage("nothing to set (pass --status, --seed, and/or --plan)");
    }
""",
    """    seed: &str,
    plan: &str,
    branch: &str,
    base: &str,
) -> Result<(), CliError> {
    if status.is_empty()
        && seed.is_empty()
        && plan.is_empty()
        && branch.is_empty()
        && base.is_empty()
    {
        return usage(
            "nothing to set (pass --status, --seed, --plan, --branch, and/or --base)",
        );
    }
""",
)
replace_once(
    "crates/cli/src/cmd/wave_b2_run.rs",
    """        if !plan.is_empty() {
            state.plan = plan.into();
        }
        Ok(())
""",
    """        if !plan.is_empty() {
            state.plan = plan.into();
        }
        if !branch.is_empty() {
            state.branch = branch.into();
        }
        if !base.is_empty() {
            state.base = base.into();
        }
        Ok(())
""",
)

# #353: a syntactically present but undecodable run is not a usable authority.
# Resolve it through the same compatibility-aware RunStore used everywhere else.
replace_once(
    "crates/cli/src/cmd/native_hook.rs",
    """    BindRootDispatchRequest, ContextInputs, DispatchService, DispatchStore, ExecutionContext,
""",
    """    BindRootDispatchRequest, ContextInputs, DispatchService, DispatchStore, ExecutionContext,
    RunStore,
""",
)
replace_once(
    "crates/cli/src/cmd/native_hook.rs",
    """    entries.filter_map(Result::ok).any(|entry| {
        let run = entry.path();
        run.join("dispatch").is_dir()
            && fs::read(run.join("run.json"))
                .ok()
                .and_then(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes).ok())
                .is_some_and(|document| document["status"] == "executing")
    })
""",
    """    entries.filter_map(Result::ok).any(|entry| {
        let run = entry.path();
        run.join("dispatch").is_dir()
            && RunStore::new(run.join("run.json"))
                .load()
                .ok()
                .is_some_and(|document| document.status == "executing")
    })
""",
)

# #354: source-tree policy adapters must resolve the project and config from
# the payload path, not from whichever cwd the host happened to assign.
replace_once(
    "hooks/scripts/_lib.sh",
    """is_shepherd_project() {
  local ns
  ns="$(resolve_namespace 2>/dev/null || true)"
  [[ -n "$ns" && -f "$ns/shepherd.toml" ]]
}
""",
    """is_shepherd_project() {
  local start="${1:-.}" ns
  ns="$(resolve_namespace "$start" 2>/dev/null || true)"
  [[ -n "$ns" && -f "$ns/shepherd.toml" ]]
}
""",
)
replace_once(
    "hooks/scripts/_lib.sh",
    """cfg_get() {
  local key="$1" f v
""",
    """cfg_get() {
  local key="$1" repo="${2:-}" f v
""",
)
replace_once(
    "hooks/scripts/_lib.sh",
    """  done < <(shepherd_config_files)
  printf '%s' ""
  return 0
}

# Section-aware companion to cfg_get:
""",
    """  done < <(shepherd_config_files "$repo")
  printf '%s' ""
  return 0
}

# Section-aware companion to cfg_get:
""",
)

write(
    "hooks/scripts/seed_preflight_check.sh",
    r'''#!/usr/bin/env bash
# Seed preflight check — blocks/warns when a written seed fails native verification.
# Input: Claude Code PreToolUse JSON on stdin.
# Config: seed_gate = "block" | "warn" | "off" (default: block)
set -uo pipefail
source "$(dirname "$0")/_lib.sh"

input=$(cat)
shepherd_require_jq_policy || exit 0

tool=$(printf '%s' "$input" | jq -r '.tool_name // ""' 2>/dev/null || echo "")
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null || echo "")

[[ "$tool" == "Write" ]] || exit 0
[[ "$file_path" == */.shepherd/runs/*/seed.md ]] || exit 0

payload_dir=$(dirname "$file_path")
while [[ ! -d "$payload_dir" && "$payload_dir" != "/" && "$payload_dir" != "." ]]; do
  payload_dir=$(dirname "$payload_dir")
done
is_shepherd_project "$payload_dir" || exit 0
project_root="$(primary_worktree_root "$payload_dir" 2>/dev/null || true)"
[[ -n "$project_root" ]] || exit 0

mode="$(cfg_get seed_gate "$project_root")"
[[ -z "$mode" ]] && mode="block"
[[ "$mode" == "off" ]] && exit 0

content=$(printf '%s' "$input" | jq -r '.tool_input.content // ""' 2>/dev/null || echo "")
[[ -n "$content" ]] || exit 0

tmp="$(mktemp "${TMPDIR:-/tmp}/shepherd-seed.XXXXXX")" || exit 0
trap 'rm -f "$tmp"' EXIT
printf '%s' "$content" > "$tmp"

shepherd_bin="$(shepherd_cli 2>/dev/null || true)"
if [[ -z "$shepherd_bin" ]]; then
  emit_context "seed preflight skipped: native shepherd binary unavailable"
fi
report="$(cd "$project_root" && "$shepherd_bin" seed verify "$tmp" 2>/dev/null || true)"

if printf '%s' "$report" | jq -e '.ok == true' >/dev/null 2>&1; then
  exit 0
fi

summary=$(printf '%s' "$report" | jq -r '[.errors[]?, .warnings[]?] | join("; ")' 2>/dev/null || echo "seed verification failed")
[[ -z "$summary" ]] && summary="seed verification failed"

if [[ "$mode" == "warn" ]]; then
  emit_context "Seed preflight warning: $summary"
fi
emit_deny "Seed preflight failed: $summary"
''',
)

# #348: package adapters and source-tree hooks share one deterministic native
# binary authority chain instead of assuming an interactive PATH.
replace_once(
    "packages/component-runtime/src/native-transport.mjs",
    'import { spawnSync } from "node:child_process";\n',
    '''import { spawnSync } from "node:child_process";
import { constants, accessSync } from "node:fs";
import { delimiter, join } from "node:path";
''',
)
replace_once(
    "packages/component-runtime/src/native-transport.mjs",
    """export function nativeShepherdBin(override = undefined, environment = process.env) {
  if (typeof override === "string" && override.length > 0) return override;
  const configured = environment?.SHEPHERD_NATIVE_BIN;
  return typeof configured === "string" && configured.length > 0 ? configured : "shepherd";
}
""",
    """function executable(candidate) {
  try {
    accessSync(candidate, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

export function nativeShepherdBin(
  override = undefined,
  environment = process.env,
  isExecutable = executable,
) {
  if (typeof override === "string" && override.length > 0) return override;
  const configured = environment?.SHEPHERD_NATIVE_BIN;
  if (typeof configured === "string" && configured.length > 0) return configured;

  const names = process.platform === "win32"
    ? ["shepherd.exe", "shepherd.cmd", "shepherd"]
    : ["shepherd"];
  const path = typeof environment?.PATH === "string" ? environment.PATH : "";
  for (const directory of path.split(delimiter).filter(Boolean)) {
    for (const name of names) {
      const candidate = join(directory, name);
      if (isExecutable(candidate)) return candidate;
    }
  }

  const home = environment?.HOME || environment?.USERPROFILE;
  if (typeof home === "string" && home.length > 0) {
    for (const directory of [join(home, ".cargo", "bin"), join(home, ".local", "bin"), join(home, "bin")]) {
      for (const name of names) {
        const candidate = join(directory, name);
        if (isExecutable(candidate)) return candidate;
      }
    }
  }
  return "shepherd";
}
""",
)

write(
    "hooks/scripts/shepherd_native.sh",
    r'''#!/usr/bin/env bash
# Resolve the operator-installed native Shepherd binary for non-interactive hooks.
set -uo pipefail

if [[ -n "${SHEPHERD_NATIVE_BIN:-}" ]]; then
  exec "$SHEPHERD_NATIVE_BIN" "$@"
fi

resolved="$(command -v shepherd 2>/dev/null || true)"
if [[ -n "$resolved" ]]; then
  exec "$resolved" "$@"
fi

for candidate in \
  "${HOME:-}/.cargo/bin/shepherd" \
  "${HOME:-}/.local/bin/shepherd" \
  "${HOME:-}/bin/shepherd"
do
  if [[ -x "$candidate" ]]; then
    exec "$candidate" "$@"
  fi
done

printf '[shepherd] native shepherd binary not found; set SHEPHERD_NATIVE_BIN or install shepherd in PATH, ~/.cargo/bin, ~/.local/bin, or ~/bin\n' >&2
exit 127
''',
)
replace_once(
    "hooks/hooks.json",
    '"command": "shepherd"',
    '"command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/shepherd_native.sh"',
)
# Replace all remaining native hook launchers after the first assertion-backed replacement.
hooks = Path("hooks/hooks.json")
hooks.write_text(hooks.read_text().replace(
    '"command": "shepherd"',
    '"command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/shepherd_native.sh"',
))

print("v6.5.5 harness-agnostic cleanup applied")
