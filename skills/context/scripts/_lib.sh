#!/usr/bin/env bash
# Shared helpers for /shepherd:ctx subcommands.
# Sourced by every script in scripts/. Never executed directly.

set -eu -o pipefail

# Resolve repo root (where shepherd.toml + the shared registry live).
#
# CRITICAL (#221): the shepherd registry (SQLite DB) and config are shared
# per-repo across ALL worktrees. `git rev-parse --show-toplevel` returns the
# CURRENT worktree's root, so from a linked worktree — every concurrent
# conductor lane under `/shepherd:spawn` — it resolved to that worktree's own
# checked-out tree. The namespace dir (.shepherd/.artifacts) is a git-TRACKED
# subtree so it exists in every worktree checkout, while the DB file is
# gitignored (absent); resolve_workdir then picked the worktree-local namespace,
# shctx_db_path targeted a never-created DB there, and the first query
# auto-vivified a 0-byte, schema-less shepherd.db (ensure_migrated's fast path
# bails on a DB with no schema_versions row) — the field "no such table:
# focus/teammates". Resolve to the MAIN worktree via --git-common-dir (which
# points at the shared .git even from a linked worktree); its parent is the main
# worktree root. Mirrors the proven hooks/scripts/_lib.sh:sprint_root pattern
# (the two libs are deliberately not cross-sourced).
#
# DF-72 (v6.4.5 dogfood): `git rev-parse` is the ONLY anchor this function
# ever tried, so a tree with no reachable `.git` (an installed plugin copy
# whose `.git` was stripped for distribution, or a `git` binary that is
# simply absent from PATH) fell straight through to bare `pwd` — trusting
# whatever the caller's cwd happened to be, exactly the "resolves relative to
# the current directory instead of walking up" failure mode this row
# describes. Before giving up, walk up from cwd looking for the plugin
# manifest (`.claude-plugin/plugin.json`) — the same anchor
# `shepherd_cli.commands.{release,doctor}` already treat as the plugin/repo
# root marker, so this recognizes the identical root a git checkout's own
# `.git` would have. Purely additive: when neither `.git` nor the manifest is
# found anywhere above cwd, this still falls through to the exact same `pwd`
# it has always returned outside a repo — the "not inside a repo" behavior is
# unchanged.
shctx_repo_root() {
  local common main
  common="$(git rev-parse --git-common-dir 2>/dev/null || true)"
  if [[ -n "$common" ]]; then
    case "$common" in /*) : ;; *) common="$(pwd)/$common" ;; esac
    main="$(cd "$(dirname "$common")" 2>/dev/null && pwd || true)"
    [[ -n "$main" ]] && { printf '%s\n' "$main"; return 0; }
  fi
  local top
  top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  [[ -n "$top" ]] && { printf '%s\n' "$top"; return 0; }
  local dir
  dir="$(pwd)"
  while [[ -n "$dir" && "$dir" != "/" ]]; do
    [[ -f "$dir/.claude-plugin/plugin.json" ]] && { printf '%s\n' "$dir"; return 0; }
    dir="$(dirname "$dir")"
  done
  pwd
}

# True when the cwd is inside a LINKED worktree (not the primary). The shared
# registry still resolves to the main worktree via shctx_repo_root; this is the
# signal `shctx doctor` uses to surface that scoping to the operator (#221).
# Port of hooks/scripts/_lib.sh:in_subworktree (libs are not cross-sourced).
shctx_in_subworktree() {
  local git_dir git_common
  git_dir="$(git rev-parse --git-dir 2>/dev/null)" || return 1
  git_common="$(git rev-parse --git-common-dir 2>/dev/null)" || return 1
  [[ -n "$git_dir" && "$git_dir" != "$git_common" ]]
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
# DB path: prefer shepherd.db (v6.1.2+ standard); fall back to root.db when it
# already exists (legacy projects untouched); default to shepherd.db for new
# projects where neither file is present yet.
shctx_db_path() {
  # Explicit override (SHCTX_DB) wins over namespace auto-detection, so tests and
  # tooling that point at a specific DB file resolve to the SAME path everywhere —
  # including the self-heal helpers (shctx_ensure_migrated), which would otherwise
  # heal the auto-detected DB while a command queried the override (v6.3.3 #200).
  if [[ -n "${SHCTX_DB:-}" ]]; then echo "$SHCTX_DB"; return 0; fi
  local wd; wd="$(shctx_artifacts_root)"
  if   [[ -f "$wd/shepherd.db" ]]; then echo "$wd/shepherd.db"
  elif [[ -f "$wd/root.db"     ]]; then echo "$wd/root.db"
  else                                   echo "$wd/shepherd.db"
  fi
}
shctx_lock_path()       { echo "$(shctx_artifacts_root)/shepherd.lock"; }
shctx_project_id_path() { echo "$(shctx_artifacts_root)/project.json"; }
# Skill root = the directory that contains schema/ + references/ + scripts/
# (i.e. .../skills/context). The dispatcher exports the correct value in
# SHCTX_SKILL_ROOT (shctx:5); prefer it. When sourced outside the dispatcher with
# CLAUDE_PLUGIN_ROOT set, the skill root is "$CLAUDE_PLUGIN_ROOT/skills/context"
# — NOT bare $CLAUDE_PLUGIN_ROOT (the plugin/repo root), which has no references/
# dir and silently broke `shctx init`/`config init` in real plugin installs (the
# cp in scaffold.sh aborts under `set -e`, so the DB is never created). Final
# fallback is this file's own location (dev symlink / direct-source path).
shctx_skill_root() {
  if   [[ -n "${SHCTX_SKILL_ROOT:-}" ]]; then echo "$SHCTX_SKILL_ROOT"
  elif [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then echo "$CLAUDE_PLUGIN_ROOT/skills/context"
  else echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
}

# The active harness id, or "" when none can be determined. SHEPHERD_HARNESS
# is explicit and always wins; otherwise Claude Code's own markers, then
# CODEX_HOME. Only the ACTIVE harness's config file is read -- reading every
# harness file would let a codex knob take effect under Claude Code, which is
# the opposite of what a per-harness layer is for.
# MUST mirror shepherd_cli/commands/config.py::resolve_harness.
shctx_harness() {
  if [[ -n "${SHEPHERD_HARNESS:-}" ]]; then printf '%s' "$SHEPHERD_HARNESS"; return 0; fi
  if [[ -n "${CLAUDECODE:-}" || -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then printf '%s' "claude"; return 0; fi
  if [[ -n "${CODEX_HOME:-}" ]]; then printf '%s' "codex"; return 0; fi
  printf '%s' ""
  return 0
}

# Echo the shepherd config precedence chain, one absolute path per line,
# HIGHEST precedence first (v6.4.2 layering contract).
#
#   project  <ns>/shepherd.local.toml          <- ultimate override
#            <ns>/shepherd.<harness>.toml
#            <ns>/shepherd.toml                <- the project binding
#   legacy   .claude/shepherd.local.toml       <- pre-v6.4.2, honored forever
#            .claude/shepherd.toml
#   user     ~/.shepherd/shepherd.local.toml   <- cross-project DEFAULTS
#            ~/.shepherd/shepherd.<harness>.toml
#            ~/.shepherd/shepherd.toml
#            $XDG_CONFIG_HOME/shepherd.toml    <- pre-v6.4.2 global
#
# Within a layer: local > harness > base. Across layers: project > user.
# The legacy .claude/ tiers are PROJECT files, so they outrank the whole user
# layer -- otherwise creating ~/.shepherd/shepherd.toml would silently
# override every existing project still bound through .claude/.
# *.local.toml is gitignored (one machine); shepherd.<harness>.toml is TRACKED.
#
# Single source of truth for this lib. MUST stay byte-identical to the other
# _lib.sh's shctx_config_files and to
# shepherd_cli/commands/config.py::_config_search_paths.
# Contract: docs/configuration.md §config-resolution.
shctx_config_files() {
  local repo ns userhome harness
  repo="$(shctx_repo_root 2>/dev/null || pwd)"
  ns="$(SHCTX_QUIET=1 resolve_workdir 2>/dev/null || printf '%s/.shepherd' "$repo")"
  userhome="${SHEPHERD_HOME:-$HOME/.shepherd}"
  harness="$(shctx_harness)"

  # project layer (highest): local -> harness -> base
  printf '%s\n' "$ns/shepherd.local.toml"
  if [[ -n "$harness" ]]; then printf '%s\n' "$ns/shepherd.$harness.toml"; fi
  printf '%s\n' "$ns/shepherd.toml"
  # legacy project layer -- pre-v6.4.2, honored indefinitely
  printf '%s\n' "$repo/.claude/shepherd.local.toml"
  printf '%s\n' "$repo/.claude/shepherd.toml"
  # user layer (defaults): local -> harness -> base
  printf '%s\n' "$userhome/shepherd.local.toml"
  if [[ -n "$harness" ]]; then printf '%s\n' "$userhome/shepherd.$harness.toml"; fi
  printf '%s\n' "$userhome/shepherd.toml"
  # legacy user global
  printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/shepherd.toml"
  return 0
}

# Echo the value of a top-level `key = value` from shepherd config, resolved by
# precedence: the shctx_config_files chain above (namespace local/project →
# legacy .claude local/project → XDG user global).
# Section-agnostic, last-match-wins within a file; strips surrounding double-quotes
# and trailing " # inline comments". Echoes "" if unset; never returns non-zero
# (safe under this lib's `set -eu -o pipefail`). MUST mirror the hooks-side cfg_get
# (hooks/scripts/_lib.sh) — same files, same order — or config diverges between
# the shctx runtime and the hooks. Contract: docs/configuration.md §config-resolution.
cfg_get() {
  local key="$1" repo f v
  repo="$(shctx_repo_root 2>/dev/null || pwd)"
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    v="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$f" 2>/dev/null | tail -1 \
          | sed -E 's/^[^=]*=[[:space:]]*//; s/[[:space:]]+#.*$//; s/^"//; s/"$//' 2>/dev/null || true)"
    if [[ -n "$v" ]]; then printf '%s' "$v"; return 0; fi
  done < <(shctx_config_files)
  printf '%s' ""
  return 0
}

