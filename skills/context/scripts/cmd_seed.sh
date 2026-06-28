#!/usr/bin/env bash
# /shepherd:ctx seed — deterministic seed pre-flight gate (v6.2.1).
#
# `shctx seed verify <path>` mechanizes the planter pre-flight checklist that
# used to be prose-only (planter.md §Step 4 / seed-template.md §Verification).
# The framework's highest-precision artifact finally gets a deterministic floor:
# hallucinated file_scope paths, oversized footprints, leftover TODO markers,
# and prescriptive `Lane N` numbering (the #67 firewall violation) are caught
# mechanically instead of by latent self-policing. seed-naming.md promised
# "future sprints will add teeth" — this is the teeth.
#
# SINGLE SOURCE OF TRUTH: the numbers below (MIN_MESH_ROWS, *_FOOTPRINT_CAP) are
# authoritative. seed-template.md and planter.md point HERE, not at their own
# copies — that is how the three-different-numbers-for-one-cap drift is killed.
#
# HARD vs WARN:
#   HARD (exit 1, blocks the SEED-GATE) — env-independent, deterministic, and
#   unambiguous: footprint over cap, TODO/FIXME, Lane-N numbering, a file_scope
#   path that neither resolves nor carries a (NEW) marker, a canonical
#   deliverable block with no GH anchor.
#   WARN (exit 0, advisory) — fuzzy or env-dependent: footprint smell, thin
#   mesh, no CRITICAL/HIGH, missing frontmatter, Sequencing:/semver judgments.
# No network. gh-backed issue-existence is intentionally NOT a hard check —
# gh present-but-unauthed/offline would spuriously block a valid seed; that is
# the planter's prose responsibility, not the gate's.
#
# Every check is conditional on the relevant structure being present, so an
# old-format or freeform seed degrades gracefully instead of false-positiving.
#
# Allow-syntax: a file_scope path created THIS sprint carries a trailing
# `(NEW)` (or `# NEW`) marker and is exempt from FS resolution — "exists OR
# correctly marked NEW" (feedback: verify-paths-in-seeds).
#
# Exit: 0 = no hard failures (warnings allowed); 1 = >=1 hard failure;
#       2 = usage error. Pure text processing — no DB, no _lib, no network.
set -uo pipefail

# --- canonical numbers (single source of truth) ---
MIN_MESH_ROWS=8
SPRINT_FOOTPRINT_CAP=400
PATCH_FOOTPRINT_CAP=200

usage() {
  cat <<'U'
shctx seed verify <path> [--quiet]
  Deterministic pre-flight gate for a *.seed.md.
  Exit 1 on >=1 HARD failure (blocks the SEED-GATE); 0 otherwise (warnings allowed).
U
}

sub="${1:-}"; shift || true
case "$sub" in
  verify) ;;
  ""|help|--help|-h) usage; exit 0 ;;
  *) echo "unknown subcommand: $sub" >&2; usage >&2; exit 2 ;;
esac

quiet=0
path=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet) quiet=1 ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *)  path="$1" ;;
  esac
  shift
done

[[ -n "$path" ]] || { echo "ERR: seed verify needs a <path>" >&2; exit 2; }
[[ -f "$path" ]] || { echo "ERR: no such file: $path" >&2; exit 2; }

hard=0
warns=0
emit() { [[ "$quiet" == "1" ]] || printf '%s\n' "$*"; }
fail() { hard=$((hard+1));  emit "  HARD  $1"; }
warn() { warns=$((warns+1)); emit "  warn  $1"; }

content="$(cat "$path")"
total_lines="$(printf '%s\n' "$content" | grep -c '' || true)"

# kind / footprint cap detection
kind="$(printf '%s\n' "$content" | grep -m1 -E '^kind:' | sed -E 's/^kind:[[:space:]]*//; s/[[:space:]]+#.*$//; s/[[:space:]]*$//' 2>/dev/null || true)"
cap="$SPRINT_FOOTPRINT_CAP"
case "$kind" in patch-seed) cap="$PATCH_FOOTPRINT_CAP" ;; esac
warn_at=$(( cap * 3 / 4 ))

