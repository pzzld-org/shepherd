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

echo "== teammate_heartbeat.sh (v6.3.3 #193 — auto liveness) =="
run_case "hb-no-payload"       teammate_heartbeat.sh ''
run_case "hb-bash-no-db"       teammate_heartbeat.sh '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"}}'
run_case "hb-edit-no-db"       teammate_heartbeat.sh '{"session_id":"s1","tool_name":"Edit","tool_input":{"file_path":"x"}}'

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

echo "== dups_write_guard.sh (v6.1.8 #157) — fast-path smoke =="
# No corpus / no coder dispatch record → role resolves to conductor → silent pass.
run_case "no-payload"          dups_write_guard.sh ''
run_case "non-coder-role"      dups_write_guard.sh '{"session_id":"s1","tool_name":"Write","tool_use_id":"x","tool_input":{"file_path":"a.rs","content":"pub struct A{a:u8,b:u8}"}}'
run_case "non-rust-file"       dups_write_guard.sh '{"session_id":"s1","tool_name":"Write","tool_use_id":"x","tool_input":{"file_path":"a.md","content":"hi"}}'
run_case "non-write-tool"      dups_write_guard.sh '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"}}'

echo "== seed_preflight_check.sh (v6.2.1) — fast-path smoke =="
run_case "no-payload"          seed_preflight_check.sh ''
run_case "non-write-tool"      seed_preflight_check.sh '{"session_id":"s1","tool_name":"Edit","tool_input":{"file_path":"x.seed.md","new_string":"x"}}'
run_case "non-seed-write"      seed_preflight_check.sh '{"session_id":"s1","tool_name":"Write","tool_input":{"file_path":"notes.md","content":"hi"}}'

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

echo "== conductor_write_guard.sh (v6.2.7 #180) — fast-path smoke =="
run_case "no-payload"          conductor_write_guard.sh ''
run_case "non-conductor-tool"  conductor_write_guard.sh '{"session_id":"s1","tool_name":"Read","tool_input":{"file_path":"a"}}'
run_case "no-sprint-open-edit" conductor_write_guard.sh '{"session_id":"s1","tool_name":"Edit","tool_input":{"file_path":"a.md"}}'

echo "== workflow_model_guard.sh (v6.2.9 #178) — fast-path smoke =="
run_case "no-payload"          workflow_model_guard.sh ''
run_case "non-workflow-tool"   workflow_model_guard.sh '{"session_id":"s1","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:coder"}}'
run_case "no-script-visible"   workflow_model_guard.sh '{"session_id":"s1","tool_name":"Workflow","tool_input":{"name":"a-saved-workflow"}}'
run_case "pinned-call"         workflow_model_guard.sh '{"session_id":"s1","tool_name":"Workflow","tool_input":{"script":"const r = await agent(\"x\", {model: \"sonnet\"})"}}'

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

# Changelog-currency gate (#130-adjacent): CHANGELOG.md must document the version
# in plugin.json — the guard that would have caught v6.3.4/v6.3.5 shipping
# undocumented. Static, self-locating; independent of the ephemeral test cwd.
echo "== test_changelog_current.sh (changelog-currency gate) =="
total=$((total+1))
if chlog_out=$(bash "$TESTS_DIR/test_changelog_current.sh" 2>&1); then
  printf '  PASS  %s\n' "changelog-documents-current-version"
else
  printf '  FAIL  %-50s\n' "changelog-current"
  printf '%s\n' "$chlog_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# #207 regression pin: the engineer + conductor leads must GRANT the Workflow
# tool their fan-out doctrine mandates. Exercises the lint's mandated-tool-
# presence guard in both directions (present passes / stripped fails).
echo "== test_lead_workflow_tool.sh (#207 lead-Workflow mandated-tool guard) =="
total=$((total+1))
if lead_wf_out=$(bash "$TESTS_DIR/test_lead_workflow_tool.sh" 2>&1); then
  printf '  PASS  %s\n' "lead-workflow-tool-mandated"
else
  printf '  FAIL  %-50s\n' "lead-workflow-tool-mandated"
  printf '%s\n' "$lead_wf_out" | sed 's/^/        /'
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

# Hotfix vehicle guard (v6.0.9, #135): blocks teammate-conductor spawns for a
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

