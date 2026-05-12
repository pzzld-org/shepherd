#!/usr/bin/env bash
# shctx doctor — diagnostic / pre-flight check (v5.0.4)
#
# Verifies the local environment + project state is ready for shepherd
# operations. Emits actionable fix lines for each failure.
#
# Exits 0 if all checks pass, 1 if any FAIL, 2 if only WARNs.
#
# Usage:
#   shctx doctor              # full health check
#   shctx doctor --json       # machine-readable output

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

fmt="md"
for arg in "$@"; do
  case "$arg" in
    --json) fmt="json" ;;
    --md)   fmt="md" ;;
    -h|--help)
      cat <<'EOF'
shctx doctor [--md|--json]

Pre-flight diagnostic for the shepherd context registry. Checks:
  - required binaries (sqlite3, jq, gh, git)
  - namespace dir + project.json present
  - schema version + pending migrations
  - lock state (held / stale / free)
  - refresh staleness per zone (symbols / github / artifacts)
  - shepherd.toml locatable

Exit codes: 0 = ok, 1 = at least one FAIL, 2 = warnings only.
EOF
      exit 0 ;;
    *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
  esac
done

results=()  # each: status|category|name|message|fix
add() { results+=("$1|$2|$3|$4|$5"); }

# --- 1. binaries ---
for bin in sqlite3 jq git; do
  if command -v "$bin" >/dev/null 2>&1; then
    add ok bin "$bin" "$($bin --version 2>/dev/null | head -1)" ""
  else
    add fail bin "$bin" "not installed" "install $bin (brew install $bin / apt install $bin)"
  fi
done
if command -v gh >/dev/null 2>&1; then
  add ok bin gh "$(gh --version 2>/dev/null | head -1)" ""
else
  add warn bin gh "not installed (refresh --scope=github will be skipped)" "install gh: https://cli.github.com/"
fi

# --- 2. namespace + project.json ---
root="$(SHCTX_QUIET=1 shctx_artifacts_root)"
repo="$(shctx_repo_root)"
if [[ -d "$root" ]]; then
  add ok ns "namespace dir" "$root" ""
else
  add fail ns "namespace dir" "missing" "run 'shctx init' or 'shctx ready'"
fi

# Dual-namespace conflict: both .shepherd/ and .artifacts/ exist.
if [[ -d "$repo/.shepherd" && -d "$repo/.artifacts" ]]; then
  active="$(basename "$root")"
  unused="$( [[ "$active" == ".shepherd" ]] && echo ".artifacts" || echo ".shepherd" )"
  add warn ns "namespace conflict" \
    "both .shepherd/ and .artifacts/ exist; using $active/, $unused/ is unused" \
    "remove $unused/ or run 'shctx init --$( echo "$unused" | tr -d '.' )' to switch"
fi

pjson="$(shctx_project_id_path)"
if [[ -f "$pjson" ]]; then
  pid=$(jq -r '.id' "$pjson" 2>/dev/null || echo "")
  if [[ -n "$pid" && "$pid" != "null" ]]; then
    add ok ns "project.json" "id=$pid" ""
  else
    add fail ns "project.json" "malformed (no .id)" "delete $pjson and run 'shctx init'"
  fi
else
  add fail ns "project.json" "missing" "run 'shctx init'"
fi

