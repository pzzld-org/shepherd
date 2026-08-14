#!/usr/bin/env bash
# shepherd hooks — shared library
#
# Sourced by every hook script. Exports:
#
#   is_shepherd_project              — returns 0 if <namespace>/shepherd.toml OR .claude/shepherd.toml exists
#   resolve_namespace                — echoes $SHEPHERD_WORKDIR, else existing .shepherd/.artifacts, else default .shepherd
#   shctx_config_files                — echoes the 5-tier config precedence list, one path per line (v6.4.2)
#   emit_context "<msg>"             — emit {"additionalContext":"<msg>"} and exit 0
#   emit_deny "<msg>"                — emit {"permissionDecision":"deny","message":"<msg>"} and exit 0
#   log_event hook decision tool role session fields_json
#                                    — append one JSONL entry to <ns>/logs/hooks/YYYY-MM-DD.jsonl
#   current_role tool_use_id         — echo agent role from <ns>/dispatch/<sprint>/<id>.json, or "unknown"
#   shepherd_mcp_available svc [cli] — probed (not just declared) MCP availability; emits the
#                                      sanctioned [WARN] MCP <svc> unavailable — using <cli> degrade
#   json_field input "<field>"       — extract scalar from JSON stdin; jq-then-python fallback
#
# All emit_* functions log_event before emitting JSON. Log failures are silent.
#
# This library does NOT set `set -euo pipefail` — sourcing scripts decide.

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
  # resolve_namespace is THIS lib's namespace resolver (the skills-side lib
  # calls its equivalent resolve_workdir). Using the wrong name here silently
  # falls through to the .shepherd fallback and ignores an .artifacts project.
  ns="$(SHCTX_QUIET=1 resolve_namespace 2>/dev/null || printf '%s/.shepherd' "$repo")"
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

# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

# True if either the NEW canonical <namespace>/shepherd.toml (tier 2) or the
# legacy .claude/shepherd.toml (tier 4) exists — a project is "shepherd" if
# EITHER binding is present, so a codex-shepherd-authored .shepherd/shepherd.toml
# is recognized without ever requiring a .claude/ file, and an existing
# .claude/-only project keeps working unchanged.
is_shepherd_project() {
  local ns
  ns="$(resolve_namespace 2>/dev/null || true)"
  [[ -n "$ns" && -f "$ns/shepherd.toml" ]] && return 0
  [[ -f ".claude/shepherd.toml" ]]
}

