#!/usr/bin/env bash
# shepherd hook — PreToolUse(Agent|Task) dispatch-contract guard (v6.0.2, Wave 1)
#
# The mechanical enforcement of the primitive↔axis binding
# (skills/shepherd/references/pipeline.md §Lane law) and the forbidden-dispatch matrix
# (skills/shepherd/SKILL.md §Dispatch law §IV-bis). Prose deterrence already
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
#   - Check 7 (concern-declaration discipline) is LOAD-BEARING and MECHANICAL:
#     it fires on every `shepherd:auditor` dispatch and enforces
#     agents/auditor.md:92 ("brief's `concern` field is authoritative, NEVER
#     collapse two into one report") in code, not prose (DF-44; a bundled
#     five-concern @auditor dispatch at a live lane's own wave-review gate is
#     the incident this whole lane exists to make mechanically impossible).
#   - Check 8 is a PURE OBSERVER: it NEVER blocks or denies, under any
#     condition. Every `shepherd:<flock>` dispatch that reaches it (i.e. was
#     not already denied by Checks 1-7) gets a forensic ownership row
#     (dispatching session, subagent_type, model, lane if resolvable from
#     `cwd`/prompt, the declared `[CONCERN]` slug when Check 7 found exactly
#     one) appended to the SAME registry DB the teammate rows live in, so a
#     completion that surfaces in the wrong session (dispatch routing/
#     attribution confusion is a live, recurring failure mode this sprint)
#     can be traced back to who actually issued the Agent()/Task call.
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
#   6. teammate-session AND a flock fan-out role, no compile    → PRIMITIVE-INVERSION (handrolled) (flag) [#89 inversion 2; #263 default-ON]
#   7. subagent_type = shepherd:auditor, [CONCERN] count ≠ 1    → AUDIT-CONCERN-UNDECLARED        (deny)  [mechanical; agents/auditor.md:92, DF-44]
#   8. subagent_type = shepherd:<flock-or-conductor>, survives 1-7 → DISPATCH-OWNERSHIP-RECORD    (observer, never deny) [forensic dispatch attribution, DF-44]
#
# Binding (skills/shepherd/references/pipeline.md §Lane law): a LANE = one teammate-conductor
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
# tool_use_id/model are ONLY consumed by Check 8 (DISPATCH-OWNERSHIP-RECORD),
# deliberately NOT extracted here: two more json_field calls (each a jq/
# python3 subprocess spawn) on EVERY dispatch, including the large majority
# that exit at Checks 1-6 before Check 8 is ever reached, was measured
# overhead with no payoff for those paths. Extracted inline inside Check 8's
# own block below, where they are actually used. Both fields are confirmed
# live on THIS exact hook event by agent_invocation_tagger.sh (same
# PreToolUse payload, `.tool_use_id` top-level + `.tool_input.model`): not
# guessed.

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
DOC='skills/shepherd/references/pipeline.md §Lane law + skills/shepherd/SKILL.md §Dispatch law'

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
  msg+="(root runs discovery + @critic). See $DOC + skills/shepherd/references/pipeline.md §INTRO."
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
  msg+="See $DOC + skills/shepherd/references/pipeline.md §INTRO."
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
# Check 7: @auditor dispatch without exactly one declared concern
# (AUDIT-CONCERN-UNDECLARED, deny). DF-44: root dispatched a single @auditor
# at a live lane's own wave-review gate carrying FIVE bundled concerns.
# agents/auditor.md:92 forbids this in prose ("brief's `concern` field is
# authoritative, NEVER collapse two into one report"), and prose deterrence
# already failed once in the field. Zero declarations means the dispatcher
# never told the auditor what to grade; two-or-more bundles multiple reviews
# into one report, the exact DF-44 shape. Strict: a prose mention of the
# WORD "concern" is NOT a declaration, only a line-anchored `[CONCERN]
# <slug>` tag counts, same anchoring discipline as MODE_RE/DISP_RE above.
# ---------------------------------------------------------------------------
CONCERN_RE='^[[:space:]]*\[CONCERN\][[:space:]]+[A-Za-z0-9][A-Za-z0-9_-]*'
if [[ "$st_lc" == "shepherd:auditor" ]]; then
  concern_matches="$(printf '%s' "$prompt" | grep -oE "$CONCERN_RE" 2>/dev/null || true)"
  if [[ -z "$concern_matches" ]]; then
    concern_count=0
  else
    concern_count=$(printf '%s\n' "$concern_matches" | wc -l | tr -d '[:space:]')
  fi
  if [[ "$concern_count" -ne 1 ]]; then
    msg="[shepherd] AUDIT-CONCERN-UNDECLARED — refused."$'\n'
    msg+="  subagent_type: 'shepherd:auditor'   [CONCERN] declarations found: ${concern_count}"$'\n'
    msg+="agents/auditor.md:92 — \"brief's \`concern\` field is authoritative — NEVER"$'\n'
    msg+="collapse two into one report.\" Every @auditor dispatch MUST declare EXACTLY"$'\n'
    msg+="ONE concern, as a line of the form: [CONCERN] <slug>"$'\n'
    if [[ "$concern_count" -eq 0 ]]; then
      msg+="Found: none. A prose mention of the word \"concern\" does not count — the"$'\n'
      msg+="bracketed [CONCERN] tag is required, on its own line."
    else
      concern_list="$(printf '%s' "$concern_matches" \
        | sed -E 's/^[[:space:]]*\[CONCERN\][[:space:]]+//' | tr '\n' ',' | sed -E 's/,$//; s/,/, /g')"
      msg+="Found ${concern_count}: ${concern_list}."$'\n'
      msg+="Split into ${concern_count} separate dispatches, one [CONCERN] <slug> each."
    fi
    emit_deny "$msg" "dispatch_guard" "$tool" "unknown" "$session"
  fi
