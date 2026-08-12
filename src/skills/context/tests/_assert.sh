# tests/_assert.sh
assert_eq() {
  if [[ "$2" != "$3" ]]; then
    echo "FAIL: $1: expected '$3' got '$2'" >&2; exit 1
  fi
}
assert_contains() {
  if ! grep -qF -- "$3" <<< "$2"; then
    echo "FAIL: $1: '$2' did not contain '$3'" >&2; exit 1
  fi
}
assert_file() {
  [[ -f "$1" ]] || { echo "FAIL: file missing: $1" >&2; exit 1; }
}
assert_table() {
  local db="$1" table="$2"
  sqlite3 "$db" ".schema $table" | grep -q "CREATE TABLE.*$table" \
    || { echo "FAIL: table missing: $table" >&2; exit 1; }
}
