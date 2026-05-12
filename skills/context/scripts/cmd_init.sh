#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# Parse flags BEFORE sourcing _lib.sh so SHCTX_ROOT_OVERRIDE takes effect on first
# path resolution. `init --artifacts` opts back into the legacy `.artifacts/`
# namespace; default (no flag) scaffolds `.shepherd/` unless an existing namespace
# is already present (auto-detected by shctx_artifacts_root).
for arg in "$@"; do
  case "$arg" in
    --artifacts) export SHCTX_ROOT_OVERRIDE=".artifacts" ;;
    --shepherd)  export SHCTX_ROOT_OVERRIDE=".shepherd" ;;
    -h|--help)
      cat <<'EOF'
shctx init [--artifacts|--shepherd]

Scaffold the per-project shepherd namespace tree, create root.db, and register
the host project.

Default: .shepherd/ (v5.0.0+). If either .shepherd/ or .artifacts/ already
exists in the repo, that one is used (auto-detect). Use --artifacts to force
the legacy .artifacts/ namespace for a NEW init.
EOF
      exit 0 ;;
    *)
      echo "ERROR: unknown init flag: $arg" >&2
      exit 1 ;;
  esac
done

source "$HERE/_lib.sh"

bash "$HERE/scaffold.sh"

db="$(shctx_db_path)"
pidfile="$(shctx_project_id_path)"

# Apply schema if DB absent.
if [[ ! -f "$db" ]]; then
  sqlite3 "$db" < "$(shctx_skill_root)/schema/0001_init.sql" >/dev/null
fi

# Insert the host project row exactly once. Persist the UUID to project.json.
if [[ -f "$pidfile" ]]; then
  pid=$(jq -r '.id' "$pidfile")
else
  pid=$(shctx_uuid7)
  name=$(basename "$(shctx_repo_root)")
  scope_json=$(jq -nc --arg p "$(shctx_repo_root)" '[$p]')
  now=$(shctx_now)
  shctx_sql "INSERT OR IGNORE INTO projects (id,name,scope,tags,created_at,updated_at)
             VALUES ('$pid', '$name', '$scope_json', '[]', $now, $now);"
  jq -nc --arg id "$pid" --argjson at "$(shctx_now)" \
    '{id:$id, scaffolded_at:$at}' > "$pidfile"
fi

echo "shctx: initialized $(basename "$(shctx_artifacts_root)")/ at $(shctx_artifacts_root)"
echo "shctx: project_id = $pid"

# Auto-refresh artifacts when the project already has markdown content under
# {plans,reports,docs}. Self-bootstrapping: a pre-existing namespace dir gets
# indexed without a separate `refresh --scope=artifacts` call.
# (macOS bash 3.2: no globstar, so we use find for the recursive walk.)
root="$(shctx_artifacts_root)"
preexisting_count=0
for d in plans reports docs; do
  if [[ -d "$root/$d" ]]; then
    n=$(find "$root/$d" -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    preexisting_count=$((preexisting_count + n))
  fi
done
if (( preexisting_count > 0 )); then
  echo "shctx: detected $preexisting_count pre-existing markdown file(s); auto-indexing"
  bash "$HERE/refresh-artifacts.sh"
fi
