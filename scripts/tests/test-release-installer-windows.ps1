param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$ArchiveDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
}

function Expect-Failure([scriptblock]$Action, [string]$Message) {
    try {
        & $Action
    } catch {
        return
    }
    throw "FAIL: $Message"
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$installer = Join-Path $root 'scripts/install-shepherd.ps1'
$archiveDirectory = (Resolve-Path $ArchiveDirectory).Path
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ('shepherd-windows-installer-' + [guid]::NewGuid().ToString('N'))
$server = $null
$previous = @{
    SHEPHERD_OS = $env:SHEPHERD_OS
    SHEPHERD_ARCH = $env:SHEPHERD_ARCH
    SHEPHERD_VERSION = $env:SHEPHERD_VERSION
    SHEPHERD_RELEASE_BASE = $env:SHEPHERD_RELEASE_BASE
    SHEPHERD_INSTALL_DIR = $env:SHEPHERD_INSTALL_DIR
    SHEPHERD_FORCE = $env:SHEPHERD_FORCE
}

try {
    $asset = "shepherd-$Version-x86_64-pc-windows-msvc.zip"
    $releaseDirectory = Join-Path $temporary "releases/download/v$Version"
    [System.IO.Directory]::CreateDirectory($releaseDirectory) | Out-Null
    Copy-Item -LiteralPath (Join-Path $archiveDirectory $asset) -Destination $releaseDirectory
    Copy-Item -LiteralPath (Join-Path $archiveDirectory "$asset.sha256") -Destination $releaseDirectory

    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $listener.Stop()
    $server = Start-Process python -ArgumentList @(
        '-m', 'http.server', "$port", '--bind', '127.0.0.1', '--directory', (Join-Path $temporary 'releases')
    ) -PassThru -WindowStyle Hidden
    $base = "http://127.0.0.1:$port"
    $ready = $false
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        try {
            Invoke-WebRequest -Uri "$base/download/v$Version/$asset.sha256" -Method Head -UseBasicParsing | Out-Null
            $ready = $true
            break
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    Assert-True $ready 'local release fixture server did not start'

    $env:SHEPHERD_OS = 'Windows_NT'
    $env:SHEPHERD_ARCH = 'x86_64'
    $env:SHEPHERD_VERSION = $Version
    $env:SHEPHERD_RELEASE_BASE = $base
    $env:SHEPHERD_INSTALL_DIR = Join-Path $temporary 'install/bin'
    $env:SHEPHERD_FORCE = '0'

    Assert-True ((& $installer -PrintAsset) -eq $asset) 'PrintAsset returned the wrong Windows asset'
    Assert-True ((& $installer -PrintUrl) -eq "$base/download/v$Version/$asset") 'PrintUrl returned the wrong URL'
    $env:SHEPHERD_ARCH = 'arm64'
    Expect-Failure { & $installer -PrintAsset | Out-Null } 'Windows ARM64 was accepted without a published asset'
    $env:SHEPHERD_ARCH = 'x86_64'
    & $installer | Out-Null
    $destination = Join-Path $env:SHEPHERD_INSTALL_DIR 'shepherd.exe'
    Assert-True (Test-Path -LiteralPath $destination -PathType Leaf) 'installer did not publish shepherd.exe'
    $expectedHash = (Get-FileHash -LiteralPath (Join-Path $root 'target/release/shepherd.exe') -Algorithm SHA256).Hash
    Assert-True ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -eq $expectedHash) 'installed binary hash differs from the build'

    Expect-Failure { & $installer | Out-Null } 'existing binary was replaced without force'
    Assert-True ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -eq $expectedHash) 'no-clobber changed the installed binary'

    [System.IO.File]::WriteAllText($destination, 'replace me')
    $env:SHEPHERD_FORCE = '1'
    & $installer | Out-Null
    Assert-True ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -eq $expectedHash) 'forced replacement did not restore the release binary'

    $env:SHEPHERD_FORCE = '0'
    $env:SHEPHERD_INSTALL_DIR = Join-Path $temporary 'tampered/bin'
    [System.IO.File]::WriteAllText((Join-Path $releaseDirectory "$asset.sha256"), ('0' * 64) + "  $asset")
    Expect-Failure { & $installer | Out-Null } 'tampered checksum was accepted'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $env:SHEPHERD_INSTALL_DIR 'shepherd.exe'))) 'checksum failure published a binary'

    Write-Output 'ok: Windows installer URL, checksum, no-clobber, and force contracts'
} finally {
    if ($null -ne $server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
        $server.WaitForExit()
    }
    foreach ($name in $previous.Keys) {
        [System.Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
