#!/usr/bin/env bash
# scripts/lib/release-package-names.sh
#
# The single source of truth for the tarball filenames `npm pack` emits for
# every package under packages/*/package.json. Every consumer that needs to
# find, stage, or fabricate one of these tarballs sources this file and calls
# release_package_names instead of hardcoding a name list — a hardcoded list
# is exactly what let the release-distribution verifier and its own test
# fixture drift to a shared WRONG set of names for four releases running,
# because both sides copied the same stale literal instead of deriving it.
#
# npm's own transform from package.json "name" to the pack filename:
#   scoped   "@scope/name" -> "scope-name-<version>.tgz"
#   unscoped "name"        -> "name-<version>.tgz"
# (drop the leading "@", replace every "/" with "-")
#
# Deriving every consumer from one function only proves the CONSUMERS agree
# with EACH OTHER — it does not prove the transform itself is right. Two
# things that read the same (possibly wrong) input always agree. --self-test
# below pins the transform against ground truth that is independent of every
# consumer, so a bug in the transform itself cannot hide behind agreement.
#
# Usage, sourced:
#   source scripts/lib/release-package-names.sh
#   release_package_names [expected-version] [packages-root]
#     Emits one tarball name per line, one per <packages-root>/*/package.json
#     (default: <repo-root>/packages), in glob order. Each manifest's own
#     "version" field is what names its tarball. If expected-version is
#     given, every manifest's version must equal it exactly, or the function
#     fails loudly instead of silently preferring either value.
#     packages-root exists only so --self-test can pin the transform against
#     synthetic fixtures without touching the real packages/ tree; every real
#     consumer omits it and scans the real tree.
#
# Usage, direct (for inspection):
#   bash scripts/lib/release-package-names.sh [expected-version]
#   bash scripts/lib/release-package-names.sh --self-test
set -euo pipefail

release_package_names() {
  local expected_version="${1:-}"
  local packages_root="${2:-}"
  local repo_root
  repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
  local scan_root="${packages_root:-${repo_root}/packages}"

  local matched=0
  local package_json
  for package_json in "${scan_root}"/*/package.json; do
    [[ -e "$package_json" ]] || continue
    matched=1

    local fields
    fields=$(python3 -c '
import json
import sys

data = json.load(open(sys.argv[1]))
print(data["name"])
print(data["version"])
' "$package_json")

    local name version
    {
      IFS= read -r name
      IFS= read -r version
    } <<<"$fields"

    if [[ -n "$expected_version" && "$version" != "$expected_version" ]]; then
      printf 'release-package-names: %s declares version %s, expected %s\n' \
        "$package_json" "$version" "$expected_version" >&2
      return 1
    fi

    local scoped_name="${name#@}"
    scoped_name="${scoped_name//\//-}"
    printf '%s-%s.tgz\n' "$scoped_name" "$version"
  done

  if [[ "$matched" -eq 0 ]]; then
    printf 'release-package-names: no */package.json found under %s\n' "$scan_root" >&2
    return 1
  fi
}

