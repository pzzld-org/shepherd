#!/usr/bin/env bash
set -euo pipefail

# Written for bash 3.2: macOS resolves `/usr/bin/env bash` to 3.2.57, so no
# mapfile, no associative arrays, no negative array indices.

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

creator="$PWD/scripts/create-release-tar.sh"
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-release-tar.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT

checks_run=0

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

# Every assertion below routes through one of these so the final `ok:` line can
# report how many properties were actually verified. A gate that cannot say how
# many things it checked is not evidence.
assert_equal() {
  [[ "$1" == "$2" ]] || fail "$3 (expected: $2 / actual: $1)"
  checks_run=$((checks_run + 1))
}

assert_contains() {
  [[ "$1" == *"$2"* ]] || fail "$3 (not found: $2 / in: $1)"
  checks_run=$((checks_run + 1))
}

assert_identical() {
  cmp -s "$1" "$2" || fail "$3"
  checks_run=$((checks_run + 1))
}

real_tar=$(command -v tar)
# bsdtar's --version line ends in a space; trim it so messages read cleanly.
real_tar_version=$("$real_tar" --version 2>/dev/null | head -1 | sed 's/[[:space:]]*$//')

source_dir="$tmp_dir/source"
mkdir -p "$source_dir/THIRD_PARTY_LICENSES"
printf 'license\n' > "$source_dir/LICENSE"
printf 'notices\n' > "$source_dir/THIRD_PARTY_NOTICES.md"
printf 'dependency license\n' > "$source_dir/THIRD_PARTY_LICENSES/dependency.txt"
printf 'payload\n' > "$source_dir/payload"
printf 'option-shaped filename\n' > "$source_dir/--exclude=payload"
TZ=UTC find "$source_dir" -type f -exec touch -t 198001010000 {} +

entries=(
  LICENSE
  THIRD_PARTY_NOTICES.md
  THIRD_PARTY_LICENSES/dependency.txt
  payload
  --exclude=payload
)

# The two ownership flag families create-release-tar.sh chooses between. Single
# source of truth: the stubs, the direct host-tar probes, and the assertions on
# what the script actually emitted are all generated from these arrays. bash 3.2
# cannot return an array, so the family setter writes the `owner_flags` global.
set_owner_flags() {
  case "$1" in
    gnu) owner_flags=(--owner 0 --group 0 --numeric-owner) ;;
    libarchive) owner_flags=(--uid 0 --gid 0 --uname '' --gname '') ;;
    *) fail "unknown tar ownership family: $1" ;;
  esac
}

owner_flags=()

# Human-readable name for a family, used in skip and failure messages.
family_label() {
  case "$1" in
    gnu) printf 'GNU --owner/--group' ;;
    libarchive) printf 'libarchive --uid/--gid/--uname/--gname' ;;
    *) printf '%s' "$1" ;;
  esac
}

# Does this tar binary actually accept this family? Probes real behaviour on a
# throwaway archive rather than parsing `tar --version`, for the same reason
# create-release-tar.sh does: the version string is not the capability.
tar_supports_family() {
  local tar_binary="$1" probe_dir
  set_owner_flags "$2"
  probe_dir=$(mktemp -d "$tmp_dir/probe.XXXXXX")
  printf 'p\n' > "$probe_dir/probe"
  LC_ALL=C "$tar_binary" --format=ustar "${owner_flags[@]}" \
    -C "$probe_dir" -cf /dev/null -- probe >/dev/null 2>&1
}

# First tar binary on this host that accepts the given family; sets `family_tar`.
# The host tar comes first so the common case needs no extra probing; bsdtar and
# gtar are checked so a host carrying both implementations proves more, not less.
select_family_tar() {
  local family="$1" candidate resolved
  family_tar=""
  for candidate in "$real_tar" bsdtar gtar gnutar; do
    resolved=$(command -v "$candidate" 2>/dev/null) || continue
    if tar_supports_family "$resolved" "$family"; then
      family_tar="$resolved"
      return 0
    fi
  done
  return 1
}

family_tar=""

