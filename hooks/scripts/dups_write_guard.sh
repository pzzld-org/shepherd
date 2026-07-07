#!/usr/bin/env bash
# shepherd hook — PreToolUse(Write|Edit) field-shape dedup gate (v6.1.8, #157).
#
# The shape-shaped sibling of dedup_write_guard.sh. That hook blocks a NEW
# public symbol that reuses an existing NAME. This one catches the harder case:
# a coder about to author a struct/enum whose FIELD SHAPE matches an existing
# type under a DIFFERENT name (the rename-to-evade-dedup shadow). It lets a
# subagent reuse a pre-built struct without having to remember its name — the
# match is surfaced at authoring time.
#
# Delegates the parse + similarity to `shctx dups check` (which reads the
# persisted index_struct_shapes corpus). Fails OPEN at every step: non-coder
# role, non-rust file, missing python3/shctx, empty corpus, or any error →
# pass silently. It can only ever block when a real shape match exists.
#
# Config: [dups].dups_hook = off | warn (default) | block.
#   off   — never runs.
#   warn  — emits additionalContext ("0.85-similar to X — reuse it?"); never blocks.
#   block — denies the write when a match ≥ block-threshold exists; warns otherwise.
#
# Input  (stdin): PreToolUse JSON { tool_name, tool_input.{file_path, content|new_string}, ... }
# Output (stdout): {"permissionDecision":"deny",...} | {"additionalContext":...} | nothing.

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

# Only police @coder (matches dedup_write_guard).
[[ "$role" != "coder" ]] && pass_silent "dups_write_guard" "$tool" "$role" "$session"

# Mode gate.
mode="$(cfg_get dups_hook)"; [[ -n "$mode" ]] || mode="warn"
[[ "$mode" == "off" ]] && pass_silent "dups_write_guard" "$tool" "$role" "$session"

file_path=$(json_field "$input" '.tool_input.file_path')
[[ -z "$file_path" ]] && file_path=$(json_field "$input" '.tool_input.path')
[[ -z "$file_path" ]] && pass_silent "dups_write_guard" "$tool" "$role" "$session"
case "$file_path" in *.rs) ;; *) pass_silent "dups_write_guard" "$tool" "$role" "$session" ;; esac

if [[ "$tool" == "Write" ]]; then
  content=$(json_field "$input" '.tool_input.content')
else
  content=$(json_field "$input" '.tool_input.new_string')
fi
[[ -z "$content" ]] && pass_silent "dups_write_guard" "$tool" "$role" "$session"

# Locate shctx relative to the plugin root (hooks/scripts/ → ../../skills/...).
plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$HERE/../.." && pwd)}"
shctx="$plugin_root/skills/context/scripts/shctx"
[[ -x "$shctx" || -f "$shctx" ]] || pass_silent "dups_write_guard" "$tool" "$role" "$session"
command -v python3 >/dev/null 2>&1 || pass_silent "dups_write_guard" "$tool" "$role" "$session"

# Ask the engine. Fail open on any error.
result=$(printf '%s' "$content" | bash "$shctx" dups check --stdin --as "$file_path" --json 2>/dev/null || true)
[[ -z "$result" ]] && pass_silent "dups_write_guard" "$tool" "$role" "$session"

# Parse .block + render the hit lines (jq, python3 fallback).
if command -v jq >/dev/null 2>&1; then
  blocked=$(printf '%s' "$result" | jq -r '.block // false' 2>/dev/null || echo false)
  hitcount=$(printf '%s' "$result" | jq -r '[.candidates[]?.hits[]?] | length' 2>/dev/null || echo 0)
  hits=$(printf '%s' "$result" | jq -r '
    .candidates[]? as $c
    | "  " + $c.name + " { " + ($c.field_names | join(", ")) + " }",
      ($c.hits[]? | "    is " + (.similarity|tostring) + "-similar to " + .package + "::" + .name
                  + " (" + .file + ":" + (.line|tostring) + ") — reuse it?")' 2>/dev/null || true)
else
  blocked=$(printf '%s' "$result" | python3 -c 'import json,sys;print(str(json.load(sys.stdin).get("block",False)).lower())' 2>/dev/null || echo false)
  hitcount=$(printf '%s' "$result" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(sum(len(c.get("hits",[])) for c in d.get("candidates",[])))' 2>/dev/null || echo 0)
  hits=$(printf '%s' "$result" | python3 -c '
import json,sys
d=json.load(sys.stdin)
for c in d.get("candidates",[]):
    print("  "+c["name"]+" { "+", ".join(c["field_names"])+" }")
    for h in c.get("hits",[]):
        print("    is %s-similar to %s::%s (%s:%s) — reuse it?"%(h["similarity"],h["package"],h["name"],h["file"],h["line"]))' 2>/dev/null || true)
fi

# No hits → pass.
[[ "${hitcount:-0}" -gt 0 ]] 2>/dev/null || pass_silent "dups_write_guard" "$tool" "$role" "$session"

if [[ "$mode" == "block" && "$blocked" == "true" ]]; then
  msg="[shepherd] SHAPE-DEDUP BLOCKED — @coder Write would create a field-shape duplicate of an existing type."$'\n'
  msg+="  Target file: $file_path"$'\n\n'
  msg+="$hits"$'\n\n'
  msg+="Per skills/context/SKILL.md §Dedup + skills/shepherd/references/pipeline.md §DEDUP-GATE:"$'\n'
  msg+="  - REUSE the existing type (import it instead of restating its fields)"$'\n'
  msg+="  - EXTEND it, or wire to the suggested canonical home"$'\n'
  msg+="  - if the twin is intentional, allow-list it: shctx dups registry allow <A> <B>"$'\n'
  msg+="  - or include a JUSTIFY-NEW block in your CODER REPORT"$'\n\n'
  msg+="A renamed shadow compiles green — that is exactly why this gate exists."
  emit_deny "$msg" "dups_write_guard" "$tool" "$role" "$session"
fi

# warn mode (or block-mode with only sub-threshold hits): surface, don't block.
wmsg="[shepherd] shape-dedup: this struct/enum is shape-similar to existing type(s) — reuse before duplicating:"$'\n'
wmsg+="$hits"$'\n'
wmsg+="(allow-list an intentional twin: shctx dups registry allow <A> <B>)"
emit_context "$wmsg" "dups_write_guard" "$tool" "$role" "$session"
