#!/usr/bin/env bash
# shctx eval — the shepherd-side glue for the eval harness (v6.2.3).
#
# services/eval is a PURE, stateless judge: (kind, input) → verdict JSON. This
# command is the stateful boundary: it resolves a subject from the registry
# (e.g. the reflection note for a sprint), calls that service through the
# services/llm contract, and records the verdict into `eval_runs`
# (migration 0018) so the dash + reports can surface eval scores over time.
#
# The latent/deterministic split: the per-dimension scores are the model's
# (latent); the rubric, the weighted overall, the threshold verdict, and this DB
# row are deterministic. Nothing here re-judges in latent space.
#
#   eval run --kind=K [--sprint=B] [--input-file=F | --input=TXT | -] \
#            [--threshold=N] [--model=M] [--timeout=S] [--record] [--json|--md]
#   eval report [--kind=K] [--sprint=B] [--json|--md]
#   eval list   [--kind=K] [--limit=N] [--json|--md]
#
# Exit (run): 0 pass · 1 below threshold · 2 usage · 4 judge/parse error.
# report/list always exit 0. bash-3.2-safe.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

usage() {
  cat <<'EOF'
shctx eval — quality-score a latent agent output against a rubric.

  eval run --kind=K [--sprint=B] [--input-file=F | --input=TXT | -] \
           [--threshold=N] [--model=M] [--timeout=S] [--record] [--json|--md]
      Score one item. With --kind=reflection --sprint=B (and no explicit input),
      the stored reflection note for that sprint is pulled from the registry.
      --record writes the verdict to eval_runs (surfaced by `shctx dash`).
  eval report [--kind=K] [--sprint=B] [--json|--md]   Latest recorded verdicts.
  eval list   [--kind=K] [--limit=N] [--json|--md]     Recent eval_runs.
  eval help

Judge model: --model > [eval].judge_model > opus. Threshold: --threshold > rubric.
Exit (run): 0 pass · 1 below threshold · 2 usage · 4 judge/parse error.
EOF
}

die() { echo "shctx eval: $1" >&2; exit "${2:-1}"; }

# Locate the eval service. Override with SHEPHERD_EVAL_SVC (tests, custom installs).
_eval_svc() {
  if [[ -n "${SHEPHERD_EVAL_SVC:-}" ]]; then echo "$SHEPHERD_EVAL_SVC"; return 0; fi
  if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" && -f "$CLAUDE_PLUGIN_ROOT/services/eval/eval.sh" ]]; then
    echo "$CLAUDE_PLUGIN_ROOT/services/eval/eval.sh"; return 0
  fi
  # skill root = <repo>/skills/context ; service = <repo>/services/eval/eval.sh
  local cand; cand="$(cd "$(shctx_skill_root)/../.." 2>/dev/null && pwd)/services/eval/eval.sh"
  echo "$cand"
}

_age() {
  local then="${1:-}" now d
  [[ -z "$then" || "$then" == "0" ]] && { echo "-"; return 0; }
  now="$(shctx_now)"; d=$(( now - then )); (( d < 0 )) && d=0
  if   (( d < 90 ));     then echo "${d}s"
  elif (( d < 5400 ));   then echo "$(( d/60 ))m"
  elif (( d < 172800 )); then echo "$(( d/3600 ))h"
  else                        echo "$(( d/86400 ))d"; fi
}

_has_eval_table() {
  [[ -n "$(shctx_sql "SELECT 1 FROM sqlite_master WHERE type='table' AND name='eval_runs' LIMIT 1;" 2>/dev/null || true)" ]]
}