# The stubs below must hand real work to the host tar, so they must speak the
# family the host tar actually supports -- otherwise the "old libarchive" stub
# only works on a host that is already libarchive, which is the exact
# host-dependence this gate exists to eliminate.
host_family=""
for family in gnu libarchive; do
  if tar_supports_family "$real_tar" "$family"; then
    host_family="$family"
    break
  fi
done
[[ -n "$host_family" ]] || \
  fail "host tar ($real_tar_version) accepts neither ownership family; cannot delegate stub work"
set_owner_flags "$host_family"
host_owner_flags=("${owner_flags[@]}")

# Two stubs modelling REAL tar implementations, not the script under test.
# GNU tar has --owner/--group and rejects --uid/--gid/--uname/--gname; older
# libarchive (bsdtar) rejects --owner/--group in every spelling and requires
# --uid/--gid/--uname/--gname instead. No real implementation accepts every
# option this script might send, which is exactly the bug: create-release-tar.sh
# must detect which family its tar actually supports rather than assume one.
#
# A stub presents one implementation's option INTERFACE and delegates the
# archive WORK to the host tar, translating the ownership options into
# `host_owner_flags` on the way through. It records the argv it was handed
# BEFORE that translation, which is what the assertions read: the recorded argv
# is the script's decision, the translation is only how the bytes get written.
for family in gnu libarchive; do
  mkdir -p "$tmp_dir/bin/$family"
  {
    printf '#!/usr/bin/env bash\n'
    printf '# Generated by scripts/tests/test-release-tar-portability.sh\n'
    printf 'stub_family=%q\n' "$family"
    printf 'host_owner_flags=(%s)\n' "$(printf '%q ' "${host_owner_flags[@]}")"
    cat <<'STUB_EOF'
set -euo pipefail

# One line per invocation, `printf %q`-quoted so an empty --uname value records
# as '' and the whole argv stays on one greppable line.
{
  printf '%q ' "$@"
  printf '\n'
} >> "${TAR_ARGV_LOG:?}"

reject_option() {
  case "$stub_family" in
    gnu)
      # GNU tar 1.35 measured: "tar: unrecognized option '--uid'", exit 64.
      printf 'portable tar regression: GNU-like tar rejects BSD-only option %s\n' "$1" >&2
      exit 64
      ;;
    libarchive)
      # Old libarchive rejects the whole --owner/--group family, exit 1.
      printf 'tar: Option %s=0 is not supported\n' "$1" >&2
      exit 1
      ;;
  esac
}

# Ownership options this stub's family accepts. Everything else in the
# ownership vocabulary is rejected the way the real implementation rejects it.
accept_or_reject_option() {
  case "$stub_family:$1" in
    gnu:--owner|gnu:--group) return 0 ;;
    libarchive:--uid|libarchive:--gid|libarchive:--uname|libarchive:--gname) return 0 ;;
    *:--numeric-owner) return 0 ;;
  esac
  reject_option "$1"
}

delegated=()
options_terminated=0
while (($# > 0)); do
  argument="$1"
  shift

  # Past `--` every argument is a filename, including one spelled like an
  # option, so nothing here may reinterpret it.
  if ((options_terminated == 1)); then
    delegated+=("$argument")
    continue
  fi

  case "$argument" in
    --)
      options_terminated=1
      delegated+=("$argument")
      ;;
    --numeric-owner)
      accept_or_reject_option "$argument"
      ;;
    --owner|--group|--uid|--gid|--uname|--gname)
      accept_or_reject_option "$argument"
      (($# > 0)) || {
        printf 'tar: Option %s requires an argument\n' "$argument" >&2
        exit 1
      }
      shift # the separated value belongs to the ownership option; both are dropped
      ;;
    --owner=*|--group=*|--uid=*|--gid=*|--uname=*|--gname=*)
      accept_or_reject_option "${argument%%=*}"
      ;;
    --exclude=payload)
      printf 'portable tar regression: option-shaped entry reached tar without --\n' >&2
      exit 64
      ;;
    *)
      delegated+=("$argument")
      ;;
  esac
done

exec "${REAL_TAR:?}" "${host_owner_flags[@]}" ${delegated[@]+"${delegated[@]}"}
STUB_EOF
  } > "$tmp_dir/bin/$family/tar"
  chmod 755 "$tmp_dir/bin/$family/tar"
