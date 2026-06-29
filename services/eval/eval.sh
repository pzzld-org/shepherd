#!/usr/bin/env bash
# services/eval/eval.sh — the shepherd eval harness.
#
# Scores a LATENT agent output (a conductor reflection, a discovery report, a
# seed, …) against a rubric, using the local-Claude-Code judge in services/llm.
# This is the standing follow-up from v6.2.0: the plugin's latent instructions
# finally have a behavioral eval, not just gate-tested storage.
#
# The latent/deterministic split this plugin teaches, applied to itself:
#   LATENT (the model owns it):  the per-dimension 1..scale scores + rationale.
#   DETERMINISTIC (code owns it): the rubric, the judge prompt build, the
#                                 weighted overall, the threshold verdict, the
#                                 exit code. Same scores in ⇒ same verdict out.
#
# Pure + stateless: reads a rubric + an input, returns a verdict. It does not
# touch a DB. `shctx eval` is the shepherd-side glue that resolves subjects from
# the registry and records verdicts; this service stays a clean function so it is
# trivially testable with a mocked judge (SHEPHERD_LLM_MOCK).
#
# ── Contract ────────────────────────────────────────────────────────────────
#   eval.sh run --kind=K [--input-file=F | --input=TXT | -] \
#               [--threshold=N] [--model=ALIAS] [--timeout=SEC] [--json|--md|--text]
#       Score the input against rubrics/K.rubric.json. Default format: text.
#       --json prints ONLY the machine verdict (what `shctx eval` records).
#   eval.sh rubrics            List available rubric kinds.
#   eval.sh show <kind>        Print a rubric.
#   eval.sh help
#
# ── Exit codes ──────────────────────────────────────────────────────────────
#   0 pass · 1 fail (below threshold) · 2 usage · 4 judge / parse error
#
# bash-3.2-safe. Depends on jq + the services/llm contract.
set -eu -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUBRIC_DIR="$HERE/rubrics"
LLM="${SHEPHERD_EVAL_LLM:-$HERE/../llm/llm.sh}"

die() { echo "eval.sh: $1" >&2; exit "${2:-1}"; }

usage() {
  cat <<'EOF'
services/eval/eval.sh — rubric-driven quality eval of a latent agent output.

Usage:
  eval.sh run --kind=K [--input-file=F | --input=TXT | -] \
              [--threshold=N] [--model=ALIAS] [--timeout=SEC] [--json|--md|--text]
  eval.sh rubrics            List available rubric kinds.
  eval.sh show <kind>        Print a rubric.
  eval.sh help

Exit: 0 pass · 1 fail (below threshold) · 2 usage · 4 judge/parse error
EOF
}

command -v jq >/dev/null 2>&1 || die "jq is required" 4

# ── rubric helpers ───────────────────────────────────────────────────────────
_rubric_path() { echo "$RUBRIC_DIR/$1.rubric.json"; }

