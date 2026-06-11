#!/usr/bin/env bash
# Shared helpers for /shepherd:ctx subcommands.
# Sourced by every script in scripts/. Never executed directly.

set -eu -o pipefail

# Resolve repo root (where shepherd.toml lives).
shctx_repo_root() {
  git rev-parse --show-toplevel 2>/dev/null || pwd
}

# Resolve the project-local work directory. For milestone c we hard-code
# defaults; full TOML parsing is upstreamed into a pluggable parser later.
#
# Precedence:
#   - SHEPHERD_WORKDIR (public, first-class) is honored first. Absolute paths
#     are used as-is; relative paths resolve against the repo root.
#   - SHCTX_ROOT_OVERRIDE (legacy, e.g. `init --artifacts` sets it to ".artifacts").
#   - Otherwise auto-detect: prefer existing .shepherd/, fall back to existing .artifacts/.
#   - If neither exists, default to .shepherd/ (the v5.0.0 default for new init).
resolve_workdir() {
  local root
  root="$(shctx_repo_root)"
  if [[ -n "${SHEPHERD_WORKDIR:-}" ]]; then
    case "$SHEPHERD_WORKDIR" in
      /*) echo "$SHEPHERD_WORKDIR" ;;
      *)  echo "$root/${SHEPHERD_WORKDIR}" ;;
    esac
  elif [[ -n "${SHCTX_ROOT_OVERRIDE:-}" ]]; then
    echo "$root/${SHCTX_ROOT_OVERRIDE}"
  elif [[ -d "$root/.shepherd" ]]; then
    # Warn when both namespaces exist — this is the split-brain state. One of
    # them is unused; shctx picks .shepherd/ by precedence. Run `shctx doctor`
    # for remediation guidance.
    if [[ -d "$root/.artifacts" && -z "${SHCTX_QUIET:-}" ]]; then
      echo "shctx WARNING: both .shepherd/ and .artifacts/ exist in $(basename "$root")." >&2
      echo "  Using .shepherd/ (detected by precedence). Run 'shctx doctor' for details." >&2
    fi
    echo "$root/.shepherd"
  elif [[ -d "$root/.artifacts" ]]; then
    echo "$root/.artifacts"
  else
    echo "$root/.shepherd"
  fi
}
# Retained as the legacy name; delegates to resolve_workdir so all callers
# (and shctx_db_path/shctx_lock_path/shctx_project_id_path) inherit $SHEPHERD_WORKDIR.
shctx_artifacts_root() { resolve_workdir; }
# DB path: prefer shepherd.db (v6.2.0+ standard); fall back to root.db when it
# already exists (legacy projects untouched); default to shepherd.db for new
# projects where neither file is present yet.
shctx_db_path() {
  local wd; wd="$(shctx_artifacts_root)"
  if   [[ -f "$wd/shepherd.db" ]]; then echo "$wd/shepherd.db"
  elif [[ -f "$wd/root.db"     ]]; then echo "$wd/root.db"
  else                                   echo "$wd/shepherd.db"
  fi
}
shctx_lock_path()       { echo "$(shctx_artifacts_root)/shepherd.lock"; }
shctx_project_id_path() { echo "$(shctx_artifacts_root)/project.json"; }
shctx_skill_root()      { echo "${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"; }

# UUIDv7 generator (timestamp-prefixed, sortable). Portable across BSD (macOS)
# and GNU (Linux) date; falls back to python3 then to seconds-precision if
# millisecond `+%s%3N` is unavailable.
shctx_uuid7() {
  local ts hi rand a b c d e
  ts=$(date +%s%3N 2>/dev/null || true)
  if [[ -z "$ts" || "$ts" == *N* ]]; then
    if command -v gdate >/dev/null 2>&1; then
      ts=$(gdate +%s%3N)
    elif command -v python3 >/dev/null 2>&1; then
      ts=$(python3 -c 'import time;print(int(time.time()*1000))')
    else
      ts=$(( $(date +%s) * 1000 ))
    fi
  fi
  hi=$(printf '%012x' "$ts")
  rand=$(od -An -tx1 -N10 /dev/urandom | tr -d ' \n')
  a=${hi:0:8}; b=${hi:8:4}
  c="7${rand:0:3}"
  d=$(printf '%04x' $((0x8000 | 0x${rand:3:3}0)))
  e=${rand:6:12}
  echo "${a}-${b}-${c}-${d:0:4}-${e}"
}

# Lookup the host project_id. Errors if project.json missing in the active namespace.
shctx_project_id() {
  local p; p=$(shctx_project_id_path)
  if [[ ! -f "$p" ]]; then
    echo "ERROR: $p missing — run 'shctx init' first" >&2
    return 1
  fi
  jq -r '.id' "$p"
}

# Run sqlite3 against the project DB.
shctx_sql() {
  sqlite3 -bail "$(shctx_db_path)" "$@"
}

# Now-epoch (seconds).
shctx_now() { date +%s; }

# Cross-lib compatibility shims (v5.1.8) — cmd_discovery.sh and any future
# cmd_*.sh that get invoked via bare `bash` (not via shctx wrapper) source
# THIS lib, not hooks/scripts/_lib.sh. These shims expose the helper names
# expected by such scripts so direct invocation does not fail with
# `command not found`.

# Delegates to shctx_artifacts_root. SHCTX_QUIET=1 suppresses the
# split-brain warning emitted when both .shepherd/ and .artifacts/ exist
# (the shim is invoked on every cmd dispatch and would otherwise be noisy).
resolve_namespace() {
  SHCTX_QUIET=1 shctx_artifacts_root
}

# Echo the current sprint branch name (or "unknown"). Mirrors the
# hooks-lib helper of the same name.
current_sprint() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown'
}

# gh wrapper with retry on transient failures (504/502/503/timeout).
# Usage: shctx_gh_retry <gh args...>
# v5.0.4 — addresses v5.0.3 feedback §8 (refresh-github + close-lane took
# intermittent 504s during high-traffic GH periods).
shctx_gh_retry() {
  local max_attempts="${SHCTX_GH_RETRY_MAX:-3}"
  local backoff_base="${SHCTX_GH_RETRY_BACKOFF:-2}"
  local attempt=1 rc=0 out=""
  while (( attempt <= max_attempts )); do
    if out=$(gh "$@" 2>&1); then
      printf '%s' "$out"
      return 0
    fi
    rc=$?
    case "$out" in
      *"HTTP 504"*|*"HTTP 502"*|*"HTTP 503"*|*"timeout"*|*"timed out"*|*"connection reset"*)
        if (( attempt < max_attempts )); then
          local sleep_for=$(( backoff_base ** attempt ))
          echo "shctx_gh_retry: transient failure (attempt $attempt/$max_attempts); retrying in ${sleep_for}s..." >&2
          sleep "$sleep_for"
          attempt=$((attempt + 1))
          continue
        fi
        ;;
      *)
        # Non-transient failure — fail fast.
        printf '%s' "$out" >&2
        return "$rc"
        ;;
    esac
    attempt=$((attempt + 1))
  done
  echo "shctx_gh_retry: exhausted $max_attempts attempts; last output:" >&2
  printf '%s\n' "$out" >&2
  return "$rc"
}
