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
#   issues); every other write is dispatched to @worker
#   (hooks/scripts/conductor_write_guard.sh is the mechanical enforcement for
#   Edit/Write/git-write Bash). conductor is NOT in READONLY_ROLES (it keeps
#   Agent + Bash for dispatch + read-only inspection), so this carve-out is
#   checked separately from the trio loop below.
#
# RUNTIME CAPABILITY GATE (DF-64/DF-65, replaces the DF-17 non-fatal FINDING):
#   every check above pins DECLARED text in `agents/*.md` — it proves nothing
#   about what a dispatched session can actually call. `agents/conductor.md`
#   and `agents/engineer.md` now self-report their OWN observed visible tool
#   list into `<ns>/dispatch/<sprint>/*.json` on turn one (§Boot verification /
#   §Mandatory protocol in each file). This script reads every such record and
#   HALTS (exit 1) on either direction of a real delta: a declared tool the
#   record shows absent (broken capability contract, DF-64), or an observed
#   MUTATING tool the record shows present but undeclared (containment breach,
#   DF-65). A record with `observed_tools: null` ("self-report-pending" — no
#   live session has self-reported yet) is skipped, never penalized.
#
# Exit 0 on pass; exit 1 with a per-violation diagnostic OR a real declared-
# vs-observed capability delta (DF-64/DF-65 §RUNTIME CAPABILITY GATE above).

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
AGENTS_DIR="${SHEPHERD_LINT_AGENTS_DIR:-$REPO_ROOT/agents}"  # override for tests
HOOKS_JSON="$REPO_ROOT/hooks/hooks.json"
GUARD="$REPO_ROOT/hooks/scripts/lock_guard.sh"
# Where agent_invocation_tagger.sh writes its per-dispatch capability record
# (<ns>/dispatch/<sprint>/<tool_use_id>.json) — glob root for the DF-17
# observed-vs-declared scan below. Overridable so a test can point this at a
# synthetic fixture dir without touching the real run tree.
RUNS_DIR="${SHEPHERD_LINT_RUNS_DIR:-$REPO_ROOT/.shepherd}"

# The closed-flock read-only reviewer set. The flock is closed (CLAUDE.md), so
# this list is stable; a new read-only role would be added here deliberately.
READONLY_ROLES="auditor discovery critic"

fails=0
note() { printf '  %s\n' "$*"; }

# ---------------------------------------------------------------------------
# DF-17/DF-64/DF-65 — role capability guarantees are unverified at RUNTIME,
# and the fix now HALTS instead of merely reporting.
#
# `tools:` frontmatter is DECLARED intent, never a runtime guarantee (measured
# live three separate times this sprint: an engineer teammate saw neither
# `Workflow` nor `Glob` nor `Grep` despite `agents/engineer.md:7` granting all
# three (DF-17/DF-E1); a `shepherd:conductor` teammate on the tmux backend was
# missing `Glob`/`Grep`/`Workflow`/`ScheduleWakeup` (DF-64); the SAME declared
# type on the in-process backend instead GAINED ungranted `Edit`/`Write`/
# `Artifact` — a containment breach, not just a capability gap (DF-65)). Every
# violation check above/below in this file pins the DECLARATION — a string
# present in a file — never what a dispatched session actually sees.
#
# The missing half was the SELF-REPORT: nothing wrote the observed side of
# the contract. `agents/conductor.md` and `agents/engineer.md` now do,
# directly — each writes its OWN capability record to
# `<ns>/dispatch/<sprint>/selfreport-<role>-<ts>-<pid>.json` on turn one
# (§Boot verification / §Capability self-report in each file), carrying
# `agent_role`, `declared_tools` (re-derived from its own `tools:` line at
# self-report time), and `observed_tools` (its own visible tool list — an
# OBSERVATION, never `ToolSearch`'d, never inferred — `skills/harness/SKILL.md
# §Tool presence`). This sidesteps `agent_invocation_tagger.sh`'s original
# session_id-keyed PATCH plan: `commands/spawn.md §Register teammates`
# documents that no caller ever learns a teammate's own session uuid, and
# this run's own registry confirms it live — `sqlite3 .shepherd/shepherd.db
# "select session_id from teammates"` returns every row EMPTY (DF-12, DF-71).
# A self-authored record keyed on nothing but the role's own name and the
# current sprint needs no such lookup.
#
# capability_delta_findings ROLE DECLARED_CSV OBSERVED_CSV — echo one
# 'FINDING ...' line per DECLARED_CSV token absent from OBSERVED_CSV (empty
# output means no delta of this kind). DF-64 direction: a broken capability
# contract.
capability_delta_findings() {
  local role="$1" declared_csv="$2" observed_csv="$3" tool observed_norm out=""
  observed_norm=",$(printf '%s' "$observed_csv" | tr -d '[:space:]'),"
  IFS=',' read -ra decl_toks <<< "$declared_csv"
  for tool in "${decl_toks[@]}"; do
    tool="$(printf '%s' "$tool" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [[ -z "$tool" ]] && continue
    case "$observed_norm" in
      *",$tool,"*) ;;
      *) out+="FINDING $role: declares '$tool' but it is not present in the runtime-observed tool list (declared != observed, DF-64)"$'\n' ;;
    esac
  done
  printf '%s' "$out"
}