# ── run ──────────────────────────────────────────────────────────────────────
_cmd_run() {
  local kind="" sprint="" inputfile="" input="" use_stdin=0 threshold="" model="" timeout="" record=0 fmt="text"
  local a
  for a in "$@"; do
    case "$a" in
      --kind=*)       kind="${a#--kind=}" ;;
      --sprint=*)     sprint="${a#--sprint=}" ;;
      --input-file=*) inputfile="${a#--input-file=}" ;;
      --input=*)      input="${a#--input=}" ;;
      --threshold=*)  threshold="${a#--threshold=}" ;;
      --model=*)      model="${a#--model=}" ;;
      --timeout=*)    timeout="${a#--timeout=}" ;;
      --record)       record=1 ;;
      --json)         fmt="json" ;;
      --md)           fmt="md" ;;
      --text)         fmt="text" ;;
      -)              use_stdin=1 ;;
      -h|--help)      usage; exit 0 ;;
      *) die "unknown arg: $a" 2 ;;
    esac
  done
  [[ -n "$kind" ]] || die "run needs --kind=<rubric>" 2

  local svc; svc="$(_eval_svc)"
  [[ -f "$svc" ]] || die "eval service not found at $svc (set SHEPHERD_EVAL_SVC)" 4

  # Resolve the model: flag > config > service default (opus).
  # cfg_get is section-agnostic + matches the bare key, so the TOML key is
  # `eval_judge_model` (prefixed to avoid collision, same convention as [dups]).
  [[ -z "$model" ]] && model="$(cfg_get eval_judge_model)"

  # Resolve the subject ref + the item to evaluate.
  local item="" subject_ref=""
  if [[ -n "$inputfile" ]]; then
    [[ -f "$inputfile" ]] || die "--input-file not found: $inputfile" 2
    item="$(cat "$inputfile")"; subject_ref="$(basename "$inputfile")"
  elif [[ -n "$input" ]]; then
    item="$input"; subject_ref="${sprint:-inline}"
  elif (( use_stdin )); then
    item="$(cat)"; subject_ref="${sprint:-stdin}"
  elif [[ -n "$sprint" && "$kind" == "reflection" ]]; then
    # Pull the stored reflection note for the sprint from the registry.
    local pid; pid="$(shctx_project_id)" || die "registry not initialized — run 'shctx init'" 4
    local sp_esc="${sprint//\'/\'\'}"
    local body
    body="$(shctx_sql "SELECT body FROM mem_entries
                       WHERE project_id='$pid' AND kind='prior'
                         AND title='prior: reflection ($sp_esc)' LIMIT 1;")"
    [[ -n "$body" ]] || die "no reflection stored for '$sprint' (run: shctx adapt reflect --sprint=$sprint --note=…)" 2
    # body shape: "[reflection] sprint <branch>: <note>" — keep just the note.
    item="$(printf '%s' "$body" | sed -E 's/^\[reflection\] sprint [^:]*: //')"
    subject_ref="$sprint"
  else
    die "no input — pass --input-file/--input/-, or (--kind=reflection --sprint=B)" 2
  fi
  [[ -n "${item//[[:space:]]/}" ]] || die "nothing to evaluate (empty input)" 2

  # Hand the item to the pure service; always ask for JSON so we can record it,
  # then render the requested format ourselves.
  local tmp; tmp="$(mktemp 2>/dev/null || mktemp -t shctxeval)"
  printf '%s' "$item" > "$tmp"
  local svc_args verdict rc=0
  svc_args=( run --kind="$kind" --input-file="$tmp" --json )
  [[ -n "$threshold" ]] && svc_args=( "${svc_args[@]}" --threshold="$threshold" )
  [[ -n "$model" ]]     && svc_args=( "${svc_args[@]}" --model="$model" )
  [[ -n "$timeout" ]]   && svc_args=( "${svc_args[@]}" --timeout="$timeout" )
  verdict="$(bash "$svc" "${svc_args[@]}")" || rc=$?
  rm -f "$tmp"
  # service: 0 pass, 1 fail (both carry a verdict); >=2 is a real error.
  if (( rc >= 2 )); then die "eval service error (exit $rc)" "$rc"; fi
  [[ -n "$verdict" ]] || die "eval service returned no verdict" 4

  # Extract fields.
  local overall passed_bool thr usedmodel scores rationale
  overall="$(jq -r '.overall'   <<<"$verdict")"
  passed_bool="$(jq -r '.passed' <<<"$verdict")"
  thr="$(jq -r '.threshold'     <<<"$verdict")"
  usedmodel="$(jq -r '.model'   <<<"$verdict")"
  scores="$(jq -c '.scores'     <<<"$verdict")"
  rationale="$(jq -r '.rationale' <<<"$verdict")"
  local passed_int=0; [[ "$passed_bool" == "true" ]] && passed_int=1

  # Record (optional).
  if (( record )); then
    _has_eval_table || die "eval_runs table missing — run 'shctx migrate'" 4
    local pid; pid="$(shctx_project_id)" || die "registry not initialized — run 'shctx init'" 4
    local id; id="$(shctx_uuid7)"
    local now; now="$(shctx_now)"
    local k_esc="${kind//\'/\'\'}"
    local sr_esc="${subject_ref//\'/\'\'}"
    local m_esc="${usedmodel//\'/\'\'}"
    local sc_esc="${scores//\'/\'\'}"
    local ra_esc="${rationale//\'/\'\'}"
    shctx_sql "INSERT INTO eval_runs
       (id,project_id,kind,subject_ref,score,threshold,passed,model,scores_json,rationale,created_at)
       VALUES ('$id','$pid','$k_esc','$sr_esc',$overall,$thr,$passed_int,'$m_esc','$sc_esc','$ra_esc',$now);"
  fi

  # Render.
  local verd; verd="$([[ "$passed_int" == 1 ]] && echo PASS || echo FAIL)"
  case "$fmt" in
    json) printf '%s\n' "$verdict" ;;
    md)
      printf '**EVAL `%s`** (%s) — **%s/100** (threshold %s) — %s · model `%s`%s\n\n' \
        "$kind" "$subject_ref" "$overall" "$thr" "$verd" "$usedmodel" \
        "$([[ "$record" == 1 ]] && echo ' · recorded' || true)"
      jq -r '.scores | to_entries[] | "- " + .key + ": " + (.value|tostring)' <<<"$verdict"
      printf '\n_%s_\n' "$rationale"
      ;;
    *)
      printf 'EVAL %s (%s) — score=%s/100 threshold=%s %s  model=%s%s\n' \
        "$kind" "$subject_ref" "$overall" "$thr" "$verd" "$usedmodel" \
        "$([[ "$record" == 1 ]] && echo '  [recorded]' || true)"
      printf '  scores: %s\n' "$scores"
      printf '  rationale: %s\n' "$rationale"
      ;;
  esac

  [[ "$passed_int" == 1 ]] && exit 0 || exit 1
}