# --- 3. db + schema ---
db="$(shctx_db_path)"
if [[ -f "$db" ]]; then
  add ok db "root.db" "$(du -h "$db" 2>/dev/null | cut -f1)" ""
  schema_ver=$(shctx_sql "SELECT MAX(version) FROM schema_versions;" 2>/dev/null || echo "")
  if [[ -n "$schema_ver" && "$schema_ver" != "null" ]]; then
    add ok db "schema_version" "$schema_ver" ""
  else
    add warn db "schema_version" "no schema_versions row" "run 'shctx migrate'"
  fi
  # Check pending migrations.
  pending=0
  if [[ -d "$HERE/../schema/migrations" ]]; then
    for m in "$HERE"/../schema/migrations/*.sql; do
      [[ -f "$m" ]] || continue
      v=$(basename "$m" | grep -oE '^[0-9]+' || echo "")
      [[ -n "$v" ]] || continue
      v=$((10#$v))  # force base-10
      if [[ -n "$schema_ver" ]] && (( v > schema_ver )); then
        pending=$((pending + 1))
      fi
    done
  fi
  if (( pending > 0 )); then
    add warn db "pending migrations" "$pending pending" "run 'shctx migrate'"
  else
    add ok db "pending migrations" "none" ""
  fi
else
  add fail db "root.db" "missing" "run 'shctx init' or 'shctx ready'"
fi

# --- 4. lock state ---
lock="$(shctx_lock_path)"
if [[ -f "$lock" ]]; then
  age=$(( $(shctx_now) - $(jq -r .acquired_at "$lock" 2>/dev/null || echo 0) ))
  age_min=$(( age / 60 ))
  pid=$(jq -r .pid "$lock" 2>/dev/null || echo "?")
  sess=$(jq -r .holder_session_id "$lock" 2>/dev/null || echo "?")
  if (( age_min > 60 )); then
    add warn lock "shepherd.lock" "held ${age_min}m by pid=$pid sess=$sess (stale?)" "run 'shctx lock reap'"
  else
    add ok lock "shepherd.lock" "held ${age_min}m by pid=$pid sess=$sess" ""
  fi
else
  add ok lock "shepherd.lock" "free" ""
fi

# --- 5. refresh staleness per zone ---
if [[ -f "$db" ]]; then
  now=$(shctx_now)
  for zone in symbols issues prs releases artifacts; do
    case "$zone" in
      symbols)   tbl=index_symbols ;;
      issues)    tbl=index_issues ;;
      prs)       tbl=index_prs ;;
      releases)  tbl=index_releases ;;
      artifacts) tbl=artifacts ;;
    esac
    cnt=$(shctx_sql "SELECT COUNT(*) FROM $tbl;" 2>/dev/null || echo 0)
    latest=$(shctx_sql "SELECT MAX(refreshed_at) FROM $tbl;" 2>/dev/null || echo 0)
    [[ -n "$latest" && "$latest" != "null" ]] || latest=0
    if (( latest == 0 )); then
      add warn refresh "$zone" "rows=$cnt, never refreshed" "run 'shctx refresh --scope=$zone' (or 'shctx sync')"
    else
      age_min=$(( (now - latest) / 60 ))
      if (( age_min > 120 )); then
        add warn refresh "$zone" "rows=$cnt, stale ${age_min}m" "run 'shctx refresh --scope=$zone'"
      else
        add ok refresh "$zone" "rows=$cnt, fresh ${age_min}m" ""
      fi
    fi
  done
fi

# --- 6. shepherd.toml ---
repo="$(shctx_repo_root)"
toml=""
for cand in "$repo/.claude/shepherd.toml" "$repo/.claude/shepherd.local.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/shepherd.toml"; do
  if [[ -f "$cand" ]]; then toml="$cand"; break; fi
done
if [[ -n "$toml" ]]; then
  add ok config "shepherd.toml" "$toml" ""
else
  add warn config "shepherd.toml" "not found at standard paths" "create .claude/shepherd.toml — see docs/configuration.md"
fi

# --- emit ---
fail_count=0
warn_count=0
for r in "${results[@]}"; do
  IFS='|' read -r status _ _ _ _ <<< "$r"
  case "$status" in fail) fail_count=$((fail_count + 1)) ;; warn) warn_count=$((warn_count + 1)) ;; esac
done

if [[ "$fmt" == "json" ]]; then
  echo '{'
  echo '  "summary": {'
  echo "    \"total\": ${#results[@]},"
  echo "    \"fail\": $fail_count,"
  echo "    \"warn\": $warn_count"
  echo '  },'
  echo '  "checks": ['
  first=1
  for r in "${results[@]}"; do
    IFS='|' read -r status cat name msg fix <<< "$r"
    (( first )) || echo ','
    first=0
    msg_esc=$(printf '%s' "$msg" | sed 's/"/\\"/g')
    fix_esc=$(printf '%s' "$fix" | sed 's/"/\\"/g')
    printf '    {"status":"%s","category":"%s","name":"%s","message":"%s","fix":"%s"}' \
      "$status" "$cat" "$name" "$msg_esc" "$fix_esc"
  done
  echo
  echo '  ]'
  echo '}'
else
  printf '%-6s %-9s %-22s %s\n' STATUS CATEGORY NAME MESSAGE
  for r in "${results[@]}"; do
    IFS='|' read -r status cat name msg fix <<< "$r"
    case "$status" in
      ok)   icon="OK   " ;;
      warn) icon="WARN " ;;
      fail) icon="FAIL " ;;
      *)    icon="$status" ;;
    esac
    printf '%-6s %-9s %-22s %s\n' "$icon" "$cat" "$name" "$msg"
    [[ -n "$fix" ]] && printf '       %-9s %-22s   → fix: %s\n' "" "" "$fix"
  done
  echo
  echo "shctx doctor: $fail_count fail, $warn_count warn, $(( ${#results[@]} - fail_count - warn_count )) ok"
fi

if (( fail_count > 0 )); then exit 1; fi
if (( warn_count > 0 )); then exit 2; fi
exit 0
