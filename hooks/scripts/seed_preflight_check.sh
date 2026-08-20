#!/usr/bin/env bash
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
