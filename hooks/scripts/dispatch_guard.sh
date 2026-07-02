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
# PLATFORM MECHANISM (#93; UPDATED for v2.1.178 — supersedes shepherd's earlier
# `Agent({team_name})` AND `TeamCreate`-tool assumptions):
#   - Teammates spawn via the NATIVE teammate-spawn — a natural-language lead
#     instruction referencing the `shepherd:conductor` subagent type. There is NO
#     setup step and NO `TeamCreate`/`TeamDelete` tool (both REMOVED in v2.1.178);
#     the team forms automatically. The Agent/Task tool spawns SUBAGENTS only and
#     never creates a teammate. The `team_name` parameter on Agent/Task is accepted
#     but IGNORED (deprecated, v2.1.178) — it is NOT a teammate discriminator.
#   - A teammate session exposes NO identity env var (anthropics/claude-code#35447,
#     closed not-planned). Teammate identity lives in hook-input JSON, not env.
#   - Teammate nesting is structurally impossible (platform: "lead is fixed",
#     "no nested teams", "one team per session"). Dynamic Workflows orchestrate
#     subagents only.
#
# WHAT THIS GUARD ENFORCES, and how strongly:
#   - Checks 1 & 5 (subagent_type discipline / off-flock) are LOAD-BEARING and
#     MECHANICAL — they fire on the real Agent/Task tool_input on every dispatch,
#     and are the primary protection against the #66/#89 drift.
#   - Checks 2/3/4/6 are TIER checks. Reliable teammate-session detection is the
#     hard part: the platform exposes no teammate env var (#93), so this guard
#     detects a teammate best-effort from the hook-input `cwd` (a shepherd
#     `.worktrees/` path) plus legacy/convention env vars. With no signal they
#     no-op — acceptable, because teammate→team nesting is ALSO guaranteed
#     impossible by the platform, and the tier contract is additionally carried
#     by the conductor profile + escalation contract (defence in depth, not the
#     sole guarantee). The `team_name`-keyed branches (2,3) are VESTIGIAL as of
#     v2.1.178: `team_name` on Agent/Task is accepted but ignored, so it no longer
#     signals a teammate even if a caller sets it. They are retained as a
#     documented contract assertion + unit-tested belt-and-suspenders, harmless.
#
# Input  (stdin): PreToolUse JSON { tool_name, cwd, tool_input.{subagent_type,prompt,description,team_name?}, ... }
# Output (stdout):
#   {"permissionDecision":"deny","message":"..."}   — a forbidden construction (hard block)
#   {"additionalContext":"..."}                       — a flagged-but-not-blocked pattern
#   exit 0 silently                                   — a well-formed dispatch
#
# Decision table (first match wins; halt codes per dispatch-tier-separation §IV-bis):
#   1. subagent_type ∈ {∅, general-purpose, Explore, Chat}     → DISPATCH-MISSING-SUBAGENT-TYPE  (deny)  [mechanical]
#   2. teammate-session AND team_name set                       → TEAMMATE-NESTING-ATTEMPT        (deny)  [defence-in-depth]
#   3. team_name set AND subagent_type ≠ shepherd:conductor     → DISPATCH-TEAMMATE-TYPE-MISMATCH (deny)  [defence-in-depth; #66.1,#61]
#   4. teammate-session AND subagent_type = engineer            → WRONG-TIER-DISPATCH             (deny)  [#66; no nested/phantom engineer]
#   4'.teammate-session AND critic, NO engineer-self-contained  → WRONG-TIER-DISPATCH             (deny)  [#66; conductor lane re-gate — engineer self-gate is allowed]
#   4b.subagent_type = engineer AND brief mode: self-contained  → ENGINEER-TOPOLOGY-MISMATCH      (deny)  [#172; self-contained must be a teammate, not a subagent]
#   4c.brief dispatcher: engineer-self-contained AND type ∉ {discovery,auditor,critic} → ENGINEER-SUBFLOCK-VIOLATION (deny) [#172; sub-flock is read-only, no code]
#   5. subagent_type = shepherd:<x>, x ∉ closed-flock+conductor → DISPATCH-OFF-FLOCK              (deny)  [mechanical]
#   6. teammate-session AND a flock fan-out role, no compile    → PRIMITIVE-INVERSION (handrolled) (flag) [#89 inversion 2]
#
# Binding (doctrines/primitive-axis-binding.md): a LANE = one teammate-conductor
# spawned via the native teammate-spawn (Agent Teams; no TeamCreate tool); a STEP =
# a subagent (Agent/Task). Spawning
# a lane is NEVER a workflow; a step fan-out is NEVER hand-rolled. This guard is
# the mechanical half; the platform's structural guarantees + the conductor
# profile carry the rest.

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
cwd=$(json_field "$input" '.cwd')
prompt=$(json_field "$input" '.tool_input.prompt')

