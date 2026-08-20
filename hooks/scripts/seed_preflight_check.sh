#!/usr/bin/env bash
# shepherd hook — PreToolUse(Write) seed pre-flight gate.
#
# Blocks a legacy *.seed.md or run-scoped runs/{run}/seed.md Write whose full
# content fails the native deterministic verifier. The payload path, not the
# hook process cwd, determines which Shepherd project and config apply.
#
# Config: [seed].seed_gate = block (default) | warn | off.
# Only a clean verifier exit 1 is policy evidence. Missing tools, malformed
# payloads, non-project paths, and verifier usage/internal errors fail open.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
shepherd_require_jq_policy || exit 0

tool=$(json_field "$input" '.tool_name')
[[ "$tool" == "Write" ]] || exit 0

file_path=$(json_field "$input" '.tool_input.file_path')
[[ -z "$file_path" ]] && file_path=$(json_field "$input" '.tool_input.path')
case "$file_path" in
  *.seed.md) ;;
  */runs/*/seed.md|runs/*/seed.md) ;;
  *) exit 0 ;;
esac

case "$file_path" in
  /*) payload_dir=$(dirname "$file_path") ;;
  *) payload_dir=$(dirname "$PWD/$file_path") ;;
esac
# A Write may target a run directory that has not been created yet. Walk to the
# nearest existing ancestor before asking Git for the primary checkout.
while [[ ! -e "$payload_dir" && "$payload_dir" != "/" && "$payload_dir" != "." ]]; do
  payload_dir=$(dirname "$payload_dir")
done
is_shepherd_project "$payload_dir" || exit 0
project_root="$(primary_worktree_root "$payload_dir" 2>/dev/null || true)"
[[ -n "$project_root" ]] || exit 0

mode="$(cfg_get seed_gate "$project_root")"; [[ -n "$mode" ]] || mode="block"
[[ "$mode" == "off" ]] && exit 0

content=$(json_field "$input" '.tool_input.content')
[[ -n "$content" ]] || exit 0
session=$(json_field "$input" '.session_id')

shepherd_bin="$(shepherd_cli 2>/dev/null || true)"
[[ -n "$shepherd_bin" ]] || exit 0

tmp="$(mktemp -t shep-seed.XXXXXX 2>/dev/null)" || exit 0
trap 'rm -f "$tmp"' EXIT
printf '%s' "$content" > "$tmp" 2>/dev/null || exit 0

rc=0
report="$(cd "$project_root" && "$shepherd_bin" seed verify "$tmp" 2>/dev/null)" || rc=$?
# Only a clean deterministic hard failure blocks. Usage/internal failures (2+)
# are infrastructure faults and retain the hook's established fail-open rule.
[[ "$rc" -eq 1 ]] || exit 0

msg="[shepherd] SEED-GATE — $file_path fails the deterministic seed pre-flight:"$'\n'
msg+="$report"$'\n\n'
msg+="Fix the HARD item(s) above, then re-write the seed."$'\n'
msg+="  - a path that will exist at Phase 0: mark it with a trailing (NEW)"$'\n'
msg+="  - lane numbering / sequencing: drop it — that is engineer territory (#67)"$'\n'
msg+="The native shepherd seed verifier is the single source of truth; see seed-template.md §Verification."

if [[ "$mode" == "warn" ]]; then
  emit_context "$msg" "seed_preflight_check" "$tool" "planter" "$session"
fi
emit_deny "$msg" "seed_preflight_check" "$tool" "planter" "$session"
