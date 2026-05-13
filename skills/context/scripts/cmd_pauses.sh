#!/usr/bin/env bash
# shctx pauses <list|show|resolve|clear> [args]
#
# Registry CLI for PAUSE-FOR-DEPENDENCY records written by
# hooks/scripts/agent_pause_detector.sh. Each pause lives at
# `<namespace>/pauses/<id>.json`. Schema: doctrines/pause-for-dependency.md §IV.
#
#   list [--status=active|resolved|all] [--json|--md]
#   show <id> [--json]
#   resolve <id> --satellite-sha=<sha> [--note=<text>]
#   clear [--older-than-days=N]   prune resolved pauses older than N (default 30)
#
# Exit codes: 0=ok, 1=usage, 2=not-found

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-}"; shift || true

_pauses_dir() {
  local root; root="$(shctx_artifacts_root)"
  echo "$root/pauses"
}

usage() {
  cat <<'EOF'
shctx pauses <list|show|resolve|clear> [args]

  list [--status=active|resolved|all] [--json|--md]
      Enumerate captured pauses. Default: --status=active.

  show <id> [--json]
      Dump one pause record. Default: rendered fields; --json for raw.

  resolve <id> --satellite-sha=<sha> [--note=<text>]
      Mark a pause as resolved after the satellite agent lands.
      Records satellite_sha + resolved_at + optional resolution note.

  clear [--older-than-days=N]
      Remove resolved pauses older than N days (default 30). Active
      pauses are never removed.

The pause registry is populated automatically by the
PostToolUse(Agent) hook hooks/scripts/agent_pause_detector.sh.
See doctrines/pause-for-dependency.md.
EOF
}

# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
_cmd_list() {
  local status_filter="active" fmt="text"
  for arg in "$@"; do
    case "$arg" in
      --status=*) status_filter="${arg#--status=}" ;;
      --json)     fmt="json" ;;
      --md)       fmt="md" ;;
      -h|--help)  usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local dir; dir="$(_pauses_dir)"
  [[ -d "$dir" ]] || { echo "No pauses recorded yet ($dir does not exist)."; exit 0; }

  local matches=()
  for f in "$dir"/*.json; do
    [[ -e "$f" ]] || continue
    if [[ "$status_filter" == "all" ]]; then
      matches+=("$f")
    else
      local st
      st=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('status',''))" "$f" 2>/dev/null || echo "")
      [[ "$st" == "$status_filter" ]] && matches+=("$f")
    fi
  done

  if (( ${#matches[@]} == 0 )); then
    echo "No pauses match --status=$status_filter."
    exit 0
  fi

  if [[ "$fmt" == "json" ]]; then
    python3 -c '
import json, sys
records = []
for path in sys.argv[1:]:
    with open(path) as f:
        records.append(json.load(f))
print(json.dumps(records, indent=2))
' "${matches[@]}"
    return
  fi

  if [[ "$fmt" == "md" ]]; then
    echo "| ID | Status | Role | Lane | Symbol/Path | Size | Reporter |"
    echo "|---|---|---|---|---|---|---|"
  else
    printf '%-30s  %-10s  %-7s  %-12s  %-30s  %-4s  %s\n' \
      "ID" "STATUS" "ROLE" "LANE" "SYMBOL/PATH" "SIZE" "REPORTER"
    printf '%-30s  %-10s  %-7s  %-12s  %-30s  %-4s  %s\n' \
      "------------------------------" "----------" "-------" "------------" \
      "------------------------------" "----" "--------"
  fi

  for f in "${matches[@]}"; do
    python3 -c '
import json, sys, os
r = json.load(open(sys.argv[1]))
sr = r.get("satellite_request", {})
fmt = sys.argv[2]
fields = [
    r.get("id",""),
    r.get("status",""),
    (r.get("agent_role") or "?"),
    (r.get("lane") or "?"),
    (sr.get("new_symbol_or_path") or "?")[:30],
    (sr.get("estimated_size") or "?"),
    (r.get("agent_id") or "?"),
]
if fmt == "md":
    print("| " + " | ".join(fields) + " |")
else:
    print("{:<30}  {:<10}  {:<7}  {:<12}  {:<30}  {:<4}  {}".format(*fields))
' "$f" "$fmt"
  done
}

# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------
_cmd_show() {
  local id="${1:-}"; shift || true
  [[ -n "$id" ]] || { echo "ERROR: usage: shctx pauses show <id>" >&2; exit 1; }
  local fmt="text"
  for arg in "$@"; do
    case "$arg" in --json) fmt="json" ;; esac
  done

  local dir; dir="$(_pauses_dir)"
  local f="$dir/${id}.json"
  [[ -f "$f" ]] || { echo "ERROR: pause $id not found at $f" >&2; exit 2; }

  if [[ "$fmt" == "json" ]]; then
    cat "$f"
    return
  fi

  python3 - "$f" <<'PY'
import json, sys, datetime
r = json.load(open(sys.argv[1]))
def ts(e):
    if not e: return "—"
    return datetime.datetime.fromtimestamp(e).isoformat(timespec="seconds")

def row(k, v):
    print("  {:<14}: {}".format(k, v if v not in (None, "") else "—"))

print("Pause:        " + r.get("id","?"))
print("Status:       " + r.get("status","?"))
print("Paused at:    " + ts(r.get("paused_at")))
print("Resolved at:  " + ts(r.get("resolved_at")))
print("Agent id:     " + (r.get("agent_id") or "?"))
print("Agent role:   " + (r.get("agent_role") or "?"))
print("Lane:         " + (r.get("lane") or "?"))
print("Reason:       " + (r.get("reason") or "?"))
print()
print("Satellite request:")
for k, v in (r.get("satellite_request") or {}).items():
    print("  {:<22}: {}".format(k, v))
print()
print("Lane state at pause:")
for k, v in (r.get("lane_state") or {}).items():
    print("  {:<8}: {}".format(k, v))
print()
print("Resume condition: " + (r.get("resume_condition") or "—"))
print("Satellite SHA:    " + (r.get("satellite_sha") or "—"))
note = r.get("resolution_note")
if note:
    print("Resolution note:  " + note)
PY
}

# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------
_cmd_resolve() {
  local id="${1:-}"; shift || true
  [[ -n "$id" ]] || { echo "ERROR: usage: shctx pauses resolve <id> --satellite-sha=<sha>" >&2; exit 1; }

  local sha="" note=""
  for arg in "$@"; do
    case "$arg" in
      --satellite-sha=*) sha="${arg#--satellite-sha=}" ;;
      --note=*)          note="${arg#--note=}" ;;
      -h|--help)         usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done
  [[ -n "$sha" ]] || { echo "ERROR: --satellite-sha=<sha> is required" >&2; exit 1; }

  local dir; dir="$(_pauses_dir)"
  local f="$dir/${id}.json"
  [[ -f "$f" ]] || { echo "ERROR: pause $id not found at $f" >&2; exit 2; }

  python3 - "$f" "$sha" "$note" <<'PY'
import json, sys, time
path, sha, note = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as fh:
    r = json.load(fh)
if r.get("status") == "resolved":
    print(f"NOTE: pause {r['id']} was already resolved at {r.get('resolved_at')}", file=sys.stderr)
r["status"] = "resolved"
r["resolved_at"] = int(time.time())
r["satellite_sha"] = sha
if note:
    r["resolution_note"] = note
with open(path, "w") as fh:
    json.dump(r, fh, indent=2)
print(f"resolved: {r['id']}  satellite={sha[:12]}")
PY
}

# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------
_cmd_clear() {
  local days=30
  for arg in "$@"; do
    case "$arg" in
      --older-than-days=*) days="${arg#--older-than-days=}" ;;
      -h|--help)           usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local dir; dir="$(_pauses_dir)"
  [[ -d "$dir" ]] || { echo "Nothing to clear ($dir does not exist)."; exit 0; }

  local now removed=0; now=$(shctx_now)
  local cutoff=$(( now - days * 86400 ))

  for f in "$dir"/*.json; do
    [[ -e "$f" ]] || continue
    local should_remove
    should_remove=$(python3 -c '
import json, sys
r = json.load(open(sys.argv[1]))
cutoff = int(sys.argv[2])
print("1" if (r.get("status") == "resolved" and (r.get("resolved_at") or 0) < cutoff) else "0")
' "$f" "$cutoff")
    if [[ "$should_remove" == "1" ]]; then
      rm -f "$f"
      removed=$(( removed + 1 ))
    fi
  done
  echo "Removed $removed resolved pause(s) older than $days days."
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
case "$sub" in
  list)        _cmd_list "$@" ;;
  show)        _cmd_show "$@" ;;
  resolve)     _cmd_resolve "$@" ;;
  clear)       _cmd_clear "$@" ;;
  ""|-h|--help) usage; exit 0 ;;
  *) echo "ERROR: unknown subcommand: $sub" >&2; usage >&2; exit 1 ;;
esac
