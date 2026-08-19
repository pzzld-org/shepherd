#!/usr/bin/env bash
# Regression contract for the v6.4.5 native CLI hook cutover.
#
# Hooks are host adapters. They may invoke the one installed `shepherd` binary,
# but must not recreate a second `shctx` launcher, prescribe that retired name,
# or shell through the plugin-local compatibility launcher.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fails=0
assertions=0

pass() { assertions=$((assertions + 1)); printf '  PASS  %s\n' "$1"; }
fail() { assertions=$((assertions + 1)); printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

expect_executable_absent() {
  local label="$1" pattern="$2" path
  local files=()
  shift 2
  while IFS= read -r path; do
    files+=("$path")
  done < <(find "$@" -type f \( -name '*.sh' -o -name '*.json' \) -print)
  # A scan set that comes up empty is exactly the failure this guard exists to
  # prevent: on bash 3.2 (this Mac) expanding "${files[@]}" here would abort
  # under `set -u`; on bash 4.4+ (every CI runner) it silently expands to zero
  # words, `awk` reads STDIN instead of the intended files, finds nothing, and
  # the caller below would print PASS for a scan that examined nothing. Mirror
  # hooks/tests/run.sh:20-25's own discovery-empty guard instead.
  if [[ "${#files[@]}" -eq 0 ]]; then
    fail "$label: no files discovered for pathspec ($*) -- pathspec drift?"
    return
  fi
  if awk -v needle="$pattern" '
    FNR == 1 { file = FILENAME }
    /^[[:space:]]*#/ { next }
    $0 ~ needle { printf "%s:%d:%s\n", file, FNR, $0; found = 1 }
    END { exit(found ? 0 : 1) }
  ' "${files[@]}" >/dev/null 2>&1; then
    fail "$label"
    awk -v needle="$pattern" '
      /^[[:space:]]*#/ { next }
      $0 ~ needle { printf "%s:%d:%s\n", FILENAME, FNR, $0 }
    ' "${files[@]}" >&2 || true
  else
    pass "$label"
  fi
}

echo "== native hook CLI contract =="

expect_executable_absent \
  "no-retired-shctx-command-or-message-in-executable-hooks" \
  '(shctx[[:space:]]|[[]shctx[]]|shctx[[:space:]]+CLI)' \
  "$ROOT/hooks/scripts" "$ROOT/hooks/hooks.json"
expect_executable_absent \
  "no-plugin-local-bash-launcher-in-hooks" \
  'bash[[:space:]]+.*bin/shepherd' \
  "$ROOT/hooks/scripts" "$ROOT/hooks/hooks.json"
expect_executable_absent \
  "session-start-does-not-install-a-second-cli" \
  'install-shctx-launcher' \
  "$ROOT/hooks/hooks.json"
expect_executable_absent \
  "retired-hooks-are-not-registered" \
  '(coder_git_guard|dups_write_guard|plan_proof_guard|tmux_pane_cleanup|workflow_model_guard)' \
  "$ROOT/hooks/hooks.json"
expect_executable_absent \
  "no-retired-file-based-role-resolution-in-hooks" \
  'current_role' \
  "$ROOT/hooks/scripts"

for command in \
  'dups check --help' \
  'seed --help' \
  'guard eval --help' \
  'plan verify --help' \
  'init --help' \
  'status --help' \
  'doctor --help' \
  'deliverable stalled --help'; do
  if (cd "$ROOT" && cargo run --quiet --locked -p shepherd-cli -- $command >/dev/null 2>&1); then
    pass "native-surface-$command"
  else
    fail "native-surface-$command"
  fi
done

# v6.4.6 (`f3d44b0`) added the `tool_name != "Workflow"` carve-out at
# crates/core/src/guard/engine.rs:398-401: `Workflow` fans out inside its own
# script, so its `tool_input` never carries a single target role, and a
# missing target there is NOT treated as unresolved the way a missing `Agent`
# target is -- this superseded the v6.4.5 contract this assertion used to
# encode (`ee682ec`). A root-tier dispatcher has no target-keyed rule to
# evade, so a script-only `Workflow` payload from `shepherd` resolves straight
# to allow rather than coming back unresolved.
raw_workflow='{"tool_name":"Workflow","role":"shepherd","tool_input":{"script":"const r = await agent(\"x\")"}}'
if raw_out="$(printf '%s' "$raw_workflow" | (cd "$ROOT" && cargo run --quiet --locked -p shepherd-cli -- guard eval) 2>&1)" \
  && printf '%s' "$raw_out" | grep -q '"decision": "allow"'; then
  pass "native-workflow-script-only-from-root-resolves-to-allow"
else
  fail "native-workflow-script-only-from-root-resolves-to-allow: ${raw_out:-no output}"
fi

# Negative control for the carve-out above: a lane lead (conductor) must not
# obtain a target-restricted role by writing the dispatch as a script string
# instead of declaring `target_role` -- the bypass-by-payload-shape guard at
# crates/core/src/guard/engine.rs:420-435. The same script-only `Workflow`
# payload as above, from `conductor` instead of `shepherd`, must still deny
# with WRONG-TIER-DISPATCH so a future author cannot delete this carve-out's
# counterpart and have it go unnoticed.
raw_workflow_lane_lead='{"tool_name":"Workflow","role":"conductor","tool_input":{"script":"const r = await agent(\"x\")"}}'
if lane_lead_out="$(printf '%s' "$raw_workflow_lane_lead" | (cd "$ROOT" && cargo run --quiet --locked -p shepherd-cli -- guard eval) 2>&1)" \
  && printf '%s' "$lane_lead_out" | grep -q '"decision": "deny"' \
  && printf '%s' "$lane_lead_out" | grep -q '"halt_code": "WRONG-TIER-DISPATCH"'; then
  pass "native-workflow-script-only-from-lane-lead-still-denies-wrong-tier-dispatch"
else
  fail "native-workflow-script-only-from-lane-lead-still-denies-wrong-tier-dispatch: ${lane_lead_out:-no output}"
fi

typed_workflow='{"tool_name":"Workflow","role":"shepherd","tool_input":{"target_role":"coder"}}'
if typed_out="$(printf '%s' "$typed_workflow" | (cd "$ROOT" && cargo run --quiet --locked -p shepherd-cli -- guard eval) 2>&1)" \
  && printf '%s' "$typed_out" | grep -q '"decision": "allow"'; then
  pass "native-workflow-typed-target-role-evaluated"
else
  fail "native-workflow-typed-target-role-evaluated: ${typed_out:-no output}"
fi

# G4: a runner that reports success without having examined anything is the
# failure this file exists to prevent (hooks/tests/run.sh:20-25's own guard).
if [[ "$assertions" -eq 0 ]]; then
  printf 'FAIL: test_native_cli_contract: 0 assertions ran -- discovery drift?\n' >&2
  exit 1
fi

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS: test_native_cli_contract (%d assertions ran, 0 failed)\n' "$assertions"
  exit 0
fi

printf 'FAIL: test_native_cli_contract (%d assertions ran, %d failed)\n' "$assertions" "$fails" >&2
exit 1
