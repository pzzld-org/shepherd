#!/usr/bin/env bash
# shepherd hook — PreToolUse(Agent|Task) dispatch-contract guard (v6.0.2, Wave 1)
#
# The mechanical enforcement of the primitive↔axis binding
# (doctrines/primitive-axis-binding.md) and the forbidden-dispatch matrix
# (doctrines/dispatch-tier-separation.md §IV-bis). Prose deterrence already
# failed in the field (#66, #89 — root spawned the conductor wave via the wrong
# primitive; coders were dispatched as teammates; general-purpose agents slipped
# through). This guard turns each invariant into a hard refusal.
#
# It inspects the OUTGOING Agent/Task tool_input (subagent_type, team_name) plus
# the CURRENT session's tier (teammate vs root/solo, from the platform env vars)
# and denies the construction when it violates the binding.
#
# Input  (stdin): PreToolUse JSON { tool_name, tool_input.{subagent_type,team_name,prompt,description}, ... }
# Output (stdout):
#   {"permissionDecision":"deny","message":"..."}   — a forbidden construction (hard block)
#   {"additionalContext":"..."}                       — a flagged-but-not-blocked pattern
#   exit 0 silently                                   — a well-formed dispatch
#
# Decision table (first match wins; halt codes per dispatch-tier-separation §IV-bis):
#   1. subagent_type ∈ {∅, general-purpose, Explore, Chat}     → DISPATCH-MISSING-SUBAGENT-TYPE  (deny)
#   2. teammate-session AND team_name set                       → TEAMMATE-NESTING-ATTEMPT        (deny)
#   3. team_name set AND subagent_type ≠ shepherd:conductor     → DISPATCH-TEAMMATE-TYPE-MISMATCH (deny)  [#66.1, #61]
#   4. teammate-session AND subagent_type ∈ {engineer,critic}   → WRONG-TIER-DISPATCH             (deny)  [#66]
#   5. subagent_type = shepherd:<x>, x ∉ closed-flock+conductor → DISPATCH-OFF-FLOCK              (deny)
#   6. teammate-session AND a flock fan-out role, no compile    → PRIMITIVE-INVERSION (handrolled) (flag) [#89 inversion 2]
#
# The lane↔teammate-conductor / step↔subagent assertion is exactly checks 2+3:
# a lane is the ONLY thing that may carry team_name, and it MUST be a conductor;
# a step (any flock role) carries NO team_name. Spawning teammates is therefore
# Agent Teams (Agent + team_name + shepherd:conductor), never anything else.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

tool=$(json_field "$input" '.tool_name')
case "$tool" in Agent|Task) ;; *) exit 0 ;; esac

subagent_type=$(json_field "$input" '.tool_input.subagent_type')
team_name=$(json_field "$input" '.tool_input.team_name')
session=$(json_field "$input" '.session_id')

# Tier detection: a teammate session sets one of these platform env vars
# (claude-code-platform-alignment.md; dispatch-tier-separation.md §III).
teammate_mode=0
if [[ -n "${CLAUDE_TEAMMATE_NAME:-}" || -n "${CLAUDE_AGENT_TEAMMATE_NAME:-}" \
   || "${CLAUDE_PROJECT_SESSION_TYPE:-}" == "teammate" ]]; then
  teammate_mode=1
fi

st_lc=$(printf '%s' "$subagent_type" | tr '[:upper:]' '[:lower:]')
FLOCK_RE='^shepherd:(engineer|critic|coder|auditor|worker|discovery)$'
CONDUCTOR='shepherd:conductor'
DOC='doctrines/primitive-axis-binding.md + doctrines/dispatch-tier-separation.md §IV-bis'

# ---------------------------------------------------------------------------
# Check 1 — missing / default subagent_type (DISPATCH-MISSING-SUBAGENT-TYPE)
# ---------------------------------------------------------------------------
case "$st_lc" in
  ""|general-purpose|explore|chat)
    msg="[shepherd] DISPATCH-MISSING-SUBAGENT-TYPE — refused."$'\n'
    msg+="  subagent_type: '${subagent_type:-<unset>}'"$'\n'
    msg+="Every flock dispatch MUST set subagent_type: \"shepherd:<role>\" (coder/auditor/"$'\n'
    msg+="worker/discovery, +engineer/critic at root, +conductor for a teammate spawn)."$'\n'
    msg+="Omitting it, or using general-purpose/Explore/Chat, breaks every framework"$'\n'
    msg+="discipline (brief contract, dedup-gate, halt codes, model pinning)."$'\n'
    msg+="See $DOC."
    emit_deny "$msg" "dispatch_guard" "$tool" "unknown" "$session"
    ;;
esac

# ---------------------------------------------------------------------------
# Check 2 — teammate trying to spawn a team (TEAMMATE-NESTING-ATTEMPT)
# ---------------------------------------------------------------------------
if [[ "$teammate_mode" -eq 1 && -n "$team_name" ]]; then
  msg="[shepherd] TEAMMATE-NESTING-ATTEMPT — refused."$'\n'
  msg+="  team_name: '$team_name' set from a TEAMMATE session."$'\n'
  msg+="A teammate-conductor is NOT a lead and owns no team. Nested teams are forbidden"$'\n'
  msg+="by the platform AND by shepherd doctrine. Your dispatches are subagents only"$'\n'
  msg+="(Agent({subagent_type: \"shepherd:<role>\"}) with NO team_name). Surface"$'\n'
  msg+="SendMessage(to: lead, halt_code: TEAMMATE-NESTING-ATTEMPT). See $DOC."
  emit_deny "$msg" "dispatch_guard" "$tool" "conductor-teammate" "$session"
