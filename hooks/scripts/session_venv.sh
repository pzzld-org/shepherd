#!/usr/bin/env bash
# hooks/scripts/session_venv.sh -- SessionStart: keep the shepherd_cli venv fresh.
#
# Calls bin/shepherd-venv-ensure so the canonical `shepherd` Python CLI is
# importable without a manual `poetry install`. Idempotent (stamp-diff in the
# ensure script) and fail-open by contract: a venv problem never blocks a
# session. Only acts inside a shepherd project (or the plugin repo itself), so
# it never installs a venv for an unrelated repo.
set -uo pipefail

if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  ROOT="$CLAUDE_PLUGIN_ROOT"
else
  SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  ROOT="$(cd "$SELF/../.." && pwd)"
fi

# Gate: only prep the venv where shepherd is actually used.
[ -f ".claude/shepherd.toml" ] || [ -f "$ROOT/.claude/shepherd.toml" ] || exit 0

"$ROOT/bin/shepherd-venv-ensure" >/dev/null 2>&1 || true
exit 0
