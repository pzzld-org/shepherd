#!/usr/bin/env bash
# shctx dups — field-shape similar-struct detection (v6.1.8, #157).
#
# The third leg of the mechanical shape-gate set (alongside dep-hygiene and
# check-impls-defs): catches the rename-to-evade-dedup shadow — a second type
# for an existing concept under a DIFFERENT name — that name-matching dedup
# (index_symbols / dedup-check.sql / dedup_write_guard.sh) cannot see.
#
#   scan      census the workspace, cluster similar shapes, suggest a canonical
#   check     match a candidate's new defs vs the persisted corpus (authoring gate)
#   registry  curate concept→canonical pins + the DO-NOT-MERGE allow-list
#
# Parse + similarity + clustering live in dups-core.py (stdlib python3); this
# wrapper handles config, file enumeration, paths, and output. Fails open
# (exit 0, no output) when python3 is unavailable so it never blocks work.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

CORE="$HERE/dups-core.py"
PY="$(command -v python3 || true)"

# ── config (unique dups_* keys — cfg_get is section-agnostic; see docs) ──────
DUPS_THRESHOLD="$(cfg_get dups_threshold)";        [[ -n "$DUPS_THRESHOLD" ]]    || DUPS_THRESHOLD=0.7
DUPS_BLOCK="$(cfg_get dups_block)";                [[ -n "$DUPS_BLOCK" ]]        || DUPS_BLOCK=0.85
DUPS_NAME_WEIGHT="$(cfg_get dups_name_weight)";    [[ -n "$DUPS_NAME_WEIGHT" ]]  || DUPS_NAME_WEIGHT=0.5
DUPS_MIN_FIELDS="$(cfg_get dups_min_fields)";      [[ -n "$DUPS_MIN_FIELDS" ]]   || DUPS_MIN_FIELDS=2