# ── report ───────────────────────────────────────────────────────────────────
_cmd_report() {
  local kind="" sprint="" fmt="text" a
  for a in "$@"; do
    case "$a" in
      --kind=*)   kind="${a#--kind=}" ;;
      --sprint=*) sprint="${a#--sprint=}" ;;
      --json)     fmt="json" ;;
      --md)       fmt="md" ;;
      -h|--help)  usage; exit 0 ;;
      *) die "unknown arg: $a" 2 ;;
    esac
  done
  _has_eval_table || { [[ "$fmt" == json ]] && echo "[]" || echo "no evals yet (run: shctx eval run … --record)"; return 0; }
  local pid; pid="$(shctx_project_id 2>/dev/null || true)"
  [[ -n "$pid" ]] || { [[ "$fmt" == json ]] && echo "[]" || echo "no evals yet"; return 0; }
  local where="WHERE project_id='$pid'"
  [[ -n "$kind" ]]   && where="$where AND kind='${kind//\'/\'\'}'"
  [[ -n "$sprint" ]] && where="$where AND IFNULL(subject_ref,'')='${sprint//\'/\'\'}'"

  case "$fmt" in
    json)
      shctx_sql "SELECT COALESCE(json_group_array(json_object(
                   'kind',kind,'subject_ref',subject_ref,'score',score,'threshold',threshold,
                   'passed',json(CASE passed WHEN 1 THEN 'true' ELSE 'false' END),
                   'model',model,'rationale',rationale,'created_at',created_at)),'[]')
                 FROM (SELECT * FROM v_eval_latest $where ORDER BY created_at DESC, id DESC);"
      ;;
    md)
      local any; any="$(shctx_sql "SELECT 1 FROM v_eval_latest $where LIMIT 1;")"
      [[ -n "$any" ]] || { echo "_no evals recorded yet._"; return 0; }
      echo "### Eval scores (latest per subject)"
      echo
      echo "| kind | subject | score | thr | verdict | model |"
      echo "|------|---------|-------|-----|---------|-------|"
      shctx_sql "SELECT '| '||kind||' | '||COALESCE(subject_ref,'·')||' | '||score||' | '||threshold||' | '||
                        CASE passed WHEN 1 THEN 'PASS' ELSE 'FAIL' END||' | '||COALESCE(model,'·')||' |'
                 FROM v_eval_latest $where ORDER BY created_at DESC, id DESC;"
      ;;
    *)
      local rows; rows="$(shctx_sql "SELECT kind||'|'||COALESCE(subject_ref,'·')||'|'||score||'|'||threshold||'|'||
                          CASE passed WHEN 1 THEN 'PASS' ELSE 'FAIL' END||'|'||COALESCE(model,'·')||'|'||created_at
                          FROM v_eval_latest $where ORDER BY created_at DESC, id DESC;")"
      [[ -n "$rows" ]] || { echo "no evals recorded yet (run: shctx eval run … --record)"; return 0; }
      printf '%-12s %-16s %5s %4s %-5s %-8s %s\n' KIND SUBJECT SCORE THR VERD MODEL AGE
      local k s sc th v m t
      printf '%s\n' "$rows" | while IFS='|' read -r k s sc th v m t; do
        printf '%-12s %-16s %4s%% %4s %-5s %-8s %s\n' "$k" "$s" "$sc" "$th" "$v" "$m" "$(_age "$t")"
      done
      ;;
  esac
}