# Brief markers (v6.2.6, engineer-self-contained-plan.md). The engineer teammate's
# own brief FROM root carries `mode: self-contained`; the sub-flock briefs it
# authors (its @critic/@auditor/@discovery) carry `dispatcher: engineer-self-contained`.
# These distinguish (a) a self-contained engineer wrongly dispatched as a subagent
# from a legitimate teammate-spawn, and (b) the engineer's own @critic self-gate
# from a conductor lane trying to re-gate a fixed plan.
mode_self_contained=0
eng_self_dispatch=0
# Match the marker only as an actual FIELD assignment, not prose that happens to
# contain the phrase (a classic brief documenting "do NOT run in mode: self-contained"
# must not be misread as a self-contained dispatch). The field may appear in either
# the dotted form `[INVOCATION-CONTEXT].mode: self-contained` or the block form
# (`[INVOCATION-CONTEXT]` header then an indented `mode: self-contained` line), so
# anchor to line-start + optional indent + optional dotted prefix, and tolerate a
# quoted value / space-before-colon. grep reads the (real-newline) prompt line-by-line.
MODE_RE='^[[:space:]]*(\[INVOCATION-CONTEXT\]\.)?"?mode"?[[:space:]]*:[[:space:]]*"?self-contained'
DISP_RE='^[[:space:]]*(\[INVOCATION-CONTEXT\]\.)?"?dispatcher"?[[:space:]]*:[[:space:]]*"?engineer-self-contained'
printf '%s' "$prompt" | grep -qiE "$MODE_RE" && mode_self_contained=1
printf '%s' "$prompt" | grep -qiE "$DISP_RE" && eng_self_dispatch=1

