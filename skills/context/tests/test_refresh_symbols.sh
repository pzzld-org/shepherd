#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

# Create a fake Rust crate (no cargo build needed — only `cargo metadata` is invoked).
mkdir -p src
cat > Cargo.toml <<'EOF'
[package]
name = "probe"
version = "0.0.1"
edition = "2021"
EOF
cat > src/lib.rs <<'EOF'
pub struct DriftCircuit;
pub trait Tick {}
pub fn allocate() {}
EOF

command -v cargo >/dev/null || { echo "skip: cargo not installed"; exit 0; }

"$SHCTX" refresh --scope=symbols

count=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" \
  "SELECT COUNT(*) FROM index_symbols WHERE language='rust';")
[[ "$count" -ge 3 ]] || { echo "FAIL: expected ≥3 symbols, got $count" >&2; exit 1; }
sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" \
  "SELECT name FROM index_symbols WHERE name='DriftCircuit';" \
  | grep -q DriftCircuit || { echo "FAIL: DriftCircuit not indexed" >&2; exit 1; }