# ── list ─────────────────────────────────────────────────────────────────────
_cmd_list() {
  local kind="" limit=10 fmt="text" a
  for a in "$@"; do
    case "$a" in
      --kind=*)  kind="${a#--kind=}" ;;
      --limit=*) limit="${a#--limit=}" ;;
      --json)    fmt="json" ;;
      --md)      fmt="md" ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown arg: $a" 2 ;;
    esac
  done
  [[ "$limit" =~ ^[0-9]+$ ]] || die "--limit must be an integer" 2
  _has_eval_table || { [[ "$fmt" == json ]] && echo "[]" || echo "no evals yet"; return 0; }
  local pid; pid="$(shctx_project_id 2>/dev/null || true)"
  [[ -n "$pid" ]] || { [[ "$fmt" == json ]] && echo "[]" || echo "no evals yet"; return 0; }
  local where="WHERE project_id='$pid'"
  [[ -n "$kind" ]] && where="$where AND kind='${kind//\'/\'\'}'"
  if [[ "$fmt" == json ]]; then
    shctx_sql "SELECT COALESCE(json_group_array(json_object(
                 'id',id,'kind',kind,'subject_ref',subject_ref,'score',score,'threshold',threshold,
                 'passed',json(CASE passed WHEN 1 THEN 'true' ELSE 'false' END),'model',model,'created_at',created_at)),'[]')
               FROM (SELECT * FROM eval_runs $where ORDER BY created_at DESC, id DESC LIMIT $limit);"
  else
    local rows; rows="$(shctx_sql "SELECT kind||'|'||COALESCE(subject_ref,'·')||'|'||score||'/'||threshold||'|'||
                        CASE passed WHEN 1 THEN 'PASS' ELSE 'FAIL' END||'|'||created_at
                        FROM eval_runs $where ORDER BY created_at DESC, id DESC LIMIT $limit;")"
    [[ -n "$rows" ]] || { echo "no evals recorded yet"; return 0; }
    local k s sc v t
    printf '%s\n' "$rows" | while IFS='|' read -r k s sc v t; do
      printf '%-12s %-16s %-8s %-5s %s ago\n' "$k" "$s" "$sc" "$v" "$(_age "$t")"
    done
  fi
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  run)    _cmd_run "$@" ;;
  report) _cmd_report "$@" ;;
  list)   _cmd_list "$@" ;;
  help|-h|--help) usage ;;
  *) die "unknown subcommand: $cmd (try: run | report | list | help)" 2 ;;
esac
