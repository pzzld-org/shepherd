#!/usr/bin/env bash
# hooks/tests/run.sh — smoke tests for shepherd's plugin hooks.
#
# Verifies every hook exits 0 under realistic Claude Code payloads. The bash
# tooling combination `set -euo pipefail` + bash 5.2 + a failing pipeline in a
# command substitution silently exits the script with a non-zero status —
# precisely the "Failed with non-blocking status code: No stderr output" that
# v5.1.0 shipped with. This file pins the contract.

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"

fails=0
total=0

run_case() {
  local name="$1" script="$2" payload="$3"
  total=$((total+1))
  local out err rc
  out=$(printf '%s' "$payload" | bash "$HOOKS_DIR/$script" 2>/tmp/shep-hook-err) || rc=$?
  rc=${rc:-0}
  err=$(cat /tmp/shep-hook-err)
  if [[ "$rc" -ne 0 ]]; then
    printf '  FAIL  %-50s rc=%d stderr=%q\n' "$name" "$rc" "$err"
    fails=$((fails+1))
  else
    printf '  PASS  %s\n' "$name"
  fi
}

# Each test runs inside an ephemeral shepherd-flagged repo so the hooks
# proceed past the `.claude/shepherd.toml` gate.
tmp=$(mktemp -d -t shep-hook-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude
touch .claude/shepherd.toml

echo "== session_open.sh =="
run_case "no-payload"          session_open.sh ''
run_case "session-start"       session_open.sh '{"session_id":"s1","hook_event_name":"SessionStart","source":"startup"}'
# v5.1.8 — quiet_warnings opt-out gate (#19). Default off; warnings visible.
mkdir -p "$tmp/.claude" && printf '[hooks]\nquiet_warnings = true\n' > "$tmp/.claude/shepherd.toml"
run_case "session-quiet-mode"  session_open.sh '{"session_id":"s1","hook_event_name":"SessionStart","source":"startup"}'
printf '' > "$tmp/.claude/shepherd.toml"

echo "== bash_guard.sh =="
run_case "normal-ls"           bash_guard.sh '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls -la"}}'
run_case "git-status"          bash_guard.sh '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"git status"}}'
run_case "cargo-sequential"    bash_guard.sh '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"cargo check && cargo clippy"}}'
run_case "cargo-backgrounded"  bash_guard.sh '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"cargo build & cargo test &"}}'
run_case "empty-input"         bash_guard.sh ''
run_case "no-command-field"    bash_guard.sh '{"session_id":"s1","tool_name":"Bash","tool_input":{}}'

echo "== bash_post.sh =="
run_case "post-ls"             bash_post.sh '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"},"tool_response":{"content":"foo"}}'
run_case "post-empty"          bash_post.sh ''

echo "== lock_guard.sh =="
run_case "no-lock"             lock_guard.sh '{"session_id":"s1","tool_name":"Edit","tool_input":{"file_path":"a"}}'
mkdir -p .artifacts
printf '{"session_id":"other","sprint":"v5.1.1-dev.0"}' > .artifacts/shepherd.lock
run_case "lock-conflict"       lock_guard.sh '{"session_id":"s1","tool_name":"Edit","tool_input":{"file_path":"a"}}'
run_case "lock-same-session"   lock_guard.sh '{"session_id":"other","tool_name":"Edit","tool_input":{"file_path":"a"}}'
rm -f .artifacts/shepherd.lock

echo "== agent_pause_detector.sh =="
run_case "no-pause"            agent_pause_detector.sh '{"session_id":"s1","tool_name":"Agent","tool_response":"plain text"}'
run_case "non-agent-tool"      agent_pause_detector.sh '{"session_id":"s1","tool_name":"Bash","tool_response":"x"}'

echo "== agent_insight_capture.sh =="
run_case "no-insights-block"   agent_insight_capture.sh '{"session_id":"s1","tool_name":"Agent","tool_response":"plain text"}'
run_case "non-agent-tool"      agent_insight_capture.sh '{"session_id":"s1","tool_name":"Bash","tool_response":"x"}'

echo "== cwd_changed.sh (v5.1.8) =="
run_case "no-payload"          cwd_changed.sh ''
run_case "cwd-event"           cwd_changed.sh '{"session_id":"s1","hook_event_name":"CwdChanged","cwd":"/tmp"}'

echo "== user_prompt_submit.sh (v5.1.8) =="
run_case "no-payload"          user_prompt_submit.sh ''
run_case "plain-prompt"        user_prompt_submit.sh '{"session_id":"s1","hook_event_name":"UserPromptSubmit","prompt":"hello"}'
run_case "shepherd-prompt"     user_prompt_submit.sh '{"session_id":"s1","hook_event_name":"UserPromptSubmit","prompt":"/shepherd:status"}'

echo "== worktree_lifecycle.sh (v5.1.8) =="
run_case "no-payload"          worktree_lifecycle.sh ''
run_case "non-worktree-event"  worktree_lifecycle.sh '{"session_id":"s1","hook_event_name":"PreToolUse"}'

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
