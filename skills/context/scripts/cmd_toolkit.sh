#!/usr/bin/env bash
# shctx toolkit <list|show|add|rm|pin|unpin|md|init|validate> [args]
#
# Tool-memory sibling to the adaptation loop's lesson-memory. Maintains a
# project-local and/or user-global JSON registry of "commonly used tools" so a
# Claude Code session never forgets a capability (MCP servers, CLIs, skills,
# plugins). Human-readable/editable — NOT a DB table. Mirror of project.json's
# approach.
#
# Storage:
#   local  → $(resolve_workdir)/toolkit.json
#   global → ${XDG_CONFIG_HOME:-$HOME/.config}/shepherd/toolkit.json
#
# Scope merge (--scope=all): global ∪ local, local wins on name collision.
#
# Canonical type enum: mcp | skill | plugin | cli
#   Non-canonical types (service, ssh, etc.) are WARN-flagged on validate but
#   fully permitted — 'cli' is the recommended home for ssh/remote targets.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
_local_path()  { echo "$(resolve_workdir)/toolkit.json"; }
_global_path() { echo "${XDG_CONFIG_HOME:-$HOME/.config}/shepherd/toolkit.json"; }
# EPHEMERAL auto-discovered roster (v6.1.5, #146) — written by the SessionStart
# capability_discovery.sh hook into gitignored cache/. NEVER the curated
# toolkit.json: discovery must never overwrite operator intent.
# See skills/shepherd/doctrines/capability-discovery.md.
_discovered_path() { echo "$(resolve_workdir)/cache/discovered-capabilities.json"; }

# Resolve path for a given scope (local|global). Exits on bad scope.
_scope_path() {
  case "${1:-local}" in
    local)  _local_path ;;
    global) _global_path ;;
    *) echo "ERROR: --scope must be local or global (got '$1')" >&2; exit 1 ;;
  esac
}

# Canonical type set — non-canonical triggers WARN (not error) on validate.
_CANONICAL_TYPES="mcp skill plugin cli"
_is_canonical_type() {
  local t="$1" ct
  for ct in $_CANONICAL_TYPES; do
    [[ "$t" == "$ct" ]] && return 0
  done
  return 1
}

# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

# Read toolkit.json at PATH; if absent emit empty registry JSON.
_read_tk() {
  local path="$1"
  if [[ -f "$path" ]]; then
    cat "$path"
  else
    jq -nc --argjson now "$(shctx_now)" \
      '{"version":1,"scope":"local","updated_at":$now,"tools":[]}'
  fi
}

# Overwrite PATH with new JSON, refreshing top-level updated_at.
# Creates parent dirs as needed.
_write_tk() {
  local path="$1" json="$2"
  mkdir -p "$(dirname "$path")"
  printf '%s\n' "$json" \
    | jq --argjson now "$(shctx_now)" '.updated_at = $now' \
    > "$path"
}

# Merge global ∪ local, local names win.
_merge_all() {
  local lp gp
  lp=$(_local_path); gp=$(_global_path)
  local ltk gtk
  ltk=$(_read_tk "$lp"); gtk=$(_read_tk "$gp")
  # Build map: start with global tools, then overlay local (local wins).
  jq -n --argjson g "$gtk" --argjson l "$ltk" '
    ($g.tools + $l.tools)
    | reduce .[] as $t ({}; .[$t.name] = $t)
    | to_entries | map(.value)
  '
}

# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
_cmd_list() {
  local scope="all" type_filter="" fmt="md"
  for arg in "$@"; do
    case "$arg" in
      --scope=*) scope="${arg#--scope=}" ;;
      --type=*)  type_filter="${arg#--type=}" ;;
      --json)    fmt="json" ;;
      --md)      fmt="md" ;;
      -h|--help) _usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local tools
  if [[ "$scope" == "all" ]]; then
    tools=$(_merge_all)
  else
    local path; path=$(_scope_path "$scope")
    tools=$(jq '.tools' < <(_read_tk "$path"))
  fi

  # Apply type filter.
  [[ -n "$type_filter" ]] && tools=$(jq --arg t "$type_filter" '[.[] | select(.type == $t)]' <<< "$tools")

  # Graceful-empty: emit nothing when there are no matching tools.
  local count; count=$(jq 'length' <<< "$tools")
  [[ "$count" -gt 0 ]] || return 0

  case "$fmt" in
    json) jq '.' <<< "$tools" ;;
    md)
      # Pinned first, then alphabetical. No cap — `list` is the full inventory
      # surface (interactive); only the injected surfaces (hook + `md`) bound at 12.
      jq -r '
        sort_by([if .pinned then 0 else 1 end, .name])[]
        | "- **" + .name + "** (" + .type + ", " + .scope + ") — " + .description
          + (if (.capabilities // [] | length) > 0 then "\n  capabilities: " + (.capabilities | join(", ")) else "" end)
          + (if .when then "\n  when: " + .when else "" end)
          + (if .pinned then " _(pinned)_" else "" end)
      ' <<< "$tools" ;;
  esac
}

# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------
_cmd_show() {
  local name="${1:-}" fmt="md"
  [[ -n "$name" ]] || { echo "ERROR: usage: shctx toolkit show <name> [--json|--md]" >&2; exit 1; }
  shift || true
  for arg in "$@"; do
    case "$arg" in
      --json) fmt="json" ;;
      --md)   fmt="md" ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  # Search local first, then global.
  local found=""
  for scope in local global; do
    local path; path=$(_scope_path "$scope")
    local entry; entry=$(jq -e --arg n "$name" '.tools[] | select(.name == $n)' < <(_read_tk "$path") 2>/dev/null || true)
    if [[ -n "$entry" ]]; then
      found="$entry"; break
    fi
  done

  if [[ -z "$found" ]]; then
    echo "ERROR: toolkit: tool '$name' not found" >&2; exit 1
  fi

  case "$fmt" in
    json) jq '.' <<< "$found" ;;
    md)
      jq -r '
        "## " + .name + " (" + .type + ")\n"
        + "**scope:** " + .scope + "  \n"
        + "**description:** " + .description + "  \n"
        + "**capabilities:** " + (.capabilities | join(", ")) + "  \n"
        + if .invocation then "**invocation:** `" + .invocation + "`  \n" else "" end
        + if .when then "**when:** " + .when + "  \n" else "" end
        + if .tags then "**tags:** " + (.tags | join(", ")) + "  \n" else "" end
        + if .pinned then "**pinned:** yes  \n" else "" end
        + if .added then "**added:** " + .added + "  \n" else "" end
      ' <<< "$found" ;;
  esac
}

# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------
_cmd_add() {
  local name="" type="" desc="" caps="" scope="local" inv="" when="" tags="" pin=0
  local today; today=$(date +%Y-%m-%d)
  for arg in "$@"; do
    case "$arg" in
      --name=*)         name="${arg#--name=}" ;;
      --type=*)         type="${arg#--type=}" ;;
      --description=*)  desc="${arg#--description=}" ;;
      --desc=*)         desc="${arg#--desc=}" ;;        # alias for --description
      --capabilities=*) caps="${arg#--capabilities=}" ;;
      --scope=*)        scope="${arg#--scope=}" ;;
      --global)         scope="global" ;;               # alias for --scope=global
      --local)          scope="local" ;;                # alias for --scope=local
      --invocation=*)   inv="${arg#--invocation=}" ;;
      --when=*)         when="${arg#--when=}" ;;
      --tags=*)         tags="${arg#--tags=}" ;;
      --pin)            pin=1 ;;
      -h|--help) _usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  [[ -n "$name" ]]  || { echo "ERROR: --name required"        >&2; exit 1; }
  [[ -n "$type" ]]  || { echo "ERROR: --type required"        >&2; exit 1; }
  [[ -n "$desc" ]]  || { echo "ERROR: --description required" >&2; exit 1; }

  # Validate scope value.
  _scope_path "$scope" > /dev/null

  # Warn on non-canonical type (not fatal — user can register any type).
  if ! _is_canonical_type "$type"; then
    echo "shctx toolkit WARN: type '$type' is non-canonical (canonical: mcp, skill, plugin, cli)." >&2
    echo "  Consider using 'cli' for ssh/remote-shell targets." >&2
  fi

  # Capabilities: comma-separated string → JSON array.
  local caps_json="[]"
  [[ -n "$caps" ]] && caps_json=$(jq -cn --arg c "$caps" '($c | split(",")) | map(ltrimstr(" ") | rtrimstr(" "))')

  # Tags: comma-separated string → JSON array.
  local tags_json="[]"
  [[ -n "$tags" ]] && tags_json=$(jq -cn --arg t "$tags" '($t | split(",")) | map(ltrimstr(" ") | rtrimstr(" "))')

  local path; path=$(_scope_path "$scope")
  local tk; tk=$(_read_tk "$path")

  # Refuse duplicate name within the same scope file.
  local dup; dup=$(jq -r --arg n "$name" '.tools[] | select(.name == $n) | .name' <<< "$tk" || true)
  if [[ -n "$dup" ]]; then
    echo "ERROR: toolkit: tool '$name' already exists in $scope scope (use 'rm' first to replace)" >&2
    exit 1
  fi

  # Build the new entry object.
  local entry
  entry=$(jq -cn \
    --arg  name    "$name" \
    --arg  scope   "$scope" \
    --arg  type    "$type" \
    --argjson caps "$caps_json" \
    --arg  desc    "$desc" \
    --arg  inv     "$inv" \
    --arg  when    "$when" \
    --argjson tags "$tags_json" \
    --argjson pin  "$pin" \
    --arg  added   "$today" \
  '{
    name: $name,
    scope: $scope,
    type: $type,
    capabilities: $caps,
    description: $desc
  }
  + (if $inv  != "" then {invocation: $inv}  else {} end)
  + (if $when != "" then {when: $when}        else {} end)
  + (if ($tags | length) > 0 then {tags: $tags} else {} end)
  + {pinned: ($pin == 1), added: $added}
  ')

  # Append to tools array and write back.
  local new_tk; new_tk=$(jq --argjson e "$entry" '.tools += [$e]' <<< "$tk")
  _write_tk "$path" "$new_tk"
  echo "shctx toolkit add: '$name' registered in $scope toolkit ($path)"
}

# ---------------------------------------------------------------------------
# rm
# ---------------------------------------------------------------------------
_cmd_rm() {
  local name="${1:-}" scope=""
  [[ -n "$name" ]] || { echo "ERROR: usage: shctx toolkit rm <name> [--scope=local|global]" >&2; exit 1; }
  shift || true
  for arg in "$@"; do
    case "$arg" in
      --scope=*) scope="${arg#--scope=}" ;;
      --global)  scope="global" ;;   # alias for --scope=global
      --local)   scope="local" ;;    # alias for --scope=local
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local removed=0
  local scopes_to_search=("local" "global")
  [[ -n "$scope" ]] && scopes_to_search=("$scope")

  for s in "${scopes_to_search[@]}"; do
    local path; path=$(_scope_path "$s")
    [[ -f "$path" ]] || continue
    local tk; tk=$(cat "$path")
    local exists; exists=$(jq -r --arg n "$name" '.tools[] | select(.name == $n) | .name' <<< "$tk" || true)
    if [[ -n "$exists" ]]; then
      local new_tk; new_tk=$(jq --arg n "$name" '.tools = [.tools[] | select(.name != $n)]' <<< "$tk")
      _write_tk "$path" "$new_tk"
      echo "shctx toolkit rm: '$name' removed from $s toolkit"
      removed=1
    fi
  done

  [[ "$removed" -eq 1 ]] || { echo "ERROR: toolkit: tool '$name' not found" >&2; exit 1; }
}

