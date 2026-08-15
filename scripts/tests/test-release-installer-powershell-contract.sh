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
rg -Fq "'.shepherd.' + [guid]::NewGuid().ToString('N') + '.backup.exe'" "$script"
rg -Fq '[System.IO.File]::Replace($Ready, $Destination, $backup)' "$script"
rg -Fq 'Restore-ReplacementFailure -Ready $Ready -Destination $Destination -Backup $backup' "$script"
rg -Fq '[System.IO.File]::Move($Backup, $Destination)' "$script"
rg -Fq "\$readyDisposition = 'preserve'" "$script"
rg -Fq '$replaceFailed = $true' "$script"
rg -Fq "if (\$backupDisposition -ceq 'delete' -and -not \$replaceFailed)" "$script"
rg -Fq "return 'destination-unproven'" "$script"
rg -Fq 'preserved recovery paths:' "$script"
rg -Fq 'Write-Warning "installed' "$script"
if rg -Fq 'refusing to replace concurrently created' "$script"; then
  printf 'post-staging no-clobber races must be owned and cleaned by Publish-Binary\n' >&2
  exit 1
fi
if rg -Fq '[System.IO.File]::Replace($Ready, $Destination, $null)' "$script"; then
  printf 'forced replacement must use a recoverable same-directory backup, not raw $null\n' >&2
  exit 1
fi
if rg -Fq '[System.Management.Automation.Language.NullString]::Value' "$script"; then
  printf 'forced replacement must retain the old binary in a recovery backup\n' >&2
  exit 1
fi
rg -Fq '[System.IO.FileAttributes]::Directory' "$script"
rg -Fq '[System.IO.FileAttributes]::ReparsePoint' "$script"
rg -q "SHEPHERD_FORCE" "$script"
rg -q 'release archive must contain shepherd.exe, LICENSE, THIRD_PARTY_NOTICES.md, and THIRD_PARTY_LICENSES only' "$script"
rg -q 'Windows ARM64 release asset is not published' "$script"
rg -q 'RuntimeInformation\]::OSArchitecture' "$script"
if rg -q 'RuntimeInformation\]::ProcessArchitecture' "$script"; then
  printf 'PowerShell installer must select the OS architecture, not ProcessArchitecture\n' >&2
  exit 1
fi
printf 'ok: PowerShell installer declares versioned/latest, checksum, no-clobber, atomic recovery, and path-kind contracts\n'
