#!/usr/bin/env bash
# shctx config init — scaffold <namespace>/shepherd.toml from the minimal template,
# deriving name + gates + namespace. Idempotent. (v6.1.5 #15)
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
# config does NOT require `shctx init` (no DB dependency — TOML scaffold only).
# Force the plugin root so the bundled examples/minimal template resolves.
export CLAUDE_PLUGIN_ROOT="$(cd "$SHCTX_SKILL_ROOT/../.." && pwd)"

# v6.4.2: the canonical write target is <namespace>/shepherd.toml, not the
# harness-owned .claude/. Legacy .claude/ bindings still RESOLVE (tiers 3-4).
dst="$SHCTX_TEST_TMP/.shepherd/shepherd.toml"

# ---- rust toolchain + git-remote name ---------------------------------------
git remote add origin https://github.com/acme/widget-service.git
touch Cargo.toml
"$SHCTX" config init
assert_file "$dst"
assert_contains "rust.name"     "$(cat "$dst")" 'name     = "widget-service"'
assert_contains "rust.language" "$(cat "$dst")" 'language = "rust"'
assert_contains "rust.check"    "$(cat "$dst")" 'cargo check --workspace'
# Default namespace is .shepherd/ when neither dir pre-exists.
assert_contains "rust.paths"    "$(cat "$dst")" 'plans   = ".shepherd/docs/plans"'

# ---- idempotent: never clobber an existing binding --------------------------
echo "# CUSTOM-EDIT" >> "$dst"
"$SHCTX" config init
grep -q "CUSTOM-EDIT" "$dst" || { echo "FAIL: config init clobbered an existing config"; exit 1; }

# ---- path subcommand --------------------------------------------------------
p="$("$SHCTX" config path)"
assert_eq "config.path" "$p" "$SHCTX_TEST_TMP/.shepherd/shepherd.toml"

# ---- get subcommand: toggle resolution + default fallback + precedence -------
cat >> "$dst" <<'TOML'
[autorun]
on_grade_floor = "pause"
[spawn]
max_parallel = 3
TOML
assert_eq "get.set"     "$("$SHCTX" config get on_grade_floor abort)" "pause"
assert_eq "get.int"     "$("$SHCTX" config get max_parallel 4)"       "3"
assert_eq "get.default" "$("$SHCTX" config get dashboard_cadence 3m)" "3m"
assert_eq "get.unset-nodef" "$("$SHCTX" config get nonexistent_key)" ""
# .local.toml overrides .toml per-key, WITHIN the same tier group (v6.4.2).
printf '[spawn]\nmax_parallel = 2\n' > "$SHCTX_TEST_TMP/.shepherd/shepherd.local.toml"
assert_eq "get.local-override" "$("$SHCTX" config get max_parallel 4)" "2"
rm -f "$SHCTX_TEST_TMP/.shepherd/shepherd.local.toml"

# ...but a LEGACY .claude/ local override does NOT beat the namespace-tier
# project file: the chain is namespace-group-then-.claude-group, so tier 3
# ranks below tier 2. This is a deliberate v6.4.2 semantic — a harness-owned
# override cannot silently outrank the harness-neutral project binding — and
# is the one behavior change for a project that adds a namespace config while
# keeping a legacy .claude/shepherd.local.toml. Pinned so it cannot regress
# unnoticed.
mkdir -p "$SHCTX_TEST_TMP/.claude"
printf '[spawn]\nmax_parallel = 9\n' > "$SHCTX_TEST_TMP/.claude/shepherd.local.toml"
assert_eq "get.legacy-local-loses-to-namespace" "$("$SHCTX" config get max_parallel 4)" "3"
rm -f "$SHCTX_TEST_TMP/.claude/shepherd.local.toml"

# ---- go toolchain detection (fresh repo) ------------------------------------
TMP2="$(mktemp -d)"; ( cd "$TMP2" && git init -q . \
  && git remote add origin git@github.com:acme/go-thing.git && touch go.mod \
  && CLAUDE_PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT" "$SHCTX" config init >/dev/null \
  && grep -q 'language = "go"' .shepherd/shepherd.toml \
  && grep -q 'go build ./...' .shepherd/shepherd.toml \
  && grep -q 'name     = "go-thing"' .shepherd/shepherd.toml ) \
  || { echo "FAIL: go toolchain detection"; rm -rf "$TMP2"; exit 1; }
rm -rf "$TMP2"

# ---- python toolchain + namespace realignment to .artifacts -----------------
TMP3="$(mktemp -d)"; ( cd "$TMP3" && git init -q . && mkdir .artifacts \
  && touch pyproject.toml \
  && CLAUDE_PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT" "$SHCTX" config init >/dev/null \
  && grep -q 'language = "python"' .artifacts/shepherd.toml \
  && grep -q 'pytest -q' .artifacts/shepherd.toml \
  && grep -q 'plans   = ".artifacts/docs/plans"' .artifacts/shepherd.toml ) \
  || { echo "FAIL: python detection / .artifacts namespace realignment"; rm -rf "$TMP3"; exit 1; }
rm -rf "$TMP3"

# ---- npm toolchain ----------------------------------------------------------
TMP4="$(mktemp -d)"; ( cd "$TMP4" && git init -q . && echo '{}' > package.json \
  && CLAUDE_PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT" "$SHCTX" config init >/dev/null \
  && grep -q 'language = "typescript"' .shepherd/shepherd.toml \
  && grep -q 'npm run build --if-present' .shepherd/shepherd.toml ) \
  || { echo "FAIL: npm/typescript detection"; rm -rf "$TMP4"; exit 1; }
rm -rf "$TMP4"

# ---- claude-md: materialize the operating doctrine block (v6.2.0) ------------
cmd="$SHCTX_TEST_TMP/CLAUDE.md"
rm -f "$cmd"
# fresh repo (no CLAUDE.md) → the managed block becomes the file
"$SHCTX" config claude-md >/dev/null
assert_file "$cmd"
assert_contains "claudemd.begin"   "$(cat "$cmd")" "BEGIN shepherd:operating-doctrine"
assert_contains "claudemd.end"     "$(cat "$cmd")" "END shepherd:operating-doctrine"
assert_contains "claudemd.content" "$(cat "$cmd")" "two machine spaces"
# idempotent: re-run without --force preserves and reports already-present
out="$("$SHCTX" config claude-md)"
assert_contains "claudemd.idempotent" "$out" "already carries"
# append: an existing operator CLAUDE.md without the block keeps its content
printf '# My Project\n\nOperator notes here.\n' > "$cmd"
"$SHCTX" config claude-md >/dev/null
assert_contains "claudemd.append-keeps-operator" "$(cat "$cmd")" "Operator notes here."
assert_contains "claudemd.append-adds-block"     "$(cat "$cmd")" "BEGIN shepherd:operating-doctrine"
# re-sync: --force replaces only the block; operator content survives; no dup block
"$SHCTX" config claude-md --force >/dev/null
assert_contains "claudemd.resync-keeps-operator" "$(cat "$cmd")" "Operator notes here."
nblocks=$(grep -c "BEGIN shepherd:operating-doctrine" "$cmd")
assert_eq "claudemd.single-block" "$nblocks" "1"
rm -f "$cmd"