# ---------------------------------------------------------------------------
# pin / unpin
# ---------------------------------------------------------------------------
_cmd_pin_unpin() {
  local sub="$1" name="${2:-}"
  [[ -n "$name" ]] || { echo "ERROR: usage: shctx toolkit $sub <name>" >&2; exit 1; }
  local val; [[ "$sub" == "pin" ]] && val=true || val=false

  local found=0
  for s in local global; do
    local path; path=$(_scope_path "$s")
    [[ -f "$path" ]] || continue
    local tk; tk=$(cat "$path")
    local exists; exists=$(jq -r --arg n "$name" '.tools[] | select(.name == $n) | .name' <<< "$tk" || true)
    if [[ -n "$exists" ]]; then
      local new_tk; new_tk=$(jq --arg n "$name" --argjson v "$val" \
        '.tools = [.tools[] | if .name == $n then .pinned = $v else . end]' <<< "$tk")
      _write_tk "$path" "$new_tk"
      echo "shctx toolkit $sub: '$name' updated in $s toolkit"
      found=1; break
    fi
  done
  [[ "$found" -eq 1 ]] || { echo "ERROR: toolkit: tool '$name' not found" >&2; exit 1; }
}

# ---------------------------------------------------------------------------
# md  — compact markdown for brief/session injection
# ---------------------------------------------------------------------------
# Graceful-empty: emits nothing when no tools match (consumers omit the block).
_cmd_md() {
  local scope="all" type_filter=""
  for arg in "$@"; do
    case "$arg" in
      --scope=*) scope="${arg#--scope=}" ;;
      --type=*)  type_filter="${arg#--type=}" ;;
      -h|--help) _usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local tools
  if [[ "$scope" == "all" ]]; then
    tools=$(_merge_all)
  else
    local path; path=$(_scope_path "$scope")
    tools=$(jq '.tools' < <(_read_tk "$path"))
  fi

  [[ -n "$type_filter" ]] && tools=$(jq --arg t "$type_filter" '[.[] | select(.type == $t)]' <<< "$tools")

  local count; count=$(jq 'length' <<< "$tools")
  [[ "$count" -gt 0 ]] || return 0  # graceful-empty

  # Section header + one line per tool, pinned first, grouped visually by type.
  # Bounded at 12 to mirror the SessionStart hook (toolkit_surface.sh) — both are
  # injected context surfaces, so they must agree. `list` stays uncapped.
  echo "### Available tools (toolkit)"
  echo
  jq -r '
    sort_by([if .pinned then 0 else 1 end, .type, .name])
    | .[0:12][]
    | "**" + .name + "** (" + .type + ", " + .scope + ") — " + .description
      + (if (.capabilities // [] | length) > 0 then " | caps: " + (.capabilities | join(", ")) else "" end)
      + (if .when then "\n  → when: " + .when else "" end)
  ' <<< "$tools"
}

# ---------------------------------------------------------------------------
# discovered  — compact markdown for the EPHEMERAL auto-discovered roster
# ---------------------------------------------------------------------------
# v6.1.5 (#146). Reads the gitignored cache file written by the SessionStart
# capability_discovery.sh hook and emits a LABELED markdown block, clearly
# DISTINCT from the curated toolkit. Graceful-empty: emits nothing when the
# roster is absent or carries zero auto-discovered capabilities. Bounded at 12,
# matching `md`. NEVER reads/writes toolkit.json — discovery is read-only here.
_cmd_discovered() {
  local path; path=$(_discovered_path)
  [[ -f "$path" ]] || return 0   # no probe yet → graceful-empty

  local caps
  caps=$(jq -c '.capabilities // []' "$path" 2>/dev/null || echo '[]')
  local count; count=$(jq 'length' <<< "$caps" 2>/dev/null || echo 0)
  [[ "${count:-0}" -gt 0 ]] || return 0  # graceful-empty

  echo "### Auto-discovered capabilities (ephemeral — NOT operator-curated)"
  echo
  jq -r '
    .[0:12][]
    | "**" + .name + "** (" + (.type // "?") + ", auto) — " + (.description // "(no description)")
      + (if (.capabilities // [] | length) > 0 then " | caps: " + (.capabilities | join(", ")) else "" end)
  ' <<< "$caps" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# init  — scaffold an empty toolkit.json + copy schema to <workdir>/types/
# ---------------------------------------------------------------------------
_cmd_init() {
  local scope="local"
  for arg in "$@"; do
    case "$arg" in
      --scope=*) scope="${arg#--scope=}" ;;
      -h|--help) _usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local path; path=$(_scope_path "$scope")

  if [[ -f "$path" ]]; then
    echo "shctx toolkit init: $path already exists (skipping)"
  else
    local empty; empty=$(jq -cn --arg s "$scope" --argjson now "$(shctx_now)" \
      '{"version":1,"scope":$s,"updated_at":$now,"tools":[]}')
    mkdir -p "$(dirname "$path")"
    printf '%s\n' "$empty" > "$path"
    echo "shctx toolkit init: created $path"
  fi

  # Copy bundled schema to <workdir>/types/toolkit.schema.json.
  # For global scope, place it alongside the global toolkit file.
  local types_dir
  if [[ "$scope" == "local" ]]; then
    types_dir="$(resolve_workdir)/types"
  else
    types_dir="$(dirname "$path")/types"
  fi
  mkdir -p "$types_dir"

  local schema_src; schema_src="$(shctx_skill_root)/references/toolkit.schema.json"
  local schema_dst="$types_dir/toolkit.schema.json"
  if [[ -f "$schema_src" ]]; then
    cp "$schema_src" "$schema_dst"
    echo "shctx toolkit init: schema → $schema_dst"
  else
    echo "shctx toolkit WARN: bundled schema not found at $schema_src" >&2
  fi
}

# ---------------------------------------------------------------------------
# validate  — check required fields; warn on non-canonical type
# ---------------------------------------------------------------------------
_cmd_validate() {
  local scope="all"
  for arg in "$@"; do
    case "$arg" in
      --scope=*) scope="${arg#--scope=}" ;;
      -h|--help) _usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local scopes=()
  case "$scope" in
    all)    scopes=("local" "global") ;;
    local)  scopes=("local") ;;
    global) scopes=("global") ;;
    *) echo "ERROR: --scope must be all|local|global" >&2; exit 1 ;;
  esac

  local hard_errors=0 warnings=0

  for s in "${scopes[@]}"; do
    local path; path=$(_scope_path "$s")
    [[ -f "$path" ]] || { echo "shctx toolkit validate: $s: no toolkit.json ($path) — skipping"; continue; }
    echo "shctx toolkit validate: checking $s ($path)"

    # Top-level required fields.
    local ver; ver=$(jq -r '.version // empty' "$path")
    local sc;  sc=$(jq -r '.scope // empty' "$path")
    local ua;  ua=$(jq -r '.updated_at // empty' "$path")

    [[ "$ver" == "1" ]] || { echo "  ERROR: .version must be 1 (got '$ver')" >&2; hard_errors=$((hard_errors+1)); }
    [[ "$sc" == "local" || "$sc" == "global" ]] || { echo "  ERROR: .scope must be local|global (got '$sc')" >&2; hard_errors=$((hard_errors+1)); }
    [[ -n "$ua" && "$ua" =~ ^[0-9]+$ ]] || { echo "  ERROR: .updated_at must be an integer epoch (got '$ua')" >&2; hard_errors=$((hard_errors+1)); }

    # Per-entry checks.
    local n; n=$(jq '.tools | length' "$path")
    local i=0
    while (( i < n )); do
      local entry; entry=$(jq --argjson i "$i" '.tools[$i]' "$path")
      local ename; ename=$(jq -r '.name // ""' <<< "$entry")
      local prefix="  tools[$i]$([ -n "$ename" ] && echo "($ename)" || true)"

      # Required fields.
      for field in name scope type capabilities description; do
        local fv; fv=$(jq -r --arg f "$field" '.[$f] // empty' <<< "$entry")
        [[ -n "$fv" ]] || {
          echo "  ERROR: ${prefix}: missing required field '$field'" >&2
          hard_errors=$((hard_errors+1))
        }
      done

      # capabilities must be a non-empty array.
      local caps_type; caps_type=$(jq -r '.capabilities | type' <<< "$entry" 2>/dev/null || echo "null")
      if [[ "$caps_type" != "array" ]]; then
        echo "  ERROR: ${prefix}: .capabilities must be an array" >&2
        hard_errors=$((hard_errors+1))
      else
        local caps_len; caps_len=$(jq '.capabilities | length' <<< "$entry")
        [[ "$caps_len" -ge 1 ]] || {
          echo "  WARN: ${prefix}: .capabilities is empty" >&2
          warnings=$((warnings+1))
        }
      fi

      # Non-canonical type warning (not an error).
      local etype; etype=$(jq -r '.type // ""' <<< "$entry")
      if [[ -n "$etype" ]] && ! _is_canonical_type "$etype"; then
        echo "  WARN: ${prefix}: type '$etype' is non-canonical (canonical: mcp, skill, plugin, cli)" >&2
        echo "        'cli' is recommended for ssh/remote-shell targets." >&2
        warnings=$((warnings+1))
      fi

      i=$((i+1))
    done

    echo "  ${n} tool(s): $hard_errors hard error(s), $warnings warning(s)"
  done

  [[ "$hard_errors" -eq 0 ]] || exit 1
}

# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------
_usage() {
  cat <<'EOF'
shctx toolkit <subcommand> [args]

  list   [--scope=local|global|all] [--type=T] [--json|--md]
                          List registered tools. Default: --scope=all --md.
                          Graceful-empty: emits nothing when no tools match.
  show   <name> [--json|--md]
                          Show a single tool entry.
  add    --name=N --type=T --description="..." [--capabilities=a,b,c]
         [--scope=local|global] [--invocation=...] [--when=...] [--tags=a,b] [--pin]
                          Register a new tool. Refuses duplicate name per scope
                          (rm first to replace). Default scope: local. Creates
                          toolkit.json if absent. Aliases: --desc=… for
                          --description=…; --global / --local for --scope=….
  rm     <name> [--scope=local|global]
                          Remove a tool. Searches local+global unless scope given.
                          Aliases: --global / --local for --scope=….
  pin    <name>           Pin a tool (appears first in list/md).
  unpin  <name>           Unpin a tool.
  md     [--scope=all|local|global] [--type=T]
                          Compact markdown for brief/session injection.
                          Graceful-empty (same contract as shctx adapt priors).
  discovered              Compact markdown for the EPHEMERAL auto-discovered
                          roster (cache/discovered-capabilities.json, written by
                          the SessionStart capability_discovery hook, #146).
                          Read-only; NEVER touches toolkit.json. Graceful-empty.
  init   [--scope=local|global]
                          Scaffold empty toolkit.json + copy schema to types/.
  validate [--scope=all|local|global]
                          Validate structure; warn on non-canonical type.
                          Exits non-zero on hard violations.

Canonical type enum: mcp | skill | plugin | cli
  Non-canonical types are permitted but flagged by validate.
  'cli' is the recommended type for ssh/remote-shell targets.

Storage:
  local  → \$(resolve_workdir)/toolkit.json      (project-specific)
  global → \${XDG_CONFIG_HOME:-\$HOME/.config}/shepherd/toolkit.json
EOF
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
sub="${1:-}"; shift || true
case "$sub" in
  ""|-h|--help) _usage; exit 0 ;;
  list)         _cmd_list     "$@" ;;
  show)         _cmd_show     "$@" ;;
  add)          _cmd_add      "$@" ;;
  rm|remove)    _cmd_rm       "$@" ;;
  pin|unpin)    _cmd_pin_unpin "$sub" "$@" ;;
  md)           _cmd_md       "$@" ;;
  discovered)   _cmd_discovered "$@" ;;
  init)         _cmd_init     "$@" ;;
  validate)     _cmd_validate "$@" ;;
  *) echo "ERROR: unknown subcommand: toolkit $sub" >&2; _usage >&2; exit 1 ;;
esac
