#!/usr/bin/env bash
# shctx dups — field-shape similar-struct detection (v6.1.8, #157).
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
DB="$SHCTX_TEST_TMP/.shepherd/shepherd.db"

command -v python3 >/dev/null || { echo "skip: python3 not installed"; exit 0; }

"$SHCTX" init >/dev/null
"$SHCTX" migrate >/dev/null   # applies 0015 (index_struct_shapes)

# Table exists.
assert_table "$DB" index_struct_shapes

# A canonical + a renamed shadow (Uuid->String, same field names) + a third file
# that consumes the shadow (so it carries traffic and the canonical is the orphan).
mkdir -p crates/types/src crates/engine/src crates/app/src
cat > crates/types/src/lib.rs <<'EOF'
pub struct OpenPositionSnapshot {
    pub token_id: uuid::Uuid,
    pub side: u8,
    pub entry_price: f64,
    pub size: f64,
}
pub struct Marker;
EOF
cat > crates/engine/src/lib.rs <<'EOF'
pub struct OpenPosition {
    pub token_id: String,
    pub side: u8,
    pub entry_price: f64,
    pub size: f64,
}
EOF
cat > crates/app/src/main.rs <<'EOF'
use engine::OpenPosition;
fn run(p: OpenPosition) { let _ = p.size; }
EOF

# ── scan: finds the cluster (default threshold 0.7; sim here = 0.8) ──────────
out=$("$SHCTX" dups scan)
assert_contains "scan.cluster"   "$out" "OpenPositionSnapshot"
assert_contains "scan.shadow"    "$out" "OpenPosition"
assert_contains "scan.canonical" "$out" "canonical"
# Marker (unit struct, 0 fields) must NOT appear — nothing to compare.
if grep -q "Marker" <<<"$out"; then echo "FAIL: unit struct Marker was clustered" >&2; exit 1; fi

# ── scan --json: structured output + foundation-blocking severity ────────────
js=$("$SHCTX" dups scan --json)
nclust=$(printf '%s' "$js" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["clusters"]))')
assert_eq "scan.json.clusters" "$nclust" "1"
sev=$(printf '%s' "$js" | python3 -c 'import json,sys;print(json.load(sys.stdin)["clusters"][0]["severity"])')
assert_eq "scan.json.severity" "$sev" "foundation-blocking"

# ── --fail-on: gate returns non-zero ────────────────────────────────────────
rc=0; "$SHCTX" dups scan --fail-on foundation-blocking >/dev/null 2>&1 || rc=$?
assert_eq "scan.fail-on.exit" "$rc" "3"

# ── --update: persists the corpus (Marker excluded — 0 fields stored too,
#    but only ≥min-fields shapes are clustered/matched). ──────────────────────
"$SHCTX" dups scan --update >/dev/null
n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM index_struct_shapes WHERE name IN ('OpenPosition','OpenPositionSnapshot');")
assert_eq "update.persisted" "$n" "2"

# ── refresh --scope=shapes is an alias for scan --update ─────────────────────
"$SHCTX" refresh --scope=shapes >/dev/null
n2=$(sqlite3 "$DB" "SELECT COUNT(*) FROM index_struct_shapes;")
[[ "$n2" -ge 2 ]] || { echo "FAIL: refresh shapes did not populate corpus (got $n2)" >&2; exit 1; }

# ── check: a NEW renamed shadow matches the corpus and blocks (exit 5) ───────
rc=0
out=$(printf 'pub struct PositionRow { pub token_id: i64, pub side: u8, pub entry_price: f64, pub size: f64 }\n' \
  | "$SHCTX" dups check --stdin --as crates/store/src/row.rs --block-threshold 0.75) || rc=$?
assert_eq "check.block.exit" "$rc" "5"
assert_contains "check.reuse" "$out" "reuse it?"

# ── check: a novel struct (no shape match) passes (exit 0, no hits) ──────────
rc=0
out=$(printf 'pub struct Cfg { pub retries: u32, pub timeout_ms: u64, pub verbose: bool }\n' \
  | "$SHCTX" dups check --stdin --as crates/store/src/cfg.rs) || rc=$?
assert_eq "check.novel.exit" "$rc" "0"

# ── registry: allow-list suppresses the cluster ─────────────────────────────
"$SHCTX" dups registry allow "engine::OpenPosition" "types::OpenPositionSnapshot" >/dev/null
assert_file "$SHCTX_TEST_TMP/.shepherd/dups-registry.json"
js=$("$SHCTX" dups scan --json)
nclust=$(printf '%s' "$js" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["clusters"]))')
assert_eq "registry.allow.suppressed" "$nclust" "0"

# ── registry: pin + show ────────────────────────────────────────────────────
"$SHCTX" dups registry pin "OpenPosition" "types::OpenPositionSnapshot" >/dev/null
show=$("$SHCTX" dups registry show)
assert_contains "registry.pin.show" "$show" "types::OpenPositionSnapshot"

echo "test_cmd_dups: all assertions passed"