# Worktree teardown guard (v6.1.0, #141): blocks blanket/destructive worktree
# teardown (git worktree prune, list|remove sweeps) when live teammates exist;
# passes scoped single-lane remove and all non-worktree commands.
echo "== test_worktree_teardown_guard.sh (v6.1.0 — #141 blanket teardown gate) =="
total=$((total+1))
if wtg_out=$(bash "$TESTS_DIR/test_worktree_teardown_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "worktree-teardown-guard-blocks-blanket-teardown"
else
  printf '  FAIL  %-50s\n' "worktree-teardown-guard"
  printf '%s\n' "$wtg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Field-shape dedup hook (v6.1.8, #157): dups_write_guard.sh blocks a renamed
# shadow (same field shape, different name) in block mode, warns in warn mode,
# and fast-paths (non-coder / non-rust / no corpus) silently. Sets up a corpus
# via shctx + a coder dispatch record, then drives the hook end-to-end.
echo "== test_dups_write_guard.sh (v6.1.8 — #157 field-shape authoring gate) =="
total=$((total+1))
if dwg_out=$(bash "$TESTS_DIR/test_dups_write_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "dups-write-guard-blocks-renamed-shadow"
else
  printf '  FAIL  %-50s\n' "dups-write-guard"
  printf '%s\n' "$dwg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# shctx CLI locator (v6.1.8): session_open must surface the absolute shctx path
# resolved from the hook's own location even when $CLAUDE_PLUGIN_ROOT is unset,
# with the "NOT on PATH / absent BY DESIGN" note — the antidote to a session
# falsely reporting "shctx absent". Off-switch must suppress it.
echo "== test_shctx_locator.sh (v6.1.8 — shctx-absent false-negative antidote) =="
total=$((total+1))
if loc_out=$(bash "$TESTS_DIR/test_shctx_locator.sh" 2>&1); then
  printf '  PASS  %s\n' "shctx-locator-surfaces-abs-path"
else
  printf '  FAIL  %-50s\n' "shctx-locator"
  printf '%s\n' "$loc_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Adaptation surface (v6.2.0): a NON-empty registry must surface the newest
# harvested lesson at session start (inverted from the old empty-only note);
# the [context].announce_adaptation off-switch must suppress it.
echo "== test_session_adaptation.sh (v6.2.0 — session_open adaptation surface) =="
total=$((total+1))
if adapt_out=$(bash "$TESTS_DIR/test_session_adaptation.sh" 2>&1); then
  printf '  PASS  %s\n' "session-adaptation-surface"
else
  printf '  FAIL  %-50s\n' "session-adaptation"
  printf '%s\n' "$adapt_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Seed pre-flight Write gate (v6.2.1): seed_preflight_check.sh denies a *.seed.md
# Write whose file_scope path is hallucinated (block mode), passes a clean seed
# silently, honors [seed].seed_gate=warn/off, and fast-paths non-seed/Edit/non-shepherd.
echo "== test_seed_preflight_check.sh (v6.2.1 — deterministic seed pre-flight) =="
total=$((total+1))
if spc_out=$(bash "$TESTS_DIR/test_seed_preflight_check.sh" 2>&1); then
  printf '  PASS  %s\n' "seed-preflight-blocks-hallucinated-seed"
else
  printf '  FAIL  %-50s\n' "seed-preflight-check"
  printf '%s\n' "$spc_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Exec-bit guard (v6.1.3): every path-invoked hook/CLI script must carry the
# git-tracked executable bit. Regression guard for the v6.1.2
# "Permission denied" shipped-as-100644 class.
echo "== test_exec_bits.sh (v6.1.3 — path-invoked scripts are executable) =="
total=$((total+1))
if xb_out=$(bash "$TESTS_DIR/test_exec_bits.sh" 2>&1); then
  printf '  PASS  %s\n' "exec-bits-all-100755"
else
  printf '  FAIL  %-50s\n' "exec-bits"
  printf '%s\n' "$xb_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Flock-output review wiring (v6.2.4, #167): the FLOCK-OUTPUT REVIEW gate + REDO
# loop is behavioral wiring across a doctrine + four profiles + the invariant
# matrix. This guard fails if any load-bearing leg is dropped or a citation dangles.
echo "== test_flock_output_review.sh (v6.2.4 — #167 review gate + redo loop) =="
total=$((total+1))
if for_out=$(bash "$TESTS_DIR/test_flock_output_review.sh" 2>&1); then
  printf '  PASS  %s\n' "flock-output-review-wired"
else
  printf '  FAIL  %-50s\n' "flock-output-review"
  printf '%s\n' "$for_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# v6.2.5 wiring (#169/#170/#171): engineer self-contained plan + critic-proof,
# the [models] map, and workdir prune are behavioral wiring across doctrines +
# profiles + CLI + the invariant matrix. This guard fails if any leg is dropped.
echo "== test_engineer_self_contained.sh (v6.2.5 — #169/#170/#171 wiring) =="
total=$((total+1))
if esc_out=$(bash "$TESTS_DIR/test_engineer_self_contained.sh" 2>&1); then
  printf '  PASS  %s\n' "v625-wiring"
else
  printf '  FAIL  %-50s\n' "v625-wiring"
  printf '%s\n' "$esc_out" | sed 's/^/        /'
  fails=$((fails+1))
fi


# Conductor write guard (v6.2.7, #180): the conductor is read+dispatch only in
# BOTH modes — Edit/Write always denied when a sprint is open, a deny-list of
# Bash write-verbs (git integration commands, filesystem mutation, mutating
# shctx subcommands) closes the same hole for Bash-as-a-write-vehicle. Fast-paths
# when no sprint is open or the call is tagged to an in-flight flock dispatch.
echo "== test_conductor_write_guard.sh (v6.2.7 — #180 conductor read+dispatch-only) =="
total=$((total+1))
if cwg_out=$(bash "$TESTS_DIR/test_conductor_write_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "conductor-write-guard-blocks-writes"
else
  printf '  FAIL  %-50s\n' "conductor-write-guard"
  printf '%s\n' "$cwg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Workflow dispatch-model-pin guard (v6.2.9, #178): workflow_model_guard.sh
# blocks (default) a PreToolUse(Workflow) script whose agent() calls omit
# BOTH model:/agentType: — the shape that silently inherits the main-loop
# model. String-content-blind (a prompt mentioning "model:" in prose, or a
# schema field named "model", must not false-pass), honors warn/off +
# the `// shepherd:model-pin-override` marker, fails open on an invisible
# named-workflow script or an unreadable scriptPath.
echo "== test_workflow_model_guard.sh (v6.2.9 — #178 workflow dispatch-model-pin gate) =="
total=$((total+1))
if wmg_out=$(bash "$TESTS_DIR/test_workflow_model_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "workflow-model-guard-blocks-unpinned-dispatch"
else
  printf '  FAIL  %-50s\n' "workflow-model-guard"
  printf '%s\n' "$wmg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Coder git guard (v6.3.0, #187): coder_git_guard.sh denies every git write for
# a @coder dispatch (commit/add/reset/checkout/stash/push/worktree/…) while
# read-only inspection (status/diff/log/show/rev-parse) passes; non-coder turns
# fail open. Git custody moves to the conductor, PASS-gated, so a REDO re-runs
# the coder over uncommitted files with nothing to unwind.
echo "== test_coder_git_guard.sh (v6.3.0 — #187 coder no-git custody gate) =="
total=$((total+1))
if cgg_out=$(bash "$TESTS_DIR/test_coder_git_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "coder-git-guard-blocks-all-coder-git-writes"
else
  printf '  FAIL  %-50s\n' "coder-git-guard"
  printf '%s\n' "$cgg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Teammate idle routing (v6.3.0, #183): teammate_idle.sh flips a teammate's
# status to idle by NAME (the key named-Agent teammates register under, across
# identity fields), and suppresses the "no row matched" flood when no spawn is
# live — the noise that masked real stalls. Skips gracefully without sqlite3.
echo "== test_teammate_idle.sh (v6.3.0 — #183 teammate idle status routing) =="
total=$((total+1))
if tid_out=$(bash "$TESTS_DIR/test_teammate_idle.sh" 2>&1); then
  printf '  PASS  %s\n' "teammate-idle-flips-by-name-no-flood"
else
  printf '  FAIL  %-50s\n' "teammate-idle"
  printf '%s\n' "$tid_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# v6.3.0 doctrine-wiring guard (#181/#183/#184/#185/#186/#187): the prose/contract
# legs of the release — conductor boot lead-attested escape (#184), worker GH
# MCP write + CLI fallback (#185), engineer SendMessage grant (#186), coder
# no-git custody doctrine (#187), teammate registration wiring (#183). Fails if
# a load-bearing leg or citation is dropped.
echo "== test_v630_wiring.sh (v6.3.0 — #181/#183/#184/#185/#186/#187 doctrine wiring) =="
total=$((total+1))
if v630_out=$(bash "$TESTS_DIR/test_v630_wiring.sh" 2>&1); then
  printf '  PASS  %s\n' "v630-doctrine-wiring"
else
  printf '  FAIL  %-50s\n' "v630-wiring"
  printf '%s\n' "$v630_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# Automatic teammate heartbeat (v6.3.3, #193): teammate_heartbeat.sh advances a
# REGISTERED teammate's last_seen_at (booting→active) on every tool call, so
# liveness is trustworthy for roles that never self-report (the self-contained
# @engineer). Observational — never blocks; fails open on any missing precondition;
# [hooks].teammate_heartbeat=off disables it.
echo "== test_teammate_heartbeat.sh (v6.3.3 — #193 auto liveness heartbeat) =="
total=$((total+1))
if hb_out=$(bash "$TESTS_DIR/test_teammate_heartbeat.sh" 2>&1); then
  printf '  PASS  %s\n' "teammate-heartbeat-auto-advances-last-seen"
else
  printf '  FAIL  %-50s\n' "teammate-heartbeat"
  printf '%s\n' "$hb_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# v6.3.6 doctrine wiring (#207 lead-Workflow mandate, #206 seed-ready phantom):
# the lint/hook behavior is pinned by test_lead_workflow_tool.sh +
# test_coordinate_drive_guard.sh; this asserts the prose/contract legs agree
# (auditor grading, invariant-matrix, guard citations) so none drifts back.
echo "== test_v636_wiring.sh (v6.3.6 — #207 lead-Workflow / #206 seed-ready doctrine wiring) =="
total=$((total+1))
if v636_out=$(bash "$TESTS_DIR/test_v636_wiring.sh" 2>&1); then
  printf '  PASS  %s\n' "v636-doctrine-wiring"
else
  printf '  FAIL  %-50s\n' "v636-wiring"
  printf '%s\n' "$v636_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

# v6.3.8 dev.5 evidence cluster: deterministic wave tooling (#213/#214/#216),
# coder governance (#215), and the /shepherd:start wave routine (#217).
echo "== test_readonly_bash_guard.sh (v6.3.8 — read-only reviewer shell-mutation gate) =="
total=$((total+1))
if rbg_out=$(bash "$TESTS_DIR/test_readonly_bash_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "readonly-reviewer-mutate-blocked"
else
  printf '  FAIL  %-50s\n' "readonly-bash-guard"
  printf '%s\n' "$rbg_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

echo "== test_loc_count.sh (v6.3.8 — #216 deterministic wave-gate LOC counter) =="
total=$((total+1))
if lc_out=$(bash "$TESTS_DIR/test_loc_count.sh" 2>&1); then
  printf '  PASS  %s\n' "loc-count-net-production-loc"
else
  printf '  FAIL  %-50s\n' "loc-count"
  printf '%s\n' "$lc_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

echo "== test_journal_status.sh (v6.3.8 — #213 journal wave-return signal) =="
total=$((total+1))
if js_out=$(bash "$TESTS_DIR/test_journal_status.sh" 2>&1); then
  printf '  PASS  %s\n' "journal-status-wave-return"
else
  printf '  FAIL  %-50s\n' "journal-status"
  printf '%s\n' "$js_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

echo "== test_df_guard.sh (v6.3.8 — #214 disk-pressure precheck) =="
total=$((total+1))
if df_out=$(bash "$TESTS_DIR/test_df_guard.sh" 2>&1); then
  printf '  PASS  %s\n' "df-guard-threshold"
else
  printf '  FAIL  %-50s\n' "df-guard"
  printf '%s\n' "$df_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

echo "== test_v638_wiring.sh (v6.3.8 — #213/#214/#215/#216/#217 + tool-wiring doctrine) =="
total=$((total+1))
if v638_out=$(bash "$TESTS_DIR/test_v638_wiring.sh" 2>&1); then
  printf '  PASS  %s\n' "v638-doctrine-wiring"
else
  printf '  FAIL  %-50s\n' "v638-wiring"
  printf '%s\n' "$v638_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

echo "== test_v639_wiring.sh (v6.3.9 — #220-#225 dev.6 remediation wiring) =="
total=$((total+1))
if v639_out=$(bash "$TESTS_DIR/test_v639_wiring.sh" 2>&1); then
  printf '  PASS  %s\n' "v639-doctrine-wiring"
else
  printf '  FAIL  %-50s\n' "v639-wiring"
  printf '%s\n' "$v639_out" | sed 's/^/        /'
  fails=$((fails+1))
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