# self_test
#
# Pins the npm-pack transform against ground truth that is independent of
# every consumer that sources this file. Sharing one function is not the
# same as that function being CORRECT: if the transform itself regressed to
# the historical fl03- bug, every consumer would derive the same wrong name
# and agree with each other — the license gate would stay green against a
# transform that is flatly wrong, exactly the mirror that hid the original
# defect for four releases, just moved one level up. These four controls
# each fail independently of any consumer:
#   1. the pinned real-world example: @pzzld/pi-claude, at a SYNTHETIC
#      version that is not any real release, so a pass proves the rule
#      itself and never goes stale as the repo version moves
#   2. the general scoped rule, with a scope/name unrelated to (1) so a pass
#      cannot be coincidental
#   3. the general unscoped rule: no prefix invented
#   4. the current real packages/*/package.json produce the four NAME STEMS
#      that were wrong for four releases, each followed by that package's
#      OWN manifest version (read independently, never hardcoded — the
#      version digits were never the bug, the stems were)
self_test() {
  printf 'self-test: pin the npm-pack transform against ground truth\n\n'
  local fails=0

  # --- (1) pinned real-world example, synthetic version ----------------------
  # 2.0.0 is deliberately NOT the current release version: pinning against
  # today's real number would let this control pass by accidentally agreeing
  # with the repo, not by exercising the rule, and it would need editing on
  # every release. A synthetic version proves the transform is
  # VERSION-AGNOSTIC. Do not "helpfully" restore the real version here.
  local fixture_a got_a want_a
  fixture_a="$(mktemp -d -t release-package-names-selftest.XXXXXX)"
  mkdir -p "${fixture_a}/pkg"
  printf '{"name":"@pzzld/pi-claude","version":"2.0.0"}\n' > "${fixture_a}/pkg/package.json"
  got_a="$(release_package_names '' "${fixture_a}")"
  want_a='pzzld-pi-claude-2.0.0.tgz'
  if [[ "${got_a}" == "${want_a}" ]]; then
    printf '  PASS  @pzzld/pi-claude at 2.0.0 -> %s\n' "${want_a}"
  else
    printf '  FAIL  @pzzld/pi-claude at 2.0.0 -> got "%s", want "%s"\n' "${got_a}" "${want_a}"
    fails=$((fails + 1))
  fi
  rm -rf "${fixture_a}"

  # --- (2) general scoped rule: drop "@", replace "/" with "-" --------------
  local fixture_b got_b
  fixture_b="$(mktemp -d -t release-package-names-selftest.XXXXXX)"
  mkdir -p "${fixture_b}/pkg"
  printf '{"name":"@acme/widget-tool","version":"9.9.9"}\n' > "${fixture_b}/pkg/package.json"
  got_b="$(release_package_names '' "${fixture_b}")"
  if [[ "${got_b}" == "acme-widget-tool-9.9.9.tgz" ]]; then
    printf '  PASS  scoped @acme/widget-tool at 9.9.9 -> acme-widget-tool-9.9.9.tgz\n'
  else
    printf '  FAIL  scoped @acme/widget-tool at 9.9.9 -> got "%s", want "acme-widget-tool-9.9.9.tgz"\n' "${got_b}"
    fails=$((fails + 1))
  fi
  rm -rf "${fixture_b}"

  # --- (3) general unscoped rule: no prefix invented -------------------------
  local fixture_c got_c
  fixture_c="$(mktemp -d -t release-package-names-selftest.XXXXXX)"
  mkdir -p "${fixture_c}/pkg"
  printf '{"name":"widget","version":"1.2.3"}\n' > "${fixture_c}/pkg/package.json"
  got_c="$(release_package_names '' "${fixture_c}")"
  if [[ "${got_c}" == "widget-1.2.3.tgz" ]]; then
    printf '  PASS  unscoped widget at 1.2.3 -> widget-1.2.3.tgz, no invented prefix\n'
  else
    printf '  FAIL  unscoped widget at 1.2.3 -> got "%s", want "widget-1.2.3.tgz"\n' "${got_c}"
    fails=$((fails + 1))
  fi
  rm -rf "${fixture_c}"

  # --- (4) the real manifests: four name stems, each own version read -------
  # independently (never through release_package_names itself, or this would
  # just be checking the function against itself) and never hardcoded, since
  # the version digits were never the bug — the stems were.
  local repo_root
  repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
  local dirs=(component-runtime harness-claude harness-codex harness-pi)
  local stems=(pzzld-component-runtime pzzld-pi-claude pzzld-pi-codex pzzld-pi-shepherd)
  local want_d='' i dir stem manifest_version
  for i in 0 1 2 3; do
    dir="${dirs[$i]}"
    stem="${stems[$i]}"
    manifest_version=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' \
      "${repo_root}/packages/${dir}/package.json")
    [[ -n "${want_d}" ]] && want_d="${want_d}"$'\n'
    want_d="${want_d}${stem}-${manifest_version}.tgz"
  done
  local got_d
  got_d="$(release_package_names)"
  if [[ "${got_d}" == "${want_d}" ]]; then
    printf '  PASS  real packages/*/package.json produce exactly the four expected name stems\n'
  else
    printf '  FAIL  real manifests produced:\n%s\n        want:\n%s\n' "${got_d}" "${want_d}"
    fails=$((fails + 1))
  fi

  printf '\n'
  if [[ "${fails}" -gt 0 ]]; then
    printf '::error::%d self-test control(s) failed — the transform is not trustworthy.\n' "${fails}"
    return 1
  fi
  printf 'ok: the npm-pack transform matches ground truth on every control.\n'
  return 0
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  if [[ "${1:-}" == "--self-test" ]]; then
    self_test
    exit $?
  fi
  release_package_names "${1:-}"
fi
