#!/usr/bin/env bash
# shepherd hook — PreToolUse(Write) seed pre-flight gate (v6.2.1).
#
# Blocks a *.seed.md Write whose content fails the deterministic seed gate
# (`shctx seed verify`). The framework's highest-precision artifact gets a
# structural floor at authorship time instead of prose self-policing — a
# hallucinated file_scope path, an oversized footprint, a leftover TODO, or
# prescriptive Lane-N numbering can no longer reach a multi-lane spawn.
#
# Scope: Write only. A fresh seed is authored with Write (full content in
# tool_input.content); Edit refinements are incremental fragments and are left
# to the explicit `shctx seed verify` / SEED-GATE node. One focused hook.
#
# Config: [seed].seed_gate = block (default) | warn | off.
#   off   — never runs.
#   warn  — emits additionalContext on a hard failure; never blocks.
#   block — denies the Write on a hard failure (verify exit 1).
#
# Fails OPEN at every step (non-shepherd repo, non-seed path, no content,
# missing shctx, any internal/verify error) — only ever blocks on a CLEAN
# verify exit 1. Never blocks authorship on a tooling hiccup.
#
# Input  (stdin): PreToolUse JSON { tool_name, tool_input.{file_path, content}, ... }
# Output (stdout): {"permissionDecision":"deny",...} | {"additionalContext":...} | nothing.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

tool=$(json_field "$input" '.tool_name')
[[ "$tool" == "Write" ]] || exit 0

file_path=$(json_field "$input" '.tool_input.file_path')
[[ -z "$file_path" ]] && file_path=$(json_field "$input" '.tool_input.path')
# Two naming shapes are gated (v6.4.1 — the rename hazard, res_12 §3): the
# legacy `{slug}.seed.md` suffix AND the run-scoped `runs/{run}/seed.md`
# (path-segment match on `runs/<run>/` + basename `seed.md`, so moving the
# seed into the run dir cannot silently disable this gate).
case "$file_path" in
  *.seed.md) ;;
  */runs/*/seed.md|runs/*/seed.md) ;;
  *) exit 0 ;;
esac

mode="$(cfg_get seed_gate)"; [[ -n "$mode" ]] || mode="block"
[[ "$mode" == "off" ]] && exit 0

content=$(json_field "$input" '.tool_input.content')
[[ -n "$content" ]] || exit 0

session=$(json_field "$input" '.session_id')

plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$HERE/../.." && pwd)}"
shctx="$plugin_root/bin/shepherd"
[[ -f "$shctx" ]] || exit 0

tmp="$(mktemp -t shep-seed.XXXXXX 2>/dev/null)" || exit 0
trap 'rm -f "$tmp"' EXIT
printf '%s' "$content" > "$tmp" 2>/dev/null || exit 0

rc=0
report="$(bash "$shctx" seed verify "$tmp" 2>/dev/null)" || rc=$?
# Only a CLEAN hard-failure (exit 1) blocks. Usage/internal errors (2+) fail open.
[[ "$rc" -eq 1 ]] || exit 0

msg="[shepherd] SEED-GATE — $file_path fails the deterministic seed pre-flight:"$'\n'
msg+="$report"$'\n\n'
msg+="Fix the HARD item(s) above, then re-write the seed."$'\n'
msg+="  - a path that will exist at Phase 0: mark it with a trailing (NEW)"$'\n'
msg+="  - lane numbering / sequencing: drop it — that is engineer territory (#67)"$'\n'
msg+="The gate is the single source of truth (services/cli/shepherd_cli/commands/seed.py; see seed-template.md §Verification)."

if [[ "$mode" == "warn" ]]; then
  emit_context "$msg" "seed_preflight_check" "$tool" "planter" "$session"
fi
emit_deny "$msg" "seed_preflight_check" "$tool" "planter" "$session"
