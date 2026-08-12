#!/usr/bin/env bash
# skills/context/tests/test_models_resolve.sh — `shctx models` (v6.2.5, #170).
#
# Deterministic: built-in defaults, [models] override, section-awareness (a bare
# role key in ANOTHER section must NOT leak into [models]), and unknown-role
# rejection. Runs cmd_models.sh inside an ephemeral git repo so cfg_section_get
# reads the temp .claude/shepherd.toml.

set -uo pipefail
SCRIPTS="$(cd "$(dirname "$0")/../scripts" && pwd)"
CMD="$SCRIPTS/cmd_models.sh"

fails=0
check() { # <label> <expected> <actual>
  if [[ "$2" == "$3" ]]; then printf '  ok   %s\n' "$1"
  else printf '  FAIL %s — expected %q got %q\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

tmp=$(mktemp -d -t shep-models-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .; git config user.email t@t; git config user.name t
mkdir -p .claude

# 1. No [models] block → built-in defaults.
printf '[project]\nname = "t"\n' > .claude/shepherd.toml
check "default engineer=opus[1m]" "opus[1m]" "$(bash "$CMD" resolve engineer)"
check "default coder=sonnet"      "sonnet"   "$(bash "$CMD" resolve coder)"
check "default root=opus[1m]"     "opus[1m]" "$(bash "$CMD" resolve root)"

# 2. [models] override wins.
cat > .claude/shepherd.toml <<'TOML'
[project]
name = "t"
[models]
conductor = "opus[1m]"
coder     = "haiku"
TOML
check "override conductor" "opus[1m]" "$(bash "$CMD" resolve conductor)"
check "override coder"     "haiku"    "$(bash "$CMD" resolve coder)"
check "unset engineer falls to default" "opus[1m]" "$(bash "$CMD" resolve engineer)"

# 3. Section-awareness: a bare `coder =` OUTSIDE [models] must NOT leak in.
cat > .claude/shepherd.toml <<'TOML'
[gates]
coder = "this-is-not-a-model"
[models]
engineer = "opus[1m]"
TOML
check "section-aware coder ignores [gates].coder" "sonnet" "$(bash "$CMD" resolve coder)"

# 4. Unknown role → exit 2.
bash "$CMD" resolve bogusrole >/dev/null 2>&1
rc=$?
check "unknown role exits 2" "2" "$rc"

# 5. show lists all nine roles.
out="$(bash "$CMD" show 2>/dev/null)"
missing=0
for r in root planter engineer conductor critic discovery coder auditor worker; do
  printf '%s' "$out" | grep -q "$r" || { printf '  FAIL show missing role %s\n' "$r"; missing=1; }
done
[[ "$missing" -eq 0 ]] && printf '  ok   show lists all nine roles\n' || fails=$((fails+1))

if [[ "$fails" -gt 0 ]]; then
  printf 'test_models_resolve: %d failure(s)\n' "$fails"; exit 1
fi
printf 'test_models_resolve: OK — defaults, override, section-awareness, unknown-role, show\n'
