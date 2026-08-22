# Install the single native Shepherd CLI from an immutable GitHub release.
# The script is intentionally self-contained so a Windows user needs neither a
# checkout nor npm. SHA-256 is checked before the archive can reach PATH.
[CmdletBinding()]
param(
    [switch]$PrintAsset,
    [switch]$PrintUrl
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$DefaultReleaseBase = 'https://github.com/pzzld-org/shepherd/releases'

function Fail([string]$Message) {
    throw "shepherd installer: $Message"
}

function Get-NormalizedOs {
    $os = if ($env:SHEPHERD_OS) { $env:SHEPHERD_OS } else { 'Windows_NT' }
    switch -Regex ($os) {
        '^(MINGW|MSYS|CYGWIN|Windows_NT)' { return 'pc-windows-msvc' }
        default { Fail "unsupported operating system '$os'" }
    }
}

function Get-NormalizedArch {
    $arch = if ($env:SHEPHERD_ARCH) {
        $env:SHEPHERD_ARCH
    } else {
        # A 32-bit or x64 PowerShell process can run under ARM64 Windows. The
        # release asset must match the operating system kernel, not that
        # emulated process.
        [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    }
    switch -Regex ($arch) {
        '^(x86_64|amd64|X64)$' { return 'x86_64' }
        '^(arm64|aarch64|Arm64)$' { Fail 'Windows ARM64 release asset is not published' }
        default { Fail "unsupported architecture '$arch'" }
    }
}

function Get-Version {
    if (-not $env:SHEPHERD_VERSION) { return $null }
    $version = $env:SHEPHERD_VERSION.TrimStart('v')
    if ($version -notmatch '^\d+\.\d+\.\d+$') {
        Fail "SHEPHERD_VERSION must be an exact semantic version, got '$version'"
    }
    return $version
}

function Get-Asset {
    $target = "$(Get-NormalizedArch)-$(Get-NormalizedOs)"
    $version = Get-Version
    if ($null -eq $version) { return "shepherd-$target.zip" }
    return "shepherd-$version-$target.zip"
}

function Get-Url {
    $base = if ($env:SHEPHERD_RELEASE_BASE) { $env:SHEPHERD_RELEASE_BASE.TrimEnd('/') } else { $DefaultReleaseBase }
    $version = Get-Version
    $asset = Get-Asset
    if ($null -eq $version) { return "$base/latest/download/$asset" }
    return "$base/download/v$version/$asset"
}

function Assert-Checksum([string]$Archive, [string]$ChecksumFile) {
    $lines = @(Get-Content -LiteralPath $ChecksumFile)
    if ($lines.Count -ne 1) { Fail 'checksum file must contain exactly one entry' }
    if ($lines[0] -notmatch '^([0-9A-Fa-f]{64})  ([^/\\]+)$') {
        Fail 'checksum file is malformed'
    }
    $declared = $Matches[1].ToLowerInvariant()
    $named = $Matches[2]
    if ($named -cne [System.IO.Path]::GetFileName($Archive)) {
        Fail 'checksum file names a different asset'
    }
    $actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $declared) { Fail 'SHA-256 checksum verification failed' }
}

function Get-PathAttributes([string]$Path) {
    try {
        return [System.IO.File]::GetAttributes($Path)
    } catch [System.IO.FileNotFoundException] {
        return $null
    } catch [System.IO.DirectoryNotFoundException] {
        return $null
    }
}

function Assert-RegularPath([string]$Path, [System.IO.FileAttributes]$Attributes) {
    if (($Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        Fail "refusing to treat reparse point '$Path' as a file"
    }
    if (($Attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
        Fail "refusing to treat directory '$Path' as a file"
    }
}

function Restore-ReplacementFailure(
    [string]$Ready,
    [string]$Destination,
    [string]$Backup,
    [string]$OldHash,
    [string]$ReadyHash,
    [scriptblock]$MoveOperation = $null
) {
    $destinationAttributes = Get-PathAttributes -Path $Destination
    $backupAttributes = Get-PathAttributes -Path $Backup

    # When both names exist, ReplaceFileW's partial result is ambiguous. Keep
    # both invocation-owned recovery files and do not infer ownership merely
    # because Destination happens to name a regular file.
    if ($null -ne $destinationAttributes -and $null -ne $backupAttributes) {
        return 'destination-and-backup-preserved'
    }

    if ($null -ne $destinationAttributes) {
        Assert-RegularPath -Path $Destination -Attributes $destinationAttributes
        $destinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        if ($destinationHash -ceq $OldHash) { return 'destination-old' }
        if ($destinationHash -ceq $ReadyHash) { return 'destination-new' }
        return 'destination-unproven'
    }

    if ($null -ne $backupAttributes) {
        Assert-RegularPath -Path $Backup -Attributes $backupAttributes
        $backupHash = (Get-FileHash -LiteralPath $Backup -Algorithm SHA256).Hash
        if ($backupHash -cne $OldHash) {
            Fail "replacement backup '$Backup' does not match the pre-replacement destination"
        }
        if ($null -eq $MoveOperation) {
            [System.IO.File]::Move($Backup, $Destination)
        } else {
            & $MoveOperation $Backup $Destination
        }
        return 'backup-restored'
    }

    $readyAttributes = Get-PathAttributes -Path $Ready
    if ($null -ne $readyAttributes) {
        Assert-RegularPath -Path $Ready -Attributes $readyAttributes
        $actualReadyHash = (Get-FileHash -LiteralPath $Ready -Algorithm SHA256).Hash
        if ($actualReadyHash -cne $ReadyHash) {
            Fail "staged recovery binary '$Ready' changed during replacement"
        }
        if ($null -eq $MoveOperation) {
            [System.IO.File]::Move($Ready, $Destination)
        } else {
            & $MoveOperation $Ready $Destination
        }
        return 'ready-restored'
    }

    Fail "atomic replacement removed '$Destination' and left no recovery file"
}

function Publish-Binary(
    [string]$Ready,
    [string]$Destination,
    [bool]$Force,
    [scriptblock]$ReplaceOperation = $null,
    [scriptblock]$MoveOperation = $null,
    [scriptblock]$DeleteOperation = $null
) {
    $readyDisposition = 'delete'
    $backupDisposition = 'preserve'
    $backup = $null
    try {
        $attributes = Get-PathAttributes -Path $Destination
        if ($null -ne $attributes) {
            Assert-RegularPath -Path $Destination -Attributes $attributes
            if (-not $Force) { Fail "refusing to replace existing '$Destination'; set SHEPHERD_FORCE=1" }
            $readyAttributes = Get-PathAttributes -Path $Ready
            if ($null -eq $readyAttributes) { Fail "staged binary disappeared before replacing '$Destination'" }
            Assert-RegularPath -Path $Ready -Attributes $readyAttributes
            $oldHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
            $readyHash = (Get-FileHash -LiteralPath $Ready -Algorithm SHA256).Hash
            $backup = Join-Path (Split-Path -Parent $Destination) ('.shepherd.' + [guid]::NewGuid().ToString('N') + '.backup.exe')
            $replaceFailed = $false
            try {
                # File.Replace atomically installs Ready while retaining the old
                # destination at a unique path on the same volume. ReplaceFileW can
                # fail after moving one of its inputs, so the catch restores a file
                # at Destination before the staged Ready file may be cleaned up.
                if ($null -eq $ReplaceOperation) {
                    [System.IO.File]::Replace($Ready, $Destination, $backup)
                } else {
                    & $ReplaceOperation $Ready $Destination $backup
                }
                $backupDisposition = 'delete'
            } catch {
                $replaceFailed = $true
                $replacementError = $_
                try {
                    $recoveryDisposition = Restore-ReplacementFailure -Ready $Ready -Destination $Destination -Backup $backup `
                        -OldHash $oldHash -ReadyHash $readyHash -MoveOperation $MoveOperation
                    switch ($recoveryDisposition) {
                        'destination-old' { }
                        'destination-new' { }
                        'backup-restored' { }
                        'ready-restored' { }
                        'destination-and-backup-preserved' { $readyDisposition = 'preserve' }
                        'destination-unproven' { $readyDisposition = 'preserve' }
                        default {
                            $readyDisposition = 'preserve'
                            $recoveryDisposition = "invalid-disposition:$recoveryDisposition"
                        }
                    }
                } catch {
                    $recoveryError = $_
                    $readyDisposition = 'preserve'
                    $recoveryDisposition = "recovery-failed:$($recoveryError.Exception.Message)"
                }

                $preservedPaths = @()
                if ($readyDisposition -ceq 'preserve' -and $null -ne (Get-PathAttributes -Path $Ready)) {
                    $preservedPaths += "'$Ready'"
                }
                if ($backupDisposition -ceq 'preserve' -and $null -ne (Get-PathAttributes -Path $backup)) {
                    $preservedPaths += "'$backup'"
                }
                $preservedDescription = if ($preservedPaths.Count -eq 0) { 'none' } else { $preservedPaths -join ', ' }
                Fail "atomic replacement failed: $($replacementError.Exception.Message); recovery disposition '$recoveryDisposition'; preserved recovery paths: $preservedDescription"
            } finally {
                if ($backupDisposition -ceq 'delete' -and -not $replaceFailed) {
                    try {
                        $backupAttributes = Get-PathAttributes -Path $backup
                        if ($null -ne $backupAttributes) {
                            Assert-RegularPath -Path $backup -Attributes $backupAttributes
                            if ($null -eq $DeleteOperation) {
                                [System.IO.File]::Delete($backup)
                            } else {
                                & $DeleteOperation $backup
                            }
                        }
                    } catch {
                        Write-Warning "installed '$Destination' but could not remove replacement backup; preserved backup at '$backup': $($_.Exception.Message)"
                    }
                }
            }
        } else {
            if ($null -eq $MoveOperation) {
                [System.IO.File]::Move($Ready, $Destination)
            } else {
                & $MoveOperation $Ready $Destination
            }
        }
    } finally {
        if ($readyDisposition -ceq 'delete' -and [System.IO.File]::Exists($Ready)) {
            $readyAttributes = Get-PathAttributes -Path $Ready
            Assert-RegularPath -Path $Ready -Attributes $readyAttributes
            [System.IO.File]::Delete($Ready)
        }
    }
}

Get-NormalizedOs | Out-Null
Get-NormalizedArch | Out-Null
$null = Get-Version
if ($PrintAsset) { Get-Asset; exit 0 }
if ($PrintUrl) { Get-Url; exit 0 }

$installDir = if ($env:SHEPHERD_INSTALL_DIR) {
    $env:SHEPHERD_INSTALL_DIR
} else {
    Join-Path $HOME '.local\bin'
}
$destination = Join-Path $installDir 'shepherd.exe'
$force = $env:SHEPHERD_FORCE -eq '1'
if ((Test-Path -LiteralPath $destination) -and -not $force) {
    Fail "refusing to replace existing '$destination'; set SHEPHERD_FORCE=1"
}

$parent = Split-Path -Parent $installDir
[System.IO.Directory]::CreateDirectory($parent) | Out-Null
$temporary = Join-Path $parent ('.shepherd-install.' + [guid]::NewGuid().ToString('N'))
$extract = Join-Path $temporary 'extract'
try {
    [System.IO.Directory]::CreateDirectory($temporary) | Out-Null
    $archive = Join-Path $temporary (Get-Asset)
    $url = Get-Url
    Invoke-WebRequest -Uri $url -OutFile $archive -MaximumRedirection 5 -UseBasicParsing
    Invoke-WebRequest -Uri "$url.sha256" -OutFile "$archive.sha256" -MaximumRedirection 5 -UseBasicParsing
    Assert-Checksum -Archive $archive -ChecksumFile "$archive.sha256"

    Expand-Archive -LiteralPath $archive -DestinationPath $extract
    $entries = @(Get-ChildItem -LiteralPath $extract -Force)
    $expectedEntries = @('LICENSE', 'shepherd.exe', 'THIRD_PARTY_LICENSES', 'THIRD_PARTY_NOTICES.md')
    $actualEntries = @($entries | ForEach-Object { $_.Name } | Sort-Object)
    if ($entries.Count -ne $expectedEntries.Count -or (Compare-Object -CaseSensitive $actualEntries $expectedEntries)) {
        Fail "release archive must contain shepherd.exe, LICENSE, THIRD_PARTY_NOTICES.md, and THIRD_PARTY_LICENSES only"
    }
    foreach ($entry in $entries) {
        if ($entry.PSIsContainer -and $entry.Name -cne 'THIRD_PARTY_LICENSES') { Fail "release archive contains a directory: '$($entry.Name)'" }
    }
    $licenseDirectory = Join-Path $extract 'THIRD_PARTY_LICENSES'
    $licenseEntries = @(Get-ChildItem -LiteralPath $licenseDirectory -Force)
    if ($licenseEntries.Count -eq 0) { Fail 'release archive has no third-party license texts' }
    foreach ($licenseEntry in $licenseEntries) {
        if ($licenseEntry.PSIsContainer -or $licenseEntry.Name -notmatch '^[0-9a-f]{64}\.txt$') {
            Fail "invalid third-party license entry '$($licenseEntry.Name)'"
        }
        $expectedHash = $licenseEntry.BaseName.ToLowerInvariant()
        $actualHash = (Get-FileHash -LiteralPath $licenseEntry.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -cne $expectedHash) { Fail "third-party license text hash mismatch '$($licenseEntry.Name)'" }
    }
    $binaryEntry = @($entries | Where-Object { $_.Name -ceq 'shepherd.exe' })
    if ($binaryEntry.Count -ne 1) { Fail "release archive does not contain 'shepherd.exe'" }
    [System.IO.Directory]::CreateDirectory($installDir) | Out-Null
    $ready = Join-Path $installDir ('.shepherd.' + [guid]::NewGuid().ToString('N') + '.ready.exe')
    [System.IO.File]::Move($binaryEntry[0].FullName, $ready)
    Publish-Binary -Ready $ready -Destination $destination -Force $force
    Write-Output "installed $(Get-Asset) to $destination"
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
