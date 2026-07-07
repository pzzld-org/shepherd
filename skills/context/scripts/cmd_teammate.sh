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

now_ms() { echo $(($(date +%s) * 1000)); }
project_id() {
  # Match cmd_init.sh convention: project id = project root path SHA-prefix.
  # For now, use a literal default; cmd_init populated the row.
  sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"
}

usage() {
  cat <<'USAGE'
shctx teammate register <name> --team=<t> --type=<role> [--session=<uuid>] [--pane=<id>]
shctx teammate heartbeat <name> [--phase=<p>] [--tool=<t>] [--note=<n>]
shctx teammate status <name>
shctx teammate liveness [--stale-mins=<n>]
shctx teammate prune --confirm [--name=<n>|--crashed]
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
    # CONDUCTOR-ONLY-TEAMMATE gate (v6.2.7, #180). Every teammate spawned via the
    # native teammate-spawn is a lane teammate-CONDUCTOR — no other flock role
    # (critic, engineer classic-mode, coder, auditor, worker, discovery) is ever
    # legitimately a teammate (skills/shepherd/references/pipeline.md §Lane law §II/§III.1;
    # dispatch-tier-separation.md). The Agent/Task PreToolUse guard
    # (hooks/scripts/dispatch_guard.sh) cannot see a native teammate-spawn at all —
    # it isn't a tool call the harness exposes a hook for (see dispatch_guard.sh's
    # own header note) — so THIS registration call is the one deterministic choke
    # point every teammate passes through. A field incident (#180) shipped @critic
    # as a teammate twice despite the prose contract; refuse here, loudly, instead
    # of trusting prose alone.
    type_norm="$(printf '%s' "$type" | tr '[:upper:]' '[:lower:]')"
    case "$type_norm" in
      conductor|shepherd:conductor) : ;;
      *)
        echo "ERR: CONDUCTOR-ONLY-TEAMMATE — refusing to register teammate '$name' with --type=$type." >&2
        echo "  Only shepherd:conductor may ever be spawned as a native teammate (one lane = one" >&2
        echo "  teammate-conductor). @critic/@engineer(classic)/@coder/@auditor/@worker/@discovery" >&2
        echo "  are SUBAGENTS ONLY — dispatch via Agent/Task, never via a native teammate-spawn" >&2
        echo "  instruction. If you meant to gate a plan or review a lane's output, dispatch" >&2
        echo "  @critic/@auditor as a subagent from within the conductor teammate (or from root)," >&2
        echo "  never as its own teammate. See skills/shepherd/references/pipeline.md §Lane law §II/§III.1 +" >&2
        echo "  skills/shepherd/SKILL.md §Dispatch law." >&2
        exit 1
        ;;
    esac
    pid="$(project_id)"
    id="$(uuidgen 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')"
    ts="$(now_ms)"
    sqlite3 "$DB" "INSERT INTO teammates (id, project_id, team_name, teammate_name, agent_type, session_id, tmux_pane_id, spawned_at, last_seen_at, status) VALUES ('$id','$pid','$team','$name','$type',NULLIF('$session',''),NULLIF('$pane',''),$ts,$ts,'booting');"
    echo "$id"
    ;;
  heartbeat)
    name="$1"; shift
    phase=""; tool=""; note=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --phase=*) phase="${1#*=}";;
      --tool=*)  tool="${1#*=}";;
      --note=*)  note="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    ts="$(now_ms)"
    tid=$(sqlite3 "$DB" "SELECT id FROM teammates WHERE teammate_name='$name' ORDER BY spawned_at DESC LIMIT 1;")
    [[ -n "$tid" ]] || { echo "ERR: no teammate named $name" >&2; exit 1; }
    # Self-heal the tmux pane id: a teammate's heartbeat runs INSIDE its own pane,
    # so $TMUX_PANE identifies it. COALESCE keeps any value root already set via
    # --pane; this populates it when (as is usual) root spawned without one. First
    # consumer: `shctx panes` observability + the SessionEnd dead-pane cleanup.
    set_pane=""
    [[ -n "${TMUX_PANE:-}" ]] && set_pane=", tmux_pane_id = COALESCE(tmux_pane_id, '${TMUX_PANE}')"
    sqlite3 "$DB" "UPDATE teammates SET last_seen_at=$ts, status=CASE WHEN status='booting' THEN 'active' ELSE status END${set_pane} WHERE id='$tid'; INSERT INTO heartbeats (teammate_id, ts, phase, tool_name, note) VALUES ('$tid', $ts, NULLIF('$phase',''), NULLIF('$tool',''), NULLIF('$note',''));"
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
    sqlite3 -header -column "$DB" "SELECT teammate_name, agent_type, status, ms_since_seen/1000 AS sec_since_seen, CASE WHEN ms_since_seen > $threshold_ms AND status IN ('booting','active') THEN 'presumed-crashed' ELSE 'ok' END AS verdict FROM v_teammates_live ORDER BY ms_since_seen DESC;"
    ;;
  prune)
    confirm=0; name=""; crashed=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --confirm)  confirm=1;;
      --name=*)   name="${1#*=}";;
      --crashed)  crashed=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ "$confirm" == "1" ]] || { echo "refusing prune without --confirm" >&2; exit 2; }
    where="1=1"
    [[ -n "$name" ]] && where="teammate_name='$name'"
    [[ "$crashed" == "1" ]] && where="status = 'crashed'"
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
