#!/usr/bin/env bash
# boundary-selftest.sh — prove the boundaries.yml grep gates can still fail.
#
# WHY THIS EXISTS.
#
# Three steps in .github/workflows/boundaries.yml enforce the engine/delivery
# split with a `grep -E` over either a dependency list or the library source:
# "libraries carry no delivery dependencies", "libraries do not touch process
# or argv", and "the engine parses configuration but does not go looking for
# it". Until this script existed, that enforcement claimed a negative control
# only in a prose comment -- nothing ever proved a typo'd regex still catches
# a real violation. A gate with no negative control may be silently passing.
#
# So each gate below runs its own regex, verbatim from boundaries.yml, against
# a deliberately-broken synthetic fixture (must reject) and against the real
# tree (must accept, or the gate is already false-positiving on legitimate
# code). No `cargo` invocation happens here: the dependency gate's fixture is
# shaped like the `cargo tree | awk '{print $1}'` output it actually filters,
# not a real build.
#
# Usage:
#     .github/scripts/boundary-selftest.sh
#
# Wired into .github/workflows/boundaries.yml ahead of the three gates it
# covers, mirroring `scripts/check-workspace.sh --self-test` and
# `scripts/check-plugin.sh --self-test` (see scripts/gate.sh:49,54).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

FAILURES=0

# ok LABEL — the check behaved as designed.
ok() { printf '  %-70s ok\n' "${1}"; }

# broken LABEL — the check did not do the one thing it exists to do.
broken() {
  printf '  %-70s DID NOT CATCH IT\n' "${1}"
  FAILURES=$((FAILURES + 1))
}

COMMENT_FILTER='^[^:]+:[0-9]+:[[:space:]]*(//|\*|/\*)'

# --------------------------------------------------------------- gate 1 --- #
# "libraries carry no delivery dependencies" (boundaries.yml:78-131).
# Fixture mirrors `cargo tree ... | awk '{print $1}' | sort -u`: one bare
# package name per line. No cargo invocation -- the regex is what is on test.
delivery='^clap$|^anyhow$|^tracing-subscriber$'
io_backend='^rusqlite$|^minijinja$|^libsqlite3-sys$'

violating_tree=$'shepherd-core\nclap\nserde\ntokio'
hits=$(printf '%s\n' "${violating_tree}" | grep -E "${delivery}|${io_backend}" || true)
if [ -n "${hits}" ]; then
  ok "forbidden-dependency gate rejects a synthetic clap dependency"
else
  broken "forbidden-dependency gate rejects a synthetic clap dependency"
fi

clean_tree=$'shepherd-core\nserde\ntokio\nthiserror'
hits=$(printf '%s\n' "${clean_tree}" | grep -E "${delivery}|${io_backend}" || true)
if [ -z "${hits}" ]; then
  ok "forbidden-dependency gate accepts a clean dependency list"
else
  broken "forbidden-dependency gate accepts a clean dependency list (false positive: ${hits})"
fi

# --------------------------------------------------------------- gate 2 --- #
# "libraries do not touch process or argv" (boundaries.yml:134-149).
process_pattern='std::process|std::env::args|process::exit'

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

mkdir -p "${TMP}/process/src"
cat >"${TMP}/process/src/violation.rs" <<'EOF'
pub fn bad() {
    std::process::exit(1);
}
EOF
cat >"${TMP}/process/src/commented.rs" <<'EOF'
// std::process::exit(1); -- commented out, must not trip the gate
pub fn fine() {}
EOF

hits=$(grep -rnE "${process_pattern}" "${TMP}/process/src" | grep -vE "${COMMENT_FILTER}" || true)
if printf '%s\n' "${hits}" | grep -q 'violation.rs'; then
  ok "process/argv gate rejects a real std::process::exit call"
else
  broken "process/argv gate rejects a real std::process::exit call"
fi
if printf '%s\n' "${hits}" | grep -q 'commented.rs'; then
  broken "process/argv gate ignores a commented-out std::process line"
else
  ok "process/argv gate ignores a commented-out std::process line"
fi

real_hits=$(grep -rnE "${process_pattern}" \
  crates/core/src crates/registry/src crates/render/src crates/sdk/lib.rs \
  | grep -vE "${COMMENT_FILTER}" || true)
if [ -z "${real_hits}" ]; then
  ok "process/argv gate accepts the real tree"
else
  broken "process/argv gate accepts the real tree (false positive: ${real_hits})"
fi

# --------------------------------------------------------------- gate 3 --- #
# "the engine parses configuration but does not go looking for it"
# (boundaries.yml:162-178).
config_pattern='config::Environment|Environment::with_prefix|File::with_name|File::from\(|add_source\(config::File::from\('

mkdir -p "${TMP}/config/src"
cat >"${TMP}/config/src/violation.rs" <<'EOF'
pub fn load() -> config::Config {
    config::Config::builder()
        .add_source(config::File::with_name("settings"))
        .build()
        .unwrap()
}
EOF
cat >"${TMP}/config/src/fine.rs" <<'EOF'
// File::with_name would be forbidden here; this line is a comment.
pub fn load(contents: &str) -> config::Config {
    config::Config::builder()
        .add_source(config::File::from_str(contents, config::FileFormat::Toml))
        .build()
        .unwrap()
}
EOF

hits=$(grep -rnE "${config_pattern}" "${TMP}/config/src" | grep -vE "${COMMENT_FILTER}" || true)
if printf '%s\n' "${hits}" | grep -q 'violation.rs'; then
  ok "config-I/O gate rejects a real File::with_name call"
else
  broken "config-I/O gate rejects a real File::with_name call"
fi
if printf '%s\n' "${hits}" | grep -q 'fine.rs'; then
  broken "config-I/O gate ignores File::from_str and its own comment (false positive: ${hits})"
else
  ok "config-I/O gate ignores File::from_str and its own comment"
fi

real_hits=$(grep -rnE "${config_pattern}" \
  crates/core/src crates/registry/src crates/render/src crates/sdk/lib.rs \
  | grep -vE "${COMMENT_FILTER}" || true)
if [ -z "${real_hits}" ]; then
  ok "config-I/O gate accepts the real tree"
else
  broken "config-I/O gate accepts the real tree (false positive: ${real_hits})"
fi

echo
if [ "${FAILURES}" -gt 0 ]; then
  echo "::error::${FAILURES} boundary gate(s) have no working negative control."
  exit 1
fi
echo "ok: every boundary gate has a working negative control."