fi

# ---------------------------------------------------------------------------
# Check 3 — a step spawned as a teammate (DISPATCH-TEAMMATE-TYPE-MISMATCH)
# Binding: a LANE (the only thing carrying team_name) MUST be a teammate-conductor.
# A flock role + team_name = a step masquerading as a lane. (#66.1, #61)
# ---------------------------------------------------------------------------
if [[ -n "$team_name" && "$st_lc" != "$CONDUCTOR" ]]; then
  msg="[shepherd] DISPATCH-TEAMMATE-TYPE-MISMATCH — refused."$'\n'
  msg+="  team_name: '$team_name'   subagent_type: '$subagent_type'"$'\n'
  msg+="Only a teammate-CONDUCTOR may carry team_name (a lane = one teammate-conductor,"$'\n'
  msg+="spawned via Agent Teams). A flock role is a STEP — an ephemeral subagent"$'\n'
  msg+="dispatched BY a conductor, never spawned AS a teammate. Either drop team_name"$'\n'
  msg+="(dispatch the step as a subagent) or set subagent_type: \"shepherd:conductor\""$'\n'
  msg+="(spawn a lane). See $DOC (step→subagent, lane→teammate-conductor)."
  emit_deny "$msg" "dispatch_guard" "$tool" "unknown" "$session"
fi

# ---------------------------------------------------------------------------
# Check 4 — teammate dispatching engineer/critic (WRONG-TIER-DISPATCH)
# ---------------------------------------------------------------------------
if [[ "$teammate_mode" -eq 1 && ( "$st_lc" == "shepherd:engineer" || "$st_lc" == "shepherd:critic" ) ]]; then
  role="${st_lc#shepherd:}"
  esc="PLAN-AUTHORSHIP-REQUEST"; [[ "$role" == "critic" ]] && esc="PLAN-GATE-REQUEST"
  msg="[shepherd] WRONG-TIER-DISPATCH — refused."$'\n'
  msg+="  A teammate tried to dispatch @${role} (root-tier-exclusive under /shepherd:spawn)."$'\n'
  msg+="@engineer and @critic run ONCE at root; the plan is fixed for all teammates."$'\n'
  msg+="Surface SendMessage(to: lead, halt_code: $esc) instead. See $DOC."
  emit_deny "$msg" "dispatch_guard" "$tool" "conductor-teammate" "$session"
fi

# ---------------------------------------------------------------------------
# Check 5 — shepherd:<unknown> outside the closed flock (DISPATCH-OFF-FLOCK)
# (Non-shepherd subagent_types are left to specialist-dispatch.md adjudication;
#  this guard only catches shepherd-namespaced impersonation.)
# ---------------------------------------------------------------------------
if [[ "$st_lc" == shepherd:* ]] && ! [[ "$st_lc" =~ $FLOCK_RE ]] && [[ "$st_lc" != "$CONDUCTOR" ]]; then
  msg="[shepherd] DISPATCH-OFF-FLOCK — refused."$'\n'
  msg+="  subagent_type: '$subagent_type' is not in the closed flock."$'\n'
  msg+="The flock is closed at six (engineer, critic, coder, auditor, worker, discovery)"$'\n'
  msg+="+ conductor (teammate spawns). Plan authorship, critic gating, audit grading,"$'\n'
  msg+="and code implementation are NEVER substitutable. See $DOC."
  emit_deny "$msg" "dispatch_guard" "$tool" "unknown" "$session"
fi

# ---------------------------------------------------------------------------
# Check 6 — hand-rolled fan-out where a compiled workflow is required (FLAG)
# #89 inversion 2: a teammate's gate-free step fan-out should compile to a
# Dynamic Workflow (shctx graph compile), not be hand-rolled in-context. A
# per-call hook cannot see the whole batch, so this is a non-blocking reminder
# when a teammate fires a flock fan-out role. The hard block is the compiler
# guard (#85, Wave 2); the PRIMARY-path doctrine is dispatch-cascade §IV-bis.
# Opt-in: only when [hooks].flag_handrolled_fanout = true (default off — avoids
# per-step noise; the reminder is most useful during teammate bring-up).
# ---------------------------------------------------------------------------
if [[ "$teammate_mode" -eq 1 ]] \
   && [[ "$st_lc" =~ ^shepherd:(coder|auditor)$ ]] \
   && [[ -f .claude/shepherd.toml ]] \
   && grep -qE '^[[:space:]]*flag_handrolled_fanout[[:space:]]*=[[:space:]]*true' .claude/shepherd.toml 2>/dev/null; then
  warn="[shepherd] PRIMITIVE-INVERSION (flag) — hand-rolled fan-out?"$'\n'
  warn+="A teammate's gate-free step fan-out (${st_lc}) should compile to a Dynamic"$'\n'
  warn+="Workflow: shctx graph compile --segment=<entry> --verify → run <seg>.workflow.js"$'\n'
  warn+="(dispatch-cascade.md §IV-bis is the PRIMARY path). Hand-rolled in-context"$'\n'
  warn+="dispatch is the fallback only on runtime failure. See $DOC."
  emit_context "$warn" "dispatch_guard" "$tool" "conductor-teammate" "$session"
fi

pass_silent "dispatch_guard" "$tool" "unknown" "$session"
