#!/usr/bin/env bash
# shepherd hook — PostToolUse(Agent|Task): capture cross-lane INSIGHTS (v5.0.9)
#
# Per doctrines/flock-cohesion.md §V. After an Agent/Task tool call returns,
# scan the response for an optional `## INSIGHTS` block and write each entry
# to `<namespace>/insights/<sprint>/<id>.json` for later consumption by the
# engineer at Phase 0 mesh row 13.
#
# This is the OPTIONAL cousin of agent_pause_detector.sh. Agents are NOT
# required to emit insights; many reports won't have any. Silent when no
# INSIGHTS block is present.
#
# Insight kinds (canonical taxonomy):
#   relocation | extension | duplication | consolidation | gap | nit
#
# Input  (stdin): PostToolUse JSON
# Output (stdout):
#   {"additionalContext":"..."}   counts insights captured + path hint
#   exit 0 silently               no INSIGHTS block

set -euo pipefail
input=$(cat)
[[ -f ".claude/shepherd.toml" ]] || exit 0

have_jq=0; command -v jq &>/dev/null && have_jq=1

# Extract tool_name and response text
if (( have_jq )); then
  tool=$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || true)
  response=$(printf '%s' "$input" | jq -r '
      (.tool_response.content // .tool_response.text // .tool_response // empty)
      | if type == "array" then map(.text // .) | join("\n") else . end' 2>/dev/null || true)
else
  tool=$(printf '%s' "$input" | python3 -c \
    "import json,sys; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || true)
  response=$(printf '%s' "$input" | python3 -c '
import json,sys
d=json.load(sys.stdin); r=d.get("tool_response","")
if isinstance(r,dict): r=r.get("content") or r.get("text") or ""
if isinstance(r,list): r="\n".join(x.get("text","") if isinstance(x,dict) else str(x) for x in r)
print(r)
' 2>/dev/null || true)
fi

case "$tool" in Agent|Task) ;; *) exit 0 ;; esac

# Fast path
printf '%s' "$response" | grep -qE '^[[:space:]]*##[[:space:]]+INSIGHTS\b' || exit 0

# Locate namespace + sprint
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
ns=""
for cand in "$repo_root/.shepherd" "$repo_root/.artifacts"; do
  [[ -d "$cand" ]] && { ns="$cand"; break; }
done
[[ -z "$ns" ]] && ns="$repo_root/.shepherd"

sprint=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || true
[[ -z "$sprint" ]] && sprint="unknown"
insights_dir="$ns/insights/$sprint"
mkdir -p "$insights_dir"

# Stage the response in a temp file (avoids shell→python interpolation hazards)
tmp=$(mktemp -t shepherd-insights.XXXXXX)
trap 'rm -f "$tmp"' EXIT
printf '%s' "$response" > "$tmp"

# Python does the parsing + per-insight JSON writes. Stdout is the captured list.
captured_json=$(python3 - "$tmp" "$insights_dir" "$sprint" <<'PY'
import json, os, re, sys, time, uuid

resp_path, insights_dir, sprint = sys.argv[1], sys.argv[2], sys.argv[3]
with open(resp_path) as f:
    response = f.read()

m = re.search(r"^##\s+INSIGHTS\b(.*?)(?=^##\s+|\Z)", response, re.MULTILINE | re.DOTALL)
if not m:
    print(json.dumps([])); sys.exit(0)
block = m.group(1)

# Split into entries by `- kind:` marker.
entries = re.split(r"(?m)^\s*-\s+kind\s*:", block)
captured = []
valid_kinds = {"relocation","extension","duplication","consolidation","gap","nit"}

for chunk in entries[1:]:
    raw = "kind:" + chunk
    fields = {}
    current_key = None
    for line in raw.splitlines():
        # Top-level key:value line (low indent)
        m2 = re.match(r"^\s{0,4}([a-z_]+)\s*:\s*(.*?)\s*$", line)
        if m2:
            current_key = m2.group(1)
            fields[current_key] = m2.group(2)
            continue
        # Continuation: indented line → append to current key
        if current_key and line.strip() and line.startswith(("    ", "\t")):
            fields[current_key] = (fields.get(current_key, "") + " " + line.strip()).strip()
    kind = (fields.get("kind") or "").lower().strip()
    if kind not in valid_kinds:
        continue
    iid = "{}-{}".format(time.strftime("%Y%m%dT%H%M%S"), uuid.uuid4().hex[:6])
    record = {
        "id": iid,
        "schema_version": 1,
        "sprint": sprint,
        "captured_at": int(time.time()),
        "kind":        kind,
        "subject":     fields.get("subject", "").strip(),
        "observation": fields.get("observation", "").strip(),
        "rationale":   fields.get("rationale", "").strip(),
        "actioned":    False,
        "actioned_in": None,
    }
    with open(os.path.join(insights_dir, iid + ".json"), "w") as f:
        json.dump(record, f, indent=2)
    captured.append({"id": iid, "kind": kind})

print(json.dumps(captured))
PY
)

count=$(printf '%s' "$captured_json" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
[[ "$count" -gt 0 ]] || exit 0

msg="[shepherd] captured ${count} cross-lane INSIGHT(s) (v5.0.9, flock-cohesion.md)."$'\n'
msg+="  Sprint:      $sprint"$'\n'
msg+="  Stored at:   ${insights_dir#$repo_root/}/"$'\n'
msg+="  Browse with: shctx insights list --sprint=$sprint"$'\n'
msg+=""$'\n'
msg+="Insights are consumed by @engineer at Phase 0 mesh row 13 of the NEXT sprint."

if (( have_jq )); then
  jq -n --arg ctx "$msg" '{"additionalContext": $ctx}'
else
  python3 -c "import json,sys; print(json.dumps({'additionalContext': sys.argv[1]}))" "$msg"
fi
