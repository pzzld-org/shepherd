#!/usr/bin/env bash
# hooks/tests/lint_agent_capabilities.sh — read-only-capability lint (GH #74).
#
# Asserts that every read-only flock reviewer (auditor, discovery, critic)
# carries NO mutating capability in its `tools:` frontmatter allowlist. A
# read-only behavioral contract that is only prose/graph-enforced evaporates
# when a different dispatcher invokes the agent — e.g. a Claude Code Dynamic
# Workflow runtime, which runs spawned agents in `acceptEdits` with no
# orchestrator in the loop (doctrines/workflow-compile-down.md §VII). The
# `tools:` allowlist is the capability-level contract; this lint pins it so a
# read-only agent cannot silently regain a mutating verb.
#
# FORBIDDEN for read-only roles (hard fail):
#   Edit, NotebookEdit, MultiEdit            — direct file mutation
#   *execute_sql                             — arbitrary DB mutation (the #74 hole)
#   *__apply_*, *__create_*, *__update_*,    — mutating MCP verbs
#   *__delete_*, *__merge_*, *__deploy_*,
#   *__close_*, *__reopen_*, *__restore_*,
#   *__pause_*, *_write
#
# CONDITIONAL:
#   Write — allowed ONLY because lock_guard.sh path-scopes it to the
#           {paths.reports} report-file pattern (GH #74 "Option B"). The lint
#           asserts lock_guard.sh exists AND is registered under a
#           PreToolUse(Write) matcher whenever a read-only role keeps Write.
#
# CARVE-OUT (single, annotated, audited):
#   auditor MAY retain mcp__plugin_github_github__issue_write for finding
#   creation — the conductor has no issue_write (agents/conductor.md) and the
#   auditor is the sole close-flow issue filer. discovery/critic may NOT.
#   (Operator lane-A scope kept issue_write; only execute_sql was dropped.)
#
# Exit 0 on pass; exit 1 with a per-violation diagnostic.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
AGENTS_DIR="${SHEPHERD_LINT_AGENTS_DIR:-$REPO_ROOT/agents}"  # override for tests
HOOKS_JSON="$REPO_ROOT/hooks/hooks.json"
GUARD="$REPO_ROOT/hooks/scripts/lock_guard.sh"

# The closed-flock read-only reviewer set. The flock is closed (CLAUDE.md), so
# this list is stable; a new read-only role would be added here deliberately.
READONLY_ROLES="auditor discovery critic"

fails=0
note() { printf '  %s\n' "$*"; }

# Echo the single-line `tools:` frontmatter value for an agent file (empty if none).
tools_line() {
  awk '/^tools:[[:space:]]/ {sub(/^tools:[[:space:]]*/, ""); print; exit}' "$1"
}

for role in $READONLY_ROLES; do
  f="$AGENTS_DIR/$role.md"
  if [[ ! -f "$f" ]]; then
    note "FAIL: agents/$role.md missing"; fails=$((fails+1)); continue
  fi
  tools="$(tools_line "$f")"
  if [[ -z "$tools" ]]; then
    note "FAIL $role: no 'tools:' frontmatter line (read-only contract is then un-enforceable)"
    fails=$((fails+1)); continue
  fi

  # Split the comma-separated allowlist into trimmed tokens.
  toks="$(printf '%s' "$tools" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$')"

  while IFS= read -r t; do
    [[ -z "$t" ]] && continue
    case "$t" in
      Edit|NotebookEdit|MultiEdit)
        note "FAIL $role: forbidden mutating tool '$t'"; fails=$((fails+1)) ;;
      *execute_sql)
        note "FAIL $role: forbidden DB-mutating verb '$t' (the GH #74 hole)"; fails=$((fails+1)) ;;
      mcp__plugin_github_github__issue_write)
        if [[ "$role" != "auditor" ]]; then
          note "FAIL $role: issue_write is the auditor-only finding-creation carve-out; not allowed for $role"
          fails=$((fails+1))
        fi
        ;;
      *__apply_*|*__create_*|*__update_*|*__delete_*|*__merge_*|*__deploy_*|*__close_*|*__reopen_*|*__restore_*|*__pause_*|*_write)
        note "FAIL $role: forbidden mutating MCP verb '$t' (GH #74)"; fails=$((fails+1)) ;;
      Write)
        # Retained Write is only safe because a PreToolUse(Write) hook path-scopes it.
        if [[ ! -f "$GUARD" ]]; then
          note "FAIL $role: keeps Write but hooks/scripts/lock_guard.sh (the path-scope hook) is missing"
          fails=$((fails+1))
        elif ! grep -q 'lock_guard.sh' "$HOOKS_JSON"; then
          note "FAIL $role: keeps Write but lock_guard.sh is not registered in hooks.json"
          fails=$((fails+1))
        elif ! grep -qE '"matcher":[[:space:]]*"Write"' "$HOOKS_JSON"; then
          note "FAIL $role: keeps Write but no PreToolUse(Write) matcher in hooks.json"
          fails=$((fails+1))
        fi
        ;;
    esac
  done <<< "$toks"
done

