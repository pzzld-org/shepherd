#!/usr/bin/env bash
# Verifies bin/shepherd is only a native-binary launcher. It must never select
# an interpreter, package manager, or legacy command implementation.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAUNCHER="$ROOT/bin/shepherd"
TMPDIR_TEST="$(mktemp -d "${TMPDIR:-/tmp}/shepherd-native-launcher.XXXXXX")"
trap 'find "$TMPDIR_TEST" -depth -delete' EXIT

failures=0
checks=0

pass() {
  checks=$((checks + 1))
  printf 'PASS %s\n' "$1"
}

fail() {
  checks=$((checks + 1))
  failures=$((failures + 1))
  printf 'FAIL %s: %s\n' "$1" "$2" >&2
}

fake_native="$TMPDIR_TEST/shepherd-native"
cat >"$fake_native" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'native argv:'
printf ' <%s>' "$@"
printf '\n'
EOF
chmod 0755 "$fake_native"

native_out="$(SHEPHERD_NATIVE_BIN="$fake_native" "$LAUNCHER" guard eval --json 2>&1)" || {
  fail 'explicit native binary is executed' "$native_out"
  native_out=''
}
if [[ "$native_out" == 'native argv: <guard> <eval> <--json>' ]]; then
  pass 'explicit native binary receives argv unchanged'
else
  fail 'explicit native binary receives argv unchanged' "got $native_out"
fi

path_bin="$TMPDIR_TEST/path-bin"
mkdir -p "$path_bin"
cp "$fake_native" "$path_bin/shepherd"
plugin_root="$TMPDIR_TEST/plugin"
mkdir -p "$plugin_root/bin"
cp "$LAUNCHER" "$plugin_root/bin/shepherd"
path_out="$(env -u SHEPHERD_NATIVE_BIN PATH="$path_bin:/usr/bin:/bin" "$plugin_root/bin/shepherd" status --json 2>&1)" || {
  fail 'installed PATH binary is executed' "$path_out"
  path_out=''
}
if [[ "$path_out" == 'native argv: <status> <--json>' ]]; then
  pass 'installed PATH binary receives argv unchanged'
else
  fail 'installed PATH binary receives argv unchanged' "got $path_out"
fi

missing_out="$(SHEPHERD_NATIVE_BIN="$TMPDIR_TEST/missing" "$LAUNCHER" init 2>&1)" && {
  fail 'missing native binary fails' 'launcher exited zero'
  missing_out=''
}
if [[ "$missing_out" == *'shepherd: native binary unavailable'* ]] \
  && [[ "$missing_out" == *'SHEPHERD_NATIVE_BIN'* ]] \
  && [[ "$missing_out" != *'python'* ]] \
  && [[ "$missing_out" != *'poetry'* ]]; then
  pass 'missing native binary has interpreter-free diagnostic'
else
  fail 'missing native binary has interpreter-free diagnostic' "got $missing_out"
fi

if rg -n '(poetry|python3?|shepherd_cli|npm|node)' "$LAUNCHER" >/dev/null; then
  fail 'launcher contains no interpreter or package-manager fallback' 'legacy runtime reference found'
else
  pass 'launcher contains no interpreter or package-manager fallback'
fi

if (( failures > 0 )); then
  printf 'FAILED %d/%d checks\n' "$failures" "$checks" >&2
  exit 1
fi

printf 'ok %d checks\n' "$checks"
