#!/usr/bin/env bash
# hooks/tests/lint_agent_capabilities.sh — read-only-capability lint (GH #74).
#
# Asserts that every read-only flock reviewer (auditor, discovery, critic)
# carries NO mutating capability in its `tools:` frontmatter allowlist. A
# read-only behavioral contract that is only prose/graph-enforced evaporates
# when a different dispatcher invokes the agent — e.g. a Claude Code Dynamic
# Workflow runtime, which runs spawned agents in `acceptEdits` with no
# orchestrator in the loop (skills/harness/references/workflow-templates.md §VII). The
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
# CARVE-OUT (annotated, audited):
#   auditor MAY retain mcp__plugin_github_github__issue_write for finding
#   creation — the auditor is the sole close-flow issue filer. discovery/critic
#   may NOT. (Operator lane-A scope kept issue_write; only execute_sql was
#   dropped.)
#   conductor (v6.2.7, #180) MAY ALSO retain issue_write — it is the conductor's
#   ONLY direct external mutation (open/close carry-forward + drift-risk
#   issues); every other write is dispatched to @worker
#   (hooks/scripts/conductor_write_guard.sh is the mechanical enforcement for
#   Edit/Write/git-write Bash). conductor is NOT in READONLY_ROLES (it keeps
#   Agent + Bash for dispatch + read-only inspection), so this carve-out is
#   checked separately from the trio loop below.
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
          note "FAIL $role: issue_write is the auditor-only finding-creation carve-out (within READONLY_ROLES); not allowed for $role"
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
# CONDUCTOR-ONLY-TEAMMATE / read+dispatch-only conductor lint (v6.2.7, #180).
# The conductor is NOT in READONLY_ROLES (it keeps Agent + Bash for dispatch +
# read-only inspection), but it must carry NO Edit/Write/NotebookEdit/MultiEdit
# grant at all — the mechanical hook (conductor_write_guard.sh) is defense in
# depth for a frontmatter contract that must itself be correct. issue_write is
# its one permitted mutating MCP verb (auditor/conductor carve-out).
# ---------------------------------------------------------------------------
cf="$AGENTS_DIR/conductor.md"
if [[ -f "$cf" ]]; then
  ctoks="$(tools_line "$cf" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$')"
  while IFS= read -r t; do
    [[ -z "$t" ]] && continue
    case "$t" in
      Edit|Write|NotebookEdit|MultiEdit)
        note "FAIL conductor: forbidden write-capable tool '$t' — conductor is read+dispatch-only (v6.2.7, #180)"
        fails=$((fails+1)) ;;
    esac
  done <<< "$ctoks"
  if ! grep -q "conductor_write_guard.sh" "$HOOKS_JSON"; then
    note "FAIL conductor: no Edit/Write grant is claimed but hooks/scripts/conductor_write_guard.sh is not registered in hooks.json (defense-in-depth missing)"
    fails=$((fails+1))
  fi
fi

# ---------------------------------------------------------------------------
# #84 least-privilege sweep — ALL NINE agents, under acceptEdits / no-orchestrator.
# Under a Dynamic Workflow runtime every spawned agent runs in acceptEdits with NO
# orchestrator in the loop (skills/harness/references/workflow-templates.md §VII), so the `tools:`
# allowlist is the ONLY capability boundary. No flock or meta role has a legitimate
# need for a DESTRUCTIVE MCP verb (delete / destroy / drop): git deletions are
# Bash-audited and conductor/shepherd-owned; DB/issue deletion is never a sprint
# action. Pin that no agent regains one. Dual-use reads (execute_sql) and release
# verbs (merge_pull_request, create_pull_request) on the writer/meta roles are
# deliberate, documented retentions — see skills/shepherd/references/invariant-matrix.md §IV.
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
# v6.3.6 / #207 lead mandated-tool PRESENCE. The INVERSE of the tool-claim
# consistency check below: a lead whose DOCTRINE mandates a tool must actually
# GRANT it in `tools:` frontmatter. The `@engineer` and `@conductor` leads are
# doctrinally required to compile gate-free fan-out into Dynamic Workflows
# (conductor.md §WORKFLOW SELF-CHECK: "compiling gate-free fan-out to a Dynamic
# Workflow is the default, not the exception"; engineer.md self-contained plan
# fan-out), and both run at `[spawn].lead_effort=ultracode` which mandates that
# path. But the `Workflow` grant was ABSENT from their frontmatter for versions
# (#207): the mandated self-check took its "Absent → slow in-context Agent()"
# branch on every spawn — the single highest-leverage wave-speed regression.
# The frontmatter fix shipped in v6.3.5; this lint pins it so a lead can never
# silently lose a doctrinally-mandated tool again (mechanizes a prose-only
# invariant per the closed-flock contract rule — the mirror of the CLAIM check).
# v6.3.8 (#217) adds `shepherd` (root): the root-drives-workflows mode
# (`/shepherd:start`, agents/shepherd.md §WORKFLOW SELF-CHECK) has root compile
# Dynamic Workflows DIRECTLY, and root's frontmatter was likewise missing the
# grant — the identical #207 gap one tier up. Root without `Workflow` cannot
# drive a single wave, so /shepherd:start would be dead on arrival.
# ---------------------------------------------------------------------------
LEAD_MANDATED_WORKFLOW="engineer conductor shepherd"
for role in $LEAD_MANDATED_WORKFLOW; do
  f="$AGENTS_DIR/$role.md"
  [[ -f "$f" ]] || continue   # a missing lead file is flagged by the loops above
  if ! tools_line "$f" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -qx 'Workflow'; then
    note "FAIL $role: lead/root doctrinally mandates the 'Workflow' tool (Dynamic-Workflow fan-out is the default under [spawn].lead_effort=ultracode; root drives it directly via /shepherd:start) but 'tools:' frontmatter does not grant it — #207/#217 regression: it silently falls back to the slow in-context Agent() path"
    fails=$((fails+1))
  fi