# Tier detection (best-effort — the platform exposes NO teammate identity env var,
# #93 / anthropics/claude-code#35447). PRIMARY signal: a shepherd teammate runs in
# a `.worktrees/` worktree (commands/spawn.md §Worktree-per-teammate), visible in
# the PreToolUse `cwd` — env-independent. SECONDARY: legacy/convention env vars
# (read empty under the live platform; kept for forward-compat + unit tests).
# Absent any signal these checks no-op; teammate→team nesting is independently
# impossible per platform, so the subagent_type checks (1,5) remain the mechanical
# floor (claude-code-platform-alignment.md; dispatch-tier-separation.md §III).
teammate_mode=0
if [[ -n "${CLAUDE_TEAMMATE_NAME:-}" || -n "${CLAUDE_AGENT_TEAMMATE_NAME:-}" \
   || "${CLAUDE_PROJECT_SESSION_TYPE:-}" == "teammate" \
   || "$cwd" == */.worktrees/* ]]; then
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
#
# @engineer: ALWAYS refused from a teammate — no nested/phantom engineer; a
#   self-contained leader never spawns another leader (v6.2.6).
# @critic: refused from a CONDUCTOR teammate (a lane must not re-gate a fixed
#   plan) — but PERMITTED from the self-contained ENGINEER teammate gating its
#   OWN plan, signalled by `dispatcher: engineer-self-contained` in the critic
#   brief (engineer-self-contained-plan.md). The marker is the discriminator; a
#   forged marker is defence-in-depth-only (see header), the conductor profile
#   carries the no-re-gate rule regardless.
# ---------------------------------------------------------------------------
if [[ "$teammate_mode" -eq 1 && "$st_lc" == "shepherd:engineer" ]]; then
  msg="[shepherd] WRONG-TIER-DISPATCH — refused."$'\n'
  msg+="  A teammate tried to dispatch @engineer (root-tier-exclusive; no nested/phantom engineer)."$'\n'
  msg+="@engineer runs ONCE at root; a leader never spawns another leader."$'\n'
  msg+="Surface SendMessage(to: lead, halt_code: PLAN-AUTHORSHIP-REQUEST) instead. See $DOC."
  emit_deny "$msg" "dispatch_guard" "$tool" "conductor-teammate" "$session"
fi
if [[ "$teammate_mode" -eq 1 && "$st_lc" == "shepherd:critic" && "$eng_self_dispatch" -ne 1 ]]; then
  msg="[shepherd] WRONG-TIER-DISPATCH — refused."$'\n'
  msg+="  A teammate tried to dispatch @critic without the engineer-self-contained marker."$'\n'
  msg+="@critic gates the plan ONCE; a conductor lane must not re-gate a fixed plan."$'\n'
  msg+="(The self-contained ENGINEER teammate MAY dispatch @critic on its OWN plan —"$'\n'
  msg+=" tag the brief [INVOCATION-CONTEXT].dispatcher: engineer-self-contained.)"$'\n'
  msg+="Surface SendMessage(to: lead, halt_code: PLAN-GATE-REQUEST) instead. See $DOC."
  emit_deny "$msg" "dispatch_guard" "$tool" "conductor-teammate" "$session"
fi

# ---------------------------------------------------------------------------
# Check 4b — self-contained engineer dispatched as a SUBAGENT (ENGINEER-TOPOLOGY-MISMATCH)
# A self-contained engineer MUST be spawned as a NAMED teammate (native
# teammate-spawn, which does not go through this Agent/Task hook). An Agent/Task
# dispatch of @engineer whose brief carries `mode: self-contained` is therefore
# the wrong topology — the "unnamed subagent engineer" v6.2.5 failure. Fires
# regardless of teammate_mode (root dispatching it as a subagent is the main
# case; the teammate case is already denied by Check 4 above). Classic engineer
# dispatch (no mode marker) is unaffected. (engineer-self-contained-plan.md)
# ---------------------------------------------------------------------------
if [[ "$st_lc" == "shepherd:engineer" && "$mode_self_contained" -eq 1 ]]; then
  msg="[shepherd] ENGINEER-TOPOLOGY-MISMATCH — refused."$'\n'
  msg+="  @engineer dispatched as an Agent/Task SUBAGENT with mode: self-contained."$'\n'
  msg+="A self-contained engineer is a NAMED TEAMMATE (native teammate-spawn), never a"$'\n'
  msg+="subagent. Spawn it as a teammate, OR drop mode: self-contained to run classic"$'\n'
  msg+="(root runs discovery + @critic). See $DOC + doctrines/engineer-self-contained-plan.md."
  emit_deny "$msg" "dispatch_guard" "$tool" "unknown" "$session"
fi

# ---------------------------------------------------------------------------
# Check 4c — engineer's own sub-flock dispatch is READ-ONLY (ENGINEER-SUBFLOCK-VIOLATION)
# The self-contained engineer tags EVERY sub-flock dispatch with `dispatcher:
# engineer-self-contained` (agents/engineer.md). Its sub-flock is the three
# read-only / adversarial roles ONLY — @discovery, @auditor, @critic — so a marked
# dispatch to ANYTHING else (a write role @coder/@worker, or a nested @engineer) is
# refused. This gives "no code is touched during this phase" the same mechanical
# teeth as the topology/tier checks, not prose alone (#172). (A conductor lane does
# NOT carry this marker, so its legitimate @coder/@worker fan-out is unaffected.)
# ---------------------------------------------------------------------------
if [[ "$eng_self_dispatch" -eq 1 ]] && ! [[ "$st_lc" =~ ^shepherd:(discovery|auditor|critic)$ ]]; then
  msg="[shepherd] ENGINEER-SUBFLOCK-VIOLATION — refused."$'\n'
  msg+="  subagent_type: '$subagent_type' dispatched with dispatcher: engineer-self-contained."$'\n'
  msg+="The self-contained engineer's sub-flock is READ-ONLY and closed at three —"$'\n'
  msg+="@discovery, @auditor, @critic. No @coder/@worker (this phase touches no code),"$'\n'
  msg+="no nested @engineer. File a plan step for the conductor to spin a coder instead."$'\n'
  msg+="See $DOC + doctrines/engineer-self-contained-plan.md."
  emit_deny "$msg" "dispatch_guard" "$tool" "unknown" "$session"
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
   && [[ "$(cfg_get flag_handrolled_fanout)" == "true" ]]; then
  warn="[shepherd] PRIMITIVE-INVERSION (flag) — hand-rolled fan-out?"$'\n'
  warn+="A teammate's gate-free step fan-out (${st_lc}) should compile to a Dynamic"$'\n'
  warn+="Workflow: shctx graph compile --segment=<entry> --verify → run <seg>.workflow.js"$'\n'
  warn+="(dispatch-cascade.md §IV-bis is the PRIMARY path). Hand-rolled in-context"$'\n'
  warn+="dispatch is the fallback only on runtime failure. See $DOC."
  emit_context "$warn" "dispatch_guard" "$tool" "conductor-teammate" "$session"
fi

pass_silent "dispatch_guard" "$tool" "unknown" "$session"
