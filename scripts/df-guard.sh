#!/usr/bin/env bash
# scripts/df-guard.sh — disk-pressure precheck before any cargo invocation.
#
# WHY: #214 — "df -h pre-check (>=12Gi available) before any cargo
# invocation." A wave that fills the disk mid-build wedges cargo (lockfile
# held, target/ half-written) and freezes the whole session; recovery means
# killing it. Running this BEFORE cargo starts turns that into a fast,
# legible failure instead of a stuck session discovered ten minutes later.
#
# Usage: df-guard.sh [--min=<GiB>] [path]
#   --min=<GiB>  minimum required available GiB (default 12)
#   path         path to check (default ".")
#   -h|--help    print usage, exit 0
#
# Exit: 0 OK, 1 INSUFFICIENT, 2 df failure/unparseable.
set -euo pipefail

usage() {
  echo "Usage: df-guard.sh [--min=<GiB>] [path]"
  echo "  --min=<GiB>  minimum required available GiB (default 12)"
  echo "  path         path to check (default \".\")"
  echo "  -h|--help    print usage, exit 0"
}

min=12
path="."
for arg in "$@"; do
  case "$arg" in
    --min=*)   min="${arg#--min=}" ;;
    -h|--help) usage; exit 0 ;;
    *)         path="$arg" ;;
  esac
done

# Resolve available space PORTABLY: df -Pk gives POSIX-format 1K-block
# output with stable columns across GNU/BSD/macOS df. Take the LAST line
# (skips the header; also survives long-devname wrap on some df builds),
# field 4 = "Available" in 1K-blocks.
line="$(df -Pk "$path" 2>/dev/null | tail -n 1)" || true
availkb="$(awk '{print $4}' <<<"$line")"

if [[ -z "$availkb" || ! "$availkb" =~ ^[0-9]+$ ]]; then
  echo "df-guard: could not read df for ${path}" >&2
  exit 2
fi

avail_gib=$(( availkb / 1024 / 1024 ))

if (( avail_gib >= min )); then
  echo "df-guard: ${avail_gib}Gi available at ${path} (min ${min}Gi) — OK"
  exit 0
fi

echo "df-guard: ${avail_gib}Gi available at ${path} (min ${min}Gi) — INSUFFICIENT"
exit 1
