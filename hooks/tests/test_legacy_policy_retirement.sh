#!/usr/bin/env bash
# v6.4.5: Claude registration delegates policy to the native component only.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="$ROOT/hooks/hooks.json"
AUDIT="$ROOT/hooks/scripts/hook_authority_inventory.py"
fails=0

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

if ! command -v jq >/dev/null 2>&1; then
  printf '  FAIL  jq is required for registry retirement checks\n' >&2
  exit 1
fi

retired=(
  session_open.sh
  focus_rehydrate.sh
  bash_guard.sh
  teammate_git_guard.sh
  worktree_teardown_guard.sh
  release_trigger_guard.sh
  conductor_write_guard.sh
  lock_guard.sh
  dedup_write_guard.sh
  dispatch_guard.sh
  teammate_idle.sh
  coordinate_drive_guard.sh
  deliverable_check.sh
  close_finalize_check.sh
  user_prompt_submit.sh
  teammate_heartbeat.sh
  worktree_lifecycle.sh
  hotfix_vehicle_guard.sh
  workflow_model_guard.sh
)

commands="$(jq -r '.. | objects | select(.type? == "command") | .command? // empty' "$CONFIG")"
for script in "${retired[@]}"; do
  if grep -qF "$script" <<<"$commands"; then
    fail "$script is unregistered"
  else
    pass "$script is unregistered"
  fi
  if [[ -e "$ROOT/hooks/scripts/$script" ]]; then
    fail "$script source is deleted"
  else
    pass "$script source is deleted"
  fi
done

if jq -e '[.. | objects | select(.type? == "agent")] | length == 0' "$CONFIG" >/dev/null; then
  pass "no nondeterministic agent hook remains"
else
  fail "no nondeterministic agent hook remains"
fi

if ! grep -Eqi 'PRIMARY-RELAY-REQUIRED|shctx|services/cli|bin/shepherd' <<<"$commands"; then
  pass "registered commands contain no secondary CLI or relay policy"
else
  fail "registered commands contain no secondary CLI or relay policy"
fi

expected_targets=$'hooks/scripts/agent_insight_capture.sh\nhooks/scripts/bash_post.sh\nhooks/scripts/cwd_changed.sh\nhooks/scripts/discovery_capture.sh\nhooks/scripts/precompact_snapshot.sh\nhooks/scripts/seed_preflight_check.sh\nhooks/scripts/subagent_telemetry.sh\npackages/harness-claude/hooks/dispatch-lifecycle.mjs\npackages/harness-claude/hooks/guard-eval.mjs'
actual_targets="$(
  jq -r '.. | objects | select(.type? == "command") | .command? // empty' "$CONFIG" \
    | sed -nE 's#.*((hooks/scripts|packages/harness-claude/hooks)/[A-Za-z0-9_.-]+\.(sh|mjs)).*#\1#p' \
    | sort -u
)"
if [[ "$actual_targets" == "$expected_targets" ]]; then
  pass "registry has exactly three native adapters and six telemetry adapters"
else
  fail "registry has exactly three native adapters and six telemetry adapters"
  printf '        actual targets:\n%s\n' "$actual_targets" >&2
fi

if strict="$(python3 "$AUDIT" --strict 2>&1)" \
   && [[ "$strict" == *'3 thin, 6 telemetry, 0 independent, 0 nondeterministic'* ]]; then
  pass "strict authority inventory is green"
else
  fail "strict authority inventory is green"
  printf '        %s\n' "${strict:-no output}" >&2
fi

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS: test_legacy_policy_retirement\n'
  exit 0
fi

printf 'FAIL: test_legacy_policy_retirement (%d)\n' "$fails" >&2
exit 1
