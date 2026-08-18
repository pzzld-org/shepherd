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
#           run-scoped report-file pattern — {run_dir}/reports/ for discovery,
#           {run_dir}/audits/ for auditor (GH #74 "Option B"). The lint
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
#   issues); every other write is dispatched to @worker. `conductor_write_guard.sh`
#   was retired in v6.4.5 (source deleted, `hooks/tests/test_legacy_policy_retirement.sh`
#   pins it unregistered); the mechanical enforcement for Edit/Write is now the
#   native PreToolUse `Write|Edit` matcher in `hooks/hooks.json` (v6.4.6, #D5),
#   backed by `content/predicates/write-boundary.toml`'s `role-write-eligibility`
#   and `path-in-declared-scope` rules. conductor is NOT in READONLY_ROLES (it
#   keeps Agent + Bash for dispatch + read-only inspection), so this carve-out is
#   checked separately from the trio loop below.
#
# Exit 0 on pass; exit 1 with a per-violation diagnostic.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
AGENTS_DIR="${SHEPHERD_LINT_AGENTS_DIR:-$REPO_ROOT/agents}"  # override for tests
HOOKS_JSON="${SHEPHERD_LINT_HOOKS_JSON:-$REPO_ROOT/hooks/hooks.json}"  # override for tests
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
# grant at all — defense in depth for a frontmatter contract that must itself
# be correct. issue_write is its one permitted mutating MCP verb (auditor/
# conductor carve-out).
#
# v6.4.6 (#D5): `hooks/scripts/conductor_write_guard.sh` was retired in v6.4.5
# (source deleted; `hooks/tests/test_legacy_policy_retirement.sh` pins it BOTH
# unregistered AND source-deleted). Asserting it is registered here directly
# contradicted that shipped, green gate — literally satisfying this line would
# have turned test_legacy_policy_retirement.sh red, proving THIS line, not
# that one, was stale. The defense-in-depth authority for "conductor cannot
# write" is now the NATIVE PreToolUse hook: hooks/hooks.json registers a
# matcher covering BOTH `Write` and `Edit` (currently
# "Write|Edit|Bash|Agent|Workflow" at hooks/hooks.json:16), routing every
# Write/Edit tool call through `shepherd claude-hook` before it executes. The
# runtime authority behind that hook is content/predicates/write-boundary.toml's
# `role-write-eligibility` rule (denies fs.write when role.write_eligible is
# false) and `path-in-declared-scope` rule (denies fs.write outside the
# dispatch's declared write scope even for a write_eligible role) — cited
# here, read-only, never edited by this file.
#
# TRAP: content/roles/conductor.md declares `write_eligible: true` with a
# documented exception — it commits/pushes its OWN lane branch via Bash git
# commands, never via the Edit/Write/NotebookEdit/MultiEdit tools. Keying this
# check on `write_eligible: false` would therefore be WRONG for conductor.
# This check keys on the ABSENCE of an Edit/Write/NotebookEdit/MultiEdit TOOL
# grant (already proven by the loop immediately below) plus the PRESENCE of
# the PreToolUse Write|Edit matcher — never on the `write_eligible` field.
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

  # Locate every "matcher" value in HOOKS_JSON and check whether any single
  # matcher's pipe-delimited token set contains BOTH "Write" and "Edit" as
  # EXACT tokens. Exact, not substring: a plain `grep -E 'Edit'` would wrongly
  # accept a matcher containing only "MultiEdit" as covering "Edit", which it
  # does not.
  write_edit_matcher_found=0
  while IFS= read -r matcher_val; do
    [[ -z "$matcher_val" ]] && continue
    has_write=0; has_edit=0
    while IFS= read -r tok; do
      [[ "$tok" == "Write" ]] && has_write=1
      [[ "$tok" == "Edit" ]] && has_edit=1
    done < <(printf '%s' "$matcher_val" | tr '|' '\n')
    if [[ "$has_write" -eq 1 && "$has_edit" -eq 1 ]]; then
      write_edit_matcher_found=1
      break
    fi
  done < <(grep -oE '"matcher"[[:space:]]*:[[:space:]]*"[^"]*"' "$HOOKS_JSON" \
             | sed -E 's/.*"matcher"[[:space:]]*:[[:space:]]*"([^"]*)"/\1/')

  if [[ "$write_edit_matcher_found" -ne 1 ]]; then
    note "FAIL conductor: no Edit/Write/NotebookEdit/MultiEdit grant is claimed (checked above) but hooks.json has no PreToolUse matcher covering both 'Write' and 'Edit' as exact tokens — defense-in-depth missing (content/predicates/write-boundary.toml: role-write-eligibility, path-in-declared-scope is the native runtime authority; conductor_write_guard.sh was retired in v6.4.5, see test_legacy_policy_retirement.sh)"
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
# v6.4.0 / #233 Workflow-tool GRANT — all three leads carry it (reverses the
# v6.3.9/#220 tier partition per operator decision). The `Workflow` tool ships
# in the `tools:` frontmatter of ROOT (`shepherd`) AND both teammate leads
# (`@engineer`, `@conductor`). #263 (v6.4.3, the fan-out vehicle inversion)
# makes the grant LIVE at every tier that holds it: root drives Dynamic
# Workflows directly (/shepherd:start), AND a teammate-`@conductor` / a
# self-contained `@engineer` now compiles its OWN Dynamic Workflow for its
# gate-free fan-out too, once a `WORKFLOW-VEHICLE-PROBE` confirms `Workflow`
# is present in ITS OWN visible tool list
# (skills/shepherd/references/pipeline.md §Lane law). The v6.3.9-era
# "Workflow is denied inside a subagent" reading is RETIRED as the standing
# instruction (#263) — shipping the grant in-tree (a) stops the release
# pipeline from clobbering the operator's manual patch (#233's concrete
# pain), and (b) is now the reachable, exercised path at every lead tier,
# not a dormant one. Whether an unavailable grant would read as "denied at
# invocation" or "invisible to discovery" is #251, deliberately left OPEN by
# the probe contract (skills/harness/SKILL.md §Tool presence) — this lint does
# not assert either as settled fact, only that the grant is PRESENT and never
# silently dropped again. The runtime reality is kept HONEST in
# agents/{conductor,engineer}.md + skills/harness/SKILL.md; this lint only
# pins presence.
# ---------------------------------------------------------------------------
LEAD_MANDATED_WORKFLOW="shepherd engineer conductor"
for role in $LEAD_MANDATED_WORKFLOW; do
  f="$AGENTS_DIR/$role.md"
  [[ -f "$f" ]] || continue   # a missing lead file is flagged by the loops above
  if ! tools_line "$f" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -qx 'Workflow'; then
    note "FAIL $role: lead must grant 'Workflow' in tools: frontmatter (#233 — shipped in-tree so a release never clobbers the operator's patch); it is missing"
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

