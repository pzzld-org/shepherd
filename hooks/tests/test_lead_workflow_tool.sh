#!/usr/bin/env bash
# test_lead_workflow_tool.sh — regression pin for the #233 Workflow-tool GRANT
# (v6.4.0, supersedes the v6.3.9/#220 tier partition; the grant went LIVE at
# every tier under #263, v6.4.3).
#
# Per operator decision, `Workflow` ships in-tree in the `tools:` frontmatter of
# ALL THREE leads: ROOT (shepherd) AND both teammate leads (engineer, conductor).
# #263 makes the grant LIVE wherever it is held: root drives Dynamic Workflows
# directly, AND a teammate-@conductor / self-contained @engineer now compiles
# its OWN Dynamic Workflow for its gate-free fan-out too, once a
# `WORKFLOW-VEHICLE-PROBE` (skills/shepherd/references/pipeline.md §Lane law)
# confirms `Workflow` is present in its own visible tool list. The v6.3.9-era
# "Workflow is denied inside a subagent" reading is RETIRED as the standing
# instruction (#263) — shipping the grant in-tree stops the release pipeline
# from clobbering the operator's manual patch (#233's concrete pain), and is
# now the reachable, exercised path at every lead tier, not a dormant one.
# Whether an unavailable grant would read as "denied at invocation" or
# "invisible to discovery" is #251, deliberately left OPEN by the probe
# contract (skills/harness/SKILL.md §Tool presence) — this test does not
# assert either as settled fact, only that the grant is PRESENT and stripping
# it from any lead FAILS the lint.
#
# This test pins the mandate against lint_agent_capabilities.sh via its
# SHEPHERD_LINT_AGENTS_DIR override (the tracked tree is never mutated):
#   • Each of shepherd, engineer, conductor MUST grant Workflow — stripping it
#     from ANY of the three FAILS the lint (#233).
#
# Exit 0 on pass; exit 1 with a diagnostic.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LINT="$HERE/lint_agent_capabilities.sh"

fails=0
note() { printf '  %s\n' "$*"; }

[[ -f "$LINT" ]] || { note "MISSING: $LINT"; exit 1; }

# grants_workflow <agent-file> → 0 if 'Workflow' is a token on the tools: line.
grants_workflow() {
  awk '/^tools:[[:space:]]/ {sub(/^tools:[[:space:]]*/, ""); print; exit}' "$1" \
    | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -qx 'Workflow'
}

LEADS="shepherd engineer conductor"

# --- 1. shipped tree: all three leads GRANT Workflow --------------------------
for role in $LEADS; do
  f="$ROOT/agents/$role.md"
  if [[ ! -f "$f" ]]; then note "FAIL: agents/$role.md missing"; fails=$((fails+1)); continue; fi
  if ! grants_workflow "$f"; then
    note "FAIL: shipped agents/$role.md does not grant 'Workflow' (all three leads must — #233)"
    fails=$((fails+1))
  fi
done

# --- 2. the shipped tree PASSES the lint --------------------------------------
if ! lint_out="$(bash "$LINT" 2>&1)"; then
  note "FAIL: lint_agent_capabilities.sh fails on the real (shipped) tree — should be green:"
  printf '%s\n' "$lint_out" | sed 's/^/      /'
  fails=$((fails+1))
fi

# --- 3. strip Workflow from EACH lead → lint must FAIL (#233 mandate) ----------
for role in $LEADS; do
  tmp="$(mktemp -d -t shep-233.XXXXXX)" || { note "mktemp failed"; exit 1; }
  cp -r "$ROOT/agents" "$tmp/agents"
  awk '
    /^tools:[[:space:]]/ && !done {
      n = split($0, a, /,[[:space:]]*/); out = ""
      for (i = 1; i <= n; i++) { t = a[i]; gsub(/[[:space:]]+$/, "", t)
        if (t == "Workflow" || t ~ /[[:space:]]Workflow$/) continue
        out = (out == "" ? t : out ", " t) }
      print out; done = 1; next
    }
    { print }
  ' "$ROOT/agents/$role.md" > "$tmp/agents/$role.md"
  if grants_workflow "$tmp/agents/$role.md"; then
    note "FAIL: harness could not strip Workflow from $role.md (test setup broken)"
    fails=$((fails+1)); rm -rf "$tmp"; continue
  fi
  if out="$(SHEPHERD_LINT_AGENTS_DIR="$tmp/agents" bash "$LINT" 2>&1)"; then
    note "FAIL: lint PASSED with 'Workflow' stripped from $role — #233 mandate not enforcing"
    printf '%s\n' "$out" | sed 's/^/      /'
    fails=$((fails+1))
  elif ! printf '%s' "$out" | grep -q "FAIL $role:.*Workflow.*#233"; then
    note "FAIL: lint failed for stripped $role but not via the #233 diagnostic:"
    printf '%s\n' "$out" | sed 's/^/      /'
    fails=$((fails+1))
  fi
  rm -rf "$tmp"
done

if [[ "$fails" -gt 0 ]]; then
  printf 'test_lead_workflow_tool: %d failure(s) — the #233 Workflow-grant mandate is not solid\n' "$fails"
  exit 1
fi
printf 'test_lead_workflow_tool: OK — all three leads (shepherd/engineer/conductor) grant Workflow; stripping it from any FAILS the lint (#233)\n'
exit 0