fi

# ---------------------------------------------------------------------------
# Check 8: DISPATCH-OWNERSHIP-RECORD (pure observer; NEVER denies, NEVER
# blocks, under any condition). DF-44 (retargeted mid-wave from an earlier
# WAVE-GATE-USURPED deny design: root's finding it was built on turned out
# to be a self-report of a violation that never happened, itself caused by
# the SAME dispatch-attribution gap this check now records against). Appends
# a forensic row (dispatching session, subagent_type, model, lane if
# resolvable from `cwd`/the prompt, never guessed, the `[CONCERN]` slug
# Check 7 already parsed when it found exactly one, and a timestamp) to the
# SAME registry DB `teammate_idle.sh`/`coordinate_drive_guard.sh` read
# (`resolve_namespace` + `hook_db_path`, no second code path). Only reaches
# dispatches that survive Checks 1-7 (this file's single-exit-per-invocation,
# first-match-wins architecture, see the header, means a check that fires
# via emit_deny/emit_context upstream has already exited before this point;
# extending ownership rows to denied dispatches too would mean restructuring
# 1-6, which is explicitly out of scope for this step).
#
# Table self-heal: hooks/scripts/_lib.sh (this file's only sourced lib) has
# no versioned-migration machinery. `shctx_ensure_migrated` is a DIFFERENT,
# skills-side helper (skills/context/scripts/_lib.sh, sourced only by `shctx`
# CLI commands, never by hooks) and a real skills/context/schema/migrations/
# entry is outside this step's exclusive [FILE-SCOPE] (hooks/scripts/
# dispatch_guard.sh only). `CREATE TABLE IF NOT EXISTS` on every invocation
# is the scope-correct equivalent: idempotent, same DB file, no parallel
# store. Flagged for the conductor as a deliberate, scope-driven deviation
# (see CODER REPORT); a real versioned migration is a legitimate follow-up.
# ---------------------------------------------------------------------------
sql_lit() {
  # Echo a single-quoted, escaped SQL string literal for a non-empty value,
  # or the bare word NULL for an empty/unset one. bash-3.2-safe.
  #
  # Escaping goes through `sed "s/'/''/g"` — the same idiom as
  # skills/context/scripts/cmd_teammate.sh's `esc()` — NOT the bash
  # `${v//\'/\'\'}` parameter-expansion doubling that used to live here: that
  # form inserts a literal backslash ahead of each doubled quote
  # (`o'brien` -> `'o\'\'brien'`), which is not valid SQL-literal escaping
  # and made sqlite3 reject the INSERT outright, silently dropping the
  # ownership row for any field containing an apostrophe. Verified against a
  # real `sqlite3 :memory:` parse, including a DROP-TABLE-shaped adversarial
  # value, before landing this.
  local v="$1"
  if [[ -z "$v" ]]; then
    printf 'NULL'
  else
    printf "'%s'" "$(printf '%s' "$v" | sed "s/'/''/g")"
  fi
}

