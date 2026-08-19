#!/usr/bin/env bash
# The Pi adapter must actually be loadable by Pi.
#
# WHY THIS EXISTS.
#
# `@pzzld/pi-shepherd` shipped for its entire history with no `pi` key in
# package.json. Pi discovers everything a package contributes from that key:
#
#   "pi": { "extensions": [...], "skills": ["./skills"], "prompts": ["./prompts"] }
#
# With the key absent, Pi loaded NOTHING -- not the nine skills, not the role
# prompts, and not `src/extension.mjs`, so the lifecycle hooks and the guard
# never ran either. The package installed cleanly and was completely inert.
# `/shepherd:shepherd` resolved to nothing in the Pi TUI while every other
# installed package listed its skills normally.
#
# Nothing caught it because no gate ever asked what Pi ships. `check-plugin.py`
# derives its roots from the Claude and Codex shipping manifests only, so
# "Claude 10 skills, Codex 9, Pi 0" was not an assertion anywhere.
#
# This gate asserts the declaration, and `test-packed-plugin-portability.sh`
# asserts the packed bytes. Both are needed: a correct `pi` key pointing at
# directories npm does not pack is still an inert package.
#
# Run with --self-test to prove the rules can fail.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACKAGE_JSON="$ROOT/packages/harness-pi/package.json"

fails=0
checks=0
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }
fail() { checks=$((checks + 1)); printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

# One reusable checker so the self-test exercises the SAME code path the real
# scan uses. A self-test that re-implements the rule proves nothing about it.
check_manifest() {
  local manifest="$1"
  python3 - "$manifest" <<'PY'
import json
import sys

manifest = json.loads(open(sys.argv[1]).read())
problems = []

pi = manifest.get("pi")
if not isinstance(pi, dict):
    print("no `pi` key: Pi loads nothing from this package -- not skills, not the extension")
    sys.exit(1)

for field in ("extensions", "skills", "prompts"):
    value = pi.get(field)
    if not isinstance(value, list) or not value:
        problems.append(f"pi.{field} must be a non-empty array")

# npm packs `files` verbatim. A `pi` key naming ./skills while `files` omits it
# produces a tarball whose declared surface does not exist -- inert in exactly
# the same way, and harder to see.
files = manifest.get("files")
if not isinstance(files, list) or not files:
    problems.append("`files` must be declared so the generated carrier is packed")
else:
    for field in ("skills", "prompts"):
        for entry in pi.get(field, []) or []:
            top = entry.lstrip("./").split("/")[0]
            if top and top not in files:
                problems.append(f"pi.{field} names ./{top} but `files` does not pack it")

if "pi-package" not in (manifest.get("keywords") or []):
    problems.append("keywords must include `pi-package` for discovery")

if problems:
    print("; ".join(problems))
    sys.exit(1)
sys.exit(0)
PY
}

if [[ "${1:-}" == "--self-test" ]]; then
  scratch="$(mktemp -d)"
  trap 'rm -rf "$scratch"' EXIT

  # Control FIRST: a correct manifest must PASS. A checker that rejects
  # everything is indistinguishable from one that works.
  cat >"$scratch/good.json" <<'JSON'
{"name":"x","keywords":["pi-package"],
 "pi":{"extensions":["./src/extension.mjs"],"skills":["./skills"],"prompts":["./prompts"]},
 "files":["src","skills","prompts"]}
JSON
  if check_manifest "$scratch/good.json" >/dev/null 2>&1; then
    pass "self-test: a correct manifest is accepted"
  else
    fail "self-test: a correct manifest was rejected ($(check_manifest "$scratch/good.json" 2>&1))"
  fi

  # The exact shipped defect: no `pi` key at all.
  cat >"$scratch/nokey.json" <<'JSON'
{"name":"x","keywords":["pi-package"],"files":["src"]}
JSON
  if check_manifest "$scratch/nokey.json" >/dev/null 2>&1; then
    fail "self-test: a manifest with NO pi key was accepted (the shipped defect)"
  else
    pass "self-test: a manifest with no pi key is rejected"
  fi

  # Declared but unpacked: the subtler inert package.
  cat >"$scratch/unpacked.json" <<'JSON'
{"name":"x","keywords":["pi-package"],
 "pi":{"extensions":["./src/extension.mjs"],"skills":["./skills"],"prompts":["./prompts"]},
 "files":["src"]}
JSON
  if check_manifest "$scratch/unpacked.json" >/dev/null 2>&1; then
    fail "self-test: pi.skills naming a directory `files` omits was accepted"
  else
    pass "self-test: a declared-but-unpacked carrier is rejected"
  fi

  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  exit "$fails"
fi

if [[ ! -f "$PACKAGE_JSON" ]]; then
  fail "packages/harness-pi/package.json is missing"
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  exit "$fails"
fi

if output="$(check_manifest "$PACKAGE_JSON" 2>&1)"; then
  pass "Pi package declares a surface Pi can load (pi.extensions/skills/prompts, packed via files)"
else
  fail "Pi package surface: ${output}"
fi

# The extension entry point the manifest names must exist, or Pi loads a path
# that is not there and the adapter is inert for a second, independent reason.
entry="$(python3 -c '
import json,sys
pi=json.load(open(sys.argv[1])).get("pi",{})
entries=pi.get("extensions") or []
print(entries[0] if entries else "")
' "$PACKAGE_JSON")"
if [[ -n "$entry" && -f "$ROOT/packages/harness-pi/${entry#./}" ]]; then
  pass "pi.extensions entry point resolves on disk: $entry"
else
  fail "pi.extensions entry point does not resolve: ${entry:-<none>}"
fi

# The generated carrier must NOT be committed -- that is a separate, correct
# gate (test-generated-carrier-authority.sh) and this one must not push against
# it. Assert the absence here too, so the two cannot drift into contradiction.
for generated in skills prompts; do
  if [[ -e "$ROOT/packages/harness-pi/$generated" ]]; then
    fail "packages/harness-pi/$generated is committed; it must be staged at release time only"
  else
    pass "packages/harness-pi/$generated is not committed (staged by stage-pi-carrier.sh)"
  fi
done

# ...and the staging script that fills that gap must exist and be executable,
# or the declaration above points at directories nothing ever creates.
if [[ -x "$ROOT/scripts/stage-pi-carrier.sh" ]]; then
  pass "scripts/stage-pi-carrier.sh exists and is executable"
else
  fail "scripts/stage-pi-carrier.sh is missing or not executable"
fi

if grep -Fq 'stage-pi-carrier.sh' "$ROOT/.github/workflows/cargo-build.yml"; then
  pass "the release build runs stage-pi-carrier.sh"
else
  fail "cargo-build.yml never runs stage-pi-carrier.sh, so the carrier is never packed"
fi

printf '%s/%s passed\n' "$((checks - fails))" "$checks"
exit "$fails"