# ---------------------------------------------------------------------------
# NO PROVIDER TOKENS IN FRONTMATTER (v6.4.3) — the categorical rule that
# replaces the per-verb allowlist above.
#
# Every `mcp__<server>__<tool>` token in a `tools:` line named ONE server's
# ONE naming scheme. Shepherd cannot guarantee any of them exist: the same
# GitHub capability is `mcp__github__*` natively, `mcp__MCP_DOCKER__*` behind
# a Docker MCP gateway (the operator's own routing), something else again via
# Composio. A token that names a server that is not connected is dead weight
# at best; taken as a dependency it binds the plugin to a toolset the
# installing user may simply not have.
#
# `skills/shepherd/SKILL.md §Provider-agnostic discovery` (#110) already said
# the tokens were "the default-provider OFFER, not a hard dependency" — but
# the frontmatter kept shipping them, so the doctrine and the manifest
# disagreed. They no longer do: the frontmatter carries NO provider tokens,
# every role that touches a service grants `ToolSearch`, and the capability is
# DISCOVERED at runtime by what is actually connected.
#
# This subsumes the GH #74/#84 destructive-verb sweeps above for MCP verbs
# specifically: a role that carries no MCP token cannot carry a destructive
# one. Those checks stay for the non-MCP verbs (Edit/Write/execute_sql) and
# as belt-and-braces if a token is ever re-added.
# ---------------------------------------------------------------------------
for role in $ALL_ROLES; do
  f="$AGENTS_DIR/$role.md"
  [[ -f "$f" ]] || continue
  provider_toks="$(tools_line "$f" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' \
                    | grep '^mcp__' || true)"
  if [[ -n "$provider_toks" ]]; then
    note "FAIL $role: frontmatter names provider-specific MCP token(s) — shepherd cannot guarantee any server's naming scheme exists (v6.4.3); drop them and discover via ToolSearch (skills/shepherd/SKILL.md §Provider-agnostic discovery, #110):"
    printf '%s\n' "$provider_toks" | sed 's/^/        /'
    fails=$((fails+1))
  fi
  # A role stripped of provider tokens still needs the discovery verb, or it
  # has no way to reach a service at all.
  if grep -qE '^(tools|allowed-tools):' "$f" && ! tools_line "$f" | grep -q 'ToolSearch'; then
    case "$role" in
      critic) : ;;  # touches no external service; genuinely needs no discovery
      *) note "FAIL $role: no provider tokens (correct) but also no ToolSearch — cannot discover any service at runtime"
         fails=$((fails+1)) ;;
    esac
  fi
done

if [[ "$fails" -gt 0 ]]; then
  printf 'lint_agent_capabilities: %d violation(s) — read-only mutation-free (GH #74); no destructive verb (GH #84); all three leads (shepherd/engineer/conductor) grant Workflow (#233); read-only shctx-runners grant Bash (#207-class); no ungranted-tool claim (v6.2.1); no provider-specific MCP token in any frontmatter (v6.4.3)\n' "$fails"
  exit 1
fi
printf 'lint_agent_capabilities: OK — read-only trio mutation-free (GH #74); all nine carry no destructive MCP verb (GH #84); all three leads (shepherd/engineer/conductor) grant Workflow in-tree (#233, live on an Agent-Teams teammate substrate — #263); read-only shctx-runners grant Bash; no profile claims an ungranted tool (v6.2.1); NO frontmatter names a provider-specific MCP token — capabilities are discovered via ToolSearch (v6.4.3, #110)\n'
exit 0
