#!/usr/bin/env bash
# shctx teammate — register/heartbeat/status/liveness/prune/retire
# Per skills/context/SKILL.md: teammates table is canonical
# store for teammate identity + liveness.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_lib.sh"
# Resolve DB path via the lib (honors $SHEPHERD_WORKDIR, then .shepherd/.artifacts).
DB="${SHCTX_DB:-$(shctx_db_path)}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
# Schema self-heal (v6.3.3 #200): bring a behind DB to HEAD before any query touches
# a recent column. Without this, a DB created under an older plugin (or left behind
# by the 0017 half-migration) crashes `liveness`/`state`/`prune` with
# "no such column: declared_state". Fail-soft — never blocks the command.
shctx_ensure_migrated

now_ms() { echo $(($(date +%s) * 1000)); }
project_id() {
  # Match cmd_init.sh convention: project id = project root path SHA-prefix.
  # For now, use a literal default; cmd_init populated the row.
  sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"
}
esc() { printf '%s' "$1" | sed "s/'/''/g"; }

# Explicit declared_state enum (migration 0019). NULL/'' = undeclared → liveness
# falls back to the last_seen_at timing heuristic. A declaration wins over timing.
DECLARED_STATES="init in-progress error complete idle"
validate_state() {
  case " $DECLARED_STATES " in *" $1 "*) return 0 ;; esac
  echo "ERR: TEAMMATE-STATE-INVALID — '$1' is not a known state. Known: init | in-progress | error | complete | idle." >&2
  return 1
}

usage() {
  cat <<'USAGE'
shctx teammate register <name> --team=<t> --type=<role> [--session=<uuid>] [--pane=<id>]
shctx teammate register-lead <team_id> --session=<lead_session_id>
shctx teammate heartbeat <name> [--phase=<p>] [--tool=<t>] [--note=<n>] [--state=<s>]
shctx teammate state <name> [--set=<s>]     # s ∈ init|in-progress|error|complete|idle
shctx teammate status <name>
shctx teammate liveness [--stale-mins=<n>]
shctx teammate prune --confirm [--name=<n>|--crashed [--stale-mins=<n>]]
shctx teammate retire <name>
USAGE
}

