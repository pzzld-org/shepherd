#!/usr/bin/env bash
set -euo pipefail

self_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
self="${self_dir}/${BASH_SOURCE[0]##*/}"
cd "${self_dir}/../.."

# Self-lint, first thing: no assertion in this file may be a bare `[[ ... ]]` or
# `(( ... ))` compound command, because macOS bash 3.2 does not honour `set -e`
# for those. Measured, not inferred:
#   /bin/bash -c 'set -e; [[ 2 -eq 3 ]]; echo SURVIVED'  # 3.2.57 -> SURVIVED, rc=0
#   bash       -c 'set -e; [[ 2 -eq 3 ]]; echo SURVIVED' # 5.2.21 -> aborts, rc=1
# (same split for `(( 0 ))`; ordinary commands such as `false` abort on both).
# So a bare assertion is VACUOUS on every developer Mac and LIVE on Linux CI,
# and when it does fire it prints nothing at all. That is exactly how the
# create-release-tar.sh count below shipped wrong from v6.4.6 (f3d44b0, which
# bumped it to `-eq 3` against a workflow that had 2 matching lines then and
# has 2 now) until CI first ran this file on Linux and failed with no reason
# given. Guarded forms -- `[[ ... ]] || { printf ...; exit 1; }` and
# `if [[ ... ]]; then` -- are correct and are what the rest of this file uses.
#
# What makes a statement bare is what follows its CLOSER, never what appears
# somewhere on the line. The first cut of this lint filtered candidate lines
# through `grep -vE '(\|\||&&)'`, which reads the whole line, so an `&&` or `||`
# INSIDE the brackets bought the line an exemption it had not earned. Measured
# against this file: `[[ 1 -eq 2 ]]` caught, `(( 1 == 2 ))` caught,
# `[[ -n "$x" && -f "$y" ]]` MISSED -- and that missed shape is the house idiom
# (scripts/create-release-tar.sh:42,56), so the lint would have passed clean
# while the exact defect it exists to catch walked past it. The same whole-line
# filter, pointed at the repo, also over-counted guarded `[[ cond ]] && action`
# lines and `[[ cond ]] \` continuations, and missed three live sites.
#
# The classifier below instead finds the opener at the head of the statement,
# walks to the closer that MATCHES it (depth-counted, so a nested `$(( ))` or a
# `[[ ]]` inside a command substitution cannot end the scan early), and calls
# the statement bare only when nothing that could consume its exit status
# follows that closer -- end of line, a `;`, or a comment. `if [[ ... ]]; then`
# and `while [[ ... ]]; do` never become candidates, because the statement does
# not start with the opener. The scan is line-scoped: a condition split across
# physical lines by a mid-condition `\` is not classified, so keep assertions
# on one line.
if [[ ! -f "$self" ]]; then
  printf '%s: cannot self-lint; resolved script path does not exist\n' "$self" >&2
  exit 1
fi