# ---------------------------------------------------------------------------
# #84 least-privilege sweep — ALL NINE agents, under acceptEdits / no-orchestrator.
# Under a Dynamic Workflow runtime every spawned agent runs in acceptEdits with NO
# orchestrator in the loop (doctrines/workflow-compile-down.md §VII), so the `tools:`
# allowlist is the ONLY capability boundary. No flock or meta role has a legitimate
# need for a DESTRUCTIVE MCP verb (delete / destroy / drop): git deletions are
# Bash-audited and conductor/shepherd-owned; DB/issue deletion is never a sprint
# action. Pin that no agent regains one. Dual-use reads (execute_sql) and release
# verbs (merge_pull_request, create_pull_request) on the writer/meta roles are
# deliberate, documented retentions — see doctrines/invariant-enforcement-matrix.md §IV.
# ---------------------------------------------------------------------------
ALL_ROLES="engineer critic coder auditor worker discovery conductor shepherd planter"
for role in $ALL_ROLES; do
  f="$AGENTS_DIR/$role.md"
  [[ -f "$f" ]] || continue   # the read-only loop above already flags a missing flock file
  toks="$(tools_line "$f" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$')"
  while IFS= read -r t; do
    [[ -z "$t" ]] && continue
    case "$t" in
      *__delete_*|*__destroy_*|*__drop_*|*_delete|*_destroy)
        note "FAIL $role: destructive MCP verb '$t' — no shepherd-role need under acceptEdits (GH #84)"
        fails=$((fails+1)) ;;
    esac
  done <<< "$toks"
done

# ---------------------------------------------------------------------------
# #119 / #169 / #172 Agent-dispatch scope pin. Two roles carry the `Agent` tool,
# each bounded to a READ-ONLY sub-flock — the grant must always travel with its
# documented scope so a future broadening to a WRITE role (@coder/@worker) cannot
# land silently with the prose contract stripped:
#   - planter  (agents/planter.md §Step 2-bis): the bounded @discovery orientation wave.
#   - engineer (agents/engineer.md §Self-contained mode + engineer-self-contained-plan.md):
#       its read-only sub-flock — @discovery + intro-@auditor (the INTRO-COMBO-WAVE it
#       runs in-session) + @critic (its adversarial self-gate). No @coder/@worker.
# The lint cannot bound a RUNTIME dispatch target, but it CAN pin that the grant
# never appears without the documented scope tokens. (Mechanizes a prose-only
# invariant per the "closed-flock contract" rule.)
# ---------------------------------------------------------------------------
scope_tokens_planter="shepherd:discovery"
scope_tokens_engineer="shepherd:discovery shepherd:auditor shepherd:critic"
for agent_with_agent in planter engineer; do
  pf="$AGENTS_DIR/$agent_with_agent.md"
  [[ -f "$pf" ]] || continue
  ptoks="$(tools_line "$pf" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$')"
  if printf '%s\n' "$ptoks" | grep -qx 'Agent'; then
    eval "want=\$scope_tokens_$agent_with_agent"
    for tok in $want; do
      if ! grep -q "$tok" "$pf"; then
        note "FAIL $agent_with_agent: grants 'Agent' but does not document the read-only '$tok' scope bound (#119/#169/#172)"
        fails=$((fails+1))
      fi
    done
  fi
done

# ---------------------------------------------------------------------------
# v6.2.1 tool-claim consistency. A profile must not CLAIM in prose to carry a
# tool its own `tools:` frontmatter does not grant — the `conductor.md` "SOLO
# carries AskUserQuestion" stale-claim class (a tool removed in v6.1.7 still
# asserted as available). Scoped to AskUserQuestion (the removal that drifted).
# Robust: positive carry / escape-valve claims MINUS negation lines (the many
# correct "does not carry AskUserQuestion" statements all over these profiles).
# ---------------------------------------------------------------------------
for role in $ALL_ROLES; do
  f="$AGENTS_DIR/$role.md"
  [[ -f "$f" ]] || continue
  case "$(tools_line "$f")" in *AskUserQuestion*) continue ;; esac   # legitimately granted (planter)
  claim="$(grep -nE 'carr(y|ies)[^.]{0,40}AskUserQuestion|AskUserQuestion[^.]{0,40}(escape valve|narrow escape)' "$f" 2>/dev/null \
            | grep -viE 'not |never |no AskUserQuestion|removed|absent|without|MUST NOT|cannot|do(es)? not' || true)"
  if [[ -n "$claim" ]]; then
    note "FAIL $role: prose claims AskUserQuestion but frontmatter does not grant it (v6.1.7 — execution sessions carry no AskUserQuestion):"
    printf '%s\n' "$claim" | sed 's/^/        /'
    fails=$((fails+1))
  fi
done

if [[ "$fails" -gt 0 ]]; then
  printf 'lint_agent_capabilities: %d violation(s) — read-only mutation-free (GH #74); no destructive verb (GH #84); no ungranted-tool claim (v6.2.1)\n' "$fails"
  exit 1
fi
printf 'lint_agent_capabilities: OK — read-only trio mutation-free (GH #74); all nine carry no destructive MCP verb (GH #84); no profile claims an ungranted tool (v6.2.1)\n'
exit 0
