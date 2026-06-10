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
TESTS_DIR="$(pwd)"

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

# Static lint, not a payload-driven hook: assert the read-only flock reviewers
# carry no un-scoped mutating capability (GH #74). Runs against the real repo
# (the lint self-locates its REPO_ROOT), independent of the ephemeral test cwd.
echo "== lint_agent_capabilities.sh (GH #74 read-only capability lint) =="
total=$((total+1))
if lint_out=$(bash "$TESTS_DIR/lint_agent_capabilities.sh" 2>&1); then
  printf '  PASS  %s\n' "readonly-capability-lint"
else
  printf '  FAIL  %-50s\n' "readonly-capability-lint"
  printf '%s\n' "$lint_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# No-residual proof for the pause-for-dependency retirement (Lane F, #70/#53/#58).
echo "== test_pause_retired.sh (Lane F no-residual) =="
total=$((total+1))
if pause_out=$(bash "$TESTS_DIR/test_pause_retired.sh" 2>&1); then
  printf '  PASS  %s\n' "pause-retired-no-residual"
else
  printf '  FAIL  %-50s\n' "pause-retired-no-residual"
  printf '%s\n' "$pause_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Gate 1 evidence (v6.0.2 Wave 1): the #89 inversions + dispatch-class #66
# violations are mechanically blocked by dispatch_guard.sh + bash_guard.sh.
echo "== test_dispatch_guard.sh (Gate 1 — #89/#66 dispatch enforcement) =="
total=$((total+1))
if dg_out=$(bash "$TESTS_DIR/test_dispatch_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "dispatch-guard-blocks-inversions-and-violations"
else
  printf '  FAIL  %-50s\n' "dispatch-guard"
  printf '%s\n' "$dg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# DB-roundtrip tests for worktree_lifecycle.sh: WorktreeCreate row insertion,
# WorktreeRemove status flip, zombie worktree-agent-* ref sweep.
echo "== test_worktree_lifecycle.sh (worktree DB roundtrip) =="
total=$((total+1))
if wl_out=$(bash "$TESTS_DIR/test_worktree_lifecycle.sh" 2>&1); then
  printf '  PASS  %s\n' "worktree-lifecycle-db-roundtrip"
else
  printf '  FAIL  %-50s\n' "worktree-lifecycle"
  printf '%s\n' "$wl_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Coordinate-mode active-drive backstop (v6.0.5, #113/#98/#112): the Stop hook
# blocks a premature root halt while teammates are idle / lead mail is unread,
# fast-paths outside spawn sessions, and is runaway-bounded.
echo "== test_coordinate_drive_guard.sh (v6.0.5 — spawn active-drive) =="
total=$((total+1))
if cdg_out=$(bash "$TESTS_DIR/test_coordinate_drive_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "coordinate-drive-guard-blocks-passive-wait"
else
  printf '  FAIL  %-50s\n' "coordinate-drive-guard"
  printf '%s\n' "$cdg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Deterministic close-finalize completion check (v6.0.7, #127 fires #1–17):
# fast-paths for non-sprint branches, subworktrees, plant-mode artifacts, and
# missing signals; blocks only when close report committed AND branch on origin.
echo "== test_close_finalize_check.sh (v6.0.7 — #127 deterministic script) =="
total=$((total+1))
if cfc_out=$(bash "$TESTS_DIR/test_close_finalize_check.sh" 2>&1); then
  printf '  PASS  %s\n' "close-finalize-check-deterministic"
else
  printf '  FAIL  %-50s\n' "close-finalize-check"
  printf '%s\n' "$cfc_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Namespace-resolution parity (GH #121): the hooks resolve_namespace must agree
# with the skills resolve_workdir / docs §SHEPHERD_WORKDIR precedence, or hooks
# write into a different namespace than the shctx runtime reads (split-brain).
echo "== test_resolve_namespace.sh (#121 — hooks/skills namespace parity) =="
total=$((total+1))
if rns_out=$(bash "$TESTS_DIR/test_resolve_namespace.sh" 2>&1); then
  printf '  PASS  %s\n' "resolve-namespace-precedence-matches-contract"
else
  printf '  FAIL  %-50s\n' "resolve-namespace"
  printf '%s\n' "$rns_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# PreCompact snapshot hook (v6.0.9, #134): captures focus record + walk trace
# to a JSON snapshot before context compaction fires; fast-paths when no sprint
# is active or the DB is absent.
echo "== test_precompact_snapshot.sh (v6.0.9 — PreCompact focus snapshot) =="
total=$((total+1))
if pcs_out=$(bash "$TESTS_DIR/test_precompact_snapshot.sh" 2>&1); then
  printf '  PASS  %s\n' "precompact-snapshot-captures-focus-record"
else
  printf '  FAIL  %-50s\n' "precompact-snapshot"
  printf '%s\n' "$pcs_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Focus rehydrate hook (v6.0.9, #134): reads the PreCompact snapshot on
# SessionStart and re-upserts the focus record into root.db so the conductor
# resumes from the correct wave position after compaction.
echo "== test_focus_rehydrate.sh (v6.0.9 — PostCompact focus rehydration) =="
total=$((total+1))
if fr_out=$(bash "$TESTS_DIR/test_focus_rehydrate.sh" 2>&1); then
  printf '  PASS  %s\n' "focus-rehydrate-restores-focus-record"
else
  printf '  FAIL  %-50s\n' "focus-rehydrate"
  printf '%s\n' "$fr_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Hotfix vehicle guard (v6.0.9, #135): blocks teammate/TeamCreate spawns for a
# single-cluster (H=1) hotfix; passes through multi-cluster dispatch unchanged.
echo "== test_hotfix_vehicle_guard.sh (v6.0.9 — #135 hotfix cardinality gate) =="
total=$((total+1))
if hvg_out=$(bash "$TESTS_DIR/test_hotfix_vehicle_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "hotfix-vehicle-guard-blocks-wrong-vehicle"
else
  printf '  FAIL  %-50s\n' "hotfix-vehicle-guard"
  printf '%s\n' "$hvg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Teammate git guard (v6.0.9): blocks dev-branch integration commands
# (merge/rebase/push/cherry-pick onto dev branch) from teammate-conductor
# sessions; fast-paths outside teammate mode and for allowed commit ops.
echo "== test_teammate_git_guard.sh (v6.0.9 — teammate integration-authority gate) =="
total=$((total+1))
if tgg_out=$(bash "$TESTS_DIR/test_teammate_git_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "teammate-git-guard-blocks-integration-commands"
else
  printf '  FAIL  %-50s\n' "teammate-git-guard"
  printf '%s\n' "$tgg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