bare_compound_awk='
{
  statement = $0
  sub(/^[ \t]*/, "", statement)
  opener = substr(statement, 1, 2)
  if (opener != "[[" && opener != "((") next
  closer = (opener == "[[") ? "]]" : "))"

  depth = 0
  matched = 0
  tail = ""
  n = length(statement)
  for (i = 1; i < n; ) {
    pair = substr(statement, i, 2)
    if (pair == opener) { depth += 1; i += 2; continue }
    if (pair == closer) {
      depth -= 1
      i += 2
      if (depth == 0) { matched = 1; tail = substr(statement, i); break }
      continue
    }
    i += 1
  }
  if (matched == 0) next

  sub(/^[ \t]*/, "", tail)
  if (tail == "\\") next
  if (tail ~ /^#/) tail = ""
  sub(/[ \t;]*$/, "", tail)
  if (tail == "") printf "%d:%s\n", FNR, $0
}
'

# Emits `LINENO:TEXT` for every bare compound statement in the named file.
bare_compound_assertions_in() {
  awk "$bare_compound_awk" "$1"
}

# Negative control for the classifier itself, run every time, for the same
# reason the hand-rolled-tar detector below carries one: a checker never shown
# to fail is not known to check anything. Every line of the first probe must be
# flagged; no line of the second may be. The probes are files run through the
# identical `bare_compound_assertions_in` code path this file uses on itself,
# and they are built with printf rather than a heredoc for a reason specific to
# this check: a heredoc would put literal bare assertions at the head of lines
# in the very file the lint scans, and the lint would fail on its own fixtures.
selflint_probe_dir=$(mktemp -d)
trap 'rm -rf "$selflint_probe_dir"' EXIT
printf '%s\n' \
  '[[ 1 -eq 2 ]]' \
  '(( 1 == 2 ))' \
  '[[ -n "$x" && -f "$y" ]]' \
  '[[ "$a" == "b" || "$a" == "c" ]]' \
  '[[ $(rg -Fc "scripts/create-release-tar.sh" "$workflow") -eq 3 ]]' \
  '(( count == $((one + two)) ))' \
  '    [[ -f "$f" ]]' \
  '[[ -f "$f" ]];' \
  '[[ -f "$f" ]]  # a trailing comment consumes no exit status' \
  > "$selflint_probe_dir/should-flag"
printf '%s\n' \
  '[[ "$rc" -eq 0 ]] || { printf "why\n" >&2; exit 1; }' \
  '[[ -n "$x" ]] && printf "why\n" >&2' \
  '[[ -d "$d" && ! -L "$d" ]] || { printf "why\n" >&2; exit 1; }' \
  '[[ -d "$d" && ! -L "$d" ]] || \' \
  '  fail "source directory is missing, not a directory, or a symlink: $d"' \
  '[[ -d "$d" && ! -L "$d" ]] \' \
  '  || { printf "why\n" >&2; exit 1; }' \
  '(( a == b )) || { printf "why\n" >&2; exit 1; }' \
  'if [[ -n "$x" && -f "$y" ]]; then :; fi' \
  'if (( a >= b )); then :; fi' \
  'while [[ -n "$x" ]]; do :; done' \
  > "$selflint_probe_dir/should-not-flag"

selflint_flagged=$(bare_compound_assertions_in "$selflint_probe_dir/should-flag")
selflint_flagged_lines=$(printf '%s\n' "$selflint_flagged" | cut -d: -f1 | tr '\n' ' ')
selflint_missed=$(awk -v flagged="$selflint_flagged_lines" '
  BEGIN { split(flagged, nums, " "); for (i in nums) seen[nums[i]] = 1 }
  !(FNR in seen) { printf "%d:%s\n", FNR, $0 }
' "$selflint_probe_dir/should-flag")
selflint_false_positives=$(bare_compound_assertions_in "$selflint_probe_dir/should-not-flag")
rm -rf "$selflint_probe_dir"
trap - EXIT

if [[ -n "$selflint_missed" ]]; then
  printf '%s: the bare-assertion classifier let a known-vacuous form through, so it is not known to check anything and cannot be trusted against this file. Undetected:\n%s\n' \
    "$self" "$selflint_missed" >&2
  exit 1
fi
if [[ -n "$selflint_false_positives" ]]; then
  printf '%s: the bare-assertion classifier fires on a correctly guarded assertion, so it would fail this file for no reason:\n%s\n' \
    "$self" "$selflint_false_positives" >&2
  exit 1
fi

bare_compound_assertions=$(bare_compound_assertions_in "$self")
if [[ -n "$bare_compound_assertions" ]]; then
  printf '%s: assertion(s) below are written as a bare [[ ]] / (( )) compound command. macOS bash 3.2 ignores set -e for those, so they never fail locally, and on Linux CI they fail with no stated reason. Guard each one: `[[ ... ]] || { printf "why\\n" >&2; exit 1; }`\n%s\n' \
    "$self" "$bare_compound_assertions" >&2
  exit 1
fi

workflow='.github/workflows/release.yml'
# The release pipeline is THREE files as of the cargo-build split. release.yml
# owns metadata, orchestration, tag, and release custody; cargo-build.yml owns
# every asset; cargo-publish.yml owns crates.io. Assertions below follow each
# property to the file that now owns it -- none were dropped in the move, and
# `pipeline` exists so a property that belongs to the pipeline as a whole
# (checkout pinning, action pins) can be asserted across all three at once.
build_workflow='.github/workflows/cargo-build.yml'
publish_workflow='.github/workflows/cargo-publish.yml'
npm_workflow='.github/workflows/npm-publish.yml'
pipeline=("$workflow" "$build_workflow" "$publish_workflow" "$npm_workflow")
packed_probe='scripts/test-packed-plugin.sh'
for pipeline_file in "${pipeline[@]}"; do
  test -f "$pipeline_file" || {
    printf 'release pipeline file is missing: %s\n' "$pipeline_file" >&2
    exit 1
  }
  ruby -e 'require "yaml"; YAML.load_file(ARGV.fetch(0))' "$pipeline_file" || {
    printf '%s: does not parse as YAML\n' "$pipeline_file" >&2
    exit 1
  }
done
printf 'ok: release pipeline parses (%s files)\n' "${#pipeline[@]}"

# The split is only real if release.yml stopped owning the build. Assert the
# delegation both ways: release.yml must CALL the two workflows, and must not
# have quietly kept an inlined copy of the jobs it delegated.
for called in "$build_workflow" "$publish_workflow" "$npm_workflow"; do
  if ! rg -Fq "uses: ./$called" "$workflow"; then
    printf '%s: release workflow must delegate to %s via `uses:`\n' "$workflow" "$called" >&2
    exit 1
  fi
done
if rg -q '^\s+(build-native-assets|build-component-assets|verify-macos-archive-layout):' "$workflow"; then
  printf '%s: asset jobs belong to %s now; release.yml must not redefine them\n' \
    "$workflow" "$build_workflow" >&2
  exit 1
fi

# Detect-release-commit predicate: the single source of truth for whether a
# commit is a release commit and for which version, exercised directly
# (outside GitHub) against the full truth table. Distinguishing the
# version-mismatch case from a legitimate skip is the whole point of the
# script; this is the assertion that would have caught it collapsed.
detect='scripts/detect-release-commit.sh'
detect_fixtures=$(mktemp -d)
# Synthetic versions, not the current release: this proves the comparison is
# general (any subject vs. any plugin.json), never edited at bump time, and
# never misclassified as a real version surface by version-bump.py.
printf '{"version":"1.2.3"}\n' > "$detect_fixtures/plugin-123.json"
printf '{"version":"1.2.2"}\n' > "$detect_fixtures/plugin-122.json"

assert_detect_skip() {
  local subject="$1" ref="$2" out rc
  out=$("$detect" --subject "$subject" --ref "$ref" --default-branch main \
    --plugin-json "$detect_fixtures/plugin-646.json") && rc=0 || rc=$?
  [[ "$rc" -eq 0 ]] || {
    printf 'expected skip (exit 0) for subject=%q ref=%q, got exit %s\n' "$subject" "$ref" "$rc" >&2
    exit 1
  }
  grep -qx 'verdict=skip' <<<"$out" || {
    printf 'expected verdict=skip for subject=%q ref=%q, got:\n%s\n' "$subject" "$ref" "$out" >&2
    exit 1
  }
}

assert_detect_proceed() {
  local subject="$1" plugin="$2" expected_version="$3" out rc
  out=$("$detect" --subject "$subject" --ref refs/heads/main --default-branch main \
    --plugin-json "$plugin") && rc=0 || rc=$?
  [[ "$rc" -eq 0 ]] || {
    printf 'expected proceed (exit 0) for subject=%q, got exit %s\n' "$subject" "$rc" >&2
    exit 1
  }
  grep -qx 'verdict=proceed' <<<"$out" || {
    printf 'expected verdict=proceed for subject=%q, got:\n%s\n' "$subject" "$out" >&2
    exit 1
  }
  grep -qx "version=${expected_version}" <<<"$out" || {
    printf 'expected version=%s for subject=%q, got:\n%s\n' "$expected_version" "$subject" "$out" >&2
    exit 1
  }
}

assert_detect_fail() {
  local subject="$1" plugin="$2" subject_version="$3" plugin_version="$4" err rc
  err=$("$detect" --subject "$subject" --ref refs/heads/main --default-branch main \
    --plugin-json "$plugin" 2>&1 >/dev/null) && rc=0 || rc=$?
  [[ "$rc" -ne 0 ]] || {
    printf 'expected non-zero exit for mismatched subject=%q, got exit 0\n' "$subject" >&2
    exit 1
  }
  grep -Fq "$subject_version" <<<"$err" || {
    printf 'fail message for subject=%q missing subject version %s: %s\n' "$subject" "$subject_version" "$err" >&2
    exit 1
  }
  grep -Fq "$plugin_version" <<<"$err" || {
    printf 'fail message for subject=%q missing plugin version %s: %s\n' "$subject" "$plugin_version" "$err" >&2
    exit 1
  }
}

assert_detect_skip 'v1.2.3' 'refs/heads/feature-x'
assert_detect_skip 'chore: whatever' 'refs/heads/main'
assert_detect_proceed 'v1.2.3' "$detect_fixtures/plugin-123.json" '1.2.3'
assert_detect_fail 'v1.2.3' "$detect_fixtures/plugin-122.json" '1.2.3' '1.2.2'
assert_detect_fail 'release: v1.2.3' "$detect_fixtures/plugin-122.json" '1.2.3' '1.2.2'
assert_detect_proceed 'v1.2.3 (#123)' "$detect_fixtures/plugin-123.json" '1.2.3'
rm -rf "$detect_fixtures"
printf 'ok: detect-release-commit truth table (non-default ref, non-release subject, proceed, version-mismatch fail, squash suffix) verified\n'

for forbidden in \
  'python3 scripts/version-bump.py bump' \
  'git checkout -b "$PATCH" "$GITHUB_SHA"' \
  'git push -u origin "$PATCH"' \
  'gh pr create' \
  'git push origin --delete' \
  'gh issue edit'; do
  if rg -Fq "$forbidden" "$workflow"; then
    printf 'release workflow must hand post-publication gitflow to gitflow.yml: %s\n' \
      "$forbidden" >&2
    exit 1
  fi
done
if rg -n 'tar -tzf .*\\|.*grep -q' "$packed_probe"; then
  printf 'packed-plugin probe must drain GNU tar before filtering its listing\n' >&2
  exit 1
fi
if rg -n "<<'PY'" "$workflow" || rg -Fq 'python3 - "$maximum" "$floor"' "$workflow"; then
  printf 'release workflow must use the tested glibc helper, not an inline heredoc\n' >&2
  exit 1
fi

python3 scripts/check-github-actions.py

# The property is that EVERY checkout in this workflow pins the exact release
# commit, not that there happen to be five of them. A literal count fails the
# moment a job is added -- which it did, when crate publication moved into this
# workflow to stop racing the asset builds.
# Counting `ref: ${{ github.sha }}` occurrences no longer works: release.yml
# also passes that SHA as an INPUT to each called workflow, so the naive count
# reported "4 of 2" -- more pins than checkouts. Assert the real property
# instead, per file: every checkout resolves to a pinned commit, which in
# release.yml means github.sha literally, and in the called workflows means the
# allowlist-validated ref resolved from the caller's SHA. A checkout pinning
# nothing (or a bare branch) is what this has always been here to catch.
for pipeline_file in "${pipeline[@]}"; do
  checkout_count=$(rg -Fc 'uses: actions/checkout@' "$pipeline_file" || true)
  [[ "$checkout_count" -gt 0 ]] || {
    printf '%s: no checkout found -- pathspec drift?\n' "$pipeline_file" >&2
    exit 1
  }
  pinned_count=$(rg -c 'ref: \$\{\{ (github\.sha|needs\.resolve\.outputs\.ref|steps\.dispatch_ref\.outputs\.ref) \}\}' "$pipeline_file" || true)
  if [[ "$pinned_count" -lt "$checkout_count" ]]; then
    printf '%s: every checkout must pin a resolved commit: %s pinned of %s checkouts\n' \
      "$pipeline_file" "$pinned_count" "$checkout_count" >&2
    exit 1
  fi
done
# ...and the SHA the release resolved must be what it hands to each called
# workflow, or the assets would be built from a different tree than the one
# being tagged.
call_ref_count=$(rg -Fc 'ref: ${{ github.sha }}' "$workflow")
[[ "$call_ref_count" -ge 2 ]] || {
  printf '%s: each called workflow must receive ref: github.sha (found %s)\n' \
    "$workflow" "$call_ref_count" >&2
  exit 1
}
if ! rg -Fq 'python3 scripts/version-bump.py check --root . --version "$current"' "$workflow"; then
  printf '%s: release workflow must call version-bump.py check with the current version before proceeding\n' \
    "$workflow" >&2
  exit 1
fi
if rg -q 'jq --arg v|sed -i\.bak' "$workflow"; then
  printf 'release workflow must delegate version authority to version-bump.py\n' >&2
  exit 1
fi
if ! rg -Fq 'DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}' "$workflow"; then
  printf '%s: release workflow must pin DEFAULT_BRANCH from github.event.repository.default_branch\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/detect-release-commit.sh' "$workflow"; then
  printf '%s: release workflow must invoke scripts/detect-release-commit.sh to classify the commit\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq -- '--plugin-json .claude-plugin/plugin.json' "$workflow"; then
  printf '%s: detect-release-commit.sh call must pass --plugin-json .claude-plugin/plugin.json\n' \
    "$workflow" >&2
  exit 1
fi
if rg -q '^\s*(#\s*)?\[\[ "\$subject" =~ \^\(release:' "$workflow"; then
  printf 'release-metadata detect step must delegate to detect-release-commit.sh, not inline the regex\n' >&2
  exit 1
fi

# No workflow file may hand-roll the release-subject regex; its only
# legitimate home is detect-release-commit.sh. This is the tripwire against
# a fourth copy: release.yml's second "Detect release commit" step and
# gitflow.yml's release-custody check both used to inline this pattern
# (under $SUBJECT, not $subject, so the narrower check above missed them).
duplicate_predicate_hits=$(grep -o 'release:\[\[:space:\]\]' .github/workflows/*.yml 2>/dev/null | wc -l) || true
duplicate_predicate_hits="${duplicate_predicate_hits//[[:space:]]/}"
if [[ "${duplicate_predicate_hits:-0}" -ne 0 ]]; then
  printf 'a workflow file hand-rolls the release-subject regex; delegate to scripts/detect-release-commit.sh instead:\n' >&2
  grep -n 'release:\[\[:space:\]\]' .github/workflows/*.yml >&2 || true
  exit 1
fi
if ! rg -Fq 'git rev-list -n 1 "$TAG"' "$workflow"; then
  printf '%s: release workflow must resolve the tag commit via git rev-list -n 1 "$TAG" before recovery\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'refs/tags/${TAG}^{}' "$workflow"; then
  printf '%s: release workflow must dereference the annotated tag via refs/tags/${TAG}^{} before recovery\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'gh release download "$TAG"' "$workflow"; then
  printf '%s: release workflow must re-download the existing release via gh release download "$TAG" before recovery\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'gh release view "$TAG" --json isDraft,isPrerelease,tagName' "$workflow"; then
  printf '%s: release workflow must inspect the existing release draft/prerelease/tag state via gh release view\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'gh release edit "$TAG" --draft=false' "$workflow"; then
  printf '%s: release workflow must promote a recovered draft release via gh release edit "$TAG" --draft=false\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'diff --recursive --brief "$ASSET_DIR" "$remote_dir"' "$workflow"; then
  printf '%s: release workflow must diff recovered assets against $ASSET_DIR before trusting them\n' \
    "$workflow" >&2
  exit 1
fi
if rg -Fq -- '--clobber' "$workflow"; then
  printf 'release recovery must not delete published assets with --clobber\n' >&2
  exit 1
fi


# ─── Asset-production properties, now owned by cargo-build.yml ──────────────
# Everything from here to the end of this block asserts how release ASSETS are
# built and packaged: targets, the glibc floor, deterministic tars and zips,
# the component and adapter tests. Those jobs moved out of release.yml into
# cargo-build.yml, so the assertions follow them. Not one was dropped or
# softened in the move -- the subject changed, the property did not.
for target in \
  aarch64-apple-darwin \
  x86_64-apple-darwin \
  aarch64-unknown-linux-gnu \
  x86_64-unknown-linux-gnu \
  x86_64-pc-windows-msvc; do
  if ! rg -Fq "$target" "$build_workflow"; then
    printf '%s: build workflow is missing the native build target %s\n' "$build_workflow" "$target" >&2
    exit 1
  fi
done
if ! rg -Fq 'wasm32-wasip2' "$build_workflow"; then
  printf '%s: build workflow is missing the wasm32-wasip2 component target\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/test-component-node.sh' "$build_workflow"; then
  printf '%s: build workflow must run scripts/test-component-node.sh\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/test-packed-plugin.sh' "$build_workflow"; then
  printf '%s: build workflow must run scripts/test-packed-plugin.sh\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'node packages/scripts/check-package-boundary.mjs' "$build_workflow"; then
  printf '%s: build workflow must run the package-boundary check via node packages/scripts/check-package-boundary.mjs\n' \
    "$build_workflow" >&2
  exit 1
fi
for adapter_test in \
  'node packages/harness-claude/test.mjs' \
  'node packages/harness-codex/test.mjs' \
  'node packages/harness-pi/test.mjs'; do
  if ! rg -Fq "$adapter_test" "$build_workflow"; then
    printf '%s: build workflow must run %s\n' "$build_workflow" "$adapter_test" >&2
    exit 1
  fi
  if ! rg -Fq "$adapter_test" scripts/gate.sh; then
    printf 'scripts/gate.sh: local gate must also run %s\n' "$adapter_test" >&2
    exit 1
  fi
done
if ! rg -Fq 'node "$probe"' scripts/tests/test-package-boundary.sh; then
  printf 'scripts/tests/test-package-boundary.sh: must invoke node "$probe" to run the boundary check\n' >&2
  exit 1
fi
if ! rg -Fq 'scripts/tests/test-release-distribution-license.sh' scripts/gate.sh; then
  printf 'scripts/gate.sh: must run scripts/tests/test-release-distribution-license.sh\n' >&2
  exit 1
fi
if ! rg -Fq 'cargo build --locked --release --package shepherd-cli' "$build_workflow"; then
  printf '%s: build workflow must build shepherd-cli via cargo build --locked --release\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'cargo zigbuild --locked --release --package shepherd-cli --target "${TARGET}.2.17"' "$build_workflow"; then
  printf '%s: linux build must use cargo zigbuild pinned to the glibc 2.17 target\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/assert-glibc-floor.py 2.17' "$build_workflow"; then
  printf '%s: build workflow must assert the glibc 2.17 floor on the linux binary\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'RuntimeInformation]::OSArchitecture' scripts/install-shepherd.ps1; then
  printf 'scripts/install-shepherd.ps1: installer must select the OS architecture via RuntimeInformation]::OSArchitecture\n' >&2
  exit 1
fi
if rg -Fq 'RuntimeInformation]::ProcessArchitecture' scripts/install-shepherd.ps1; then
  printf 'Windows installer must select the OS architecture, not the emulated process architecture\n' >&2
  exit 1
fi
if ! rg -Fq 'actual=$("$binary" --version)' "$build_workflow"; then
  printf '%s: build workflow must capture the built binary --version output as actual\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'expected="shepherd-cli ${VERSION}"' "$build_workflow"; then
  printf '%s: build workflow must assert the built binary reports shepherd-cli ${VERSION}\n' "$build_workflow" >&2
  exit 1
fi
# The property is that EVERY release tarball is produced by
# scripts/create-release-tar.sh -- the single place that pins member order,
# ownership, and mtimes -- and that no step hand-rolls tar to build one. It is
# NOT that there are N call-site lines, for the same reason the checkout check
# above counts a property: a literal count fails the moment a job is added, and
# a reader cannot tell a correct literal from a wrong one. This was `-eq 3` and
# had never been true; release.yml has had exactly 2 call-site LINES since
# v6.4.6. The 3 was most likely the runtime ARCHIVE count -- 1 native archive
# per matrix target, plus 2 component archives from the two-iteration
# `for asset in ...` loop -- which a line count can never observe.
#
# The pattern matches an archive-CREATING tar in command position, in the
# spellings a runner might have (GNU tar, bsdtar, gtar; `--create`, clustered
# `-czf`, or the bare mode word `czf`). The leading separator class is what
# keeps it off the two benign `tar` substrings release.yml legitimately
# contains -- `create-release-tar.sh` (preceded by `-`) and the `*.tar.gz`
# asset names (preceded by `.`) -- and the create-mode tail is what keeps it
# off read-only `tar -tzf` / `tar -xzf` verification calls.
raw_tar_pattern='(^|[[:space:];&|(])(bsdtar|gtar|tar)[[:space:]]+(--create|-[[:alnum:]-]*c|c[acfjJvxz]*[[:space:]])'

# Negative control for the pattern itself, run every time: a checker never shown
# to fail is not known to check anything. Every line of the first probe must be
# caught; no line of the second may be. The second is verbatim release.yml text
# plus the read-only tar calls that must stay legal.
#
# The probes are files, not here-string variables, for two reasons: the check
# then runs the identical `grep -nE` code path it runs against release.yml, and
# `var=$(cat <<'EOF' ...)` silently eats a trailing-backslash line continuation
# even with a quoted delimiter -- which would have dropped the `\` from the
# `scripts/create-release-tar.sh \` line, the single most important negative.
raw_tar_probe_dir=$(mktemp -d)
trap 'rm -rf "$raw_tar_probe_dir"' EXIT
cat <<'PROBE' > "$raw_tar_probe_dir/should-match"
tar -czf dist/shepherd.tar.gz -C stage .
bsdtar --create --file dist/shepherd.tar stage
          tar czf dist/shepherd.tar.gz stage
run: cd stage && tar -cf - . | gzip -9 > ../out.tar.gz
gtar --create --gzip --file out.tar.gz stage
PROBE
cat <<'PROBE' > "$raw_tar_probe_dir/should-not-match"
          scripts/create-release-tar.sh \
          versioned="shepherd-${VERSION}-${TARGET}.tar.gz"
          stable="shepherd-${TARGET}.tar.gz"
            'shepherd-component-wasm32-wasip2.tar.gz'; do
          tar -tzf "$archive" > listing.txt
          tar -xzf "$archive" -C "$probe"
          # member order in the tar is pinned by the shared script
PROBE
raw_tar_expected=$(grep -c '' "$raw_tar_probe_dir/should-match")
raw_tar_caught=$(grep -cE "$raw_tar_pattern" "$raw_tar_probe_dir/should-match" || true)
if [[ "$raw_tar_caught" -ne "$raw_tar_expected" ]]; then
  printf '%s: the hand-rolled-tar detector missed a known-bad invocation (caught %s of %s); it cannot be trusted against %s. Undetected:\n%s\n' \
    "$self" "$raw_tar_caught" "$raw_tar_expected" "$build_workflow" \
    "$(grep -vE "$raw_tar_pattern" "$raw_tar_probe_dir/should-match" || true)" >&2
  exit 1
fi
raw_tar_false_positives=$(grep -nE "$raw_tar_pattern" "$raw_tar_probe_dir/should-not-match" || true)
if [[ -n "$raw_tar_false_positives" ]]; then
  printf '%s: the hand-rolled-tar detector fires on legitimate text (a create-release-tar.sh call site, a .tar.gz asset name, or a read-only tar listing/extraction), so it would fail %s for no reason:\n%s\n' \
    "$self" "$build_workflow" "$raw_tar_false_positives" >&2
  exit 1
fi

hand_rolled_tar=$(grep -nE "$raw_tar_pattern" "$build_workflow" || true)
if [[ -n "$hand_rolled_tar" ]]; then
  printf '%s: a release step hand-rolls tar to build an archive. Every release tarball must be produced by scripts/create-release-tar.sh, the only place that pins member order, ownership, and mtimes; a hand-rolled tar silently breaks byte reproducibility:\n%s\n' \
    "$build_workflow" "$hand_rolled_tar" >&2
  exit 1
fi
create_release_tar_calls=$(rg -Fc 'scripts/create-release-tar.sh' "$build_workflow") || true
create_release_tar_calls="${create_release_tar_calls:-0}"
if [[ "$create_release_tar_calls" -lt 1 ]]; then
  printf '%s: release workflow never calls scripts/create-release-tar.sh, and hand-rolls no tar either, so it cannot produce a release tarball at all\n' \
    "$build_workflow" >&2
  exit 1
fi

# Every staging tree that becomes a tarball must have its mtimes normalized
# before packing, or the archive stops being byte-reproducible across reruns.
# Two such trees exist today: the native per-target staging dir and the wasm32
# component staging dir. `-lt 2`, not `-eq 2`, on the same reasoning as above:
# adding a third staging tree must not fail the gate, dropping a normalization
# must.
mtime_normalizations=$(rg -Fc 'TZ=UTC find' "$build_workflow") || true
mtime_normalizations="${mtime_normalizations:-0}"
if [[ "$mtime_normalizations" -lt 2 ]]; then
  printf '%s: every staging tree that becomes a release tarball must normalize mtimes with TZ=UTC find ... -exec touch -t 198001010000; expected at least 2 (native staging and wasm32 component staging), found %s\n' \
    "$build_workflow" "$mtime_normalizations" >&2
  exit 1
fi
if rg -Fq -- '--uid 0' "$build_workflow" || rg -Fq -- '--gid 0' "$build_workflow"; then
  printf 'build workflow must not use BSD-only tar ownership flags\n' >&2
  exit 1
fi
if ! rg -Fq "LastWriteTimeUtc = [DateTime]'1980-01-01T00:00:00Z'" "$build_workflow"; then
  printf '%s: Windows zip staging must pin LastWriteTimeUtc to the epoch 1980-01-01T00:00:00Z\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'function New-DeterministicZip' "$build_workflow"; then
  printf '%s: Windows packaging must define function New-DeterministicZip\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'CreateEntry($relative, [System.IO.Compression.CompressionLevel]::Optimal)' "$build_workflow"; then
  printf '%s: New-DeterministicZip must add entries via CreateEntry at Optimal compression\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq '$entry.LastWriteTime = [DateTimeOffset]' "$build_workflow"; then
  printf '%s: New-DeterministicZip must stamp each zip entry LastWriteTime deterministically\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'Windows release ZIP is not reproducible from identical staged inputs' "$build_workflow"; then
  printf '%s: Windows packaging must self-verify zip reproducibility with a named failure message\n' "$build_workflow" >&2
  exit 1
fi
if rg -Fq 'Compress-Archive' "$build_workflow"; then
  printf 'Windows release archive must use deterministic ZipArchive entries, not Compress-Archive\n' >&2
  exit 1
fi
if ! rg -Fq 'scripts/tests/test-release-installer-windows.ps1' "$build_workflow"; then
  printf '%s: build workflow must run scripts/tests/test-release-installer-windows.ps1\n' "$build_workflow" >&2
  exit 1
fi
if ! rg -Fq 'npm ci --ignore-scripts' "$build_workflow"; then
  printf '%s: build workflow must install npm dependencies via npm ci --ignore-scripts\n' "$build_workflow" >&2
  exit 1
fi

# ─── Back to release.yml's own custody ─────────────────────────────────────
if ! rg -Fq 'gh release create' "$workflow"; then
  printf '%s: release workflow must create the GitHub release via gh release create\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq -- '--verify-tag' "$workflow"; then
  printf '%s: gh release create must pass --verify-tag\n' "$workflow" >&2
  exit 1
fi
if rg -Fq 'gh release upload' "$workflow"; then
  printf 'existing releases must be verified, never overwritten in place\n' >&2
  exit 1
fi
if ! rg -Fq 'sha256sum' scripts/verify-release-assets.sh; then
  printf 'scripts/verify-release-assets.sh: must verify checksums via sha256sum\n' >&2
  exit 1
fi
if ! rg -Fq '((${#release_files[@]} == 32))' "$workflow"; then
  printf '%s: release workflow must assert exactly 32 release_files before uploading\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'ASSET_LIST="${ASSET_DIR}.txt"' "$workflow"; then
  printf '%s: release workflow must derive ASSET_LIST from ASSET_DIR.txt\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/verify-release-assets.sh "$ASSET_DIR" "$ASSET_LIST" "$VERSION"' "$workflow"; then
  printf '%s: release workflow must run scripts/verify-release-assets.sh against the staged assets\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/verify-release-distribution.sh "$ASSET_DIR" "$VERSION"' "$workflow"; then
  printf '%s: release workflow must run scripts/verify-release-distribution.sh against the staged assets\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'expected exactly 32 files (16 assets and 16 sidecars)' scripts/verify-release-assets.sh; then
  printf 'scripts/verify-release-assets.sh: must name the 32-file (16 assets and 16 sidecars) expectation in its failure message\n' >&2
  exit 1
fi
if rg -n '== 34|17 assets|17 checksum' "$workflow" scripts/verify-release-assets.sh; then
  printf 'release workflow retains the removed Claude ZIP asset inventory\n' >&2
  exit 1
fi
if rg -Fq '$ASSET_DIR/assets.txt' "$workflow"; then
  printf 'release workflow must not enumerate a manifest inside its asset directory\n' >&2
  exit 1
fi

# S4(a): the tag must never precede crates.io actually reporting the release published.
crates_line=$(rg -Fn 'https://crates.io/api/v1/crates/${CRATE}' "$workflow" | head -1 | cut -d: -f1 || true)
if [[ -z "$crates_line" ]]; then
  printf 'release workflow must gate the tag on a crates.io publication check\n' >&2
  exit 1
fi
tag_line=$(rg -Fn -- '- name: Tag the verified release commit' "$workflow" | head -1 | cut -d: -f1 || true)
if [[ -z "$tag_line" ]]; then
  printf 'release workflow is missing its tag step; cannot verify crates.io ordering\n' >&2
  exit 1
fi
if ((crates_line >= tag_line)); then
  printf 'crates.io publication gate must run BEFORE the tag step (gate at line %s, tag at line %s)\n' \
    "$crates_line" "$tag_line" >&2
  exit 1
fi
if ! rg -Fq 'gh workflow run cargo-publish.yml -f version=' "$workflow"; then
  printf '%s: release workflow must trigger cargo-publish.yml with -f version=\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq -- '-f publish=true' "$workflow"; then
  printf '%s: cargo-publish.yml dispatch must pass -f publish=true\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'User-Agent' "$workflow"; then
  printf '%s: release workflow polling the GitHub API must set a User-Agent header\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'MAX_ATTEMPTS' "$workflow"; then
  printf '%s: cargo-publish polling loop must bound its retries with MAX_ATTEMPTS\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq '"$published" != true' "$workflow"; then
  printf '%s: cargo-publish polling loop must check "$published" != true before proceeding\n' "$workflow" >&2
  exit 1
fi

# S4(c): the macos-14 binstall archive-layout job must exist and invoke the
# packaging script. It moved to cargo-build.yml with the rest of the assets.
if ! rg -Fq 'runs-on: macos-14' "$build_workflow"; then
  printf '%s: build workflow is missing the macos-14 binstall archive-layout job\n' "$build_workflow" >&2
  exit 1
fi
# The archive-layout check itself lives in one place, scripts/tests/test-release-archive-layout.sh
# (a stronger, four-entry ordered check than the workflow ever inlined). Assert the build path
# calls it both as a self-test (proving the checker itself still fails on bad input) and for real
# (proving it actually runs against the built archive) -- never that the workflow re-implements it.
archive_layout_calls=$(rg -Fc 'scripts/tests/test-release-archive-layout.sh' "$build_workflow") || true
archive_layout_calls="${archive_layout_calls:-0}"
if [[ "$archive_layout_calls" -lt 2 ]]; then
  printf '%s: macos-14 job must both self-test and actually run scripts/tests/test-release-archive-layout.sh (the shared archive-layout check), found %s call(s)\n' \
    "$build_workflow" "$archive_layout_calls" >&2
  exit 1
fi

# S4: no step may reference a secret outside the known set (an undefined secret resolves
# to empty and fails at runtime in a way no local gate catches).
known_secrets=$'secrets.GITHUB_TOKEN\nsecrets.CARGO_REGISTRY_TOKEN\nsecrets.ANTHROPIC_API_KEY\nsecrets.NPM_REGISTRY_TOKEN'
unknown_secrets=$(rg -o 'secrets\.[A-Z_]+' "${pipeline[@]}" | sed 's/^[^:]*://' | sort -u | comm -23 - <(printf '%s\n' "$known_secrets" | sort))
if [[ -n "$unknown_secrets" ]]; then
  printf 'release pipeline references an undefined secret:\n%s\n' "$unknown_secrets" >&2
  exit 1
fi
# A called workflow cannot inherit secrets implicitly: `cargo-publish.yml`
# declares CARGO_REGISTRY_TOKEN as a required `workflow_call` secret, so
# release.yml MUST pass it explicitly or publication fails at runtime with an
# empty token -- the exact class of failure no local gate would otherwise see.
if ! rg -Fq 'CARGO_REGISTRY_TOKEN: ${{ secrets.CARGO_REGISTRY_TOKEN }}' "$workflow"; then
  printf '%s: must forward CARGO_REGISTRY_TOKEN to %s; workflow_call does not inherit secrets\n' \
    "$workflow" "$publish_workflow" >&2
  exit 1
fi
if ! rg -Fq 'CARGO_REGISTRY_TOKEN:' "$publish_workflow"; then
  printf '%s: must declare CARGO_REGISTRY_TOKEN as a workflow_call secret\n' "$publish_workflow" >&2
  exit 1
fi
# Same rule for npm: a called workflow inherits no secrets, so an unforwarded
# NPM_REGISTRY_TOKEN publishes with an empty credential and fails at upload time.
if ! rg -Fq 'NPM_REGISTRY_TOKEN: ${{ secrets.NPM_REGISTRY_TOKEN }}' "$workflow"; then
  printf '%s: must forward NPM_REGISTRY_TOKEN to %s; workflow_call does not inherit secrets\n' \
    "$workflow" "$npm_workflow" >&2
  exit 1
fi
if ! rg -Fq 'NPM_REGISTRY_TOKEN:' "$npm_workflow"; then
  printf '%s: must declare NPM_REGISTRY_TOKEN as a workflow_call secret\n' "$npm_workflow" >&2
  exit 1
fi
# Publication must be held behind the build, on BOTH registries. An npm version
# and a crates.io version are equally un-reissuable, and publication that races
# the asset build is what burned two patch versions.
for publisher in publish-crates publish-npm; do
  if ! rg -Fq "needs: [release-metadata, build]" "$workflow"; then
    printf '%s: %s must declare needs on the asset build\n' "$workflow" "$publisher" >&2
    exit 1
  fi
done

for release_test in \
  test-release-assets.sh \
  test-release-installers.sh \
  test-release-installer-powershell-contract.sh \
  test-release-distribution-license.sh \
  test-release-workflow.sh; do
  if ! rg -Fq "$release_test" scripts/gate.sh; then
    printf 'scripts/gate.sh: must run %s as part of the release gate\n' "$release_test" >&2
    exit 1
  fi
done
bash scripts/tests/test-packed-plugin-portability.sh
bash scripts/tests/test-glibc-floor.sh
bash scripts/tests/test-gitflow-workflow.sh
printf 'ok: release workflow declares native matrix, component/adapters, locked builds, and verified upload\n'
