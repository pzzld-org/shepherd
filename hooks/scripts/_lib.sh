#!/usr/bin/env bash
# shepherd hooks — shared library
#
# Sourced by every hook script. Exports:
#
#   is_shepherd_project              — returns 0 for a canonical project config
#   resolve_namespace                — echoes <primary-worktree>/.shepherd
#   shepherd_config_files            — echoes the canonical 4/6 config candidates
#   emit_context "<msg>"             — emit {"additionalContext":"<msg>"} and exit 0
#   emit_deny "<msg>"                — emit {"permissionDecision":"deny","message":"<msg>"} and exit 0
#   log_event hook decision tool role session fields_json
#                                    — append one JSONL entry to <active-run>/events/hooks-YYYY-MM-DD.jsonl
#   primary_worktree_root            — echo Git's primary checkout root for this worktree
#   primary_active_run_dir           — echo the primary checkout's active run directory
#   json_field input "<field>"       — extract scalar from JSON stdin via jq
#   shepherd_cli                       — echo the installed canonical native `shepherd` binary, or fail
#
# All emit_* functions log_event before emitting JSON. Log failures are silent.
#
# This library does NOT set `set -euo pipefail` — sourcing scripts decide.

# Hooks are host adapters, never a second CLI distribution. Resolve the one
# operator-installed native binary from PATH. Callers must fail open when the
# binary is absent unless their own hook contract explicitly blocks.
shepherd_cli() {
  command -v shepherd 2>/dev/null
}

# Source-tree hooks are development-only host adapters. They use jq for JSON;
# the packaged Claude adapter uses Node plus the native component instead.
# Never add a Python parser fallback: it would create a hidden second runtime
# whose behavior is neither shipped nor covered by the component contract.
shepherd_jq_available() {
  command -v jq >/dev/null 2>&1
}

# PreToolUse policy hooks call this immediately after their project gate. A
# policy that cannot parse a harness payload cannot safely allow it, so this
# emits a complete Claude denial directly (without depending on emit_deny,
# which itself serializes through jq) and returns non-zero for shell callers.
shepherd_require_jq_policy() {
  shepherd_jq_available && return 0
  printf '%s\n' '{"permissionDecision":"deny","message":"[shepherd] jq is required to evaluate this source-tree policy hook; refusing the action until the parser dependency is available."}'
  return 1
}

# Telemetry must not become enforcement merely because its optional parser is
# absent. It skips with a diagnostic, making the missing evidence visible
# without fabricating a policy verdict.
shepherd_skip_without_jq() {
  local hook="${1:-telemetry}"
  shepherd_jq_available && return 0
  printf '[shepherd] %s skipped: jq parser unavailable\n' "$hook" >&2
  return 1
}

