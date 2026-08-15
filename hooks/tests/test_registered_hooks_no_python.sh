#!/usr/bin/env bash
# Registered source-tree hooks are shell/jq adapters only.  The packaged
# Claude distribution uses Node + the native component; dogfood hooks must not
# smuggle a second Python runtime back into the supported surface.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="$ROOT/hooks/hooks.json"
LIB="$ROOT/hooks/scripts/_lib.sh"
fails=0
checks=0

fail() { checks=$((checks + 1)); printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }

if ! command -v jq >/dev/null 2>&1; then
  printf '  FAIL  test fixture requires jq to inspect registered hook commands\n' >&2
  exit 1
fi

scripts=()
while IFS= read -r script; do
  [[ -n "$script" ]] || continue
  scripts+=("$script")
done < <(
  jq -r '.. | objects | select(.type? == "command") | .command? // empty' "$CONFIG" \
    | sed -nE 's#.*hooks/scripts/([A-Za-z0-9_.-]+\.sh).*#\1#p' \
    | sort -u
)

if ((${#scripts[@]} == 0)); then
  fail "registered hook scripts discovered"
else
  pass "registered hook scripts discovered (${#scripts[@]})"
fi

for script in "${scripts[@]}"; do
  path="$ROOT/hooks/scripts/$script"
  if [[ ! -x "$path" ]]; then
    fail "$script exists and is executable"
    continue
  fi
  matches="$(rg -n '\bpython3\b' "$path" 2>/dev/null || true)"
  if [[ -n "$matches" ]]; then
    fail "$script has no Python runtime dependency: $matches"
  fi
done

# The sole shell PreToolUse adapter delegates its verdict to the native binary.
# Telemetry names the diagnostic skip branch so a future registration cannot
# silently fall back to an empty parser result.
for script in seed_preflight_check.sh; do
  if rg -qF 'shepherd_require_jq_policy' "$ROOT/hooks/scripts/$script"; then
    pass "$script declares PreToolUse jq fail-closed behavior"
  else
    fail "$script lacks PreToolUse jq fail-closed behavior"
  fi
done

telemetry_hooks=(
  agent_insight_capture.sh
  bash_post.sh
  cwd_changed.sh
  discovery_capture.sh
  precompact_snapshot.sh
  subagent_telemetry.sh
)
for script in "${telemetry_hooks[@]}"; do
  if rg -qF 'shepherd_skip_without_jq' "$ROOT/hooks/scripts/$script"; then
    pass "$script declares telemetry jq diagnostic behavior"
  else
    fail "$script lacks telemetry jq diagnostic behavior"
  fi
done

tmp="$(mktemp -d -t shepherd-hook-jq-contract.XXXXXX)"
trap 'find "$tmp" -depth -delete' EXIT
mkdir -p "$tmp/bin"

policy_out="$(PATH="$tmp/bin" /bin/bash -c 'source "$1"; shepherd_require_jq_policy' _ "$LIB" 2>/dev/null || true)"
if [[ "$policy_out" == *'"permissionDecision":"deny"'* && "$policy_out" == *'jq is required'* ]]; then
  pass "policy helper fails closed without jq"
else
  fail "policy helper fails closed without jq (out=$policy_out)"
fi

telemetry_err="$({ PATH="$tmp/bin" /bin/bash -c 'source "$1"; shepherd_skip_without_jq telemetry-contract' _ "$LIB"; } 2>&1 >/dev/null || true)"
if [[ "$telemetry_err" == *'telemetry-contract skipped: jq parser unavailable'* ]]; then
  pass "telemetry helper skips with a jq diagnostic"
else
  fail "telemetry helper skips with a jq diagnostic (err=$telemetry_err)"
fi

printf '%s/%s passed\n' "$((checks - fails))" "$checks"
exit "$fails"
