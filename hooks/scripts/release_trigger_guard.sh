#!/usr/bin/env bash
# shepherd hook — PreToolUse(Bash): release-trigger guard (v6.x).
#
# BACKSTOP for the "cut dev.{sprints_per_patch} instead of releasing" incident.
#
# PROBLEM: at the close of dev.{last} (e.g. v0.3.5-dev.9 with sprints_per_patch=10)
# an exhausted-context conductor ran the visible `git checkout -b …-dev.10` from the
# close brief and skipped the prose mod-N condition above it — cutting dev.10 instead
# of firing the release cascade (rebase dev.{last} → patch, squash patch → main, tag +
# release). references/branching-model.md §I: "No dev.{sprints_per_patch} ever — hitting
# it is a missed-release-trigger emergency." This guard makes that invariant mechanical.
#
# RULE: deny a Bash command that CREATES or PUBLISHES a sprint branch whose sprint
# number N >= sprints_per_patch (K). Legitimate mid-patch cuts (N < K) and dev.0 of the
# next patch (N = 0) are always allowed — they never reach K. Deletions/cleanup of a
# mis-created dev.>=K branch are ALSO allowed (remediation must not be blocked).
#
# Verbs watched: `git checkout -b`, `git switch -c`, `git branch <name>`, `git push`.
# N is the MAX dev.N token in the command (catches the create target regardless of
# argument position, e.g. `checkout -b v0.3.5-dev.10 v0.3.5-dev.9`).
#
# HALT CODE: RELEASE-TRIGGER-DEVLAST
# CONFIG:    [release].devlast_guard = block (default) | warn | off
# EVENT:     PreToolUse(Bash)
# STDIN:     { session_id, tool_name, tool_input.command, ... }
# OUTPUT:    {"permissionDecision":"deny","message":"…"}  — dev.>=K create/publish blocked
#            silent exit 0 — not a branch create/publish, N < K, a deletion, or guard off
# EXIT:      always 0 (fail-open on any error/uncertainty).

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- fast-path: only inside a shepherd project -------------------------------
is_shepherd_project || exit 0

# --- cheap pre-filter (perf): skip ALL JSON parsing unless the raw payload even
# mentions a dev.N branch token. This keeps the common Bash call (no dev.N) from
# ever spawning jq — the guard costs ~nothing on the 99% of commands it ignores.
printf '%s' "$PAYLOAD" | grep -qE '\-dev\.[0-9]+' 2>/dev/null || exit 0

# --- fast-path: only the Bash tool -------------------------------------------
TOOL="$(json_field "$PAYLOAD" '.tool_name' 2>/dev/null || true)"
[[ "$TOOL" == "Bash" ]] || exit 0

CMD="$(json_field "$PAYLOAD" '.tool_input.command' 2>/dev/null || true)"
[[ -n "$CMD" ]] || exit 0

# --- fast-path: must reference a sprint branch (…-dev.N) ----------------------
printf '%s' "$CMD" | grep -qE '\-dev\.[0-9]+' 2>/dev/null || exit 0

# --- never block deletion/cleanup of an existing (mis-created) dev branch -----
# `git branch -d/-D X`, `git push origin --delete X`, `git worktree remove …`.
printf '%s' "$CMD" | grep -qE '(--delete|[[:space:]]-[dD]([[:space:]]|$)|worktree[[:space:]]+remove)' 2>/dev/null && exit 0

# --- fast-path: must be a branch CREATE or PUBLISH ----------------------------
printf '%s' "$CMD" | grep -qE '(checkout[[:space:]]+-b|switch[[:space:]]+-c|git[[:space:]]+branch[[:space:]]|push)' 2>/dev/null || exit 0

# --- config: block (default) | warn | off ------------------------------------
MODE="block"
# cfg_get honors .claude/shepherd.local.toml + XDG global (v6.1.5).
cfg="$(cfg_get devlast_guard | grep -oE '(block|warn|off)' | tail -1 || true)"
[[ -n "$cfg" ]] && MODE="$cfg"
[[ "$MODE" == "off" ]] && exit 0

# --- sprints_per_patch (K), default 10 ---------------------------------------
K="$(cfg_get sprints_per_patch | grep -oE '[0-9]+' | tail -1 || true)"
[[ "$K" =~ ^[0-9]+$ ]] || K=10

# --- highest dev.N referenced in the command ---------------------------------
N="$(printf '%s' "$CMD" | grep -oE '\-dev\.[0-9]+' | grep -oE '[0-9]+$' | sort -rn | head -1)"
[[ "$N" =~ ^[0-9]+$ ]] || exit 0

# --- the guard: N >= K is the release trigger, never a new sprint ------------
[[ "$N" -ge "$K" ]] || exit 0

SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"

LAST=$((K - 1))
MSG="[shepherd] RELEASE-TRIGGER-DEVLAST — refusing to create/publish dev.${N} (sprints_per_patch=${K})."$'\n'
MSG+="  Halt code : RELEASE-TRIGGER-DEVLAST"$'\n'
MSG+="  Command   : ${CMD:0:200}"$'\n'
MSG+=""$'\n'
MSG+="dev.${N} is >= sprints_per_patch (${K}). There is no dev.${K}: closing dev.${LAST}"$'\n'
MSG+="(the patch's LAST sprint) is a RELEASE, not a new sprint. Cutting dev.${N} is the"$'\n'
MSG+="missed-release-trigger emergency (references/branching-model.md §I)."$'\n'
MSG+=""$'\n'
MSG+="Do this instead (references/branching-model.md §III + [release].driver):"$'\n'
MSG+="  1. Confirm the mechanical verdict:  shctx release --dry-run"$'\n'
MSG+="  2. Rebase dev.${LAST} -> the patch branch; delete the dev branch."$'\n'
MSG+="  3. Release per [release].driver:"$'\n'
MSG+="       conductor        ->  shctx release   (squash -> tag -> gh release -> next patch + dev.0)"$'\n'
MSG+="       github-workflow  ->  open the patch->main release PR; .github/workflows/release.yml runs the cascade"$'\n'
MSG+="       operator         ->  surface release notes and stop"$'\n'
MSG+=""$'\n'
MSG+="The next sprint branch after dev.${LAST} is dev.0 of the NEXT patch — never dev.${N}."$'\n'
MSG+="(Override: set [release].devlast_guard = warn|off in .claude/shepherd.toml.)"

if [[ "$MODE" == "warn" ]]; then
  echo "[shctx] release-trigger-guard: dev.${N} >= sprints_per_patch=${K} (warn mode — proceeding anyway)" >&2
  log_event "release_trigger_guard" "warn" "Bash" "shepherd" "$SESSION" \
    "$(emit_json_obj n "$N" k "$K")" 2>/dev/null || true
  exit 0
fi

# block mode (default): emit_deny logs internally and exits 0.
emit_deny "$MSG" "release_trigger_guard" "Bash" "shepherd" "$SESSION"
