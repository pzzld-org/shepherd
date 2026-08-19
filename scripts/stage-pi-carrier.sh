#!/usr/bin/env bash
# Materialize the Pi skill and prompt carrier into a staged package tree.
#
# WHY THIS EXISTS.
#
# Pi discovers a package's surface from the `pi` key in its package.json:
#
#   "pi": { "extensions": [...], "skills": ["./skills"], "prompts": ["./prompts"] }
#
# Those paths must resolve INSIDE the published tarball. `@pzzld/pi-shepherd`
# shipped without the `pi` key and without either directory for its entire
# history, so Pi loaded nothing from it -- not the nine skills, not the role
# prompts, and not `src/extension.mjs` itself. The adapter installed cleanly and
# was completely inert: `/shepherd:shepherd` resolved to nothing in the Pi TUI
# while every other package's skills listed normally.
#
# The content was never missing. `shepherd compile --target pi` emits exactly
# the shape Pi wants -- `skills/<name>/SKILL.md` and `prompts/<role>.md` -- and
# has all along. What was missing was anything that put that output inside the
# package.
#
# WHY IT IS STAGED RATHER THAN COMMITTED.
#
# `scripts/tests/test-generated-carrier-authority.sh` fails if
# `packages/harness-pi/skills` or `packages/harness-pi/prompts` exists in the
# repository, and that gate is correct: a hand-copied generated tree becomes a
# second, inevitably stale authority that package tests cannot tell apart from
# the Rust compiler's output. So the carrier is generated into the STAGE copy at
# release time, the same way `scripts/stage-component-runtime.sh` stages the
# generated component runtime, and the repository keeps exactly one authority.
#
# Usage: scripts/stage-pi-carrier.sh <stage-root>
#   <stage-root> holds packages/harness-pi, as prepared by the release workflow.
set -euo pipefail

STAGE_ROOT="${1:-}"
if [[ -z "$STAGE_ROOT" ]]; then
  printf 'usage: %s <stage-root>\n' "$0" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="$STAGE_ROOT/packages/harness-pi"

if [[ ! -d "$PACKAGE_DIR" ]]; then
  printf 'FAIL: staged Pi package not found at %s\n' "$PACKAGE_DIR" >&2
  exit 1
fi

# The native CLI is the only writer of compiled content. Resolve it the same way
# every other adapter path does: an explicit override first, then PATH, then a
# local debug build -- never a hand-rolled copy of the compiler's job.
SHEPHERD_BIN="${SHEPHERD_NATIVE_BIN:-$(command -v shepherd || true)}"
if [[ -z "$SHEPHERD_BIN" && -x "$REPO_ROOT/target/release/shepherd" ]]; then
  SHEPHERD_BIN="$REPO_ROOT/target/release/shepherd"
fi
if [[ -z "$SHEPHERD_BIN" && -x "$REPO_ROOT/target/debug/shepherd" ]]; then
  SHEPHERD_BIN="$REPO_ROOT/target/debug/shepherd"
fi
if [[ -z "$SHEPHERD_BIN" ]]; then
  printf 'FAIL: no shepherd binary (set SHEPHERD_NATIVE_BIN, put shepherd on PATH, or build it)\n' >&2
  exit 1
fi

# `compile --out` requires an absolute path and refuses to write anywhere it
# does not own, so resolve the destination before handing it over.
DEST="$(cd "$PACKAGE_DIR" && pwd)"

# Emit into the staged package. The compiler writes skills/, prompts/, and its
# own .shepherd-generated.json ownership manifest.
"$SHEPHERD_BIN" compile --target pi --out "$DEST"

# STATE THE COUNT, AND FAIL ON ZERO. A staging step that silently produced an
# empty tree would republish exactly the defect this script exists to fix, and
# an empty directory still satisfies "the path exists".
skill_count=$(find "$DEST/skills" -mindepth 2 -maxdepth 2 -name 'SKILL.md' 2>/dev/null | wc -l | tr -d ' ')
prompt_count=$(find "$DEST/prompts" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')

if [[ "$skill_count" -eq 0 ]]; then
  printf 'FAIL: staged Pi carrier contains zero skills at %s/skills\n' "$DEST" >&2
  exit 1
fi
if [[ "$prompt_count" -eq 0 ]]; then
  printf 'FAIL: staged Pi carrier contains zero role prompts at %s/prompts\n' "$DEST" >&2
  exit 1
fi

# The carrier must match the authored source it projects, or the package ships a
# subset and nobody notices. Every skill that is not `portability: claude-only`
# belongs here -- derived, never hardcoded, so adding a skill needs no edit.
expected_skills=$(find "$REPO_ROOT/content/skills" -mindepth 1 -maxdepth 1 -type d | while read -r skill_dir; do
  grep -q '^portability: claude-only' "$skill_dir/SKILL.md" || printf 'x\n'
done | wc -l | tr -d ' ')
expected_prompts=$(find "$REPO_ROOT/content/roles" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')

if [[ "$skill_count" -ne "$expected_skills" ]]; then
  printf 'FAIL: staged Pi carrier has %s skills, expected %s from content/skills\n' \
    "$skill_count" "$expected_skills" >&2
  exit 1
fi
if [[ "$expected_prompts" -gt 0 && "$prompt_count" -ne "$expected_prompts" ]]; then
  printf 'FAIL: staged Pi carrier has %s prompts, expected %s from content/roles\n' \
    "$prompt_count" "$expected_prompts" >&2
  exit 1
fi

printf 'staged Pi carrier: %s skills, %s role prompts under %s\n' \
  "$skill_count" "$prompt_count" "$DEST"
