#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# ── layout migration (--layout v2) ─────────────────────────────────────────
# Opt-in filesystem migration from legacy layout → v6.1.0 standard layout.
# Safe, idempotent, and re-runnable; never clobbers existing destination files.
_layout_v2_migrate() {
  local wd; wd="$(shctx_artifacts_root)"
  local moved=0 skipped=0 created=0

  echo "shctx migrate --layout v2: workdir = $wd"

  # Helper: move a glob of files src_dir → dst_dir (git mv with plain mv fallback).
  _mv_dir_contents() {
    local src="$1" dst="$2"
    [[ -d "$src" ]] || return 0
    local count; count=$(find "$src" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')
    (( count == 0 )) && return 0
    mkdir -p "$dst"
    while IFS= read -r -d '' f; do
      local base; base="$(basename "$f")"
      if [[ -e "$dst/$base" ]]; then
        echo "  SKIP (dest exists): $f -> $dst/$base"
        skipped=$(( skipped + 1 ))
      else
        if git -C "$wd" ls-files --error-unmatch "$f" >/dev/null 2>&1; then
          git -C "$wd" mv "$f" "$dst/$base"
        else
          mv "$f" "$dst/$base"
        fi
        echo "  moved: $f -> $dst/$base"
        moved=$(( moved + 1 ))
      fi
    done < <(find "$src" -maxdepth 1 -type f -print0 2>/dev/null)
  }

  # 1. plans/* -> docs/plans/   (legacy top-level only; docs/plans already new)
  if [[ -d "$wd/plans" && "$wd/plans" != "$wd/docs/plans" ]]; then
    _mv_dir_contents "$wd/plans" "$wd/docs/plans"
  fi

  # 2. reports/* -> docs/reports/
  if [[ -d "$wd/reports" && "$wd/reports" != "$wd/docs/reports" ]]; then
    _mv_dir_contents "$wd/reports" "$wd/docs/reports"
  fi

  # 3. root.db* -> shepherd.db* (gitignored runtime files; plain mv only).
  for ext in "" "-journal" "-wal" "-shm"; do
    local src="$wd/root.db${ext}" dst="$wd/shepherd.db${ext}"
    if [[ -f "$src" ]]; then
      if [[ -f "$dst" ]]; then
        echo "  SKIP (dest exists): $src -> $dst"
        skipped=$(( skipped + 1 ))
      else
        mv "$src" "$dst"
        echo "  renamed: $src -> $dst"
        moved=$(( moved + 1 ))
      fi
    fi
  done

  # 4. Create new standard dirs (idempotent).
  for d in archive scripts templates types cache docs/plans docs/reports; do
    if [[ ! -d "$wd/$d" ]]; then
      mkdir -p "$wd/$d"
      touch "$wd/$d/.gitkeep"
      echo "  created: $wd/$d/"
      created=$(( created + 1 ))
    fi
  done

  echo "shctx migrate --layout v2: done — moved=$moved skipped=$skipped created=$created"
}

# ── flag dispatch ───────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --layout=v2|--layout) : ;;  # valid; two-arg form handled in dispatch below
    --layout=*) echo "ERROR: unknown --layout value (only 'v2' supported)" >&2; exit 1 ;;
    v2) : ;;  # value token when --layout was the preceding arg
    *) ;;
  esac
done

if [[ "${1:-}" == "--layout" && "${2:-}" == "v2" ]] || [[ "${1:-}" == "--layout=v2" ]]; then
  _layout_v2_migrate
  exit 0
fi

# ── schema migrations (default behavior — unchanged) ───────────────────────
# The gap-fill apply loop lives in _lib.sh (shctx_apply_pending_migrations) so it
# is the SINGLE source of truth shared with the on-demand self-heal
# (shctx_ensure_migrated, v6.3.3 #200). Behavior is identical to the historical
# inline loop: apply any migration whose version is ABSENT from schema_versions.
migdir="$(shctx_skill_root)/schema/migrations"
[[ -d "$migdir" ]] || { echo "no migrations dir"; exit 0; }

current=$(shctx_sql "SELECT COALESCE(MAX(version),0) FROM schema_versions;")
applied="$(shctx_apply_pending_migrations)"   # progress → stderr; count → stdout
if (( applied == 0 )); then
  echo "shctx migrate: no migrations pending (at version $current)"
else
  echo "shctx migrate: applied $applied migration(s)"
fi
