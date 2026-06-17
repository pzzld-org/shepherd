#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

scope="all"
for arg in "$@"; do
  case "$arg" in
    --scope=*) scope="${arg#--scope=}" ;;
    --all)     scope="all" ;;  # canonical "all targets" alias (v5.0.4)
    -h|--help)
      cat <<'EOF'
shctx refresh [--scope=symbols|shapes|github|artifacts|telemetry|all] [--all]

  --scope=NAME  refresh a single zone
                  symbols   — index public symbols from the workspace
                  shapes    — index public struct/enum FIELD SHAPES for `dups` (v6.1.8 #157)
                  github    — issues / PRs / releases / milestones via gh
                  artifacts — markdown specs / plans / handoffs / journal
                  telemetry — cache-usage events from <ns>/logs/events-*.jsonl (v5.1.3+)
                  all       — every zone above (default)
  --all         alias for --scope=all (canonical universal flag, v5.0.4)
EOF
      exit 0 ;;
    *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
  esac
done

# Refresh the cache-telemetry rollup from the JSONL event log. The function
# reads every <ns>/logs/events-*.jsonl, filters for event_type=='cache_usage',
# and inserts (idempotently via UNIQUE(session_id,agent_id,ts)) into
# index_cache_usage. See doctrines/cache-telemetry.md.
refresh_telemetry() {
  local project_id ns logs_dir db inserted
  project_id=$(shctx_project_id) || return 1
  ns=$(shctx_artifacts_root)
  logs_dir="$ns/logs"
  db=$(shctx_db_path)

  if [[ ! -d "$logs_dir" ]]; then
    echo "shctx refresh telemetry: no log dir at $logs_dir (skipping)"
    return 0
  fi

  inserted=$(python3 - "$project_id" "$db" "$logs_dir" <<'PY' 2>/dev/null
import glob, json, os, sqlite3, sys

project_id, db_path, logs_dir = sys.argv[1:]
inserted = 0
conn = sqlite3.connect(db_path)
try:
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()
    for path in sorted(glob.glob(os.path.join(logs_dir, "events-*.jsonl"))):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    if ev.get("event_type") != "cache_usage":
                        continue
                    # Coerce ISO ts string to unix seconds; tolerate already-int.
                    ts = ev.get("ts")
                    if isinstance(ts, str):
                        # Strip trailing 'Z' and fractional seconds for fromisoformat compatibility.
                        s = ts.rstrip("Z")
                        try:
                            import datetime as _dt
                            try:
                                dt = _dt.datetime.fromisoformat(s)
                            except ValueError:
                                # Drop microseconds / 'Z' edge cases.
                                if "." in s:
                                    s = s.split(".", 1)[0]
                                dt = _dt.datetime.fromisoformat(s)
                            ts_int = int(dt.replace(tzinfo=_dt.timezone.utc).timestamp())
                        except Exception:
                            continue
                    elif isinstance(ts, (int, float)):
                        ts_int = int(ts)
                    else:
                        continue
                    try:
                        cur.execute("""
                            INSERT OR IGNORE INTO index_cache_usage (
                              project_id, ts, session_id, role, agent_id, sprint,
                              turns, input_tokens, output_tokens,
                              cache_read_input_tokens, cache_creation_input_tokens,
                              ephemeral_5m_input_tokens, ephemeral_1h_input_tokens,
                              hit_rate, parse_error
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (
                            project_id,
                            ts_int,
                            ev.get("session_id"),
                            ev.get("role") or "unknown",
                            ev.get("agent_id"),
                            ev.get("sprint"),
                            ev.get("turns"),
                            ev.get("input_tokens"),
                            ev.get("output_tokens"),
                            ev.get("cache_read_input_tokens"),
                            ev.get("cache_creation_input_tokens"),
                            ev.get("ephemeral_5m_input_tokens"),
                            ev.get("ephemeral_1h_input_tokens"),
                            ev.get("hit_rate"),
                            ev.get("parse_error"),
                        ))
                        if cur.rowcount > 0:
                            inserted += 1
                    except sqlite3.Error:
                        # Individual row failure (e.g., FK violation on project_id) — skip.
                        continue
        except OSError:
            continue
    conn.commit()
finally:
    conn.close()

print(inserted)
PY
  ) || inserted="?"

  echo "shctx refresh telemetry: $inserted new row(s)"
}

# Refresh the struct/enum field-shape corpus (index_struct_shapes) used by
# `shctx dups`. Delegates to `dups scan --update --quiet` so the PreToolUse
# authoring gate and the close-time census read a current corpus. Fails open
# (no python3 / no rust files → no-op).
refresh_shapes() {
  bash "$HERE/cmd_dups.sh" scan --update --quiet
  echo "shctx refresh shapes: ok"
}

case "$scope" in
  symbols)   bash "$HERE/refresh-symbols.sh" ;;
  shapes)    refresh_shapes ;;
  github)    bash "$HERE/refresh-github.sh" ;;
  artifacts) bash "$HERE/refresh-artifacts.sh" ;;
  telemetry) refresh_telemetry ;;
  all)
    # Each scope is isolated — one zone's failure must not block the others.
    bash "$HERE/refresh-symbols.sh"   || echo "shctx: symbols refresh failed (continuing)"   >&2
    refresh_shapes                    || echo "shctx: shapes refresh failed (continuing)"     >&2
    bash "$HERE/refresh-github.sh"    || echo "shctx: github refresh failed (continuing)"    >&2
    bash "$HERE/refresh-artifacts.sh" || echo "shctx: artifacts refresh failed (continuing)" >&2
    refresh_telemetry                 || echo "shctx: telemetry refresh failed (continuing)" >&2
    ;;
  *) echo "ERROR: unknown --scope: $scope" >&2; exit 1 ;;
esac
