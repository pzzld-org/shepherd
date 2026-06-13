#!/usr/bin/env bash
# shepherd hook — SessionEnd: dead-pane cleanup (closes the #66.6 gap).
#
# In teammateMode=tmux|auto, Claude Code opens one pane per teammate. Panes for
# CLOSED teammates (status crashed|retired) linger after a sprint — they were
# tracked (teammates.tmux_pane_id) but nothing ever reaped them. This hook sweeps
# them at session end by delegating to the single cleanup implementation,
# `shctx panes prune --closed-only` (never touches a live teammate's pane).
#
# CONFIG: [tmux].pane_cleanup = on (default) | off
# EVENT:  SessionEnd
# EXIT:   always 0 (best-effort; cleanup must never block session teardown).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

is_shepherd_project || exit 0
command -v tmux >/dev/null 2>&1 || exit 0

# config: on (default) | off
MODE="on"
# Resolved via cfg_get → honors .claude/shepherd.local.toml + XDG global (v6.1.5).
cfg="$(cfg_get pane_cleanup | grep -oE '(on|off)' | tail -1 || true)"
[[ -n "$cfg" ]] && MODE="$cfg"
[[ "$MODE" == "off" ]] && exit 0

# Delegate to the single cleanup implementation. shctx lives two dirs up from
# hooks/scripts/ at skills/context/scripts/shctx (CLAUDE_PLUGIN_ROOT-relative).
SHCTX="${CLAUDE_PLUGIN_ROOT:-$HERE/../..}/skills/context/scripts/shctx"
[[ -f "$SHCTX" ]] || exit 0
bash "$SHCTX" panes prune --closed-only >/dev/null 2>&1 || true
exit 0
