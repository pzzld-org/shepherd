#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

script='scripts/install-shepherd.ps1'
rg -q '\[switch\]\$PrintAsset' "$script"
rg -q '\[switch\]\$PrintUrl' "$script"
rg -q "SHEPHERD_VERSION" "$script"
rg -q "latest/download" "$script"
rg -q 'download/v\$version' "$script"
rg -q "Get-FileHash.*SHA256" "$script"
[[ "$(rg -c 'Invoke-WebRequest .* -UseBasicParsing' "$script")" == 2 ]]
rg -q "File\]::Replace" "$script"
rg -q "SHEPHERD_FORCE" "$script"
rg -q 'release archive must contain shepherd.exe, LICENSE, THIRD_PARTY_NOTICES.md, and THIRD_PARTY_LICENSES only' "$script"
rg -q 'Windows ARM64 release asset is not published' "$script"
rg -q 'RuntimeInformation\]::OSArchitecture' "$script"
if rg -q 'RuntimeInformation\]::ProcessArchitecture' "$script"; then
  printf 'PowerShell installer must select the OS architecture, not ProcessArchitecture\n' >&2
  exit 1
fi
printf 'ok: PowerShell installer declares versioned/latest, checksum, no-clobber, and atomic contracts\n'
