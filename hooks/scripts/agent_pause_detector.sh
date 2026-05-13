#!/usr/bin/env bash
# shepherd hook — PostToolUse(Agent): capture PAUSE-FOR-DEPENDENCY reports (v5.0.9)
#
# Mechanizes pause detection from doctrines/pause-for-dependency.md §III–IV:
# fires after an Agent / Task tool call returns, scans the response for
# `Halt code: PAUSE-FOR-DEPENDENCY`, parses the structured satellite request,
# and writes it to `<namespace>/pauses/<id>.json` so the conductor reads
# structured data rather than re-parsing the agent's text.
#
# Input  (stdin): PostToolUse JSON { tool_name, tool_input, tool_response, ... }
# Output (stdout):
#   {"additionalContext":"..."}  surfaces a pause-alert + pause id to conductor
#   exit 0 silently  no pause detected.

set -euo pipefail

input=$(cat)

# Skip if not a shepherd project
[[ -f ".claude/shepherd.toml" ]] || exit 0

# Extract tool_name + response (response shape varies; try a few paths)
have_jq=0; command -v jq &>/dev/null && have_jq=1

if (( have_jq )); then
  tool=$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || true)
  response=$(printf '%s' "$input" | jq -r '
      (.tool_response.content // .tool_response.text // .tool_response // empty)
      | if type == "array" then map(.text // .) | join("\n") else . end' 2>/dev/null || true)
else
  read_args=$(printf '%s' "$input")
  tool=$(printf '%s' "$read_args" | python3 -c \
    "import json,sys; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || true)
  response=$(printf '%s' "$read_args" | python3 -c '
import json, sys
d = json.load(sys.stdin)
r = d.get("tool_response", "")
if isinstance(r, dict):
    r = r.get("content") or r.get("text") or ""
if isinstance(r, list):
    r = "\n".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in r)
print(r)
' 2>/dev/null || true)
fi

# Bail unless tool is Agent or Task
case "$tool" in Agent|Task) ;; *) exit 0 ;; esac

# Fast path: no pause marker → exit
printf '%s' "$response" | grep -qE 'Halt code:\s*PAUSE-FOR-DEPENDENCY' || exit 0

# ---------------------------------------------------------------------------
# Locate namespace and mint a sortable id
# ---------------------------------------------------------------------------
repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || repo_root=""
[[ -z "$repo_root" ]] && repo_root="$(pwd)"
ns=""
for cand in "$repo_root/.shepherd" "$repo_root/.artifacts"; do
  [[ -d "$cand" ]] && { ns="$cand"; break; }
done
[[ -z "$ns" ]] && ns="$repo_root/.shepherd"
pauses_dir="$ns/pauses"
mkdir -p "$pauses_dir"

ts=$(date +%Y%m%dT%H%M%S 2>/dev/null || echo "unknown")
rand=$(od -An -tx1 -N4 /dev/urandom 2>/dev/null | tr -d ' \n' || echo "rnd")
pause_id="${ts}-${rand}"
pause_file="$pauses_dir/${pause_id}.json"

# ---------------------------------------------------------------------------
# Field extraction — tolerant to indentation/whitespace
# ---------------------------------------------------------------------------
_extract() {
  # Match: optional markdown bullet + optional indent + label + colon + value.
  # Labels in the canonical report shape are intentionally metachar-free
  # (see doctrines/pause-for-dependency.md §II) so no escape is needed.
  printf '%s' "$response" \
    | grep -m1 -E "^[[:space:]]*([-*][[:space:]]+)?${1}[[:space:]]*:" \
    | sed -E "s/^[[:space:]]*([-*][[:space:]]+)?${1}[[:space:]]*:[[:space:]]*//; s/[[:space:]]*$//"
}

lane=$(_extract "Lane" || true)
role=$(_extract "Role" || true)
reason=$(_extract "Reason" || true)
target_path=$(_extract "target_path" || true)
file_scope=$(_extract "file_scope_proposed" || true)
work=$(_extract "work" || true)
size=$(_extract "estimated_size" || true)
new_symbol=$(_extract "new_symbol_or_path" || true)
[[ -z "$new_symbol" ]] && new_symbol=$(_extract "new_symbol" || true)
satellite_role=$(_extract "satellite_role" || true)
[[ -z "$satellite_role" ]] && satellite_role="coder"
acceptance=$(_extract "acceptance" || true)
branch=$(_extract "branch" || true)
wip_sha=$(_extract "wip_sha" || true)
resume_cond=$(_extract "Resume condition" || true)
agent_id=$(_extract "Reporter" || true)
[[ -z "$agent_id" ]] && agent_id=$(_extract "Agent ID" || true)   # back-compat

# ---------------------------------------------------------------------------
# Write the structured pause record (argv-passing — no shell interpolation in py)
# ---------------------------------------------------------------------------
python3 - "$pause_file" \
  "$pause_id" "$agent_id" "$role" "$lane" "$reason" \
  "$target_path" "$file_scope" "$work" "$size" "$new_symbol" \
  "$satellite_role" "$acceptance" "$branch" "$wip_sha" "$resume_cond" <<'PY'
import json, sys, time
(out_path, pause_id, agent_id, role, lane, reason,
 target_path, file_scope, work, size, new_symbol,
 satellite_role, acceptance, branch, wip_sha, resume_cond) = sys.argv[1:]
record = {
    "id": pause_id,
    "schema_version": 1,
    "status": "active",
    "paused_at": int(time.time()),
    "resolved_at": None,
    "satellite_sha": None,
    "agent_id":   agent_id,
    "agent_role": role,
    "lane":       lane,
    "reason":     reason,
    "satellite_request": {
        "target_path":         target_path,
        "file_scope_proposed": file_scope,
        "work":                work,
        "estimated_size":      size,
        "new_symbol_or_path":  new_symbol,
        "satellite_role":      satellite_role,
        "acceptance":          acceptance,
    },
    "lane_state": {"branch": branch, "wip_sha": wip_sha},
    "resume_condition": resume_cond,
}
with open(out_path, "w") as f:
    json.dump(record, f, indent=2)
PY

# ---------------------------------------------------------------------------
# Surface the alert (structured pointer, no re-parsing needed)
# ---------------------------------------------------------------------------
rel_path="${pause_file#$repo_root/}"
msg="[shepherd] PAUSE-FOR-DEPENDENCY captured by hook (v5.0.9)."$'\n'
msg+="  Pause id:    $pause_id"$'\n'
msg+="  Agent role:  ${role:-unknown}"$'\n'
msg+="  Lane:        ${lane:-unknown}"$'\n'
msg+="  Satellite:   ${satellite_role} (size: ${size:-?})"$'\n'
msg+="  Recorded:    $rel_path"$'\n'
msg+=""$'\n'
msg+="Next steps:"$'\n'
msg+="  1. shctx pauses show $pause_id     — inspect the structured request"$'\n'
msg+="  2. Dispatch the satellite @${satellite_role} (XS/S, isolation: worktree)"$'\n'
msg+="  3. shctx pauses resolve $pause_id --satellite-sha=<sha>"$'\n'
msg+="  4. SendMessage to ${agent_id:-the paused agent} with the resume signal"$'\n'
msg+=""$'\n'
msg+="See doctrines/pause-for-dependency.md §III–IV"

if (( have_jq )); then
  jq -n --arg ctx "$msg" '{"additionalContext": $ctx}'
else
  python3 -c "import json,sys; print(json.dumps({'additionalContext': sys.argv[1]}))" "$msg"
fi