registry_path() {
  local p; p="$(cfg_get dups_registry)"
  if [[ -n "$p" ]]; then
    case "$p" in /*) printf '%s' "$p" ;; *) printf '%s/%s' "$(shctx_repo_root)" "$p" ;; esac
  else
    printf '%s/dups-registry.json' "$(shctx_artifacts_root)"
  fi
}

# Newline list of *.rs files (git-aware: tracked + new-but-not-ignored), repo-relative.
list_rust_files() {
  local root; root="$(shctx_repo_root)"
  if git -C "$root" rev-parse >/dev/null 2>&1; then
    git -C "$root" ls-files --cached --others --exclude-standard -- '*.rs' 2>/dev/null
  else
    ( cd "$root" && find . -type f -name '*.rs' \
        -not -path '*/target/*' -not -path '*/.git/*' -not -path '*/node_modules/*' \
        2>/dev/null | sed 's|^\./||' )
  fi
}

require_python() {
  [[ -n "$PY" ]] || { echo "shctx dups: python3 not found — skipping (fail-open)." >&2; exit 0; }
}

# ── registry helpers (jq-managed JSON; mirrors the toolkit.json pattern) ─────
_read_registry() {
  local p; p="$(registry_path)"
  if [[ -f "$p" ]]; then cat "$p"
  else echo '{"version":1,"canonical":{},"allow":[]}'
  fi
}
_write_registry() {
  local p; p="$(registry_path)"
  mkdir -p "$(dirname "$p")"
  cat > "$p"
  echo "shctx dups registry: wrote $p"
}

usage() {
  cat <<'EOF'
shctx dups — field-shape similar-struct detection (#157)

  scan  [--threshold F] [--name-weight F] [--min-fields N]
        [--fail-on medium|high|foundation-blocking|any] [--update] [--json]
            Census every public struct/enum, cluster by field-shape similarity,
            and report clusters with a suggested canonical (lowest dep tier).
            --update persists the shape corpus to index_struct_shapes (so
            `dups check` is fast). --fail-on sets a non-zero exit for gates/CI.

  check <file> | --stdin --as <path>  [--threshold F] [--block-threshold F] [--json]
            Match a candidate's NEW struct/enum defs against the persisted
            corpus; report any same-shape existing type ("reuse it?"). Exits 5
            when a match ≥ block-threshold exists. Used by the PreToolUse hook
            and as a coder Phase-0 step.

  registry show|path|allow A B|unallow A B|pin CONCEPT PKG::TYPE|unpin CONCEPT|update
            Curate the concept→canonical pins and the DO-NOT-MERGE allow-list
            (intentional distinct-role twins). Feeds scan + check.

Config (.claude/shepherd.toml [dups]): dups_threshold, dups_block,
dups_name_weight, dups_min_fields, dups_hook (off|warn|block), dups_registry.
EOF
}

sub="${1:-}"; shift || true
case "$sub" in
  scan)
    require_python
    threshold="$DUPS_THRESHOLD"; nw="$DUPS_NAME_WEIGHT"; mf="$DUPS_MIN_FIELDS"
    fail_on=""; update=0; json=0; quiet=0
    # Accept both `--flag value` (issue spec) and `--flag=value` (shctx house style).
    while [[ $# -gt 0 ]]; do
      arg="$1"
      case "$arg" in
        --threshold)     threshold="${2:?--threshold needs a value}"; shift ;;
        --threshold=*)   threshold="${arg#*=}" ;;
        --name-weight)   nw="${2:?--name-weight needs a value}"; shift ;;
        --name-weight=*) nw="${arg#*=}" ;;
        --min-fields)    mf="${2:?--min-fields needs a value}"; shift ;;
        --min-fields=*)  mf="${arg#*=}" ;;
        --fail-on)       fail_on="${2:?--fail-on needs a value}"; shift ;;
        --fail-on=*)     fail_on="${arg#*=}" ;;
        --update)        update=1 ;;
        --json)          json=1 ;;
        --quiet)         quiet=1 ;;
        -h|--help)       usage; exit 0 ;;
        *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
      esac
      shift
    done
    db="$(shctx_db_path)"; pid="$(shctx_project_id 2>/dev/null || true)"
    args=(scan --files-stdin --threshold "$threshold" --name-weight "$nw" --min-fields "$mf"
          --registry "$(registry_path)")
    [[ -n "$fail_on" ]] && args+=(--fail-on "$fail_on")
    (( update )) && [[ -n "$pid" ]] && args+=(--update --db "$db" --project-id "$pid")
    (( json )) && args+=(--json)
    rc=0
    if (( quiet )); then
      list_rust_files | ( cd "$(shctx_repo_root)" && "$PY" "$CORE" "${args[@]}" >/dev/null ) || rc=$?
    else
      list_rust_files | ( cd "$(shctx_repo_root)" && "$PY" "$CORE" "${args[@]}" ) || rc=$?
    fi
    exit "$rc"
    ;;

  check)
    require_python
    threshold="$DUPS_THRESHOLD"; block="$DUPS_BLOCK"; nw="$DUPS_NAME_WEIGHT"; mf="$DUPS_MIN_FIELDS"
    json=0; use_stdin=0; as_path=""; file_arg=""
    while [[ $# -gt 0 ]]; do
      arg="$1"
      case "$arg" in
        --threshold)         threshold="${2:?--threshold needs a value}"; shift ;;
        --threshold=*)       threshold="${arg#*=}" ;;
        --block-threshold)   block="${2:?--block-threshold needs a value}"; shift ;;
        --block-threshold=*) block="${arg#*=}" ;;
        --name-weight)       nw="${2:?--name-weight needs a value}"; shift ;;
        --name-weight=*)     nw="${arg#*=}" ;;
        --min-fields)        mf="${2:?--min-fields needs a value}"; shift ;;
        --min-fields=*)      mf="${arg#*=}" ;;
        --as)                as_path="${2:?--as needs a value}"; shift ;;
        --as=*)              as_path="${arg#*=}" ;;
        --stdin)             use_stdin=1 ;;
        --json)              json=1 ;;
        -h|--help)           usage; exit 0 ;;
        --*) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
        *)   file_arg="$arg" ;;
      esac
      shift
    done
    db="$(shctx_db_path)"; pid="$(shctx_project_id 2>/dev/null || true)"
    # normalize as_path to repo-relative so self-exclusion matches the corpus
    if [[ -n "$as_path" ]]; then
      root="$(shctx_repo_root)"
      case "$as_path" in "$root"/*) as_path="${as_path#"$root"/}" ;; esac
    fi
    args=(check --threshold "$threshold" --block-threshold "$block" --name-weight "$nw"
          --min-fields "$mf" --registry "$(registry_path)")
    [[ -n "$pid" ]] && args+=(--db "$db" --project-id "$pid")
    [[ -n "$as_path" ]] && args+=(--as "$as_path")
    (( json )) && args+=(--json)
    rc=0
    if (( use_stdin )); then
      args+=(--stdin)
      "$PY" "$CORE" "${args[@]}" || rc=$?
    else
      [[ -n "$file_arg" ]] || { echo "ERROR: usage: shctx dups check <file> | --stdin --as <path>" >&2; exit 1; }
      [[ -z "$as_path" ]] && args+=(--as "$file_arg")
      "$PY" "$CORE" "${args[@]}" "$file_arg" || rc=$?
    fi
    exit "$rc"
    ;;

  registry)
    action="${1:-show}"; shift || true
    case "$action" in
      path) registry_path; echo ;;
      show)
        if [[ "${1:-}" == "--json" ]]; then _read_registry | jq '.'
        else
          _read_registry | jq -r '
            "DO-NOT-MERGE allow-list (\(.allow|length) pair(s)):",
            (.allow[]? | "  - \(.[0])  ⟷  \(.[1])"),
            "",
            "Concept → canonical pins (\(.canonical|length)):",
            (.canonical | to_entries[]? | "  - \(.key)  →  \(.value)")'
        fi ;;
      allow)
        a="${1:-}"; b="${2:-}"
        [[ -n "$a" && -n "$b" ]] || { echo "ERROR: usage: shctx dups registry allow <A> <B>" >&2; exit 1; }
        _read_registry | jq --arg a "$a" --arg b "$b" \
          '.allow = ((.allow // []) + [[$a,$b]] | unique)' | _write_registry ;;
      unallow)
        a="${1:-}"; b="${2:-}"
        [[ -n "$a" && -n "$b" ]] || { echo "ERROR: usage: shctx dups registry unallow <A> <B>" >&2; exit 1; }
        _read_registry | jq --arg a "$a" --arg b "$b" \
          '.allow = [(.allow // [])[] | select((. == [$a,$b]) or (. == [$b,$a]) | not)]' | _write_registry ;;
      pin)
        concept="${1:-}"; target="${2:-}"
        [[ -n "$concept" && -n "$target" ]] || { echo "ERROR: usage: shctx dups registry pin <concept> <pkg::Type>" >&2; exit 1; }
        _read_registry | jq --arg c "$concept" --arg t "$target" '.canonical[$c] = $t' | _write_registry ;;
      unpin)
        concept="${1:-}"
        [[ -n "$concept" ]] || { echo "ERROR: usage: shctx dups registry unpin <concept>" >&2; exit 1; }
        _read_registry | jq --arg c "$concept" 'del(.canonical[$c])' | _write_registry ;;
      update)
        require_python
        db="$(shctx_db_path)"; pid="$(shctx_project_id 2>/dev/null || true)"
        scan_json="$(list_rust_files | ( cd "$(shctx_repo_root)" && "$PY" "$CORE" scan --files-stdin \
          --threshold "$DUPS_THRESHOLD" --name-weight "$DUPS_NAME_WEIGHT" --min-fields "$DUPS_MIN_FIELDS" \
          --registry "$(registry_path)" --json ) || true)"
        [[ -n "$scan_json" ]] || { echo "shctx dups registry update: no scan output"; exit 0; }
        # Merge a canonical pin for each cluster's concept (non-destructive: keep existing pins).
        merged="$(_read_registry | jq --argjson scan "$scan_json" '
          reduce ($scan.clusters[]? ) as $c (.;
            if (.canonical[$c.concept] // null) == null
            then .canonical[$c.concept] = $c.suggested_canonical
            else . end)')"
        printf '%s' "$merged" | _write_registry
        added="$(printf '%s' "$scan_json" | jq '[.clusters[].concept] | length')"
        echo "shctx dups registry update: considered $added cluster concept(s)."
        ;;
      *) echo "ERROR: usage: shctx dups registry <show|path|allow|unallow|pin|unpin|update>" >&2; exit 1 ;;
    esac
    ;;

  ""|-h|--help) usage ;;
  *) echo "ERROR: unknown dups subcommand: $sub" >&2; usage >&2; exit 1 ;;
esac