# True (rc 0) if $1 is a mutating tool/verb — the SAME taxonomy the READONLY_ROLES
# loop below already forbids (Edit/Write family, execute_sql, mutating MCP verb
# patterns), factored out so the containment check below shares one definition
# rather than drifting from it.
is_mutating_tool() {
  case "$1" in
    Edit|NotebookEdit|MultiEdit|Write|Artifact) return 0 ;;
    *execute_sql) return 0 ;;
    *__apply_*|*__create_*|*__update_*|*__delete_*|*__merge_*|*__deploy_*|*__close_*|*__reopen_*|*__restore_*|*__pause_*|*_write) return 0 ;;
    *) return 1 ;;
  esac
}

# capability_extra_write_findings ROLE DECLARED_CSV OBSERVED_CSV — echo one
# 'FINDING ...' line per OBSERVED_CSV token that is BOTH absent from
# DECLARED_CSV AND mutating (`is_mutating_tool`). DF-65 direction: a
# containment breach — an undeclared WRITE capability the role's `tools:`
# frontmatter never granted (measured live: an in-process `shepherd:conductor`
# gained `Edit`/`Write`/`Artifact` it never declared). An extra NON-mutating
# tool (e.g. a benign read tool) is not flagged here — only the direction
# DF-65 named as a safety breach is fatal.
capability_extra_write_findings() {
  local role="$1" declared_csv="$2" observed_csv="$3" tool declared_norm out=""
  declared_norm=",$(printf '%s' "$declared_csv" | tr -d '[:space:]'),"
  IFS=',' read -ra obs_toks <<< "$observed_csv"
  for tool in "${obs_toks[@]}"; do
    tool="$(printf '%s' "$tool" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [[ -z "$tool" ]] && continue
    case "$declared_norm" in
      *",$tool,"*) continue ;;
    esac
    if is_mutating_tool "$tool"; then
      out+="FINDING $role: observed tool '$tool' is a MUTATING capability not present in the declared 'tools:' allowlist (observed != declared, containment breach, DF-65)"$'\n'
    fi
  done
  printf '%s' "$out"
}

# Echo a JSON array field (e.g. .observed_tools, .declared_tools) from a
# capability record as a comma-joined string; "" for null/[]/missing/unparsable.
record_array_csv() {
  local f="$1" field="$2"
  if command -v jq &>/dev/null; then
    jq -r --arg f "$field" '(.[$f] // []) | join(",")' "$f" 2>/dev/null
  else
    python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("")
else:
    print(",".join(d.get(sys.argv[2]) or []))
' "$f" "$field" 2>/dev/null
  fi
}

# scan_observed_capability_deltas DIR — walk every capability record under
# DIR matching '*/dispatch/*/*.json' (the same glob shape both
# agent_invocation_tagger.sh's PreToolUse records and the new self-reports
# use), diff declared vs. observed in BOTH directions, and HALT (increment the
# caller's $fails) on either kind of delta DF-64/DF-65 named as fatal. A
# still-null/empty `observed_tools` is self-report-pending, not a delta, and
# is skipped without penalty — most records on any given run are expected to
# stay in this state until a dispatched conductor/engineer actually runs its
# turn-one self-report. Updates the globals the caller's summary line reports:
# capability_scanned (records seen), capability_self_reported (records with
# actual observed data), capability_deltas (records with a fatal delta) —
# and $fails directly, the SAME counter every other check in this file feeds,
# so a capability delta fails the whole lint exactly like any other violation.
scan_observed_capability_deltas() {
  local dir="$1" rec observed rrole declared missing_findings extra_findings rec_findings
  while IFS= read -r rec; do
    [[ -f "$rec" ]] || continue
    capability_scanned=$((capability_scanned+1))
    observed="$(record_array_csv "$rec" observed_tools)"
    [[ -z "$observed" ]] && continue
    capability_self_reported=$((capability_self_reported+1))
    if command -v jq &>/dev/null; then
      rrole="$(jq -r '.agent_role // "unknown"' "$rec" 2>/dev/null)"
    else
      rrole="$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("agent_role","unknown"))
except Exception: print("unknown")' "$rec" 2>/dev/null)"
    fi
    declared="$(record_array_csv "$rec" declared_tools)"
    missing_findings="$(capability_delta_findings "${rrole:-unknown}" "$declared" "$observed")"
    extra_findings="$(capability_extra_write_findings "${rrole:-unknown}" "$declared" "$observed")"
    rec_findings="${missing_findings}${extra_findings}"
    if [[ -n "$rec_findings" ]]; then
      capability_deltas=$((capability_deltas+1))
      fails=$((fails+1))
      note "FAIL ($rec): self-reported declared-vs-observed capability delta — HALTING per DF-64/DF-65, not a non-fatal finding:"
      printf '%s\n' "$rec_findings" | sed 's/^/    /'
    fi
  done < <(find "$dir" -path '*/dispatch/*/*.json' -type f 2>/dev/null)
}