# Is this a canonical (v6.0.0+) seed at all? Gate the canonical-only checks so an
# old-format / freeform seed is not punished for omitting fields it never had.
is_canonical=0
if printf '%s\n' "$content" | grep -qE '\*\*Priority:\*\*|^file_scope:|Phase 0 mesh|\*\*GH:\*\*'; then
  is_canonical=1
fi

# --- 1. footprint (universal) ---
if [[ "$total_lines" -gt "$cap" ]]; then
  fail "footprint ${total_lines} lines > cap ${cap} (kind=${kind:-sprint})"
elif [[ "$total_lines" -gt "$warn_at" ]]; then
  warn "footprint ${total_lines} lines > smell threshold ${warn_at}"
fi

# --- 2. TODO/FIXME (universal) ---
if printf '%s\n' "$content" | grep -qE '\b(TODO|FIXME):'; then
  fail "TODO:/FIXME: marker(s) present — resolve before commit"
fi

# --- 3. Lane-N numbering (universal — #67 firewall) ---
if printf '%s\n' "$content" | grep -qE '\bLane[[:space:]]+[0-9]'; then
  fail "prescriptive 'Lane N' numbering present — lane decomposition is engineer territory (#67)"
fi

# --- 4. Sequencing / semver judgments (universal, WARN — fuzzy) ---
if printf '%s\n' "$content" | grep -qE '^[[:space:]]*\*{0,2}Sequencing:'; then
  warn "'Sequencing:' directive present — sequencing is engineer territory (#67)"
fi
if printf '%s\n' "$content" | grep -qiE 'too (small|big|large) for a (patch|minor|sprint)|should be a (patch|minor|major)|really a (minor|major)'; then
  warn "semver-content judgment present — version tier is the operator's call"
fi

# --- 5. file_scope paths resolve OR (NEW) (HARD, only if file_scope present) ---
# Resolve relative to the repo root (not the CWD) so the gate behaves the same
# from a worktree subdir. Tolerates the idiomatic forms a planter actually writes:
# a trailing annotation (` — desc`, ` (desc)`, ` # comment`), an embellished NEW
# marker (`(NEW - reason)`, `(new)`), and directory/recursive GLOBS (`crates/**/*.rs`).
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"

# resolve_one <raw-scope-entry> → 0 if it resolves or is NEW-marked, 1 otherwise.
resolve_one() {
  local raw="$1" tok cand
  case "$raw" in
    *'(NEW'*|*'(new'*|*'(New'*|*'#NEW'*|*'#new'*|*'# NEW'*|*'# new'*) return 0 ;;   # NEW-marker (embellishment-tolerant)
  esac
  tok="${raw%%[[:space:]]*}"                  # path token = first whitespace-delimited field
  case "$tok" in '<'*'>'|'') return 0 ;; esac # template placeholder / empty
  cand="$tok"
  if [[ -n "$repo_root" && "$tok" != /* ]]; then cand="$repo_root/$tok"; fi
  case "$tok" in
    *'*'*|*'?'*|*'['*) ( shopt -s nullglob; set -- $cand; [[ $# -gt 0 ]] ) ;;   # glob: >=1 match
    *)                 [[ -e "$cand" ]] ;;
  esac
}

scope_block="$(printf '%s\n' "$content" | awk '
  /^file_scope:/ { inblk=1; next }
  inblk && /^---[[:space:]]*$/ { inblk=0 }
  inblk && /^[^[:space:]]/     { inblk=0 }
  inblk { print }
')"
if [[ -n "$scope_block" ]]; then
  scope_seen=0
  while IFS= read -r line; do
    # flow-style:  exclusive: [a, b]  /  additive: [a, b]
    case "$line" in
      *exclusive:*\[*\]*|*additive:*\[*\]*)
        inner="${line#*\[}"; inner="${inner%\]*}"
        oldifs="$IFS"; IFS=','
        for e in $inner; do
          e="$(printf '%s' "$e" | sed -E 's/^[[:space:]]*//; s/[[:space:]]*$//')"
          [[ -n "$e" ]] || continue
          scope_seen=1
          resolve_one "$e" || fail "file_scope path does not resolve and is not marked (NEW): ${e%%[[:space:]]*}"
        done
        IFS="$oldifs"
        continue ;;
    esac
    # block-style list item:  - path
    case "$line" in *-\ *) : ;; *) continue ;; esac
    entry="$(printf '%s' "$line" | sed -E 's/^[[:space:]]*-[[:space:]]*//')"
    [[ -n "$entry" ]] || continue
    case "$entry" in exclusive:*|additive:*) continue ;; esac
    scope_seen=1
    resolve_one "$entry" || fail "file_scope path does not resolve and is not marked (NEW): ${entry%%[[:space:]]*}"
  done <<< "$scope_block"
  # file_scope present but nothing parsed (unrecognized YAML shape) → don't silently skip
  [[ "$scope_seen" -eq 1 ]] || warn "file_scope present but no entries parsed — verify paths manually (unrecognized YAML shape)"