sub="${1:-}"; shift || true
case "$sub" in
  register)
    name="$1"; shift
    team=""; type=""; session=""; pane=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --team=*)    team="${1#*=}";;
      --type=*)    type="${1#*=}";;
      --session=*) session="${1#*=}";;
      --pane=*)    pane="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$team" && -n "$type" ]] || { usage; exit 2; }
    # TEAMMATE-ROLE gate (v6.2.7 #180; widened v6.3.0 #183). Two flock profiles
    # are legitimately spawned as native teammates: the lane teammate-CONDUCTOR
    # (one lane = one conductor) and the self-contained @engineer that root spawns
    # to author + self-gate the plan in-session (commands/spawn.md §Self-contained
    # engineer; skills/shepherd/references/flock.md §@engineer). Every OTHER flock
    # role (critic, coder, auditor, worker, discovery) is a SUBAGENT ONLY. The
    # Agent/Task PreToolUse guard (hooks/scripts/dispatch_guard.sh) cannot see a
    # native teammate-spawn — it isn't a hook-exposed tool call — so THIS
    # registration call is the one deterministic choke point every teammate passes
    # through. A field incident (#180) shipped @critic as a teammate twice despite
    # the prose contract; refuse the non-{conductor,engineer} roles here, loudly.
    # Refusing @engineer was ALSO a bug (#183): it left the self-contained engineer
    # unregistered, so `teammate liveness` returned empty and TeammateIdle could
    # not flip its status — a flood of unmatched idle pings the lead had to ignore.
    type_norm="$(printf '%s' "$type" | tr '[:upper:]' '[:lower:]')"
    case "$type_norm" in
      conductor|shepherd:conductor|engineer|shepherd:engineer) : ;;
      *)
        echo "ERR: TEAMMATE-ROLE-INVALID — refusing to register teammate '$name' with --type=$type." >&2
        echo "  Only shepherd:conductor (one lane = one teammate-conductor) and the self-contained" >&2
        echo "  shepherd:engineer may be spawned as native teammates. @critic/@coder/@auditor/" >&2
        echo "  @worker/@discovery are SUBAGENTS ONLY — dispatch via Agent/Task, never via a native" >&2
        echo "  teammate-spawn. To gate a plan or review a lane's output, dispatch @critic/@auditor" >&2
        echo "  as a subagent from within the conductor teammate (or from root), never as its own" >&2
        echo "  teammate. See skills/shepherd/references/pipeline.md §Lane law §II/§III.1 +" >&2
        echo "  skills/shepherd/SKILL.md §Dispatch law + commands/spawn.md §Self-contained engineer." >&2
        exit 1
        ;;
    esac
    pid="$(project_id)"
    id="$(uuidgen 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')"
    ts="$(now_ms)"
    # Idempotent register (v6.3.0 #183): root registers each teammate at spawn so
    # the row EXISTS before the first TeammateIdle fires (the hook matches by
    # teammate_name within the team). A re-register — root refresh, or a teammate
    # self-register at boot — must not violate UNIQUE(project_id,team_name,
    # teammate_name) or orphan the row id; upsert, preserving the id + heartbeat
    # history, and revive a previously crashed/retired name back to 'booting'.
    e_team="$(esc "$team")"; e_name="$(esc "$name")"; e_type="$(esc "$type")"
    e_session="$(esc "$session")"; e_pane="$(esc "$pane")"
    sqlite3 "$DB" "INSERT INTO teammates (id, project_id, team_name, teammate_name, agent_type, session_id, tmux_pane_id, spawned_at, last_seen_at, status)
      VALUES ('$id','$pid','$e_team','$e_name','$e_type',NULLIF('$e_session',''),NULLIF('$e_pane',''),$ts,$ts,'booting')
      ON CONFLICT(project_id, team_name, teammate_name) DO UPDATE SET
        agent_type   = excluded.agent_type,
        session_id   = COALESCE(excluded.session_id, teammates.session_id),
        tmux_pane_id = COALESCE(excluded.tmux_pane_id, teammates.tmux_pane_id),
        last_seen_at = excluded.last_seen_at,
        status       = CASE WHEN teammates.status IN ('retired','crashed') THEN 'booting' ELSE teammates.status END;"
    # Echo the canonical row id (existing on conflict, freshly inserted otherwise).
    sqlite3 "$DB" "SELECT id FROM teammates WHERE project_id='$pid' AND team_name='$e_team' AND teammate_name='$e_name';"
    ;;
  register-lead)
    # #223: record which session is the LEAD of a spawned team, so
    # coordinate_drive_guard.sh can tell "I am the recorded lead of a live
    # team" apart from "I am a bystander session sharing this DB with someone
    # else's live team". Spawn refuses a second concurrent team, so team_name
    # is a safe natural key — one row per live spawned team (migration 0021).
    team="$1"; shift || true
    session=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --session=*) session="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$team" && -n "$session" ]] || { echo "ERR: register-lead requires <team_id> --session=<lead_session_id>" >&2; usage; exit 2; }
    pid="$(project_id)"
    ts="$(now_ms)"
    e_team="$(esc "$team")"; e_session="$(esc "$session")"
    sqlite3 "$DB" "INSERT INTO spawn_leads (team_name, project_id, session_id, spawned_at)
      VALUES ('$e_team','$pid','$e_session',$ts)
      ON CONFLICT(team_name) DO UPDATE SET
        session_id  = excluded.session_id,
        spawned_at  = excluded.spawned_at;"
    ;;
  heartbeat)
    name="$1"; shift
    phase=""; tool=""; note=""; state=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --phase=*) phase="${1#*=}";;
      --tool=*)  tool="${1#*=}";;
      --note=*)  note="${1#*=}";;
      --state=*) state="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -z "$state" ]] || validate_state "$state" || exit 2
    ts="$(now_ms)"
    tid=$(sqlite3 "$DB" "SELECT id FROM teammates WHERE teammate_name='$(esc "$name")' ORDER BY spawned_at DESC LIMIT 1;")
    [[ -n "$tid" ]] || { echo "ERR: no teammate named $name" >&2; exit 1; }
    # Self-heal the tmux pane id: a teammate's heartbeat runs INSIDE its own pane,
    # so $TMUX_PANE identifies it. COALESCE keeps any value root already set via
    # --pane; this populates it when (as is usual) root spawned without one. First
    # consumer: `shctx panes` observability + the SessionEnd dead-pane cleanup.
    set_pane=""
    [[ -n "${TMUX_PANE:-}" ]] && set_pane=", tmux_pane_id = COALESCE(tmux_pane_id, '$(esc "${TMUX_PANE}")')"
    # Optional one-call declaration: `heartbeat --state=in-progress` both stamps
    # last_seen_at AND declares the explicit state (0019), so a teammate needs only
    # one call per phase boundary. Omitted → declared_state untouched.
    set_state=""
    [[ -n "$state" ]] && set_state=", declared_state='$state'"
    sqlite3 "$DB" "UPDATE teammates SET last_seen_at=$ts, status=CASE WHEN status='booting' THEN 'active' ELSE status END${set_pane}${set_state} WHERE id='$tid'; INSERT INTO heartbeats (teammate_id, ts, phase, tool_name, note) VALUES ('$tid', $ts, NULLIF('$(esc "$phase")',''), NULLIF('$(esc "$tool")',''), NULLIF('$(esc "$note")',''));"
    ;;
  state)
    # Explicit progress declaration (0019). `state <name>` reads the current value;
    # `state <name> --set=<s>` declares it. Callable by the teammate itself (its
    # name is in its boot brief) or by the lead for any teammate. This is the fact
    # that stops liveness / the coordinate-drive Stop hook from guessing wrong.
    name="${1:-}"; shift || true
    set_state=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --set=*) set_state="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$name" ]] || { usage; exit 2; }
    e_name="$(esc "$name")"
    tid=$(sqlite3 "$DB" "SELECT id FROM teammates WHERE teammate_name='$e_name' ORDER BY spawned_at DESC LIMIT 1;")
    [[ -n "$tid" ]] || { echo "ERR: no teammate named $name" >&2; exit 1; }
    if [[ -n "$set_state" ]]; then
      validate_state "$set_state" || exit 2
      sqlite3 "$DB" "UPDATE teammates SET declared_state='$set_state' WHERE id='$tid';"
    fi
    sqlite3 "$DB" "SELECT COALESCE(declared_state,'') FROM teammates WHERE id='$tid';"
    ;;
  status)
    name="$1"
    sqlite3 -json "$DB" "SELECT * FROM teammates WHERE teammate_name='$name' ORDER BY spawned_at DESC LIMIT 1;"
    ;;
  liveness)
    stale=5
    while [[ $# -gt 0 ]]; do case "$1" in
      --stale-mins=*) stale="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    threshold_ms=$((stale * 60 * 1000))
    # An explicit declared_state (0019) wins over the last_seen_at timing heuristic:
    # in-progress is affirmatively alive (never presumed-crashed, no matter the
    # heartbeat gap — #193); error is the escalation signal (#98); complete is
    # terminal; idle is an explicit rest. `init` is a TRANSIENT boot marker — it
    # falls through to the timing heuristic (a fresh init is fine, but an init gone
    # stale past the window is a crashed boot), so it stays prunable. NULL is
    # undeclared → pure pre-0019 timing behavior.
    # Backstop for #200: the self-heal above brings declared_state into existence in
    # virtually every case. If it could NOT (a read-only or locked DB), degrade to
    # the pre-0019 timing-only verdict instead of crashing on the missing column —
    # the same column-exists guard coordinate_drive_guard.sh uses.
    if [[ -n "$(sqlite3 "$DB" "SELECT 1 FROM pragma_table_info('teammates') WHERE name='declared_state' LIMIT 1;" 2>/dev/null)" ]]; then
      sqlite3 -header -column "$DB" "SELECT teammate_name, agent_type, status, COALESCE(declared_state,'-') AS declared, ms_since_seen/1000 AS sec_since_seen,
        CASE
          WHEN declared_state = 'in-progress' THEN 'ok'
          WHEN declared_state = 'error'       THEN 'error'
          WHEN declared_state = 'complete'    THEN 'complete'
          WHEN declared_state = 'idle'        THEN 'idle'
          WHEN ms_since_seen > $threshold_ms AND status IN ('booting','active') THEN 'presumed-crashed'
          ELSE 'ok'
        END AS verdict
        FROM v_teammates_live ORDER BY ms_since_seen DESC;"
    else
      sqlite3 -header -column "$DB" "SELECT teammate_name, agent_type, status, '-' AS declared, ms_since_seen/1000 AS sec_since_seen,
        CASE WHEN ms_since_seen > $threshold_ms AND status IN ('booting','active') THEN 'presumed-crashed' ELSE 'ok' END AS verdict
        FROM v_teammates_live ORDER BY ms_since_seen DESC;"
    fi
    ;;
  prune)
    confirm=0; name=""; crashed=0; stale=5
    while [[ $# -gt 0 ]]; do case "$1" in
      --confirm)      confirm=1;;
      --name=*)       name="${1#*=}";;
      --crashed)      crashed=1;;
      --stale-mins=*) stale="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ "$confirm" == "1" ]] || { echo "refusing prune without --confirm" >&2; exit 2; }
    where="1=1"
    [[ -n "$name" ]] && where="teammate_name='$(esc "$name")'"
    # --crashed matches the DERIVED presumed-crashed verdict `liveness` shows (#194),
    # NOT the status='crashed' literal that no writer ever sets (so the old filter
    # matched zero rows). A crash = an UNDECLARED teammate (declared_state IS NULL)
    # still booting/active whose last_seen_at is older than the stale window. A
    # teammate that declared init/in-progress/error/complete/idle is never a crash.
    if [[ "$crashed" == "1" ]]; then
      threshold_ms=$((stale * 60 * 1000))
      where="(declared_state IS NULL OR declared_state = 'init') AND status IN ('booting','active') AND (strftime('%s','now')*1000 - last_seen_at) > $threshold_ms"
    fi
    n=$(sqlite3 "$DB" "SELECT count(*) FROM teammates WHERE $where;")
    sqlite3 "$DB" "DELETE FROM teammates WHERE $where;"
    echo "pruned $n teammate(s)"
    ;;
  retire)
    name="$1"
    sqlite3 "$DB" "UPDATE teammates SET status='retired' WHERE teammate_name='$name';"
    ;;
  ""|help|--help|-h) usage;;
  *) echo "unknown subcommand: $sub" >&2; usage; exit 2;;
esac