# Echo the value of `key = value` under a specific `[section]` from shepherd
# config, resolved by the SAME precedence as cfg_get (local → project → XDG).
# Section-aware companion to cfg_get for TOML blocks whose bare keys would
# otherwise collide across sections (e.g. [models] role keys like `conductor`).
# Last-match-wins within the section of a given file; strips surrounding
# double-quotes and a trailing " # inline comment". Echoes "" if unset; never
# returns non-zero (safe under `set -eu -o pipefail`). bash-3.2-safe — awk does
# the section parsing (no associative arrays / mapfile). MUST mirror the
# hooks-side cfg_section_get (hooks/scripts/_lib.sh). Contract source of truth:
# docs/configuration.md §config-resolution.
cfg_section_get() {
  local section="$1" key="$2" repo f v
  repo="$(shctx_repo_root 2>/dev/null || pwd)"
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    v="$(awk -v sect="$section" -v k="$key" '
      /^[ \t]*\[/ { h=$0; sub(/^[ \t]*\[/,"",h); sub(/\].*$/,"",h); gsub(/[ \t]/,"",h); cur=h; next }
      cur==sect && $0 ~ ("^[ \t]*" k "[ \t]*=") {
        val=$0; sub(/^[^=]*=[ \t]*/,"",val); sub(/[ \t]+#.*$/,"",val);
        sub(/^"/,"",val); sub(/"$/,"",val); result=val
      }
      END { if (result!="") printf "%s", result }
    ' "$f" 2>/dev/null || true)"
    if [[ -n "$v" ]]; then printf '%s' "$v"; return 0; fi
  done < <(shctx_config_files)
  printf '%s' ""
  return 0
}

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

# ── schema migrations (v6.3.3 #200 — self-heal) ─────────────────────────────
# Apply every migration whose 4-digit version is ABSENT from schema_versions
# (gap-fill — repairs a DB that skipped an out-of-place or half-applied migration,
# not merely one below MAX(version)). Progress is written to STDERR; the number of
# migrations applied is echoed to STDOUT as the sole stdout line, so a caller can
# capture the count without swallowing progress. Concurrency-tolerant: if a
# sibling process applied a migration between our absence-check and our write,
# sqlite reports "duplicate column" / "already exists" — treat that as
# already-applied rather than aborting (the schema_versions row is still recorded,
# INSERT OR IGNORE). Any OTHER sqlite error is a hard failure (non-zero return).
# Single source of truth for the apply loop — cmd_migrate.sh and
# shctx_ensure_migrated both call this.
shctx_apply_pending_migrations() {
  local migdir db f fname num v sum applied=0 out
  migdir="$(shctx_skill_root)/schema/migrations"
  db="$(shctx_db_path)"
  if [[ ! -d "$migdir" || ! -f "$db" ]]; then echo 0; return 0; fi
  local had_nullglob=0; shopt -q nullglob && had_nullglob=1; shopt -s nullglob
  for f in "$migdir"/[0-9][0-9][0-9][0-9]_*.sql; do
    fname="$(basename "$f")"; num="${fname:0:4}"; v=$((10#$num))
    [[ -z "$(sqlite3 "$db" "SELECT 1 FROM schema_versions WHERE version=$v LIMIT 1;" 2>/dev/null)" ]] || continue
    echo "shctx migrate: applying $fname" >&2
    sum="$(shasum -a 256 "$f" 2>/dev/null | awk '{print $1}')"
    if ! out="$({ echo "PRAGMA busy_timeout=5000;"; cat "$f"; } | sqlite3 "$db" 2>&1)"; then
      case "$out" in
        *"duplicate column"*|*"already exists"*) : ;;  # sibling already applied it
        *) echo "shctx migrate: ERROR applying $fname: $out" >&2
           (( had_nullglob )) || shopt -u nullglob
           echo "$applied"; return 1 ;;
      esac
    fi
    sqlite3 -cmd ".timeout 5000" "$db" \
      "INSERT OR IGNORE INTO schema_versions (version, applied_at, checksum) VALUES ($v, $(shctx_now), '$sum');" 2>/dev/null || true
    applied=$((applied+1))
  done
  (( had_nullglob )) || shopt -u nullglob
  echo "$applied"
}

# Idempotent, cheap schema self-heal (v6.3.3 #200). Ensures the project DB is at
# the shipped HEAD schema before a caller reads a recent column. Root cause of
# #200: `shctx init` seeds only 0001 and migrations are applied by a SEPARATE
# `shctx migrate`, so a DB from an older plugin (or one left half-migrated by the
# 0017 abort) lags the code — `SELECT declared_state` then fails with
# "no such column". Calling this at the top of a stateful command closes that gap
# structurally: the schema can no longer drift out from under the query.
#
# FAST path (DB already current): one MAX + one COUNT over schema_versions plus a
# dir listing — near-zero cost, safe on every invocation. When behind, auto-applies
# the missing migrations. Fail-soft by contract: missing DB, absent sqlite3, or an
# unreadable/locked schema_versions returns 0 without aborting the caller (which
# carries its own column-exists degradation as the final backstop). Never let this
# take down a command under `set -e`.
shctx_ensure_migrated() {
  command -v sqlite3 >/dev/null 2>&1 || return 0
  local migdir db
  migdir="$(shctx_skill_root)/schema/migrations"
  db="$(shctx_db_path)"
  [[ -d "$migdir" && -f "$db" ]] || return 0
  # Shipped HEAD: highest version + count of migration files.
  local shipped_cnt=0 shipped_max=0 f num v
  local had_nullglob=0; shopt -q nullglob && had_nullglob=1; shopt -s nullglob
  for f in "$migdir"/[0-9][0-9][0-9][0-9]_*.sql; do
    num="$(basename "$f")"; num="${num:0:4}"; v=$((10#$num))
    shipped_cnt=$((shipped_cnt+1)); (( v > shipped_max )) && shipped_max=$v
  done
  (( had_nullglob )) || shopt -u nullglob
  (( shipped_cnt > 0 )) || return 0
  local applied_max applied_cnt
  applied_max="$(sqlite3 "$db" "SELECT COALESCE(MAX(version),0) FROM schema_versions;" 2>/dev/null || echo -1)"
  [[ "$applied_max" =~ ^-?[0-9]+$ ]] || return 0
  (( applied_max < 0 )) && return 0   # couldn't read schema_versions → let caller degrade
  applied_cnt="$(sqlite3 "$db" "SELECT COUNT(*) FROM schema_versions;" 2>/dev/null || echo 0)"
  [[ "$applied_cnt" =~ ^[0-9]+$ ]] || applied_cnt=0
  # Up-to-date iff we reached the top version AND applied at least as many rows as
  # shipped (the count catches a GAP a middle migration left, even when max is
  # current). Otherwise heal — best-effort, fail-soft.
  if (( applied_max >= shipped_max && applied_cnt >= shipped_cnt )); then
    return 0
  fi
  shctx_apply_pending_migrations >/dev/null 2>&1 || true
  return 0
}

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
