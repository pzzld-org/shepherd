#!/usr/bin/env bash
# hooks/tests/test_dups_write_guard.sh — PreToolUse(Write|Edit) field-shape gate
# (v6.1.8, #157). Verifies the hook blocks a renamed shadow in block mode, warns
# in warn mode, and fast-paths (non-coder / non-rust / no corpus) silently.
set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/dups_write_guard.sh"
SHCTX="$ROOT/skills/context/scripts/shctx"
export CLAUDE_PLUGIN_ROOT="$ROOT"

command -v python3 >/dev/null || { echo "skip: python3 not installed"; exit 0; }
command -v sqlite3 >/dev/null || { echo "skip: sqlite3 not installed"; exit 0; }

tmp=$(mktemp -d -t shep-dups-hook.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t && git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude crates/types/src
printf '[project]\nname="t"\nlanguage="rust"\n[dups]\ndups_block = 0.75\n' > .claude/shepherd.toml
cat > crates/types/src/lib.rs <<'EOF'
pub struct OpenPositionSnapshot { pub token_id: uuid::Uuid, pub side: u8, pub entry_price: f64, pub size: f64 }
EOF

"$SHCTX" init >/dev/null
"$SHCTX" migrate >/dev/null
"$SHCTX" refresh --scope=shapes >/dev/null   # populate index_struct_shapes

sprint=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
mkdir -p ".shepherd/dispatch/$sprint"
echo '{"agent_role":"coder"}'   > ".shepherd/dispatch/$sprint/coder1.json"
echo '{"agent_role":"auditor"}' > ".shepherd/dispatch/$sprint/aud1.json"

fails=0
expect() { # name expected_substr actual ; empty expected => expect EMPTY output
  local name="$1" want="$2" got="$3"
  if [[ -z "$want" ]]; then
    if [[ -n "$got" ]]; then echo "  FAIL  $name: expected no output, got: $got"; fails=$((fails+1)); else echo "  PASS  $name"; fi
  else
    if grep -qF -- "$want" <<<"$got"; then echo "  PASS  $name"; else echo "  FAIL  $name: want '$want' in: $got"; fails=$((fails+1)); fi
  fi
}

shadow='{"tool_name":"Write","tool_use_id":"coder1","session_id":"s","tool_input":{"file_path":"crates/store/src/row.rs","content":"pub struct PositionRow { pub token_id: i64, pub side: u8, pub entry_price: f64, pub size: f64 }\n"}}'

# block mode (default config dups_block=0.75; set hook mode to block)
printf '[project]\nname="t"\nlanguage="rust"\n[dups]\ndups_block = 0.75\ndups_hook = "block"\n' > .claude/shepherd.toml
out=$(printf '%s' "$shadow" | bash "$HOOK" 2>/dev/null || true)
expect "block-mode-denies-shadow" '"permissionDecision":"deny"' "$out"
expect "block-mode-suggests-reuse" 'reuse it?' "$out"

# warn mode: additionalContext, never deny
printf '[project]\nname="t"\nlanguage="rust"\n[dups]\ndups_block = 0.75\ndups_hook = "warn"\n' > .claude/shepherd.toml
out=$(printf '%s' "$shadow" | bash "$HOOK" 2>/dev/null || true)
expect "warn-mode-context" 'additionalContext' "$out"
if grep -qF '"deny"' <<<"$out"; then echo "  FAIL  warn-mode-must-not-deny"; fails=$((fails+1)); else echo "  PASS  warn-mode-no-deny"; fi

# off mode: silent
printf '[project]\nname="t"\nlanguage="rust"\n[dups]\ndups_hook = "off"\n' > .claude/shepherd.toml
out=$(printf '%s' "$shadow" | bash "$HOOK" 2>/dev/null || true)
expect "off-mode-silent" '' "$out"

# back to block for the negative cases
printf '[project]\nname="t"\nlanguage="rust"\n[dups]\ndups_block = 0.75\ndups_hook = "block"\n' > .claude/shepherd.toml

# non-coder role passes silently
naud='{"tool_name":"Write","tool_use_id":"aud1","session_id":"s","tool_input":{"file_path":"crates/store/src/row.rs","content":"pub struct PositionRow { pub token_id: i64, pub side: u8, pub entry_price: f64, pub size: f64 }\n"}}'
out=$(printf '%s' "$naud" | bash "$HOOK" 2>/dev/null || true)
expect "non-coder-silent" '' "$out"

# non-rust file passes silently
nrs='{"tool_name":"Write","tool_use_id":"coder1","session_id":"s","tool_input":{"file_path":"notes.md","content":"pub struct PositionRow { a: i64 }"}}'
out=$(printf '%s' "$nrs" | bash "$HOOK" 2>/dev/null || true)
expect "non-rust-silent" '' "$out"

# novel struct (no shape match) passes silently
novel='{"tool_name":"Write","tool_use_id":"coder1","session_id":"s","tool_input":{"file_path":"crates/store/src/cfg.rs","content":"pub struct Cfg { pub retries: u32, pub timeout_ms: u64, pub verbose: bool }\n"}}'
out=$(printf '%s' "$novel" | bash "$HOOK" 2>/dev/null || true)
expect "novel-struct-silent" '' "$out"

exit "$fails"