if [[ "$st_lc" == shepherd:* ]]; then
  tool_use_id=$(json_field "$input" '.tool_use_id')
  model=$(json_field "$input" '.tool_input.model')

  do_lane=""
  case "$cwd" in
    */.worktrees/*)
      do_lane="$(printf '%s' "$cwd" | grep -oE '\.worktrees/[A-Za-z0-9_.-]+' 2>/dev/null | head -1 \
        | sed -E 's#^\.worktrees/##')" || true
      ;;
  esac
  if [[ -z "$do_lane" ]]; then
    do_lane="$(printf '%s' "$prompt" | grep -oE '\.worktrees/[A-Za-z0-9_.-]+' 2>/dev/null | head -1 \
      | sed -E 's#^\.worktrees/##')" || true
  fi

  do_concern=""
  if [[ "${concern_count:-0}" -eq 1 && -n "${concern_matches:-}" ]]; then
    do_concern="$(printf '%s' "$concern_matches" | sed -E 's/^[[:space:]]*\[CONCERN\][[:space:]]+//')"
  fi

  do_ns="$(resolve_namespace 2>/dev/null || echo .)"
  do_db="$(hook_db_path "$do_ns" 2>/dev/null || true)"
  do_ts=$(date +%s 2>/dev/null || echo 0)

  # WAL + synchronous=NORMAL: journal_mode is a PERSISTENT property of the
  # DB FILE (set once, on the first-ever write, and every later connection
  # inherits it, matching the codebase's own schema-init idiom, e.g.
  # skills/context/schema/0001_init.sql:3, migrations/0007:12); synchronous
  # is PER-CONNECTION and defaults back to FULL (fsync every commit) unless
  # reasserted here, so it has to be on every invocation's SQL, not just the
  # first. No existing journal_mode/synchronous idiom lives in hooks/scripts/
  # or skills/context/scripts/ (grepped both before writing this), so this
  # is the plain, direct form. Default rollback-journal mode measured at
  # ~91ms/invocation (fsync-per-write); WAL+NORMAL keeps Check 7/8's actual
  # deny/record/fail-visible behavior byte-for-byte unchanged, this is a
  # connection tuning change only.
  do_sql="PRAGMA busy_timeout=5000;
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS dispatch_ownership (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tool_use_id   TEXT,
  session_id    TEXT,
  subagent_type TEXT NOT NULL,
  model         TEXT,
  lane          TEXT,
  concern_slug  TEXT,
  tool          TEXT NOT NULL,
  recorded_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dispatch_ownership_recorded ON dispatch_ownership(recorded_at);
INSERT INTO dispatch_ownership
  (tool_use_id, session_id, subagent_type, model, lane, concern_slug, tool, recorded_at)
VALUES
  ($(sql_lit "$tool_use_id"), $(sql_lit "$session"), $(sql_lit "$subagent_type"), $(sql_lit "$model"),
   $(sql_lit "$do_lane"), $(sql_lit "$do_concern"), $(sql_lit "$tool"), $do_ts);"

  if ! command -v sqlite3 >/dev/null 2>&1; then
    warn="[shepherd] DISPATCH-OWNERSHIP-RECORD degraded — sqlite3 not found on PATH."$'\n'
    warn+="  subagent_type: '${subagent_type}'   tool_use_id: '${tool_use_id:-<none>}'"$'\n'
    warn+="Dispatch PASSED WITHOUT the ownership record — this observer NEVER blocks."
    emit_context "$warn" "dispatch_guard" "$tool" "unknown" "$session"
  else
    # Skip the mkdir(1) fork entirely once the namespace dir already exists
    # (the steady-state case on every invocation after the first): measured
    # ~30x cheaper as a bash builtin `[[ -d ]]` test than an unconditional
    # `mkdir -p` fork+exec on an already-existing directory.
    do_dir="$(dirname "$do_db")"
    do_mkdir_err=""
    [[ -d "$do_dir" ]] || do_mkdir_err="$(mkdir -p "$do_dir" 2>&1)" || true
    if [[ -n "$do_mkdir_err" ]]; then
      warn="[shepherd] DISPATCH-OWNERSHIP-RECORD degraded — registry directory create failed."$'\n'
      warn+="  dir: '${do_dir}'   subagent_type: '${subagent_type}'   tool_use_id: '${tool_use_id:-<none>}'"$'\n'
      warn+="  error: ${do_mkdir_err}"$'\n'
      warn+="Dispatch PASSED WITHOUT the ownership record — this observer NEVER blocks."
      emit_context "$warn" "dispatch_guard" "$tool" "unknown" "$session"
    elif ! do_err="$(sqlite3 "$do_db" "$do_sql" 2>&1)"; then
      warn="[shepherd] DISPATCH-OWNERSHIP-RECORD degraded — registry write failed."$'\n'
      warn+="  DB: '${do_db}'   subagent_type: '${subagent_type}'   tool_use_id: '${tool_use_id:-<none>}'"$'\n'
      warn+="  error: ${do_err}"$'\n'
      warn+="Dispatch PASSED WITHOUT the ownership record — this observer NEVER blocks."
      emit_context "$warn" "dispatch_guard" "$tool" "unknown" "$session"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Check 6 — hand-rolled fan-out where a compiled workflow is required (FLAG)
# #263 (fan-out vehicle inversion): a teammate's gate-free step fan-out MUST
# compile to a Dynamic Workflow. PRIMARY-path doctrine is now
# skills/shepherd/references/pipeline.md §Lane law + skills/shepherd/SKILL.md
# §Dispatch law (= $DOC, below) — the old "dispatch-cascade.md §IV-bis"
# citation named a doc path that no longer exists anywhere in this repo;
# repointed here to the live doctrine surfaces (#263). In-context Agent()
# dispatch at a grant-holding tier (root, a teammate-@conductor, a
# self-contained @engineer) is the DOWNGRADE path ONLY — legitimate exactly
# when the dispatcher ran WORKFLOW-VEHICLE-PROBE (read its own visible tool
# list for the literal token `Workflow`) FIRST, found the grant genuinely
# absent, and recorded a `fanout_downgrade_reason` alongside
# `fanout: "in-context"` in its WAVE-COMPLETE. A downgrade with no recorded
# reason at a grant-holding tier is FANOUT-VEHICLE-DOWNGRADE — a wave-review
# finding, never a certified-correct outcome. This check CANNOT distinguish a
# probed-and-recorded downgrade from a silent one, or a compiled Workflow's
# OWN internal agent() calls (never routed through THIS hook) from a
# genuinely hand-rolled batch — it is a single per-call PreToolUse invocation
# with no view of the whole batch — so it stays a non-blocking REMINDER,
# never a deny; a hard block, if one exists, is a batch-aware
# compiler/registry guard, not this hook.
# Default: ON (#263 — the behavior this flags is now a real finding, not
# per-step noise to be suppressed by default). Set
# [hooks].flag_handrolled_fanout = false to silence it per-operator; unset,
# or any value other than the literal string "false", keeps it ON.
# ---------------------------------------------------------------------------
if [[ "$teammate_mode" -eq 1 ]] \
   && [[ "$st_lc" =~ ^shepherd:(coder|auditor)$ ]] \
   && [[ "$(cfg_get flag_handrolled_fanout)" != "false" ]]; then
  warn="[shepherd] PRIMITIVE-INVERSION (flag) — hand-rolled fan-out where a"$'\n'
  warn+="compiled Dynamic Workflow is required (#263)."$'\n'
  warn+="A teammate's gate-free step fan-out (${st_lc}) MUST compile to a Dynamic"$'\n'
  warn+="Workflow: shctx graph compile --segment=<entry> --verify → run <seg>.workflow.js."$'\n'
  warn+="In-context Agent() dispatch is the DOWNGRADE path ONLY — legitimate if-and-"$'\n'
  warn+="only-if you ran WORKFLOW-VEHICLE-PROBE (read your visible tool list for the"$'\n'
  warn+="literal token \`Workflow\`) FIRST, found it genuinely absent, and recorded"$'\n'
  warn+="fanout_downgrade_reason (e.g. \"workflow-absent-from-tool-list\") alongside"$'\n'
  warn+="fanout: \"in-context\" in your WAVE-COMPLETE. A downgrade with no recorded"$'\n'
  warn+="reason is FANOUT-VEHICLE-DOWNGRADE — a wave-review finding, not a certified-"$'\n'
  warn+="correct outcome. If you have not probed yet, probe now before your next"$'\n'
  warn+="dispatch. NEVER ToolSearch for \`Workflow\` to answer the probe"$'\n'
  warn+="(WORKFLOW-SELFCHECK-TOOLSEARCH — ToolSearch resolves DEFERRED tools only, so a null"$'\n'
  warn+="on a native primitive is a false negative by construction and establishes nothing)."$'\n'
  warn+="Silence this reminder with [hooks].flag_handrolled_fanout = false. See $DOC."
  emit_context "$warn" "dispatch_guard" "$tool" "conductor-teammate" "$session"
fi

pass_silent "dispatch_guard" "$tool" "unknown" "$session"
