#!/usr/bin/env bash
# shepherd hook — SessionStart: capability auto-discovery (v6.1.5, #146)
#
# WHY: The curated toolkit.json is hand-maintained — the operator registers
# tools once and shepherd resurfaces them. But the SESSION ENVIRONMENT often
# carries capabilities the operator never wired: installed Claude Code plugins
# (/remember, superpowers, pr-review-toolkit), skills, and MCP servers. This
# probe enumerates what it can cheaply observe at SessionStart and writes an
# EPHEMERAL capability roster — kept DISTINCT from the curated toolkit.json —
# so the flock adapts to what's actually available without operator wiring.
# The toolkit_surface hook + `shctx inject` merge that ephemeral roster into the
# [TOOLKIT] surface, clearly labeled auto-discovered.
#
# EVENT:  SessionStart
# STDIN:  { session_id, transcript_path, cwd, source, hook_event_name }
# OUTPUT: nothing on stdout (writes the roster file). Never emits
#         additionalContext — toolkit_surface.sh owns the [TOOLKIT] surface.
#
# WHAT A HOOK CAN vs CANNOT SEE (honest enumeration):
#   CAN  — installed plugin/skill directories on disk, env-derived signals
#          (e.g. CLAUDE_CODE_ENTRYPOINT, web/remote markers), the marketplace
#          plugin tree.
#   CANNOT — the agent's VISIBLE tool list, or deferred tools requiring
#          ToolSearch (a SessionStart hook is not the agent and cannot call
#          ToolSearch / list its own tools). For those the roster carries a
#          documented `agent_fillin` contract: the agent records Workflow-tool
#          presence + ToolSearch-discovered specialists on first /shepherd:*.
#
# FAST-PATHS (exit 0 silently, ZERO hot-path cost — non-negotiable):
#   - not a shepherd project
#   - [discovery].auto_capabilities = off
#   - already probed this session (TTL marker under <ns>/cache/)
#   - jq unavailable
# FAIL-OPEN: any error → exit 0. Never blocks; never hard-depends on a plugin.
# See: skills/shepherd/doctrines/capability-discovery.md

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- is_shepherd_project guard -----------------------------------------------
is_shepherd_project || exit 0

# --- config gate: [discovery].auto_capabilities (default on) ------------------
# Default-on per the issue; disabled only when explicitly set to a false-y
# token. Resolved through cfg_get (local.toml → project → XDG-global precedence,
# section-agnostic) so the toggle honors the same resolution as every other
# shepherd config key. cfg_get is bash-3.2-safe and never returns non-zero.
AC="$(cfg_get auto_capabilities 2>/dev/null || true)"
case "$AC" in
  off|false|0|no) exit 0 ;;
esac

# --- jq guard ----------------------------------------------------------------
command -v jq >/dev/null 2>&1 || exit 0

# --- session id for the marker + log -----------------------------------------
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"

# --- resolve namespace + paths -----------------------------------------------
NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"
CACHE_DIR="$NS/cache"
ROSTER="$CACHE_DIR/discovered-capabilities.json"
# Per-session marker so the probe is one-time-per-session (ZERO hot-path cost).
# Markers are short-TTL so a stale one from a crashed session does not pin a
# stale roster forever.
MARKER="$CACHE_DIR/.capdisc-${SESSION}.probed"
TTL_SECONDS=3600  # 1h — comfortably longer than a SessionStart burst.

mkdir -p "$CACHE_DIR" 2>/dev/null || exit 0

# --- already-probed-this-session fast-path -----------------------------------
# If the marker exists and is younger than TTL, no-op. find -mmin is portable
# (bash-3.2 / BSD + GNU). On any uncertainty we re-probe (cheap) rather than
# risk a stale roster — but we never re-probe within the same SessionStart.
if [[ -f "$MARKER" ]]; then
  fresh="$(find "$MARKER" -mmin "-$((TTL_SECONDS/60))" 2>/dev/null || true)"
  [[ -n "$fresh" ]] && exit 0
fi

NOW="$(date +%s 2>/dev/null || echo 0)"

# ---------------------------------------------------------------------------
# Enumerate cheaply-observable capabilities → JSON array of entry objects.
# Each entry mirrors the toolkit entry shape enough to merge: name/type/
# description/capabilities + a `source:"auto"` marker + `origin` (where seen).
# ---------------------------------------------------------------------------

EMITTED="[]"        # JSON array accumulator
SEEN_NAMES=" "      # space-delimited dedup set (bash-3.2 — no assoc arrays)

# add_cap <name> <type> <description> <capabilities-csv> <origin>
add_cap() {
  local name="$1" type="$2" desc="$3" caps="$4" origin="$5"
  [[ -n "$name" ]] || return 0
  # Dedup by name (first wins).
  case "$SEEN_NAMES" in *" $name "*) return 0 ;; esac
  SEEN_NAMES="$SEEN_NAMES$name "
  local caps_json="[]"
  [[ -n "$caps" ]] && caps_json="$(printf '%s' "$caps" | jq -Rc 'split(",") | map(gsub("^ +| +$";""))' 2>/dev/null || echo '[]')"
  local entry
  entry="$(jq -cn \
    --arg n "$name" --arg t "$type" --arg d "$desc" \
    --arg o "$origin" --argjson c "$caps_json" \
    '{name:$n, type:$t, description:$d, capabilities:$c, source:"auto", origin:$o}' \
    2>/dev/null || true)"
  [[ -n "$entry" ]] || return 0
  EMITTED="$(printf '%s' "$EMITTED" | jq -c --argjson e "$entry" '. + [$e]' 2>/dev/null || printf '%s' "$EMITTED")"
}