# --self-test: prove the detector CAN fail, at both the unit layer (the two
# pure diff functions) and the integration layer (scan_observed_capability_
# deltas actually walking on-disk fixture records and turning a delta into a
# HALT) — the concrete evidence, per §ACCEPTANCE, that this is a real detector
# and not text-presence theater. Also proves the NEGATIVE control: a clean
# self-report (declared == observed) must NOT be flagged, so the gate doesn't
# cry wolf on a legitimate report. No real agents/ file or run-tree record is
# touched — everything below lives in a throwaway mktemp dir.
if [[ "${1:-}" == "--self-test" ]]; then
  note "SELF-TEST 1/3 (unit): capability_delta_findings must detect a fabricated MISSING-tool delta (DF-64 direction)"
  unit_missing="$(capability_delta_findings "fixture-role" "Read,Write,Workflow,Glob" "Read,Write,Workflow")"
  if [[ -z "$unit_missing" ]]; then
    printf 'lint_agent_capabilities --self-test: FAIL — the injected MISSING-tool delta went undetected; capability_delta_findings is broken\n'
    exit 1
  fi
  note "  detected: $(printf '%s' "$unit_missing" | tr -d '\n')"

  note "SELF-TEST 2/3 (unit): capability_extra_write_findings must detect a fabricated EXTRA-write delta (DF-65 direction)"
  unit_extra="$(capability_extra_write_findings "fixture-role" "Read" "Read,Edit")"
  if [[ -z "$unit_extra" ]]; then
    printf 'lint_agent_capabilities --self-test: FAIL — the injected EXTRA-write delta went undetected; capability_extra_write_findings is broken\n'
    exit 1
  fi
  note "  detected: $(printf '%s' "$unit_extra" | tr -d '\n')"
  unit_extra_benign="$(capability_extra_write_findings "fixture-role" "Read" "Read,WebSearch")"
  if [[ -n "$unit_extra_benign" ]]; then
    printf 'lint_agent_capabilities --self-test: FAIL — a NON-mutating extra tool (WebSearch) was wrongly flagged; only mutating extras are DF-65-fatal\n'
    exit 1
  fi
  note "  negative control OK: an extra non-mutating tool (WebSearch) was correctly NOT flagged"

  note "SELF-TEST 3/3 (integration): scan_observed_capability_deltas must HALT the checker on fabricated on-disk records, and must NOT halt on a clean one"
  fixture_dir="$(mktemp -d -t shep-lint-capability.XXXXXX)"
  trap 'rm -rf "$fixture_dir"' EXIT
  mkdir -p "$fixture_dir/dispatch/self-test-sprint"
  cat > "$fixture_dir/dispatch/self-test-sprint/missing.json" <<'EOF'
{"agent_role":"fixture-conductor","declared_tools":["Read","Glob","Workflow"],"observed_tools":["Read","Workflow"]}
EOF
  cat > "$fixture_dir/dispatch/self-test-sprint/extra.json" <<'EOF'
{"agent_role":"fixture-conductor","declared_tools":["Read"],"observed_tools":["Read","Edit"]}
EOF
  cat > "$fixture_dir/dispatch/self-test-sprint/pending.json" <<'EOF'
{"agent_role":"fixture-conductor","declared_tools":["Read","Glob"],"observed_tools":null}
EOF
  cat > "$fixture_dir/dispatch/self-test-sprint/clean.json" <<'EOF'
{"agent_role":"fixture-conductor","declared_tools":["Read","Bash"],"observed_tools":["Read","Bash"]}
EOF
  fails=0; capability_scanned=0; capability_self_reported=0; capability_deltas=0
  scan_observed_capability_deltas "$fixture_dir"
  rm -rf "$fixture_dir"; trap - EXIT
  if [[ "$capability_scanned" -ne 4 ]]; then
    printf 'lint_agent_capabilities --self-test: FAIL — expected 4 fixture records scanned, got %d\n' "$capability_scanned"
    exit 1
  fi
  if [[ "$fails" -ne 2 ]]; then
    printf 'lint_agent_capabilities --self-test: FAIL — expected exactly 2 fatal deltas from the fixture set (missing.json + extra.json; pending.json and clean.json must NOT fail), got %d\n' "$fails"
    exit 1
  fi
  note "SELF-TEST OK — 4 fixture records scanned, exactly 2 fatal deltas detected (missing-tool + extra-write), pending/clean correctly left alone"
  printf 'lint_agent_capabilities --self-test: exiting 1 deliberately — this is the proof the detector CAN fail (and can correctly NOT fail), not a normal-run failure\n'
  exit 1
