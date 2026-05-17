#!/usr/bin/env bash
# shepherd hook — PreToolUse(Write|Edit) dedup gate (v5.1.2)
#
# Final-line defense against duplicate symbol creation. Inspects pending
# Write/Edit content for new public symbol declarations; if the same
# identifier already exists in the workspace at another location, BLOCK
# the write with a DEDUP-HIT message citing the existing location.
#
# Only fires for @coder role (other roles can write architecturally).
# The conductor's pre-dispatch DEDUP-GATE remains the primary check;
# this hook catches what slipped through.
#
# Input  (stdin): PreToolUse JSON { tool_name, tool_input.{file_path, content}, ... }
# Output (stdout):
#   {"permissionDecision":"deny","message":"DEDUP-HIT: ..."}    — when a hit
#   exit 0 silently otherwise.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

tool=$(json_field "$input" '.tool_name')
case "$tool" in Write|Edit) ;; *) exit 0 ;; esac

tool_use_id=$(json_field "$input" '.tool_use_id')
session=$(json_field "$input" '.session_id')
sprint=$(current_sprint)
role=$(current_role "$tool_use_id" "$sprint")

# Only police @coder. Engineer/critic/auditor/discovery/worker/conductor pass.
[[ "$role" != "coder" ]] && pass_silent "dedup_write_guard" "$tool" "$role" "$session"

file_path=$(json_field "$input" '.tool_input.file_path')
[[ -z "$file_path" ]] && file_path=$(json_field "$input" '.tool_input.path')
[[ -z "$file_path" ]] && pass_silent "dedup_write_guard" "$tool" "$role" "$session"

# Extract pending content
if [[ "$tool" == "Write" ]]; then
  content=$(json_field "$input" '.tool_input.content')
else
  # Edit — check the new_string for new symbol introductions
  content=$(json_field "$input" '.tool_input.new_string')
fi
[[ -z "$content" ]] && pass_silent "dedup_write_guard" "$tool" "$role" "$session"

# Determine language by extension
case "$file_path" in
  *.rs)              lang="rust"     ;;
  *.py)              lang="python"   ;;
  *.ts|*.tsx)        lang="typescript" ;;
  *.js|*.jsx|*.mjs)  lang="javascript" ;;
  *.go)              lang="go"       ;;
  *)                 pass_silent "dedup_write_guard" "$tool" "$role" "$session" ;;
esac

# Per-language regex for new PUBLIC symbol introductions
case "$lang" in
  rust)
    # pub fn / pub struct / pub trait / pub enum / pub const / pub static / pub type
    patterns='^[[:space:]]*pub(\([a-z_]+\))?[[:space:]]+(fn|struct|trait|enum|const|static|type|union)[[:space:]]+([a-zA-Z_][a-zA-Z0-9_]*)'
    ;;
  python)
    # def / class / module-level uppercased name
    patterns='^(def|class)[[:space:]]+([a-zA-Z_][a-zA-Z0-9_]*)'
    ;;
  typescript|javascript)
    # export function / export class / export interface / export type / export const
    patterns='^export[[:space:]]+(async[[:space:]]+)?(function|class|interface|type|const|enum)[[:space:]]+([a-zA-Z_][a-zA-Z0-9_]*)'
    ;;
  go)
    # func / type / var / const at top level, uppercase-leading (exported)
    patterns='^(func|type|var|const)[[:space:]]+([A-Z][a-zA-Z0-9_]*)'
    ;;
esac

# Extract candidate new symbols from content
new_symbols=$(printf '%s' "$content" | grep -oE "$patterns" 2>/dev/null | awk '{print $NF}' | sort -u || true)
[[ -z "$new_symbols" ]] && pass_silent "dedup_write_guard" "$tool" "$role" "$session"

# Resolve abs path so we can exclude the target file from the hit check
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
abs_target=$(cd "$(dirname "$file_path")" 2>/dev/null && pwd)/$(basename "$file_path") || abs_target="$file_path"

# Build the pre-existing search patterns per language
hit_lines=""
hit_count=0
while IFS= read -r sym; do
  [[ -z "$sym" ]] && continue
  # Search the workspace (excluding the target file itself + transient dirs)
  case "$lang" in
    rust)        search_pat="^[[:space:]]*pub(\([a-z_]+\))?[[:space:]]+(fn|struct|trait|enum|const|static|type|union)[[:space:]]+${sym}\b" ;;
    python)      search_pat="^(def|class)[[:space:]]+${sym}\b" ;;
    typescript|javascript) search_pat="^export[[:space:]]+(async[[:space:]]+)?(function|class|interface|type|const|enum)[[:space:]]+${sym}\b" ;;
    go)          search_pat="^(func|type|var|const)[[:space:]]+${sym}\b" ;;
  esac

  if command -v rg &>/dev/null; then
    hits=$(rg -n --no-heading -g "*.${file_path##*.}" --glob '!target' --glob '!node_modules' --glob '!.shepherd' --glob '!.artifacts/logs' "$search_pat" "$repo_root" 2>/dev/null | grep -v "^${abs_target}:" | head -3 || true)
  else
    hits=$(grep -rn -E "$search_pat" --include="*.${file_path##*.}" "$repo_root" 2>/dev/null | grep -v "^${abs_target}:" | head -3 || true)
  fi

  if [[ -n "$hits" ]]; then
    hit_count=$((hit_count + 1))
    hit_lines+="  '$sym' already exists:"$'\n'
    while IFS= read -r line; do
      hit_lines+="    ${line}"$'\n'
    done <<<"$hits"
  fi
done <<<"$new_symbols"

# No hits — pass
if [[ $hit_count -eq 0 ]]; then
  pass_silent "dedup_write_guard" "$tool" "$role" "$session"
fi

# At least one hit — BLOCK
msg="[shepherd] DEDUP-HIT BLOCKED — @coder Write would create duplicate(s) of existing symbol(s)."$'\n'
msg+="  Target file:  $file_path"$'\n'
msg+="  Language:     $lang"$'\n'
msg+=""$'\n'
msg+="$hit_lines"
msg+=""$'\n'
msg+="Per doctrines/agent-excellence.md + zero-duplicate-tolerance.md:"$'\n'
msg+="  - REUSE the existing symbol (import + delegate)"$'\n'
msg+="  - EXTEND it (add method/variant; preserve callers)"$'\n'
msg+="  - or include a JUSTIFY-NEW block in your CODER REPORT explaining why a new symbol is required"$'\n'
msg+=""$'\n'
msg+="Lazy duplication is more work, not less — refuse it."

log_event "dedup_write_guard" "deny" "$tool" "$role" "$session" \
  "$(emit_json_obj symbols "$new_symbols" hit_count "$hit_count" file_path "$file_path")"
emit_json_obj permissionDecision "deny" message "$msg"
exit 0