done

check_archive_properties() {
  local archive="$1" label="$2" actual expected verified

  actual=$(tar -tzf "$archive")
  expected=$'LICENSE\nTHIRD_PARTY_NOTICES.md\nTHIRD_PARTY_LICENSES/dependency.txt\npayload\n--exclude=payload'
  assert_equal "$actual" "$expected" \
    "$label: release tar contains an unexpected entry set or order"

  # Prints the number of member properties it verified so the total is real.
  verified=$(python3 - "$archive" "$label" <<'PY'
from pathlib import Path
import sys
import tarfile

archive = Path(sys.argv[1])
label = sys.argv[2]
with tarfile.open(archive, "r:gz") as handle:
    members = handle.getmembers()

if not members:
    raise SystemExit(f"{label}: release tar is empty")
for member in members:
    if (member.uid, member.gid) != (0, 0):
        raise SystemExit(f"{label}: non-canonical owner for {member.name}: {member.uid}:{member.gid}")
    if member.mtime != 315532800:
        raise SystemExit(f"{label}: non-canonical mtime for {member.name}: {member.mtime}")
print(2 * len(members))
PY
)
  checks_run=$((checks_run + verified))
}

# create-release-tar.sh calls tar more than once: one probe per candidate family
# until one is accepted, then the real run. Only the real run writes the archive,
# and it is the only invocation whose output goes to stdout (-cf -); the probes
# write to /dev/null. Every assertion below names which invocation it reads.
archive_writing_marker='-cf - '

count_invocations() {
  awk 'END {print NR}' "$1"
}

count_archive_writing_invocations() {
  awk -v marker="$archive_writing_marker" 'index($0, marker) {found++} END {print found + 0}' "$1"
}

archive_writing_invocation() {
  awk -v marker="$archive_writing_marker" 'index($0, marker)' "$1"
}

# Expected probe ladder per stub. GNU is probed first, so a GNU-like tar accepts
# on probe 1; an old-libarchive-like tar rejects probe 1 and accepts probe 2.
expected_probes_for() {
  case "$1" in
    gnu) printf '1' ;;
    libarchive) printf '2' ;;
  esac
}

for label in gnu libarchive; do
  first="$tmp_dir/$label-first.tar.gz"
  second="$tmp_dir/$label-second.tar.gz"

  run_index=0
  for archive in "$first" "$second"; do
    run_index=$((run_index + 1))
    PATH="$tmp_dir/bin/$label:$PATH" REAL_TAR="$real_tar" \
      TAR_ARGV_LOG="$tmp_dir/$label-argv-$run_index.log" \
      "$creator" "$source_dir" "$archive" "${entries[@]}" || \
      fail "$label: create-release-tar.sh failed under the $label-like tar stub"
    checks_run=$((checks_run + 1))
  done

  assert_identical "$first" "$second" \
    "$label: release tar must be byte-reproducible across two runs under the $label-like tar stub"
  # Only the archive-writing invocation is compared across runs: the probes run
  # in a fresh `mktemp -d`, so their -C path is expected to differ.
  assert_equal \
    "$(archive_writing_invocation "$tmp_dir/$label-argv-2.log")" \
    "$(archive_writing_invocation "$tmp_dir/$label-argv-1.log")" \
    "$label: create-release-tar.sh must issue an identical archive-writing tar command line on every run"

  check_archive_properties "$first" "$label"

  # Assertions below read run 1's log; run 2's archive-writing invocation was
  # just proven identical to it.
  argv_log="$tmp_dir/$label-argv-1.log"
  invocations=$(count_invocations "$argv_log")
  archive_writing=$(count_archive_writing_invocations "$argv_log")
  probes=$((invocations - archive_writing))
  real_invocation=$(tail -n 1 "$argv_log")
  first_invocation=$(head -n 1 "$argv_log")

  assert_equal "$archive_writing" '1' \
    "$label: exactly one tar invocation may write the release archive"
  assert_contains "$real_invocation" "$archive_writing_marker" \
    "$label: the archive-writing tar invocation must be the last one"
  assert_equal "$probes" "$(expected_probes_for "$label")" \
    "$label: unexpected ownership-flag probe ladder before the archive-writing invocation"

  # The first invocation is always the GNU probe: it is what the libarchive-like
  # stub has to reject for the fallback to mean anything.
  set_owner_flags gnu
  gnu_flags=$(printf '%q ' "${owner_flags[@]}")
  assert_contains "$first_invocation" "$gnu_flags" \
    "$label: the first tar invocation must probe the GNU ownership family"
  [[ "$first_invocation" != *"$archive_writing_marker"* ]] || \
    fail "$label: the first tar invocation must be a throwaway probe, not the release archive"
  checks_run=$((checks_run + 1))

  # The point of the whole gate: which family did the script actually select for
  # the run that produces the artifact?
  set_owner_flags "$label"
  selected_flags=$(printf '%q ' "${owner_flags[@]}")
  assert_contains "$real_invocation" "$selected_flags" \
    "$label: the archive-writing tar invocation must use the $(family_label "$label") family"

  case "$label" in
    gnu) forbidden_flags=(--uid --gid --uname --gname) ;;
    libarchive) forbidden_flags=(--owner --group --numeric-owner) ;;
  esac
  for flag in "${forbidden_flags[@]}"; do
    [[ "$real_invocation" != *"$flag"* ]] || \
      fail "$label: the archive-writing tar invocation leaked the foreign-family option $flag"
  done
  checks_run=$((checks_run + 1))

  # The option-shaped entry must arrive after the `--` terminator, so tar reads
  # it as a filename. Asserted on the recorded argv, not just on the stub's
  # willingness to run.
  before_option_shaped_entry="${real_invocation%%--exclude=payload*}"
  assert_contains "$before_option_shaped_entry" ' -- ' \
    "$label: --exclude=payload must be passed after the -- terminator"