fi

# --- 6. canonical deliverable blocks must carry a **GH:** anchor (HARD, conditional) ---
block_report="$(printf '%s\n' "$content" | awk '
  function flush() { if (started) print (isdel?1:0) "\t" (hasgh?1:0) }
  /^###[[:space:]]/ {
    flush(); started=1; isdel=0; hasgh=0
    if ($0 ~ /\[(CRITICAL|HIGH|MEDIUM|LOW)\]/) isdel=1
    next
  }
  /^##[[:space:]]/ { flush(); started=0 }
  /\*\*Priority:\*\*/ { isdel=1 }
  /\*\*GH:\*\*/       { hasgh=1 }
  END { flush() }
')"
deliverable_blocks=0
missing_gh=0
if [[ -n "$block_report" ]]; then
  while IFS="$(printf '\t')" read -r isdel hasgh; do
    [[ "$isdel" == "1" ]] || continue
    deliverable_blocks=$((deliverable_blocks+1))
    [[ "$hasgh" == "1" ]] || missing_gh=$((missing_gh+1))
  done <<< "$block_report"
fi
if [[ "$deliverable_blocks" -gt 0 && "$missing_gh" -gt 0 ]]; then
  fail "${missing_gh} deliverable block(s) carry a priority but no **GH:** anchor (seed-anchored-by-issues.md)"
fi

# --- 7. canonical-only WARN checks ---
if [[ "$is_canonical" == "1" ]]; then
  # mesh rows
  mesh_rows="$(printf '%s\n' "$content" | grep -cE '^\|[[:space:]]*[0-9]+[[:space:]]*\|' || true)"
  if [[ "$mesh_rows" -gt 0 && "$mesh_rows" -lt "$MIN_MESH_ROWS" ]]; then
    warn "Phase 0 mesh has ${mesh_rows} row(s) (< ${MIN_MESH_ROWS} recommended)"
  fi
  # at least one CRITICAL/HIGH
  if printf '%s\n' "$content" | grep -qE '\*\*Priority:\*\*|\[(CRITICAL|HIGH|MEDIUM|LOW)\]'; then
    if ! printf '%s\n' "$content" | grep -qE '\[(CRITICAL|HIGH)\]|\*\*Priority:\*\*[[:space:]]*(CRITICAL|HIGH)'; then
      warn "no deliverable ranked CRITICAL or HIGH — confirm this sprint earns a slot"
    fi
  fi
  # recommended frontmatter
  printf '%s\n' "$content" | grep -qE '^milestone:' || warn "frontmatter missing 'milestone:' (engineer + critic parse it)"
  printf '%s\n' "$content" | grep -qE '^kind:'      || warn "frontmatter missing 'kind:' (sprint-seed | patch-seed)"
fi

# --- verdict ---
if [[ "$hard" -gt 0 ]]; then
  emit "FAIL: ${hard} hard failure(s), ${warns} warning(s)"
  exit 1
fi
emit "OK: 0 hard failures, ${warns} warning(s)"
exit 0
