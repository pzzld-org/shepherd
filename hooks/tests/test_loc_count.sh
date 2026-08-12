#!/usr/bin/env bash
# hooks/tests/test_loc_count.sh — regression guard for scripts/loc-count.py (GH #216).
#
# Builds a throwaway git repo whose diff exercises every failure mode the issue
# named, and asserts the exact net-production-LOC the counter must report:
#   - multiple cfg(test) spans in one file      (the W1 "single-span" bug)
#   - #[cfg(all(test, feature = "x"))]           (the W2 regex-miss bug)
#   - #[cfg(not(test))] counted AS production    (negation must not gate)
#   - a file under tests/ skipped entirely
#   - an UNTRACKED new .rs file counted (root gate runs pre-commit)
#   - removed production lines, excluding the old file's cfg(test) span
#
# If the arithmetic here ever disagrees with the script, one of them is wrong —
# and the number is deterministic, so the test is the oracle.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../../scripts/loc-count.py"
fails=0
note() { printf '  %s\n' "$*"; }

[[ -f "$SCRIPT" ]] || { note "FAIL: scripts/loc-count.py missing"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
git init -q
git config user.email t@t.t
git config user.name t
git config commit.gpgsign false
mkdir -p src tests

# --- base commit: fn a (3 lines); rm.rs with a cfg(test) module to be deleted.
cat > src/lib.rs <<'EOF'
pub fn a() -> u32 {
    1
}
EOF
cat > src/rm.rs <<'EOF'
pub fn keep() -> u32 {
    1
}

#[cfg(test)]
mod tests {
    #[test]
    fn old_t() {
        assert!(true);
    }
}
EOF
git add -A && git commit -qm base
BASE="$(git rev-parse HEAD)"

# --- worktree: lib.rs gains production + cfg(not(test)) + TWO test spans.
cat > src/lib.rs <<'EOF'
pub fn a() -> u32 {
    1
}

pub fn b() -> u32 {
    2
}

#[cfg(not(test))]
pub fn only_prod() -> u32 {
    3
}

#[cfg(test)]
mod tests {
    #[test]
    fn t1() {
        assert_eq!(super::a(), 1);
    }
}

#[cfg(all(test, feature = "x"))]
mod extra_tests {
    #[test]
    fn t2() {
        assert_eq!(super::b(), 2);
    }
}
EOF
# rm.rs: delete the whole cfg(test) module (and its leading blank line).
cat > src/rm.rs <<'EOF'
pub fn keep() -> u32 {
    1
}
EOF
# untracked new production file with its own cfg(test) span.
cat > src/newmod.rs <<'EOF'
pub fn n() -> u32 {
    9
}

#[cfg(test)]
mod tests {
    #[test]
    fn nt() {
        assert_eq!(super::n(), 9);
    }
}
EOF
# untracked file under tests/ — must be skipped entirely.
cat > tests/integration.rs <<'EOF'
#[test]
fn it_works() {
    assert!(true);
}
EOF

OUT="$(python3 "$SCRIPT" "$BASE" "$TMP")"

check() {  # <needle> <label>
  if printf '%s\n' "$OUT" | grep -qF -- "$1"; then
    note "PASS  $2"
  else
    note "FAIL  $2 — expected line: $1"
    fails=$((fails+1))
  fi
}
refute() {  # <needle> <label>
  if printf '%s\n' "$OUT" | grep -qF -- "$1"; then
    note "FAIL  $2 — unexpected: $1"
    fails=$((fails+1))
  else
    note "PASS  $2"
  fi
}

check "+11/-0  src/lib.rs"       "lib.rs: 11 prod added (multi-span + cfg(all(test)) + cfg(not(test)) excluded/counted)"
check "+4/-0  src/newmod.rs"     "newmod.rs: untracked new file, 4 prod added, cfg(test) span excluded"
check "+0/-1  src/rm.rs"         "rm.rs: 1 prod line removed, old cfg(test) span excluded"
check "TOTAL: +15/-1 (net 14)"   "TOTAL net production LOC"
refute "tests/integration.rs"    "tests/ dir file skipped"

# --- verify-wave regressions: deletion / rename / trailing-comment cfg(test) ---
has() {  # has <haystack> <needle> <label>
  if printf '%s\n' "$1" | grep -qF -- "$2"; then note "PASS  $3"
  else note "FAIL  $3 — expected: $2"; fails=$((fails+1)); fi
}
newrepo() {  # newrepo <dir>
  git init -q "$1"; git -C "$1" config user.email t@t.t; git -C "$1" config user.name t
  git -C "$1" config commit.gpgsign false; git -C "$1" config diff.renames true
}

# Deletion: a wholly-deleted production .rs must count its removed lines, not
# silently report 0 (the `+++ /dev/null` → path=None drop; verify-wave CRITICAL).
D1="$(mktemp -d)"; newrepo "$D1"; mkdir -p "$D1/src"
printf 'pub fn d() -> u32 {\n    5\n}\n' > "$D1/src/del.rs"
git -C "$D1" add -A && git -C "$D1" commit -qm base >/dev/null
BASE1="$(git -C "$D1" rev-parse HEAD)"; git -C "$D1" rm -q src/del.rs
OUT_DEL="$(python3 "$SCRIPT" "$BASE1" "$D1")"
has "$OUT_DEL" "+0/-3  src/del.rs"      "deletion: removed production lines counted (not zeroed)"
has "$OUT_DEL" "TOTAL: +0/-3 (net -3)"  "deletion: total reflects the deleted file"
rm -rf "$D1"

# Trailing-comment cfg attr: `#[cfg(test)] // note` must still gate its item.
D2="$(mktemp -d)"; newrepo "$D2"; mkdir -p "$D2/src"
printf '// base\n' > "$D2/src/base.rs"
git -C "$D2" add -A && git -C "$D2" commit -qm base >/dev/null
BASE2="$(git -C "$D2" rev-parse HEAD)"
printf '#[cfg(test)] // gate\nmod tests {\n    fn t() {}\n}\npub fn prod() -> u32 { 1 }\n' > "$D2/src/tc.rs"
OUT_TC="$(python3 "$SCRIPT" "$BASE2" "$D2")"
has "$OUT_TC" "+1/-0  src/tc.rs"        "trailing-comment cfg(test) attr recognized (only prod line counts)"
rm -rf "$D2"

# Rename + drop a test fn: the removed line lived in the OLD file's cfg(test)
# span, so it must NOT be miscounted as production (old blob read at OLD path).
# net 0 holds whether or not git pairs the rename; the bug produced net -1.
D3="$(mktemp -d)"; newrepo "$D3"; mkdir -p "$D3/src"
printf 'pub fn keep_a() -> u32 { 1 }\npub fn keep_b() -> u32 { 2 }\npub fn keep_c() -> u32 { 3 }\n#[cfg(test)]\nmod tests {\n    fn t1() {}\n    fn t2() {}\n}\n' > "$D3/src/orig.rs"
git -C "$D3" add -A && git -C "$D3" commit -qm base >/dev/null
BASE3="$(git -C "$D3" rev-parse HEAD)"
git -C "$D3" mv src/orig.rs src/orig2.rs
printf 'pub fn keep_a() -> u32 { 1 }\npub fn keep_b() -> u32 { 2 }\npub fn keep_c() -> u32 { 3 }\n#[cfg(test)]\nmod tests {\n    fn t1() {}\n}\n' > "$D3/src/orig2.rs"
OUT_REN="$(python3 "$SCRIPT" "$BASE3" "$D3")"
has "$OUT_REN" "TOTAL: +0/-0 (net 0)"   "rename+drop-test-fn: removed test-span line not miscounted (old path resolved)"
rm -rf "$D3"

if [[ "$fails" -gt 0 ]]; then
  printf '  FAIL  %d loc-count assertion(s) failed\n' "$fails" >&2
  printf '  ---- script output ----\n%s\n' "$OUT" >&2
  exit 1
fi
printf '  PASS  loc-count.py counts net production LOC deterministically (all spans handled)\n'