# DF-04/DF-E2: declared capability becomes PROBED capability. `[mcp].<svc> =
# true` is the operator's intent, not proof — docs/configuration.md: "an
# [mcp] server is true but unloaded" is a documented, silent-degrade WARNING
# case (confirmed live 2026-08-12: this repo's own shepherd.toml sets
# `[mcp].github = true` with no `github` MCP connected this session). Returns
# 0 only when BOTH hold: the config flag is on, AND a runtime probe confirms
# the server actually answers.
#
# The runtime probe: a bash hook cannot call ToolSearch (agent-only,
# skills/shepherd/SKILL.md §Provider-agnostic discovery) or read a
# per-session tool manifest — no such file/env var exists (checked live,
# v6.4.5). The one runtime signal a shell process has is the `claude` CLI
# itself: `claude mcp list` health-checks every configured server and
# renders each as "<name>: <target> - <status>", "Connected" (with a ✔) the
# only positive status (verbatim per `claude mcp list --help`; there is no
# --json form). A same-line, case-insensitive match of <svc> followed by
# "Connected" counts as available. This is a literal-name probe, not full
# provider-agnostic resolution (a GitHub capability routed through a
# differently-named Docker gateway, e.g. `MCP_DOCKER`, will not match
# "github" here) — that full resolution is exactly what ToolSearch is for,
# and stays the agent's job; this helper's failure mode is deliberately
# conservative (treat as unavailable, degrade to CLI) rather than guess.
#
# `claude mcp list` performs a real network round-trip per configured
# server, so the result is cached per-<svc> under <ns>/cache/mcp-probe/<svc>
# for MCP_PROBE_TTL_S seconds (default 300) — a hook firing on every tool
# call cannot pay a multi-second health-check on every invocation.
#
# Usage: shepherd_mcp_available <svc> [<cli>]   e.g. shepherd_mcp_available github gh
# On failure (config off OR probe negative), emits the sanctioned degrade
# line to stderr so no caller has to remember to (skills/shepherd/SKILL.md
# §MCP-over-CLI): "[WARN] MCP <svc> unavailable — using <cli>".
MCP_PROBE_TTL_S="${MCP_PROBE_TTL_S:-300}"
shepherd_mcp_available() {
  local svc="$1" cli="${2:-cli}"
  [[ -n "$svc" ]] || return 1

  # 1. Config gate — an operator's explicit `[mcp].<svc> = false` is a hard
  # opt-out, never overridden by a stray same-named MCP the probe happens
  # to find connected for an unrelated reason.
  if [[ "$(cfg_section_get mcp "$svc" 2>/dev/null)" != "true" ]]; then
    printf '[WARN] MCP %s unavailable — using %s\n' "$svc" "$cli" >&2
    return 1
  fi

  # 2. Runtime probe, TTL-cached.
  local ns cache_file now mtime hit
  ns="$(resolve_namespace 2>/dev/null || printf '.shepherd')"
  cache_file="$ns/cache/mcp-probe/$svc"
  now="$(date -u +%s 2>/dev/null || echo 0)"
  if [[ -f "$cache_file" ]]; then
    mtime="$(stat -f %m "$cache_file" 2>/dev/null || stat -c %Y "$cache_file" 2>/dev/null || echo 0)"
    if [[ "$((now - mtime))" -lt "$MCP_PROBE_TTL_S" ]]; then
      hit="$(cat "$cache_file" 2>/dev/null || echo 0)"
      [[ "$hit" == "1" ]] && return 0
      printf '[WARN] MCP %s unavailable — using %s\n' "$svc" "$cli" >&2
      return 1
    fi
  fi

  hit=0
  if command -v claude &>/dev/null && claude mcp list 2>/dev/null | grep -qiE "${svc}.*Connected"; then
    hit=1
  fi
  mkdir -p "$ns/cache/mcp-probe" 2>/dev/null || true
  printf '%s' "$hit" > "$cache_file" 2>/dev/null || true

  [[ "$hit" == "1" ]] && return 0
  printf '[WARN] MCP %s unavailable — using %s\n' "$svc" "$cli" >&2
  return 1
}

# Echoes the project-local work directory. Mirrors the skills-lib
# resolve_workdir precedence EXACTLY (kept dependency-free so hooks stay fast):
#   1. SHEPHERD_WORKDIR (absolute as-is, else relative to repo_root)
#   2. SHCTX_ROOT_OVERRIDE (legacy; set by `shctx init --artifacts`)
#   3. existing .shepherd/  (the v5.0.0 default; wins the tie-break)
#   4. existing .artifacts/ (legacy auto-pickup fallback)
#   5. default .shepherd/   (matches `shctx init` for new projects)
# Contract source of truth: docs/configuration.md §SHEPHERD_WORKDIR and
# services/cli/shepherd_cli/resolution.py resolve_workdir. These MUST agree or hooks
# write event logs / dispatch tags / locks into a different namespace than the
# shctx runtime reads (split-brain — GH #121).
resolve_namespace() {
  local repo_root
  repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
  if [[ -n "${SHEPHERD_WORKDIR:-}" ]]; then
    case "$SHEPHERD_WORKDIR" in
      /*) printf '%s' "$SHEPHERD_WORKDIR" ;;
      *)  printf '%s' "$repo_root/$SHEPHERD_WORKDIR" ;;
    esac
    return 0
  fi
  if [[ -n "${SHCTX_ROOT_OVERRIDE:-}" ]]; then
    printf '%s' "$repo_root/$SHCTX_ROOT_OVERRIDE"
    return 0
  fi
  for cand in "$repo_root/.shepherd" "$repo_root/.artifacts"; do
    if [[ -d "$cand" ]]; then
      printf '%s' "$cand"
      return 0
    fi
  done
  printf '%s' "$repo_root/.shepherd"
}

# Registry DB path inside a namespace. Mirrors the skills-side shctx_db_path()
# (services/cli/shepherd_cli/resolution.py): prefer shepherd.db (the v6.1.2+ standard
# `shctx init` creates), fall back to an EXISTING root.db (legacy projects,
# untouched), else default to shepherd.db. Pass the already-resolved namespace
# to preserve each caller's exact resolve_namespace fallback; omit to resolve
# here. Hooks that hardcoded "$ns/root.db" silently no-op'd on every modern
# project (the file is named shepherd.db), disabling the spawn-coordination
# guards — this keeps hooks and the shctx runtime reading the same file.
hook_db_path() {
  local ns="${1:-$(resolve_namespace 2>/dev/null || echo .shepherd)}"
  if   [[ -f "$ns/shepherd.db" ]]; then echo "$ns/shepherd.db"
  elif [[ -f "$ns/root.db"     ]]; then echo "$ns/root.db"
  else                                   echo "$ns/shepherd.db"
  fi
}

# Echo the value of a top-level `key = value` from shepherd config, resolved by
# the shctx_config_files precedence (v6.4.2): <namespace>/shepherd.local.toml →
# <namespace>/shepherd.toml → .claude/shepherd.local.toml (per-key local
# override, gitignored — mirrors Claude Code's settings.local.json) →
# .claude/shepherd.toml (project) → $XDG_CONFIG_HOME/shepherd.toml (user
# global). Section-agnostic, last-match-wins within a file; strips surrounding
# double-quotes and trailing " # inline comments". Echoes "" if the key is
# unset everywhere. bash-3.2-safe (no TOML parser) and never returns non-zero,
# so it is safe to call under `set -e`/pipefail.
# Contract source of truth: docs/configuration.md §config-resolution. MUST agree
# with the CLI-side config resolution (services/cli/shepherd_cli/commands/config.py) — they read the
# same files in the same order or config diverges between hooks and runtime.
cfg_get() {
  local key="$1" f v
  while IFS= read -r f; do
    [[ -n "$f" && -f "$f" ]] || continue
    v="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$f" 2>/dev/null | tail -1 \
          | sed -E 's/^[^=]*=[[:space:]]*//; s/[[:space:]]+#.*$//; s/^"//; s/"$//' 2>/dev/null || true)"
    if [[ -n "$v" ]]; then printf '%s' "$v"; return 0; fi
  done < <(shctx_config_files)
  printf '%s' ""
  return 0
}

