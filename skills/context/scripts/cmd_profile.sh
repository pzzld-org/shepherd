#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-list}"; shift || true
project_id=$(shctx_project_id)
now=$(shctx_now)
pdir="$(shctx_artifacts_root)/profiles"

case "$sub" in
  list)
    shctx_sql -header -column \
      "SELECT name, kind, active, source_path FROM profiles_defs WHERE project_id='$project_id';"
    ;;
  show)
    name="${1:-}"; [[ -n "$name" ]] || { echo "usage: profile show <name>" >&2; exit 1; }
    shctx_sql -header -column \
      "SELECT name, kind, active, json(config) AS config, source_path FROM profiles_defs WHERE project_id='$project_id' AND name='$name';"
    ;;
  enable|disable)
    name="${1:-}"; [[ -n "$name" ]] || { echo "usage: profile $sub <name>" >&2; exit 1; }
    val=$([[ "$sub" == "enable" ]] && echo 1 || echo 0)
    shctx_sql "UPDATE profiles_defs SET active=$val, updated_at=$now WHERE project_id='$project_id' AND name='$name';"
    ;;
  sync)
    [[ -d "$pdir" ]] || { echo "no profiles dir; nothing to sync"; exit 0; }
    for f in "$pdir"/*.toml; do
      [[ -f "$f" ]] || continue
      # Minimal TOML parser: name, kind, [config] block as JSON.
      name=$(awk -F' *= *' '/^name *=/{gsub(/"/,"",$2); print $2; exit}' "$f")
      kind=$(awk -F' *= *' '/^kind *=/{gsub(/"/,"",$2); print $2; exit}' "$f")
      config=$(awk '
        /^\[config\]/{flag=1; next}
        /^\[/{flag=0}
        flag && /=/{
          k=$1; sub(/ *=.*/,"",k);
          v=$0; sub(/^[^=]*= */,"",v); gsub(/"/,"\\\"",v);
          printf "\"%s\": %s, ", k, v
        }
        END{}' "$f" | sed 's/, $//')
      cfg_json="{${config:-}}"
      jq -e . >/dev/null 2>&1 <<<"$cfg_json" || cfg_json="{}"
      cfg_esc=${cfg_json//\'/\'\'}
      uid=$(shctx_uuid7)
      shctx_sql "INSERT INTO profiles_defs (id,project_id,name,kind,config,source_path,active,created_at,updated_at)
                 VALUES ('$uid','$project_id','$name','$kind','$cfg_esc','$f',1,$now,$now)
                 ON CONFLICT(project_id,name) DO UPDATE SET
                   kind=excluded.kind, config=excluded.config, source_path=excluded.source_path,
                   updated_at=excluded.updated_at;"
    done
    echo "shctx profile sync: ok"
    ;;
  *) echo "ERROR: usage: shctx profile <list|show|enable|disable|sync>" >&2; exit 1 ;;
esac
