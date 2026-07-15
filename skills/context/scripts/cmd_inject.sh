#!/usr/bin/env bash
# shctx inject <role> [--scope=<glob>] [--limit=N] [--full]
#
# v5.0.4 — role-tailored: token-budget-aware. The engineer sees the full
# context surface; the coder sees a file-scope-filtered subset; the auditor
# sees cross-cutting state only. --full overrides for any role.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

role="${1:-}"
[[ -n "$role" ]] || { echo "ERROR: usage: shctx inject <engineer|coder|auditor|planter> [--scope=<glob>] [--limit=N] [--full]" >&2; exit 1; }
shift

scope_glob=""
limit=""
full=0
for arg in "$@"; do
  case "$arg" in
    --scope=*) scope_glob="${arg#--scope=}" ;;
    --limit=*) limit="${arg#--limit=}" ;;
    --full)    full=1 ;;
  esac
done

emit_block() { echo "[DB-CONTEXT]"; printf '%s\n' "$1"; echo "[/DB-CONTEXT]"; }

# Default per-role limits — tuned for typical brief budgets.
# Override with --limit=N. --full removes the cap entirely.
default_limit_for() {
  case "$1" in
    engineer) echo 80 ;;     # full context surface
    coder)    echo 30 ;;     # file-scope-filtered, smaller cap
    auditor)  echo 25 ;;     # cross-cutting concerns only
    planter)  echo 60 ;;     # seed-author surface
    *)        echo 50 ;;
  esac
}
[[ -n "$limit" ]] || limit=$(default_limit_for "$role")
(( full )) && limit=0  # 0 = no cap

cap_md() {
  local n="$1"
  if (( n == 0 )); then cat
  else head -n "$n"
  fi
}

# Filter canonical-types markdown by file-scope glob (coder role).
# Each row in canonical-types.md has a `path` column; the filter is a
# best-effort line-grep — for richer filtering, the coder reads the full
# canonical-types catalog separately.
filter_by_scope() {
  if [[ -n "$scope_glob" ]]; then
    grep -E -- "$scope_glob" || true
  else
    cat
  fi
}

case "$role" in
  engineer)
    # Full surface: open issues, drift risk, canonical types (broad).
    issues=$(bash "$HERE/cmd_query.sh" open-issues --md 2>/dev/null || echo "_(no open issues / gh unavailable)_")
    drift=$(bash "$HERE/cmd_query.sh" drift-risk --md 2>/dev/null || echo "_(no drift-risk index)_")
    types=$(bash "$HERE/cmd_query.sh" canonical-types --md 2>/dev/null | cap_md "$limit")
    body=$(printf '## Open issues\n%s\n\n## Drift risk\n%s\n\n## Canonical types (top %d)\n%s\n' "$issues" "$drift" "$limit" "$types")
    # Lesson priors are the most variable content → append LAST (cache-tail per
    # brief-cache-discipline). Omitted entirely when the store is empty (#95).
    priors=$(bash "$HERE/cmd_adapt.sh" priors --lessons --md 2>/dev/null || true)
    [[ -n "$priors" ]] && body=$(printf '%s\n\n%s\n' "$body" "$priors")
    # Dispatch recommendation (v6.0.8) — measured lane/size guidance, appended
    # after priors. Emits nothing on an empty store, so the section is omitted
    # for cold starts (graceful, same omit-if-empty contract as priors).
    rec=$(bash "$HERE/cmd_adapt.sh" recommend --md 2>/dev/null || true)
    case "$rec" in
      *'no history yet'*|'') : ;;
      *) body=$(printf '%s\n\n%s\n' "$body" "$rec") ;;
    esac
    emit_block "$body"
    ;;

  coder)
    # File-scope-filtered: only the canonical types relevant to [FILE-SCOPE].
    # The conductor passes --scope=<regex over file paths> (e.g. "crates/store").
    types=$(bash "$HERE/cmd_query.sh" canonical-types --md 2>/dev/null \
      | filter_by_scope \
      | cap_md "$limit")
    if [[ -z "$types" ]]; then
      types="_(no matches; coder should read canonical-types.md catalog directly)_"
    fi
    if [[ -n "$scope_glob" ]]; then
      header="## Existing canonical types in scope \`$scope_glob\` — REUSE; do not duplicate"
    else
      header="## Existing canonical types (top $limit) — REUSE; do not duplicate"
    fi
    body="$(printf '%s\n%s\n' "$header" "$types")"
    emit_block "$body"
    ;;

  auditor)
    # Cross-cutting concerns only — open issues + open PRs. Auditors read
    # source state directly; injecting canonical types would be redundant.
    issues=$(bash "$HERE/cmd_query.sh" open-issues --md 2>/dev/null | cap_md "$limit" || echo "_(none)_")
    prs=$(bash "$HERE/cmd_query.sh" open-prs --md 2>/dev/null | cap_md "$limit" || echo "_(none)_")
    emit_block "$(printf '## Open issues (cross-cutting)\n%s\n\n## Open PRs\n%s\n' "$issues" "$prs")"
    ;;

  planter)
    # Seed-author surface (/shepherd:plant): what's open + the lessons to guard.
    # Priors are the variable tail (cache-discipline), omitted when empty (#95).
    issues=$(bash "$HERE/cmd_query.sh" open-issues --md 2>/dev/null | cap_md "$limit" || echo "_(no open issues / gh unavailable)_")
    drift=$(bash "$HERE/cmd_query.sh" drift-risk --md 2>/dev/null || echo "_(no drift-risk index)_")
    body=$(printf '## Open issues\n%s\n\n## Drift risk\n%s\n' "$issues" "$drift")
    priors=$(bash "$HERE/cmd_adapt.sh" priors --lessons --md 2>/dev/null || true)
    [[ -n "$priors" ]] && body=$(printf '%s\n\n%s\n' "$body" "$priors")
    emit_block "$body"
    ;;

  *) echo "ERROR: unknown role: $role" >&2; exit 1 ;;
esac