# Section-aware companion to cfg_get: echo `key = value` under a specific
# `[section]` from shepherd config, resolved by the SAME precedence
# (shctx_config_files, v6.4.2: namespace-local → namespace → .claude-local →
# .claude → XDG). For TOML blocks whose bare keys would collide across
# sections (e.g. [models] role keys). Last-match-wins within the section;
# strips surrounding double-quotes and a trailing " # inline comment". Echoes
# "" if unset; never returns non-zero. bash-3.2-safe (awk parses the section —
# no associative arrays / mapfile). MUST mirror the skills-side cfg_section_get
# (services/cli/shepherd_cli/commands/config.py) — same files, same order, same parse — or
# config diverges between hooks and the shctx runtime. Contract source of truth:
# docs/configuration.md §config-resolution.
cfg_section_get() {
  local section="$1" key="$2" f v
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
  done < <(shctx_config_files)
  printf '%s' ""
  return 0
}

# List the KEYS of a `[section]` block across the shepherd config precedence
# (shctx_config_files, v6.4.2), one per line, union'ed with first-seen wins —
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
  done < <(shctx_config_files)
  printf '%s' "$out"
  return 0
}

# ---------------------------------------------------------------------------
# Run-scoped artifact layout (v6.4.1 — .shepherd/runs/{run}/)
# ---------------------------------------------------------------------------

