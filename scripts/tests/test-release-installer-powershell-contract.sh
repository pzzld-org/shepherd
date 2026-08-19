#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

script='scripts/install-shepherd.ps1'
windows_test='scripts/tests/test-release-installer-windows.ps1'
rg -q '\[switch\]\$PrintAsset' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must declare a -PrintAsset switch (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q '\[switch\]\$PrintUrl' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must declare a -PrintUrl switch (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q "SHEPHERD_VERSION" "$script" || { rc=$?; printf 'FAIL: PowerShell installer must honour the SHEPHERD_VERSION override (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q "latest/download" "$script" || { rc=$?; printf 'FAIL: PowerShell installer must support the latest/download URL form (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q 'download/v\$version' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must support the versioned download/v$version URL form (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q "Get-FileHash.*SHA256" "$script" || { rc=$?; printf 'FAIL: PowerShell installer must verify the downloaded asset with Get-FileHash SHA256 (rg rc=%s)\n' "$rc" >&2; exit 1; }
[[ "$(rg -c 'Invoke-WebRequest .* -UseBasicParsing' "$script")" == 2 ]] || { printf 'FAIL: PowerShell installer must call Invoke-WebRequest with -UseBasicParsing exactly twice\n' >&2; exit 1; }
rg -Fq "'.shepherd.' + [guid]::NewGuid().ToString('N') + '.backup.exe'" "$script" || { rc=$?; printf 'FAIL: PowerShell installer must stage a same-directory GUID-named backup file (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq '[System.IO.File]::Replace($Ready, $Destination, $backup)' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must perform atomic replacement via [System.IO.File]::Replace (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'Restore-ReplacementFailure -Ready $Ready -Destination $Destination -Backup $backup' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must call Restore-ReplacementFailure with the ready, destination, and backup paths (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq '[System.IO.File]::Move($Backup, $Destination)' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must restore the backup via [System.IO.File]::Move on failure recovery (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq "\$readyDisposition = 'preserve'" "$script" || { rc=$?; printf 'FAIL: PowerShell installer must default the ready-file disposition to preserve (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq '$replaceFailed = $true' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must track replacement failure via $replaceFailed (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq "if (\$backupDisposition -ceq 'delete' -and -not \$replaceFailed)" "$script" || { rc=$?; printf 'FAIL: PowerShell installer must only delete the backup when replacement succeeded (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq "return 'destination-unproven'" "$script" || { rc=$?; printf 'FAIL: PowerShell installer must return destination-unproven when the destination cannot be verified (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'preserved recovery paths:' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must report preserved recovery paths on failure (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'Write-Warning "installed' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must warn on install completion with a preserved recovery artifact (rg rc=%s)\n' "$rc" >&2; exit 1; }
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
rg -Fq '[System.IO.FileAttributes]::Directory' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must detect a directory destination via FileAttributes (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq '[System.IO.FileAttributes]::ReparsePoint' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must detect a reparse-point destination via FileAttributes (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q "SHEPHERD_FORCE" "$script" || { rc=$?; printf 'FAIL: PowerShell installer must honour the SHEPHERD_FORCE override (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q 'release archive must contain shepherd.exe, LICENSE, THIRD_PARTY_NOTICES.md, and THIRD_PARTY_LICENSES only' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must enforce the exact release archive membership (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q 'Windows ARM64 release asset is not published' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must refuse Windows ARM64 until the release matrix publishes that asset (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q 'RuntimeInformation\]::OSArchitecture' "$script" || { rc=$?; printf 'FAIL: PowerShell installer must select architecture via RuntimeInformation::OSArchitecture (rg rc=%s)\n' "$rc" >&2; exit 1; }
if rg -q 'RuntimeInformation\]::ProcessArchitecture' "$script"; then
  printf 'PowerShell installer must select the OS architecture, not ProcessArchitecture\n' >&2
  exit 1
fi
if ! rg -Fq 'New-Item -ItemType SymbolicLink -Path $danglingDestination -Target $missingTarget -Force | Out-Null' "$windows_test"; then
  printf '%s: the dangling-symlink New-Item must pass -Force (PowerShell 5.1 refuses a symlink to an unresolved target)\n' "$windows_test" >&2
  exit 1
fi
printf 'ok: PowerShell installer declares versioned/latest, checksum, no-clobber, atomic recovery, and path-kind contracts\n'