done

# ---------------------------------------------------------------------------
# v6.3.8 read-only-role Bash PRESENCE (#207-class). The three READONLY_ROLES are
# read-only on SOURCE, but each writes its canonical output as registry ROWS via
# `shctx` shelled through Bash (auditor: deliverable + audit_findings; critic:
# deliverable + verdict rows; discovery: discovery_findings insert) and runs
# gates. critic shipped WITHOUT the Bash grant while its Step 0.5 mandated
# `shctx deliverable promise` — a hard #207-class gap with NO fallback: the critic
# could not register its verdict deliverable at all. Pin that every read-only
# reviewer whose prose runs shctx actually grants Bash. Bash is NOT a source-
# mutation verb (the mutation bans above still hold; bash_guard.sh scopes it), so
# this composes with the read-only contract rather than weakening it.
# ---------------------------------------------------------------------------
for role in $READONLY_ROLES; do
  f="$AGENTS_DIR/$role.md"
  [[ -f "$f" ]] || continue
  if grep -q 'shctx ' "$f" \
     && ! tools_line "$f" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -qx 'Bash'; then
    note "FAIL $role: prose runs 'shctx' via Bash but 'tools:' does not grant Bash — #207-class no-fallback gap (the critic Step 0.5 deliverable-promise hole)"
    fails=$((fails+1))
  fi
done

# ---------------------------------------------------------------------------
# v6.2.1 / v6.3.0 tool-claim consistency. A profile must not CLAIM in prose to
# carry / use a session-coordination tool its own `tools:` frontmatter does not
# grant. Original class (v6.2.1): the `conductor.md` "SOLO carries
# AskUserQuestion" stale-claim (a tool removed in v6.1.7 still asserted).
# v6.3.0 (#186) extends the SAME guard to SendMessage — the engineer
# self-contained flow's step (7) "alert root via SendMessage" was prose-only
# while the frontmatter omitted the grant, so the contract and the toolset
# disagreed and the PLAN-READY alert raced/failed. Data-driven over the
# coordination-tool set; a role that GRANTS the tool is skipped (legit use).
# Robust: positive carry/use claims MINUS negation lines (the many correct
# "does not carry / never SendMessage for X" statements across these profiles).
# ---------------------------------------------------------------------------
CLAIM_CHECK_TOOLS="AskUserQuestion SendMessage"
for tool in $CLAIM_CHECK_TOOLS; do
  case "$tool" in
    AskUserQuestion) claim_re='carr(y|ies)[^.]{0,40}AskUserQuestion|AskUserQuestion[^.]{0,40}(escape valve|narrow escape)' ;;
    SendMessage)     claim_re='(carr(y|ies)|via|through|use[sd]?|alert[^.]{0,20}via|surface[^.]{0,20}via)[^.]{0,40}SendMessage|SendMessage[^.]{0,40}to:[[:space:]]*(lead|root)' ;;
    *)               claim_re="carr(y|ies)[^.]{0,40}$tool" ;;
  esac
  for role in $ALL_ROLES; do
    f="$AGENTS_DIR/$role.md"
    [[ -f "$f" ]] || continue
    case "$(tools_line "$f")" in *"$tool"*) continue ;; esac   # legitimately granted
    claim="$(grep -nE "$claim_re" "$f" 2>/dev/null \
              | grep -viE "not |never |no $tool|removed|absent|without|MUST NOT|cannot|do(es)? not" || true)"
    if [[ -n "$claim" ]]; then
      note "FAIL $role: prose claims/uses $tool but frontmatter does not grant it (v6.2.1/#186 tool-claim consistency):"
      printf '%s\n' "$claim" | sed 's/^/        /'
      fails=$((fails+1))
    fi
  done
done

if [[ "$fails" -gt 0 ]]; then
  printf 'lint_agent_capabilities: %d violation(s) — read-only mutation-free (GH #74); no destructive verb (GH #84); lead/root grant mandated Workflow (#207/#217); read-only shctx-runners grant Bash (#207-class); no ungranted-tool claim (v6.2.1)\n' "$fails"
  exit 1
fi
printf 'lint_agent_capabilities: OK — read-only trio mutation-free (GH #74); all nine carry no destructive MCP verb (GH #84); engineer/conductor/shepherd grant the mandated Workflow tool (#207/#217); read-only shctx-runners grant Bash; no profile claims an ungranted tool (v6.2.1)\n'
exit 0