# The [paths]-aware runs root: `[paths].runs` from config (repo-relative unless
# absolute), else `<namespace>/runs` — the same default the Python CLI's
# models_run.runs_root() uses, so hooks and `shepherd run` read the same tree.
runs_root_dir() {
  local repo cfg
  repo="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  cfg="$(cfg_section_get paths runs 2>/dev/null || true)"
  if [[ -n "$cfg" ]]; then
    case "$cfg" in /*) printf '%s' "$cfg" ;; *) printf '%s' "$repo/$cfg" ;; esac
  else
    printf '%s' "$(resolve_namespace)/runs"
  fi
  return 0
}

# Echo the DIRECTORY of the active run — the newest runs/*/run.json whose
# status is "executing" (run.json is CLI-written via `shepherd run`, so the
# grep against its canonical rendering is deterministic). Echoes "" when no
# run is active; never returns non-zero.
active_run_dir() {
  local root f
  root="$(runs_root_dir 2>/dev/null || true)"
  [[ -d "$root" ]] || return 0
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    if grep -q '"status"[[:space:]]*:[[:space:]]*"executing"' "$f" 2>/dev/null; then
      printf '%s' "$(dirname "$f")"
      return 0
    fi
  done < <(ls -1t "$root"/*/run.json 2>/dev/null || true)
  return 0
}

# ---------------------------------------------------------------------------
# Session-tier marker (#232/#228 — positive teammate identity)
# ---------------------------------------------------------------------------

# Echo the marker path for a session: <ns>/tmp/session-tier-<session>. STAMPED
# by user_prompt_submit.sh when a session boots as a TEAMMATE (the rendered
# boot prompt's INVOCATION-CONTEXT dispatcher field is the signal). READ by
# coordinate_drive_guard.sh (a marked session is NEVER nudged — fail-closed
# for teammates) and conductor_write_guard.sh (the marker's lane_plan field
# scopes the lane-plan custody exemption).
session_tier_marker() {
  local ns="${1:-$(resolve_namespace 2>/dev/null || echo .shepherd)}" session="${2:-nosession}"
  printf '%s/tmp/session-tier-%s' "$ns" "${session//[^A-Za-z0-9_.-]/_}"
}

# ---------------------------------------------------------------------------
# JSON extraction (jq preferred, python3 fallback)
# ---------------------------------------------------------------------------

# Usage: json_field "$input_json" '.tool_input.command'
# Echoes the field value (empty string if absent OR if the JSON is malformed —
# fail-open with rc 0 so a sourcing `set -e` hook never dies on bad input, the
# same contract json_response already guarantees).
json_field() {
  local input="$1" path="$2"
  if command -v jq &>/dev/null; then
    printf '%s' "$input" | jq -r "$path // empty" 2>/dev/null || true
  else
    # Convert jq path like '.foo.bar' into a python dict.get chain.
    python3 -c '
import json, sys
data = json.load(sys.stdin)
path = sys.argv[1].lstrip(".").split(".")
for p in path:
    if isinstance(data, dict):
        data = data.get(p, "")
    else:
        data = ""
        break
print(data if isinstance(data, str) else (json.dumps(data) if data else ""))
' "$path" <<<"$input" 2>/dev/null || true
  fi
}

# Extract the tool_response (which varies — string, dict.content, dict.text, or list).
# Usage: json_response "$input_json"
#
# v6.0.0: jq queries use `?` after each property access to suppress
# "Cannot index string with X" errors when tool_response is itself a string
# (jq rc=5). Without `?`, callers under `set -e` exit with code 5 on string
# tool_responses. The function additionally returns 0 unconditionally so a
# jq/python failure surfaces as an empty response, not a propagated exit.
json_response() {
  local input="$1"
  if command -v jq &>/dev/null; then
    printf '%s' "$input" | jq -r '
      (.tool_response.content? // .tool_response.text? // .tool_response // empty)
      | if type == "array" then map(.text? // .) | join("\n") else . end' 2>/dev/null || true
  else
    python3 -c '
import json, sys
d = json.load(sys.stdin)
r = d.get("tool_response", "")
if isinstance(r, dict):
    r = r.get("content") or r.get("text") or ""
if isinstance(r, list):
    r = "\n".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in r)
print(r)
' 2>/dev/null <<<"$input" || true
  fi
}

# ---------------------------------------------------------------------------
# JSON emission
# ---------------------------------------------------------------------------

# Usage: emit_json_obj key1 val1 key2 val2 ...
# Echoes a single-line JSON object. Used by emit_context / emit_deny.
emit_json_obj() {
  if command -v jq &>/dev/null; then
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
    python3 -c '
import json, sys
args = sys.argv[1:]
obj = {args[i]: args[i+1] for i in range(0, len(args), 2)}
print(json.dumps(obj))
' "$@"
  fi
}

# Returns 0 if `.claude/shepherd.toml` contains `quiet_warnings = true` under
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
# JSON is suppressed (log_event still fires); operators can grep
# `<namespace>/logs/hooks/YYYY-MM-DD.jsonl` to recover the warning text.
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
  local hook="${1:-}" tool="${2:-}" role="${3:-unknown}" session="${4:-}" fields="${5:-{\}}"
  [[ -n "$hook" ]] && log_event "$hook" "pass" "$tool" "$role" "$session" "$fields"
  exit 0
}

# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

# Append one JSONL entry to <ns>/logs/hooks/YYYY-MM-DD.jsonl.
# Errors are silent; log failures must not break hooks.
log_event() {
  local hook="$1" decision="$2" tool="$3" role="$4" session="$5" fields_json="${6:-{\}}"
  local ns log_dir log_file ts
  ns=$(resolve_namespace) 2>/dev/null || return 0
  log_dir="$ns/logs/hooks"
  mkdir -p "$log_dir" 2>/dev/null || return 0
  log_file="$log_dir/$(date -u +%Y-%m-%d).jsonl"
  ts=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ 2>/dev/null) || ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  if command -v jq &>/dev/null; then
    jq -cn \
      --arg ts "$ts" --arg hook "$hook" --arg decision "$decision" \
      --arg tool "$tool" --arg role "$role" --arg session "$session" \
      --argjson fields "${fields_json:-{}}" \
      '{ts:$ts, hook:$hook, decision:$decision, tool:$tool, role:$role, session_id:$session, fields:$fields}' \
      >> "$log_file" 2>/dev/null || true
  else
    python3 -c '
import json, sys
print(json.dumps({
    "ts":         sys.argv[1],
    "hook":       sys.argv[2],
    "decision":   sys.argv[3],
    "tool":       sys.argv[4],
    "role":       sys.argv[5],
    "session_id": sys.argv[6],
    "fields":     json.loads(sys.argv[7] or "{}"),
}))
' "$ts" "$hook" "$decision" "$tool" "$role" "$session" "${fields_json:-{}}" \
      >> "$log_file" 2>/dev/null || true
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Role resolution (from agent_invocation_tagger writes)
# ---------------------------------------------------------------------------

# Given a tool_use_id, echo the agent role written by agent_invocation_tagger.sh.
#
# THREE outcomes, deliberately distinct (DF-77 FIX 2, #187 field incident —
# was previously TWO outcomes that collapsed "no tool call in flight" and "a
# tool call is in flight but its role can't be confirmed" into ONE value,
# "conductor" — the tier that HOLDS lane commit/push rights the rest of the
# flock does not. An unidentified caller was thereby PROMOTED into MORE
# authority than an identified one, the opposite of every other guard's
# posture in this repo):
#   - tool_use_id empty            → "conductor". No tool call is even in
#     flight (e.g. a CwdChanged event) — this genuinely IS the top-level
#     session's own action, not an unresolved dispatch. Several consumers
#     (cwd_changed.sh, conductor_write_guard.sh) depend on this EXACT value
#     for exactly this case; do not touch it.
#   - tool_use_id present, dispatch record found → the record's own
#     `agent_role` (written by agent_invocation_tagger.sh from
#     tool_input.subagent_type — DF-77 FIX 1).
#   - tool_use_id present, NO matching record found → "unknown". This is the
#     escalation this fix closes: previously fell through to "conductor" too,
#     which is what let an unidentified caller (in practice: EVERY @coder
#     dispatch, per the FIX-3 note below) inherit conductor's git-write tier.
#     Every consumer must treat "unknown" as "could not confirm, NOT as safe
#     as a positively-identified non-target role" — see coder_git_guard.sh for
#     the worked example (warn-loud instead of silent-pass on a git write).
#
# DF-77 FIX 3, evidence trail (the correlation key this lookup depends on):
# this function is called with the CURRENT tool call's OWN tool_use_id (e.g.
# a coder's live `git commit` Bash call), but agent_invocation_tagger.sh wrote
# the dispatch record under the DISPATCHING Agent()/Task() call's tool_use_id
# — a DIFFERENT tool_use block, minted at a different (earlier) turn. Per the
# Anthropic tool-use protocol every tool_use block gets a fresh, never-reused
# id, so these two ids are STRUCTURALLY never equal — confirmed against this
# session's own live dispatch tree (`.shepherd/dispatch/*/*.json` filenames
# match each subagent's `<session>/subagents/agent-*.meta.json` `toolUseId`
# field exactly, which is NEVER the id any tool call issued *by* that
# subagent later carries). `session_id` does not substitute either: it is
# IDENTICAL across an entire dispatch tree (root + every nested subagent
# share one `session_id` — confirmed via this coder's own
# `CLAUDE_CODE_SESSION_ID` env var matching the root session's transcript,
# and via `.shepherd/logs/events-*.jsonl` `cache_usage` rows showing dozens of
# concurrent `shepherd:coder`/`shepherd:auditor` dispatches under one shared
# `session_id`), so it cannot disambiguate between concurrent sibling
# dispatches in one wave. `agent_id` is Claude Code's documented per-subagent
# identifier (used by this exact codebase on `SubagentStop` —
# subagent_telemetry.sh — and `TeammateIdle` — teammate_idle.sh, both sourced
# against https://code.claude.com/docs/en/hooks) and is the best-evidenced
# candidate key, but whether `PreToolUse` ALSO carries it for a tool call
# issued from inside an already-running subagent could NOT be confirmed here:
# a live-capture attempt (instrumenting this hook to dump its own stdin, then
# triggering a real Bash call from this exact dispatch) produced no payload —
# this coder-dispatch harness does not route through the installed hook
# pipeline the way an interactive session does. Closing this needs either a
# live capture from an interactive session, or wiring the (currently
# unregistered — see CHANGELOG "Deferred to v5.2.0+: SubagentStart hook
# consumption") `SubagentStart` event, which fires once `agent_id` exists and
# could re-key the record — both outside this step's file_scope (hooks.json
# is not in [FILE-SCOPE]). Net effect: the tool_use_id lookup below still
# runs (harmless — matches on the rare occasion a caller passes the SAME id
# through, e.g. a test fixture or a future correlator), but production
# @coder Bash calls should be assumed to resolve "unknown", not "coder",
# until FIX 3 lands for real; consumers are written to that assumption.
#
# Usage: role=$(current_role "$tool_use_id" "$sprint")
current_role() {
  local tool_use_id="${1:-}" sprint="${2:-unknown}"
  [[ -z "$tool_use_id" ]] && { printf 'conductor'; return 0; }

  # The dispatch record was written by agent_invocation_tagger.sh from the
  # SPRINT-ROOT context. A @coder reads it from INSIDE its own linked worktree
  # (`shctx worktree create-batch` — a different toplevel AND a different branch),
  # so a cwd-relative lookup (`resolve_namespace` uses `--show-toplevel`;
  # `current_sprint` returns the checked-out branch) misses the record entirely
  # and every consumer falls back to role=conductor — the coder_git_guard #187
  # field no-op. Resolve robustly: search the cwd namespace AND the MAIN
  # worktree's namespace (via `--git-common-dir`, which points at the shared .git
  # even from a linked worktree), and match the record by its UNIQUE tool_use_id
  # under ANY sprint dir (branch-independent) — a glob, since the reader's
  # current branch need not equal the sprint segment recorded at write time.
  local ns dispatch_file="" cand common main_root
  local -a roots=()
  ns="$(resolve_namespace 2>/dev/null || true)"; [[ -n "$ns" ]] && roots+=("$ns")
  common="$(git rev-parse --git-common-dir 2>/dev/null || true)"
  if [[ -n "$common" ]]; then
    case "$common" in /*) : ;; *) common="$(pwd)/$common" ;; esac
    main_root="$(cd "$(dirname "$common")" 2>/dev/null && pwd || true)"
    [[ -n "$main_root" ]] && roots+=("$main_root/.shepherd" "$main_root/.artifacts")
  fi
  for ns in "${roots[@]}"; do
    [[ -n "$ns" ]] || continue
    for cand in "$ns/dispatch/$sprint/${tool_use_id}.json" "$ns"/dispatch/*/"${tool_use_id}.json"; do
      [[ -f "$cand" ]] && { dispatch_file="$cand"; break 2; }
    done
  done

  if [[ -n "$dispatch_file" ]] && command -v jq &>/dev/null; then
    jq -r '.agent_role // "unknown"' "$dispatch_file" 2>/dev/null || printf 'unknown'
  elif [[ -n "$dispatch_file" ]]; then
    python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('agent_role','unknown'))" "$dispatch_file" 2>/dev/null || printf 'unknown'
  else
    # DF-77 FIX 2: a tool call WAS in flight (tool_use_id non-empty) but no
    # dispatch record matched it — unresolved, NOT conductor. See the
    # function-level comment above for the full three-way contract and why
    # promoting this case to "conductor" was the #187 field defect.
    printf 'unknown'
  fi
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
