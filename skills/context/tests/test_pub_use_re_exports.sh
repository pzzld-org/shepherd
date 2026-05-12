#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init >/dev/null

# Create a fake Rust crate with re-exports to test the v5.0.3 pub-use parser.
mkdir -p src
cat > Cargo.toml <<'EOF'
[package]
name = "reexport_probe"
version = "0.0.1"
edition = "2021"
EOF
cat > src/lib.rs <<'EOF'
pub use foo::Bar;
pub use foo::{Baz, Qux as Quux};
pub use other::Path;

pub mod foo {
    pub struct Bar;
    pub struct Baz;
    pub struct Qux;
}
pub mod other {
    pub struct Path;
}
EOF

command -v cargo >/dev/null || { echo "skip: cargo not installed"; exit 0; }
"$SHCTX" refresh --scope=symbols >/dev/null

db=".shepherd/root.db"
# Verify single re-export (Bar) was indexed
n=$(sqlite3 "$db" "SELECT COUNT(*) FROM index_symbols WHERE name='Bar' AND kind='re-export';")
[[ "$n" -ge 1 ]] || { echo "FAIL: 'pub use foo::Bar' not indexed as re-export (got n=$n)" >&2; sqlite3 "$db" "SELECT name,kind,signature FROM index_symbols;"; exit 1; }

# Verify group re-export with rename (Quux from `Qux as Quux`)
n=$(sqlite3 "$db" "SELECT COUNT(*) FROM index_symbols WHERE name='Quux' AND kind='re-export';")
[[ "$n" -ge 1 ]] || { echo "FAIL: 'pub use foo::{... Qux as Quux}' not indexed (got n=$n)" >&2; exit 1; }

# Verify group member without rename (Baz)
n=$(sqlite3 "$db" "SELECT COUNT(*) FROM index_symbols WHERE name='Baz' AND kind='re-export';")
[[ "$n" -ge 1 ]] || { echo "FAIL: 'pub use foo::{Baz, ...}' not indexed (got n=$n)" >&2; exit 1; }

echo "PASS: test_pub_use_re_exports.sh"