# The active harness id, or "" when none can be determined. SHEPHERD_HARNESS
# is explicit and always wins; otherwise Claude Code's own markers, then
# CODEX_HOME. Only the ACTIVE harness's config file is read -- reading every
# harness file would let a codex knob take effect under Claude Code, which is
# the opposite of what a per-harness layer is for.
# MUST mirror crates/cli/src/context.rs::resolve_environment_harness.
shepherd_harness() {
  if [[ -n "${SHEPHERD_HARNESS:-}" ]]; then printf '%s' "$SHEPHERD_HARNESS"; return 0; fi
  if [[ -n "${CLAUDECODE:-}" || -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then printf '%s' "claude"; return 0; fi
  if [[ -n "${CODEX_HOME:-}" ]]; then printf '%s' "codex"; return 0; fi
  printf '%s' ""
  return 0
}

# Echo the Rust loader's canonical config candidates, highest priority first.
#
#   project  <primary>/.shepherd/shepherd.local.toml
#            <primary>/.shepherd/shepherd.<harness>.toml
#            <primary>/.shepherd/shepherd.toml
#   user     $SHEPHERD_HOME/shepherd.local.toml
#            $SHEPHERD_HOME/shepherd.<harness>.toml
#            $SHEPHERD_HOME/shepherd.toml
#
# Within a layer: local > harness > base. Across layers: project > user.
# This is a read-only host adapter for `shepherd_core::loader::candidates`.
# Migration-only legacy paths never participate in ordinary hook resolution.
shepherd_config_files() {
  local repo="${1:-.}" ns userhome harness
  ns="$(resolve_namespace "$repo" 2>/dev/null || true)"
  [[ -n "$ns" ]] || return 0
  repo="$(primary_worktree_root "$repo" 2>/dev/null || true)"
  [[ -n "$repo" ]] || return 0
  userhome="${SHEPHERD_HOME:-${HOME:-}/.shepherd}"
  case "$userhome" in
    /*) ;;
    *) userhome="$repo/$userhome" ;;
  esac
  if [[ -d "$userhome" ]]; then
    userhome="$(cd "$userhome" 2>/dev/null && pwd -P || printf '%s' "$userhome")"
  fi
  harness="$(shepherd_harness)"

  # project layer (highest): local -> harness -> base
  printf '%s\n' "$ns/shepherd.local.toml"
  if [[ -n "$harness" ]]; then printf '%s\n' "$ns/shepherd.$harness.toml"; fi
  printf '%s\n' "$ns/shepherd.toml"
  # user layer (defaults): local -> harness -> base
  if [[ "$userhome" != "$ns" ]]; then
    printf '%s\n' "$userhome/shepherd.local.toml"
    if [[ -n "$harness" ]]; then printf '%s\n' "$userhome/shepherd.$harness.toml"; fi
    printf '%s\n' "$userhome/shepherd.toml"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

# True only when the primary worktree has the canonical project config.
is_shepherd_project() {
  local ns
  ns="$(resolve_namespace 2>/dev/null || true)"
  [[ -n "$ns" && -f "$ns/shepherd.toml" ]]
}

# Echo the one canonical project namespace for a primary worktree. It is not
# configurable at runtime: allowing per-hook environment redirects causes
# split-brain dispatch, lock, and memory state.
resolve_namespace() {
  local primary
  primary="$(primary_worktree_root "${1:-.}" 2>/dev/null || true)"
  [[ -n "$primary" ]] || return 1
  printf '%s/.shepherd' "$primary"
}

# Echo the primary checkout root shared by the current Git worktree. A linked
# worktree's `.git` is a file under the primary checkout, while the primary
# checkout itself has a `.git` directory. Resolve Git's common directory from
# the current repository root so a relative `.git` is never accidentally
# interpreted below an arbitrary subdirectory. Outside Git, the current
# repository fallback is the only available root.
primary_worktree_root() {
  local start="${1:-.}" repo common root
  repo="$(git -C "$start" rev-parse --show-toplevel 2>/dev/null || true)"
  [[ -n "$repo" ]] || repo="$(cd "$start" 2>/dev/null && pwd -P || pwd)"
  common="$(git -C "$repo" rev-parse --git-common-dir 2>/dev/null || true)"
  if [[ -z "$common" ]]; then
    printf '%s' "$repo"
    return 0
  fi
  case "$common" in
    /*) ;;
    *) common="$repo/$common" ;;
  esac
  root="$(cd "$(dirname "$common")" 2>/dev/null && pwd || true)"
  if [[ -n "$root" ]]; then
    printf '%s' "$root"
  else
    printf '%s' "$repo"
  fi
  return 0
}

# Registry DB path inside the canonical namespace. Migration is the only
# compatibility boundary for retired database names; ordinary hooks never read
# another database authority.
hook_db_path() {
  local ns="${1:-$(resolve_namespace 2>/dev/null || echo .shepherd)}"
  printf '%s/shepherd.db' "$ns"
}

# Echo the value of a top-level `key = value` from shepherd config, resolved by
# shepherd_config_files precedence: project local/harness/base, then user
# local/harness/base. Section-agnostic, last-match-wins within a file; strips surrounding
# double-quotes and trailing " # inline comments". Echoes "" if the key is
# unset everywhere. bash-3.2-safe (no TOML parser) and never returns non-zero,
# so it is safe to call under `set -e`/pipefail.
# Contract source of truth: docs/configuration.md §config-resolution. MUST agree
# with `shepherd_core::loader::candidates` — the same files in the same order.
cfg_get() {
  local key="$1" f v
  while IFS= read -r f; do
    [[ -n "$f" && -f "$f" ]] || continue
    v="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$f" 2>/dev/null | tail -1 \
          | sed -E 's/^[^=]*=[[:space:]]*//; s/[[:space:]]+#.*$//; s/^"//; s/"$//' 2>/dev/null || true)"
    if [[ -n "$v" ]]; then printf '%s' "$v"; return 0; fi
  done < <(shepherd_config_files)
  printf '%s' ""
  return 0
}

# Section-aware companion to cfg_get: echo `key = value` under a specific
# `[section]` from shepherd config, resolved by the SAME precedence
# (shepherd_config_files: project local/harness/base → user local/harness/base).
# For TOML blocks whose bare keys would collide across
# sections (e.g. [models] role keys). Last-match-wins within the section;
# strips surrounding double-quotes and a trailing " # inline comment". Echoes
# "" if unset; never returns non-zero. bash-3.2-safe (awk parses the section —
# no associative arrays / mapfile). An optional third
# argument pins config discovery to an explicit repository root for the
# linked-worktree canonical dispatch reader. Contract source of truth:
# docs/configuration.md §config-resolution.
cfg_section_get() {
  local section="$1" key="$2" repo="${3:-}" f v
  while IFS= read -r f; do
    [[ -n "$f" && -f "$f" ]] || continue
    v="$(awk -v sect="$section" -v k="$key" '
      /^[ \t]*\[/ { h=$0; sub(/^[ \t]*\[/,"",h); sub(/\].*$/,"",h); gsub(/[ \t]/,"",h); cur=h; next }
      cur==sect && $0 ~ ("^[ \t]*" k "[ \t]*=") {
        val=$0; sub(/^[^=]*=[ \t]*/,"",val); sub(/[ \t]+#.*$/,"",val);
        sub(/^"/,"",val); sub(/"$/,"",val); result=val
      }
      END { if (result!="") printf "%s", result }
    ' "$f" 2>/dev/null || true)"
    if [[ -n "$v" ]]; then printf '%s' "$v"; return 0; fi
  done < <(shepherd_config_files "$repo")
  printf '%s' ""
  return 0
}

# List the KEYS of a `[section]` block across the shepherd config precedence
# (shepherd_config_files), one per line, union'ed with first-seen wins —
# the enumeration companion to cfg_section_get (which needs a known key).
# Used by the #59 gates ledger to walk `[gates.extra]` entries whose names are
# project-defined. bash-3.2-safe; never returns non-zero.
cfg_section_keys() {
  local section="$1" f out="" k
  while IFS= read -r f; do
    [[ -n "$f" && -f "$f" ]] || continue
    while IFS= read -r k; do
      [[ -n "$k" ]] || continue
      case $'\n'"$out" in *$'\n'"$k"$'\n'*) ;; *) out+="$k"$'\n' ;; esac
    done < <(awk -v sect="$section" '
      /^[ \t]*\[/ { h=$0; sub(/^[ \t]*\[/,"",h); sub(/\].*$/,"",h); gsub(/[ \t]/,"",h); cur=h; next }
      cur==sect && /^[ \t]*[A-Za-z0-9_-]+[ \t]*=/ {
        key=$0; sub(/^[ \t]*/,"",key); sub(/[ \t]*=.*$/,"",key); print key
      }
    ' "$f" 2>/dev/null || true)
  done < <(shepherd_config_files)
  printf '%s' "$out"
  return 0
}

# ---------------------------------------------------------------------------
# Run-scoped artifact layout (v6.4.1 — .shepherd/runs/{run}/)
# ---------------------------------------------------------------------------

# The [paths]-aware runs root: `[paths].runs` from config (repo-relative unless
# absolute), else `<namespace>/runs` — the same default used by the native
# `shepherd run` surface.
# An optional repository root pins both config discovery and relative-path
# resolution to that root for the linked-worktree primary retry.
runs_root_dir() {
  local repo="${1:-}" cfg
  repo="$(primary_worktree_root "${repo:-.}" 2>/dev/null || pwd)"
  cfg="$(cfg_section_get paths runs "$repo" 2>/dev/null || true)"
  if [[ -n "$cfg" ]]; then
    case "$cfg" in /*) printf '%s' "$cfg" ;; *) printf '%s' "$repo/$cfg" ;; esac
  else
    printf '%s' "$(resolve_namespace "$repo")/runs"
  fi
  return 0
}

# True only when run.json is one strict JSON document whose top-level value is
# an object and whose status is the exact string "executing". jq slurps every
# document; without jq this function returns false rather than introducing a
# second JSON runtime.
active_run_document_is_executing() {
  local f="$1"
  [[ -f "$f" && ! -L "$f" ]] || return 1
  shepherd_jq_available || return 1
  jq -e -s '
    length == 1
    and (.[0] | type == "object")
    and (.[0].status | type == "string" and . == "executing")
  ' "$f" >/dev/null 2>&1
}

# This decision reads run.json directly. One strict JSON object with a
# top-level status string exactly equal to "executing" is active; JSON streams,
# arrays, scalars, and status values with any trailing byte are inactive.
# The jq structural check is the one parser contract for source-tree hooks.
active_run_dir() {
  local root="${1:-}" f
  [[ -n "$root" ]] || root="$(runs_root_dir 2>/dev/null || true)"
  [[ -d "$root" ]] || return 0
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    if active_run_document_is_executing "$f"; then
      printf '%s' "$(dirname "$f")"
      return 0
    fi
  done < <(ls -1t "$root"/*/run.json 2>/dev/null || true)
  return 0
}

# Canonical dispatch records are owned by the primary worktree's active run.
# Calling this shared resolver from both the writer and reader prevents a
# copied linked-worktree namespace from becoming a competing record store.
primary_active_run_dir() {
  local primary_root runs_root
  primary_root="$(primary_worktree_root 2>/dev/null || true)"
  [[ -n "$primary_root" ]] || return 0
  runs_root="$(runs_root_dir "$primary_root" 2>/dev/null || true)"
  [[ -n "$runs_root" ]] || return 0
  active_run_dir "$runs_root"
}

# ---------------------------------------------------------------------------
# JSON extraction (jq only)
# ---------------------------------------------------------------------------

# Usage: json_field "$input_json" '.tool_input.command'
# Echoes the field value (empty string if absent OR if the JSON is malformed —
# fail-open with rc 0 so a sourcing `set -e` hook never dies on bad input, the
# same contract json_response already guarantees).
json_field() {
  local input="$1" path="$2"
  shepherd_jq_available || { printf '%s' ""; return 0; }
  printf '%s' "$input" | jq -r "$path // empty" 2>/dev/null || true
}

# Extract the tool_response (which varies — string, dict.content, dict.text, or list).
# Usage: json_response "$input_json"
#
# v6.0.0: jq queries use `?` after each property access to suppress
# "Cannot index string with X" errors when tool_response is itself a string
# (jq rc=5). Without `?`, callers under `set -e` exit with code 5 on string
# tool_responses. The function additionally returns 0 unconditionally so a
# jq failure surfaces as an empty response, not a propagated exit.
json_response() {
  local input="$1"
  shepherd_jq_available || { printf '%s' ""; return 0; }
  printf '%s' "$input" | jq -r '
    (.tool_response.content? // .tool_response.text? // .tool_response // empty)
    | if type == "array" then map(.text? // .) | join("\n") else . end' 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# JSON emission
# ---------------------------------------------------------------------------

# Usage: emit_json_obj key1 val1 key2 val2 ...
# Echoes a single-line JSON object. Used by emit_context / emit_deny.
emit_json_obj() {
  if shepherd_jq_available; then
    local args=() i=0
    while [[ $# -gt 0 ]]; do
      args+=(--arg "k$i" "$1")
      args+=(--arg "v$i" "$2")
      i=$((i+1))
      shift 2
    done
    local jq_filter=""
    for ((j=0; j<i; j++)); do
      [[ -n "$jq_filter" ]] && jq_filter+=" + "
      jq_filter+="{ (\$k$j): \$v$j }"
    done
    jq -nc "${args[@]}" "$jq_filter"
  else
    return 1
  fi
}

# Returns 0 if the canonical config resolves `quiet_warnings = true` under
# `[hooks]`. Used by emit_context to suppress informational additionalContext
# emissions for operators who find them noisy in the UI (issue #19, v5.1.8+).
# Default: false (preserve v5.1.7 and prior behavior — warnings visible).
# Cheap grep — no TOML parser needed; the key is unique enough.
quiet_warnings() {
  [[ "$(cfg_get quiet_warnings)" == "true" ]]
}

# Emit an additionalContext warning and exit 0.
# Usage: emit_context "<msg>" [hook_name] [tool] [role] [session_id]
# The optional fields are for log_event; if omitted, log_event is skipped.
# When [hooks].quiet_warnings = true in shepherd.toml, the additionalContext
# JSON is suppressed (log_event still fires); operators can inspect the
# active run's `events/hooks-YYYY-MM-DD.jsonl` to recover the warning text.
emit_context() {
  local msg="$1" hook="${2:-}" tool="${3:-}" role="${4:-unknown}" session="${5:-}"
  [[ -n "$hook" ]] && log_event "$hook" "warn" "$tool" "$role" "$session" "$(emit_json_obj reason "$msg")"
  if quiet_warnings; then
    exit 0
  fi
  emit_json_obj additionalContext "$msg"
  exit 0
}

# Emit a permissionDecision:deny and exit 0.
# Usage: emit_deny "<msg>" [hook_name] [tool] [role] [session_id]
emit_deny() {
  local msg="$1" hook="${2:-}" tool="${3:-}" role="${4:-unknown}" session="${5:-}"
  [[ -n "$hook" ]] && log_event "$hook" "deny" "$tool" "$role" "$session" "$(emit_json_obj reason "$msg")"
  emit_json_obj permissionDecision "deny" message "$msg"
  exit 0
}

# Emit nothing, just exit 0 with optional log.
# Usage: pass_silent [hook_name] [tool] [role] [session_id] [fields_json]
pass_silent() {
  local hook="${1:-}" tool="${2:-}" role="${3:-unknown}" session="${4:-}" fields="${5:-}"
  [[ -n "$fields" ]] || fields='{}'
  [[ -n "$hook" ]] && log_event "$hook" "pass" "$tool" "$role" "$session" "$fields"
  exit 0
}

# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

# Append one JSONL entry to <active-run>/events/hooks-YYYY-MM-DD.jsonl.
# No active run means no run-scoped evidence sink, so logging skips silently.
# Errors are silent; log failures must not break hooks.
log_event() {
  local hook="$1" decision="$2" tool="$3" role="$4" session="$5" fields_json="${6:-}"
  [[ -n "$fields_json" ]] || fields_json='{}'
  local run_dir log_dir log_file ts
  run_dir="$(primary_active_run_dir 2>/dev/null || true)"
  [[ -n "$run_dir" ]] || return 0
  log_dir="$run_dir/events"
  mkdir -p "$log_dir" 2>/dev/null || return 0
  log_file="$log_dir/hooks-$(date -u +%Y-%m-%d).jsonl"
  ts=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ 2>/dev/null) || ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  if shepherd_jq_available; then
    jq -cn \
      --arg ts "$ts" --arg hook "$hook" --arg decision "$decision" \
      --arg tool "$tool" --arg role "$role" --arg session "$session" \
      --argjson fields "$fields_json" \
      '{ts:$ts, hook:$hook, decision:$decision, tool:$tool, role:$role, session_id:$session, fields:$fields}' \
      >> "$log_file" 2>/dev/null || true
  fi
  return 0
}

# Echo the current sprint branch name (or "unknown").
current_sprint() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown'
}

# Echo the path the conductor's HEAD claims (sprint root).
sprint_root() {
  git rev-parse --git-common-dir 2>/dev/null | sed 's|/\.git$||; s|/.git$||' || pwd
}

# Returns 0 if pwd is inside a sub-worktree (not the primary).
in_subworktree() {
  local git_dir git_common
  git_dir=$(git rev-parse --git-dir 2>/dev/null) || return 1
  git_common=$(git rev-parse --git-common-dir 2>/dev/null) || return 1
  [[ -n "$git_dir" && "$git_dir" != "$git_common" ]]
}
