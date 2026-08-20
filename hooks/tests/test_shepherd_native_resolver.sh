#!/usr/bin/env bash
# Native hook launchers must not depend on an interactive shell's PATH.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RESOLVER="$ROOT/hooks/scripts/shepherd_native.sh"

tmp=$(mktemp -d -t shep-native-resolver.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home/.cargo/bin" "$tmp/explicit"

cat > "$tmp/home/.cargo/bin/shepherd" <<'EOF'
#!/usr/bin/env bash
printf 'cargo:%s\n' "$*"
EOF
chmod +x "$tmp/home/.cargo/bin/shepherd"

cat > "$tmp/explicit/shepherd" <<'EOF'
#!/usr/bin/env bash
printf 'explicit:%s\n' "$*"
EOF
chmod +x "$tmp/explicit/shepherd"

fails=0
out=$(HOME="$tmp/home" PATH="/usr/bin:/bin" bash "$RESOLVER" claude-hook 2>&1 || true)
if [[ "$out" == "cargo:claude-hook" ]]; then
  echo '  PASS  cargo-home-fallback'
else
  echo "  FAIL  cargo-home-fallback: $out"
  fails=$((fails + 1))
fi

out=$(
  HOME="$tmp/home" \
  PATH="/usr/bin:/bin" \
  SHEPHERD_NATIVE_BIN="$tmp/explicit/shepherd" \
  bash "$RESOLVER" claude-hook 2>&1 || true
)
if [[ "$out" == "explicit:claude-hook" ]]; then
  echo '  PASS  explicit-native-authority'
else
  echo "  FAIL  explicit-native-authority: $out"
  fails=$((fails + 1))
fi

rm -f "$tmp/home/.cargo/bin/shepherd"
out=$(HOME="$tmp/home" PATH="/usr/bin:/bin" bash "$RESOLVER" claude-hook 2>&1)
status=$?
if [[ "$status" -eq 127 ]] && grep -qF 'native shepherd binary not found' <<<"$out"; then
  echo '  PASS  missing-binary-is-actionable'
else
  echo "  FAIL  missing-binary-is-actionable: status=$status output=$out"
  fails=$((fails + 1))
fi

if [[ "$fails" -eq 0 ]]; then
  echo 'PASS: test_shepherd_native_resolver'
  exit 0
fi
echo "FAIL: test_shepherd_native_resolver ($fails)"
exit 1
