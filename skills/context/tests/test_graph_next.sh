#!/usr/bin/env bash
# test_graph_next.sh — GH #225 regression: `shctx graph next` threw a Python
# AttributeError when a plan.md Stage Graph node used the natural shorthand
# `agents: [engineer]` (a bare role-name string, valid YAML) instead of the
# mapping form `agents: [{role: engineer, count: 1}]`. Nothing enforced the
# mapping shape, so it sailed through `plan extract` / `plan validate` clean
# and detonated in cmd_graph.sh's `a.get("role")` (`a` was a str, not a dict).
#
# Verifies the full fix:
#   1. `plan extract` normalizes a bare-string agents entry to
#      {"role": ..., "count": 1} (the single writer of state.json's `agents`
#      field) so every downstream reader sees a dict.
#   2. `shctx graph next` (no --json) succeeds on that shorthand and prints
#      the dispatch line with the role tag.
#   3. `plan validate` now REJECTS a genuinely malformed agents entry (no
#      role key) instead of reporting OK for a plan that would still
#      AttributeError downstream.
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
export SHCTX_QUIET=1

# ---------------------------------------------------------------------------
# Fixture A: bare-string shorthand ("agents: [engineer]") + a well-formed
# mapping-form node, in the same plan. Both must extract and dispatch clean.
# ---------------------------------------------------------------------------
cd "$SHCTX_TEST_TMP"
git init -q .
mkdir -p .shepherd .claude
touch .claude/shepherd.toml

cat > plan.md <<'EOF'
## Stage Graph

```yaml
- id: WAVE-1-IMPL
  type: WAVE-1-IMPL
  agents: [engineer]
  parallel_with: [WORKER-IO]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: WORKER-IO
  type: WORKER-IO
  parallel_with: [WAVE-1-IMPL]
  agents: [{role: coder, count: 2}]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: WAVE-1-AUDIT
  type: WAVE-1-AUDIT
  in_predicates: [{predecessor: WAVE-1-IMPL, edge: on-pass}]
  agents: [{role: auditor, count: 1}]
```
EOF

extract_out=$("$SHCTX" plan extract plan.md --sprint=v6.3.9-dev.0)
extract_rc=$?
assert_eq "extract.rc" "$extract_rc" "0"
assert_contains "extract.out" "$extract_out" "extracted 3 nodes"

# `plan validate` must still report OK — the shorthand is now normalized,
# not malformed.
validate_out=$("$SHCTX" plan validate)
validate_rc=$?
assert_eq "validate.rc" "$validate_rc" "0"
assert_contains "validate.ok" "$validate_out" "validate: OK"

# `graph next` (no --json, the crash site from #225) must succeed and show
# both the normalized bare-string role and the mapping-form role.
next_out=$("$SHCTX" graph next)
next_rc=$?
assert_eq "next.rc" "$next_rc" "0"
assert_contains "next.engineer" "$next_out" "@engineer"
assert_contains "next.coder"    "$next_out" "@coder ×2"

# `graph next --json` must also succeed and carry the normalized dict shape.
next_json=$("$SHCTX" graph next --json)
assert_eq "next.json.rc" "$?" "0"
assert_contains "next.json.role" "$next_json" '"role": "engineer"'
assert_contains "next.json.count" "$next_json" '"count": 1'

# `plan topology` (the other pn()-guarded reader) must also survive.
topo_out=$("$SHCTX" plan topology)
assert_eq "topo.rc" "$?" "0"
assert_contains "topo.engineer" "$topo_out" "engineerx1"

echo "test_graph_next: fixture A (bare-string shorthand) OK"

# ---------------------------------------------------------------------------
# Fixture B: a genuinely malformed agents entry — no `role` key at all.
# `plan extract` must now fail loudly at the source instead of writing a
# malformed state.json that only crashes later.
# ---------------------------------------------------------------------------
rm -rf "$SHCTX_TEST_TMP/.shepherd/graph"
cat > plan-bad.md <<'EOF'
## Stage Graph

```yaml
- id: WAVE-1-IMPL
  type: WAVE-1-IMPL
  agents: [{count: 3}]
```
EOF

bad_extract_out=$("$SHCTX" plan extract plan-bad.md --sprint=v6.3.9-dev.0 2>&1) && bad_extract_rc=0 || bad_extract_rc=$?
assert_eq "bad.extract.rc" "$bad_extract_rc" "1"
assert_contains "bad.extract.msg" "$bad_extract_out" "malformed agents entry"

# ---------------------------------------------------------------------------
# Fixture C: malformed agents entry that slips PAST extract because state.json
# was hand-edited / pre-dates the fix. `plan validate` (defense-in-depth check
# #5) must catch it directly rather than reporting OK.
# ---------------------------------------------------------------------------
rm -rf "$SHCTX_TEST_TMP/.shepherd/graph"
cat > plan-good.md <<'EOF'
## Stage Graph

```yaml
- id: WAVE-1-IMPL
  type: WAVE-1-IMPL
  agents: [engineer]
```
EOF
"$SHCTX" plan extract plan-good.md --sprint=v6.3.9-dev.0 >/dev/null

state_path=".shepherd/graph/state.json"
assert_file "$state_path"
python3 - "$state_path" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
# Corrupt the normalized entry back into a malformed shape (no role key) to
# simulate a hand-edited / pre-fix state.json reaching `plan validate`.
d["nodes"]["WAVE-1-IMPL"]["agents"] = [{"count": 3}]
json.dump(d, open(p, "w"), indent=2)
PY

bad_validate_out=$("$SHCTX" plan validate 2>&1) && bad_validate_rc=0 || bad_validate_rc=$?
assert_eq "bad.validate.rc" "$bad_validate_rc" "1"
assert_contains "bad.validate.msg" "$bad_validate_out" "malformed agents entry"

# And the defense-in-depth guard at `graph next` must not crash even on this
# hand-corrupted state — it degrades to printing the bare value, not an
# AttributeError.
next_bad_out=$("$SHCTX" graph next 2>&1) && next_bad_rc=0 || next_bad_rc=$?
assert_eq "bad.next.rc" "$next_bad_rc" "0"
if grep -qi "AttributeError" <<<"$next_bad_out"; then
  echo "FAIL: graph next threw AttributeError on malformed agents entry (#225 regression)" >&2
  printf '%s\n' "$next_bad_out" >&2
  exit 1
fi

echo "test_graph_next: fixture B (malformed → extract fails) OK"
echo "test_graph_next: fixture C (malformed → validate fails, next degrades) OK"
echo "test_graph_next: OK"