fi

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

# ---------------------------------------------------------------------------
# DF-64/DF-65 — declared-vs-OBSERVED capability scan, FATAL on a real delta
# (see `scan_observed_capability_deltas` + the block above `note()` for the
# full contract). Scans every capability record under $RUNS_DIR (real
# dispatches, or a SHEPHERD_LINT_RUNS_DIR-pointed fixture tree in a test) —
# both `agent_invocation_tagger.sh`'s PreToolUse records (still `observed_
# tools: null` until a future wave patches them) and `agents/conductor.md` /
# `agents/engineer.md`'s own turn-one self-reports. A record with a still-
# -null/empty `observed_tools` is self-report-pending, not a delta, and is
# skipped without penalty. A REAL delta increments $fails directly — the same
# counter every other check in this file feeds — so this is no longer a
# non-fatal FINDING (the DF-17 posture this replaces): it is a HALT, exactly
# what DF-64/DF-65 asked for.
# ---------------------------------------------------------------------------
capability_scanned=0
capability_self_reported=0
capability_deltas=0
scan_observed_capability_deltas "$RUNS_DIR"
if [[ "$capability_scanned" -eq 0 ]]; then
  note "OBSERVED-CAPABILITY (DF-64/DF-65): 0 dispatch record(s) under $RUNS_DIR yet — expected until a dispatched conductor/engineer runs its turn-one capability self-report (agents/conductor.md, agents/engineer.md §Capability self-report)"
elif [[ "$capability_self_reported" -eq 0 ]]; then
  note "OBSERVED-CAPABILITY (DF-64/DF-65): scanned $capability_scanned dispatch record(s) under $RUNS_DIR, none carry self-reported data yet (all self-report-pending) — nothing to diff"
elif [[ "$capability_deltas" -eq 0 ]]; then
  note "OBSERVED-CAPABILITY (DF-64/DF-65): scanned $capability_scanned dispatch record(s), $capability_self_reported self-reported, 0 delta(s) — declared matches observed everywhere self-reported"
else
  note "OBSERVED-CAPABILITY (DF-64/DF-65): scanned $capability_scanned dispatch record(s), $capability_self_reported self-reported, $capability_deltas fatal delta(s) — see FAIL lines above"
fi

if [[ "$fails" -gt 0 ]]; then
  printf 'lint_agent_capabilities: %d violation(s) — read-only mutation-free (GH #74); no destructive verb (GH #84); all three leads (shepherd/engineer/conductor) grant Workflow (#233); read-only shctx-runners grant Bash (#207-class); no ungranted-tool claim (v6.2.1); no provider-specific MCP token in any frontmatter (v6.4.3); runtime declared-vs-observed capability delta HALTS the run (DF-64/DF-65) — %d self-reported delta(s) among them\n' "$fails" "$capability_deltas"
  exit 1
fi
printf 'lint_agent_capabilities: OK — read-only trio mutation-free (GH #74); all nine carry no destructive MCP verb (GH #84); all three leads (shepherd/engineer/conductor) grant Workflow in-tree (#233, live on an Agent-Teams teammate substrate — #263); read-only shctx-runners grant Bash; no profile claims an ungranted tool (v6.2.1); NO frontmatter names a provider-specific MCP token — capabilities are discovered via ToolSearch (v6.4.3, #110); runtime capability self-report scan ran and HALTS on a delta (DF-64/DF-65) — %d dispatch record(s) scanned, %d self-reported, 0 delta(s)\n' "$capability_scanned" "$capability_self_reported"
exit 0