done

# Both stubs delegate to the same host tar, so comparing their two archives
# proves nothing about the flag families -- it only proves the stubs agree. The
# honest form of that claim is checked directly against the real tar binaries:
# within one implementation the two families must write identical bytes, so
# which family create-release-tar.sh picks cannot change the artifact.
#
# It is only ever a within-implementation claim. Measured across
# implementations, GNU tar 1.35 and bsdtar 3.5.3 differ on the same input
# regardless of family (GNU NUL-terminates the octal header fields and pads to a
# 10240-byte block; bsdtar space-terminates and fills devmajor/devminor), so a
# cross-runner byte comparison would be a false claim, not a stronger one.
build_direct_archive() {
  set_owner_flags "$2"
  COPYFILE_DISABLE=1 LC_ALL=C "$1" --format=ustar "${owner_flags[@]}" \
    -C "$source_dir" -cf - -- "${entries[@]}" \
    | gzip -n > "$3"
}

gnu_tar=""
libarchive_tar=""
if select_family_tar gnu; then
  gnu_tar="$family_tar"
fi
if select_family_tar libarchive; then
  libarchive_tar="$family_tar"
fi

if [[ -n "$gnu_tar" && -n "$libarchive_tar" ]]; then
  build_direct_archive "$gnu_tar" gnu "$tmp_dir/direct-gnu.tar.gz"
  build_direct_archive "$libarchive_tar" libarchive "$tmp_dir/direct-libarchive.tar.gz"
  assert_identical "$tmp_dir/direct-gnu.tar.gz" "$tmp_dir/direct-libarchive.tar.gz" \
    "the $(family_label gnu) and $(family_label libarchive) families must write identical bytes on this host"
else
  if [[ -z "$gnu_tar" ]]; then
    missing_family=gnu
  else
    missing_family=libarchive
  fi
  printf 'skip: cross-family byte identity is unprovable on this host -- no available tar accepts the %s family (host tar: %s); the recorded-argv assertions above are what prove the family selection\n' \
    "$(family_label "$missing_family")" "$real_tar_version"
fi

printf 'ok: %d checks passed -- release tar creation is portable, exact, and reproducible under both GNU-like and old-libarchive-like tar (host tar: %s, stubs delegate the %s family)\n' \
  "$checks_run" "$real_tar_version" "$(family_label "$host_family")"
