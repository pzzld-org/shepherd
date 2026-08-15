param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$ArchiveDirectory,
    [switch]$RecoveryOnly
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

function Get-FailureMessage([scriptblock]$Action, [string]$Message) {
    try {
        & $Action
    } catch {
        return $_.Exception.Message
    }
    throw "FAIL: $Message"
}

function New-ReplacementFixture([string]$Parent, [string]$Name) {
    $directory = Join-Path $Parent $Name
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    $ready = Join-Path $directory '.shepherd.ready.exe'
    $destination = Join-Path $directory 'shepherd.exe'
    [System.IO.File]::WriteAllText($ready, "new binary $Name")
    [System.IO.File]::WriteAllText($destination, "old binary $Name")
    return @{
        Directory = $directory
        Ready = $ready
        Destination = $destination
        NewContent = "new binary $Name"
        OldContent = "old binary $Name"
    }
}

function Assert-FileContent([string]$Path, [string]$Expected, [string]$Message) {
    Assert-True ([System.IO.File]::Exists($Path)) "$Message (file is missing)"
    Assert-True ([System.IO.File]::ReadAllText($Path) -ceq $Expected) $Message
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
    $tokens = $null
    $parseErrors = $null
    $installerAst = [System.Management.Automation.Language.Parser]::ParseFile(
        $installer,
        [ref]$tokens,
        [ref]$parseErrors
    )
    Assert-True ($parseErrors.Count -eq 0) 'installer has PowerShell parse errors'
    foreach ($functionName in @('Fail', 'Get-PathAttributes', 'Assert-RegularPath', 'Restore-ReplacementFailure', 'Publish-Binary')) {
        $definitions = @($installerAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -ceq $functionName
        }, $true))
        Assert-True ($definitions.Count -eq 1) "installer must define exactly one $functionName function"
        . ([scriptblock]::Create($definitions[0].Extent.Text))
    }

    $failureRoot = Join-Path $temporary 'replace-failure-recovery'
    [System.IO.Directory]::CreateDirectory($failureRoot) | Out-Null

    $noForceRace = New-ReplacementFixture -Parent $failureRoot -Name 'no-force-race'
    $script:replaceCalled = $false
    Get-FailureMessage {
        Publish-Binary -Ready $noForceRace.Ready -Destination $noForceRace.Destination -Force $false -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:replaceCalled = $true
        }
    } 'no-force publication race unexpectedly succeeded' | Out-Null
    Assert-True (-not $script:replaceCalled) 'no-force publication race reached replacement'
    Assert-FileContent $noForceRace.Destination $noForceRace.OldContent 'no-force publication race changed the destination'
    Assert-True (-not [System.IO.File]::Exists($noForceRace.Ready)) 'no-force publication race leaked the staged binary'

    $cleanupFailure = New-ReplacementFixture -Parent $failureRoot -Name 'backup-cleanup-failure'
    $script:observedBackup = $null
    $cleanupOutput = @(Publish-Binary `
        -Ready $cleanupFailure.Ready `
        -Destination $cleanupFailure.Destination `
        -Force $true `
        -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Move($destination, $backup)
            [System.IO.File]::Move($ready, $destination)
        } `
        -DeleteOperation {
            param($path)
            throw [System.IO.IOException]::new('simulated backup cleanup failure')
        } 3>&1)
    Assert-FileContent $cleanupFailure.Destination $cleanupFailure.NewContent 'backup cleanup failure rolled back the successful replacement'
    Assert-FileContent $script:observedBackup $cleanupFailure.OldContent 'backup cleanup failure lost the preserved old binary'
    Assert-True (-not [System.IO.File]::Exists($cleanupFailure.Ready)) 'successful replacement left the moved staged binary behind'
    $cleanupWarnings = @($cleanupOutput | Where-Object { $_ -is [System.Management.Automation.WarningRecord] })
    Assert-True ($cleanupWarnings.Count -eq 1) 'backup cleanup failure did not emit exactly one warning'
    Assert-True ($cleanupWarnings[0].Message.Contains($script:observedBackup)) 'backup cleanup warning omitted the exact preserved path'

    $nonRegularCleanup = New-ReplacementFixture -Parent $failureRoot -Name 'nonregular-backup-cleanup'
    $script:observedBackup = $null
    $nonRegularCleanupOutput = @(Publish-Binary `
        -Ready $nonRegularCleanup.Ready `
        -Destination $nonRegularCleanup.Destination `
        -Force $true `
        -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Move($destination, $backup)
            [System.IO.File]::Move($ready, $destination)
            [System.IO.File]::Delete($backup)
            [System.IO.Directory]::CreateDirectory($backup) | Out-Null
        } 3>&1)
    Assert-FileContent $nonRegularCleanup.Destination $nonRegularCleanup.NewContent 'non-regular backup cleanup rolled back the successful replacement'
    Assert-True ([System.IO.Directory]::Exists($script:observedBackup)) 'non-regular backup cleanup removed the preserved path'
    $nonRegularCleanupWarnings = @($nonRegularCleanupOutput | Where-Object { $_ -is [System.Management.Automation.WarningRecord] })
    Assert-True ($nonRegularCleanupWarnings.Count -eq 1) 'non-regular backup cleanup did not emit exactly one warning'
    Assert-True ($nonRegularCleanupWarnings[0].Message.Contains($script:observedBackup)) 'non-regular backup cleanup warning omitted the exact path'

    $case1175 = New-ReplacementFixture -Parent $failureRoot -Name '1175'
    $script:observedBackup = $null
    $message1175 = Get-FailureMessage {
        Publish-Binary -Ready $case1175.Ready -Destination $case1175.Destination -Force $true -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            throw [System.IO.IOException]::new('simulated ERROR_UNABLE_TO_REMOVE_REPLACED')
        }
    } 'simulated 1175 replacement unexpectedly succeeded'
    Assert-FileContent $case1175.Destination $case1175.OldContent '1175 did not retain the old destination'
    Assert-True (-not [System.IO.File]::Exists($case1175.Ready)) '1175 left a redundant staged binary after verifying the old destination'
    Assert-True (-not [System.IO.File]::Exists($script:observedBackup)) '1175 unexpectedly created a backup'
    Assert-True ($message1175 -match 'recovery disposition') '1175 error omitted its recovery disposition'

    $case1176 = New-ReplacementFixture -Parent $failureRoot -Name '1176'
    $script:observedBackup = $null
    $message1176 = Get-FailureMessage {
        Publish-Binary -Ready $case1176.Ready -Destination $case1176.Destination -Force $true -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Copy($destination, $backup)
            throw [System.IO.IOException]::new('simulated ERROR_UNABLE_TO_MOVE_REPLACEMENT')
        }
    } 'simulated 1176 replacement unexpectedly succeeded'
    Assert-FileContent $case1176.Destination $case1176.OldContent '1176 changed the destination'
    Assert-FileContent $case1176.Ready $case1176.NewContent '1176 deleted the staged recovery binary'
    Assert-FileContent $script:observedBackup $case1176.OldContent '1176 deleted the old-binary backup'
    Assert-True ($message1176.Contains($case1176.Ready) -and $message1176.Contains($script:observedBackup)) '1176 error omitted preserved recovery paths'

    $case1177 = New-ReplacementFixture -Parent $failureRoot -Name '1177'
    $script:observedBackup = $null
    Get-FailureMessage {
        Publish-Binary -Ready $case1177.Ready -Destination $case1177.Destination -Force $true -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Move($destination, $backup)
            throw [System.IO.IOException]::new('simulated ERROR_UNABLE_TO_MOVE_REPLACEMENT_2')
        }
    } 'simulated 1177 replacement unexpectedly succeeded' | Out-Null
    Assert-FileContent $case1177.Destination $case1177.OldContent '1177 did not restore the old-binary backup'
    Assert-True (-not [System.IO.File]::Exists($case1177.Ready)) '1177 left the staged binary after restoring the old binary'
    Assert-True (-not [System.IO.File]::Exists($script:observedBackup)) '1177 left a moved backup behind'

    $lastResort = New-ReplacementFixture -Parent $failureRoot -Name 'last-resort'
    $script:observedBackup = $null
    Get-FailureMessage {
        Publish-Binary -Ready $lastResort.Ready -Destination $lastResort.Destination -Force $true -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Delete($destination)
            throw [System.IO.IOException]::new('simulated failure without backup')
        }
    } 'no-backup replacement unexpectedly succeeded' | Out-Null
    Assert-FileContent $lastResort.Destination $lastResort.NewContent 'no-backup recovery did not publish the verified staged binary'
    Assert-True (-not [System.IO.File]::Exists($lastResort.Ready)) 'no-backup recovery left the moved staged binary behind'
    Assert-True (-not [System.IO.File]::Exists($script:observedBackup)) 'no-backup recovery unexpectedly created a backup'

    $backupCollision = New-ReplacementFixture -Parent $failureRoot -Name 'backup-collision'
    $script:observedBackup = $null
    $backupCollisionMessage = Get-FailureMessage {
        Publish-Binary -Ready $backupCollision.Ready -Destination $backupCollision.Destination -Force $true -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Move($destination, $backup)
            throw [System.IO.IOException]::new('simulated replacement failure before backup recovery')
        } -MoveOperation {
            param($source, $destination)
            [System.IO.File]::WriteAllText($destination, 'concurrent backup collision')
            throw [System.IO.IOException]::new('simulated backup restore collision')
        }
    } 'backup collision unexpectedly succeeded'
    Assert-FileContent $backupCollision.Destination 'concurrent backup collision' 'backup collision overwrote the concurrent destination'
    Assert-FileContent $backupCollision.Ready $backupCollision.NewContent 'backup collision deleted the staged recovery binary'
    Assert-FileContent $script:observedBackup $backupCollision.OldContent 'backup collision deleted the old-binary backup'
    Assert-True ($backupCollisionMessage.Contains($backupCollision.Ready) -and $backupCollisionMessage.Contains($script:observedBackup)) 'backup collision error omitted preserved recovery paths'

    $readyCollision = New-ReplacementFixture -Parent $failureRoot -Name 'ready-collision'
    $script:observedBackup = $null
    $readyCollisionMessage = Get-FailureMessage {
        Publish-Binary -Ready $readyCollision.Ready -Destination $readyCollision.Destination -Force $true -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Delete($destination)
            throw [System.IO.IOException]::new('simulated replacement failure before ready recovery')
        } -MoveOperation {
            param($source, $destination)
            [System.IO.File]::WriteAllText($destination, 'concurrent ready collision')
            throw [System.IO.IOException]::new('simulated ready restore collision')
        }
    } 'ready collision unexpectedly succeeded'
    Assert-FileContent $readyCollision.Destination 'concurrent ready collision' 'ready collision overwrote the concurrent destination'
    Assert-FileContent $readyCollision.Ready $readyCollision.NewContent 'ready collision deleted the staged recovery binary'
    Assert-True (-not [System.IO.File]::Exists($script:observedBackup)) 'ready collision unexpectedly created a backup'
    Assert-True ($readyCollisionMessage.Contains($readyCollision.Ready)) 'ready collision error omitted the preserved staged path'

    $nonRegularDestination = New-ReplacementFixture -Parent $failureRoot -Name 'nonregular-destination'
    $script:observedBackup = $null
    $nonRegularDestinationMessage = Get-FailureMessage {
        Publish-Binary -Ready $nonRegularDestination.Ready -Destination $nonRegularDestination.Destination -Force $true -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Move($destination, $backup)
            [System.IO.Directory]::CreateDirectory($destination) | Out-Null
            throw [System.IO.IOException]::new('simulated non-regular destination')
        }
    } 'non-regular destination unexpectedly succeeded'
    Assert-True ([System.IO.Directory]::Exists($nonRegularDestination.Destination)) 'non-regular destination was removed'
    Assert-FileContent $nonRegularDestination.Ready $nonRegularDestination.NewContent 'non-regular destination deleted the staged binary'
    Assert-FileContent $script:observedBackup $nonRegularDestination.OldContent 'non-regular destination deleted the backup'
    Assert-True ($nonRegularDestinationMessage.Contains($nonRegularDestination.Ready) -and $nonRegularDestinationMessage.Contains($script:observedBackup)) 'non-regular destination error omitted preserved recovery paths'

    $nonRegularBackup = New-ReplacementFixture -Parent $failureRoot -Name 'nonregular-backup'
    $script:observedBackup = $null
    $nonRegularBackupMessage = Get-FailureMessage {
        Publish-Binary -Ready $nonRegularBackup.Ready -Destination $nonRegularBackup.Destination -Force $true -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Delete($destination)
            [System.IO.Directory]::CreateDirectory($backup) | Out-Null
            throw [System.IO.IOException]::new('simulated non-regular backup')
        }
    } 'non-regular backup unexpectedly succeeded'
    Assert-True ([System.IO.Directory]::Exists($script:observedBackup)) 'non-regular backup was removed'
    Assert-FileContent $nonRegularBackup.Ready $nonRegularBackup.NewContent 'non-regular backup deleted the staged binary'
    Assert-True ($nonRegularBackupMessage.Contains($nonRegularBackup.Ready) -and $nonRegularBackupMessage.Contains($script:observedBackup)) 'non-regular backup error omitted preserved recovery paths'

    $nonRegularReady = New-ReplacementFixture -Parent $failureRoot -Name 'nonregular-ready'
    $script:observedBackup = $null
    $nonRegularReadyMessage = Get-FailureMessage {
        Publish-Binary -Ready $nonRegularReady.Ready -Destination $nonRegularReady.Destination -Force $true -ReplaceOperation {
            param($ready, $destination, $backup)
            $script:observedBackup = $backup
            [System.IO.File]::Delete($destination)
            [System.IO.File]::Delete($ready)
            [System.IO.Directory]::CreateDirectory($ready) | Out-Null
            throw [System.IO.IOException]::new('simulated non-regular ready path')
        }
    } 'non-regular ready path unexpectedly succeeded'
    Assert-True ([System.IO.Directory]::Exists($nonRegularReady.Ready)) 'non-regular ready path was removed'
    Assert-True (-not [System.IO.File]::Exists($script:observedBackup)) 'non-regular ready case unexpectedly created a backup'
    Assert-True ($nonRegularReadyMessage.Contains($nonRegularReady.Ready)) 'non-regular ready error omitted the preserved path'

    if ($RecoveryOnly) {
        Write-Output 'ok: Windows replacement failure and recovery state machine'
        return
    }

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

    $directoryInstall = Join-Path $temporary 'directory-destination/bin'
    $directoryDestination = Join-Path $directoryInstall 'shepherd.exe'
    [System.IO.Directory]::CreateDirectory($directoryDestination) | Out-Null
    $env:SHEPHERD_INSTALL_DIR = $directoryInstall
    Expect-Failure { & $installer | Out-Null } 'force treated a destination directory as a file'
    Assert-True (Test-Path -LiteralPath $directoryDestination -PathType Container) 'force replaced the destination directory'
    Assert-True (@(Get-ChildItem -LiteralPath $directoryInstall -Filter '.shepherd.*.ready.exe' -Force).Count -eq 0) 'directory refusal leaked a ready file'

    $linkInstall = Join-Path $temporary 'link-destination/bin'
    $linkTarget = Join-Path $temporary 'link-destination/target.exe'
    [System.IO.Directory]::CreateDirectory($linkInstall) | Out-Null
    [System.IO.File]::WriteAllText($linkTarget, 'link target')
    $linkDestination = Join-Path $linkInstall 'shepherd.exe'
    New-Item -ItemType SymbolicLink -Path $linkDestination -Target $linkTarget | Out-Null
    $env:SHEPHERD_INSTALL_DIR = $linkInstall
    Expect-Failure { & $installer | Out-Null } 'force treated a destination symbolic link as a file'
    $linkAttributes = [System.IO.File]::GetAttributes($linkDestination)
    Assert-True (($linkAttributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) 'force replaced the destination symbolic link'
    Assert-True ([System.IO.File]::ReadAllText($linkTarget) -ceq 'link target') 'force followed and replaced the symbolic-link target'
    Assert-True (@(Get-ChildItem -LiteralPath $linkInstall -Filter '.shepherd.*.ready.exe' -Force).Count -eq 0) 'symbolic-link refusal leaked a ready file'

    $danglingInstall = Join-Path $temporary 'dangling-link-destination/bin'
    [System.IO.Directory]::CreateDirectory($danglingInstall) | Out-Null
    $danglingDestination = Join-Path $danglingInstall 'shepherd.exe'
    $missingTarget = Join-Path $temporary 'dangling-link-destination/missing.exe'
    New-Item -ItemType SymbolicLink -Path $danglingDestination -Target $missingTarget | Out-Null
    $env:SHEPHERD_INSTALL_DIR = $danglingInstall
    Expect-Failure { & $installer | Out-Null } 'force treated a dangling destination symbolic link as a file'
    $danglingAttributes = [System.IO.File]::GetAttributes($danglingDestination)
    Assert-True (($danglingAttributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) 'force replaced the dangling destination symbolic link'
    Assert-True (-not [System.IO.File]::Exists($missingTarget)) 'force created the dangling symbolic-link target'
    Assert-True (@(Get-ChildItem -LiteralPath $danglingInstall -Filter '.shepherd.*.ready.exe' -Force).Count -eq 0) 'dangling-link refusal leaked a ready file'

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
