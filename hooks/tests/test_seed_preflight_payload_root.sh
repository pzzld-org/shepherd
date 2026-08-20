#!/usr/bin/env bash
# The seed policy is about tool_input.file_path, not the hook process cwd.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/seed_preflight_check.sh"

if ! command -v jq >/dev/null 2>&1; then
  printf 'SKIP: jq is required by the registered seed adapter\n'
  exit 0
fi
if [[ ! -x "$ROOT/target/debug/shepherd" ]]; then
  (cd "$ROOT" && cargo build --quiet --locked -p shepherd-cli --bin shepherd)
fi
export PATH="$ROOT/target/debug:$PATH"

tmp=$(mktemp -d -t shep-seed-payload-root.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
repo="$tmp/project"
outside="$tmp/outside"
mkdir -p "$repo/.shepherd/runs/v039-dev2" "$repo/src" "$outside"
(
  cd "$repo"
  git init -q . >/dev/null
  git config user.email t@t
  git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
)
echo x > "$repo/src/real.rs"
printf '[project]\nname="payload-root"\n' > "$repo/.shepherd/shepherd.toml"

cat > "$tmp/bad.txt" <<'EOF'
---
title: payload root regression
branch: v0.3.9-dev.2
kind: sprint-seed
milestone: 1
file_scope:
  exclusive:
    - src/ghost.rs
---

### D [CRITICAL]

- **GH:** #354
- **Priority:** CRITICAL
- **Acceptance:** TODO: replace this marker
EOF

payload=$(jq -n \
  --arg fp "$repo/.shepherd/runs/v039-dev2/seed.md" \
  --rawfile content "$tmp/bad.txt" \
  '{tool_name:"Write",session_id:"payload-root",tool_input:{file_path:$fp,content:$content}}')

fails=0
run_outside() {
  (cd "$outside" && printf '%s' "$payload" | bash "$HOOK" 2>/dev/null || true)
}

out=$(run_outside)
if grep -qF '"permissionDecision":"deny"' <<<"$out"; then
  echo '  PASS  absolute-payload-path-denies-outside-project-cwd'
else
  echo "  FAIL  absolute-payload-path-denies-outside-project-cwd: $out"
  fails=$((fails + 1))
fi

printf '[project]\nname="payload-root"\n[seed]\nseed_gate = "warn"\n' > "$repo/.shepherd/shepherd.toml"
out=$(run_outside)
if grep -qF 'additionalContext' <<<"$out" && ! grep -qF '"deny"' <<<"$out"; then
  echo '  PASS  payload-project-config-controls-warn-mode'
else
  echo "  FAIL  payload-project-config-controls-warn-mode: $out"
  fails=$((fails + 1))
fi

printf '[project]\nname="payload-root"\n[seed]\nseed_gate = "off"\n' > "$repo/.shepherd/shepherd.toml"
out=$(run_outside)
if [[ -z "$out" ]]; then
  echo '  PASS  payload-project-config-controls-off-mode'
else
  echo "  FAIL  payload-project-config-controls-off-mode: $out"
  fails=$((fails + 1))
fi

if [[ "$fails" -eq 0 ]]; then
  echo 'PASS: test_seed_preflight_payload_root'
  exit 0
fi
echo "FAIL: test_seed_preflight_payload_root ($fails)"
exit 1
