#!/usr/bin/env bash
# PostToolUse(Bash) must not mint gate provenance from command text.

set -eu -o pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="${HOOK_OVERRIDE:-$ROOT/hooks/scripts/bash_post.sh}"
fails=0
cases=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails + 1)); }

if ! command -v jq >/dev/null 2>&1; then
  printf 'FAIL: jq is required by the registered telemetry adapter\n' >&2
  exit 1
fi

[[ -x "$HOOK" ]] || { printf 'FAIL: hook is not executable: %s\n' "$HOOK" >&2; exit 1; }

tmp="$(mktemp -d -t shep-bash-post.XXXXXX)"
trap 'find "$tmp" -depth -delete' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t@t
git_opts='-c commit.gpgsign=false'
git $git_opts commit -q --allow-empty -m init
mkdir -p .shepherd/runs/v100-dev0
cat > .shepherd/shepherd.toml <<'TOML'
[gates]
check = "cargo test -p shepherd-core"
TOML
printf '%s\n' '{"status":"executing"}' > .shepherd/runs/v100-dev0/run.json

run_case() {
  local label="$1" command_value="$2" response="${3-}" session="s$((cases + 1))" payload events unexpected
  local telemetry_files=() telemetry_file
  [[ -n "$response" ]] || response="{}"
  cases=$((cases + 1))
  if [[ "$command_value" == '__MISSING__' ]]; then
    payload="$(jq -nc --arg session "$session" --argjson response "$response" \
      '{session_id:$session,tool_name:"Bash",tool_input:{},tool_response:$response}')"
  else
    payload="$(jq -nc --arg session "$session" --arg command "$command_value" \
      --argjson response "$response" \
      '{session_id:$session,tool_name:"Bash",tool_input:{command:$command},tool_response:$response}')"
  fi
  printf '%s' "$payload" | bash "$HOOK" >/dev/null 2>&1 || true

  # Only ordinary hook telemetry may exist. A renamed ledger is still command
  # authority, so inspect every path below the event directory, not just its
  # immediate children. Only direct hooks-*.jsonl files are allowed.
  events=".shepherd/runs/v100-dev0/events"
  unexpected=""
  while IFS= read -r artifact; do
    case "$artifact" in
      "$events"/hooks-*.jsonl) ;;
      *) unexpected="$artifact"; break ;;
    esac
  done < <(find "$events" -mindepth 1 -print | sort)
  while IFS= read -r telemetry_file; do
    [[ -n "$telemetry_file" ]] || continue
    telemetry_files+=("$telemetry_file")
  done < <(find "$events" -mindepth 1 -type f -name 'hooks-*.jsonl' -print | sort)
  if [[ -n "$unexpected" ]]; then
    fail "$label does not create gate provenance" "unexpected non-telemetry artifact=$unexpected"
  elif [[ "${#telemetry_files[@]}" -eq 0 ]] || ! jq -e -s '    length > 0
    and all(.[]; .hook == "bash_post" and .decision == "pass" and .fields == {})
    and ([.[] | .. | objects | keys_unsorted[]
      | select(. == "command" or . == "gate" or . == "status" or
               . == "provenance" or . == "tool_input" or . == "tool_response" or
               . == "exit_code" or . == "result" or . == "invocation" or
               . == "invoked" or . == "passed" or . == "failed")] | length == 0)
  ' "${telemetry_files[@]}" >/dev/null; then
    fail "$label does not create gate provenance" "telemetry is missing or authoritative"
  else
    pass "$label does not create gate provenance"
  fi
}

# A command string is only an observation. None of these forms establishes
# process invocation or a result, so none may create a successful gate row.
run_case "comment" '# cargo test -p shepherd-core'
run_case "echo" "echo 'cargo test -p shepherd-core'"
run_case "printf" "printf '%s\\n' 'cargo test -p shepherd-core'"
run_case "quoted text" 'message="cargo test -p shepherd-core"; printf "%s\\n" "$message"'
run_case "concatenation" "printf '%s' 'cargo test -p ' 'shepherd-core'"
run_case "alias" "alias gate='cargo test -p shepherd-core'; gate"
run_case "wrapper" "bash -c 'cargo test -p shepherd-core'"
run_case "missing command" '__MISSING__'
run_case "failing gate" 'cargo test -p shepherd-core' '{"exit_code":1,"stderr":"gate failed"}'
run_case "outer success status" 'cargo test -p shepherd-core' '{"exit_code":0,"stdout":"gate passed"}'

# Positive control: ordinary Bash post telemetry still records the hook event,
# but the event is not gate provenance and carries no command-derived claim.
events=".shepherd/runs/v100-dev0/events"
if find "$events" -mindepth 1 -type f -name 'hooks-*.jsonl' -print -quit | grep -q . \
  && jq -e 'select(.hook == "bash_post" and .decision == "pass" and .fields == {})' \
    "$events"/hooks-*.jsonl >/dev/null; then
  pass "ordinary post-hook telemetry remains non-authoritative"
else
  fail "ordinary post-hook telemetry remains non-authoritative" "missing bash_post pass event"
fi

(( cases > 0 )) || { printf 'FAIL: zero adversarial cases executed\n' >&2; exit 1; }
printf '—— %d/%d adversarial cases passed, %d failed ——\n' "$((cases - fails))" "$cases" "$fails"
exit "$fails"
