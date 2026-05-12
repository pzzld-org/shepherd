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
[[ -n "$role" ]] || { echo "ERROR: usage: shctx inject <engineer|coder|auditor> [--scope=<glob>] [--limit=N] [--full]" >&2; exit 1; }
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
    emit_block "$(printf '## Open issues\n%s\n\n## Drift risk\n%s\n\n## Canonical types (top %d)\n%s\n' "$issues" "$drift" "$limit" "$types")"
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
    emit_block "$(printf '%s\n%s\n' "$header" "$types")"
    ;;

  auditor)
    # Cross-cutting concerns only — open issues + open PRs. Auditors read
    # source state directly; injecting canonical types would be redundant.
    issues=$(bash "$HERE/cmd_query.sh" open-issues --md 2>/dev/null | cap_md "$limit" || echo "_(none)_")
    prs=$(bash "$HERE/cmd_query.sh" open-prs --md 2>/dev/null | cap_md "$limit" || echo "_(none)_")
    emit_block "$(printf '## Open issues (cross-cutting)\n%s\n\n## Open PRs\n%s\n' "$issues" "$prs")"
    ;;

  *) echo "ERROR: unknown role: $role" >&2; exit 1 ;;
esac
