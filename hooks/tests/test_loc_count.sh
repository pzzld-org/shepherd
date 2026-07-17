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

if [[ "$fails" -gt 0 ]]; then
  printf '  FAIL  %d loc-count assertion(s) failed\n' "$fails" >&2
  printf '  ---- script output ----\n%s\n' "$OUT" >&2
  exit 1
fi
printf '  PASS  loc-count.py counts net production LOC deterministically (all spans handled)\n'