cmd_rubrics() {
  local f k
  shopt -s nullglob
  for f in "$RUBRIC_DIR"/*.rubric.json; do
    k="$(basename "$f")"; k="${k%.rubric.json}"
    printf '%-14s %s\n' "$k" "$(jq -r '.subject' "$f" 2>/dev/null | cut -c1-80)"
  done
}

cmd_show() {
  local kind="${1:-}"; [[ -n "$kind" ]] || die "show needs a <kind>" 2
  local rp; rp="$(_rubric_path "$kind")"
  [[ -f "$rp" ]] || die "no rubric for kind '$kind' (try: eval.sh rubrics)" 2
  jq . "$rp"
}

# Extract a JSON object from a model response that may carry fences or prose.
# Tier 1: parse as-is. Tier 2: strip ``` fences. Tier 3: slice first { to last }.
_extract_json() {
  local raw="$1" clean
  if printf '%s' "$raw" | jq -e . >/dev/null 2>&1; then printf '%s' "$raw"; return 0; fi
  clean="$(printf '%s' "$raw" | sed -e 's/```json//g' -e 's/```//g')"
  if printf '%s' "$clean" | jq -e . >/dev/null 2>&1; then printf '%s' "$clean"; return 0; fi
  clean="$(printf '%s' "$clean" | tr '\n' ' ')"
  clean="{${clean#*\{}"      # drop everything before the first {
  clean="${clean%\}*}}"      # drop everything after the last }
  if printf '%s' "$clean" | jq -e . >/dev/null 2>&1; then printf '%s' "$clean"; return 0; fi
  return 1
}

cmd_run() {
  local kind="" inputfile="" input="" use_stdin=0 threshold="" model="" timeout="" fmt="text"
  local a
  for a in "$@"; do
    case "$a" in
      --kind=*)       kind="${a#--kind=}" ;;
      --input-file=*) inputfile="${a#--input-file=}" ;;
      --input=*)      input="${a#--input=}" ;;
      --threshold=*)  threshold="${a#--threshold=}" ;;
      --model=*)      model="${a#--model=}" ;;
      --timeout=*)    timeout="${a#--timeout=}" ;;
      --json)         fmt="json" ;;
      --md)           fmt="md" ;;
      --text)         fmt="text" ;;
      -)              use_stdin=1 ;;
      -h|--help)      usage; exit 0 ;;
      *) die "unknown arg: $a" 2 ;;
    esac
  done
  [[ -n "$kind" ]] || die "run needs --kind=<rubric>" 2
  local rp; rp="$(_rubric_path "$kind")"
  [[ -f "$rp" ]] || die "no rubric for kind '$kind' (try: eval.sh rubrics)" 2

  # Resolve the item to evaluate.
  local item=""
  if [[ -n "$inputfile" ]]; then
    [[ -f "$inputfile" ]] || die "--input-file not found: $inputfile" 2
    item="$(cat "$inputfile")"
  elif [[ -n "$input" ]]; then
    item="$input"
  else
    item="$(cat)"   # stdin (with or without explicit '-')
  fi
  [[ -n "${item//[[:space:]]/}" ]] || die "nothing to evaluate (empty input)" 2

  # Rubric fields.
  local scale subject guidance keys dims_text
  scale="$(jq -r '.scale' "$rp")"
  subject="$(jq -r '.subject' "$rp")"
  guidance="$(jq -r '.guidance // ""' "$rp")"
  [[ -z "$threshold" ]] && threshold="$(jq -r '.threshold // 60' "$rp")"
  [[ "$threshold" =~ ^[0-9]+$ ]] || die "--threshold must be an integer (got '$threshold')" 2
  keys="$(jq -r '[.dimensions[].key] | join(", ")' "$rp")"
  dims_text="$(jq -r --arg s "$scale" '.dimensions[] | "- " + .key + " (1.." + $s + "): " + .desc' "$rp")"

  # Build the judge prompts deterministically (reproducible from the rubric).
  local system prompt
  system="You are a strict, calibrated evaluation judge for the shepherd plugin. Score the SUBJECT against each rubric dimension on an integer scale of 1..${scale} (1=poor, ${scale}=excellent). Use the full range and default LOW when evidence is weak. Output ONLY a single JSON object and nothing else — no prose, no markdown fences. Shape: {\"scores\":{<dimension>:<int>,...},\"rationale\":\"<=160 chars\"}. Include exactly these dimension keys: ${keys}."
  prompt="SUBJECT TYPE: ${subject}

RUBRIC (score each dimension 1..${scale}):
${dims_text}

GUIDANCE: ${guidance}

=== ITEM TO EVALUATE (between the markers) ===
<<<
${item}
>>>

Return the JSON object now."

  # Call the LLM service (the only model seam). Forward model/timeout if set.
  local llm_args resp rc=0
  llm_args=( complete --system="$system" )
  [[ -n "$model" ]]   && llm_args=( "${llm_args[@]}" --model="$model" )
  [[ -n "$timeout" ]] && llm_args=( "${llm_args[@]}" --timeout="$timeout" )
  resp="$(printf '%s' "$prompt" | bash "$LLM" "${llm_args[@]}")" || rc=$?
  (( rc == 0 )) || die "judge call failed (llm.sh exit $rc)" 4

  # Resolve which model was actually used (for the record), mirroring llm.sh's default.
  local used_model="${model:-${SHEPHERD_LLM_MODEL:-opus}}"

  # Parse the judge's JSON.
  local vj
  vj="$(_extract_json "$resp")" || die "judge did not return parseable JSON:
$resp" 4

  # Validate + compute the deterministic verdict in jq.
  local result
  result="$(jq -n \
      --slurpfile rub "$rp" \
      --argjson resp "$vj" \
      --argjson threshold "$threshold" \
      --arg model "$used_model" \
      --arg kind "$kind" '
    ($rub[0]) as $r
    | ($r.scale) as $scale
    | ($r.dimensions) as $dims
    | ($resp.scores // {}) as $sc
    | ($dims | map(.key) | map($sc[.] == null) | any) as $missing
    | if $missing then error("missing dimension score in judge output") else . end
    | ($dims | map(($sc[.key]|type) != "number") | any) as $nonnum
    | if $nonnum then error("non-numeric dimension score") else . end
    | ($dims | map($sc[.key] < 1 or $sc[.key] > $scale) | any) as $oor
    | if $oor then error("dimension score out of range 1.." + ($scale|tostring)) else . end
    | ($dims | map(.weight) | add) as $tw
    | ($dims | map(($sc[.key]) * .weight) | add) as $ws
    | ((100 * $ws / ($scale * $tw) + 0.5) | floor) as $overall
    | { kind: $kind,
        model: $model,
        overall: $overall,
        threshold: $threshold,
        passed: ($overall >= $threshold),
        scale: $scale,
        scores: ($dims | map({ (.key): $sc[.key] }) | add),
        rationale: ($resp.rationale // "") }
  ' 2>/dev/null)" || die "judge output failed validation:
$vj" 4

  # Emit.
  local overall passed rationale
  overall="$(jq -r '.overall' <<<"$result")"
  passed="$(jq -r '.passed'  <<<"$result")"
  rationale="$(jq -r '.rationale' <<<"$result")"

  case "$fmt" in
    json) printf '%s\n' "$result" ;;
    md)
      printf '**EVAL `%s`** — score **%s/100** (threshold %s) — %s · model `%s`\n\n' \
        "$kind" "$overall" "$threshold" "$([[ "$passed" == true ]] && echo PASS || echo FAIL)" "$used_model"
      jq -r --arg s "$(jq -r .scale <<<"$result")" '.scores | to_entries[] | "- " + .key + ": " + (.value|tostring) + "/" + $s' <<<"$result"
      printf '\n_%s_\n' "$rationale"
      ;;
    *)
      printf 'EVAL %s — score=%s/100 threshold=%s %s  model=%s\n' \
        "$kind" "$overall" "$threshold" "$([[ "$passed" == true ]] && echo PASS || echo FAIL)" "$used_model"
      jq -r --arg s "$(jq -r .scale <<<"$result")" '.scores | to_entries | map(.key + "=" + (.value|tostring) + "/" + $s) | "  " + join("  ")' <<<"$result"
      printf '  rationale: %s\n' "$rationale"
      ;;
  esac

  [[ "$passed" == true ]] && exit 0 || exit 1
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  run)     cmd_run "$@" ;;
  rubrics) cmd_rubrics "$@" ;;
  show)    cmd_show "$@" ;;
  help|-h|--help) usage ;;
  *) die "unknown subcommand: $cmd (try: run | rubrics | show | help)" 2 ;;
esac