# --- 1. Installed Claude Code plugins (marketplace + plugin trees) -----------
# Plugins live under ~/.claude/plugins/. A plugin dir with a .claude-plugin/
# plugin.json (or commands/) is a real install. We name a small known set of
# opportunistic-integration plugins explicitly (so their guarded doctrine hooks
# fire), and otherwise record presence generically. Cheap dir-stat only.
PLUGIN_ROOT="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins"
probe_plugin_dir() {
  local pdir="$1"
  [[ -d "$pdir" ]] || return 0
  local p name
  for p in "$pdir"/*/; do
    [[ -d "$p" ]] || continue
    name="$(basename "$p")"
    case "$name" in marketplaces|.*) continue ;; esac
    # Known opportunistic integrations get a richer, guidance-bearing entry.
    case "$name" in
      *remember*)
        add_cap "$name" "plugin" "memory continuity (/remember) — use at handoff/CLOSE-FINALIZE + on resume" "memory,continuity" "plugins:$name" ;;
      *superpowers*)
        add_cap "$name" "plugin" "brainstorming / TDD / systematic-debugging skills — route at the right seams" "brainstorming,tdd,debugging" "plugins:$name" ;;
      *pr-review*|*review-toolkit*)
        add_cap "$name" "plugin" "PR-review specialist agents — surface per doctrines/specialist-dispatch.md" "pr-review,specialist" "plugins:$name" ;;
      *)
        add_cap "$name" "plugin" "installed Claude Code plugin (auto-discovered)" "" "plugins:$name" ;;
    esac
  done
}
probe_plugin_dir "$PLUGIN_ROOT"
# Marketplace-registered plugins (e.g. fl03 marketplace tree) — presence only.
probe_plugin_dir "$PLUGIN_ROOT/marketplaces"

# --- 2. Installed skills (~/.claude/skills + project .claude/skills) ---------
probe_skill_dir() {
  local sdir="$1" origin="$2"
  [[ -d "$sdir" ]] || return 0
  local s name
  for s in "$sdir"/*/; do
    [[ -d "$s" ]] || continue
    [[ -f "$s/SKILL.md" ]] || continue
    name="$(basename "$s")"
    case "$name" in .*) continue ;; esac
    add_cap "skill:$name" "skill" "installed skill (auto-discovered) — load via Skill(skill=\"$name\")" "" "$origin:$name"
  done
}
probe_skill_dir "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills" "skills"
probe_skill_dir ".claude/skills" "project-skills"

# ---------------------------------------------------------------------------
# Compose the ephemeral roster. We ALWAYS write it (even when empty) so the
# `agent_fillin` contract is present — that block tells the agent what the hook
# could NOT see and asks it to record those on first /shepherd:* (Workflow-tool
# presence, ToolSearch-discovered specialists). Bounded: cap auto entries at 12
# to match the toolkit injection budget; the agent_fillin block is metadata.
# ---------------------------------------------------------------------------
CAPPED="$(printf '%s' "$EMITTED" | jq -c '.[0:12]' 2>/dev/null || echo '[]')"
COUNT="$(printf '%s' "$CAPPED" | jq 'length' 2>/dev/null || echo 0)"

# Detect cheap environment signals for the workflow-tool note (advisory only —
# the AGENT confirms presence via its visible tool list; a hook cannot).
ENTRYPOINT="${CLAUDE_CODE_ENTRYPOINT:-}"
WEB_HINT="unknown"
case "$ENTRYPOINT" in
  *web*|*remote*) WEB_HINT="likely-omitted" ;;   # web/remote sessions may omit Workflow (#146)
  cli|"") WEB_HINT="likely-present-verify" ;;
esac

ROSTER_JSON="$(jq -cn \
  --argjson now "$NOW" \
  --arg session "$SESSION" \
  --argjson caps "$CAPPED" \
  --argjson count "$COUNT" \
  --arg webhint "$WEB_HINT" \
  --arg entry "$ENTRYPOINT" \
  '{
    version: 1,
    source: "auto-discovered",
    note: "EPHEMERAL — gitignored cache. NEVER edit toolkit.json from this; the curated registry is operator intent (doctrines/capability-discovery.md).",
    probed_at: $now,
    session_id: $session,
    capabilities: $caps,
    count: $count,
    agent_fillin: {
      instructions: "A SessionStart hook cannot see the visible tool list or call ToolSearch. On first /shepherd:* the agent SHOULD record what only it can observe.",
      workflow_tool: {
        env_entrypoint: $entry,
        env_hint: $webhint,
        present: null,
        how: "Is `Workflow` in your visible tool list? Set present:true|false. If false, spawn/loop degrade to in-context Agent(...) fan-out (references/glossary.md sense 1; #146). NEVER ToolSearch for it."
      },
      deferred_specialists: {
        present: null,
        how: "Specialists (pr-review-toolkit:*, superpowers:*, etc.) are DEFERRED tools — enumerate via ToolSearch per doctrines/specialist-dispatch.md, then record names here."
      }
    }
  }' 2>/dev/null || true)"

[[ -n "$ROSTER_JSON" ]] || exit 0

# Atomic-ish write: temp then mv (mv is atomic on the same filesystem).
TMP="$ROSTER.tmp.$$"
printf '%s\n' "$ROSTER_JSON" > "$TMP" 2>/dev/null || exit 0
mv -f "$TMP" "$ROSTER" 2>/dev/null || { rm -f "$TMP" 2>/dev/null; exit 0; }

# Stamp the per-session marker (best-effort).
: > "$MARKER" 2>/dev/null || true

# Log the probe (silent on failure).
log_event "capability_discovery" "context" "SessionStart" "shepherd" "$SESSION" \
  "$(emit_json_obj count "$COUNT" web_hint "$WEB_HINT")" 2>/dev/null || true

exit 0
