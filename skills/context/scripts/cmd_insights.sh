#!/usr/bin/env bash
# shctx insights <list|show|export|clear> [args]
#
# Registry CLI for cross-lane INSIGHTS captured by
# hooks/scripts/agent_insight_capture.sh. Per skills/adaptation/SKILL.md §INSIGHTS.
#
#   list [--sprint=BRANCH] [--kind=relocation|extension|...] [--actioned|--unactioned] [--json|--md]
#   show <id> [--json]
#   export [--sprint=BRANCH] [--md]
#       Render insights for the engineer's Phase 0 mesh row 13 consumption.
#   clear [--older-than-days=N]  Prune actioned + old insights.
#
# Insight kinds: relocation | extension | duplication | consolidation | gap | nit

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-}"; shift || true

_insights_root() {
  local root; root="$(shctx_artifacts_root)"
  echo "$root/insights"
}

usage() {
  cat <<'EOF'
shctx insights <list|show|export|clear> [args]

  list [--sprint=BRANCH] [--kind=K] [--actioned|--unactioned] [--json|--md]
      Enumerate insights. Default: all sprints, all kinds, all states.
      --sprint=BRANCH limits to one sprint dir.

  show <id> [--json]
      Render one insight record (assumes unique id across sprints).

  export [--sprint=BRANCH] [--md]
      Render as markdown for engineer mesh row 13 consumption.
      Groups by kind, omits actioned items by default.

  clear [--older-than-days=N]
      Remove actioned insights older than N days (default 60).

Schema: skills/adaptation/SKILL.md §INSIGHTS §V.
EOF
}

# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
_cmd_list() {
  local sprint="" kind="" want_actioned="" fmt="text"
  for arg in "$@"; do
    case "$arg" in
      --sprint=*)    sprint="${arg#--sprint=}" ;;
      --kind=*)      kind="${arg#--kind=}" ;;
      --actioned)    want_actioned="true" ;;
      --unactioned)  want_actioned="false" ;;
      --json)        fmt="json" ;;
      --md)          fmt="md" ;;
      -h|--help)     usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local root; root="$(_insights_root)"
  [[ -d "$root" ]] || { echo "No insights recorded yet."; exit 0; }

  # Collect candidate files
  local files=()
  if [[ -n "$sprint" ]]; then
    [[ -d "$root/$sprint" ]] || { echo "No insights for sprint $sprint."; exit 0; }
    for f in "$root/$sprint"/*.json; do [[ -e "$f" ]] && files+=("$f"); done
  else
    for f in "$root"/*/*.json; do [[ -e "$f" ]] && files+=("$f"); done
  fi
  (( ${#files[@]} > 0 )) || { echo "No insight records."; exit 0; }

  python3 - "$fmt" "$kind" "$want_actioned" "${files[@]}" <<'PY'
import json, sys
fmt, kind_filter, actioned_filter = sys.argv[1], sys.argv[2], sys.argv[3]
files = sys.argv[4:]
rows = []
for p in files:
    try:
        r = json.load(open(p))
    except Exception:
        continue
    if kind_filter and r.get("kind") != kind_filter: continue
    if actioned_filter == "true"  and not r.get("actioned"): continue
    if actioned_filter == "false" and r.get("actioned"):     continue
    rows.append(r)
rows.sort(key=lambda r: r.get("captured_at", 0), reverse=True)

if fmt == "json":
    print(json.dumps(rows, indent=2)); sys.exit(0)

if not rows:
    print("(no insights match the filters)"); sys.exit(0)

if fmt == "md":
    print("| ID | Sprint | Kind | Subject | Actioned |")
    print("|---|---|---|---|---|")
    for r in rows:
        a = "✓ " + (r.get("actioned_in") or "") if r.get("actioned") else "—"
        print("| `{}` | {} | {} | {} | {} |".format(
            r["id"], r.get("sprint",""), r.get("kind",""),
            (r.get("subject","")[:60]), a))
else:
    print("{:<25}  {:<18}  {:<14}  {:<50}  {}".format(
        "ID","SPRINT","KIND","SUBJECT","ACTIONED"))
    print("-" * 130)
    for r in rows:
        a = "yes ({})".format(r.get("actioned_in") or "") if r.get("actioned") else "no"
        print("{:<25}  {:<18}  {:<14}  {:<50}  {}".format(
            r["id"][:25], (r.get("sprint","") or "")[:18],
            r.get("kind",""), (r.get("subject","") or "")[:50], a))
PY
}

# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------
_cmd_show() {
  local id="${1:-}"; shift || true
  [[ -n "$id" ]] || { echo "ERROR: usage: shctx insights show <id>" >&2; exit 1; }
  local fmt="text"
  for arg in "$@"; do
    case "$arg" in --json) fmt="json" ;; esac
  done

  local root; root="$(_insights_root)"
  local match=""
  for f in "$root"/*/"${id}.json"; do
    [[ -f "$f" ]] && { match="$f"; break; }
  done
  [[ -n "$match" ]] || { echo "ERROR: insight $id not found" >&2; exit 2; }

  if [[ "$fmt" == "json" ]]; then cat "$match"; return; fi

  python3 - "$match" <<'PY'
import json, sys, datetime
r = json.load(open(sys.argv[1]))
ts = datetime.datetime.fromtimestamp(r.get("captured_at",0)).isoformat(timespec="seconds")
print("Insight:      " + r.get("id","?"))
print("Sprint:       " + (r.get("sprint") or "?"))
print("Captured at:  " + ts)
print("Kind:         " + r.get("kind","?"))
print("Actioned:     " + ("yes (in " + (r.get("actioned_in") or "?") + ")" if r.get("actioned") else "no"))
print()
print("Subject:")
print("  " + (r.get("subject") or ""))
print("Observation:")
print("  " + (r.get("observation") or ""))
print("Rationale:")
print("  " + (r.get("rationale") or ""))
PY
}

# ---------------------------------------------------------------------------
# export — markdown grouped by kind, intended for engineer mesh row 13
# ---------------------------------------------------------------------------
_cmd_export() {
  local sprint="" fmt="md"
  for arg in "$@"; do
    case "$arg" in
      --sprint=*) sprint="${arg#--sprint=}" ;;
      --md)       fmt="md" ;;
      -h|--help)  usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local root; root="$(_insights_root)"
  [[ -d "$root" ]] || { echo "(no insights)"; exit 0; }

  local files=()
  if [[ -n "$sprint" ]]; then
    [[ -d "$root/$sprint" ]] || { echo "(no insights for $sprint)"; exit 0; }
    for f in "$root/$sprint"/*.json; do [[ -e "$f" ]] && files+=("$f"); done
  else
    for f in "$root"/*/*.json; do [[ -e "$f" ]] && files+=("$f"); done
  fi
  (( ${#files[@]} > 0 )) || { echo "(no insight records)"; exit 0; }

  python3 - "$sprint" "${files[@]}" <<'PY'
import json, sys, collections
sprint, files = sys.argv[1], sys.argv[2:]
groups = collections.defaultdict(list)
for p in files:
    try: r = json.load(open(p))
    except Exception: continue
    if r.get("actioned"): continue
    groups[r.get("kind","gap")].append(r)

label = sprint if sprint else "all sprints"
print("## Cross-lane insights — " + label)
print()
order = ["relocation","extension","duplication","consolidation","gap","nit"]
seen_any = False
for k in order:
    items = groups.get(k, [])
    if not items: continue
    seen_any = True
    print(f"### {k} ({len(items)})")
    print()
    for r in sorted(items, key=lambda x: x.get("captured_at",0)):
        print(f"- **{r.get('subject','?')}**  _(sprint: {r.get('sprint','?')}, id: `{r['id']}`)_")
        if r.get("observation"): print(f"  - observation: {r['observation']}")
        if r.get("rationale"):   print(f"  - rationale:   {r['rationale']}")
    print()
if not seen_any:
    print("_(no unactioned insights)_")
PY
}

# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------
_cmd_clear() {
  local days=60
  for arg in "$@"; do
    case "$arg" in
      --older-than-days=*) days="${arg#--older-than-days=}" ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local root; root="$(_insights_root)"
  [[ -d "$root" ]] || { echo "(nothing to clear)"; exit 0; }

  local now=$(shctx_now)
  local cutoff=$(( now - days * 86400 ))
  local removed=0
  for f in "$root"/*/*.json; do
    [[ -e "$f" ]] || continue
    local keep
    keep=$(python3 -c '
import json, sys
r = json.load(open(sys.argv[1]))
cutoff = int(sys.argv[2])
# Keep if NOT actioned OR captured_at >= cutoff
print("1" if (not r.get("actioned") or (r.get("captured_at") or 0) >= cutoff) else "0")
' "$f" "$cutoff")
    if [[ "$keep" == "0" ]]; then
      rm -f "$f"
      removed=$(( removed + 1 ))
    fi
  done
  echo "Removed $removed actioned insight(s) older than $days days."
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
case "$sub" in
  list)        _cmd_list "$@" ;;
  show)        _cmd_show "$@" ;;
  export)      _cmd_export "$@" ;;
  clear)       _cmd_clear "$@" ;;
  ""|-h|--help) usage; exit 0 ;;
  *) echo "ERROR: unknown subcommand: $sub" >&2; usage >&2; exit 1 ;;
esac
